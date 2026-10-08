"""Narrow page-title entity disambiguation for FEVER location claims.

This is a precision guard, NOT a knowledge-base entity linker. It only decides
when a title clearly refers to a sibling/qualified entity in a locative claim.
Uncertain evidence is left for the regular NLI/abstention path.
"""

import re
from dataclasses import dataclass
from enum import StrEnum


class EntityMismatch(StrEnum):
    ENTITY_VARIANT_MISMATCH = "ENTITY_VARIANT_MISMATCH"
    CANONICAL_PAGE_FOR_QUALIFIED_ENTITY = "CANONICAL_PAGE_FOR_QUALIFIED_ENTITY"


@dataclass(frozen=True)
class PageTitle:
    base: str
    qualifier: str | None


_MARKUP = {
    "-lrb-": "(",
    "-rrb-": ")",
    "-lsb-": "[",
    "-rsb-": "]",
}
_WORDS = re.compile(r"\w+", re.UNICODE)
_LOCATIVE = re.compile(
    r"\b(?:is|are|was|were)\s+(?:not\s+)?(?:located|situated|based)\s+in\b"
    r"|\b(?:is|are|was|were)\s+(?:not\s+)?in\b"
    r"|\b(?:stands|stood)\s+in\b",
)
_COMPARISON = re.compile(
    r"\b(?:replica|replicas|copy|copies|model|models|imitation|imitation[s]?|"
    r"different|multiple|versions?|inspired)\b",
)


def normalized_words(text: str) -> str:
    """Normalize title and claim punctuation without inventing entity mappings."""
    for marker, value in _MARKUP.items():
        text = re.sub(re.escape(marker), value, text, flags=re.IGNORECASE)
    return " ".join(_WORDS.findall(text.replace("_", " ").casefold()))


def parse_page_title(page_id: str) -> PageTitle:
    """Decode Wikipedia parenthetical qualifiers from FEVER IDs."""
    text = page_id.replace("_", " ")
    for marker, replacement in _MARKUP.items():
        text = re.sub(re.escape(marker), replacement, text, flags=re.IGNORECASE)
    match = re.fullmatch(r"(.*?)\s*\(([^()]*)\)\s*", text)
    if match:
        return PageTitle(normalized_words(match.group(1)), normalized_words(match.group(2)))
    return PageTitle(normalized_words(text), None)


def _contains_phrase(text: str, phrase: str) -> bool:
    return bool(phrase) and bool(re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text))


def _explicit_subject_variant(claim: str, base: str, qualifier: str) -> bool:
    """Only accept a qualifier as a subject anchor directly after the title."""
    return bool(
        re.search(
            rf"(?<!\w){re.escape(base)}\s+(?:in|at|near)\s+"
            rf"{re.escape(qualifier)}(?!\w)",
            claim,
        )
    )


def entity_mismatch(
    claim: str,
    page_id: str,
    available_page_ids: list[str],
) -> EntityMismatch | None:
    """Reject provably off-target title variants for narrowly scoped location claims.

    The unqualified title is preferred for an unqualified location claim when
    present. Without it, only comma-qualified siblings are screened; single-word
    or occupation qualifiers remain undecided to avoid over-exclusion.
    """
    normalized_claim = normalized_words(claim)
    if not _LOCATIVE.search(normalized_claim) or _COMPARISON.search(normalized_claim):
        return None

    title = parse_page_title(page_id)
    if len(title.base.split()) < 2 or not _contains_phrase(normalized_claim, title.base):
        return None

    siblings = [parse_page_title(page) for page in available_page_ids]
    siblings = [sibling for sibling in siblings if sibling.base == title.base]

    scoped_qualifiers = {
        sibling.qualifier
        for sibling in siblings
        if sibling.qualifier is not None
        and _explicit_subject_variant(normalized_claim, title.base, sibling.qualifier)
    }

    if title.qualifier is None:
        if scoped_qualifiers:
            return EntityMismatch.CANONICAL_PAGE_FOR_QUALIFIED_ENTITY
        return None

    if title.qualifier in scoped_qualifiers:
        return None

    # The claimed destination may match a sibling qualifier without referring to
    # that sibling. Only an explicit subject anchor above disambiguates it.
    canonical_present = any(sibling.qualifier is None for sibling in siblings)
    # Recognize 'Paris, Texas' as a multi-part location, not 'film director'.
    explicit_geo_qualifier = "," in page_id.rsplit("-LRB-", maxsplit=1)[-1]
    if canonical_present or explicit_geo_qualifier:
        return EntityMismatch.ENTITY_VARIANT_MISMATCH
    return None
