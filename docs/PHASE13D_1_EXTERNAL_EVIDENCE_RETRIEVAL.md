# Phase 13D.1 — External evidence candidate retrieval

This is a **read-only lexical candidate retrieval baseline** for authorized, stored, external article passages. It does **not** download live articles, infer truth, run DeBERTa, or establish source independence.

## Inputs and requirements

- 3–5000 character factual claim with at least one searchable Latin-alphanumeric term
- `top_k`: 1–20; `candidate_limit`: 1–100 and >= `top_k`
- Postgres 17 / SQLAlchemy async session; English full-text search (`websearch_to_tsquery`)
- Article documents with a **latest** immutable document-version snapshot, matching passages, an active source and an associated `secure_article_fetch_v1` **FETCHED** observation that explicitly records `independently_verified: false`

Pure discovery records, snippets and independent claims made by a third party **do not qualify**. The resolver always uses stored snapshots, never untrusted search result bodies.

The result includes passage ID, document ID and version ID, source ID, publisher name/domain, original URL, passage text and SHA-256, retrieval timestamp and lexical relevance score. Hashes and offsets are validated before results are returned. Any corrupted matching candidate fails the query closed. Scores are not probabilities and are not claim support/confidence values.

## Development testing

After copying the package files into `C:\Projects\explainable-news-verifier` on branch `feat/phase13-cross-source`:

```powershell
python -m unittest discover -s tests/unit -p 'test_phase13d1_external_retrieval.py' -v
& .\scripts\phase13d1\run_local_external_retrieval.ps1
git diff --check
```

The DB test uses local Docker PostgreSQL credentials with `127.0.0.1:5432` only, inserts **synthetic** publisher/article metadata, verifies the discovery-only exclusion and passage retrieval, and **rolls back** the transaction. No outbound HTTP or AWS access. It closes the connection pool. The test assumes the existing development database migrations are present.

## Known limitations / later subparts

- PostgreSQL full-text relevance (`english` dictionary) is a **lexical recall baseline**, not semantic BGE retrieval or cross-encoder reranking. It can miss paraphrases, non-English writing, negations, uncommon names and domain-specific terminology. Phase 13D.2/13D.5 extend ranking and NLI.
- The FTS expression has **no documented GIN index**. **Do not put this against a large production corpus** before an index plan, EXPLAIN/benchmark and resource safeguards. The LIMIT caps result count, not scan cost. The query is parameterized but cannot enforce a strict server-side runtime until DB statement timeouts are configured.
- Selected snapshots are the **latest version of each document**. Historic snapshots are not returned by this read path. This policy must be revisited for historical claim verification.
- Metadata labeled `independently_verified: false` means that the text is *not an established truth*. Later Phase 13D.3–D.7 perform provenance, source-family, NLI and corroboration decisions. URL/domain checks are not a claim of publisher independence.
- RSS/GDELT discovery success is separate from article-retention authorization. Fetch-and-store remains explicitly permission-gated; no publisher access rules are relaxed here.
- No API routes, migrations, workers, secrets, Docker images or frontend files are modified by this package.
