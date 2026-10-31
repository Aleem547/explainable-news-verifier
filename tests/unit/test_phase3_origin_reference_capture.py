"""Synthetic HTML tests for the real pure origin-reference capture service."""

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import unittest
from uuid import uuid4

from apps.api.services.external_origin_reference_capture import (
    OriginReferenceCaptureError, OriginReferencePolicy, capture_origin_reference,
)


class OriginCaptureTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.now(UTC)
        self.policy = OriginReferencePolicy(
            subject_url="https://www.nist.gov/news-events/news/reviewed-story",
            target_reference_url="https://jqi.umd.edu/news/reviewed-story",
            expected_anchor_label="New Chip-Based Frequency Combs Demonstrate Potential",
            required_declaration="a research partnership between NIST and the University of Maryland",
            policy_id="test-nist-jqi-v1",
        )
        self.text = ("Scientists at NIST and JQI, a research partnership between NIST and the University of Maryland, "
                     "have developed new chip-based optical frequency combs for measuring light.")
        self.anchor = '<a href="' + self.policy.target_reference_url + '">' + self.policy.expected_anchor_label + '</a>'
        self.values = dict(policy=self.policy, subject_document_id=uuid4(), subject_document_version_id=uuid4(),
                           retained_text_sha256=sha256(self.text.encode()).hexdigest(),
                           retained_retrieved_at=self.now - timedelta(hours=1), fetched_url=self.policy.subject_url,
                           html_body=("<html><body><article>" + self.anchor + "</article></body></html>").encode(),
                           extracted_text=self.text, observed_at=self.now)

    def capture(self, **changes):
        return capture_origin_reference(**{**self.values, **changes})

    def test_captures_reference_without_independence_promotion(self):
        result = self.capture()
        self.assertEqual(result.indicator, "CROSS_PUBLICATION_ATTRIBUTION")
        self.assertEqual(result.target_reference_url, self.policy.target_reference_url)
        self.assertFalse(result.independent_corroboration_established)
        self.assertFalse(result.target_full_text_ingested_by_this_capture)
        self.assertFalse(result.bound_to_eligible_origin_review_pair)

    def test_capture_record_is_immutable_and_deterministic(self):
        result = self.capture()
        self.assertEqual(result, self.capture())
        with self.assertRaises(FrozenInstanceError):
            result.independently_verified = True

    def test_different_version_changes_capture_fingerprint(self):
        self.assertNotEqual(self.capture().capture_record_sha256,
                            self.capture(subject_document_version_id=uuid4()).capture_record_sha256)

    def test_changed_article_text_is_rejected(self):
        with self.assertRaisesRegex(OriginReferenceCaptureError, "text_changed_since_retention"):
            self.capture(extracted_text=self.text + " Changed")

    def test_wrong_evidence_page_is_rejected(self):
        with self.assertRaisesRegex(OriginReferenceCaptureError, "page_identity_mismatch"):
            self.capture(fetched_url="https://example.org/different")

    def test_wrong_reference_destination_is_not_captured(self):
        html = self.anchor.replace("jqi.umd.edu", "other.example.org").encode()
        with self.assertRaises(OriginReferenceCaptureError):
            self.capture(html_body=html)

    def test_script_embedded_link_is_ignored(self):
        with self.assertRaises(OriginReferenceCaptureError):
            self.capture(html_body=("<script>" + self.anchor + "</script>").encode())

    def test_comment_embedded_link_is_ignored(self):
        with self.assertRaises(OriginReferenceCaptureError):
            self.capture(html_body=("<!-- " + self.anchor + " -->").encode())

    def test_template_embedded_link_is_ignored(self):
        with self.assertRaises(OriginReferenceCaptureError):
            self.capture(html_body=("<template>" + self.anchor + "</template>").encode())

    def test_head_link_is_ignored(self):
        with self.assertRaises(OriginReferenceCaptureError):
            self.capture(html_body=("<head>" + self.anchor + "</head>").encode())

    def test_hidden_attribute_link_is_ignored(self):
        with self.assertRaises(OriginReferenceCaptureError):
            self.capture(html_body=('<div hidden><div>' + self.anchor + '</div></div>').encode())

    def test_aria_hidden_link_is_ignored(self):
        with self.assertRaises(OriginReferenceCaptureError):
            self.capture(html_body=('<div aria-hidden="true">' + self.anchor + '</div>').encode())

    def test_oversized_label_is_not_exported(self):
        html = self.anchor.replace(self.policy.expected_anchor_label, self.policy.expected_anchor_label + 'x' * 600)
        with self.assertRaises(OriginReferenceCaptureError):
            self.capture(html_body=html.encode())

    def test_duplicate_href_attributes_are_refused(self):
        html = self.anchor.replace('href="', 'href="https://example.org/" href="', 1).encode()
        with self.assertRaises(OriginReferenceCaptureError):
            self.capture(html_body=html)

    def test_incorrect_label_is_not_captured(self):
        with self.assertRaises(OriginReferenceCaptureError):
            self.capture(html_body=self.anchor.replace(self.policy.expected_anchor_label, "Unrelated label").encode())

    def test_repeated_visible_reference_is_counted(self):
        result = self.capture(html_body=(self.anchor + self.anchor).encode())
        self.assertEqual(result.matching_anchor_occurrences, 2)

    def test_nested_formatting_in_label_is_supported(self):
        html = self.anchor.replace("Frequency Combs", "<strong>Frequency Combs</strong>").encode()
        self.assertEqual(self.capture(html_body=html).matching_anchor_occurrences, 1)

    def test_missing_declaration_is_refused(self):
        policy = replace(self.policy, required_declaration="an unrelated declared research collaboration")
        with self.assertRaisesRegex(OriginReferenceCaptureError, "declaration_not_found"):
            self.capture(policy=policy)

    def test_changed_html_with_same_bound_text_is_a_new_capture(self):
        first = self.capture()
        second = self.capture(html_body=self.values["html_body"] + b"\n")
        self.assertNotEqual(first.evidence_page_html_sha256, second.evidence_page_html_sha256)
        self.assertEqual(first.retained_text_sha256, second.retained_text_sha256)

    def test_naive_timestamp_is_refused(self):
        with self.assertRaises(OriginReferenceCaptureError):
            self.capture(observed_at=self.now.replace(tzinfo=None))

    def test_capture_predating_retention_is_refused(self):
        with self.assertRaises(OriginReferenceCaptureError):
            self.capture(observed_at=self.now - timedelta(days=1))

    def test_future_capture_is_refused(self):
        with self.assertRaises(OriginReferenceCaptureError):
            self.capture(observed_at=self.now + timedelta(days=1))

    def test_invalid_identity_is_refused(self):
        with self.assertRaises(OriginReferenceCaptureError):
            self.capture(subject_document_version_id="not-a-uuid")

    def test_insecure_policy_target_is_refused(self):
        with self.assertRaises(OriginReferenceCaptureError):
            self.capture(policy=replace(self.policy, target_reference_url="http://jqi.umd.edu/news/story"))

    def test_reference_is_not_inferred_from_body_words_alone(self):
        with self.assertRaises(OriginReferenceCaptureError):
            self.capture(html_body=b"<html><body>NIST works with JQI.</body></html>")


if __name__ == "__main__":
    unittest.main()
