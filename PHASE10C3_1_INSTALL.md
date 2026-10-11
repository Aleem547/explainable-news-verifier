# Phase 10C.3.1 — Install and validate (Windows PowerShell)

Download `phase10c3_1_patch.zip` to your Windows Downloads folder.

```powershell
cd C:\Projects\explainable-news-verifier
Expand-Archive -Path "$env:USERPROFILE\Downloads\phase10c3_1_patch.zip" -DestinationPath . -Force

uv run ruff format scripts\deployment\phase10c3_1_artifacts.py tests\unit\test_phase10c3_1_artifacts.py
uv run ruff check .
uv run ruff format --check .
uv run mypy apps ml scripts
uv run pytest tests\unit\test_phase10c3_1_artifacts.py -v
uv run pytest

uv run python -m scripts.deployment.phase10c3_1_artifacts

docker build -f infra/docker/api/Dockerfile -t verifier-api:10c3.1 .
```

Read `docs/PHASE10C3_1_API_DOCKER.md` before any `docker run` command. Production
URLs, credentials, HF cache, memory, and mounted artifacts must be set up first.
The Docker image is a draft until the build and smoke test pass on your workstation.
No Git commit or push is included.
