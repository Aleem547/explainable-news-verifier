"""Dry-run by default; execute with --execute. Delete usage older than N days.

PowerShell: uv run python scripts/usage/prune_verification_usage.py --days 90
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select

from apps.api.db.models.verification_usage import VerificationUsageEvent
from apps.api.db.session import AsyncSessionLocal


async def prune(*, days: int, execute: bool) -> None:
    cutoff = datetime.now(UTC) - timedelta(days=days)
    async with AsyncSessionLocal() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(VerificationUsageEvent)
            .where(VerificationUsageEvent.occurred_at < cutoff)
        )
        print(f"Usage events older than {days} days: {count or 0}")
        if execute:
            await session.execute(
                delete(VerificationUsageEvent).where(VerificationUsageEvent.occurred_at < cutoff)
            )
            await session.commit()
            print("Pruning completed.")
        else:
            print("Dry run only: no rows deleted. Add --execute to delete.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Prune expired usage history")
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.days <= 3650:
        parser.error("--days must be between 1 and 3650")
    asyncio.run(prune(days=args.days, execute=args.execute))


if __name__ == "__main__":
    main()
