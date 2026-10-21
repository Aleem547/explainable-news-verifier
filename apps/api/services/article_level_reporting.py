"""Phase 13E.6: auditable presentation of individual article-claim findings.

Offline/report-only: no model inference, network, SQL, storage or API routes.
Article inputs are never promoted to independent evidence. We count execution
statuses, not true claims or independently corroborating publishers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from apps.api.services.article_claim_candidates import (
    ClaimCandidatePolicy,
    extract_article_claim_candidates,
)
from apps.api.services.article_multi_claim_verification import (
    POLICY_VERSION as MULTI_CLAIM_POLICY_VERSION,
    ClaimVerificationItem,
    MultiClaimVerificationReport,
    _bounded_reasons,
    _validate_unified_report,
)
from apps.api.services.article_url_preparation import PreparedArticleUrl
from apps.api.services.pasted_article_preparation import PreparedPastedArticle

POLICY_VERSION = "phase13e6-article-report-v1"
_VALID_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_STATUS = frozenset(("ASSESSED", "UNAVAILABLE", "FAILED", "SKIPPED_LIMIT"))


class ArticleReportingError(ValueError):
    """Safe error code: never include submitted text, URLs or secrets."""


@dataclass(frozen=True, slots=True)
class ArticleEvidenceReference:
    """A claim-specific reference, NOT an independent corroboration unit."""

    citation_id: str
    claim_id: str
    passage_id: UUID
    document_version_id: UUID
    publisher_domain: str
    article_url: str
    nli_label: str
    nli_confidence: float
    nli_threshold_passed: bool
    dependency_risk_family: int
    duplicate_group: int
    independence_status: Literal["NOT_ESTABLISHED"] = "NOT_ESTABLISHED"


@dataclass(frozen=True, slots=True)
class ArticleClaimFinding:
    candidate_id: str
    literal_text: str
    start_char: int
    end_char: int
    paragraph_index: int
    normalized_fingerprint: str
    duplicate_locations: tuple[tuple[int, int], ...]
    has_reporting_attribution: bool
    execution_status: str
    wikipedia_status: str | None
    wikipedia_verdict: str | None
    wikipedia_supporting_pages: tuple[str, ...]
    wikipedia_refuting_pages: tuple[str, ...]
    external_status: str | None
    external_verdict: str | None
    external_references: tuple[ArticleEvidenceReference, ...]
    cross_corpus_relationship: str | None
    warning_codes: tuple[str, ...]
    independent_corroboration_established: bool = False


@dataclass(frozen=True, slots=True)
class ArticleLevelReport:
    article_sha256: str
    source_kind: str
    source_url: str | None
    publisher_domain: str | None
    source_timestamp: datetime
    assessed_at: datetime
    candidate_count: int
    assessed_count: int
    unavailable_count: int
    failed_count: int
    skipped_count: int
    filtered_sentence_count: int
    omitted_candidate_count: int
    wikipedia_available_count: int
    external_available_count: int
    opposing_corpus_count: int
    conflicting_corpus_count: int
    claims: tuple[ArticleClaimFinding, ...]
    warnings: tuple[str, ...]
    policy_version: str = POLICY_VERSION
    provenance_status: Literal["ARTICLE_INPUT_NOT_INDEPENDENT_EVIDENCE"] = (
        "ARTICLE_INPUT_NOT_INDEPENDENT_EVIDENCE"
    )
    independence_status: Literal["NOT_ESTABLISHED"] = "NOT_ESTABLISHED"
    independently_verified: bool = False
    independent_corroboration_established: bool = False
    eligible_as_independent_evidence: bool = False
    overall_article_truth_verdict: None = None
    overall_article_truth_probability: None = None


def _expected_status_warnings(status: str) -> tuple[str, ...]:
    return {
        "ASSESSED": (),
        "UNAVAILABLE": ("BOTH_EVIDENCE_PATHS_UNAVAILABLE_OR_INSUFFICIENT",),
        "FAILED": ("CLAIM_VERIFICATION_FAILED",),
        "SKIPPED_LIMIT": ("CLAIM_BUDGET_EXHAUSTED",),
    }[status]


def _expected_report_warnings(*, candidate_count: int, failed: int,
                              skipped: int, unavailable: int) -> tuple[str, ...]:
    codes = {"NO_ARTICLE_LEVEL_TRUTH_VERDICT", "SOURCE_INDEPENDENCE_NOT_ESTABLISHED"}
    if candidate_count == 0:
        codes.add("NO_EXTRACTABLE_CLAIM_CANDIDATES")
    if skipped:
        codes.add("CLAIM_VERIFICATION_BUDGET_EXHAUSTED")
    if failed:
        codes.add("CLAIM_VERIFICATION_PARTIAL_FAILURE")
    if unavailable:
        codes.add("EVIDENCE_UNAVAILABLE_FOR_SOME_CLAIMS")
    return tuple(sorted(codes))


def build_article_level_report(
    *,
    prepared: PreparedPastedArticle | PreparedArticleUrl,
    verification: MultiClaimVerificationReport,
    extraction_policy: ClaimCandidatePolicy | None = None,
) -> ArticleLevelReport:
    """Build an immutable, source-checked report; reject inconsistent inputs.

    `prepared` and `verification` must be produced by trusted server-side code.
    If Phase 13E.5 used a custom extraction policy, supply the same policy here.
    This function does not call upstream models or mutate/persist article text.
    """
    if (not isinstance(verification, MultiClaimVerificationReport)
            or verification.policy_version != MULTI_CLAIM_POLICY_VERSION
            or verification.independently_verified is not False
            or verification.independent_corroboration_established is not False
            or verification.eligible_as_independent_evidence is not False
            or verification.overall_article_truth_verdict is not None):
        raise ArticleReportingError("invalid_multi_claim_report")
    at = verification.assessed_at
    if (not isinstance(at, datetime) or at.tzinfo is None
            or at.utcoffset() is None
            or at > datetime.now(UTC) + timedelta(minutes=5)):
        raise ArticleReportingError("invalid_assessment_timestamp")
    try:
        expected = extract_article_claim_candidates(prepared=prepared, policy=extraction_policy)
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ArticleReportingError("article_source_provenance_invalid") from None
    if (verification.source_kind != expected.source_kind
            or verification.article_sha256 != expected.source_text_sha256
            or _VALID_SHA256.fullmatch(verification.article_sha256) is None
            or verification.source_url != expected.source_url
            or verification.publisher_domain != expected.publisher_domain
            or verification.source_timestamp != expected.source_timestamp
            or type(verification.candidate_count) is not int
            or verification.candidate_count != len(expected.candidates)
            or not isinstance(verification.claims, tuple)
            or len(verification.claims) != len(expected.candidates)
            or not _bounded_reasons(verification.warnings)
            or type(verification.filtered_sentence_count) is not int
            or verification.filtered_sentence_count != sum(n for _, n in expected.filtered_reasons)
            or type(verification.omitted_candidate_count) is not int
            or verification.omitted_candidate_count != expected.omitted_for_limit):
        raise ArticleReportingError("article_report_source_mismatch")

    if any(type(c) is not int or not 0 <= c <= 50 for c in (
        verification.assessed_count, verification.unavailable_count,
        verification.failed_count, verification.skipped_count,
    )):
        raise ArticleReportingError("article_report_invalid_counts")
    if (verification.assessed_count + verification.unavailable_count
            + verification.failed_count + verification.skipped_count != len(expected.candidates)):
        raise ArticleReportingError("article_report_invalid_counts")

    findings: list[ArticleClaimFinding] = []
    wiki_available = external_available = opposing = conflicting = 0
    status_counts: dict[str, int] = {key: 0 for key in _STATUS}
    for claim, candidate in zip(verification.claims, expected.candidates, strict=True):
        if not isinstance(claim, ClaimVerificationItem):
            raise ArticleReportingError("article_claim_invalid_type")
        if (type(claim.start_char) is not int or type(claim.end_char) is not int
                or type(claim.paragraph_index) is not int
                or type(claim.has_reporting_attribution) is not bool
                or claim.candidate_id != candidate.candidate_id
                or claim.literal_text != candidate.literal_text
                or claim.start_char != candidate.start_char
                or claim.end_char != candidate.end_char
                or claim.paragraph_index != candidate.paragraph_index
                or claim.normalized_fingerprint != candidate.normalized_fingerprint
                or claim.duplicate_locations != candidate.duplicate_locations
                or claim.has_reporting_attribution != candidate.has_reporting_attribution):
            raise ArticleReportingError("article_claim_source_span_mismatch")
        if (claim.status not in _STATUS or not _bounded_reasons(claim.warning_codes)
                or claim.warning_codes != _expected_status_warnings(claim.status)):
            raise ArticleReportingError("article_claim_invalid_status")
        status_counts[claim.status] += 1
        if claim.status in ("FAILED", "SKIPPED_LIMIT"):
            if claim.report is not None:
                raise ArticleReportingError("article_claim_unexpected_verification")
            findings.append(ArticleClaimFinding(
                candidate_id=claim.candidate_id, literal_text=claim.literal_text,
                start_char=claim.start_char, end_char=claim.end_char,
                paragraph_index=claim.paragraph_index,
                normalized_fingerprint=claim.normalized_fingerprint,
                duplicate_locations=claim.duplicate_locations,
                has_reporting_attribution=claim.has_reporting_attribution,
                execution_status=claim.status,
                wikipedia_status=None, wikipedia_verdict=None,
                wikipedia_supporting_pages=(), wikipedia_refuting_pages=(),
                external_status=None, external_verdict=None, external_references=(),
                cross_corpus_relationship=None, warning_codes=claim.warning_codes,
            ))
            continue
        try:
            unified = _validate_unified_report(claim.report, claim=claim.literal_text, at=at)
        except (ValueError, TypeError, AttributeError) as exc:
            raise ArticleReportingError("article_claim_verification_invalid") from None
        if ((claim.status == "UNAVAILABLE") != (
            unified.wikipedia.status != "AVAILABLE" and unified.external.status != "AVAILABLE"
        )):
            raise ArticleReportingError("article_claim_status_mismatch")
        wiki_available += unified.wikipedia.status == "AVAILABLE"
        external_available += unified.external.status == "AVAILABLE"
        opposing += unified.relationship == "OPPOSING_CORPUS_FINDINGS"
        conflicting += unified.relationship == "CONFLICT_OR_REVIEW_REQUIRED"
        # Same passage can be cited for several claims. Keep the claim identity
        # in its citation ID because its NLI label is claim-specific.
        references = tuple(ArticleEvidenceReference(
            citation_id=f"ext-{claim.candidate_id[:16]}-{ref.passage_id.hex}",
            claim_id=claim.candidate_id,
            passage_id=ref.passage_id,
            document_version_id=ref.document_version_id,
            publisher_domain=ref.publisher_domain,
            article_url=ref.article_url,
            nli_label=ref.nli_label,
            nli_confidence=ref.nli_confidence,
            nli_threshold_passed=ref.nli_threshold_passed,
            dependency_risk_family=ref.dependency_risk_family,
            duplicate_group=ref.duplicate_group,
        ) for ref in unified.external.provenance)
        findings.append(ArticleClaimFinding(
            candidate_id=claim.candidate_id, literal_text=claim.literal_text,
            start_char=claim.start_char, end_char=claim.end_char,
            paragraph_index=claim.paragraph_index,
            normalized_fingerprint=claim.normalized_fingerprint,
            duplicate_locations=claim.duplicate_locations,
            has_reporting_attribution=claim.has_reporting_attribution,
            execution_status=claim.status,
            wikipedia_status=unified.wikipedia.status,
            wikipedia_verdict=unified.wikipedia.evidence_verdict,
            wikipedia_supporting_pages=unified.wikipedia.supporting_pages,
            wikipedia_refuting_pages=unified.wikipedia.refuting_pages,
            external_status=unified.external.status,
            external_verdict=unified.external.evidence_verdict,
            external_references=references,
            cross_corpus_relationship=unified.relationship,
            warning_codes=tuple(sorted(set(claim.warning_codes)
                                        | set(unified.warnings)
                                        | set(unified.wikipedia.warnings)
                                        | set(unified.external.warnings))),
        ))

    if (status_counts["ASSESSED"] != verification.assessed_count
            or status_counts["UNAVAILABLE"] != verification.unavailable_count
            or status_counts["FAILED"] != verification.failed_count
            or status_counts["SKIPPED_LIMIT"] != verification.skipped_count
            or verification.warnings != _expected_report_warnings(
                candidate_count=len(findings), failed=verification.failed_count,
                skipped=verification.skipped_count, unavailable=verification.unavailable_count,
            )):
        raise ArticleReportingError("article_report_invalid_counts_or_warnings")
    warnings = set(verification.warnings)
    warnings.update((
        "ARTICLE_INPUT_IS_NOT_INDEPENDENT_EVIDENCE",
        "EXTERNAL_NLI_NOT_FACTUAL_TRUTH_PROBABILITY",
        "NO_ARTICLE_LEVEL_TRUTH_SCORE",
    ))
    if opposing:
        warnings.add("OPPOSING_CORPUS_FINDINGS_REVIEW_REQUIRED")
    if conflicting:
        warnings.add("CONFLICTING_EVIDENCE_REVIEW_REQUIRED")
    return ArticleLevelReport(
        article_sha256=verification.article_sha256,
        source_kind=verification.source_kind,
        source_url=verification.source_url,
        publisher_domain=verification.publisher_domain,
        source_timestamp=verification.source_timestamp,
        assessed_at=verification.assessed_at,
        candidate_count=verification.candidate_count,
        assessed_count=verification.assessed_count,
        unavailable_count=verification.unavailable_count,
        failed_count=verification.failed_count,
        skipped_count=verification.skipped_count,
        filtered_sentence_count=verification.filtered_sentence_count,
        omitted_candidate_count=verification.omitted_candidate_count,
        wikipedia_available_count=wiki_available,
        external_available_count=external_available,
        opposing_corpus_count=opposing,
        conflicting_corpus_count=conflicting,
        claims=tuple(findings), warnings=tuple(sorted(warnings)),
    )
