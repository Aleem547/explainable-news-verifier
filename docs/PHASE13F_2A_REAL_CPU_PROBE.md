# Phase 13F.2A — Real CPU cancellation and admission smoke probe

This is an opt-in **local-only** test. It imports the same frozen CPU NLI model as `tests/integration/test_phase13d5_real_model_smoke.py`. It patches the article workflow at the *route* layer, deliberately bypassing PostgreSQL, browser authentication, networking, and external retrieval. Consequently it tests route admission and cancellation with a real model thread, **not** end-to-end production verification.

## Install and run

Extract this ZIP into the existing repository root, keeping `tests/integration/test_phase13f2a_real_cpu_admission.py`. No application source files are replaced. In Windows PowerShell:

```powershell
cd C:\Projects\explainable-news-verifier
Test-Path .\tests\integration\test_phase13f2a_real_cpu_admission.py
uv run --frozen python -m unittest discover -s tests/integration -p "test_phase13f2a_real_cpu_admission.py" -v
```

## What a pass proves

- A real CPU NLI inference runs and returns normalized probabilities.
- After the article coroutine is cancelled, the route does not free its one-process admission semaphore before the background model thread ends.
- An overlapping request is rejected with HTTP 429; once the worker completes, a new request can be accepted.
- Best-effort Windows process working-set memory is printed; these measurements concern **this test process**, not the live AWS container.

## Important limitations

The test does not measure meaningful sustained throughput, fully exercised HTTP disconnect behavior, PostgreSQL session handling, or cross-process contention. A per-process `asyncio.Semaphore(1)` is **not** a global lock across multiple Uvicorn/Gunicorn processes. Real-world production limits and the AWS 4 GiB API memory ceiling remain to be checked before rollout.

Do not push anything to `main` or deploy to AWS/Vercel as part of this probe. Do not install extra packages or download new models. The model can take some time to initialize in a fresh process, and CPU/RAM use can increase temporarily. Close other heavy local workloads before running it.
