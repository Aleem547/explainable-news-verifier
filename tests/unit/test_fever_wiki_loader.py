import pytest

from ml.datasets.loaders.fever_wiki import (
    parse_wiki_page,
    parse_wiki_sentences,
)


def test_parse_standard_wiki_page() -> None:
    payload = {
        "id": "Albert_Einstein",
        "text": "Albert Einstein was a physicist.",
        "lines": ("0\tAlbert Einstein was a physicist.\n1\tHe developed the theory of relativity."),
    }

    page = parse_wiki_page(payload)

    assert page is not None
    assert page.page_id == "Albert_Einstein"
    assert page.text == ("Albert Einstein was a physicist.")


def test_parse_archive_quoted_keys() -> None:
    payload = {
        "'id'": "Albert_Einstein",
        "'text'": ("Albert Einstein was a physicist."),
        "'lines'": ("0\tAlbert Einstein was a physicist."),
    }

    page = parse_wiki_page(payload)

    assert page is not None
    assert page.page_id == "Albert_Einstein"


def test_blank_archive_record_is_skipped() -> None:
    payload = {
        "'id'": "",
        "'text'": "",
        "'lines'": "",
    }

    page = parse_wiki_page(payload)

    assert page is None


def test_parse_wiki_sentences() -> None:
    payload = {
        "id": "Albert_Einstein",
        "text": "Example",
        "lines": ("0\tAlbert Einstein was a physicist.\n1\tHe developed relativity."),
    }

    page = parse_wiki_page(payload)

    assert page is not None

    sentences = parse_wiki_sentences(page)

    assert len(sentences) == 2

    assert sentences[0].sentence_id == 0

    assert sentences[0].text == ("Albert Einstein was a physicist.")

    assert sentences[1].sentence_id == 1

    assert sentences[1].text == ("He developed relativity.")


def test_inline_link_metadata_is_preserved() -> None:
    payload = {
        "id": "Example_Page",
        "text": "Example",
        "lines": ("0\tExample sentence.\tLinked text\tLinked_Page"),
    }

    page = parse_wiki_page(payload)

    assert page is not None

    sentences = parse_wiki_sentences(page)

    assert len(sentences) == 1
    assert sentences[0].sentence_id == 0
    assert sentences[0].text == "Example sentence."

    assert "Linked text" in (sentences[0].raw_line)


def test_multiline_link_metadata_is_preserved() -> None:
    payload = {
        "id": "1971_Castrol_Trophy",
        "text": "Example",
        "lines": (
            "0\tFirst sentence.\n"
            "1\tThe event was staged at "
            "Warwick Farm.\t\n"
            "Warwick Farm\tWarwick Farm Raceway"
            "\tNew South Wales\tNew South Wales\n"
            "2\tThird sentence."
        ),
    }

    page = parse_wiki_page(payload)

    assert page is not None

    sentences = parse_wiki_sentences(page)

    assert len(sentences) == 3

    assert sentences[0].sentence_id == 0

    assert sentences[1].sentence_id == 1

    assert sentences[1].text == ("The event was staged at Warwick Farm.")

    assert "Warwick Farm Raceway" in (sentences[1].raw_line)

    assert sentences[2].sentence_id == 2
    assert sentences[2].text == "Third sentence."


def test_empty_sentence_text_is_preserved() -> None:
    payload = {
        "id": "Example_Page",
        "text": "Example",
        "lines": "2\t",
    }

    page = parse_wiki_page(payload)

    assert page is not None

    sentences = parse_wiki_sentences(page)

    assert len(sentences) == 1
    assert sentences[0].sentence_id == 2
    assert sentences[0].text == ""


def test_missing_page_id_with_content_is_rejected() -> None:
    payload = {
        "id": "",
        "text": "This record contains content.",
        "lines": "0\tExample sentence.",
    }

    with pytest.raises(
        ValueError,
        match="page id cannot be empty",
    ):
        parse_wiki_page(payload)
