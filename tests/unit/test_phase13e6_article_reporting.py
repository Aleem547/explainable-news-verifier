"""Phase 13E.6: deterministic, offline article reporting and tamper tests."""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import unittest
from datetime import UTC, datetime
from uuid import UUID

from apps.api.services.article_claim_candidates import (
    ClaimCandidatePolicy,
    extract_article_claim_candidates,
)
from apps.api.services.article_level_reporting import (
    POLICY_VERSION,
    ArticleReportingError,
    build_article_level_report,
)
from apps.api.services.article_multi_claim_verification import (
    MultiClaimPolicy,
    verify_article_claims,
)
from apps.api.services.pasted_article_preparation import prepare_pasted_article
from apps.api.services.unified_verification import (
    ExternalEvidenceReference,
    ExternalFinding,
    UnifiedVerificationReport,
    WikipediaFinding,
    _relationship,
)

CLAIMS = (
    "The Eiffel Tower is located in Paris.",
    "NASA launched the Artemis program in 2017.",
    "Officials recorded 27 new bridges in Kerala.",
    "The ministry announced that 15 stations opened in Berlin.",
)
TEXT = " ".join(CLAIMS)


def _unified(claim: str, at: datetime, *, wiki: str = "SUPPORTING_EVIDENCE",
             external: str | None = None, shared_id: int = 101):
    w = WikipediaFinding(
        status="AVAILABLE" if wiki else "UNAVAILABLE",
        evidence_verdict=wiki if wiki else None,
        retrieved_count=2 if wiki else 0, assessed_count=1 if wiki else 0,
        supporting_pages=("Paris",) if wiki == "SUPPORTING_EVIDENCE" else (),
        refuting_pages=("London",) if wiki == "REFUTING_EVIDENCE" else (),
        warnings=("WIKIPEDIA_SINGLE_CORPUS_NOT_INDEPENDENT_CORROBORATION",),
    )
    ref = tuple(ExternalEvidenceReference(
        passage_id=UUID(int=shared_id + i), document_version_id=UUID(int=201 + i),
        publisher_domain=f"news{i}.example", article_url=f"https://news{i}.example/story",
        nli_label=("CONTRADICTION" if external == "PROVISIONAL_REFUTATION" else "ENTAILMENT"),
        nli_confidence=.97, nli_threshold_passed=True,
        dependency_risk_family=i + 1, duplicate_group=i + 1,
    ) for i in range(2)) if external else ()
    e = ExternalFinding(
        status="AVAILABLE" if external else "INSUFFICIENT_STORED_EVIDENCE",
        evidence_verdict=external, retrieved_count=2 if external else 1,
        assessed_count=2 if external else 0,
        provisional_agreement_units=2 if external else 0,
        provenance=ref, warnings=("SOURCE_EDITORIAL_INDEPENDENCE_NOT_ESTABLISHED",),
    )
    return UnifiedVerificationReport(
        claim=claim, assessed_at=at,
        wikipedia=w, external=e, relationship=_relationship(w, e),
        warnings=("NO_INDEPENDENT_CORROBORATION_CLAIM",),
    )


