# Phase 10C.1 — Deployment security preflight

## Confirmed initial audit finding

The Phase 10B3 Next.js verification transport accepted `http://` upstream URLs
in production while forwarding `X-Service-Token`. The Phase 10C.1 replacement
requires HTTPS for a production backend URL, and sets fetch `redirect: "error"`
so the private service credential is not forwarded through redirects.

This patch does **not** modify FastAPI authentication, Google OAuth, quotas,
user usage records, or the database. It is **not** a full production security sign-off.

## Preflight tool

Read-only; inspects tracked filenames (not file contents), source usage of
secret-related `NEXT_PUBLIC_` names, verification transport safeguards, and
optional process environment readiness. It prints only whether variable names
are configured, never their values. The checks are heuristic and do not
replace tests of deployed traffic, secret rotation or vulnerability scanning.

Run locally (no production secrets required):

```powershell
uv run python -m scripts.security.phase10c1_preflight
```

When deployed, run separately in each runtime with real environment variables:

```powershell
# Vercel/Next.js runtime
uv run python -m scripts.security.phase10c1_preflight --mode production --service web
# Backend runtime
uv run python -m scripts.security.phase10c1_preflight --mode production --service api
```

On Vercel you may not have Python installed; these are also usable from a
CI environment with the same non-secret environment variable names and values.
Do not copy `.env.local` into Docker images or upload credentials to this chat.

## Required operator review before actual deployment

- In Vercel, set `API_BASE_URL` to the HTTPS origin of the remote backend.
  `localhost:8000` does not refer to the developer's machine from Vercel.
- Keep `INTERNAL_API_TOKEN`, `AUTH_SECRET`, and Google OAuth secret **server only**;
  never give them a `NEXT_PUBLIC_` prefix. Provision the same random 32+ character
  service token in the web and backend runtimes through their separate secret managers.
- Explicitly set backend `APP_ENV=production`. Its current local default is
  `development`, which bypasses some shared rate-limit dependencies.
- `NODE_ENV=production` is automatic in a regular Next.js production build.
  Auth.js needs valid HTTPS origins and a registered Google OAuth redirect URI.
- Check that expensive backend routes are protected in the deployed environment.
  Keep the backend private where possible; do not expose its token to browsers.
- Confirm production PostgreSQL, Redis, Qdrant, model artifacts, backups and
  retention, and verify readiness without exposing diagnostic internals.
- Run npm dependency audit separately; do not blindly apply breaking upgrades.
- No git commit/push until user authorization at end of Phase 10.
