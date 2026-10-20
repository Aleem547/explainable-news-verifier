"""Phase 13D.2: bounded, provenance-preserving evidence normalization.

Only transforms already retrieved, unverified Phase 13D.1 evidence candidates.
Neither exact duplication nor lexical similarity demonstrates publication dependence,
source reliability, NLI entailment, or independent corroboration. In particular,
*near duplicate* groupings are tentative and MUST NOT suppress NLI assessment of
individual passages without additional checks in later Phase 13D stages.
"""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from urllib.parse import urlsplit
from uuid import UUID

from apps.api.services.external_passage_retrieval import ExternalPassageCandidate


class EvidenceNormalizationError(ValueError):
    """Untrusted candidate or invalid deduplication policy."""


@dataclass(frozen=True, slots=True)
class EvidenceNormalizationPolicy:
    max_candidates: int = 100
    max_passage_chars: int = 20_000
    min_near_duplicate_tokens: int = 24
    near_duplicate_jaccard: float = 0.92

    def __post_init__(self) -> None:
        if not 1 <= self.max_candidates <= 100:
            raise ValueError("invalid_max_candidates")
        if not 100 <= self.max_passage_chars <= 50_000:
            raise ValueError("invalid_max_passage_chars")
        if not 12 <= self.min_near_duplicate_tokens <= 100:
            raise ValueError("invalid_near_duplicate_token_limit")
        if not 0.90 <= self.near_duplicate_jaccard <= 1:
            raise ValueError("invalid_near_duplicate_threshold")


@dataclass(frozen=True, slots=True)
class NormalizedEvidence:
    candidate: ExternalPassageCandidate
    normalized_text: str
    normalized_sha256: str


@dataclass(frozen=True, slots=True)
class EvidenceDuplicateGroup:
    """All members remain accessible and individually attributable.

    match_types: for each member, 'representative', 'exact' or 'near'.
    A near match is a possible duplication, not proof of common reporting.
    """

    representative: NormalizedEvidence
    members: tuple[NormalizedEvidence, ...]
    match_types: tuple[str, ...]
    publisher_domains: tuple[str, ...]
    independently_verified: bool = False
    nli_evaluated: bool = False
    independent_corroboration_established: bool = False


@dataclass(frozen=True, slots=True)
class EvidenceNormalizationReport:
    groups: tuple[EvidenceDuplicateGroup, ...]
    input_count: int
    exact_duplicate_count: int
    possible_near_duplicate_count: int
    independently_verified: bool = False
    independent_corroboration_established: bool = False


# These are deliberately conservative: a single negation or numeral change can
# reverse a claim, even when most of two news passages remains identical.
_NEGATION = re.compile(
    r"\b(?:no|not|never|none|without|cannot|can't|won't|isn't|aren't|wasn't|"
    r"weren't|doesn't|didn't|don't|couldn't|shouldn't|wouldn't)\b",
    flags=re.IGNORECASE,
)
_NUMERIC = re.compile(r"\b\d+(?:[.,]\d+)*%?")
_TOKENS = re.compile(r"\w+(?:['’]\w+)?", flags=re.UNICODE)


def normalize_evidence_text(text: str) -> str:
    """Display normalization only; source text remains unchanged on candidates."""
    if not isinstance(text, str):
        raise EvidenceNormalizationError("invalid_evidence_text")
    normalized = unicodedata.normalize("NFKC", text)
    # Remove formatting/control characters other than whitespace, avoiding
    # hidden zero-width separators while retaining regular word spacing.
    normalized = "".join(
        " " if ch.isspace() else ch
        for ch in normalized
        if not unicodedata.category(ch).startswith("C") or ch.isspace()
    )
    return " ".join(normalized.split())


def _words(normalized_text: str) -> tuple[str, ...]:
    return tuple(_TOKENS.findall(normalized_text.casefold()))


def _shingles(words: tuple[str, ...], width: int = 4) -> frozenset[tuple[str, ...]]:
    return frozenset(tuple(words[i:i + width]) for i in range(len(words) - width + 1))


def _possible_near_duplicate(
    left: NormalizedEvidence,
    right: NormalizedEvidence,
    *,
    policy: EvidenceNormalizationPolicy,
) -> bool:
    first, second = _words(left.normalized_text), _words(right.normalized_text)
    if min(len(first), len(second)) < policy.min_near_duplicate_tokens:
        return False
    if _NUMERIC.findall(left.normalized_text) != _NUMERIC.findall(right.normalized_text):
        return False
    if _NEGATION.findall(left.normalized_text.casefold()) != _NEGATION.findall(right.normalized_text.casefold()):
        return False
    a, b = _shingles(first), _shingles(second)
    if not a or not b:
        return False
    return len(a & b) / len(a | b) >= policy.near_duplicate_jaccard


