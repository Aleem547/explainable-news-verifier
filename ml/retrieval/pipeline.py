from dataclasses import dataclass
from typing import Protocol

from ml.retrieval.dense.bge_sentence_ranker import (
    DenseSentenceSearchResult,
)
from ml.retrieval.hybrid.rrf import (
    RankedSentence,
    reciprocal_rank_fusion,
)
from ml.retrieval.rerank.cross_encoder import (
    CrossEncoderSearchResult,
)
from ml.retrieval.sparse.bm25_sentence_ranker import (
    BM25SentenceRanker,
    SentenceDocument,
)
from ml.retrieval.sparse.tantivy_page_retriever import (
    PageSearchResult,
)


class PageRetrieverProtocol(Protocol):
    def search(
        self,
        query_text: str,
        *,
        limit: int = 10,
    ) -> list[PageSearchResult]: ...


class SentenceStoreProtocol(Protocol):
    def get_by_page_ids(
        self,
        page_ids: list[str],
    ) -> list[SentenceDocument]: ...


class DenseRankerProtocol(Protocol):
    def rank(
        self,
        query: str,
        documents: list[SentenceDocument],
        *,
        limit: int = 50,
    ) -> list[DenseSentenceSearchResult]: ...


class RerankerProtocol(Protocol):
    def rerank(
        self,
        query: str,
        documents: list[SentenceDocument],
        *,
        limit: int = 50,
    ) -> list[CrossEncoderSearchResult]: ...


@dataclass(frozen=True)
class RetrievalPipelineConfig:
    page_limit: int = 20
    sentence_source_depth: int = 100
    hybrid_limit: int = 50
    rrf_k: int = 60


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

    def retrieve(
        self,
        claim: str,
        *,
        top_k: int = 10,
    ) -> list[RetrievedEvidence]:
        normalized_claim = claim.strip()

        if not normalized_claim:
            return []

        if top_k <= 0:
            raise ValueError("top_k must be greater than zero.")

        page_results = self.page_retriever.search(
            normalized_claim,
            limit=self.config.page_limit,
        )

        if not page_results:
            return []

        page_rank_map = {page_result.page_id: page_result.rank for page_result in page_results}

        page_ids = [page_result.page_id for page_result in page_results]

        source_documents = self.sentence_store.get_by_page_ids(page_ids)

        if not source_documents:
            return []

        unique_documents: dict[
            tuple[str, int],
            SentenceDocument,
        ] = {}

        for source_document in source_documents:
            sentence_key = (
                source_document.page_id,
                source_document.sentence_id,
            )

            unique_documents.setdefault(
                sentence_key,
                source_document,
            )

        document_list = list(unique_documents.values())

        if not document_list:
            return []

        bm25_results = self.bm25_ranker.rank(
            normalized_claim,
            document_list,
            limit=(self.config.sentence_source_depth),
        )

        dense_results = self.dense_ranker.rank(
            normalized_claim,
            document_list,
            limit=(self.config.sentence_source_depth),
        )

        bm25_ranked = [
            RankedSentence(
                page_id=bm25_item.page_id,
                sentence_id=(bm25_item.sentence_id),
                rank=bm25_item.rank,
            )
            for bm25_item in bm25_results
        ]

        dense_ranked = [
            RankedSentence(
                page_id=dense_item.page_id,
                sentence_id=(dense_item.sentence_id),
                rank=dense_item.rank,
            )
            for dense_item in dense_results
        ]

        fused_results = reciprocal_rank_fusion(
            [
                bm25_ranked,
                dense_ranked,
            ],
            k=self.config.rrf_k,
            limit=self.config.hybrid_limit,
        )

        if not fused_results:
            return []

        document_map = {
            (
                source_document.page_id,
                source_document.sentence_id,
            ): source_document
            for source_document in document_list
        }

        bm25_score_map = {
            (
                bm25_item.page_id,
                bm25_item.sentence_id,
            ): bm25_item.score
            for bm25_item in bm25_results
        }

        dense_score_map = {
            (
                dense_item.page_id,
                dense_item.sentence_id,
            ): dense_item.score
            for dense_item in dense_results
        }

        rrf_score_map = {
            (
                fused_item.page_id,
                fused_item.sentence_id,
            ): fused_item.score
            for fused_item in fused_results
        }

        rerank_documents: list[SentenceDocument] = []

        for fused_item in fused_results:
            sentence_key = (
                fused_item.page_id,
                fused_item.sentence_id,
            )

            matched_document = document_map.get(sentence_key)

            if matched_document is None:
                continue

            rerank_documents.append(matched_document)

        if not rerank_documents:
            return []

        reranked_results = self.reranker.rerank(
            normalized_claim,
            rerank_documents,
            limit=min(
                top_k,
                len(rerank_documents),
            ),
        )

        evidence_results: list[RetrievedEvidence] = []

        for reranked_item in reranked_results:
            sentence_key = (
                reranked_item.page_id,
                reranked_item.sentence_id,
            )

            evidence_results.append(
                RetrievedEvidence(
                    rank=reranked_item.rank,
                    page_id=(reranked_item.page_id),
                    sentence_id=(reranked_item.sentence_id),
                    text=reranked_item.text,
                    page_rank=(page_rank_map.get(reranked_item.page_id)),
                    bm25_score=(bm25_score_map.get(sentence_key)),
                    dense_score=(dense_score_map.get(sentence_key)),
                    rrf_score=(
                        rrf_score_map.get(
                            sentence_key,
                            0.0,
                        )
                    ),
                    cross_encoder_score=(reranked_item.score),
                )
            )

        return evidence_results
