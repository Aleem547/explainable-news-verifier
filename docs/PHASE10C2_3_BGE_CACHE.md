# Phase 10C.2.3 — BGE document embedding reuse

## Motivation
The local retrieval profiler showed BGE dense ranking taking roughly 2.1 s of a ~3.6 s warm retrieval. The ranker encoded ~70 candidate sentences every request, including repeated candidates from the same Wikipedia pages.

## Implementation
- Opt-in, **disabled by default** (`VERIFIER_BGE_DOCUMENT_CACHE_SIZE=0`).
- Reuse document vectors keyed by `(page_id, sentence_id, exact text)` within each `BGESentenceRanker` instance. Query embeddings are always recomputed.
- Keep normalized embeddings on the model's device; bounded `OrderedDict` LRU cache with a lock. Cache does not persist and is not shared across workers.
- Preserve original uncached `encode()` code path for size 0. Preserve downstream retrieval config, BGE scoring, RRF, reranking, NLI and API contracts.
- Clear manually with `clear_document_cache()` if model weights are modified in place.

## Limitations
- New candidate pages have no cache hits; cold starts and first requests remain costly.
- Shared sentence text across different page IDs is stored separately by design.
- Tensor bytes are bounded by the configured entry count, but memory includes metadata, model tensors and temporary batch buffers.
- Cache hits can produce tiny floating point score differences if original dynamically batched encoding had different padding/device kernels. The comparison script checks actual candidate identity, order and score tolerance. **Do not enable for production unless evaluation on representative diverse claims passes.**
- A cache is not a substitute for precomputed dense indexes, and does not improve independent-source evidence quality or user quotas.

## Acceptance
1. Existing backend tests pass, new 18 unit tests pass, and mypy/Ruff pass.
2. Local comparison reports no evidence identity, ordering, or score mismatch; compare multiple claim types before deployment.
3. Benchmark warm requests with caching on and off; document improvements and memory use.
4. Keep disabled in production until representative evaluation and approval.
