"""Actual private-store decision/replay tests over fictional evidence only."""
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
import json
import os
import unittest
from unittest.mock import patch
from uuid import uuid4

import test_phase5_trusted_reporting_review as fixtures
from apps.api.services import trusted_reporting_review as trusted
from apps.api.services.reviewed_corroboration import (
    decide_reviewed_corroboration, validate_reviewed_corroboration,
)
from apps.api.services.external_presentation_contract import validate_external_presentation


class ReviewedDecisionTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.TrustedReviewTests();self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.refs=self.fixture.ext.provenance;self.ids=self.fixture.ids

    def review(self, *, refs=None, ids=None, claim=fixtures.CLAIM):
        return trusted.resolve_pair_scopes(claim, refs or self.refs, ids or self.ids, store=self.fixture.root)

    def decide(self, *, review=None, refs=None, ids=None, claim=fixtures.CLAIM):
        value=review if review is not None else self.review(refs=refs,ids=ids,claim=claim)
        return decide_reviewed_corroboration(value,claim=claim,refs=refs or self.refs,
                                            candidate_count=len(ids or self.ids))

    def sign_pair(self, refs, pair, *, decision='REVIEWED_DISTINCT_REPORTING'):
        by_id={str(r.passage_id):r for r in refs}
        scope=trusted.make_scope(fixtures.CLAIM,by_id[pair[0]],by_id[pair[1]],pair[2])
        return trusted.sign_review(self.fixture.root,{'scope':scope,'decision':decision,
            'reason':'Documented synthetic source-origin review for this exact fixture claim and pair.',
            'checks':fixtures.checks()},self.fixture.key,confirm_distinct=True)

    def third_ref(self):
        ref=next(r for r in self.refs if r.decisive_evidence_admitted is True)
        return replace(ref,passage_id=uuid4(),document_version_id=uuid4(),parent_passage_id=uuid4(),
            fetch_observation_id=uuid4(),publisher_domain='zzthird.example.org',
            article_url='https://zzthird.example.org/fictional-report',dependency_risk_family=19,duplicate_group=19)

    def test_legacy_without_store_has_no_new_decision(self):
        with patch.dict(os.environ,{trusted.ENVIRONMENT_KEY:''}):
            self.assertIsNone(self.fixture.snapshot().reviewed_corroboration)
        self.assertIsNone(decide_reviewed_corroboration(None,claim=fixtures.CLAIM,refs=self.refs,candidate_count=0))

    def test_pending_review_cannot_establish_corroboration(self):
        result=self.decide();self.assertEqual(result.status,'NOT_ESTABLISHED')
        self.assertFalse(result.corroboration_established);self.assertEqual(result.supporting_pair_count,0)

    def test_inconclusive_review_cannot_establish_corroboration(self):
        trusted.sign_review(self.fixture.root,self.fixture.draft,self.fixture.key)
        self.assertFalse(self.decide().corroboration_established)

    def test_documented_dependency_cannot_establish_corroboration(self):
        self.sign_pair(self.refs,self.ids[0],decision='DEPENDENCY_DOCUMENTED')
        result=self.decide();self.assertFalse(result.corroboration_established)
        self.assertIn('DOCUMENTED_DEPENDENCY_REQUIRES_RESOLUTION',result.reason_codes)

    def test_authorized_distinct_reporting_and_support_establish_scoped_result(self):
        signed=self.fixture.approve();result=self.decide()
        self.assertEqual(result.status,'REVIEWED_SUPPORT');self.assertTrue(result.corroboration_established)
        self.assertEqual(result.supporting_pair_count,1)
        self.assertEqual(result.review_record_sha256s,(signed['record_sha256'],))
        self.assertEqual(len(result.evidence_passage_ids),2)

    def test_authorized_refutation_has_a_separate_direction(self):
        refs=tuple(replace(r,nli_label='CONTRADICTION') if r.decisive_evidence_admitted else r for r in self.refs)
        pair=(*self.ids[0][:2],'REFUTE_ONLY');self.sign_pair(refs,pair)
        result=self.decide(refs=refs,ids=(pair,))
        self.assertEqual(result.status,'REVIEWED_REFUTATION');self.assertTrue(result.corroboration_established)
        self.assertEqual(result.refuting_pair_count,1);self.assertEqual(result.supporting_pair_count,0)

    def test_admitted_counterevidence_blocks_one_sided_support(self):
        self.fixture.approve();other=replace(self.third_ref(),nli_label='CONTRADICTION')
        result=self.decide(refs=(*self.refs,other))
        self.assertEqual(result.status,'CONFLICTING_EVIDENCE');self.assertFalse(result.corroboration_established)

    def test_nonadmitted_neutral_reference_does_not_mint_a_countervote(self):
        self.fixture.approve();other=replace(self.third_ref(),nli_label='NEUTRAL',nli_threshold_passed=False,
                                           decisive_evidence_admitted=False)
        self.assertEqual(self.decide(refs=(*self.refs,other)).status,'REVIEWED_SUPPORT')

    def test_unavailable_record_blocks_a_positive_summary(self):
        self.fixture.approve();other=self.third_ref();refs=(*self.refs,other)
        left=self.ids[0][0];second=(left,str(other.passage_id),'SUPPORT_ONLY');ids=(*self.ids,second)
        by_id={str(r.passage_id):r for r in refs}
        scope=trusted.make_scope(fixtures.CLAIM,by_id[left],other,'SUPPORT_ONLY')
        (self.fixture.root/'records'/(trusted.digest(scope)+'.json')).write_text('invalid record')
        result=self.decide(refs=refs,ids=ids)
        self.assertFalse(result.corroboration_established)
        self.assertIn('CURRENT_ORIGIN_REVIEW_UNAVAILABLE',result.reason_codes)

    def test_dependency_on_another_candidate_blocks_promotion(self):
        self.fixture.approve();other=self.third_ref();refs=(*self.refs,other)
        second=(self.ids[0][0],str(other.passage_id),'SUPPORT_ONLY')
        self.sign_pair(refs,second,decision='DEPENDENCY_DOCUMENTED')
        self.assertFalse(self.decide(refs=refs,ids=(*self.ids,second)).corroboration_established)

    def test_revoked_record_invalidates_cached_positive_decision(self):
        signed=self.fixture.approve();review=self.review();value=self.decide(review=review)
        trusted.revoke_review(self.fixture.root,record_id=signed['record_id'])
        with self.assertRaises(ValueError):
            validate_reviewed_corroboration(value,review=review,claim=fixtures.CLAIM,refs=self.refs,candidate_count=1)
        self.assertFalse(self.decide().corroboration_established)

    def test_revoked_operator_cannot_continue_to_corroborate(self):
        self.fixture.approve();trusted.revoke_review(self.fixture.root,key_id=self.fixture.key)
        self.assertFalse(self.decide().corroboration_established)

    def test_expired_review_cannot_corroborate(self):
        draft=self.fixture.draft|{'decision':'REVIEWED_DISTINCT_REPORTING','checks':fixtures.checks()}
        trusted.sign_review(self.fixture.root,draft,self.fixture.key,confirm_distinct=True,
                            now=datetime.now(UTC)-timedelta(days=10))
        self.assertFalse(self.decide().corroboration_established)

    def test_new_claim_does_not_reuse_the_old_review(self):
        self.fixture.approve()
        result=self.decide(claim='Quinn Harper has joined Northstar Club.')
        self.assertFalse(result.corroboration_established)

    def test_changed_snapshot_cannot_reuse_review(self):
        self.fixture.approve();refs=tuple(replace(r,snapshot_sha256='c'*64) for r in self.refs)
        self.assertFalse(self.decide(refs=refs).corroboration_established)

    def test_shared_dependency_group_is_never_counted_as_two_origins(self):
        self.fixture.approve();family=self.refs[0].dependency_risk_family
        refs=tuple(replace(r,dependency_risk_family=family) for r in self.refs)
        with self.assertRaises(ValueError):self.decide(refs=refs)

    def test_admission_threshold_and_scope_are_still_mandatory(self):
        self.fixture.approve()
        for change in ({'decisive_evidence_admitted':False},{'nli_threshold_passed':False},
                       {'scope_exclusion_codes':('NAMED_SUBJECT_MISMATCH',)}):
            refs=tuple(replace(r,**change) for r in self.refs)
            with self.subTest(change=change),self.assertRaises(ValueError):self.decide(refs=refs)

    def test_forged_decision_fields_rejected_at_presentation(self):
        self.fixture.approve();ext=self.fixture.snapshot()
        for change in ({'status':'NOT_ESTABLISHED'},{'corroboration_established':False},
                       {'supporting_pair_count':True},{'claim_sha256':'b'*64},
                       {'review_record_sha256s':('d'*64,)},{'policy_version':'unreviewed-policy'}):
            value=replace(ext.reviewed_corroboration,**change)
            with self.subTest(change=change),self.assertRaises(ValueError):
                validate_external_presentation(replace(ext,reviewed_corroboration=value),claim=fixtures.CLAIM)

    def test_decision_requires_the_current_trusted_summary(self):
        self.fixture.approve();ext=self.fixture.snapshot()
        with self.assertRaises(ValueError):
            validate_external_presentation(replace(ext,trusted_origin_review=None),claim=fixtures.CLAIM)

    def test_fresh_validation_accepts_the_actual_server_decision(self):
        self.fixture.approve();validate_external_presentation(self.fixture.snapshot(),claim=fixtures.CLAIM)

    def test_actual_article_serialization_preserves_scope_and_factual_limits(self):
        self.fixture.approve();report=self.fixture.public_report()
        data=json.loads(json.dumps(asdict(report),default=str));claim=data['claims'][0]
        self.assertEqual(claim['external_reviewed_corroboration']['status'],'REVIEWED_SUPPORT')
        self.assertFalse(claim['independent_corroboration_established'])
        self.assertFalse(data['independent_corroboration_established']);self.assertFalse(data['independently_verified'])
        self.assertIsNone(data['overall_article_truth_verdict']);self.assertIsNone(data['overall_article_truth_probability'])
        public=json.dumps(claim['external_reviewed_corroboration'])
        for private in ('secret_hex','mac_sha256',self.fixture.key,'fixture.operator'):
            self.assertNotIn(private,public)
