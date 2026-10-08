"""Windows-friendly, evidence-grounded verification smoke test."""

import argparse
import json
from dataclasses import asdict

from apps.api.services.retrieval import get_retrieval_pipeline
from ml.verification.evidence_pipeline import ClaimVerificationPipeline
from ml.verification.nli_inference import CalibratedNliVerifier


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify a claim against retrieved FEVER evidence.")
    parser.add_argument("--claim", required=True, help="Text of the claim to check.")
    parser.add_argument("--top-k", type=int, default=5)
    arguments = parser.parse_args()

    if not arguments.claim.strip():
        parser.error("--claim must not be blank")
    if not 1 <= arguments.top_k <= 20:
        parser.error("--top-k must be between 1 and 20")

    print("Loading frozen retrieval and calibrated NLI models (first run may take time)...")
    retrieval = get_retrieval_pipeline()
    nli_verifier = CalibratedNliVerifier(device="cpu")
    pipeline = ClaimVerificationPipeline(
        retriever=retrieval,
        nli_predictor=nli_verifier,
        confidence_threshold=0.90,
    )
    result = pipeline.verify(arguments.claim, top_k=arguments.top_k)
    print(json.dumps(asdict(result), indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
