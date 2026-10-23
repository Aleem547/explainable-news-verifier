param(
    [ValidateRange(1, 500)]
    [int]$Articles = 200,
    [ValidateRange(3, 20)]
    [int]$Samples = 7,
    [ValidateRange(2, 50)]
    [int]$MatchEvery = 10
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$pg = 'explainable-news-verifier-dev-postgres-1'

if (-not (Test-Path (Join-Path $repo 'pyproject.toml'))) {
    throw "Expected project not found at $repo"
}

$running = (docker inspect --format '{{.State.Running}}' $pg 2>$null | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $running -ne 'true') {
    throw "Local PostgreSQL Docker container is not running: $pg"
}

$bindings = docker port $pg 5432/tcp
if ($LASTEXITCODE -ne 0 -or -not ($bindings | Where-Object { $_ -match ':5432$' })) {
    throw 'Expected local Docker PostgreSQL port mapping to 5432 not found.'
}

Push-Location $repo
try {
    $env:PHASE13F_PG_USER = (docker exec $pg printenv POSTGRES_USER | Out-String).Trim()
    $env:PHASE13F_PG_PASSWORD = (docker exec $pg printenv POSTGRES_PASSWORD | Out-String).Trim()
    $env:PHASE13F_PG_DB = (docker exec $pg printenv POSTGRES_DB | Out-String).Trim()
    $env:PHASE13F_BENCH_ARTICLES = [string]$Articles
    $env:PHASE13F_BENCH_SAMPLES = [string]$Samples
    $env:PHASE13F_BENCH_MATCH_EVERY = [string]$MatchEvery

    if (-not $env:PHASE13F_PG_USER -or -not $env:PHASE13F_PG_PASSWORD) {
        throw 'PostgreSQL local credentials unavailable.'
    }
    if ($env:PHASE13F_PG_DB -ne 'verifier') {
        throw 'Only the local verifier database is permitted.'
    }

    @'
from __future__ import annotations

import asyncio
import json
import math
import os
import statistics
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import NullPool
from sqlalchemy.sql.expression import ClauseElement, Executable

from apps.api.connectors.contracts import ContentKind, DiscoveryResult, ExternalDiscoveryHit, Provider
from apps.api.db.models.retrieval_observation import RetrievalObservation
from apps.api.services.external_ingestion import ingest_discovery_result, ingest_supplied_content
from apps.api.services.external_passage_retrieval import (
    build_external_retrieval_stmt,
    retrieve_external_passages,
)

CLAIM = "zyphra renewable solar energy"


class ExplainQuery(Executable, ClauseElement):
    inherit_cache = False

    def __init__(self, statement):
        self.statement = statement


@compiles(ExplainQuery, "postgresql")
def compile_explain(element, compiler, **kwargs):
    return "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + compiler.process(
        element.statement, **kwargs
    )


def walk_nodes(node):
    yield node
    for child in node.get("Plans", []):
        yield from walk_nodes(child)


def percentile(numbers, value):
    ordered = sorted(numbers)
    return ordered[max(0, math.ceil(len(ordered) * value) - 1)]


async def main():
    user = os.environ["PHASE13F_PG_USER"]
    password = os.environ["PHASE13F_PG_PASSWORD"]
    database = os.environ["PHASE13F_PG_DB"]
    articles = int(os.environ["PHASE13F_BENCH_ARTICLES"])
    samples = int(os.environ["PHASE13F_BENCH_SAMPLES"])
    match_every = int(os.environ["PHASE13F_BENCH_MATCH_EVERY"])

    assert database == "verifier"
    assert 1 <= articles <= 500
    assert 3 <= samples <= 20
    assert 2 <= match_every <= 50
    url = URL.create(
        "postgresql+asyncpg",
        username=user,
        password=password,
        host="127.0.0.1",
        port=5432,
        database=database,
    )
    engine = create_async_engine(url, poolclass=NullPool, connect_args={"timeout": 8})
    run_id = uuid4().hex[:12]
    tx = None
    initial_count = None
    inserted = 0

    print("TARGET: 127.0.0.1:5432/verifier")
    print("SYNTHETIC_ARTICLES_TARGET:", articles)
    print("EXPLAIN_SAMPLES:", samples)
    print("MATCH_EVERY_NTH_ARTICLE:", match_every)
    print("SAFETY: transaction rollback; no external HTTP, ML models, or AWS")

    try:
        async with engine.connect() as conn:
            tx = await conn.begin()
            try:
                await conn.execute(text("SET LOCAL statement_timeout = '30s'"))
                initial_count = await conn.scalar(
                    text("SELECT COUNT(*) FROM public.document_passages")
                )
                async with AsyncSession(bind=conn, expire_on_commit=False) as session:
                    now = datetime.now(UTC)
                    urls = set()
                    for i in range(articles):
                        domain = f"phase13f-{run_id}-{i % 5}.example.org"
                        article_url = f"https://{domain}/synthetic-article-{i:05d}"
                        urls.add(article_url)
                        hit = ExternalDiscoveryHit(
                            provider=Provider.RSS_FEED,
                            kind=ContentKind.NEWS_ARTICLE,
                            url=article_url,
                            publisher_domain=domain,
                            publisher_name=f"Synthetic Publisher {i % 5}",
                            title=f"Fictional solar demonstration {i}",
                            snippet="Synthetic report about renewable energy measurements.",
                            discovered_at=now,
                            published_at=now,
                            language="en",
                        )
                        await ingest_discovery_result(
                            session,
                            DiscoveryResult(
                                provider=Provider.RSS_FEED,
                                query=CLAIM,
                                hits=(hit,),
                            ),
                        )
                        if i % match_every == 0:
                            article_text = (
                                f"Fictional report number {i}: the zyphra renewable solar energy "
                                "project operated during a synthetic laboratory demonstration. "
                                "Researchers measured solar equipment output, reported how "
                                "renewable panels supplied electricity to an imaginary treatment "
                                "station, and archived their fictional observations. "
                                "This article is generated test data, not a real news source."
                            )
                        else:
                            article_text = (
                                f"Fictional report number {i}: a botanical catalogue recorded "
                                "laboratory specimens and archival inventory movements. "
                                "Researchers sorted plant samples and documented shelf "
                                "labels during a staged internal exercise. "
                                "This article is generated test data, not a real news source."
                            )
                        content = await ingest_supplied_content(
                            session,
                            url=article_url,
                            text=article_text,
                            retrieved_at=now,
                            storage_authorized=True,
                            provider="secure_article_fetch_v1",
                        )
                        observation = await session.get(
                            RetrievalObservation, content.retrieval_observation_id
                        )
                        if observation is None:
                            raise AssertionError("Missing ingestion observation")
                        observation.metadata_json = {
                            "independently_verified": False,
                            "extraction_method": "synthetic_local_benchmark",
                        }
                        inserted += 1
                        if inserted % 25 == 0:
                            await session.flush()
                            print("SYNTHETIC_INGESTED:", inserted, flush=True)

                    await session.flush()
                    count_in_tx = await session.scalar(
                        text("SELECT COUNT(*) FROM public.document_passages")
                    )
                    if count_in_tx <= initial_count:
                        raise AssertionError("Synthetic passages were not stored")

                    retrieved = await retrieve_external_passages(
                        session, claim=CLAIM, top_k=10, candidate_limit=60
                    )
                    matched = sum(1 for candidate in retrieved if candidate.original_url in urls)
                    if matched < 1:
                        raise AssertionError("Actual retrieval returned no synthetic passage")

                    statement = build_external_retrieval_stmt(
                        CLAIM, candidate_limit=60
                    )
                    planning_ms = []
                    execution_ms = []
                    final_plan = None
                    for _ in range(samples):
                        raw = await conn.scalar(ExplainQuery(statement))
                        data = json.loads(raw) if isinstance(raw, str) else raw
                        result = data[0]
                        planning_ms.append(float(result["Planning Time"]))
                        execution_ms.append(float(result["Execution Time"]))
                        final_plan = result["Plan"]

                    nodes = list(walk_nodes(final_plan))
                    indexes = sorted(
                        {x["Index Name"] for x in nodes if x.get("Index Name")}
                    )
                    print("BASELINE_PASSAGES:", initial_count)
                    print("SYNTHETIC_ARTICLES_INGESTED:", inserted)
                    print("EXPECTED_MATCHING_ARTICLES:", sum(i % match_every == 0 for i in range(inserted)))
                    print("PASSAGES_WITHIN_TRANSACTION:", count_in_tx)
                    print("MATCHED_SYNTHETIC_RESULTS:", matched)
                    print("EXECUTION_MS_SAMPLES:", [round(x, 3) for x in execution_ms])
                    print("EXECUTION_P50_MS:", round(statistics.median(execution_ms), 3))
                    print("EXECUTION_P95_MS:", round(percentile(execution_ms, 0.95), 3))
                    print("PLANNING_P50_MS:", round(statistics.median(planning_ms), 3))
                    print("INDEXES_USED:", ", ".join(indexes) or "none in this plan")
                    print("GIN_INDEX_USED:", "ix_document_passages_text_fts" in indexes)
                    print("PLAN_NODE_TYPES:", ", ".join(sorted({x['Node Type'] for x in nodes})))
            finally:
                if tx is not None and tx.is_active:
                    await tx.rollback()
                    print("TRANSACTION_ROLLED_BACK: YES")

        async with engine.connect() as verify_conn:
            after = await verify_conn.scalar(
                text("SELECT COUNT(*) FROM public.document_passages")
            )
        print("PASSAGES_AFTER_ROLLBACK:", after)
        if after != initial_count:
            raise AssertionError("Post-rollback row count differs from baseline")
        print("PHASE13F_FULL_QUERY_SYNTHETIC_BENCHMARK_PASS")
        print("NOTE: This baseline is not a production-scale capacity benchmark.")
    finally:
        await engine.dispose()


asyncio.run(main())
'@ | uv run --frozen python -

    if ($LASTEXITCODE -ne 0) {
        throw 'PHASE13F_FULL_QUERY_SYNTHETIC_BENCHMARK_FAILED'
    }
}
finally {
    foreach ($name in @(
        'PHASE13F_PG_USER',
        'PHASE13F_PG_PASSWORD',
        'PHASE13F_PG_DB',
        'PHASE13F_BENCH_ARTICLES',
        'PHASE13F_BENCH_SAMPLES',
        'PHASE13F_BENCH_MATCH_EVERY'
    )) {
        Remove-Item "Env:\$name" -ErrorAction SilentlyContinue
    }
    Pop-Location
}
