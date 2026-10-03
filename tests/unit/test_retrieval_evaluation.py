from ml.retrieval.evaluation import (
    first_relevant_rank,
    hit_at_k,
    recall_at_k,
    reciprocal_rank,
)


def test_first_relevant_rank() -> None:
    retrieved = [
        "Page_A",
        "Page_B",
        "Page_C",
    ]

    gold = {
        "Page_B",
    }

    assert (
        first_relevant_rank(
            retrieved,
            gold,
        )
        == 2
    )


def test_first_relevant_rank_missing() -> None:
    retrieved = [
        "Page_A",
        "Page_B",
    ]

    gold = {
        "Page_X",
    }

    assert (
        first_relevant_rank(
            retrieved,
            gold,
        )
        is None
    )


def test_hit_at_k() -> None:
    retrieved = [
        "Page_A",
        "Page_B",
        "Page_C",
    ]

    gold = {
        "Page_C",
    }

    assert (
        hit_at_k(
            retrieved,
            gold,
            2,
        )
        == 0.0
    )

    assert (
        hit_at_k(
            retrieved,
            gold,
            3,
        )
        == 1.0
    )


def test_recall_at_k() -> None:
    retrieved = [
        "Page_A",
        "Page_B",
        "Page_C",
    ]

    gold = {
        "Page_A",
        "Page_C",
    }

    assert (
        recall_at_k(
            retrieved,
            gold,
            1,
        )
        == 0.5
    )

    assert (
        recall_at_k(
            retrieved,
            gold,
            3,
        )
        == 1.0
    )


def test_reciprocal_rank() -> None:
    retrieved = [
        "Page_A",
        "Page_B",
        "Page_C",
    ]

    gold = {
        "Page_B",
    }

    assert (
        reciprocal_rank(
            retrieved,
            gold,
        )
        == 0.5
    )
