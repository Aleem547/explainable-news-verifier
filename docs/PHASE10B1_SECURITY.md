# Phase 10B.1 — Internal inference ingress security

## What is implemented

- **Private FastAPI service authentication** for POST `/api/v1/verify`, `/api/v1/retrieval`, `/api/v1/classification`, and both `/api/v1/multisource/*` routes in non-development environments. The existing multi-source operator token is **still required** for its diagnostic routes.
- **Redis atomic shared cost quota**, using one INCR+EXPIRE Lua operation with 60-second expiry. This is a *service-wide* quota, **not per-user rate limiting**.
- **16 KiB default request cap** on all `/api/v1/*` POSTs, applied to actual received bytes, even when Content-Length is absent/incorrect; JSON-only inference requests.
- **Same-origin architecture**: Next.js calls FastAPI only server-side, transmitting `X-Service-Token` from the server environment. No credentials go into browser code.
- Existing `/api/v1/health` and `/api/v1/ready` remain accessible to health probes. CORS is disabled on production FastAPI.

## Configuration — environment variables (never commit secrets)

FastAPI server (staging/production):

```dotenv
APP_ENV=production
INTERNAL_API_TOKEN=<same-random-secret-at-both-services-at-least-32-characters>
INFERENCE_REQUESTS_PER_MINUTE=30
INFERENCE_MAX_BODY_BYTES=16384
```

Next.js server (staging/production):

```dotenv
API_BASE_URL=https://<private-or-restricted-fastapi-origin>
INTERNAL_API_TOKEN=<same-secret-as-fastapi>
```

Use your hosting provider's secret manager. **Never** prefix the credential with `NEXT_PUBLIC_`. Restrict FastAPI ingress at the network level and use TLS between services wherever the network is not independently trusted.

Generate a strong random credential on Windows (copy output directly to your secret manager, not terminal logs or source):

```powershell
uv run python -c "import secrets; print(secrets.token_urlsafe(48))"
```

## Security boundaries and what is still disabled

This phase **does not** implement individual user identity, login, cookie sessions, CSRF defense, or a shared per-user quota. **Do not disable the Next.js route's existing production 503 guard.** A service credential only proves that a request came from a trusted application server. It cannot protect a publicly exposed web form on its own.

Until Phase 10B.2 adds user authentication and frontend/shared end-user abuse controls, **public verification remains disabled in production**. Existing local development continues to work without any token when `APP_ENV=development`.

The rate limiter relies on Redis being reachable; a Redis outage produces HTTP 503, not unlimited requests. The 60-second window is measured from the first request, shared across API instances using the same Redis and credential. Its use of a single shared counter can cause one user to consume everyone's quota; per-user quotas will address this in the next subphase.

## Verification commands (from project root)

```powershell
uv run ruff check .
uv run ruff format --check .
uv run mypy apps ml scripts
uv run pytest
```

From `apps\web`:

```powershell
npm run lint
npx tsc --noEmit
npm run build
```

The included unit tests use a fake Redis client. These tests do not prove integration against production Redis or the public authentication flow. Before production deployment, verify staging with real Redis, the app proxy, TLS, token rotation, concurrent quotas, and private network policy.
