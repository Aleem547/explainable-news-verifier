"""Fail-closed internal access for the optional Phase 9G diagnostic endpoints."""

import hmac
import os

from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader

_access_header = APIKeyHeader(name="X-Internal-Token", auto_error=False)


def require_multisource_access(token: str | None = Depends(_access_header)) -> None:
    """Never allow operator diagnostics without both opt-in and a strong secret."""
    secret = os.getenv("MULTISOURCE_INTERNAL_TOKEN", "")
    if os.getenv("ENABLE_EXPERIMENTAL_MULTISOURCE_API") != "1" or len(secret) < 32:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Multi-source API is disabled")
    if not token or not hmac.compare_digest(token, secret):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid internal credentials")
