"""Phase 13D.7 -- entirely offline conservative decision tests."""

from __future__ import annotations

import dataclasses
import unittest
from datetime import datetime, UTC
from uuid import uuid4

from apps.api.services.external_evidence_agreement import (
    analyze_external_evidence_agreement,
)
from apps.api.services.external_corroboration_decision import (
    CorroborationDecisionError,
    ExternalCorroborationDecision,
    ExternalEvidenceVerdict,
    decide_external_corroboration,
)
from test_phase13d6_evidence_agreement import make_passage, make_report


class DecisionTests(unittest.TestCase):
    def evaluate(self, *rows, report_changes=None):
        report = make_report(*rows, **(report_changes or {}))
        agreement = analyze_external_evidence_agreement(nli_report=report)
        return decide_external_corroboration(nli_report=report, agreement_report=agreement)

    def test_two_supporting_families_not_proof_of_independence(self):
        result = self.evaluate(make_passage(family=1, group=1), make_passage(family=2, group=2))
        self.assertEqual(result.evidence_verdict, ExternalEvidenceVerdict.PROVISIONAL_SUPPORT)
        self.assertEqual(result.supporting_unit_count, 2)
        self.assertFalse(result.independent_corroboration_established)
        self.assertEqual(result.independence_status, "NOT_ESTABLISHED")

    def test_distinct_publisher_domains_not_proof(self):
        report = self.evaluate(make_passage(family=1, group=1, domain="news-a.org"), make_passage(family=2, group=2, domain="news-b.org"))
        self.assertIn("SOURCE_EDITORIAL_INDEPENDENCE_NOT_PROVEN", report.explanation_codes)

    def test_refuting_only_is_provisional(self):
        report = self.evaluate(make_passage(family=1, group=1, stance="refute"), make_passage(family=2, group=2, stance="refute"))
        self.assertEqual(report.evidence_verdict, ExternalEvidenceVerdict.PROVISIONAL_REFUTATION)
        self.assertFalse(report.independently_verified)

    def test_opposing_families_conflict(self):
        report = self.evaluate(make_passage(family=1, group=1), make_passage(family=2, group=2, stance="refute"))
        self.assertEqual(report.evidence_verdict, ExternalEvidenceVerdict.CONFLICTING_EVIDENCE)
        self.assertEqual((report.supporting_unit_count, report.refuting_unit_count), (1, 1))

    def test_same_family_conflict(self):
        report = self.evaluate(make_passage(family=1, group=1), make_passage(family=1, group=2, stance="refute"))
        self.assertEqual(report.evidence_verdict, ExternalEvidenceVerdict.CONFLICTING_EVIDENCE)
        self.assertIn("WITHIN_RISK_UNIT_NLI_CONFLICT", report.explanation_codes)

    def test_duplicate_bridge_yields_single_provisional_unit(self):
        report = self.evaluate(make_passage(family=1, group=1), make_passage(family=2, group=1))
        self.assertEqual(report.provisional_unit_count, 1)
        self.assertIn("DUPLICATE_EVIDENCE_LINKS_SOURCE_RISK_FAMILIES", report.explanation_codes)
        self.assertIn("SINGLE_DEPENDENCY_RISK_UNIT", report.explanation_codes)
        self.assertFalse(report.independent_corroboration_established)

    def test_weak_and_neutral_is_insufficient(self):
        report = self.evaluate(make_passage(family=1, group=1, stance="weak_support"), make_passage(family=2, group=2, stance="neutral"))
        self.assertEqual(report.evidence_verdict, ExternalEvidenceVerdict.INSUFFICIENT_EVIDENCE)
        self.assertEqual(len(report.inconclusive_passage_ids), 2)

    def test_weak_refute_does_not_veto_support(self):
        report = self.evaluate(make_passage(family=1, group=1), make_passage(family=2, group=2, stance="weak_support"))
        self.assertEqual(report.evidence_verdict, ExternalEvidenceVerdict.PROVISIONAL_SUPPORT)
        self.assertIn("SOME_EVIDENCE_NOT_DECISIVE", report.explanation_codes)

    def test_neutral_does_not_veto_refutation(self):
        report = self.evaluate(make_passage(family=1, group=1, stance="refute"), make_passage(family=2, group=2, stance="neutral"))
        self.assertEqual(report.evidence_verdict, ExternalEvidenceVerdict.PROVISIONAL_REFUTATION)

    def test_passage_ids_partition_and_stable_order(self):
        a, b, c = make_passage(family=1, group=1), make_passage(family=2, group=2, stance="refute"), make_passage(family=3, group=3, stance="neutral")
        d1 = self.evaluate(c, a, b)
        d2 = self.evaluate(b, c, a)
        self.assertEqual(d1, d2)
        self.assertEqual(set(d1.evidence_passage_ids), set(d1.supporting_passage_ids + d1.refuting_passage_ids + d1.inconclusive_passage_ids))

    def test_preserves_all_evidence_ids_for_audit(self):
        a, b = make_passage(family=1, group=1), make_passage(family=2, group=2)
        result = self.evaluate(a, b)
        self.assertEqual(set(result.evidence_passage_ids), {a.passage_id, b.passage_id})

    def test_status_is_never_positive_independence(self):
        for statuses in (("support", "support"), ("refute", "refute"), ("support", "refute"), ("neutral", "neutral")):
            d = self.evaluate(make_passage(family=1, group=1, stance=statuses[0]), make_passage(family=2, group=2, stance=statuses[1]))
            self.assertFalse(d.independent_corroboration_established)
            self.assertFalse(d.independently_verified)
            self.assertEqual(d.independence_status, "NOT_ESTABLISHED")

    def test_report_is_immutable(self):
        d = self.evaluate(make_passage(family=1, group=1), make_passage(family=2, group=2))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            d.independent_corroboration_established = True

    def test_policy_version_and_explanations(self):
        d = self.evaluate(make_passage(family=1, group=1), make_passage(family=2, group=2))
        self.assertEqual(d.policy_version, "phase13d7-conservative-v1")
        self.assertIn("NLI_SCORES_NOT_TRUTH_PROBABILITIES", d.explanation_codes)
        self.assertIn("NO_INDEPENDENT_CORROBORATION_WITHOUT_SEPARATE_AUDITED_PROOF", d.warnings)

    def test_rejects_wrong_nli_type(self):
        with self.assertRaisesRegex(CorroborationDecisionError, "invalid_nli_report"):
            decide_external_corroboration(nli_report={}, agreement_report=object())

    def test_rejects_wrong_agreement_type(self):
        n = make_report(make_passage(family=1, group=1), make_passage(family=2, group=2))
        with self.assertRaisesRegex(CorroborationDecisionError, "invalid_agreement_report"):
            decide_external_corroboration(nli_report=n, agreement_report={})

    def test_rejects_forged_counts(self):
        n = make_report(make_passage(family=1, group=1), make_passage(family=2, group=2))
        a = analyze_external_evidence_agreement(nli_report=n)
        with self.assertRaisesRegex(CorroborationDecisionError, "agreement_and_nli_reports_mismatch"):
            decide_external_corroboration(nli_report=n, agreement_report=dataclasses.replace(a, supporting_unit_count=99))

    def test_rejects_forged_independence_flag(self):
        n = make_report(make_passage(family=1, group=1), make_passage(family=2, group=2))
        a = analyze_external_evidence_agreement(nli_report=n)
        with self.assertRaisesRegex(CorroborationDecisionError, "agreement_and_nli_reports_mismatch"):
            decide_external_corroboration(nli_report=n, agreement_report=dataclasses.replace(a, independent_corroboration_established=True))

    def test_rejects_changed_evidence_row(self):
        n = make_report(make_passage(family=1, group=1), make_passage(family=2, group=2))
        a = analyze_external_evidence_agreement(nli_report=n)
        with self.assertRaisesRegex(CorroborationDecisionError, "agreement_and_nli_reports_mismatch"):
            decide_external_corroboration(nli_report=n, agreement_report=dataclasses.replace(a, evidence=(n.evidence[1], n.evidence[0])))

    def test_rejects_changed_claim(self):
        n = make_report(make_passage(family=1, group=1), make_passage(family=2, group=2))
        a = analyze_external_evidence_agreement(nli_report=n)
        with self.assertRaisesRegex(CorroborationDecisionError, "agreement_and_nli_reports_mismatch"):
            decide_external_corroboration(nli_report=n, agreement_report=dataclasses.replace(a, claim="Completely different claim"))

    def test_rejects_changed_timestamp(self):
        n = make_report(make_passage(family=1, group=1), make_passage(family=2, group=2))
        a = analyze_external_evidence_agreement(nli_report=n)
        with self.assertRaisesRegex(CorroborationDecisionError, "agreement_and_nli_reports_mismatch"):
            decide_external_corroboration(nli_report=n, agreement_report=dataclasses.replace(a, assessed_at=datetime.now(UTC)))

    def test_rejects_changed_warning_set(self):
        n = make_report(make_passage(family=1, group=1), make_passage(family=2, group=2))
        a = analyze_external_evidence_agreement(nli_report=n)
        with self.assertRaisesRegex(CorroborationDecisionError, "agreement_and_nli_reports_mismatch"):
            decide_external_corroboration(nli_report=n, agreement_report=dataclasses.replace(a, warnings=()))

    def test_rejects_tampered_nli_input(self):
        a, b = make_passage(family=1, group=1), make_passage(family=2, group=2)
        n = make_report(a, b)
        agreement = analyze_external_evidence_agreement(nli_report=n)
        altered = dataclasses.replace(n, evidence=(dataclasses.replace(a, passage_sha256="0" * 64), b))
        with self.assertRaisesRegex(CorroborationDecisionError, "invalid_upstream_evidence"):
            decide_external_corroboration(nli_report=altered, agreement_report=agreement)

    def test_rejects_forged_threshold_flag_even_if_other_report_exists(self):
        a, b = make_passage(family=1, group=1), make_passage(family=2, group=2)
        n = make_report(a, b)
        agreement = analyze_external_evidence_agreement(nli_report=n)
        altered_n = dataclasses.replace(n, evidence=(dataclasses.replace(a, nli_threshold_passed=False), b))
        with self.assertRaisesRegex(CorroborationDecisionError, "invalid_upstream_evidence"):
            decide_external_corroboration(nli_report=altered_n, agreement_report=agreement)

    def test_rejects_nli_report_with_claimed_independence(self):
        a, b = make_passage(family=1, group=1), make_passage(family=2, group=2)
        n = make_report(a, b)
        agreement = analyze_external_evidence_agreement(nli_report=n)
        altered = dataclasses.replace(n, independently_verified=True)
        with self.assertRaisesRegex(CorroborationDecisionError, "invalid_upstream_evidence"):
            decide_external_corroboration(nli_report=altered, agreement_report=agreement)


if __name__ == "__main__":
    unittest.main()
