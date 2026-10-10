"""Authenticate trusted internal verification requests."""

from secrets import compare_digest
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status

from apps.api.core.config import Settings, get_settings


def require_internal_verification(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    service_token: Annotated[str | None, Header(alias="X-Service-Token")] = None,
    verified_user: Annotated[str | None, Header(alias="X-Verified-User")] = None,
) -> str:
    """Require a trusted service token and authenticated user identity."""

    expected_token = settings.internal_api_token.strip()

    # Never silently disable authentication when configuration is missing.
    if len(expected_token) < 32:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Internal verification authentication is not configured.",
        )

    if not service_token or not compare_digest(
        service_token.encode("utf-8"),
        expected_token.encode("utf-8"),
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing service credentials.",
        )

    # The user identity is trusted only after service authentication succeeds.
    if (
        not verified_user
        or not verified_user.strip()
        or verified_user != verified_user.strip()
        or len(verified_user) > 256
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="A verified user identity is required.",
        )

    request.state.verified_user_id = verified_user

    return verified_user
