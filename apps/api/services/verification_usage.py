"""Write pseudonymous, authenticated verification usage events to PostgreSQL.

Best-effort product analytics only. Redis enforces quotas. This history does not
provide exactly-once billing or guaranteed accounting under process crashes.
"""

from __future__ import annotations

from apps.api.db.models.verification_usage import VerificationUsageEvent


async def persist_usage_event(
    *,
    request_id: str,
    actor_fingerprint: str,
    status_code: int,
    outcome: str,
    latency_ms: float,
) -> None:
    # Import lazily: isolated API/middleware tests must not create DB engines.
    from apps.api.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        session.add(
            VerificationUsageEvent(
                request_id=request_id,
                actor_fingerprint=actor_fingerprint,
                status_code=status_code,
                outcome=outcome,
                latency_ms=max(0.0, latency_ms),
            )
        )
        await session.commit()
