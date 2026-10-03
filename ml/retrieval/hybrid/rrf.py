from collections.abc import Sequence
from dataclasses import dataclass

SentenceKey = tuple[str, int]


@dataclass(frozen=True)
class RankedSentence:
    page_id: str
    sentence_id: int
    rank: int


@dataclass(frozen=True)
class FusedSentence:
    page_id: str
    sentence_id: int
    rank: int
    score: float


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[RankedSentence]],
    *,
    k: int = 60,
    limit: int = 50,
) -> list[FusedSentence]:
    if k <= 0:
        raise ValueError("k must be greater than zero.")

    if limit <= 0:
        raise ValueError("limit must be greater than zero.")

    scores: dict[
        SentenceKey,
        float,
    ] = {}

    for ranking in rankings:
        seen: set[SentenceKey] = set()

        for item in ranking:
            key = (
                item.page_id,
                item.sentence_id,
            )

            if key in seen:
                continue

            seen.add(key)

            scores[key] = scores.get(key, 0.0) + 1.0 / (k + item.rank)

    ordered = sorted(
        scores.items(),
        key=lambda item: (
            -item[1],
            item[0][0],
            item[0][1],
        ),
    )

    results: list[FusedSentence] = []

    for rank, (
        key,
        score,
    ) in enumerate(
        ordered[:limit],
        start=1,
    ):
        results.append(
            FusedSentence(
                page_id=key[0],
                sentence_id=key[1],
                rank=rank,
                score=score,
            )
        )

    return results
