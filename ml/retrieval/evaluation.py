from collections.abc import Sequence


def first_relevant_rank(
    retrieved_pages: Sequence[str],
    gold_pages: set[str],
) -> int | None:
    for rank, page_id in enumerate(
        retrieved_pages,
        start=1,
    ):
        if page_id in gold_pages:
            return rank

    return None


def hit_at_k(
    retrieved_pages: Sequence[str],
    gold_pages: set[str],
    k: int,
) -> float:
    if not gold_pages:
        return 0.0

    retrieved_at_k = set(retrieved_pages[:k])

    return float(bool(retrieved_at_k & gold_pages))


def recall_at_k(
    retrieved_pages: Sequence[str],
    gold_pages: set[str],
    k: int,
) -> float:
    if not gold_pages:
        return 0.0

    retrieved_at_k = set(retrieved_pages[:k])

    relevant_found = retrieved_at_k & gold_pages

    return len(relevant_found) / len(gold_pages)


def reciprocal_rank(
    retrieved_pages: Sequence[str],
    gold_pages: set[str],
) -> float:
    rank = first_relevant_rank(
        retrieved_pages,
        gold_pages,
    )

    if rank is None:
        return 0.0

    return 1.0 / rank
