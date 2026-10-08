"""Offline smoke check: never makes external API calls or writes to PostgreSQL."""

from datetime import UTC, datetime

from apps.api.connectors.contracts import ContentKind, ExternalDiscoveryHit, Provider
from ml.ingestion.passages import split_passages
from ml.ingestion.validation import validated_discovery_identity


def main() -> None:
    example = ExternalDiscoveryHit(
        provider=Provider.NEWSAPI,
        kind=ContentKind.NEWS_ARTICLE,
        url="https://example.com/story",
        publisher_domain="example.com",
        publisher_name="Example Publisher",
        title="Example demonstration",
        snippet="Discovery-only preview, not verified evidence.",
        discovered_at=datetime.now(UTC),
        published_at=None,
    )
    url, domain = validated_discovery_identity(example)
    sample = "Example content. " * 70
    spans = split_passages(sample)
    assert "".join(span.text for span in spans) == sample
    print("Phase 9C offline checks passed")
    print(f"Example publisher domain: {domain}")
    print(f"Example URL: {url}")
    print(f"Prepared passages: {len(spans)}")
    print("No API requests or database writes performed")


if __name__ == "__main__":
    main()
