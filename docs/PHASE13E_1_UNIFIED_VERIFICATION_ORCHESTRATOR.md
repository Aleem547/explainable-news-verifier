# Phase 13E.1 — Unified Verification Orchestrator

## Status and scope

A **read-only Python service** unifies two *separate* evidence assessments:

1. The existing FEVER/Wikipedia-derived `run_verification` service, which enforces its own bounded CPU inference queue.
2. The existing Phase 13D pipeline for already-stored external article passages: PostgreSQL lexical retrieval → provenance / normalization / source-dependency audit → calibrated DeBERTa NLI → agreement → conservative decision.

**Phase 13E.1 does not add a public endpoint, article URL processing, claim extraction, or a production release.** Those belong to later Phase 13E steps. Nothing needs to be deployed to AWS/Vercel.

## API

`apps.api.services.unified_verification.orchestrate_unified_verification(session, *, claim, wikipedia_top_k=5, external_top_k=10, nli_threshold=0.90)`

- `session` is a caller-managed SQLAlchemy async session (use a read-only transaction where appropriate).
- The function never performs explicit writes or commits. Its dependencies are designed to read stored external snapshots.
- Input claim length 3–2,000 characters; Wikipedia 1–20 passages; external 2–20; NLI threshold 0.5–1.0.
- It runs Wikipedia first and then external retrieval/NLI **sequentially within one request**. Other concurrent requests use the pre-existing inference controls of each service; this is not a new global GPU/CPU semaphore.
- It returns an immutable `UnifiedVerificationReport` with separate `wikipedia` and `external` assessments, source references and an informational relationship code. There is **no merged factual truth verdict or overall probability**.

### External evidence handling

- At least two stored article *versions* are required before Phase 13D auditing/NLI can execute. Having two versions does not prove two independently sourced articles.
- Empty, single-document or unavailable external evidence returns a clear incomplete status. Wikipedia still returns if available.
- If a leg fails, the other leg remains accessible; exceptions are represented by short public reason codes, not raw errors that may leak claims or internal credentials.
- Phase 13D.7 recomputes agreement from the NLI report and refuses inconsistent counts, then 13E.1 verifies identities and that **independence remains `NOT_ESTABLISHED`**.
- External references preserve passage ID, article URL, publisher domain, version ID, NLI stance/score, and dependency/duplicate groups. These are evidence-analysis outputs, **not verified facts**.

### Relationship codes

`PROVISIONALLY_ALIGNED_SUPPORT`, `PROVISIONALLY_ALIGNED_REFUTATION`, `OPPOSING_CORPUS_FINDINGS`, `CONFLICT_OR_REVIEW_REQUIRED`, `PARTIAL_OR_INCONCLUSIVE`, `WIKIPEDIA_ONLY`, `EXTERNAL_ONLY`, `BOTH_UNAVAILABLE_OR_INSUFFICIENT`.

**These labels describe textual evidence agreement between corpora only.** Wikipedia and news sites are not assumed independent or infallible.

## Security and runtime constraints

- No user-submitted URL fetching, no new network clients, no external API subscriptions, no database migrations.
- The injected `*_runner` arguments are developer/test-only. **Never expose callable injection through an API request.**
- Uses existing model locks/queues. An already-running worker-thread model **cannot be forcibly terminated** by `asyncio` task cancellation; avoid promising hard inference timeouts. The production API must separately apply admission controls, authentication, quotas, disconnection handling, and conservative request limits (Phase 13E.7).
- All data from external articles remains provisional; Phase 13D does not certify affirmative editorial independence.
- PostgreSQL lexical search has no guaranteed production-scale latency until appropriate indexing and benchmarks are completed in Phase 13F.

## Tests on Windows

From `C:\Projects\explainable-news-verifier` on `feat/phase13-cross-source`:

```powershell
& .\scripts\phase13e1\run_local_unified_orchestrator_tests.ps1
& .\scripts\phase13e1\run_local_unified_orchestrator_tests.ps1 -IncludeRegressions
git diff --check
git status -sb
```

The **36 offline new tests** use fake model/retrieval outputs and do not touch a real database, network, or DeBERTa artifacts. Model-backed and PostgreSQL-backed integration remain to be tested in later phases. Phase 13D.5 model smoke and 13D.8 rollback-only database integration were previously validated locally and are not repeated by the new unit suite.

## Acceptance checklist

- [ ] 36 Phase 13E.1 tests pass locally
- [ ] Existing Phase 13D.7 and D.8 regression suites pass locally
- [ ] No staged secrets or unrelated submission ZIPs
- [ ] Commit only 4 Phase 13E.1 files on feature branch
- [ ] No merge to `main`, no AWS/Vercel modifications

Next: **13E.2 — Article URL Verification**.
