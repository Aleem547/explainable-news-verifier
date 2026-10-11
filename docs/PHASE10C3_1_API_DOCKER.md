# Phase 10C.3.1 — FastAPI production-container baseline

## Scope

This is a **provisional production Docker baseline**, not deployment completion.
It adds a single-worker, non-root FastAPI runtime with a Python 3.12 environment
installed from the committed `uv.lock`. It leaves existing `infra/docker/compose.dev.yml`
and all production/service credentials unchanged. Vercel continues to host Next.js
separately.

### Source-specific findings

- The project requires Python >=3.12, and has a uv lock file.
- `Settings` requires `DATABASE_URL`, `REDIS_URL`, `QDRANT_URL`, and
  `MLFLOW_TRACKING_URI`, and supports `APP_ENV=production` and
  `INTERNAL_API_TOKEN`.
- Local artifact sizes are 14.11 GB of models, 1.38 GB of indexes, and 4.68 GB of
  processed data. Not every artifact is necessarily needed for API inference.
- The FEVER verification code currently needs the specific mounted paths checked
  by `scripts/deployment/phase10c3_1_artifacts.py`.

## Build

From the repository root, **not** the `apps/web` folder:

```powershell
uv run python -m scripts.deployment.phase10c3_1_artifacts

docker build -f infra/docker/api/Dockerfile -t verifier-api:10c3.1 .
```

A first build is potentially **large and slow**: the `pyproject.toml` dependencies
include training/evaluation tooling and PyTorch, not yet a slim inference-only
optional dependency group. Docker's base images and Python wheels require network
access. `ghcr.io/astral-sh/uv:latest` should be pinned to a reviewed digest before
an actual release; `uv.lock` only pins Python packages, not the base images.
Do not publish the image publicly before a dependency/license audit.

The `.dockerignore` is an allowlist. It transfers `apps/api`, `ml`, `pyproject.toml`
and `uv.lock` to the build and **excludes secrets and artifact folders**. Container
startup does not preload models; first inference may have a significant cold start.

## Environment and local smoke test

Prepare a **private, gitignored** `.env.api.docker.local` on your Windows machine.
Do not upload or commit it. It must contain your valid service settings:
`DATABASE_URL`, `REDIS_URL`, `QDRANT_URL`, `MLFLOW_TRACKING_URI`, and
`INTERNAL_API_TOKEN` (plus all applicable middleware/authentication and logging
secrets from the current project). Use real strong values; never substitute the
placeholder strings in production. The image defaults `APP_ENV=production`.

When using Docker Desktop to access services exposed on the **Windows host**, use
`host.docker.internal` instead of `127.0.0.1`/`localhost` **inside connection URLs**.
For example, a local PostgreSQL URL may look like:
`postgresql+asyncpg://USER:URL_ENCODED_PASSWORD@host.docker.internal:5432/DB`.
If services are on the same Docker network instead, use Docker service names.

Make sure the four backend services are already running. Then, from the repo root:

```powershell
$models = (Resolve-Path .\models).Path
$data = (Resolve-Path .\data).Path

docker run --rm --name verifier-api-smoke `
  -p '127.0.0.1:8001:8000' `
  --env-file '.env.api.docker.local' `
  --mount "type=bind,source=$models,target=/app/models,readonly" `
  --mount "type=bind,source=$data,target=/app/data,readonly" `
  --mount 'type=volume,source=verifier_hf_cache,target=/home/verifier/.cache/huggingface' `
  verifier-api:10c3.1
```

The BGE and cross-encoder Hugging Face models are separate from the local
`models/nli_verifier` checkpoint. They may download on initial use; either allow
controlled initial downloads into the persistent Hugging Face cache or pre-provision
that cache from reviewed model artifacts. **No service token belongs in the image.**

In a separate PowerShell window:

```powershell
Invoke-WebRequest http://127.0.0.1:8001/api/v1/ready

docker inspect verifier-api-smoke --format '{{.State.Health.Status}}'
```

If `/ready` fails, inspect backend logs using `docker logs verifier-api-smoke` and
check service URLs, mounted files, access permissions and production credentials.
Do **not** turn off production authentication to make a smoke test pass. Backend
health and actual claim verification need additional integration checks.

Stop with Ctrl+C in the container terminal. The bind mounts are read-only; Python
may still create its **HF cache** in the named volume. PostgreSQL, Redis and Qdrant
are not run by this Dockerfile and should stay private in production.

## Limits / pending work

- No Docker image was built or run as part of creating this patch; run local commands.
- The default dependency set includes research dependencies; later shrink to an
  inference-only group **without** breaking dependency resolution or model loading.
- CPU inference needs adequate memory; model weights and corpus occupy gigabytes.
  Benchmark real peak memory, startup time and model fetches before selecting a host.
- The `--workers 1` setting reduces simultaneous copies of the models but does not
  provide horizontal scaling or guaranteed request scheduling.
- Per-process BGE document caching remains opt-in and increases resident memory.
- Docker's readiness probe is deliberately dependency-aware; it is not a substitute
  for a live, authenticated inference check.
- Do not use an ephemeral filesystem for required artifacts or Hugging Face models
  on a production host unless provisioning/re-download behavior is accounted for.
- Vercel should only receive frontend/NextAuth secrets; inference service credentials
  remain private server-to-server values.
- Do not commit or push until Phase 10 is reviewed and user approval is explicit.
