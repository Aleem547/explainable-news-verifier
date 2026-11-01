"""Phase 13E.1: read-only orchestration of existing Wikipedia and external evidence.

This module is deliberately NOT an API route. It performs no downloads, writes,
commits, source-independence certification, or claim-level truth aggregation.
External findings are only about stored and provenance-audited passage text.
"""

from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Event
from typing import Any, Callable
from urllib.parse import urlsplit
from uuid import UUID

from apps.api.services.external_evidence_agreement import ExternalAgreementReport
from apps.api.services.external_evidence_nli import ExternalNliReport, validate_nli_input_bindings
from ml.verification.paragraph_inputs import parent_matches_candidate
from apps.api.services.external_independence_review import (
    ExternalIndependenceReview,
    build_external_independence_review,
)
from apps.api.services.external_reporting_origin_audit import (
    ReportingOriginAudit,
    ReportingOriginAuditSummary,
    assess_reporting_origin_dependencies,
    summarize_reporting_origin_audit,
)

from apps.api.services.trusted_reporting_review import TrustedOriginReviewSummary, resolve_trusted_origin_review
from apps.api.services.reviewed_corroboration import ReviewedCorroboration, decide_reviewed_corroboration

POLICY_VERSION = "phase13e1-separate-corpus-v1"
_WIKI_VERDICTS = frozenset({
    "SUPPORTING_EVIDENCE", "REFUTING_EVIDENCE",
    "CONFLICTING_EVIDENCE", "INSUFFICIENT_EVIDENCE",
})
_EXTERNAL_VERDICTS = frozenset({
    "PROVISIONAL_SUPPORT", "PROVISIONAL_REFUTATION",
    "CONFLICTING_EVIDENCE", "INSUFFICIENT_EVIDENCE",
})


class UnifiedVerificationError(ValueError):
    """Invalid caller policy/claim, before any expensive work starts."""


@dataclass(frozen=True, slots=True)
class WikipediaFinding:
    status: str  # AVAILABLE or UNAVAILABLE
    evidence_verdict: str | None
    retrieved_count: int
    assessed_count: int
    supporting_pages: tuple[str, ...]
    refuting_pages: tuple[str, ...]
    warnings: tuple[str, ...]
    corroboration_status: str = "NOT_ESTABLISHED_SINGLE_CORPUS"


@dataclass(frozen=True, slots=True)
class ExternalEvidenceReference:
    passage_id: UUID
    document_version_id: UUID
    publisher_domain: str
    article_url: str
    nli_label: str
    nli_confidence: float
    nli_threshold_passed: bool
    dependency_risk_family: int
    duplicate_group: int
    # None is reserved for injected compatibility/test reports without a real
    # replay-validated project decision. Raw NLI flags remain unchanged.
    decisive_evidence_admitted: bool | None = None
    scope_exclusion_codes: tuple[str, ...] = ()
    input_kind: str = "STORED_PASSAGE"
    parent_passage_id: UUID | None = None
    input_sha256: str | None = None
    input_start_offset: int | None = None
    input_end_offset: int | None = None
    snapshot_sha256: str | None = None
    fetch_observation_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class ExternalFinding:
    status: str  # AVAILABLE, INSUFFICIENT_STORED_EVIDENCE, or UNAVAILABLE
    evidence_verdict: str | None
    retrieved_count: int
    assessed_count: int
    provisional_agreement_units: int
    provenance: tuple[ExternalEvidenceReference, ...]
    warnings: tuple[str, ...]
    independence_status: str = "NOT_ESTABLISHED"
    independent_corroboration_established: bool = False
    origin_audit: ReportingOriginAuditSummary | None = None
    decisive_admissibility_policy_version: str | None = None
    subject_excluded_decisive_passage_ids: tuple[UUID, ...] = ()
    scope_excluded_decisive_passages: tuple[tuple[UUID, tuple[str, ...]], ...] = ()
    evidence_input_kind: str = "STORED_PASSAGE"
    audited_parent_count: int | None = None
    trusted_origin_review: TrustedOriginReviewSummary | None = None
    reviewed_corroboration: ReviewedCorroboration | None = None


