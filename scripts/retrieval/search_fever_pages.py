import argparse
from pathlib import Path

from ml.retrieval.sparse.tantivy_page_retriever import (
    TantivyPageRetriever,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]

INDEX_DIRECTORY = PROJECT_ROOT / "data" / "indexes" / "fever" / "page_bm25"


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=("Search the FEVER Wikipedia page BM25 index."))

    parser.add_argument(
        "query",
        type=str,
        help="Natural-language claim to search.",
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum number of results.",
    )

    return parser.parse_args()


def main() -> None:
    arguments = parse_arguments()

    retriever = TantivyPageRetriever(INDEX_DIRECTORY)

    results = retriever.search(
        arguments.query,
        limit=arguments.limit,
    )

    print()
    print(f"Query: {arguments.query}")

    print(f"Results: {len(results)}")

    print()

    if not results:
        print("No pages found.")
        return

    for result in results:
        print(f"{result.rank:>2}. {result.page_id}")

        print(f"    title: {result.title}")

        print(f"    score: {result.score:.4f}")


if __name__ == "__main__":
    main()
