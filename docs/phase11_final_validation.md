# Phase 11 — Development Validation & Closeout Report

**Project:** Explainable News Verifier  
**Report date:** 2026-10-16  
**Environment:** Local Windows/PowerShell development environment; Docker Compose; FastAPI; PostgreSQL; Redis; Qdrant; FEVER-derived Wikipedia sentence corpus  
**Validation scope:** Phase 11 development tests, retrieval optimization, evidence-processing safeguards, API checks, and isolated rollback exercise  
**Disposition:** **Scoped development validation PASSED. Production cutover NOT CERTIFIED.**

## 1. Executive summary

Phase 11's **observed local development checks** passed for the selected unit-test modules, three running API instances, evidence retrieval equivalence, and isolated rollback recovery. Across four pytest invocations, **93 test executions passed with zero recorded failures**. The API readiness endpoint returned `ready: true` and `ok` for PostgreSQL, Redis, and Qdrant on all three tested ports.

The results establish evidence for the *tested conditions only*. They do not establish general fact-checking accuracy, comprehensive cross-source corroboration, sustained production reliability, recovery time objectives, or production deployment readiness. An intermittent DuckDB Parquet read/memory-allocation failure remains open.

## 2. Test evidence

The following results were observed in terminal outputs shared during the Phase 11 closeout workflow.

| Test run | Test modules | Observed result |
|---|---|---|
| Evidence screening and entity relevance | `tests/unit/test_evidence_quality.py`; `tests/unit/test_entity_relevance.py` | **23 passed** in 32.97 s |
| Core verification, aggregation, admissibility | `tests/unit/test_evidence_verification_pipeline.py`; `tests/unit/test_evidence_aggregation.py`; `tests/unit/test_decisive_admissibility.py` | **48 passed** in 30.53 s |
| Verification API and stage profiling | `tests/unit/test_verification_api.py`; `tests/unit/test_phase11c5_stage_timing.py` | **13 passed, 1 warning** in 29.61 s |
| Request queue and graceful shutdown | `tests/unit/test_phase11b_queue.py`; `tests/unit/test_phase11b_shutdown.py` | **9 passed** in 2.15 s |
| **Total across runs** | **9 module paths** | **93 passing test executions; 0 failed** |

The total counts executions across separate invocations, rather than asserting that all 93 tests are unique or that the entire repository test suite ran. The warning in the API/profiling run was a Starlette `TestClient` deprecation warning concerning `httpx`; it did not fail the tests.

Tests ran in a Docker Compose API image with a read-only bind mount of the repository and an existing read-only pytest-dependencies mount; the test commands did not rebuild images or intentionally alter project source.

## 3. Evidence-screening and entity safeguards reviewed

Code inspection and focused tests covered:

- Canonicalization of case, punctuation/FEVER markup, and whitespace.
- Disambiguation-page handling where a claim is not itself about disambiguation.
- Conservative entity-title mismatch screening for location-related claims.
- Duplicate evidence IDs, duplicate canonical text, and conservative same-page near-duplicate detection.
- Rank-preserving selection of the first `top_k` candidates that pass quality filters, with excluded/unused-candidate accounting.
- NLI-based entailment/contradiction/neutral assessment, admissibility decisions, and aggregation of accepted evidence.

**Interpretation:** Evidence screening is a filtering/selection stage, **not a proof of source truthfulness** and not an independent semantic reranker. Passing unit tests support the specified safeguards but do not prove their generalization to arbitrary claims or languages.

## 4. Retrieval optimization and corpus checks

The recorded prototype and checks reported:

| Measure | Observed result |
|---|---|
| Corpus record count | **4,204,186** |
| Sorted Parquet prototype size | Approximately **2.28 GiB** (script reported `2.28` using `1024**3`) |
| Original-versus-sorted full-corpus fingerprint | **Match: True** |
| Selected-batch retrieved-evidence equivalence | **Exact match: True** in recorded batch checks |
| Eight-batch total, original | **14,842.91 ms** |
| Eight-batch total, optimized | **2,867.97 ms** |
| Eight-batch observed speedup | **5.18×** |

The speedup is an **observed local benchmark for the tested batches**, not a guaranteed end-to-end API or production throughput improvement. Earlier tests showed verdict sensitivity to `top_k`, including insufficient evidence at smaller depths and refuting evidence at greater depth for a sample false Eiffel Tower claim.

## 5. API readiness and security checks

A final local readiness sweep reported:

