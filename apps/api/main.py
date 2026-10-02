import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse

from apps.api.core.config import get_settings
from apps.api.core.logging import configure_logging
from apps.api.routes.health import router as health_router

configure_logging()

logger = structlog.get_logger()

settings = get_settings()


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    debug=settings.debug,
    default_response_class=ORJSONResponse,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
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


@app.on_event("startup")
async def startup_event() -> None:
    logger.info(
        "application_started",
        application=settings.app_name,
        environment=settings.app_env,
        version=settings.app_version,
    )
