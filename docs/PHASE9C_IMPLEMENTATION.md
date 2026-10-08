# Phase 9C — Discovery ingestion, snapshot passages and indexing preparation

**Compatible with the uploaded Phase 9A PostgreSQL model set and the Phase 9B
`ExternalDiscoveryHit` / `DiscoveryResult` contract.**

## Architecture and boundaries

This phase provides:

1. **Metadata discovery ingestion.** It accepts `DiscoveryResult` from the
   existing NewsAPI or Google Fact Check Tools connectors. Source and document
   registration are idempotent by normalized publisher domain and canonical URL.
   A new `discovery_records` table retains provider/query, discovered time,
   snippets and attributed third-party claim-review metadata.
2. **Explicitly authorized content ingestion.** `ingest_supplied_content` takes
   *actual text supplied by a caller who affirms storage permission*; it does
   not request arbitrary URLs or promote provider snippets into full articles.
   It uses Phase 9A `capture_document_version` to snapshot exact bytes/text.
3. **Passages.** `document_passages` stores character-exact, deterministic,
   version-linked passages for a *later* vector or sparse indexing worker.
   Offset slicing of the snapshot reproduces the original Unicode text.
4. **Index outbox.** A durable, unique `index_outbox` record is created per
   document version. Status `PENDING` means prepared, **not indexed in Qdrant**.
5. **Provenance.** `RetrievalObservation` is written when text is explicitly
   supplied and snapshotted, not for metadata-only discovery. Future claim-linked
   evidence can attach the existing Phase 9A `EvidenceProvenance` when verified.

A Google Fact Check Tools `textualRating` is stored as a *reviewer's published
statement*, not a system truth label. Neither a domain nor a source registry
entry implies independence or authority. SourceType's existing `NEWS` default
is unchanged; finer-grained publisher classifications belong in Phase 9D.

No live article HTML extractor or arbitrary URL fetching is included. Future
network fetching must enforce DNS/IP validation, redirect/IP revalidation,
robots/terms/licensing checks and bounded response sizes. Phase 9B only talks
with allowlisted provider JSON endpoints.

## Installation (Windows PowerShell, from repository root)

Back up `apps/api/db/models/__init__.py` before extraction (this package updates
that file). Download the package ZIP into Downloads, then:

```powershell
cd C:\Projects\explainable-news-verifier
Copy-Item apps\api\db\models\__init__.py "$env:TEMP\phase9c_models_init_backup.py"
Expand-Archive -LiteralPath "$HOME\Downloads\phase9c_implementation.zip" -DestinationPath . -Force
uv run ruff check . --fix
uv run ruff format .
uv run ruff check .
uv run mypy apps ml scripts
uv run pytest
uv run python -m scripts.ingestion.check_phase9c
uv run alembic current
uv run alembic heads
```

The **new head** is `9c36be16d992` and the previously applied database
revision is `9a16d02cbe34`. Run `uv run alembic upgrade head` **only on the
local development database**, after checking your PostgreSQL backup and .env.
Then verify with `uv run alembic current`.

Optional database write/rollback smoke check (after migration):

```powershell
uv run python -m scripts.ingestion.check_phase9c_database
```

This uses a synthetic `.invalid` hostname, creates a transaction, and rolls
back in `finally`. No outbound HTTP or test data persistence occurs.

## Application usage

```python
# Inside an existing AsyncSession transaction:
result = await newsapi_connector.search(DiscoveryRequest(query="example"))
await ingest_discovery_result(session, result)
# The connector offers article discovery only. Do NOT use snippet as full text.

# Later, only if you have lawfully and safely obtained full source content:
await ingest_supplied_content(
    session,
    url="https://news-publisher.example/specific-story",
    text=licensed_full_text,
    retrieved_at=aware_retrieval_time,
    storage_authorized=True,
)
# Caller decides to commit the transaction on success.
```

**No automatic database commit is performed by these services.** If any stage
fails, the caller should roll back the transaction. Both SQL `INSERT ... ON
CONFLICT DO NOTHING` and per-document row locking protect normal retry paths.

## Non-goals and remaining phases

- `index_outbox` entries are **not** indexed in Qdrant until a future worker
  consumes them; no misleading "indexed" status is returned.
- There is no web scraper or complete license-compliance implementation.
- Passage preparation is not claim-level evidence or a fact-check verdict.
- Duplicate URLs and exact content hashes do **not** prove independent sources.
- Integration of external retrieval into the claim verifier is scheduled later
  in Phase 9F/9G after independence analysis.
- The offline unit tests do not establish PostgreSQL migration success; the
  optional rollback test exercises PostgreSQL on your local machine.

GitHub commit and push remain deferred until Phase 9G, as agreed.
