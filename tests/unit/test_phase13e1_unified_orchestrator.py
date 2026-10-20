"""Offline tests for 13E.1. All evidence, model results and DB calls are fakes."""
from __future__ import annotations

import asyncio
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from uuid import UUID

from apps.api.services.unified_verification import (
    UnifiedVerificationError,
    _relationship,
    _snapshot_external,
    _snapshot_wikipedia,
    _validate_request,
    orchestrate_unified_verification,
)

AT = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
CLAIM = "Paris is the capital of France."


def wiki(verdict="SUPPORTING_EVIDENCE", **changes):
    values = dict(
        claim=CLAIM, verdict=verdict, corroboration_status="NOT_ESTABLISHED_SINGLE_CORPUS",
        retrieved_count=4, assessed_count=2, supporting_pages=["Paris"], refuting_pages=[],
    )
    values.update(changes)
    return SimpleNamespace(**values)


def candidates(count=2, same_version=False):
    return tuple(SimpleNamespace(
        passage_id=UUID(int=100+i), document_version_id=UUID(int=200 if same_version else 200+i),
    ) for i in range(count))


def reports(cands, verdict="PROVISIONAL_SUPPORT", **changes):
    rows = tuple(SimpleNamespace(
        passage_id=x.passage_id, document_version_id=x.document_version_id,
        publisher_domain=f"publisher{i}.example", article_url=f"https://publisher{i}.example/story",
        nli_label="ENTAILMENT", nli_confidence=.97, nli_threshold_passed=True,
        dependency_risk_family=i+1, duplicate_group=i+1,
    ) for i, x in enumerate(cands))
    nli = SimpleNamespace(
        claim=CLAIM, assessed_at=AT, evidence=rows, independence_status="NOT_ESTABLISHED",
        independently_verified=False, independent_corroboration_established=False,
    )
    agreement = SimpleNamespace(
        claim=CLAIM, assessed_at=AT,
        provisional_agreement_unit_count=len(cands), independence_status="NOT_ESTABLISHED",
        independently_verified=False, independent_corroboration_established=False,
    )
    decision = SimpleNamespace(
        claim=CLAIM, assessed_at=AT,
        evidence_verdict=verdict, evidence_passage_ids=tuple(x.passage_id for x in cands),
        warnings=("PROVISIONAL_EVIDENCE_ONLY",), independence_status="NOT_ESTABLISHED",
        independently_verified=False, independent_corroboration_established=False,
    )
    for key, val in changes.items():
        target, attr = key.split("__", 1)
        setattr({"nli": nli, "agreement": agreement, "decision": decision}[target], attr, val)
    return nli, agreement, decision


