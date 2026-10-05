from apps.api.services.retrieval import (
    clean_fever_text,
)


def test_clean_fever_parentheses() -> None:
    value = "Paris -LRB- France -RRB-"

    assert clean_fever_text(value) == "Paris ( France )"


def test_clean_fever_brackets() -> None:
    value = "Example -LSB- text -RSB-"

    assert clean_fever_text(value) == "Example [ text ]"


def test_clean_extra_whitespace() -> None:
    value = "The   Eiffel   Tower is in Paris ."

    assert clean_fever_text(value) == ("The Eiffel Tower is in Paris.")
