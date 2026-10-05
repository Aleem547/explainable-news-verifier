import argparse
from pathlib import Path
from time import perf_counter

from ml.retrieval.factory import (
    build_fever_retrieval_pipeline,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=("Run the complete FEVER evidence retrieval pipeline.")
    )

    parser.add_argument(
        "claim",
        type=str,
    )

    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
    )

    return parser.parse_args()


def main() -> None:
    arguments = parse_arguments()

    print("Loading production retrieval pipeline...")

    pipeline = build_fever_retrieval_pipeline(
        PROJECT_ROOT,
        device="cpu",
    )

    print("Retrieving evidence...")

    started = perf_counter()

    results = pipeline.retrieve(
        arguments.claim,
        top_k=arguments.top_k,
    )

    elapsed = perf_counter() - started

    print()
    print(f"Claim: {arguments.claim}")

    print(f"Evidence results: {len(results)}")

    print(f"Retrieval time: {elapsed:.2f}s")

    print()

    for result in results:
        print(f"{result.rank}. {result.page_id} [sentence {result.sentence_id}]")

        print(f"   CrossEncoder: {result.cross_encoder_score:.4f}")

        print(f"   RRF: {result.rrf_score:.6f}")

        if result.bm25_score is not None:
            print(f"   BM25: {result.bm25_score:.4f}")

        if result.dense_score is not None:
            print(f"   Dense: {result.dense_score:.4f}")

        print(f"   {result.text}")

        print()


if __name__ == "__main__":
    main()
