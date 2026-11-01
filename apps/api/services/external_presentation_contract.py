"""Validate public external-evidence diagnostics without certifying their origin.

The actual NLI/decision/audit services must first validate full internal records.
This boundary checks that later article presentation preserves their type and
count invariants; fingerprints here remain integrity values, not signatures.
"""
from __future__ import annotations

import re
from uuid import UUID

from apps.api.services.external_reporting_origin_audit import ReportingOriginAuditSummary, ORIGIN_AUDIT_POLICY_VERSION
from apps.api.services.unified_verification import ExternalFinding

_SHA = re.compile(r"[0-9a-f]{64}\Z")
_CODE = re.compile(r"[A-Z0-9_]{1,256}\Z")


def _digest(value):
    return isinstance(value, str) and _SHA.fullmatch(value) is not None


def _codes(value):
    return (type(value) is tuple and len(value) <= 80
            and all(isinstance(c, str) and _CODE.fullmatch(c) for c in value)
            and len(set(value)) == len(value))


def validate_external_presentation(ext: ExternalFinding, *, claim: str | None = None) -> None:
    if ext.evidence_input_kind not in {"STORED_PASSAGE", "DERIVED_PARAGRAPH"}:
        raise ValueError("external_presentation_invalid_input_kind")
    derived = ext.evidence_input_kind == "DERIVED_PARAGRAPH"
    if derived:
        if (ext.status != "AVAILABLE" or type(ext.audited_parent_count) is not int
                or not 2 <= ext.audited_parent_count <= 20
                or not isinstance(ext.decisive_admissibility_policy_version, str)
                or not 1 <= len(ext.decisive_admissibility_policy_version) <= 128
                or ext.origin_audit is None):
            raise ValueError("external_presentation_missing_derived_metadata")
    elif ext.audited_parent_count is not None:
        raise ValueError("external_presentation_parent_count_without_derived_inputs")
    if (type(ext.subject_excluded_decisive_passage_ids) is not tuple
            or type(ext.scope_excluded_decisive_passages) is not tuple
            or len(ext.scope_excluded_decisive_passages) > 20
            or any(type(item) is not tuple or len(item) != 2
                   or not isinstance(item[0], UUID) or not _codes(item[1]) or not item[1]
                   for item in ext.scope_excluded_decisive_passages)):
        raise ValueError("external_presentation_invalid_exclusions")
    scopes = dict(ext.scope_excluded_decisive_passages)
    subjects = ext.subject_excluded_decisive_passage_ids
    ids = {r.passage_id for r in ext.provenance}
    if (len(scopes) != len(ext.scope_excluded_decisive_passages)
            or any(not isinstance(p, UUID) for p in subjects) or len(set(subjects)) != len(subjects)
            or not set(scopes) <= ids or not set(subjects) <= ids or set(scopes) & set(subjects)):
        raise ValueError("external_presentation_invalid_exclusion_ids")
    parents = {}
    for ref in ext.provenance:
        if (ref.input_kind != ext.evidence_input_kind
                or ref.decisive_evidence_admitted is not None and type(ref.decisive_evidence_admitted) is not bool
                or not _codes(ref.scope_exclusion_codes)
                or ref.scope_exclusion_codes != scopes.get(ref.passage_id, ())
                or ref.input_sha256 is not None and not _digest(ref.input_sha256)):
            raise ValueError("external_presentation_invalid_reference_metadata")
        if (ref.decisive_evidence_admitted is True and (
                not ref.nli_threshold_passed or ref.nli_label == "NEUTRAL"
                or ref.scope_exclusion_codes or ref.passage_id in subjects)):
            raise ValueError("external_presentation_inconsistent_admission")
        if derived:
            if (type(ref.decisive_evidence_admitted) is not bool
                    or not isinstance(ref.parent_passage_id, UUID) or ref.parent_passage_id == ref.passage_id
                    or not isinstance(ref.fetch_observation_id, UUID)
                    or not _digest(ref.input_sha256) or not _digest(ref.snapshot_sha256)
                    or type(ref.input_start_offset) is not int or type(ref.input_end_offset) is not int
                    or not 0 <= ref.input_start_offset < ref.input_end_offset <= 2_000_000):
                raise ValueError("external_presentation_invalid_paragraph_binding")
            identity = (ref.document_version_id, ref.publisher_domain, ref.article_url,
                        ref.snapshot_sha256, ref.fetch_observation_id)
            prior = parents.setdefault(ref.parent_passage_id, identity)
            if prior != identity:
                raise ValueError("external_presentation_inconsistent_parent")
        elif any(v is not None for v in (ref.parent_passage_id, ref.input_start_offset,
                                         ref.input_end_offset, ref.snapshot_sha256, ref.fetch_observation_id)):
            raise ValueError("external_presentation_paragraph_metadata_without_kind")
    if derived and (len(parents) > ext.audited_parent_count or len(parents) < 2
                    or len({r.document_version_id for r in ext.provenance}) < 2):
        raise ValueError("external_presentation_invalid_parent_count")
    audit = ext.origin_audit
    if audit is not None:
        if type(audit) is not ReportingOriginAuditSummary:
            raise ValueError("external_presentation_invalid_origin_summary")
        counts = (audit.candidate_pair_count, audit.dependency_indicated_pair_count,
                  audit.unverified_origin_pair_count, audit.unreviewed_pair_count, audit.observations_count)
        admitted_count = sum(r.decisive_evidence_admitted is True for r in ext.provenance)
        if (any(type(n) is not int or not 0 <= n <= 190 for n in counts)
                or audit.observations_count > 100
                # Candidate pairs bind exact admitted paragraphs. Several can
                # belong to one publisher unit without increasing source count.
                or audit.candidate_pair_count > admitted_count*(admitted_count-1)//2
                or audit.observations_count < audit.dependency_indicated_pair_count + audit.unverified_origin_pair_count
                or audit.candidate_pair_count == 0 and audit.observations_count != 0
                or sum(counts[1:4]) != audit.candidate_pair_count
                or audit.policy_version != ORIGIN_AUDIT_POLICY_VERSION
                or not _digest(audit.review_packet_sha256) or not _digest(audit.audit_packet_sha256)):
            raise ValueError("external_presentation_invalid_origin_summary")

    if ext.trusted_origin_review is not None:
        from apps.api.services.trusted_reporting_review import validate_trusted_origin_review
        if claim is None or not derived or audit is None:
            raise ValueError("trusted_review_missing_claim_or_origin_binding")
        validate_trusted_origin_review(ext.trusted_origin_review, claim=claim,
                                      refs=ext.provenance, candidate_count=audit.candidate_pair_count)
    if ext.reviewed_corroboration is not None or ext.trusted_origin_review is not None:
        from apps.api.services.reviewed_corroboration import validate_reviewed_corroboration
        validate_reviewed_corroboration(ext.reviewed_corroboration, review=ext.trusted_origin_review,
            claim=claim, refs=ext.provenance, candidate_count=audit.candidate_pair_count if audit else 0)
