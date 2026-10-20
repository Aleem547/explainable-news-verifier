"""Offline checks for bounded SQL construction and fail-closed passage auditing."""

import unittest
from datetime import UTC, datetime
from hashlib import sha256
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from sqlalchemy.dialects import postgresql

from apps.api.services.external_passage_retrieval import (
    ExternalRetrievalError,
    build_external_retrieval_stmt,
    build_lexical_query,
    retrieve_external_passages,
)


TEXT = "The renewable energy council confirmed a solar project near the coastal city."


def row(*, text=TEXT, snapshot=None, offset=0, score=0.5, **overrides):
    snapshot = snapshot if snapshot is not None else text
    values = dict(
        passage_id=uuid4(), document_version_id=uuid4(), document_id=uuid4(),
        source_id=uuid4(), publisher_name="Local Press",
        publisher_domain="example.org", original_url="https://example.org/test-report",
        retrieved_at=datetime.now(UTC),
        passage_text=text,
        passage_sha256=sha256(text.encode()).hexdigest(),
        start_offset=offset, end_offset=offset + len(text),
        content_text=snapshot,
        content_sha256=sha256(snapshot.encode()).hexdigest(), lexical_rank=score,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


class FtsTest(unittest.TestCase):
    def test_or_query_removes_duplicate_and_stopwords(self):
        self.assertEqual(build_lexical_query("The Paris Tower is in Paris"), "paris OR tower")

    def test_query_rejects_empty_and_unsupported(self):
        for invalid in ("", "is the of", "x" * 5001, None):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ExternalRetrievalError):
                    build_lexical_query(invalid)

    def test_long_query_is_bounded_to_12_tokens(self):
        self.assertEqual(len(build_lexical_query(" ".join(f"token{i}" for i in range(50))).split(" OR ")), 12)

    def test_bound_candidates(self):
        for limit in (0, 101):
            with self.assertRaises(ExternalRetrievalError):
                build_external_retrieval_stmt("Climate energy", candidate_limit=limit)

    def test_parameterized_query_no_user_string_in_sql(self):
        statement = build_external_retrieval_stmt("Paris' suspicious;text --", candidate_limit=40)
        sql = str(statement.compile(dialect=postgresql.dialect()))
        self.assertNotIn("suspicious", sql)
        self.assertIn("websearch_to_tsquery", sql)
        self.assertIn("to_tsvector", sql)
        self.assertIn("secure_article_fetch_v1", statement.compile(dialect=postgresql.dialect()).params.values())

    def test_requires_live_full_text_observation(self):
        compiled = build_external_retrieval_stmt("Renewable solar energy").compile(dialect=postgresql.dialect())
        sql = str(compiled)
        values = list(compiled.params.values())
        self.assertIn("retrieval_observations", sql)
        self.assertIn("FETCHED", values)
        self.assertIn("independently_verified", values)
        self.assertIn("document_versions", sql)
        self.assertIn("is_active", sql)
        self.assertNotIn("discovery_records", sql)


class AsyncSearchTest(unittest.IsolatedAsyncioTestCase):
    def make_session(self, *rows):
        session = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(all=lambda: list(rows))))
        return session

    async def test_returns_scored_unverified_candidate(self):
        source = row()
        response = await retrieve_external_passages(self.make_session(source), claim="Renewable solar")
        self.assertEqual(len(response), 1)
        hit = response[0]
        self.assertEqual(hit.original_url, "https://example.org/test-report")
        self.assertEqual(hit.passage_sha256, source.passage_sha256)
        self.assertEqual(hit.rank, 1)
        self.assertFalse(hit.independently_verified)
        self.assertFalse(hit.nli_evaluated)
        self.assertFalse(hit.independent_corroboration_established)
        self.assertEqual(hit.retrieval_method, "postgres_english_fts_v1")

    async def test_empty_result(self):
        self.assertEqual(await retrieve_external_passages(self.make_session(), claim="Solar energy"), ())

    async def test_limit_validation_prevents_db_access(self):
        session = self.make_session()
        for k, cap in ((0, 60), (21, 60), (10, 9)):
            with self.subTest(k=k, cap=cap):
                with self.assertRaises(ExternalRetrievalError):
                    await retrieve_external_passages(session, claim="Solar energy", top_k=k, candidate_limit=cap)
        session.execute.assert_not_called()

    async def test_deduplicates_and_bounds_output(self):
        a, b, c = row(), row(), row()
        response = await retrieve_external_passages(self.make_session(a, a, b, c), claim="Solar energy", top_k=2)
        self.assertEqual([r.passage_id for r in response], [a.passage_id, b.passage_id])
        self.assertEqual([r.rank for r in response], [1, 2])

    async def test_hash_tampering_fails_closed(self):
        invalid = row(content_sha256="0" * 64)
        with self.assertRaisesRegex(ExternalRetrievalError, "stored_passage_provenance_invalid"):
            await retrieve_external_passages(self.make_session(invalid), claim="Solar energy")

    async def test_offset_tampering_fails_closed(self):
        invalid = row(start_offset=3)
        with self.assertRaisesRegex(ExternalRetrievalError, "stored_passage_provenance_invalid"):
            await retrieve_external_passages(self.make_session(invalid), claim="Solar energy")

    async def test_rejects_http_and_naive_times(self):
        for candidate in (row(original_url="http://example.org"), row(retrieved_at=datetime.now().replace(tzinfo=None))):
            with self.assertRaises(ExternalRetrievalError):
                await retrieve_external_passages(self.make_session(candidate), claim="Solar energy")

    async def test_rejects_nonpositive_nan_and_inf_scores(self):
        for score in (0, -1, float('nan'), float('inf')):
            with self.subTest(score=score):
                with self.assertRaises(ExternalRetrievalError):
                    await retrieve_external_passages(self.make_session(row(score=score)), claim="Solar energy")


if __name__ == "__main__":
    unittest.main()
