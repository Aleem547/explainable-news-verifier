from pydantic import BaseModel, Field

from ml.datasets.loaders.fever import (
    FeverLabel,
)


class ClassificationRequest(BaseModel):
    claim: str = Field(
        min_length=3,
        max_length=2000,
    )


class ClassificationResponse(BaseModel):
    claim: str

    label: FeverLabel
    label_id: int

    confidence: float

    probabilities: dict[str, float]

    latency_ms: float
