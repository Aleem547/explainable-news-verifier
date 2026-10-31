"""Phase 13F.4.54: independent-origin review *candidates*, never certificates.

This read-only/offline stage identifies precisely which NLI evidence pairs need
external, independently auditable origin checks. Source counts, distinct domains,
NLI alignment, and duplicate-risk clustering CANNOT establish original reporting.
It does not fetch URLs, access a database, sign attestations, or set a positive
independence/factual-verification flag.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from itertools import product
from uuid import UUID

from apps.api.services.external_evidence_agreement import (
    EvidenceAgreementError,
    ExternalAgreementReport,
    analyze_external_evidence_agreement,
)
from apps.api.services.external_evidence_nli import ExternalNliPassage, ExternalNliReport

REVIEW_POLICY_VERSION = "phase3.10-all-eligible-paragraph-origin-pairs-v5"


class ExternalIndependenceReviewError(ValueError):
    """The upstream evidence or review packet has not passed validation."""


@dataclass(frozen=True, slots=True)
class OriginReviewCandidate:
    """Pair of provisional NLI evidence units requiring *human origin review*."""

    stance: str  # SUPPORT_ONLY or REFUTE_ONLY
    left_passage_id: UUID
    right_passage_id: UUID
    left_version_id: UUID
    right_version_id: UUID
    left_source_id: UUID
    right_source_id: UUID
    left_domain: str
    right_domain: str
    left_article_url: str
    right_article_url: str
    left_passage_sha256: str
    right_passage_sha256: str
    left_input_kind: str = "STORED_PASSAGE"
    right_input_kind: str = "STORED_PASSAGE"
    left_parent_passage_id: UUID | None = None
    right_parent_passage_id: UUID | None = None
    left_input_start_offset: int | None = None
    right_input_start_offset: int | None = None
    left_input_end_offset: int | None = None
    right_input_end_offset: int | None = None
    left_snapshot_sha256: str | None = None
    right_snapshot_sha256: str | None = None
    left_fetch_observation_id: UUID | None = None
    right_fetch_observation_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class ExternalIndependenceReview:
    claim: str
    assessed_at: datetime
    review_candidates: tuple[OriginReviewCandidate, ...]
    review_packet_sha256: str
    review_status: str
    warnings: tuple[str, ...]
    policy_version: str = REVIEW_POLICY_VERSION
    independence_status: str = "NOT_ESTABLISHED"
    independent_corroboration_established: bool = False
    independently_verified: bool = False


def _single_publisher_inputs(unit: object, rows: dict[UUID, ExternalNliPassage]):
    """Conservatively omit merged multi-publisher units from candidate pairs."""
    if (len(unit.source_ids) != 1 or len(unit.document_version_ids) != 1
            or len(unit.article_urls) != 1 or not unit.passage_ids):
        return ()
    evidence = [rows[pid] for pid in unit.passage_ids]
    if (len({r.publisher_domain for r in evidence}) != 1
            or len({r.duplicate_group for r in evidence}) != len(unit.duplicate_groups)):
        return ()
    decisive = (
        unit.support_passage_ids if unit.stance == "SUPPORT_ONLY"
        else unit.refute_passage_ids if unit.stance == "REFUTE_ONLY"
        else ()
    )
    if not decisive:
        return ()
    # Every admitted paragraph can have a different reporting origin. Choosing
    # one by UUID can hide an observation behind another paragraph's repetition.
    # These remain candidate inputs, never additional independent sources.
    return tuple(sorted((rows[pid] for pid in decisive), key=lambda r: r.passage_id.hex))


def build_external_independence_review(
    *, nli_report: ExternalNliReport, agreement_report: ExternalAgreementReport,
) -> ExternalIndependenceReview:
    """Validate the complete agreement, then find pairs for independent audit.

    The resulting SHA-256 is a deterministic integrity fingerprint, NOT a
    signature, reviewer identity or proof that origin declarations are true.
    """
    if not isinstance(nli_report, ExternalNliReport):
        raise ExternalIndependenceReviewError("invalid_nli_report")
    if not isinstance(agreement_report, ExternalAgreementReport):
        raise ExternalIndependenceReviewError("invalid_agreement_report")
    try:
        verified = analyze_external_evidence_agreement(nli_report=nli_report)
    except (EvidenceAgreementError, TypeError, ValueError, AttributeError) as exc:
        raise ExternalIndependenceReviewError("invalid_upstream_evidence") from exc
    if agreement_report != verified:
        raise ExternalIndependenceReviewError("agreement_and_nli_reports_mismatch")

    by_id = {row.passage_id: row for row in verified.evidence}
    possibilities = []
    # An agreement unit may bridge duplicates across multiple publishers;
    # such units are ineligible for a simple original-reporting pair.
    units = [
        (unit, _single_publisher_inputs(unit, by_id))
        for unit in verified.units
    ]
    for index, (left_unit, left_inputs) in enumerate(units):
        if not left_inputs:
            continue
        for right_unit, right_inputs in units[index + 1:]:
            if not right_inputs or left_unit.stance != right_unit.stance:
                continue
            if (left_inputs[0].source_id == right_inputs[0].source_id
                    or left_inputs[0].publisher_domain == right_inputs[0].publisher_domain):
                continue
            if (set(left_unit.duplicate_groups) & set(right_unit.duplicate_groups)
                    or set(left_unit.risk_family_ids) & set(right_unit.risk_family_ids)):
                continue
            for left, right in product(left_inputs, right_inputs):
                # Canonical ordering makes report stable under input permutations.
                first, second = sorted(
                    (left, right),
                    key=lambda r: (r.publisher_domain, r.document_version_id.hex, r.passage_id.hex),
                )
                possibilities.append(OriginReviewCandidate(
                    stance=left_unit.stance,
                    left_passage_id=first.passage_id,
                    right_passage_id=second.passage_id,
                    left_version_id=first.document_version_id,
                    right_version_id=second.document_version_id,
                    left_source_id=first.source_id,
                    right_source_id=second.source_id,
                    left_domain=first.publisher_domain,
                    right_domain=second.publisher_domain,
                    left_article_url=first.article_url,
                    right_article_url=second.article_url,
                    left_passage_sha256=first.passage_sha256,
                    right_passage_sha256=second.passage_sha256,
                    left_input_kind=first.input_kind, right_input_kind=second.input_kind,
                    left_parent_passage_id=(first.paragraph_input.parent.passage_id if first.paragraph_input else None),
                    right_parent_passage_id=(second.paragraph_input.parent.passage_id if second.paragraph_input else None),
                    left_input_start_offset=(first.paragraph_input.start_offset if first.paragraph_input else None),
                    right_input_start_offset=(second.paragraph_input.start_offset if second.paragraph_input else None),
                    left_input_end_offset=(first.paragraph_input.end_offset if first.paragraph_input else None),
                    right_input_end_offset=(second.paragraph_input.end_offset if second.paragraph_input else None),
                    left_snapshot_sha256=(first.paragraph_input.parent.snapshot_sha256 if first.paragraph_input else None),
                    right_snapshot_sha256=(second.paragraph_input.parent.snapshot_sha256 if second.paragraph_input else None),
                    left_fetch_observation_id=(first.paragraph_input.parent.fetch_observation_id if first.paragraph_input else None),
                    right_fetch_observation_id=(second.paragraph_input.parent.fetch_observation_id if second.paragraph_input else None),
                ))
    pairs = tuple(sorted(possibilities, key=lambda p: (
        p.stance, p.left_domain, p.right_domain, p.left_passage_id.hex, p.right_passage_id.hex,
    )))
    # Fingerprint binds all evidence, including neutral/conflicting rows that
    # cannot enter a pair, so changes to the NLI input invalidate the packet.
    record = {
        "policy": REVIEW_POLICY_VERSION,
        "claim": verified.claim,
        "paragraph_selection_sha256": (
            nli_report.paragraph_selection.selection_sha256 if nli_report.paragraph_selection else None),
        "assessed_at": verified.assessed_at.isoformat(),
        "nli_threshold": verified.nli_threshold,
        "decisive_admissibility_policy": verified.decisive_admissibility_policy_version,
        "subject_excluded_decisive_passage_ids": [str(pid) for pid in verified.subject_excluded_decisive_passage_ids],
        "scope_excluded_decisive_passages": [
            [str(pid), list(codes)] for pid, codes in verified.scope_excluded_decisive_passages
        ],
        "evidence": sorted((
            [str(row.passage_id), str(row.document_version_id), str(row.source_id),
             row.publisher_domain, row.article_url, row.passage_sha256,
             row.retrieved_at.isoformat(), row.lexical_relevance_score,
             row.nli_label, row.nli_confidence, row.nli_threshold_passed,
             row.entailment, row.contradiction, row.neutral,
             row.dependency_risk_family, row.duplicate_group,
             row.input_kind, row.input_pair_tokens, row.model_max_length]
            for row in verified.evidence
        ), key=lambda x: x[0]),
        "review_pairs": [
            [pair.stance, str(pair.left_passage_id), str(pair.right_passage_id)]
            for pair in pairs
        ],
    }
    digest = hashlib.sha256(json.dumps(
        record, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")).hexdigest()
    return ExternalIndependenceReview(
        claim=verified.claim,
        assessed_at=verified.assessed_at,
        review_candidates=pairs,
        review_packet_sha256=digest,
        review_status="ORIGIN_REVIEW_REQUIRED" if pairs else "NO_ELIGIBLE_ORIGIN_PAIRS",
        warnings=(
            "DIFFERENT_PUBLISHERS_DO_NOT_ESTABLISH_EDITORIAL_INDEPENDENCE",
            "SHARED_WIRE_OWNER_PRIMARY_SOURCE_AND_SYNDICATION_MUST_BE_AUDITED",
            "REVIEW_PACKET_HASH_IS_NOT_AN_AUTHENTICATED_PROOF",
            "NLI_ALIGNMENT_DOES_NOT_ESTABLISH_FACTUAL_TRUTH",
        ),
    )
