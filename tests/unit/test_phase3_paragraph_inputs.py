"""Derived-input provenance, admission and orchestration contracts; no real IO."""
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import sys
from types import ModuleType, SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, patch
from uuid import UUID

from ml.verification.paragraph_inputs import (
    ParentPassageBinding, ParagraphInputError, ParagraphInput, AuditedParagraphInput,
    _select, selection_from_audits, validate_parent, validate_paragraph_input,
    validate_paragraph_selection,
)
from apps.api.services.external_evidence_nli import (
    ExternalNliError, build_external_nli_report, validate_nli_input_bindings,
)
from apps.api.services.external_evidence_normalization import normalize_and_group_external_evidence
from apps.api.services.external_evidence_agreement import analyze_external_evidence_agreement
from apps.api.services.external_independence_review import build_external_independence_review
from apps.api.services.external_reporting_origin_audit import assess_reporting_origin_dependencies
from apps.api.services.external_corroboration_decision import decide_external_corroboration
from apps.api.services.unified_verification import _snapshot_external
from apps.api.services.external_paragraph_nli import assess_external_paragraph_nli, _predict_checked

NOW = datetime(2026, 10, 28, tzinfo=UTC)
CLAIM = "Quinn Harper has resigned from Northstar Club."
A = "Quinn Harper has resigned from Northstar Club."
B = "Northstar Club confirmed the resignation of Quinn Harper on Monday."


def uid(number): return UUID(int=number)
def digest(text): return sha256(text.encode()).hexdigest()


def parent(number=1, text=None, **updates):
    text = text or (A if number == 1 else B)
    value = ParentPassageBinding(
        uid(number), uid(100+number), uid(200+number), uid(300+number),
        f"Publisher {number}", f"source{number}.example.org",
        f"https://source{number}.example.org/a", NOW, text, digest(text),
        0, len(text), digest(text), len(text), 1, uid(400+number), NOW, .7,
    )
    return replace(value, **updates)


def candidate(p):
    keys = ("passage_id", "document_id", "document_version_id", "source_id",
            "publisher_name", "publisher_domain", "original_url", "retrieved_at",
            "passage_text", "passage_sha256", "lexical_relevance_score")
    return NS(**{k: getattr(p, k) for k in keys}, independently_verified=False,
              independent_corroboration_established=False, nli_evaluated=False)


def audit(p):
    return NS(candidate=candidate(p), traceable=True, nli_evaluated=False,
              independently_verified=False, independent_corroboration_established=False,
              passage_start_offset=p.start_offset, passage_end_offset=p.end_offset,
              snapshot_sha256=p.snapshot_sha256, snapshot_text_length=p.snapshot_text_length,
              snapshot_version_number=p.snapshot_version_number,
              fetch_observation_id=p.fetch_observation_id, fetch_observed_at=p.fetch_observed_at)


def dependencies(parents):
    versions = tuple(sorted({p.document_version_id for p in parents}, key=str))
    return NS(risk_families=tuple((v,) for v in versions), version_ids=versions,
              independence_status="NOT_ESTABLISHED", independently_verified=False,
              independent_corroboration_established=False, warnings=())


def make_report(parents=None, claim=CLAIM):
    selection = _select(parents or (parent(), parent(2)), CLAIM)
    return build_external_nli_report(
        claim=claim, assessed_at=NOW, paragraph_selection=selection,
        audits=tuple(AuditedParagraphInput(p) for p in selection.inputs),
        normalization=normalize_and_group_external_evidence(list(selection.inputs)),
        dependencies=dependencies(selection.parents),
        predictions=[NS(entailment=.96, contradiction=.02, neutral=.02) for _ in selection.inputs],
        input_pair_tokens=[32]*len(selection.inputs), model_max_length=256,
    )


def prepare(nli):
    agreement = analyze_external_evidence_agreement(nli_report=nli)
    review = build_external_independence_review(nli_report=nli, agreement_report=agreement)
    origin = assess_reporting_origin_dependencies(
        nli_report=nli, agreement_report=agreement, independence_review=review)
    decision = decide_external_corroboration(nli_report=nli, agreement_report=agreement,
                                            independence_review=review, reporting_origin_audit=origin)
    return agreement, review, origin, decision


