from functools import lru_cache
from pathlib import Path
from time import perf_counter

from apps.api.schemas.classification import (
    ClassificationResponse,
)
from ml.classification.inference import (
    ClaimClassifier,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]

MODEL_DIRECTORY = PROJECT_ROOT / "models" / "claim_classifier" / "distilbert_fever_balanced_30k"


@lru_cache(maxsize=1)
def get_claim_classifier() -> ClaimClassifier:
    return ClaimClassifier(
        model_directory=(MODEL_DIRECTORY),
        device="cpu",
        max_length=128,
    )


def classify_claim(
    claim: str,
) -> ClassificationResponse:
    normalized_claim = claim.strip()

    if not normalized_claim:
        raise ValueError("Claim cannot be empty.")

    classifier = get_claim_classifier()

    started = perf_counter()

    prediction = classifier.predict(normalized_claim)

    latency_ms = (perf_counter() - started) * 1000

    return ClassificationResponse(
        claim=normalized_claim,
        label=prediction.label,
        label_id=prediction.label_id,
        confidence=(prediction.confidence),
        probabilities=(prediction.probabilities),
        latency_ms=latency_ms,
    )
