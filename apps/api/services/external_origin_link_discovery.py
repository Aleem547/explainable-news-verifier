"""Truthful publisher-link discovery from an unverified, version-bound capture.

Pure metadata only. This is a distinct provider, never fabricated RSS discovery.
The policy must be trusted server/operator configuration. A capture fingerprint
provides consistency, not authenticated reporting origin or content permission.
"""

from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json
import re
from urllib.parse import urlsplit
from uuid import UUID

from apps.api.connectors.contracts import ContentKind, DiscoveryResult, ExternalDiscoveryHit, Provider
from apps.api.services.external_origin_reference_capture import CapturedOriginReference, POLICY_VERSION
from ml.ingestion.validation import validated_discovery_identity


class OriginLinkDiscoveryError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class OriginLinkDiscoveryPolicy:
    subject_url: str
    subject_version_id: UUID
    subject_text_sha256: str
    target_url: str
    target_publisher_name: str
    target_publisher_domain: str


@dataclass(frozen=True, slots=True)
class OriginLinkedDiscovery:
    result: DiscoveryResult
    source_document_version_id: UUID
    source_page_url: str
    capture_record_sha256: str
    title_basis: str = "source_page_anchor_text"
    independently_verified: bool = False
    independent_corroboration_established: bool = False


def discover_captured_publisher_link(*, reference: CapturedOriginReference,
                                    policy: OriginLinkDiscoveryPolicy) -> OriginLinkedDiscovery:
    if type(reference) is not CapturedOriginReference or type(policy) is not OriginLinkDiscoveryPolicy:
        raise OriginLinkDiscoveryError("captured_link_type_invalid")
    if (reference.policy_version != POLICY_VERSION
            or reference.status != "UNAUTHENTICATED_DEPENDENCY_LEAD"
            or reference.indicator != "CROSS_PUBLICATION_ATTRIBUTION"
            or reference.independence_status != "NOT_ESTABLISHED"
            or reference.independently_verified is not False
            or reference.independent_corroboration_established is not False
            or reference.target_full_text_ingested_by_this_capture is not False
            or reference.bound_to_eligible_origin_review_pair is not False):
        raise OriginLinkDiscoveryError("captured_link_flags_invalid")
    if (reference.subject_url != policy.subject_url
            or reference.subject_document_version_id != policy.subject_version_id
            or reference.retained_text_sha256 != policy.subject_text_sha256
            or reference.target_reference_url != policy.target_url
            or urlsplit(policy.target_url).hostname != policy.target_publisher_domain):
        raise OriginLinkDiscoveryError("captured_link_policy_identity_mismatch")
    if (type(reference.subject_document_id) is not UUID or type(reference.subject_document_version_id) is not UUID
            or not isinstance(reference.retained_text_sha256, str)
            or not re.fullmatch(r"[0-9a-f]{64}", reference.retained_text_sha256)
            or type(reference.matching_anchor_occurrences) is not int
            or not 1 <= reference.matching_anchor_occurrences <= 10):
        raise OriginLinkDiscoveryError("captured_link_identity_invalid")
    if (any(not isinstance(t, datetime) or t.tzinfo is None or t.utcoffset() is None
            for t in (reference.observed_at, reference.retained_retrieved_at))
            or reference.observed_at < reference.retained_retrieved_at
            or reference.observed_at > datetime.now(UTC) + timedelta(minutes=5)):
        raise OriginLinkDiscoveryError("captured_link_time_invalid")
    fields = (
        "subject_document_id", "subject_document_version_id", "subject_url", "retained_text_sha256",
        "retained_retrieved_at", "target_reference_url", "observed_anchor_label", "observed_declaration",
        "matching_anchor_occurrences", "evidence_page_html_sha256", "observed_at", "capture_policy_id",
        "policy_version", "indicator",
    )
    values = asdict(reference)
    def encode(value):
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, UUID):
            return str(value)
        raise TypeError("Unsupported capture field")
    fingerprint = sha256(json.dumps({key: values[key] for key in fields}, sort_keys=True,
                                    separators=(",", ":"), default=encode).encode()).hexdigest()
    if fingerprint != reference.capture_record_sha256:
        raise OriginLinkDiscoveryError("captured_link_fingerprint_mismatch")
    hit = ExternalDiscoveryHit(
        provider=Provider.PUBLISHER_LINK, kind=ContentKind.NEWS_ARTICLE,
        url=reference.target_reference_url, publisher_domain=policy.target_publisher_domain,
        publisher_name=policy.target_publisher_name, title=reference.observed_anchor_label,
        snippet=None, discovered_at=reference.observed_at, published_at=None,
    )
    validated_discovery_identity(hit)
    return OriginLinkedDiscovery(
        result=DiscoveryResult(provider=Provider.PUBLISHER_LINK,
                               query=reference.observed_anchor_label[:300], hits=(hit,)),
        source_document_version_id=reference.subject_document_version_id,
        source_page_url=reference.subject_url, capture_record_sha256=reference.capture_record_sha256,
    )
