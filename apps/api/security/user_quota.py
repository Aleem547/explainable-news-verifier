"""Verified end-user quota for the private inference API.

This dependency must be used *after* require_inference_access on the same
route. The x-verified-user assertion is trusted only from authenticated
Next.js server-side transport, never directly from the browser.
"""

from __future__ import annotations

import hashlib
import re

from fastapi import HTTPException, Request, Response, status

from apps.api.core.config import get_settings
from apps.api.dependencies import get_redis_client

# Prevent unbounded identity input or newline/header ambiguity. This is an
# internal assertion populated with an OAuth provider's stable subject ID.
_SUBJECT = re.compile(r"\A[a-z][a-z0-9_-]{0,24}:[A-Za-z0-9_-]{1,128}\Z")

# Redis command and TTL are atomic across multiple FastAPI workers.
_QUOTA_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
  redis.call('EXPIRE', KEYS[1], tonumber(ARGV[1]))
end
return {count, redis.call('TTL', KEYS[1])}
"""


async def require_verified_user_access(request: Request, response: Response) -> None:
    """Enforce a second (per-user) limit on POST /api/v1/verify.

    Development bypass preserves existing local workflows. In staging and
    production the server-to-server credential dependency runs separately.
    """
    settings = get_settings()
    if settings.app_env.casefold() in {"development", "test"}:
        return

    subject = request.headers.get("x-verified-user", "")
    if not _SUBJECT.fullmatch(subject):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated user context is required.",
            headers={"Cache-Control": "no-store"},
        )

    # Never put email addresses, profile names or provider identifiers in Redis keys.
    opaque_id = hashlib.sha256(subject.encode("utf-8")).hexdigest()
    key = f"inference:user:v1:{opaque_id}"
    try:
        client = get_redis_client()
        try:
            result: object = await client.eval(_QUOTA_SCRIPT, 1, key, 60)
        finally:
            await client.aclose()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Per-user rate limiter is unavailable.",
        ) from exc

    if not isinstance(result, (list, tuple)) or len(result) != 2:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Per-user rate limiter returned an invalid response.",
        )
    try:
        count, ttl = int(result[0]), int(result[1])
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Per-user rate limiter returned an invalid response.",
        ) from exc

    if count < 1 or ttl < 0:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Per-user rate limiter returned an invalid response.",
        )

    limit = settings.inference_user_requests_per_minute
    if count > limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Your verification quota has been reached. Try again shortly.",
            headers={"Retry-After": str(max(ttl, 1)), "Cache-Control": "no-store"},
        )

    # Distinguish these from the service-wide X-RateLimit-* response headers.
    response.headers["X-User-RateLimit-Limit"] = str(limit)
    response.headers["X-User-RateLimit-Remaining"] = str(max(limit - count, 0))
    response.headers["Cache-Control"] = "no-store"