@dataclass(frozen=True, slots=True)
class UnifiedVerificationReport:
    claim: str
    assessed_at: datetime
    wikipedia: WikipediaFinding
    external: ExternalFinding
    relationship: str  # Informational relationship, never a merged truth verdict.
    warnings: tuple[str, ...]
    policy_version: str = POLICY_VERSION
    independence_status: str = "NOT_ESTABLISHED"
    independent_corroboration_established: bool = False
    independently_verified: bool = False


def _valid_count(value: object, maximum: int = 1_000_000) -> bool:
    return type(value) is int and 0 <= value <= maximum


def _validate_request(
    claim: str, wikipedia_top_k: int, external_top_k: int,
    nli_threshold: float, assessed_at: datetime,
) -> str:
    if not isinstance(claim, str) or not 3 <= len(claim.strip()) <= 2000:
        raise UnifiedVerificationError("invalid_claim")
    if type(wikipedia_top_k) is not int or not 1 <= wikipedia_top_k <= 20:
        raise UnifiedVerificationError("invalid_wikipedia_top_k")
    if type(external_top_k) is not int or not 2 <= external_top_k <= 20:
        raise UnifiedVerificationError("invalid_external_top_k")
    if (isinstance(nli_threshold, bool) or not isinstance(nli_threshold, (int, float))
            or not math.isfinite(nli_threshold) or not 0.5 <= nli_threshold <= 1.0):
        raise UnifiedVerificationError("invalid_nli_threshold")
    if (not isinstance(assessed_at, datetime) or assessed_at.tzinfo is None
            or assessed_at.utcoffset() is None):
        raise UnifiedVerificationError("naive_assessment_timestamp")
    return claim.strip()


def _wiki_failure(code: str) -> WikipediaFinding:
    return WikipediaFinding(
        status="UNAVAILABLE", evidence_verdict=None,
        retrieved_count=0, assessed_count=0,
        supporting_pages=(), refuting_pages=(), warnings=(code,),
    )


def _external_failure(status: str, code: str, count: int = 0) -> ExternalFinding:
    return ExternalFinding(
        status=status, evidence_verdict=None, retrieved_count=count,
        assessed_count=0, provisional_agreement_units=0,
        provenance=(), warnings=(code,),
    )


def _snapshot_wikipedia(raw: object, claim: str) -> WikipediaFinding:
    if getattr(raw, "claim", None) != claim:
        raise ValueError("wikipedia_claim_mismatch")
    verdict = str(getattr(raw, "verdict", ""))
    if verdict not in _WIKI_VERDICTS:
        raise ValueError("invalid_wikipedia_verdict")
    if getattr(raw, "corroboration_status", None) != "NOT_ESTABLISHED_SINGLE_CORPUS":
        raise ValueError("invalid_wikipedia_corroboration_status")
    retrieved, assessed = getattr(raw, "retrieved_count", None), getattr(raw, "assessed_count", None)
    if not _valid_count(retrieved) or not _valid_count(assessed) or assessed > retrieved:
        raise ValueError("invalid_wikipedia_counts")
    supporting, refuting = getattr(raw, "supporting_pages", None), getattr(raw, "refuting_pages", None)
    if (not isinstance(supporting, list) or not isinstance(refuting, list)
            or len(supporting) > 20 or len(refuting) > 20
            or any(not isinstance(x, str) or not 1 <= len(x) <= 1000 for x in supporting + refuting)):
        raise ValueError("invalid_wikipedia_pages")
    return WikipediaFinding(
        status="AVAILABLE", evidence_verdict=verdict,
        retrieved_count=retrieved, assessed_count=assessed,
        supporting_pages=tuple(supporting), refuting_pages=tuple(refuting),
        warnings=("WIKIPEDIA_SINGLE_CORPUS_NOT_INDEPENDENT_CORROBORATION",),
    )


