# Phase 9G: restricted multi-source integration and reliability checks

**Status:** candidate implementation. Do not mark Phase 9G validated until Windows
Ruff, mypy, pytest, the PostgreSQL rollback smoke test and API security checks pass.

## Scope

This release composes the existing Phase 9B–9F layers without replacing the
Phase 8 `/api/v1/verify` endpoint or pretending that news discovery snippets
are full evidence:

1. `/api/v1/multisource/discover` (operator-only) uses allowlisted NewsAPI/Google
   Fact Check provider endpoints, registers publisher + discovered documents,
   and stores **metadata only** in Phase 9C tables.
2. The **existing** `ingest_supplied_content` function accepts authorized,
   externally supplied full text, creates immutable document versions, passage
   offsets, successful fetch observations, and indexing-outbox events. This
   release does not automate article retrieval or validate content licenses.
3. `/api/v1/multisource/assess` (operator-only) accepts IDs of **already stored
   passages** from at least two document snapshots. It verifies both text
   hashes and span offsets before loading the frozen calibrated CPU NLI model.
4. On the same SQL transaction it records temporal/source context (9D),
   provisional evidence families and reuse pairs (9E), and cross-source
   passage findings (9F). It returns exact document/passage IDs, publisher URL,
   subject-grounding status, temporal relation, and diagnostics.
5. Database writes roll back on failure; no client-supplied NLI outcomes are
   trusted in the public request. A read-only listing script helps an operator
   identify existing captured passage IDs.

**No new Alembic migration is needed in Phase 9G.** The current revision is
`9f52a1c840d6`. Phase 9A–9F tables already contain the required audit records.

## Unverified claims and known limitations

- Different publisher URLs or provisional evidence families **do not prove
  independent reporting**. Output always says `NOT_ESTABLISHED`.
- NLI scores are pair-level, not claim-level probabilities. Phase 9G has **no
  validated real-world cross-source accuracy estimate**.
- Subject grounding checks only an initial named subject literally present in
  the passage. It is a deliberately conservative heuristic, **not complete
  entity linking**. Missing source fetch provenance blocks decisive votes.
- Every assessment should have a claim-reference time when freshness matters.
  Missing publication timestamps remain unknown, never automatically false.
- NLI model-run database linkage is not yet fully registered and is warned
  about as `NLI_MODEL_PROVENANCE_INCOMPLETE`.
- The API does **not** fetch arbitrary article URLs, scrape paywalls, or index
  the Phase 9C outbox into Qdrant. Discovery without authorized full-text
  ingestion does not provide passages for verification.
- There is no full multi-hop claim decomposition or external-source ranking in
  this release. Selection of stored passages is operator-controlled and can
  introduce selection bias. Operator-entered claim-reference times require care.
- An internal static access token is a **staging control**, not a replacement
  for production OAuth/RBAC, short-lived credentials, TLS, gateway rate limits,
  multi-tenant access control, retention policy, and audit monitoring.

## Installation (Windows PowerShell)

1. Back up `apps\api\main.py` before extracting the ZIP into
   `C:\Projects\explainable-news-verifier`.
2. From the project root:

```powershell
uv run ruff check . --fix
uv run ruff format .
uv run ruff check .
uv run ruff format --check .
uv run mypy apps ml scripts
uv run pytest
uv run python -m scripts.multisource.check_phase9g
uv run alembic current
uv run alembic heads
```

Expected Alembic output from **both** commands: `9f52a1c840d6 (head)`.
The new unit tests are in `tests/unit/test_phase9g_*.py`. Earlier there were
320 passing tests; if all 32 new tests are collected unchanged, expect **352**.

3. On your **development-only** PostgreSQL database, after backing up any
   important data, run the rollback-only end-to-end integration test:

```powershell
uv run python -m scripts.multisource.check_phase9g_database
```

This test creates synthetic NewsAPI-shaped discovery metadata, ingests
explicitly authorized synthetic content, stores snapshots and passages, runs
9D/9E/9F with a **deterministic fake NLI model**, asserts the audit outcome,
then rolls back the entire test transaction. It does NOT call NewsAPI or the
actual transformer. Real checkpoint evaluation requires separate testing.

## Optional local API enablement

The endpoint is **disabled by default**. Use it only on a local/staging server
behind a trusted boundary. Generate a random secret without hardcoding one in
Python or committing one to Git:

```powershell
$env:ENABLE_EXPERIMENTAL_MULTISOURCE_API = "1"
$env:MULTISOURCE_INTERNAL_TOKEN = uv run python -c "import secrets; print(secrets.token_urlsafe(48))"
uv run uvicorn apps.api.main:app --host 127.0.0.1 --port 8000
```

From a **second PowerShell session**, supply the same token securely through
that session's environment (do not paste it in shared terminal screenshots).
The `X-Internal-Token` header is mandatory. Without both flag and a secret of
at least 32 characters, both endpoints return HTTP 503.

To get stored passage IDs without printing their content:

```powershell
uv run python -m scripts.multisource.list_passages
```

Example assessment **only after two genuine stored passages are available**:

```powershell
$body = @{
    claim = "The Eiffel Tower is in Paris"
    passage_ids = @("<UUID-of-passage-1>", "<UUID-of-passage-2>")
    reference_at = "2026-10-08T12:00:00Z"
    max_age_days = 365
} | ConvertTo-Json
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/multisource/assess" `
    -Method Post -ContentType "application/json" -Body $body `
    -Headers @{ "X-Internal-Token" = $env:MULTISOURCE_INTERNAL_TOKEN }
```

If the NLI model was trained on FEVER, its confidence and provenance must be
re-evaluated before reliance on current news. Observe false positives and
abstentions and never treat a returned support signal as a final truth label.

The opt-in discovery route also requires separately configured `NEWSAPI_KEY`
and/or `GOOGLE_FACTCHECK_API_KEY`; there is no need to purchase keys just to
run Phase 9G offline tests. No web searches run without keys and opt-in.

## Deployment gate

The goal remains a publicly deployed startup-grade product, but these tests
validate a **staging integration boundary**, not production readiness. Before
public launch: implement authenticated users with RBAC, isolate tenants,
rate-limit/queue ML workloads, implement authorized full-text acquisition and
outbox indexing, build a trustworthy independent-source provenance policy,
monitor model drift, calibrate claim-level decisions on a *new untouched*
evaluation set, audit licensing/PII, add logging and metrics without secrets,
and establish CI/CD plus rollback and disaster recovery.

## Git policy

Do not commit or push until you have confirmed the Windows checks, integration
smoke test, and final file review. After confirmation, use a selective stage;
exclude reference and implementation ZIPs, `.env`, model weights, and generated
reports. Phase 9G adds no database migration.
