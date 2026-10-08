"""Orchestrate existing retrieval, calibrated NLI and auditable page aggregation."""

import math
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from time import perf_counter
from typing import Protocol

from ml.retrieval.pipeline import RetrievedEvidence
from ml.verification.decisive_admissibility import (
    AdmissibilityDecision,
    AdmissibilityReason,
    check_decisive_admissibility,
)
from ml.verification.evidence_aggregation import (
    AggregationReason,
    ContributionRole,
    aggregate_evidence,
    contribution_role,
)
from ml.verification.evidence_quality import ExcludedEvidence, screen_evidence


class EvidenceVerdict(StrEnum):
    SUPPORTING_EVIDENCE = "SUPPORTING_EVIDENCE"
    REFUTING_EVIDENCE = "REFUTING_EVIDENCE"
    CONFLICTING_EVIDENCE = "CONFLICTING_EVIDENCE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


@dataclass(frozen=True)
class NliProbabilities:
    """Probabilities in project order: entailment, contradiction, neutral."""

    entailment: float
    contradiction: float
    neutral: float

    def checked(self) -> "NliProbabilities":
        values = (self.entailment, self.contradiction, self.neutral)
        if not all(math.isfinite(p) and 0.0 <= p <= 1.0 for p in values):
            raise ValueError("NLI probabilities must be finite values in [0, 1].")
        if not math.isclose(sum(values), 1.0, abs_tol=1e-4):
            raise ValueError("NLI probabilities must sum to one.")
        return self

    def top_label(self) -> tuple[str, float]:
        values = (
            ("ENTAILMENT", self.entailment),
            ("CONTRADICTION", self.contradiction),
            ("NEUTRAL", self.neutral),
        )
        return max(values, key=lambda item: item[1])


class EvidenceRetriever(Protocol):
    def retrieve(self, claim: str, *, top_k: int = 10) -> list[RetrievedEvidence]: ...


class NliPredictor(Protocol):
    def predict(self, claim: str, evidence_texts: Sequence[str]) -> list[NliProbabilities]: ...


@dataclass(frozen=True)
class AssessedEvidence:
    rank: int
    page_id: str
    sentence_id: int
    text: str
    page_rank: int | None
    bm25_score: float | None
    dense_score: float | None
    rrf_score: float
    cross_encoder_score: float
    nli_label: str
    nli_confidence: float
    accepted: bool
    probability_entailment: float
    probability_contradiction: float
    probability_neutral: float
    contribution_role: ContributionRole = ContributionRole.NOT_DECISIVE
    admissibility_reason: AdmissibilityReason | None = None


@dataclass(frozen=True)
class ClaimVerification:
    claim: str
    verdict: EvidenceVerdict
    confidence_threshold: float
    retrieved_count: int
    assessed_count: int
    supporting_pages: list[str]
    refuting_pages: list[str]
    evidence: list[AssessedEvidence]
    latency_ms: float
    quality_excluded_count: int = 0
    quality_exclusions: list[ExcludedEvidence] = field(default_factory=list)
    unused_candidate_count: int = 0
    aggregation_reason: AggregationReason = AggregationReason.NO_DECISIVE_EVIDENCE
    supporting_evidence_count: int = 0
    refuting_evidence_count: int = 0
    primary_evidence_count: int = 0
    corroboration_status: str = "NOT_ESTABLISHED_SINGLE_CORPUS"
    admissibility_blocked_count: int = 0
    warning: str = (
        "Provisional finding from one Wikipedia-derived corpus. Wikipedia pages "
        "are not independent external sources; NLI scores are calibrated per "
        "evidence pair, not as claim-level truth probabilities."
    )


class ClaimVerificationPipeline:
    """Combine ranked evidence with per-sentence NLI; never equate relevance with truth."""

    def __init__(
        self,
        *,
        retriever: EvidenceRetriever,
        nli_predictor: NliPredictor,
        confidence_threshold: float = 0.90,
        enforce_subject_grounding: bool = True,
    ) -> None:
        if not 0.0 < confidence_threshold <= 1.0:
            raise ValueError("confidence_threshold must be in (0, 1].")
        self.retriever = retriever
        self.nli_predictor = nli_predictor
        self.confidence_threshold = confidence_threshold
        self.enforce_subject_grounding = enforce_subject_grounding

    def verify(self, claim: str, *, top_k: int = 5) -> ClaimVerification:
        normalized_claim = claim.strip()
        if not normalized_claim:
            raise ValueError("Claim cannot be empty.")
        if not 1 <= top_k <= 20:
            raise ValueError("top_k must be between 1 and 20.")

        started = perf_counter()
        candidate_count = min(20, top_k * 2)
        retrieved = self.retriever.retrieve(normalized_claim, top_k=candidate_count)
        quality = screen_evidence(normalized_claim, retrieved, top_k=top_k)
        usable = quality.selected
        distributions = (
            self.nli_predictor.predict(normalized_claim, [item.text for item in usable])
            if usable
            else []
        )
        if len(distributions) != len(usable):
            raise ValueError("NLI predictor returned an incorrect number of results.")

        assessments: list[AssessedEvidence] = []
        blocked_count = 0
        for item, raw_distribution in zip(usable, distributions, strict=True):
            distribution = raw_distribution.checked()
            label, confidence = distribution.top_label()
            decision = (
                check_decisive_admissibility(normalized_claim, item.page_id, item.text, label)
                if self.enforce_subject_grounding
                else AdmissibilityDecision(permitted=True)
            )
            if not decision.permitted and confidence >= self.confidence_threshold:
                blocked_count += 1
            assessments.append(
                AssessedEvidence(
                    rank=item.rank,
                    page_id=item.page_id,
                    sentence_id=item.sentence_id,
                    text=item.text,
                    page_rank=item.page_rank,
                    bm25_score=item.bm25_score,
                    dense_score=item.dense_score,
                    rrf_score=item.rrf_score,
                    cross_encoder_score=item.cross_encoder_score,
                    nli_label=label,
                    nli_confidence=confidence,
                    accepted=(confidence >= self.confidence_threshold and decision.permitted),
                    probability_entailment=distribution.entailment,
                    probability_contradiction=distribution.contradiction,
                    probability_neutral=distribution.neutral,
                    admissibility_reason=(
                        decision.reason if confidence >= self.confidence_threshold else None
                    ),
                )
            )

        summary = aggregate_evidence(assessments)
        annotated = [
            replace(item, contribution_role=contribution_role(item, summary))
            for item in assessments
        ]
        return ClaimVerification(
            claim=normalized_claim,
            verdict=EvidenceVerdict(summary.verdict),
            confidence_threshold=self.confidence_threshold,
            retrieved_count=len(retrieved),
            assessed_count=len(annotated),
            supporting_pages=summary.supporting_pages,
            refuting_pages=summary.refuting_pages,
            evidence=annotated,
            latency_ms=(perf_counter() - started) * 1000,
            quality_excluded_count=len(quality.excluded),
            quality_exclusions=quality.excluded,
            unused_candidate_count=quality.unused_candidate_count,
            aggregation_reason=summary.reason,
            supporting_evidence_count=summary.supporting_evidence_count,
            refuting_evidence_count=summary.refuting_evidence_count,
            primary_evidence_count=summary.primary_count,
            admissibility_blocked_count=blocked_count,
        )
