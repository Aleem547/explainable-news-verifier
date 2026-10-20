"""Phase 13D.4: conservative dependencies between full article snapshots.

This is NOT a classifier for editorial independence. Distinct publisher domains,
nonmatching text, and different risk families do not establish independence.
No external calls, persistence, credibility scoring, or factual conclusions occur.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from itertools import combinations
from uuid import UUID

from ml.provenance.identity import canonical_public_url
from ml.verification.source_independence import (
    Relationship, Snapshot, assess_source_independence, normalized_tokens,
)

RULE_VERSION = "phase13d4-risk-v1"


class SourceDependencyError(ValueError):
    """Incomplete, unbounded, or inconsistent dependency evidence."""


class ReportedDependencyKind(StrEnum):
    SHARED_WIRE_REPORT = "SHARED_WIRE_REPORT"
    SHARED_PRIMARY_SOURCE = "SHARED_PRIMARY_SOURCE"
    SHARED_PUBLISHER_OWNER = "SHARED_PUBLISHER_OWNER"


@dataclass(frozen=True, slots=True)
class ReportedDependency:
    """A *reported* link, with where/when it was observed, not confirmed fact."""

    left_version_id: UUID
    right_version_id: UUID
    kind: ReportedDependencyKind
    observation_url: str
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class DependencyPair:
    left_version_id: UUID
    right_version_id: UUID
    relationship: str
    reason: str
    grouped_as_dependency_risk: bool
    requires_review: bool
    observed_url: str | None = None
    fivegram_similarity: float | None = None


@dataclass(frozen=True, slots=True)
class DependencyRiskReport:
    version_ids: tuple[UUID, ...]
    # Groups of sources NOT safe to count as separate based on observed signals.
    risk_families: tuple[tuple[UUID, ...], ...]
    pairs: tuple[DependencyPair, ...]
    warnings: tuple[str, ...]
    rule_version: str = RULE_VERSION
    independence_status: str = "NOT_ESTABLISHED"
    independent_corroboration_established: bool = False
    independently_verified: bool = False
    nli_evaluated: bool = False

    @property
    def risk_family_count(self) -> int:
        return len(self.risk_families)


def _validate_snapshot(row: Snapshot) -> None:
    if not isinstance(row, Snapshot) or not isinstance(row.version_id, UUID) or not isinstance(row.source_id, UUID):
        raise SourceDependencyError("invalid_snapshot_identity")
    if not isinstance(row.text, str) or not 20 <= len(row.text) <= 100_000:
        raise SourceDependencyError("invalid_full_snapshot_text")
    if row.reported_origin_url is not None:
        if not row.origin_observation_url:
            raise SourceDependencyError("origin_observation_missing")
        for link in (row.reported_origin_url, row.origin_observation_url):
            try:
                canonical = canonical_public_url(link)
                if not canonical.startswith("https://"):
                    raise ValueError("HTTPS required")
            except (TypeError, ValueError) as exc:
                raise SourceDependencyError("invalid_origin_reference") from exc
    elif row.origin_observation_url is not None:
        raise SourceDependencyError("origin_without_attribution")


def assess_external_source_dependencies(
    snapshots: list[Snapshot] | tuple[Snapshot, ...],
    *,
    assessed_at: datetime,
    reported_links: tuple[ReportedDependency, ...] | list[ReportedDependency] = (),
) -> DependencyRiskReport:
    """Bounded, deterministic dependencies on *full*, immutable snapshots.

    Explicit dependency observations are conservatively grouped, but remain
    reported/unverified. Near matches are flagged but not silently unioned.
    The result never establishes independent reporting, even with many domains.
    """
    if not isinstance(assessed_at, datetime) or assessed_at.tzinfo is None or assessed_at.utcoffset() is None:
        raise SourceDependencyError("assessment_timestamp_must_be_aware")
    if not isinstance(snapshots, (tuple, list)) or not 2 <= len(snapshots) <= 20:
        raise SourceDependencyError("snapshot_batch_must_be_2_to_20")
    if not isinstance(reported_links, (tuple, list)) or len(reported_links) > 100:
        raise SourceDependencyError("too_many_reported_links")
    for row in snapshots:
        _validate_snapshot(row)
    keys = [row.version_id for row in snapshots]
    if len(set(keys)) != len(keys):
        raise SourceDependencyError("duplicate_snapshot_version")
    if sum(len(row.text) for row in snapshots) > 500_000:
        raise SourceDependencyError("snapshot_text_budget_exceeded")

    valid_ids = set(keys)
    links: dict[frozenset[UUID], ReportedDependency] = {}
    for item in reported_links:
        if not isinstance(item, ReportedDependency):
            raise SourceDependencyError("invalid_link")
        if (not isinstance(item.left_version_id, UUID) or not isinstance(item.right_version_id, UUID)
                or item.left_version_id == item.right_version_id
                or item.left_version_id not in valid_ids or item.right_version_id not in valid_ids):
            raise SourceDependencyError("unmatched_linked_versions")
        if not isinstance(item.kind, ReportedDependencyKind):
            raise SourceDependencyError("invalid_reported_dependency_kind")
        if (not isinstance(item.observed_at, datetime) or item.observed_at.tzinfo is None
                or item.observed_at.utcoffset() is None or item.observed_at > assessed_at):
            raise SourceDependencyError("invalid_link_observation_timestamp")
        try:
            uri = canonical_public_url(item.observation_url)
            if not uri.startswith("https://"):
                raise ValueError("HTTPS required")
        except (TypeError, ValueError) as exc:
            raise SourceDependencyError("invalid_link_observation_url") from exc
        pair_key = frozenset((item.left_version_id, item.right_version_id))
        if pair_key in links:
            raise SourceDependencyError("duplicate_pair_attribution")
        links[pair_key] = item

    # Reuse the established Phase 9 snapshot comparison to avoid diverging
    # rules for exact content, declared common origins, and long near matches.
    base = assess_source_independence(list(snapshots))
    parents = {key: key for key in base.version_ids}

    def find(key: UUID) -> UUID:
        while parents[key] != key:
            parents[key] = parents[parents[key]]
            key = parents[key]
        return key

    def union(left: UUID, right: UUID) -> None:
        root_a, root_b = find(left), find(right)
        if root_a != root_b:
            parents[max(root_a, root_b, key=lambda x: x.hex)] = min(root_a, root_b, key=lambda x: x.hex)

    by_id = {row.version_id: row for row in snapshots}
    base_pairs = {frozenset((p.left_version_id, p.right_version_id)): p for p in base.pairs}
    findings: list[DependencyPair] = []
    warnings = set(base.warnings)
    for left_id, right_id in combinations(base.version_ids, 2):
        base_pair = base_pairs[frozenset((left_id, right_id))]
        note = links.get(frozenset((left_id, right_id)))
        left = by_id[left_id]
        right = by_id[right_id]
        relation = base_pair.relationship.value
        reason = base_pair.basis
        grouped = base_pair.group_together
        review = base_pair.relationship in (Relationship.POSSIBLE_TEXT_REUSE, Relationship.UNDETERMINED)
        observation_url = None

        # Unmodified short identical full snapshots are the same publication
        # text even though Phase 9 deliberately requires 12 words for exact.
        lhs, rhs = normalized_tokens(left.text), normalized_tokens(right.text)
        if not grouped and len(lhs) >= 6 and lhs == rhs:
            relation, reason, grouped, review = (
                "IDENTICAL_SHORT_SNAPSHOT", "identical_full_text_at_least_six_words", True, False,
            )
        if note is not None:
            observation_url = canonical_public_url(note.observation_url)
            if not grouped:
                relation = f"REPORTED_{note.kind.value}"
                reason = "explicit_attributed_dependency_observation_not_independently_verified"
                grouped = True  # do not double-count sources when dependency is reported
            review = True  # origin and ownership statements still need validation
            warnings.add("REPORTED_RELATIONSHIP_REQUIRES_VERIFICATION")
        if base_pair.relationship == Relationship.POSSIBLE_TEXT_REUSE:
            warnings.add("POSSIBLE_SYNDICATION_REQUIRES_REVIEW")
        if grouped:
            union(left_id, right_id)
        findings.append(DependencyPair(
            left_version_id=left_id, right_version_id=right_id,
            relationship=relation, reason=reason,
            grouped_as_dependency_risk=grouped,
            requires_review=review,
            observed_url=observation_url,
            fivegram_similarity=base_pair.shared_5gram_jaccard,
        ))

    members: dict[UUID, list[UUID]] = {}
    for key in base.version_ids:
        members.setdefault(find(key), []).append(key)
    families = tuple(sorted(
        (tuple(sorted(group, key=lambda k: k.hex)) for group in members.values()),
        key=lambda group: group[0].hex,
    ))
    warnings.update((
        "DISTINCT_DOMAINS_DO_NOT_PROVE_INDEPENDENCE",
        "UNKNOWN_RELATIONSHIPS_CANNOT_BE_COUNTED_AS_INDEPENDENT",
        "NO_NLI_OR_TRUTH_ASSESSMENT",
    ))
    return DependencyRiskReport(
        version_ids=base.version_ids,
        risk_families=families,
        pairs=tuple(findings),
        warnings=tuple(sorted(warnings)),
    )
