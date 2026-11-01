"""Phase 13F.4.57: bound, replayable reporting-origin dependency audit.

A URL, hash or reviewer-entered label is only an untrusted annotation; this
module cannot authenticate a publisher's original reporting or certify truth.
It binds annotations to a freshly recomputed NLI origin-review packet, detects
recorded reuse indicators and keeps every independence flag negative.

No network access, database writes, ML inference, or feature activation.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from uuid import UUID

from apps.api.services.external_evidence_agreement import ExternalAgreementReport
from apps.api.services.external_evidence_nli import ExternalNliReport
from apps.api.services.external_independence_review import (
    ExternalIndependenceReview,
    ExternalIndependenceReviewError,
    OriginReviewCandidate,
    build_external_independence_review,
)

ORIGIN_AUDIT_POLICY_VERSION = "phase13f-origin-dependency-audit-v2"

# Indications of shared reporting origins. Values must be supported by an
# externally auditable reference; this module does NOT authenticate the link.
DEPENDENCY_INDICATORS = frozenset({
    "SHARED_WIRE_STORY",
    "SYNDICATED_REPUBLICATION",
    "SHARED_PRIMARY_SOURCE",
    "COMMON_EDITORIAL_CONTROL",
    "CROSS_PUBLICATION_ATTRIBUTION",
    "DOCUMENTED_CONTENT_REUSE",
})
INCONCLUSIVE_INDICATORS = frozenset({
    "DISTINCT_ORIGIN_ASSERTED",
    "NO_DEPENDENCY_OBSERVED",
    "REPORTING_ORIGIN_UNKNOWN",
})
VALID_INDICATORS = DEPENDENCY_INDICATORS | INCONCLUSIVE_INDICATORS
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_OBSERVER = re.compile(r"[A-Za-z0-9_.:@-]{3,128}\Z")


class ReportingOriginAuditError(ValueError):
    """Invalid or inconsistent input; do not consume this audit."""


@dataclass(frozen=True, slots=True)
class ReportingOriginObservation:
    """Reviewer-supplied lead for subsequent trusted audit, NOT a verified fact."""

    left_passage_id: UUID
    right_passage_id: UUID
    indicator: str
    reference_url: str
    reference_sha256: str
    observer_label: str
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class OriginPairDependencyAssessment:
    pair: OriginReviewCandidate
    status: str  # DEPENDENCY_INDICATED, UNVERIFIED_ORIGIN_CLAIM, or NOT_REVIEWED
    indicators: tuple[str, ...]
    reference_sha256s: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReportingOriginAudit:
    review_packet_sha256: str
    audit_packet_sha256: str
    pairs: tuple[OriginPairDependencyAssessment, ...]
    observations_count: int
    dependency_indicated_pairs: int
    policy_version: str = ORIGIN_AUDIT_POLICY_VERSION
    independence_status: str = "NOT_ESTABLISHED"
    independent_corroboration_established: bool = False
    independently_verified: bool = False
    warnings: tuple[str, ...] = (
        "ORIGIN_ANNOTATIONS_NOT_AUTHENTICATED",
        "DIFFERENT_REPORTING_DOMAINS_ARE_NOT_PROOF_OF_INDEPENDENCE",
        "NO_POSITIVE_INDEPENDENCE_OR_FACTUAL_VERIFICATION_FROM_THIS_AUDIT",
    )
    # Retain the inputs privately so consumers can recompute the entire audit.
    # Never serialize these reviewer labels/reference URLs into public reports.
    observations: tuple[ReportingOriginObservation, ...] = ()


@dataclass(frozen=True, slots=True)
class ReportingOriginAuditSummary:
    """Public diagnostics only; every count describes unverified origin leads."""

    review_packet_sha256: str
    audit_packet_sha256: str
    candidate_pair_count: int
    dependency_indicated_pair_count: int
    unverified_origin_pair_count: int
    unreviewed_pair_count: int
    observations_count: int
    policy_version: str = ORIGIN_AUDIT_POLICY_VERSION


def _validate_reference(url: str) -> None:
    if not isinstance(url, str) or not 12 <= len(url) <= 2048 or url != url.strip():
        raise ReportingOriginAuditError("invalid_reference_url")
    try:
        parts = urlsplit(url)
    except ValueError as exc:
        raise ReportingOriginAuditError("invalid_reference_url") from exc
    if (parts.scheme != "https" or not parts.hostname or parts.username is not None
            or parts.password is not None or parts.fragment or "\\" in url
            or any(ch.isspace() or ord(ch) < 32 for ch in url)):
        raise ReportingOriginAuditError("invalid_reference_url")
    try:
        _ = parts.port
    except ValueError as exc:
        raise ReportingOriginAuditError("invalid_reference_url") from exc
    # No URL is fetched. Requiring a public-looking host prevents accidental
    # internal URLs from being accepted as audit references.
    hostname = parts.hostname
    if hostname == "localhost" or "." not in hostname:
        raise ReportingOriginAuditError("invalid_reference_url")
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        raise ReportingOriginAuditError("invalid_reference_url")


def assess_reporting_origin_dependencies(
    *,
    nli_report: ExternalNliReport,
    agreement_report: ExternalAgreementReport,
    independence_review: ExternalIndependenceReview,
    observations: tuple[ReportingOriginObservation, ...] = (),
) -> ReportingOriginAudit:
    """Recompute the upstream review; classify *indications*, never proof.

    This is a stateless, offline audit-readiness stage. A caller must supply
    separately authenticated acquisition and reviewer provenance before any
    later policy may make a positive independence assertion.
    """
    if not isinstance(independence_review, ExternalIndependenceReview):
        raise ReportingOriginAuditError("invalid_independence_review")
    try:
        expected = build_external_independence_review(
            nli_report=nli_report, agreement_report=agreement_report,
        )
    except (ExternalIndependenceReviewError, TypeError, AttributeError, ValueError) as exc:
        raise ReportingOriginAuditError("invalid_upstream_review") from exc
    if independence_review != expected:
        raise ReportingOriginAuditError("independence_review_mismatch")
    if type(observations) is not tuple or len(observations) > 100:
        raise ReportingOriginAuditError("invalid_observation_batch")

    pair_lookup = {
        (pair.left_passage_id, pair.right_passage_id): pair
        for pair in expected.review_candidates
    }
    by_pair: dict[tuple[UUID, UUID], list[ReportingOriginObservation]] = {}
    observed_keys: set[tuple[UUID, UUID, str, str]] = set()
    current = datetime.now(timezone.utc)

    for item in observations:
        if type(item) is not ReportingOriginObservation:
            raise ReportingOriginAuditError("invalid_observation_type")
        if (type(item.left_passage_id) is not UUID
                or type(item.right_passage_id) is not UUID):
            raise ReportingOriginAuditError("invalid_observation_pair_identity")
        pair_key = (item.left_passage_id, item.right_passage_id)
        if pair_key not in pair_lookup:
            raise ReportingOriginAuditError("observation_not_bound_to_review_pair")
        if type(item.indicator) is not str or item.indicator not in VALID_INDICATORS:
            raise ReportingOriginAuditError("invalid_origin_indicator")
        _validate_reference(item.reference_url)
        if type(item.reference_sha256) is not str or not _SHA.fullmatch(item.reference_sha256):
            raise ReportingOriginAuditError("invalid_reference_hash")
        if type(item.observer_label) is not str or not _OBSERVER.fullmatch(item.observer_label):
            raise ReportingOriginAuditError("invalid_observer_label")
        at = item.observed_at
        if (not isinstance(at, datetime) or at.tzinfo is None or at.utcoffset() is None
                or at < expected.assessed_at or at > current + timedelta(minutes=5)):
            raise ReportingOriginAuditError("invalid_observation_time")
        key = (*pair_key, item.indicator, item.reference_sha256)
        if key in observed_keys:
            raise ReportingOriginAuditError("duplicate_origin_observation")
        observed_keys.add(key)
        by_pair.setdefault(pair_key, []).append(item)

    results: list[OriginPairDependencyAssessment] = []
    for pair in expected.review_candidates:
        records = by_pair.get((pair.left_passage_id, pair.right_passage_id), [])
        indicators = tuple(sorted({r.indicator for r in records}))
        if DEPENDENCY_INDICATORS.intersection(indicators):
            status = "DEPENDENCY_INDICATED"
        elif indicators:
            status = "UNVERIFIED_ORIGIN_CLAIM"
        else:
            status = "NOT_REVIEWED"
        results.append(OriginPairDependencyAssessment(
            pair=pair,
            status=status,
            indicators=indicators,
            reference_sha256s=tuple(sorted({r.reference_sha256 for r in records})),
        ))

    # Sort every observation to make the packet insensitive to input order;
    # reference digest is an integrity token, NOT proof of reference content.
    normalized = sorted([
        [str(o.left_passage_id), str(o.right_passage_id), o.indicator,
         o.reference_url, o.reference_sha256, o.observer_label,
         o.observed_at.isoformat()]
        for o in observations
    ])
    payload = {
        "policy": ORIGIN_AUDIT_POLICY_VERSION,
        "upstream_review": expected.review_packet_sha256,
        "observations": normalized,
        "pair_statuses": [[str(r.pair.left_passage_id), str(r.pair.right_passage_id), r.status]
                          for r in results],
    }
    fingerprint = hashlib.sha256(json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    return ReportingOriginAudit(
        review_packet_sha256=expected.review_packet_sha256,
        audit_packet_sha256=fingerprint,
        pairs=tuple(results),
        observations_count=len(observations),
        dependency_indicated_pairs=sum(r.status == "DEPENDENCY_INDICATED" for r in results),
        observations=tuple(sorted(observations, key=lambda o: (
            o.left_passage_id.hex, o.right_passage_id.hex, o.indicator,
            o.reference_url, o.reference_sha256, o.observer_label,
            o.observed_at.isoformat(),
        ))),
    )


def summarize_reporting_origin_audit(
    *,
    nli_report: ExternalNliReport,
    agreement_report: ExternalAgreementReport,
    independence_review: ExternalIndependenceReview,
    audit: ReportingOriginAudit,
) -> ReportingOriginAuditSummary:
    """Rebuild from retained observations before trusting any audit diagnostics.

    Comparing only packet hashes would accept forged counts, statuses, flags,
    warnings or review pairs. Recompute and compare the complete immutable
    record; a matching hash still conveys integrity, never authentication.
    """
    if type(audit) is not ReportingOriginAudit:
        raise ReportingOriginAuditError("invalid_reporting_origin_audit")
    if (audit.independence_status != "NOT_ESTABLISHED"
            or audit.independent_corroboration_established is not False
            or audit.independently_verified is not False
            or type(audit.observations_count) is not int
            or type(audit.dependency_indicated_pairs) is not int
            or type(audit.pairs) is not tuple
            or any(type(pair) is not OriginPairDependencyAssessment for pair in audit.pairs)):
        raise ReportingOriginAuditError("invalid_reporting_origin_audit")
    expected = assess_reporting_origin_dependencies(
        nli_report=nli_report,
        agreement_report=agreement_report,
        independence_review=independence_review,
        observations=audit.observations,
    )
    if audit != expected:
        raise ReportingOriginAuditError("reporting_origin_audit_mismatch")
    return ReportingOriginAuditSummary(
        review_packet_sha256=expected.review_packet_sha256,
        audit_packet_sha256=expected.audit_packet_sha256,
        candidate_pair_count=len(expected.pairs),
        dependency_indicated_pair_count=expected.dependency_indicated_pairs,
        unverified_origin_pair_count=sum(
            pair.status == "UNVERIFIED_ORIGIN_CLAIM" for pair in expected.pairs
        ),
        unreviewed_pair_count=sum(pair.status == "NOT_REVIEWED" for pair in expected.pairs),
        observations_count=expected.observations_count,
    )
