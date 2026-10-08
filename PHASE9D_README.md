# Phase 9D — Source Metadata and Temporal Context (Windows)

## Scope and safety boundaries

This *additive* release is compatible with Phase 9C (`9c36be16d992`). It adds source-profile observations and document-context assessments **without modifying** Phase 8 verdicts, retrieval ranking, source credibility, or external indexing. `BEFORE_REFERENCE`/`AFTER_REFERENCE` are **time relationships**, not NLI labels. `OLDER_THAN_WINDOW` is a caller-selected age heuristic, **not evidence of falsity**. Absence of a publisher disclosure URL is **not** a negative credibility judgment.

- A `source_profile_observation` records what was reported, by which collection method, and when; it does **not** establish that a policy was actually followed.
- A `document_context_assessment` refers to one immutable snapshot and stores the optional SHA-256 hash of the claim text (not the raw claim), explicit reference time, contextual flags, and warnings.
- All timestamps must include timezone information. UTC day granularity is used for source publication versus claim reference; no date is inferred from free-form claim prose.
- The retrieval event must refer to the same source/document/version and be a `FETCHED` observation before it can count as matching fetch metadata.
- Existing document versions must pass SHA-256 text-integrity validation. Context cannot use observations made *after* its `assessed_at` time.
- No API key, internet connection, paid service, or LLM download is necessary for the offline checks.
- URL normalization does **not** imply SSRF protection; **never fetch** arbitrary URLs without secure outbound connector validation.

## Files shipped

**Models:** `apps/api/db/models/source_profile_observation.py`, `document_context_assessment.py`, updated `__init__.py` exports.

**Engine:** `ml/verification/source_context.py`.

**Database service:** `apps/api/services/source_context.py` (`record_source_profile`, `assess_document_context`). The calling worker owns commit/rollback; services never commit or make HTTP calls.

**Migration:** `migrations/versions/9d4ef081ac23_phase9d_context_assessments.py`.

**Scripts:** `scripts/context/check_phase9d.py` (offline), `scripts/context/check_phase9d_database.py` (opt-in PostgreSQL transaction rollback test).

**Tests:** `tests/unit/test_phase9d_context.py`, `test_phase9d_schema.py`, `test_phase9d_service.py`.

## Install

From PowerShell, at `C:\Projects\explainable-news-verifier`:

```powershell
cd C:\Projects\explainable-news-verifier
Test-Path "$HOME\Downloads\phase9d_implementation.zip"
Copy-Item apps\api\db\models\__init__.py "$env:TEMP\phase9d_models_init_backup.py"
Expand-Archive -LiteralPath "$HOME\Downloads\phase9d_implementation.zip" -DestinationPath . -Force
```

The `__init__.py` file is the only existing file that is replaced; it preserves Phase 9A–9C model exports and adds two new classes. Inspect `git diff` before proceeding. Do not stage, commit, or push until Phase 9G, as agreed.

## 1: Validate **before** applying migrations

```powershell
uv run ruff check . --fix
uv run ruff format .
uv run ruff check .
uv run ruff format --check .
uv run mypy apps ml scripts
uv run pytest
uv run python -m scripts.context.check_phase9d
uv run alembic current
uv run alembic heads
```

Expected Alembic state *before* migration:

- `current`: `9c36be16d992`
- `heads`: `9d4ef081ac23`

If anything fails, stop and share the full error, do not continue to migration.

## 2: Migrate local development PostgreSQL

Inspect environment and take a database backup if existing local data matters. Compose may warn about unresolved variable substitutions if your project's `.env` values differ; do not recreate containers using empty passwords.

```powershell
docker compose -f infra\docker\compose.dev.yml ps
uv run alembic upgrade head
uv run alembic current
uv run alembic heads
```

Both revision commands should show `9d4ef081ac23 (head)`. The migration adds two tables and indexes. It does not alter Phase 9A/9C rows.

## 3: Optional real PostgreSQL transactional smoke test

```powershell
uv run python -m scripts.context.check_phase9d_database
```

This **writes and reads temporary data inside a database transaction and rolls it back**. Use only your development DB and verify the database URL; never point this script at production. It does not call external APIs.

## 4: Verify after migration

```powershell
uv run ruff check .
uv run mypy apps ml scripts
uv run pytest
uv run alembic current
```

A deprecation warning inside Starlette's TestClient may appear. It does not affect the Phase 9D tests.

## Example usage from future workers (not wired into the FastAPI verification route yet)

```python
from datetime import UTC, datetime
from ml.verification.source_context import SourceObservationMethod
from apps.api.services.source_context import record_source_profile, assess_document_context

# `session` is an existing AsyncSession with an open transaction.
profile = await record_source_profile(
    session,
    source_id=source_id,
    observed_at=datetime.now(UTC),
    method=SourceObservationMethod.PROVIDER_METADATA,
    publisher_name_reported="Publisher-provided display name",
)
assessment = await assess_document_context(
    session,
    document_version_id=document_version_id,
    assessed_at=datetime.now(UTC),
    reference_at=datetime(2025, 1, 1, tzinfo=UTC),
    max_age_days=365,
    source_profile_observation_id=profile.id,
    claim_text="An explicitly dated claim",
)
# The worker commits on success, or rolls back on failure.
```

This code example is only applicable when actual `source_id` and `document_version_id` exist and refer to the same stored source/document. The example source name is unverified metadata.

## Future Phase 9E/9F dependencies

- 9E checks **reporting lineage and independence**, not inferred from domain alone.
- 9F will apply domain-specific temporal relevance to individual atomic claims. Generic `BEFORE_REFERENCE` cannot automatically invalidate retrospective or historical evidence.
- 9G will integrate and evaluate these metadata assessments in the API. The Phase 8 Wikipedia verdict is unchanged during 9D.
- Live API credentials and cloud deployment are not part of this archive.

## Rollback strategy

If only code checks fail, revert the extracted new files and restore the original `__init__.py` from the temporary backup. **Do not run `alembic downgrade` as a casual recovery step**: it drops the two Phase 9D tables and their audit records. Back up the database first and discuss the failure before schema rollback.
