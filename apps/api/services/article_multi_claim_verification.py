"""Phase 13E.5: bounded, in-memory, sequential per-claim verification.

This is NOT an API route or an article truth classifier. Upstream prepared
articles are revalidated through the Phase 13E.4 extractor; individual claims
are assessed through the Phase 13E.1 unified verifier, without feeding the
submitted article back into its external evidence corpus.
"""

from __future__ import annotations

import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from apps.api.services.article_claim_candidates import (
    ClaimCandidate,
    ClaimCandidatePolicy,
    ClaimCandidateReport,
    extract_article_claim_candidates,
)
from apps.api.services.article_url_preparation import PreparedArticleUrl
from apps.api.services.pasted_article_preparation import PreparedPastedArticle
from apps.api.services.unified_verification import (
    POLICY_VERSION as UNIFIED_POLICY_VERSION,
    ExternalEvidenceReference,
    ExternalFinding,
    UnifiedVerificationReport,
    WikipediaFinding,
    _relationship,
    orchestrate_unified_verification,
)

POLICY_VERSION = "phase13e5-bounded-multiclaim-v1"
_RUNNER = Callable[..., Awaitable[UnifiedVerificationReport]]
_WIKI_VERDICTS = frozenset({
    "SUPPORTING_EVIDENCE", "REFUTING_EVIDENCE", "CONFLICTING_EVIDENCE",
    "INSUFFICIENT_EVIDENCE",
})
_EXT_VERDICTS = frozenset({
    "PROVISIONAL_SUPPORT", "PROVISIONAL_REFUTATION", "CONFLICTING_EVIDENCE",
    "INSUFFICIENT_EVIDENCE",
})


class MultiClaimVerificationError(ValueError):
    """Sanitized, stable validation code; never include article contents."""


@dataclass(frozen=True, slots=True)
class MultiClaimPolicy:
    max_verifications: int = 8
    wikipedia_top_k: int = 5
    external_top_k: int = 10
    nli_threshold: float = 0.90

    def __post_init__(self) -> None:
        if type(self.max_verifications) is not int or not 1 <= self.max_verifications <= 20:
            raise ValueError("invalid_max_verifications")
        if type(self.wikipedia_top_k) is not int or not 1 <= self.wikipedia_top_k <= 20:
            raise ValueError("invalid_wikipedia_top_k")
        if type(self.external_top_k) is not int or not 2 <= self.external_top_k <= 20:
            raise ValueError("invalid_external_top_k")
        if (type(self.nli_threshold) not in (float, int)
                or not math.isfinite(self.nli_threshold)
                or not 0.5 <= self.nli_threshold <= 1.0):
            raise ValueError("invalid_nli_threshold")


@dataclass(frozen=True, slots=True)
class ClaimVerificationItem:
    candidate_id: str
    literal_text: str
    start_char: int
    end_char: int
    paragraph_index: int
    normalized_fingerprint: str
    has_reporting_attribution: bool
    duplicate_locations: tuple[tuple[int, int], ...]
    status: str  # ASSESSED, UNAVAILABLE, FAILED, SKIPPED_LIMIT
    report: UnifiedVerificationReport | None
    warning_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MultiClaimVerificationReport:
    article_sha256: str
    source_kind: str
    source_url: str | None
    publisher_domain: str | None
    source_timestamp: datetime
    candidate_count: int
    assessed_count: int
    unavailable_count: int
    failed_count: int
    skipped_count: int
    filtered_sentence_count: int
    omitted_candidate_count: int
    claims: tuple[ClaimVerificationItem, ...]
    assessed_at: datetime
    warnings: tuple[str, ...]
    policy_version: str = POLICY_VERSION
    independently_verified: bool = False
    independent_corroboration_established: bool = False
    overall_article_truth_verdict: None = None
    eligible_as_independent_evidence: bool = False


def _bounded_reasons(codes: object) -> bool:
    return (isinstance(codes, tuple) and len(codes) <= 80
            and all(isinstance(code, str) and 1 <= len(code) <= 256
                    and code.isascii() and code.replace("_", "").isalnum()
                    for code in codes))


