"""Safe, conservative normalization for provider discovery metadata."""

from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from ml.provenance.identity import canonical_public_url, normalize_source_domain


def string_value(value: Any, *, limit: int = 1000) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.split()).strip()
    return text[:limit] if text else None


def timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def article_identity(value: Any) -> tuple[str, str] | None:
    """Validate discovery URL syntax only; never fetch an article in 9B."""
    if not isinstance(value, str):
        return None
    try:
        url = canonical_public_url(value)
        domain = normalize_source_domain(urlsplit(url).hostname or "")
    except (ValueError, UnicodeError):
        return None
    # Protect data integrity: discovery links must be HTTPS; never load them in 9B.
    if urlsplit(url).scheme != "https":
        return None
    return url, domain
