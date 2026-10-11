# Phase 10B3.1 patch installation

**Back up or commit current changes before overwriting files.** The patch
contains exact relative paths under the repository root. The only existing
file overwritten is `apps/api/main.py`. Everything else is new.

From `C:\Projects\explainable-news-verifier` in PowerShell:

```powershell
cd C:\Projects\explainable-news-verifier
git status -sb
Expand-Archive -Path "$env:USERPROFILE\Downloads\phase10b3_1_patch.zip" -DestinationPath . -Force
uv run ruff format apps/api/main.py apps/api/security/verification_audit.py tests/unit/test_phase10b3_verification_audit.py
uv run ruff check .
uv run ruff format --check .
uv run mypy apps ml scripts
uv run pytest tests/unit/test_phase10b3_verification_audit.py -v
uv run pytest
```

Do not commit yet if a check fails. Share the complete error output. No
secrets, .env files, or DB credentials are included in the patch.
