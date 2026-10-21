"""Phase 13E.4 offline, no-network claim-candidate and provenance tests."""

import dataclasses
import hashlib
import unittest
from datetime import UTC, datetime

from apps.api.services.article_extraction import ExtractedArticle
from apps.api.services.article_url_preparation import PreparedArticleUrl
from apps.api.services.article_claim_candidates import (
    POLICY_VERSION,
    ClaimCandidateExtractionError,
    ClaimCandidatePolicy,
    extract_article_claim_candidates,
)
from apps.api.services.pasted_article_preparation import prepare_pasted_article

ONE = "The Eiffel Tower is located in Paris."
TWO = "NASA launched the Artemis program in 2017."
THREE = "Officials recorded 27 new bridges in Kerala."
FOUR = "The ministry announced that 15 new stations opened in Berlin."
GOOD = f"{ONE} {TWO} {THREE} {FOUR}"


def pasted(text=GOOD):
    return prepare_pasted_article(pasted_text=text)


def fetched(text=GOOD):
    sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    article = ExtractedArticle(
        document_url="https://example.org/news/123",
        publisher_domain="example.org",
        publisher_name="Example News",
        text=text,
        text_sha256=sha,
        html_sha256="a" * 64,
        title="Published article",
        author=None,
        reported_publication_date=None,
        retrieved_at=datetime.now(UTC),
    )
    return PreparedArticleUrl(
        canonical_url=article.document_url,
        publisher_domain=article.publisher_domain,
        publisher_name=article.publisher_name,
        article=article,
    )


