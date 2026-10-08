"""Conservative validation for Phase 9B discovery hits and ingested text."""

from urllib.parse import urlsplit

from apps.api.connectors.contracts import ExternalDiscoveryHit
from ml.provenance.identity import canonical_public_url, normalize_source_domain


def validated_discovery_identity(hit: ExternalDiscoveryHit) -> tuple[str, str]:
    url = canonical_public_url(hit.url)
    if urlsplit(url).scheme != "https":
        raise ValueError("External discovery records must use HTTPS URLs")
    actual_domain = normalize_source_domain(urlsplit(url).hostname or "")
    supplied_domain = normalize_source_domain(hit.publisher_domain)
    if actual_domain != supplied_domain:
        raise ValueError("Discovery publisher domain does not match the article URL")
    if not hit.title.strip() or len(hit.title) > 1000:
        raise ValueError("Discovery title must have 1 to 1000 characters")
    if not hit.publisher_name.strip() or len(hit.publisher_name) > 255:
        raise ValueError("Publisher name must have 1 to 255 characters")
    if hit.language is not None and len(hit.language) > 16:
        raise ValueError("Language metadata is too long")
    if hit.snippet is not None and len(hit.snippet) > 4000:
        raise ValueError("Discovery snippet is too long")
    return url, actual_domain
