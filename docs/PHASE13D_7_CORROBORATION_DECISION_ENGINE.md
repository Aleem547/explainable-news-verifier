# Phase 13D.7 — Conservative external-evidence decision engine

## Scope

**Local-only and read-only**. The component consumes a Phase 13D.5 `ExternalNliReport` together with the exact corresponding Phase 13D.6 `ExternalAgreementReport`. It does not fetch articles, write to PostgreSQL, call DeBERTa, change the API, or update production.

Function:

```python
from apps.api.services.external_corroboration_decision import decide_external_corroboration

decision = decide_external_corroboration(
    nli_report=nli_report,
    agreement_report=agreement_report,
)
```

It **recomputes the complete Phase 13D.6 agreement** from the supplied Phase 13D.5 NLI report and rejects mismatched, forged or tampered counts, warnings, claims, timestamps and evidence. The upstream report validator also checks evidence hashes, grouping, and model scores. The results are immutable dataclasses with deterministic explanation codes and all relevant passage UUIDs.

## Decision semantics

| `evidence_verdict` | Meaning |
|---|---|
| `PROVISIONAL_SUPPORT` | At least one decisive NLI support stance and no decisive contradiction |
| `PROVISIONAL_REFUTATION` | At least one decisive NLI contradiction and no decisive support |
| `CONFLICTING_EVIDENCE` | Both decisive support and contradiction, including conflict within a risk unit |
| `INSUFFICIENT_EVIDENCE` | No decisive NLI stance under the existing threshold |

**A critical limitation:** Phase 13D.4's dependency-risk families are *not* verified editorial independence. Even if many different publishers or risk families agree, Phase 13D.7 cannot legitimately claim independent corroboration. Therefore, until a **separately auditable affirmative independence determination** exists, every output has:

- `independence_status = "NOT_ESTABLISHED"`
- `independently_verified = False`
- `independent_corroboration_established = False`

Do **not** label `PROVISIONAL_SUPPORT` as `CORROBORATED`, `TRUE`, or an independently established factual claim. Do not treat NLI scores as calibrated truth probabilities: the existing model has not been calibrated for independent external-news verification.

The `source_risk_family_count` and `provisional_unit_count` represent *upper-bound grouping heuristics for counting*, not an independence certificate. Duplicates shared across risk families bridge the units and cannot boost any count.

## Validation and caveats

- Entire report contracts must be internally consistent or the decision fails closed.
- Requires at least two external passages from distinct immutable article versions (enforced by upstream NLI contract).
- Evidence/provenance integrity is checked upstream, but the decision cannot prove that a publisher's factual claims are correct, that two outlets worked independently, or that neither relied on a common unobserved source.
- No API/frontend output change yet. **Phase 13D.8** must exercise the orchestrated workflow, failure handling and regressions; Phase 13E can expose careful evidence-alignment terminology in the UI.
- Producing actual independent corroboration in future requires a separately reviewed/validated affirmative independence signal linked to evidence and source identity, not a user-supplied boolean or an automatic assumption from different domains.

## Test locally (Windows PowerShell)

```powershell
& .\scripts\phase13d7\run_local_corroboration_tests.ps1

git diff --check
git status -sb
```

The tests use synthetic evidence only and require no network, database, model weights, paid API, or AWS changes. No files should be committed to `main` or deployed to AWS while Phase 13D is in development.
