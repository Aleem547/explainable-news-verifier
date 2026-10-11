# syntax=docker/dockerfile:1.7
# Build from the repository root:
# docker build -f infra/docker/api/Dockerfile -t verifier-api:10c3.1 .
# Production inference runs on CPU; model/corpus artifacts are mounted, never copied.
FROM ghcr.io/astral-sh/uv:latest AS uv_binary

FROM python:3.12-slim-bookworm AS dependencies
COPY --from=uv_binary /uv /uvx /usr/local/bin/
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_COMPILE_BYTECODE=0
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

FROM python:3.12-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH \
    APP_ENV=production \
    DEBUG=false \
    HF_HOME=/home/verifier/.cache/huggingface \
    TOKENIZERS_PARALLELISM=false

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 verifier \
    && useradd --uid 10001 --gid verifier --home-dir /home/verifier --create-home verifier \
    && mkdir -p /app/models /app/data /home/verifier/.cache/huggingface \
    && chown -R verifier:verifier /app /home/verifier

WORKDIR /app
COPY --from=dependencies /opt/venv /opt/venv
COPY --chown=verifier:verifier apps/api ./apps/api
COPY --chown=verifier:verifier ml ./ml

USER verifier
EXPOSE 8000

# Dependency-aware readiness; the container may be unhealthy until services are configured.
HEALTHCHECK --interval=30s --timeout=8s --start-period=120s --retries=3 \
    CMD python -c "from urllib.request import urlopen; urlopen('http://127.0.0.1:8000/api/v1/ready', timeout=5).close()" || exit 1

# One worker avoids loading multiple large CPU model copies into memory.
CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
