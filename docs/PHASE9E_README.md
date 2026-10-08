# Phase 9E — Source-independence and syndication diagnostics

## Scope

Adds auditable grouping for full-text document-version snapshots. It **does not** fetch articles, process discovery snippets as evidence, call APIs, rank source trust, or change claim-level verdicts. Distinct publishers/domains are **not** proof of independent reporting. A family is a conservative grouping of evidence which should not automatically be counted as independent.

## Pair rules (ordered)

1. Same registered publisher: `SAME_PUBLISHER`, grouped.
2. Matching **explicitly reported** origin URL, with observation URL recorded for each report: `DECLARED_COMMON_ORIGIN`, grouped and flagged as not externally verified.
3. Identical normalized full text (minimum 12 tokens): `IDENTICAL_TEXT`, grouped.
4. High five-word shingle overlap (minimum 80 tokens each; Jaccard >= 0.85): `POSSIBLE_TEXT_REUSE`, **not** automatically grouped; review required.
5. No qualifying evidence: `UNDETERMINED`, **not** declared independent.

Rule priority is intentionally conservative; these signals are not calibrated accuracy or truth probabilities. Near-duplicate thresholds are diagnostics, not an empirically validated plagiarism model. The family count must not be described as a verified count of independent news organizations or sources. Other shared wire-service patterns may still be missed.

## Files

- `ml/verification/source_independence.py`: deterministic offline assessment and evidence-family grouping.
- `apps/api/db/models/independence_assessment.py`, `independence_pair.py`: append-only records.
- `apps/api/services/source_independence.py`: transaction-bound read of immutable `document_versions`, pair persistence; does not commit.
- `migrations/versions/9e7c40b8f621_phase9e_independence.py`: additive migration from `9d4ef081ac23`.
- `scripts/independence/check_phase9e.py`: offline example.
- `scripts/independence/check_phase9e_database.py`: opt-in transactional PostgreSQL smoke test, rolled back.
- `tests/unit/test_phase9e_independence.py`, `test_phase9e_schema.py`: tests.

## Windows installation and validation

From `C:\Projects\explainable-news-verifier`, back up `apps\api\db\models\__init__.py` before extracting the archive with `Expand-Archive -Force`. Do **not** extract unless migration base is at revision `9d4ef081ac23`.

```powershell
uv run ruff check . --fix
uv run ruff format .
uv run ruff check .
uv run ruff format --check .
uv run mypy apps ml scripts
uv run pytest
uv run python -m scripts.independence.check_phase9e
uv run alembic current
uv run alembic heads
```

Expected current `9d4ef081ac23`, head `9e7c40b8f621`. After checks pass, **back up your development database** and run:

```powershell
uv run alembic upgrade head
uv run alembic current
uv run python -m scripts.independence.check_phase9e_database
```

The smoke test deliberately rolls back temporary sources, documents, versions, assessment and pair rows. Never run it against production.

## Integration boundaries

`record_independence_assessment(session, version_ids=..., assessed_at=..., reported_origins=...)` accepts 2–50 existing immutable full-text document snapshots. It persists the assessment and all pair findings to the caller's ongoing transaction. Only supply `ReportedOrigin` metadata when a traceable origin declaration exists and you are authorized to retain the metadata. The origin is **reported**, not independently verified.

This phase does not retroactively change Phase 8 claim-level NLI or corroboration status. Phase 9F can use the stored pair/family information to avoid double-counting reused reports after appropriate review and end-to-end evaluation.

## Known limits

- Full-text only, not snippets; no browser scraping or licensed-article acquisition.
- Conservative family merging is a heuristic and may undercount truly separate work or miss paraphrased syndication.
- No claim truth or publisher credibility scores.
- No automatic confirmation of independent corroboration, even if families differ.
- Full production integration and offline/online evaluation are later tasks.
