"""Conservative, optional query hints for finding pages about a claim subject.

Query hints are retrieval hypotheses, not verified entity resolutions. They
never establish support/refutation and must still pass reranking and NLI.
"""

import re

_PREDICATE = re.compile(
    r"\s+(?:is|are|was|were|has|have|had|contains?|includes?|became|"
    r"will|can|did|does|do)\b",
    flags=re.IGNORECASE,
)
_SEQUEL = re.compile(r"^(.+?)['\u2019]s sequel$", flags=re.IGNORECASE)
_WORDS = re.compile(r"[A-Za-z][A-Za-z0-9'\u2019-]*")
_FILM_CONTEXT = re.compile(
    r"\b(?:directed|filmed|shot|starring|produced|movie|film)\b",
    flags=re.IGNORECASE,
)
_ARTICLE = frozenset({"the", "a", "an"})
_GENERIC = frozenset({"some", "many", "most", "all", "every", "this", "that", "these", "those"})


def _named_subject(claim: str) -> str | None:
    """Extract an initial, visibly proper-name-like subject or return None."""
    match = _PREDICATE.search(claim)
    if match is None:
        return None
    subject = claim[: match.start()].strip(' "\u201c\u201d.,;:!?')
    tokens = _WORDS.findall(subject)
    if not 1 <= len(tokens) <= 7:
        return None
    if tokens[0].casefold() in _GENERIC:
        return None
    named = tokens[1:] if tokens[0].casefold() in _ARTICLE else tokens
    if not named or not named[0][0].isupper():
        return None
    # Avoid expanding generic sentence-case phrases such as "The army of men".
    # Compound proper names may contain lowercase connectors ("The King and I").
    if len(named) > 1 and not named[-1][0].isupper():
        # An explicitly possessive named subject is covered by the sequel rule.
        if not (len(named) == 2 and named[-1].casefold() == "sequel"):
            return None
    return " ".join(tokens)


def subject_search_queries(claim: str) -> list[str]:
    """Return at most two narrowly focused additional page-search queries.

    ``Rio's sequel`` -> ``Rio 2`` (a *hypothesis*) and ``Rio sequel film``.
    ``Due Date was only shot ...`` -> ``Due Date`` and ``Due Date film``.
    The original claim is always searched separately by the retrieval pipeline.
    """
    subject = _named_subject(claim)
    if subject is None:
        return []

    sequel = _SEQUEL.fullmatch(subject)
    if sequel is not None:
        base = sequel.group(1).strip()
        # Not a statement that the official title *is* base + "2".
        return [f"{base} 2", f"{base} sequel film"]

    queries = [subject]
    if _FILM_CONTEXT.search(claim) and not subject.casefold().endswith(" film"):
        queries.append(f"{subject} film")
    return queries
