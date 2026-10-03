import hashlib
import io
import json
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from ml.datasets.loaders.fever_wiki import (
    parse_wiki_page,
    parse_wiki_sentences,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]

RAW_DIRECTORY = PROJECT_ROOT / "data" / "raw" / "fever"
PROCESSED_DIRECTORY = PROJECT_ROOT / "data" / "processed" / "fever"
METADATA_DIRECTORY = PROJECT_ROOT / "data" / "metadata"

WIKI_ARCHIVE = RAW_DIRECTORY / "wiki-pages.zip"

PAGES_OUTPUT = PROCESSED_DIRECTORY / "wiki_pages.parquet"
SENTENCES_OUTPUT = PROCESSED_DIRECTORY / "wiki_sentences.parquet"

MANIFEST_OUTPUT = METADATA_DIRECTORY / "fever_wiki_processing_manifest.json"

PAGE_BATCH_SIZE = 5_000
SENTENCE_BATCH_SIZE = 50_000


PAGES_SCHEMA = pa.schema(
    [
        pa.field("page_id", pa.string()),
        pa.field("text", pa.string()),
        pa.field("sentence_count", pa.int32()),
        pa.field("source_member", pa.string()),
    ]
)


SENTENCES_SCHEMA = pa.schema(
    [
        pa.field("page_id", pa.string()),
        pa.field("sentence_id", pa.int32()),
        pa.field("text", pa.string()),
        pa.field("raw_line", pa.string()),
        pa.field("source_member", pa.string()),
    ]
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as file_handle:
        for chunk in iter(
            lambda: file_handle.read(1024 * 1024),
            b"",
        ):
            digest.update(chunk)

    return digest.hexdigest()


def is_valid_wiki_member(member: str) -> bool:
    member_path = PurePosixPath(member)

    if "__MACOSX" in member_path.parts:
        return False

    if member_path.name.startswith("._"):
        return False

    return member_path.name.lower().endswith(".jsonl")


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


def process_wikipedia_corpus() -> dict[str, object]:
    if not WIKI_ARCHIVE.exists():
        raise FileNotFoundError(f"Missing FEVER Wikipedia archive: {WIKI_ARCHIVE}")

    PROCESSED_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    METADATA_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary_pages = PAGES_OUTPUT.with_suffix(".parquet.tmp")

    temporary_sentences = SENTENCES_OUTPUT.with_suffix(".parquet.tmp")

    for path in (
        temporary_pages,
        temporary_sentences,
    ):
        if path.exists():
            path.unlink()

    pages_writer = pq.ParquetWriter(
        temporary_pages,
        PAGES_SCHEMA,
        compression="zstd",
    )

    sentences_writer = pq.ParquetWriter(
        temporary_sentences,
        SENTENCES_SCHEMA,
        compression="zstd",
    )

    page_buffer: list[dict[str, Any]] = []
    sentence_buffer: list[dict[str, Any]] = []

    total_pages = 0
    total_sentences = 0
    total_members = 0

    skipped_blank_records = 0

    try:
        with zipfile.ZipFile(WIKI_ARCHIVE) as archive:
            members = sorted(
                member for member in archive.namelist() if is_valid_wiki_member(member)
            )

            if not members:
                raise ValueError("No valid FEVER Wikipedia JSONL files found in the archive.")

            print(f"Wikipedia JSONL files: {len(members)}")

            for member_index, member in enumerate(
                members,
                start=1,
            ):
                print(f"[{member_index}/{len(members)}] Processing {member}")

                total_members += 1

                with archive.open(member) as raw_file:
                    with io.TextIOWrapper(
                        raw_file,
                        encoding="utf-8",
                    ) as text_file:
                        for line_number, line in enumerate(
                            text_file,
                            start=1,
                        ):
                            line = line.strip()

                            if not line:
                                skipped_blank_records += 1
                                continue

                            try:
                                payload = json.loads(line)

                                page = parse_wiki_page(payload)

                                if page is None:
                                    skipped_blank_records += 1
                                    continue

                                sentences = parse_wiki_sentences(page)

                            except Exception as exc:
                                raise ValueError(
                                    f"Invalid FEVER Wikipedia record in {member}:{line_number}"
                                ) from exc

                            page_buffer.append(
                                {
                                    "page_id": page.page_id,
                                    "text": page.text,
                                    "sentence_count": len(sentences),
                                    "source_member": member,
                                }
                            )

                            for sentence in sentences:
                                sentence_buffer.append(
                                    {
                                        "page_id": (sentence.page_id),
                                        "sentence_id": (sentence.sentence_id),
                                        "text": sentence.text,
                                        "raw_line": (sentence.raw_line),
                                        "source_member": member,
                                    }
                                )

                            total_pages += 1
                            total_sentences += len(sentences)

                            if len(page_buffer) >= PAGE_BATCH_SIZE:
                                flush_rows(
                                    pages_writer,
                                    page_buffer,
                                    PAGES_SCHEMA,
                                )

                            if len(sentence_buffer) >= SENTENCE_BATCH_SIZE:
                                flush_rows(
                                    sentences_writer,
                                    sentence_buffer,
                                    SENTENCES_SCHEMA,
                                )

        flush_rows(
            pages_writer,
            page_buffer,
            PAGES_SCHEMA,
        )

        flush_rows(
            sentences_writer,
            sentence_buffer,
            SENTENCES_SCHEMA,
        )

    finally:
        pages_writer.close()
        sentences_writer.close()

    temporary_pages.replace(PAGES_OUTPUT)

    temporary_sentences.replace(SENTENCES_OUTPUT)

    manifest: dict[str, object] = {
        "dataset": "fever",
        "artifact": "wikipedia_corpus",
        "source_archive": str(WIKI_ARCHIVE.relative_to(PROJECT_ROOT)),
        "source_archive_sha256": sha256_file(WIKI_ARCHIVE),
        "jsonl_members_processed": total_members,
        "total_pages": total_pages,
        "total_sentences": total_sentences,
        "skipped_blank_records": (skipped_blank_records),
        "artifacts": {
            "pages": {
                "path": str(PAGES_OUTPUT.relative_to(PROJECT_ROOT)),
                "size_bytes": (PAGES_OUTPUT.stat().st_size),
                "sha256": sha256_file(PAGES_OUTPUT),
            },
            "sentences": {
                "path": str(SENTENCES_OUTPUT.relative_to(PROJECT_ROOT)),
                "size_bytes": (SENTENCES_OUTPUT.stat().st_size),
                "sha256": sha256_file(SENTENCES_OUTPUT),
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
    manifest = process_wikipedia_corpus()

    print()
    print("FEVER Wikipedia processing completed.")

    print(f"Pages: {manifest['total_pages']}")

    print(f"Sentences: {manifest['total_sentences']}")

    print(f"Skipped blank records: {manifest['skipped_blank_records']}")

    print(f"Manifest: {MANIFEST_OUTPUT}")


if __name__ == "__main__":
    main()
