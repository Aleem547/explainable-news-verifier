"""Phase 13D.4: full-snapshot dependency risks; no external calls or DB."""
from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from ml.verification.external_source_dependencies import (
    ReportedDependency, ReportedDependencyKind, SourceDependencyError,
    assess_external_source_dependencies,
)
from ml.verification.source_independence import Snapshot

NOW = datetime(2026, 10, 20, 12, tzinfo=UTC)
NEWS = (
    "The coastal bridge reopened after detailed engineering inspections confirmed "
    "that structural repairs were finished on Wednesday afternoon. Local officials "
    "reviewed the inspection documentation and released the report to residents. "
    "The city transport office monitored traffic and provided an independent "
    "summary of what engineers observed during the inspection period. "
) * 3
OTHER = (
    "A farming cooperative published a new soil testing protocol to help orchard "
    "owners evaluate irrigation and fertilizer treatments without relying on "
    "unverified weather forecasts. The report describes sampling methods, "
    "laboratory measurements, and a timetable for the seasonal review. "
) * 3


def snap(text=NEWS, *, source_id=None, **kwargs):
    return Snapshot(version_id=uuid4(), source_id=source_id or uuid4(), text=text, **kwargs)


def link(a, b, kind=ReportedDependencyKind.SHARED_WIRE_REPORT, **kwargs):
    return ReportedDependency(a.version_id, b.version_id, kind,
        kwargs.get("observation_url", "https://publisher.example.org/corrections/report"),
        kwargs.get("observed_at", NOW))


