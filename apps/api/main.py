import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.api.core.config import get_settings
from apps.api.routes.health import router as health_router
from apps.api.routes.retrieval import router as retrieval_router

settings = get_settings()

logger = structlog.get_logger(__name__)


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "Explainable News Verification API with evidence retrieval and cross-source verification."
    ),
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(
    health_router,
    prefix="/api/v1",
)


app.include_router(
    retrieval_router,
    prefix="/api/v1",
)


@app.get(
    "/",
    tags=["system"],
)
async def root() -> dict[str, str]:
    return {
        "application": settings.app_name,
        "environment": settings.app_env,
        "version": settings.app_version,
        "status": "running",
    }


@app.on_event("startup")
async def startup_event() -> None:
    logger.info(
        "application_started",
        application=settings.app_name,
        environment=settings.app_env,
        version=settings.app_version,
    )
