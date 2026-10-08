"""Import all ORM models so Alembic and SQLAlchemy see every table."""

from apps.api.db.models.analysis_job import AnalysisJob
from apps.api.db.models.audit import AuditEvent
from apps.api.db.models.claim import AtomicClaim, Claim
from apps.api.db.models.cross_source_assessment import CrossSourceAssessment
from apps.api.db.models.cross_source_evidence import CrossSourceEvidence
from apps.api.db.models.discovery_record import DiscoveryRecord
from apps.api.db.models.document_context_assessment import DocumentContextAssessment
from apps.api.db.models.document import Document
from apps.api.db.models.document_passage import DocumentPassage
from apps.api.db.models.document_version import DocumentVersion
from apps.api.db.models.evidence import Evidence
from apps.api.db.models.evidence_provenance import EvidenceProvenance
from apps.api.db.models.independence_assessment import IndependenceAssessment
from apps.api.db.models.independence_pair import IndependencePair
from apps.api.db.models.index_outbox import IndexOutbox
from apps.api.db.models.model_run import ModelRun
from apps.api.db.models.prediction import Prediction
from apps.api.db.models.retrieval_observation import RetrievalObservation
from apps.api.db.models.source import Source
from apps.api.db.models.source_profile_observation import SourceProfileObservation
from apps.api.db.models.verification import VerificationResult

__all__ = [
    "AnalysisJob",
    "AtomicClaim",
    "AuditEvent",
    "Claim",
    "CrossSourceAssessment",
    "CrossSourceEvidence",
    "DiscoveryRecord",
    "DocumentContextAssessment",
    "Document",
    "DocumentPassage",
    "DocumentVersion",
    "Evidence",
    "EvidenceProvenance",
    "IndependenceAssessment",
    "IndependencePair",
    "IndexOutbox",
    "ModelRun",
    "Prediction",
    "RetrievalObservation",
    "Source",
    "SourceProfileObservation",
    "VerificationResult",
]
