# Phase 9B — External News and Fact-Checking Connectors

This stage introduces **provider-specific article and fact-check discovery**. It performs **no full-article crawling, scraping, automatic database writes, claim verdicts, or corroboration scoring**. Those are later stages (9C–9F). It does **not** change the Phase 8 `/api/v1/verify` endpoint or alter the Phase 9A database migration.

## Providers

- **NewsAPI** `GET https://newsapi.org/v2/everything`: returns article URLs, source, titles, descriptions, publication timestamps. The `content` field is intentionally ignored because NewsAPI truncates it; the description is a preview, not extracted evidence. Requires a NewsAPI key to perform real calls and is subject to plan restrictions.
- **Google Fact Check Tools** `GET https://factchecktools.googleapis.com/v1alpha1/claims:search`: returns claims and published third-party reviews, with source publisher, article URL, review date and human-written textual rating. A publisher's rating is kept in `rating_text`, **not** interpreted as a verified model truth label. Requires a separately enabled API and a key for live requests.

Provider URLs are fixed (not supplied by user input). API keys are only passed as request headers, not URL parameters. Redirects are rejected; HTTP payloads and retry budgets are bounded; HTTP 429/503/etc. use short capped retries. URL canonicalization for returned **discovery metadata** is not SSRF protection: this module never fetches returned article URLs. Phase 9C must validate DNS/resolved addresses, redirects, network egress and article fetches before opening a discovered article URL.

## Windows install

1. Download the Phase 9B archive and save it under `Downloads`; keep the ZIP outside the project root.
2. From VS Code PowerShell, inspect ZIP contents if desired (`tar -tf ...`), then extract into `C:\Projects\explainable-news-verifier`.
3. Existing `httpx` is needed for connectors and mock HTTP tests. Check with `uv run python -c "import httpx; print(httpx.__version__)"`; if missing from the **project's dependencies**, install explicitly with `uv add httpx`.
4. From the repository root, run:

   ```powershell
   uv run ruff format .
   uv run ruff check .
   uv run ruff format --check .
   uv run mypy apps ml scripts
   uv run pytest
   uv run python -m scripts.connectors.check_phase9b
   ```

5. All tests run without network calls or credentials (httpx MockTransport). The CLI reports whether environment keys exist; it **never prints their values**.
6. Do **not** commit or push until Phase 9G. Continue to protect `.env`, raw data, model weights, reports and downloaded ZIPs.

## Optional live testing (not needed now)

In a secret-managed process environment, set `NEWSAPI_KEY` or `GOOGLE_FACTCHECK_API_KEY` to use the corresponding service. Keep keys out of source files, Git, logs, shell histories, screenshots, and exception messages. Real provider access may have account limits, terms of use, quotas or fees. No keys = no live outbound API calls.

```python
import asyncio
from apps.api.connectors.contracts import DiscoveryRequest
from apps.api.connectors.http_client import ProviderHttpClient, new_provider_http_client
from apps.api.connectors.registry import ConnectorConfiguration, build_connectors


async def run() -> None:
    cfg = ConnectorConfiguration.from_environment()
    async with new_provider_http_client() as client:
        for provider in build_connectors(ProviderHttpClient(client), cfg):
            result = await provider.search(DiscoveryRequest("Eiffel Tower", limit=5))
            print(result.provider, len(result.hits))


asyncio.run(run())
```

The code above is an illustrative opt-in call: it does **not** run during installation or startup. The app does not automatically import/connect to provider APIs. Publication timestamps are provider metadata, not independently validated truth. Distinct domains do not prove independent reporting; syndication and upstream copy detection will be built in Phase 9E.

## Phase 9A integration boundary

Existing `apps.api.services.source_registry.register_source`, `capture_document_version`, `record_retrieval_observation` and `attach_evidence_provenance` are intentionally **not** called in 9B: these discovery records do not yet contain verified article body text, passage offsets or document snapshots. Phase 9C will implement careful ingestion/persistence and identify what was actually fetched. Do not turn `snippet` into a `DocumentVersion` claiming to be article full text.

## Coverage and limitations

- Offline tests exercise schema normalization, retry limits, API-key isolation in request headers, truncation, malformed records, auth failures, refusal of redirects, output types and no-key behavior.
- No live provider connection has been tested in the packaging environment; your keys, permissions and quotas are unknown.
- In-process retry logic is not a distributed quota manager; a deployment will need a global rate limit and circuit breaker.
- This phase does not perform cross-source verification or independent-source reliability scoring.