def _validate_unified_report(raw: object, *, claim: str, at: datetime) -> UnifiedVerificationReport:
    """Fail closed on forged source-independence flags or mismatched claim reports."""
    if not isinstance(raw, UnifiedVerificationReport):
        raise ValueError("unified_report_invalid_type")
    if (raw.claim != claim or raw.assessed_at != at
            or raw.policy_version != UNIFIED_POLICY_VERSION
            or raw.independence_status != "NOT_ESTABLISHED"
            or raw.independent_corroboration_established is not False
            or raw.independently_verified is not False
            or not _bounded_reasons(raw.warnings)):
        raise ValueError("unified_report_invalid_metadata")
    wiki, ext = raw.wikipedia, raw.external
    if not isinstance(wiki, WikipediaFinding) or not isinstance(ext, ExternalFinding):
        raise ValueError("unified_report_invalid_findings")
    if (wiki.corroboration_status != "NOT_ESTABLISHED_SINGLE_CORPUS"
            or ext.independence_status != "NOT_ESTABLISHED"
            or ext.independent_corroboration_established is not False):
        raise ValueError("unified_report_false_independence")
    if (wiki.status not in ("AVAILABLE", "UNAVAILABLE")
            or ext.status not in ("AVAILABLE", "UNAVAILABLE", "INSUFFICIENT_STORED_EVIDENCE")
            or (wiki.evidence_verdict in _WIKI_VERDICTS) != (wiki.status == "AVAILABLE")
            or (ext.evidence_verdict in _EXT_VERDICTS) != (ext.status == "AVAILABLE")
            or raw.relationship != _relationship(wiki, ext)):
        raise ValueError("unified_report_status_mismatch")
    for count in (wiki.retrieved_count, wiki.assessed_count,
                  ext.retrieved_count, ext.assessed_count, ext.provisional_agreement_units):
        if type(count) is not int or not 0 <= count <= 1_000_000:
            raise ValueError("unified_report_invalid_counts")
    if (wiki.assessed_count > wiki.retrieved_count
            or ext.assessed_count > ext.retrieved_count
            or ext.provisional_agreement_units > ext.assessed_count):
        raise ValueError("unified_report_invalid_counts")
    if (not _bounded_reasons(wiki.warnings) or not _bounded_reasons(ext.warnings)
            or not isinstance(wiki.supporting_pages, tuple)
            or not isinstance(wiki.refuting_pages, tuple)
            or not isinstance(ext.provenance, tuple)
            or len(wiki.supporting_pages) > 20 or len(wiki.refuting_pages) > 20
            or len(ext.provenance) > 20
            or (ext.status == "AVAILABLE" and len(ext.provenance) != ext.assessed_count)
            or (ext.status != "AVAILABLE" and bool(ext.provenance))):
        raise ValueError("unified_report_invalid_references")
    if any(not isinstance(p, str) or not 1 <= len(p) <= 1000
           for p in (*wiki.supporting_pages, *wiki.refuting_pages)):
        raise ValueError("unified_report_invalid_references")
    seen: set[UUID] = set()
    for ref in ext.provenance:
        if (not isinstance(ref, ExternalEvidenceReference)
                or not isinstance(ref.passage_id, UUID)
                or not isinstance(ref.document_version_id, UUID)
                or not isinstance(ref.publisher_domain, str)
                or not 1 <= len(ref.publisher_domain) <= 255
                or not isinstance(ref.article_url, str) or not 1 <= len(ref.article_url) <= 2048
                or ref.nli_label not in ("ENTAILMENT", "CONTRADICTION", "NEUTRAL")
                or type(ref.nli_confidence) not in (float, int)
                or not math.isfinite(ref.nli_confidence)
                or not 0 <= ref.nli_confidence <= 1
                or type(ref.nli_threshold_passed) is not bool
                or type(ref.dependency_risk_family) is not int
                or type(ref.duplicate_group) is not int
                or not 1 <= ref.dependency_risk_family <= 20
                or not 1 <= ref.duplicate_group <= 20):
            raise ValueError("unified_report_invalid_references")
        try:
            parsed = urlsplit(ref.article_url)
            if parsed.scheme != "https" or not parsed.hostname or parsed.port not in (None, 443):
                raise ValueError("invalid_url")
        except ValueError as exc:
            raise ValueError("unified_report_invalid_references") from exc
        if ref.passage_id in seen:
            raise ValueError("unified_report_duplicate_evidence")
        seen.add(ref.passage_id)
    return raw


