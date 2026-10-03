from dataclasses import dataclass
from pathlib import Path

import tantivy

from ml.retrieval.sparse.normalization import (
    normalize_query,
)


@dataclass(frozen=True)
class PageSearchResult:
    rank: int
    page_id: str
    title: str
    score: float


class TantivyPageRetriever:
    def __init__(
        self,
        index_directory: Path,
    ) -> None:
        if not index_directory.exists():
            raise FileNotFoundError(f"Tantivy index does not exist: {index_directory}")

        if not tantivy.Index.exists(str(index_directory)):
            raise ValueError(f"Directory does not contain a Tantivy index: {index_directory}")

        self.index = tantivy.Index.open(str(index_directory))

        self.index.reload()

    def search(
        self,
        query_text: str,
        *,
        limit: int = 10,
    ) -> list[PageSearchResult]:
        normalized = normalize_query(query_text)

        if not normalized:
            return []

        if limit <= 0:
            raise ValueError("Search limit must be greater than zero.")

        query, _errors = self.index.parse_query_lenient(
            normalized,
            [
                "title",
                "body",
            ],
            field_boosts={
                "title": 3.0,
                "body": 1.0,
            },
        )

        searcher = self.index.searcher()

        search_result = searcher.search(
            query,
            limit,
        )

        results: list[PageSearchResult] = []

        for rank, hit in enumerate(
            search_result.hits,
            start=1,
        ):
            score, address = hit

            document = searcher.doc(address)

            page_id_value = document.get_first("page_id")

            if page_id_value is None:
                continue

            title_value = document.get_first("title")

            page_id = str(page_id_value)

            if title_value is None:
                title = page_id
            else:
                title = str(title_value)

            results.append(
                PageSearchResult(
                    rank=rank,
                    page_id=page_id,
                    title=title,
                    score=float(score),
                )
            )

        return results
