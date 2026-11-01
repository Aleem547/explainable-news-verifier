"""Bounded recall regressions with explicit offline audits; no real IO/inference."""
from dataclasses import replace
from types import ModuleType
import sys
import unittest
from unittest.mock import AsyncMock, patch

from ml.verification.paragraph_inputs import (
    ParagraphInputError, choose_audited_paragraph_candidates, selection_from_audits,
)
from apps.api.services.external_paragraph_retrieval import retrieve_external_paragraph_parents
from test_phase3_paragraph_inputs import parent, audit, digest, CLAIM, A, B, uid


def family(base,texts,ranks):
    parts=['\n'+text+'\n' for text in texts]
    snapshot=''.join(parts);offset=0;rows=[]
    for index,(part,rank) in enumerate(zip(parts,ranks,strict=True)):
        p=parent(base+index,text=part,document_id=uid(1000+base),
            document_version_id=uid(2000+base),source_id=uid(3000+base),
            publisher_name=f'Publisher {base}',publisher_domain=f'news{base}.example.org',
            original_url=f'https://news{base}.example.org/story',
            fetch_observation_id=uid(4000+base),start_offset=offset,end_offset=offset+len(part),
            snapshot_sha256=digest(snapshot),snapshot_text_length=len(snapshot))
        item=audit(p);item.candidate.rank=rank
        rows.append(item);offset+=len(part)
    return tuple(rows)


def diagnostic_case():
    # The top four contain two snapshots, but the second snapshot's first
    # complete usable context is ranked fifth. No particular publisher/claim
    # is built into the production policy.
    return family(1,(A,B,'Mount Etna is a volcano in Sicily.'),(1,2,3))+family(
        10,('An unrelated background sentence.',B),(4,5))