def _snapshot_external(
    *, claim: str, at: datetime, retrieved: tuple[object, ...],
    nli: object, agreement: object, decision: object,
    independence_review: ExternalIndependenceReview | None = None,
    reporting_origin_audit: ReportingOriginAudit | None = None,
) -> ExternalFinding:
    if any(getattr(report, "claim", None) != claim for report in (nli, agreement, decision)):
        raise ValueError("external_claim_mismatch")
    if any(getattr(report, "assessed_at", None) != at for report in (nli, agreement, decision)):
        raise ValueError("external_timestamp_mismatch")
    if (getattr(decision, "independence_status", None) != "NOT_ESTABLISHED"
            or getattr(decision, "independent_corroboration_established", None) is not False
            or getattr(decision, "independently_verified", None) is not False):
        raise ValueError("external_independence_claim_not_supported")
    for report in (nli, agreement):
        if (getattr(report, "independence_status", None) != "NOT_ESTABLISHED"
                or getattr(report, "independent_corroboration_established", None) is not False
                or getattr(report, "independently_verified", None) is not False):
            raise ValueError("upstream_independence_claim_not_supported")
    verdict = str(getattr(decision, "evidence_verdict", ""))
    if verdict not in _EXTERNAL_VERDICTS:
        raise ValueError("invalid_external_verdict")
    rows = getattr(nli, "evidence", None)
    model_inputs = retrieved
    audited_parent_count = None
    if isinstance(nli, ExternalNliReport) and nli.paragraph_selection is not None:
        validate_nli_input_bindings(nli)
        selection = nli.paragraph_selection
        by_parent = {p.passage_id: p for p in selection.parents}
        if (len(by_parent) != len(retrieved)
                or {getattr(p, "passage_id", None) for p in retrieved} != set(by_parent)
                or any(not parent_matches_candidate(by_parent[p.passage_id], p) for p in retrieved)):
            raise ValueError("paragraph_parent_retrieval_binding_mismatch")
        audited_parent_count = len(retrieved)
        model_inputs = selection.inputs
    if not isinstance(rows, tuple) or len(rows) != len(model_inputs) or not 2 <= len(rows) <= 20:
        raise ValueError("external_evidence_count_mismatch")
    expected_ids = [getattr(candidate, "passage_id", None) for candidate in model_inputs]
    result_ids = [getattr(row, "passage_id", None) for row in rows]
    if len(set(expected_ids)) != len(expected_ids) or set(expected_ids) != set(result_ids):
        raise ValueError("external_passage_ids_mismatch")
    if (set(getattr(decision, "evidence_passage_ids", ())) != set(expected_ids)
            or len(getattr(decision, "evidence_passage_ids", ())) != len(expected_ids)):
        raise ValueError("decision_passage_ids_mismatch")
    count = getattr(agreement, "provisional_agreement_unit_count", None)
    if not _valid_count(count, 20) or count > len(rows):
        raise ValueError("invalid_agreement_unit_count")
    from apps.api.services.external_corroboration_decision import (
        ExternalCorroborationDecision, decide_external_corroboration,
    )
    admitted_ids = None
    guard_policy = None
    subject_excluded = ()
    scope_excluded = ()
    if isinstance(decision, ExternalCorroborationDecision):
        # Replay the full real decision before exposing per-passage admission.
        # Synthetic injected decision objects retain the explicit test seam.
        if not isinstance(nli, ExternalNliReport) or not isinstance(agreement, ExternalAgreementReport):
            raise ValueError("external_decision_binding_missing")
        admitted_ids = set(decision.supporting_passage_ids + decision.refuting_passage_ids)
        guard_policy = decision.decisive_admissibility_policy_version
        subject_excluded = decision.subject_excluded_decisive_passage_ids
        scope_excluded = decision.scope_excluded_decisive_passages
    scope_codes_by_id = dict(scope_excluded)
    refs: list[ExternalEvidenceReference] = []
    for row in rows:
        passage_id, version_id = getattr(row, "passage_id", None), getattr(row, "document_version_id", None)
        domain, url = getattr(row, "publisher_domain", None), getattr(row, "article_url", None)
        conf, label = getattr(row, "nli_confidence", None), getattr(row, "nli_label", None)
        family, duplicate = getattr(row, "dependency_risk_family", None), getattr(row, "duplicate_group", None)
        if (not isinstance(passage_id, UUID) or not isinstance(version_id, UUID)
                or not isinstance(domain, str) or not domain or len(domain) > 255
                or not isinstance(url, str) or not 1 <= len(url) <= 2048
                or urlsplit(url).scheme != "https" or not urlsplit(url).hostname
                or label not in ("ENTAILMENT", "CONTRADICTION", "NEUTRAL")
                or isinstance(conf, bool) or not isinstance(conf, (float, int))
                or not math.isfinite(conf) or not 0 <= conf <= 1
                or type(family) is not int or not 1 <= family <= 20
                or type(duplicate) is not int or not 1 <= duplicate <= 20
                or type(getattr(row, "nli_threshold_passed", None)) is not bool):
            raise ValueError("invalid_external_evidence_reference")
        refs.append(ExternalEvidenceReference(
            passage_id=passage_id, document_version_id=version_id,
            publisher_domain=domain, article_url=url,
            nli_label=label, nli_confidence=float(conf),
            nli_threshold_passed=row.nli_threshold_passed,
            dependency_risk_family=family, duplicate_group=duplicate,
            decisive_evidence_admitted=(passage_id in admitted_ids if admitted_ids is not None else None),
            scope_exclusion_codes=scope_codes_by_id.get(passage_id, ()),
            input_kind=getattr(row, "input_kind", "STORED_PASSAGE"),
            parent_passage_id=(row.paragraph_input.parent.passage_id
                               if getattr(row, "paragraph_input", None) else None),
            input_sha256=getattr(row, "passage_sha256", None),
            input_start_offset=(row.paragraph_input.start_offset if getattr(row, "paragraph_input", None) else None),
            input_end_offset=(row.paragraph_input.end_offset if getattr(row, "paragraph_input", None) else None),
            snapshot_sha256=(row.paragraph_input.parent.snapshot_sha256 if getattr(row, "paragraph_input", None) else None),
            fetch_observation_id=(row.paragraph_input.parent.fetch_observation_id if getattr(row, "paragraph_input", None) else None),
        ))
    # Warnings are bounded, public reason codes; no internal failure text is returned.
    codes = getattr(decision, "warnings", ())
    if (not isinstance(codes, tuple) or len(codes) > 60
            or any(not isinstance(x, str) or not 1 <= len(x) <= 256 for x in codes)):
        raise ValueError("invalid_external_warning_codes")
    origin_summary = None
    decision_summary = getattr(decision, "origin_audit", None)
    if reporting_origin_audit is not None:
        if (independence_review is None
                or not isinstance(nli, ExternalNliReport)
                or not isinstance(agreement, ExternalAgreementReport)):
            raise ValueError("external_origin_audit_binding_missing")
        origin_summary = summarize_reporting_origin_audit(
            nli_report=nli, agreement_report=agreement,
            independence_review=independence_review, audit=reporting_origin_audit,
        )
        summary_counts = (
            "candidate_pair_count", "dependency_indicated_pair_count",
            "unverified_origin_pair_count", "unreviewed_pair_count", "observations_count",
        )
        if (type(decision_summary) is not ReportingOriginAuditSummary
                or any(type(getattr(decision_summary, key)) is not int for key in summary_counts)
                or decision_summary != origin_summary
                or type(getattr(decision, "origin_review_pair_count", None)) is not int
                or decision.origin_review_pair_count != origin_summary.candidate_pair_count
                or getattr(decision, "origin_review_packet_sha256", None)
                != origin_summary.review_packet_sha256):
            raise ValueError("external_origin_audit_decision_mismatch")
    elif decision_summary is not None:
        raise ValueError("external_origin_audit_binding_missing")
    if isinstance(decision, ExternalCorroborationDecision):
        expected_decision = decide_external_corroboration(
            nli_report=nli, agreement_report=agreement,
            independence_review=independence_review,
            reporting_origin_audit=reporting_origin_audit,
        )
        if decision != expected_decision:
            raise ValueError("external_decision_replay_mismatch")
    trusted = (resolve_trusted_origin_review(claim, tuple(refs), independence_review.review_candidates)
               if audited_parent_count is not None and independence_review is not None else None)
    reviewed = (decide_reviewed_corroboration(trusted, claim=claim, refs=tuple(refs),
                candidate_count=origin_summary.candidate_pair_count)
                if trusted is not None and origin_summary is not None else None)
    return ExternalFinding(
        status="AVAILABLE", evidence_verdict=verdict,
        retrieved_count=len(model_inputs), assessed_count=len(rows),
        provisional_agreement_units=count, provenance=tuple(refs),
        origin_audit=origin_summary,
        decisive_admissibility_policy_version=guard_policy,
        subject_excluded_decisive_passage_ids=subject_excluded,
        scope_excluded_decisive_passages=scope_excluded,
        evidence_input_kind="DERIVED_PARAGRAPH" if audited_parent_count is not None else "STORED_PASSAGE",
        audited_parent_count=audited_parent_count,
        trusted_origin_review=trusted,
        reviewed_corroboration=reviewed,
        warnings=tuple(sorted(set(codes) | {
            "EXTERNAL_NLI_PROVISIONAL_NOT_CLAIM_TRUTH",
            "SOURCE_EDITORIAL_INDEPENDENCE_NOT_ESTABLISHED",
        })),
    )


