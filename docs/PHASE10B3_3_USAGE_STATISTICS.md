# Phase 10B3.3 — Private user usage statistics

Source of truth: PostgreSQL `verification_usage_events`, written by Phase 10B3.2's audit middleware. Metrics are **best-effort telemetry**, not live quota balances or billing records.

The GET endpoint uses `require_internal_verification` for service-authenticated user identity. `get_usage_statistics()` uses the exact HMAC-SHA256 construction used by `VerificationAuditMiddleware`: first 24 hex characters of `HMAC(internal_api_token, verified_user_id)`. No client-supplied user selector can affect the query.

One SQL aggregation groups only matching actor rows by UTC day. The API supports 7, 30, and 90 day inclusive UTC windows, gap-filled to include days without events. HTTP statuses 200–299 count as successes, 429 as rate-limited, and other >=400 as failures. The mean latency is across all persisted events in the window.

A Next.js route obtains the stable user subject from Auth.js on the server and calls FastAPI with the private service token. It rejects redirects, non-HTTPS URLs in production, invalid session identities and malformed backend results. The account activity page consumes only the same-origin proxy. Responses are marked `Cache-Control: no-store`.

Operational limitations: users with no persisted events will see zeros. Historical events are retained only according to the retention policy. Do not use these counters for subscription enforcement or invoicing. Logging failures and database outages can omit usage events. Rate enforcement stays Redis-backed.
