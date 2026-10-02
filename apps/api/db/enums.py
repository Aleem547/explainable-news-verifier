from enum import StrEnum


class SourceType(StrEnum):
    NEWS = "news"
    FACT_CHECKER = "fact_checker"
    OFFICIAL = "official"
    RESEARCH = "research"
    SOCIAL = "social"
    OTHER = "other"


class DocumentType(StrEnum):
    ARTICLE = "article"
    FACT_CHECK = "fact_check"
    OFFICIAL_STATEMENT = "official_statement"
    RESEARCH_PAPER = "research_paper"
    SOCIAL_POST = "social_post"
    OTHER = "other"


class ClaimStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    VERIFIED = "verified"
    FAILED = "failed"


class AnalysisJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class EvidenceStance(StrEnum):
    SUPPORT = "support"
    REFUTE = "refute"
    NEUTRAL = "neutral"
    INSUFFICIENT = "insufficient"


class PredictionTask(StrEnum):
    CONTENT_CLASSIFICATION = "content_classification"
    CLAIM_EXTRACTION = "claim_extraction"
    RETRIEVAL = "retrieval"
    RERANKING = "reranking"
    NLI = "nli"
    FUSION = "fusion"


class VerificationVerdict(StrEnum):
    SUPPORTED = "supported"
    LIKELY_SUPPORTED = "likely_supported"
    REFUTED = "refuted"
    LIKELY_REFUTED = "likely_refuted"
    CONFLICTING = "conflicting_evidence"
    INSUFFICIENT = "insufficient_evidence"


class ActorType(StrEnum):
    USER = "user"
    SYSTEM = "system"
    WORKER = "worker"
    MODEL = "model"
