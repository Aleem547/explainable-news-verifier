"""Subject-admission regressions with synthetic scores and real pure services."""

from dataclasses import replace
from hashlib import sha256
import unittest

from apps.api.services.external_evidence_agreement import analyze_external_evidence_agreement
from apps.api.services.external_corroboration_decision import (
    CorroborationDecisionError, decide_external_corroboration,
)
from apps.api.services.external_independence_review import build_external_independence_review
from apps.api.services.external_reporting_origin_audit import assess_reporting_origin_dependencies
from apps.api.services.unified_verification import _snapshot_external
from test_phase13d6_evidence_agreement import make_passage, make_report


class SubjectGroundingTests(unittest.TestCase):
    claim = "NIST has developed a chip-based frequency comb for measuring light."

    def passage(self, family=1, *, text=None, stance="support", **changes):
        text = text or "NIST researchers have developed a frequency comb for measuring light."
        return make_passage(family=family, group=family, stance=stance,
                            passage_text=text, passage_sha256=sha256(text.encode()).hexdigest(), **changes)

    def prepare(self, *rows, claim=None):
        nli = make_report(*rows, claim=claim or self.claim)
        agreement = analyze_external_evidence_agreement(nli_report=nli)
        review = build_external_independence_review(nli_report=nli, agreement_report=agreement)
        audit = assess_reporting_origin_dependencies(nli_report=nli, agreement_report=agreement,
                                                    independence_review=review)
        decision = decide_external_corroboration(nli_report=nli, agreement_report=agreement,
                                                 independence_review=review, reporting_origin_audit=audit)
        return nli, agreement, review, audit, decision

    def pair(self, *, wrong_stance="support", **changes):
        return self.prepare(self.passage(), self.passage(2, text="NASA plans a Moon landing simulation.",
                                                         stance=wrong_stance), **changes)

    def test_high_confidence_wrong_subject_support_is_inconclusive(self):
        nli, agreement, _, _, decision = self.pair()
        wrong = nli.evidence[1]
        self.assertTrue(wrong.nli_threshold_passed)
        self.assertEqual(agreement.decisive_passages, 1)
        self.assertEqual(decision.supporting_passage_ids, (nli.evidence[0].passage_id,))
        self.assertIn(wrong.passage_id, decision.inconclusive_passage_ids)
        self.assertEqual(decision.subject_excluded_decisive_passage_ids, (wrong.passage_id,))

    def test_wrong_subject_contradiction_cannot_create_conflict(self):
        _, agreement, _, _, decision = self.pair(wrong_stance="refute")
        self.assertEqual(str(decision.evidence_verdict), "PROVISIONAL_SUPPORT")
        self.assertFalse(agreement.has_opposing_evidence)
        self.assertEqual(decision.refuting_passage_ids, ())

    def test_all_wrong_subjects_abstain(self):
        _, agreement, review, _, decision = self.prepare(
            self.passage(text="NASA launched a rocket."),
            self.passage(2, text="ESA observed an asteroid.", stance="refute"))
        self.assertEqual(str(decision.evidence_verdict), "INSUFFICIENT_EVIDENCE")
        self.assertEqual(agreement.decisive_passages, 0)
        self.assertEqual(len(review.review_candidates), 0)

    def test_unknown_named_subject_abstains(self):
        _, agreement, _, _, decision = self.pair(claim="NIST developed a frequency comb for measuring light.")
        self.assertEqual(agreement.decisive_passages, 0)
        self.assertEqual(str(decision.evidence_verdict), "INSUFFICIENT_EVIDENCE")

    def test_generic_subject_abstains(self):
        _, agreement, _, _, _ = self.pair(claim="A chip has measured light.")
        self.assertEqual(agreement.decisive_passages, 0)

    def test_grounded_support_survives(self):
        nli, _, _, _, decision = self.pair()
        self.assertIn(nli.evidence[0].passage_id, decision.supporting_passage_ids)

    def test_grounded_refutation_survives(self):
        nli, _, _, _, decision = self.prepare(self.passage(stance="refute"), self.passage(2, stance="neutral"))
        self.assertEqual(str(decision.evidence_verdict), "PROVISIONAL_REFUTATION")
        self.assertIn(nli.evidence[0].passage_id, decision.refuting_passage_ids)

    def test_negation_keeps_the_subject_anchor(self):
        _, agreement, _, _, _ = self.prepare(self.passage(stance="refute"), self.passage(2, stance="neutral"),
                                           claim="NIST has not developed a frequency comb.")
        self.assertEqual(agreement.refuting_unit_count, 1)

    def test_case_normalization_accepts_exact_subject(self):
        _, agreement, _, _, _ = self.prepare(self.passage(text="nist has a frequency comb."), self.passage(2))
        self.assertEqual(agreement.supporting_unit_count, 2)

    def test_word_fragment_is_not_a_subject_match(self):
        _, agreement, _, _, _ = self.prepare(self.passage(text="NISTerious fictional company has a chip."),
                                           self.passage(2, stance="neutral"))
        self.assertEqual(agreement.decisive_passages, 0)

    def test_neutral_missing_subject_is_not_a_rejected_decisive_vote(self):
        _, agreement, _, _, _ = self.pair(wrong_stance="neutral")
        self.assertEqual(agreement.subject_excluded_decisive_passage_ids, ())

    def test_low_confidence_missing_subject_is_not_a_decisive_rejection(self):
        _, agreement, _, _, _ = self.pair(wrong_stance="weak_support")
        self.assertEqual(agreement.subject_excluded_decisive_passage_ids, ())

    def test_raw_scores_and_input_objects_remain_unchanged(self):
        nli, agreement, _, _, _ = self.pair(wrong_stance="refute")
        self.assertIs(agreement.evidence, nli.evidence)
        self.assertEqual(nli.evidence[1].contradiction, .96)
        self.assertTrue(nli.evidence[1].nli_threshold_passed)

    def test_subject_rejections_cannot_be_forged_away(self):
        nli, agreement, _, _, _ = self.pair()
        with self.assertRaises(CorroborationDecisionError):
            decide_external_corroboration(nli_report=nli, agreement_report=replace(
                agreement, subject_excluded_decisive_passage_ids=()))

    def test_guard_policy_cannot_be_forged(self):
        nli, agreement, _, _, _ = self.pair()
        with self.assertRaises(CorroborationDecisionError):
            decide_external_corroboration(nli_report=nli, agreement_report=replace(
                agreement, decisive_admissibility_policy_version="forged"))

    def test_decision_ids_partition_all_original_evidence(self):
        nli, _, _, _, decision = self.pair(wrong_stance="refute")
        all_ids = decision.supporting_passage_ids + decision.refuting_passage_ids + decision.inconclusive_passage_ids
        self.assertEqual(len(all_ids), len(set(all_ids)))
        self.assertEqual(set(all_ids), {r.passage_id for r in nli.evidence})

    def test_wrong_subject_does_not_enter_an_origin_pair(self):
        _, _, review, _, decision = self.prepare(self.passage(), self.passage(2),
                                                self.passage(3, text="NASA has a rocket."))
        self.assertEqual(len(review.review_candidates), 1)
        self.assertEqual(decision.origin_audit.unreviewed_pair_count, 1)

    def test_no_independence_promotion(self):
        _, _, _, _, decision = self.pair()
        self.assertFalse(decision.independent_corroboration_established)
        self.assertFalse(decision.independently_verified)
        self.assertEqual(decision.independence_status, "NOT_ESTABLISHED")

    def test_unified_snapshot_exposes_raw_and_admitted_separately(self):
        nli, agreement, review, audit, decision = self.pair()
        finding = _snapshot_external(claim=nli.claim, at=nli.assessed_at, retrieved=nli.evidence,
                                     nli=nli, agreement=agreement, decision=decision,
                                     independence_review=review, reporting_origin_audit=audit)
        by_id = {r.passage_id: r for r in finding.provenance}
        wrong = by_id[nli.evidence[1].passage_id]
        self.assertTrue(wrong.nli_threshold_passed)
        self.assertFalse(wrong.decisive_evidence_admitted)
        self.assertTrue(by_id[nli.evidence[0].passage_id].decisive_evidence_admitted)

    def test_unified_snapshot_rejects_forged_vote_ids(self):
        nli, agreement, review, audit, decision = self.pair()
        forged = replace(decision, supporting_passage_ids=decision.evidence_passage_ids)
        with self.assertRaisesRegex(ValueError, "decision_replay_mismatch"):
            _snapshot_external(claim=nli.claim, at=nli.assessed_at, retrieved=nli.evidence,
                               nli=nli, agreement=agreement, decision=forged,
                               independence_review=review, reporting_origin_audit=audit)

    def test_shared_risk_unit_uses_only_admitted_stances(self):
        grounded = self.passage()
        wrong = self.passage(text="NASA has a rocket.", stance="refute",
                             source_id=grounded.source_id, publisher_domain=grounded.publisher_domain)
        nli = make_report(grounded, wrong, claim=self.claim)
        agreement = analyze_external_evidence_agreement(nli_report=nli)
        self.assertEqual(agreement.mixed_unit_count, 0)
        self.assertEqual(agreement.supporting_unit_count, 1)

    def test_duplicate_bridge_remains_conservative(self):
        first = self.passage()
        second = replace(self.passage(2), duplicate_group=1)
        _, agreement, _, _, decision = self.prepare(first, second)
        self.assertEqual(agreement.provisional_agreement_unit_count, 1)
        self.assertFalse(decision.independent_corroboration_established)


