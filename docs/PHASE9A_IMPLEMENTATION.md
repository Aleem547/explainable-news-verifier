# Phase 9A — Multi-Source Architecture and Provenance

**Scope:** Additive PostgreSQL schema + typed services + unit tests. No crawling,
API calls, user-facing routes, source trust scores, or independent corroboration yet.

**Existing schema inspected:** `sources`, `documents`, and `evidence` from the
reference archive. Alembic head was `5014402fb40f`. Phase 9A migration
`9a16d02cbe34` depends on that revision and **does not alter or drop the old tables**.

## New tables

| Table | What is stored | Important safeguard |
| --- | --- | --- |
| `document_versions` | Content text, exact UTF-8 SHA-256, snapshot URL, capture/retrieval times | Unique `(document_id, version_number)`; previous versions kept |
| `retrieval_observations` | Provider, requested URL, status, redirects, ETag, fetch time, optional snapshot linkage | Failures/304s can be logged without inventing document contents |
| `evidence_provenance` | Existing evidence row -> exact version, optional observation, extraction locator | One provenance record per evidence ID; document/snapshot match validated by service |

Reuses the existing unique `sources.domain` constraint; `register_source` is
transaction-safe (`INSERT ... ON CONFLICT DO NOTHING`) and leaves existing records
unchanged. The existing `documents.raw_text` and `documents.content_hash` cache is
updated only by the explicit `capture_document_version` operation, under a parent
row lock. The caller is responsible for committing/rolling back the transaction.

`Source` is **publisher identity**, not a source-reliability rating. Two distinct
hostnames do not imply two independently originated reports. Syndication/ownership
analysis and true corroboration belong to Phases 9D–9F.

## Windows installation: VS Code + PowerShell

1. From `C:\Projects\explainable-news-verifier`, verify your Git tree and keep
   the ZIP outside the source tree. Do **not** run `git add` or `git push` yet.
2. Make a backup of `apps\api\db\models\__init__.py` before extraction.
3. Inspect ZIP members using `tar -tf "<zip-path>"`; ensure paths are under the
   existing project layout, with no unexpected absolute paths.
4. Extract the ZIP to your repository root using `Expand-Archive`.
5. Run (from the repository root):

   ```powershell
   uv run ruff format .
   uv run ruff check .
   uv run ruff format --check .
   uv run mypy apps ml scripts
   uv run pytest
   uv run alembic heads
   uv run alembic current
   ```

   `heads` should report `9a16d02cbe34`, while `current` stays
   `5014402fb40f` until the migration is applied.
6. **Only for your local development database**, after confirming PostgreSQL
   is running and your database URL points to your *development* DB, create a DB
   backup/snapshot, then run:

   ```powershell
   uv run alembic upgrade head
   uv run alembic current
   ```

   Expected current revision: `9a16d02cbe34 (head)`.
7. Re-run lint, mypy and pytest after migrating. Review `git status --short`.
   Commit/push only at the end of **Phase 9G**, as agreed.

Do not run `alembic downgrade` on a database containing valuable real data.

## Service entry points

- `ml.provenance.identity.normalize_source_domain(domain)`
- `ml.provenance.identity.canonical_public_url(url)`
- `ml.provenance.identity.sha256_text(text)`
- `apps.api.services.source_registry.register_source(session, *, name, domain, source_type)`
- `apps.api.services.provenance.capture_document_version(session, *, document_id, text, retrieved_at)`
- `apps.api.services.provenance.record_retrieval_observation(...)`
- `apps.api.services.provenance.attach_evidence_provenance(...)`

Use one SQLAlchemy async session transaction for capture + observation + evidence
linking. All timestamps supplied to service methods must include a timezone.
Each retrieval attempt gets a new observation; unchanged content can reuse the
latest version. A change back to previously seen text creates a new version if
the immediately preceding snapshot differed.

## Design boundaries and limitations

- **No outbound HTTP request occurs in Phase 9A.** URL normalization is *not*
  SSRF protection. Phase 9B must resolve and reject private/reserved IP addresses,
  enforce egress policy and re-check each redirect; DNS can change between checks.
- Preserving query strings avoids merging distinct articles. Only URL fragments,
  scheme/hostname case and default port are normalized; no arbitrary `www` or
  tracking-parameter removal.
- Source registry must not be treated as an authority classifier.
- Do not store credentials, API keys, authorization headers or other secrets in
  `retrieval_observations` or its `metadata_json` field.
- New evidence provenance applies to **new relational evidence records** only.
  Historical Phase 8 FEVER outputs aren't retroactively backfilled.
- The `attach_evidence_provenance` service verifies parent document consistency.
  It does not yet check that the passage text is a substring of the exact version;
  detailed span validation is part of Phase 9C ingestion.
- Content history currently stores text in PostgreSQL. A future object-store
  strategy may be needed for very large corpora and copyright/retention policies.
- The migration can be tested against your local PostgreSQL installation; package
  unit tests use offline metadata checks and mocked sessions. They are not a
  substitute for a real migration integration test.

## Validation gates before Phase 9B

- `uv run alembic current` reports `9a16d02cbe34`.
- Ruff lint + format, strict mypy and pytest pass.
- The old `/api/v1/verify` endpoint still works with the Phase 8 models.
- `git status --short` contains only intended source/tests/docs/migration;
  no raw data, ZIPs, `.env`, model weights or generated reports.
