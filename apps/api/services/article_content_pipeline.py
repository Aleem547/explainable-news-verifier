"""Phase 13C.3: permission-gated, transactional article text ingestion.

Discovery metadata is NOT evidence. Fetched text remains unverified and is
stored only after the caller attests that retaining that specific article is
permitted. These functions do not create claim verdicts or evidence rows.

The caller owns the outer database transaction and must commit or roll it back.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.connectors.contracts import ContentKind, DiscoveryResult, ExternalDiscoveryHit
from apps.api.db.models.retrieval_observation import RetrievalObservation
from apps.api.services.article_extraction import (
    ExtractedArticle,
    extract_discovered_article_html,
)
from apps.api.services.article_fetch import (
    FetchedArticleHtml,
    fetch_discovered_article_html,
)
from apps.api.services.external_ingestion import (
    ingest_discovery_result,
    ingest_supplied_content,
)
from ml.ingestion.validation import validated_discovery_identity
from ml.provenance.identity import normalize_source_domain, sha256_text


class ArticlePipelineError(ValueError):
    """Safe failure reason, never includes remote content or sensitive URLs."""


@dataclass(frozen=True, slots=True)
class StoredArticle:
    document_id: UUID
    document_version_id: UUID
    retrieval_observation_id: UUID
    passages_count: int
    queued_for_indexing: bool
    html_sha256: str
    text_sha256: str
    independently_verified: bool = False


def _single_article(result: DiscoveryResult) -> ExternalDiscoveryHit:
    if len(result.hits) != 1:
        raise ArticlePipelineError("exactly_one_discovery_hit_required")
    hit = result.hits[0]
    if hit.provider != result.provider:
        raise ArticlePipelineError("discovery_provider_mismatch")
    if hit.kind is not ContentKind.NEWS_ARTICLE:
        raise ArticlePipelineError("not_a_news_article")
    if not 1 <= len(result.query.strip()) <= 300:
        raise ArticlePipelineError("invalid_query")
    try:
        validated_discovery_identity(hit)
    except (ValueError, UnicodeError) as exc:
        raise ArticlePipelineError("invalid_discovery_identity") from exc
    return hit


def _validate_extracted(hit: ExternalDiscoveryHit, article: ExtractedArticle) -> None:
    try:
        canonical_url, domain = validated_discovery_identity(hit)
    except (ValueError, UnicodeError) as exc:
        raise ArticlePipelineError("invalid_discovery_identity") from exc
    if article.document_url != canonical_url or article.publisher_domain != domain:
        raise ArticlePipelineError("extracted_identity_mismatch")
    if article.publisher_name != hit.publisher_name:
        raise ArticlePipelineError("publisher_name_mismatch")
    if article.independently_verified:
        raise ArticlePipelineError("verified_claim_not_allowed")
    if article.retrieved_at.tzinfo is None or article.retrieved_at.utcoffset() is None:
        raise ArticlePipelineError("naive_retrieval_timestamp")
    if not article.text.strip() or len(article.text) > 2_000_000:
        raise ArticlePipelineError("invalid_article_text")
    if sha256_text(article.text) != article.text_sha256:
        raise ArticlePipelineError("text_hash_mismatch")
    if len(article.html_sha256) != 64 or any(
        c not in '0123456789abcdef' for c in article.html_sha256
    ):
        raise ArticlePipelineError("invalid_html_hash")
    if not 1 <= len(article.extraction_method) <= 100:
        raise ArticlePipelineError("invalid_extraction_method")


async def store_authorized_article(
    session: AsyncSession,
    *,
    discovery_result: DiscoveryResult,
    article: ExtractedArticle,
    storage_authorized: bool = False,
) -> StoredArticle:
    """Save one *already-extracted*, authorized article using existing models.

    Atomically registers the metadata and saves a version, passages, observation
    and outbox entry within a nested transaction. Does not call session.commit().
    Requires an explicit authorized-retention decision external to this module.
    HTML fingerprint is preserved on the retrieval observation metadata JSONB.
    """
    if storage_authorized is not True:
        raise ArticlePipelineError("storage_not_authorized")
    hit = _single_article(discovery_result)
    _validate_extracted(hit, article)

    # A savepoint avoids leaving partially registered metadata if an ingestion
    # step raises; the owner still controls the outer commit or rollback.
    async with session.begin_nested():
        await ingest_discovery_result(session, discovery_result)
        content = await ingest_supplied_content(
            session,
            url=article.document_url,
            text=article.text,
            retrieved_at=article.retrieved_at,
            content_type="text/plain",  # Trafilatura output is plain extracted text.
            extraction_method=article.extraction_method,
            provider="secure_article_fetch_v1",  # Never label the HTML fetch 'rss'.
            storage_authorized=True,
        )
        observation = await session.get(RetrievalObservation, content.retrieval_observation_id)
        if observation is None:
            raise ArticlePipelineError("missing_retrieval_observation")
        observation.metadata_json = {
            "discovery_provider": discovery_result.provider.value,
            "extraction_method": article.extraction_method,
            "html_sha256": article.html_sha256,
            "text_sha256": article.text_sha256,
            "response_content_type": article.content_type,
            "reported_publication_date": article.reported_publication_date,
            "reported_title": article.title,
            "reported_author": article.author,
            "independently_verified": False,
        }
        await session.flush()

    return StoredArticle(
        document_id=content.document_id,
        document_version_id=content.document_version_id,
        retrieval_observation_id=content.retrieval_observation_id,
        passages_count=content.passages_count,
        queued_for_indexing=content.queued_for_indexing,
        html_sha256=article.html_sha256,
        text_sha256=article.text_sha256,
    )


async def fetch_extract_store_authorized_article(
    session: AsyncSession,
    *,
    discovery_result: DiscoveryResult,
    approved_publisher_domains: frozenset[str],
    publisher_access_approved: bool = False,
    storage_authorized: bool = False,
    fetcher: Callable[..., FetchedArticleHtml] = fetch_discovered_article_html,
    extractor: Callable[..., ExtractedArticle] = extract_discovered_article_html,
) -> StoredArticle:
    """Explicitly permission-gated fetch -> extraction -> database workflow.

    The caller must decide publisher permissions/robots policy AND text-retention
    authorization out of band. This module intentionally exposes no API route.
    The domain allowlist must come from trusted server configuration, never a
    user's request. Blocking fetch/extraction run in threads, not the event loop.
    """
    if publisher_access_approved is not True:
        raise ArticlePipelineError("publisher_access_not_approved")
    if storage_authorized is not True:
        raise ArticlePipelineError("storage_not_authorized")
    hit = _single_article(discovery_result)
    _, domain = validated_discovery_identity(hit)
    try:
        vetted_domains = frozenset(normalize_source_domain(d) for d in approved_publisher_domains)
    except (ValueError, UnicodeError) as exc:
        raise ArticlePipelineError("invalid_publisher_allowlist") from exc
    if domain not in vetted_domains:
        raise ArticlePipelineError("publisher_not_approved")

    # fetcher is the Phase 13C.2 IP-pinned TLS client, no redirects permitted.
    fetched = await asyncio.to_thread(
        fetcher, discovery_hit=hit, approved_publisher_domains=vetted_domains
    )
    if fetched.independently_verified:
        raise ArticlePipelineError("verified_claim_not_allowed")
    article = await asyncio.to_thread(
        extractor,
        discovery_hit=hit,
        fetched_url=fetched.fetched_url,
        html_body=fetched.html_body,
        retrieved_at=fetched.retrieved_at,
        content_type=fetched.content_type,
    )
    # Ensure an injected extractor did not change the article identity/content.
    _validate_extracted(hit, article)
    if sha256(fetched.html_body).hexdigest() != article.html_sha256:
        raise ArticlePipelineError("html_hash_mismatch")
    if article.retrieved_at != fetched.retrieved_at:
        raise ArticlePipelineError("retrieval_timestamp_mismatch")

    return await store_authorized_article(
        session, discovery_result=discovery_result, article=article,
        storage_authorized=True,
    )
