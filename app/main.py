import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.database import Base, engine
from app.core.logging import configure_logging, correlation_middleware
from app.routers import audit, cis, governance, ingest, integrations, lifecycle
from app.schemas import HealthResponse

configure_logging()
logger = logging.getLogger(__name__)
settings = get_settings()

app = FastAPI(title="Thin CMDB Core", version="0.1.0")
app.middleware("http")(correlation_middleware)


async def request_size_middleware(request: Request, call_next):
    if request.method in {"POST", "PUT", "PATCH"}:
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > settings.max_request_body_bytes:
                    return JSONResponse(
                        status_code=413,
                        content={"detail": "Request body exceeds allowed size"},
                    )
            except ValueError:
                return JSONResponse(status_code=400, content={"detail": "Invalid content-length header"})

        body = await request.body()
        if len(body) > settings.max_request_body_bytes:
            return JSONResponse(
                status_code=413,
                content={"detail": "Request body exceeds allowed size"},
            )
        request._body = body

    return await call_next(request)


app.middleware("http")(request_size_middleware)


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)
    logger.info("Thin CMDB Core started")


@app.get("/health", response_model=HealthResponse, tags=["health"])
def health() -> HealthResponse:
    return HealthResponse()


app.include_router(ingest.router)
app.include_router(cis.router)
app.include_router(governance.router)
app.include_router(lifecycle.router)
app.include_router(audit.router)
app.include_router(integrations.router)
