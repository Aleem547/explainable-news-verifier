import numpy as np

from ml.retrieval.rerank.cross_encoder import (
    build_pairs,
    rank_score_indices,
)
from ml.retrieval.sparse.bm25_sentence_ranker import (
    SentenceDocument,
)


def test_build_pairs() -> None:
    documents = [
        SentenceDocument(
            page_id="A",
            sentence_id=0,
            text="First sentence.",
        ),
        SentenceDocument(
            page_id="B",
            sentence_id=1,
            text="Second sentence.",
        ),
    ]

    pairs = build_pairs(
        "Example claim",
        documents,
    )

    assert pairs == [
        (
            "Example claim",
            "First sentence.",
        ),
        (
            "Example claim",
            "Second sentence.",
        ),
    ]


def test_rank_score_indices() -> None:
    scores = np.asarray(
        [
            0.2,
            0.9,
            0.4,
        ],
        dtype=np.float32,
    )

    result = rank_score_indices(
        scores,
        limit=3,
    )

    assert result == [
        1,
        2,
        0,
    ]


def test_rank_score_indices_limit() -> None:
    scores = np.asarray(
        [
            0.2,
            0.9,
            0.4,
        ],
        dtype=np.float32,
    )

    result = rank_score_indices(
        scores,
        limit=2,
    )

    assert result == [
        1,
        2,
    ]
