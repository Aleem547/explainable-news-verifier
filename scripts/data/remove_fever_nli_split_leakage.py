import hashlib
import json
from pathlib import Path

import duckdb

PROJECT_ROOT = Path(__file__).resolve().parents[2]

FEVER_DIRECTORY = PROJECT_ROOT / "data" / "processed" / "fever"

SOURCE_PATH = FEVER_DIRECTORY / "nli_pairs_clean.parquet"

OUTPUT_PATH = FEVER_DIRECTORY / "nli_pairs_final.parquet"

METADATA_DIRECTORY = PROJECT_ROOT / "data" / "metadata"

MANIFEST_PATH = METADATA_DIRECTORY / "fever_nli_split_leakage_manifest.json"


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
    result = connection.execute(query).fetchone()

    if result is None:
        return 0

    return int(result[0])


def main() -> None:
    if not SOURCE_PATH.exists():
        raise FileNotFoundError(f"Clean NLI dataset does not exist: {SOURCE_PATH}")

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
        connection.execute(
            f"""
            CREATE TEMP VIEW
                source_pairs AS

            SELECT *
            FROM read_parquet(
                '{source_sql}'
            )
            """
        )

        original_rows = scalar_int(
            connection,
            """
            SELECT COUNT(*)
            FROM source_pairs
            """,
        )

        print("Checking global claim-premise consistency...")

        connection.execute(
            """
            CREATE TEMP TABLE
                ambiguous_pairs AS

            SELECT
                claim,
                premise

            FROM source_pairs

            GROUP BY
                claim,
                premise

            HAVING
                COUNT(
                    DISTINCT nli_label
                ) > 1
            """
        )

        ambiguous_pair_groups = scalar_int(
            connection,
            """
            SELECT COUNT(*)
            FROM ambiguous_pairs
            """,
        )

        ambiguous_rows = scalar_int(
            connection,
            """
            SELECT COUNT(*)

            FROM source_pairs AS source

            INNER JOIN ambiguous_pairs
                AS ambiguous

                ON source.claim
                    = ambiguous.claim

               AND source.premise
                    = ambiguous.premise
            """,
        )

        print(f"Globally ambiguous claim-premise groups: {ambiguous_pair_groups:,}")

        print(f"Rows belonging to ambiguous pairs: {ambiguous_rows:,}")

        print()
        print("Removing globally ambiguous logical pairs...")

        connection.execute(
            """
            CREATE TEMP TABLE
                consistent_pairs AS

            SELECT
                source.*

            FROM source_pairs AS source

            WHERE NOT EXISTS (
                SELECT 1

                FROM ambiguous_pairs
                    AS ambiguous

                WHERE
                    source.claim
                    = ambiguous.claim

                    AND source.premise
                    = ambiguous.premise
            )
            """
        )

        rows_after_ambiguity_cleanup = scalar_int(
            connection,
            """
                SELECT COUNT(*)
                FROM consistent_pairs
                """,
        )

        remaining_conflicts = scalar_int(
            connection,
            """
            SELECT COUNT(*)

            FROM (
                SELECT
                    claim,
                    premise

                FROM consistent_pairs

                GROUP BY
                    claim,
                    premise

                HAVING
                    COUNT(
                        DISTINCT nli_label
                    ) > 1
            )
            """,
        )

        if remaining_conflicts != 0:
            raise ValueError(
                f"Ambiguous-label cleanup failed. Remaining conflicts: {remaining_conflicts}"
            )

        print("Checking cross-split leakage...")

        leakage_before = scalar_int(
            connection,
            """
            SELECT COUNT(*)

            FROM (
                SELECT
                    claim,
                    premise

                FROM consistent_pairs

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

        print(f"Cross-split leakage groups before cleanup: {leakage_before:,}")

        connection.execute(
            """
            CREATE TEMP TABLE
                pair_split_keepers AS

            SELECT
                claim,
                premise,

                arg_min(
                    split,

                    CASE
                        WHEN split = 'test'
                        THEN 1

                        WHEN split = 'validation'
                        THEN 2

                        WHEN split = 'train'
                        THEN 3

                        ELSE 99
                    END
                ) AS keep_split

            FROM consistent_pairs

            GROUP BY
                claim,
                premise
            """
        )

        split_removal_rows = connection.execute(
            """
                SELECT
                    source.split,
                    COUNT(*) AS rows_removed

                FROM consistent_pairs
                    AS source

                INNER JOIN pair_split_keepers
                    AS keeper

                    ON source.claim
                        = keeper.claim

                   AND source.premise
                        = keeper.premise

                WHERE
                    source.split
                    <> keeper.keep_split

                GROUP BY
                    source.split

                ORDER BY
                    source.split
                """
        ).fetchall()

        print()
        print("Applying split priority:")

        print("  test > validation > train")

        connection.execute(
            """
            CREATE TEMP TABLE
                canonical_split_pairs AS

            SELECT
                source.*

            FROM consistent_pairs
                AS source

            INNER JOIN pair_split_keepers
                AS keeper

                ON source.claim
                    = keeper.claim

               AND source.premise
                    = keeper.premise

            WHERE
                source.split
                = keeper.keep_split
            """
        )

        rows_after_split_cleanup = scalar_int(
            connection,
            """
                SELECT COUNT(*)
                FROM canonical_split_pairs
                """,
        )

        print()
        print("Removing remaining logical duplicate pairs...")

        logical_duplicates_before = scalar_int(
            connection,
            """
                SELECT COUNT(*)

                FROM (
                    SELECT
                        claim,
                        premise

                    FROM canonical_split_pairs

                    GROUP BY
                        claim,
                        premise

                    HAVING COUNT(*) > 1
                )
                """,
        )

        print(f"Logical duplicate groups before final selection: {logical_duplicates_before:,}")

        connection.execute(
            f"""
            COPY (
                WITH ranked AS (
                    SELECT
                        *,

                        ROW_NUMBER() OVER (
                            PARTITION BY
                                claim,
                                premise

                            ORDER BY
                                claim_id ASC,
                                nli_label_id ASC,
                                source_type ASC,
                                evidence_set_id ASC,
                                example_id ASC
                        ) AS logical_rank

                    FROM canonical_split_pairs
                ),

                retained AS (
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

                    WHERE logical_rank = 1
                )

                SELECT
                    CAST(
                        ROW_NUMBER() OVER (
                            ORDER BY
                                split,
                                claim_id,
                                nli_label_id,
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

                FROM retained
            )

            TO '{output_sql}'
            (
                FORMAT PARQUET,
                COMPRESSION ZSTD
            )
            """
        )

        final_rows = scalar_int(
            connection,
            f"""
            SELECT COUNT(*)
            FROM read_parquet(
                '{output_sql}'
            )
            """,
        )

        conflicts_after = scalar_int(
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
                        DISTINCT nli_label
                    ) > 1
            )
            """,
        )

        leakage_after = scalar_int(
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

        logical_duplicates_after = scalar_int(
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

                    HAVING COUNT(*) > 1
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

    if conflicts_after != 0:
        raise ValueError(f"Final NLI dataset still contains conflicting labels: {conflicts_after}")

    if leakage_after != 0:
        raise ValueError(f"Final NLI dataset still contains cross-split leakage: {leakage_after}")

    if logical_duplicates_after != 0:
        raise ValueError(
            f"Final NLI dataset still contains logical duplicates: {logical_duplicates_after}"
        )

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

    split_removed_by_split = {
        str(split_value): int(count_value)
        for (
            split_value,
            count_value,
        ) in split_removal_rows
    }

    split_removed_rows = rows_after_ambiguity_cleanup - rows_after_split_cleanup

    logical_duplicate_rows_removed = rows_after_split_cleanup - final_rows

    total_removed_rows = original_rows - final_rows

    manifest: dict[str, object] = {
        "dataset": "fever",
        "stage": ("nli_final_integrity_cleanup"),
        "policy": {
            "ambiguous_pairs": (
                "Remove every logical claim-premise pair that has more than one NLI label."
            ),
            "split_priority": ("Preserve test over validation over train."),
            "logical_duplicates": (
                "Keep one deterministic representative per exact claim-premise pair."
            ),
        },
        "original_rows": (original_rows),
        "ambiguous_pair_groups": (ambiguous_pair_groups),
        "ambiguous_rows_removed": (ambiguous_rows),
        "rows_after_ambiguity_cleanup": (rows_after_ambiguity_cleanup),
        "cross_split_leakage_before": (leakage_before),
        "cross_split_rows_removed": (split_removed_rows),
        "cross_split_removed_by_split": (split_removed_by_split),
        "logical_duplicate_groups_before": (logical_duplicates_before),
        "logical_duplicate_rows_removed": (logical_duplicate_rows_removed),
        "final_rows": (final_rows),
        "total_removed_rows": (total_removed_rows),
        "conflicting_labels_after": (conflicts_after),
        "cross_split_leakage_after": (leakage_after),
        "logical_duplicates_after": (logical_duplicates_after),
        "distribution": (distribution),
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
    print("Final FEVER NLI integrity cleanup completed.")

    print()
    print(f"Original rows: {original_rows:,}")

    print(f"Ambiguous logical pairs: {ambiguous_pair_groups:,}")

    print(f"Rows removed for ambiguity: {ambiguous_rows:,}")

    print(f"Cross-split leakage before: {leakage_before:,}")

    print(f"Rows removed for split leakage: {split_removed_rows:,}")

    print(f"Logical duplicate groups before: {logical_duplicates_before:,}")

    print(f"Rows removed as logical duplicates: {logical_duplicate_rows_removed:,}")

    print()

    print(f"Final rows: {final_rows:,}")

    print(f"Total rows removed: {total_removed_rows:,}")

    print()

    print(f"Conflicting labels after: {conflicts_after:,}")

    print(f"Cross-split leakage after: {leakage_after:,}")

    print(f"Logical duplicates after: {logical_duplicates_after:,}")

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
