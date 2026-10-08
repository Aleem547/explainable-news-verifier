"""Request and response contracts for evidence-grounded claim verification."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

VerificationVerdict = Literal[
    "SUPPORTING_EVIDENCE",
    "REFUTING_EVIDENCE",
    "CONFLICTING_EVIDENCE",
    "INSUFFICIENT_EVIDENCE",
]


class VerificationRequest(BaseModel):
    claim: str = Field(min_length=3, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=20)

    @field_validator("claim")
    @classmethod
    def validate_claim(cls, claim: str) -> str:
        cleaned = claim.strip()
        if len(cleaned) < 3:
            raise ValueError("Claim must contain at least three non-whitespace characters.")
        return cleaned


class VerifiedEvidenceResponse(BaseModel):
    rank: int
    page_id: str
    sentence_id: int
    text: str
    page_rank: int | None
    bm25_score: float | None
    dense_score: float | None
    rrf_score: float
    cross_encoder_score: float
    nli_label: Literal["ENTAILMENT", "CONTRADICTION", "NEUTRAL"]
    nli_confidence: float = Field(ge=0.0, le=1.0)
    accepted: bool
    probability_entailment: float = Field(ge=0.0, le=1.0)
    probability_contradiction: float = Field(ge=0.0, le=1.0)
    probability_neutral: float = Field(ge=0.0, le=1.0)
    admissibility_reason: Literal["SUBJECT_NOT_GROUNDED"] | None = None
    contribution_role: Literal[
        "PRIMARY_SUPPORT",
        "PRIMARY_REFUTATION",
        "SAME_PAGE_ADDITIONAL",
        "NOT_DECISIVE",
    ] = "NOT_DECISIVE"


class QualityExclusionResponse(BaseModel):
    rank: int
    page_id: str
    sentence_id: int
    reason: Literal[
        "EMPTY_TEXT",
        "DISAMBIGUATION_PAGE",
        "DUPLICATE_EVIDENCE_ID",
        "DUPLICATE_TEXT",
        "NEAR_DUPLICATE_SAME_PAGE",
        "ENTITY_VARIANT_MISMATCH",
        "CANONICAL_PAGE_FOR_QUALIFIED_ENTITY",
    ]


class VerificationResponse(BaseModel):
    claim: str
    verdict: VerificationVerdict
    confidence_threshold: float = Field(ge=0.0, le=1.0)
    retrieved_count: int = Field(ge=0)
    assessed_count: int = Field(ge=0)
    supporting_pages: list[str]
    refuting_pages: list[str]
    evidence: list[VerifiedEvidenceResponse]
    latency_ms: float = Field(ge=0.0)
    quality_excluded_count: int = Field(default=0, ge=0)
    quality_exclusions: list[QualityExclusionResponse] = Field(default_factory=list)
    unused_candidate_count: int = Field(default=0, ge=0)
    aggregation_reason: Literal[
        "NO_DECISIVE_EVIDENCE", "SUPPORT_ONLY", "REFUTATION_ONLY", "OPPOSING_EVIDENCE"
    ] = "NO_DECISIVE_EVIDENCE"
    supporting_evidence_count: int = Field(default=0, ge=0)
    refuting_evidence_count: int = Field(default=0, ge=0)
    primary_evidence_count: int = Field(default=0, ge=0)
    admissibility_blocked_count: int = Field(default=0, ge=0)
    corroboration_status: Literal["NOT_ESTABLISHED_SINGLE_CORPUS"] = "NOT_ESTABLISHED_SINGLE_CORPUS"
    warning: str
