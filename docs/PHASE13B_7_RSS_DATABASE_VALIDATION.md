# Phase 13B.7 — RSS metadata -> PostgreSQL, local integration validation

This phase **adds tests only**. The existing `ingest_discovery_result` service is used unchanged, and it is the only code that registers sources, documents and discovery records. No production schema changes, no live RSS requests, and no API changes are included.

## Why this test is safe

- Requires explicit `PHASE13B7_LOCAL_DB_TEST=1` and the loopback PostgreSQL development database named `verifier`.
- `scripts/phase13b7/run_local_rss_db_test.ps1` assembles the local URL from the already-running development PostgreSQL container's settings, without printing the password or creating a secrets file.
- Creates an artificial, unique BBC-format article URL from an in-memory RSS fixture. **That URL is not a real article and is never fetched.**
- Uses the app's existing SQLAlchemy async engine, an isolated PostgreSQL outer transaction, and a session savepoint.
- Invokes the existing service twice and checks one source relationship, one document, and one discovery record. Verifies no article body or content hash is added.
- Even if the session commits its savepoint, the outer transaction is rolled back in `finally`. A new connection confirms that the synthetic article was not persisted.
- The external discovery ingestion function reports *items seen*, not counts of *new inserts*. The test asserts actual row counts for idempotency.

## Windows execution

Run in VS Code PowerShell from `C:\Projects\explainable-news-verifier`, with Docker Desktop running and your project `.venv` activated:

```powershell
python -m unittest discover -s tests/integration -p 'test_phase13b7_rss_db.py' -v
# Expected: fixture test passes, database test SKIPPED (safe default)

& .\scripts\phase13b7\run_local_rss_db_test.ps1
# Expected: both tests pass, 0 skipped (if asyncpg is installed and DB reachable)

git diff --check
```

If PowerShell blocks `.ps1` scripts, first run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned` (affects only the current terminal). If you see a connection error, verify PostgreSQL is healthy and that port 5432 is published. Do not expose database credentials in screenshots.

## Success criteria

1. Local offline fixture test succeeds.
2. Local PostgreSQL transaction test succeeds and inserts are rolled back.
3. RSS metadata remains **discovery only**. No document full-text passage or truth verdict is produced.
4. Source code is still on `feat/phase13-cross-source`; AWS is unchanged.

## Limitations and next step

This tests the persistence service with a representative in-memory RSS result. It does **not** prove a live RSS -> API -> DB request path. After success, run an authenticated local discovery endpoint check under the app's existing access control and verify its transaction commit/rollback behavior. Later phases handle authorized article extraction and independent corroboration.
