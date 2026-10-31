"""Article presentation must retain guarded paragraph provenance and origin counts."""
import asyncio
from dataclasses import asdict,replace
from datetime import UTC,datetime
from uuid import uuid4
import json
import unittest

from apps.api.services.external_corroboration_decision import decide_external_corroboration
from apps.api.services.external_presentation_contract import validate_external_presentation
from apps.api.services.unified_verification import UnifiedVerificationReport, WikipediaFinding, _snapshot_external, _relationship
from apps.api.services.article_multi_claim_verification import _validate_unified_report, verify_article_claims, MultiClaimPolicy
from apps.api.services.article_level_reporting import build_article_level_report, ArticleReportingError
from apps.api.services.pasted_article_preparation import prepare_pasted_article
from test_phase3_captured_origin_review import run as origin_review
from test_phase3_paragraph_inputs import candidate,CLAIM,NOW


def finding():
    nli,agreement,review,captured=origin_review()
    audit=captured.origin_audit
    decision=decide_external_corroboration(nli_report=nli,agreement_report=agreement,
        independence_review=review,reporting_origin_audit=audit)
    return _snapshot_external(claim=CLAIM,at=NOW,nli=nli,agreement=agreement,decision=decision,
        retrieved=tuple(candidate(p) for p in nli.paragraph_selection.parents),
        independence_review=review,reporting_origin_audit=audit)


def unified(ext,claim=CLAIM,at=NOW):
    wiki=WikipediaFinding('UNAVAILABLE',None,0,0,(),(),('WIKIPEDIA_NOT_RUN_IN_OFFLINE_REPLAY',))
    return UnifiedVerificationReport(claim,at,wiki,ext,_relationship(wiki,ext),('NO_INDEPENDENT_CORROBORATION_CLAIM',))


class PresentationTests(unittest.TestCase):
    def setUp(self):self.ext=finding()
    def reject_ref(self,**changes):
        ref=replace(self.ext.provenance[0],**changes)
        ext=replace(self.ext,provenance=(ref,)+self.ext.provenance[1:])
        with self.assertRaises(ValueError):_validate_unified_report(unified(ext),claim=CLAIM,at=NOW)
    def test_valid_derived_metadata_passes(self):
        self.assertEqual(_validate_unified_report(unified(self.ext),claim=CLAIM,at=NOW).external,self.ext)
    def test_context_cannot_lose_parent_id(self):self.reject_ref(parent_passage_id=None)
    def test_context_cannot_pose_as_its_parent(self):self.reject_ref(parent_passage_id=self.ext.provenance[0].passage_id)
    def test_context_cannot_lose_text_hash(self):self.reject_ref(input_sha256=None)
    def test_invalid_text_hash_rejected(self):self.reject_ref(input_sha256='wrong')
    def test_context_cannot_lose_snapshot_hash(self):self.reject_ref(snapshot_sha256=None)
    def test_context_cannot_lose_fetch_observation(self):self.reject_ref(fetch_observation_id=None)
    def test_invalid_offset_range_rejected(self):self.reject_ref(input_start_offset=100,input_end_offset=1)
    def test_boolean_offset_rejected(self):self.reject_ref(input_start_offset=True)
    def test_missing_admission_result_rejected(self):self.reject_ref(decisive_evidence_admitted=None)
    def test_below_threshold_cannot_be_admitted(self):self.reject_ref(nli_threshold_passed=False,decisive_evidence_admitted=True)
    def test_neutral_relation_cannot_be_admitted(self):self.reject_ref(nli_label='NEUTRAL',decisive_evidence_admitted=True)
    def test_derived_kind_cannot_be_dropped(self):self.reject_ref(input_kind='STORED_PASSAGE')
    def test_derived_parent_count_required(self):
        with self.assertRaises(ValueError):validate_external_presentation(replace(self.ext,audited_parent_count=None))
    def test_origin_summary_required_for_derived_inputs(self):
        with self.assertRaises(ValueError):validate_external_presentation(replace(self.ext,origin_audit=None))
    def test_impossible_origin_counts_rejected(self):
        for change in ({'unverified_origin_pair_count':2},{'unreviewed_pair_count':True},{'observations_count':0},
                       {'review_packet_sha256':'wrong'},{'policy_version':'other'}):
            with self.subTest(change=change),self.assertRaises(ValueError):
                validate_external_presentation(replace(self.ext,origin_audit=replace(self.ext.origin_audit,**change)))
    def test_unknown_and_duplicate_exclusion_ids_rejected(self):
        for ids in ((uuid4(),),(self.ext.provenance[0].passage_id,)*2):
            with self.assertRaises(ValueError):validate_external_presentation(replace(self.ext,subject_excluded_decisive_passage_ids=ids))
    def test_subject_exclusion_cannot_keep_a_decisive_vote(self):
        with self.assertRaises(ValueError):validate_external_presentation(replace(self.ext,subject_excluded_decisive_passage_ids=(self.ext.provenance[0].passage_id,)))
    def test_scope_exclusion_codes_must_match_global_record(self):self.reject_ref(scope_exclusion_codes=('SCOPE_REVIEW_REQUIRED',))
    def test_unknown_mode_cannot_pass_presentation(self):
        with self.assertRaises(ValueError):validate_external_presentation(replace(self.ext,evidence_input_kind='PROVEN_INDEPENDENT'))
    def test_legacy_refs_remain_compatible(self):
        from test_phase13e6_article_reporting import _unified
        result=_unified(CLAIM,NOW,external='PROVISIONAL_SUPPORT')
        self.assertIs(_validate_unified_report(result,claim=CLAIM,at=NOW),result)
    def test_legacy_refs_cannot_hide_derived_metadata(self):
        from test_phase13e6_article_reporting import _unified
        ext=_unified(CLAIM,NOW,external='PROVISIONAL_SUPPORT').external
        refs=(replace(ext.provenance[0],parent_passage_id=uuid4()),)+ext.provenance[1:]
        with self.assertRaises(ValueError):validate_external_presentation(replace(ext,provenance=refs))


