"""Real NLI orchestration/ML dependency rules with explicit audit/model fixtures."""

import sys
from types import ModuleType
import unittest
from unittest.mock import patch

from apps.api.services.external_evidence_nli import assess_external_evidence_nli, ExternalNliError
from ml.verification.external_source_dependencies import (
    ReportedDependency, ReportedDependencyKind, SourceDependencyError, assess_external_source_dependencies,
)
from ml.verification.source_independence import Snapshot
from test_phase13d5_external_evidence_nli import setup, NOW


class ReportedDependencyNliTests(unittest.IsolatedAsyncioTestCase):
    async def execute(self, *, links="default", legacy=False):
        args = setup()
        candidates = tuple(a.candidate for a in args["audits"])
        declaration = ReportedDependency(
            candidates[0].document_version_id, candidates[1].document_version_id,
            ReportedDependencyKind.CROSS_PUBLICATION_ATTRIBUTION,
            "https://www.nist.gov/news-events/news/reviewed-source", NOW,
        )
        supplied = (declaration,) if links == "default" else links
        seen = []

        async def audit(session, rows):
            return tuple(args["audits"])

        async def dependencies(session, rows, *, assessed_at, reported_links=()):
            seen.extend(reported_links)
            return assess_external_source_dependencies(
                [Snapshot(c.document_version_id, c.source_id, c.passage_text) for c in rows],
                assessed_at=assessed_at, reported_links=reported_links,
            )

        async def legacy_dependencies(session, rows, *, assessed_at):
            return assess_external_source_dependencies(
                [Snapshot(c.document_version_id, c.source_id, c.passage_text) for c in rows], assessed_at=assessed_at,
            )

        imports = {}
        for name, attr, method in (
            ("apps.api.services.external_evidence_provenance", "audit_external_passage_provenance", audit),
            ("apps.api.services.external_evidence_normalization", "normalize_and_group_external_evidence", lambda rows: args["normalization"]),
            ("apps.api.services.external_source_independence", "audit_external_source_dependencies", legacy_dependencies if legacy else dependencies),
        ):
            module = ModuleType(name)
            setattr(module, attr, method)
            imports[name] = module

        class Predictor:
            def predict(self, claim, texts):
                return args["predictions"]

        with patch.dict(sys.modules, imports):
            result = await assess_external_evidence_nli(object(), claim=args["claim"], candidates=candidates,
                                                        predictor=Predictor(), assessed_at=NOW, reported_links=supplied)
        return result, seen, declaration

    async def test_reported_attribution_collapses_two_versions_to_one_risk_family(self):
        report, seen, declaration = await self.execute()
        self.assertEqual(seen, [declaration])
        self.assertEqual(report.dependency_risk_family_count, 1)
        self.assertEqual({row.dependency_risk_family for row in report.evidence}, {1})

    async def test_reported_link_warning_and_negative_flags_are_preserved(self):
        report, _, _ = await self.execute()
        self.assertIn("REPORTED_DEPENDENCIES_ARE_UNAUTHENTICATED_DECLARATIONS", report.warnings)
        self.assertFalse(report.independent_corroboration_established)
        self.assertFalse(report.independently_verified)
        self.assertNotIn("NO_NLI_OR_TRUTH_ASSESSMENT", report.warnings)

    async def test_empty_link_input_preserves_legacy_auditor_signature(self):
        report, seen, _ = await self.execute(links=(), legacy=True)
        self.assertEqual(report.dependency_risk_family_count, 2)
        self.assertEqual(seen, [])

    async def test_non_sequence_dependency_input_is_refused(self):
        with self.assertRaisesRegex(ExternalNliError, "invalid_reported_dependency_batch"):
            await self.execute(links=None)

    async def test_untyped_reported_link_is_refused_by_dependency_audit(self):
        with self.assertRaises(SourceDependencyError):
            await self.execute(links=("untrusted untyped declaration",))
