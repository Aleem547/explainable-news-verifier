"""Conservative named-subject grounding for decisive NLI evidence.

An NLI contradiction between two *different* named things is not a valid
refutation of the claim. This guard operates on the claim subject and the
retrieved page title/sentence, and deliberately abstains on ungrounded pairs.

This is NOT full entity linking or multi-hop reasoning. Keep raw NLI outputs
for auditing and assess real-world impact on held-out validation data.
"""

import re
from dataclasses import dataclass
from enum import StrEnum

from ml.verification.entity_relevance import normalized_words


class AdmissibilityReason(StrEnum):
    SUBJECT_NOT_GROUNDED = "SUBJECT_NOT_GROUNDED"


@dataclass(frozen=True)
class AdmissibilityDecision:
    permitted: bool
    reason: AdmissibilityReason | None = None
    named_subject: str | None = None


# Require an explicit simple copular/factual predicate. Without one, don't
# attempt a possibly incorrect subject extraction.
_PREDICATE = re.compile(
    r"\s+(?:is|are|was|were|has|have|had|contains?|included|includes|"
    r"became|becomes|produced|directed|written|released|located|situated)\b",
    flags=re.IGNORECASE,
)
_POSSESSIVE = re.compile(r"^([A-Z][\w-]*(?:\s+[A-Z][\w-]*)*)['\u2019]s\b")
_IN_LOCATION = re.compile(r"\s+(?:in|at|near)\s+", flags=re.IGNORECASE)
_WORD = re.compile(r"\b[A-Za-z][\w'-]*\b")
_GENERIC = frozenset(
    {"a", "an", "most", "some", "many", "all", "every", "this", "that", "these", "those"}
)


def named_subject_anchor(claim: str) -> str | None:
    """Return a high-precision initial named subject, or None when uncertain.

    Supported examples: "Rio's sequel is ...", "The Eiffel Tower is ...",
    "The King and I is ...", "Paris, Texas has ...".
    """
    original = claim.strip().strip('"\u201c\u201d')
    match = _PREDICATE.search(original)
    if match is None:
        return None

    subject = original[: match.start()].strip(" ,.;:!?\t")
    possessive = _POSSESSIVE.match(subject)
    if possessive is not None:
        subject = possessive.group(1)
    else:
        # "The Eiffel Tower in Paris, Texas" names the tower; the location
        # is a qualifier and the existing Phase 8B rule handles variants.
        subject = _IN_LOCATION.split(subject, maxsplit=1)[0].strip()

    tokens = _WORD.findall(subject)
    if not tokens:
        return None
    if tokens[0].casefold() in _GENERIC:
        return None
    if tokens[0].casefold() == "the":
        tokens = tokens[1:]
        if not tokens:
            return None
    if not tokens[0][0].isupper():
        return None
    # Don't mistake sentence-case generic subjects ("Most of the ...")
    # for proper names. The final subject token also needs title casing for
    # multiword subjects, except a proper name followed by a roman numeral.
    if len(tokens) > 1 and not tokens[-1][0].isupper():
        return None

    phrase = normalized_words(" ".join(tokens))
    return phrase or None


def _contains_phrase(haystack: str, phrase: str) -> bool:
    return bool(re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", haystack))


def check_decisive_admissibility(
    claim: str,
    page_id: str,
    evidence_text: str,
    nli_label: str,
) -> AdmissibilityDecision:
    """Require an explicit subject anchor for decisive entailment/refutation.

    Neutral evidence is never decisive and remains unmodified. Claims without
    a safely detected named subject use the legacy behavior; they are not
    automatically declared relevant.
    """
    if nli_label not in {"ENTAILMENT", "CONTRADICTION"}:
        return AdmissibilityDecision(permitted=True)
    anchor = named_subject_anchor(claim)
    if anchor is None:
        return AdmissibilityDecision(permitted=True)

    page = normalized_words(page_id)
    sentence = normalized_words(evidence_text)
    if _contains_phrase(page, anchor) or _contains_phrase(sentence, anchor):
        return AdmissibilityDecision(permitted=True, named_subject=anchor)

    return AdmissibilityDecision(
        permitted=False,
        reason=AdmissibilityReason.SUBJECT_NOT_GROUNDED,
        named_subject=anchor,
    )
