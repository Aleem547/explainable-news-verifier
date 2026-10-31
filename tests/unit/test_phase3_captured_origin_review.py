"""Captured-origin review is bound to actual paragraph inputs, never proof."""
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json
import unittest
from uuid import uuid4

from apps.api.services.external_reporting_capture_review import (
    CapturedOriginReviewError, PageOriginContext, bind_source_capture,
    capture_page_origin, review_captured_reporting_origins,
)
from apps.api.services.external_reporting_origin_audit import summarize_reporting_origin_audit
from apps.api.services.external_corroboration_decision import decide_external_corroboration
from apps.api.services.unified_verification import _snapshot_external
from test_phase3_paragraph_inputs import make_report as base_report, prepare, candidate, parent, driver_parent, NOW, CLAIM


DEFAULT_HTML=b'<article><p><a href="/authors/a-reporter">A Reporter</a> reports for a newsroom.</p></article>'


def make_report(parents=None, claim=CLAIM, html=DEFAULT_HTML):
    parents=parents or (parent(),parent(2))
    return base_report(tuple(replace(p,fetch_html_sha256=sha256(html).hexdigest()) for p in parents),claim=claim)


def page(p, *, html=None, genre="NEWS_REPORT", author="A Reporter"):
    html = html or b'<article><p><a href="/authors/a-reporter">A Reporter</a> reports for a newsroom.</p></article>'
    return capture_page_origin(article_url=p.original_url, text=p.passage_text+" "*100,
        html_body=html, expected_html_sha256=sha256(html).hexdigest(), reported_author=author,
        reviewed_author="A Reporter", reviewed_genre=genre)


def captures(nli, **updates):
    result=[]
    for p in nli.paragraph_selection.parents:
        # Fixture parent snapshot is its short text; use a valid, independently
        # captured longer page and then bind only the source text digest here.
        raw=page(p,**updates)
        result.append(bind_source_capture(p,replace(raw,text_sha256=p.snapshot_sha256)))
    return tuple(result)


def run(nli=None, supplied=None, at=NOW):
    nli=nli or make_report();agreement,review,_,_=prepare(nli)
    result=review_captured_reporting_origins(nli_report=nli,agreement_report=agreement,
        independence_review=review,captures=supplied if supplied is not None else captures(nli),reviewed_at=at)
    return nli,agreement,review,result


