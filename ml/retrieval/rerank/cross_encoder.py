from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt
from sentence_transformers import CrossEncoder

from ml.retrieval.sparse.bm25_sentence_ranker import (
    SentenceDocument,
)

DEFAULT_CROSS_ENCODER_MODEL = "cross-encoder/ms-marco-MiniLM-L6-v2"


@dataclass(frozen=True)
class CrossEncoderSearchResult:
    rank: int
    page_id: str
    sentence_id: int
    text: str
    score: float


def build_pairs(
    query: str,
    documents: list[SentenceDocument],
) -> list[tuple[str, str]]:
    return [
        (
            query,
            document.text,
        )
        for document in documents
    ]


def rank_score_indices(
    scores: npt.NDArray[np.float32],
    *,
    limit: int,
) -> list[int]:
    if limit <= 0:
        raise ValueError("limit must be greater than zero.")

    if scores.ndim != 1:
        raise ValueError("scores must be one-dimensional.")

    result_limit = min(
        limit,
        scores.shape[0],
    )

    ranked = np.argsort(
        -scores,
        kind="stable",
    )[:result_limit]

    return [int(index) for index in ranked]


class CrossEncoderSentenceReranker:
    def __init__(
        self,
        *,
        model_name: str = (DEFAULT_CROSS_ENCODER_MODEL),
        device: str | None = None,
        batch_size: int = 32,
    ) -> None:
        if batch_size <= 0:
            raise ValueError("batch_size must be greater than zero.")

        self.model_name = model_name
        self.batch_size = batch_size

        self.model = CrossEncoder(
            model_name,
            device=device,
            max_length=512,
        )

    def rerank(
        self,
        query: str,
        documents: list[SentenceDocument],
        *,
        limit: int = 50,
    ) -> list[CrossEncoderSearchResult]:
        query = query.strip()

        if not query:
            return []

        if not documents:
            return []

        pairs = build_pairs(
            query,
            documents,
        )

        raw_scores: Any = self.model.predict(
            pairs,
            batch_size=self.batch_size,
            show_progress_bar=False,
        )

        scores = np.asarray(
            raw_scores,
            dtype=np.float32,
        ).reshape(-1)

        if scores.shape[0] != len(documents):
            raise ValueError("CrossEncoder returned an unexpected number of scores.")

        ranked_indices = rank_score_indices(
            scores,
            limit=limit,
        )

        results: list[CrossEncoderSearchResult] = []

        for rank, index in enumerate(
            ranked_indices,
            start=1,
        ):
            document = documents[index]

            results.append(
                CrossEncoderSearchResult(
                    rank=rank,
                    page_id=document.page_id,
                    sentence_id=(document.sentence_id),
                    text=document.text,
                    score=float(scores[index]),
                )
            )

        return results
