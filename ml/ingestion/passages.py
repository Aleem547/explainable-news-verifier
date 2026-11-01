"""Deterministic lossless passage segmentation; offsets refer to original Unicode text.

No semantic assertion is made by a passage. No content is fetched from the network.
"""

from dataclasses import dataclass
import re

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


# This separate opt-in transformation does not alter split_passages, database
# passage boundaries, or stored identifiers. Consumers must record the actual
# derived input hash and offsets rather than reuse a parent passage's identity.
CONTEXT_POLICY_VERSION = "complete-line-paragraph-context-v1"


@dataclass(frozen=True, slots=True)
class ParagraphContext:
    ordinal: int
    parent_passage_ordinal: int
    parent_passage_sha256: str
    start_offset: int
    end_offset: int
    text: str
    sha256: str
    policy_version: str = CONTEXT_POLICY_VERSION


@dataclass(frozen=True, slots=True)
class ExcludedContext:
    start_offset: int
    end_offset: int
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ParagraphContextReport:
    contexts: tuple[ParagraphContext, ...]
    excluded: tuple[ExcludedContext, ...]
    policy_version: str = CONTEXT_POLICY_VERSION


def extract_paragraph_contexts(
    span: PassageSpan,
    *,
    document_length: int,
    max_chars: int = 800,
    max_contexts: int = 32,
) -> ParagraphContextReport:
    """Derive whole line-delimited paragraphs inside an exact parent span.

    The article extractor separates paragraphs with newlines. A newline is a
    structural boundary, not proof of semantic completeness or factual truth.
    First/last fragments at unknown parent boundaries are excluded. Long
    paragraphs and non-sentence headings are reported, never truncated. Every
    returned text is an exact substring with original document offsets.

    This function does not select by claim, NLI score, stance or publisher, and
    does not join paragraphs, delete qualifications, or change stored passages.
    Callers must keep exclusions and parent provenance visible. Line-wrapped
    inputs require a separately validated paragraph policy.
    """
    if type(span) is not PassageSpan:
        raise ValueError("invalid_parent_passage_type")
    if (type(document_length) is not int or not 1 <= document_length <= 2_000_000
            or type(max_chars) is not int or not 100 <= max_chars <= 4000
            or type(max_contexts) is not int or not 1 <= max_contexts <= 32):
        raise ValueError("invalid_context_limits")
    if (type(span.ordinal) is not int or span.ordinal < 0
            or type(span.start_offset) is not int or type(span.end_offset) is not int
            or not 0 <= span.start_offset < span.end_offset <= document_length
            or not isinstance(span.text, str) or not 1 <= len(span.text) <= 4000
            or len(span.text) != span.end_offset - span.start_offset
            or sha256_text(span.text) != span.sha256):
        raise ValueError("invalid_parent_passage_provenance")
    ranges = []
    cursor = 0
    for separator in re.finditer(r"\r\n|\r|\n", span.text):
        ranges.append((cursor, separator.start()))
        cursor = separator.end()
    ranges.append((cursor, len(span.text)))
    contexts, excluded = [], []
    for left, right in ranges:
        fragment = span.text[left:right]
        if not fragment.strip():
            continue
        # Trimming only outer whitespace adjusts offsets; source text within
        # the interval is never normalized or rewritten.
        first = left + len(fragment) - len(fragment.lstrip())
        last = right - (len(fragment) - len(fragment.rstrip()))
        text = span.text[first:last]
        reasons = []
        if left == 0 and span.start_offset != 0:
            reasons.append("UNPROVEN_LEFT_PARAGRAPH_BOUNDARY")
        if right == len(span.text) and span.end_offset != document_length:
            reasons.append("UNPROVEN_RIGHT_PARAGRAPH_BOUNDARY")
        if len(text) > max_chars:
            reasons.append("PARAGRAPH_EXCEEDS_CONTEXT_LIMIT")
        if not re.search(r"[.!?][\"'\u201d\u2019)\]]*$", text):
            reasons.append("NO_TERMINAL_SENTENCE_PUNCTUATION")
        start, end = span.start_offset + first, span.start_offset + last
        if reasons:
            excluded.append(ExcludedContext(start, end, tuple(reasons)))
            continue
        if len(contexts) >= max_contexts:
            raise ValueError("context_count_exceeds_limit")
        contexts.append(ParagraphContext(
            len(contexts), span.ordinal, span.sha256,
            start, end, text, sha256_text(text),
        ))
    return ParagraphContextReport(tuple(contexts), tuple(excluded))