class SelectionTests(unittest.TestCase):
    def test_reproduces_previous_top_four_coverage_failure(self):
        with self.assertRaisesRegex(ParagraphInputError,'paragraphs_do_not_cover_all_audited_versions'):
            selection_from_audits(diagnostic_case()[:4],CLAIM)

    def test_lower_ranked_usable_second_snapshot_is_retrieved(self):
        audits=diagnostic_case();selected=choose_audited_paragraph_candidates(audits,CLAIM)
        self.assertIn(audits[4].candidate,selected)
        self.assertNotIn(audits[3].candidate,selected)
        self.assertEqual(len({p.document_version_id for p in selected}),2)
        selected_ids={p.passage_id for p in selected}
        replay=selection_from_audits(tuple(a for a in audits if a.candidate.passage_id in selected_ids),CLAIM)
        self.assertLessEqual(len(replay.inputs),4)

    def test_returns_exact_original_candidate_objects(self):
        audits=diagnostic_case();selected=choose_audited_paragraph_candidates(audits,CLAIM)
        self.assertTrue(all(any(p is a.candidate for a in audits) for p in selected))

    def test_ranking_order_is_preserved_after_pair_selection(self):
        selected=choose_audited_paragraph_candidates(diagnostic_case()[::-1],CLAIM)
        self.assertEqual([p.rank for p in selected],sorted(p.rank for p in selected))

    def test_extra_contexts_are_never_trimmed_to_fit(self):
        audits=family(1,(A+'\n'+B+'\n'+A+'\n'+B,),(1,))+family(10,(B,),(2,))
        self.assertEqual(choose_audited_paragraph_candidates(audits,CLAIM,max_inputs=4),())

    def test_feasible_lower_ranked_parent_is_used_when_first_is_too_expensive(self):
        audits=family(1,(A+'\n'+B+'\n'+A+'\n'+B,A),(1,3))+family(10,(B,),(2,))
        selected=choose_audited_paragraph_candidates(audits,CLAIM)
        self.assertEqual([p.rank for p in selected],[2,3])

    def test_two_parent_limit_still_covers_two_snapshots(self):
        selected=choose_audited_paragraph_candidates(diagnostic_case(),CLAIM,max_parents=2)
        self.assertEqual(len(selected),2)
        self.assertEqual(len({p.document_version_id for p in selected}),2)

    def test_one_usable_snapshot_abstains(self):
        audits=family(1,(A,B),(1,2))+family(10,('Unrelated background.',),(3,))
        self.assertEqual(choose_audited_paragraph_candidates(audits,CLAIM),())

    def test_all_unused_audits_are_validated(self):
        audits=diagnostic_case();audits[-1].candidate.passage_sha256='0'*64
        with self.assertRaises(ParagraphInputError):choose_audited_paragraph_candidates(audits,CLAIM)

    def test_corrupt_unselected_background_parent_is_not_ignored(self):
        audits=diagnostic_case();audits[3].candidate.passage_sha256='0'*64
        with self.assertRaises(ParagraphInputError):choose_audited_paragraph_candidates(audits,CLAIM)

    def test_assessed_candidate_flag_rejected(self):
        audits=diagnostic_case();audits[3].candidate.nli_evaluated=True
        with self.assertRaises(ParagraphInputError):choose_audited_paragraph_candidates(audits,CLAIM)

    def test_invalid_policy_budgets_rejected(self):
        for value in (True,None,1,21,'4',4.0):
            for key in ('max_inputs','max_parents'):
                with self.subTest(value=value,key=key),self.assertRaises(ParagraphInputError):
                    choose_audited_paragraph_candidates(diagnostic_case(),CLAIM,**{key:value})

    def test_missing_or_invalid_rank_rejected(self):
        for value in (True,None,0,'1',1.0):
            audits=diagnostic_case();audits[3].candidate.rank=value
            with self.subTest(value=value),self.assertRaises(ParagraphInputError):
                choose_audited_paragraph_candidates(audits,CLAIM)

    def test_duplicate_parent_identity_rejected(self):
        audits=diagnostic_case()
        with self.assertRaisesRegex(ParagraphInputError,'duplicate_parent_passage'):
            choose_audited_paragraph_candidates(audits+(audits[0],),CLAIM)

    def test_each_selected_parent_retains_its_entire_eligible_input_set(self):
        audits=family(1,(A+'\n'+B,),(1,))+family(10,(B+'\n'+A,),(2,))
        selected=choose_audited_paragraph_candidates(audits,CLAIM)
        self.assertEqual(len(selected),2)
        self.assertEqual(len(selection_from_audits(audits,CLAIM).inputs),4)


