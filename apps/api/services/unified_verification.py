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
    if not isinstance(rows, tuple) or len(rows) != len(retrieved) or not 2 <= len(rows) <= 20:
        raise ValueError("external_evidence_count_mismatch")
    expected_ids = [getattr(candidate, "passage_id", None) for candidate in retrieved]
    result_ids = [getattr(row, "passage_id", None) for row in rows]
    if len(set(expected_ids)) != len(expected_ids) or set(expected_ids) != set(result_ids):
        raise ValueError("external_passage_ids_mismatch")
    if (set(getattr(decision, "evidence_passage_ids", ())) != set(expected_ids)
            or len(getattr(decision, "evidence_passage_ids", ())) != len(expected_ids)):
        raise ValueError("decision_passage_ids_mismatch")
    count = getattr(agreement, "provisional_agreement_unit_count", None)
    if not _valid_count(count, 20) or count > len(rows):
        raise ValueError("invalid_agreement_unit_count")
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
        ))
    # Warnings are bounded, public reason codes; no internal failure text is returned.
    codes = getattr(decision, "warnings", ())
    if (not isinstance(codes, tuple) or len(codes) > 60
            or any(not isinstance(x, str) or not 1 <= len(x) <= 256 for x in codes)):
        raise ValueError("invalid_external_warning_codes")
    return ExternalFinding(
        status="AVAILABLE", evidence_verdict=verdict,
        retrieved_count=len(retrieved), assessed_count=len(rows),
        provisional_agreement_units=count, provenance=tuple(refs),
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
                    "TWO_DISTINCT_STORED_ARTICLE_SNAPSHOTS_REQUIRED", len(candidates),
                )
            elif len(candidates) > external_top_k:
                ext = _external_failure("UNAVAILABLE", "EXTERNAL_RETRIEVAL_LIMIT_VIOLATION")
            else:
                if external_nli_runner is None:
                    from apps.api.services.external_evidence_nli import assess_external_evidence_nli
                    external_nli_runner = assess_external_evidence_nli
                nli = await external_nli_runner(
                    session, claim=normalized, candidates=candidates,
                    assessed_at=at, nli_threshold=nli_threshold,
                )
                if agreement_analyzer is None:
                    from apps.api.services.external_evidence_agreement import analyze_external_evidence_agreement
                    agreement_analyzer = analyze_external_evidence_agreement
                agreement = agreement_analyzer(nli_report=nli)
                if decision_engine is None:
                    from apps.api.services.external_corroboration_decision import decide_external_corroboration
                    decision_engine = decide_external_corroboration
                decision = decision_engine(nli_report=nli, agreement_report=agreement)
                ext = _snapshot_external(
                    claim=normalized, at=at, retrieved=candidates,
                    nli=nli, agreement=agreement, decision=decision,
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
