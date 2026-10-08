"""Conservative hygiene for retrieved FEVER sentences before NLI inference.

This module is not an authority or a source-reliability classifier. Its rules
remove navigation pages and repeated *text*, while avoiding semantic guesses.
"""

import re
from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher
from enum import StrEnum

from ml.retrieval.pipeline import RetrievedEvidence
from ml.verification.entity_relevance import entity_mismatch


class ExclusionReason(StrEnum):
    EMPTY_TEXT = "EMPTY_TEXT"
    DISAMBIGUATION_PAGE = "DISAMBIGUATION_PAGE"
    DUPLICATE_EVIDENCE_ID = "DUPLICATE_EVIDENCE_ID"
    DUPLICATE_TEXT = "DUPLICATE_TEXT"
    NEAR_DUPLICATE_SAME_PAGE = "NEAR_DUPLICATE_SAME_PAGE"
    ENTITY_VARIANT_MISMATCH = "ENTITY_VARIANT_MISMATCH"
    CANONICAL_PAGE_FOR_QUALIFIED_ENTITY = "CANONICAL_PAGE_FOR_QUALIFIED_ENTITY"


@dataclass(frozen=True)
class ExcludedEvidence:
    rank: int
    page_id: str
    sentence_id: int
    reason: ExclusionReason


@dataclass(frozen=True)
class EvidenceQualityResult:
    selected: list[RetrievedEvidence]
    excluded: list[ExcludedEvidence]
    unused_candidate_count: int


# FEVER's Wikipedia dump encodes certain punctuation as these tokens.
_FEVER_MARKUP = {
    "-lrb-": "(",
    "-rrb-": ")",
    "-lsb-": "[",
    "-rsb-": "]",
    "-lcb-": "{",
    "-rcb-": "}",
}
_WORDS = re.compile(r"\w+", flags=re.UNICODE)
_SPACES = re.compile(r"\s+")


def canonical_text(text: str) -> str:
    """Discard only casing, punctuation and whitespace differences."""
    prepared = text.casefold()
    for marker, replacement in _FEVER_MARKUP.items():
        prepared = prepared.replace(marker, replacement)
    return " ".join(_WORDS.findall(prepared))


def is_disambiguation_page(page_id: str) -> bool:
    """Detect FEVER page IDs such as Eiffel_Tower_-LRB-disambiguation-RRB-."""
    prepared = page_id.casefold()
    for marker, replacement in _FEVER_MARKUP.items():
        prepared = prepared.replace(marker, replacement)
    prepared = prepared.replace("_", " ")
    return bool(re.search(r"\(\s*disambiguation\s*\)$", prepared))


def _is_near_duplicate_same_page(
    item: RetrievedEvidence,
    prior: list[tuple[RetrievedEvidence, str]],
    canonical: str,
) -> bool:
    """Require identical lexical content AND almost identical ordering.

    The token-counter guard prevents merging sentences whose geographic names,
    numbers or negations differ, even if their edit similarity is extremely high.
    """
    if len(canonical) < 100:
        return False
    item_tokens = Counter(canonical.split())
    for previous, old_text in prior:
        if previous.page_id != item.page_id or len(old_text) < 100:
            continue
        if item_tokens != Counter(old_text.split()):
            continue
        if SequenceMatcher(None, canonical, old_text, autojunk=False).ratio() >= 0.98:
            return True
    return False


def screen_evidence(
    claim: str,
    candidates: list[RetrievedEvidence],
    *,
    top_k: int,
) -> EvidenceQualityResult:
    """Keep ranked, non-navigation and non-redundant evidence.

    The first/highest-ranked instance is retained. Excess distinct candidates
    are *unused*, not quality failures. This avoids falsely claiming they were
    screened out for poor quality.
    """
    if not 1 <= top_k <= 20:
        raise ValueError("top_k must be between 1 and 20.")

    selected: list[RetrievedEvidence] = []
    excluded: list[ExcludedEvidence] = []
    accepted_candidates: list[tuple[RetrievedEvidence, str]] = []
    seen_ids: set[tuple[str, int]] = set()
    seen_text: set[str] = set()
    unused_count = 0
    asks_about_disambiguation = "disambiguation" in claim.casefold()
    available_page_ids = [item.page_id for item in candidates]

    for item in candidates:
        canonical = canonical_text(item.text)
        reason: ExclusionReason | None = None
        evidence_id = (item.page_id, item.sentence_id)

        if not canonical:
            reason = ExclusionReason.EMPTY_TEXT
        elif is_disambiguation_page(item.page_id) and not asks_about_disambiguation:
            reason = ExclusionReason.DISAMBIGUATION_PAGE
        elif (mismatch := entity_mismatch(claim, item.page_id, available_page_ids)) is not None:
            reason = ExclusionReason(mismatch.value)
        elif evidence_id in seen_ids:
            reason = ExclusionReason.DUPLICATE_EVIDENCE_ID
        elif canonical in seen_text:
            reason = ExclusionReason.DUPLICATE_TEXT
        elif _is_near_duplicate_same_page(item, accepted_candidates, canonical):
            reason = ExclusionReason.NEAR_DUPLICATE_SAME_PAGE

        if reason is not None:
            excluded.append(
                ExcludedEvidence(
                    rank=item.rank,
                    page_id=item.page_id,
                    sentence_id=item.sentence_id,
                    reason=reason,
                )
            )
            continue

        # Keep a comparison history for unique candidates even after top_k
        # so quality exclusion counts remain meaningful for the whole pool.
        seen_ids.add(evidence_id)
        seen_text.add(canonical)
        accepted_candidates.append((item, canonical))
        if len(selected) < top_k:
            selected.append(item)
        else:
            unused_count += 1

    return EvidenceQualityResult(
        selected=selected,
        excluded=excluded,
        unused_candidate_count=unused_count,
    )
