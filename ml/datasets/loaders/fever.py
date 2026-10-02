from enum import StrEnum
from typing import Any

from pydantic import BaseModel


class FeverLabel(StrEnum):
    SUPPORTS = "SUPPORTS"
    REFUTES = "REFUTES"
    NOT_ENOUGH_INFO = "NOT ENOUGH INFO"


class FeverEvidenceItem(BaseModel):
    annotation_id: int | None
    evidence_id: int | None
    wiki_page: str | None
    sentence_id: int | None


class FeverRecord(BaseModel):
    claim_id: int
    label: FeverLabel
    claim: str
    evidence: list[list[FeverEvidenceItem]]


def parse_fever_record(payload: dict[str, Any]) -> FeverRecord:
    claim_id = int(payload["id"])
    label = FeverLabel(payload["label"])
    claim = str(payload["claim"]).strip()

    if not claim:
        raise ValueError("FEVER claim cannot be empty")

    raw_evidence = payload.get("evidence", [])
    parsed_evidence: list[list[FeverEvidenceItem]] = []

    for raw_set in raw_evidence:
        evidence_set: list[FeverEvidenceItem] = []

        for raw_item in raw_set:
            if len(raw_item) != 4:
                raise ValueError("Each FEVER evidence item must contain exactly 4 values")

            evidence_set.append(
                FeverEvidenceItem(
                    annotation_id=raw_item[0],
                    evidence_id=raw_item[1],
                    wiki_page=raw_item[2],
                    sentence_id=raw_item[3],
                )
            )

        parsed_evidence.append(evidence_set)

    return FeverRecord(
        claim_id=claim_id,
        label=label,
        claim=claim,
        evidence=parsed_evidence,
    )