class DependencyRules(unittest.TestCase):
    def assess(self, a, b, *rest, reported_links=(), assessed_at=NOW):
        return assess_external_source_dependencies([a, b, *rest],
                                                    assessed_at=assessed_at,
                                                    reported_links=reported_links)

    def test_different_domains_not_independence(self):
        result = self.assess(snap(NEWS), snap(OTHER))
        self.assertEqual(result.independence_status, "NOT_ESTABLISHED")
        self.assertFalse(result.independent_corroboration_established)
        self.assertFalse(result.independently_verified)
        self.assertFalse(result.nli_evaluated)
        self.assertEqual(len(result.risk_families), 2)
        self.assertTrue(result.pairs[0].requires_review)
        self.assertIn("DISTINCT_DOMAINS_DO_NOT_PROVE_INDEPENDENCE", result.warnings)

    def test_same_publisher_is_one_risk_family(self):
        source_id = uuid4()
        result = self.assess(snap(NEWS, source_id=source_id), snap(OTHER, source_id=source_id))
        self.assertEqual(result.risk_family_count, 1)
        self.assertEqual(result.pairs[0].relationship, "SAME_PUBLISHER")
        self.assertTrue(result.pairs[0].grouped_as_dependency_risk)

    def test_identical_article_text_across_publishers(self):
        result = self.assess(snap(NEWS), snap(NEWS))
        self.assertEqual(result.risk_family_count, 1)
        self.assertEqual(result.pairs[0].relationship, "IDENTICAL_TEXT")

    def test_short_identical_full_snapshot_detected(self):
        text = "This report confirms the coastal bridge reopened after inspection."
        result = self.assess(snap(text), snap(text))
        self.assertEqual(result.pairs[0].relationship, "IDENTICAL_SHORT_SNAPSHOT")
        self.assertEqual(result.risk_family_count, 1)

    def test_short_distinct_text_not_grouped(self):
        result = self.assess(snap("Bridge reopened after inspection Wednesday."),
                             snap("Bridge closed after inspection Thursday."))
        self.assertEqual(result.risk_family_count, 2)

    def test_near_text_is_review_only(self):
        result = self.assess(snap(NEWS), snap(NEWS + " Additional details follow soon."))
        self.assertEqual(result.pairs[0].relationship, "POSSIBLE_TEXT_REUSE")
        self.assertFalse(result.pairs[0].grouped_as_dependency_risk)
        self.assertTrue(result.pairs[0].requires_review)
        self.assertIn("POSSIBLE_SYNDICATION_REQUIRES_REVIEW", result.warnings)
        self.assertFalse(result.independent_corroboration_established)

    def test_common_reported_origin_groups_but_not_verifies(self):
        a = snap(NEWS, reported_origin_url="https://wire.example.org/story",
                 origin_observation_url="https://paper-a.example.org/credits")
        b = snap(OTHER, reported_origin_url="https://wire.example.org/story",
                 origin_observation_url="https://paper-b.example.org/credits")
        result = self.assess(a, b)
        self.assertEqual(result.pairs[0].relationship, "DECLARED_COMMON_ORIGIN")
        self.assertEqual(result.risk_family_count, 1)
        self.assertIn("ORIGIN_ATTRIBUTION_NOT_INDEPENDENTLY_VERIFIED", result.warnings)

    def test_reported_wire_link_keeps_observation_and_groups(self):
        a, b = snap(NEWS), snap(OTHER)
        observed = link(a, b)
        result = self.assess(a, b, reported_links=[observed])
        self.assertEqual(result.risk_family_count, 1)
        self.assertEqual(result.pairs[0].relationship, "REPORTED_SHARED_WIRE_REPORT")
        self.assertEqual(result.pairs[0].observed_url, observed.observation_url)
        self.assertTrue(result.pairs[0].requires_review)
        self.assertIn("REPORTED_RELATIONSHIP_REQUIRES_VERIFICATION", result.warnings)

    def test_reported_common_owner_groups_risk_not_truth(self):
        a, b = snap(NEWS), snap(OTHER)
        result = self.assess(a, b, reported_links=[link(a, b, ReportedDependencyKind.SHARED_PUBLISHER_OWNER)])
        self.assertEqual(result.risk_family_count, 1)
        self.assertFalse(result.independent_corroboration_established)

    def test_reported_shared_primary_source_is_risk(self):
        a, b = snap(NEWS), snap(OTHER)
        result = self.assess(a, b, reported_links=[link(a, b, ReportedDependencyKind.SHARED_PRIMARY_SOURCE)])
        self.assertEqual(result.pairs[0].relationship, "REPORTED_SHARED_PRIMARY_SOURCE")

    def test_duplicate_snapshot_id_fails(self):
        a = snap()
        with self.assertRaises(SourceDependencyError):
            self.assess(a, replace(a, source_id=uuid4()))

    def test_too_many_snapshots_fails(self):
        with self.assertRaises(SourceDependencyError):
            assess_external_source_dependencies([snap() for _ in range(21)], assessed_at=NOW)

    def test_naive_assessment_date_fails(self):
        with self.assertRaises(SourceDependencyError):
            self.assess(snap(), snap(), assessed_at=datetime(2026, 10, 20))

    def test_invalid_origin_without_observation_fails(self):
        a = snap(reported_origin_url="https://wire.example.org/report")
        with self.assertRaises(SourceDependencyError):
            self.assess(a, snap())

    def test_insecure_reported_origin_fails(self):
        a = snap(reported_origin_url="http://wire.example.org/report",
                 origin_observation_url="https://paper.example.org/credits")
        with self.assertRaises(SourceDependencyError):
            self.assess(a, snap())

    def test_unrelated_reported_link_fails(self):
        a, b, c = snap(), snap(), snap()
        with self.assertRaises(SourceDependencyError):
            self.assess(a, b, reported_links=[link(a, c)])

    def test_duplicate_link_pair_reversed_fails(self):
        a, b = snap(), snap()
        with self.assertRaises(SourceDependencyError):
            self.assess(a, b, reported_links=[link(a, b), link(b, a)])

    def test_future_observation_fails(self):
        a, b = snap(), snap()
        with self.assertRaises(SourceDependencyError):
            self.assess(a, b, reported_links=[link(a, b, observed_at=NOW+timedelta(days=1))])

    def test_invalid_observation_url_fails(self):
        a, b = snap(), snap()
        with self.assertRaises(SourceDependencyError):
            self.assess(a, b, reported_links=[link(a, b, observation_url="http://example.org/insecure")])

    def test_no_unbounded_article_text(self):
        with self.assertRaises(SourceDependencyError):
            self.assess(snap("word " * 22000), snap())

    def test_permutation_stability(self):
        a, b, c = snap(NEWS), snap(OTHER), snap(NEWS)
        first = self.assess(a, b, c)
        second = self.assess(c, b, a)
        self.assertEqual(first.risk_families, second.risk_families)
        self.assertEqual(first.pairs, second.pairs)

    def test_transitive_same_origin_and_publisher_grouping(self):
        one_source = uuid4()
        a = snap(NEWS, source_id=one_source)
        b = snap(OTHER, source_id=one_source)
        c = snap(OTHER)
        result = self.assess(a, b, c)
        self.assertEqual(result.risk_family_count, 1)
        self.assertEqual(len(result.pairs), 3)

    def test_zero_manual_links_do_not_imply_absence_of_dependency(self):
        report = self.assess(snap(NEWS), snap(OTHER))
        self.assertIn("UNKNOWN_RELATIONSHIPS_CANNOT_BE_COUNTED_AS_INDEPENDENT", report.warnings)


if __name__ == "__main__":
    unittest.main()
