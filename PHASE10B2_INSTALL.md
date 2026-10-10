# Phase 10B.2 — Google sign-in and per-user inference quota

Windows + VS Code + PowerShell. This ZIP includes **complete replacement files** and new files; it never contains passwords or credentials.

## 0. Current scope and safety

- Phase 10B.1's service authentication and 30/minute global Redis quota remain intact.
- Production `/api/verification` now requires an Auth.js Google session **and** a configured private API token.
- Backend `/api/v1/verify` requires a private service token and a trusted `X-Verified-User` forwarded only from the authenticated Next.js server. It enforces an additional 10/minute quota per account.
- **Development** (`APP_ENV=development` and `NODE_ENV=development`) retains the existing unauthenticated local verification workflow for backward compatibility. To test login locally, set `VERIFY_REQUIRE_LOGIN=true` in `apps/web/.env.local` and configure OAuth credentials.
- **Before public deployment**, use non-development backend environment, HTTPS, private ingress/network access to FastAPI, secure secret management, and separate Google OAuth callback URLs for each domain. Test actual production OAuth and rate limits.
- Full Next.js build cannot be validated by this package alone; install `next-auth@beta` and run local lint/build/tests below.

## 1. Stop dev processes, then create backup

```powershell
cd C:\Projects\explainable-news-verifier
$backup = Join-Path $env:TEMP ("phase10b2_backup_" + (Get-Date -Format 'yyyyMMdd_HHmmss'))
$files = @(
 'apps\api\main.py',
 'apps\api\core\config.py',
 'apps\web\src\app\api\verification\route.ts',
 'apps\web\src\lib\api\server.ts',
 'apps\web\src\lib\api\contracts.ts'
)
foreach ($file in $files) {
  $dest = Join-Path $backup $file
  New-Item -ItemType Directory -Force -Path (Split-Path $dest -Parent) | Out-Null
  Copy-Item -LiteralPath $file -Destination $dest -Force
}
Write-Host "Backup: $backup"
```

## 2. Unzip to repo root

Download `phase10b2_auth_patch.zip` to Downloads, then:

```powershell
Expand-Archive -LiteralPath "$HOME\Downloads\phase10b2_auth_patch.zip" -DestinationPath "C:\Projects\explainable-news-verifier" -Force
```

If files already exist that were not part of Phase 10B.1, review their differences before overwriting.

## 3. Install Auth.js

```powershell
cd C:\Projects\explainable-news-verifier\apps\web
npm install next-auth@beta
```

Official Auth.js v5 installation currently specifies `next-auth@beta`. Do not run `npm audit fix --force` blindly; assess any findings separately.

## 4. Configure Google OAuth locally

Auth.js official Google provider guide:
https://authjs.dev/reference/core/providers/google

In Google Cloud console, create an OAuth web application and authorize this redirect URI:

`http://localhost:3000/api/auth/callback/google`

In `apps/web/.env.local` (**never Git-commit this file**), add:

```dotenv
AUTH_SECRET=<generate-random-secret>
AUTH_GOOGLE_ID=<Google-OAuth-client-id>
AUTH_GOOGLE_SECRET=<Google-OAuth-client-secret>
VERIFY_REQUIRE_LOGIN=true
```

Generate `AUTH_SECRET` using `npx auth secret` from `apps/web` (this writes a value into an environment file) or another cryptographically secure secret generator. Never paste secrets into ChatGPT or public logs.

Existing `API_BASE_URL=http://127.0.0.1:8000` remains. In development `INTERNAL_API_TOKEN` is not required for a local verification demo.

You can temporarily omit `VERIFY_REQUIRE_LOGIN` to keep local verification working while setting up Google.

## 5. Backend validation

```powershell
cd C:\Projects\explainable-news-verifier
uv run ruff check . --fix
uv run ruff format .
uv run ruff check .
uv run ruff format --check .
uv run mypy apps ml scripts
uv run pytest
```

Check for the new `test_phase10b2_user_quota.py` cases; do not assume tests passed without running them.

## 6. Frontend validation

```powershell
cd C:\Projects\explainable-news-verifier\apps\web
npm run lint
npx tsc --noEmit
npm run build
```

After Google credentials are configured, run FastAPI in one PowerShell window and Next.js in another, then visit:

- `http://localhost:3000/account` — Google sign-in/sign-out.
- `http://localhost:3000/verify` — verification UI.

With `VERIFY_REQUIRE_LOGIN=true`, an unauthenticated POST `/api/verification` must return HTTP **401**, not run inference. After login, the same request should succeed in development.

## 7. Secure production configuration (do not turn on yet)

- Next.js environment: `NODE_ENV=production`, `AUTH_SECRET` (strong random value), `AUTH_GOOGLE_ID`, `AUTH_GOOGLE_SECRET`, `INTERNAL_API_TOKEN` (strong random value), `API_BASE_URL` set to a private internal FastAPI address, HTTPS public domain.
- FastAPI environment: `APP_ENV=production`, `INTERNAL_API_TOKEN` **identical** to Next.js value, `INFERENCE_REQUESTS_PER_MINUTE=30`, `INFERENCE_USER_REQUESTS_PER_MINUTE=10`, Redis configured as protected service.
- In Google Cloud, register `https://YOUR_PUBLIC_DOMAIN/api/auth/callback/google` for the production OAuth app.
- Do NOT expose FastAPI directly to the Internet; only Next.js should reach it over a trusted private network. Headers are a trust assertion **only after** the service token is validated.
- Do NOT use `NEXT_PUBLIC_` for secrets. Configure ingress, secure cookies, `Cache-Control: no-store`, TLS, deployment-time secret rotation and monitoring.

## 8. Review before any Git push

```powershell
cd C:\Projects\explainable-news-verifier
git status --short
git diff --check
git check-ignore apps/web/.env.local
```

Expected ignored `.env.local` should NOT be staged. Retest before deployment.