class ArticlePipelineTests(unittest.TestCase):
    def setUp(self):
        self.ext=finding()
        self.text=CLAIM+'\nThis background paragraph explains the scope of this local replay without adding independent evidence.'
        self.prepared=prepare_pasted_article(pasted_text=self.text)
    def pipeline(self,ext=None):
        async def runner(session,*,claim,assessed_at,**kwargs):
            self.assertEqual(claim,CLAIM)
            return unified(self.ext if ext is None else ext,claim=claim,at=assessed_at)
        return asyncio.run(verify_article_claims(None,prepared=self.prepared,
            policy=MultiClaimPolicy(max_verifications=1),unified_runner=runner))
    def render(self):return build_article_level_report(prepared=self.prepared,verification=self.pipeline())
    def test_guarded_metadata_survives_multiclaim_and_article_reporting(self):
        result=self.render();claim=next(c for c in result.claims if c.execution_status=='ASSESSED')
        self.assertEqual(claim.external_input_kind,'DERIVED_PARAGRAPH')
        self.assertEqual(claim.external_audited_parent_count,2)
        self.assertEqual(claim.external_origin_audit,self.ext.origin_audit)
        for actual,original in zip(claim.external_references,self.ext.provenance):
            for key in ['input_kind','parent_passage_id','input_sha256','input_start_offset','input_end_offset',
                        'snapshot_sha256','fetch_observation_id','decisive_evidence_admitted','scope_exclusion_codes']:
                self.assertEqual(getattr(actual,key),getattr(original,key),key)
    def test_json_serialization_keeps_metadata_and_false_independence(self):
        raw=json.loads(json.dumps(asdict(self.render()),default=str))
        self.assertFalse(raw['independent_corroboration_established'])
        claim=next(c for c in raw['claims'] if c['execution_status']=='ASSESSED')
        self.assertEqual(claim['external_origin_audit']['unverified_origin_pair_count'],1)
        self.assertTrue(all(r['parent_passage_id'] and r['input_sha256'] for r in claim['external_references']))
        self.assertIsNone(raw['overall_article_truth_probability'])
    def test_invalid_derived_metadata_fails_claim_without_leaking_details(self):
        bad=replace(self.ext,provenance=(replace(self.ext.provenance[0],input_sha256='private-sensitive-value'),)+self.ext.provenance[1:])
        result=self.pipeline(bad)
        self.assertEqual(result.failed_count,1)
        self.assertNotIn('private-sensitive-value',str(asdict(result)))
    def test_renderer_revalidates_modified_provenance(self):
        result=self.pipeline();items=list(result.claims);index=next(i for i,c in enumerate(items) if c.status=='ASSESSED')
        old=items[index];badext=replace(old.report.external,origin_audit=None)
        items[index]=replace(old,report=replace(old.report,external=badext))
        with self.assertRaises(ArticleReportingError):
            build_article_level_report(prepared=self.prepared,verification=replace(result,claims=tuple(items)))
    def test_output_never_exposes_origin_observer_identity(self):
        raw=json.dumps(asdict(self.render()),default=str)
        self.assertNotIn('observer_label',raw)
        self.assertNotIn('context_json',raw)
        self.assertNotIn('server.captured-origin-review',raw)

if __name__=='__main__':unittest.main()
