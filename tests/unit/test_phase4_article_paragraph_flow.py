"""Offline routing/guard tests. Fixtures replace IO and predictions, not live results."""
from dataclasses import asdict, replace
from types import SimpleNamespace as NS, ModuleType
import sys
import unittest
from unittest.mock import AsyncMock, patch

from apps.api.services import unified_verification as unified
from apps.api.services import article_multi_claim_verification as multi
from apps.api.services import external_paragraph_nli as paragraphs
from apps.api.services.article_api_workflow import verify_pasted_article
from apps.api.services.pasted_article_preparation import prepare_pasted_article
from apps.api.services.external_evidence_nli import ExternalNliError
from test_phase3_paragraph_inputs import (
    make_report, parent, candidate, audit, dependencies, Predictor, CLAIM, NOW, A, B,
)


def wikipedia(claim=CLAIM):
    return NS(claim=claim, verdict="INSUFFICIENT_EVIDENCE", retrieved_count=0,
              assessed_count=0, supporting_pages=[], refuting_pages=[],
              corroboration_status="NOT_ESTABLISHED_SINGLE_CORPUS")


class ModeTests(unittest.IsolatedAsyncioTestCase):
    async def flow(self, *, mode="DERIVED_PARAGRAPH", nli=None, candidates=None, error=None):
        nli = make_report() if nli is None else nli
        candidates = (tuple(candidate(p) for p in nli.paragraph_selection.parents)
                      if candidates is None else candidates)
        retrieve = AsyncMock(return_value=candidates)
        assess = AsyncMock(return_value=nli, side_effect=error)
        with patch.object(paragraphs, "assess_external_paragraph_nli", assess):
            report = await unified.orchestrate_unified_verification(
                object(), claim=CLAIM, assessed_at=NOW, external_top_k=4,
                external_input_mode=mode, wikipedia_runner=lambda c, k: wikipedia(c),
                external_retriever=retrieve,
            )
        return report, assess, retrieve

    async def test_paragraph_mode_uses_real_agreement_decision_and_unreviewed_audit(self):
        result, assess, _ = await self.flow()
        self.assertEqual(result.external.status, "AVAILABLE")
        self.assertEqual(result.external.evidence_input_kind, "DERIVED_PARAGRAPH")
        self.assertEqual(result.external.evidence_verdict, "PROVISIONAL_SUPPORT")
        self.assertEqual(result.external.origin_audit.unreviewed_pair_count, 1)
        self.assertEqual(result.external.origin_audit.observations_count, 0)
        self.assertEqual(assess.await_args.kwargs["max_inputs"], 4)
        self.assertFalse(result.independent_corroboration_established)

    async def test_no_evidence_does_not_load_paragraph_model(self):
        result, assess, _ = await self.flow(candidates=())
        self.assertEqual(result.external.status, "INSUFFICIENT_STORED_EVIDENCE")
        assess.assert_not_awaited()

    async def test_one_snapshot_does_not_load_model(self):
        candidates = (candidate(parent()), candidate(parent(2, document_version_id=parent().document_version_id)))
        result, assess, _ = await self.flow(candidates=candidates)
        self.assertEqual(result.external.status, "INSUFFICIENT_STORED_EVIDENCE")
        assess.assert_not_awaited()

    async def test_token_budget_failure_never_falls_back_to_raw_passages(self):
        from apps.api.services import external_evidence_nli
        raw = AsyncMock()
        with patch.object(external_evidence_nli, "assess_external_evidence_nli", raw):
            result, _, _ = await self.flow(error=ExternalNliError("private diagnostic"))
        raw.assert_not_awaited()
        self.assertEqual(result.wikipedia.status, "AVAILABLE")
        self.assertEqual(result.external.status, "UNAVAILABLE")
        self.assertNotIn("private diagnostic", str(result))

    async def test_derived_mode_rejects_report_without_paragraph_binding(self):
        result, _, _ = await self.flow(nli=replace(make_report(), paragraph_selection=None),
            candidates=(candidate(parent()), candidate(parent(2))))
        self.assertEqual(result.external.status, "UNAVAILABLE")

    async def test_paragraph_count_above_policy_cannot_escape_through_injected_runner(self):
        nli = make_report((parent(text=A+"\n"+B+"\n"+A), parent(2, text=B+"\n"+A)))
        self.assertGreater(len(nli.evidence), 4)
        result, _, _ = await self.flow(nli=nli)
        self.assertEqual(result.external.status, "UNAVAILABLE")

    async def test_invalid_mode_rejected_before_wikipedia_or_sql(self):
        for value in (None, True, [], {}, "paragraph", "DERIVED_PARAGRAPH "):
            called = []
            with self.subTest(value=value), self.assertRaises(unified.UnifiedVerificationError):
                await unified.orchestrate_unified_verification(None, claim=CLAIM,
                    external_input_mode=value, wikipedia_runner=lambda *args: called.append(args))
            self.assertEqual(called, [])

    async def test_default_mode_keeps_legacy_runner_arguments(self):
        from apps.api.services import external_evidence_nli
        assess = AsyncMock(side_effect=ExternalNliError("fixture stop"))
        with patch.object(external_evidence_nli, "assess_external_evidence_nli", assess):
            await unified.orchestrate_unified_verification(object(), claim=CLAIM,
                wikipedia_runner=lambda c,k: wikipedia(c),
                external_retriever=AsyncMock(return_value=(candidate(parent()),candidate(parent(2)))))
        self.assertNotIn("max_inputs", assess.await_args.kwargs)


class WorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_preview_adapter_to_orchestrator_to_public_report(self):
        nli=make_report()
        retrieve=AsyncMock(return_value=tuple(candidate(p) for p in nli.paragraph_selection.parents))
        assess=AsyncMock()
        async def model_result(session, **kwargs):
            await assess(session, **kwargs)
            return replace(nli, assessed_at=kwargs["assessed_at"])
        async def call_orchestrator(session, **kwargs):
            return await unified.orchestrate_unified_verification(session, **kwargs,
                wikipedia_runner=lambda c,k: wikipedia(c), external_retriever=retrieve)
        with patch.object(multi,"orchestrate_unified_verification",side_effect=call_orchestrator), \
                patch.object(paragraphs,"assess_external_paragraph_nli",side_effect=model_result):
            report=await verify_pasted_article(object(),text=CLAIM+"\n"+
                "This background paragraph explains the scope of this check without adding independent evidence.")
        claim=report.claims[0]
        self.assertEqual(claim.execution_status,"ASSESSED")
        self.assertEqual(claim.external_input_kind,"DERIVED_PARAGRAPH")
        self.assertEqual(claim.external_origin_audit.unreviewed_pair_count,1)
        self.assertEqual(claim.external_origin_audit.observations_count,0)
        self.assertEqual(len(claim.external_references),2)
        self.assertTrue(all(r.parent_passage_id and r.input_sha256 and r.fetch_observation_id
                            for r in claim.external_references))
        self.assertFalse(report.independent_corroboration_established)
        self.assertIsNone(report.overall_article_truth_verdict)
        self.assertIsNone(report.overall_article_truth_probability)
        self.assertEqual(retrieve.await_args.kwargs["top_k"],5)

    async def test_policy_rejects_public_style_or_boolean_mode(self):
        for value in (True,None,[],"auto","DERIVED_PARAGRAPH "):
            with self.subTest(value=value),self.assertRaises(ValueError):
                multi.MultiClaimPolicy(external_input_mode=value)

    async def test_default_multi_claim_runner_remains_backward_compatible(self):
        seen=[]
        async def fixture(session, *,claim,assessed_at,wikipedia_top_k,external_top_k,nli_threshold):
            seen.append(claim)
            raise ValueError("fixture")
        prepared=prepare_pasted_article(pasted_text=CLAIM+" "+"A background sentence. "*5)
        await multi.verify_article_claims(None,prepared=prepared,
            policy=multi.MultiClaimPolicy(max_verifications=1),unified_runner=fixture)
        self.assertEqual(seen,[CLAIM])


class BudgetTests(unittest.IsolatedAsyncioTestCase):
    async def invoke(self, parents, *, budget=4, predictor=None):
        provenance=ModuleType("apps.api.services.external_evidence_provenance")
        provenance.audit_external_passage_provenance=AsyncMock(return_value=tuple(audit(p) for p in parents))
        risk=ModuleType("apps.api.services.external_source_independence")
        risk.audit_external_source_dependencies=AsyncMock(return_value=dependencies(parents))
        with patch.dict(sys.modules,{provenance.__name__:provenance,risk.__name__:risk}):
            return await paragraphs.assess_external_paragraph_nli(object(),claim=CLAIM,
                candidates=tuple(candidate(p) for p in parents),assessed_at=NOW,
                predictor=predictor or Predictor(),max_inputs=budget)

    async def test_exact_budget_keeps_both_versions(self):
        nli=await self.invoke((parent(text=A+"\n"+B),parent(2,text=B+"\n"+A)))
        self.assertEqual(len(nli.evidence),4)
        self.assertEqual(len({r.document_version_id for r in nli.evidence}),2)

    async def test_over_budget_stops_before_tokenization_prediction_and_model_load(self):
        p=Predictor()
        with patch.object(paragraphs,"_predict_checked") as predict:
            with self.assertRaisesRegex(ExternalNliError,"paragraph_input_budget_exceeded"):
                await self.invoke((parent(text=A+"\n"+B+"\n"+A),parent(2,text=B+"\n"+A)),predictor=p)
        predict.assert_not_called()
        self.assertEqual(p.calls,[])

    async def test_invalid_budget_stops_before_audit(self):
        for value in (True,None,1,21,"4",4.0):
            with self.subTest(value=value),self.assertRaisesRegex(ExternalNliError,"invalid_paragraph_input_budget"):
                await self.invoke((parent(),parent(2)),budget=value)

    async def test_tokens_over_model_budget_still_rejected(self):
        p=Predictor(length=257)
        with self.assertRaisesRegex(ExternalNliError,"paragraph_input_would_be_truncated"):
            await self.invoke((parent(),parent(2)),predictor=p)
        self.assertEqual(p.calls,[])
