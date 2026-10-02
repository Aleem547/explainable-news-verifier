import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from ml.datasets.loaders.fever import FeverRecord, parse_fever_record

PROJECT_ROOT = Path(__file__).resolve().parents[2]

RAW_DIRECTORY = PROJECT_ROOT / "data" / "raw" / "fever"
PROCESSED_DIRECTORY = PROJECT_ROOT / "data" / "processed" / "fever"
METADATA_DIRECTORY = PROJECT_ROOT / "data" / "metadata"

FILES = {
    "train": "train.jsonl",
    "validation": "paper_dev.jsonl",
    "test": "paper_test.jsonl",
}

CLAIMS_BATCH_SIZE = 5_000
EVIDENCE_BATCH_SIZE = 20_000


CLAIMS_SCHEMA = pa.schema(
    [
        pa.field("claim_id", pa.int64()),
        pa.field("split", pa.string()),
        pa.field("label", pa.string()),
        pa.field("claim", pa.string()),
        pa.field("evidence_set_count", pa.int32()),
        pa.field("source_file", pa.string()),
    ]
)


EVIDENCE_SCHEMA = pa.schema(
    [
        pa.field("claim_id", pa.int64()),
        pa.field("split", pa.string()),
        pa.field("evidence_set_id", pa.int32()),
        pa.field("evidence_item_position", pa.int32()),
        pa.field("annotation_id", pa.int64()),
        pa.field("evidence_id", pa.int64()),
        pa.field("wiki_page", pa.string()),
        pa.field("sentence_id", pa.int32()),
    ]
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest()


def flush_rows(
    writer: pq.ParquetWriter,
    rows: list[dict[str, Any]],
    schema: pa.Schema,
) -> None:
    if not rows:
        return

    table = pa.Table.from_pylist(
        rows,
        schema=schema,
    )

    writer.write_table(table)

    rows.clear()


def create_claim_row(
    record: FeverRecord,
    split: str,
    source_file: str,
) -> dict[str, Any]:
    return {
        "claim_id": record.claim_id,
        "split": split,
        "label": record.label.value,
        "claim": record.claim,
        "evidence_set_count": len(record.evidence),
        "source_file": source_file,
    }


def create_evidence_rows(
    record: FeverRecord,
    split: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    for evidence_set_id, evidence_set in enumerate(record.evidence):
        for position, evidence_item in enumerate(evidence_set):
            rows.append(
                {
                    "claim_id": record.claim_id,
                    "split": split,
                    "evidence_set_id": evidence_set_id,
                    "evidence_item_position": position,
                    "annotation_id": evidence_item.annotation_id,
                    "evidence_id": evidence_item.evidence_id,
                    "wiki_page": evidence_item.wiki_page,
                    "sentence_id": evidence_item.sentence_id,
                }
            )

    return rows


def process_dataset() -> dict[str, object]:
    PROCESSED_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    METADATA_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    claims_output = PROCESSED_DIRECTORY / "claims.parquet"
    evidence_output = PROCESSED_DIRECTORY / "evidence.parquet"

    temporary_claims = claims_output.with_suffix(".parquet.tmp")
    temporary_evidence = evidence_output.with_suffix(".parquet.tmp")

    for path in (temporary_claims, temporary_evidence):
        if path.exists():
            path.unlink()

    claims_writer = pq.ParquetWriter(
        temporary_claims,
        CLAIMS_SCHEMA,
        compression="zstd",
    )

    evidence_writer = pq.ParquetWriter(
        temporary_evidence,
        EVIDENCE_SCHEMA,
        compression="zstd",
    )

    claims_buffer: list[dict[str, Any]] = []
    evidence_buffer: list[dict[str, Any]] = []

    split_counts: Counter[str] = Counter()
    label_counts: Counter[str] = Counter()

    total_evidence_rows = 0
    invalid_records = 0

    try:
        for split, filename in FILES.items():
            input_path = RAW_DIRECTORY / filename

            if not input_path.exists():
                raise FileNotFoundError(f"Missing FEVER file: {input_path}")

            print(f"Processing {split}: {filename}")

            with input_path.open(
                "r",
                encoding="utf-8",
            ) as input_file:
                for line_number, line in enumerate(
                    input_file,
                    start=1,
                ):
                    line = line.strip()

                    if not line:
                        continue

                    try:
                        payload = json.loads(line)
                        record = parse_fever_record(payload)
                    except Exception as exc:
                        invalid_records += 1

                        raise ValueError(
                            f"Invalid FEVER record in {filename}:{line_number}"
                        ) from exc

                    claims_buffer.append(
                        create_claim_row(
                            record=record,
                            split=split,
                            source_file=filename,
                        )
                    )

                    new_evidence_rows = create_evidence_rows(
                        record=record,
                        split=split,
                    )

                    evidence_buffer.extend(new_evidence_rows)

                    split_counts[split] += 1
                    label_counts[record.label.value] += 1

                    total_evidence_rows += len(new_evidence_rows)

                    if len(claims_buffer) >= CLAIMS_BATCH_SIZE:
                        flush_rows(
                            claims_writer,
                            claims_buffer,
                            CLAIMS_SCHEMA,
                        )

                    if len(evidence_buffer) >= EVIDENCE_BATCH_SIZE:
                        flush_rows(
                            evidence_writer,
                            evidence_buffer,
                            EVIDENCE_SCHEMA,
                        )

        flush_rows(
            claims_writer,
            claims_buffer,
            CLAIMS_SCHEMA,
        )

        flush_rows(
            evidence_writer,
            evidence_buffer,
            EVIDENCE_SCHEMA,
        )

    finally:
        claims_writer.close()
        evidence_writer.close()

    temporary_claims.replace(claims_output)
    temporary_evidence.replace(evidence_output)

    total_claims = sum(split_counts.values())

    metadata: dict[str, object] = {
        "dataset": "fever",
        "total_claims": total_claims,
        "total_evidence_rows": total_evidence_rows,
        "invalid_records": invalid_records,
        "split_counts": dict(split_counts),
        "label_counts": dict(label_counts),
        "artifacts": {
            "claims": {
                "path": str(claims_output.relative_to(PROJECT_ROOT)),
                "sha256": sha256_file(claims_output),
                "size_bytes": claims_output.stat().st_size,
            },
            "evidence": {
                "path": str(evidence_output.relative_to(PROJECT_ROOT)),
                "sha256": sha256_file(evidence_output),
                "size_bytes": evidence_output.stat().st_size,
            },
        },
    }

    metadata_path = METADATA_DIRECTORY / "fever_processing_manifest.json"

    metadata_path.write_text(
        json.dumps(
            metadata,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    return metadata


def main() -> None:
    metadata = process_dataset()

    print()
    print("FEVER processing completed.")
    print(f"Claims: {metadata['total_claims']}")
    print(f"Evidence rows: {metadata['total_evidence_rows']}")


if __name__ == "__main__":
    main()
