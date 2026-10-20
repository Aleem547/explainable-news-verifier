# Phase 13C.2 — Secure article fetch primitive (development only)

This isolated Python module safely requests **already-discovered public HTML** for publishers explicitly approved in trusted **server-side** configuration. It must NOT be called directly with user-provided allowlists, and it is NOT wired to FastAPI, PostgreSQL, the public website, or AWS in this phase.

## Security choices

- Requires a `NEWS_ARTICLE` discovery hit whose normalized HTTPS host matches the publisher identity.
- Requires an explicit trusted publisher allowlist, defaulting to empty. Feed discovery alone is NOT publisher permission; review publisher terms, applicable robots directives and copyright before approving live fetching.
- Refuses non-standard ports, credentials, HTTP, IP-literal hostnames and host/publisher mismatches.
- Checks all DNS answers and refuses private, loopback, link-local, reserved and mixed DNS responses; requires at least one public IPv4.
- **Pins the TCP socket to the vetted IP**, while keeping the **original hostname for TLS SNI, certificate verification, and HTTP Host header**. This prevents DNS-rebinding between validation and connection.
- Refuses redirects and compressed responses rather than following unvalidated URLs or decompressing oversized payloads.
- Enforces bounded socket timeout and maximum retrieved HTML byte count; limited to `text/html`. No automatic retries, JavaScript, authentication, cookie handling, CAPTCHA or paywall bypass.
- Returns HTML **not verified evidence**. Trafilatura and subsequent evidence admissibility checks remain separate.

## Known limitations / next work

- `getaddrinfo()` runs using the OS DNS resolver; the application should execute this synchronous primitive in a worker thread with sensible external request concurrency limits. The deadline starts after DNS resolution, so this is not a strict total-end-to-end DNS deadline.
- IPv6-only sites and redirects are refused. Real publishers frequently redirect, so authorized redirect support will need per-hop DNS/IP revalidation, TLS verification and a strict hop cap in a later phase.
- HTTPS response may be legally restricted even if technically accessible; publisher permission/robots/license checks must be implemented as a separate service before enabling live article crawling.
- Publisher independence, full-text storage rights, semantic relevance and truth verification are NOT established here.
- All tests run fully offline using mocked DNS and pinned connections. A controlled egress-network test and security review are still required before enabling production.

## Windows tests

```powershell
cd C:\Projects\explainable-news-verifier
python -m unittest discover -s tests/unit -p "test_phase13c2_article_fetch.py" -v
python -m unittest discover -s tests/unit -p "test_phase13c1_article_extraction.py" -v
git diff --check
git status -sb
```

Do not run live article fetches or merge to `main` based only on offline unit tests.
