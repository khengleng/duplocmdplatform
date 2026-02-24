import logging

from fastapi import FastAPI

from app.core.database import Base, engine
from app.core.logging import configure_logging, correlation_middleware
from app.routers import audit, cis, governance, ingest, integrations, lifecycle
from app.schemas import HealthResponse

configure_logging()
logger = logging.getLogger(__name__)

app = FastAPI(title="Thin CMDB Core", version="0.1.0")
app.middleware("http")(correlation_middleware)


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
