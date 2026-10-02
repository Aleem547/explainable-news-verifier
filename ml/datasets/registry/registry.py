from pathlib import Path

from ml.datasets.registry.models import (
    DatasetDefinition,
    DatasetPurpose,
    DatasetSource,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]


FEVER = DatasetDefinition(
    name="fever",
    version="1.0",
    purposes=[
        DatasetPurpose.CLAIM_VERIFICATION,
        DatasetPurpose.EVIDENCE_RETRIEVAL,
        DatasetPurpose.NLI,
    ],
    source=DatasetSource(
        name="FEVER",
        provider="FEVER",
        homepage="https://fever.ai/dataset/fever.html",
    ),
    raw_path=PROJECT_ROOT / "data" / "raw" / "fever",
    processed_path=PROJECT_ROOT / "data" / "processed" / "fever",
    description=(
        "Fact Extraction and VERification dataset containing "
        "claims, labels, and evidence annotations."
    ),
)


AVERITEC = DatasetDefinition(
    name="averitec",
    version="1.0",
    purposes=[
        DatasetPurpose.CLAIM_VERIFICATION,
        DatasetPurpose.EVIDENCE_RETRIEVAL,
    ],
    source=DatasetSource(
        name="AVeriTeC",
        provider="AVeriTeC",
        homepage="https://fever.ai/dataset/averitec.html",
    ),
    raw_path=PROJECT_ROOT / "data" / "raw" / "averitec",
    processed_path=PROJECT_ROOT / "data" / "processed" / "averitec",
    description=(
        "Real-world claim verification dataset containing "
        "claims, evidence, and textual justifications."
    ),
)


DATASETS: dict[str, DatasetDefinition] = {
    FEVER.name: FEVER,
    AVERITEC.name: AVERITEC,
}


def get_dataset(name: str) -> DatasetDefinition:
    try:
        return DATASETS[name]
    except KeyError as exc:
        raise ValueError(f"Unknown dataset: {name}") from exc


def list_datasets() -> list[DatasetDefinition]:
    return list(DATASETS.values())
