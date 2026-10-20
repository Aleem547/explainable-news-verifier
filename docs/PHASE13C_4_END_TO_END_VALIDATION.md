# Phase 13C.4 — End-to-End Local Article Processing Validation

Tests the full `fetch_extract_store_authorized_article` coordinator with:

- A deterministic, in-memory HTTPS response stub (NO live HTTP or real publisher content)
- Real Trafilatura extraction of synthetic HTML
- The existing PostgreSQL document, document-version, passage, index-outbox and provenance tables
- A second identical ingest that must not duplicate the document, version, or outbox
- An explicit assertion that *no* claim-linked Evidence is created
- A DB transaction rollback and post-rollback absence assertion

## Run on Windows

After extracting the ZIP at your repository root:

```powershell
cd C:\Projects\explainable-news-verifier
& .\scripts\phase13c4\run_local_end_to_end.ps1
```

Prerequisites: the `feat/phase13-cross-source` branch, a running local
`explainable-news-verifier-dev-postgres-1` container, `.venv` with
`trafilatura`, `sqlalchemy` and `asyncpg`, and the migrated `verifier` DB.

This test DOES NOT verify publisher permissions or run a live article download.
The `publisher_access_approved=True` and `storage_authorized=True` flags
apply strictly to synthetic, test-owned HTML in the fixture. Never set these
flags automatically based only on an RSS or GDELT discovery result.

Passage indexing is queued, not executed in this test. These records are
**unverified external text**, never independent corroboration.

The script refuses non-loopback databases and restores DATABASE_URL and the
test flag when complete. Do not run it against AWS.
