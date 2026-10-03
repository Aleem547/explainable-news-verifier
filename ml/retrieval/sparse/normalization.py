import re
import unicodedata

SEPARATOR_PATTERN = re.compile(r"[_\-]+")
WHITESPACE_PATTERN = re.compile(r"\s+")


def normalize_wiki_title(value: str) -> str:
    text = unicodedata.normalize("NFKC", value)

    text = SEPARATOR_PATTERN.sub(
        " ",
        text,
    )

    text = WHITESPACE_PATTERN.sub(
        " ",
        text,
    )

    return text.strip()


def normalize_query(value: str) -> str:
    text = unicodedata.normalize("NFKC", value)

    text = WHITESPACE_PATTERN.sub(
        " ",
        text,
    )

    return text.strip()
