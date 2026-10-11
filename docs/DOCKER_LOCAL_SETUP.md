
# Explainable News Verifier — Local Docker Setup

## Prerequisites

- Docker Desktop with Docker Compose
- Python 3.12
- uv package manager
- Git

## Environment Setup

1. Clone the repository.
2. Copy `.env.example` to `.env` if `.env` does not exist.
3. Configure the required environment variables.
4. Create `.env.docker` in the project root.

The `.env.docker` file must contain:

- DATABASE_URL
- REDIS_URL
- QDRANT_URL

Use the connection URL schemes and credentials appropriate
for the application, with these Docker service hosts:

- PostgreSQL: postgres:5432
- Redis: redis:6379
- Qdrant: qdrant:6333

Both `.env` and `.env.docker` must remain untracked.

## Build and Start Services

From the project root:

```powershell
docker compose --env-file .env -f infra/docker/compose.dev.yml up -d --build
```

## Check Container Status

```powershell
docker compose --env-file .env -f infra/docker/compose.dev.yml ps
```

The stack contains PostgreSQL, Redis, Qdrant,
MLflow, and FastAPI.

## Verify API Readiness

```powershell
curl.exe http://127.0.0.1:8001/api/v1/ready
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

## Run Automated Tests

```powershell
uv run pytest -q
```

## Security Notes

- Never commit credentials or environment files.
- Keep large ML model artifacts out of Git.
- Do not commit local reference ZIP archives.
- Docker readiness does not replace full inference testing.
