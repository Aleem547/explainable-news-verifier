from ml.retrieval.sparse.bm25_sentence_ranker import (
    BM25SentenceRanker,
    SentenceDocument,
    tokenize,
)


def test_tokenize() -> None:
    assert tokenize("Albert Einstein was a physicist.") == [
        "albert",
        "einstein",
        "was",
        "a",
        "physicist",
    ]


def test_rank_relevant_sentence_first() -> None:
    ranker = BM25SentenceRanker()

    documents = [
        SentenceDocument(
            page_id="Page_A",
            sentence_id=0,
            text=("Albert Einstein was a theoretical physicist."),
        ),
        SentenceDocument(
            page_id="Page_B",
            sentence_id=0,
            text=("Paris is the capital of France."),
        ),
        SentenceDocument(
            page_id="Page_C",
            sentence_id=0,
            text=("The Pacific Ocean is the largest ocean."),
        ),
    ]

    results = ranker.rank(
        "Albert Einstein was a physicist",
        documents,
    )

    assert results
    assert results[0].page_id == "Page_A"


def test_empty_documents() -> None:
    ranker = BM25SentenceRanker()

    assert (
        ranker.rank(
            "example query",
            [],
        )
        == []
    )


def test_invalid_limit() -> None:
    ranker = BM25SentenceRanker()

    documents = [
        SentenceDocument(
            page_id="Page_A",
            sentence_id=0,
            text="Example sentence.",
        )
    ]

    try:
        ranker.rank(
            "example",
            documents,
            limit=0,
        )
    except ValueError:
        pass
    else:
        raise AssertionError("Expected ValueError.")
