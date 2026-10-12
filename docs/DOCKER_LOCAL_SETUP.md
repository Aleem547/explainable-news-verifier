
# Explainable News Verifier — Local Docker Setup

## 1. Overview

This guide explains how to run the Explainable News Verifier
development infrastructure and AI inference backend using Docker.

The local stack includes:

- PostgreSQL 17 — application database
- Redis 8 — caching and supporting services
- Qdrant — vector database
- MLflow — experiment and artifact tracking
- FastAPI — AI verification backend

The Next.js frontend runs separately on Windows during local
development.

## 2. Prerequisites

Install:

- Docker Desktop with Docker Compose
- Python 3.12
- uv package manager
- Node.js and npm
- Git

Ensure Docker Desktop is running before starting the stack.

The API image contains substantial ML dependencies and needs
sufficient disk space and memory.

## 3. Project Directory

Open PowerShell and navigate to the repository:

```powershell
cd C:\Projects\explainable-news-verifier
```

Run all Docker Compose commands from this directory.

## 4. Environment Configuration

The repository uses two local configuration files:

- `.env` — main development configuration
- `.env.docker` — Docker-specific service connection URLs

If `.env` does not exist, create it using `.env.example`
as the starting template and configure the required values.

Do not overwrite an existing configured `.env`.

Create `.env.docker` in the repository root if it does not exist.

This file must include the application connection URLs:

- `DATABASE_URL`
- `REDIS_URL`
- `QDRANT_URL`

Inside Docker, use these service hostnames:

- PostgreSQL: `postgres` on port `5432`
- Redis: `redis` on port `6379`
- Qdrant: `qdrant` on port `6333`

Keep the correct URL schemes, credentials, database names,
and other connection settings for the application.

Do not use localhost for these three dependencies inside
the API container.

Never commit `.env`, `.env.docker`, or `.env.local`.

## 5. Required AI Artifacts

The local model and retrieval artifacts must exist:

```text
models/
  nli_verifier/
    nli-deberta-v3-small_fever_nli_30k/

data/
  metadata/
    fever_nli_calibration_config.json
  indexes/
    fever/
      page_bm25/
  processed/
    fever/
      wiki_sentences.parquet
```

Run the read-only artifact preflight:

```powershell
uv run python -m scripts.deployment.phase10c3_1_artifacts
```

All six checks should pass before starting inference.

Additional BGE retrieval and cross-encoder reranking models
must be available through the Hugging Face cache or
downloadable at runtime.

## 6. Create the Writable Tantivy Runtime Index

Tantivy requires a writable index directory for lock files.

The original BM25 index must not be modified by the
running Docker API.

Create a separate runtime copy:

```powershell
$source = ".\data\indexes\fever\page_bm25"
$destination = ".\docker-data\page_bm25"

if (!(Test-Path $source -PathType Container)) {
    throw "Original BM25 index not found"
}

if (!(Test-Path $destination)) {
    New-Item -ItemType Directory `
        -Path ".\docker-data" -Force | Out-Null

    Copy-Item -LiteralPath $source `
        -Destination $destination -Recurse
}

Test-Path $destination
```

Expected result:

```text
True
```

The Compose configuration mounts:

- Original trained models: read-only
- Original FEVER data: read-only
- Runtime BM25 index: writable

The `docker-data/` directory is ignored by Git.

If a runtime index already exists, inspect it before replacing
or rebuilding it.

## 7. Validate Docker Compose

```powershell
docker compose --env-file .env -f infra/docker/compose.dev.yml config --quiet
```

No output indicates successful configuration validation.

## 8. Build and Start Services

For a fresh installation:

```powershell
docker compose --env-file .env -f infra/docker/compose.dev.yml up -d --build
```

Building the API image for the first time can take
significant time.

For an existing installation with the image already built:

```powershell
docker compose --env-file .env -f infra/docker/compose.dev.yml up -d --no-build
```

To recreate only the API after changing its configuration:

```powershell
docker compose --env-file .env -f infra/docker/compose.dev.yml up -d --no-build --no-deps --force-recreate api
```

Do not use `docker compose down -v` unless intentionally
removing persistent infrastructure data.

## 9. Check Container Status

```powershell
docker compose --env-file .env -f infra/docker/compose.dev.yml ps
```

Verify the API and supporting services are running.

