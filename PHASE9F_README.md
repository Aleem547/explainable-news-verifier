# Phase 9F — Auditable cross-source evidence corroboration

## Scope and guarantees

**This phase creates an assessment service, not a fact-checking truth oracle.**

- Works with Phase 9C **full-text document passages** and exact `DocumentVersion` hashes, never NewsAPI/fact-check discovery snippets.
- Reuses an immutable Phase 9E `IndependenceAssessment`. Counts each provisional evidence **family once per stance**, avoiding duplicate article vote inflation.
- Keeps opposing evidence visible across/within evidence families; never averages contradictions into a truth confidence.
- Reports `MULTI_FAMILY_SUPPORT_UNVERIFIED` / `MULTI_FAMILY_REFUTATION_UNVERIFIED`, **not** independently corroborated, because Phase 9E does not establish independence.
- Makes a passage non-decisive when explicitly out of the caller's freshness window or future-dated; `AFTER_REFERENCE` warns because retrospective reporting can be valid.
- Retains the exact passage reference, claim hash, source-family assessment reference, optional temporal context, optional NLI model-run reference, threshold, original NLI label/confidence and decisions. If model provenance is not supplied, emits `NLI_MODEL_PROVENANCE_INCOMPLETE`.
- Creates **append-only** tables `cross_source_assessments`, `cross_source_evidence` via an **additive** Alembic migration.
- Does **not** modify `/api/v1/verify`, Phase 8 behavior or FEVER benchmark scores. It does not invoke NLI models, fetch news, contact external providers, publish to Qdrant, assert source independence or produce a public truth verdict. Wiring and evaluation follow in Phase 9G.

## Windows installation

Run from `C:\Projects\explainable-news-verifier` in VS Code PowerShell.

1. Ensure ZIP is in Downloads: `Test-Path "$HOME\Downloads\phase9f_implementation.zip"` — expect `True`.
2. Back up the sole overwritten file: `Copy-Item apps\api\db\models\__init__.py "$env:TEMP\phase9f_models_init_backup.py"`.
3. Extract: `Expand-Archive -LiteralPath "$HOME\Downloads\phase9f_implementation.zip" -DestinationPath "C:\Projects\explainable-news-verifier" -Force`.
4. Run offline:

```powershell
uv run ruff check . --fix
uv run ruff format .
uv run ruff check .
uv run ruff format --check .
uv run mypy apps ml scripts
uv run pytest
uv run python -m scripts.corroboration.check_phase9f
uv run alembic current
uv run alembic heads
```

Expected **before migration**: `current` = `9e7c40b8f621`, `heads` = `9f52a1c840d6`.

Only after the tests pass and confirming it is your local development PostgreSQL with a backup as appropriate:

```powershell
uv run alembic upgrade head
uv run alembic current
uv run alembic heads
uv run python -m scripts.corroboration.check_phase9f_database
```

Both migrations should then report `9f52a1c840d6 (head)`; smoke test prints `Phase 9F PostgreSQL transactional smoke test passed` followed by `Rolled back the smoke-test transaction`.

## Service interface

Use `apps.api.services.cross_source.record_cross_source_assessment(session, claim=..., independence_assessment_id=..., passages=(PassageNliInput(...), ...), assessed_at=..., reference_at=...)` *inside a caller-owned transaction*.

A `PassageNliInput` contains `passage_id`, `stance: EvidenceStance`, `confidence` (caller-supplied pair score), `nli_accepted`, `admissible`, optional `context_assessment_id`, and optional `model_run_id`.

- Each passage **must** exist in Phase 9C's `document_passages`, match its immutable version's offsets and hashes, and belong to the supplied Phase 9E assessment.
- Context assessments, when supplied, **must** refer to that same snapshot, exact claim SHA-256 and reference time; future context is rejected.
- `nli_accepted` and `admissible` must originate from an auditable verification workflow. Phase 9F **cannot independently prove that caller-supplied NLI predictions are valid, calibrated or relevant**.
- The returned `CrossSourceAssessment` has `outcome`, `independence_status`, and arrays of provisional supporting/refuting/mixed family IDs; inspect related `CrossSourceEvidence` rows for passage-level reasons.
- Do not confuse `decisive_count` (candidate passage-level NLI signals) with independently confirmed evidence sources or claim truth.

## Tests and safeguards

The new `test_phase9f_*` suite checks family counting, abstention, temporal review, contradictions, duplicates, tampering, future data and persistence boundaries. The offline check makes no external calls, model loads or database writes. The database smoke test uses a transaction and **always rolls it back**, including when an assertion fails.

The source ZIP for compatibility was provided by the user; the package contains only Phase 9F additions and a complete compatible `apps/api/db/models/__init__.py` replacement. It does not include user `.env`, credentials, datasets or weights.

**Git agreement:** do not commit or push until Phase 9G is completed and its checks pass.
