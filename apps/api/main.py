import structlog
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.api.core.config import get_settings
from apps.api.routes.classification import router as classification_router
from apps.api.routes.health import router as health_router
from apps.api.routes.multisource import router as multisource_router
from apps.api.routes.retrieval import router as retrieval_router
from apps.api.routes.verification import router as verification_router
from apps.api.security.body_limit import InferenceBodyLimitMiddleware
from apps.api.security.inference import require_inference_access

settings = get_settings()
logger = structlog.get_logger(__name__)

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "Explainable News Verification API "
        "with claim classification, evidence retrieval and cross-source verification."
    ),
    # Do not publish an API schema on the production ingress by default.
    docs_url=None if settings.app_env.casefold() == "production" else "/docs",
    redoc_url=None if settings.app_env.casefold() == "production" else "/redoc",
    openapi_url=None if settings.app_env.casefold() == "production" else "/openapi.json",
)

app.add_middleware(
    InferenceBodyLimitMiddleware,
    max_bytes=settings.inference_max_body_bytes,
)

# Browser traffic uses the Next.js same-origin API proxy. CORS is only needed
# for local development; production does not need browser access to FastAPI.
if settings.app_env.casefold() == "development":
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

app.include_router(health_router, prefix="/api/v1")

# Apply the service gate to every expensive route, not only /verify.
# Multi-source routes retain their separate, existing operator authorization.
secured = [Depends(require_inference_access)]
app.include_router(retrieval_router, prefix="/api/v1", dependencies=secured)
app.include_router(classification_router, prefix="/api/v1", dependencies=secured)
app.include_router(verification_router, prefix="/api/v1", dependencies=secured)
app.include_router(multisource_router, prefix="/api/v1", dependencies=secured)


@app.get("/", tags=["system"])
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
