"""Phase 13D.6 synthetic, deterministic and entirely offline tests."""

from __future__ import annotations

import dataclasses
import unittest
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import uuid4

from apps.api.services.external_evidence_agreement import (
    EvidenceAgreementError,
    analyze_external_evidence_agreement,
)
from apps.api.services.external_evidence_nli import ExternalNliPassage, ExternalNliReport

NOW = datetime(2026, 10, 20, tzinfo=UTC)


def make_passage(*, family=1, group=1, stance="support", domain=None, **overrides):
    values = {
        "support": ("ENTAILMENT", .96, .02, .02, .96, True),
        "refute": ("CONTRADICTION", .02, .96, .02, .96, True),
        "neutral": ("NEUTRAL", .04, .04, .92, .92, False),
        "weak_support": ("ENTAILMENT", .70, .20, .10, .70, False),
    }
    label, e, c, n, confidence, passed = values[stance]
    text = f"An evidence passage about a geographical fact, source {uuid4()}."
    domain = domain or f"paper-{family}.example.org"
    kwargs = dict(
        passage_id=uuid4(), document_version_id=uuid4(), source_id=uuid4(),
        publisher_domain=domain, article_url=f"https://{domain}/article",
        passage_text=text, passage_sha256=sha256(text.encode()).hexdigest(),
        retrieved_at=NOW, lexical_relevance_score=.6,
        dependency_risk_family=family, duplicate_group=group,
        nli_label=label, entailment=e, contradiction=c, neutral=n,
        nli_confidence=confidence, nli_threshold_passed=passed,
    )
    kwargs.update(overrides)
    return ExternalNliPassage(**kwargs)


def make_report(*passages, **overrides):
    kwargs = dict(
        claim="A monument is located in Paris", assessed_at=NOW,
        nli_threshold=.90, evidence=tuple(passages),
        dependency_risk_family_count=len({p.dependency_risk_family for p in passages}),
        exact_duplicate_count=0, possible_near_duplicate_count=0,
    )
    kwargs.update(overrides)
    return ExternalNliReport(**kwargs)


