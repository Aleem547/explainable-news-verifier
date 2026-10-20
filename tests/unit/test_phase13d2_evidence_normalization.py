"""Offline Phase 13D.2 normalization/deduplication regression tests."""

import unittest
from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
from uuid import uuid4

from apps.api.services.external_evidence_normalization import (
    EvidenceNormalizationError,
    EvidenceNormalizationPolicy,
    normalize_and_group_external_evidence,
    normalize_evidence_text,
)
from apps.api.services.external_passage_retrieval import ExternalPassageCandidate

BASE = (
    "A national investigation found that the coastal bridge was closed for repairs "
    "after a safety inspection by the local engineering council. The agency said "
    "crews inspected the supports and reviewed maintenance records before reopening "
    "the route for public transport. Local officials confirmed the inspection and "
    "said further assessments would follow in the coming weeks."
)


def hit(text=BASE, *, score=0.7, rank=1, domain="example.org", **changes):
    result = ExternalPassageCandidate(
        rank=rank, passage_id=uuid4(), document_version_id=uuid4(),
        document_id=uuid4(), source_id=uuid4(), publisher_name="Example News",
        publisher_domain=domain, original_url=f"https://{domain}/article",
        retrieved_at=datetime.now(UTC), passage_text=text,
        passage_sha256=sha256(text.encode("utf-8")).hexdigest(),
        lexical_relevance_score=score,
    )
    return replace(result, **changes)


