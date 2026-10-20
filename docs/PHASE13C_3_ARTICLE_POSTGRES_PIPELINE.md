# Phase 13C.3 — Authorized Article to PostgreSQL (development only)

## Existing contracts reviewed

The existing `ingest_discovery_result()` registers a publisher, document identity,
and metadata record. `ingest_supplied_content()` requires **explicit storage
authorization** and creates a content snapshot, exact-offset passages, pending
`external_passages_v1` outbox entry, and a retrieval observation. It never
commits on behalf of the caller. This phase reuses those APIs and ORM tables.

## New integration module

`apps/api/services/article_content_pipeline.py` exposes:

- `store_authorized_article(session, discovery_result=..., article=...,
  storage_authorized=True)` for already-extracted text.
- `fetch_extract_store_authorized_article(session, discovery_result=...,
  approved_publisher_domains=..., publisher_access_approved=True,
  storage_authorized=True)` for trusted server-side orchestration.

Both accept exactly **one** `NEWS_ARTICLE` discovery hit. Discovery/provider,
publisher-domain, URL identity, extraction hashes and timestamps are checked.
The fetcher is the Phase 13C.2 DNS-checked, pinned-IP HTTPS fetcher and is
run in a worker thread, as is Trafilatura extraction. The default implementation
**does not follow redirects**. Publisher domain allowlists must come from
trusted server configuration, *never* an HTTP request body. A human/operator
or independently implemented publisher-policy process must confirm URL access,
robots and applicable retention rights first. Booleans are explicit gates,
**not an automatic publisher-authorization service**.

The module intentionally **does not add a public FastAPI endpoint**. It is not
safe to accept an arbitrary URL from a user and set permission flags to True.
Do not use to download paywalled, restricted or forbidden content.

### Transaction and provenance

- DB work uses a nested savepoint. Caller still owns the surrounding transaction
  and must `commit()` on success or `rollback()` on failure.
- First metadata, then content, then passage splitting, version and outbox.
- Retrieval observation provider is `secure_article_fetch_v1` (not incorrectly
  `rss_feed`), with discovery provider and SHA-256 of HTML and extracted text in
  `metadata_json`.
- Article body is stored as extracted `text/plain`; original HTML is not stored.
- Duplicate same-document content reuses the existing latest version/passages;
  each authorized fetch still produces its own retrieval observation.
- `IndexOutbox` status is only **PENDING**; this does not assert actual Qdrant
  indexing, evidence acceptability, source independence or claim truth.
- Retrieved content remains **independently_verified=False**. No claim-linked
  `Evidence` row is created or verdict produced by this workflow.

## Local tests (no network requests)

1. Offline unit tests: 11 tests for permission gates, identities, hashes,
   metadata preservation and orchestration via injected fake fetch/extract.
2. Offline fixture: one test that asserts the synthetic sample is unverified.
3. PostgreSQL integration test: gated by `PHASE13C3_LOCAL_DB_TEST=1`, and uses
   only `postgresql+asyncpg`, host `127.0.0.1`/`localhost` and DB name `verifier`.
   It tests duplicate registration, versions, passages, outbox, source and
   retrieval metadata. An outer transaction is always rolled back, including
   after a session savepoint commit. No live news URLs are accessed.

From **Windows PowerShell in repository root**:

```powershell
python -m unittest discover -s tests/unit -p "test_phase13c3_article_pipeline.py" -v
& .\scripts\phase13c3\run_local_article_db_test.ps1
git diff --check
```

The second command requires running local Docker PostgreSQL and an activated
project `.venv`. It reads PostgreSQL credentials from that container to assemble
a loopback-only connection string, and restores the former environment value
without printing passwords. It MUST NOT be run against production.

## Not yet complete

- A publisher permissions/robots decision service, rate limits, robots cache,
  content-use policies and operations dashboard
- An approved, scheduled production fetch worker with source-specific policies
- A production-approved full text retention policy and deletion schedule
- Index-outbox consumer verification (actual vector indexing), source
  independence analysis, DeBERTa corroboration and accuracy evaluation
- Live HTTP fetching/integration tests of permitted publisher URLs

Do not merge to `main` or deploy to AWS until those controls are reviewed and
full CI/end-to-end checks pass.
