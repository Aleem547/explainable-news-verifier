"""Optional transaction-rollback smoke test against local Phase 9C PostgreSQL.

Uses synthetic .invalid URLs, never calls external services, never commits.
Run only after applying the Phase 9C migration to the development database.
"""

import asyncio
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from apps.api.connectors.contracts import (
    ContentKind,
    DiscoveryResult,
    ExternalDiscoveryHit,
    Provider,
)
from apps.api.core.config import get_settings
from apps.api.services.external_ingestion import ingest_discovery_result, ingest_supplied_content


async def run() -> None:
    engine = create_async_engine(get_settings().database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            try:
                now = datetime.now(UTC)
                url = "https://phase9c-fixture.invalid/dry-run"
                example = ExternalDiscoveryHit(
                    provider=Provider.NEWSAPI,
                    kind=ContentKind.NEWS_ARTICLE,
                    url=url,
                    publisher_domain="phase9c-fixture.invalid",
                    publisher_name="Synthetic Phase 9C Fixture",
                    title="Synthetic database smoke test",
                    snippet="Not evidence. Offline test metadata only.",
                    discovered_at=now,
                    published_at=now,
                )
                result = DiscoveryResult(
                    provider=Provider.NEWSAPI, query="phase9c synthetic test", hits=(example,)
                )
                registered = await ingest_discovery_result(session, result)
                captured = await ingest_supplied_content(
                    session,
                    url=url,
                    text="This is synthetic text, not a real published article. " * 30,
                    retrieved_at=now,
                    storage_authorized=True,
                    provider="synthetic_fixture",
                    extraction_method="synthetic_fixture",
                )
                await session.flush()
                print("Phase 9C database transaction smoke test passed")
                print(f"Documents seen: {registered.documents_seen}")
                print(f"Passages prepared: {captured.passages_count}")
            finally:
                await session.rollback()
                print("Test transaction rolled back; no fixture content was saved")
    finally:
        await engine.dispose()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
