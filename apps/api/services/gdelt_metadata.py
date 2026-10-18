"""Phase 13B.1: keyless GDELT DOC news-link discovery (metadata ONLY).

No networking, database writes, article fetching, or truth judgements happen
in this module. The caller must make a bounded request to the fixed GDELT API
endpoint and pass the response body to parse_article_list().

NEVER feed discovery titles/snippets into the claim-evidence NLI pipeline.
Article retrieval requires a separate approved-content policy, DNS/rebinding
and redirect-safe network client, and provenance/audit checks.
"""

from __future__ import annotations

import ipaddress
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode, urlsplit, urlunsplit

GDELT_DOC_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
MAX_RESPONSE_BYTES = 1_000_000
MAX_RESULTS = 20

# First version targets short English factual claims; no claim-level relevance
# or article availability is implied by a search-result match.
_STOPWORDS = frozenset(
    "a an and are as at be by for from has have in into is it of on or that the "
    "their there these this to was were will with about after before which who when where".split()
)
_WORD = re.compile(r"[A-Za-z0-9]+(?:['-][A-Za-z0-9]+)*")
_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


class DiscoveryFormatError(ValueError):
    """The external service produced an invalid or unusable discovery body."""


@dataclass(frozen=True, slots=True)
class ArticleCandidate:
    """An unverified link, never evidence and never an independent source."""

    url: str
    title: str
    publisher_domain: str
    seen_at: datetime | None
    language: str | None
    provider: str = "gdelt_doc"
    content_obtained: bool = False
    evidence_accepted: bool = False
    source_independence_verified: bool = False


def _query_keywords(claim: str) -> str:
    if not isinstance(claim, str) or not 3 <= len(claim.strip()) <= 300:
        raise ValueError("Claim must contain between 3 and 300 characters")
    if any(ord(char) < 32 and char not in "\t\n\r" for char in claim):
        raise ValueError("Control characters are not allowed")
    words = [word for word in _WORD.findall(claim) if word.casefold() not in _STOPWORDS]
    if not words:
        raise ValueError("Claim contains no searchable keywords")
    # A short literal keyword search, not provider-supplied advanced operators.
    # Keep the original term spelling, but deduplicate case-insensitively.
    chosen: list[str] = []
    seen: set[str] = set()
    for word in words:
        if word.casefold() not in seen:
            seen.add(word.casefold())
            chosen.append(word)
        if len(chosen) >= 7:
            break
    return " ".join(chosen)


def build_article_list_url(
    claim: str, *, limit: int = 10, timespan: str = "1week"
) -> str:
    """Construct a request to one fixed host. Does not perform HTTP I/O."""
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_RESULTS:
        raise ValueError(f"limit must be 1..{MAX_RESULTS}")
    if timespan not in {"1day", "1week", "1month"}:
        raise ValueError("Unsupported GDELT timespan")
    params = {
        "query": _query_keywords(claim),
        "mode": "artlist",
        "format": "json",
        "maxrecords": limit,
        "timespan": timespan,
        "sort": "datedesc",
    }
    return f"{GDELT_DOC_URL}?{urlencode(params)}"


def _safe_link_for_metadata(raw: object) -> tuple[str, str] | None:
    """Sanitize a link for *display/metadata*; NOT SSRF-safe for fetching.

    In particular, DNS resolution has NOT occurred. Do not use this helper
    to approve a server-side connection to any URL.
    """
    if not isinstance(raw, str) or not 1 <= len(raw) <= 4096:
        return None
    if any(ord(char) < 33 or ord(char) == 127 for char in raw):
        return None
    try:
        parts = urlsplit(raw)
        if parts.scheme.lower() != "https" or parts.username or parts.password:
            return None
        if parts.port not in (None, 443) or not parts.hostname:
            return None
        domain = parts.hostname.encode("idna").decode("ascii").lower()
        if len(domain) > 253 or domain.endswith(".") or "." not in domain:
            return None
        if any(not _LABEL.fullmatch(label) for label in domain.split(".")):
            return None
        if domain.endswith((".local", ".internal", ".localhost", ".test", ".invalid")):
            return None
        try:
            ipaddress.ip_address(domain)
            return None
        except ValueError:
            pass
        clean = urlunsplit(("https", domain, parts.path or "/", parts.query, ""))
        return clean, domain
    except (ValueError, UnicodeError):
        return None


def _parse_seen_at(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    for fmt in ("%Y%m%dT%H%M%SZ", "%Y%m%d%H%M%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def parse_article_list(body: bytes | str, *, limit: int = 10) -> list[ArticleCandidate]:
    """Parse GDELT article metadata with bounded input and no trust promotion."""
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_RESULTS:
        raise ValueError(f"limit must be 1..{MAX_RESULTS}")
    if not isinstance(body, (str, bytes)):
        raise DiscoveryFormatError("Expected JSON text or bytes")
    if len(body.encode("utf-8") if isinstance(body, str) else body) > MAX_RESPONSE_BYTES:
        raise DiscoveryFormatError("GDELT response exceeds size limit")
    try:
        payload: Any = json.loads(body)
    except (ValueError, UnicodeError) as exc:
        raise DiscoveryFormatError("Provider did not return valid JSON") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("articles"), list):
        # Do not mistake an HTTP error, HTML page or provider schema change for
        # legitimate evidence absence.
        raise DiscoveryFormatError("GDELT article list is missing or malformed")
    if len(payload["articles"]) > 500:
        raise DiscoveryFormatError("GDELT returned an unexpectedly large article list")

    result: list[ArticleCandidate] = []
    seen_urls: set[str] = set()
    for item in payload["articles"]:
        if not isinstance(item, dict):
            continue
        validated = _safe_link_for_metadata(item.get("url"))
        title = item.get("title")
        if not validated or not isinstance(title, str) or not title.strip():
            continue
        url, domain = validated
        if url in seen_urls:
            continue
        seen_urls.add(url)
        language = item.get("language")
        result.append(
            ArticleCandidate(
                url=url,
                title=title.strip()[:500],
                publisher_domain=domain,  # derive from URL, not provider's field
                seen_at=_parse_seen_at(item.get("seendate")),
                language=language.strip()[:40] if isinstance(language, str) and language.strip() else None,
            )
        )
        if len(result) >= limit:
            break
    return result
