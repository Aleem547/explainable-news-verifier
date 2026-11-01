"""Scope rules and the real pure agreement/decision/review boundary."""

from dataclasses import replace
from hashlib import sha256
import unittest

from ml.verification.evidence_scope import assess_evidence_scope
from apps.api.services.external_evidence_agreement import analyze_external_evidence_agreement
from apps.api.services.external_corroboration_decision import CorroborationDecisionError, decide_external_corroboration
from apps.api.services.external_independence_review import build_external_independence_review
from apps.api.services.external_reporting_origin_audit import assess_reporting_origin_dependencies
from apps.api.services.unified_verification import _snapshot_external
from test_phase13d6_evidence_agreement import make_passage, make_report

ATTRIBUTION = "NON_FACTIVE_ATTRIBUTION_REQUIRES_SCOPE_REVIEW"
TIME = "RECURRING_STATE_WEEKDAY_SCOPE_MISMATCH"
STAGE = "EARLIER_EVENT_STAGE_DOES_NOT_ESTABLISH_OUTCOME"


class ScopeRuleTests(unittest.TestCase):
    def assertBlocked(self, claim, text, reason):
        result = assess_evidence_scope(claim, text)
        self.assertFalse(result.permitted)
        self.assertIn(reason, result.reason_codes)

    def test_allegation_does_not_establish_underlying_event(self):
        self.assertBlocked("Quinn Harper has resigned.", "A visitor alleged that Quinn Harper resigned.", ATTRIBUTION)

    def test_claimed_that_and_reportedly_variants_require_review(self):
        for text in ("A blog claims that Delta Club has closed.",
                     "Delta Club reportedly closed.", "It is rumoured that Delta Club closed."):
            with self.subTest(text=text):
                self.assertBlocked("Delta Club has closed.", text, ATTRIBUTION)

    def test_unconfirmed_and_speculation_require_review(self):
        for text in ("An unconfirmed story describes Orion City's election.",
                     "Observers speculated that Orion City would close its station."):
            with self.subTest(text=text):
                self.assertBlocked("Orion City has closed its station.", text, ATTRIBUTION)

    def test_normal_assertion_is_preserved(self):
        self.assertTrue(assess_evidence_scope("Delta Club has closed.", "Delta Club has closed.").permitted)

    def test_factive_record_wording_is_not_a_nonfactive_keyword(self):
        result = assess_evidence_scope("Delta Board has approved the plan.",
                                       "The minutes confirm that Delta Board approved the plan.")
        self.assertTrue(result.permitted)

    def test_accusation_background_does_not_remove_explicit_acquittal(self):
        result = assess_evidence_scope(
            "Avery Quinn was acquitted in the trial.",
            "Avery Quinn was acquitted in the trial. Avery Quinn had been accused of misconduct.")
        self.assertTrue(result.permitted)

    def test_mixed_allegation_and_confirmation_is_conservatively_deferred(self):
        self.assertBlocked("Delta Club has closed.",
                           "A blog alleged that Delta Club closed. Its records confirm the closure.", ATTRIBUTION)

    def test_claim_about_allegation_also_requires_scope_review(self):
        self.assertBlocked("Delta Club has received an allegation.",
                           "A person alleged that Delta Club misused funds.", ATTRIBUTION)

    def test_weekday_change_is_not_a_refutation_of_recurring_state(self):
        self.assertBlocked("Glenhaven Pool was open on Saturday.",
                           "Glenhaven Pool was open on Friday.", TIME)

    def test_same_weekday_open_closed_contradiction_survives(self):
        self.assertTrue(assess_evidence_scope(
            "Glenhaven Pool was open on Saturday.", "Glenhaven Pool was closed on Saturday.").permitted)

    def test_same_weekday_support_survives(self):
        self.assertTrue(assess_evidence_scope(
            "Meadow Office was available on Tuesday.", "Meadow Office was available on Tuesday.").permitted)

    def test_weekday_spelling_case_and_whitespace_variants(self):
        self.assertBlocked("Meadow Office was OPEN on TUESDAY.",
                           "Meadow Office was open on\nWednesday.", TIME)

    def test_intersecting_weekday_range_is_not_automatically_excluded(self):
        self.assertTrue(assess_evidence_scope(
            "Meadow Office was open on Saturday.",
            "Meadow Office was open from Friday through Saturday.").permitted)

    def test_no_explicit_weekday_cannot_be_inferred(self):
        self.assertTrue(assess_evidence_scope(
            "Meadow Office was open on Saturday.", "Meadow Office was open yesterday.").permitted)

    def test_unique_event_date_difference_remains_eligible_for_nli_refutation(self):
        self.assertTrue(assess_evidence_scope(
            "Delta Library is scheduled to reopen on 14 May.",
            "Delta Library is scheduled to reopen only on 16 May.").permitted)

    def test_unique_event_weekday_difference_is_not_recurring_state_rule(self):
        self.assertTrue(assess_evidence_scope(
            "Delta Festival was held on Saturday.", "Delta Festival was held on Friday.").permitted)

    def test_application_submission_is_not_acceptance(self):
        self.assertBlocked("Linden University has accepted Dana Reed's application.",
                           "Dana Reed submitted an application to Linden University.", STAGE)

    def test_application_submission_is_not_rejection_either(self):
        self.assertBlocked("Linden University has rejected Dana Reed's application.",
                           "Dana Reed submitted an application to Linden University.", STAGE)

    def test_explicit_acceptance_after_submission_survives(self):
        self.assertTrue(assess_evidence_scope(
            "Linden University has accepted Dana Reed's application.",
            "Dana Reed submitted the application, and Linden University accepted it.").permitted)

    def test_explicit_rejection_is_not_suppressed_for_opposite_outcome(self):
        self.assertTrue(assess_evidence_scope(
            "Linden University has accepted Dana Reed's application.",
            "Dana Reed submitted the application, but Linden University rejected it.").permitted)

    def test_nonacceptance_after_submission_is_available_for_nli(self):
        for outcome in ("did not accept it", "did not admit Dana Reed", "denied it"):
            with self.subTest(outcome=outcome):
                self.assertTrue(assess_evidence_scope(
                    "Linden University has accepted Dana Reed's application.",
                    "Dana Reed submitted an application. Linden University " + outcome + ".").permitted)

    def test_proposal_discussion_is_not_approval(self):
        self.assertBlocked("Harbor Council has approved the marina plan.",
                           "Harbor Council discussed the marina plan.", STAGE)

    def test_proposal_rejection_after_discussion_remains_eligible(self):
        self.assertTrue(assess_evidence_scope(
            "Harbor Council has approved the marina plan.",
            "Harbor Council discussed and rejected the marina plan.").permitted)

    def test_trial_attendance_does_not_establish_conviction(self):
        self.assertBlocked("Avery Quinn was convicted in the trial.",
                           "Avery Quinn attended the trial with counsel.", STAGE)

    def test_conviction_and_acquittal_remain_terminal_opposites(self):
        for claim, text in (
            ("Avery Quinn was convicted in the trial.", "Avery Quinn attended the trial and was acquitted."),
            ("Avery Quinn was acquitted in the trial.", "Avery Quinn was convicted of the sole charge."),
            ("Avery Quinn was acquitted in the trial.", "Avery Quinn attended the trial. The court did not acquit Avery Quinn."),
        ):
            with self.subTest(claim=claim):
                self.assertTrue(assess_evidence_scope(claim, text).permitted)

    def test_nist_development_statement_is_not_changed(self):
        self.assertTrue(assess_evidence_scope(
            "NIST has developed a frequency comb.", "NIST researchers have developed a frequency comb.").permitted)

    def test_multiple_reasons_are_stable_and_deduplicated(self):
        result = assess_evidence_scope("Meadow Office was open on Saturday.",
                                      "A source alleged that Meadow Office was open on Friday.")
        self.assertEqual(result.reason_codes, tuple(sorted({ATTRIBUTION, TIME})))

    def test_immutable_decision_has_no_factual_or_independence_flags(self):
        result = assess_evidence_scope("Delta Club has closed.", "Delta Club closed.")
        self.assertFalse(hasattr(result, "independently_verified"))
        with self.assertRaises(AttributeError):
            result.permitted = False

    def test_invalid_or_unbounded_inputs_fail_closed(self):
        for claim, text in ((None, "text"), ("x", "text"), ("Claim has facts.", ""),
                            ("c"*2001, "text"), ("Claim has facts.", "x"*20001)):
            with self.subTest(claim=str(claim)[:10]), self.assertRaises(ValueError):
                assess_evidence_scope(claim, text)

    def test_scope_guard_does_not_create_a_subject_match_or_relation(self):
        result = assess_evidence_scope("Riverton Museum is in Oakport.",
                                      "Oakport Gallery is in Riverton.")
        self.assertTrue(result.permitted)
        self.assertEqual(result.reason_codes, ())
        # Permitted here means no lexical scope flag, not admissible evidence.


