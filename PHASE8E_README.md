# Phase 8E — Named-subject admissibility before NLI aggregation

## Scope

This change addresses an observed failure: the claim **"Rio's sequel is an American musical comedy film"** was incorrectly refuted by an NLI result from **An Inconvenient Sequel: Truth to Power** (a film unrelated to *Rio 2*).

Rather than adjusting the calibrated NLI temperature or guessing a new threshold, the pipeline now checks whether the retrieved page title or evidence sentence explicitly anchors the claim's *initial named subject*. Only high-confidence ENTAILMENT / CONTRADICTION results require this additional check. A rejected result remains in the `evidence` array for audit, but has `accepted=false` and `admissibility_reason="SUBJECT_NOT_GROUNDED"` and cannot become a primary verdict contributor. `admissibility_blocked_count` counts blocked, otherwise accepted, decisive predictions. The original NLI label and confidence are retained unchanged.

**Scope limitation:** This is a high-precision text heuristic, NOT full entity linking, coreference resolution, semantic relevance modeling, or multi-hop evidence-chain reconstruction. Evidence with an implicit or aliased subject can be incorrectly rejected. Compare on validation before deciding to keep this safeguard as a product default.

## Files

- `ml/verification/decisive_admissibility.py` (new)
- `ml/verification/evidence_pipeline.py` (complete replacement, based on Phase 8C)
- `apps/api/schemas/verification.py` (complete replacement with optional audit fields)
- `tests/unit/test_decisive_admissibility.py` (new)
- `PHASE8E_README.md` (this file)

Your existing `ml/verification/entity_relevance.py` and `ml/verification/evidence_quality.py` **must remain untouched**. The new guard executes *after NLI*, immediately before aggregation, and is independent of Phase 8B pre-screening.

## Windows PowerShell installation

Stop the running FastAPI server with Ctrl+C. From the repository root:

```powershell
cd C:\Projects\explainable-news-verifier
$backup = Join-Path $env:TEMP 'verifier_phase8e_backup'
New-Item -ItemType Directory -Force -Path $backup | Out-Null
Copy-Item ml\verification\evidence_pipeline.py "$backup\evidence_pipeline.py"
Copy-Item apps\api\schemas\verification.py "$backup\verification_schema.py"
Expand-Archive -LiteralPath "$HOME\Downloads\phase8e_named_subject_grounding.zip" -DestinationPath . -Force
```

Check the installation:

```powershell
Test-Path ml\verification\decisive_admissibility.py
Test-Path tests\unit\test_decisive_admissibility.py
uv run ruff check .
uv run mypy apps ml scripts
uv run pytest
```

## Rio API reproduction

Run FastAPI in Terminal 1:

```powershell
uv run uvicorn apps.api.main:app --host 127.0.0.1 --port 8000 --reload
```

Terminal 2:

```powershell
$body = @{claim = "Rio's sequel is an American musical comedy film."; top_k = 10} | ConvertTo-Json
$r = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/verify" -Method Post -ContentType "application/json" -Body $body
$r | Select-Object claim, verdict, aggregation_reason, admissibility_blocked_count
$r.evidence | Where-Object {$_.admissibility_reason} | Format-List page_id, text, nli_label, nli_confidence, accepted, contribution_role, admissibility_reason
```

Expected *for the previously shown Rio failure*: the `An_Inconvenient_Sequel...` candidate should have `accepted=False`, `admissibility_reason=SUBJECT_NOT_GROUNDED`, and `contribution_role=NOT_DECISIVE`. Overall verdict cannot be guaranteed before execution because other evidence may also be decisive.

## Controlled validation comparison

Run the same 60-claim validation sample and seed previously used for both top-k 5 and 10:

```powershell
uv run python -m scripts.evaluation.evaluate_fever_verification --split validation --max-examples 60 --seed 42 --top-k 5
uv run python -m scripts.evaluation.evaluate_fever_verification --split validation --max-examples 60 --seed 42 --top-k 10
```

Compare decision coverage, wrong decisive verdicts, macro F1, gold-set alignment, latency, and number of abstentions. The earlier diagnostic test set is not a pristine holdout and must not be used for tuning.

Ablation support for local experiments: `ClaimVerificationPipeline(..., enforce_subject_grounding=False)` restores the previous behavior. The default is `True` while this experiment is installed.

## Rollback

Stop FastAPI; restore original two files:

```powershell
Copy-Item "$backup\evidence_pipeline.py" ml\verification\evidence_pipeline.py -Force
Copy-Item "$backup\verification_schema.py" apps\api\schemas\verification.py -Force
```

The new module and test can remain unreferenced, or be deleted if no longer needed. This package does not touch Git, model artifacts, databases, or DVC-tracked data.
