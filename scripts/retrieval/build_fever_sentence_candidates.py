import json
from pathlib import Path

import duckdb

PROJECT_ROOT = Path(__file__).resolve().parents[2]

PROCESSED_DIRECTORY = PROJECT_ROOT / "data" / "processed" / "fever"

METADATA_DIRECTORY = PROJECT_ROOT / "data" / "metadata"

PAGE_CANDIDATES_PATH = PROCESSED_DIRECTORY / "bm25_page_candidates.parquet"

WIKI_SENTENCES_PATH = PROCESSED_DIRECTORY / "wiki_sentences.parquet"

OUTPUT_PATH = PROCESSED_DIRECTORY / "sentence_candidates.parquet"

MANIFEST_PATH = METADATA_DIRECTORY / "fever_sentence_candidates_manifest.json"


def sql_path(path: Path) -> str:
    return path.as_posix().replace(
        "'",
        "''",
    )


def scalar_int(
    connection: duckdb.DuckDBPyConnection,
    query: str,
) -> int:
    result = connection.execute(query).fetchone()

    if result is None:
        return 0

    return int(result[0])


def build_sentence_candidates() -> dict[str, object]:
    if not PAGE_CANDIDATES_PATH.exists():
        raise FileNotFoundError(f"Missing page candidates: {PAGE_CANDIDATES_PATH}")

    if not WIKI_SENTENCES_PATH.exists():
        raise FileNotFoundError(f"Missing Wikipedia sentence corpus: {WIKI_SENTENCES_PATH}")

    METADATA_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    if OUTPUT_PATH.exists():
        OUTPUT_PATH.unlink()

    page_candidates_sql = sql_path(PAGE_CANDIDATES_PATH)

    wiki_sentences_sql = sql_path(WIKI_SENTENCES_PATH)

    output_sql = sql_path(OUTPUT_PATH)

    connection = duckdb.connect()

    try:
        print("Building FEVER sentence candidates...")

        print("Joining BM25 candidate pages with Wikipedia sentences...")

        connection.execute(
            f"""
            COPY (
                SELECT
                    p.claim_id,
                    p.split,
                    p.label,
                    p.claim,

                    p.page_rank,
                    p.page_id,
                    p.page_title,
                    p.page_score,

                    s.sentence_id,
                    s.text AS sentence_text,
                    s.raw_line,
                    s.source_member

                FROM read_parquet(
                    '{page_candidates_sql}'
                ) AS p

                INNER JOIN read_parquet(
                    '{wiki_sentences_sql}'
                ) AS s

                ON p.page_id = s.page_id

                ORDER BY
                    p.claim_id,
                    p.page_rank,
                    s.sentence_id
            )
            TO '{output_sql}'
            (
                FORMAT PARQUET,
                COMPRESSION ZSTD
            )
            """
        )

        candidate_rows = scalar_int(
            connection,
            f"""
            SELECT COUNT(*)
            FROM read_parquet(
                '{output_sql}'
            )
            """,
        )

        unique_claims = scalar_int(
            connection,
            f"""
            SELECT COUNT(
                DISTINCT claim_id
            )
            FROM read_parquet(
                '{output_sql}'
            )
            """,
        )

        unique_pages = scalar_int(
            connection,
            f"""
            SELECT COUNT(
                DISTINCT page_id
            )
            FROM read_parquet(
                '{output_sql}'
            )
            """,
        )

        empty_sentence_rows = scalar_int(
            connection,
            f"""
            SELECT COUNT(*)
            FROM read_parquet(
                '{output_sql}'
            )
            WHERE sentence_text IS NULL
               OR TRIM(sentence_text) = ''
            """,
        )

    finally:
        connection.close()

    average_candidates = candidate_rows / unique_claims if unique_claims else 0.0

    manifest: dict[str, object] = {
        "dataset": "fever",
        "stage": "sentence_candidate_generation",
        "candidate_rows": candidate_rows,
        "unique_claims": unique_claims,
        "unique_pages": unique_pages,
        "empty_sentence_rows": (empty_sentence_rows),
        "average_sentences_per_claim": (average_candidates),
        "output": str(OUTPUT_PATH.relative_to(PROJECT_ROOT)),
    }

    MANIFEST_PATH.write_text(
        json.dumps(
            manifest,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    print()
    print("Sentence candidate generation complete.")

    print(f"Claims: {unique_claims:,}")

    print(f"Candidate sentences: {candidate_rows:,}")

    print(f"Unique pages: {unique_pages:,}")

    print(f"Average sentences per claim: {average_candidates:.2f}")

    print(f"Empty sentence rows: {empty_sentence_rows:,}")

    print(f"Output: {OUTPUT_PATH}")

    return manifest


def main() -> None:
    build_sentence_candidates()


if __name__ == "__main__":
    main()
