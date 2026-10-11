"""Privacy-conscious request audit for the verification API.

Records outcomes and a random request ID without recording claims, user IDs,
OAuth tokens, service credentials, or request bodies. Logs are not durable
usage accounting: configure secure log retention separately in production.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from typing import Any

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = structlog.get_logger(__name__)


def _outcome(status_code: int) -> str:
    if status_code == 401:
        return "unauthorized"
    if status_code == 403:
        return "forbidden"
    if status_code == 422:
        return "invalid_request"
    if status_code == 429:
        return "rate_limited"
    if status_code == 503:
        return "unavailable"
    if status_code >= 500:
        return "server_error"
    if status_code >= 400:
        return "client_error"
    if status_code >= 300:
        return "redirect"
    return "success"


class VerificationAuditMiddleware:
    """Audit POST /api/v1/verify, including failures raised by dependencies.

    The actor fingerprint is generated only when the authentication dependency
    has populated request.state.verified_user_id. A caller-supplied identity
    header alone cannot become an audit actor.
    """

    def __init__(self, app: ASGIApp, *, audit_key: str, persist_usage: bool = False) -> None:
        self.app = app
        self.audit_key = audit_key.encode("utf-8")
        self.persist_usage = persist_usage

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope.get("method") != "POST"
            or scope.get("path") != "/api/v1/verify"
        ):
            await self.app(scope, receive, send)
            return

        request_id = secrets.token_hex(12)
        started_at = time.perf_counter()
        status_code = 500

        async def send_audited(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                # Never trust or duplicate identifiers / cache directives
                # supplied by another response layer.
                headers = [
                    (name, value)
                    for name, value in message.get("headers", [])
                    if name.lower() not in {b"x-request-id", b"cache-control"}
                ]
                headers.append((b"x-request-id", request_id.encode("ascii")))
                headers.append((b"cache-control", b"no-store"))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_audited)
        finally:
            state: Any = scope.get("state") or {}
            verified_user: object = state.get("verified_user_id")
            actor_fingerprint: str | None = None
            if isinstance(verified_user, str) and verified_user and self.audit_key:
                actor_fingerprint = hmac.new(
                    self.audit_key,
                    verified_user.encode("utf-8"),
                    hashlib.sha256,
                ).hexdigest()[:24]

            elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
            outcome = _outcome(status_code)

            logger.info(
                "verification_request_audit",
                request_id=request_id,
                method="POST",
                route="/api/v1/verify",
                status_code=status_code,
                outcome=outcome,
                actor_fingerprint=actor_fingerprint,
                elapsed_ms=elapsed_ms,
            )

            # Only server-authenticated requests have an actor fingerprint.
            # DB persistence is opt-in so isolated middleware tests work unchanged.
            if self.persist_usage and actor_fingerprint is not None:
                try:
                    from apps.api.services.verification_usage import persist_usage_event

                    await persist_usage_event(
                        request_id=request_id,
                        actor_fingerprint=actor_fingerprint,
                        status_code=status_code,
                        outcome=outcome,
                        latency_ms=elapsed_ms,
                    )
                except Exception as exc:
                    # Usage history is not a quota/billing ledger. Never change an
                    # already-computed response because telemetry is unavailable.
                    logger.warning(
                        "verification_usage_persist_failed",
                        request_id=request_id,
                        error_type=type(exc).__name__,
                    )
