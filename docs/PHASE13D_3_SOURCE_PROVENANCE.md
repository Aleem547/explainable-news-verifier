# Phase 13D.3 — Source Provenance Tracking

## Scope

`apps/api/services/external_evidence_provenance.py` provides a bounded, **read-only** validation step for candidates already returned by Phase 13D.1. It does not create evidence, download pages, evaluate claims with NLI, rank publishers, or establish source independence.

### Verification chain

`ExternalPassageCandidate` → `DocumentPassage` → latest `DocumentVersion` → `Document` → `Source` → matching `RetrievalObservation`.

The validator requires:

- exact match of candidate IDs, publisher and document URL against stored data;
- current/latest, immutable document version and passage text, offsets and SHA-256 hashes;
- a valid, canonical public HTTPS URL belonging to the registered publisher hostname or its subdomain;
- timezone-aware retrieval, observation and optional publication timestamps;
- a matching `secure_article_fetch_v1`, `FETCHED`, full-content retrieval observation, explicitly marked `independently_verified=False`;
- a bounded batch of 1–20 distinct passage UUIDs, parameterized SELECTs, and no database writes.

Any missing or contradictory provenance fails the whole batch. Results contain a fetch observation UUID, version number, snapshot hash, original passage offsets and reported publication timestamp. They **do not claim independent corroboration**, or prove the article's claims are true.

**Important terminology:** `AuditedExternalPassage.traceable=True` means *internally consistent evidence ancestry*. It is not a claim about external publisher trustworthiness, content accuracy or independence. Real-world author/publisher attribution still requires separate checks. The source domain is an identity from the stored source registry, not an attested publisher organization.

## Installation and tests (Windows PowerShell)

Use only branch `feat/phase13-cross-source`. Extract the package contents into the repository root, preserving folders.

```powershell
& .\.venv\Scripts\python.exe -m unittest discover -s tests/unit -p "test_phase13d3_external_provenance.py" -v
& .\.venv\Scripts\python.exe -m unittest discover -s tests/unit -p "test_phase13d2_evidence_normalization.py" -v
& .\scripts\phase13d3\run_local_provenance.ps1

git diff --check
git status -sb
```

Expected outcomes: 21 new provenance tests, 21 normalization regression tests, 1 **local** PostgreSQL integration test. The local integration test uses synthetic article text, a transaction that rolls back on success or failure, and connects only to `127.0.0.1:5432`. Docker Desktop and the already running dev PostgreSQL container are required. It neither contacts AWS nor requests live news pages.

The offline tests were run in a temporary environment assembled from the provided review ZIPs; the PostgreSQL test **has not** been executed against your Windows Docker instance yet.

## Usage

```python
candidates = await retrieve_external_passages(session, claim=claim, top_k=10)
audited = await audit_external_passage_provenance(session, candidates)
# Only use audited passages as candidate inputs for later independence/NLI logic.
# Do not equate `traceable` with `independent_corroboration_established`.
```

## Limitations and next steps

- The audit assumes `RetrievalObservation` records are populated by the authorized Phase 13C ingestion pipeline. This validator cannot prove the observation itself wasn't forged by a privileged database writer.
- No publisher authorization or cryptographic digital signature is verified. Hashes detect internal inconsistency, not whether an original publisher made the statement.
- Full-text extraction, source independence and NLI remain separate concerns.
- PostgreSQL query performance must be benchmarked as external corpora and observation history grow; avoid treating the initial implementation as production-scale optimization.
- Next is **13D.4 Source Independence Analysis**, where dependency relationships and syndicated/copy-paste reporting are assessed conservatively.

Do not merge into `main` or deploy to AWS until final validation.
