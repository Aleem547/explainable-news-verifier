"""Phase 13F.4.57: real service contracts, synthetic evidence, no model/DB/HTTP.

Exercise replay validation, decision binding, the default orchestration branch,
and safe diagnostics. These tests do not establish real publisher independence.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError, asdict, replace
from datetime import timedelta
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import patch

from apps.api.services.external_corroboration_decision import (
    CorroborationDecisionError,
    ExternalEvidenceVerdict,
    decide_external_corroboration,
)
from apps.api.services.external_evidence_agreement import analyze_external_evidence_agreement
from apps.api.services.external_independence_review import build_external_independence_review
from apps.api.services.external_reporting_origin_audit import (
    ReportingOriginAuditError,
    ReportingOriginObservation,
    assess_reporting_origin_dependencies,
    summarize_reporting_origin_audit,
)
from apps.api.services.unified_verification import (
    _snapshot_external,
    orchestrate_unified_verification,
)
from test_phase13d6_evidence_agreement import NOW, make_passage, make_report


class AuditFixture:
    def prepare(self, *, duplicate=False):
        self.rows = tuple(make_passage(
            family=i, group=1 if duplicate else i,
        ) for i in (1, 2, 3))
        self.nli = make_report(*self.rows)
        self.agreement = analyze_external_evidence_agreement(nli_report=self.nli)
        self.review = build_external_independence_review(
            nli_report=self.nli, agreement_report=self.agreement,
        )

    def note(self, *, pair_index=0, indicator="SHARED_WIRE_STORY", **changes):
        pair = self.review.review_candidates[pair_index]
        data = dict(
            left_passage_id=pair.left_passage_id,
            right_passage_id=pair.right_passage_id,
            indicator=indicator,
            reference_url="https://origin.example.org/private-review-reference",
            reference_sha256="a" * 64,
            observer_label="private.operator-label",
            observed_at=NOW + timedelta(minutes=1),
        )
        data.update(changes)
        return ReportingOriginObservation(**data)

    def audit(self, *observations):
        return assess_reporting_origin_dependencies(
            nli_report=self.nli, agreement_report=self.agreement,
            independence_review=self.review, observations=tuple(observations),
        )

    def summarize(self, audit):
        return summarize_reporting_origin_audit(
            nli_report=self.nli, agreement_report=self.agreement,
            independence_review=self.review, audit=audit,
        )

    def decide(self, audit):
        return decide_external_corroboration(
            nli_report=self.nli, agreement_report=self.agreement,
            independence_review=self.review, reporting_origin_audit=audit,
        )

    def snapshot(self, audit, *, decision=None, review=None):
        return _snapshot_external(
            claim=self.nli.claim, at=self.nli.assessed_at, retrieved=self.rows,
            nli=self.nli, agreement=self.agreement,
            decision=self.decide(audit) if decision is None else decision,
            independence_review=self.review if review is None else review,
            reporting_origin_audit=audit,
        )


class AuditReplayTests(AuditFixture, TestCase):
    def setUp(self):
        self.prepare()

    def test_original_annotations_retained_in_canonical_order(self):
        first = self.note(pair_index=0)
        second = self.note(pair_index=1, indicator="DISTINCT_ORIGIN_ASSERTED")
        left, right = self.audit(first, second), self.audit(second, first)
        self.assertEqual(left, right)
        self.assertEqual(set(left.observations), {first, second})
        self.assertEqual(self.summarize(left).observations_count, 2)

    def test_empty_audit_means_unreviewed(self):
        summary = self.summarize(self.audit())
        self.assertEqual(summary.candidate_pair_count, 3)
        self.assertEqual(summary.unreviewed_pair_count, 3)
        self.assertEqual(summary.observations_count, 0)
        self.assertEqual(summary.dependency_indicated_pair_count, 0)

    def test_dependency_lead_reaches_decision_without_truth_promotion(self):
        decision = self.decide(self.audit(self.note()))
        self.assertEqual(decision.origin_audit.dependency_indicated_pair_count, 1)
        self.assertEqual(decision.origin_audit.unreviewed_pair_count, 2)
        self.assertIn("REPORTING_ORIGIN_DEPENDENCY_INDICATED", decision.warnings)
        self.assertIn("ORIGIN_ANNOTATIONS_NOT_AUTHENTICATED", decision.warnings)
        self.assertEqual(decision.evidence_verdict, ExternalEvidenceVerdict.PROVISIONAL_SUPPORT)
        self.assertEqual(decision.independence_status, "NOT_ESTABLISHED")
        self.assertFalse(decision.independently_verified)
        self.assertFalse(decision.independent_corroboration_established)

    def test_distinct_origin_annotation_stays_unverified(self):
        decision = self.decide(self.audit(self.note(indicator="DISTINCT_ORIGIN_ASSERTED")))
        self.assertEqual(decision.origin_audit.unverified_origin_pair_count, 1)
        self.assertIn("REPORTING_ORIGIN_CLAIMS_UNVERIFIED", decision.warnings)
        self.assertFalse(decision.independent_corroboration_established)

    def test_counts_partition_all_review_pairs(self):
        audit = self.audit(
            self.note(), self.note(pair_index=1, indicator="NO_DEPENDENCY_OBSERVED"),
        )
        summary = self.summarize(audit)
        self.assertEqual(summary.candidate_pair_count, 3)
        self.assertEqual((summary.dependency_indicated_pair_count,
                          summary.unverified_origin_pair_count,
                          summary.unreviewed_pair_count), (1, 1, 1))

    def test_forged_audit_fields_rejected_even_with_original_digest(self):
        audit = self.audit(self.note())
        mutations = (
            {"audit_packet_sha256": "0" * 64},
            {"review_packet_sha256": "0" * 64},
            {"observations_count": 99},
            {"dependency_indicated_pairs": 0},
            {"pairs": ()},
            {"observations": ()},
            {"warnings": ()},
            {"policy_version": "forged-policy"},
            {"independence_status": "ESTABLISHED"},
            {"independently_verified": True},
            {"independent_corroboration_established": True},
            {"pairs": (replace(audit.pairs[0], status="NOT_REVIEWED"), *audit.pairs[1:])},
            {"observations": (replace(audit.observations[0], indicator="DISTINCT_ORIGIN_ASSERTED"),)},
        )
        for changes in mutations:
            with self.subTest(changes=changes), self.assertRaises(CorroborationDecisionError):
                self.decide(replace(audit, **changes))

    def test_boolean_counts_or_non_boolean_flags_rejected(self):
        audit = self.audit(self.note())
        for changes in (
            {"observations_count": True}, {"dependency_indicated_pairs": True},
            {"independently_verified": 0}, {"independent_corroboration_established": 0},
        ):
            with self.subTest(changes=changes), self.assertRaises(ReportingOriginAuditError):
                self.summarize(replace(audit, **changes))

    def test_audit_cannot_be_rebound_to_another_claim(self):
        audit = self.audit()
        changed = replace(self.nli, claim="A different geographical claim.")
        agreement = analyze_external_evidence_agreement(nli_report=changed)
        review = build_external_independence_review(nli_report=changed, agreement_report=agreement)
        with self.assertRaises(CorroborationDecisionError):
            decide_external_corroboration(
                nli_report=changed, agreement_report=agreement,
                independence_review=review, reporting_origin_audit=audit,
            )

    def test_audit_cannot_be_rebound_to_changed_nli_probabilities(self):
        audit = self.audit()
        changed_row = replace(self.rows[0], entailment=.95, contradiction=.03, nli_confidence=.95)
        changed = replace(self.nli, evidence=(changed_row, *self.rows[1:]))
        agreement = analyze_external_evidence_agreement(nli_report=changed)
        review = build_external_independence_review(nli_report=changed, agreement_report=agreement)
        with self.assertRaises(CorroborationDecisionError):
            decide_external_corroboration(
                nli_report=changed, agreement_report=agreement,
                independence_review=review, reporting_origin_audit=audit,
            )

    def test_bound_review_required_when_audit_supplied(self):
        with self.assertRaisesRegex(CorroborationDecisionError, "requires_independence_review"):
            decide_external_corroboration(
                nli_report=self.nli, agreement_report=self.agreement,
                reporting_origin_audit=self.audit(),
            )

    def test_legacy_decision_call_remains_compatible(self):
        decision = decide_external_corroboration(nli_report=self.nli, agreement_report=self.agreement)
        self.assertIsNone(decision.origin_audit)
        self.assertEqual(decision.policy_version, "phase3.2-grounded-conservative-v1")

    def test_public_summary_excludes_private_annotations(self):
        note = self.note()
        summary = self.summarize(self.audit(note))
        output = repr(asdict(summary))
        self.assertNotIn(note.observer_label, output)
        self.assertNotIn(note.reference_url, output)
        self.assertNotIn("observations'", output)
        with self.assertRaises(FrozenInstanceError):
            summary.observations_count = 100


class AuditSnapshotTests(AuditFixture, TestCase):
    def setUp(self):
        self.prepare()

    def test_validated_summary_reaches_external_finding(self):
        audit = self.audit(self.note())
        finding = self.snapshot(audit)
        self.assertEqual(finding.origin_audit, self.summarize(audit))
        self.assertIn("REPORTING_ORIGIN_DEPENDENCY_INDICATED", finding.warnings)
        self.assertFalse(finding.independent_corroboration_established)

    def test_forged_decision_summary_rejected(self):
        audit = self.audit(self.note())
        decision = self.decide(audit)
        for changes in (
            {"dependency_indicated_pair_count": 0},
            {"dependency_indicated_pair_count": True},
            {"audit_packet_sha256": "0" * 64},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.snapshot(audit, decision=replace(
                    decision, origin_audit=replace(decision.origin_audit, **changes),
                ))

    def test_summary_requires_raw_audit_binding(self):
        with self.assertRaisesRegex(ValueError, "binding_missing"):
            _snapshot_external(
                claim=self.nli.claim, at=self.nli.assessed_at, retrieved=self.rows,
                nli=self.nli, agreement=self.agreement, decision=self.decide(self.audit()),
            )

    def test_corrupt_raw_audit_rejected_at_snapshot(self):
        audit = self.audit(self.note())
        with self.assertRaises(ValueError):
            self.snapshot(replace(audit, observations=()), decision=self.decide(audit))

    def test_decision_review_digest_must_match_bound_audit(self):
        audit = self.audit()
        with self.assertRaisesRegex(ValueError, "decision_mismatch"):
            self.snapshot(audit, decision=replace(
                self.decide(audit), origin_review_packet_sha256="0" * 64,
            ))


class AuditOrchestrationTests(AuditFixture, IsolatedAsyncioTestCase):
    def setUp(self):
        self.prepare()

    async def flow(self, *, retrieved=None, agreement_analyzer=None):
        async def retrieve(session, **kwargs):
            return self.rows if retrieved is None else retrieved

        async def nli_runner(session, **kwargs):
            return self.nli

        def wikipedia_runner(claim, top_k):
            return SimpleNamespace(
                claim=claim, verdict="SUPPORTING_EVIDENCE", retrieved_count=2,
                assessed_count=2, supporting_pages=["Paris"], refuting_pages=[],
                corroboration_status="NOT_ESTABLISHED_SINGLE_CORPUS",
            )

        return await orchestrate_unified_verification(
            object(), claim=self.nli.claim, assessed_at=self.nli.assessed_at,
            wikipedia_runner=wikipedia_runner, external_retriever=retrieve,
            external_nli_runner=nli_runner, agreement_analyzer=agreement_analyzer,
        )

    async def test_default_decision_path_runs_review_and_audit(self):
        report = await self.flow()
        self.assertEqual(report.external.status, "AVAILABLE")
        self.assertEqual(report.external.origin_audit.unreviewed_pair_count, 3)
        self.assertIn("REPORTING_ORIGIN_PAIRS_NOT_REVIEWED", report.warnings)
        self.assertEqual(report.relationship, "PROVISIONALLY_ALIGNED_SUPPORT")
        self.assertFalse(report.independently_verified)
        self.assertFalse(report.independent_corroboration_established)

    async def test_valid_dependency_lead_flows_without_private_annotation_leak(self):
        note = self.note()
        with patch(
            "apps.api.services.unified_verification.assess_reporting_origin_dependencies",
            return_value=self.audit(note),
        ):
            report = await self.flow()
        self.assertEqual(report.external.origin_audit.dependency_indicated_pair_count, 1)
        self.assertIn("REPORTING_ORIGIN_DEPENDENCY_INDICATED", report.warnings)
        self.assertNotIn(note.reference_url, repr(asdict(report)))
        self.assertNotIn(note.observer_label, repr(asdict(report)))
        self.assertFalse(report.independently_verified)

    async def test_forged_audit_fails_only_external_leg_closed(self):
        with patch(
            "apps.api.services.unified_verification.assess_reporting_origin_dependencies",
            return_value=replace(self.audit(), independently_verified=True),
        ):
            report = await self.flow()
        self.assertEqual(report.external.status, "UNAVAILABLE")
        self.assertIsNone(report.external.origin_audit)
        self.assertEqual(report.wikipedia.status, "AVAILABLE")
        self.assertEqual(report.relationship, "WIKIPEDIA_ONLY")

    async def test_audit_exception_is_sanitized(self):
        with patch(
            "apps.api.services.unified_verification.assess_reporting_origin_dependencies",
            side_effect=RuntimeError("private reviewer details"),
        ):
            report = await self.flow()
        self.assertEqual(report.external.status, "UNAVAILABLE")
        self.assertNotIn("private reviewer details", repr(report))
        self.assertIn("EXTERNAL_VERIFICATION_UNAVAILABLE", report.warnings)

    async def test_invalid_agreement_cannot_bypass_audit(self):
        report = await self.flow(agreement_analyzer=lambda **kwargs: replace(
            self.agreement, supporting_unit_count=99,
        ))
        self.assertEqual(report.external.status, "UNAVAILABLE")

    async def test_duplicate_sources_create_no_review_pairs(self):
        self.prepare(duplicate=True)
        report = await self.flow()
        self.assertEqual(report.external.status, "AVAILABLE")
        self.assertEqual(report.external.provisional_agreement_units, 1)
        self.assertEqual(report.external.origin_audit.candidate_pair_count, 0)
        self.assertFalse(report.independent_corroboration_established)

    async def test_insufficient_evidence_has_no_audit(self):
        report = await self.flow(retrieved=self.rows[:1])
        self.assertEqual(report.external.status, "INSUFFICIENT_STORED_EVIDENCE")
        self.assertIsNone(report.external.origin_audit)


if __name__ == "__main__":
    import unittest
    unittest.main()
