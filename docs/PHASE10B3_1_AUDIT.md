# Phase 10B3.1 — Verification Request Auditing

This increment adds a privacy-conscious, structured audit event to every
`POST /api/v1/verify` request, including authentication, validation, rate-limit,
and backend failures.

Each audit event records: randomly generated request ID, HTTP status, outcome,
route, method, elapsed time, and (only after authentication succeeds) an HMAC
fingerprint of the verified user ID. The same request ID is returned in the
`X-Request-ID` response header when the response passes through the middleware.

The middleware **does not log** claim text, request body, identity headers,
raw user IDs, emails, OAuth/session tokens, or service tokens. Responses for
`POST /api/v1/verify` have `Cache-Control: no-store` enforced.

The fingerprint key is currently derived from `internal_api_token`. Keep that
secret server-side and rotate it through coordinated credential management.
Rotating the secret also changes the fingerprints, which intentionally prevents
long-term cross-secret linkability.

**Scope boundary**: These events go to the application's structured logger.
They are not a durable billing ledger or database-backed usage-history table.
For persistent tracking in a subsequent 10B3 increment, use a database-backed
append-only event store or durable log sink with retention/access controls. The
current 60-second Redis quota counters are not lifetime usage analytics.

**Important**: For 401/429 responses rejected before the route's separate
`require_internal_verification` dependency completes, the event may have no
actor fingerprint. This is intentional, to avoid attributing unverified
`X-Verified-User` header values to real users. Request ID, HTTP code, and
outcome still identify these events.

## Local verification (Windows PowerShell)

From the repository root:

```powershell
uv run ruff format apps/api/main.py apps/api/security/verification_audit.py tests/unit/test_phase10b3_verification_audit.py
uv run ruff check .
uv run ruff format --check .
uv run mypy apps ml scripts
uv run pytest tests/unit/test_phase10b3_verification_audit.py -v
uv run pytest
```

Production readiness still requires ensuring a log collector retains relevant
events securely, avoids unauthorized access, and applies sensible retention.
