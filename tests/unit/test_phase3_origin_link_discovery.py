from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import unittest
from uuid import uuid4

from apps.api.connectors.contracts import Provider
from apps.api.services.external_origin_reference_capture import OriginReferencePolicy, capture_origin_reference
from apps.api.services.external_origin_link_discovery import (
    OriginLinkDiscoveryError, OriginLinkDiscoveryPolicy, discover_captured_publisher_link,
)


class LinkedDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.source = "https://www.nist.gov/news-events/news/test"
        self.target = "https://jqi.umd.edu/news/test"
        self.version = uuid4()
        text = "NIST and JQI are a research partnership between NIST and the University of Maryland. " * 2
        self.policy = OriginLinkDiscoveryPolicy(self.source, self.version, sha256(text.encode()).hexdigest(),
                                                self.target, "JQI", "jqi.umd.edu")
        now = datetime.now(UTC)
        self.reference = capture_origin_reference(
            policy=OriginReferencePolicy(self.source, self.target, "Reviewed JQI frequency-comb story",
                                         "a research partnership between NIST and the University of Maryland", "test-link-v1"),
            subject_document_id=uuid4(), subject_document_version_id=self.version,
            retained_text_sha256=self.policy.subject_text_sha256,
            retained_retrieved_at=now - timedelta(hours=1), observed_at=now,
            fetched_url=self.source, extracted_text=text,
            html_body=('<a href="' + self.target + '">Reviewed JQI frequency-comb story</a>').encode(),
        )

    def discover(self, reference=None, policy=None):
        return discover_captured_publisher_link(reference=reference or self.reference, policy=policy or self.policy)

    def test_link_uses_distinct_truthful_discovery_provider(self):
        hit = self.discover().result.hits[0]
        self.assertEqual(hit.provider, Provider.PUBLISHER_LINK)
        self.assertNotEqual(hit.provider, Provider.RSS_FEED)
        self.assertEqual(hit.url, self.target)

    def test_link_title_is_anchor_metadata_not_article_text(self):
        hit = self.discover().result.hits[0]
        self.assertEqual(hit.title, self.reference.observed_anchor_label)
        self.assertIsNone(hit.snippet)
        self.assertIsNone(hit.published_at)
        self.assertEqual(hit.discovered_at, self.reference.observed_at)

    def test_mutated_capture_content_is_refused(self):
        with self.assertRaisesRegex(OriginLinkDiscoveryError, "fingerprint_mismatch"):
            self.discover(replace(self.reference, observed_anchor_label="Changed JQI title"))

    def test_other_source_version_cannot_rebind_capture(self):
        with self.assertRaises(OriginLinkDiscoveryError):
            self.discover(policy=replace(self.policy, subject_version_id=uuid4()))

    def test_other_target_cannot_rebind_capture(self):
        with self.assertRaises(OriginLinkDiscoveryError):
            self.discover(policy=replace(self.policy, target_url="https://jqi.umd.edu/news/different"))

    def test_publisher_domain_mismatch_is_refused(self):
        with self.assertRaises(OriginLinkDiscoveryError):
            self.discover(policy=replace(self.policy, target_publisher_domain="example.org"))

    def test_independence_assertion_is_refused(self):
        with self.assertRaises(OriginLinkDiscoveryError):
            self.discover(replace(self.reference, independently_verified=True))

    def test_capture_is_not_promoted_to_pair_proof(self):
        with self.assertRaises(OriginLinkDiscoveryError):
            self.discover(replace(self.reference, bound_to_eligible_origin_review_pair=True))

    def test_malformed_capture_identity_is_refused(self):
        with self.assertRaises(OriginLinkDiscoveryError):
            self.discover(replace(self.reference, subject_document_id="not-a-uuid"))

    def test_fingerprint_does_not_become_an_authentication_claim(self):
        result = self.discover()
        self.assertFalse(result.independently_verified)
        self.assertFalse(result.independent_corroboration_established)

    def test_result_is_immutable(self):
        with self.assertRaises(FrozenInstanceError):
            self.discover().independently_verified = True

    def test_unsupported_capture_policy_version_is_refused(self):
        with self.assertRaises(OriginLinkDiscoveryError):
            self.discover(replace(self.reference, policy_version="unknown-policy"))
