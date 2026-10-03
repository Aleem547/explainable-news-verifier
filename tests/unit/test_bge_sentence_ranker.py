from ml.retrieval.dense.bge_sentence_ranker import (
    QUERY_INSTRUCTION,
    prepare_query,
)


def test_prepare_query() -> None:
    query = "Albert Einstein was a physicist."

    result = prepare_query(query)

    assert result == (QUERY_INSTRUCTION + query)


def test_prepare_query_strips_whitespace() -> None:
    result = prepare_query("   Eiffel Tower is in Paris   ")

    assert result == (QUERY_INSTRUCTION + "Eiffel Tower is in Paris")


def test_prepare_empty_query() -> None:
    assert prepare_query("   ") == ""