class EvidenceAgreementTests(unittest.TestCase):
    def analyze(self, *passages, **updates):
        return analyze_external_evidence_agreement(nli_report=make_report(*passages, **updates))

    def rejects(self, error, passages=None, *, report_changes=None):
        passages = passages or [make_passage(family=1, group=1), make_passage(family=2, group=2)]
        with self.assertRaisesRegex(EvidenceAgreementError, error):
            self.analyze(*passages, **(report_changes or {}))

    def test_support_only_remains_provisional(self):
        result = self.analyze(make_passage(family=1, group=1), make_passage(family=2, group=2))
        self.assertEqual(result.evidence_status, "PROVISIONAL_SUPPORT_ONLY")
        self.assertEqual(result.supporting_unit_count, 2)
        self.assertEqual(result.provisional_agreement_unit_count, 2)
        self.assertFalse(result.independent_corroboration_established)
        self.assertFalse(result.independently_verified)
        self.assertEqual(result.independence_status, "NOT_ESTABLISHED")

    def test_refute_only_is_provisional_not_fact_check(self):
        r = self.analyze(make_passage(family=1, group=1, stance="refute"), make_passage(family=2, group=2, stance="refute"))
        self.assertEqual(r.evidence_status, "PROVISIONAL_REFUTE_ONLY")
        self.assertEqual(r.refuting_unit_count, 2)

    def test_conflicting_separate_families(self):
        r = self.analyze(make_passage(family=1, group=1), make_passage(family=2, group=2, stance="refute"))
        self.assertEqual(r.evidence_status, "UNRESOLVED_OPPOSING_EVIDENCE")
        self.assertTrue(r.has_opposing_evidence)
        self.assertFalse(r.has_within_unit_conflict)
        self.assertEqual((r.supporting_unit_count, r.refuting_unit_count), (1, 1))

    def test_conflicting_same_family_is_one_mixed_unit(self):
        a = make_passage(family=1, group=1)
        b = make_passage(family=1, group=2, stance="refute")
        r = self.analyze(a, b)
        self.assertTrue(r.has_within_unit_conflict)
        self.assertEqual(r.mixed_unit_count, 1)
        self.assertEqual(r.supporting_unit_count, 0)
        self.assertEqual(r.refuting_unit_count, 0)
        self.assertEqual(r.provisional_agreement_unit_count, 1)

    def test_neutral_and_low_confidence_are_inconclusive(self):
        r = self.analyze(make_passage(family=1, group=1, stance="neutral"), make_passage(family=2, group=2, stance="weak_support"))
        self.assertEqual(r.evidence_status, "INSUFFICIENT_DECISIVE_EVIDENCE")
        self.assertEqual(r.decisive_passages, 0)
        self.assertEqual(r.inconclusive_passages, 2)
        self.assertEqual(r.inconclusive_unit_count, 2)

    def test_duplicate_across_different_families_bridges_units(self):
        r = self.analyze(make_passage(family=1, group=1), make_passage(family=2, group=1))
        self.assertEqual(r.raw_dependency_risk_family_count, 2)
        self.assertEqual(r.provisional_agreement_unit_count, 1)
        self.assertEqual(r.supporting_unit_count, 1)
        self.assertEqual(r.units[0].risk_family_ids, (1, 2))
        self.assertIn("DUPLICATE_PASSAGES_BRIDGE_RISK_FAMILIES", r.warnings)

    def test_near_duplicate_bridge_is_conservative(self):
        r = self.analyze(make_passage(family=1, group=1), make_passage(family=2, group=1), possible_near_duplicate_count=1)
        self.assertEqual(r.supporting_unit_count, 1)
        self.assertFalse(r.independent_corroboration_established)

    def test_transitive_bridging(self):
        rows = [
            make_passage(family=1, group=1), make_passage(family=2, group=1),
            make_passage(family=2, group=2), make_passage(family=3, group=2),
        ]
        r = self.analyze(*rows)
        self.assertEqual(r.provisional_agreement_unit_count, 1)
        self.assertEqual(r.units[0].risk_family_ids, (1, 2, 3))

    def test_conflict_inside_duplicate_group_flagged(self):
        r = self.analyze(make_passage(family=1, group=1), make_passage(family=2, group=1, stance="refute"))
        self.assertEqual(r.mixed_unit_count, 1)
        self.assertIn("CONTRADICTORY_LABELS_INSIDE_DUPLICATE_GROUP", r.warnings)
        self.assertEqual(r.evidence_status, "UNRESOLVED_OPPOSING_EVIDENCE")

    def test_unmatched_neutral_ignored_for_decisive_counts(self):
        r = self.analyze(make_passage(family=1, group=1), make_passage(family=2, group=2, stance="neutral"))
        self.assertEqual(r.supporting_unit_count, 1)
        self.assertEqual(r.inconclusive_unit_count, 1)
        self.assertEqual(r.decisive_passages, 1)

    def test_output_preserves_all_evidence_and_urls(self):
        a, b = make_passage(family=1, group=1), make_passage(family=2, group=2)
        r = self.analyze(a, b)
        self.assertEqual(r.evidence, (a, b))
        self.assertEqual(set(r.units[0].article_urls + r.units[1].article_urls), {a.article_url, b.article_url})
        self.assertEqual(sum(len(u.passage_ids) for u in r.units), 2)

    def test_deterministic_unit_order_when_inputs_permuted(self):
        a, b, c = make_passage(family=1, group=1), make_passage(family=2, group=2), make_passage(family=3, group=3)
        r1 = self.analyze(c, a, b)
        r2 = self.analyze(b, c, a)
        self.assertEqual(r1.units, r2.units)
        self.assertEqual(r1.warnings, r2.warnings)

    def test_input_report_and_output_are_immutable(self):
        r = self.analyze(make_passage(family=1, group=1), make_passage(family=2, group=2))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            r.units[0].stance = "true"
        with self.assertRaises(dataclasses.FrozenInstanceError):
            r.independent_corroboration_established = True

    def test_upstream_warnings_retained(self):
        r = self.analyze(make_passage(family=1, group=1), make_passage(family=2, group=2))
        self.assertIn("MODEL_CALIBRATION_WAS_NOT_FITTED_ON_EXTERNAL_NEWS_EVIDENCE", r.warnings)

    def test_real_phase13d5_report_contract(self):
        # Exercise the actual Phase 13D.5 report constructor, not a mocked NLI report.
        from types import SimpleNamespace
        from apps.api.services.external_evidence_nli import build_external_nli_report
        raw = [make_passage(family=1, group=1), make_passage(family=2, group=2, stance="refute")]
        candidates = [SimpleNamespace(
            passage_id=r.passage_id, document_version_id=r.document_version_id,
            source_id=r.source_id, publisher_domain=r.publisher_domain,
            original_url=r.article_url, passage_text=r.passage_text,
            passage_sha256=r.passage_sha256, retrieved_at=r.retrieved_at,
            lexical_relevance_score=r.lexical_relevance_score,
            nli_evaluated=False, independently_verified=False,
            independent_corroboration_established=False,
        ) for r in raw]
        audits = [SimpleNamespace(candidate=c, traceable=True, nli_evaluated=False,
                                  independently_verified=False, independent_corroboration_established=False,
                                  fetch_observation_id=uuid4(), fetch_observed_at=NOW)
                  for c in candidates]
        normalized = SimpleNamespace(input_count=2, exact_duplicate_count=0,
                                     possible_near_duplicate_count=0,
                                     independent_corroboration_established=False,
                                     groups=tuple(SimpleNamespace(members=(SimpleNamespace(candidate=c),))
                                                  for c in candidates))
        deps = SimpleNamespace(
            risk_families=tuple((c.document_version_id,) for c in candidates),
            version_ids=tuple(c.document_version_id for c in candidates),
            independence_status="NOT_ESTABLISHED",
            independent_corroboration_established=False, independently_verified=False,
        )
        predictions = [SimpleNamespace(entailment=r.entailment, contradiction=r.contradiction,
                                       neutral=r.neutral) for r in raw]
        nli = build_external_nli_report(
            claim="A monument is located in Paris", audits=audits,
            normalization=normalized, dependencies=deps,
            predictions=predictions, assessed_at=NOW,
        )
        agreement = analyze_external_evidence_agreement(nli_report=nli)
        self.assertEqual(agreement.evidence_status, "UNRESOLVED_OPPOSING_EVIDENCE")
        self.assertEqual((agreement.supporting_unit_count, agreement.refuting_unit_count), (1, 1))
        self.assertFalse(agreement.independent_corroboration_established)

    def test_rejects_wrong_report_type(self):
        with self.assertRaises(EvidenceAgreementError):
            analyze_external_evidence_agreement(nli_report=object())

    def test_rejects_empty_or_single_batch(self):
        self.rejects("invalid_evidence_batch", [make_passage(family=1, group=1)], report_changes={"dependency_risk_family_count": 1})

    def test_rejects_duplicate_passage_id(self):
        a = make_passage(family=1, group=1)
        b = make_passage(family=2, group=2, passage_id=a.passage_id)
        self.rejects("duplicate_passage_id", [a, b])

    def test_rejects_hash_tampering(self):
        a = make_passage(family=1, group=1, passage_sha256="f" * 64)
        self.rejects("passage_hash_mismatch", [a, make_passage(family=2, group=2)])

    def test_rejects_false_nli_flag(self):
        self.rejects("invalid_nli_evidence_flags", [make_passage(family=1, group=1, nli_evaluated=False), make_passage(family=2, group=2)])

    def test_rejects_premature_independence_in_passage(self):
        self.rejects("invalid_nli_evidence_flags", [make_passage(family=1, group=1, independently_verified=True), make_passage(family=2, group=2)])

    def test_rejects_premature_independence_in_report(self):
        self.rejects("upstream_report_claims_independence", report_changes={"independent_corroboration_established": True})

    def test_rejects_incorrect_nli_threshold_flag(self):
        self.rejects("nli_threshold_flag_mismatch", [make_passage(family=1, group=1, nli_threshold_passed=False), make_passage(family=2, group=2)])

    def test_rejects_forged_label(self):
        self.rejects("nli_label_or_confidence_mismatch", [make_passage(family=1, group=1, nli_label="CONTRADICTION"), make_passage(family=2, group=2)])

    def test_rejects_nan_probability(self):
        self.rejects("invalid_nli_scores", [make_passage(family=1, group=1, entailment=float("nan")), make_passage(family=2, group=2)])

    def test_rejects_invalid_probability_distribution(self):
        self.rejects("invalid_nli_distribution", [make_passage(family=1, group=1, entailment=.8), make_passage(family=2, group=2)])

    def test_rejects_future_retrieval(self):
        self.rejects("invalid_retrieval_time", [make_passage(family=1, group=1, retrieved_at=NOW + timedelta(days=1)), make_passage(family=2, group=2)])

    def test_rejects_naive_assessment_date(self):
        self.rejects("invalid_assessment_time", report_changes={"assessed_at": datetime(2026, 10, 20)})

    def test_rejects_fake_family_count(self):
        self.rejects("missing_risk_families", [make_passage(family=1, group=1), make_passage(family=1, group=2), make_passage(family=2, group=3)], report_changes={"dependency_risk_family_count": 3})

    def test_rejects_source_divided_between_risk_families(self):
        a = make_passage(family=1, group=1)
        b = make_passage(family=2, group=2, source_id=a.source_id)
        self.rejects("same_source_split_across_risk_families", [a, b])

    def test_rejects_publisher_divided_between_risk_families(self):
        a = make_passage(family=1, group=1)
        b = make_passage(family=2, group=2, domain=a.publisher_domain)
        self.rejects("same_publisher_split_across_risk_families", [a, b])

    def test_rejects_duplicate_group_number_gaps(self):
        a = make_passage(family=1, group=1)
        b = make_passage(family=2, group=1)
        c = make_passage(family=3, group=3)
        self.rejects("invalid_duplicate_group_numbering", [a, b, c])

    def test_rejects_nonconsecutive_risk_families(self):
        a = make_passage(family=1, group=1)
        b = make_passage(family=3, group=2)
        self.rejects("invalid_family_or_duplicate_group", [a, b])

    def test_rejects_unverified_provenance_is_not_source_proof(self):
        a = make_passage(family=1, group=1, independent_corroboration_established=True)
        b = make_passage(family=2, group=2)
        self.rejects("invalid_nli_evidence_flags", [a, b])

    def test_rejects_invalid_threshold(self):
        self.rejects("invalid_threshold", report_changes={"nli_threshold": float("nan")})

    def test_rejects_two_urls_for_same_immutable_document_version(self):
        a = make_passage(family=1, group=1)
        b = make_passage(family=1, group=2, document_version_id=a.document_version_id,
                         article_url="https://paper-1.example.org/another-page")
        self.rejects("document_version_identity_mismatch", [a, b])

    def test_rejects_source_id_with_changed_publisher_identity(self):
        a = make_passage(family=1, group=1)
        b = make_passage(family=1, group=2, source_id=a.source_id, domain="other.example.org")
        self.rejects("source_domain_mismatch", [a, b])

    def test_rejects_unsafe_url(self):
        self.rejects("invalid_article_url", [make_passage(family=1, group=1, article_url="http://localhost/news"), make_passage(family=2, group=2)])


if __name__ == "__main__":
    unittest.main()
