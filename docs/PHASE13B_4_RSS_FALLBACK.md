# Phase 13B.4 — Free RSS Discovery Fallback (local development)

## Scope

Adds **metadata-only** RSS discovery using fixed, publicly accessible feeds from:

- BBC News World: `https://feeds.bbci.co.uk/news/world/rss.xml`
- NPR: `https://feeds.npr.org/1001/rss.xml`
- The Guardian World: `https://www.theguardian.com/world/rss`

These curated feeds are not guaranteed to cover a claim, stay available, or be permitted for commercial reuse. Review each publisher's terms before production use. No paid news API is required. No article bodies are fetched or verified, and no third-party publisher automatically becomes a "trusted" or "independent" source.

## Discovery API selection

The existing restricted endpoint `/multisource/discover` supports two new explicit provider choices:

- `"provider": "rss"`: use the curated RSS feeds directly (does not call GDELT).
- `"provider": "gdelt_rss"`: request GDELT; if it fails due to 429, timeout, network error, or supported 5xx errors, fall back to RSS.

The existing `"provider": "gdelt"` and default `"both"` behavior is unchanged. GDELT invalid-response errors do **not** get silently hidden by RSS. The multi-source access gate remains in place; no public endpoint was added.

Response `searched_providers` and `failed_providers` expose whether fallback occurred. A successful search yielding 0 links **does not** establish the truth or falsity of a claim.

## Security and provenance safeguards

- Strict allowlist of three HTTPS RSS feed destinations (no user-supplied fetch URLs).
- No redirects, no proxies from environment, short HTTP timeouts via existing client.
- One request per feed per discovery, with an XML payload bound to 512 KB.
- Reject HTML/non-XML responses, XML doctypes/entities and malformed RSS.
- RSS item URLs must be HTTPS and belong to the feed's approved article publisher domain.
- Keyword matches are discovery hints only, not relevance probabilities or evidence.
- No article text, feed descriptions, or NLI verdicts are persisted by this phase.
- RSS publication dates are retained only if timezone-aware and parsable.

## Install (Windows PowerShell, branch feat/phase13-cross-source)

Unzip into `%TEMP%` and copy the 9 files into their matching paths inside the existing repository. This overwrites only five existing code files and creates four new ones. No commit or push is needed.

## Offline regression tests

```powershell
python -m unittest discover -s tests/unit -p "test_phase13b*.py" -v

git diff --check

git status -sb
```

Expected from the supplied review snapshot: **29 passing tests**. Local results might differ if other repository dependencies have changed; share failures before troubleshooting.

## Known limitations / next phase

- RSS feeds aren't query-search engines; a relevant article might not appear in the limited current headlines. Zero hits are expected for older or niche claims.
- A provider may rate-limit or redirect a feed; this connector refuses redirects and records failure, instead of fetching arbitrary destinations.
- A missing or incompatible HTTP content type will cause a safe failure.
- The fallback is not a replacement for the later licensed/authorized article-ingestion phase, claim evidence extraction, or rigorous independent-source analysis.
- Pre-production work still needs live RSS checks and an end-to-end database integration test.
- Add per-feed caching and global request budgets before enabling this at public production scale.