class RetrievalTests(unittest.IsolatedAsyncioTestCase):
    async def invoke(self, *, audits=None, count=None, **kwargs):
        audits=diagnostic_case() if audits is None else audits
        pool=tuple(a.candidate for a in audits)
        if count is not None:pool=pool[:count]
        retrieval=ModuleType('apps.api.services.external_passage_retrieval')
        retrieval.retrieve_external_passages=AsyncMock(return_value=pool)
        provenance=ModuleType('apps.api.services.external_evidence_provenance')
        provenance.audit_external_passage_provenance=AsyncMock(return_value=audits)
        with patch.dict(sys.modules,{retrieval.__name__:retrieval,provenance.__name__:provenance}):
            result=await retrieve_external_paragraph_parents(self,claim=CLAIM,**kwargs)
        return result,retrieval.retrieve_external_passages,provenance.audit_external_passage_provenance

    async def test_queries_bounded_pool_then_audits_all_candidates(self):
        result,fetch,check=await self.invoke()
        self.assertEqual(fetch.await_args.kwargs,{'claim':CLAIM,'top_k':20,'candidate_limit':60})
        self.assertIs(fetch.await_args.args[0],self)
        self.assertEqual(len(check.await_args.args[1]),5)
        self.assertEqual([p.rank for p in result],[1,2,5])

    async def test_too_small_pool_does_not_start_audit_or_inference(self):
        for count in (0,1):
            result,_,check=await self.invoke(count=count)
            self.assertEqual(result,())
            check.assert_not_awaited()

    async def test_audit_order_or_identity_mismatch_fails_closed(self):
        from apps.api.services import external_paragraph_retrieval as service
        audits=diagnostic_case();pool=tuple(a.candidate for a in audits)
        retrieval=ModuleType('apps.api.services.external_passage_retrieval')
        retrieval.retrieve_external_passages=AsyncMock(return_value=pool)
        provenance=ModuleType('apps.api.services.external_evidence_provenance')
        provenance.audit_external_passage_provenance=AsyncMock(return_value=audits[::-1])
        with patch.dict(sys.modules,{retrieval.__name__:retrieval,provenance.__name__:provenance}), \
                self.assertRaisesRegex(ParagraphInputError,'paragraph_retrieval_audit_binding_mismatch'):
            await service.retrieve_external_paragraph_parents(self,claim=CLAIM)

    async def test_invalid_retrieval_limits_rejected_before_io(self):
        for changes in ({'top_k':True},{'top_k':1},{'top_k':21},{'candidate_limit':19},
                        {'candidate_limit':101},{'candidate_limit':60.0}):
            with self.subTest(changes=changes),self.assertRaises(ParagraphInputError):await self.invoke(**changes)

    async def test_default_derived_orchestration_uses_new_retriever(self):
        from apps.api.services import external_paragraph_retrieval as service
        from apps.api.services.unified_verification import orchestrate_unified_verification
        from test_phase4_article_paragraph_flow import wikipedia
        retrieve=AsyncMock(return_value=())
        with patch.object(service,'retrieve_external_paragraph_parents',retrieve):
            result=await orchestrate_unified_verification(None,claim=CLAIM,
                external_input_mode='DERIVED_PARAGRAPH',wikipedia_runner=lambda c,k:wikipedia(c))
            retrieve.assert_not_awaited()
            result=await orchestrate_unified_verification(object(),claim=CLAIM,
                external_input_mode='DERIVED_PARAGRAPH',wikipedia_runner=lambda c,k:wikipedia(c))
        retrieve.assert_awaited_once()
        self.assertEqual(result.external.status,'INSUFFICIENT_STORED_EVIDENCE')
        self.assertIn('TWO_COMPLETE_AUDITED_ARTICLE_INPUTS_REQUIRED',result.external.warnings)


class FiveInputLandingRetrievalTests(unittest.TestCase):
    def rows(self):
        two='Chandrayaan-3 landed on the Moon.\nChandrayaan-3 collected mission data.'
        three='LRO imaged Chandrayaan-3 on the Moon.\nChandrayaan-3 touched down on the Moon.\nChandrayaan-3 images were released.'
        return family(1,(two,),(2,))+family(10,(three,),(1,))

    def test_complete_three_plus_two_pair_requires_five_input_cap(self):
        claim='Chandrayaan-3 landed on the Moon.'
        rows=self.rows()
        self.assertEqual(choose_audited_paragraph_candidates(rows,claim,max_inputs=4),())
        selected=choose_audited_paragraph_candidates(rows,claim,max_inputs=5,max_parents=5)
        self.assertEqual(len(selected),2)
        self.assertEqual({r.passage_id for r in selected},{r.candidate.passage_id for r in rows})
        selection=selection_from_audits(rows,claim)
        self.assertEqual(len(selection.inputs),5)
        self.assertTrue(all(p.parent.passage_text[p.start_offset-p.parent.start_offset:p.end_offset-p.parent.start_offset]==p.text
                            for p in selection.inputs))

    def test_larger_budget_does_not_admit_a_sibling_mission(self):
        self.assertEqual(choose_audited_paragraph_candidates(self.rows(),
            'Chandrayaan-2 landed on the Moon.',max_inputs=5,max_parents=5),())
