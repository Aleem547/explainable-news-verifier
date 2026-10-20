# Phase 13D.4 — Source dependency risks (not independent corroboration)

## Intent

Conservatively identify reporting relationships that make apparently distinct publisher URLs unsafe to treat as independent confirmation. This does not infer veracity, credibility or actual editorial independence. Cross-source NLI and genuine corroboration are later phases.

## Implementation

- `ml/verification/external_source_dependencies.py`: pure, bounded full-snapshot risk analysis building on the existing Phase 9E source-independence comparisons.
- `apps/api/services/external_source_independence.py`: read-only database coordinator that first performs Phase 13D.3 provenance validation against latest securely fetched snapshots. It never writes or commits.
- `tests/unit/test_phase13d4_source_independence.py`: synthetic reporting reuse, syndicated/source attribution, short-text exact matches, uncertainty, invalid metadata, and stability.
- `tests/unit/test_phase13d4_dependency_service.py`: mocked database coordinator and tamper/identity checks.
- `tests/integration/test_phase13d4_dependency_db.py`: two synthetic external publishers with identical full articles in a transaction, provenance audit + dependency grouping, rollback and absence check.
- `scripts/phase13d4/run_local_independence.ps1`: runs only against the already-running local development PostgreSQL container.

## Semantics and limits

- **Risk families** represent *not safe to count separately* based on evidence. They are NOT certified independent source groups.
- Identical full snapshots across different domains and same registered publisher are grouped. Matching explicitly reported common origins are grouped, but remain unverified third-party statements.
- Externally supplied `ReportedDependency` observations can express shared wire reports, shared primary sources or common publisher ownership. They require a recorded public HTTPS observation URL and timestamp, and are still only *reported* dependencies. Do not manufacture these records from a publisher name or a guessed owner.
- Strong near-duplicate similarity is **review-only**, not automatically unioned: changed numbers or negations can reverse claim meaning. Different nonmatching articles remain `UNDETERMINED` and are never considered proven independent.
- URL validation in this package is **identity validation**, not network fetch protection. This module makes no network calls.
- Max 20 full versions, 500,000 cumulative characters, 100 reported links. Candidate provenance is reaudited via Phase 13D.3. No new migrations.
- `independence_status` remains `NOT_ESTABLISHED` and `independent_corroboration_established` stays `False`. This is intentional until a separately justified decision policy in Phase 13D.7, supported by external evaluation in Phase 13F.
- This phase does not automatically query publisher ownership registries or infer syndicated origins. Observations need traceable manual or upstream attribution; no ownership assertions are made without explicit evidence.

## Local commands (Windows PowerShell)

```powershell
& .\.venv\Scripts\python.exe -m unittest discover -s tests/unit -p 'test_phase13d4*.py' -v
& .\.venv\Scripts\python.exe -m unittest discover -s tests/unit -p 'test_phase13d3_external_provenance.py' -v
& .\.venv\Scripts\python.exe -m unittest discover -s tests/unit -p 'test_phase13d2_evidence_normalization.py' -v
& .\scripts\phase13d4\run_local_independence.ps1
git diff --check
git status -sb
```

Do not deploy Phase 13D work to AWS/Vercel yet. Proceed to Phase **13D.5 — Cross-Source NLI Verification** after this checkpoint is validated and pushed to the development branch.
