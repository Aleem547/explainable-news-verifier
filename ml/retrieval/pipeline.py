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

        self.config = config or RetrievalPipelineConfig()

    def retrieve(
        self,
        claim: str,
        *,
        top_k: int = 10,
    ) -> list[RetrievedEvidence]:
        claim = claim.strip()

        if not claim:
            return []

        if top_k <= 0:
            raise ValueError("top_k must be greater than zero.")

        pages = self.page_retriever.search(
            claim,
            limit=self.config.page_limit,
        )

        if not pages:
            return []

        page_rank_map = {page.page_id: page.rank for page in pages}

        page_ids = [page.page_id for page in pages]

        documents = self.sentence_store.get_by_page_ids(page_ids)

        if not documents:
            return []

        unique_documents: dict[
            tuple[str, int],
            SentenceDocument,
        ] = {}

        for document in documents:
            key = (
                document.page_id,
                document.sentence_id,
            )

            unique_documents.setdefault(
                key,
                document,
            )

        document_list = list(unique_documents.values())

        bm25_results = self.bm25_ranker.rank(
            claim,
            document_list,
            limit=(self.config.sentence_source_depth),
        )

        dense_results = self.dense_ranker.rank(
            claim,
            document_list,
            limit=(self.config.sentence_source_depth),
        )

        bm25_ranked = [
            RankedSentence(
                page_id=result.page_id,
                sentence_id=(result.sentence_id),
                rank=result.rank,
            )
            for result in bm25_results
        ]

        dense_ranked = [
            RankedSentence(
                page_id=result.page_id,
                sentence_id=(result.sentence_id),
                rank=result.rank,
            )
            for result in dense_results
        ]

        fused = reciprocal_rank_fusion(
            [
                bm25_ranked,
                dense_ranked,
            ],
            k=self.config.rrf_k,
            limit=self.config.hybrid_limit,
        )

        if not fused:
            return []

        document_map = {
            (
                document.page_id,
                document.sentence_id,
            ): document
            for document in document_list
        }

        bm25_score_map = {
            (
                result.page_id,
                result.sentence_id,
            ): result.score
            for result in bm25_results
        }

        dense_score_map = {
            (
                result.page_id,
                result.sentence_id,
            ): result.score
            for result in dense_results
        }

        rrf_score_map = {
            (
                result.page_id,
                result.sentence_id,
            ): result.score
            for result in fused
        }

        rerank_documents: list[SentenceDocument] = []

        for result in fused:
            key = (
                result.page_id,
                result.sentence_id,
            )

            document = document_map.get(key)

            if document is not None:
                rerank_documents.append(document)

        reranked = self.reranker.rerank(
            claim,
            rerank_documents,
            limit=min(
                top_k,
                len(rerank_documents),
            ),
        )

        evidence: list[RetrievedEvidence] = []

        for result in reranked:
            key = (
                result.page_id,
                result.sentence_id,
            )

            evidence.append(
                RetrievedEvidence(
                    rank=result.rank,
                    page_id=result.page_id,
                    sentence_id=(result.sentence_id),
                    text=result.text,
                    page_rank=(page_rank_map.get(result.page_id)),
                    bm25_score=(bm25_score_map.get(key)),
                    dense_score=(dense_score_map.get(key)),
                    rrf_score=(
                        rrf_score_map.get(
                            key,
                            0.0,
                        )
                    ),
                    cross_encoder_score=(result.score),
                )
            )

        return evidence
