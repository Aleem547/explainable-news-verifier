"""Phase 13E.2: permission-gated preparation of a discovered article URL.

An exact trusted discovery hit is required; arbitrary submitted URLs are never
converted into self-attested discovery metadata. The caller must check publisher
access rules (including robots terms) and supply its own approved domain set.

This module does not expose an API, store text, extract claims or make verdicts.
The public-facing route and authorization/rate-limit controls are Phase 13E.7.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from apps.api.connectors.contracts import ContentKind, ExternalDiscoveryHit
from apps.api.services.article_extraction import (
    ArticleExtractionPolicy,
    ExtractedArticle,
    extract_discovered_article_html,
)
from apps.api.services.article_fetch import (
    ArticleFetchPolicy,
    FetchedArticleHtml,
    fetch_discovered_article_html,
)
from ml.ingestion.validation import validated_discovery_identity
from ml.provenance.identity import canonical_public_url, normalize_source_domain, sha256_text


class ArticleUrlPreparationError(ValueError):
    """Sanitized, stable refusal code; do not expose raw remote content."""


@dataclass(frozen=True, slots=True)
class PreparedArticleUrl:
    """Internal-only article preparation result, NOT a truth determination."""

    canonical_url: str
    publisher_domain: str
    publisher_name: str
    article: ExtractedArticle
    state: str = "READY_FOR_CLAIM_EXTRACTION"
    independently_verified: bool = False


def _canonical_input(value: str) -> str:
    if not isinstance(value, str) or not (1 <= len(value) <= 2048):
        raise ArticleUrlPreparationError("invalid_submitted_url")
    # Reject leading/trailing whitespace and controls rather than silently
    # rewriting hostile/unintended input before the security boundary.
    if value != value.strip() or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ArticleUrlPreparationError("invalid_submitted_url")
    try:
        canonical = canonical_public_url(value)
        parsed = urlsplit(canonical)
        if parsed.scheme != "https" or parsed.port not in (None, 443):
            raise ValueError("insecure URL")
    except (ValueError, UnicodeError) as exc:
        raise ArticleUrlPreparationError("invalid_submitted_url") from exc
    return canonical


def _validate_permission_context(
    *,
    submitted_url: str,
    approved_discovery_hit: ExternalDiscoveryHit,
    publisher_access_approved: bool,
    approved_publisher_domains: frozenset[str],
) -> tuple[str, str]:
    canonical = _canonical_input(submitted_url)
    if publisher_access_approved is not True:
        raise ArticleUrlPreparationError("publisher_access_not_approved")
    if not isinstance(approved_discovery_hit, ExternalDiscoveryHit):
        raise ArticleUrlPreparationError("trusted_discovery_hit_required")
    if approved_discovery_hit.kind is not ContentKind.NEWS_ARTICLE:
        raise ArticleUrlPreparationError("not_a_news_article")
    try:
        discovered_url, domain = validated_discovery_identity(approved_discovery_hit)
    except (ValueError, UnicodeError) as exc:
        raise ArticleUrlPreparationError("invalid_discovery_identity") from exc
    if discovered_url != canonical:
        raise ArticleUrlPreparationError("url_not_equal_to_trusted_discovery")
    try:
        approved = frozenset(normalize_source_domain(d) for d in approved_publisher_domains)
    except (ValueError, UnicodeError, TypeError) as exc:
        raise ArticleUrlPreparationError("invalid_publisher_allowlist") from exc
    if domain not in approved:
        raise ArticleUrlPreparationError("publisher_not_approved")
    return canonical, domain


def _validate_fetch(
    fetched: FetchedArticleHtml,
    *,
    expected_url: str,
    fetch_policy: ArticleFetchPolicy,
) -> None:
    if not isinstance(fetched, FetchedArticleHtml):
        raise ArticleUrlPreparationError("invalid_fetch_result")
    if fetched.independently_verified is not False:
        raise ArticleUrlPreparationError("unexpected_verified_content")
    if not isinstance(fetched.fetched_url, str) or fetched.fetched_url != expected_url:
        raise ArticleUrlPreparationError("fetched_url_mismatch")
    if not isinstance(fetched.content_type, str) or fetched.content_type.split(";", 1)[0].strip().lower() != "text/html":
        raise ArticleUrlPreparationError("unexpected_content_type")
    if not isinstance(fetched.html_body, bytes) or not (1 <= len(fetched.html_body) <= fetch_policy.max_html_bytes):
        raise ArticleUrlPreparationError("invalid_html_body")
    if not isinstance(fetched.retrieved_at, datetime) or fetched.retrieved_at.tzinfo is None or fetched.retrieved_at.utcoffset() is None:
        raise ArticleUrlPreparationError("invalid_fetch_timestamp")
    if fetched.retrieved_at > datetime.now(timezone.utc) + timedelta(minutes=5):
        raise ArticleUrlPreparationError("future_fetch_timestamp")


def _validate_extracted(
    extracted: ExtractedArticle,
    *,
    hit: ExternalDiscoveryHit,
    expected_url: str,
    expected_domain: str,
    fetched: FetchedArticleHtml,
    extraction_policy: ArticleExtractionPolicy,
) -> None:
    if not isinstance(extracted, ExtractedArticle):
        raise ArticleUrlPreparationError("invalid_extraction_result")
    if extracted.independently_verified is not False:
        raise ArticleUrlPreparationError("unexpected_verified_content")
    if (extracted.document_url != expected_url or extracted.publisher_domain != expected_domain
            or extracted.publisher_name != hit.publisher_name):
        raise ArticleUrlPreparationError("extraction_identity_mismatch")
    if extracted.retrieved_at != fetched.retrieved_at:
        raise ArticleUrlPreparationError("extraction_timestamp_mismatch")
    if not isinstance(extracted.text, str) or not (
        extraction_policy.min_text_chars <= len(extracted.text) <= extraction_policy.max_text_chars
    ) or extracted.text != extracted.text.strip():
        raise ArticleUrlPreparationError("extracted_text_invalid")
    if not isinstance(extracted.text_sha256, str) or extracted.text_sha256 != sha256_text(extracted.text):
        raise ArticleUrlPreparationError("extracted_text_hash_mismatch")
    if not isinstance(extracted.html_sha256, str) or extracted.html_sha256 != hashlib.sha256(fetched.html_body).hexdigest():
        raise ArticleUrlPreparationError("extracted_html_hash_mismatch")
    if extracted.content_type != "text/html":
        raise ArticleUrlPreparationError("invalid_extraction_content_type")


async def prepare_discovered_article_url(
    *,
    submitted_url: str,
    approved_discovery_hit: ExternalDiscoveryHit,
    approved_publisher_domains: frozenset[str],
    publisher_access_approved: bool = False,
    fetch_policy: ArticleFetchPolicy | None = None,
    extraction_policy: ArticleExtractionPolicy | None = None,
    fetcher: Callable[..., FetchedArticleHtml] = fetch_discovered_article_html,
    extractor: Callable[..., ExtractedArticle] = extract_discovered_article_html,
) -> PreparedArticleUrl:
    """Prepare one URL only after trusted discovery and access approval.

    Caller-supplied injection hooks are for tests ONLY. Never expose `fetcher`,
    `extractor`, `approved_discovery_hit`, `approved_publisher_domains` or
    `publisher_access_approved` as user-controlled API fields.

    Blocking I/O/extraction use worker threads. A cancelled async request may
    not cancel an already-running thread; upper-layer controls must enforce
    concurrent-worker budgets and user quotas before enabling a public route.
    """
    canonical, domain = _validate_permission_context(
        submitted_url=submitted_url,
        approved_discovery_hit=approved_discovery_hit,
        publisher_access_approved=publisher_access_approved,
        approved_publisher_domains=approved_publisher_domains,
    )
    fetch_settings = fetch_policy or ArticleFetchPolicy()
    extract_settings = extraction_policy or ArticleExtractionPolicy()
    if extract_settings.max_html_bytes < fetch_settings.max_html_bytes:
        # Prevent retrieving content the extractor was not configured to accept.
        raise ArticleUrlPreparationError("incompatible_html_size_limits")

    try:
        fetched = await asyncio.to_thread(
            fetcher,
            discovery_hit=approved_discovery_hit,
            approved_publisher_domains=frozenset({domain}),
            policy=fetch_settings,
        )
    except Exception as exc:
        raise ArticleUrlPreparationError("approved_article_fetch_failed") from exc
    _validate_fetch(fetched, expected_url=canonical, fetch_policy=fetch_settings)
    try:
        article = await asyncio.to_thread(
            extractor,
            discovery_hit=approved_discovery_hit,
            fetched_url=fetched.fetched_url,
            html_body=fetched.html_body,
            retrieved_at=fetched.retrieved_at,
            content_type=fetched.content_type,
            policy=extract_settings,
        )
    except Exception as exc:
        raise ArticleUrlPreparationError("article_extraction_failed") from exc
    _validate_extracted(
        article, hit=approved_discovery_hit, expected_url=canonical,
        expected_domain=domain, fetched=fetched, extraction_policy=extract_settings,
    )
    return PreparedArticleUrl(
        canonical_url=canonical,
        publisher_domain=domain,
        publisher_name=approved_discovery_hit.publisher_name,
        article=article,
    )