class ValidationTests(TestCase):
    def test_valid_claim_normalized(self):
        self.assertEqual(_validate_request("  Hello world  ", 5, 10, .9, AT), "Hello world")

    def test_claim_too_short(self):
        with self.assertRaises(UnifiedVerificationError):
            _validate_request(" x ", 5, 10, .9, AT)

    def test_claim_too_long(self):
        with self.assertRaises(UnifiedVerificationError):
            _validate_request("x" * 2001, 5, 10, .9, AT)

    def test_invalid_claim_type(self):
        with self.assertRaises(UnifiedVerificationError):
            _validate_request(12, 5, 10, .9, AT)

    def test_reject_boolean_wiki_top_k(self):
        with self.assertRaises(UnifiedVerificationError):
            _validate_request(CLAIM, True, 10, .9, AT)

    def test_reject_external_top_k_below_two(self):
        with self.assertRaises(UnifiedVerificationError):
            _validate_request(CLAIM, 5, 1, .9, AT)

    def test_reject_invalid_threshold(self):
        for threshold in (float('nan'), float('inf'), True, 0.49, 1.1):
            with self.subTest(threshold=threshold), self.assertRaises(UnifiedVerificationError):
                _validate_request(CLAIM, 5, 10, threshold, AT)

    def test_reject_naive_time(self):
        with self.assertRaises(UnifiedVerificationError):
            _validate_request(CLAIM, 5, 10, .9, datetime(2026,10,20))

    def test_wiki_forged_corrob_flag(self):
        with self.assertRaises(ValueError):
            _snapshot_wikipedia(wiki(corroboration_status="ESTABLISHED"), CLAIM)

    def test_wiki_claim_mismatch(self):
        with self.assertRaises(ValueError):
            _snapshot_wikipedia(wiki(claim="different"), CLAIM)

    def test_wiki_inverted_counts(self):
        with self.assertRaises(ValueError):
            _snapshot_wikipedia(wiki(retrieved_count=1, assessed_count=3), CLAIM)

    def test_wiki_invalid_verdict(self):
        with self.assertRaises(ValueError):
            _snapshot_wikipedia(wiki(verdict="TRUE"), CLAIM)

    def test_wiki_snapshot(self):
        res = _snapshot_wikipedia(wiki(), CLAIM)
        self.assertEqual(res.supporting_pages, ("Paris",))
        self.assertEqual(res.evidence_verdict, "SUPPORTING_EVIDENCE")

    def test_external_passage_mismatch(self):
        c = candidates()
        n, a, d = reports(c, decision__evidence_passage_ids=(c[0].passage_id,))
        with self.assertRaises(ValueError):
            _snapshot_external(claim=CLAIM, at=AT, retrieved=c, nli=n, agreement=a, decision=d)

    def test_external_independence_flag_refused(self):
        c = candidates()
        n, a, d = reports(c, decision__independent_corroboration_established=True)
        with self.assertRaises(ValueError):
            _snapshot_external(claim=CLAIM, at=AT, retrieved=c, nli=n, agreement=a, decision=d)

    def test_external_upstream_independence_flag_refused(self):
        c = candidates()
        n, a, d = reports(c, nli__independently_verified=True)
        with self.assertRaises(ValueError):
            _snapshot_external(claim=CLAIM, at=AT, retrieved=c, nli=n, agreement=a, decision=d)

    def test_external_timestamp_mismatch(self):
        c = candidates()
        n, a, d = reports(c, agreement__assessed_at=AT+timedelta(seconds=1))
        with self.assertRaises(ValueError):
            _snapshot_external(claim=CLAIM, at=AT, retrieved=c, nli=n, agreement=a, decision=d)

    def test_external_invalid_url(self):
        c = candidates()
        n, a, d = reports(c)
        n.evidence[0].article_url = "http://internal.example/story"
        with self.assertRaises(ValueError):
            _snapshot_external(claim=CLAIM, at=AT, retrieved=c, nli=n, agreement=a, decision=d)

    def test_external_valid_snapshot_has_provenance(self):
        c = candidates()
        n, a, d = reports(c)
        result = _snapshot_external(claim=CLAIM, at=AT, retrieved=c, nli=n, agreement=a, decision=d)
        self.assertEqual(result.assessed_count, 2)
        self.assertEqual(result.provenance[0].article_url, "https://publisher0.example/story")
        self.assertFalse(result.independent_corroboration_established)
        self.assertIn("SOURCE_EDITORIAL_INDEPENDENCE_NOT_ESTABLISHED", result.warnings)