class OriginReviewTests(unittest.TestCase):
    def test_pair_is_reviewed_but_unknown_and_not_certified(self):
        nli,agreement,review,result=run()
        summary=summarize_reporting_origin_audit(nli_report=nli,agreement_report=agreement,
            independence_review=review,audit=result.origin_audit)
        self.assertEqual(summary.candidate_pair_count,1)
        self.assertEqual(summary.observations_count,2)
        self.assertEqual(summary.unreviewed_pair_count,0)
        self.assertEqual(summary.unverified_origin_pair_count,1)
        self.assertEqual(summary.dependency_indicated_pair_count,0)
        self.assertFalse(result.independent_corroboration_established)
        self.assertFalse(result.independently_verified)

    def test_unknown_origin_survives_real_decision_and_unified_snapshot(self):
        nli,agreement,review,result=run()
        decision=decide_external_corroboration(nli_report=nli,agreement_report=agreement,
            independence_review=review,reporting_origin_audit=result.origin_audit)
        snapshot=_snapshot_external(claim=CLAIM,at=NOW,nli=nli,agreement=agreement,decision=decision,
            retrieved=tuple(candidate(p) for p in nli.paragraph_selection.parents),
            independence_review=review,reporting_origin_audit=result.origin_audit)
        self.assertEqual(snapshot.origin_audit.unverified_origin_pair_count,1)
        self.assertEqual(snapshot.origin_audit.unreviewed_pair_count,0)
        self.assertFalse(snapshot.independent_corroboration_established)
        self.assertEqual(str(decision.evidence_verdict),"PROVISIONAL_SUPPORT")

    def test_captures_and_observations_bind_actual_context_ids(self):
        nli,_,review,result=run()
        pair=review.review_candidates[0]
        hashes={c.binding_sha256 for c in captures(nli)}
        for note in result.origin_audit.observations:
            self.assertEqual((note.left_passage_id,note.right_passage_id),(pair.left_passage_id,pair.right_passage_id))
            self.assertIn(note.reference_sha256,hashes)
            self.assertEqual(note.indicator,"REPORTING_ORIGIN_UNKNOWN")

    def test_missing_source_capture_fails_closed(self):
        nli=make_report()
        with self.assertRaises(CapturedOriginReviewError):run(nli,captures(nli)[:1])

    def test_duplicate_or_foreign_source_capture_rejected(self):
        nli=make_report();a,b=captures(nli)
        for other in (a,replace(b,document_version_id=uuid4())):
            with self.subTest(other=other),self.assertRaises(CapturedOriginReviewError):run(nli,(a,other))

    def test_source_fetch_and_document_identity_tampering_rejected(self):
        nli=make_report();a,b=captures(nli)
        for changes in ({"source_id":uuid4()},{"document_id":uuid4()},{"fetch_observation_id":uuid4()},
                        {"retrieved_at":NOW-timedelta(seconds=1)},{"fetch_observed_at":NOW-timedelta(seconds=1)}):
            with self.subTest(changes=changes),self.assertRaises(CapturedOriginReviewError):run(nli,(replace(a,**changes),b))

    def test_page_snapshot_and_url_tampering_rejected(self):
        nli=make_report();a,b=captures(nli)
        for changes in ({"text_sha256":"a"*64},{"html_sha256":"b"*64},{"article_url":"https://other.example.org/a"}):
            with self.subTest(changes=changes),self.assertRaises(CapturedOriginReviewError):
                run(nli,(replace(a,page=replace(a.page,**changes)),b))

    def test_missing_stored_html_hash_cannot_bind_current_page(self):
        nli=base_report()
        with self.assertRaises(CapturedOriginReviewError):captures(nli)

    def test_changed_html_with_same_text_changes_review_fingerprints(self):
        a=make_report()
        html=DEFAULT_HTML+b'<footer>New unrelated footer.</footer>'
        b=make_report(html=html)
        self.assertNotEqual(a.paragraph_selection.selection_sha256,b.paragraph_selection.selection_sha256)
        self.assertNotEqual(run(a)[3].review_packet_sha256,
                            run(b,captures(b,html=html))[3].review_packet_sha256)

    def test_unsupported_capture_policy_rejected(self):
        nli=make_report();a,b=captures(nli)
        with self.assertRaises(CapturedOriginReviewError):run(nli,(replace(a,page=replace(a.page,policy_version="fake")),b))

    def test_context_cannot_claim_authenticated_origin(self):
        nli=make_report();a,b=captures(nli);d=json.loads(a.page.context_json);d["origin_authenticated"]=True
        bad=replace(a.page,context_json=json.dumps(d,sort_keys=True,ensure_ascii=False,separators=(",",":")))
        with self.assertRaises(CapturedOriginReviewError):run(nli,(replace(a,page=bad),b))

    def test_unrelated_probe_has_no_origin_notes(self):
        _,_,_,result=run(make_report(claim="Mount Etna is a volcano in Sicily."))
        self.assertEqual(result.origin_audit.observations_count,0)
        self.assertEqual(result.origin_audit.pairs,())

    def test_analysis_genre_and_missing_extracted_author_are_explicit(self):
        nli=make_report();_,_,_,result=run(nli,captures(nli,genre="ANALYSIS_ARTICLE",author=None))
        for item in result.source_diagnostics:
            self.assertIn("GENRE_REQUIRES_ORIGINAL_REPORTING_REVIEW",item.reason_codes)
            self.assertIn("EXTRACTED_AUTHOR_MISSING_DOES_NOT_MEAN_NO_BYLINE",item.reason_codes)
            self.assertIn("PUBLISHER_BYLINE_PROFILE_IS_NOT_ORIGIN_PROOF",item.reason_codes)

    def test_capture_order_does_not_change_result(self):
        nli=make_report();a=captures(nli)
        self.assertEqual(run(nli,a)[3],run(nli,a[::-1])[3])

    def test_uuid_subclass_parent_remains_supported(self):
        nli=make_report((driver_parent(parent()),driver_parent(parent(2))))
        self.assertEqual(run(nli)[3].origin_audit.observations_count,2)

    def test_future_naive_or_earlier_review_time_rejected(self):
        for at in (NOW-timedelta(seconds=1),NOW.replace(tzinfo=None),datetime.now(UTC)+timedelta(days=1)):
            with self.subTest(at=at),self.assertRaises(CapturedOriginReviewError):run(at=at)

    def test_record_is_immutable(self):
        result=run()[3]
        with self.assertRaises(AttributeError):result.independently_verified=True