def _relationship(wikipedia: WikipediaFinding, external: ExternalFinding) -> str:
    if wikipedia.status != "AVAILABLE" and external.status != "AVAILABLE":
        return "BOTH_UNAVAILABLE_OR_INSUFFICIENT"
    if wikipedia.status != "AVAILABLE":
        return "EXTERNAL_ONLY"
    if external.status != "AVAILABLE":
        return "WIKIPEDIA_ONLY"
    wiki, ext = wikipedia.evidence_verdict, external.evidence_verdict
    if wiki == "SUPPORTING_EVIDENCE" and ext == "PROVISIONAL_SUPPORT":
        return "PROVISIONALLY_ALIGNED_SUPPORT"
    if wiki == "REFUTING_EVIDENCE" and ext == "PROVISIONAL_REFUTATION":
        return "PROVISIONALLY_ALIGNED_REFUTATION"
    if ((wiki == "SUPPORTING_EVIDENCE" and ext == "PROVISIONAL_REFUTATION")
            or (wiki == "REFUTING_EVIDENCE" and ext == "PROVISIONAL_SUPPORT")):
        return "OPPOSING_CORPUS_FINDINGS"
    if wiki == "CONFLICTING_EVIDENCE" or ext == "CONFLICTING_EVIDENCE":
        return "CONFLICT_OR_REVIEW_REQUIRED"
    return "PARTIAL_OR_INCONCLUSIVE"


