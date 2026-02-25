import logging
from pathlib import Path
from uuid import uuid4

import anyio
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import get_settings
from app.core.database import Base, engine
from app.core.logging import configure_logging, correlation_middleware
from app.core.security import enforce_global_rate_limit, require_service_auth
from app.routers import approvals, audit, cis, dashboard, governance, ingest, integrations, lifecycle, relationships
from app.schemas import HealthResponse
from app.services.sync_jobs import start_sync_worker, stop_sync_worker

configure_logging()
logger = logging.getLogger(__name__)
settings = get_settings()

app = FastAPI(
    title="Thin CMDB Core",
    version="0.1.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.middleware("http")(correlation_middleware)
PORTAL_STATIC_DIR = Path(__file__).resolve().parent / "static" / "portal"
app.mount("/portal/static", StaticFiles(directory=PORTAL_STATIC_DIR), name="portal-static")


def _error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
) -> JSONResponse:
    request_id = getattr(request.state, "correlation_id", None) or request.headers.get("x-correlation-id") or str(uuid4())
    request.state.correlation_id = request_id
    payload = {
        "detail": message,
        "error": {
            "code": code,
            "message": message,
            "request_id": request_id,
        }
    }
    response = JSONResponse(status_code=status_code, content=payload)
    response.headers["x-correlation-id"] = request_id
    return response


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    status_code = exc.status_code
    if status_code >= 500:
        if status_code == 503:
            return _error_response(
                request,
                status_code=status_code,
                code="SERVICE_UNAVAILABLE",
                message="Service unavailable",
            )
        return _error_response(
            request,
            status_code=status_code,
            code="INTERNAL_ERROR",
            message="Internal server error",
        )

    detail = exc.detail if isinstance(exc.detail, str) else "Request failed"
    return _error_response(
        request,
        status_code=status_code,
        code="REQUEST_FAILED",
        message=detail,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    logger.info("Request validation failed", extra={"errors": exc.errors()})
    return _error_response(
        request,
        status_code=422,
        code="VALIDATION_ERROR",
        message="Invalid request payload or parameters",
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled application exception")
    return _error_response(
        request,
        status_code=500,
        code="INTERNAL_ERROR",
        message="Internal server error",
    )


async def global_rate_limit_middleware(request: Request, call_next):
    path = request.url.path
    if path.startswith("/portal/static") or path == "/health":
        return await call_next(request)

    if not enforce_global_rate_limit(request):
        return _error_response(
            request,
            status_code=429,
            code="RATE_LIMITED",
            message="Request rate limit exceeded",
        )

    return await call_next(request)


app.middleware("http")(global_rate_limit_middleware)


async def request_size_middleware(request: Request, call_next):
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        content_length = request.headers.get("content-length")
        if content_length is None:
            return _error_response(
                request,
                status_code=411,
                code="LENGTH_REQUIRED",
                message="Content-Length header is required",
            )
        try:
            declared_size = int(content_length)
        except ValueError:
            return _error_response(
                request,
                status_code=400,
                code="INVALID_CONTENT_LENGTH",
                message="Invalid content-length header",
            )

        if declared_size < 0:
            return _error_response(
                request,
                status_code=400,
                code="INVALID_CONTENT_LENGTH",
                message="Invalid content-length header",
            )
        if declared_size > settings.max_request_body_bytes:
            return _error_response(
                request,
                status_code=413,
                code="PAYLOAD_TOO_LARGE",
                message="Request body exceeds allowed size",
            )

    return await call_next(request)


app.middleware("http")(request_size_middleware)


async def request_timeout_middleware(request: Request, call_next):
    timeout_seconds = max(1, settings.request_timeout_seconds)
    try:
        with anyio.fail_after(timeout_seconds):
            return await call_next(request)
    except TimeoutError:
        return _error_response(
            request,
            status_code=504,
            code="REQUEST_TIMEOUT",
            message="Request processing timed out",
        )


app.middleware("http")(request_timeout_middleware)


def _openapi_schema() -> dict:
    if app.openapi_schema:
        return app.openapi_schema
    app.openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        routes=app.routes,
    )
    return app.openapi_schema


if settings.api_docs_enabled:
    docs_dependencies = [Depends(require_service_auth)] if settings.api_docs_require_auth else []

    @app.get("/openapi.json", include_in_schema=False, dependencies=docs_dependencies)
    def openapi_json() -> dict:
        return _openapi_schema()

    @app.get("/docs", include_in_schema=False, dependencies=docs_dependencies)
    def swagger_ui():
        return get_swagger_ui_html(openapi_url="/openapi.json", title=f"{app.title} - Swagger UI")

    @app.get("/redoc", include_in_schema=False, dependencies=docs_dependencies)
    def redoc_ui():
        return get_redoc_html(openapi_url="/openapi.json", title=f"{app.title} - ReDoc")


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)
    start_sync_worker()
    logger.info("Thin CMDB Core started")


@app.on_event("shutdown")
def on_shutdown() -> None:
    stop_sync_worker()


@app.get("/health", response_model=HealthResponse, tags=["health"])
def health() -> HealthResponse:
    return HealthResponse()


app.include_router(ingest.router)
app.include_router(cis.router)
app.include_router(governance.router)
app.include_router(lifecycle.router)
app.include_router(audit.router)
app.include_router(integrations.router)
app.include_router(dashboard.router)
app.include_router(relationships.router)
app.include_router(approvals.router)
