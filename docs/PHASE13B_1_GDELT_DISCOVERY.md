# Phase 13B.1 — Free GDELT discovery, metadata only

Scope: implements a pure **offline-testable** GDELT DOC ArticleList query builder and metadata parser, with no runtime dependency purchases and no modifications to FastAPI routes, database schema, or AWS production code.

## Why it is separate

Your existing `multisource_discovery.py` depends on configured NewsAPI / Google Fact Check provider credentials. The actual ingestion module (`external_ingestion.py`) correctly separates discovery metadata from authorized captured text, writes an indexing outbox rather than assuming indexing succeeded, and needs a transaction, a registered document and an explicit `storage_authorized=True` assertion. We preserve those boundaries.

`gdelt_metadata.py` intentionally contains **no HTTP requests**. A future adapter should make HTTPS requests **only** to `api.gdeltproject.org`, with a finite timeout, bounded response size, backoff/rate limits and security checks. Article links from GDELT are **untrusted discovery metadata**. Never fetch them by reusing this module's metadata URL validation: an independent SSRF-safe, redirect-safe and DNS-rebinding-safe article fetcher and an explicit content rights policy are required.

## Install into your existing branch

Copy these *new* files to matching relative paths in your existing checkout on `feat/phase13-cross-source`:

- `apps/api/services/gdelt_metadata.py`
- `tests/unit/test_phase13b_gdelt_metadata.py`
- `docs/PHASE13B_1_GDELT_DISCOVERY.md`

Run:

```powershell
python -m unittest discover -s tests/unit -p 'test_phase13b_gdelt_metadata.py' -v
```

If Python dependencies for the wider repo are not installed locally, these isolated tests use only standard-library imports.

**Do not turn on new production routes yet.** Existing cross-source scoring intentionally reports `independent_corroboration_established=False`; this patch must not alter it.

## What remains for 13B.2

1. Audit connector contracts, async provider HTTP client, and discovery DB models so the adapter fits existing code rather than bypassing validation and provenance.
2. Build a bounded HTTP client **only for the fixed GDELT API endpoint** with safe retries and rate-limit handling.
3. Normalize candidates through existing `DiscoveryHit` / `DiscoveryResult` contracts and transactional `ingest_discovery_result` if supported, without treating titles or snippets as factual evidence.
4. Add controlled article fetching and authorized ingestion only after SSRF/robots/terms/content rights decisions and integration tests.
5. Only then evaluate captured passages, assess common-origin/syndication, independently audit pairs and calibrate acceptance thresholds.

## GDELT limitations

GDELT is an external public service and may respond with rate limits or incomplete coverage. An absence of search results is **not** evidence that a claim is false. Publisher URLs listed in GDELT are not guaranteed accessible or licensed for storage, and multiple articles may copy the same primary report. Phase 13B.1 is English-keyword matching only and returns **candidates**, not corroboration.
