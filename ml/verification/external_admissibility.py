"""Conservative text-only named-subject grounding for externally sourced passages.

This is not entity linking: when the claim's subject cannot be identified,
we abstain from decisive cross-source voting rather than inferring identity.
"""

import re

from ml.verification.decisive_admissibility import named_subject_anchor
from ml.verification.entity_relevance import normalized_words


def external_subject_grounded(claim: str, evidence_text: str) -> bool:
    anchor = named_subject_anchor(claim)
    if anchor is None:
        return False
    text = normalized_words(evidence_text)
    return bool(re.search(rf"(?<!\w){re.escape(anchor)}(?!\w)", text))
