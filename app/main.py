import logging
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import get_settings
from app.core.database import Base, engine
from app.core.logging import configure_logging, correlation_middleware
from app.core.security import require_service_auth
from app.routers import audit, cis, dashboard, governance, ingest, integrations, lifecycle, relationships
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


async def request_size_middleware(request: Request, call_next):
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        content_length = request.headers.get("content-length")
        if content_length is None:
            return JSONResponse(status_code=411, content={"detail": "Content-Length header is required"})
        try:
            declared_size = int(content_length)
        except ValueError:
            return JSONResponse(status_code=400, content={"detail": "Invalid content-length header"})

        if declared_size < 0:
            return JSONResponse(status_code=400, content={"detail": "Invalid content-length header"})
        if declared_size > settings.max_request_body_bytes:
            return JSONResponse(
                status_code=413,
                content={"detail": "Request body exceeds allowed size"},
            )

    return await call_next(request)


app.middleware("http")(request_size_middleware)


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
