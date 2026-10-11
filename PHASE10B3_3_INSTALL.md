# Phase 10B3.3 — Private usage statistics API + account dashboard

**Local changes only. Do not commit or push until you explicitly choose to.**

The existing Phase 10B3.2 database migration `10b32a1c2026` must already be applied.

## Windows / PowerShell

1. Download `phase10b3_3_patch.zip` to your Downloads folder.
2. In VS Code's PowerShell terminal, from `C:\Projects\explainable-news-verifier`:

```powershell
cd C:\Projects\explainable-news-verifier
git status -sb
Expand-Archive -Path "$env:USERPROFILE\Downloads\phase10b3_3_patch.zip" -DestinationPath . -Force
uv run python -m scripts.apply_phase10b3_3_routes
uv run ruff format apps/api/main.py apps/api/routes/usage_statistics.py apps/api/schemas/usage_statistics.py apps/api/services/usage_statistics.py tests/unit/test_phase10b3_3_usage_statistics.py scripts/apply_phase10b3_3_routes.py
uv run ruff check .
uv run ruff format --check .
uv run mypy apps ml scripts
uv run pytest tests/unit/test_phase10b3_3_usage_statistics.py -v
uv run pytest
```

3. In another terminal:

```powershell
cd C:\Projects\explainable-news-verifier\apps\web
npm run lint
npx tsc --noEmit
npm run build
```

4. Restart FastAPI and the Next.js development server. Go to `http://localhost:3000/account/usage` and sign in with Google.

This phase **does not overwrite your existing `apps/web/src/app/account/page.tsx`**. The account usage page is accessible directly by `/account/usage`. Optionally, add a link from your account page with `href="/account/usage"` later.

## Security and data behavior

- Browser route: `GET /api/account/usage?days=7|30|90`, requires Auth.js session.
- FastAPI route: `GET /api/v1/account/usage?days=7|30|90`, requires internal service token and trusted user assertion.
- The database search uses the **same HMAC actor fingerprint** as the usage audit middleware.
- Includes UTC daily totals, success/failure/rate-limit breakdown, and average latency.
- Data retention remains managed separately; no new migration needed.
- Uses best-effort Phase 10B3.2 records; cannot reconstruct dropped events during outages.
- Backend database errors return a generic 503. No private identities or claims are included in API responses.
- Production `API_BASE_URL` must use HTTPS for this endpoint.

**No Git commands that change staging or commits are needed.**
