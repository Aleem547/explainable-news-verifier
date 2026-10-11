"""Aggregate per-user verification activity from durable PostgreSQL events.

This is best-effort product telemetry, not a billing or quota ledger. No claim
text, email address, original OAuth subject, or service token is returned.
"""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import func, select

from apps.api.db.models.verification_usage import VerificationUsageEvent
from apps.api.schemas.usage_statistics import DailyUsageStatistics, UsageStatistics


@dataclass(frozen=True)
class DailyAggregate:
    day: date
    total: int
    successful: int
    failed: int
    rate_limited: int
    latency_sum_ms: float


def verified_actor_fingerprint(subject: str, audit_key: str) -> str:
    """Same HMAC derivation as VerificationAuditMiddleware in Phase 10B3.2."""
    return hmac.new(
        audit_key.encode("utf-8"),
        subject.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:24]


def summarize_usage(rows: Sequence[DailyAggregate], *, days: int, today: date) -> UsageStatistics:
    """Return a bounded, gap-filled UTC series and overall usage totals."""
    if days not in {7, 30, 90}:
        raise ValueError("Unsupported usage window")

    earliest = today - timedelta(days=days - 1)
    indexed = {row.day: row for row in rows if earliest <= row.day <= today}
    daily: list[DailyUsageStatistics] = []
    total_requests = successes = failures = rate_limited = 0
    latency_total = 0.0

    for offset in range(days):
        day = earliest + timedelta(days=offset)
        row = indexed.get(day)
        if row is None:
            daily.append(
                DailyUsageStatistics(
                    date=day.isoformat(), total=0, successful=0, failed=0, rate_limited=0
                )
            )
            continue

        daily.append(
            DailyUsageStatistics(
                date=day.isoformat(),
                total=row.total,
                successful=row.successful,
                failed=row.failed,
                rate_limited=row.rate_limited,
            )
        )
        total_requests += row.total
        successes += row.successful
        failures += row.failed
        rate_limited += row.rate_limited
        latency_total += row.latency_sum_ms

    return UsageStatistics(
        window_days=days,
        total_requests=total_requests,
        successful_requests=successes,
        failed_requests=failures,
        rate_limited_requests=rate_limited,
        average_latency_ms=round(latency_total / total_requests, 2) if total_requests else 0.0,
        daily=daily,
    )


async def fetch_user_aggregates(
    *, actor_fingerprint: str, earliest: datetime
) -> list[DailyAggregate]:
    """One grouped SQL query, filtered by server-derived actor fingerprint."""
    # Import lazily so route-only tests do not require opening a database engine.
    from apps.api.db.session import AsyncSessionLocal

    event = VerificationUsageEvent
    utc_day = func.date(func.timezone("UTC", event.occurred_at))
    successful = event.status_code.between(200, 299)
    rate_limited = event.status_code == 429
    failed = (event.status_code >= 400) & (event.status_code != 429)

    query = (
        select(
            utc_day.label("day"),
            func.count(event.request_id),
            func.count(event.request_id).filter(successful),
            func.count(event.request_id).filter(failed),
            func.count(event.request_id).filter(rate_limited),
            func.sum(event.latency_ms),
        )
        .where(event.actor_fingerprint == actor_fingerprint, event.occurred_at >= earliest)
        .group_by(utc_day)
        .order_by(utc_day)
    )

    async with AsyncSessionLocal() as session:
        result = await session.execute(query)
        return [
            DailyAggregate(
                day=row[0],
                total=int(row[1]),
                successful=int(row[2]),
                failed=int(row[3]),
                rate_limited=int(row[4]),
                latency_sum_ms=float(row[5] or 0.0),
            )
            for row in result.all()
        ]


async def get_usage_statistics(*, verified_user: str, audit_key: str, days: int) -> UsageStatistics:
    today = datetime.now(UTC).date()
    earliest_day = today - timedelta(days=days - 1)
    earliest = datetime.combine(earliest_day, time.min, tzinfo=UTC)
    fingerprint = verified_actor_fingerprint(verified_user, audit_key)
    rows = await fetch_user_aggregates(actor_fingerprint=fingerprint, earliest=earliest)
    return summarize_usage(rows, days=days, today=today)
