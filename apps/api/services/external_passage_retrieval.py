"""Phase 13D.1: read-only lexical retrieval over authorized article snapshots.

Discovery snippets and search metadata are NEVER eligible. This module does not
fetch URLs, run NLI, infer source independence, or write to the database.

PostgreSQL FTS is a baseline, not semantic retrieval. An index and benchmark
are required before this is used on a large external article corpus.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from uuid import UUID

from sqlalchemy import and_, desc, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.db.enums import DocumentType
from apps.api.db.models.document import Document
from apps.api.db.models.document_passage import DocumentPassage
from apps.api.db.models.document_version import DocumentVersion
from apps.api.db.models.retrieval_observation import RetrievalObservation
from apps.api.db.models.source import Source


class ExternalRetrievalError(ValueError):
    """Read-only retrieval input or stored provenance validation failure."""


@dataclass(frozen=True, slots=True)
class ExternalPassageCandidate:
    rank: int
    passage_id: UUID
    document_version_id: UUID
    document_id: UUID
    source_id: UUID
    publisher_name: str
    publisher_domain: str
    original_url: str
    retrieved_at: datetime
    passage_text: str
    passage_sha256: str
    lexical_relevance_score: float
    retrieval_method: str = "postgres_english_fts_v1"
    independently_verified: bool = False
    nli_evaluated: bool = False
    independent_corroboration_established: bool = False


# Only select a few informative words from the bounded claim. This is an OR
# retrieval query for candidate *recall*, never a criterion for claim support.
_STOP_WORDS = frozenset(
    "a an and are as at be been being by can did do does for from had has have "
    "in into is it its of on or our that the their there these this those to was "
    "were what when where which who will with would not no they them he she we you"
    .split()
)


def build_lexical_query(claim: str) -> str:
    """Return a bounded server-generated websearch OR query (never raw SQL)."""
    if not isinstance(claim, str) or not 3 <= len(claim.strip()) <= 5000:
        raise ExternalRetrievalError("invalid_claim_length")
    words: list[str] = []
    for word in re.findall(r"[A-Za-z0-9]{3,40}", claim.casefold()):
        if word not in _STOP_WORDS and word not in words:
            words.append(word)
        if len(words) >= 12:
            break
    if not words:
        raise ExternalRetrievalError("no_searchable_claim_terms")
    return " OR ".join(words)


def build_external_retrieval_stmt(claim: str, *, candidate_limit: int = 60):
    """Produce parameterized, read-only SQL over latest vetted article snapshots.

    The EXISTS guard prevents a discovery-only document from entering retrieval.
    It requires the Phase 13C secure-fetch observation, marked unverified.
    """
    if not 1 <= candidate_limit <= 100:
        raise ExternalRetrievalError("invalid_candidate_limit")
    query = build_lexical_query(claim)
    document_fts = func.to_tsvector("english", DocumentPassage.text)
    search = func.websearch_to_tsquery("english", query)
    relevance = func.ts_rank_cd(document_fts, search).label("lexical_rank")
    latest = (
        select(DocumentVersion.id)
        .where(DocumentVersion.document_id == Document.id)
        .order_by(DocumentVersion.version_number.desc(), DocumentVersion.id.desc())
        .limit(1)
        .correlate(Document)
        .scalar_subquery()
    )
    eligible_fetch = exists(
        select(RetrievalObservation.id).where(
            and_(
                RetrievalObservation.document_id == Document.id,
                RetrievalObservation.document_version_id == DocumentVersion.id,
                RetrievalObservation.source_id == Source.id,
                RetrievalObservation.provider == "secure_article_fetch_v1",
                RetrievalObservation.outcome == "FETCHED",
                RetrievalObservation.final_url == Document.url,
                RetrievalObservation.metadata_json["independently_verified"].as_boolean().is_(False),
            )
        )
    )
    return (
        select(
            DocumentPassage.id.label("passage_id"),
            DocumentPassage.document_version_id,
            DocumentPassage.start_offset,
            DocumentPassage.end_offset,
            DocumentPassage.text.label("passage_text"),
            DocumentPassage.passage_sha256,
            DocumentVersion.document_id,
            DocumentVersion.original_url,
            DocumentVersion.content_text,
            DocumentVersion.content_sha256,
            DocumentVersion.retrieved_at,
            Source.id.label("source_id"),
            Source.name.label("publisher_name"),
            Source.domain.label("publisher_domain"),
            relevance,
        )
        .select_from(DocumentPassage)
        .join(DocumentVersion, DocumentPassage.document_version_id == DocumentVersion.id)
        .join(Document, DocumentVersion.document_id == Document.id)
        .join(Source, Document.source_id == Source.id)
        .where(
            Document.document_type == DocumentType.ARTICLE,
            Source.is_active.is_(True),
            DocumentVersion.id == latest,
            DocumentVersion.original_url == Document.url,
            eligible_fetch,
            document_fts.op("@@")(search),
        )
        .order_by(desc(relevance), DocumentVersion.retrieved_at.desc(), DocumentPassage.id.asc())
        .limit(candidate_limit)
    )


def _validate_row(row: object) -> None:
    """Fail closed for corrupt snapshots rather than return misleading passages."""
    if (
        not isinstance(row.content_text, str)
        or sha256(row.content_text.encode("utf-8")).hexdigest() != row.content_sha256
        or not isinstance(row.passage_text, str)
        or sha256(row.passage_text.encode("utf-8")).hexdigest() != row.passage_sha256
        or not isinstance(row.start_offset, int)
        or not isinstance(row.end_offset, int)
        or not (0 <= row.start_offset < row.end_offset <= len(row.content_text))
        or row.content_text[row.start_offset : row.end_offset] != row.passage_text
        or not isinstance(row.retrieved_at, datetime)
        or row.retrieved_at.tzinfo is None
        or row.retrieved_at.utcoffset() is None
        or not isinstance(row.original_url, str)
        or not row.original_url.startswith("https://")
        or not isinstance(row.publisher_domain, str)
        or not row.publisher_domain.strip()
    ):
        raise ExternalRetrievalError("stored_passage_provenance_invalid")


async def retrieve_external_passages(
    session: AsyncSession,
    *,
    claim: str,
    top_k: int = 10,
    candidate_limit: int = 60,
) -> tuple[ExternalPassageCandidate, ...]:
    """Read only: lexical candidate ranking, not source credibility or NLI.

    Do not call this on unbounded data until a PostgreSQL text-search index and
    EXPLAIN ANALYZE benchmarking are in place. Later 13D stages add reranking.
    """
    if not 1 <= top_k <= 20 or candidate_limit < top_k:
        raise ExternalRetrievalError("invalid_result_limits")
    statement = build_external_retrieval_stmt(claim, candidate_limit=candidate_limit)
    rows = (await session.execute(statement)).all()
    results: list[ExternalPassageCandidate] = []
    seen: set[UUID] = set()
    for row in rows:
        _validate_row(row)
        if row.passage_id in seen:
            continue
        seen.add(row.passage_id)
        if len(results) >= top_k:
            break
        score = float(row.lexical_rank)
        if not 0 < score < float("inf"):
            raise ExternalRetrievalError("invalid_lexical_rank")
        results.append(
            ExternalPassageCandidate(
                rank=len(results) + 1,
                passage_id=row.passage_id,
                document_version_id=row.document_version_id,
                document_id=row.document_id,
                source_id=row.source_id,
                publisher_name=row.publisher_name,
                publisher_domain=row.publisher_domain,
                original_url=row.original_url,
                retrieved_at=row.retrieved_at,
                passage_text=row.passage_text,
                passage_sha256=row.passage_sha256,
                lexical_relevance_score=score,
            )
        )
    return tuple(results)
