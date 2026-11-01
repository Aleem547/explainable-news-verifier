"""Version-bound review of publisher-supplied origin leads; never certification.

The acquisition caller supplies checked raw HTML/text, then binds the result to
freshly audited source/fetch identities. Bylines, genre, links and hashes cannot
establish independent reporting. Every eligible pair remains explicitly unknown.
No HTTP, SQL, model inference, public request fields or positive independence.
"""
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json
from uuid import UUID

from apps.api.services.external_origin_context import ArticleContext
from apps.api.services.external_evidence_nli import validate_nli_input_bindings
from apps.api.services.external_independence_review import build_external_independence_review
from apps.api.services.external_reporting_origin_audit import (
    ReportingOriginObservation, assess_reporting_origin_dependencies,
)
from ml.verification.paragraph_inputs import validate_parent
from ml.provenance.identity import canonical_public_url

POLICY = "phase3.11-captured-source-origin-review-v1"


class CapturedOriginReviewError(ValueError):
    pass


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _sha(value):
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


@dataclass(frozen=True, slots=True)
class PageOriginContext:
    article_url: str
    text_sha256: str
    html_sha256: str
    reported_author: str | None
    reviewed_genre: str
    context_json: str
    policy_version: str = POLICY

    @property
    def capture_sha256(self):
        return sha256(_json([self.policy_version, self.article_url, self.text_sha256,
                             self.html_sha256, self.reported_author, self.reviewed_genre,
                             self.context_json]).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class ReportingSourceCapture:
    document_id: UUID
    document_version_id: UUID
    source_id: UUID
    fetch_observation_id: UUID
    retrieved_at: datetime
    fetch_observed_at: datetime
    page: PageOriginContext

    @property
    def binding_sha256(self):
        return sha256(_json([POLICY, str(self.document_id), str(self.document_version_id),
                             str(self.source_id), str(self.fetch_observation_id),
                             self.retrieved_at.isoformat(), self.fetch_observed_at.isoformat(),
                             self.page.capture_sha256]).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class SourceOriginDiagnostic:
    document_version_id: UUID
    source_capture_sha256: str
    reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CapturedOriginReview:
    review_packet_sha256: str
    capture_binding_sha256s: tuple[str, ...]
    source_diagnostics: tuple[SourceOriginDiagnostic, ...]
    origin_audit: object
    policy_version: str = POLICY
    independence_status: str = "NOT_ESTABLISHED"
    independently_verified: bool = False
    independent_corroboration_established: bool = False


def capture_page_origin(*, article_url, text, html_body, expected_html_sha256,
                        reported_author, reviewed_author, reviewed_genre):
    """Inspect one already approved fetch; supplied metadata remains untrusted."""
    if (not isinstance(html_body, bytes) or not 1 <= len(html_body) <= 2_000_000
            or not isinstance(text, str) or not 100 <= len(text) <= 100_000
            or sha256(html_body).hexdigest() != expected_html_sha256
            or not isinstance(reviewed_author, str) or not 1 <= len(reviewed_author) <= 200
            or reviewed_genre not in {"NEWS_REPORT", "ANALYSIS_ARTICLE", "UNKNOWN"}
            or reported_author is not None and (not isinstance(reported_author, str) or len(reported_author) > 500)):
        raise CapturedOriginReviewError("invalid_origin_page_capture")
    if canonical_public_url(article_url) != article_url or not article_url.startswith("https://"):
        raise CapturedOriginReviewError("invalid_origin_page_url")
    parser = ArticleContext(article_url)
    parser.feed(html_body.decode("utf-8", errors="replace"))
    parser.close()
    return PageOriginContext(article_url, sha256(text.encode()).hexdigest(), expected_html_sha256,
                             reported_author, reviewed_genre, _json(parser.result(reviewed_author)))


def _validate_page(page):
    if (type(page) is not PageOriginContext or page.policy_version != POLICY
            or not _sha(page.html_sha256) or not _sha(page.text_sha256)
            or page.reviewed_genre not in {"NEWS_REPORT", "ANALYSIS_ARTICLE", "UNKNOWN"}
            or not isinstance(page.context_json, str) or len(page.context_json) > 100_000
            or page.reported_author is not None and (not isinstance(page.reported_author, str) or len(page.reported_author)>500)):
        raise CapturedOriginReviewError("invalid_origin_page_record")
    try:
        context = json.loads(page.context_json)
    except (ValueError, TypeError) as exc:
        raise CapturedOriginReviewError("invalid_origin_context_json") from exc
    if (not isinstance(context, dict) or page.context_json != _json(context)
            or context.get("origin_authenticated") is not False
            or context.get("independence_status") != "NOT_ESTABLISHED"
            or context.get("byline_leads_are_publisher_supplied") is not True
            or context.get("photo_credits_are_not_text_origin_proof") is not True
            or type(context.get("reference_leads")) is not list or len(context["reference_leads"])>16
            or type(context.get("matching_byline_profile_lead_observed")) is not bool):
        raise CapturedOriginReviewError("invalid_or_promoted_origin_context")
    return context


def bind_source_capture(parent, page):
    validate_parent(parent)
    _validate_page(page)
    if (page.article_url != parent.original_url or page.text_sha256 != parent.snapshot_sha256
            or page.html_sha256 != parent.fetch_html_sha256):
        raise CapturedOriginReviewError("origin_page_and_audited_snapshot_mismatch")
    return ReportingSourceCapture(parent.document_id, parent.document_version_id, parent.source_id,
                                  parent.fetch_observation_id, parent.retrieved_at, parent.fetch_observed_at, page)


def review_captured_reporting_origins(*, nli_report, agreement_report, independence_review,
                                     captures, reviewed_at):
    """Bind unknown-origin observations to the actual eligible paragraph pairs.

    A body citation, photo credit, missing link, distinct byline, or publisher
    label does not automatically indicate either shared or independent reporting.
    Dependency indicators require their separately scoped audit path.
    """
    validate_nli_input_bindings(nli_report)
    selection = nli_report.paragraph_selection
    if selection is None:
        raise CapturedOriginReviewError("audited_paragraph_selection_required")
    expected = build_external_independence_review(nli_report=nli_report, agreement_report=agreement_report)
    if independence_review != expected:
        raise CapturedOriginReviewError("origin_review_packet_mismatch")
    if (type(captures) is not tuple or not 2 <= len(captures) <= 20
            or any(type(c) is not ReportingSourceCapture for c in captures)):
        raise CapturedOriginReviewError("invalid_bound_source_capture_batch")
    by_version = {c.document_version_id: c for c in captures}
    if len(by_version) != len(captures) or set(by_version) != {p.document_version_id for p in selection.parents}:
        raise CapturedOriginReviewError("origin_source_capture_coverage_mismatch")
    if (not isinstance(reviewed_at, datetime) or reviewed_at.tzinfo is None or reviewed_at.utcoffset() is None
            or reviewed_at < nli_report.assessed_at
            or reviewed_at > datetime.now(UTC)+timedelta(minutes=5)):
        raise CapturedOriginReviewError("invalid_origin_review_time")
    contexts = {}
    for parent in selection.parents:
        capture = by_version[parent.document_version_id]
        if capture != bind_source_capture(parent, capture.page):
            raise CapturedOriginReviewError("origin_capture_fetch_or_source_binding_mismatch")
        contexts[capture.document_version_id] = _validate_page(capture.page)
    diagnostics = []
    for capture in sorted(captures, key=lambda c:c.document_version_id.hex):
        context = contexts[capture.document_version_id]
        reasons = {"ORIGINAL_REPORTING_NOT_AUTHENTICATED", "PHOTO_CREDITS_ARE_NOT_TEXT_ORIGIN_PROOF"}
        if capture.page.reported_author is None:
            reasons.add("EXTRACTED_AUTHOR_MISSING_DOES_NOT_MEAN_NO_BYLINE")
        if context["matching_byline_profile_lead_observed"]:
            reasons.add("PUBLISHER_BYLINE_PROFILE_IS_NOT_ORIGIN_PROOF")
        if capture.page.reviewed_genre != "NEWS_REPORT":
            reasons.add("GENRE_REQUIRES_ORIGINAL_REPORTING_REVIEW")
        if (context.get("collection_scope") != "article_elements"
                or any(context.get(k) is not False for k in (
                    "selected_scope_reference_limit_reached", "html_structure_limit_reached",
                    "reference_details_export_capped"))):
            reasons.add("REFERENCE_SCAN_INCOMPLETE")
        diagnostics.append(SourceOriginDiagnostic(capture.document_version_id,
                                                   capture.binding_sha256, tuple(sorted(reasons))))
    notes = []
    for pair in expected.review_candidates:
        for version in (pair.left_version_id, pair.right_version_id):
            capture = by_version[version]
            notes.append(ReportingOriginObservation(pair.left_passage_id, pair.right_passage_id,
                "REPORTING_ORIGIN_UNKNOWN", capture.page.article_url, capture.binding_sha256,
                "server.captured-origin-review.v1", reviewed_at))
    audit = assess_reporting_origin_dependencies(nli_report=nli_report, agreement_report=agreement_report,
                                               independence_review=expected, observations=tuple(notes))
    return CapturedOriginReview(expected.review_packet_sha256,
        tuple(sorted(c.binding_sha256 for c in captures)), tuple(diagnostics), audit)
