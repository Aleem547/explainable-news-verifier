"""Capture a page's attribution link as a version-bound, unverified origin lead.

Pure metadata construction: no HTTP, database writes, NLI, or independence
certification. The caller must use approved acquisition and verify the retained
snapshot. A fresh page with the same extracted text is a later observation, not
the original HTML snapshot and not proof of independent reporting.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from html.parser import HTMLParser
import json
import re
import unicodedata
from urllib.parse import urljoin, urlsplit
from uuid import UUID

from ml.provenance.identity import canonical_public_url

POLICY_VERSION = "phase3.3-bound-origin-reference-v1"


class OriginReferenceCaptureError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class OriginReferencePolicy:
    # Trusted server/operator configuration; never populated from request fields.
    subject_url: str
    target_reference_url: str
    expected_anchor_label: str
    required_declaration: str
    policy_id: str


@dataclass(frozen=True, slots=True)
class CapturedOriginReference:
    subject_document_id: UUID
    subject_document_version_id: UUID
    subject_url: str
    retained_text_sha256: str
    retained_retrieved_at: datetime
    target_reference_url: str
    observed_anchor_label: str
    observed_declaration: str
    matching_anchor_occurrences: int
    evidence_page_html_sha256: str
    observed_at: datetime
    capture_policy_id: str
    capture_record_sha256: str
    indicator: str = "CROSS_PUBLICATION_ATTRIBUTION"
    status: str = "UNAUTHENTICATED_DEPENDENCY_LEAD"
    policy_version: str = POLICY_VERSION
    target_full_text_ingested_by_this_capture: bool = False
    bound_to_eligible_origin_review_pair: bool = False
    independence_status: str = "NOT_ESTABLISHED"
    independently_verified: bool = False
    independent_corroboration_established: bool = False


def normalized_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _https_url(value: str) -> str:
    try:
        canonical = canonical_public_url(value)
        parsed = urlsplit(canonical)
        if parsed.scheme != "https" or parsed.port not in (None, 443) or canonical != value:
            raise ValueError
        return canonical
    except (ValueError, TypeError, AttributeError):
        raise OriginReferenceCaptureError("origin_reference_url_invalid") from None


class _Anchors(HTMLParser):
    ignored = {"head", "script", "style", "template", "noscript", "svg"}
    void = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.elements = []
        self.current = None
        self.anchors = []

    def handle_starttag(self, tag, attrs):
        hidden = (bool(self.elements and self.elements[-1][1]) or tag in self.ignored
                  or any(key == "hidden" or (key == "aria-hidden" and str(value).casefold() == "true")
                         for key, value in attrs))
        if tag not in self.void:
            self.elements.append((tag, hidden))
            if len(self.elements) > 256:
                raise OriginReferenceCaptureError("origin_html_nesting_limit_exceeded")
        if hidden:
            return
        if tag == "a":
            if self.current is not None:
                raise OriginReferenceCaptureError("nested_origin_anchor_refused")
            hrefs = [value for key, value in attrs if key == "href"]
            self.current = (hrefs[0], []) if len(hrefs) == 1 and isinstance(hrefs[0], str) else (None, [])

    def handle_endtag(self, tag):
        index = next((i for i in range(len(self.elements) - 1, -1, -1) if self.elements[i][0] == tag), None)
        if index is None:
            return
        hidden = self.elements[index][1]
        del self.elements[index:]
        if hidden:
            return
        if tag == "a" and self.current is not None:
            href, text = self.current
            self.anchors.append((href, " ".join("".join(text).split())))
            self.current = None
            if len(self.anchors) > 5000:
                raise OriginReferenceCaptureError("too_many_origin_anchors")

    def handle_data(self, data):
        if not (self.elements and self.elements[-1][1]) and self.current is not None:
            self.current[1].append(data)


def capture_origin_reference(
    *, policy: OriginReferencePolicy, subject_document_id: UUID,
    subject_document_version_id: UUID, retained_text_sha256: str,
    retained_retrieved_at: datetime, fetched_url: str, html_body: bytes,
    extracted_text: str, observed_at: datetime,
) -> CapturedOriginReference:
    if type(policy) is not OriginReferencePolicy:
        raise OriginReferenceCaptureError("origin_policy_type_invalid")
    source, target = _https_url(policy.subject_url), _https_url(policy.target_reference_url)
    if source == target:
        raise OriginReferenceCaptureError("self_reference_not_a_cross_publication_lead")
    if (type(subject_document_id) is not UUID or type(subject_document_version_id) is not UUID
            or not isinstance(retained_text_sha256, str)
            or not re.fullmatch(r"[0-9a-f]{64}", retained_text_sha256)):
        raise OriginReferenceCaptureError("retained_origin_subject_identity_invalid")
    if (any(not isinstance(t, datetime) or t.tzinfo is None or t.utcoffset() is None
            for t in (retained_retrieved_at, observed_at))
            or observed_at < retained_retrieved_at
            or observed_at > datetime.now(UTC) + timedelta(minutes=5)):
        raise OriginReferenceCaptureError("origin_capture_timestamp_invalid")
    if fetched_url != source:
        raise OriginReferenceCaptureError("origin_evidence_page_identity_mismatch")
    if (not isinstance(html_body, bytes) or not 1 <= len(html_body) <= 2_000_000
            or not isinstance(extracted_text, str) or not 100 <= len(extracted_text) <= 100_000):
        raise OriginReferenceCaptureError("origin_evidence_content_invalid")
    if sha256(extracted_text.encode()).hexdigest() != retained_text_sha256:
        raise OriginReferenceCaptureError("origin_source_text_changed_since_retention")
    if (not isinstance(policy.expected_anchor_label, str) or not 10 <= len(policy.expected_anchor_label) <= 300
            or not isinstance(policy.required_declaration, str) or not 10 <= len(policy.required_declaration) <= 300
            or not isinstance(policy.policy_id, str)
            or not re.fullmatch(r"[A-Za-z0-9_.-]{3,100}", policy.policy_id)):
        raise OriginReferenceCaptureError("origin_reference_policy_invalid")
    if normalized_text(policy.required_declaration) not in normalized_text(extracted_text):
        raise OriginReferenceCaptureError("required_origin_declaration_not_found")
    try:
        body = html_body.decode("utf-8-sig")
    except UnicodeError:
        raise OriginReferenceCaptureError("origin_page_encoding_refused") from None
    parser = _Anchors()
    parser.feed(body)
    parser.close()
    matches = []
    for href, label in parser.anchors:
        if href is None:
            continue
        try:
            url = canonical_public_url(urljoin(source, href))
        except (ValueError, TypeError, AttributeError):
            continue
        if url == target and 1 <= len(label) <= 500 and normalized_text(policy.expected_anchor_label) in normalized_text(label):
            matches.append(label)
    if not 1 <= len(matches) <= 10:
        raise OriginReferenceCaptureError("reviewed_origin_reference_not_found_or_ambiguous")
    record = dict(
        subject_document_id=subject_document_id,
        subject_document_version_id=subject_document_version_id, subject_url=source,
        retained_text_sha256=retained_text_sha256, retained_retrieved_at=retained_retrieved_at,
        target_reference_url=target, observed_anchor_label=min(matches),
        observed_declaration=policy.required_declaration, matching_anchor_occurrences=len(matches),
        evidence_page_html_sha256=sha256(html_body).hexdigest(), observed_at=observed_at,
        capture_policy_id=policy.policy_id,
    )
    # This fingerprint supports consistency/replay; it is not a signature or
    # acquisition/reviewer authentication. Keep that distinction in consumers.
    packet = {**record, "policy_version": POLICY_VERSION, "indicator": "CROSS_PUBLICATION_ATTRIBUTION"}
    def json_value(value):
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, UUID):
            return str(value)
        raise TypeError("Unsupported origin capture value")
    fingerprint = sha256(json.dumps(packet, sort_keys=True, separators=(",", ":"), default=json_value).encode()).hexdigest()
    return CapturedOriginReference(**record, capture_record_sha256=fingerprint)