class OrchestratorTests(IsolatedAsyncioTestCase):
    async def run_flow(self, *, wiki_raw=None, ext_verdict="PROVISIONAL_SUPPORT", cands=None,
                       wiki_error=None, retrieve_error=None, nli_error=None):
        cands = candidates() if cands is None else cands
        n, a, d = reports(cands, verdict=ext_verdict) if len(cands) >= 2 else (None, None, None)
        calls = []
        def wiki_runner(claim, top_k):
            calls.append("wiki")
            if wiki_error:
                raise wiki_error
            return wiki_raw if wiki_raw is not None else wiki()
        async def retrieve(session, **kwargs):
            calls.append("retrieval")
            if retrieve_error:
                raise retrieve_error
            return cands
        async def assess(session, **kwargs):
            calls.append("nli")
            if nli_error:
                raise nli_error
            self.assertEqual(kwargs["claim"], CLAIM)
            return n
        def agree(**kwargs):
            calls.append("agreement")
            return a
        def decide(**kwargs):
            calls.append("decision")
            return d
        result = await orchestrate_unified_verification(
            object(), claim=CLAIM, assessed_at=AT,
            wikipedia_runner=wiki_runner, external_retriever=retrieve,
            external_nli_runner=assess, agreement_analyzer=agree, decision_engine=decide,
        )
        return result, calls

    async def test_aligned_support_sequential(self):
        result, calls = await self.run_flow()
        self.assertEqual(calls, ["wiki", "retrieval", "nli", "agreement", "decision"])
        self.assertEqual(result.relationship, "PROVISIONALLY_ALIGNED_SUPPORT")
        self.assertEqual(result.external.evidence_verdict, "PROVISIONAL_SUPPORT")

    async def test_aligned_refutation(self):
        result, _ = await self.run_flow(
            wiki_raw=wiki("REFUTING_EVIDENCE"), ext_verdict="PROVISIONAL_REFUTATION",
        )
        self.assertEqual(result.relationship, "PROVISIONALLY_ALIGNED_REFUTATION")

    async def test_opposing_stances(self):
        result, _ = await self.run_flow(ext_verdict="PROVISIONAL_REFUTATION")
        self.assertEqual(result.relationship, "OPPOSING_CORPUS_FINDINGS")

    async def test_conflicting_external(self):
        result, _ = await self.run_flow(ext_verdict="CONFLICTING_EVIDENCE")
        self.assertEqual(result.relationship, "CONFLICT_OR_REVIEW_REQUIRED")

    async def test_both_inconclusive(self):
        result, _ = await self.run_flow(
            wiki_raw=wiki("INSUFFICIENT_EVIDENCE"), ext_verdict="INSUFFICIENT_EVIDENCE",
        )
        self.assertEqual(result.relationship, "PARTIAL_OR_INCONCLUSIVE")

    async def test_no_stored_evidence(self):
        result, calls = await self.run_flow(cands=())
        self.assertEqual(calls, ["wiki", "retrieval"])
        self.assertEqual(result.external.status, "INSUFFICIENT_STORED_EVIDENCE")
        self.assertEqual(result.relationship, "WIKIPEDIA_ONLY")

    async def test_one_document_version_not_enough(self):
        result, calls = await self.run_flow(cands=candidates(same_version=True))
        self.assertEqual(calls, ["wiki", "retrieval"])
        self.assertEqual(result.external.status, "INSUFFICIENT_STORED_EVIDENCE")

    async def test_wiki_failure_external_survives(self):
        result, calls = await self.run_flow(wiki_error=RuntimeError("private log detail"))
        self.assertEqual(result.wikipedia.status, "UNAVAILABLE")
        self.assertEqual(result.external.status, "AVAILABLE")
        self.assertEqual(result.relationship, "EXTERNAL_ONLY")
        self.assertNotIn("private log detail", str(result))
        self.assertEqual(len(calls), 5)

    async def test_invalid_wiki_report_fails_closed(self):
        result, _ = await self.run_flow(wiki_raw=wiki(corroboration_status="ESTABLISHED"))
        self.assertEqual(result.wikipedia.status, "UNAVAILABLE")
        self.assertEqual(result.external.status, "AVAILABLE")

    async def test_external_retrieval_failure_wikipedia_survives(self):
        result, calls = await self.run_flow(retrieve_error=RuntimeError("secret SQL"))
        self.assertEqual(result.external.status, "UNAVAILABLE")
        self.assertEqual(result.relationship, "WIKIPEDIA_ONLY")
        self.assertNotIn("secret SQL", str(result))
        self.assertEqual(calls, ["wiki", "retrieval"])

    async def test_external_nli_failure_wikipedia_survives(self):
        result, calls = await self.run_flow(nli_error=RuntimeError("private claim"))
        self.assertEqual(result.external.status, "UNAVAILABLE")
        self.assertNotIn("private claim", str(result))
        self.assertEqual(calls, ["wiki", "retrieval", "nli"])

    async def test_no_database_still_wikipedia(self):
        report = await orchestrate_unified_verification(
            None, claim=CLAIM, assessed_at=AT, wikipedia_runner=lambda c, k: wiki(),
        )
        self.assertEqual(report.wikipedia.status, "AVAILABLE")
        self.assertEqual(report.external.status, "UNAVAILABLE")

    async def test_too_many_external_candidates_rejected(self):
        async def many(session, **kwargs):
            return candidates(11)
        result = await orchestrate_unified_verification(
            object(), claim=CLAIM, assessed_at=AT,
            wikipedia_runner=lambda c, k: wiki(), external_retriever=many,
            external_top_k=10,
        )
        self.assertEqual(result.external.status, "UNAVAILABLE")
        self.assertIn("EXTERNAL_RETRIEVAL_LIMIT_VIOLATION", result.external.warnings)

    async def test_report_immutable(self):
        result, _ = await self.run_flow()
        with self.assertRaises(FrozenInstanceError):
            result.independently_verified = True
        self.assertFalse(result.independently_verified)
        self.assertFalse(result.external.independent_corroboration_established)

    async def test_bad_parameters_do_not_run_services(self):
        calls = []
        with self.assertRaises(UnifiedVerificationError):
            await orchestrate_unified_verification(
                object(), claim="x", wikipedia_runner=lambda *_: calls.append("called"),
            )
        self.assertEqual(calls, [])

    async def test_cancellation_not_swallowed_in_external_leg(self):
        async def cancelled(session, **kwargs):
            raise asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await orchestrate_unified_verification(
                object(), claim=CLAIM, assessed_at=AT,
                wikipedia_runner=lambda c, k: wiki(), external_retriever=cancelled,
            )

    async def test_flags_remain_false(self):
        result, _ = await self.run_flow()
        self.assertFalse(result.independent_corroboration_established)
        self.assertFalse(result.independently_verified)
        self.assertEqual(result.independence_status, "NOT_ESTABLISHED")
        self.assertIn("NO_UNIFIED_FACTUAL_TRUTH_PROBABILITY", result.warnings)


if __name__ == "__main__":
    import unittest
    unittest.main()