def _validate_candidate(candidate: ExternalPassageCandidate, policy: EvidenceNormalizationPolicy) -> None:
    if not isinstance(candidate, ExternalPassageCandidate):
        raise EvidenceNormalizationError("invalid_candidate_type")
    if (
        candidate.independently_verified
        or candidate.nli_evaluated
        or candidate.independent_corroboration_established
    ):
        raise EvidenceNormalizationError("already_assessed_candidate")
    if (
        not isinstance(candidate.passage_text, str)
        or not 1 <= len(candidate.passage_text) <= policy.max_passage_chars
        or not isinstance(candidate.passage_sha256, str)
        or sha256(candidate.passage_text.encode("utf-8")).hexdigest() != candidate.passage_sha256
    ):
        raise EvidenceNormalizationError("invalid_passage_integrity")
    if (
        not isinstance(candidate.rank, int)
        or candidate.rank < 1
        or not isinstance(candidate.lexical_relevance_score, (int, float))
        or not math.isfinite(candidate.lexical_relevance_score)
        or candidate.lexical_relevance_score <= 0
        or not isinstance(candidate.retrieved_at, datetime)
        or candidate.retrieved_at.tzinfo is None
        or candidate.retrieved_at.utcoffset() is None
        or not all(isinstance(value, UUID) for value in (
            candidate.passage_id, candidate.document_version_id,
            candidate.document_id, candidate.source_id,
        ))
        or not isinstance(candidate.publisher_domain, str)
        or not candidate.publisher_domain.strip()
        or not isinstance(candidate.original_url, str)
    ):
        raise EvidenceNormalizationError("invalid_candidate_provenance")
    url = urlsplit(candidate.original_url)
    if url.scheme != "https" or not url.hostname or url.username or url.password:
        raise EvidenceNormalizationError("invalid_candidate_url")


def normalize_and_group_external_evidence(
    candidates: tuple[ExternalPassageCandidate, ...] | list[ExternalPassageCandidate],
    *,
    policy: EvidenceNormalizationPolicy | None = None,
) -> EvidenceNormalizationReport:
    """Group exact and potential near-duplicates without losing attribution.

    Each source passage is retained. No NLI, source-independence, or veracity
    decision occurs here. Each near match is compared ONLY to the cluster's
    original representative, avoiding transitive similarity chains.
    """
    settings = policy or EvidenceNormalizationPolicy()
    if not isinstance(candidates, (tuple, list)) or len(candidates) > settings.max_candidates:
        raise EvidenceNormalizationError("candidate_limit_exceeded")

    verified: list[NormalizedEvidence] = []
    seen_ids: set[UUID] = set()
    for candidate in candidates:
        _validate_candidate(candidate, settings)
        if candidate.passage_id in seen_ids:
            raise EvidenceNormalizationError("duplicate_passage_id")
        seen_ids.add(candidate.passage_id)
        normalized = normalize_evidence_text(candidate.passage_text)
        if not normalized:
            raise EvidenceNormalizationError("empty_normalized_passage")
        verified.append(NormalizedEvidence(
            candidate=candidate,
            normalized_text=normalized,
            normalized_sha256=sha256(normalized.casefold().encode("utf-8")).hexdigest(),
        ))

    # Stable primary ordering: higher retrieval relevance first, then earlier
    # original rank and UUID for reproducible representatives.
    verified.sort(key=lambda x: (
        -x.candidate.lexical_relevance_score, x.candidate.rank, str(x.candidate.passage_id),
    ))
    groups: list[list[NormalizedEvidence]] = []
    kinds: list[list[str]] = []
    exact = near = 0
    for item in verified:
        match_group: int | None = None
        match_type = ""
        for index, members in enumerate(groups):
            representative = members[0]
            if any(item.normalized_sha256 == m.normalized_sha256 for m in members):
                match_group = index
                match_type = "exact"
                break
            if _possible_near_duplicate(item, representative, policy=settings):
                match_group = index
                match_type = "near"
                break
        if match_group is None:
            groups.append([item])
            kinds.append(["representative"])
        else:
            groups[match_group].append(item)
            kinds[match_group].append(match_type)
            if match_type == "exact":
                exact += 1
            else:
                near += 1

    output = tuple(EvidenceDuplicateGroup(
        representative=items[0],
        members=tuple(items),
        match_types=tuple(kinds[i]),
        publisher_domains=tuple(dict.fromkeys(
            item.candidate.publisher_domain for item in items
        )),
    ) for i, items in enumerate(groups))
    return EvidenceNormalizationReport(
        groups=output,
        input_count=len(verified),
        exact_duplicate_count=exact,
        possible_near_duplicate_count=near,
    )
