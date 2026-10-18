# Phase 13B.2 — Keyless GDELT DOC discovery HTTP integration

**Scope:** An explicit `provider: "gdelt"` request to the existing restricted multi-source `/discover` API uses a keyless GDELT DOC article-list search to register URL, publisher, title, and discovery provenance via the existing transactional ingestion service. The existing `require_multisource_access` restriction stays intact. Legacy provider selection (`both`, `newsapi`, `google_factcheck`) is unchanged.

**Important:** Discovered URL metadata is **not** article text, evidence, independent verification, or a truth verdict. `independent_corroboration_established=False` remains unchanged. A GDELT `seendate` is an observation timestamp, not the article's publication date; `published_at` remains null. Only English-language matching is supported in this iteration, and empty responses do not imply false claims.

## Files

- `apps/api/connectors/gdelt.py`: new GDELT connector, no credentials; maps to existing contracts.
- `apps/api/connectors/contracts.py`: `Provider.GDELT_DOC` enum.
- `apps/api/connectors/http_client.py`: a single new HTTPS endpoint on the existing strict allowlist. No redirects, finite retries, bounded response, fixed timeouts.
- `apps/api/connectors/__init__.py`: exports the connector.
- `apps/api/services/multisource_discovery.py`: explicit GDELT routing and normal database discovery ingestion. All-provider transport errors are distinguished from missing credentials.
- `apps/api/schemas/multisource.py`: accepts `provider: "gdelt"` while retaining the default `both`.
- `apps/api/routes/multisource.py`: sanitized 502 when all selected providers fail.
- `tests/unit/test_phase13b2_gdelt_http.py`: offline MockTransport tests.

## Local-only installation

Phase 13B.1 (`apps/api/services/gdelt_metadata.py`) **must already be installed**. Extract this ZIP separately, and copy its relative paths to the repository on `feat/phase13-cross-source`. Do **not** commit, push, or deploy. Review tracked code changes with `git diff`.

Run these offline tests (requires the existing project's Python dependencies):

```powershell
python -m unittest discover -s tests/unit -p "test_phase13b_gdelt_metadata.py" -v
python -m unittest discover -s tests/unit -p "test_phase13b2_gdelt_http.py" -v
git diff --check
git status -sb
```

Once the local API, database and restricted operator route are running, an **authorized operator** may test discovery with the JSON body `{"query":"Eiffel Tower Paris","limit":5,"provider":"gdelt"}` at the existing multi-source discovery route. This is **not tested against the live GDELT service** in the offline unit suite. Avoid repeated rapid queries: public GDELT may rate limit.

## Phase 13B.3

Article content ingestion requires publisher permissions and an independent SSRF-resistant network fetcher with IP/DNS checks, rebinding safety, redirect limits, robots/terms controls, size and MIME limits, provenance tracking and audited tests. Do not fetch GDELT-returned article links with the provider HTTP client. Do not promote headlines or snippets to evidence.
