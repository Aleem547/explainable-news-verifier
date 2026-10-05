from pathlib import Path

from ml.retrieval.dense.bge_sentence_ranker import (
    BGESentenceRanker,
)
from ml.retrieval.pipeline import (
    EvidenceRetrievalPipeline,
    RetrievalPipelineConfig,
)
from ml.retrieval.rerank.cross_encoder import (
    CrossEncoderSentenceReranker,
)
from ml.retrieval.sparse.bm25_sentence_ranker import (
    BM25SentenceRanker,
)
from ml.retrieval.sparse.tantivy_page_retriever import (
    TantivyPageRetriever,
)
from ml.retrieval.store.fever_sentence_store import (
    FeverSentenceStore,
)


def build_fever_retrieval_pipeline(
    project_root: Path,
    *,
    device: str = "cpu",
) -> EvidenceRetrievalPipeline:
    page_index = project_root / "data" / "indexes" / "fever" / "page_bm25"

    sentence_corpus = project_root / "data" / "processed" / "fever" / "wiki_sentences.parquet"

    return EvidenceRetrievalPipeline(
        page_retriever=(TantivyPageRetriever(page_index)),
        sentence_store=(FeverSentenceStore(sentence_corpus)),
        bm25_ranker=(BM25SentenceRanker()),
        dense_ranker=(
            BGESentenceRanker(
                device=device,
                batch_size=64,
            )
        ),
        reranker=(
            CrossEncoderSentenceReranker(
                device=device,
                batch_size=32,
            )
        ),
        config=RetrievalPipelineConfig(
            page_limit=20,
            sentence_source_depth=100,
            hybrid_limit=50,
            rrf_k=60,
        ),
    )
