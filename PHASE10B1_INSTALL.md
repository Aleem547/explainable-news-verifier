# Phase 10B.1 — Installation (Windows + PowerShell)

This ZIP contains **complete replacement files**, plus new security files and tests.

1. Stop FastAPI and Next.js with Ctrl+C if running. Keep PostgreSQL, Redis, Qdrant, and MLflow in Docker running.
2. Run in a new PowerShell terminal:

```powershell
cd C:\Projects\explainable-news-verifier
$source = "$HOME\Downloads\phase10b1_security_patch.zip"
$backup = Join-Path $env:TEMP ("phase10b1_backup_" + (Get-Date -Format 'yyyyMMdd_HHmmss'))
$files = @(
  'apps\api\main.py',
  'apps\api\core\config.py',
  'apps\web\src\lib\api\server.ts'
)
foreach ($file in $files) {
  $target = Join-Path $backup $file
  New-Item -ItemType Directory -Force -Path (Split-Path $target -Parent) | Out-Null
  Copy-Item -LiteralPath $file -Destination $target -Force
}
Write-Host "Backup: $backup"
Expand-Archive -LiteralPath $source -DestinationPath (Get-Location).Path -Force
```

3. Run project-root validation:

```powershell
uv run ruff check . --fix
uv run ruff format .
uv run ruff check .
uv run ruff format --check .
uv run mypy apps ml scripts
uv run pytest
```

4. Check Next.js:

```powershell
cd C:\Projects\explainable-news-verifier\apps\web
npm run lint
npx tsc --noEmit
npm run build
```

5. For the browser smoke test, **continue using `APP_ENV=development`** and your existing `.env.local`/`API_BASE_URL`. Do not add a live credential yet. Start the services using your existing commands. The verification UI should behave exactly as before.

6. **Do not delete** the existing production 503 guard in `apps/web/src/app/api/verification/route.ts`. Phase 10B.2 will add end-user authentication and per-user limits before lifting that guard. The environment configuration for staging/production is explained in `docs/PHASE10B1_SECURITY.md`.

**Do not `git push` yet.**
