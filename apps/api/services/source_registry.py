"""Transaction-friendly, idempotent source registration for PostgreSQL.

A registered domain identifies a publisher; it is not a reliability score.
"""

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.db.enums import SourceType
from apps.api.db.models.source import Source
from ml.provenance.identity import normalize_source_domain


async def register_source(
    session: AsyncSession,
    *,
    name: str,
    domain: str,
    source_type: SourceType = SourceType.NEWS,
) -> Source:
    """Create a source once; return an existing row without overwriting it.

    Uses the database's unique domain constraint to handle concurrent workers.
    Caller owns the transaction and must commit or roll it back.
    """
    display_name = name.strip()
    if not display_name or len(display_name) > 255:
        raise ValueError("Source name must have between 1 and 255 characters.")
    canonical_domain = normalize_source_domain(domain)

    statement = (
        insert(Source)
        .values(name=display_name, domain=canonical_domain, source_type=source_type)
        .on_conflict_do_nothing(index_elements=[Source.domain])
    )
    await session.execute(statement)
    source = await session.scalar(select(Source).where(Source.domain == canonical_domain))
    if source is None:
        raise RuntimeError("Source registration could not be read back.")
    return source
