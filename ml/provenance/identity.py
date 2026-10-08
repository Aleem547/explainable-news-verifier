"""Conservative publisher identity and document snapshot helpers.

These functions never fetch URLs or claim that two hosts are independent sources.
DNS resolution and redirect/SSRF protections belong to network connector code.
"""

import hashlib
import ipaddress
import re
from urllib.parse import urlsplit, urlunsplit

_DOMAIN_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def normalize_source_domain(value: str) -> str:
    """Normalize one public DNS hostname, without collapsing publisher aliases.

    Do not pass an arbitrary URL here; use canonical_public_url for article URLs.
    A valid hostname is not a guarantee that a remote server is safe to contact.
    """
    name = value.strip().rstrip(".").lower()
    if not name or any(char in name for char in "/:@?#\\ "):
        raise ValueError("Expected a hostname without scheme, path, or credentials.")
    try:
        name = name.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ValueError("Invalid internationalized hostname.") from exc
    if len(name) > 253 or name == "localhost" or "." not in name:
        raise ValueError("Expected a public-style DNS hostname.")
    if any(not _DOMAIN_LABEL.fullmatch(label) for label in name.split(".")):
        raise ValueError("Invalid hostname label.")
    try:
        ipaddress.ip_address(name)
    except ValueError:
        return name
    raise ValueError("IP literals are not publisher domains.")


def canonical_public_url(value: str) -> str:
    """Normalize only identity-safe URL components, preserving path and query.

    This is NOT SSRF protection. Network connectors must additionally verify DNS,
    resolved IP ranges, and each redirect before making outbound requests.
    """
    try:
        parsed = urlsplit(value.strip())
        if parsed.scheme.lower() not in {"http", "https"}:
            raise ValueError("Only HTTP(S) URLs are supported.")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("URLs containing credentials are not allowed.")
        if not parsed.hostname:
            raise ValueError("Missing hostname.")
        host = normalize_source_domain(parsed.hostname)
        port = parsed.port
    except (ValueError, UnicodeError) as exc:
        raise ValueError(f"Invalid public article URL: {exc}") from exc

    default_port = 80 if parsed.scheme.lower() == "http" else 443
    netloc = host if port is None or port == default_port else f"{host}:{port}"
    result = urlunsplit((parsed.scheme.lower(), netloc, parsed.path or "/", parsed.query, ""))
    if len(result) > 2048:
        raise ValueError("Article URL exceeds the document URL column limit.")
    return result


def sha256_text(value: str) -> str:
    """Hash the exact UTF-8 bytes; never hash lossy display-normalized text."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