class ClaimCandidateTests(unittest.TestCase):
    def run_article(self, text=GOOD, **kw):
        return extract_article_claim_candidates(prepared=pasted(text), **kw)

    def test_report_origin_never_independent(self):
        report = self.run_article()
        self.assertEqual(report.source_kind, "USER_SUPPLIED_ONLY")
        self.assertFalse(report.independently_verified)
        self.assertFalse(report.independent_corroboration_established)
        self.assertFalse(report.eligible_as_independent_evidence)
        self.assertIsNone(report.source_url)
        self.assertIsNone(report.publisher_domain)
        self.assertEqual(report.policy_version, POLICY_VERSION)

    def test_literal_offsets_round_trip(self):
        report = self.run_article()
        self.assertGreaterEqual(len(report.candidates), 3)
        for item in report.candidates:
            self.assertEqual(GOOD[item.start_char:item.end_char], item.literal_text)
            self.assertTrue(item.candidate_id)
            self.assertEqual(item.status, "UNVERIFIED_CANDIDATE")
            self.assertFalse(item.eligible_as_independent_evidence)

    def test_source_fingerprint(self):
        report = self.run_article()
        self.assertEqual(report.source_text_sha256, hashlib.sha256(GOOD.encode()).hexdigest())

    def test_candidate_order(self):
        report = self.run_article()
        self.assertEqual([c.literal_text for c in report.candidates], [ONE, TWO, THREE, FOUR])

    def test_stable_candidate_identity(self):
        a = self.run_article()
        b = self.run_article()
        self.assertEqual([x.candidate_id for x in a.candidates],
                         [x.candidate_id for x in b.candidates])

    def test_candidates_immutable(self):
        with self.assertRaises(dataclasses.FrozenInstanceError):
            self.run_article().candidates[0].literal_text = "forged"

    def test_report_immutable(self):
        with self.assertRaises(dataclasses.FrozenInstanceError):
            self.run_article().source_kind = "PUBLISHED"

    def test_url_publisher_and_source_provenance(self):
        r = extract_article_claim_candidates(prepared=fetched())
        self.assertEqual(r.source_kind, "FETCHED_ARTICLE_UNVERIFIED")
        self.assertEqual(r.source_url, "https://example.org/news/123")
        self.assertEqual(r.publisher_domain, "example.org")
        self.assertEqual([c.literal_text for c in r.candidates], [ONE, TWO, THREE, FOUR])
        self.assertFalse(r.independently_verified)

    def test_url_bad_hash_rejected(self):
        data = fetched()
        replaced = dataclasses.replace(data.article, text_sha256="0" * 64)
        with self.assertRaisesRegex(ClaimCandidateExtractionError, "invalid_fetched_article_provenance"):
            extract_article_claim_candidates(prepared=dataclasses.replace(data, article=replaced))

    def test_url_changed_domain_rejected(self):
        data = fetched()
        with self.assertRaisesRegex(ClaimCandidateExtractionError, "invalid_fetched_article_provenance"):
            extract_article_claim_candidates(prepared=dataclasses.replace(data, publisher_domain="evil.org"))

    def test_url_changed_url_rejected(self):
        data = fetched()
        with self.assertRaisesRegex(ClaimCandidateExtractionError, "invalid_fetched_article_provenance"):
            extract_article_claim_candidates(prepared=dataclasses.replace(data, canonical_url="https://bad.org/"))

    def test_url_forged_verified_state_rejected(self):
        data = fetched()
        with self.assertRaisesRegex(ClaimCandidateExtractionError, "invalid_fetched_article_provenance"):
            extract_article_claim_candidates(prepared=dataclasses.replace(data, independently_verified=True))

    def test_url_forged_inner_verified_state_rejected(self):
        data = fetched()
        with self.assertRaisesRegex(ClaimCandidateExtractionError, "invalid_fetched_article_provenance"):
            extract_article_claim_candidates(prepared=dataclasses.replace(
                data, article=dataclasses.replace(data.article, independently_verified=True)))

    def test_url_wrong_state_rejected(self):
        data = fetched()
        with self.assertRaisesRegex(ClaimCandidateExtractionError, "invalid_fetched_article_provenance"):
            extract_article_claim_candidates(prepared=dataclasses.replace(data, state="VERIFIED"))

    def test_rejects_tampered_pasted_sha(self):
        data = pasted()
        with self.assertRaisesRegex(ClaimCandidateExtractionError, "invalid_pasted_article_provenance"):
            extract_article_claim_candidates(prepared=dataclasses.replace(data, text_sha256="a"*64))

    def test_rejects_forged_pasted_publisher(self):
        data = pasted()
        with self.assertRaisesRegex(ClaimCandidateExtractionError, "invalid_pasted_article_provenance"):
            extract_article_claim_candidates(prepared=dataclasses.replace(data, publisher_domain="example.org"))

    def test_rejects_arbitrary_raw_text(self):
        with self.assertRaisesRegex(ClaimCandidateExtractionError, "unsupported_prepared_article_type"):
            extract_article_claim_candidates(prepared=GOOD)

    def test_preserve_unicode_offsets(self):
        text = "Café analysts stated that 14 libraries opened in Montréal. " + TWO + " " + THREE
        r = self.run_article(text)
        self.assertEqual(r.candidates[0].literal_text,
                         "Café analysts stated that 14 libraries opened in Montréal.")
        for c in r.candidates:
            self.assertEqual(text[c.start_char:c.end_char], c.literal_text)

    def test_preserve_newline_paragraph_offset(self):
        text = ONE + "\n\n" + TWO + "\n\n" + THREE
        r = self.run_article(text)
        self.assertEqual([c.paragraph_index for c in r.candidates], [0, 1, 2])
        self.assertEqual([c.start_char for c in r.candidates],
                         [0, text.index(TWO), text.index(THREE)])

    def test_duplicate_records_offset_without_extra_candidate(self):
        text = ONE + " " + TWO + " " + ONE + " " + THREE
        r = self.run_article(text)
        self.assertEqual(len(r.candidates), 3)
        self.assertEqual(r.candidates[0].duplicate_locations,
                         ((text.rindex(ONE), text.rindex(ONE) + len(ONE)),))
        self.assertIn(("duplicate_candidate", 1), r.filtered_reasons)

    def test_case_punctuation_dedup(self):
        text = ONE + " The Eiffel Tower IS located in Paris. " + TWO
        r = self.run_article(text)
        self.assertEqual(len(r.candidates), 2)
        self.assertEqual(len(r.candidates[0].duplicate_locations), 1)

    def test_negated_claim_not_deduplicated(self):
        text = ONE + " The Eiffel Tower is not located in Paris. " + TWO
        r = self.run_article(text)
        self.assertEqual(len(r.candidates), 3)

    def test_changed_numbers_not_deduplicated(self):
        text = THREE + " Officials recorded 28 new bridges in Kerala. " + TWO
        r = self.run_article(text)
        self.assertEqual(len(r.candidates), 3)

    def test_same_words_different_offsets_independent_id(self):
        text1 = ONE + " " + TWO + " " + THREE
        text2 = THREE + " " + ONE + " " + TWO
        r1 = self.run_article(text1)
        r2 = self.run_article(text2)
        self.assertNotEqual(r1.candidates[0].candidate_id, r2.candidates[1].candidate_id)

    def test_reject_question(self):
        r = self.run_article("Did NASA launch the Artemis program in 2017? " + THREE + " " + TWO)
        self.assertEqual(len(r.candidates), 2)
        self.assertIn(("non_assertive_punctuation", 1), r.filtered_reasons)

    def test_reject_opinion(self):
        r = self.run_article("In my opinion, the Eiffel Tower is the best building in Paris. " + TWO + " " + THREE)
        self.assertEqual(len(r.candidates), 2)

    def test_reject_speculation(self):
        r = self.run_article("NASA might have launched its Artemis program in 2017. " + TWO + " " + THREE)
        self.assertEqual(len(r.candidates), 2)

    def test_reject_deictic_sentence(self):
        r = self.run_article("It was inaugurated in Paris in 2019. " + TWO + " " + THREE)
        self.assertEqual(len(r.candidates), 2)

    def test_reject_headline_fragment(self):
        r = self.run_article("New bridges across the state of Kerala. " + TWO + " " + THREE)
        self.assertEqual(len(r.candidates), 2)

    def test_reject_long_sentence(self):
        sentence = "NASA announced " + "the project involved Berlin staff " * 25 + "in 2020."
        r = self.run_article(sentence + " " + ONE + " " + TWO)
        self.assertEqual(len(r.candidates), 2)

    def test_reject_short_sentence(self):
        r = self.run_article("NASA won. " + ONE + " " + TWO + " " + THREE)
        self.assertEqual(len(r.candidates), 3)

    def test_decimal_does_not_split_sentence(self):
        text = "NASA measured 3.5 metres of rainfall in Mumbai on Monday. " + TWO + " " + THREE
        r = self.run_article(text)
        self.assertEqual(r.sentences_scanned, 3)
        self.assertEqual(r.candidates[0].literal_text,
                         "NASA measured 3.5 metres of rainfall in Mumbai on Monday.")

    def test_abbreviation_does_not_split_sentence(self):
        text = "Dr. Lee recorded 35 measurements in Delhi in January. " + TWO + " " + THREE
        r = self.run_article(text)
        self.assertEqual(r.sentences_scanned, 3)
        self.assertEqual(r.candidates[0].literal_text,
                         "Dr. Lee recorded 35 measurements in Delhi in January.")

    def test_url_domain_period_not_split(self):
        text = "NASA announced that example.org hosted 14 reports in 2020. " + TWO + " " + THREE
        r = self.run_article(text)
        self.assertEqual(r.sentences_scanned, 3)

    def test_attributed_statement_keeps_attribution(self):
        text = "According to NASA, the agency launched 14 satellites in 2020. " + TWO + " " + THREE
        r = self.run_article(text)
        self.assertTrue(r.candidates[0].has_reporting_attribution)
        self.assertIn("According to NASA", r.candidates[0].literal_text)

    def test_claim_cap_bounds(self):
        text = " ".join(f"NASA recorded {i} missions in Florida during 2020." for i in range(1, 15))
        r = self.run_article(text, policy=ClaimCandidatePolicy(max_claims=3))
        self.assertEqual(len(r.candidates), 3)
        self.assertEqual(r.omitted_for_limit, 11)
        self.assertEqual(r.sentences_scanned, 14)

    def test_sentence_cap_fails_closed(self):
        text = " ".join(f"NASA recorded {i} missions in Florida during 2020." for i in range(1, 15))
        with self.assertRaisesRegex(ClaimCandidateExtractionError, "too_many_article_sentences"):
            self.run_article(text, policy=ClaimCandidatePolicy(max_sentences_scanned=4))

    def test_policy_rejects_bool(self):
        with self.assertRaisesRegex(ValueError, "invalid_claim_candidate_policy"):
            ClaimCandidatePolicy(max_claims=True)

    def test_policy_rejects_zero(self):
        with self.assertRaisesRegex(ValueError, "invalid_claim_candidate_policy"):
            ClaimCandidatePolicy(max_claims=0)

    def test_policy_rejects_invalid_sentence_lengths(self):
        with self.assertRaisesRegex(ValueError, "invalid_claim_candidate_policy"):
            ClaimCandidatePolicy(min_sentence_chars=100, max_sentence_chars=20)

    def test_policy_rejects_invalid_max_source(self):
        with self.assertRaisesRegex(ValueError, "invalid_claim_candidate_policy"):
            ClaimCandidatePolicy(max_article_chars=50)

    def test_invalid_policy_type(self):
        with self.assertRaisesRegex(ClaimCandidateExtractionError, "invalid_claim_candidate_policy"):
            self.run_article(policy="fake")

    def test_article_char_limit(self):
        with self.assertRaisesRegex(ClaimCandidateExtractionError, "article_text_outside_limit"):
            self.run_article(policy=ClaimCandidatePolicy(max_article_chars=100))

    def test_original_inputs_not_modified(self):
        source = pasted()
        before = dataclasses.asdict(source)
        extract_article_claim_candidates(prepared=source)
        self.assertEqual(before, dataclasses.asdict(source))

    def test_no_provenance_loss_empty_candidate_set(self):
        text = "The incredible weather! " * 12
        r = self.run_article(text)
        self.assertEqual(len(r.candidates), 0)
        self.assertEqual(r.source_kind, "USER_SUPPLIED_ONLY")
        self.assertFalse(r.independently_verified)

    def test_unbalanced_nonascii_does_not_mutate(self):
        text = "NASA reported that 27 districts in Delhi reopened on Tuesday. " + TWO + " " + THREE
        r = self.run_article(text)
        self.assertEqual(r.candidates[0].literal_text, text[:text.index(". ")+1])


if __name__ == "__main__":
    unittest.main()