class ScopeIntegrationTests(unittest.TestCase):
    claim = "Quinn Harper has resigned from Northstar Club."
    valid = "Quinn Harper has resigned from Northstar Club."
    alleged = "A visitor alleged that Quinn Harper had resigned from Northstar Club."

    def row(self, family=1, text=None, stance="support", **kwargs):
        text = text or self.valid
        return make_passage(family=family, group=family, stance=stance, passage_text=text,
                            passage_sha256=sha256(text.encode()).hexdigest(), **kwargs)

    def prepare(self, *rows):
        nli = make_report(*rows, claim=self.claim)
        agreement = analyze_external_evidence_agreement(nli_report=nli)
        review = build_external_independence_review(nli_report=nli, agreement_report=agreement)
        audit = assess_reporting_origin_dependencies(
            nli_report=nli, agreement_report=agreement, independence_review=review)
        decision = decide_external_corroboration(
            nli_report=nli, agreement_report=agreement, independence_review=review,
            reporting_origin_audit=audit)
        return nli, agreement, review, audit, decision

    def test_raw_high_score_preserved_but_vote_excluded(self):
        nli, agreement, _, _, decision = self.prepare(self.row(), self.row(2, text=self.alleged))
        bad = nli.evidence[1]
        self.assertTrue(bad.nli_threshold_passed)
        self.assertEqual(bad.entailment, .96)
        self.assertIs(agreement.evidence, nli.evidence)
        self.assertEqual(agreement.subject_excluded_decisive_passage_ids, ())
        self.assertEqual(decision.scope_excluded_decisive_passages, ((bad.passage_id, (ATTRIBUTION,)),))
        self.assertIn(bad.passage_id, decision.inconclusive_passage_ids)
        self.assertNotIn(bad.passage_id, decision.supporting_passage_ids)

    def test_qualified_refutation_cannot_create_conflict(self):
        _, agreement, _, _, decision = self.prepare(self.row(), self.row(2, text=self.alleged, stance="refute"))
        self.assertFalse(agreement.has_opposing_evidence)
        self.assertEqual(str(decision.evidence_verdict), "PROVISIONAL_SUPPORT")

    def test_all_qualified_rows_produce_insufficient_evidence(self):
        _, agreement, review, _, decision = self.prepare(
            self.row(text=self.alleged), self.row(2, text=self.alleged))
        self.assertEqual(agreement.decisive_passages, 0)
        self.assertEqual(str(decision.evidence_verdict), "INSUFFICIENT_EVIDENCE")
        self.assertEqual(review.review_candidates, ())

    def test_scope_rejected_source_cannot_enter_origin_pair(self):
        _, _, review, _, decision = self.prepare(self.row(), self.row(2, text=self.alleged))
        self.assertEqual(review.review_candidates, ())
        self.assertEqual(decision.origin_audit.candidate_pair_count, 0)

    def test_valid_source_pair_is_preserved(self):
        _, agreement, review, _, decision = self.prepare(self.row(), self.row(2))
        self.assertEqual(agreement.decisive_passages, 2)
        self.assertEqual(len(review.review_candidates), 1)
        self.assertFalse(decision.independent_corroboration_established)

    def test_subject_rejection_is_not_mislabelled_as_scope_rejection(self):
        nli, agreement, _, _, decision = self.prepare(
            self.row(), self.row(2, text="A visitor alleged that Another Person resigned."))
        self.assertEqual(agreement.subject_excluded_decisive_passage_ids, (nli.evidence[1].passage_id,))
        self.assertEqual(decision.scope_excluded_decisive_passages, ())

    def test_neutral_and_subthreshold_rows_are_not_newly_rejected_votes(self):
        for stance in ("neutral", "weak_support"):
            with self.subTest(stance=stance):
                _, agreement, _, _, _ = self.prepare(self.row(), self.row(2, text=self.alleged, stance=stance))
                self.assertEqual(agreement.scope_excluded_decisive_passages, ())

    def test_scope_reasons_cannot_be_forged_away(self):
        nli, agreement, _, _, _ = self.prepare(self.row(), self.row(2, text=self.alleged))
        with self.assertRaises(CorroborationDecisionError):
            decide_external_corroboration(nli_report=nli, agreement_report=replace(
                agreement, scope_excluded_decisive_passages=()))

    def test_scope_reason_codes_cannot_be_forged(self):
        nli, agreement, _, _, _ = self.prepare(self.row(), self.row(2, text=self.alleged))
        changed = tuple((pid, ("forged",)) for pid, _ in agreement.scope_excluded_decisive_passages)
        with self.assertRaises(CorroborationDecisionError):
            decide_external_corroboration(nli_report=nli, agreement_report=replace(
                agreement, scope_excluded_decisive_passages=changed))

    def test_unified_report_exposes_raw_score_admission_and_reason(self):
        nli, agreement, review, audit, decision = self.prepare(self.row(), self.row(2, text=self.alleged))
        finding = _snapshot_external(
            claim=nli.claim, at=nli.assessed_at, retrieved=nli.evidence,
            nli=nli, agreement=agreement, decision=decision,
            independence_review=review, reporting_origin_audit=audit)
        by_id = {row.passage_id: row for row in finding.provenance}
        bad = by_id[nli.evidence[1].passage_id]
        self.assertTrue(bad.nli_threshold_passed)
        self.assertFalse(bad.decisive_evidence_admitted)
        self.assertEqual(bad.scope_exclusion_codes, (ATTRIBUTION,))
        self.assertEqual(finding.scope_excluded_decisive_passages, decision.scope_excluded_decisive_passages)

    def test_unified_replay_rejects_forged_scope_metadata(self):
        nli, agreement, review, audit, decision = self.prepare(self.row(), self.row(2, text=self.alleged))
        with self.assertRaisesRegex(ValueError, "decision_replay_mismatch"):
            _snapshot_external(
                claim=nli.claim, at=nli.assessed_at, retrieved=nli.evidence,
                nli=nli, agreement=agreement, decision=replace(decision, scope_excluded_decisive_passages=()),
                independence_review=review, reporting_origin_audit=audit)

    def test_origin_review_replay_rejects_forged_agreement_scope_metadata(self):
        nli, agreement, _, _, _ = self.prepare(self.row(), self.row(2, text=self.alleged))
        with self.assertRaises(ValueError):
            build_external_independence_review(
                nli_report=nli, agreement_report=replace(agreement, scope_excluded_decisive_passages=()))

    def test_score_threshold_hashes_and_ids_are_not_rewritten(self):
        nli, agreement, _, _, decision = self.prepare(self.row(), self.row(2, text=self.alleged))
        self.assertEqual(agreement.nli_threshold, nli.nli_threshold)
        self.assertEqual(set(decision.evidence_passage_ids), {r.passage_id for r in nli.evidence})
        self.assertEqual(agreement.evidence, nli.evidence)
        self.assertFalse(decision.independently_verified)


if __name__ == "__main__":
    unittest.main()
