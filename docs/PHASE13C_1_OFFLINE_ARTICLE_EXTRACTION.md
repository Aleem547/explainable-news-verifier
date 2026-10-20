# Phase 13C.1 — Bounded offline article extraction

## Status and scope

This change extracts **already-fetched** HTML into unverified article text and advisory metadata.
It introduces **no HTTP fetching**, no persistence, no claim verification, and no changes to
AWS or Vercel. It is not the full Phase 13C article-ingestion pipeline.

The extractor is built around [Trafilatura](https://trafilatura.readthedocs.io/en/latest/usage-python.html),
which is free and open source. The `pyproject.toml` dependency is pinned to a compatible
major version (`trafilatura>=2.3.1,<3`). Do not call `trafilatura.fetch_url()`.

## Provenance and validation

`extract_discovered_article_html()` accepts an existing `ExternalDiscoveryHit`,
bytes from a trusted audited downloader, the final fetched URL, content type and a
timezone-aware retrieval timestamp. It checks:

- The discovery result represents a news article, not a fact-check rating.
- Publisher domain matches the discovered HTTPS article URL.
- The fetched URL matches the recorded discovery URL. Unvalidated redirects fail closed.
- Only HTTPS on the normal 443 port is admitted, and only HTML content types are parsed.
- The already-decompressed HTML payload must fit within 1,000,000 bytes by default.
- Extracted article text must be between 100 and 500,000 Unicode characters by default.
- The returned record contains SHA-256 digests of the exact source HTML and extracted text.
- Page-declared `url` and `source` are ignored so that embedded metadata cannot replace
  the discovery URL/publisher identity.
- `independently_verified` is always `False`; extraction **does not establish truth**.
- Reported title, author, and publication date are **unverified page metadata**.

Extraction deliberately performs **no** network or database activity. A discovered URL
being syntactically HTTPS is not an SSRF safety guarantee. Do not take a discovered URL
and pass it to `httpx.get()` or `trafilatura.fetch_url()` without an audited fetch policy.

## Local installation and tests (Windows PowerShell)

Make sure your working branch is `feat/phase13-cross-source`. Copy the five files
in the ZIP into the matching project locations, **including** the updated `pyproject.toml`
(which adds Trafilatura as a required dependency).

```powershell
cd C:\Projects\explainable-news-verifier
& .\.venv\Scripts\Activate.ps1
python -m pip install "trafilatura>=2.3.1,<3"
python -m unittest discover -s tests/unit -p "test_phase13c1_article_extraction.py" -v
python -m unittest discover -s tests/integration -p "test_phase13c1_trafilatura_smoke.py" -v
git diff --check
git status -sb
```

The first suite uses a fake, deterministic extractor so it can run offline without
Trafilatura installed. The second test exercises the **actual** library using a
synthetic HTML article; it skips if the library isn't installed. It sends no requests.

No ZIP-supplied module is automatically invoked by the running API; tests only.

## Remaining Phase 13C work (not yet delivered)

1. A separate, audited **fetcher** enforcing publisher-specific access permission,
   anti-SSRF IP/DNS handling (including rebinding), secure redirects/redirect refusal,
   response streaming, compressed/decompressed size caps, media-type verification,
   timeouts, TLS, and rate limits. It must not bypass a publisher's robots, paywalls,
   or website restrictions.
2. Explicit content-retention authorization before calling `ingest_supplied_content()`.
   Extracted text must not be copied to PostgreSQL without permission to store it.
3. Document/version snapshot and retrieval-observation linkage in PostgreSQL, plus
   transactional tests and duplicate/retry handling.
4. Evidence admissibility, passage retrieval and NLI tests; corroboration requires
   multiple **genuinely independent** sources, not copied syndicated content.
5. Evaluation and performance before merging into main or deploying to AWS/Vercel.

If the live website is already serving users, keep that production deployment unchanged.
