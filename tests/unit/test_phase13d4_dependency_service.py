"""Read-only Phase 13D.4 service validation with mocked DB rows."""
from __future__ import annotations

import asyncio
import unittest
from datetime import UTC, datetime
from hashlib import sha256
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from apps.api.db.models.document import Document
from apps.api.db.models.document_version import DocumentVersion
from apps.api.services.external_evidence_provenance import AuditedExternalPassage
from apps.api.services.external_passage_retrieval import ExternalPassageCandidate
from apps.api.services.external_source_independence import audit_external_source_dependencies
from ml.verification.external_source_dependencies import SourceDependencyError

NOW = datetime(2026, 10, 20, 12, tzinfo=UTC)


def fixture(text, domain):
    sid, did, vid, pid, oid = (uuid4() for _ in range(5))
    passage = text[:100]
    candidate = ExternalPassageCandidate(
        rank=1, passage_id=pid, document_version_id=vid, document_id=did,
        source_id=sid, publisher_name=domain, publisher_domain=domain,
        original_url=f"https://{domain}/story", retrieved_at=NOW,
        passage_text=passage, passage_sha256=sha256(passage.encode()).hexdigest(),
        lexical_relevance_score=0.4,
    )
    audited = AuditedExternalPassage(
        candidate=candidate, fetch_observation_id=oid, fetch_observed_at=NOW,
        snapshot_version_number=1, snapshot_sha256=sha256(text.encode()).hexdigest(),
        passage_start_offset=0, passage_end_offset=len(passage),
        reported_publication_at=None,
    )
    version = SimpleNamespace(
        id=vid, document_id=did, original_url=candidate.original_url,
        content_text=text, content_sha256=audited.snapshot_sha256,
        version_number=1, retrieved_at=NOW,
    )
    document = SimpleNamespace(
        id=did, source_id=sid, url=candidate.original_url,
    )
    return candidate, audited, version, document


class Session:
    def __init__(self, fixtures):
        self.rows = {}
        for _, _, version, doc in fixtures:
            self.rows[(DocumentVersion, version.id)] = version
            self.rows[(Document, doc.id)] = doc
        self.calls = []

    async def get(self, model, key):
        self.calls.append((model, key))
        return self.rows.get((model, key))

    async def commit(self):
        raise AssertionError("read-only service cannot commit")

    async def flush(self):
        raise AssertionError("read-only service cannot flush")


class ServiceTests(unittest.TestCase):
    def run_audit(self, fixtures, *, replace_audit=None):
        session = Session(fixtures)
        audited = tuple(row[1] for row in fixtures) if replace_audit is None else replace_audit
        with patch("apps.api.services.external_source_independence.audit_external_passage_provenance", return_value=audited) as mock:
            result = asyncio.run(audit_external_source_dependencies(
                session, [row[0] for row in fixtures], assessed_at=NOW,
            ))
            mock.assert_awaited_once()
        return result, session

    def test_reads_full_snapshot_and_never_claims_independence(self):
        a = fixture("The same complete reporting text published by another website. " * 3, "paper-a.example.org")
        b = fixture("The same complete reporting text published by another website. " * 3, "paper-b.example.org")
        report, sess = self.run_audit([a, b])
        self.assertEqual(report.risk_family_count, 1)
        self.assertFalse(report.independent_corroboration_established)
        self.assertEqual(len(sess.calls), 4)

    def test_rejects_modified_database_snapshot(self):
        a = fixture("The inspection was reported in detail for all local readers. " * 3, "paper-a.example.org")
        b = fixture("The claim was unrelated to reporting from that agency. " * 3, "paper-b.example.org")
        b[2].content_text = "TAMPERED"
        with self.assertRaises(SourceDependencyError):
            self.run_audit([a, b])

    def test_two_passages_one_snapshot_not_two_sources(self):
        a = fixture("The inspection was documented by the national board. " * 3, "paper-a.example.org")
        with self.assertRaises(SourceDependencyError):
            self.run_audit([a, a])

    def test_forged_audit_flags_rejected(self):
        from dataclasses import replace
        a = fixture("The inspection was documented by the national board. " * 3, "paper-a.example.org")
        b = fixture("Another agency published an unrelated explanation. " * 3, "paper-b.example.org")
        audited = [a[1], replace(b[1], independently_verified=True)]
        with self.assertRaises(SourceDependencyError):
            self.run_audit([a, b], replace_audit=audited)

    def test_missing_db_row_rejected(self):
        a = fixture("The inspection was documented by the national board. " * 3, "paper-a.example.org")
        b = fixture("Another agency published an unrelated explanation. " * 3, "paper-b.example.org")
        b[2].document_id = uuid4()
        with self.assertRaises(SourceDependencyError):
            self.run_audit([a, b])

    def test_rejects_one_candidate(self):
        a = fixture("Article content is recorded in the database. " * 3, "paper-a.example.org")
        with self.assertRaises(SourceDependencyError):
            self.run_audit([a])


if __name__ == "__main__":
    unittest.main()
