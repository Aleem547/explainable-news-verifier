# Phase 10C.1 local installation (no Git commit or push)

1. Save `phase10c1_security_patch.zip` to your Downloads directory.
2. From VS Code PowerShell:

```powershell
cd C:\Projects\explainable-news-verifier
Expand-Archive -Path "$env:USERPROFILE\Downloads\phase10c1_security_patch.zip" -DestinationPath . -Force
uv run python -m scripts.security.phase10c1_preflight
uv run pytest tests\unit\test_phase10c1_preflight.py -v
uv run ruff format .
uv run ruff check .
uv run ruff format --check .
uv run mypy apps ml scripts
uv run pytest
cd apps\web
npm run lint
npx tsc --noEmit
npm run build
```

3. Read `docs/PHASE10C1_SECURITY_AUDIT.md` for deployment environment checks.
4. Send the validation results before proceeding. **Do not use git add,
commit or push.** The ZIP does not include `.env` files or credentials.
