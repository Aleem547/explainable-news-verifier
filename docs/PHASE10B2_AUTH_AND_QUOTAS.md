# Phase 10B.2 — Identity and per-user inference quotas

## Trust boundaries

- **Browser -> Next.js:** Auth.js validates the user's Google OAuth session using an encrypted session token. Browser never sees the service API token.
- **Next.js -> FastAPI:** `X-Service-Token` authenticates the trusted Next.js service, `X-Verified-User` carries a stable provider subject derived **only from the server-side session**. The browser cannot choose this value.
- **FastAPI -> Redis:** separate server-wide and per-user atomic Redis quotas are enforced by distinct dependencies. Subject identifiers are hashed before use in Redis keys.
- **Production Next.js:** missing Auth.js / Google credentials or private service token means `/api/verification` fails closed. Unauthenticated requests return HTTP 401.
- **Production FastAPI:** expensive routes require the service token. `/api/v1/verify` also requires a server-asserted subject and its own quota. Internal endpoints such as classification/retrieval retain the service-wide quota only; they are not public browser routes.

## Important limitations

1. The first full Google OAuth login cannot be verified without Google credentials configured by the project owner. Do not consider this deployment-ready until successful manual OAuth and fail-closed tests.
2. This is per-provider-**account** rate limiting, not payment tier or anti-bot enforcement. A user with multiple OAuth accounts can evade per-account limits. Consider WAF, abuse analysis, CAPTCHA only when warranted, and account creation controls before a public launch.
3. Redis quotas use a fixed 60-second window. Bursts around a window boundary are possible; the global service quota and infrastructure-level concurrency limits mitigate cost but do not eliminate them.
4. JWT sessions don't provide instant server-side revocation without additional state. Consider a database-backed session strategy and incident-response flows for mature production releases.
5. Service token is a strong bearer secret. Protect and rotate it, use private networking and TLS, and consider short-lived workload identity for a mature deployment.
6. OAuth provider configuration, domain, HTTPS, cloud secret storage, staging and operational monitoring remain deployment tasks.
7. Avoid treating sentence-level NLI scores or single-corpus supporting evidence as independently corroborated truths.
