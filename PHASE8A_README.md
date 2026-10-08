# Phase 8A — Conservative Evidence Hygiene (Windows)

## Scope

- Filters navigation/disambiguation articles unless the claim explicitly asks about disambiguation.
- Removes empty sentences and repeated sentence IDs/text, keeping the highest-ranked representative.
- Conservatively removes near-duplicates *within the same page* only if the words and numbers match exactly and ordering is almost identical.
- Overfetches up to 2× the requested top_k (capped at 20) to refill the candidate pool.
- Adds audit fields to the `/api/v1/verify` response:
  `quality_excluded_count`, `quality_exclusions`, `unused_candidate_count`.
- **Does not** filter replicas or geographically qualified page titles by keyword alone. That is Phase 8B entity resolution and requires separate validation.
- **Does not** convert a high NLI probability into a claim-level truth probability.

## Installation

1. Stop your running FastAPI server (Ctrl+C) before changing files.
2. From the project root back up existing files:

   ```powershell
   Copy-Item ml\verification\evidence_pipeline.py ml\verification\evidence_pipeline.phase7e.bak
   Copy-Item apps\api\schemas\verification.py apps\api\schemas\verification.phase7f.bak
   ```

3. Extract `phase8a_evidence_quality.zip` directly to the repo root using `Expand-Archive ... -Force`.
4. Run `uv run ruff check . --fix`, `uv run ruff format .`, `uv run mypy apps ml scripts`, `uv run pytest`.
5. Start the API and call the existing `/api/v1/verify` endpoint; existing request JSON is unchanged.

## Behavioral notes

`retrieved_count` now counts the larger retrieval candidate pool; `assessed_count` is at most the requested `top_k`. Some evidence is deliberately excluded. A smaller list is not itself a failure.

## Do not yet deploy publicly

This is evidence hygiene, not cross-source provenance verification, calibration on retrieved-pair distribution, temporal/geo entity resolution, or a substitute for human review. Treat outcomes as provisional.

No Git commit or push is required.
