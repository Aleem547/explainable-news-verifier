# Phase 10B3.2 — Postgres usage history

## What is stored

One row per **authenticated** POST `/api/v1/verify` request, **best effort**:
request ID (random 24 hex characters), pseudonymous HMAC actor fingerprint,
HTTP status code, outcome class, response time (milliseconds), and database
created-at timestamp. No claims, email addresses, IP addresses, OAuth subjects,
headers, service credentials or inference input/output text are stored.

The fingerprint uses the same `internal_api_token`-keyed HMAC established in
Phase 10B3.1. **Rotating the service token changes fingerprints**, splitting
usage history; a separate stable HMAC key and identity migration will be needed
before using these records for long-lived user analytics.

## Guarantees and limits

- Redis per-user and service rate limits remain authoritative; this new table
  is for usage reporting, not billing or enforcing quotas.
- A failing PostgreSQL write is logged with a request ID and exception **type**,
  and does not change the HTTP response. Process crashes and DB outages can
  therefore result in missing usage records. There is no exactly-once guarantee.
- The new middleware persistence defaults to **off** in isolated apps/tests,
  and is explicitly enabled in `apps/api/main.py`.
- Reads/usage dashboard are a later phase, so no new public user-data endpoint
  is exposed in this patch.
- Retention: run `scripts/usage/prune_verification_usage.py` as a scheduled
  operation after selecting a 90-day policy; script defaults to dry-run.
  It is not automatically scheduled in this patch.
- Before production rollout, limit DB permissions and validate migration/backups.
