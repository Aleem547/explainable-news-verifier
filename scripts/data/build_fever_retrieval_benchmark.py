import hashlib
import json
from pathlib import Path

import duckdb

PROJECT_ROOT = Path(__file__).resolve().parents[2]

PROCESSED_DIRECTORY = PROJECT_ROOT / "data" / "processed" / "fever"

METADATA_DIRECTORY = PROJECT_ROOT / "data" / "metadata"

CLAIMS_PATH = PROCESSED_DIRECTORY / "claims.parquet"

RESOLVED_EVIDENCE_PATH = PROCESSED_DIRECTORY / "resolved_evidence.parquet"

QUERIES_OUTPUT = PROCESSED_DIRECTORY / "retrieval_queries.parquet"

QRELS_OUTPUT = PROCESSED_DIRECTORY / "retrieval_qrels.parquet"

GOLD_PAGES_OUTPUT = PROCESSED_DIRECTORY / "retrieval_gold_pages.parquet"

MANIFEST_OUTPUT = METADATA_DIRECTORY / "fever_retrieval_benchmark_manifest.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as file_handle:
        for chunk in iter(
            lambda: file_handle.read(1024 * 1024),
            b"",
        ):
            digest.update(chunk)

    return digest.hexdigest()


def sql_path(path: Path) -> str:
    return path.as_posix().replace("'", "''")


def scalar_int(
    connection: duckdb.DuckDBPyConnection,
    query: str,
) -> int:
    result = connection.execute(query).fetchone()

    if result is None:
        return 0

    return int(result[0])


def remove_old_outputs() -> None:
    for path in (
        QUERIES_OUTPUT,
        QRELS_OUTPUT,
        GOLD_PAGES_OUTPUT,
    ):
        if path.exists():
            path.unlink()


def build_benchmark() -> dict[str, object]:
    if not CLAIMS_PATH.exists():
        raise FileNotFoundError(f"Missing claims file: {CLAIMS_PATH}")

    if not RESOLVED_EVIDENCE_PATH.exists():
        raise FileNotFoundError(f"Missing resolved evidence file: {RESOLVED_EVIDENCE_PATH}")

    METADATA_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    remove_old_outputs()

    claims_sql = sql_path(CLAIMS_PATH)

    evidence_sql = sql_path(RESOLVED_EVIDENCE_PATH)

    queries_sql = sql_path(QUERIES_OUTPUT)
    qrels_sql = sql_path(QRELS_OUTPUT)

    gold_pages_sql = sql_path(GOLD_PAGES_OUTPUT)

    connection = duckdb.connect()

    try:
        print("Building FEVER retrieval queries...")

        connection.execute(
            f"""
            COPY (
                SELECT DISTINCT
                    c.claim_id,
                    c.split,
                    c.claim,
                    c.label
                FROM read_parquet(
                    '{claims_sql}'
                ) AS c

                INNER JOIN read_parquet(
                    '{evidence_sql}'
                ) AS e
                    ON c.claim_id = e.claim_id

                WHERE e.resolved = TRUE

                ORDER BY
                    c.split,
                    c.claim_id
            )
            TO '{queries_sql}'
            (
                FORMAT PARQUET,
                COMPRESSION ZSTD
            )
            """
        )

        print("Building sentence-level qrels...")

        connection.execute(
            f"""
            COPY (
                SELECT DISTINCT
                    e.claim_id,
                    e.split,
                    e.wiki_page,
                    e.sentence_id,
                    e.evidence_text,
                    1 AS relevance
                FROM read_parquet(
                    '{evidence_sql}'
                ) AS e

                WHERE e.resolved = TRUE
                  AND e.wiki_page IS NOT NULL
                  AND e.sentence_id IS NOT NULL
                  AND e.evidence_text IS NOT NULL

                ORDER BY
                    e.split,
                    e.claim_id,
                    e.wiki_page,
                    e.sentence_id
            )
            TO '{qrels_sql}'
            (
                FORMAT PARQUET,
                COMPRESSION ZSTD
            )
            """
        )

        print("Building page-level qrels...")

        connection.execute(
            f"""
            COPY (
                SELECT DISTINCT
                    claim_id,
                    split,
                    wiki_page,
                    1 AS relevance
                FROM read_parquet(
                    '{qrels_sql}'
                )

                ORDER BY
                    split,
                    claim_id,
                    wiki_page
            )
            TO '{gold_pages_sql}'
            (
                FORMAT PARQUET,
                COMPRESSION ZSTD
            )
            """
        )

        query_count = scalar_int(
            connection,
            f"""
            SELECT COUNT(*)
            FROM read_parquet(
                '{queries_sql}'
            )
            """,
        )

        qrel_count = scalar_int(
            connection,
            f"""
            SELECT COUNT(*)
            FROM read_parquet(
                '{qrels_sql}'
            )
            """,
        )

        gold_page_count = scalar_int(
            connection,
            f"""
            SELECT COUNT(*)
            FROM read_parquet(
                '{gold_pages_sql}'
            )
            """,
        )

        train_queries = scalar_int(
            connection,
            f"""
            SELECT COUNT(*)
            FROM read_parquet(
                '{queries_sql}'
            )
            WHERE split = 'train'
            """,
        )

        dev_queries = scalar_int(
            connection,
            f"""
            SELECT COUNT(*)
            FROM read_parquet(
                '{queries_sql}'
            )
            WHERE split = 'paper_dev'
            """,
        )

        test_queries = scalar_int(
            connection,
            f"""
            SELECT COUNT(*)
            FROM read_parquet(
                '{queries_sql}'
            )
            WHERE split = 'paper_test'
            """,
        )

    finally:
        connection.close()

    manifest: dict[str, object] = {
        "dataset": "fever",
        "stage": "retrieval_benchmark",
        "query_count": query_count,
        "sentence_qrel_count": qrel_count,
        "gold_page_count": gold_page_count,
        "split_counts": {
            "train": train_queries,
            "paper_dev": dev_queries,
            "paper_test": test_queries,
        },
        "artifacts": {
            "retrieval_queries": {
                "path": str(QUERIES_OUTPUT.relative_to(PROJECT_ROOT)),
                "size_bytes": (QUERIES_OUTPUT.stat().st_size),
                "sha256": sha256_file(QUERIES_OUTPUT),
            },
            "retrieval_qrels": {
                "path": str(QRELS_OUTPUT.relative_to(PROJECT_ROOT)),
                "size_bytes": (QRELS_OUTPUT.stat().st_size),
                "sha256": sha256_file(QRELS_OUTPUT),
            },
            "retrieval_gold_pages": {
                "path": str(GOLD_PAGES_OUTPUT.relative_to(PROJECT_ROOT)),
                "size_bytes": (GOLD_PAGES_OUTPUT.stat().st_size),
                "sha256": sha256_file(GOLD_PAGES_OUTPUT),
            },
        },
    }

    MANIFEST_OUTPUT.write_text(
        json.dumps(
            manifest,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    return manifest


def main() -> None:
    manifest = build_benchmark()

    print()
    print("FEVER retrieval benchmark created.")

    print(f"Queries: {manifest['query_count']}")

    print(f"Sentence qrels: {manifest['sentence_qrel_count']}")

    print(f"Gold page mappings: {manifest['gold_page_count']}")

    print(f"Manifest: {MANIFEST_OUTPUT}")


if __name__ == "__main__":
    main()
