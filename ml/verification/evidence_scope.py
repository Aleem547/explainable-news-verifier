"""Negative-only lexical scope checks for external evidence admission.

These bounded rules request review; passing them is not a semantic relevance
proof. They neither change raw NLI scores nor establish factual truth.
"""

from dataclasses import dataclass
import re
import unicodedata

SCOPE_POLICY_VERSION = "phase3.9-evidence-scope-review-v1"


@dataclass(frozen=True, slots=True)
class EvidenceScopeDecision:
    permitted: bool
    reason_codes: tuple[str, ...]
    policy_version: str = SCOPE_POLICY_VERSION


# Whole-passage abstention is intentional: a lexical rule cannot reliably
# separate an alleged proposition from a confirmed one elsewhere in the text.
_NON_FACTIVE = re.compile(
    r"\b(?:(?:alleged|alleges|alleging|claimed|claims|speculated|speculates)"
    r"\s+that|allegedly|reportedly|unconfirmed|rumou?red|rumou?rs?)\b"
)
_RECURRING_STATE = re.compile(
    r"\b(?:is|are|was|were)\s+(?:(?:not|still|temporarily|currently|fully)\s+)*"
    r"(?:open|closed|available|unavailable|operational|offline|online)\b"
)
_WEEKDAY = re.compile(
    r"\b(?:on|from|until|to|through|every|each)\s+"
    r"(monday|tuesday|wednesday|thursday|friday|saturday|sunday)s?\b"
)

# (event nouns in the claim, terminal outcomes in claim/evidence, earlier stages)
# Both positive and negative outcomes count as terminal tokens. This prevents a
# stage check from suppressing refutations merely for using an opposite outcome.
_EVENT_STAGES = (
    (
        frozenset({"application", "applications", "admission"}),
        frozenset({"accept", "accepts", "accepted", "acceptance", "admit", "admits", "admitted",
                   "approve", "approves", "approved", "reject", "rejects", "rejected",
                   "decline", "declines", "declined", "deny", "denies", "denied"}),
        frozenset({"submitted", "submit", "applied", "apply", "filed"}),
    ),
    (
        frozenset({"plan", "proposal", "amendment", "amendments", "bill"}),
        frozenset({"approve", "approves", "approved", "adopt", "adopts", "adopted",
                   "pass", "passes", "passed", "reject", "rejects", "rejected",
                   "defeat", "defeats", "defeated", "deny", "denies", "denied"}),
        frozenset({"proposed", "discussed", "discuss", "debated", "debate", "considered", "introduced", "submitted"}),
    ),
    (
        frozenset({"trial", "charge", "charges", "court"}),
        frozenset({"convict", "convicts", "convicted", "conviction",
                   "acquit", "acquits", "acquitted", "acquittal"}),
        frozenset({"accused", "charged", "indicted", "tried", "attended", "investigated"}),
    ),
)


def assess_evidence_scope(claim: str, evidence_text: str) -> EvidenceScopeDecision:
    """Abstain for specified unresolved attribution, weekday and stage patterns.

    This does not resolve pronouns, aliases, arbitrary dates, implicit time,
    multi-event narratives or all possible event-stage synonyms. Non-factive
    attribution can cause conservative abstention even in mixed passages or
    claims about allegations themselves. Such cases require further review.
    """
    if (not isinstance(claim, str) or not 3 <= len(claim.strip()) <= 2000
            or not isinstance(evidence_text, str) or not 1 <= len(evidence_text) <= 20_000):
        raise ValueError("invalid_evidence_scope_input")
    claim_text = " ".join(unicodedata.normalize("NFKC", claim).casefold().split())
    premise = " ".join(unicodedata.normalize("NFKC", evidence_text).casefold().split())
    reasons = []
    if _NON_FACTIVE.search(premise):
        reasons.append("NON_FACTIVE_ATTRIBUTION_REQUIRES_SCOPE_REVIEW")
    # Restrict this rule to recurring state claims. Different dates can be
    # genuine contradictions for a uniquely scheduled event; do not suppress
    # those using a blanket date-mismatch rule.
    if _RECURRING_STATE.search(claim_text) and _RECURRING_STATE.search(premise):
        claim_days, premise_days = set(_WEEKDAY.findall(claim_text)), set(_WEEKDAY.findall(premise))
        if claim_days and premise_days and claim_days.isdisjoint(premise_days):
            reasons.append("RECURRING_STATE_WEEKDAY_SCOPE_MISMATCH")
    claim_words = frozenset(re.findall(r"[a-z]+", claim_text))
    premise_words = frozenset(re.findall(r"[a-z]+", premise))
    for nouns, outcomes, earlier in _EVENT_STAGES:
        if (claim_words & nouns and claim_words & outcomes
                and premise_words & earlier and not premise_words & outcomes):
            reasons.append("EARLIER_EVENT_STAGE_DOES_NOT_ESTABLISH_OUTCOME")
            break
    codes = tuple(sorted(set(reasons)))
    return EvidenceScopeDecision(not codes, codes)