class CaptureParserTests(unittest.TestCase):
    def parse(self,html,**updates):return page(parent(),html=html.encode(),**updates)

    def test_capture_checks_raw_html_hash(self):
        with self.assertRaises(CapturedOriginReviewError):
            capture_page_origin(article_url=parent().original_url,text="x"*100,html_body=b'<article/>',
                expected_html_sha256="0"*64,reported_author=None,reviewed_author="A",reviewed_genre="UNKNOWN")

    def test_page_capture_preserves_missing_author_and_hashes(self):
        p=self.parse('<article><a href="/authors/a-reporter">A Reporter</a></article>',author=None)
        self.assertIsNone(p.reported_author)
        self.assertTrue(json.loads(p.context_json)["matching_byline_profile_lead_observed"])
        self.assertEqual(len(p.capture_sha256),64)

    def test_body_reference_keeps_context_separate_from_byline_and_caption(self):
        p=self.parse('<article><p>The FBI investigation <a href="https://apnews.com/a">AP</a> continues.</p>'
                     '<figure><figcaption><a href="https://apnews.com/photo">AP photo</a></figcaption></figure></article>')
        leads=json.loads(p.context_json)["reference_leads"]
        self.assertEqual({x["role"] for x in leads},{"BODY_REFERENCE_LEAD","FIGURE_OR_CAPTION"})
        self.assertTrue(any("FBI" in x["context_excerpt"] for x in leads))

    def test_hidden_or_script_author_is_not_a_visible_byline_lead(self):
        for tag in ('<script>','<div hidden>','<div aria-hidden="true">','<template>'):
            end='</'+tag[1:].split()[0].split('>')[0]+'>'
            p=self.parse('<article>'+tag+'<a href="/authors/a-reporter">A Reporter</a>'+end+'</article>')
            self.assertFalse(json.loads(p.context_json)["matching_byline_profile_lead_observed"])

    def test_page_without_article_boundary_requires_scan_review(self):
        html=b'<p>No article wrapper.</p>';nli=make_report(html=html);_,_,_,result=run(nli,captures(nli,html=html))
        self.assertTrue(all("REFERENCE_SCAN_INCOMPLETE" in s.reason_codes for s in result.source_diagnostics))

    def test_absence_of_links_never_creates_independence_or_dependency(self):
        html=b'<article><p>No links.</p></article>';nli=make_report(html=html);_,_,_,result=run(nli,captures(nli,html=html))
        self.assertEqual(result.origin_audit.dependency_indicated_pairs,0)
        self.assertFalse(result.independent_corroboration_established)

    def test_too_many_exported_leads_is_visible_as_incomplete(self):
        html='<article>'+''.join('<p><a href="https://other.example.org/'+str(i)+'">Reference</a></p>' for i in range(20))+'</article>'
        nli=make_report(html=html.encode());_,_,_,result=run(nli,captures(nli,html=html.encode()))
        self.assertTrue(all("REFERENCE_SCAN_INCOMPLETE" in s.reason_codes for s in result.source_diagnostics))

    def test_unsafe_reference_links_are_not_collected(self):
        for url in ('http://other.example.org/a','https://127.0.0.1/a','https://user:pass@other.example.org/a'):
            p=self.parse('<article><a href="'+url+'">AP</a></article>')
            self.assertEqual(json.loads(p.context_json)["reference_leads"],[])


if __name__=="__main__":unittest.main()
