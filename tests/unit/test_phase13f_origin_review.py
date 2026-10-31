"""Phase 13F: offline tests for review-only independence evidence packets."""

import dataclasses
import unittest

from apps.api.services.external_evidence_agreement import analyze_external_evidence_agreement
from apps.api.services.external_corroboration_decision import (
    CorroborationDecisionError, decide_external_corroboration,
)
from apps.api.services.external_independence_review import (
    ExternalIndependenceReviewError, build_external_independence_review,
)
from test_phase13d6_evidence_agreement import make_passage, make_report


class OriginReviewTests(unittest.TestCase):
    def calculate(self, *rows):
        nli = make_report(*rows)
        agreement = analyze_external_evidence_agreement(nli_report=nli)
        review = build_external_independence_review(
            nli_report=nli, agreement_report=agreement,
        )
        return nli, agreement, review

    def test_two_supporting_sources_produce_review_candidate_but_no_proof(self):
        n, a, r = self.calculate(make_passage(family=1, group=1), make_passage(family=2, group=2))
        self.assertEqual(r.review_status, "ORIGIN_REVIEW_REQUIRED")
        self.assertEqual(len(r.review_candidates), 1)
        self.assertEqual(r.review_candidates[0].stance, "SUPPORT_ONLY")
        self.assertNotEqual(r.review_candidates[0].left_domain, r.review_candidates[0].right_domain)
        self.assertEqual(r.independence_status, "NOT_ESTABLISHED")
        self.assertFalse(r.independent_corroboration_established)
        self.assertFalse(r.independently_verified)
        decision = decide_external_corroboration(nli_report=n, agreement_report=a, independence_review=r)
        self.assertEqual(decision.origin_review_pair_count, 1)
        self.assertEqual(decision.origin_review_packet_sha256, r.review_packet_sha256)
        self.assertIn("ORIGIN_REVIEW_CANDIDATES_REQUIRE_INDEPENDENT_AUDIT", decision.explanation_codes)
        self.assertFalse(decision.independent_corroboration_established)
        self.assertFalse(decision.independently_verified)

    def test_two_refuting_sources_produce_review_pair_not_a_truth_verdict(self):
        _, _, r = self.calculate(make_passage(family=1, group=1, stance="refute"), make_passage(family=2, group=2, stance="refute"))
        self.assertEqual(len(r.review_candidates), 1)
        self.assertEqual(r.review_candidates[0].stance, "REFUTE_ONLY")
        self.assertFalse(r.independently_verified)

    def test_opposing_stances_never_form_agreement_pair(self):
        _, _, r = self.calculate(make_passage(family=1, group=1), make_passage(family=2, group=2, stance="refute"))
        self.assertEqual(r.review_status, "NO_ELIGIBLE_ORIGIN_PAIRS")
        self.assertFalse(r.review_candidates)

    def test_neutral_and_weak_evidence_not_eligible(self):
        _, _, r = self.calculate(make_passage(family=1, group=1, stance="neutral"), make_passage(family=2, group=2, stance="weak_support"))
        self.assertEqual(r.review_candidates, ())

    def test_duplicate_bridge_blocks_candidate(self):
        _, _, r = self.calculate(make_passage(family=1, group=1), make_passage(family=2, group=1))
        self.assertEqual(r.review_candidates, ())

    def test_multiple_passages_from_one_source_not_a_new_source(self):
        a = make_passage(family=1, group=1)
        b = make_passage(family=1, group=2, document_version_id=a.document_version_id,
                         source_id=a.source_id, domain=a.publisher_domain, article_url=a.article_url)
        _, _, r = self.calculate(a, b)
        self.assertEqual(r.review_candidates, ())

    def test_multiple_domains_in_merged_unit_cannot_form_simple_pair(self):
        a, b, c = make_passage(family=1, group=1), make_passage(family=2, group=1), make_passage(family=3, group=2)
        _, _, r = self.calculate(a, b, c)
        self.assertEqual(r.review_candidates, ())

    def test_three_support_sources_produce_three_review_pairs(self):
        _, _, r = self.calculate(make_passage(family=1, group=1), make_passage(family=2, group=2), make_passage(family=3, group=3))
        self.assertEqual(len(r.review_candidates), 3)

    def test_permutation_invariant_packet(self):
        a, b, c = make_passage(family=1, group=1), make_passage(family=2, group=2), make_passage(family=3, group=3)
        first = self.calculate(a, b, c)[-1]
        second = self.calculate(c, a, b)[-1]
        self.assertEqual(first, second)

    def test_forged_agreement_rejected(self):
        n = make_report(make_passage(family=1, group=1), make_passage(family=2, group=2))
        a = analyze_external_evidence_agreement(nli_report=n)
        with self.assertRaisesRegex(ExternalIndependenceReviewError, "agreement_and_nli_reports_mismatch"):
            build_external_independence_review(nli_report=n, agreement_report=dataclasses.replace(a, supporting_unit_count=10))

    def test_forged_nli_hash_rejected(self):
        n = make_report(make_passage(family=1, group=1), make_passage(family=2, group=2))
        a = analyze_external_evidence_agreement(nli_report=n)
        n = dataclasses.replace(n, evidence=(dataclasses.replace(n.evidence[0], passage_sha256="0" * 64), n.evidence[1]))
        with self.assertRaisesRegex(ExternalIndependenceReviewError, "invalid_upstream_evidence"):
            build_external_independence_review(nli_report=n, agreement_report=a)

    def test_forged_origin_review_packet_rejected_by_decision(self):
        n, a, r = self.calculate(make_passage(family=1, group=1), make_passage(family=2, group=2))
        altered = dataclasses.replace(r, independence_status="ESTABLISHED")
        with self.assertRaisesRegex(CorroborationDecisionError, "independence_review_mismatch"):
            decide_external_corroboration(nli_report=n, agreement_report=a, independence_review=altered)

    def test_forged_origin_review_count_rejected_by_decision(self):
        n, a, r = self.calculate(make_passage(family=1, group=1), make_passage(family=2, group=2))
        altered = dataclasses.replace(r, review_candidates=())
        with self.assertRaisesRegex(CorroborationDecisionError, "independence_review_mismatch"):
            decide_external_corroboration(nli_report=n, agreement_report=a, independence_review=altered)

    def test_default_decision_still_conservative_without_review(self):
        n, a, _ = self.calculate(make_passage(family=1, group=1), make_passage(family=2, group=2))
        original = decide_external_corroboration(nli_report=n, agreement_report=a)
        self.assertEqual(original.origin_review_pair_count, 0)
        self.assertIsNone(original.origin_review_packet_sha256)
        self.assertFalse(original.independent_corroboration_established)

    def test_packet_immutable_and_hash_shape(self):
        _, _, r = self.calculate(make_passage(family=1, group=1), make_passage(family=2, group=2))
        self.assertEqual(len(r.review_packet_sha256), 64)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            r.independence_status = "ESTABLISHED"

    def test_packet_contains_exact_evidence_ids_and_hashes(self):
        a, b = make_passage(family=1, group=1), make_passage(family=2, group=2)
        _, _, r = self.calculate(a, b)
        pair = r.review_candidates[0]
        self.assertEqual({pair.left_passage_id, pair.right_passage_id}, {a.passage_id, b.passage_id})
        self.assertEqual({pair.left_passage_sha256, pair.right_passage_sha256}, {a.passage_sha256, b.passage_sha256})

    def test_each_decisive_paragraph_is_available_without_counting_another_source(self):
        a, b = make_passage(family=1, group=1), make_passage(family=2, group=2)
        other = make_passage(family=2, group=3, document_version_id=b.document_version_id,
                             source_id=b.source_id, domain=b.publisher_domain, article_url=b.article_url)
        nli, agreement, review = self.calculate(a, b, other)
        self.assertEqual(agreement.provisional_agreement_unit_count, 2)
        self.assertEqual(len(review.review_candidates), 2)
        self.assertEqual({frozenset((p.left_passage_id, p.right_passage_id))
                          for p in review.review_candidates},
                         {frozenset((a.passage_id, b.passage_id)),
                          frozenset((a.passage_id, other.passage_id))})
        decision = decide_external_corroboration(nli_report=nli, agreement_report=agreement,
                                                independence_review=review)
        self.assertEqual(decision.origin_review_pair_count, 2)
        self.assertFalse(decision.independent_corroboration_established)

    def test_all_cross_unit_pairs_are_stable_under_permutation(self):
        a, b = make_passage(family=1, group=1), make_passage(family=2, group=2)
        c = make_passage(family=1, group=3, document_version_id=a.document_version_id,
                         source_id=a.source_id, domain=a.publisher_domain, article_url=a.article_url)
        d = make_passage(family=2, group=4, document_version_id=b.document_version_id,
                         source_id=b.source_id, domain=b.publisher_domain, article_url=b.article_url)
        review = self.calculate(a, b, c, d)[-1]
        self.assertEqual(len(review.review_candidates), 4)
        self.assertEqual(review, self.calculate(d, c, b, a)[-1])
        for pair in review.review_candidates:
            self.assertNotEqual(pair.left_domain, pair.right_domain)

    def test_additional_neutral_or_weak_paragraphs_do_not_become_pairs(self):
        a, b = make_passage(family=1, group=1), make_passage(family=2, group=2)
        extras = [make_passage(family=2, group=i, stance=stance,
                              document_version_id=b.document_version_id, source_id=b.source_id,
                              domain=b.publisher_domain, article_url=b.article_url)
                  for i, stance in ((3, 'neutral'), (4, 'weak_support'))]
        self.assertEqual(len(self.calculate(a, b, *extras)[-1].review_candidates), 1)

    def test_mixed_unit_still_cannot_supply_an_origin_pair(self):
        a, b = make_passage(family=1, group=1), make_passage(family=2, group=2)
        opposite = make_passage(family=2, group=3, stance='refute',
                                document_version_id=b.document_version_id, source_id=b.source_id,
                                domain=b.publisher_domain, article_url=b.article_url)
        self.assertFalse(self.calculate(a, b, opposite)[-1].review_candidates)

    def test_twenty_evidence_inputs_bound_the_candidate_count(self):
        rows = [make_passage(family=i, group=i) for i in range(1, 21)]
        review = self.calculate(*rows)[-1]
        self.assertEqual(len(review.review_candidates), 190)
        self.assertEqual(len({(p.left_passage_id, p.right_passage_id)
                              for p in review.review_candidates}), 190)


if __name__ == "__main__":
    unittest.main()
