import hashlib
import json
from pathlib import Path

import duckdb

PROJECT_ROOT = Path(__file__).resolve().parents[2]

FEVER_DIRECTORY = PROJECT_ROOT / "data" / "processed" / "fever"

SOURCE_PATH = FEVER_DIRECTORY / "nli_pairs.parquet"

OUTPUT_PATH = FEVER_DIRECTORY / "nli_pairs_clean.parquet"

METADATA_DIRECTORY = PROJECT_ROOT / "data" / "metadata"

MANIFEST_PATH = METADATA_DIRECTORY / "fever_nli_deduplication_manifest.json"


def sql_path(
    path: Path,
) -> str:
    return path.as_posix().replace(
        "'",
        "''",
    )


def sha256_file(
    path: Path,
) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as file_handle:
        for chunk in iter(
            lambda: file_handle.read(1024 * 1024),
            b"",
        ):
            digest.update(chunk)

    return digest.hexdigest()


def scalar_int(
    connection: duckdb.DuckDBPyConnection,
    query: str,
) -> int:
    row = connection.execute(query).fetchone()

    if row is None:
        return 0

    return int(row[0])


def main() -> None:
    if not SOURCE_PATH.exists():
        raise FileNotFoundError(f"NLI dataset does not exist: {SOURCE_PATH}")

    METADATA_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    if OUTPUT_PATH.exists():
        OUTPUT_PATH.unlink()

    source_sql = sql_path(SOURCE_PATH)

    output_sql = sql_path(OUTPUT_PATH)

    connection = duckdb.connect()

    try:
        print("Inspecting NLI dataset...")

        original_rows = scalar_int(
            connection,
            f"""
            SELECT COUNT(*)
            FROM read_parquet(
                '{source_sql}'
            )
            """,
        )

        duplicate_groups = scalar_int(
            connection,
            f"""
            SELECT COUNT(*)

            FROM (
                SELECT
                    split,
                    claim_id,
                    premise,
                    nli_label

                FROM read_parquet(
                    '{source_sql}'
                )

                GROUP BY
                    split,
                    claim_id,
                    premise,
                    nli_label

                HAVING COUNT(*) > 1
            )
            """,
        )

        excess_rows = scalar_int(
            connection,
            f"""
            SELECT
                COALESCE(
                    SUM(row_count - 1),
                    0
                )

            FROM (
                SELECT
                    COUNT(*) AS row_count

                FROM read_parquet(
                    '{source_sql}'
                )

                GROUP BY
                    split,
                    claim_id,
                    premise,
                    nli_label

                HAVING COUNT(*) > 1
            )
            """,
        )

        max_copies = scalar_int(
            connection,
            f"""
            SELECT
                COALESCE(
                    MAX(row_count),
                    1
                )

            FROM (
                SELECT
                    COUNT(*) AS row_count

                FROM read_parquet(
                    '{source_sql}'
                )

                GROUP BY
                    split,
                    claim_id,
                    premise,
                    nli_label
            )
            """,
        )

        conflicting_pairs = scalar_int(
            connection,
            f"""
            SELECT COUNT(*)

            FROM (
                SELECT
                    split,
                    claim_id,
                    premise

                FROM read_parquet(
                    '{source_sql}'
                )

                GROUP BY
                    split,
                    claim_id,
                    premise

                HAVING
                    COUNT(
                        DISTINCT nli_label
                    ) > 1
            )
            """,
        )

        print(f"Original rows: {original_rows:,}")

        print(f"Duplicate groups: {duplicate_groups:,}")

        print(f"Excess duplicate rows: {excess_rows:,}")

        print(f"Maximum copies: {max_copies:,}")

        print(f"Conflicting pairs: {conflicting_pairs:,}")

        if conflicting_pairs > 0:
            raise ValueError("Cannot safely deduplicate: conflicting NLI labels exist.")

        print()
        print("Applying deterministic deduplication...")

        connection.execute(
            f"""
            COPY (
                WITH ranked AS (
                    SELECT
                        *,

                        ROW_NUMBER() OVER (
                            PARTITION BY
                                split,
                                claim_id,
                                premise,
                                nli_label

                            ORDER BY
                                source_type ASC,
                                evidence_set_id ASC,
                                example_id ASC
                        ) AS duplicate_rank

                    FROM read_parquet(
                        '{source_sql}'
                    )
                ),

                deduplicated AS (
                    SELECT
                        claim_id,
                        split,
                        claim,
                        claim_label,
                        premise,

                        nli_label,
                        nli_label_id,

                        source_type,

                        evidence_set_id,

                        evidence_page_ids,
                        evidence_sentence_ids,
                        evidence_sentence_count

                    FROM ranked

                    WHERE duplicate_rank = 1
                )

                SELECT
                    CAST(
                        ROW_NUMBER() OVER (
                            ORDER BY
                                split,
                                claim_id,
                                nli_label_id,
                                evidence_set_id,
                                premise
                        )
                        AS BIGINT
                    ) AS example_id,

                    claim_id,
                    split,
                    claim,
                    claim_label,
                    premise,

                    nli_label,
                    nli_label_id,

                    source_type,

                    evidence_set_id,

                    evidence_page_ids,
                    evidence_sentence_ids,
                    evidence_sentence_count

                FROM deduplicated
            )

            TO '{output_sql}'
            (
                FORMAT PARQUET,
                COMPRESSION ZSTD
            )
            """
        )

        clean_rows = scalar_int(
            connection,
            f"""
            SELECT COUNT(*)
            FROM read_parquet(
                '{output_sql}'
            )
            """,
        )

        remaining_duplicates = scalar_int(
            connection,
            f"""
            SELECT COUNT(*)

            FROM (
                SELECT
                    split,
                    claim_id,
                    premise,
                    nli_label

                FROM read_parquet(
                    '{output_sql}'
                )

                GROUP BY
                    split,
                    claim_id,
                    premise,
                    nli_label

                HAVING COUNT(*) > 1
            )
            """,
        )

        remaining_conflicts = scalar_int(
            connection,
            f"""
            SELECT COUNT(*)

            FROM (
                SELECT
                    split,
                    claim_id,
                    premise

                FROM read_parquet(
                    '{output_sql}'
                )

                GROUP BY
                    split,
                    claim_id,
                    premise

                HAVING
                    COUNT(
                        DISTINCT nli_label
                    ) > 1
            )
            """,
        )

        cross_split_pair_leaks = scalar_int(
            connection,
            f"""
                SELECT COUNT(*)

                FROM (
                    SELECT
                        claim,
                        premise

                    FROM read_parquet(
                        '{output_sql}'
                    )

                    GROUP BY
                        claim,
                        premise

                    HAVING
                        COUNT(
                            DISTINCT split
                        ) > 1
                )
                """,
        )

        distribution_rows = connection.execute(
            f"""
                SELECT
                    split,
                    nli_label,
                    COUNT(*) AS row_count

                FROM read_parquet(
                    '{output_sql}'
                )

                GROUP BY
                    split,
                    nli_label

                ORDER BY
                    split,
                    nli_label
                """
        ).fetchall()

    finally:
        connection.close()

    if remaining_duplicates != 0:
        raise ValueError(f"Deduplication failed: {remaining_duplicates} duplicate groups remain.")

    if remaining_conflicts != 0:
        raise ValueError(f"Clean dataset contains {remaining_conflicts} conflicting pairs.")

    distribution: dict[
        str,
        dict[str, int],
    ] = {}

    for (
        split_value,
        label_value,
        count_value,
    ) in distribution_rows:
        split = str(split_value)

        label = str(label_value)

        count = int(count_value)

        distribution.setdefault(
            split,
            {},
        )[label] = count

    removed_rows = original_rows - clean_rows

    manifest: dict[str, object] = {
        "dataset": "fever",
        "stage": "nli_deduplication",
        "original_rows": original_rows,
        "clean_rows": clean_rows,
        "removed_rows": removed_rows,
        "duplicate_groups_before": (duplicate_groups),
        "excess_rows_before": (excess_rows),
        "max_copies_before": (max_copies),
        "conflicting_pairs_before": (conflicting_pairs),
        "duplicate_groups_after": (remaining_duplicates),
        "conflicting_pairs_after": (remaining_conflicts),
        "cross_split_pair_leaks": (cross_split_pair_leaks),
        "distribution": distribution,
        "artifact": {
            "path": str(OUTPUT_PATH.relative_to(PROJECT_ROOT)),
            "size_bytes": (OUTPUT_PATH.stat().st_size),
            "sha256": sha256_file(OUTPUT_PATH),
        },
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
    print("FEVER NLI deduplication completed.")

    print(f"Original rows: {original_rows:,}")

    print(f"Clean rows: {clean_rows:,}")

    print(f"Rows removed: {removed_rows:,}")

    print(f"Remaining duplicate groups: {remaining_duplicates:,}")

    print(f"Remaining conflicting pairs: {remaining_conflicts:,}")

    print(f"Cross-split pair leakage: {cross_split_pair_leaks:,}")

    print()

    for split, labels in distribution.items():
        print(f"{split}:")

        for label, count in labels.items():
            print(f"  {label}: {count:,}")

    print()

    print(f"Output: {OUTPUT_PATH}")

    print(f"Manifest: {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
