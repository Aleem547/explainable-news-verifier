from pydantic import BaseModel, Field


class RetrievalRequest(BaseModel):
    claim: str = Field(
        min_length=3,
        max_length=2000,
    )

    top_k: int = Field(
        default=5,
        ge=1,
        le=20,
    )


class EvidenceResponse(BaseModel):
    rank: int

    page_id: str
    sentence_id: int
    text: str

    page_rank: int | None

    bm25_score: float | None
    dense_score: float | None

    rrf_score: float
    cross_encoder_score: float


class RetrievalResponse(BaseModel):
    claim: str

    requested_top_k: int
    returned_evidence: int

    latency_ms: float

    evidence: list[EvidenceResponse]