async def orchestrate_unified_verification(
    session: Any,
    *,
    claim: str,
    wikipedia_top_k: int = 5,
    external_top_k: int = 10,
    nli_threshold: float = 0.90,
    assessed_at: datetime | None = None,
    external_input_mode: str = "STORED_PASSAGE",
    wikipedia_runner: Callable[[str, int], Any] | None = None,
    external_retriever: Callable[..., Any] | None = None,
    external_nli_runner: Callable[..., Any] | None = None,
    agreement_analyzer: Callable[..., Any] | None = None,
    decision_engine: Callable[..., Any] | None = None,
) -> UnifiedVerificationReport:
    """Execute existing corpora *sequentially*; return separate provisional findings.

    Wikipedia uses the existing bounded CPU inference queue. External NLI uses
    the existing multi-source CPU model lock. Neither executes concurrently.
    No wall-clock hard timeout is claimed: cancellation of a worker thread does
    not stop an already-running model. An API route will be added in 13E.7.

    Injected functions are for offline deterministic tests only. Never accept
    injected callables from untrusted request data or add them to the API.
    """
    at = assessed_at if assessed_at is not None else datetime.now(UTC)
    normalized = _validate_request(claim, wikipedia_top_k, external_top_k, nli_threshold, at)
    if type(external_input_mode) is not str or external_input_mode not in {
        "STORED_PASSAGE", "DERIVED_PARAGRAPH",
    }:
        raise UnifiedVerificationError("invalid_external_input_mode")

    if wikipedia_runner is None:
        from apps.api.services.verification import run_verification, verification_cancellation_context
        cancel_event = Event()

        def run_wikipedia(c: str, k: int) -> Any:
            with verification_cancellation_context(cancel_event):
                return run_verification(c, k, cancel_event=cancel_event)
    else:
        cancel_event = None
        run_wikipedia = wikipedia_runner

    try:
        # The synchronous frozen model must not block the asyncio event loop.
        wiki_raw = await asyncio.to_thread(run_wikipedia, normalized, wikipedia_top_k)
        try:
            wiki = _snapshot_wikipedia(wiki_raw, normalized)
        except (ValueError, TypeError, AttributeError):
            wiki = _wiki_failure("WIKIPEDIA_REPORT_INVALID")
    except Exception:
        # Do not emit raw upstream exception text (could include user data).
        wiki = _wiki_failure("WIKIPEDIA_VERIFICATION_UNAVAILABLE")
    finally:
        if cancel_event is not None:
            cancel_event.set()

    ext: ExternalFinding
    if session is None:
        ext = _external_failure("UNAVAILABLE", "EXTERNAL_DATABASE_UNAVAILABLE")
    else:
        try:
            if external_retriever is None:
                if external_input_mode == "DERIVED_PARAGRAPH":
                    from apps.api.services.external_paragraph_retrieval import retrieve_external_paragraph_parents
                    external_retriever = retrieve_external_paragraph_parents
                else:
                    from apps.api.services.external_passage_retrieval import retrieve_external_passages
                    external_retriever = retrieve_external_passages
            candidates = tuple(await external_retriever(
                session, claim=normalized, top_k=external_top_k,
                candidate_limit=max(60, external_top_k),
            ))
            if (len(candidates) < 2
                    or len({getattr(x, "document_version_id", None) for x in candidates}) < 2):
                ext = _external_failure(
                    "INSUFFICIENT_STORED_EVIDENCE",
                    ("TWO_COMPLETE_AUDITED_ARTICLE_INPUTS_REQUIRED"
                     if external_input_mode == "DERIVED_PARAGRAPH"
                     else "TWO_DISTINCT_STORED_ARTICLE_SNAPSHOTS_REQUIRED"), len(candidates),
                )
            elif len(candidates) > external_top_k:
                ext = _external_failure("UNAVAILABLE", "EXTERNAL_RETRIEVAL_LIMIT_VIOLATION")
            else:
                if external_nli_runner is None:
                    if external_input_mode == "DERIVED_PARAGRAPH":
                        from apps.api.services.external_paragraph_nli import assess_external_paragraph_nli
                        external_nli_runner = assess_external_paragraph_nli
                    else:
                        from apps.api.services.external_evidence_nli import assess_external_evidence_nli
                        external_nli_runner = assess_external_evidence_nli
                input_options = ({"max_inputs": external_top_k}
                                 if external_input_mode == "DERIVED_PARAGRAPH" else {})
                nli = await external_nli_runner(
                    session, claim=normalized, candidates=candidates,
                    assessed_at=at, nli_threshold=nli_threshold, **input_options,
                )
                if external_input_mode == "DERIVED_PARAGRAPH" and (
                    not isinstance(nli, ExternalNliReport) or nli.paragraph_selection is None
                    or len(nli.evidence) > external_top_k
                ):
                    raise ValueError("paragraph_mode_requires_bounded_audited_inputs")
                if agreement_analyzer is None:
                    from apps.api.services.external_evidence_agreement import analyze_external_evidence_agreement
                    agreement_analyzer = analyze_external_evidence_agreement
                agreement = agreement_analyzer(nli_report=nli)
                review: ExternalIndependenceReview | None = None
                origin_audit: ReportingOriginAudit | None = None
                if decision_engine is None:
                    from apps.api.services.external_corroboration_decision import decide_external_corroboration
                    # Build/replay the audit on the real stored-evidence path.
                    # Empty observations explicitly mean origin is unreviewed.
                    # Request data cannot supply observations or audit flags.
                    review = build_external_independence_review(
                        nli_report=nli, agreement_report=agreement,
                    )
                    origin_audit = assess_reporting_origin_dependencies(
                        nli_report=nli, agreement_report=agreement,
                        independence_review=review,
                    )
                    decision = decide_external_corroboration(
                        nli_report=nli, agreement_report=agreement,
                        independence_review=review, reporting_origin_audit=origin_audit,
                    )
                else:
                    # Preserve the existing trusted, test-only injection contract.
                    decision = decision_engine(nli_report=nli, agreement_report=agreement)
                ext = _snapshot_external(
                    claim=normalized, at=at, retrieved=candidates,
                    nli=nli, agreement=agreement, decision=decision,
                    independence_review=review, reporting_origin_audit=origin_audit,
                )
        except Exception:
            # Fail the external leg closed. No partial assessments are exposed.
            ext = _external_failure("UNAVAILABLE", "EXTERNAL_VERIFICATION_UNAVAILABLE")

    warnings = set(wiki.warnings) | set(ext.warnings)
    warnings.update({
        "NO_UNIFIED_FACTUAL_TRUTH_PROBABILITY",
        "NO_INDEPENDENT_CORROBORATION_CLAIM",
    })
    return UnifiedVerificationReport(
        claim=normalized, assessed_at=at, wikipedia=wiki, external=ext,
        relationship=_relationship(wiki, ext), warnings=tuple(sorted(warnings)),
    )
