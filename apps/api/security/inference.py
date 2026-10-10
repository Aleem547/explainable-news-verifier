"""Fail-closed service authentication and Redis-backed inference quota.

A shared service credential authenticates trusted server-to-server callers, not
individual end users. User sessions and per-user quotas belong to Phase 10B.2.
"""

from __future__ import annotations

import hashlib
import hmac

from fastapi import HTTPException, Request, Response, status

from apps.api.core.config import get_settings
from apps.api.dependencies import get_redis_client

# INCR + EXPIRE are performed atomically; quotas are shared across API workers.
_RATE_LIMIT_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
  redis.call('EXPIRE', KEYS[1], tonumber(ARGV[1]))
end
return {count, redis.call('TTL', KEYS[1])}
"""


async def require_inference_access(request: Request, response: Response) -> None:
    """Require a private service credential and enforce the shared quota in production.

    This is intentionally not an end-user authentication system. Public access
    remains disabled at the Next.js proxy until Phase 10B.2 is complete.
    """
    settings = get_settings()
    if settings.app_env.casefold() in {"development", "test"}:
        return

    secret = settings.internal_api_token
    if len(secret) < 32:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Inference access is not configured.",
        )

    supplied = request.headers.get("x-service-token", "")
    if not hmac.compare_digest(supplied, secret):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Service authentication required.",
            headers={"WWW-Authenticate": 'Bearer realm="internal-api"'},
        )

    # One global quota for the trusted service identity. This limits total
    # inference cost but does not provide per-user fairness.
    service_id = hashlib.sha256(secret.encode("utf-8")).hexdigest()[:24]
    key = f"inference:quota:v1:{service_id}"
    try:
        client = get_redis_client()
        try:
            raw: object = await client.eval(
                _RATE_LIMIT_SCRIPT,
                1,
                key,
                60,
            )
        finally:
            await client.aclose()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Inference rate limiter is unavailable.",
        ) from exc

    if not isinstance(raw, (list, tuple)) or len(raw) != 2:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Inference rate limiter returned an invalid response.",
        )

    try:
        count = int(raw[0])
        ttl = int(raw[1])
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Inference rate limiter returned an invalid response.",
        ) from exc

    if count < 1 or ttl < 0:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Inference rate limiter returned an invalid response.",
        )

    limit = settings.inference_requests_per_minute
    if count > limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Inference request quota exceeded. Try again shortly.",
            headers={"Retry-After": str(max(1, ttl)), "Cache-Control": "no-store"},
        )

    response.headers["X-RateLimit-Limit"] = str(limit)
    response.headers["X-RateLimit-Remaining"] = str(max(0, limit - count))
    response.headers["Cache-Control"] = "no-store"
