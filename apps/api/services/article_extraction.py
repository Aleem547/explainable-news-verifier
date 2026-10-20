
"""Phase 13C.1: bounded, offline-only extraction from already-fetched HTML.

This module does not fetch URLs, store articles, index evidence, or verify claims.
Only pass HTML obtained through a separately audited and authorized fetcher.
"""

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from urllib.parse import urlsplit

from apps.api.connectors.contracts import ContentKind, ExternalDiscoveryHit
from ml.ingestion.validation import validated_discovery_identity
from ml.provenance.identity import canonical_public_url, sha256_text


class ArticleExtractionError(ValueError):
    """A short, safe extraction failure reason."""


@dataclass(frozen=True, slots=True)
class ArticleExtractionPolicy:
    max_html_bytes: int = 1_000_000
    max_text_chars: int = 500_000
    min_text_chars: int = 100

    def __post_init__(self) -> None:
        if not 1024 <= self.max_html_bytes <= 2_000_000:
            raise ValueError("Invalid HTML byte limit")

        if not 100 <= self.max_text_chars <= 2_000_000:
            raise ValueError("Invalid article text limit")

        if not 1 <= self.min_text_chars <= self.max_text_chars:
            raise ValueError("Invalid minimum article length")


@dataclass(frozen=True, slots=True)
class ExtractedArticle:
    document_url: str
    publisher_domain: str
    publisher_name: str
    text: str
    text_sha256: str
    html_sha256: str
    title: str | None
    author: str | None
    reported_publication_date: str | None
    retrieved_at: datetime
    extraction_method: str = "trafilatura_json_v1"
    content_type: str = "text/html"
    independently_verified: bool = False


ExtractionFunction = Callable[..., str | None]


def _trafilatura_extract(
    html: bytes,
    **kwargs: object,
) -> str | None:
    try:
        from trafilatura import extract
    except ImportError as exc:
        raise ArticleExtractionError(
            "trafilatura_not_installed"
        ) from exc

    return extract(html, **kwargs)


def _short_metadata(
    value: object,
    limit: int,
) -> str | None:
    if not isinstance(value, str):
        return None

    normalized = " ".join(value.split())

    return normalized[:limit] if normalized else None


def extract_discovered_article_html(
    *,
    discovery_hit: ExternalDiscoveryHit,
    fetched_url: str,
    html_body: bytes,
    retrieved_at: datetime,
    content_type: str = "text/html",
    policy: ArticleExtractionPolicy | None = None,
    extractor: ExtractionFunction | None = None,
) -> ExtractedArticle:
    """Extract unverified article content from a supplied HTML response.

    URL checks below validate document identity, not network safety.

    A separate secure fetcher must validate remote IP addresses,
    block private networks, enforce publisher restrictions,
    handle redirects safely, and bound response sizes.
    """

    settings = policy or ArticleExtractionPolicy()

    # Check the content type of the discovery result.
    if discovery_hit.kind is not ContentKind.NEWS_ARTICLE:
        raise ArticleExtractionError("not_a_news_article")

    # Validate article identity.
    try:
        discovered_url, publisher_domain = (
            validated_discovery_identity(discovery_hit)
        )

        actual_url = canonical_public_url(fetched_url)

    except (ValueError, UnicodeError) as exc:
        raise ArticleExtractionError(
            "invalid_article_identity"
        ) from exc

    # Prevent unverified URL substitutions and redirects.
    if discovered_url != actual_url:
        raise ArticleExtractionError(
            "article_url_mismatch"
        )

    parsed_url = urlsplit(actual_url)

    if parsed_url.scheme != "https" or parsed_url.port not in (
        None,
        443,
    ):
        raise ArticleExtractionError(
            "insecure_article_scheme_or_port"
        )

    # Require a timezone-aware retrieval timestamp.
    if (
        retrieved_at.tzinfo is None
        or retrieved_at.utcoffset() is None
    ):
        raise ArticleExtractionError(
            "naive_retrieval_timestamp"
        )

    # Validate the downloaded HTML.
    if not isinstance(html_body, bytes):
        raise ArticleExtractionError(
            "html_body_must_be_bytes"
        )

    if not 1 <= len(html_body) <= settings.max_html_bytes:
        raise ArticleExtractionError(
            "html_response_size_outside_limit"
        )

    # Only HTML is accepted by this extractor.
    normalized_type = (
        content_type.split(";", 1)[0]
        .strip()
        .lower()
    )

    if normalized_type != "text/html":
        raise ArticleExtractionError(
            "unsupported_content_type"
        )

    # Use Trafilatura or the injected testing extractor.
    extraction = extractor or _trafilatura_extract

    try:
        result = extraction(
            html_body,
            url=actual_url,
            output_format="json",
            with_metadata=True,
            include_comments=False,
            include_tables=False,
            include_links=False,
            include_images=False,
            favor_precision=True,
            fast=True,
        )

    except ArticleExtractionError:
        raise

    except Exception as exc:
        raise ArticleExtractionError(
            "extractor_failed"
        ) from exc

    # Validate the extraction output.
    if not isinstance(result, str) or not result:
        raise ArticleExtractionError(
            "article_text_not_found"
        )

    try:
        structured = json.loads(result)

    except (ValueError, UnicodeError) as exc:
        raise ArticleExtractionError(
            "invalid_extraction_json"
        ) from exc

    if not isinstance(structured, dict):
        raise ArticleExtractionError(
            "invalid_extraction_structure"
        )

    text = structured.get("text")

    if not isinstance(text, str):
        raise ArticleExtractionError(
            "article_text_not_found"
        )

    text = text.strip()

    # Enforce extracted article length limits.
    if not (
        settings.min_text_chars
        <= len(text)
        <= settings.max_text_chars
    ):
        raise ArticleExtractionError(
            "article_text_size_outside_limit"
        )

    # Publication dates obtained from HTML are advisory.
    date_value = structured.get("date")

    reported_date = (
        date_value
        if (
            isinstance(date_value, str)
            and re.fullmatch(
                r"\d{4}-\d{2}-\d{2}",
                date_value,
            )
        )
        else None
    )

    # Preserve validated discovery identity and fingerprints.
    # Page-provided URL and source values are not trusted.
    return ExtractedArticle(
        document_url=discovered_url,
        publisher_domain=publisher_domain,
        publisher_name=discovery_hit.publisher_name,
        text=text,
        text_sha256=sha256_text(text),
        html_sha256=sha256(html_body).hexdigest(),
        title=_short_metadata(
            structured.get("title"),
            1000,
        ),
        author=_short_metadata(
            structured.get("author"),
            500,
        ),
        reported_publication_date=reported_date,
        retrieved_at=retrieved_at,
    )
