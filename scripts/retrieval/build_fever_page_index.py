import json
import shutil
from pathlib import Path

import pyarrow.parquet as pq
import tantivy

from ml.retrieval.sparse.normalization import (
    normalize_wiki_title,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]

PAGES_PATH = PROJECT_ROOT / "data" / "processed" / "fever" / "wiki_pages.parquet"

INDEX_DIRECTORY = PROJECT_ROOT / "data" / "indexes" / "fever" / "page_bm25"

METADATA_DIRECTORY = PROJECT_ROOT / "data" / "metadata"

MANIFEST_PATH = METADATA_DIRECTORY / "fever_page_bm25_index_manifest.json"

BATCH_SIZE = 5_000

WRITER_HEAP_SIZE = 512_000_000
WRITER_THREADS = 2

PROGRESS_INTERVAL = 50_000


def build_schema() -> tantivy.Schema:
    schema_builder = tantivy.SchemaBuilder()

    schema_builder.add_text_field(
        "page_id",
        stored=True,
        tokenizer_name="raw",
    )

    schema_builder.add_text_field(
        "title",
        stored=True,
        tokenizer_name="en_stem",
    )

    schema_builder.add_text_field(
        "body",
        stored=False,
        tokenizer_name="en_stem",
    )

    return schema_builder.build()


def recreate_index_directory() -> None:
    if INDEX_DIRECTORY.exists():
        shutil.rmtree(INDEX_DIRECTORY)

    INDEX_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )


def build_index() -> dict[str, object]:
    if not PAGES_PATH.exists():
        raise FileNotFoundError(f"Missing Wikipedia pages file: {PAGES_PATH}")

    METADATA_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    recreate_index_directory()

    parquet_file = pq.ParquetFile(PAGES_PATH)

    total_rows = parquet_file.metadata.num_rows

    print("Building streaming FEVER page BM25 index...")

    print(f"Wikipedia pages: {total_rows:,}")

    print(f"Batch size: {BATCH_SIZE:,}")

    print(f"Tantivy writer memory: {WRITER_HEAP_SIZE / 1_000_000:.0f} MB")

    print(f"Writer threads: {WRITER_THREADS}")

    schema = build_schema()

    index = tantivy.Index(
        schema,
        path=str(INDEX_DIRECTORY),
    )

    writer = index.writer(
        heap_size=WRITER_HEAP_SIZE,
        num_threads=WRITER_THREADS,
    )

    total_pages = 0
    skipped_pages = 0
    next_progress = PROGRESS_INTERVAL

    try:
        for batch in parquet_file.iter_batches(
            batch_size=BATCH_SIZE,
            columns=[
                "page_id",
                "text",
            ],
        ):
            page_ids = batch.column("page_id").to_pylist()

            page_texts = batch.column("text").to_pylist()

            for page_id_value, text_value in zip(
                page_ids,
                page_texts,
                strict=True,
            ):
                if page_id_value is None:
                    skipped_pages += 1
                    continue

                page_id = str(page_id_value).strip()

                if not page_id:
                    skipped_pages += 1
                    continue

                title = normalize_wiki_title(page_id)

                if text_value is None:
                    body = ""
                else:
                    body = str(text_value)

                document = tantivy.Document()

                document.add_text(
                    "page_id",
                    page_id,
                )

                document.add_text(
                    "title",
                    title,
                )

                document.add_text(
                    "body",
                    body,
                )

                writer.add_document(document)

                total_pages += 1

                if total_pages >= next_progress:
                    percentage = total_pages / total_rows * 100

                    print(f"Indexed {total_pages:,} / {total_rows:,} pages ({percentage:.2f}%)")

                    next_progress += PROGRESS_INTERVAL

        print()
        print("Committing Tantivy index...")

        writer.commit()

        print("Waiting for Tantivy segment merges...")

        writer.wait_merging_threads()

    except Exception:
        del writer
        raise

    index.reload()

    indexed_percentage = total_pages / total_rows * 100 if total_rows else 0.0

    manifest: dict[str, object] = {
        "dataset": "fever",
        "stage": "page_bm25_index",
        "source": str(PAGES_PATH.relative_to(PROJECT_ROOT)),
        "index_directory": str(INDEX_DIRECTORY.relative_to(PROJECT_ROOT)),
        "source_rows": total_rows,
        "pages_indexed": total_pages,
        "pages_skipped": skipped_pages,
        "indexed_percentage": (indexed_percentage),
        "batch_size": BATCH_SIZE,
        "writer_heap_size_bytes": (WRITER_HEAP_SIZE),
        "writer_threads": (WRITER_THREADS),
        "tokenizers": {
            "page_id": "raw",
            "title": "en_stem",
            "body": "en_stem",
        },
        "fields": {
            "page_id": {
                "indexed": True,
                "stored": True,
            },
            "title": {
                "indexed": True,
                "stored": True,
            },
            "body": {
                "indexed": True,
                "stored": False,
            },
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
    print("FEVER page BM25 index completed.")

    print(f"Pages indexed: {total_pages:,}")

    print(f"Pages skipped: {skipped_pages:,}")

    print(f"Coverage: {indexed_percentage:.4f}%")

    print(f"Index: {INDEX_DIRECTORY}")

    print(f"Manifest: {MANIFEST_PATH}")

    return manifest


def main() -> None:
    build_index()


if __name__ == "__main__":
    main()
