"""Real local MAC/store/replay tests over fictional evidence; no live news/model IO."""
import asyncio
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from uuid import uuid4

from apps.api.services import trusted_reporting_review as trusted
from apps.api.services.unified_verification import _snapshot_external
from apps.api.services.external_corroboration_decision import decide_external_corroboration
from apps.api.services.article_multi_claim_verification import verify_article_claims, MultiClaimPolicy, _validate_unified_report
from apps.api.services.article_level_reporting import build_article_level_report, ArticleReportingError
from apps.api.services.pasted_article_preparation import prepare_pasted_article
from test_phase3_article_provenance import unified
from test_phase3_captured_origin_review import run as original_reports
from test_phase3_paragraph_inputs import candidate, CLAIM, NOW

ROOT=Path(__file__).resolve().parents[2]


def checks():
    return {key:{'explanation':'Synthetic operator-reviewed fixture evidence for this checklist section.',
                 'references':[{'url':'https://audit.example.org/'+key,'sha256':'a'*64}]}
            for key in trusted.CHECKS}


class TrustedReviewTests(unittest.TestCase):
    def setUp(self):
        self.directory=TemporaryDirectory(prefix='origin-review-tests-')
        self.root=Path(self.directory.name)/'private'
        self.key=trusted.init_store(self.root,'fixture.operator')
        self.env=patch.dict(os.environ,{trusted.ENVIRONMENT_KEY:str(self.root)})
        self.env.start()
        self.nli,self.agreement,self.review,self.captured=original_reports()
        self.ext=self.snapshot()
        self.pair=self.ext.trusted_origin_review.pairs[0]
        self.ids=((self.pair.left_passage_id,self.pair.right_passage_id,self.pair.stance),)
        by_id={str(r.passage_id):r for r in self.ext.provenance}
        self.scope=trusted.make_scope(CLAIM,by_id[self.pair.left_passage_id],by_id[self.pair.right_passage_id],self.pair.stance)
        self.file=self.root/'records'/(trusted.digest(self.scope)+'.json')
        self.draft={'scope':self.scope,'decision':'INCONCLUSIVE',
                    'reason':'The saved fixture source origins remain inconclusive after operator review.','checks':{}}

    def tearDown(self):
        self.env.stop();self.directory.cleanup()

    def snapshot(self):
        decision=decide_external_corroboration(nli_report=self.nli,agreement_report=self.agreement,
            independence_review=self.review,reporting_origin_audit=self.captured.origin_audit)
        return _snapshot_external(claim=CLAIM,at=NOW,nli=self.nli,agreement=self.agreement,decision=decision,
            retrieved=tuple(candidate(p) for p in self.nli.paragraph_selection.parents),
            independence_review=self.review,reporting_origin_audit=self.captured.origin_audit)

    def approve(self):
        draft=self.draft|{'decision':'REVIEWED_DISTINCT_REPORTING','checks':checks()}
        return trusted.sign_review(self.root,draft,self.key,confirm_distinct=True)

    def resolve(self,refs=None,claim=CLAIM,now=None):
        return trusted.resolve_pair_scopes(claim,refs or self.ext.provenance,self.ids,store=self.root,now=now)

    def test_unconfigured_store_preserves_legacy_report(self):
        with patch.dict(os.environ,{trusted.ENVIRONMENT_KEY:''}):self.assertIsNone(self.snapshot().trusted_origin_review)

    def test_empty_store_exposes_pending_exact_pair(self):
        self.assertEqual(self.ext.trusted_origin_review.status,'PENDING')
        self.assertEqual(self.ext.trusted_origin_review.candidate_pair_count,1)
        self.assertEqual(self.pair.scope_sha256,trusted.digest(self.scope))

    def test_signed_inconclusive_record_is_not_positive(self):
        trusted.sign_review(self.root,self.draft,self.key)
        value=self.snapshot().trusted_origin_review
        self.assertEqual(value.status,'INCONCLUSIVE');self.assertEqual(value.distinct_reporting_pair_count,0)

    def test_distinct_review_requires_explicit_operator_confirmation(self):
        with self.assertRaises(trusted.TrustedReviewError):
            trusted.sign_review(self.root,self.draft|{'decision':'REVIEWED_DISTINCT_REPORTING','checks':checks()},self.key)
        self.assertFalse(self.file.exists())

    def test_distinct_review_requires_all_evidence_sections(self):
        for key in trusted.CHECKS:
            value=checks();value.pop(key)
            with self.subTest(key=key),self.assertRaises(trusted.TrustedReviewError):
                trusted.sign_review(self.root,self.draft|{'decision':'REVIEWED_DISTINCT_REPORTING','checks':value},
                                    self.key,confirm_distinct=True)

    def test_valid_authenticated_assessment_does_not_mint_truth(self):
        self.approve();ext=self.snapshot()
        self.assertEqual(ext.trusted_origin_review.status,'REVIEWED_DISTINCT_REPORTING')
        self.assertFalse(ext.independent_corroboration_established)
        self.assertEqual(ext.independence_status,'NOT_ESTABLISHED')
        self.assertIs(_validate_unified_report(unified(ext),claim=CLAIM,at=NOW).external,ext)

    def test_documented_dependency_requires_a_reference(self):
        with self.assertRaises(trusted.TrustedReviewError):
            trusted.sign_review(self.root,self.draft|{'decision':'DEPENDENCY_DOCUMENTED'},self.key)
        trusted.sign_review(self.root,self.draft|{'decision':'DEPENDENCY_DOCUMENTED',
            'checks':{'syndication_and_wire':checks()['syndication_and_wire']}},self.key)
        self.assertEqual(self.resolve().status,'DEPENDENCY_DOCUMENTED')

    def test_tampered_signed_record_is_unavailable(self):
        self.approve();data=trusted.read_private(self.file);data['payload']['reason']='Attacker replaced the authenticated review reason.'
        self.file.write_text(json.dumps(data));self.assertEqual(self.resolve().status,'REVIEW_UNAVAILABLE')

    def test_wrong_private_key_cannot_authenticate_record(self):
        self.approve();data=trusted.registry(self.root);data['reviewers'][self.key]['secret_hex']='b'*64
        trusted.atomic_private(self.root/'trust.json',data);self.assertEqual(self.resolve().status,'REVIEW_UNAVAILABLE')

    def test_unknown_key_cannot_approve(self):
        self.approve();data=trusted.read_private(self.file);data['payload']['key_id']='untrusted-key'
        self.file.write_text(json.dumps(data));self.assertEqual(self.resolve().status,'REVIEW_UNAVAILABLE')

    def test_revoked_reviewer_invalidates_record(self):
        self.approve();trusted.revoke_review(self.root,key_id=self.key)
        self.assertEqual(self.resolve().status,'REVIEW_UNAVAILABLE')

    def test_revoked_record_cannot_be_replayed(self):
        result=self.approve();trusted.revoke_review(self.root,record_id=result['record_id'])
        self.assertEqual(self.resolve().status,'REVIEW_UNAVAILABLE')

    def test_expired_review_cannot_be_used(self):
        self.approve();self.assertEqual(self.resolve(now=datetime.now(UTC)+timedelta(days=8)).status,'REVIEW_UNAVAILABLE')

    def test_future_record_cannot_be_used_early(self):
        trusted.sign_review(self.root,self.draft,self.key,now=datetime.now(UTC)+timedelta(minutes=10))
        self.assertEqual(self.resolve().status,'REVIEW_UNAVAILABLE')

    def test_excessive_validity_refused(self):
        with self.assertRaises(trusted.TrustedReviewError):trusted.sign_review(self.root,self.draft,self.key,valid_days=31)

    def test_changed_claim_cannot_reuse_approval(self):
        self.approve();self.assertEqual(self.resolve(claim='Quinn Harper has not resigned from Northstar Club.').status,'PENDING')

    def test_changed_capture_or_derived_identity_cannot_reuse_approval(self):
        self.approve()
        changes=({'input_sha256':'b'*64},{'snapshot_sha256':'c'*64},{'fetch_observation_id':uuid4()},
                 {'document_version_id':uuid4()},{'parent_passage_id':uuid4()},
                 {'input_start_offset':self.ext.provenance[0].input_start_offset+1},
                 {'article_url':self.ext.provenance[0].article_url+'/changed'})
        for update in changes:
            with self.subTest(update=update):
                refs=(replace(self.ext.provenance[0],**update),)+self.ext.provenance[1:]
                self.assertEqual(self.resolve(refs=refs).status,'PENDING')

    def test_neutral_or_nonadmitted_evidence_cannot_be_reviewed(self):
        for update in ({'nli_label':'NEUTRAL'},{'nli_threshold_passed':False},{'decisive_evidence_admitted':False},
                       {'scope_exclusion_codes':('SCOPE_REVIEW_REQUIRED',)}):
            with self.subTest(update=update),self.assertRaises(trusted.TrustedReviewError):
                self.resolve(refs=(replace(self.ext.provenance[0],**update),)+self.ext.provenance[1:])

    def test_same_risk_or_duplicate_family_cannot_mint_review_pair(self):
        for key in ('dependency_risk_family','duplicate_group'):
            refs=(replace(self.ext.provenance[0],**{key:getattr(self.ext.provenance[1],key)}),)+self.ext.provenance[1:]
            with self.subTest(key=key),self.assertRaises(trusted.TrustedReviewError):self.resolve(refs=refs)

    def test_bad_documentation_urls_or_hashes_are_rejected(self):
        for change in ({'url':'http://audit.example.org/x'},{'url':'https://localhost/x'},
                       {'url':'https://127.0.0.1/x'},{'url':'https://user:password@audit.example.org/x'},
                       {'sha256':'invalid'}):
            value=checks();value['left_original_reporting']['references'][0].update(change)
            with self.subTest(change=change),self.assertRaises(trusted.TrustedReviewError):
                trusted.sign_review(self.root,self.draft|{'decision':'REVIEWED_DISTINCT_REPORTING','checks':value},
                                    self.key,confirm_distinct=True)

    def test_private_record_has_no_public_identity_notes_or_mac(self):
        self.approve();public=json.dumps(asdict(self.snapshot().trusted_origin_review))
        secret=trusted.registry(self.root)['reviewers'][self.key]['secret_hex']
        for private in ('fixture.operator',self.key,secret,'mac_sha256','checks','reason'):
            self.assertNotIn(private,public)

    def test_forged_summary_counts_and_receipts_rejected(self):
        self.approve();value=self.snapshot().trusted_origin_review
        for change in ({'distinct_reporting_pair_count':0},{'candidate_pair_count':True},
                       {'status':'PENDING'},{'pairs':(replace(value.pairs[0],record_sha256='d'*64),)}):
            with self.subTest(change=change),self.assertRaises(trusted.TrustedReviewError):
                trusted.validate_trusted_origin_review(replace(value,**change),claim=CLAIM,
                    refs=self.ext.provenance,candidate_count=1)

    def test_revocation_is_rechecked_before_article_presentation(self):
        result=self.approve();ext=self.snapshot();trusted.revoke_review(self.root,record_id=result['record_id'])
        with self.assertRaises(ValueError):_validate_unified_report(unified(ext),claim=CLAIM,at=NOW)

    def test_superseded_approval_cannot_be_resurrected(self):
        self.approve();old=self.file.read_bytes()
        trusted.sign_review(self.root,self.draft,self.key)
        self.assertEqual(self.resolve().status,'INCONCLUSIVE')
        self.file.write_bytes(old);self.assertEqual(self.resolve().status,'REVIEW_UNAVAILABLE')

    def test_reinitialization_cannot_replace_existing_key(self):
        old=(self.root/'trust.json').read_bytes()
        with self.assertRaises(trusted.TrustedReviewError):trusted.init_store(self.root,'another.operator')
        self.assertEqual((self.root/'trust.json').read_bytes(),old)

    def test_second_operator_writer_is_refused(self):
        with trusted.locked_store(self.root):
            with self.assertRaises(trusted.TrustedReviewError):trusted.sign_review(self.root,self.draft,self.key)

    def test_invalid_registry_fails_closed_without_exposing_text(self):
        for text in ('private malformed content', '{"reviewers":{},"reviewers":{}}',
                     '{"reviewers":NaN}', ' ' * 1_048_577):
            with self.subTest(input_length=len(text)):
                (self.root/'trust.json').write_text(text)
                value=self.resolve();self.assertEqual(value.status,'REVIEW_UNAVAILABLE')
                self.assertNotIn('private malformed content',str(asdict(value)))

    def test_symlink_record_is_refused(self):
        self.approve();alternate=self.root/'alternate.json';self.file.replace(alternate)
        try:self.file.symlink_to(alternate)
        except OSError:self.skipTest('Symlink creation is unavailable for this Windows account')
        self.assertEqual(self.resolve().status,'REVIEW_UNAVAILABLE')

    def test_wrong_pair_identity_cannot_be_resolved(self):
        with self.assertRaises(trusted.TrustedReviewError):
            trusted.resolve_pair_scopes(CLAIM,self.ext.provenance,((str(uuid4()),self.ids[0][1],self.ids[0][2]),),store=self.root)

    def public_report(self,ext=None):
        ext=ext if ext is not None else self.snapshot()
        prepared=prepare_pasted_article(pasted_text=CLAIM+'\nThis background paragraph explains this synthetic fixture without adding independent evidence.')
        async def runner(session,*,claim,assessed_at,**kwargs):return unified(ext,claim=claim,at=assessed_at)
        multi=asyncio.run(verify_article_claims(None,prepared=prepared,assessed_at=NOW,
                      policy=MultiClaimPolicy(max_verifications=1),unified_runner=runner))
        return build_article_level_report(prepared=prepared,verification=multi)

    def test_authenticated_review_survives_multiclaim_and_public_serialization(self):
        self.approve();result=self.public_report();raw=json.loads(json.dumps(asdict(result),default=str))
        claim=next(c for c in raw['claims'] if c['execution_status']=='ASSESSED')
        self.assertEqual(claim['external_trusted_origin_review']['status'],'REVIEWED_DISTINCT_REPORTING')
        self.assertFalse(raw['independent_corroboration_established']);self.assertIsNone(raw['overall_article_truth_probability'])
        self.assertNotIn('secret_hex',json.dumps(raw));self.assertNotIn('mac_sha256',json.dumps(raw))

    def test_cli_template_sign_and_revoke_roundtrip(self):
        report=Path(self.directory.name)/'report.json';draft=Path(self.directory.name)/'draft.json'
        report.write_text(json.dumps(asdict(self.public_report()),default=str))
        cli=ROOT/'tools/reporting_origin_review.py'
        for args in (['template','--report',str(report),'--out',str(draft)],
                     ['sign','--store',str(self.root),'--draft',str(draft),'--key-id',self.key]):
            result=subprocess.run([sys.executable,'-B',str(cli),*args],cwd=ROOT,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertNotIn('secret_hex',result.stdout)
        self.assertEqual(self.resolve().status,'INCONCLUSIVE')
        record=trusted.read_private(self.file)['payload']['record_id']
        result=subprocess.run([sys.executable,'-B',str(cli),'revoke','--store',str(self.root),'--record-id',record],
                              cwd=ROOT,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertEqual(self.resolve().status,'REVIEW_UNAVAILABLE')

    def test_cli_refuses_private_store_inside_project(self):
        cli=ROOT/'tools/reporting_origin_review.py'
        result=subprocess.run([sys.executable,'-B',str(cli),'init','--store',str(ROOT/'artifacts/forbidden-key-store'),
            '--reviewer-label','fixture.operator'],cwd=ROOT,capture_output=True,text=True)
        self.assertEqual(result.returncode,1);self.assertIn('outside_git_project',result.stdout)
        self.assertFalse((ROOT/'artifacts/forbidden-key-store').exists())

    def multi_paragraph_case(self):
        from test_phase3_captured_origin_review import make_report
        from test_phase3_paragraph_inputs import parent, A, B
        nli = make_report((parent(text=A+'\n'+
            'Quinn Harper has resigned from Northstar Club after a separate interview about future plans.'),
            parent(2, text=B)))
        self.nli, self.agreement, self.review, self.captured = original_reports(nli)
        ext = self.snapshot()
        self.assertEqual(len(ext.provenance), 3)
        self.assertEqual(ext.provisional_agreement_units, 2)
        self.assertEqual(ext.trusted_origin_review.candidate_pair_count, 2)
        pair = ext.trusted_origin_review.pairs[0]
        by_id = {str(r.passage_id): r for r in ext.provenance}
        scope = trusted.make_scope(CLAIM, by_id[pair.left_passage_id],
                                   by_id[pair.right_passage_id], pair.stance)
        signed = trusted.sign_review(self.root, {'scope':scope, 'decision':'REVIEWED_DISTINCT_REPORTING',
            'reason':'Synthetic distinct observation origins for this exact evidence-pair fixture.',
            'checks':checks()}, self.key, confirm_distinct=True)
        return signed

    def test_multiple_paragraph_pairs_preserve_pending_scope_and_public_result(self):
        self.multi_paragraph_case()
        raw = asdict(self.public_report())
        claim = next(c for c in raw['claims'] if c['execution_status']=='ASSESSED')
        review = claim['external_trusted_origin_review']
        self.assertEqual((review['candidate_pair_count'],review['distinct_reporting_pair_count'],
                          review['pending_pair_count']), (2,1,1))
        decision = claim['external_reviewed_corroboration']
        self.assertEqual(decision['status'],'REVIEWED_SUPPORT')
        self.assertEqual(decision['supporting_pair_count'],1)
        self.assertFalse(raw['independent_corroboration_established'])
        self.assertIsNone(raw['overall_article_truth_verdict'])

    def test_revoked_pair_blocks_result_even_with_another_pending_pair(self):
        signed = self.multi_paragraph_case()
        trusted.revoke_review(self.root,record_id=signed['record_id'])
        ext = self.snapshot()
        self.assertEqual(ext.trusted_origin_review.status,'REVIEW_UNAVAILABLE')
        self.assertEqual(ext.trusted_origin_review.pending_pair_count,1)
        self.assertEqual(ext.reviewed_corroboration.status,'NOT_ESTABLISHED')
        self.assertFalse(ext.reviewed_corroboration.corroboration_established)


if __name__=='__main__':unittest.main()
