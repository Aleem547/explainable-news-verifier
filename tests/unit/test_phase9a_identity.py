"""Offline Phase 9A identity tests: never contact a publisher."""

import pytest

from ml.provenance.identity import canonical_public_url, normalize_source_domain, sha256_text


def test_domain_normalization_preserves_subdomains() -> None:
    assert normalize_source_domain(" WWW.Example.COM. ") == "www.example.com"
    assert normalize_source_domain("example.com") == "example.com"
    assert normalize_source_domain("www.example.com") != normalize_source_domain("example.com")


def test_domain_supports_idna() -> None:
    assert normalize_source_domain("BÜCHER.example") == "xn--bcher-kva.example"


@pytest.mark.parametrize(
    "domain",
    ["localhost", "127.0.0.1", "example", "example.com/path", "a..example.org", "x@example.org"],
)
def test_invalid_publisher_domains(domain: str) -> None:
    with pytest.raises(ValueError):
        normalize_source_domain(domain)


def test_url_canonicalization_keeps_query_and_strips_fragment() -> None:
    assert canonical_public_url("HTTPS://EXAMPLE.com:443/news?story=1#section") == (
        "https://example.com/news?story=1"
    )


def test_url_keeps_nondefault_port_and_case_sensitive_path() -> None:
    assert canonical_public_url("https://Example.com:8443/ABC") == "https://example.com:8443/ABC"


@pytest.mark.parametrize(
    "url",
    ["file:///tmp/a", "http://localhost/test", "https://127.0.0.1/", "https://a:b@example.org/"],
)
def test_unsafe_url_forms_rejected(url: str) -> None:
    with pytest.raises(ValueError):
        canonical_public_url(url)


def test_sha256_uses_exact_text_bytes() -> None:
    assert sha256_text("abc") == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )
    assert sha256_text("a\nb") != sha256_text("a\r\nb")
