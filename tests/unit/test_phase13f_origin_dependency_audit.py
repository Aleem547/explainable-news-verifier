"""Phase 13F.4.56 conservative, offline origin-dependency annotation tests."""

from __future__ import annotations

import dataclasses
import unittest
from datetime import timedelta
from uuid import uuid4

from apps.api.services.external_evidence_agreement import analyze_external_evidence_agreement
from apps.api.services.external_independence_review import build_external_independence_review
from apps.api.services.external_reporting_origin_audit import (
    ReportingOriginAuditError,
    ReportingOriginObservation,
    assess_reporting_origin_dependencies,
)
from test_phase13d6_evidence_agreement import NOW, make_passage, make_report

HASH = "a" * 64


class ReportingOriginAuditTests(unittest.TestCase):
    def setUp(self):
        a, b, c = [make_passage(family=i, group=i) for i in (1, 2, 3)]
        self.nli = make_report(a, b, c)
        self.agreement = analyze_external_evidence_agreement(nli_report=self.nli)
        self.review = build_external_independence_review(
            nli_report=self.nli, agreement_report=self.agreement,
        )
        self.pair = self.review.review_candidates[0]

    def note(self, indicator="SHARED_WIRE_STORY", **overrides):
        data = dict(
            left_passage_id=self.pair.left_passage_id,
            right_passage_id=self.pair.right_passage_id,
            indicator=indicator,
            reference_url="https://source.example.org/origin-record",
            reference_sha256=HASH,
            observer_label="operator.audit-1",
            observed_at=NOW + timedelta(minutes=1),
        )
        data.update(overrides)
        return ReportingOriginObservation(**data)

    def audit(self, *notes, **kwargs):
        params = dict(nli_report=self.nli, agreement_report=self.agreement,
                      independence_review=self.review, observations=tuple(notes))
        params.update(kwargs)
        return assess_reporting_origin_dependencies(**params)

    def reject(self, expected, *notes, **kwargs):
        with self.assertRaisesRegex(ReportingOriginAuditError, expected):
            self.audit(*notes, **kwargs)

    def test_empty_annotations_stay_unreviewed_and_unverified(self):
        audit = self.audit()
        self.assertEqual(len(audit.pairs), 3)
        self.assertTrue(all(p.status == "NOT_REVIEWED" for p in audit.pairs))
        self.assertEqual(audit.independence_status, "NOT_ESTABLISHED")
        self.assertFalse(audit.independently_verified)
        self.assertFalse(audit.independent_corroboration_established)

    def test_shared_wire_flags_dependency_not_truth(self):
        audit = self.audit(self.note())
        self.assertEqual(audit.pairs[0].status, "DEPENDENCY_INDICATED")
        self.assertEqual(audit.dependency_indicated_pairs, 1)
        self.assertFalse(audit.independently_verified)

    def test_each_negative_reuse_indicator(self):
        for code in (
            "SHARED_WIRE_STORY", "SYNDICATED_REPUBLICATION", "SHARED_PRIMARY_SOURCE",
            "COMMON_EDITORIAL_CONTROL", "CROSS_PUBLICATION_ATTRIBUTION",
            "DOCUMENTED_CONTENT_REUSE",
        ):
            with self.subTest(code=code):
                self.assertEqual(self.audit(self.note(code)).pairs[0].status, "DEPENDENCY_INDICATED")

    def test_different_origins_claimed_is_not_a_certificate(self):
        audit = self.audit(self.note("DISTINCT_ORIGIN_ASSERTED"))
        self.assertEqual(audit.pairs[0].status, "UNVERIFIED_ORIGIN_CLAIM")
        self.assertFalse(audit.independent_corroboration_established)
        self.assertFalse(audit.independently_verified)

    def test_no_dependency_observed_is_not_a_certificate(self):
        audit = self.audit(self.note("NO_DEPENDENCY_OBSERVED"))
        self.assertEqual(audit.pairs[0].status, "UNVERIFIED_ORIGIN_CLAIM")
        self.assertEqual(audit.independence_status, "NOT_ESTABLISHED")

    def test_dependency_overrides_distinct_origin_claim(self):
        a = self.note("DISTINCT_ORIGIN_ASSERTED")
        b = self.note("SHARED_PRIMARY_SOURCE", reference_sha256="b" * 64)
        self.assertEqual(self.audit(a, b).pairs[0].status, "DEPENDENCY_INDICATED")

    def test_observation_order_invariance(self):
        a = self.note("DISTINCT_ORIGIN_ASSERTED")
        b = self.note("SHARED_PRIMARY_SOURCE", reference_sha256="b" * 64)
        self.assertEqual(self.audit(a, b), self.audit(b, a))

    def test_wrong_pair_rejected(self):
        self.reject("observation_not_bound_to_review_pair", self.note(left_passage_id=uuid4()))

    def test_reverse_pair_rejected(self):
        self.reject("observation_not_bound_to_review_pair", self.note(
            left_passage_id=self.pair.right_passage_id,
            right_passage_id=self.pair.left_passage_id,
        ))

    def test_invalid_pair_identity_type_rejected(self):
        self.reject("invalid_observation_pair_identity", self.note(left_passage_id="not-uuid"))

    def test_unknown_dataclass_rejected(self):
        self.reject("invalid_observation_type", "fake-observation")

    def test_unhashable_indicator_rejected(self):
        self.reject("invalid_origin_indicator", self.note(indicator=["SHARED_WIRE_STORY"]))

    def test_future_observation_rejected(self):
        self.reject("invalid_observation_time", self.note(observed_at=NOW + timedelta(days=365)))

    def test_private_ip_reference_rejected(self):
        self.reject("invalid_reference_url", self.note(reference_url="https://192.168.1.5/a"))

    def test_duplicate_observation_rejected(self):
        note = self.note()
        self.reject("duplicate_origin_observation", note, note)

    def test_injected_indicator_rejected(self):
        self.reject("invalid_origin_indicator", self.note("PROVEN_INDEPENDENT"))

    def test_invalid_reference_hash_rejected(self):
        self.reject("invalid_reference_hash", self.note(reference_sha256="not-a-sha"))

    def test_unsafe_reference_urls_rejected(self):
        for url in ("http://news.example.org/story", "https://localhost/origin",
                    "https://operator:secret@news.example.org/a", "https://example.org/a#frag",
                    "https://example.org/a\nmore", "https://news"):
            with self.subTest(url=url):
                self.reject("invalid_reference_url", self.note(reference_url=url))

    def test_observer_label_is_not_authentication(self):
        report = self.audit(self.note(observer_label="trusted-sounding-person"))
        self.assertIn("ORIGIN_ANNOTATIONS_NOT_AUTHENTICATED", report.warnings)
        self.assertFalse(report.independently_verified)

    def test_invalid_observer_label_rejected(self):
        self.reject("invalid_observer_label", self.note(observer_label=""))

    def test_naive_or_stale_time_rejected(self):
        self.reject("invalid_observation_time", self.note(observed_at=NOW.replace(tzinfo=None)))
        self.reject("invalid_observation_time", self.note(observed_at=NOW-timedelta(seconds=1)))

    def test_not_tuple_or_oversized_batch_rejected(self):
        self.reject("invalid_observation_batch", observations=[self.note()])
        self.reject("invalid_observation_batch", observations=(self.note(),) * 101)

    def test_forged_review_rejected(self):
        fake = dataclasses.replace(self.review, review_packet_sha256="0" * 64)
        self.reject("independence_review_mismatch", independence_review=fake)

    def test_forged_nli_rejected(self):
        wrong = dataclasses.replace(self.nli, claim="Other claim")
        self.reject("invalid_upstream_review", nli_report=wrong)

    def test_forged_agreement_rejected(self):
        wrong = dataclasses.replace(self.agreement, supporting_unit_count=999)
        self.reject("invalid_upstream_review", agreement_report=wrong)

    def test_fingerprint_binds_review_and_annotations(self):
        a = self.audit()
        b = self.audit(self.note())
        self.assertNotEqual(a.audit_packet_sha256, b.audit_packet_sha256)
        self.assertEqual(a.review_packet_sha256, b.review_packet_sha256)
        self.assertEqual(len(a.audit_packet_sha256), 64)

    def test_result_immutable(self):
        result = self.audit()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            result.independently_verified = True

    def test_duplicate_bridged_sources_not_reviewable(self):
        nli = make_report(make_passage(family=1, group=1), make_passage(family=2, group=1))
        agreement = analyze_external_evidence_agreement(nli_report=nli)
        review = build_external_independence_review(nli_report=nli, agreement_report=agreement)
        result = assess_reporting_origin_dependencies(
            nli_report=nli, agreement_report=agreement, independence_review=review,
        )
        self.assertEqual(result.pairs, ())
        self.assertFalse(result.independently_verified)


if __name__ == "__main__":
    unittest.main()