class ArticleReportTests(unittest.TestCase):
    def setUp(self):
        self.prepared = prepare_pasted_article(pasted_text=TEXT)
        self.at = datetime.now(UTC)

    def multi(self, *, fail=(), skip=None, unavailable=(), wiki="SUPPORTING_EVIDENCE",
              external=None, mixed=False, prepared=None, policy=None):
        prepared = self.prepared if prepared is None else prepared
        async def run(session, *, claim, assessed_at, **kwargs):
            if claim in fail:
                raise RuntimeError("secret-password user-sensitive-article")
            if claim in unavailable:
                return _unified(claim, assessed_at, wiki="")
            if mixed and claim == CLAIMS[1]:
                return _unified(claim, assessed_at, wiki="REFUTING_EVIDENCE", external="PROVISIONAL_SUPPORT")
            return _unified(claim, assessed_at, wiki=wiki, external=external)
        return asyncio.run(verify_article_claims(
            None, prepared=prepared, policy=policy if policy is not None else (
                MultiClaimPolicy(max_verifications=skip) if skip is not None else None
            ), assessed_at=self.at, unified_runner=run,
        ))

    def render(self, report=None, *, prepared=None, extraction_policy=None):
        return build_article_level_report(
            prepared=self.prepared if prepared is None else prepared,
            verification=self.multi() if report is None else report,
            extraction_policy=extraction_policy,
        )


    def test_no_extractable_claims(self):
        prepared = prepare_pasted_article(pasted_text="What a wonderful afternoon? " * 7)
        report = self.multi(prepared=prepared)
        result = self.render(report, prepared=prepared)
        self.assertEqual(result.candidate_count, 0)
        self.assertEqual(result.claims, ())
        self.assertIn("NO_EXTRACTABLE_CLAIM_CANDIDATES", result.warnings)

    def test_refutation_is_only_a_corpus_finding(self):
        result = self.render(self.multi(wiki="REFUTING_EVIDENCE", external="PROVISIONAL_REFUTATION"))
        self.assertEqual(result.claims[0].wikipedia_verdict, "REFUTING_EVIDENCE")
        self.assertEqual(result.claims[0].external_verdict, "PROVISIONAL_REFUTATION")
        self.assertEqual(result.claims[0].cross_corpus_relationship,
                         "PROVISIONALLY_ALIGNED_REFUTATION")
        self.assertIsNone(result.overall_article_truth_verdict)

    def test_fetched_article_canonical_provenance(self):
        from apps.api.services.article_extraction import ExtractedArticle
        from apps.api.services.article_url_preparation import PreparedArticleUrl
        extracted = ExtractedArticle(
            document_url="https://example.org/news/123", publisher_domain="example.org",
            publisher_name="Example News", text=TEXT,
            text_sha256=hashlib.sha256(TEXT.encode()).hexdigest(),
            html_sha256="a" * 64, title="Example", author=None,
            reported_publication_date=None, retrieved_at=self.at,
        )
        fetched = PreparedArticleUrl(
            canonical_url=extracted.document_url, publisher_domain="example.org",
            publisher_name="Example News", article=extracted,
        )
        result = self.render(self.multi(prepared=fetched), prepared=fetched)
        self.assertEqual(result.source_kind, "FETCHED_ARTICLE_UNVERIFIED")
        self.assertEqual(result.source_url, "https://example.org/news/123")
        self.assertEqual(result.publisher_domain, "example.org")
        self.assertFalse(result.eligible_as_independent_evidence)

    def test_reject_forged_filtered_count(self):
        report = dataclasses.replace(self.multi(), filtered_sentence_count=True)
        with self.assertRaises(ArticleReportingError):
            self.render(report)

    def test_reject_forged_omitted_count(self):
        report = dataclasses.replace(self.multi(), omitted_candidate_count=True)
        with self.assertRaises(ArticleReportingError):
            self.render(report)

    def test_reject_source_timestamp(self):
        report = dataclasses.replace(self.multi(), source_timestamp=datetime(2000, 1, 1, tzinfo=UTC))
        with self.assertRaises(ArticleReportingError):
            self.render(report)

    def test_reject_unavailable_with_available_evidence(self):
        report = self.multi()
        items = list(report.claims)
        items[0] = dataclasses.replace(items[0], status="UNAVAILABLE",
                                      warning_codes=("BOTH_EVIDENCE_PATHS_UNAVAILABLE_OR_INSUFFICIENT",))
        report = dataclasses.replace(report, claims=tuple(items), assessed_count=3, unavailable_count=1,
                                     warnings=("EVIDENCE_UNAVAILABLE_FOR_SOME_CLAIMS",
                                               "NO_ARTICLE_LEVEL_TRUTH_VERDICT",
                                               "SOURCE_INDEPENDENCE_NOT_ESTABLISHED"))
        with self.assertRaises(ArticleReportingError):
            self.render(report)

    def test_report_policy_version(self):
        self.assertEqual(self.render().policy_version, POLICY_VERSION)

    def test_all_claims_and_counts(self):
        result = self.render()
        self.assertEqual((result.candidate_count, result.assessed_count, result.failed_count), (4, 4, 0))
        self.assertEqual(len(result.claims), 4)
        self.assertEqual(result.wikipedia_available_count, 4)
        self.assertEqual(result.external_available_count, 0)

    def test_exact_original_offsets(self):
        result = self.render()
        for item in result.claims:
            self.assertEqual(self.prepared.text[item.start_char:item.end_char], item.literal_text)

    def test_pasted_provenance_no_forged_publisher(self):
        result = self.render()
        self.assertEqual(result.source_kind, "USER_SUPPLIED_ONLY")
        self.assertIsNone(result.source_url)
        self.assertIsNone(result.publisher_domain)
        self.assertEqual(result.article_sha256, hashlib.sha256(TEXT.encode()).hexdigest())
        self.assertEqual(result.provenance_status, "ARTICLE_INPUT_NOT_INDEPENDENT_EVIDENCE")

    def test_no_aggregate_factual_truth_or_independence(self):
        result = self.render()
        self.assertIsNone(result.overall_article_truth_verdict)
        self.assertIsNone(result.overall_article_truth_probability)
        self.assertFalse(result.independently_verified)
        self.assertFalse(result.independent_corroboration_established)
        self.assertFalse(result.eligible_as_independent_evidence)
        self.assertEqual(result.independence_status, "NOT_ESTABLISHED")

    def test_wikipedia_pages_not_fabricated_urls(self):
        result = self.render()
        self.assertEqual(result.claims[0].wikipedia_supporting_pages, ("Paris",))
        self.assertEqual(result.claims[0].wikipedia_refuting_pages, ())

    def test_external_citations_preserve_urls_and_versions(self):
        result = self.render(self.multi(external="PROVISIONAL_SUPPORT"))
        self.assertEqual(result.external_available_count, 4)
        self.assertEqual(len(result.claims[0].external_references), 2)
        ref = result.claims[0].external_references[0]
        self.assertEqual(ref.publisher_domain, "news0.example")
        self.assertEqual(ref.article_url, "https://news0.example/story")
        self.assertEqual(ref.document_version_id, UUID(int=201))
        self.assertEqual(ref.passage_id, UUID(int=101))
        self.assertAlmostEqual(ref.nli_confidence, .97)
        self.assertEqual(ref.independence_status, "NOT_ESTABLISHED")

    def test_same_passage_claim_specific_citation_id(self):
        result = self.render(self.multi(external="PROVISIONAL_SUPPORT"))
        a, b = result.claims[0].external_references[0], result.claims[1].external_references[0]
        self.assertEqual(a.passage_id, b.passage_id)
        self.assertNotEqual(a.citation_id, b.citation_id)
        self.assertNotEqual(a.claim_id, b.claim_id)

    def test_opposing_corpus_not_truth_override(self):
        result = self.render(self.multi(mixed=True, external="PROVISIONAL_SUPPORT"))
        self.assertEqual(result.opposing_corpus_count, 1)
        self.assertEqual(result.claims[1].cross_corpus_relationship, "OPPOSING_CORPUS_FINDINGS")
        self.assertIn("OPPOSING_CORPUS_FINDINGS_REVIEW_REQUIRED", result.warnings)
        self.assertIsNone(result.overall_article_truth_verdict)

    def test_failed_claim_does_not_hide_others(self):
        result = self.render(self.multi(fail={CLAIMS[1]}))
        self.assertEqual(result.failed_count, 1)
        self.assertEqual(result.assessed_count, 3)
        self.assertEqual(result.claims[1].execution_status, "FAILED")
        self.assertIsNone(result.claims[1].wikipedia_status)
        self.assertNotIn("secret-password", repr(result))
        self.assertIn("CLAIM_VERIFICATION_PARTIAL_FAILURE", result.warnings)

    def test_skipped_claim_explicit(self):
        result = self.render(self.multi(skip=2))
        self.assertEqual(result.skipped_count, 2)
        self.assertEqual(result.claims[2].warning_codes, ("CLAIM_BUDGET_EXHAUSTED",))
        self.assertIn("CLAIM_VERIFICATION_BUDGET_EXHAUSTED", result.warnings)

    def test_unavailable_claim_keeps_snapshot(self):
        result = self.render(self.multi(unavailable={CLAIMS[0]}))
        self.assertEqual(result.unavailable_count, 1)
        self.assertEqual(result.claims[0].wikipedia_status, "UNAVAILABLE")
        self.assertEqual(result.claims[0].external_status, "INSUFFICIENT_STORED_EVIDENCE")
        self.assertEqual(result.claims[0].execution_status, "UNAVAILABLE")

    def test_read_only_immutable(self):
        report = self.render()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            report.assessed_count = 800
        with self.assertRaises(dataclasses.FrozenInstanceError):
            report.claims[0].literal_text = "altered"

    def test_reject_wrong_article_hash(self):
        report = dataclasses.replace(self.multi(), article_sha256="0" * 64)
        with self.assertRaises(ArticleReportingError):
            self.render(report)

    def test_reject_wrong_source_kind(self):
        report = dataclasses.replace(self.multi(), source_kind="FETCHED_ARTICLE_UNVERIFIED")
        with self.assertRaises(ArticleReportingError):
            self.render(report)

    def test_reject_forged_source_url(self):
        report = dataclasses.replace(self.multi(), source_url="https://fake.example/story")
        with self.assertRaises(ArticleReportingError):
            self.render(report)

    def test_reject_changed_article_input(self):
        other = prepare_pasted_article(pasted_text=TEXT + " Another outlet opened in Rome in 2025.")
        with self.assertRaises(ArticleReportingError):
            self.render(self.multi(), prepared=other)

    def test_reject_modified_claim_literal(self):
        report = self.multi()
        claims = list(report.claims)
        claims[0] = dataclasses.replace(claims[0], literal_text="Something false")
        with self.assertRaises(ArticleReportingError):
            self.render(dataclasses.replace(report, claims=tuple(claims)))

    def test_reject_changed_offset(self):
        report = self.multi()
        claims = list(report.claims)
        claims[0] = dataclasses.replace(claims[0], start_char=5)
        with self.assertRaises(ArticleReportingError):
            self.render(dataclasses.replace(report, claims=tuple(claims)))

    def test_reject_swapped_claim_order(self):
        report = self.multi()
        with self.assertRaises(ArticleReportingError):
            self.render(dataclasses.replace(report, claims=tuple(reversed(report.claims))))

    def test_reject_count_inflation(self):
        report = dataclasses.replace(self.multi(), assessed_count=100)
        with self.assertRaises(ArticleReportingError):
            self.render(report)

    def test_reject_negative_count(self):
        report = dataclasses.replace(self.multi(), failed_count=-1)
        with self.assertRaises(ArticleReportingError):
            self.render(report)

    def test_reject_boolean_count(self):
        report = dataclasses.replace(self.multi(), failed_count=True)
        with self.assertRaises(ArticleReportingError):
            self.render(report)

    def test_reject_forged_complete_truth(self):
        report = dataclasses.replace(self.multi(), independently_verified=True)
        with self.assertRaises(ArticleReportingError):
            self.render(report)

    def test_reject_article_warnings_with_secrets(self):
        report = dataclasses.replace(self.multi(), warnings=("password=secret",))
        with self.assertRaises(ArticleReportingError):
            self.render(report)

    def test_reject_forged_nested_independence(self):
        report = self.multi(external="PROVISIONAL_SUPPORT")
        items = list(report.claims)
        forged = dataclasses.replace(items[0].report, independently_verified=True)
        items[0] = dataclasses.replace(items[0], report=forged)
        with self.assertRaises(ArticleReportingError):
            self.render(dataclasses.replace(report, claims=tuple(items)))

    def test_reject_forged_external_reference_url(self):
        report = self.multi(external="PROVISIONAL_SUPPORT")
        items = list(report.claims)
        unified = items[0].report
        refs = unified.external.provenance
        forged = dataclasses.replace(refs[0], article_url="http://127.0.0.1")
        ext = dataclasses.replace(unified.external, provenance=(forged, refs[1]))
        items[0] = dataclasses.replace(items[0], report=dataclasses.replace(unified, external=ext))
        with self.assertRaises(ArticleReportingError):
            self.render(dataclasses.replace(report, claims=tuple(items)))

    def test_reject_forged_warning_for_failed(self):
        report = self.multi(fail={CLAIMS[1]})
        items = list(report.claims)
        items[1] = dataclasses.replace(items[1], warning_codes=("SOME_RANDOM_WARNING",))
        with self.assertRaises(ArticleReportingError):
            self.render(dataclasses.replace(report, claims=tuple(items)))

    def test_reject_failed_with_unified_report(self):
        report = self.multi(fail={CLAIMS[1]})
        items = list(report.claims)
        items[1] = dataclasses.replace(items[1], report=items[0].report)
        with self.assertRaises(ArticleReportingError):
            self.render(dataclasses.replace(report, claims=tuple(items)))

    def test_reject_skipped_with_report(self):
        report = self.multi(skip=1)
        items = list(report.claims)
        items[1] = dataclasses.replace(items[1], report=items[0].report)
        with self.assertRaises(ArticleReportingError):
            self.render(dataclasses.replace(report, claims=tuple(items)))

    def test_reject_forged_status(self):
        report = self.multi()
        items = list(report.claims)
        items[0] = dataclasses.replace(items[0], status="VERIFIED_TRUE")
        with self.assertRaises(ArticleReportingError):
            self.render(dataclasses.replace(report, claims=tuple(items)))

    def test_reject_bad_candidate_count(self):
        report = dataclasses.replace(self.multi(), candidate_count=3)
        with self.assertRaises(ArticleReportingError):
            self.render(report)

    def test_reject_wrong_assessment_time(self):
        report = self.multi()
        items = list(report.claims)
        items[0] = dataclasses.replace(items[0], report=dataclasses.replace(items[0].report,
                                                     assessed_at=datetime(2000, 1, 1, tzinfo=UTC)))
        with self.assertRaises(ArticleReportingError):
            self.render(dataclasses.replace(report, claims=tuple(items)))

    def test_custom_claim_extraction_policy_must_match(self):
        p = ClaimCandidatePolicy(max_claims=2)
        prepared = self.prepared
        multi = self.multi(prepared=prepared, policy=None)  # Uses original full report.
        with self.assertRaises(ArticleReportingError):
            self.render(multi, extraction_policy=p)


if __name__ == "__main__":
    unittest.main()
