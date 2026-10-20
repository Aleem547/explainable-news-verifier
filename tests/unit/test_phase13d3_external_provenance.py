"""Phase 13D.3 unit tests. No DB or external network required."""
from __future__ import annotations

import asyncio
import dataclasses
import math
import unittest
from datetime import datetime, timezone
from hashlib import sha256
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy.dialects import postgresql

from apps.api.services.external_passage_retrieval import ExternalPassageCandidate
from apps.api.services.external_evidence_provenance import (
    AuditedExternalPassage, ExternalProvenanceError,
    _validate_stored_record, audit_external_passage_provenance,
    build_external_provenance_statement,
)

UTC = timezone.utc
T = datetime(2026, 10, 20, 8, 0, tzinfo=UTC)


def fixture():
    passage = "A trusted observation is not the same as independent confirmation."
    text = "Before. " + passage + " After."
    offset = text.index(passage)
    pid, vid, did, sid, oid = (uuid4() for _ in range(5))
    candidate = ExternalPassageCandidate(
        rank=1, passage_id=pid, document_version_id=vid, document_id=did,
        source_id=sid, publisher_name="Example News", publisher_domain="example.org",
        original_url="https://news.example.org/story", retrieved_at=T,
        passage_text=passage, passage_sha256=sha256(passage.encode()).hexdigest(),
        lexical_relevance_score=0.32,
    )
    record = SimpleNamespace(
        passage_id=pid, document_version_id=vid, passage_text=passage,
        passage_sha256=candidate.passage_sha256, start_offset=offset,
        end_offset=offset + len(passage), version_id=vid, document_id=did,
        version_number=2, original_url=candidate.original_url, content_text=text,
        content_sha256=sha256(text.encode()).hexdigest(), retrieved_at=T,
        published_at_snapshot=T, parent_document_id=did,
        document_url=candidate.original_url, document_source_id=sid,
        source_id=sid, publisher_name=candidate.publisher_name,
        publisher_domain=candidate.publisher_domain, observation_id=oid,
        observation_document_id=did, observation_version_id=vid,
        observation_source_id=sid, fetch_final_url=candidate.original_url,
        fetch_provider="secure_article_fetch_v1", fetch_outcome="FETCHED",
        fetch_metadata={"independently_verified": False}, fetch_observed_at=T,
    )
    return candidate, record


class _Session:
    def __init__(self, rows):
        self.rows = rows
        self.queries = []
    async def execute(self, statement):
        self.queries.append(statement)
        return SimpleNamespace(all=lambda: self.rows)
    async def commit(self):
        raise AssertionError("Read-only provenance audit must never commit")
    async def flush(self):
        raise AssertionError("Read-only provenance audit must never flush")


