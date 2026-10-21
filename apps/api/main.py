"""FastAPI application and lifecycle management."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool

from apps.api.core.config import get_settings
from apps.api.routes.classification import router as classification_router
from apps.api.routes.health import router as health_router
from apps.api.routes.multisource import router as multisource_router
from apps.api.routes.retrieval import router as retrieval_router
from apps.api.routes.usage_statistics import router as usage_statistics_router
from apps.api.routes.verification import router as verification_router
from apps.api.routes.article_verification import router as article_verification_router
from apps.api.security.body_limit import InferenceBodyLimitMiddleware
from apps.api.security.inference import require_inference_access
from apps.api.security.user_quota import require_verified_user_access
from apps.api.security.verification_audit import VerificationAuditMiddleware
from apps.api.services.verification import (
    shutdown_verification_queue,
    start_verification_queue,
    wait_for_verification_idle,
)

settings = get_settings()
logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Open local queue on startup; close and drain at lifespan shutdown.

    ASGI servers normally call lifespan shutdown AFTER handling active connections.
    Docker's stop_grace_period is therefore also needed to allow requests to finish.
    """
    start_verification_queue()
    logger.info(
        "application_started",
        application=settings.app_name,
        environment=settings.app_env,
        version=settings.app_version,
    )
    try:
        yield
    finally:
        shutdown_verification_queue()
        drained = await run_in_threadpool(wait_for_verification_idle, 5.0)
        logger.info("application_stopped", inference_drained=drained)


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "Explainable News Verification API "
        "with claim classification, evidence retrieval and cross-source verification."
    ),
    docs_url=None if settings.app_env.casefold() == "production" else "/docs",
    redoc_url=None if settings.app_env.casefold() == "production" else "/redoc",
    openapi_url=None if settings.app_env.casefold() == "production" else "/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(
    InferenceBodyLimitMiddleware,
    max_bytes=settings.inference_max_body_bytes,
)

if settings.app_env.casefold() == "development":
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

# Keep the audit middleware outermost so errors are recorded without request bodies.
app.add_middleware(
    VerificationAuditMiddleware, audit_key=settings.internal_api_token, persist_usage=True
)

app.include_router(health_router, prefix="/api/v1")
app.include_router(usage_statistics_router, prefix="/api/v1")

secured = [Depends(require_inference_access)]
app.include_router(retrieval_router, prefix="/api/v1", dependencies=secured)
app.include_router(classification_router, prefix="/api/v1", dependencies=secured)
app.include_router(
    verification_router,
    prefix="/api/v1",
    dependencies=[*secured, Depends(require_verified_user_access)],
)
app.include_router(multisource_router, prefix="/api/v1", dependencies=secured)

# Phase 13E.7: feature gated inside the handler as well as the web proxy.
# The same service and per-user quota checks apply as /api/v1/verify.
app.include_router(
    article_verification_router, prefix="/api/v1",
    dependencies=[*secured, Depends(require_verified_user_access)],
)


@app.get("/", tags=["system"])
async def root() -> dict[str, str]:
    return {
        "application": settings.app_name,
        "environment": settings.app_env,
        "version": settings.app_version,
        "status": "running",
    }
