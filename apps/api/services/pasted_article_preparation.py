"""Phase 13E.3: bounded, offline preparation of user-pasted plain-text articles.

This service NEVER fetches URLs, stores personal data, indexes evidence, or
verifies facts. Pasted material is self-attested input, NOT independent evidence.
Only an authenticated, rate-limited upper layer may decide how long to retain it.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Sequence

from ml.provenance.identity import sha256_text

POLICY_VERSION = "phase13e3-pasted-text-v1"
_HTML_TAG = re.compile(r"</?[a-z][a-z0-9-]*(?:\s[^<>]*)?/?>", re.IGNORECASE)
_INLINE_SPACE = re.compile(r"\s+", re.UNICODE)
_PARAGRAPH_BREAK = re.compile(r"\n[\t \v\f]*\n+")


class PastedArticlePreparationError(ValueError):
    """Safe reason code; caller must not include user text in public logs."""


@dataclass(frozen=True, slots=True)
class PastedArticlePolicy:
    """Hard limits for one submitted plain-text article."""

    min_text_chars: int = 100
    max_text_chars: int = 100_000
    max_input_utf8_bytes: int = 400_000
    max_paragraphs: int = 500
    max_title_chars: int = 300

    def __post_init__(self) -> None:
        numbers = (
            self.min_text_chars, self.max_text_chars, self.max_input_utf8_bytes,
            self.max_paragraphs, self.max_title_chars,
        )
        if any(type(n) is not int for n in numbers):
            raise ValueError("invalid_pasted_article_policy")
        if not 1 <= self.min_text_chars <= self.max_text_chars <= 200_000:
            raise ValueError("invalid_pasted_article_text_limit")
        if not 1024 <= self.max_input_utf8_bytes <= 800_000:
            raise ValueError("invalid_pasted_article_byte_limit")
        if not 1 <= self.max_paragraphs <= 1_000:
            raise ValueError("invalid_pasted_article_paragraph_limit")
        if not 1 <= self.max_title_chars <= 1_000:
            raise ValueError("invalid_pasted_article_title_limit")


@dataclass(frozen=True, slots=True)
class PreparedPastedArticle:
    """In-memory unverified content; MUST NOT be fed into the evidence corpus."""

    text: str
    text_sha256: str
    raw_input_sha256: str
    text_length: int
    paragraph_count: int
    user_supplied_title: str | None
    received_at: datetime
    policy_version: str = POLICY_VERSION
    content_kind: str = "USER_PASTED_PLAIN_TEXT"
    provenance_status: str = "USER_SUPPLIED_ONLY"
    claim_extraction_state: str = "READY_FOR_CLAIM_EXTRACTION"
    canonical_article_url: None = None
    publisher_domain: None = None
    independently_verified: bool = False
    eligible_as_independent_evidence: bool = False


def _reject_invisible_or_unsafe(text: str) -> None:
    for char in text:
        # Reject bidi override, zero-width/format controls, surrogate codepoints,
        # NUL, escape and other controls. Tabs and CR/LF are normalized later.
        category = unicodedata.category(char)
        if (category in {"Cf", "Cs"}
                or (category == "Cc" and char not in "\t\r\n")
                or char in "\u2028\u2029"):
            raise PastedArticlePreparationError("unsafe_pasted_text_character")


def _normalize_text(text: str, policy: PastedArticlePolicy) -> tuple[str, int]:
    if not isinstance(text, str) or not text:
        raise PastedArticlePreparationError("invalid_pasted_article_text")
    # Preflight before allocating large copies or normalizing Unicode.
    if len(text) > policy.max_input_utf8_bytes:
        raise PastedArticlePreparationError("pasted_article_too_large")
    try:
        raw_bytes = text.encode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise PastedArticlePreparationError("invalid_pasted_text_encoding") from exc
    if len(raw_bytes) > policy.max_input_utf8_bytes:
        raise PastedArticlePreparationError("pasted_article_too_large")
    _reject_invisible_or_unsafe(text)
    if _HTML_TAG.search(text):
        raise PastedArticlePreparationError("plain_text_required_not_html")
    canonical = unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))
    parts: list[str] = []
    for paragraph in _PARAGRAPH_BREAK.split(canonical):
        normalized = _INLINE_SPACE.sub(" ", paragraph).strip()
        if normalized:
            parts.append(normalized)
        if len(parts) > policy.max_paragraphs:
            raise PastedArticlePreparationError("too_many_pasted_paragraphs")
    normalized_text = "\n\n".join(parts)
    if not policy.min_text_chars <= len(normalized_text) <= policy.max_text_chars:
        raise PastedArticlePreparationError("pasted_text_size_outside_limit")
    return normalized_text, len(parts)


def _normalize_title(title: str | None, policy: PastedArticlePolicy) -> str | None:
    if title is None:
        return None
    if not isinstance(title, str) or not title or len(title) > 4 * policy.max_title_chars:
        raise PastedArticlePreparationError("invalid_user_supplied_title")
    _reject_invisible_or_unsafe(title)
    if _HTML_TAG.search(title):
        raise PastedArticlePreparationError("plain_text_title_required")
    value = _INLINE_SPACE.sub(" ", unicodedata.normalize("NFC", title)).strip()
    if not 1 <= len(value) <= policy.max_title_chars:
        raise PastedArticlePreparationError("invalid_user_supplied_title")
    return value


def prepare_pasted_article(
    *,
    pasted_text: str,
    user_supplied_title: str | None = None,
    policy: PastedArticlePolicy | None = None,
    received_at: datetime | None = None,
) -> PreparedPastedArticle:
    """Prepare plain text for future claim extraction, without side effects.

    `received_at` is supplied by trusted server code (or tests), never by an
    external API caller. Neither title nor text is publisher-verified.
    """
    settings = policy or PastedArticlePolicy()
    if not isinstance(settings, PastedArticlePolicy):
        raise PastedArticlePreparationError("invalid_pasted_article_policy")
    if not isinstance(pasted_text, str):
        raise PastedArticlePreparationError("invalid_pasted_article_text")
    clean_text, paragraphs = _normalize_text(pasted_text, settings)
    clean_title = _normalize_title(user_supplied_title, settings)
    timestamp = datetime.now(UTC) if received_at is None else received_at
    if (not isinstance(timestamp, datetime) or timestamp.tzinfo is None
            or timestamp.utcoffset() is None):
        raise PastedArticlePreparationError("naive_pasted_article_timestamp")
    if timestamp > datetime.now(UTC) + timedelta(minutes=5):
        raise PastedArticlePreparationError("future_pasted_article_timestamp")
    return PreparedPastedArticle(
        text=clean_text,
        text_sha256=sha256_text(clean_text),
        raw_input_sha256=sha256_text(pasted_text),
        text_length=len(clean_text),
        paragraph_count=paragraphs,
        user_supplied_title=clean_title,
        received_at=timestamp,
    )


def validate_prepared_pasted_article(
    prepared: PreparedPastedArticle,
    *,
    policy: PastedArticlePolicy | None = None,
) -> None:
    """Fail closed if a prepared in-memory object is modified or misattributed."""
    settings = policy or PastedArticlePolicy()
    if not isinstance(prepared, PreparedPastedArticle):
        raise PastedArticlePreparationError("invalid_pasted_article_record")
    if (prepared.policy_version != POLICY_VERSION
            or prepared.content_kind != "USER_PASTED_PLAIN_TEXT"
            or prepared.provenance_status != "USER_SUPPLIED_ONLY"
            or prepared.claim_extraction_state != "READY_FOR_CLAIM_EXTRACTION"
            or prepared.canonical_article_url is not None
            or prepared.publisher_domain is not None
            or prepared.independently_verified is not False
            or prepared.eligible_as_independent_evidence is not False):
        raise PastedArticlePreparationError("pasted_article_provenance_invalid")
    normalized, count = _normalize_text(prepared.text, settings)
    if (normalized != prepared.text or count != prepared.paragraph_count
            or len(prepared.text) != prepared.text_length
            or sha256_text(prepared.text) != prepared.text_sha256):
        raise PastedArticlePreparationError("pasted_article_content_invalid")
    if (not isinstance(prepared.raw_input_sha256, str)
            or not re.fullmatch(r"[0-9a-f]{64}", prepared.raw_input_sha256)):
        raise PastedArticlePreparationError("pasted_article_raw_fingerprint_invalid")
    if (
        prepared.user_supplied_title is not None
        and _normalize_title(prepared.user_supplied_title, settings)
        != prepared.user_supplied_title
    ):
        raise PastedArticlePreparationError("pasted_article_title_invalid")
    if (not isinstance(prepared.received_at, datetime)
            or prepared.received_at.tzinfo is None
            or prepared.received_at.utcoffset() is None
            or prepared.received_at > datetime.now(UTC) + timedelta(minutes=5)):
        raise PastedArticlePreparationError("pasted_article_timestamp_invalid")


def find_duplicate_pasted_articles(
    articles: Sequence[PreparedPastedArticle],
) -> tuple[tuple[int, ...], ...]:
    """Identify exact duplicates after text normalization, only inside this batch.

    Returns index groups of size >= 2. This does NOT compare other users,
    persist fingerprints, or assess publisher independence.
    """
    if not isinstance(articles, (list, tuple)) or len(articles) > 20:
        raise PastedArticlePreparationError("invalid_pasted_article_batch")
    groups: dict[str, list[int]] = {}
    originals: dict[str, str] = {}
    for index, article in enumerate(articles):
        validate_prepared_pasted_article(article)
        if article.text_sha256 in originals and originals[article.text_sha256] != article.text:
            raise PastedArticlePreparationError("pasted_content_fingerprint_collision")
        originals[article.text_sha256] = article.text
        groups.setdefault(article.text_sha256, []).append(index)
    return tuple(tuple(indices) for indices in groups.values() if len(indices) > 1)
