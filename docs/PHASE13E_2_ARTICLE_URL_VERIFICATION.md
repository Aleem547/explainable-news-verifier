# Phase 13E.2 — Article URL Preparation (local only)

## Scope

A **permission-gated, internal** coordinator accepts a submitted public HTTPS URL only if it exactly matches a trusted `ExternalDiscoveryHit` from an already audited discovery process. An approved publisher must be present in a **server-controlled** domain allowlist and the server must attest to appropriate publisher-access permissions. The coordinator then uses the existing Phase 13C.2 pinned-IP/TLS HTTPS fetcher and Phase 13C.1 Trafilatura extractor, preserving article URLs, publishers, retrieval timestamps and SHA-256 fingerprints.

**Do not call this a complete article verification endpoint.** It does not store article text, extract factual claims, run NLI, evaluate accuracy or produce truth verdicts. Its result state is `READY_FOR_CLAIM_EXTRACTION`, always `independently_verified=False`. Pasted text, claim extraction, multi-claim verification, reporting and a secured public route are Phases 13E.3–13E.7.

## Security and permissions

- No arbitrary URL is fetched just because a user submits it. A trusted discovered-hit identity must match its canonical URL exactly; path and query remain part of the identity.
- HTTP, nonstandard ports, IP literals, credentials and malformed domains fail closed. The underlying existing fetcher also checks DNS answers, pins the public IPv4 peer, verifies the TLS hostname, refuses redirects and non-HTML/compressed responses, and enforces size/timeout limits.
- Publisher permission and robots/access rules must be evaluated **outside this module** by a trusted service. Setting `publisher_access_approved=True` in client-supplied JSON is NOT acceptable. The domain allowlist and trusted discovery records must never be taken from user-controlled request fields.
- Fetch/extract are blocking operations run via `asyncio.to_thread`; cancellation does not terminate a running thread. A future API route must implement authenticated quotas, concurrent-worker limits, abuse protection, and request lifecycle handling.
- Metadata in extracted HTML (title, author, date) is advisory; discovery identity is authoritative for this stage. Hash and timestamp inconsistencies are rejected. No article body is persisted here.
- Dependency injection (`fetcher`, `extractor`) exists for **offline tests**, not for untrusted inputs.
- A structurally valid provenance trail and matching hashes do not establish source independence or prove a claim.

## Files

- `apps/api/services/article_url_preparation.py`: internal async coordinator and immutable result.
- `tests/unit/test_phase13e2_article_url_preparation.py`: 39 offline tests (mocked fetcher/extractor, no network).
- `tests/integration/test_phase13e2_article_url_extractor_smoke.py`: optional 1-test real-Trafilatura extraction from synthetic HTML, with a mocked fetcher.
- `scripts/phase13e2/run_local_article_url_tests.ps1`: Windows test runner.

## Windows validation

From the repository root, on `feat/phase13-cross-source`, in the project `.venv`:

```powershell
& .\scripts\phase13e2\run_local_article_url_tests.ps1
& .\scripts\phase13e2\run_local_article_url_tests.ps1 -IncludeRegressions
& .\scripts\phase13e2\run_local_article_url_tests.ps1 -IncludeExtractorSmoke
git diff --check
git status -sb
```

Expect **39 new unit tests**. With regressions, expect **16 Phase 13C.1**, **20 Phase 13C.2**, and **36 Phase 13E.1** tests as previously specified, for **111** total across those suites. The optional real-extractor smoke test adds **1** more test. If any test fails, do not commit or deploy.

## Deferred

Phase 13E.7 will design the actual authenticated HTTP API after publisher policy evaluation, quotas, privacy implications, and request size/rate boundaries are reviewed. Phase 13F must audit live network behavior, DNS and redirects, race conditions, publisher access, and content licensing before production release. Phase 13E.4–13E.6 still need claim extraction and reporting.
