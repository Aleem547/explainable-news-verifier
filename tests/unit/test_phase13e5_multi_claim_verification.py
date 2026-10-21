"""Phase 13E.5: offline, no-model, no-DB, no-HTTP tests."""
from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import unittest
from datetime import UTC, datetime, timedelta
from uuid import UUID

from apps.api.services.article_claim_candidates import (
    ClaimCandidatePolicy,
    extract_article_claim_candidates,
)
from apps.api.services.article_multi_claim_verification import (
    POLICY_VERSION,
    MultiClaimPolicy,
    MultiClaimVerificationError,
    _validate_unified_report,
    verify_article_claims,
)
from apps.api.services.pasted_article_preparation import prepare_pasted_article
from apps.api.services.unified_verification import (
    POLICY_VERSION as UNIFIED_VERSION,
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


def _wiki(available=True, verdict="SUPPORTING_EVIDENCE"):
    return WikipediaFinding(
        status="AVAILABLE" if available else "UNAVAILABLE",
        evidence_verdict=verdict if available else None,
        retrieved_count=2 if available else 0,
        assessed_count=1 if available else 0,
        supporting_pages=("Paris",) if available else (),
        refuting_pages=(), warnings=("WIKIPEDIA_SINGLE_CORPUS_NOT_INDEPENDENT_CORROBORATION",),
    )


def _ext(available=False, verdict="PROVISIONAL_SUPPORT"):
    refs = tuple(ExternalEvidenceReference(
        passage_id=UUID(int=101+i), document_version_id=UUID(int=201+i),
        publisher_domain=f"news{i}.example", article_url=f"https://news{i}.example/story",
        nli_label="ENTAILMENT", nli_confidence=0.97, nli_threshold_passed=True,
        dependency_risk_family=i+1, duplicate_group=i+1,
    ) for i in range(2)) if available else ()
    return ExternalFinding(
        status="AVAILABLE" if available else "INSUFFICIENT_STORED_EVIDENCE",
        evidence_verdict=verdict if available else None,
        retrieved_count=2 if available else 1,
        assessed_count=2 if available else 0,
        provisional_agreement_units=2 if available else 0,
        provenance=refs,
        warnings=("SOURCE_EDITORIAL_INDEPENDENCE_NOT_ESTABLISHED",),
    )


def _unified(claim, at, *, wiki=True, ext=False, wiki_verdict="SUPPORTING_EVIDENCE", ext_verdict="PROVISIONAL_SUPPORT"):
    w = _wiki(wiki, wiki_verdict)
    e = _ext(ext, ext_verdict)
    return UnifiedVerificationReport(
        claim=claim, assessed_at=at, wikipedia=w, external=e,
        relationship=_relationship(w, e),
        warnings=("NO_INDEPENDENT_CORROBORATION_CLAIM",),
    )


class PolicyTests(unittest.TestCase):
    def test_defaults(self):
        p = MultiClaimPolicy()
        self.assertEqual(p.max_verifications, 8)
        self.assertEqual(p.external_top_k, 10)
        self.assertEqual(p.nli_threshold, 0.9)

    def test_immutable(self):
        with self.assertRaises(dataclasses.FrozenInstanceError):
            MultiClaimPolicy().max_verifications = 300

    def test_valid_edges(self):
        MultiClaimPolicy(max_verifications=1, wikipedia_top_k=1, external_top_k=2, nli_threshold=0.5)
        MultiClaimPolicy(max_verifications=20, wikipedia_top_k=20, external_top_k=20, nli_threshold=1.0)

    def test_bad_max_verifications(self):
        for value in (0, 21, -1, True, 1.3, "8"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                MultiClaimPolicy(max_verifications=value)

    def test_bad_wiki_k(self):
        for value in (0, 21, True, 3.2, "10"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                MultiClaimPolicy(wikipedia_top_k=value)

    def test_bad_external_k(self):
        for value in (0, 1, 21, True, 3.2, "10"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                MultiClaimPolicy(external_top_k=value)

    def test_bad_threshold(self):
        for value in (float("nan"), float("inf"), -1, True, "0.9", .49, 1.01):
            with self.subTest(value=value), self.assertRaises(ValueError):
                MultiClaimPolicy(nli_threshold=value)


class ValidationTests(unittest.TestCase):
    def test_accept_wiki_only(self):
        result = _unified(CLAIMS[0], datetime.now(UTC))
        self.assertIs(_validate_unified_report(result, claim=result.claim, at=result.assessed_at), result)

    def test_accept_external_with_references(self):
        result = _unified(CLAIMS[0], datetime.now(UTC), ext=True)
        self.assertIs(_validate_unified_report(result, claim=result.claim, at=result.assessed_at), result)

    def test_refuse_raw_dict(self):
        with self.assertRaises(ValueError):
            _validate_unified_report({"claim": CLAIMS[0]}, claim=CLAIMS[0], at=datetime.now(UTC))

    def test_wrong_claim_rejected(self):
        result = _unified(CLAIMS[0], datetime.now(UTC))
        with self.assertRaises(ValueError):
            _validate_unified_report(result, claim=CLAIMS[1], at=result.assessed_at)

    def test_wrong_time_rejected(self):
        result = _unified(CLAIMS[0], datetime.now(UTC))
        with self.assertRaises(ValueError):
            _validate_unified_report(result, claim=CLAIMS[0], at=result.assessed_at + timedelta(seconds=1))

    def test_wrong_policy_rejected(self):
        result = dataclasses.replace(_unified(CLAIMS[0], datetime.now(UTC)), policy_version="x")
        with self.assertRaises(ValueError):
            _validate_unified_report(result, claim=result.claim, at=result.assessed_at)

    def test_forged_independence_rejected(self):
        for attribute, value in (("independently_verified", True),
                                 ("independence_status", "ESTABLISHED"),
                                 ("independent_corroboration_established", True)):
            result = dataclasses.replace(_unified(CLAIMS[0], datetime.now(UTC)), **{attribute: value})
            with self.subTest(attribute=attribute), self.assertRaises(ValueError):
                _validate_unified_report(result, claim=result.claim, at=result.assessed_at)

    def test_forged_external_independence_rejected(self):
        result = _unified(CLAIMS[0], datetime.now(UTC), ext=True)
        result = dataclasses.replace(result, external=dataclasses.replace(result.external,
                                        independent_corroboration_established=True))
        with self.assertRaises(ValueError):
            _validate_unified_report(result, claim=result.claim, at=result.assessed_at)

    def test_forged_wiki_corroboration_rejected(self):
        result = _unified(CLAIMS[0], datetime.now(UTC))
        result = dataclasses.replace(result, wikipedia=dataclasses.replace(result.wikipedia,
                                        corroboration_status="ESTABLISHED"))
        with self.assertRaises(ValueError):
            _validate_unified_report(result, claim=result.claim, at=result.assessed_at)

    def test_wrong_relationship_rejected(self):
        result = dataclasses.replace(_unified(CLAIMS[0], datetime.now(UTC)), relationship="TRUE")
        with self.assertRaises(ValueError):
            _validate_unified_report(result, claim=result.claim, at=result.assessed_at)

    def test_nonfinite_confidence_rejected(self):
        result = _unified(CLAIMS[0], datetime.now(UTC), ext=True)
        corrupted = dataclasses.replace(result.external.provenance[0], nli_confidence=float("nan"))
        result = dataclasses.replace(result, external=dataclasses.replace(result.external,
                                        provenance=(corrupted, result.external.provenance[1])))
        with self.assertRaises(ValueError):
            _validate_unified_report(result, claim=result.claim, at=result.assessed_at)

    def test_duplicate_reference_rejected(self):
        result = _unified(CLAIMS[0], datetime.now(UTC), ext=True)
        refs = result.external.provenance
        result = dataclasses.replace(result, external=dataclasses.replace(result.external,
                                        provenance=(refs[0], refs[0])))
        with self.assertRaises(ValueError):
            _validate_unified_report(result, claim=result.claim, at=result.assessed_at)

    def test_http_reference_rejected(self):
        result = _unified(CLAIMS[0], datetime.now(UTC), ext=True)
        forged = dataclasses.replace(result.external.provenance[0], article_url="http://news.example")
        result = dataclasses.replace(result, external=dataclasses.replace(result.external,
                                        provenance=(forged, result.external.provenance[1])))
        with self.assertRaises(ValueError):
            _validate_unified_report(result, claim=result.claim, at=result.assessed_at)

    def test_external_status_inconsistent_rejected(self):
        result = _unified(CLAIMS[0], datetime.now(UTC), ext=True)
        result = dataclasses.replace(result, external=dataclasses.replace(result.external,
                                        status="UNAVAILABLE"))
        with self.assertRaises(ValueError):
            _validate_unified_report(result, claim=result.claim, at=result.assessed_at)

    def test_bad_warnings_rejected(self):
        result = dataclasses.replace(_unified(CLAIMS[0], datetime.now(UTC)), warnings=("SECRET password=123",))
        with self.assertRaises(ValueError):
            _validate_unified_report(result, claim=result.claim, at=result.assessed_at)

    def test_negative_counts_rejected(self):
        result = _unified(CLAIMS[0], datetime.now(UTC))
        result = dataclasses.replace(result, wikipedia=dataclasses.replace(result.wikipedia, retrieved_count=-1))
        with self.assertRaises(ValueError):
            _validate_unified_report(result, claim=result.claim, at=result.assessed_at)

    def test_report_nested_immutable(self):
        result = _unified(CLAIMS[0], datetime.now(UTC))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            result.claim = "altered"


class RunTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.prepared = prepare_pasted_article(pasted_text=TEXT)
        self.candidates = extract_article_claim_candidates(prepared=self.prepared)
        self.at = datetime.now(UTC)
        self.calls = []

    def runner(self, *, outcomes=None, failing=None, ext=False):
        failing = set() if failing is None else failing
        async def run(session, *, claim, wikipedia_top_k, external_top_k, nli_threshold, assessed_at):
            self.calls.append((session, claim, wikipedia_top_k, external_top_k, nli_threshold, assessed_at))
            if claim in failing:
                raise RuntimeError("sensitive SQL and submitted text")
            if outcomes and claim in outcomes:
                return outcomes[claim]
            return _unified(claim, assessed_at, ext=ext)
        return run

    async def invoke(self, **kwargs):
        return await verify_article_claims(
            object(), prepared=self.prepared, candidate_report=self.candidates,
            assessed_at=self.at, unified_runner=self.runner(), **kwargs,
        )

    async def test_order_and_all_claims(self):
        report = await self.invoke()
        self.assertEqual(report.candidate_count, 4)
        self.assertEqual(report.assessed_count, 4)
        self.assertEqual([c.literal_text for c in report.claims], list(CLAIMS))
        self.assertEqual([x[1] for x in self.calls], list(CLAIMS))

    async def test_span_identity_and_provenance(self):
        report = await self.invoke()
        for c in report.claims:
            self.assertEqual(self.prepared.text[c.start_char:c.end_char], c.literal_text)
        self.assertEqual(report.article_sha256, hashlib.sha256(TEXT.encode()).hexdigest())
        self.assertEqual(report.source_kind, "USER_SUPPLIED_ONLY")
        self.assertEqual(report.source_timestamp, self.prepared.received_at)
        self.assertTrue(all(len(c.normalized_fingerprint) == 64 for c in report.claims))
        self.assertIsNone(report.source_url)
        self.assertIsNone(report.publisher_domain)
        self.assertFalse(report.eligible_as_independent_evidence)

    async def test_shared_assessment_clock(self):
        report = await self.invoke()
        self.assertEqual(report.assessed_at, self.at)
        self.assertEqual({x[5] for x in self.calls}, {self.at})
        self.assertEqual({r.report.assessed_at for r in report.claims}, {self.at})

    async def test_uses_configured_budgets(self):
        p = MultiClaimPolicy(max_verifications=2, wikipedia_top_k=3, external_top_k=4, nli_threshold=.95)
        report = await self.invoke(policy=p)
        self.assertEqual(len(self.calls), 2)
        self.assertTrue(all(x[2:5] == (3, 4, .95) for x in self.calls))
        self.assertEqual([r.status for r in report.claims],
                         ["ASSESSED", "ASSESSED", "SKIPPED_LIMIT", "SKIPPED_LIMIT"])
        self.assertEqual((report.assessed_count, report.skipped_count), (2, 2))

    async def test_policy_one_executes_one(self):
        report = await self.invoke(policy=MultiClaimPolicy(max_verifications=1))
        self.assertEqual((report.assessed_count, report.skipped_count), (1, 3))
        self.assertIn("CLAIM_VERIFICATION_BUDGET_EXHAUSTED", report.warnings)

    async def test_fail_one_continue_rest(self):
        report = await verify_article_claims(
            None, prepared=self.prepared, assessed_at=self.at,
            unified_runner=self.runner(failing={CLAIMS[1]}),
        )
        self.assertEqual([x.status for x in report.claims],
                         ["ASSESSED", "FAILED", "ASSESSED", "ASSESSED"])
        self.assertEqual(len(self.calls), 4)
        self.assertEqual(report.failed_count, 1)
        self.assertNotIn("sensitive SQL", repr(report))
        self.assertIn("CLAIM_VERIFICATION_PARTIAL_FAILURE", report.warnings)

    async def test_multiple_failures(self):
        report = await verify_article_claims(
            None, prepared=self.prepared, assessed_at=self.at,
            unified_runner=self.runner(failing={CLAIMS[0], CLAIMS[2]}),
        )
        self.assertEqual(report.failed_count, 2)
        self.assertEqual(report.assessed_count, 2)

    async def test_unavailable_not_reported_as_assessed(self):
        async def unavailable(session, *, claim, assessed_at, **kw):
            self.calls.append(claim)
            return _unified(claim, assessed_at, wiki=False, ext=False)
        report = await verify_article_claims(
            None, prepared=self.prepared, assessed_at=self.at, unified_runner=unavailable,
        )
        self.assertEqual(report.unavailable_count, 4)
        self.assertEqual(report.assessed_count, 0)
        self.assertTrue(all(c.status == "UNAVAILABLE" for c in report.claims))

    async def test_wiki_only_is_assessed_not_truth(self):
        report = await self.invoke()
        self.assertTrue(all(x.report.external.status == "INSUFFICIENT_STORED_EVIDENCE" for x in report.claims))
        self.assertTrue(all(x.report.relationship == "WIKIPEDIA_ONLY" for x in report.claims))
        self.assertIsNone(report.overall_article_truth_verdict)
        self.assertFalse(report.independently_verified)
        self.assertFalse(report.independent_corroboration_established)

    async def test_external_provisional_not_article_truth(self):
        result = await verify_article_claims(None, prepared=self.prepared, assessed_at=self.at,
                                           unified_runner=self.runner(ext=True))
        self.assertTrue(all(c.report.external.evidence_verdict == "PROVISIONAL_SUPPORT" for c in result.claims))
        self.assertFalse(result.independent_corroboration_established)
        self.assertIsNone(result.overall_article_truth_verdict)

    async def test_forged_report_isolated(self):
        bad = dataclasses.replace(_unified(CLAIMS[0], self.at), independently_verified=True)
        report = await verify_article_claims(None, prepared=self.prepared, assessed_at=self.at,
                                           unified_runner=self.runner(outcomes={CLAIMS[0]: bad}))
        self.assertEqual(report.failed_count, 1)
        self.assertIsNone(report.claims[0].report)
        self.assertEqual(report.assessed_count, 3)

    async def test_wrong_claim_report_isolated(self):
        bad = _unified(CLAIMS[1], self.at)
        report = await verify_article_claims(None, prepared=self.prepared, assessed_at=self.at,
                                           unified_runner=self.runner(outcomes={CLAIMS[0]: bad}))
        self.assertEqual(report.claims[0].status, "FAILED")
        self.assertEqual(report.claims[1].status, "ASSESSED")

    async def test_bad_timestamp_report_isolated(self):
        bad = _unified(CLAIMS[0], self.at + timedelta(seconds=3))
        report = await verify_article_claims(None, prepared=self.prepared, assessed_at=self.at,
                                           unified_runner=self.runner(outcomes={CLAIMS[0]: bad}))
        self.assertEqual(report.claims[0].status, "FAILED")

    async def test_result_immutable(self):
        report = await self.invoke()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            report.claims[0].literal_text = "something else"

    async def test_report_immutable(self):
        report = await self.invoke()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            report.independently_verified = True

    async def test_policy_version(self):
        report = await self.invoke()
        self.assertEqual(report.policy_version, POLICY_VERSION)
        self.assertEqual(report.claims[0].report.policy_version, UNIFIED_VERSION)

    async def test_duplicate_candidate_only_verified_once(self):
        text = f"{CLAIMS[0]} {CLAIMS[1]} {CLAIMS[0]} {CLAIMS[2]}"
        prepared = prepare_pasted_article(pasted_text=text)
        report = await verify_article_claims(None, prepared=prepared, assessed_at=self.at,
                                            unified_runner=self.runner())
        self.assertEqual(report.candidate_count, 3)
        self.assertEqual(len(self.calls), 3)
        self.assertEqual(len(report.claims[0].duplicate_locations), 1)

    async def test_zero_candidates(self):
        prep = prepare_pasted_article(pasted_text="A headline with no recognizable factual structure. " * 3)
        report = await verify_article_claims(None, prepared=prep, assessed_at=self.at,
                                            unified_runner=self.runner())
        self.assertEqual(report.candidate_count, 0)
        self.assertIn("NO_EXTRACTABLE_CLAIM_CANDIDATES", report.warnings)
        self.assertEqual(self.calls, [])

    async def test_reject_tampered_article_no_runner(self):
        forged = dataclasses.replace(self.prepared, text_sha256="f" * 64)
        with self.assertRaises(MultiClaimVerificationError):
            await verify_article_claims(None, prepared=forged,
                                        assessed_at=self.at, unified_runner=self.runner())
        self.assertEqual(self.calls, [])

    async def test_reject_forged_extraction_report_no_runner(self):
        forged = dataclasses.replace(self.candidates, independently_verified=True)
        with self.assertRaisesRegex(MultiClaimVerificationError, "article_candidate_report_mismatch"):
            await verify_article_claims(None, prepared=self.prepared, candidate_report=forged,
                                        assessed_at=self.at, unified_runner=self.runner())
        self.assertEqual(self.calls, [])

    async def test_reject_wrong_source_report_no_runner(self):
        other = prepare_pasted_article(pasted_text=" ".join(reversed(CLAIMS)))
        forged = extract_article_claim_candidates(prepared=other)
        with self.assertRaisesRegex(MultiClaimVerificationError, "article_candidate_report_mismatch"):
            await verify_article_claims(None, prepared=self.prepared, candidate_report=forged,
                                        assessed_at=self.at, unified_runner=self.runner())
        self.assertEqual(self.calls, [])

    async def test_reject_forged_candidate_offset(self):
        altered = dataclasses.replace(self.candidates.candidates[0], start_char=3)
        forged = dataclasses.replace(self.candidates, candidates=(altered, *self.candidates.candidates[1:]))
        with self.assertRaisesRegex(MultiClaimVerificationError, "article_candidate_report_mismatch"):
            await verify_article_claims(None, prepared=self.prepared, candidate_report=forged,
                                        assessed_at=self.at, unified_runner=self.runner())

    async def test_reject_invalid_policy(self):
        with self.assertRaisesRegex(MultiClaimVerificationError, "invalid_multi_claim_policy"):
            await verify_article_claims(None, prepared=self.prepared, policy="illegal", unified_runner=self.runner())

    async def test_reject_invalid_extraction_policy(self):
        with self.assertRaisesRegex(MultiClaimVerificationError, "invalid_claim_extraction_policy"):
            await verify_article_claims(None, prepared=self.prepared, extraction_policy=123,
                                        unified_runner=self.runner())

    async def test_custom_extraction_policy(self):
        policy = ClaimCandidatePolicy(max_claims=2)
        report = extract_article_claim_candidates(prepared=self.prepared, policy=policy)
        result = await verify_article_claims(None, prepared=self.prepared, candidate_report=report,
                                            extraction_policy=policy, assessed_at=self.at,
                                            unified_runner=self.runner())
        self.assertEqual(result.candidate_count, 2)
        self.assertEqual(result.omitted_candidate_count, 2)

    async def test_reject_naive_timestamp(self):
        with self.assertRaisesRegex(MultiClaimVerificationError, "invalid_assessment_timestamp"):
            await verify_article_claims(None, prepared=self.prepared,
                                        assessed_at=datetime(2026, 10, 1), unified_runner=self.runner())

    async def test_reject_future_timestamp(self):
        with self.assertRaisesRegex(MultiClaimVerificationError, "invalid_assessment_timestamp"):
            await verify_article_claims(None, prepared=self.prepared,
                                        assessed_at=datetime.now(UTC) + timedelta(days=1), unified_runner=self.runner())

    async def test_invalid_runner_rejected(self):
        with self.assertRaisesRegex(MultiClaimVerificationError, "invalid_unified_runner"):
            await verify_article_claims(None, prepared=self.prepared, unified_runner="not callable")

    async def test_cancellation_propagates(self):
        async def cancelled(*args, **kwargs):
            raise asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await verify_article_claims(None, prepared=self.prepared,
                                        assessed_at=self.at, unified_runner=cancelled)

    async def test_no_confidence_as_article_truth(self):
        result = await self.invoke()
        self.assertNotIn("overall_accuracy", dataclasses.asdict(result))
        self.assertIsNone(result.overall_article_truth_verdict)

    async def test_candidate_failure_does_not_remove_later_candidates(self):
        report = await verify_article_claims(None, prepared=self.prepared, assessed_at=self.at,
                                            unified_runner=self.runner(failing={CLAIMS[2]}))
        self.assertEqual(report.claims[-1].status, "ASSESSED")
        self.assertEqual(report.claims[2].status, "FAILED")


if __name__ == "__main__":
    unittest.main()

# Tests for an already permission-gated, fetched URL article. No HTTP occurs.
class FetchedArticleTests(unittest.IsolatedAsyncioTestCase):
    async def test_url_provenance_propagated_without_publisher_trust_claim(self):
        from apps.api.services.article_extraction import ExtractedArticle
        from apps.api.services.article_url_preparation import PreparedArticleUrl
        sha = hashlib.sha256(TEXT.encode("utf-8")).hexdigest()
        article = ExtractedArticle(
            document_url="https://example.org/news/123", publisher_domain="example.org",
            publisher_name="Example News", text=TEXT, text_sha256=sha,
            html_sha256="a" * 64, title="Article", author=None,
            reported_publication_date=None, retrieved_at=datetime.now(UTC),
        )
        prepared = PreparedArticleUrl(
            canonical_url=article.document_url, publisher_domain="example.org",
            publisher_name="Example News", article=article,
        )
        async def runner(session, *, claim, assessed_at, **kw):
            return _unified(claim, assessed_at)
        report = await verify_article_claims(None, prepared=prepared, unified_runner=runner)
        self.assertEqual(report.source_kind, "FETCHED_ARTICLE_UNVERIFIED")
        self.assertEqual(report.source_url, "https://example.org/news/123")
        self.assertEqual(report.publisher_domain, "example.org")
        self.assertEqual(report.assessed_count, 4)
        self.assertFalse(report.independent_corroboration_established)

    async def test_url_modified_hash_rejected_before_runner(self):
        from apps.api.services.article_extraction import ExtractedArticle
        from apps.api.services.article_url_preparation import PreparedArticleUrl
        article = ExtractedArticle(
            document_url="https://example.org/news/123", publisher_domain="example.org",
            publisher_name="Example News", text=TEXT, text_sha256="0" * 64,
            html_sha256="a" * 64, title="Article", author=None,
            reported_publication_date=None, retrieved_at=datetime.now(UTC),
        )
        prepared = PreparedArticleUrl(
            canonical_url=article.document_url, publisher_domain="example.org",
            publisher_name="Example News", article=article,
        )
        calls = []
        async def runner(*args, **kw):
            calls.append(kw)
        with self.assertRaises(MultiClaimVerificationError):
            await verify_article_claims(None, prepared=prepared, unified_runner=runner)
        self.assertEqual(calls, [])
