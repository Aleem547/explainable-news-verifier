# Phase 13D.6 — Provisional Evidence Agreement and Conflict Analysis

## Scope

Pure, deterministic, offline/read-only analysis of a validated **Phase 13D.5** `ExternalNliReport`.

Input: `ExternalNliReport` obtained from the Phase 13D.5 audited, normalized, source-risk-assessed, calibrated NLI pipeline.

Output: immutable `ExternalAgreementReport` with all original passage IDs, publisher/source identities, article URLs, risk families, provisional agreement units, per-unit NLI stance, and warnings.

No article fetching, database changes, inference, truth classification, editorial-independence assertion, or corroboration verdict takes place in this phase.

## Key rules

1. Only **decisive**, threshold-passing entailment and contradiction labels contribute to agreement/conflict summaries; neutral or below-threshold NLI is inconclusive.
2. All passages belonging to a Phase 13D.4 dependency-risk family form **one** preliminary unit. A repeated `duplicate_group` spanning two families conservatively connects those families into **one** unit. The bridge is not proof of shared ownership; it prevents double-counting copied or near-duplicate reporting.
3. Two opposing decisive stances anywhere produce `UNRESOLVED_OPPOSING_EVIDENCE`; if both appear in a single unit, that unit is `MIXED` and flagged.
4. **Distinct** provisional risk units never prove two independent original investigations. Every output keeps `independence_status=NOT_ESTABLISHED`, `independent_corroboration_established=False`, and `independently_verified=False`.
5. Validation fails closed on invalid hashes, duplicate passage IDs, inconsistent document/version/source/publisher identities, non-finite or inconsistent NLI probabilities, contradictory NLI flags, invalid timestamps, premature verification claims, or invalid family indices.
6. Source and article URL details and the original NLI evidence are preserved. The returned report contains no truth probability, source trust score, or new network-derived metadata.

## Statuses

- `PROVISIONAL_SUPPORT_ONLY`: at least one decisive entailment, no decisive contradiction.
- `PROVISIONAL_REFUTE_ONLY`: at least one decisive contradiction, no decisive entailment.
- `UNRESOLVED_OPPOSING_EVIDENCE`: both decisive entailment and contradiction are present, in any combination of risk units.
- `INSUFFICIENT_DECISIVE_EVIDENCE`: only neutral/below-threshold predictions.

These are **evidence relation summaries**, *not* factual verdicts.

## Install and local tests

Place these files at their matching relative paths in the existing feature branch:

- `apps/api/services/external_evidence_agreement.py`
- `tests/unit/test_phase13d6_evidence_agreement.py`
- `scripts/phase13d6/run_local_agreement_tests.ps1`
- `docs/PHASE13D_6_AGREEMENT_CONFLICT_ANALYSIS.md`

On Windows PowerShell from the repository root:

```powershell
& .\scripts\phase13d6\run_local_agreement_tests.ps1

git diff --check
git status -sb
```

Expected: 38 new tests and 29 Phase 13D.5 regressions; no DB or live service required.

## Example Python integration

```python
from apps.api.services.external_evidence_agreement import analyze_external_evidence_agreement

# nli_report must be a validated Phase 13D.5 ExternalNliReport.
agreement = analyze_external_evidence_agreement(nli_report=nli_report)
print(agreement.evidence_status)
print(agreement.provisional_agreement_unit_count)
print(agreement.independent_corroboration_established)  # always False
```

## Limitations / follow-up

- NLI calibration from the original domain does not guarantee factual reliability on external news.
- Near-duplicate grouping may be conservative; overlap can reduce provisional agreement-unit counts.
- Unknown editorial relationships remain unknown. Provisional units must not be promoted to independence evidence automatically.
- **Phase 13D.7** must add explicitly conservative admission/decision rules, review policy for uncertain source independence, and robust evidence semantics; **13D.8** must test the entire pipeline, provenance, and regressions.

The new module has not been wired to any public API route, frontend, or AWS deployment.
