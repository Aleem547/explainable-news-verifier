# Phase 13E.5 — Bounded Multi-Claim Verification

**Scope:** local development branch `feat/phase13-cross-source`. This phase adds an in-memory service, not a public API. It does not write databases, fetch articles, alter model artifacts, or deploy to AWS/Vercel.

## Purpose

Combine Phase 13E.4's exact-span claim candidates with Phase 13E.1's unified Wikipedia + stored external evidence verification. Each claim receives its **own** separate-corpus verification report, source references, status and uncertainty; the article is never given a binary truth label or a fabricated accuracy percentage.

## Files

- `apps/api/services/article_multi_claim_verification.py`: typed policy, immutable per-claim/report structures, validated sequential orchestrator.
- `tests/unit/test_phase13e5_multi_claim_verification.py`: offline isolated tests with a controlled fake unified runner.
- `scripts/phase13e5/run_local_multi_claim_tests.ps1`: Windows `.venv` runner, optional prior-phase regression suites.
- This documentation.

## Local test procedure

From `C:\Projects\explainable-news-verifier` in Windows PowerShell:

```powershell
& .\scripts\phase13e5\run_local_multi_claim_tests.ps1
& .\scripts\phase13e5\run_local_multi_claim_tests.ps1 -IncludeRegressions
git diff --check
git status -sb
```

Expected: **57 new unit tests** and, with `-IncludeRegressions`, an additional **170 previous unit tests** (13E.4 = 46, 13E.3 = 49, 13E.2 = 39, 13E.1 = 36), for **227 selected tests**. The Windows run is required to verify the complete repository; the review ZIP is only a partial snapshot.

## API for trusted internal callers

```python
from apps.api.services.article_multi_claim_verification import (
    MultiClaimPolicy,
    verify_article_claims,
)

# Inside an authenticated, quota-enforced, trusted API/service layer:
result = await verify_article_claims(
    session,
    prepared=trusted_prepared_article,
    policy=MultiClaimPolicy(max_verifications=8),
)
```

`trusted_prepared_article` must be returned by Phase 13E.2 or 13E.3. The service recomputes Phase 13E.4 claim candidates from the immutable prepared article and rejects any caller-supplied candidate report that does not match; use `extraction_policy` if the candidates were created with a nondefault extraction policy. Do not construct article provenance from untrusted API JSON or pass a user-controlled `unified_runner`.

## Rules and failure behavior

1. **Sequential, bounded**: default maximum 8 claim verifications; hard policy range 1–20, no uncontrolled concurrency or parallel model loading.
2. **No implicit source trust**: the source article stays `USER_SUPPLIED_ONLY` or `FETCHED_ARTICLE_UNVERIFIED`. It is **not added as independent evidence**. External findings refer only to already stored, audited evidence.
3. **Exact source grounding**: every result retains candidate ID, exact text, offset and duplicate locations. Recompute candidate metadata to reject report/offset/hash tampering before any model work.
4. **Fail one, continue**: per-claim exceptions become sanitized `FAILED` statuses without leaking exception text or exposing partial invalid findings; unassessed sources become `UNAVAILABLE`.
5. **Explicit budget skips**: remaining candidates become `SKIPPED_LIMIT`, never silently omitted. A claim extractor may also report candidates omitted by its own separate limit.
6. **No false corroboration**: every result preserves the Wikipedia and external findings separately. Editorial independence remains `NOT_ESTABLISHED`, not proven, so this phase never emits an article-wide factual verdict.
7. **Cancellation and resource limits**: cancellation propagates. Python task cancellation cannot forcibly stop a CPU inference thread already executing within the upstream verifier; the server must enforce authentication, per-user quotas, queue limits and infrastructure capacity.
8. **No auto-persistence**: no article content is written by this module, but the returned in-memory object contains source text and should be subject to existing privacy and retention policies.

## Test limitations and next phases

The tests use deterministic injected unified reports, **not live inference or retrieval**. Prior Phase 13D.5 separately smoke-tested the real frozen DeBERTa model. Phase 13E.6 will add article-level reporting (still not a truth score), 13E.7 the authenticated API/frontend, and 13E.8 end-to-end local deployment tests. Phase 13F covers quantitative evaluation, security and performance.
