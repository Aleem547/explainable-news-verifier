from datetime import UTC, datetime

import pytest

from apps.api.connectors.contracts import ContentKind, ExternalDiscoveryHit, Provider
from ml.ingestion.passages import split_passages
from ml.ingestion.validation import validated_discovery_identity
from ml.provenance.identity import sha256_text


def test_partition_exact_text() -> None:
    text = "Hello world!\n\n" + ("A claim needs a source. " * 80) + "Final🚀"
    spans = split_passages(text, max_chars=150)
    assert len(spans) > 1
    assert "".join(piece.text for piece in spans) == text
    assert [span.ordinal for span in spans] == list(range(len(spans)))
    for span in spans:
        assert span.text == text[span.start_offset : span.end_offset]
        assert span.sha256 == sha256_text(span.text)
    assert spans[-1].end_offset == len(text)


def test_long_unbroken_word() -> None:
    text = "x" * 1000
    spans = split_passages(text, max_chars=150)
    assert "".join(span.text for span in spans) == text
    assert max(len(span.text) for span in spans) <= 150


@pytest.mark.parametrize("bad", ["", "  \n", "\t"])
def test_empty_text_refused(bad: str) -> None:
    with pytest.raises(ValueError):
        split_passages(bad)


def test_max_chars_bounds() -> None:
    with pytest.raises(ValueError):
        split_passages("x", max_chars=99)
    with pytest.raises(ValueError):
        split_passages("x", max_chars=4001)


def test_large_document_refused() -> None:
    with pytest.raises(ValueError):
        split_passages("x" * 2_000_001)


def hit(url: str, domain: str) -> ExternalDiscoveryHit:
    return ExternalDiscoveryHit(
        provider=Provider.NEWSAPI,
        kind=ContentKind.NEWS_ARTICLE,
        url=url,
        publisher_domain=domain,
        publisher_name="Example",
        title="A title",
        snippet="Not article full text",
        discovered_at=datetime.now(UTC),
        published_at=None,
    )


def test_discovery_identity_matches_publisher() -> None:
    assert validated_discovery_identity(hit("https://EXAMPLE.com/a#fragment", "example.com")) == (
        "https://example.com/a",
        "example.com",
    )


def test_discovery_domain_spoof_rejected() -> None:
    with pytest.raises(ValueError, match="does not match"):
        validated_discovery_identity(hit("https://hostile.example/story", "trusted.example"))


def test_discovery_http_rejected() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        validated_discovery_identity(hit("http://example.com/story", "example.com"))