| Instance | Local port | `ready` | PostgreSQL | Redis | Qdrant |
|---|---:|---|---|---|---|
| Original API | 8001 | `true` | `ok` | `ok` | `ok` |
| Optimized API | 8002 | `true` | `ok` | `ok` | `ok` |
| Isolated rollback API | 8003 | `true` | `ok` | `ok` | `ok` |

Separate recorded checks showed missing and invalid service tokens returned **HTTP 401** for both original and optimized API instances. Authenticated example requests returned **HTTP 200**. These observations do not replace security review, credential rotation, penetration testing, or production authentication validation.

## 6. Verification behavior and rollback exercise

The scoped claim-level checks included:

- **True example:** “The Eiffel Tower is located in Paris, France.” At `top_k=5`, the recorded result was `SUPPORTING_EVIDENCE` with accepted entailment evidence.
- **False example:** “The Eiffel Tower is located in Berlin, Germany.” At `top_k=5`, the recorded result was `REFUTING_EVIDENCE` with accepted contradiction evidence; at smaller `top_k` settings, some results remained `INSUFFICIENT_EVIDENCE`.
- **Rollback parity:** For the single documented Berlin claim, original and reconstructed rollback APIs produced equivalent selected response fields: verdict, retrieved/assessed counts, and evidence role/acceptance details.

The isolated rollback exercise included: recovering source files from a running original container, checking SHA-256 source equivalence, rebuilding a rollback candidate image, verifying its configured image identity, starting an isolated rollback API, checking dependency readiness, executing authenticated inference, restarting the rollback container, and checking post-restart recovery. **These checks passed in the recorded test environment.**

**Scope limit:** This was not a production failover or real-traffic cutover. Neither a production recovery-time objective (RTO) nor a production recovery-point objective (RPO) has been certified. The original API was preserved during the exercise.

## 7. Open risks and limitations

1. **DuckDB memory-allocation failure — OPEN.** A verification run at `top_k=3` previously failed while reading `/app/data/processed/fever/wiki_sentences.parquet` with `duckdb.IOException: Cannot allocate memory`. Subsequent readiness checks passed, but readiness does not demonstrate that the intermittent read failure is resolved. Investigate under controlled memory limits and representative concurrent requests; monitor memory, DuckDB file access, and workload behavior before declaring this fixed.
2. **Quality and robustness — NOT CERTIFIED.** The recorded claim checks are useful regression samples, not benchmark-quality estimates of classification accuracy, calibration, evidence recall, geographic/entity coverage, or cross-source independence.
3. **Production operations — NOT CERTIFIED.** Capacity, stress/soak behavior, concurrency under load, disaster recovery, observability, deployment hardening, and externally measurable RTO/RPO require independent validation.
4. **Dependency warning — NONBLOCKING FOR TESTS.** The observed Starlette `TestClient`/`httpx` deprecation warning should be tracked and resolved through a controlled dependency update.
5. **Untracked local artifacts — REVIEW BEFORE STAGING.** The local working directory contains untracked test backups, benchmark results, and reference ZIP files. They were not part of the latest validated tracked commit and should not be added via `git add .` without classification and secret/size checks.

## 8. Git provenance at time of final screenshot

- Branch: `main`.
- Latest observed commit: `8850d0d` — `docs: add rollback recovery validation and optimized compose override`.
- `HEAD`, `main`, and `origin/main` were displayed at this commit.
- `git diff --check` produced no diagnostics.
- Remaining changes listed by `git status --short` were **untracked (`??`)** files, not changes to already tracked files.

This report is a **new documentation artifact** and needs a separate, narrowly scoped commit if included in the repository. It does not claim that this report itself has already been pushed.

## 9. Closeout decision and acceptance boundaries

**Accepted as complete for Phase 11 scoped local development validation:** the recorded 93 passing unit-test executions, sampled retrieval and corpus equivalence checks, the observed local eight-batch retrieval performance comparison, security response checks, three healthy development API instances, and isolated rollback/restart behavior.

**Not accepted as demonstrated:** production cutover readiness; absence of memory errors; general claim-verification correctness; real-world multi-source corroboration; or tested production recovery SLOs.

**Next engineering work:** isolate and remediate the DuckDB memory issue; establish repeatable full-pipeline quality evaluation over a labeled dataset; add representative load and concurrency stress tests; and conduct a separate production-like rollback/cutover rehearsal with measured service objectives.

---

*Prepared from the user-provided PowerShell/Docker/Git test outputs and screenshots in the Phase 11 workflow. It is an observation-based closeout record, not an independent audit of source files or a production certification.*
