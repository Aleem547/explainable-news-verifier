# Phase 13E.7 — Feature-gated article frontend/API pilot

## Scope and limits

This package adds a **separate**, opt-in `/article` Next.js page; its authenticated
same-origin `POST /api/article-verification` server proxy; and a FastAPI
`POST /api/v1/article/verify` server endpoint. The original claim verifier
and its API route remain unchanged. The feature is **disabled by default**
on **both** services via `ARTICLE_VERIFICATION_ENABLED=true`; do not set
that environment variable in AWS or Vercel before Phase 13E.8 and release review.

The pilot can process **pasted plaintext** (100–8,000 Unicode characters,
no more than 10,000 UTF-8 bytes); it builds a complete Phase 13E.6 report of
factual-claim **candidates** but runs CPU-backed inference for **only the first
candidate**. All later candidates are labeled `SKIPPED_LIMIT`. This is an
intentional budget/latency safeguard: even a single DeBERTa pass can be slow,
and the server's existing verification queue is CPU-constrained.

**Article URL submission is not supported in this pilot**. Phase 13E.2 requires
an exact server-trusted external discovery hit, explicit publisher access
approval, and a configured server-side domain allowlist. The review ZIP did
not include enough DB/discovery registry code to wire those checks. Neither
browser nor API may invent trusted discovery metadata; do not replace this
restriction with an arbitrary URL fetch. A later follow-up must finish that
path before URL verification can be claimed complete.

## Security and privacy

- The Next.js route authenticates with Auth.js, rejects cross-site requests,
  reads bytes with an actual 12-KB cap, and keeps `INTERNAL_API_TOKEN` private.
- The backend route is mounted with existing `require_inference_access` and
  `require_verified_user_access` dependencies; the existing internal-user
  authorization dependency is also retained on the article handler.
- The existing ASGI JSON-body limiter (default 16,384 bytes) remains intact.
  The article payload caps are below this ceiling; no global relaxation.
- A process-local one-at-a-time semaphore prevents an unlimited wait queue.
  Across multiple workers/instances there is no global article semaphore.
- Responses are `Cache-Control: no-store`; body contents are neither persisted
  nor logged by the new code, and are never inserted into the evidence corpus.
  The existing hashed audit accounting now recognizes the article endpoint.
- Model calls may outlive proxy/browser timeouts or a disconnected client.
  Cancellation **does not guarantee** that already running CPU inference stops.
- A per-request article may still take longer than Vercel's route duration;
  production readiness requires latency/load testing and possibly a background
  job architecture, which is **not** part of this pilot.

## Outcomes and honest claims

Wikipedia and external evidence verdicts are kept separate per claim. Every
external reference preserves the publisher and URL, and reports NLI results.
Provisional source-risk families do **not** prove independent corroboration.
There is no article-wide truth verdict or percentage. The frontend explicitly
labels failed, unavailable, and skipped claims; it never upgrades user-submitted
text into independently sourced evidence.

## Local test / manual QA

1. Stay on `feat/phase13-cross-source`. Keep AWS and Vercel unchanged.
2. Run `scripts/phase13e7/run_local_article_integration_tests.ps1
   -IncludeRegressions -IncludeFrontendTypecheck` from the repo root.
   Node dependencies must already be installed in `apps/web/node_modules`.
3. Optional local-only pilot: put `ARTICLE_VERIFICATION_ENABLED=true` into
   the **local development process environment** for **both** web and API,
   then restart both apps. Do not add credentials or toggle flags in Git.
4. Sign in and visit `/article`. Paste 100–8,000 characters of ordinary prose.
   Verify that report labels are conservative and evidence URLs are HTTPS.
5. Check the URL tab for disabled, non-fetching behavior; check a non-logged-in
   request returns 401; oversized JSON 413; wrong content type 415; forged
   user identity rejected by backend; feature disabled 503.
6. Restart production web/api (unmodified) only after final release review.

## Deployment and source-change precautions

Files modified: `apps/api/main.py`,
`apps/api/security/verification_audit.py`,
`apps/web/src/lib/api/server.ts`,
`apps/web/src/components/layout/app-sidebar.tsx`.

Files added: `apps/api/routes/article_verification.py`,
`apps/api/services/article_api_workflow.py`, Next.js `/article` and
`/api/article-verification`, `article-contracts.ts`,
`article-verification-workspace.tsx`, tests, docs and test runner.

Commit the exact listed files only. Do **not** use `git add .`, and do not
merge into `main` or deploy to AWS/Vercel yet. Phase 13E.8 needs full-stack
integration and security checks, plus explicit review of how to handle long
CPU inference and trusted URL discovery.
