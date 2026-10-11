# Phase 10B3.2 — Windows installation (NO GIT COMMIT/PUSH)

This patch **assumes Phase 10B3.1 has already been installed**.
Work only on your local copy until you explicitly choose to commit.

1. From the repository root, run `git status -sb` and
   `uv run alembic heads`. **If there are multiple heads or the current head
   differs from `9f52a1c840d6`, stop and send the output. Do NOT run an upgrade.**
2. Download `phase10b3_2_patch.zip` into `Downloads`.
3. From `C:\Projects\explainable-news-verifier`, run:

```powershell
Expand-Archive -Path "$env:USERPROFILE\Downloads\phase10b3_2_patch.zip" -DestinationPath . -Force
uv run python scripts\apply_phase10b3_2_registry.py
uv run ruff format apps\api\main.py apps\api\security\verification_audit.py apps\api\db\models\verification_usage.py apps\api\services\verification_usage.py tests\unit\test_phase10b3_2_usage.py scripts\apply_phase10b3_2_registry.py scripts\usage\prune_verification_usage.py
uv run ruff check .
uv run ruff format --check .
uv run mypy apps ml scripts
uv run pytest tests\unit\test_phase10b3_2_usage.py -v
uv run pytest
```

4. If tests succeed and your local Postgres service is running, inspect schema:

```powershell
uv run alembic current
uv run alembic heads
```

With a reviewed migration chain, run on your **local development DB only**:

```powershell
uv run alembic upgrade head
uv run alembic current
```

5. Test safe retention query (requires migrated, running Postgres):

```powershell
uv run python scripts\usage\prune_verification_usage.py --days 90
```

Do **not** use `--execute` yet. No CI deployment, staging migration, or Git
commit/push is part of this phase. Send your test results and `alembic heads`.

> Note: The ZIP contains complete replacements for Phase 10B3.1
> `apps/api/main.py` and `apps/api/security/verification_audit.py`. Review
> differences first if you edited either file after installing 10B3.1.
