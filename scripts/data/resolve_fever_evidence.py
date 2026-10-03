import hashlib
import json
from pathlib import Path
from typing import cast

import duckdb

PROJECT_ROOT = Path(__file__).resolve().parents[2]

PROCESSED_DIRECTORY = PROJECT_ROOT / "data" / "processed" / "fever"

METADATA_DIRECTORY = PROJECT_ROOT / "data" / "metadata"

EVIDENCE_PATH = PROCESSED_DIRECTORY / "evidence.parquet"

SENTENCES_PATH = PROCESSED_DIRECTORY / "wiki_sentences.parquet"

RESOLVED_OUTPUT = PROCESSED_DIRECTORY / "resolved_evidence.parquet"

UNRESOLVED_OUTPUT = PROCESSED_DIRECTORY / "unresolved_evidence.parquet"

DUPLICATES_OUTPUT = PROCESSED_DIRECTORY / "duplicate_wiki_sentences.parquet"

MANIFEST_OUTPUT = METADATA_DIRECTORY / "fever_evidence_resolution_manifest.json"


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


def remove_old_outputs() -> None:
    for path in (
        RESOLVED_OUTPUT,
        UNRESOLVED_OUTPUT,
        DUPLICATES_OUTPUT,
    ):
        if path.exists():
            path.unlink()


