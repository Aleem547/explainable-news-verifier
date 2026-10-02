from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field


class DatasetPurpose(StrEnum):
    ARTICLE_CLASSIFICATION = "article_classification"
    CLAIM_VERIFICATION = "claim_verification"
    EVIDENCE_RETRIEVAL = "evidence_retrieval"
    NLI = "nli"
    RERANKING = "reranking"


class DatasetSplit(StrEnum):
    TRAIN = "train"
    VALIDATION = "validation"
    TEST = "test"


class DatasetSource(BaseModel):
    name: str
    provider: str
    homepage: str | None = None
    license_name: str | None = None
    citation: str | None = None


class DatasetDefinition(BaseModel):
    name: str
    version: str

    purposes: list[DatasetPurpose]

    source: DatasetSource

    raw_path: Path
    processed_path: Path

    description: str

    expected_splits: list[DatasetSplit] = Field(
        default_factory=lambda: [
            DatasetSplit.TRAIN,
            DatasetSplit.VALIDATION,
            DatasetSplit.TEST,
        ]
    )
