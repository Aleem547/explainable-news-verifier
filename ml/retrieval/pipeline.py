"""Hybrid FEVER evidence retrieval with opt-in subject-focused page discovery.

Baseline behavior is unchanged unless VERIFIER_SUBJECT_QUERY_EXPANSION=1 or
RetrievalPipelineConfig.enable_subject_query_expansion=True. Supplemental
queries only add page candidates; all sentences are scored against the
*original* claim using the existing BM25/dense/RRF/cross-encoder sequence.
"""

import os
from dataclasses import dataclass
from typing import Protocol

from ml.retrieval.dense.bge_sentence_ranker import DenseSentenceSearchResult
from ml.retrieval.hybrid.rrf import RankedSentence, reciprocal_rank_fusion
from ml.retrieval.rerank.cross_encoder import CrossEncoderSearchResult
from ml.retrieval.sparse.bm25_sentence_ranker import BM25SentenceRanker, SentenceDocument
from ml.retrieval.sparse.tantivy_page_retriever import PageSearchResult
from ml.retrieval.subject_queries import subject_search_queries


class PageRetrieverProtocol(Protocol):
    def search(self, query_text: str, *, limit: int = 10) -> list[PageSearchResult]: ...


class SentenceStoreProtocol(Protocol):
    def get_by_page_ids(self, page_ids: list[str]) -> list[SentenceDocument]: ...


class DenseRankerProtocol(Protocol):
    def rank(
        self, query: str, documents: list[SentenceDocument], *, limit: int = 50
    ) -> list[DenseSentenceSearchResult]: ...


class RerankerProtocol(Protocol):
    def rerank(
        self, query: str, documents: list[SentenceDocument], *, limit: int = 50
    ) -> list[CrossEncoderSearchResult]: ...


@dataclass(frozen=True)
class RetrievalPipelineConfig:
    page_limit: int = 20
    sentence_source_depth: int = 100
    hybrid_limit: int = 50
    rrf_k: int = 60
    enable_subject_query_expansion: bool = False
    subject_page_limit: int = 10
    max_pages_with_expansion: int = 32


@dataclass(frozen=True)
class RetrievedEvidence:
    rank: int
    page_id: str
    sentence_id: int
    text: str
    page_rank: int | None
    bm25_score: float | None
    dense_score: float | None
    rrf_score: float
    cross_encoder_score: float


class EvidenceRetrievalPipeline:
    def __init__(
        self,
        *,
        page_retriever: PageRetrieverProtocol,
        sentence_store: SentenceStoreProtocol,
        bm25_ranker: BM25SentenceRanker,
        dense_ranker: DenseRankerProtocol,
        reranker: RerankerProtocol,
        config: RetrievalPipelineConfig | None = None,
    ) -> None:
        self.page_retriever = page_retriever
        self.sentence_store = sentence_store
        self.bm25_ranker = bm25_ranker
        self.dense_ranker = dense_ranker
        self.reranker = reranker
        self.config = config if config is not None else RetrievalPipelineConfig()

    def _subject_queries_enabled(self) -> bool:
        # An environment switch works even when the existing factory passes
        # an explicit config instance, so no factory/API edits are needed.
        environment_enabled = os.getenv("VERIFIER_SUBJECT_QUERY_EXPANSION", "").strip()
        return self.config.enable_subject_query_expansion or environment_enabled == "1"

    def _find_pages(self, claim: str) -> tuple[list[str], dict[str, int]]:
        primary = self.page_retriever.search(claim, limit=self.config.page_limit)
        page_ids: list[str] = []
        page_rank_map: dict[str, int] = {}

        for result in primary:
            if result.page_id not in page_rank_map:
                page_ids.append(result.page_id)
                page_rank_map[result.page_id] = result.rank

        if not self._subject_queries_enabled():
            return page_ids, page_rank_map

        # This is a bounded candidate expansion, not a relevance or verdict
        # shortcut. In particular, ``Rio 2`` is merely a search hypothesis.
        page_cap = max(len(page_ids), self.config.max_pages_with_expansion)
        for query in subject_search_queries(claim):
            if len(page_ids) >= page_cap:
                break
            if query.casefold() == claim.casefold():
                continue
            extras = self.page_retriever.search(query, limit=self.config.subject_page_limit)
            for result in extras:
                if result.page_id in page_rank_map:
                    continue
                if len(page_ids) >= page_cap:
                    break
                page_ids.append(result.page_id)
                # Rank is an ordinal in the merged page candidate pool. Original
                # page ranks are never overwritten by supplemental search ranks.
                page_rank_map[result.page_id] = len(page_ids)

        return page_ids, page_rank_map

    def retrieve(self, claim: str, *, top_k: int = 10) -> list[RetrievedEvidence]:
        normalized_claim = claim.strip()
        if not normalized_claim:
            return []
        if top_k <= 0:
            raise ValueError("top_k must be greater than zero.")

        page_ids, page_rank_map = self._find_pages(normalized_claim)
        if not page_ids:
            return []
        source_documents = self.sentence_store.get_by_page_ids(page_ids)
        if not source_documents:
            return []

        unique_documents: dict[tuple[str, int], SentenceDocument] = {}
        for document in source_documents:
            unique_documents.setdefault((document.page_id, document.sentence_id), document)
        document_list = list(unique_documents.values())
        if not document_list:
            return []

        # Score all discovered sentences against the original claim, NOT an
        # expansion query. No subject match is treated as factual evidence.
        bm25_results = self.bm25_ranker.rank(
            normalized_claim,
            document_list,
            limit=self.config.sentence_source_depth,
        )
        dense_results = self.dense_ranker.rank(
            normalized_claim,
            document_list,
            limit=self.config.sentence_source_depth,
        )
        bm25_ranked = [
            RankedSentence(page_id=item.page_id, sentence_id=item.sentence_id, rank=item.rank)
            for item in bm25_results
        ]
        dense_ranked = [
            RankedSentence(page_id=item.page_id, sentence_id=item.sentence_id, rank=item.rank)
            for item in dense_results
        ]
        fused_results = reciprocal_rank_fusion(
            [bm25_ranked, dense_ranked],
            k=self.config.rrf_k,
            limit=self.config.hybrid_limit,
        )
        if not fused_results:
            return []

        document_map = {(item.page_id, item.sentence_id): item for item in document_list}
        bm25_score_map = {(item.page_id, item.sentence_id): item.score for item in bm25_results}
        dense_score_map = {(item.page_id, item.sentence_id): item.score for item in dense_results}
        rrf_score_map = {(item.page_id, item.sentence_id): item.score for item in fused_results}
        rerank_documents = [
            document_map[key]
            for item in fused_results
            if (key := (item.page_id, item.sentence_id)) in document_map
        ]
        if not rerank_documents:
            return []
        reranked_results = self.reranker.rerank(
            normalized_claim,
            rerank_documents,
            limit=min(top_k, len(rerank_documents)),
        )

        evidence_results: list[RetrievedEvidence] = []
        for item in reranked_results:
            key = (item.page_id, item.sentence_id)
            evidence_results.append(
                RetrievedEvidence(
                    rank=item.rank,
                    page_id=item.page_id,
                    sentence_id=item.sentence_id,
                    text=item.text,
                    page_rank=page_rank_map.get(item.page_id),
                    bm25_score=bm25_score_map.get(key),
                    dense_score=dense_score_map.get(key),
                    rrf_score=rrf_score_map.get(key, 0.0),
                    cross_encoder_score=item.score,
                )
            )
        return evidence_results
