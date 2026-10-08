# Phase 7E — Retrieval + Calibrated NLI Integration

Copy the contents of this ZIP to the **root** of your existing `C:\Projects\explainable-news-verifier` project. These are five new Python files; they do not replace the existing retrieval pipeline, API route, or classifier.

## Windows PowerShell

```powershell
cd C:\Projects\explainable-news-verifier
Expand-Archive -Path .\phase7e_integration.zip -DestinationPath . -Force
uv run ruff check . --fix
uv run ruff format .
uv run ruff check .
uv run mypy apps ml scripts
uv run pytest
uv run python -m scripts.verification.run_claim_verification --claim "The Eiffel Tower is located in Paris" --top-k 5
```

If you download the ZIP to the standard Downloads folder, change `-Path` accordingly, e.g. `$HOME\Downloads\phase7e_integration.zip`.

## Artifacts required on disk

- Existing FEVER retrieval artifacts and ranking models; the existing `apps.api.services.retrieval.get_retrieval_pipeline` must already work.
- `models/nli_verifier/nli-deberta-v3-small_fever_nli_30k/` with `config.json`, tokenizer, and model weights.
- `data/metadata/fever_nli_calibration_config.json` with `model_fingerprints`, label order, and the frozen validation-fitted temperature.

The inference adapter checks the checkpoint's SHA-256 fingerprints before use; it will fail closed on a mismatch. First startup may take time to hash weights and load retrieval/NLI models.

## Interpretation

Predictions are evidence-pair NLI results on the FEVER Wikipedia snapshot; retrieved evidence is not necessarily sufficient or current. `SUPPORTING_EVIDENCE` and `REFUTING_EVIDENCE` are provisional, not real-world `true`/`false` decisions. The 0.90 acceptance cutoff was fixed on validation, but its previously observed coverage/accuracy need not transfer to retrieved evidence. Conflicting or low-confidence results are not silently collapsed into a binary verdict.

No API route is added in this part; the dedicated verification API is planned for Phase 7F.
