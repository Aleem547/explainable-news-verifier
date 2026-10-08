"""Transport contracts for the future Phase 9 external-source connectors.

No public API endpoints are added in Phase 9A.
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class SourceRegistration(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    domain: str = Field(min_length=3, max_length=255)


class DocumentSnapshotInput(BaseModel):
    document_id: UUID
    text: str = Field(min_length=1)
    retrieved_at: datetime
    content_type: str | None = Field(default=None, max_length=128)


class RetrievalObservationInput(BaseModel):
    source_id: UUID
    provider: str = Field(min_length=1, max_length=100)
    requested_url: str = Field(min_length=1, max_length=2048)
    outcome: Literal["FETCHED", "NOT_MODIFIED", "HTTP_ERROR", "NETWORK_ERROR"]
    observed_at: datetime
    document_id: UUID | None = None
    document_version_id: UUID | None = None
    final_url: str | None = Field(default=None, max_length=2048)
    http_status: int | None = Field(default=None, ge=100, le=599)


class EvidenceProvenanceInput(BaseModel):
    evidence_id: UUID
    document_version_id: UUID
    extraction_method: str = Field(min_length=1, max_length=100)
    observation_id: UUID | None = None
    locator_json: dict[str, object] | None = None
