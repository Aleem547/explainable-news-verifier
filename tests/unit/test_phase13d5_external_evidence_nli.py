"""Offline Phase 13D.5 tests. No model weights, database, or HTTP required."""

from __future__ import annotations

import dataclasses
import math
import sys
import unittest
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from apps.api.services.external_evidence_nli import (
    ExternalNliError, build_external_nli_report, _probabilities,
)

NOW = datetime(2026, 10, 20, tzinfo=UTC)


def cand(text: str, *, version=None, p_id=None, **overrides):
    values = dict(
        passage_id=p_id or uuid4(), document_version_id=version or uuid4(),
        source_id=uuid4(), publisher_domain="example.org", original_url="https://example.org/a",
        passage_text=text, passage_sha256=sha256(text.encode()).hexdigest(),
        retrieved_at=NOW, lexical_relevance_score=0.7,
        independently_verified=False, nli_evaluated=False,
        independent_corroboration_established=False,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def wrap(c):
    return SimpleNamespace(
        candidate=c, traceable=True, nli_evaluated=False,
        independently_verified=False, independent_corroboration_established=False,
        fetch_observation_id=uuid4(), fetch_observed_at=NOW,
    )


def prob(e, c, n):
    return SimpleNamespace(entailment=e, contradiction=c, neutral=n)


def setup():
    a = cand("Paris is the location of a famous tower, says one article.")
    b = cand("A source disputes that statement and provides another location.")
    audits = [wrap(a), wrap(b)]
    normalization = SimpleNamespace(
        groups=(SimpleNamespace(members=(SimpleNamespace(candidate=a),)),
                SimpleNamespace(members=(SimpleNamespace(candidate=b),))),
        input_count=2, exact_duplicate_count=0,
        possible_near_duplicate_count=0,
        independent_corroboration_established=False,
    )
    deps = SimpleNamespace(
        risk_families=((a.document_version_id,), (b.document_version_id,)),
        version_ids=(a.document_version_id, b.document_version_id),
        independence_status="NOT_ESTABLISHED",
        independent_corroboration_established=False, independently_verified=False,
    )
    return dict(
        claim="The Eiffel Tower is in Paris", audits=audits,
        normalization=normalization, dependencies=deps,
        predictions=[prob(0.96, 0.02, 0.02), prob(0.01, 0.96, 0.03)],
        assessed_at=NOW,
    )


class ExternalNliReportTests(unittest.TestCase):
    def report(self, **updates):
        args = setup()
        args.update(updates)
        return build_external_nli_report(**args)

    def rejected(self, label, alter):
        args = setup()
        alter(args)
        with self.assertRaisesRegex(ExternalNliError, label):
            build_external_nli_report(**args)

    def test_two_passages_classified_without_truth_claim(self):
        result = self.report()
        self.assertEqual([x.nli_label for x in result.evidence], ["ENTAILMENT", "CONTRADICTION"])
        self.assertTrue(all(e.nli_threshold_passed for e in result.evidence))
        self.assertFalse(result.independently_verified)
        self.assertFalse(result.independent_corroboration_established)
        self.assertEqual(result.independence_status, "NOT_ESTABLISHED")

    def test_preserves_unmodified_passages_and_source_details(self):
        args = setup(); result = build_external_nli_report(**args)
        for source, item in zip(args["audits"], result.evidence, strict=True):
            self.assertEqual(item.passage_text, source.candidate.passage_text)
            self.assertEqual(item.passage_sha256, source.candidate.passage_sha256)
            self.assertEqual(item.article_url, source.candidate.original_url)
            self.assertEqual(item.source_id, source.candidate.source_id)

    def test_neutral_never_passes_decisive_threshold(self):
        a = setup(); a["predictions"] = [prob(0.02, 0.01, 0.97), prob(0.03, 0.94, 0.03)]
        result = build_external_nli_report(**a)
        self.assertEqual(result.evidence[0].nli_label, "NEUTRAL")
        self.assertFalse(result.evidence[0].nli_threshold_passed)

    def test_below_threshold_not_decisive(self):
        a = setup(); a["predictions"] = [prob(0.88, 0.10, 0.02), prob(0.8, 0.1, 0.1)]
        self.assertFalse(any(p.nli_threshold_passed for p in build_external_nli_report(**a).evidence))

    def test_same_risk_family_does_not_claim_independence(self):
        a = setup(); versions = [x.candidate.document_version_id for x in a["audits"]]
        a["dependencies"].risk_families = (tuple(versions),)
        self.assertEqual([x.dependency_risk_family for x in build_external_nli_report(**a).evidence], [1,1])

    def test_duplicate_normalization_groups_preserve_sources(self):
        a = setup(); members = tuple(SimpleNamespace(candidate=x.candidate) for x in a["audits"])
        a["normalization"].groups = (SimpleNamespace(members=members),)
        a["normalization"].exact_duplicate_count = 1
        report = build_external_nli_report(**a)
        self.assertEqual(report.exact_duplicate_count, 1)
        self.assertEqual(len(report.evidence), 2)
        self.assertEqual([p.duplicate_group for p in report.evidence], [1,1])

    def test_invalid_nli_values_rejected(self):
        for value in (float("nan"), float("inf"), -0.01, 1.1):
            self.subTest(value=value)
            with self.assertRaises(ExternalNliError):
                self.report(predictions=[prob(value, 0.05, 0.95), prob(0,1,0)])

    def test_invalid_nli_sum_rejected(self):
        self.rejected("invalid_nli_probability_distribution", lambda a: a.update(predictions=[prob(.5, .2, .2), prob(0,1,0)]))

    def test_model_output_missing_rejected(self):
        self.rejected("nli_output_missing_probabilities", lambda a: a.update(predictions=[object(), prob(0,1,0)]))

    def test_model_result_count_mismatch(self):
        self.rejected("nli_output_count_mismatch", lambda a: a.update(predictions=[prob(0,1,0)]))

    def test_reject_foreign_normalization_id(self):
        self.rejected("duplicate_or_foreign_normalized_passage", lambda a: setattr(a["normalization"].groups[0].members[0], "candidate", cand("stranger")))

    def test_reject_normalization_text_mismatch(self):
        def alter(a):
            fake = cand("changed", version=a["audits"][0].candidate.document_version_id, p_id=a["audits"][0].candidate.passage_id)
            a["normalization"].groups[0].members[0].candidate = fake
        self.rejected("normalized_evidence_mismatch", alter)

    def test_reject_missing_normalized_passage(self):
        self.rejected("normalization_candidate_coverage_mismatch", lambda a: setattr(a["normalization"], "groups", a["normalization"].groups[:1]))

    def test_reject_stale_independence_state(self):
        self.rejected("invalid_dependency_status", lambda a: setattr(a["dependencies"], "independent_corroboration_established", True))

    def test_reject_foreign_dependency_version(self):
        self.rejected("dependency_versions_mismatch", lambda a: setattr(a["dependencies"], "risk_families", ((uuid4(),),)))

    def test_reject_duplicate_dependency_version(self):
        def alter(a):
            version = a["audits"][0].candidate.document_version_id
            a["dependencies"].risk_families = ((version,), (version,))
        self.rejected("duplicate_dependency_version", alter)

    def test_reject_untraceable_passage(self):
        self.rejected("unaudited_or_preassessed_passage", lambda a: setattr(a["audits"][0], "traceable", False))

    def test_reject_missing_fetch_observation(self):
        self.rejected("missing_fetch_observation", lambda a: setattr(a["audits"][0], "fetch_observation_id", None))

    def test_reject_future_evidence(self):
        from datetime import timedelta
        self.rejected("future_or_invalid_observation_time", lambda a: setattr(a["audits"][0], "fetch_observed_at", NOW + timedelta(days=1)))

    def test_reject_tampered_hash(self):
        self.rejected("tampered_candidate_text", lambda a: setattr(a["audits"][0].candidate, "passage_sha256", "f"*64))

    def test_reject_already_nli_evaluated_input(self):
        self.rejected("candidate_already_assessed", lambda a: setattr(a["audits"][0].candidate, "nli_evaluated", True))

    def test_reject_repeated_passage_id(self):
        self.rejected("requires_distinct_passages_and_versions", lambda a: setattr(a["audits"][1].candidate, "passage_id", a["audits"][0].candidate.passage_id))

    def test_reject_one_snapshot_only(self):
        self.rejected("requires_distinct_passages_and_versions", lambda a: setattr(a["audits"][1].candidate, "document_version_id", a["audits"][0].candidate.document_version_id))

    def test_reject_naive_clock(self):
        self.rejected("assessment_timestamp_must_be_aware", lambda a: a.update(assessed_at=datetime(2026, 10, 20)))

    def test_reject_invalid_threshold(self):
        self.rejected("invalid_nli_threshold", lambda a: a.update(nli_threshold=float("nan")))

    def test_reject_too_many_evidence_candidates(self):
        def alter(a):
            a["audits"] = [wrap(cand("passage")) for _ in range(21)]
        self.rejected("invalid_candidate_batch", alter)

    def test_report_is_immutable(self):
        with self.assertRaises(dataclasses.FrozenInstanceError):
            self.report().evidence[0].nli_label = "NOT_REAL"


class AsyncIntegrationContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_uses_existing_pipeline_and_does_not_mutate_input(self):
        from unittest.mock import patch
        from types import ModuleType
        from apps.api.services.external_evidence_nli import assess_external_evidence_nli
        args = setup()
        input_candidates = tuple(x.candidate for x in args["audits"])
        imports = {}

        async def audit(session, cands):
            self.assertEqual(tuple(cands), input_candidates)
            return tuple(args["audits"])

        async def deps(session, cands, *, assessed_at):
            self.assertEqual(tuple(cands), input_candidates)
            return args["dependencies"]

        def normalize(cands):
            return args["normalization"]

        for name, method in (
            ("apps.api.services.external_evidence_normalization", ("normalize_and_group_external_evidence", normalize)),
            ("apps.api.services.external_evidence_provenance", ("audit_external_passage_provenance", audit)),
            ("apps.api.services.external_source_independence", ("audit_external_source_dependencies", deps)),
        ):
            module = ModuleType(name)
            setattr(module, method[0], method[1])
            imports[name] = module

        class Predictor:
            def predict(self, claim, texts):
                self.called = True
                self.last = (claim, texts)
                return args["predictions"]

        predictor = Predictor()
        with patch.dict(sys.modules, imports):
            result = await assess_external_evidence_nli(
                object(), claim=args["claim"], candidates=input_candidates,
                predictor=predictor, assessed_at=NOW,
            )
        self.assertTrue(predictor.called)
        self.assertEqual(predictor.last[1], [c.passage_text for c in input_candidates])
        self.assertEqual(len(result.evidence), 2)
        self.assertFalse(result.independent_corroboration_established)

    async def test_model_count_error_fails_without_partial_report(self):
        from unittest.mock import patch
        from types import ModuleType
        from apps.api.services.external_evidence_nli import assess_external_evidence_nli
        args = setup()
        mods = {}

        async def audit(session, cands):
            return args["audits"]

        async def deps(session, cands, *, assessed_at):
            return args["dependencies"]

        def normalize(cands):
            return args["normalization"]

        for name, attr, value in (
            ("apps.api.services.external_evidence_normalization", "normalize_and_group_external_evidence", normalize),
            ("apps.api.services.external_evidence_provenance", "audit_external_passage_provenance", audit),
            ("apps.api.services.external_source_independence", "audit_external_source_dependencies", deps),
        ):
            module = ModuleType(name)
            setattr(module, attr, value)
            mods[name] = module

        class Predictor:
            def predict(self, claim, texts):
                return args["predictions"][:1]

        with patch.dict(sys.modules, mods):
            with self.assertRaisesRegex(ExternalNliError, "nli_output_count_mismatch"):
                await assess_external_evidence_nli(
                    object(), claim=args["claim"], candidates=[x.candidate for x in args["audits"]],
                    predictor=Predictor(), assessed_at=NOW,
                )


if __name__ == "__main__":
    unittest.main()
