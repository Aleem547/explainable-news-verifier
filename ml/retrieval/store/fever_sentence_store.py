
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Sequence

import duckdb

from ml.retrieval.sparse.bm25_sentence_ranker import SentenceDocument


class FeverSentenceStore:
    def __init__(
        self,
        parquet_path: Path,
        *,
        duckdb_threads: int = 2,
        duckdb_memory_limit_mb: int = 512,
        duckdb_max_temp_directory_size_mb: int = 1024,
    ) -> None:

        if not parquet_path.exists():
            raise FileNotFoundError(
                f"Wikipedia sentence corpus does not exist: {parquet_path}"
            )

        # Phase 12A: Validate DuckDB resource settings
        if not 1 <= duckdb_threads <= 8:
            raise ValueError("Invalid DuckDB thread count")

        if not 128 <= duckdb_memory_limit_mb <= 2048:
            raise ValueError("Invalid DuckDB memory limit")

        if not 128 <= duckdb_max_temp_directory_size_mb <= 8192:
            raise ValueError("Invalid DuckDB temporary disk limit")

        self.parquet_path = parquet_path
        self.duckdb_threads = duckdb_threads
        self.duckdb_memory_limit_mb = duckdb_memory_limit_mb
        self.duckdb_max_temp_directory_size_mb = (
            duckdb_max_temp_directory_size_mb
        )

    def get_by_page_ids(
        self,
        page_ids: Sequence[str],
    ) -> list[SentenceDocument]:

        unique_page_ids = list(
            dict.fromkeys(
                page_id
                for page_id in page_ids
                if page_id.strip()
            )
        )

        if not unique_page_ids:
            return []

        placeholders = ", ".join(
            "?" for _ in unique_page_ids
        )

        parquet_sql = (
            self.parquet_path.as_posix().replace("'", "''")
        )

        connection = duckdb.connect()

        try:
            # Phase 12A: Configurable DuckDB resources
            connection.execute(
                f"SET threads = {self.duckdb_threads}"
            )

            connection.execute(
                "SET memory_limit = "
                f"'{self.duckdb_memory_limit_mb}MB'"
            )

            # Temporary disk spilling directory
            temp_path = (
                Path(tempfile.gettempdir()) / "fever_duckdb"
            )

            temp_sql = (
                temp_path.as_posix().replace("'", "''")
            )

            connection.execute(
                f"SET temp_directory = '{temp_sql}'"
            )

            connection.execute(
                "SET max_temp_directory_size = "
                f"'{self.duckdb_max_temp_directory_size_mb}MB'"
            )

            # Retrieve and deduplicate FEVER sentences
            rows = connection.execute(
                f"""
                SELECT
                    page_id,
                    sentence_id,
                    text
                FROM (
                    SELECT
                        page_id,
                        sentence_id,
                        text,
                        ROW_NUMBER() OVER (
                            PARTITION BY page_id, sentence_id
                            ORDER BY
                                LENGTH(
                                    COALESCE(raw_line, '')
                                ) DESC,
                                source_member ASC
                        ) AS row_number
                    FROM read_parquet('{parquet_sql}')
                    WHERE page_id IN ({placeholders})
                )
                WHERE row_number = 1
                  AND text IS NOT NULL
                  AND TRIM(text) <> ''
                ORDER BY
                    page_id,
                    sentence_id
                """,
                unique_page_ids,
            ).fetchall()

        finally:
            connection.close()

        return [
            SentenceDocument(
                page_id=str(row[0]),
                sentence_id=int(row[1]),
                text=str(row[2]),
            )
            for row in rows
        ]
