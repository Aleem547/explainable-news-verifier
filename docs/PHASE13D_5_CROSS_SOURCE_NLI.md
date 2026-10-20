# Phase 13D.5 — NLI over audited external evidence

**Status:** local integration implementation; not deployed, not independently corroborated. Part of branch `feat/phase13-cross-source`.

## Purpose

Evaluate claim-to-passage textual relationships using the **existing** frozen, temperature-calibrated DeBERTa model. Reuse Phase 13D.1 external passage candidates, Phase 13D.2 normalization/duplicate groups, Phase 13D.3 provenance audit, and Phase 13D.4 dependency-risk grouping. No new model, paid API, schema migration, remote HTTP fetch, or database write.

## Interfaces

- `apps.api.services.external_evidence_nli.assess_external_evidence_nli(session, *, claim, candidates, predictor=None, assessed_at=None, nli_threshold=0.90)` — asynchronous read-only coordinator.
- It audits every candidate, builds normalized duplicate groups, audits full-snapshot source dependencies, calls the existing `apps.api.services.multisource._model_predict` through Starlette's worker pool (which already shares a CPU model/inference lock), and validates the returned distribution lengths and values.
- An optional **synchronous** `predictor.predict(claim, evidence_texts)` permits deterministic unit testing. Never run an untrusted model implementation in the API process.
- `build_external_nli_report(...)` only assembles validated input and model outputs; it never accesses a database or checkpoint.
- Every `ExternalNliPassage` retains passage ID, version ID, source ID, publisher domain, URL, original text and hash, retrieval time, relevance score, duplicate group, risk family, NLI label, all three probabilities, and a **passage-level** threshold flag.

## Safeguards and limits

- 2–20 distinct passages representing 2+ distinct stored document versions; up to 120k characters total, 20k per passage, claim 3–2,000 characters, aware assessment clock, NLI threshold 0.5–1.0 (default 0.90).
- Candidates marked previously evaluated or verified are rejected; originals and normalized groups must exactly correspond; successful fetch provenance must be present, assessed-at timestamps cannot precede fetch/retrieval, dependency families must cover exactly these version IDs.
- All scores must be finite, in range [0,1], sum to one. A neutral prediction is never marked threshold-passed. Any missing or invalid output rejects the *whole batch*; no silent partial evidence.
- **A threshold-passing entailment/contradiction does not establish decisive factual evidence.** Subject grounding, source independence, temporal relevance, corroboration aggregation, calibration on external news and claim-level uncertainty are still pending. The returned `independent_corroboration_established` and `independently_verified` flags are *always false*.
- A `risk_family` number identifies only a *possible dependency cluster*. Two separate families are **not proof** of independent journalism. No counts of independently supporting news sources should be inferred at this phase.

## Local tests

Run from `C:\Projects\explainable-news-verifier` on Windows:

```powershell
& .\scripts\phase13d5\run_local_nli_tests.ps1
```

Optional: to verify the **real** existing frozen checkpoint is installed and can predict on CPU without HTTP:

```powershell
& .\scripts\phase13d5\run_local_nli_tests.ps1 -IncludeModelSmoke
```

The optional smoke requires frozen model weights, matching calibration fingerprints, and the project's Torch/Transformers installation. It may take longer on CPU. It tests NLI execution **only**, not published-article accuracy. Don't use this smoke on AWS until deployment is explicitly approved.

Afterward, also rerun existing Phases 13D.2–D.4 tests as regressions. Keep all changes on the feature branch, not `main`.

## Still remaining

- **13D.6:** agreement/conflict analysis across source dependency risk groups, explicitly accounting for unknown relationships and contradictory evidence.
- **13D.7:** conservative corroboration decision engine with strong abstention behavior; never infer independent verification from number of domains.
- **13D.8:** integration tests with the actual checkpoint, stored article evidence, end-to-end validations, and performance measurements.