def process_resolution() -> dict[str, object]:
    if not EVIDENCE_PATH.exists():
        raise FileNotFoundError(f"Missing evidence file: {EVIDENCE_PATH}")

    if not SENTENCES_PATH.exists():
        raise FileNotFoundError(f"Missing Wikipedia sentence corpus: {SENTENCES_PATH}")

    METADATA_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    remove_old_outputs()

    evidence_sql = sql_path(EVIDENCE_PATH)

    sentences_sql = sql_path(SENTENCES_PATH)

    resolved_sql = sql_path(RESOLVED_OUTPUT)

    unresolved_sql = sql_path(UNRESOLVED_OUTPUT)

    duplicates_sql = sql_path(DUPLICATES_OUTPUT)

    connection = duckdb.connect()

    try:
        print("Loading Wikipedia sentence corpus...")

        connection.execute(
            f"""
            CREATE TEMP VIEW wiki_sentences AS
            SELECT *
            FROM read_parquet(
                '{sentences_sql}'
            )
            """
        )

        print("Checking Wikipedia sentence integrity...")

        connection.execute(
            """
            CREATE TEMP VIEW duplicate_keys AS
            SELECT
                page_id,
                sentence_id,
                COUNT(*) AS duplicate_count,
                COUNT(
                    DISTINCT COALESCE(
                        text,
                        ''
                    )
                ) AS distinct_text_count
            FROM wiki_sentences
            GROUP BY
                page_id,
                sentence_id
            HAVING COUNT(*) > 1
            """
        )

        duplicate_sentence_keys = scalar_int(
            connection,
            """
                SELECT COUNT(*)
                FROM duplicate_keys
                """,
        )

        conflicting_duplicate_keys = scalar_int(
            connection,
            """
                SELECT COUNT(*)
                FROM duplicate_keys
                WHERE distinct_text_count > 1
                """,
        )

        duplicate_rows = scalar_int(
            connection,
            """
            SELECT COUNT(*)
            FROM wiki_sentences AS s
            INNER JOIN duplicate_keys AS d
                ON s.page_id = d.page_id
               AND s.sentence_id =
                   d.sentence_id
            """,
        )

        connection.execute(
            f"""
            COPY (
                SELECT
                    s.page_id,
                    s.sentence_id,
                    s.text,
                    s.raw_line,
                    s.source_member,
                    d.duplicate_count,
                    d.distinct_text_count
                FROM wiki_sentences AS s
                INNER JOIN duplicate_keys AS d
                    ON s.page_id = d.page_id
                   AND s.sentence_id =
                       d.sentence_id
                ORDER BY
                    s.page_id,
                    s.sentence_id,
                    LENGTH(
                        COALESCE(
                            s.raw_line,
                            ''
                        )
                    ) DESC
            )
            TO '{duplicates_sql}'
            (
                FORMAT PARQUET,
                COMPRESSION ZSTD
            )
            """
        )

        if conflicting_duplicate_keys > 0:
            raise ValueError(
                "Wikipedia sentence corpus "
                "contains "
                f"{conflicting_duplicate_keys} "
                "duplicate key(s) with "
                "different sentence text. "
                "Inspect "
                f"{DUPLICATES_OUTPUT}."
            )

        if duplicate_sentence_keys > 0:
            print(f"Found {duplicate_sentence_keys} duplicate sentence key(s).")

            print("All duplicates contain identical sentence text.")

            print("Applying deterministic deduplication...")

        connection.execute(
            """
            CREATE TEMP VIEW
                deduplicated_sentences AS
            SELECT
                page_id,
                sentence_id,
                text,
                raw_line,
                source_member
            FROM (
                SELECT
                    page_id,
                    sentence_id,
                    text,
                    raw_line,
                    source_member,

                    ROW_NUMBER() OVER (
                        PARTITION BY
                            page_id,
                            sentence_id

                        ORDER BY
                            CASE
                                WHEN text
                                    IS NOT NULL
                                 AND TRIM(text)
                                    <> ''
                                THEN 0
                                ELSE 1
                            END,

                            LENGTH(
                                COALESCE(
                                    raw_line,
                                    ''
                                )
                            ) DESC,

                            LENGTH(
                                COALESCE(
                                    text,
                                    ''
                                )
                            ) DESC,

                            source_member ASC
                    ) AS row_number

                FROM wiki_sentences
            )
            WHERE row_number = 1
            """
        )

        original_sentence_rows = scalar_int(
            connection,
            """
            SELECT COUNT(*)
            FROM wiki_sentences
            """,
        )

        deduplicated_sentence_rows = scalar_int(
            connection,
            """
                SELECT COUNT(*)
                FROM deduplicated_sentences
                """,
        )

        deduplicated_rows_removed = original_sentence_rows - deduplicated_sentence_rows

        print("Wikipedia corpus ready.")

        print(f"Original sentence rows: {original_sentence_rows}")

        print(f"Rows after deduplication: {deduplicated_sentence_rows}")

        print(f"Duplicate rows removed: {deduplicated_rows_removed}")

        total_evidence_rows = scalar_int(
            connection,
            f"""
            SELECT COUNT(*)
            FROM read_parquet(
                '{evidence_sql}'
            )
            """,
        )

        null_reference_rows = scalar_int(
            connection,
            f"""
            SELECT COUNT(*)
            FROM read_parquet(
                '{evidence_sql}'
            )
            WHERE wiki_page IS NULL
               OR sentence_id IS NULL
            """,
        )

        resolvable_reference_rows = scalar_int(
            connection,
            f"""
                SELECT COUNT(*)
                FROM read_parquet(
                    '{evidence_sql}'
                )
                WHERE wiki_page IS NOT NULL
                  AND sentence_id IS NOT NULL
                """,
        )

        print()
        print("Resolving FEVER evidence references...")

        connection.execute(
            f"""
            COPY (
                SELECT
                    e.claim_id,
                    e.split,
                    e.evidence_set_id,
                    e.evidence_item_position,
                    e.annotation_id,
                    e.evidence_id,
                    e.wiki_page,
                    e.sentence_id,

                    s.text AS evidence_text,

                    s.raw_line AS
                        evidence_raw_line,

                    s.source_member,

                    CASE
                        WHEN s.page_id
                            IS NOT NULL
                        THEN TRUE
                        ELSE FALSE
                    END AS resolved

                FROM read_parquet(
                    '{evidence_sql}'
                ) AS e

                LEFT JOIN
                    deduplicated_sentences AS s

                ON e.wiki_page = s.page_id

                AND e.sentence_id =
                    s.sentence_id
            )
            TO '{resolved_sql}'
            (
                FORMAT PARQUET,
                COMPRESSION ZSTD
            )
            """
        )

        connection.execute(
            f"""
            COPY (
                SELECT *
                FROM read_parquet(
                    '{resolved_sql}'
                )
                WHERE wiki_page IS NOT NULL
                  AND sentence_id IS NOT NULL
                  AND resolved = FALSE
            )
            TO '{unresolved_sql}'
            (
                FORMAT PARQUET,
                COMPRESSION ZSTD
            )
            """
        )

        resolved_reference_rows = scalar_int(
            connection,
            f"""
                SELECT COUNT(*)
                FROM read_parquet(
                    '{resolved_sql}'
                )
                WHERE wiki_page IS NOT NULL
                  AND sentence_id IS NOT NULL
                  AND resolved = TRUE
                """,
        )

        unresolved_reference_rows = scalar_int(
            connection,
            f"""
                SELECT COUNT(*)
                FROM read_parquet(
                    '{resolved_sql}'
                )
                WHERE wiki_page IS NOT NULL
                  AND sentence_id IS NOT NULL
                  AND resolved = FALSE
                """,
        )

        unique_resolved_references = scalar_int(
            connection,
            f"""
                SELECT COUNT(*)
                FROM (
                    SELECT DISTINCT
                        wiki_page,
                        sentence_id

                    FROM read_parquet(
                        '{resolved_sql}'
                    )

                    WHERE resolved = TRUE
                )
                """,
        )

        unique_unresolved_references = scalar_int(
            connection,
            f"""
                SELECT COUNT(*)
                FROM (
                    SELECT DISTINCT
                        wiki_page,
                        sentence_id

                    FROM read_parquet(
                        '{resolved_sql}'
                    )

                    WHERE wiki_page
                        IS NOT NULL

                      AND sentence_id
                        IS NOT NULL

                      AND resolved = FALSE
                )
                """,
        )

    finally:
        connection.close()

    if resolvable_reference_rows == 0:
        resolution_rate = 0.0
    else:
        resolution_rate = resolved_reference_rows / resolvable_reference_rows

    manifest: dict[str, object] = {
        "dataset": "fever",
        "stage": "evidence_resolution",
        "total_evidence_rows": (total_evidence_rows),
        "null_reference_rows": (null_reference_rows),
        "resolvable_reference_rows": (resolvable_reference_rows),
        "resolved_reference_rows": (resolved_reference_rows),
        "unresolved_reference_rows": (unresolved_reference_rows),
        "resolution_rate": (resolution_rate),
        "original_sentence_rows": (original_sentence_rows),
        "deduplicated_sentence_rows": (deduplicated_sentence_rows),
        "duplicate_sentence_keys": (duplicate_sentence_keys),
        "duplicate_rows": (duplicate_rows),
        "conflicting_duplicate_keys": (conflicting_duplicate_keys),
        "deduplicated_rows_removed": (deduplicated_rows_removed),
        "duplicate_resolution_policy": (
            "Duplicates with identical text are "
            "deduplicated by retaining the row "
            "with the longest raw_line, then the "
            "longest text, then source_member "
            "lexicographically. Duplicate keys "
            "with conflicting sentence text "
            "cause the pipeline to fail."
        ),
        "unique_resolved_references": (unique_resolved_references),
        "unique_unresolved_references": (unique_unresolved_references),
        "artifacts": {
            "resolved_evidence": {
                "path": str(RESOLVED_OUTPUT.relative_to(PROJECT_ROOT)),
                "size_bytes": (RESOLVED_OUTPUT.stat().st_size),
                "sha256": sha256_file(RESOLVED_OUTPUT),
            },
            "unresolved_evidence": {
                "path": str(UNRESOLVED_OUTPUT.relative_to(PROJECT_ROOT)),
                "size_bytes": (UNRESOLVED_OUTPUT.stat().st_size),
                "sha256": sha256_file(UNRESOLVED_OUTPUT),
            },
            "duplicate_wiki_sentences": {
                "path": str(DUPLICATES_OUTPUT.relative_to(PROJECT_ROOT)),
                "size_bytes": (DUPLICATES_OUTPUT.stat().st_size),
                "sha256": sha256_file(DUPLICATES_OUTPUT),
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
    manifest = process_resolution()

    print()
    print("FEVER evidence resolution completed.")

    print(f"Resolvable references: {manifest['resolvable_reference_rows']}")

    print(f"Resolved references: {manifest['resolved_reference_rows']}")

    print(f"Unresolved references: {manifest['unresolved_reference_rows']}")

    resolution_rate = cast(
        float,
        manifest["resolution_rate"],
    )

    print(f"Resolution rate: {resolution_rate:.4%}")

    print(f"Duplicate sentence keys: {manifest['duplicate_sentence_keys']}")

    print(f"Conflicting duplicate keys: {manifest['conflicting_duplicate_keys']}")

    print(f"Duplicate rows removed: {manifest['deduplicated_rows_removed']}")

    print(f"Manifest: {MANIFEST_OUTPUT}")


if __name__ == "__main__":
    main()
