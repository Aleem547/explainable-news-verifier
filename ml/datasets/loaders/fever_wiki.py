from pydantic import BaseModel


class FeverWikiPage(BaseModel):
    page_id: str
    text: str
    lines: str


class FeverWikiSentence(BaseModel):
    page_id: str
    sentence_id: int
    text: str
    raw_line: str


def normalize_key(key: object) -> str:
    return str(key).strip().strip("'\"")


def normalize_payload(
    payload: dict[str, object],
) -> dict[str, object]:
    return {normalize_key(key): value for key, value in payload.items()}


def value_as_string(value: object | None) -> str:
    if value is None:
        return ""

    return str(value)


def parse_wiki_page(
    payload: dict[str, object],
) -> FeverWikiPage | None:
    normalized = normalize_payload(payload)

    page_id = value_as_string(normalized.get("id")).strip()

    text = value_as_string(normalized.get("text"))

    lines = value_as_string(normalized.get("lines"))

    if not page_id and not text.strip() and not lines.strip():
        return None

    if not page_id:
        raise ValueError("Wikipedia page id cannot be empty")

    return FeverWikiPage(
        page_id=page_id,
        text=text,
        lines=lines,
    )


def parse_wiki_sentences(
    page: FeverWikiPage,
) -> list[FeverWikiSentence]:
    sentences: list[FeverWikiSentence] = []

    if not page.lines.strip():
        return sentences

    for physical_line in page.lines.splitlines():
        if not physical_line.strip():
            continue

        first_field, separator, remainder = physical_line.partition("\t")

        if not separator:
            if sentences:
                sentences[-1].raw_line += "\n" + physical_line

            continue

        try:
            sentence_id = int(first_field)
        except ValueError:
            # FEVER occasionally stores hyperlink metadata
            # on a continuation line rather than on the
            # same physical line as the sentence.
            #
            # Example:
            #
            # 1<TAB>Sentence text<TAB>
            # Warwick Farm<TAB>Warwick Farm Raceway
            #
            # This is metadata belonging to the previous
            # sentence, not another sentence.
            if sentences:
                sentences[-1].raw_line += "\n" + physical_line

            continue

        sentence_text, _, _link_metadata = remainder.partition("\t")

        sentences.append(
            FeverWikiSentence(
                page_id=page.page_id,
                sentence_id=sentence_id,
                text=sentence_text.strip(),
                raw_line=physical_line,
            )
        )

    return sentences