async def verify_article_claims(
    session: Any,
    *,
    prepared: PreparedPastedArticle | PreparedArticleUrl,
    candidate_report: ClaimCandidateReport | None = None,
    extraction_policy: ClaimCandidatePolicy | None = None,
    policy: MultiClaimPolicy | None = None,
    assessed_at: datetime | None = None,
    unified_runner: _RUNNER | None = None,
) -> MultiClaimVerificationReport:
    """Verify bounded claim candidates sequentially, preserving source offsets.

    The prepared article and injected functions must originate from trusted
    server code. In production, callers MUST use their own authorization,
    quota, and request concurrency controls; model calls may take minutes on CPU.
    No hard timeout is promised because cancelling a thread doesn't stop a model.
    """
    settings = policy if policy is not None else MultiClaimPolicy()
    if not isinstance(settings, MultiClaimPolicy):
        raise MultiClaimVerificationError("invalid_multi_claim_policy")
    if extraction_policy is not None and not isinstance(extraction_policy, ClaimCandidatePolicy):
        raise MultiClaimVerificationError("invalid_claim_extraction_policy")
    at = datetime.now(UTC) if assessed_at is None else assessed_at
    if (not isinstance(at, datetime) or at.tzinfo is None
            or at.utcoffset() is None or at > datetime.now(UTC) + timedelta(minutes=5)):
        raise MultiClaimVerificationError("invalid_assessment_timestamp")

    try:
        expected = extract_article_claim_candidates(prepared=prepared, policy=extraction_policy)
    except (TypeError, ValueError, UnicodeError) as exc:
        raise MultiClaimVerificationError("article_candidate_provenance_invalid") from exc
    if candidate_report is not None and (not isinstance(candidate_report, ClaimCandidateReport)
                                         or candidate_report != expected):
        raise MultiClaimVerificationError("article_candidate_report_mismatch")
    report = expected
    if (report.independently_verified is not False
            or report.independent_corroboration_established is not False
            or report.eligible_as_independent_evidence is not False
            or not isinstance(report.candidates, tuple) or len(report.candidates) > 50):
        raise MultiClaimVerificationError("article_candidate_provenance_invalid")
    runner = unified_runner if unified_runner is not None else orchestrate_unified_verification
    if not callable(runner):
        raise MultiClaimVerificationError("invalid_unified_runner")

    results: list[ClaimVerificationItem] = []
    for index, candidate in enumerate(report.candidates):
        if not isinstance(candidate, ClaimCandidate):
            raise MultiClaimVerificationError("article_candidate_report_mismatch")
        status: str
        finding: UnifiedVerificationReport | None = None
        codes: tuple[str, ...] = ()
        if index >= settings.max_verifications:
            status, codes = "SKIPPED_LIMIT", ("CLAIM_BUDGET_EXHAUSTED",)
        else:
            try:
                raw = await runner(
                    session, claim=candidate.literal_text,
                    wikipedia_top_k=settings.wikipedia_top_k,
                    external_top_k=settings.external_top_k,
                    nli_threshold=settings.nli_threshold,
                    assessed_at=at,
                )
                finding = _validate_unified_report(raw, claim=candidate.literal_text, at=at)
                status = ("UNAVAILABLE" if finding.wikipedia.status != "AVAILABLE"
                          and finding.external.status != "AVAILABLE" else "ASSESSED")
                if status == "UNAVAILABLE":
                    codes = ("BOTH_EVIDENCE_PATHS_UNAVAILABLE_OR_INSUFFICIENT",)
            except Exception:
                # Do not expose raw exception text, submitted content, SQL, or secrets.
                status, codes = "FAILED", ("CLAIM_VERIFICATION_FAILED",)
        results.append(ClaimVerificationItem(
            candidate_id=candidate.candidate_id,
            literal_text=candidate.literal_text,
            start_char=candidate.start_char, end_char=candidate.end_char,
            paragraph_index=candidate.paragraph_index,
            normalized_fingerprint=candidate.normalized_fingerprint,
            has_reporting_attribution=candidate.has_reporting_attribution,
            duplicate_locations=candidate.duplicate_locations,
            status=status, report=finding, warning_codes=codes,
        ))

    assessed = sum(item.status == "ASSESSED" for item in results)
    unavailable = sum(item.status == "UNAVAILABLE" for item in results)
    failed = sum(item.status == "FAILED" for item in results)
    skipped = sum(item.status == "SKIPPED_LIMIT" for item in results)
    warnings = {"NO_ARTICLE_LEVEL_TRUTH_VERDICT", "SOURCE_INDEPENDENCE_NOT_ESTABLISHED"}
    if not results:
        warnings.add("NO_EXTRACTABLE_CLAIM_CANDIDATES")
    if skipped:
        warnings.add("CLAIM_VERIFICATION_BUDGET_EXHAUSTED")
    if failed:
        warnings.add("CLAIM_VERIFICATION_PARTIAL_FAILURE")
    if unavailable:
        warnings.add("EVIDENCE_UNAVAILABLE_FOR_SOME_CLAIMS")
    return MultiClaimVerificationReport(
        article_sha256=report.source_text_sha256, source_kind=report.source_kind,
        source_url=report.source_url, publisher_domain=report.publisher_domain,
        source_timestamp=report.source_timestamp, candidate_count=len(results), assessed_count=assessed,
        unavailable_count=unavailable, failed_count=failed, skipped_count=skipped,
        filtered_sentence_count=sum(number for _, number in report.filtered_reasons),
        omitted_candidate_count=report.omitted_for_limit, claims=tuple(results),
        assessed_at=at, warnings=tuple(sorted(warnings)),
    )
