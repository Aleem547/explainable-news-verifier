"""Phase 9C: transactional discovery and licensed-content ingestion.

A discovery snippet or a third-party rating is never inserted into the claim-
linked Evidence table. Publishing outbox records is not actual search indexing.
The calling worker owns the transaction; this module never commits or fetches URLs.
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.connectors.contracts import DiscoveryResult
from apps.api.db.enums import DocumentType
from apps.api.db.models.discovery_record import DiscoveryRecord
from apps.api.db.models.document import Document
from apps.api.db.models.document_passage import DocumentPassage
from apps.api.db.models.index_outbox import IndexOutbox
from apps.api.services.provenance import capture_document_version, record_retrieval_observation
from apps.api.services.source_registry import register_source
from ml.ingestion.passages import split_passages
from ml.ingestion.validation import validated_discovery_identity
from ml.provenance.identity import canonical_public_url, sha256_text


@dataclass(frozen=True, slots=True)
class DiscoveryIngestion:
    documents_seen: int
    discovery_records_seen: int


@dataclass(frozen=True, slots=True)
class ContentIngestion:
    document_id: UUID
    document_version_id: UUID
    retrieval_observation_id: UUID
    passages_count: int
    queued_for_indexing: bool


async def ingest_discovery_result(
    session: AsyncSession, result: DiscoveryResult
) -> DiscoveryIngestion:
    """Register publisher, document identity, and provider discovery provenance.

    No raw article text, document version, passages, or indexed evidence is made
    from snippets or fact-check ratings. Unique constraints make retries safe.
    """
    query = result.query.strip()
    if not 1 <= len(query) <= 300:
        raise ValueError("Discovery query must be 1 to 300 characters")
    query_hash = sha256_text(query)
    unique_documents: set[str] = set()
    for hit in result.hits:
        if hit.provider != result.provider:
            raise ValueError("Discovery hit provider does not match its result")
        url, domain = validated_discovery_identity(hit)
        unique_documents.add(url)
        # A web publisher is not assigned a credibility rating at ingestion.
        # The existing SourceType enum is left unchanged in this phase.
        source = await register_source(session, name=hit.publisher_name, domain=domain)
        await session.execute(
            insert(Document)
            .values(
                source_id=source.id,
                url=url,
                title=hit.title,
                published_at=hit.published_at,
                language=hit.language,
                document_type=DocumentType.ARTICLE,
            )
            .on_conflict_do_nothing(index_elements=[Document.url])
        )
        document = await session.scalar(select(Document).where(Document.url == url))
        if document is None:
            raise RuntimeError("Document registration could not be read back")
        if document.source_id != source.id:
            raise ValueError("Existing document points to another publisher")
        await session.execute(
            insert(DiscoveryRecord)
            .values(
                document_id=document.id,
                provider=result.provider.value,
                content_kind=hit.kind.value,
                query_text=query,
                query_sha256=query_hash,
                discovered_at=hit.discovered_at,
                snippet=hit.snippet,
                matched_claim=hit.matched_claim,
                claimant=hit.claimant,
                rating_text=hit.rating_text,
                claim_date=hit.claim_date,
            )
            .on_conflict_do_nothing(constraint="uq_discovery_doc_provider_query")
        )
    return DiscoveryIngestion(
        documents_seen=len(unique_documents), discovery_records_seen=len(result.hits)
    )


async def ingest_supplied_content(
    session: AsyncSession,
    *,
    url: str,
    text: str,
    retrieved_at: datetime,
    content_type: str = "text/plain",
    extraction_method: str = "licensed_text_import",
    provider: str = "authorized_import",
    storage_authorized: bool = False,
    max_passage_chars: int = 800,
) -> ContentIngestion:
    """Store explicitly supplied text, snapshot passages, and an index outbox entry.

    Source retrieval MUST happen through separately audited and SSRF-safe code.
    The caller must have permission to retain this particular text. No network
    request occurs here, and no claim verification result is produced.
    """
    if not storage_authorized:
        raise ValueError("Storage authorization must be explicitly affirmed")
    if retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None:
        raise ValueError("retrieved_at must be timezone-aware")
    if not text.strip() or len(text) > 2_000_000:
        raise ValueError("Supplied content must contain 1 to 2,000,000 characters")
    if not 1 <= len(provider.strip()) <= 100:
        raise ValueError("Provider name must contain 1 to 100 characters")
    if not 1 <= len(extraction_method.strip()) <= 100:
        raise ValueError("Extraction method must contain 1 to 100 characters")
    if not 1 <= len(content_type) <= 128:
        raise ValueError("Invalid content type length")

    normalized_url = canonical_public_url(url)
    document = await session.scalar(
        select(Document).where(Document.url == normalized_url).with_for_update()
    )
    if document is None:
        raise ValueError("Document must first be registered through provider discovery")

    # Exact text (including spaces) is retained to make character offsets auditable.
    snapshot = await capture_document_version(
        session,
        document_id=document.id,
        text=text,
        retrieved_at=retrieved_at,
        content_type=content_type,
    )
    existing = (
        await session.scalars(
            select(DocumentPassage)
            .where(DocumentPassage.document_version_id == snapshot.id)
            .order_by(DocumentPassage.ordinal)
        )
    ).all()
    spans = split_passages(text, max_chars=max_passage_chars)
    if existing:
        if len(existing) != len(spans) or any(
            (row.ordinal, row.start_offset, row.end_offset, row.passage_sha256)
            != (span.ordinal, span.start_offset, span.end_offset, span.sha256)
            for row, span in zip(existing, spans, strict=True)
        ):
            raise ValueError("Existing passage index disagrees with snapshot or chunk policy")
    else:
        for span in spans:
            session.add(
                DocumentPassage(
                    document_version_id=snapshot.id,
                    ordinal=span.ordinal,
                    start_offset=span.start_offset,
                    end_offset=span.end_offset,
                    text=span.text,
                    passage_sha256=span.sha256,
                )
            )
        await session.flush()

    await session.execute(
        insert(IndexOutbox)
        .values(document_version_id=snapshot.id, index_name="external_passages_v1")
        .on_conflict_do_nothing(constraint="uq_outbox_version_index")
    )
    observation = await record_retrieval_observation(
        session,
        source_id=document.source_id,
        provider=provider.strip(),
        requested_url=normalized_url,
        final_url=normalized_url,
        outcome="FETCHED",
        observed_at=retrieved_at,
        document_id=document.id,
        document_version_id=snapshot.id,
    )
    return ContentIngestion(
        document_id=document.id,
        document_version_id=snapshot.id,
        retrieval_observation_id=observation.id,
        passages_count=len(spans),
        queued_for_indexing=True,
    )
