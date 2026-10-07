import hashlib
import json
from pathlib import Path

import duckdb

from ml.classification.labels import (
    LABEL_TO_ID,
)
from ml.datasets.loaders.fever import (
    FeverLabel,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]

PROCESSED_DIRECTORY = PROJECT_ROOT / "data" / "processed" / "fever"

METADATA_DIRECTORY = PROJECT_ROOT / "data" / "metadata"

CLAIMS_PATH = PROCESSED_DIRECTORY / "claims.parquet"

OUTPUT_PATH = PROCESSED_DIRECTORY / "claim_classification.parquet"

MANIFEST_PATH = METADATA_DIRECTORY / "fever_claim_classification_manifest.json"


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


def build_dataset() -> dict[str, object]:
    if not CLAIMS_PATH.exists():
        raise FileNotFoundError(f"Missing FEVER claims: {CLAIMS_PATH}")

    METADATA_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    if OUTPUT_PATH.exists():
        OUTPUT_PATH.unlink()

    claims_sql = sql_path(CLAIMS_PATH)

    output_sql = sql_path(OUTPUT_PATH)

    connection = duckdb.connect()

    try:
        connection.execute(
            f"""
            CREATE TEMP VIEW
                source_claims AS

            SELECT
                claim_id,
                split,
                TRIM(claim) AS claim,
                label

            FROM read_parquet(
                '{claims_sql}'
            )
            """
        )

        print("Validating FEVER classification data...")

        empty_claim_rows = scalar_int(
            connection,
            """
            SELECT COUNT(*)
            FROM source_claims
            WHERE claim IS NULL
               OR claim = ''
            """,
        )

        if empty_claim_rows > 0:
            raise ValueError(f"Classification source contains {empty_claim_rows} empty claims.")

        duplicate_claim_rows = scalar_int(
            connection,
            """
                SELECT COUNT(*)
                FROM (
                    SELECT
                        split,
                        claim_id,
                        COUNT(*) AS row_count

                    FROM source_claims

                    GROUP BY
                        split,
                        claim_id

                    HAVING COUNT(*) > 1
                )
                """,
        )

        if duplicate_claim_rows > 0:
            raise ValueError(
                "Classification source contains "
                f"{duplicate_claim_rows} "
                "duplicate (split, claim_id) "
                "keys."
            )

        label_rows = connection.execute(
            """
            SELECT DISTINCT label
            FROM source_claims
            ORDER BY label
            """
        ).fetchall()

        observed_labels = {str(row[0]) for row in label_rows}

        expected_labels = {label.value for label in FeverLabel}

        if observed_labels != expected_labels:
            raise ValueError(
                "Unexpected FEVER labels. "
                f"Observed: "
                f"{sorted(observed_labels)}; "
                f"expected: "
                f"{sorted(expected_labels)}"
            )

        supports_id = LABEL_TO_ID[FeverLabel.SUPPORTS]

        refutes_id = LABEL_TO_ID[FeverLabel.REFUTES]

        nei_id = LABEL_TO_ID[FeverLabel.NOT_ENOUGH_INFO]

        print("Writing classification dataset...")

        connection.execute(
            f"""
            COPY (
                SELECT
                    claim_id,
                    split,
                    claim,
                    label,

                    CASE
                        WHEN label =
                            'SUPPORTS'
                        THEN {supports_id}

                        WHEN label =
                            'REFUTES'
                        THEN {refutes_id}

                        WHEN label =
                            'NOT ENOUGH INFO'
                        THEN {nei_id}

                        ELSE NULL
                    END AS label_id

                FROM source_claims

                ORDER BY
                    split,
                    claim_id
            )
            TO '{output_sql}'
            (
                FORMAT PARQUET,
                COMPRESSION ZSTD
            )
            """
        )

        total_rows = scalar_int(
            connection,
            f"""
            SELECT COUNT(*)
            FROM read_parquet(
                '{output_sql}'
            )
            """,
        )

        distribution_rows = connection.execute(
            f"""
                SELECT
                    split,
                    label,
                    label_id,
                    COUNT(*) AS row_count

                FROM read_parquet(
                    '{output_sql}'
                )

                GROUP BY
                    split,
                    label,
                    label_id

                ORDER BY
                    split,
                    label_id
                """
        ).fetchall()

    finally:
        connection.close()

    distribution: dict[
        str,
        dict[str, int],
    ] = {}

    for (
        split_value,
        label_value,
        _label_id,
        count_value,
    ) in distribution_rows:
        split = str(split_value)

        label = str(label_value)

        count = int(count_value)

        distribution.setdefault(
            split,
            {},
        )[label] = count

    manifest: dict[str, object] = {
        "dataset": "fever",
        "stage": ("claim_classification_dataset"),
        "total_rows": total_rows,
        "label_mapping": {label.value: label_id for label, label_id in LABEL_TO_ID.items()},
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
    print("FEVER claim classification dataset completed.")

    print(f"Rows: {total_rows:,}")

    print()

    for split, labels in distribution.items():
        print(f"{split}:")

        for label, count in labels.items():
            print(f"  {label}: {count:,}")

    print()

    print(f"Output: {OUTPUT_PATH}")

    print(f"Manifest: {MANIFEST_PATH}")

    return manifest


def main() -> None:
    build_dataset()


if __name__ == "__main__":
    main()
