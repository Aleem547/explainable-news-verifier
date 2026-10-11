# Phase 10C.2.2 — Internal retrieval latency investigation

Previous standalone verification measurements had a warm median of about 3.87 seconds, of which retrieval consumed about 3.6 seconds. That does not identify the internal retrieval bottleneck.

The current retrieval pipeline, preserved unchanged in this phase, follows:

1. Tantivy page search, optionally supplemented by subject-focused searches.
2. FEVER sentence-store loading by page IDs.
3. BM25 sentence ranking.
4. BGE dense sentence ranking.
5. Reciprocal-rank fusion of the sparse and dense lists.
6. Cross-encoder reranking of the fused candidates.

The factory currently sets `page_limit=20`, `sentence_source_depth=100`, `hybrid_limit=50`, and `rrf_k=60`; the reranker uses batch size 32. The wrapper script measures the actual component time without changing these values. It also reports the numbers of page-search calls, loaded pages/sentences, and dense/reranker inputs. `other` covers Python deduplication, sorting/formatting, and measurement overhead.

Do **not** reduce the page pool, sentence depth, hybrid depth, or reranker candidate count until evaluation confirms evidence recall, ranking quality, accepted evidence, and the final verdict are retained. A speed gain alone is insufficient. For the first benchmark, use the same claim as the prior baseline.

The benchmark does not connect to an external service, write user content, or modify the production application. Its timing wrappers temporarily replace attributes of a standalone pipeline instance and restore them on completion or exception. Do not use the profiler in a server process handling live requests.