class ProvenanceUnitTests(unittest.TestCase):
    def audit(self, candidates, records):
        session = _Session(records)
        result = asyncio.run(audit_external_passage_provenance(session, candidates))
        return result, session

    def test_success_preserves_attribution_without_attesting_truth(self):
        candidate, record = fixture()
        result, sess = self.audit([candidate], [record])
        self.assertEqual(len(sess.queries), 1)
        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], AuditedExternalPassage)
        self.assertEqual(result[0].fetch_observation_id, record.observation_id)
        self.assertEqual(result[0].snapshot_sha256, record.content_sha256)
        self.assertTrue(result[0].traceable)
        self.assertFalse(result[0].nli_evaluated)
        self.assertFalse(result[0].independent_corroboration_established)
        self.assertFalse(result[0].independently_verified)

    def test_empty_batch_makes_no_db_query(self):
        result, session = self.audit([], [])
        self.assertEqual(result, ())
        self.assertEqual(session.queries, [])

    def test_returns_input_order_not_database_order(self):
        a, r1 = fixture()
        b, r2 = fixture()
        out, _ = self.audit([a, b], [r2, r1])
        self.assertEqual([x.candidate.passage_id for x in out], [a.passage_id, b.passage_id])

    def test_missing_fetch_is_fail_closed(self):
        a, _ = fixture()
        with self.assertRaisesRegex(ExternalProvenanceError, "missing_or_unfetched"):
            self.audit([a], [])

    def test_duplicate_input_is_rejected(self):
        a, r = fixture()
        with self.assertRaisesRegex(ExternalProvenanceError, "duplicate_passage"):
            self.audit([a, a], [r])

    def test_duplicate_db_record_rejected(self):
        a, r = fixture()
        with self.assertRaisesRegex(ExternalProvenanceError, "nonunique"):
            self.audit([a], [r, r])

    def test_large_batch_rejected_before_db(self):
        a, r = fixture()
        with self.assertRaisesRegex(ExternalProvenanceError, "invalid_candidate_batch"):
            self.audit([dataclasses.replace(a, passage_id=uuid4()) for _ in range(21)], [r])

    def test_candidate_already_assessed_rejected(self):
        a, r = fixture()
        for flag in ("independently_verified", "nli_evaluated", "independent_corroboration_established"):
            with self.subTest(flag=flag), self.assertRaises(ExternalProvenanceError):
                self.audit([dataclasses.replace(a, **{flag: True})], [r])

    def test_candidate_hash_tampering_rejected(self):
        a, r = fixture()
        with self.assertRaises(ExternalProvenanceError):
            self.audit([dataclasses.replace(a, passage_text=a.passage_text + "x")], [r])

    def test_candidate_nonpublic_url_rejected(self):
        a, r = fixture()
        for url in ("http://news.example.org/story", "https://localhost/story", "https://example.org.evil.net/x", "https://user:pass@news.example.org/story", "https://news.example.org:8443/story"):
            with self.subTest(url=url), self.assertRaises(ExternalProvenanceError):
                self.audit([dataclasses.replace(a, original_url=url)], [r])

    def test_candidate_rejects_unbounded_relevance(self):
        a, r = fixture()
        for score in (math.nan, math.inf, 0, -1):
            with self.subTest(score=score), self.assertRaises(ExternalProvenanceError):
                self.audit([dataclasses.replace(a, lexical_relevance_score=score)], [r])

    def test_mismatched_publisher_and_source_ids(self):
        a, r = fixture()
        for key, value in (("publisher_domain", "other.org"), ("document_source_id", uuid4()), ("observation_source_id", uuid4()), ("publisher_name", "Wrong News")):
            with self.subTest(key=key), self.assertRaises(ExternalProvenanceError):
                original = getattr(r, key)
                setattr(r, key, value)
                try: self.audit([a], [r])
                finally: setattr(r, key, original)

    def test_mismatched_document_and_snapshot_ids(self):
        a, r = fixture()
        for key in ("parent_document_id", "version_id", "observation_document_id", "observation_version_id"):
            with self.subTest(key=key), self.assertRaises(ExternalProvenanceError):
                old = getattr(r, key)
                setattr(r, key, uuid4())
                try: self.audit([a], [r])
                finally: setattr(r, key, old)

    def test_redirected_final_url_rejected(self):
        a, r = fixture()
        r.fetch_final_url = "https://elsewhere.example.org/syndication"
        with self.assertRaisesRegex(ExternalProvenanceError, "source_attribution"):
            self.audit([a], [r])

    def test_version_hash_tampering_rejected(self):
        a, r = fixture()
        r.content_text += "changed"
        with self.assertRaisesRegex(ExternalProvenanceError, "stored_snapshot"):
            self.audit([a], [r])

    def test_offsets_tampering_rejected(self):
        a, r = fixture()
        r.start_offset += 1
        with self.assertRaisesRegex(ExternalProvenanceError, "stored_snapshot"):
            self.audit([a], [r])

    def test_stored_passage_hash_tampering_rejected(self):
        a, r = fixture()
        r.passage_sha256 = "f" * 64
        with self.assertRaises(ExternalProvenanceError):
            self.audit([a], [r])

    def test_missing_verified_false_marker_fails_closed(self):
        a, r = fixture()
        for meta in ({}, {"independently_verified": True}, {"independently_verified": "false"}):
            with self.subTest(meta=meta), self.assertRaisesRegex(ExternalProvenanceError, "invalid_fetch"):
                r.fetch_metadata = meta
                self.audit([a], [r])

    def test_naive_snapshot_or_fetch_time_rejected(self):
        a, r = fixture()
        for key in ("retrieved_at", "fetch_observed_at", "published_at_snapshot"):
            with self.subTest(key=key), self.assertRaises(ExternalProvenanceError):
                old = getattr(r, key)
                setattr(r, key, old.replace(tzinfo=None))
                try: self.audit([a], [r])
                finally: setattr(r, key, old)

    def test_query_is_parameterized_and_read_only(self):
        a, _ = fixture()
        sql = str(build_external_provenance_statement([a.passage_id]).compile(dialect=postgresql.dialect()))
        self.assertIn("SELECT", sql)
        self.assertIn("retrieval_observations", sql)
        self.assertIn("document_versions", sql)
        self.assertIn("__\u005bPOSTCOMPILE", sql)
        self.assertNotIn(str(a.passage_id), sql)
        for keyword in ("INSERT ", "DELETE ", "UPDATE "):
            self.assertNotIn(keyword, sql)

    def test_bad_id_batches_rejected(self):
        a, _ = fixture()
        for ids in ([], [a.passage_id, a.passage_id], ["not UUID"], [uuid4() for _ in range(21)]):
            with self.subTest(ids=ids), self.assertRaises(ExternalProvenanceError):
                build_external_provenance_statement(ids)


if __name__ == "__main__":
    unittest.main()
