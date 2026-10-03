from ml.retrieval.hybrid.rrf import (
    RankedSentence,
    reciprocal_rank_fusion,
)


def test_rrf_promotes_shared_result() -> None:
    lexical = [
        RankedSentence(
            page_id="A",
            sentence_id=1,
            rank=1,
        ),
        RankedSentence(
            page_id="B",
            sentence_id=2,
            rank=2,
        ),
    ]

    dense = [
        RankedSentence(
            page_id="B",
            sentence_id=2,
            rank=1,
        ),
        RankedSentence(
            page_id="A",
            sentence_id=1,
            rank=2,
        ),
    ]

    results = reciprocal_rank_fusion(
        [
            lexical,
            dense,
        ]
    )

    assert len(results) == 2


def test_rrf_limit() -> None:
    ranking = [
        RankedSentence(
            page_id="A",
            sentence_id=1,
            rank=1,
        ),
        RankedSentence(
            page_id="B",
            sentence_id=2,
            rank=2,
        ),
    ]

    results = reciprocal_rank_fusion(
        [ranking],
        limit=1,
    )

    assert len(results) == 1


def test_rrf_invalid_k() -> None:
    try:
        reciprocal_rank_fusion(
            [],
            k=0,
        )
    except ValueError:
        pass
    else:
        raise AssertionError("Expected ValueError.")
