from ml.retrieval.dense.bge_sentence_ranker import (
    DenseSentenceSearchResult,
)
from ml.retrieval.pipeline import (
    EvidenceRetrievalPipeline,
    RetrievalPipelineConfig,
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


class FakePageRetriever:
    def search(
        self,
        query_text: str,
        *,
        limit: int = 10,
    ) -> list[PageSearchResult]:
        del query_text
        del limit

        return [
            PageSearchResult(
                rank=1,
                page_id="Albert_Einstein",
                title="Albert Einstein",
                score=10.0,
            )
        ]


class FakeSentenceStore:
    def get_by_page_ids(
        self,
        page_ids: list[str],
    ) -> list[SentenceDocument]:
        assert page_ids == ["Albert_Einstein"]

        return [
            SentenceDocument(
                page_id="Albert_Einstein",
                sentence_id=0,
                text=("Albert Einstein was a theoretical physicist."),
            ),
            SentenceDocument(
                page_id="Albert_Einstein",
                sentence_id=1,
                text=("Einstein developed the theory of relativity."),
            ),
        ]


class FakeDenseRanker:
    def rank(
        self,
        query: str,
        documents: list[SentenceDocument],
        *,
        limit: int = 50,
    ) -> list[DenseSentenceSearchResult]:
        del query
        del limit

        return [
            DenseSentenceSearchResult(
                rank=1,
                page_id=(documents[0].page_id),
                sentence_id=(documents[0].sentence_id),
                text=documents[0].text,
                score=0.9,
            )
        ]


class FakeReranker:
    def rerank(
        self,
        query: str,
        documents: list[SentenceDocument],
        *,
        limit: int = 50,
    ) -> list[CrossEncoderSearchResult]:
        del query

        return [
            CrossEncoderSearchResult(
                rank=index,
                page_id=document.page_id,
                sentence_id=(document.sentence_id),
                text=document.text,
                score=1.0,
            )
            for index, document in enumerate(
                documents[:limit],
                start=1,
            )
        ]


def test_retrieval_pipeline() -> None:
    pipeline = EvidenceRetrievalPipeline(
        page_retriever=(FakePageRetriever()),
        sentence_store=(FakeSentenceStore()),
        bm25_ranker=(BM25SentenceRanker()),
        dense_ranker=(FakeDenseRanker()),
        reranker=(FakeReranker()),
        config=(
            RetrievalPipelineConfig(
                page_limit=20,
                sentence_source_depth=10,
                hybrid_limit=10,
                rrf_k=60,
            )
        ),
    )

    results = pipeline.retrieve(
        "Albert Einstein was a physicist.",
        top_k=2,
    )

    assert results

    assert results[0].page_id == "Albert_Einstein"

    assert results[0].sentence_id == 0

    assert results[0].page_rank == 1


def test_empty_claim() -> None:
    pipeline = EvidenceRetrievalPipeline(
        page_retriever=(FakePageRetriever()),
        sentence_store=(FakeSentenceStore()),
        bm25_ranker=(BM25SentenceRanker()),
        dense_ranker=(FakeDenseRanker()),
        reranker=(FakeReranker()),
    )

    assert pipeline.retrieve("   ") == []
