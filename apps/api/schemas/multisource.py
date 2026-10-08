"""Phase 9G restricted workflow contracts; outputs are evidence diagnostics, not truth."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


class MultiSourceAssessmentRequest(BaseModel):
    claim: str = Field(min_length=3, max_length=2000)
    passage_ids: list[UUID] = Field(min_length=2, max_length=20)
    reference_at: datetime | None = None
    max_age_days: int | None = Field(default=None, ge=1, le=36500)
    confidence_threshold: float = Field(default=0.90, gt=0, le=1, allow_inf_nan=False)

    @field_validator("claim")
    @classmethod
    def clean_claim(cls, value: str) -> str:
        cleaned = value.strip()
        if len(cleaned) < 3:
            raise ValueError("Claim must contain at least three non-whitespace characters")
        return cleaned

    @field_validator("reference_at")
    @classmethod
    def aware_reference(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("Reference time requires a timezone")
        return value

    @model_validator(mode="after")
    def validate_set(self) -> "MultiSourceAssessmentRequest":
        if len(set(self.passage_ids)) != len(self.passage_ids):
            raise ValueError("Evidence passages must be distinct")
        if self.max_age_days is not None and self.reference_at is None:
            raise ValueError("A freshness window requires an explicit reference time")
        return self


class MultiSourceEvidenceResponse(BaseModel):
    passage_id: UUID
    document_version_id: UUID
    family_id: UUID
    publisher_domain: str
    article_url: str
    passage_text: str
    passage_sha256: str
    stance: Literal["ENTAILMENT", "CONTRADICTION", "NEUTRAL"]
    confidence: float
    decision: str
    temporal_relation: str
    freshness_status: str
    metadata_flags: list[str]


class MultiSourceAssessmentResponse(BaseModel):
    assessment_id: UUID
    independence_assessment_id: UUID
    claim: str
    claim_sha256: str
    outcome: str
    independence_status: str
    independent_corroboration_established: bool = False
    provisional_supporting_families: int
    provisional_refuting_families: int
    decisive_evidence_count: int
    warnings: list[str]
    evidence: list[MultiSourceEvidenceResponse]
    interpretation: str = (
        "Provisional cross-source evidence diagnostics; not an independent fact check "
        "or a calibrated claim-level probability."
    )


class ExternalDiscoveryRequest(BaseModel):
    query: str = Field(min_length=1, max_length=300)
    limit: int = Field(default=5, ge=1, le=20)
    provider: Literal["newsapi", "google_factcheck", "both"] = "both"

    @field_validator("query")
    @classmethod
    def clean_query(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Discovery query cannot be blank")
        return cleaned


class ExternalDiscoveryResponse(BaseModel):
    searched_providers: list[str]
    failed_providers: list[str]
    discovered_hits: int
    documents_seen: int
    warning: str = (
        "Only discovery metadata is stored. No full article was fetched, "
        "indexed or assessed as supporting/refuting evidence."
    )