class NormalizationTest(unittest.TestCase):
    def test_normalization_preserves_information_and_removes_hidden_formatting(self):
        text = "  Ｎｅｗｓ \u200bnetwork\t\n   alerts.  "
        self.assertEqual(normalize_evidence_text(text), "News network alerts.")

    def test_rejects_nonstring(self):
        with self.assertRaises(EvidenceNormalizationError):
            normalize_evidence_text(None)

    def test_no_input(self):
        report = normalize_and_group_external_evidence(())
        self.assertEqual(report.groups, ())
        self.assertEqual(report.input_count, 0)

    def test_single_preserves_every_source_field(self):
        value = hit()
        result = normalize_and_group_external_evidence([value])
        item = result.groups[0].members[0]
        self.assertEqual(item.candidate, value)
        self.assertEqual(item.candidate.original_url, value.original_url)
        self.assertEqual(item.candidate.source_id, value.source_id)
        self.assertEqual(result.groups[0].match_types, ("representative",))
        self.assertFalse(result.independent_corroboration_established)
        self.assertFalse(result.groups[0].nli_evaluated)

    def test_exact_identical_across_publishers_are_grouped_but_both_retained(self):
        a, b = hit(domain="a.example"), hit(domain="b.example", rank=2)
        report = normalize_and_group_external_evidence((a, b))
        self.assertEqual(len(report.groups), 1)
        self.assertEqual(report.exact_duplicate_count, 1)
        self.assertEqual(report.groups[0].publisher_domains, ("a.example", "b.example"))
        self.assertEqual(len(report.groups[0].members), 2)
        self.assertFalse(report.groups[0].independently_verified)

    def test_case_whitespace_unicode_normalization_exact(self):
        a = hit("This news article reports confirmed repairs of the public bridge.")
        b = hit("  this  NEWS article reports  confirmed repairs of the public bridge.\n", rank=2)
        report = normalize_and_group_external_evidence((a, b))
        self.assertEqual(len(report.groups), 1)
        self.assertEqual(report.exact_duplicate_count, 1)
        self.assertEqual(report.groups[0].members[0].candidate.passage_text, a.passage_text)

    def test_nonduplicates_remain_separate(self):
        a, b = hit(), hit("A separate report discussed crop irrigation and soil management.")
        report = normalize_and_group_external_evidence((a, b))
        self.assertEqual(len(report.groups), 2)
        self.assertEqual(report.exact_duplicate_count, 0)

    def test_long_near_duplicate_is_provisional_and_keeps_both(self):
        a = hit(BASE, score=0.8)
        b = hit(BASE + " Today.", score=0.7)
        report = normalize_and_group_external_evidence([a, b])
        self.assertEqual(len(report.groups), 1)
        self.assertEqual(report.possible_near_duplicate_count, 1)
        self.assertEqual(report.groups[0].match_types, ("representative", "near"))
        self.assertFalse(report.groups[0].independently_verified)

    def test_exact_duplicate_of_near_member_is_tracked_as_exact(self):
        near_text = BASE + " Today."
        a = hit(BASE, score=0.8)
        b = hit(near_text, score=0.7)
        c = hit(near_text, score=0.6)
        report = normalize_and_group_external_evidence([a, b, c])
        self.assertEqual(len(report.groups), 1)
        self.assertEqual(report.groups[0].match_types, ("representative", "near", "exact"))
        self.assertEqual(report.exact_duplicate_count, 1)
        self.assertEqual(report.possible_near_duplicate_count, 1)
        self.assertEqual(len(report.groups[0].members), 3)

    def test_negation_change_never_merged_near(self):
        a = hit(BASE)
        b = hit(BASE.replace("was closed", "was not closed"))
        report = normalize_and_group_external_evidence([a, b])
        self.assertEqual(len(report.groups), 2)

    def test_numeric_change_never_merged_near(self):
        a = hit(BASE.replace("coastal bridge", "2024 coastal bridge"))
        b = hit(BASE.replace("coastal bridge", "2025 coastal bridge"))
        report = normalize_and_group_external_evidence([a, b])
        self.assertEqual(len(report.groups), 2)

    def test_short_similar_passages_are_not_near_deduplicated(self):
        a = hit("The bridge opened Monday morning.")
        b = hit("The bridge opened Tuesday morning.")
        report = normalize_and_group_external_evidence([a, b])
        self.assertEqual(len(report.groups), 2)

    def test_representative_is_highest_ranked_relevance(self):
        low = hit(score=0.2)
        high = hit(score=0.8, rank=2)
        report = normalize_and_group_external_evidence([low, high])
        self.assertEqual(report.groups[0].representative.candidate.passage_id, high.passage_id)

    def test_same_passage_id_rejected_even_if_text_same(self):
        original = hit()
        duplicate = replace(original, rank=2)
        with self.assertRaisesRegex(EvidenceNormalizationError, "duplicate_passage_id"):
            normalize_and_group_external_evidence([original, duplicate])

    def test_tampered_hash_rejected(self):
        with self.assertRaisesRegex(EvidenceNormalizationError, "invalid_passage_integrity"):
            normalize_and_group_external_evidence([hit(passage_sha256="0" * 64)])

    def test_rejects_assessed_flags(self):
        for setting in ("independently_verified", "nli_evaluated", "independent_corroboration_established"):
            with self.subTest(setting=setting):
                with self.assertRaisesRegex(EvidenceNormalizationError, "already_assessed_candidate"):
                    normalize_and_group_external_evidence([hit(**{setting: True})])

    def test_invalid_relevance_scores_fail_closed(self):
        for val in (0, -1, float("nan"), float("inf")):
            with self.subTest(score=val):
                with self.assertRaisesRegex(EvidenceNormalizationError, "invalid_candidate_provenance"):
                    normalize_and_group_external_evidence([hit(score=val)])

    def test_invalid_timestamps_and_insecure_urls_fail_closed(self):
        with self.assertRaises(EvidenceNormalizationError):
            normalize_and_group_external_evidence([hit(retrieved_at=datetime.now())])
        with self.assertRaises(EvidenceNormalizationError):
            normalize_and_group_external_evidence([hit(original_url="http://localhost/secret")])

    def test_rejects_more_than_limit_and_invalid_policy(self):
        with self.assertRaisesRegex(EvidenceNormalizationError, "candidate_limit_exceeded"):
            normalize_and_group_external_evidence([hit(rank=i+1) for i in range(101)])
        with self.assertRaises(ValueError):
            EvidenceNormalizationPolicy(near_duplicate_jaccard=0.4)

    def test_original_text_not_mutated(self):
        article = "  Something\n else   is here. "
        candidate = hit(article)
        output = normalize_and_group_external_evidence([candidate])
        self.assertEqual(candidate.passage_text, article)
        self.assertEqual(output.groups[0].members[0].normalized_text, "Something else is here.")

    def test_input_data_type_rejected(self):
        with self.assertRaises(EvidenceNormalizationError):
            normalize_and_group_external_evidence("not-a-sequence")
        with self.assertRaises(EvidenceNormalizationError):
            normalize_and_group_external_evidence([object()])


if __name__ == "__main__":
    unittest.main()
