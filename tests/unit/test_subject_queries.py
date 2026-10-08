"""Focused regression tests for conservative subject query hypotheses."""

from ml.retrieval.subject_queries import subject_search_queries


def test_rio_sequel_is_a_search_hypothesis_not_an_asserted_alias() -> None:
    assert subject_search_queries("Rio's sequel is an American musical comedy film.") == [
        "Rio 2",
        "Rio sequel film",
    ]


def test_typographic_apostrophe_supported() -> None:
    assert subject_search_queries("Rio’s sequel is an American musical comedy film.") == [
        "Rio 2",
        "Rio sequel film",
    ]


def test_cincinnati_kid_finds_named_title() -> None:
    assert subject_search_queries("The Cincinnati Kid was directed by Norman Jewison in 1960.") == [
        "The Cincinnati Kid",
        "The Cincinnati Kid film",
    ]


def test_due_date_finds_named_film_title() -> None:
    assert subject_search_queries("Due Date was only shot in Maine.") == [
        "Due Date",
        "Due Date film",
    ]


def test_armed_force_subject() -> None:
    assert subject_search_queries("The Indian Army is an armed force.") == ["The Indian Army"]


def test_the_king_and_i_subject() -> None:
    assert subject_search_queries(
        "The King and I is based on a novel by an American writer born in 1903."
    ) == ["The King and I"]


def test_unsupported_generic_phrase_not_expanded() -> None:
    assert subject_search_queries("Most of the animals are nocturnal.") == []


def test_generic_lowercase_subject_not_expanded() -> None:
    assert subject_search_queries("The army of men is powerful.") == []


def test_empty_and_non_predicate() -> None:
    assert subject_search_queries("") == []
    assert subject_search_queries("What happened to Rio?") == []
