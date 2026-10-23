# Phase 13F.2A — cancellation and admission hardening

## Source

Based on the Phase 13F.1 user-provided static audit archive as of `feat/phase13-cross-source` at user-reported commit `fdb1765` (22 October 2026).

## Production bug

Article route held a per-process `asyncio.Semaphore(1)`, but request cancellation propagated directly through `verify_pasted_article` into an `asyncio.to_thread` Wikipedia CPU inference await. Cancelling the coroutine does not stop the Python thread. The `finally` block released the route semaphore while the thread was still active, admitting overlapping work.

## Scope of patch

`apps/api/routes/article_verification.py`:

- Create a tracked task for the **entire** async article workflow (including any database session work).
- Shield it from the ASGI request task's cancellation.
- If the outer request is cancelled, wait for the workflow to finish **before** allowing the dependency-scoped database session to close and releasing the admission slot; tolerate repeated cancellation and consume background exceptions without echoing user content.
- Keep existing feature flag, request limits, immediate 429-on-busy, error mapping, and no-store output unchanged.

No new runtime dependency; no production feature flag or deployment change.

## Test commands (Windows PowerShell, project root)

```powershell
uv run --frozen python -m pytest tests/unit/test_phase13f2a_cancellation_admission.py tests/unit/test_phase13f2a_cancellation_followups.py -q
uv run --frozen python -m pytest tests/unit/test_phase13e7_article_integration.py -q
```

Tests are deterministic synthetic thread tests. In a *partial archive* with stubs for omitted auth/DB modules, 3 targeted tests passed, plus 7 existing router/workflow tests. They were not run against the user's complete Windows repository or real ML model in this environment.

## Limitations and remaining gates

1. Cancellation does not stop a running CPU inference thread; it waits for completion and retains admission. A stuck model could keep this worker slot busy until restart. This approach intentionally favors concurrency/memory safety over fast release, without claiming an inference wall-clock timeout.
2. Semaphore is **per process**. Validate Uvicorn/Gunicorn worker count (and container replicas) before release; multiple workers may admit more than one CPU request in total. Model-level global throttling and Redis quotas must still be verified.
3. Validate actual end-to-end ASGI disconnect, timeout, real model execution, database-session lifetime, host RSS/cgroup memory, and existing `/verify` route before production.
4. Do not merge this branch into `main`, deploy to AWS/Vercel, or enable new flags until Phase 13F.3 release validation gates pass.

## Rollback

Restore the original file from Git on the **feature branch only**, after inspecting any other local modifications, or restore your separately saved route backup. Do not reset unrelated files.
