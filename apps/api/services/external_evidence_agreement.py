"""Phase 13D.6: provisional agreement/conflict diagnostics over validated NLI.

Pure/read-only: no database calls, network requests, model execution, factual
verdicts, or independent corroboration claims. Downstream Phase 13D.7 must
make any admissibility/corroboration determination independently.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from uuid import UUID

from apps.api.services.external_evidence_nli import ExternalNliPassage, ExternalNliReport


class EvidenceAgreementError(ValueError):
    """An upstream report is incomplete, inconsistent or unsafe to aggregate."""


@dataclass(frozen=True, slots=True)
class AgreementUnit:
    """A *dependency-risk* unit, NOT an independently verified source."""

    risk_family_ids: tuple[int, ...]
    passage_ids: tuple[UUID, ...]
    document_version_ids: tuple[UUID, ...]
    source_ids: tuple[UUID, ...]
    article_urls: tuple[str, ...]
    duplicate_groups: tuple[int, ...]
    support_passage_ids: tuple[UUID, ...]
    refute_passage_ids: tuple[UUID, ...]
    inconclusive_passage_ids: tuple[UUID, ...]
    stance: str  # SUPPORT_ONLY, REFUTE_ONLY, MIXED, NO_DECISIVE_EVIDENCE


@dataclass(frozen=True, slots=True)
class ExternalAgreementReport:
    claim: str
    assessed_at: datetime
    nli_threshold: float
    evidence: tuple[ExternalNliPassage, ...]
    units: tuple[AgreementUnit, ...]
    total_passages: int
    decisive_passages: int
    inconclusive_passages: int
    raw_dependency_risk_family_count: int
    provisional_agreement_unit_count: int
    supporting_unit_count: int
    refuting_unit_count: int
    mixed_unit_count: int
    inconclusive_unit_count: int
    has_opposing_evidence: bool
    has_within_unit_conflict: bool
    evidence_status: str
    warnings: tuple[str, ...]
    # Explicitly provisional: a different publisher or agreement is NOT proof
    # of source independence, real-world fact, or calibrated claim truth.
    independence_status: str = "NOT_ESTABLISHED"
    independently_verified: bool = False
    independent_corroboration_established: bool = False


def _validate_report(report: ExternalNliReport) -> None:
    if not isinstance(report, ExternalNliReport):
        raise EvidenceAgreementError("invalid_nli_report_type")
    if not isinstance(report.claim, str) or not 3 <= len(report.claim.strip()) <= 2000:
        raise EvidenceAgreementError("invalid_claim")
    at = report.assessed_at
    if not isinstance(at, datetime) or at.tzinfo is None or at.utcoffset() is None:
        raise EvidenceAgreementError("invalid_assessment_time")
    threshold = report.nli_threshold
    if (not isinstance(threshold, (int, float)) or isinstance(threshold, bool)
            or not math.isfinite(threshold) or not 0.5 <= threshold <= 1.0):
        raise EvidenceAgreementError("invalid_threshold")
    if (report.independence_status != "NOT_ESTABLISHED"
            or report.independently_verified is not False
            or report.independent_corroboration_established is not False):
        raise EvidenceAgreementError("upstream_report_claims_independence")
    if (not isinstance(report.evidence, tuple)
            or not 2 <= len(report.evidence) <= 20):
        raise EvidenceAgreementError("invalid_evidence_batch")
    if (type(report.dependency_risk_family_count) is not int
            or not 1 <= report.dependency_risk_family_count <= len(report.evidence)):
        raise EvidenceAgreementError("invalid_risk_family_count")
    for count in (report.exact_duplicate_count, report.possible_near_duplicate_count):
        if type(count) is not int or not 0 <= count <= len(report.evidence):
            raise EvidenceAgreementError("invalid_duplicate_counts")
    if (not isinstance(report.warnings, tuple)
            or not all(isinstance(w, str) and 0 < len(w) <= 256 for w in report.warnings)):
        raise EvidenceAgreementError("invalid_nli_warnings")

    pids: set[UUID] = set()
    version_family: dict[UUID, int] = {}
    version_identity: dict[UUID, tuple[UUID, str, str, datetime]] = {}
    source_domain: dict[UUID, str] = {}
    source_family: dict[UUID, int] = {}
    domain_family: dict[str, int] = {}
    seen_families: set[int] = set()
    seen_duplicates: set[int] = set()
    for row in report.evidence:
        if not isinstance(row, ExternalNliPassage):
            raise EvidenceAgreementError("invalid_evidence_item")
        if (not isinstance(row.passage_id, UUID)
                or not isinstance(row.document_version_id, UUID)
                or not isinstance(row.source_id, UUID)):
            raise EvidenceAgreementError("invalid_evidence_identity")
        if row.passage_id in pids:
            raise EvidenceAgreementError("duplicate_passage_id")
        pids.add(row.passage_id)
        if (type(row.dependency_risk_family) is not int
                or not 1 <= row.dependency_risk_family <= report.dependency_risk_family_count
                or type(row.duplicate_group) is not int or not 1 <= row.duplicate_group <= len(report.evidence)):
            raise EvidenceAgreementError("invalid_family_or_duplicate_group")
        seen_families.add(row.dependency_risk_family)
        seen_duplicates.add(row.duplicate_group)
        for mapping, key in ((version_family, row.document_version_id),
                             (source_family, row.source_id)):
            old = mapping.setdefault(key, row.dependency_risk_family)
            if old != row.dependency_risk_family:
                raise EvidenceAgreementError("same_source_split_across_risk_families")
        if not isinstance(row.publisher_domain, str) or not row.publisher_domain or row.publisher_domain != row.publisher_domain.strip().lower():
            raise EvidenceAgreementError("invalid_publisher_domain")
        identity = (row.source_id, row.publisher_domain, row.article_url, row.retrieved_at)
        existing_identity = version_identity.setdefault(row.document_version_id, identity)
        if existing_identity != identity:
            raise EvidenceAgreementError("document_version_identity_mismatch")
        prior_source_domain = source_domain.setdefault(row.source_id, row.publisher_domain)
        if prior_source_domain != row.publisher_domain:
            raise EvidenceAgreementError("source_domain_mismatch")
        prior = domain_family.setdefault(row.publisher_domain, row.dependency_risk_family)
        if prior != row.dependency_risk_family:
            raise EvidenceAgreementError("same_publisher_split_across_risk_families")
        if not isinstance(row.article_url, str) or not row.article_url.startswith("https://") or len(row.article_url) > 2048:
            raise EvidenceAgreementError("invalid_article_url")
        if not isinstance(row.retrieved_at, datetime) or row.retrieved_at.tzinfo is None or row.retrieved_at.utcoffset() is None or row.retrieved_at > at:
            raise EvidenceAgreementError("invalid_retrieval_time")
        if not isinstance(row.passage_text, str) or not 1 <= len(row.passage_text) <= 20_000:
            raise EvidenceAgreementError("invalid_passage_text")
        if sha256(row.passage_text.encode("utf-8")).hexdigest() != row.passage_sha256:
            raise EvidenceAgreementError("passage_hash_mismatch")
        if (row.nli_evaluated is not True or row.independently_verified is not False
                or row.independent_corroboration_established is not False):
            raise EvidenceAgreementError("invalid_nli_evidence_flags")
        scores = (row.entailment, row.contradiction, row.neutral, row.nli_confidence)
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and 0 <= v <= 1 for v in scores):
            raise EvidenceAgreementError("invalid_nli_scores")
        if not math.isclose(row.entailment + row.contradiction + row.neutral, 1.0, abs_tol=1e-4):
            raise EvidenceAgreementError("invalid_nli_distribution")
        label, conf = max(
            (("ENTAILMENT", row.entailment), ("CONTRADICTION", row.contradiction), ("NEUTRAL", row.neutral)),
            key=lambda item: item[1],
        )
        if row.nli_label != label or not math.isclose(row.nli_confidence, conf, abs_tol=1e-6):
            raise EvidenceAgreementError("nli_label_or_confidence_mismatch")
        expected = label != "NEUTRAL" and conf >= threshold
        if row.nli_threshold_passed is not expected:
            raise EvidenceAgreementError("nli_threshold_flag_mismatch")
    if len(seen_families) != report.dependency_risk_family_count or seen_families != set(range(1, report.dependency_risk_family_count + 1)):
        raise EvidenceAgreementError("missing_risk_families")
    if seen_duplicates != set(range(1, len(seen_duplicates) + 1)):
        raise EvidenceAgreementError("invalid_duplicate_group_numbering")


def analyze_external_evidence_agreement(*, nli_report: ExternalNliReport) -> ExternalAgreementReport:
    """Summarize *provisional* agreement while conservatively merging reuse risk.

    Duplication across different dependency-risk families bridges those families
    for counting purposes. No model or database I/O and no truth decision.
    """
    _validate_report(nli_report)
    rows = nli_report.evidence
    parents = {row.dependency_risk_family: row.dependency_risk_family for row in rows}

    def find(i: int) -> int:
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i

    def union(a: int, b: int) -> None:
        a, b = find(a), find(b)
        if a != b:
            parents[max(a, b)] = min(a, b)

    by_duplicate: dict[int, set[int]] = {}
    for row in rows:
        by_duplicate.setdefault(row.duplicate_group, set()).add(row.dependency_risk_family)
    for families in by_duplicate.values():
        first = min(families)
        for other in families:
            union(first, other)
    buckets: dict[int, list[ExternalNliPassage]] = {}
    for row in rows:
        buckets.setdefault(find(row.dependency_risk_family), []).append(row)

    units: list[AgreementUnit] = []
    for family_id in sorted(buckets):
        items = buckets[family_id]
        supports = tuple(sorted((r.passage_id for r in items if r.nli_threshold_passed and r.nli_label == "ENTAILMENT"), key=lambda x: x.hex))
        refutes = tuple(sorted((r.passage_id for r in items if r.nli_threshold_passed and r.nli_label == "CONTRADICTION"), key=lambda x: x.hex))
        unresolved = tuple(sorted((r.passage_id for r in items if not r.nli_threshold_passed), key=lambda x: x.hex))
        stance = ("MIXED" if supports and refutes else "SUPPORT_ONLY" if supports
                  else "REFUTE_ONLY" if refutes else "NO_DECISIVE_EVIDENCE")
        units.append(AgreementUnit(
            risk_family_ids=tuple(sorted({r.dependency_risk_family for r in items})),
            passage_ids=tuple(sorted((r.passage_id for r in items), key=lambda x: x.hex)),
            document_version_ids=tuple(sorted({r.document_version_id for r in items}, key=lambda x: x.hex)),
            source_ids=tuple(sorted({r.source_id for r in items}, key=lambda x: x.hex)),
            article_urls=tuple(sorted({r.article_url for r in items})),
            duplicate_groups=tuple(sorted({r.duplicate_group for r in items})),
            support_passage_ids=supports,
            refute_passage_ids=refutes,
            inconclusive_passage_ids=unresolved,
            stance=stance,
        ))

    support_count = sum(u.stance == "SUPPORT_ONLY" for u in units)
    refute_count = sum(u.stance == "REFUTE_ONLY" for u in units)
    mixed_count = sum(u.stance == "MIXED" for u in units)
    none_count = sum(u.stance == "NO_DECISIVE_EVIDENCE" for u in units)
    support_exists = any(u.support_passage_ids for u in units)
    refute_exists = any(u.refute_passage_ids for u in units)
    opposing = support_exists and refute_exists
    status = ("UNRESOLVED_OPPOSING_EVIDENCE" if opposing
              else "PROVISIONAL_SUPPORT_ONLY" if support_exists
              else "PROVISIONAL_REFUTE_ONLY" if refute_exists
              else "INSUFFICIENT_DECISIVE_EVIDENCE")
    warnings = set(nli_report.warnings)
    warnings.update((
        "AGREEMENT_IS_NOT_EDITORIAL_INDEPENDENCE",
        "NLI_OUTPUT_IS_NOT_A_FACTUAL_TRUTH_PROBABILITY",
        "CORROBORATION_DECISION_DEFERRED_TO_PHASE_13D7",
    ))
    if len(units) < nli_report.dependency_risk_family_count:
        warnings.add("DUPLICATE_PASSAGES_BRIDGE_RISK_FAMILIES")
    if mixed_count:
        warnings.add("OPPOSING_NLI_STANCES_WITHIN_DEPENDENCY_RISK_UNIT")
    if opposing:
        warnings.add("OPPOSING_NLI_EVIDENCE_REQUIRES_REVIEW")
    if any(len({r.nli_label for r in rows if r.duplicate_group == g and r.nli_threshold_passed}) > 1 for g in by_duplicate):
        warnings.add("CONTRADICTORY_LABELS_INSIDE_DUPLICATE_GROUP")
    return ExternalAgreementReport(
        claim=nli_report.claim,
        assessed_at=nli_report.assessed_at,
        nli_threshold=nli_report.nli_threshold,
        evidence=rows,
        units=tuple(units),
        total_passages=len(rows),
        decisive_passages=sum(r.nli_threshold_passed for r in rows),
        inconclusive_passages=sum(not r.nli_threshold_passed for r in rows),
        raw_dependency_risk_family_count=nli_report.dependency_risk_family_count,
        provisional_agreement_unit_count=len(units),
        supporting_unit_count=support_count,
        refuting_unit_count=refute_count,
        mixed_unit_count=mixed_count,
        inconclusive_unit_count=none_count,
        has_opposing_evidence=opposing,
        has_within_unit_conflict=bool(mixed_count),
        evidence_status=status,
        warnings=tuple(sorted(warnings)),
    )
