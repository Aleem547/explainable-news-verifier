import hashlib
import json
from pathlib import Path

import duckdb

from ml.verification.labels import (
    NLI_LABEL_TO_ID,
    NliLabel,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]

FEVER_DIRECTORY = PROJECT_ROOT / "data" / "processed" / "fever"

CLAIMS_PATH = FEVER_DIRECTORY / "claims.parquet"

RESOLVED_EVIDENCE_PATH = FEVER_DIRECTORY / "resolved_evidence.parquet"

WIKI_SENTENCES_PATH = FEVER_DIRECTORY / "wiki_sentences.parquet"

OUTPUT_PATH = FEVER_DIRECTORY / "nli_pairs.parquet"

METADATA_DIRECTORY = PROJECT_ROOT / "data" / "metadata"

MANIFEST_PATH = METADATA_DIRECTORY / "fever_nli_dataset_manifest.json"


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
    required_paths = [
        CLAIMS_PATH,
        RESOLVED_EVIDENCE_PATH,
        WIKI_SENTENCES_PATH,
    ]

    for required_path in required_paths:
        if not required_path.exists():
            raise FileNotFoundError(f"Required FEVER artifact does not exist: {required_path}")

    METADATA_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    if OUTPUT_PATH.exists():
        OUTPUT_PATH.unlink()

    claims_sql = sql_path(CLAIMS_PATH)

    evidence_sql = sql_path(RESOLVED_EVIDENCE_PATH)

    wiki_sql = sql_path(WIKI_SENTENCES_PATH)

    output_sql = sql_path(OUTPUT_PATH)

    connection = duckdb.connect()

    try:
        print("Loading FEVER claims...")

        connection.execute(
            f"""
            CREATE TEMP VIEW claims AS

            SELECT
                claim_id,
                split,
                label,
                TRIM(claim) AS claim

            FROM read_parquet(
                '{claims_sql}'
            )

            WHERE claim IS NOT NULL
              AND TRIM(claim) <> ''
            """
        )

        print("Loading resolved gold evidence...")

        connection.execute(
            f"""
            CREATE TEMP VIEW resolved AS

            SELECT
                claim_id,
                split,
                evidence_set_id,
                evidence_item_position,
                wiki_page,
                sentence_id,
                TRIM(evidence_text)
                    AS evidence_text

            FROM read_parquet(
                '{evidence_sql}'
            )

            WHERE resolved = TRUE
              AND evidence_text IS NOT NULL
              AND TRIM(evidence_text) <> ''
              AND wiki_page IS NOT NULL
              AND sentence_id IS NOT NULL
            """
        )

        print("Building gold evidence sets...")

        entailment_id = NLI_LABEL_TO_ID[NliLabel.ENTAILMENT]

        contradiction_id = NLI_LABEL_TO_ID[NliLabel.CONTRADICTION]

        neutral_id = NLI_LABEL_TO_ID[NliLabel.NEUTRAL]

        connection.execute(
            f"""
            CREATE TEMP TABLE
                positive_examples AS

            SELECT
                c.claim_id,
                c.split,
                c.claim,
                c.label AS claim_label,

                r.evidence_set_id,

                string_agg(
                    r.evidence_text,
                    ' '
                    ORDER BY
                        r.evidence_item_position
                ) AS premise,

                list(
                    r.wiki_page
                    ORDER BY
                        r.evidence_item_position
                ) AS evidence_page_ids,

                list(
                    r.sentence_id
                    ORDER BY
                        r.evidence_item_position
                ) AS evidence_sentence_ids,

                CAST(
                    COUNT(*)
                    AS INTEGER
                ) AS evidence_sentence_count,

                CASE
                    WHEN c.label = 'SUPPORTS'
                    THEN 'ENTAILMENT'

                    WHEN c.label = 'REFUTES'
                    THEN 'CONTRADICTION'
                END AS nli_label,

                CASE
                    WHEN c.label = 'SUPPORTS'
                    THEN {entailment_id}

                    WHEN c.label = 'REFUTES'
                    THEN {contradiction_id}
                END AS nli_label_id,

                'gold_evidence_set'
                    AS source_type

            FROM claims AS c

            INNER JOIN resolved AS r
                ON c.claim_id = r.claim_id
               AND c.split = r.split

            WHERE c.label IN (
                'SUPPORTS',
                'REFUTES'
            )

            GROUP BY
                c.claim_id,
                c.split,
                c.claim,
                c.label,
                r.evidence_set_id
            """
        )

        positive_count = scalar_int(
            connection,
            """
            SELECT COUNT(*)
            FROM positive_examples
            """,
        )

        print(f"Gold NLI pairs: {positive_count:,}")

        print("Generating same-page hard neutral candidates...")

        connection.execute(
            f"""
            CREATE TEMP TABLE
                neutral_candidates AS

            WITH neighbor_targets AS (
                SELECT
                    r.claim_id,
                    r.split,
                    r.evidence_set_id,

                    r.wiki_page
                        AS page_id,

                    r.sentence_id
                        AS gold_sentence_id,

                    offsets.sentence_offset,

                    r.sentence_id
                        + offsets.sentence_offset
                        AS candidate_sentence_id,

                    ABS(
                        offsets.sentence_offset
                    ) AS distance

                FROM resolved AS r

                CROSS JOIN (
                    VALUES
                        (-2),
                        (-1),
                        (1),
                        (2)
                ) AS offsets(
                    sentence_offset
                )

                WHERE
                    r.sentence_id
                    + offsets.sentence_offset
                    >= 0
            ),

            matched_candidates AS (
                SELECT
                    target.claim_id,
                    target.split,
                    target.evidence_set_id,

                    target.page_id,
                    target.candidate_sentence_id,

                    TRIM(wiki.text)
                        AS premise,

                    target.distance,

                    ROW_NUMBER() OVER (
                        PARTITION BY
                            target.claim_id,
                            target.split,
                            target.evidence_set_id

                        ORDER BY
                            target.distance ASC,
                            target.page_id ASC,
                            target.candidate_sentence_id ASC,
                            LENGTH(
                                TRIM(wiki.text)
                            ) DESC
                    ) AS candidate_rank

                FROM neighbor_targets
                    AS target

                INNER JOIN read_parquet(
                    '{wiki_sql}'
                ) AS wiki

                    ON wiki.page_id
                        = target.page_id

                   AND wiki.sentence_id
                        = target.candidate_sentence_id

                WHERE wiki.text IS NOT NULL
                  AND TRIM(wiki.text) <> ''

                  AND NOT EXISTS (
                      SELECT 1

                      FROM resolved
                          AS gold_key

                      WHERE
                          gold_key.claim_id
                              = target.claim_id

                          AND gold_key.split
                              = target.split

                          AND gold_key.wiki_page
                              = target.page_id

                          AND gold_key.sentence_id
                              = target.candidate_sentence_id
                  )

                  AND NOT EXISTS (
                      SELECT 1

                      FROM resolved
                          AS gold_text

                      WHERE
                          gold_text.claim_id
                              = target.claim_id

                          AND gold_text.split
                              = target.split

                          AND TRIM(
                              gold_text.evidence_text
                          ) = TRIM(
                              wiki.text
                          )
                  )
            )

            SELECT
                claim_id,
                split,
                evidence_set_id,
                page_id,
                candidate_sentence_id,
                premise

            FROM matched_candidates

            WHERE candidate_rank = 1
            """
        )

        neutral_candidate_count = scalar_int(
            connection,
            """
                SELECT COUNT(*)
                FROM neutral_candidates
                """,
        )

        print(f"Hard neutral pairs: {neutral_candidate_count:,}")

        print("Building final NLI dataset...")

        connection.execute(
            f"""
            COPY (
                WITH neutral_examples AS (
                    SELECT
                        positive.claim_id,
                        positive.split,
                        positive.claim,
                        positive.claim_label,

                        positive.evidence_set_id,

                        neutral.premise,

                        [neutral.page_id]
                            AS evidence_page_ids,

                        [
                            neutral.candidate_sentence_id
                        ] AS evidence_sentence_ids,

                        CAST(
                            1 AS INTEGER
                        ) AS evidence_sentence_count,

                        'NEUTRAL'
                            AS nli_label,

                        {neutral_id}
                            AS nli_label_id,

                        'same_page_hard_negative'
                            AS source_type

                    FROM positive_examples
                        AS positive

                    INNER JOIN neutral_candidates
                        AS neutral

                        ON positive.claim_id
                            = neutral.claim_id

                       AND positive.split
                            = neutral.split

                       AND positive.evidence_set_id
                            = neutral.evidence_set_id
                ),

                combined AS (
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

                    FROM positive_examples

                    UNION ALL

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

                    FROM neutral_examples
                )

                SELECT
                    CAST(
                        ROW_NUMBER() OVER (
                            ORDER BY
                                split,
                                claim_id,
                                evidence_set_id,
                                nli_label_id,
                                source_type
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

                FROM combined
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

        duplicate_rows = scalar_int(
            connection,
            f"""
            SELECT COUNT(*)

            FROM (
                SELECT
                    claim_id,
                    split,
                    premise,
                    nli_label,
                    COUNT(*) AS row_count

                FROM read_parquet(
                    '{output_sql}'
                )

                GROUP BY
                    claim_id,
                    split,
                    premise,
                    nli_label

                HAVING COUNT(*) > 1
            )
            """,
        )

        empty_rows = scalar_int(
            connection,
            f"""
            SELECT COUNT(*)

            FROM read_parquet(
                '{output_sql}'
            )

            WHERE claim IS NULL
               OR TRIM(claim) = ''
               OR premise IS NULL
               OR TRIM(premise) = ''
            """,
        )

    finally:
        connection.close()

    if empty_rows > 0:
        raise ValueError(f"Generated NLI dataset contains {empty_rows} empty claim/premise rows.")

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

    hard_negative_coverage = neutral_candidate_count / positive_count if positive_count > 0 else 0.0

    manifest: dict[str, object] = {
        "dataset": "fever",
        "stage": "nli_pair_dataset",
        "strategy": {
            "entailment": ("SUPPORTS claim with complete gold evidence set"),
            "contradiction": ("REFUTES claim with complete gold evidence set"),
            "neutral": ("nearest non-gold sentence from the same gold Wikipedia page"),
        },
        "label_mapping": {label.value: label_id for label, label_id in NLI_LABEL_TO_ID.items()},
        "gold_positive_pairs": (positive_count),
        "hard_neutral_pairs": (neutral_candidate_count),
        "hard_negative_coverage": (hard_negative_coverage),
        "total_rows": total_rows,
        "duplicate_rows": (duplicate_rows),
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
    print("FEVER NLI dataset completed.")

    print(f"Gold positive pairs: {positive_count:,}")

    print(f"Hard neutral pairs: {neutral_candidate_count:,}")

    print(f"Hard-negative coverage: {hard_negative_coverage:.2%}")

    print(f"Total NLI pairs: {total_rows:,}")

    print(f"Duplicate rows: {duplicate_rows:,}")

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