class BindingTests(unittest.TestCase):
    def test_new_id_keeps_parent_id_explicit(self):
        s = _select((parent(), parent(2)), CLAIM)
        self.assertEqual({p.parent.passage_id for p in s.inputs}, {uid(1), uid(2)})
        self.assertTrue(all(p.context_id != p.parent.passage_id for p in s.inputs))
        self.assertTrue(all(p.passage_id == p.context_id for p in s.inputs))

    def test_parent_order_does_not_change_selection_or_hash(self):
        p = (parent(), parent(2))
        self.assertEqual(_select(p, CLAIM), _select(p[::-1], CLAIM))
        self.assertEqual(_select(p, CLAIM).selection_sha256, _select(p[::-1], CLAIM).selection_sha256)

    def test_unicode_offsets_count_source_characters(self):
        text = "Édition.\n  Quinn Harper has resigned from Northstar Club.  \n"
        s = _select((parent(text=text), parent(2)), CLAIM)
        p = next(p for p in s.inputs if p.parent.passage_id == uid(1))
        self.assertEqual(text[p.start_offset:p.end_offset], p.text)
        self.assertEqual(p.start_offset, 11)
        self.assertEqual(p.sha256, digest(p.text))

    def test_two_contexts_from_one_parent_keep_distinct_ids(self):
        s = _select((parent(text=A+"\n"+B), parent(2)), CLAIM)
        rows = [p for p in s.inputs if p.parent.passage_id == uid(1)]
        self.assertEqual(len(rows), 2)
        self.assertNotEqual(rows[0].context_id, rows[1].context_id)

    def test_unrelated_context_is_recorded_as_exclusion(self):
        s = _select((parent(text="Mount Etna is in Sicily.\n"+A), parent(2)), CLAIM)
        self.assertTrue(any("SUBJECT_UNGROUNDED_PARAGRAPH" in x[3] for x in s.exclusions))
        self.assertNotIn("Mount Etna is in Sicily.", [p.text for p in s.inputs])

    def test_unknown_boundary_fragment_is_excluded(self):
        text = A+"\n"+B+"\n"+A
        s = _select((parent(text=text, start_offset=10, end_offset=10+len(text),
                            snapshot_text_length=len(text)+20), parent(2)), CLAIM)
        rows = [p for p in s.inputs if p.parent.passage_id == uid(1)]
        self.assertEqual([p.text for p in rows], [B])
        self.assertEqual(len([x for x in s.exclusions if x[0] == uid(1)]), 2)

    def test_missing_subject_in_one_version_fails_closed(self):
        with self.assertRaises(ParagraphInputError):
            _select((parent(text=A+"\n"+B), parent(2, text="Mount Etna is in Sicily.")), CLAIM)

    def test_same_version_pair_is_rejected(self):
        with self.assertRaises(ParagraphInputError):
            _select((parent(), parent(2, document_version_id=uid(201))), CLAIM)

    def test_duplicate_parent_id_rejected(self):
        with self.assertRaises(ParagraphInputError):
            _select((parent(), parent()), CLAIM)

    def test_input_count_bound_is_enforced(self):
        with self.assertRaises(ParagraphInputError):
            _select((parent(text="\n".join([A]*20)), parent(2)), CLAIM)

    def test_bad_parent_provenance_rejected(self):
        for kwargs in ({"passage_sha256": "0"*64}, {"start_offset": -1},
                       {"end_offset": 3}, {"snapshot_text_length": 0},
                       {"snapshot_sha256": "z"*64}, {"fetch_observed_at": NOW.replace(tzinfo=None)},
                       {"snapshot_version_number": 0}, {"source_id": "x"},
                       {"lexical_relevance_score": float("nan")}, {"original_url": "http://a"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ParagraphInputError):
                validate_parent(parent(**kwargs))

    def test_altered_input_fields_cannot_replay(self):
        p = _select((parent(), parent(2)), CLAIM).inputs[0]
        for kwargs in ({"start_offset": 1}, {"end_offset": p.end_offset-1},
                       {"text": A+" Changed."}, {"sha256": "0"*64}, {"rank": 0},
                       {"policy_version": "other"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ParagraphInputError):
                validate_paragraph_input(replace(p, **kwargs))

    def test_selection_input_removal_rank_and_exclusions_tampering_rejected(self):
        s = _select((parent(text="Background.\n"+A), parent(2)), CLAIM)
        for changed in (replace(s, inputs=s.inputs[:1]), replace(s, inputs=s.inputs[::-1]),
                        replace(s, exclusions=()), replace(s, policy_version="x")):
            with self.subTest(changed=changed), self.assertRaises(ParagraphInputError):
                validate_paragraph_selection(changed)

    def test_fetch_observation_is_part_of_selection_receipt(self):
        a = _select((parent(), parent(2)), CLAIM)
        b = _select((parent(fetch_observation_id=uid(999)), parent(2)), CLAIM)
        self.assertNotEqual(a.selection_sha256, b.selection_sha256)
        self.assertEqual(a.inputs[0].context_id, b.inputs[0].context_id)

    def test_snapshot_change_changes_derived_id(self):
        a = _select((parent(), parent(2)), CLAIM)
        b = _select((parent(snapshot_sha256="a"*64), parent(2)), CLAIM)
        self.assertNotEqual(a.inputs[0].context_id, b.inputs[0].context_id)

    def test_audit_requires_unverified_traceable_parent(self):
        for field, value in (("traceable", False), ("nli_evaluated", True),
                             ("independently_verified", True), ("independent_corroboration_established", True)):
            audits = [audit(parent()), audit(parent(2))]
            setattr(audits[0], field, value)
            with self.subTest(field=field), self.assertRaises(ParagraphInputError):
                selection_from_audits(audits, CLAIM)

    def test_audit_must_include_snapshot_length(self):
        a = audit(parent()); a.snapshot_text_length = None
        with self.assertRaises(ParagraphInputError):
            selection_from_audits((a, audit(parent(2))), CLAIM)

    def test_immutable_bindings_do_not_establish_independence(self):
        p = _select((parent(), parent(2)), CLAIM).inputs[0]
        with self.assertRaises(AttributeError): p.text = "changed"
        self.assertFalse(p.independently_verified)
        self.assertFalse(p.independent_corroboration_established)


class DriverUUID(UUID):
    """Model a driver UUID implementation that subclasses the standard UUID."""


def driver_parent(p):
    return replace(p, **{key: DriverUUID(str(getattr(p, key))) for key in
                        ("passage_id", "document_id", "document_version_id", "source_id", "fetch_observation_id")})


class UUIDCompatibilityTests(unittest.TestCase):
    def test_all_parent_uuid_fields_accept_uuid_subclasses(self):
        p = driver_parent(parent())
        self.assertTrue(all(type(getattr(p, key)) is DriverUUID for key in
                            ("passage_id", "document_id", "document_version_id", "source_id", "fetch_observation_id")))
        validate_parent(p)

    def test_driver_and_standard_uuids_keep_same_selection_and_context_ids(self):
        plain = _select((parent(), parent(2)), CLAIM)
        derived = _select((driver_parent(parent()), driver_parent(parent(2))), CLAIM)
        self.assertEqual(plain, derived)
        self.assertEqual(plain.selection_sha256, derived.selection_sha256)
        self.assertEqual([p.context_id for p in plain.inputs], [p.context_id for p in derived.inputs])

    def test_driver_uuid_audits_preserve_original_identity_objects(self):
        parents = (driver_parent(parent()), driver_parent(parent(2)))
        selection = selection_from_audits(tuple(audit(p) for p in parents), CLAIM)
        by_id = {p.passage_id: p for p in parents}
        for value in selection.parents:
            self.assertIs(value.passage_id, by_id[value.passage_id].passage_id)
            self.assertIs(value.fetch_observation_id, by_id[value.passage_id].fetch_observation_id)

    def test_uuid_subclasses_pass_full_pure_agreement_and_domain_view(self):
        nli = make_report((driver_parent(parent()), driver_parent(parent(2))))
        agreement, review, origin, decision = prepare(nli)
        result = _snapshot_external(claim=CLAIM, at=NOW,
            retrieved=tuple(candidate(p) for p in nli.paragraph_selection.parents),
            nli=nli, agreement=agreement, decision=decision,
            independence_review=review, reporting_origin_audit=origin)
        self.assertEqual(result.assessed_count, 2)
        self.assertEqual(agreement.supporting_unit_count, 2)
        self.assertFalse(decision.independent_corroboration_established)

    def test_non_uuid_ids_remain_rejected_for_each_identity_field(self):
        for key in ("passage_id", "document_id", "document_version_id", "source_id", "fetch_observation_id"):
            for value in (str(uid(1)), uid(1).bytes, 1, None):
                with self.subTest(key=key, value=value), self.assertRaisesRegex(ParagraphInputError, "invalid_parent_identity"):
                    validate_parent(replace(parent(), **{key: value}))


class DownstreamTests(unittest.TestCase):
    def test_derived_scores_use_derived_ids_text_and_token_count(self):
        nli = make_report(); validate_nli_input_bindings(nli)
        for row in nli.evidence:
            self.assertEqual(row.passage_text, row.paragraph_input.text)
            self.assertEqual(row.passage_id, row.paragraph_input.context_id)
            self.assertEqual(row.input_pair_tokens, 32)
            self.assertEqual(row.input_kind, "DERIVED_PARAGRAPH")

    def test_changed_report_binding_fields_rejected_before_admission(self):
        nli = make_report(); row = nli.evidence[0]
        for kwargs in ({"passage_id": uid(999)}, {"passage_text": "different"},
                       {"passage_sha256": "0"*64}, {"article_url": "https://other.org"},
                       {"source_id": uid(999)}, {"document_version_id": uid(999)},
                       {"paragraph_input": None}, {"input_pair_tokens": 257},
                       {"input_pair_tokens": True}, {"model_max_length": 2},
                       {"model_max_length": 128}, {"lexical_relevance_score": .3}):
            bad = replace(nli, evidence=(replace(row, **kwargs),)+nli.evidence[1:])
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                analyze_external_evidence_agreement(nli_report=bad)

    def test_selection_cannot_be_removed_while_context_metadata_remains(self):
        with self.assertRaises(ExternalNliError):
            validate_nli_input_bindings(replace(make_report(), paragraph_selection=None))

    def test_normalization_uses_paragraph_text_not_distinct_parent_background(self):
        nli = make_report((parent(text="First background.\n"+A), parent(2, text="Other background.\n"+A)))
        self.assertEqual(nli.exact_duplicate_count, 1)
        agreement, review, _, decision = prepare(nli)
        self.assertEqual(agreement.provisional_agreement_unit_count, 1)
        self.assertFalse(review.review_candidates)
        self.assertFalse(decision.independent_corroboration_established)

    def test_qualification_elsewhere_in_parent_still_blocks_vote(self):
        nli = make_report((parent(text=A+"\nA visitor alleged that the club had closed."), parent(2)))
        agreement, review, _, decision = prepare(nli)
        first = nli.evidence[0]
        codes = dict(agreement.scope_excluded_decisive_passages)[first.passage_id]
        self.assertIn("PARENT_PASSAGE_SCOPE_REQUIRES_REVIEW", codes)
        self.assertNotIn(first.passage_id, decision.supporting_passage_ids)
        self.assertTrue(first.nli_threshold_passed)
        self.assertFalse(review.review_candidates)

    def test_origin_pair_exposes_parent_offset_snapshot_and_fetch(self):
        nli = make_report(); _, review, _, _ = prepare(nli)
        pair = review.review_candidates[0]
        by_id = {r.passage_id: r.paragraph_input for r in nli.evidence}
        for side in ("left", "right"):
            p = by_id[getattr(pair, side+"_passage_id")]
            self.assertEqual(getattr(pair, side+"_input_kind"), "DERIVED_PARAGRAPH")
            self.assertEqual(getattr(pair, side+"_parent_passage_id"), p.parent.passage_id)
            self.assertEqual(getattr(pair, side+"_input_start_offset"), p.start_offset)
            self.assertEqual(getattr(pair, side+"_input_end_offset"), p.end_offset)
            self.assertEqual(getattr(pair, side+"_snapshot_sha256"), p.parent.snapshot_sha256)
            self.assertEqual(getattr(pair, side+"_fetch_observation_id"), p.parent.fetch_observation_id)

    def test_origin_packet_fingerprint_binds_fetch_observation(self):
        a = make_report(); b = make_report((parent(fetch_observation_id=uid(999)), parent(2)))
        self.assertNotEqual(prepare(a)[1].review_packet_sha256, prepare(b)[1].review_packet_sha256)

    def test_unified_domain_snapshot_retains_both_id_types(self):
        nli = make_report(); agreement, review, origin, decision = prepare(nli)
        result = _snapshot_external(claim=CLAIM, at=NOW,
            retrieved=tuple(candidate(p) for p in nli.paragraph_selection.parents),
            nli=nli, agreement=agreement, decision=decision,
            independence_review=review, reporting_origin_audit=origin)
        self.assertEqual(result.evidence_input_kind, "DERIVED_PARAGRAPH")
        self.assertEqual(result.audited_parent_count, 2)
        self.assertEqual(result.assessed_count, 2)
        for ref, row in zip(result.provenance, nli.evidence):
            self.assertEqual(ref.parent_passage_id, row.paragraph_input.parent.passage_id)
            self.assertEqual(ref.input_sha256, row.passage_sha256)
            self.assertEqual(ref.fetch_observation_id, row.paragraph_input.parent.fetch_observation_id)

    def test_unified_snapshot_rejects_foreign_retrieved_parent(self):
        nli = make_report(); agreement, review, origin, decision = prepare(nli)
        parents = [candidate(p) for p in nli.paragraph_selection.parents]
        parents[0].original_url = "https://other.example.org/x"
        with self.assertRaisesRegex(ValueError, "paragraph_parent_retrieval"):
            _snapshot_external(claim=CLAIM, at=NOW, retrieved=tuple(parents), nli=nli,
                agreement=agreement, decision=decision, independence_review=review,
                reporting_origin_audit=origin)

    def test_unrelated_probe_uses_frozen_selection_but_has_no_votes(self):
        nli = make_report(claim="Mount Etna is a volcano in Sicily.")
        agreement, review, _, decision = prepare(nli)
        self.assertEqual(len(nli.evidence), 2)
        self.assertFalse(decision.supporting_passage_ids)
        self.assertFalse(review.review_candidates)
        self.assertEqual(agreement.decisive_passages, 0)


class Predictor:
    max_length = 256
    def __init__(self, length=32): self.length, self.calls = length, []
    def tokenizer(self, texts, claims, **kwargs):
        self.tokenized = (list(texts), list(claims), kwargs)
        return {"length": [self.length]*len(texts)}
    def predict(self, claim, texts):
        self.calls.append((claim, list(texts)))
        return [NS(entailment=.96, contradiction=.02, neutral=.02) for _ in texts]


class ServiceTests(unittest.IsolatedAsyncioTestCase):
    def fake_modules(self, audits):
        provenance = ModuleType("apps.api.services.external_evidence_provenance")
        provenance.audit_external_passage_provenance = AsyncMock(return_value=audits)
        dependency = ModuleType("apps.api.services.external_source_independence")
        dependency.audit_external_source_dependencies = AsyncMock(return_value=dependencies((parent(), parent(2))))
        return provenance, dependency

    async def invoke(self, *, audits=None, parents=None, predictor=None, **kwargs):
        parents = parents or (parent(text="Background.\n"+A), parent(2))
        provenance, dependency = self.fake_modules(audits or tuple(audit(p) for p in parents))
        predictor = predictor or Predictor()
        with patch.dict(sys.modules, {provenance.__name__: provenance, dependency.__name__: dependency}):
            result = await assess_external_paragraph_nli(object(), claim=CLAIM,
                candidates=tuple(candidate(p) for p in parents), assessed_at=NOW, predictor=predictor, **kwargs)
        return result, predictor, provenance, dependency

    async def test_actual_paragraphs_are_tokenized_and_predicted(self):
        result, predictor, provenance, dependency = await self.invoke()
        expected = [p.text for p in result.paragraph_selection.inputs]
        self.assertEqual(predictor.calls, [(CLAIM, expected)])
        self.assertEqual(predictor.tokenized[0], expected)
        self.assertFalse(predictor.tokenized[2]["truncation"])
        self.assertNotIn("Background.", expected)
        self.assertTrue(provenance.audit_external_passage_provenance.await_count == 1)
        selected = dependency.audit_external_source_dependencies.call_args.args[1]
        self.assertTrue(all(not isinstance(c, ParagraphInput) for c in selected))
        self.assertEqual(selected[0].passage_text, "Background.\n"+A)

    async def test_over_token_budget_prevents_prediction(self):
        predictor = Predictor(257)
        with self.assertRaisesRegex(ExternalNliError, "truncated"):
            await self.invoke(predictor=predictor)
        self.assertFalse(predictor.calls)

    async def test_foreign_audited_parent_stops_before_prediction(self):
        predictor = Predictor()
        with self.assertRaisesRegex(ExternalNliError, "audit_parent"):
            await self.invoke(audits=(audit(parent(3, text=A)), audit(parent(2))), predictor=predictor)
        self.assertFalse(predictor.calls)

    async def test_future_observation_stops_before_prediction(self):
        predictor = Predictor()
        parents = (parent(fetch_observed_at=NOW+timedelta(days=1)), parent(2))
        with self.assertRaisesRegex(ExternalNliError, "audit_parent_or_time"):
            await self.invoke(parents=parents, predictor=predictor)
        self.assertFalse(predictor.calls)

    async def test_bad_audit_stops_before_dependency_or_prediction(self):
        predictor = Predictor(); a = audit(parent()); a.traceable = False
        provenance, dependency = self.fake_modules((a, audit(parent(2))))
        with patch.dict(sys.modules, {provenance.__name__: provenance, dependency.__name__: dependency}):
            with self.assertRaises(ParagraphInputError):
                await assess_external_paragraph_nli(object(), claim=CLAIM,
                    candidates=(candidate(parent()), candidate(parent(2))), assessed_at=NOW, predictor=predictor)
        self.assertFalse(predictor.calls)
        dependency.audit_external_source_dependencies.assert_not_awaited()

    async def test_dependency_failure_stops_before_prediction(self):
        predictor = Predictor(); provenance, dependency = self.fake_modules((audit(parent()), audit(parent(2))))
        dependency.audit_external_source_dependencies.side_effect = ValueError("dependency_failed")
        with patch.dict(sys.modules, {provenance.__name__: provenance, dependency.__name__: dependency}):
            with self.assertRaisesRegex(ValueError, "dependency_failed"):
                await assess_external_paragraph_nli(object(), claim=CLAIM,
                    candidates=(candidate(parent()), candidate(parent(2))), assessed_at=NOW, predictor=predictor)
        self.assertFalse(predictor.calls)

    async def test_fixed_selection_does_not_reselect_using_probe_or_scores(self):
        result, predictor, _, _ = await self.invoke(selection_claim=CLAIM)
        self.assertEqual(result.paragraph_selection.claim, CLAIM)
        self.assertEqual(result.paragraph_selection.inputs[0].text, A)

    async def test_expected_selection_checked_before_prediction(self):
        predictor = Predictor()
        wrong = _select((parent(), parent(2)), CLAIM)
        with self.assertRaisesRegex(ExternalNliError, "selection_changed"):
            await self.invoke(predictor=predictor, expected_selection=wrong)
        self.assertFalse(predictor.calls)

    async def test_matching_frozen_selection_can_run(self):
        parents = (parent(text="Background.\n"+A), parent(2))
        result, _, _, _ = await self.invoke(parents=parents, expected_selection=_select(parents, CLAIM))
        self.assertEqual(result.paragraph_selection, _select(parents, CLAIM))

    async def test_unbounded_or_missing_tokenizer_budget_rejected(self):
        for value in (None, True, 1, 4097):
            predictor = Predictor(); predictor.max_length = value
            with self.subTest(value=value), self.assertRaises(ExternalNliError):
                _predict_checked(CLAIM, [A, B], predictor)
            self.assertFalse(predictor.calls)


if __name__ == "__main__": unittest.main()