class LandingSubjectGroundingTests(unittest.TestCase):
    """Pure identity checks, independent of NLI scores or publisher approval."""
    def test_landing_and_negation_keep_the_exact_mission_designator(self):
        from ml.verification.decisive_admissibility import named_subject_anchor
        from ml.verification.external_admissibility import external_subject_grounded
        for claim in ('Chandrayaan-3 landed on the Moon.',
                      'Chandrayaan-3 did not land on the Moon.',
                      'Chandrayaan-3 did land on the Moon.'):
            with self.subTest(claim=claim):
                self.assertEqual(named_subject_anchor(claim,allow_landing_event=True),'chandrayaan 3')
                self.assertTrue(external_subject_grounded(claim,'An orbital camera imaged Chandrayaan-3 on the Moon.'))

    def test_sibling_missions_and_word_fragments_remain_excluded(self):
        from ml.verification.external_admissibility import external_subject_grounded
        claim='Chandrayaan-3 landed on the Moon.'
        for text in ('Chandrayaan-2 landed on the Moon.','Chandrayaan-30 was on the Moon.',
                     'Chandrayaan-3B was imaged.','A reference to Chandrayaan is available.',
                     'Mount Etna is in Sicily.'):
            with self.subTest(text=text):self.assertFalse(external_subject_grounded(claim,text))

    def test_legacy_wikipedia_subject_policy_keeps_its_default(self):
        from ml.verification.decisive_admissibility import named_subject_anchor,check_decisive_admissibility
        claim='Chandrayaan-3 landed on the Moon.'
        self.assertIsNone(named_subject_anchor(claim))
        self.assertIsNone(check_decisive_admissibility(claim,'Other page','Other text','ENTAILMENT').named_subject)

    def test_generic_ambiguous_or_number_losing_subjects_abstain(self):
        from ml.verification.external_admissibility import external_subject_grounded
        for claim in ('A mission landed on the Moon.','The mission landed on the Moon.',
                      'It landed on the Moon.','Apollo 11 landed on the Moon.',
                      'Chandrayaan - 3 landed on the Moon.'):
            with self.subTest(claim=claim):self.assertFalse(external_subject_grounded(claim,claim))

    def test_landing_named_subject_match_is_case_normalized_but_not_truth(self):
        from ml.verification.external_admissibility import external_subject_grounded
        claim='Chandrayaan-3 landed on the Moon.'
        # Matching the subject does not decide whether the predicate is true.
        self.assertTrue(external_subject_grounded(claim,'chandrayaan-3 did not land on the moon.'))
        self.assertFalse(external_subject_grounded('Chandrayaan-3 landing site on the Moon.',claim))

    def test_event_before_later_copula_still_extracts_only_the_named_subject(self):
        from ml.verification.decisive_admissibility import named_subject_anchor
        self.assertEqual(named_subject_anchor('Chandrayaan-3 landed where the terrain is flat.',
                                              allow_landing_event=True),'chandrayaan 3')
