from collections.abc import Sequence
from pathlib import Path

import duckdb

from ml.retrieval.sparse.bm25_sentence_ranker import (
    SentenceDocument,
)


class FeverSentenceStore:
    def __init__(
        self,
        parquet_path: Path,
    ) -> None:
        if not parquet_path.exists():
            raise FileNotFoundError(f"Wikipedia sentence corpus does not exist: {parquet_path}")

        self.parquet_path = parquet_path

    def get_by_page_ids(
        self,
        page_ids: Sequence[str],
    ) -> list[SentenceDocument]:
        unique_page_ids = list(dict.fromkeys(page_id for page_id in page_ids if page_id.strip()))

        if not unique_page_ids:
            return []

        placeholders = ", ".join("?" for _ in unique_page_ids)

        parquet_sql = self.parquet_path.as_posix().replace("'", "''")

        connection = duckdb.connect()

        try:
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
                            PARTITION BY
                                page_id,
                                sentence_id

                            ORDER BY
                                LENGTH(
                                    COALESCE(
                                        raw_line,
                                        ''
                                    )
                                ) DESC,

                                source_member ASC
                        ) AS row_number

                    FROM read_parquet(
                        '{parquet_sql}'
                    )

                    WHERE page_id IN (
                        {placeholders}
                    )
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
