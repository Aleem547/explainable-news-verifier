"""Private per-user verification usage statistics."""

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from apps.api.core.config import Settings, get_settings
from apps.api.core.service_auth import require_internal_verification
from apps.api.schemas.usage_statistics import UsageStatistics
from apps.api.services.usage_statistics import get_usage_statistics

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/account", tags=["account"])


@router.get("/usage", response_model=UsageStatistics)
async def user_usage_statistics(
    verified_user: Annotated[str, Depends(require_internal_verification)],
    settings: Annotated[Settings, Depends(get_settings)],
    response: Response,
    days: int = Query(default=30, ge=7, le=90),
) -> UsageStatistics:
    """Never accept an actor from a query/header supplied by the browser."""
    response.headers["Cache-Control"] = "no-store"
    if days not in {7, 30, 90}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="days must be 7, 30, or 90.",
            headers={"Cache-Control": "no-store"},
        )
    try:
        return await get_usage_statistics(
            verified_user=verified_user, audit_key=settings.internal_api_token, days=days
        )
    except Exception as exc:
        logger.warning("usage_statistics_unavailable", error_type=type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Usage statistics are temporarily unavailable.",
            headers={"Cache-Control": "no-store"},
        ) from exc
