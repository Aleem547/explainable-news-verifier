# Phase 13E.8 — End-to-End Validation

## Scope and evidence boundaries

This phase validates the **pasted-article preview** and the existing claim verifier before a Phase 13F release decision. URL submission is intentionally unsupported. In the pilot, at most **one claim is model-assessed per article request**; additional extracted candidates are `SKIPPED_LIMIT`. Evidence from Wikipedia is not independently sourced. External stored evidence is *not* certified editorially independent. **No overall article truth verdict or truth probability is available.**

The tests are intentionally split into **isolated offline** contracts, **unauthenticated loopback** HTTP guards, and a **manual authenticated model-backed** flow. Passing one category does not imply the others have passed.

## New files

- `tests/unit/test_phase13e8_article_release.py`: offline static source boundary checks, real article preparation/extraction/reporting with **injected synthetic/failing model**, and isolated HTTP validation with overridden dependencies. The isolated HTTP tests do **not** demonstrate actual authentication enforcement.
- `tests/integration/test_phase13e8_local_guards.py`: optional **loopback-only**, no-credential live GET/POST tests against `127.0.0.1:8001` and `127.0.0.1:3000`. Does not submit authorized inference or send cookies/tokens.
- `scripts/phase13e8/run_local_end_to_end_tests.ps1`: Phase 13E.8 offline checks, optional Phase 13E.1–13E.7 regressions, TypeScript, live guard checks and Git whitespace check.

## Windows execution

Run from the repository root, branch `feat/phase13-cross-source`:

```powershell
& .\scripts\phase13e8\run_local_end_to_end_tests.ps1
& .\scripts\phase13e8\run_local_end_to_end_tests.ps1 -IncludeRegressions -IncludeFrontendTypecheck
```

**Optional, with both localhost services running**:

```powershell
& .\scripts\phase13e8\run_local_end_to_end_tests.ps1 -IncludeLiveGuards
```

The optional HTTP checks never follow redirects, never use a proxy, accept only `http://localhost` or `http://127.0.0.1` URLs and do not send secrets. With the feature enabled on the local web server, an anonymous POST should return `401`; `503` may indicate the feature is disabled and therefore does **not** establish that sign-in was enforced. A cross-site POST should return `403` when enabled. A `405 Allow: POST` response to GET confirms route registration, not authorized functionality.

## Manually exercised model-backed local smoke cases (observed during Phase 13E.7)

- Pasted synthetic Eiffel Tower article: 3 candidate claims, 1 assessed, 2 skipped; first claim's Wikipedia finding showed supporting evidence; external evidence insufficient and no independence claim.
- Existing single-claim verifier: "The Eiffel Tower is located in London." produced `REFUTING_EVIDENCE` with evidence excerpt identifying Paris (1 accepted refuting page). These are two **illustrative local smoke cases**, not representative accuracy metrics.

## Required local release checks

| Area | Minimum condition |
|---|---|
| Existing single-claim workflow | Authenticated `/verify` still works in UI; evidence can be expanded and filtered; no client token displayed |
| Article preview feature flag | Disabled without explicit opt-in; enabled locally only, not on AWS/Vercel |
| Session protection | Anonymous web POST denied (`401` when enabled) |
| Service authorization | Backend anonymous POST denied (`401`/`403`) |
| Cross-origin control | Web POST from an untrusted Origin denied (`403` when enabled) |
| Input validation | URL mode/extra publisher fields, short text and overlong UTF-8 rejected |
| Concurrency | One processing slot; excess requests return bounded busy status (`429`) |
| Report integrity | Exact claim spans and IDs; sum of execution statuses equals candidate count; no truth percentage or invented independence |
| Failure isolation | Failed first claim is sanitized; later claims explicitly skipped under one-claim budget |
| Existing verification regression | Run Phase 13E.1–13E.7 test suites and TypeScript check |
| Operational safety | No cloud commands, no volume deletion, no secrets in logs; no production toggle |

## Limitations and release gates

The automated Phase 13E.8 package does not install a browser automation framework, emulate the user's Google OAuth session, or run a large model-backed accuracy benchmark. The frontend authenticated model-backed path has been manually smoke-tested in the existing local session, but automated browser/auth testing and broader datasets remain additional release evidence if this preview is to be offered widely. CPU inference can exceed normal frontend timeouts. Model-backend concurrency is partly controlled per process; scaling horizontally requires an additional shared admission/quota design.

Do not merge/deploy solely because the offline tests pass. Before any release: verify the full test output, inspect diffs for sensitive changes, confirm effective environment and security boundaries, perform an authenticated live smoke test, update project documentation truthfully, and obtain a clean Phase 13F release decision. Avoid running `docker compose down -v`, Docker pruning, or any AWS/Vercel config change for this phase.