The API may take time to initialize after recreation.

## 10. Verify FastAPI Readiness

```powershell
curl.exe -sS http://127.0.0.1:8001/api/v1/ready
```

Expected result:

```json
{
  "ready": true,
  "checks": {
    "postgres": "ok",
    "redis": "ok",
    "qdrant": "ok"
  }
}
```

Readiness confirms infrastructure connectivity.
It does not guarantee ML inference has initialized.

## 11. Verify Tantivy Runtime Index

```powershell
docker compose --env-file .env -f infra/docker/compose.dev.yml exec -T api python -c "import tantivy; idx=tantivy.Index.open('/app/data/indexes/fever/page_bm25'); idx.reload(); print('RUNTIME_INDEX_OK')"
```

Expected:

```text
RUNTIME_INDEX_OK
```

## 12. Verify Hugging Face Cache Permissions

```powershell
docker compose --env-file .env -f infra/docker/compose.dev.yml exec -T api python -c "import os; p='/home/verifier/.cache/huggingface'; print('HF_CACHE_WRITABLE' if os.access(p,os.W_OK) else 'HF_CACHE_NOT_WRITABLE')"
```

Expected:

```text
HF_CACHE_WRITABLE
```

A persistent Docker volume stores the Hugging Face cache
across normal API container recreations.

## 13. Verify AI Pipeline Initialization

```powershell
docker compose --env-file .env -f infra/docker/compose.dev.yml exec -T api python -u -c "from apps.api.services.verification import get_verification_pipeline; get_verification_pipeline(); print('PIPELINE_READY')"
```

Expected:

```text
PIPELINE_READY
```

This initializes the pipeline in a separate process.
The API process must still initialize its own inference
pipeline for real requests.

## 14. Start the Next.js Frontend

Open another PowerShell terminal:

```powershell
cd C:\Projects\explainable-news-verifier\apps\web
```

In `.env.local`, configure the server-side backend URL:

```dotenv
API_BASE_URL=http://127.0.0.1:8001
```

Do not expose private backend credentials using
`NEXT_PUBLIC_` environment variables.

Start Next.js:

```powershell
npm run dev
```

Open:

http://localhost:3000/verify

## 15. Test End-to-End Verification

Test three claim categories:

### Supporting evidence

The Eiffel Tower is located in Paris, France.

### Refuting evidence

The Eiffel Tower is located in Berlin, Germany.

### Insufficient evidence

In 2024, the fictional city of Veloria opened a museum
called the Amber Archive.

For each test:

1. Submit the claim.
2. Examine the verdict.
3. Inspect the retrieved evidence.
4. Check NLI relations and evidence acceptance.
5. Verify that independent corroboration is not falsely claimed.

A successful result must be evidence-grounded and must
communicate the limitations of the available corpus.

## 16. Run Automated Tests

From the repository root:

```powershell
uv run pytest -q
```

The last verified baseline was 459 passing tests.

Run frontend checks from `apps/web`:

```powershell
npm run lint
npm run build
```

## 17. Troubleshooting

### HTTP 503 During Verification

Check API logs:

```powershell
docker compose --env-file .env -f infra/docker/compose.dev.yml logs --tail 100 api
```

Potential causes include:

- Missing inference artifacts
- Incorrect Docker mounts
- Tantivy index permission errors
- Model download failures
- Model initialization errors

### Tantivy ReadOnlyFilesystem Error

Ensure the writable runtime index copy exists and that
Docker mounts it at:

`/app/data/indexes/fever/page_bm25`

### Model Loading Warnings

Hugging Face authentication warnings may appear when
downloading public models without a token.

Warnings alone do not establish inference failure.

### Frontend Backend Connection Errors

Confirm that `.env.local` points to:

`http://127.0.0.1:8001`

Restart Next.js after changing environment configuration.

## 18. Security and Deployment Notes

- Never commit local credentials.
- Do not commit trained model weights or datasets.
- Do not commit reference ZIP archives.
- Keep the original BM25 index separate from its runtime copy.
- Do not expose local development services publicly.
- Preserve authentication, authorization, and rate limiting.
- Do not interpret NLI model scores as claim-level truth probabilities.
- Single-corpus evidence is not independent corroboration.

This configuration is for local development and integration testing.
Production deployment requires additional security, operational,
performance, and end-to-end acceptance checks.
