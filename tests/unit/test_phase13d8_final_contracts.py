"""Phase 13D.8: cross-stage contract invariants using synthetic NLI evidence.

Pure offline tests. This is NOT a measured accuracy evaluation, real-world
publisher independence proof, or production API test.
"""

from __future__ import annotations

from dataclasses import replace
import unittest

from apps.api.services.external_evidence_agreement import analyze_external_evidence_agreement
from apps.api.services.external_corroboration_decision import (
    CorroborationDecisionError,
    ExternalEvidenceVerdict,
    decide_external_corroboration,
)
from test_phase13d6_evidence_agreement import make_passage, make_report


class FinalContracts(unittest.TestCase):
    def run_decision(self, *evidence):
        nli = make_report(*evidence)
        agreement = analyze_external_evidence_agreement(nli_report=nli)
        return decide_external_corroboration(nli_report=nli, agreement_report=agreement)

    def assert_safe(self, result):
        self.assertFalse(result.independent_corroboration_established)
        self.assertFalse(result.independently_verified)
        self.assertEqual(result.independence_status, "NOT_ESTABLISHED")
        self.assertIn("SOURCE_EDITORIAL_INDEPENDENCE_NOT_PROVEN", result.explanation_codes)
        self.assertEqual(
            set(result.evidence_passage_ids),
            set(result.supporting_passage_ids + result.refuting_passage_ids + result.inconclusive_passage_ids),
        )

    def test_support_from_two_domains_is_only_provisional(self):
        d = self.run_decision(make_passage(family=1, group=1), make_passage(family=2, group=2))
        self.assertEqual(d.evidence_verdict, ExternalEvidenceVerdict.PROVISIONAL_SUPPORT)
        self.assertEqual(d.supporting_unit_count, 2)
        self.assert_safe(d)

    def test_refuting_evidence_remains_provisional(self):
        d = self.run_decision(make_passage(family=1, group=1, stance="refute"), make_passage(family=2, group=2, stance="refute"))
        self.assertEqual(d.evidence_verdict, ExternalEvidenceVerdict.PROVISIONAL_REFUTATION)
        self.assert_safe(d)

    def test_opposing_external_stances_remain_conflicting(self):
        d = self.run_decision(make_passage(family=1, group=1), make_passage(family=2, group=2, stance="refute"))
        self.assertEqual(d.evidence_verdict, ExternalEvidenceVerdict.CONFLICTING_EVIDENCE)
        self.assert_safe(d)

    def test_weak_and_neutral_stances_are_insufficient(self):
        d = self.run_decision(make_passage(family=1, group=1, stance="weak_support"), make_passage(family=2, group=2, stance="neutral"))
        self.assertEqual(d.evidence_verdict, ExternalEvidenceVerdict.INSUFFICIENT_EVIDENCE)
        self.assertEqual(len(d.inconclusive_passage_ids), 2)
        self.assert_safe(d)

    def test_duplicates_do_not_inflate_agreement_units(self):
        d = self.run_decision(make_passage(family=1, group=1), make_passage(family=2, group=1), make_passage(family=3, group=1))
        self.assertEqual(d.provisional_unit_count, 1)
        self.assertEqual(d.supporting_unit_count, 1)
        self.assertEqual(d.source_risk_family_count, 3)
        self.assert_safe(d)

    def test_conflicting_duplicate_groups_fail_to_form_agreement(self):
        d = self.run_decision(make_passage(family=1, group=1), make_passage(family=2, group=1, stance="refute"))
        self.assertEqual(d.evidence_verdict, ExternalEvidenceVerdict.CONFLICTING_EVIDENCE)
        self.assertEqual(d.mixed_unit_count, 1)
        self.assert_safe(d)

    def test_neutral_source_does_not_overrule_decisive_refutation(self):
        d = self.run_decision(make_passage(family=1, group=1, stance="refute"), make_passage(family=2, group=2, stance="neutral"))
        self.assertEqual(d.evidence_verdict, ExternalEvidenceVerdict.PROVISIONAL_REFUTATION)
        self.assert_safe(d)

    def test_report_order_does_not_change_result(self):
        a = make_passage(family=1, group=1)
        b = make_passage(family=2, group=2, stance="refute")
        c = make_passage(family=3, group=3, stance="neutral")
        self.assertEqual(self.run_decision(a, b, c), self.run_decision(c, a, b))

    def test_forged_agreement_count_fails_closed(self):
        report = make_report(make_passage(family=1, group=1), make_passage(family=2, group=2))
        agreement = analyze_external_evidence_agreement(nli_report=report)
        with self.assertRaisesRegex(CorroborationDecisionError, "mismatch"):
            decide_external_corroboration(nli_report=report, agreement_report=replace(agreement, supporting_unit_count=20))

    def test_changed_passage_hash_fails_closed(self):
        a = make_passage(family=1, group=1)
        b = make_passage(family=2, group=2)
        original = make_report(a, b)
        agreement = analyze_external_evidence_agreement(nli_report=original)
        forged = replace(original, evidence=(replace(a, passage_sha256="0" * 64), b))
        with self.assertRaises(CorroborationDecisionError):
            decide_external_corroboration(nli_report=forged, agreement_report=agreement)


if __name__ == "__main__":
    unittest.main()
