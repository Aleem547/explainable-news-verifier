from ml.retrieval.sparse.normalization import (
    normalize_query,
    normalize_wiki_title,
)


def test_normalize_wiki_title() -> None:
    assert normalize_wiki_title("Albert_Einstein") == "Albert Einstein"


def test_normalize_wiki_title_hyphen() -> None:
    assert normalize_wiki_title("New-York_City") == "New York City"


def test_normalize_query_whitespace() -> None:
    assert normalize_query("Albert   Einstein  was born") == "Albert Einstein was born"
