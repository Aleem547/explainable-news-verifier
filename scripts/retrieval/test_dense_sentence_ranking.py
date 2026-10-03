from ml.retrieval.dense.bge_sentence_ranker import (
    BGESentenceRanker,
)
from ml.retrieval.sparse.bm25_sentence_ranker import (
    SentenceDocument,
)


def main() -> None:
    documents = [
        SentenceDocument(
            page_id="Albert_Einstein",
            sentence_id=0,
            text=("Albert Einstein was a German-born theoretical physicist."),
        ),
        SentenceDocument(
            page_id="Paris",
            sentence_id=0,
            text=("Paris is the capital and largest city of France."),
        ),
        SentenceDocument(
            page_id="Pacific_Ocean",
            sentence_id=0,
            text=("The Pacific Ocean is the largest ocean on Earth."),
        ),
    ]

    ranker = BGESentenceRanker()

    print(f"Model device: {ranker.device}")

    results = ranker.rank(
        "Albert Einstein worked as a physicist.",
        documents,
        limit=3,
    )

    print()

    for result in results:
        print(f"{result.rank}. {result.page_id}")

        print(f"   score: {result.score:.4f}")

        print(f"   {result.text}")


if __name__ == "__main__":
    main()
