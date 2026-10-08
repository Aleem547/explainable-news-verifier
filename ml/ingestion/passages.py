"""Deterministic lossless passage segmentation; offsets refer to original Unicode text.

No semantic assertion is made by a passage. No content is fetched from the network.
"""

from dataclasses import dataclass

from ml.provenance.identity import sha256_text


@dataclass(frozen=True, slots=True)
class PassageSpan:
    ordinal: int
    start_offset: int
    end_offset: int
    text: str
    sha256: str


def split_passages(text: str, *, max_chars: int = 800) -> tuple[PassageSpan, ...]:
    """Partition content exactly, preferring whitespace split points.

    Every original character belongs to exactly one span. Offset slicing recovers
    the exact original text; no truncation or approximate offset matching occurs.
    """
    if not 100 <= max_chars <= 4000:
        raise ValueError("max_chars must be between 100 and 4000")
    if not text or not text.strip():
        raise ValueError("Cannot index empty or whitespace-only content")
    if len(text) > 2_000_000:
        raise ValueError("Document exceeds the 2-million-character ingestion limit")

    pieces: list[PassageSpan] = []
    offset = 0
    while offset < len(text):
        end = min(offset + max_chars, len(text))
        if end < len(text):
            split = max(
                text.rfind(" ", offset + max_chars // 2, end),
                text.rfind("\n", offset + max_chars // 2, end),
            )
            if split > offset:
                end = split + 1
        fragment = text[offset:end]
        # Exact offsets and original spacing are part of the provenance record.
        pieces.append(PassageSpan(len(pieces), offset, end, fragment, sha256_text(fragment)))
        offset = end
    return tuple(pieces)
