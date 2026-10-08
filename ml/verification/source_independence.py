"""Conservative grouping of document snapshots by evidence reuse, not truth.

Two different domains are *never* evidence of independent reporting. A family
means 'not safe to count separately' and is not a finding of reliability.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from itertools import combinations
from uuid import UUID

RULE_VERSION = "phase9e-v1"
_MIN_EXACT_WORDS = 12
_MIN_NEAR_WORDS = 80
_NEAR_JACCARD = 0.85
_WORD = re.compile(r"\w+", re.UNICODE)


class Relationship(StrEnum):
    SAME_PUBLISHER = "SAME_PUBLISHER"
    DECLARED_COMMON_ORIGIN = "DECLARED_COMMON_ORIGIN"
    IDENTICAL_TEXT = "IDENTICAL_TEXT"
    POSSIBLE_TEXT_REUSE = "POSSIBLE_TEXT_REUSE"
    UNDETERMINED = "UNDETERMINED"


@dataclass(frozen=True, slots=True)
class Snapshot:
    version_id: UUID
    source_id: UUID
    text: str
    # Only explicitly *reported* origins, never guessed from page-title/domain.
    reported_origin_url: str | None = None
    origin_observation_url: str | None = None


@dataclass(frozen=True, slots=True)
class PairFinding:
    left_version_id: UUID
    right_version_id: UUID
    relationship: Relationship
    group_together: bool
    basis: str
    shared_5gram_jaccard: float | None = None


@dataclass(frozen=True, slots=True)
class FamilyAssessment:
    version_ids: tuple[UUID, ...]
    pairs: tuple[PairFinding, ...]
    families: tuple[tuple[UUID, ...], ...]
    warnings: tuple[str, ...]
    rule_version: str = RULE_VERSION

    @property
    def family_count(self) -> int:
        return len(self.families)


def normalized_tokens(text: str) -> tuple[str, ...]:
    """Normalize casing and presentation, preserving words/numbers/negation."""
    text = unicodedata.normalize("NFKC", text).casefold()
    return tuple(_WORD.findall(text))


def _shingles(tokens: tuple[str, ...], width: int = 5) -> set[tuple[str, ...]]:
    return {tuple(tokens[i : i + width]) for i in range(len(tokens) - width + 1)}


def _origin_fingerprint(item: Snapshot) -> str | None:
    if item.reported_origin_url is None:
        return None
    if not item.origin_observation_url:
        raise ValueError("Origin attribution requires an observation URL")
    from ml.provenance.identity import canonical_public_url

    origin_url = canonical_public_url(item.reported_origin_url)
    canonical_public_url(item.origin_observation_url)
    return sha256(origin_url.encode("utf-8")).hexdigest()


def assess_source_independence(snapshots: list[Snapshot]) -> FamilyAssessment:
    """Group conservatively; nothing here proves actual editorial independence.

    Input must be unique, immutable document versions. Near matches need review;
    they are not automatically unioned. Never infer trust or claim truth.
    """
    if not 2 <= len(snapshots) <= 50:
        raise ValueError("Provide between 2 and 50 document snapshots")
    if len({row.version_id for row in snapshots}) != len(snapshots):
        raise ValueError("Document version IDs must be unique")
    if any(not row.text.strip() for row in snapshots):
        raise ValueError("Full snapshot text is required, not discovery snippets")
    sorted_rows = sorted(snapshots, key=lambda row: row.version_id.hex)
    tokens = {row.version_id: normalized_tokens(row.text) for row in sorted_rows}
    origins = {row.version_id: _origin_fingerprint(row) for row in sorted_rows}
    parents = {row.version_id: row.version_id for row in sorted_rows}

    def find(key: UUID) -> UUID:
        while key != parents[key]:
            key = parents[key]
        return key

    def union(left: UUID, right: UUID) -> None:
        root_left, root_right = find(left), find(right)
        if root_left != root_right:
            parents[max(root_left, root_right, key=lambda v: v.hex)] = min(
                root_left, root_right, key=lambda v: v.hex
            )

    findings: list[PairFinding] = []
    for left, right in combinations(sorted_rows, 2):
        lhs, rhs = tokens[left.version_id], tokens[right.version_id]
        similarity: float | None = None
        if left.source_id == right.source_id:
            relation = Relationship.SAME_PUBLISHER
            basis = "same_registered_source_id"
            group = True
        elif origins[left.version_id] and origins[left.version_id] == origins[right.version_id]:
            relation = Relationship.DECLARED_COMMON_ORIGIN
            basis = "matching_reported_origin_with_observation_urls"
            group = True
        elif lhs == rhs and len(lhs) >= _MIN_EXACT_WORDS:
            relation = Relationship.IDENTICAL_TEXT
            basis = "identical_normalized_full_snapshot_text"
            group = True
        elif len(lhs) >= _MIN_NEAR_WORDS and len(rhs) >= _MIN_NEAR_WORDS:
            left_set, right_set = _shingles(lhs), _shingles(rhs)
            similarity = len(left_set & right_set) / len(left_set | right_set)
            relation = (
                Relationship.POSSIBLE_TEXT_REUSE
                if similarity >= _NEAR_JACCARD
                else Relationship.UNDETERMINED
            )
            basis = (
                "five_word_shingle_similarity_review"
                if similarity >= _NEAR_JACCARD
                else "no_strong_reuse_signal"
            )
            group = False
        else:
            relation = Relationship.UNDETERMINED
            basis = "insufficient_evidence_of_shared_or_independent_reporting"
            group = False
        if group:
            union(left.version_id, right.version_id)
        findings.append(
            PairFinding(
                left_version_id=left.version_id,
                right_version_id=right.version_id,
                relationship=relation,
                group_together=group,
                basis=basis,
                shared_5gram_jaccard=similarity,
            )
        )

    components: dict[UUID, list[UUID]] = {}
    for row in sorted_rows:
        components.setdefault(find(row.version_id), []).append(row.version_id)
    families = tuple(
        sorted(
            (tuple(sorted(members, key=lambda v: v.hex)) for members in components.values()),
            key=lambda family: family[0].hex,
        )
    )
    warnings = ["INDEPENDENCE_NOT_PROVEN", "NO_CLAIM_TRUTH_INFERENCE"]
    if any(pair.relationship == Relationship.POSSIBLE_TEXT_REUSE for pair in findings):
        warnings.append("POSSIBLE_SYNDICATION_REQUIRES_REVIEW")
    if any(pair.relationship == Relationship.DECLARED_COMMON_ORIGIN for pair in findings):
        warnings.append("ORIGIN_ATTRIBUTION_NOT_INDEPENDENTLY_VERIFIED")
    return FamilyAssessment(
        version_ids=tuple(row.version_id for row in sorted_rows),
        pairs=tuple(findings),
        families=families,
        warnings=tuple(warnings),
    )
