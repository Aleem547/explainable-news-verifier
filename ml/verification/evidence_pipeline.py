"""Orchestrate existing retrieval and calibrated, evidence-pair NLI."""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from time import perf_counter
from typing import Protocol

from ml.retrieval.pipeline import RetrievedEvidence


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
    warning: str = (
        "This is a provisional inference from retrieved Wikipedia evidence. "
        "NLI confidence is per evidence pair, not a calibrated claim-level probability."
    )


class ClaimVerificationPipeline:
    """Combine ranked evidence with per-sentence NLI; never equate relevance with truth."""

    def __init__(
        self,
        *,
        retriever: EvidenceRetriever,
        nli_predictor: NliPredictor,
        confidence_threshold: float = 0.90,
    ) -> None:
        if not 0.0 < confidence_threshold <= 1.0:
            raise ValueError("confidence_threshold must be in (0, 1].")
        self.retriever = retriever
        self.nli_predictor = nli_predictor
        self.confidence_threshold = confidence_threshold

    def verify(self, claim: str, *, top_k: int = 5) -> ClaimVerification:
        normalized_claim = claim.strip()
        if not normalized_claim:
            raise ValueError("Claim cannot be empty.")
        if not 1 <= top_k <= 20:
            raise ValueError("top_k must be between 1 and 20.")

        started = perf_counter()
        retrieved = self.retriever.retrieve(normalized_claim, top_k=top_k)
        # Empty sentences should not become apparently meaningful NLI evidence.
        usable = [item for item in retrieved if item.text.strip()]
        distributions = (
            self.nli_predictor.predict(normalized_claim, [item.text for item in usable])
            if usable
            else []
        )
        if len(distributions) != len(usable):
            raise ValueError("NLI predictor returned an incorrect number of results.")

        assessments: list[AssessedEvidence] = []
        support_pages: set[str] = set()
        refute_pages: set[str] = set()

        for item, raw_distribution in zip(usable, distributions, strict=True):
            distribution = raw_distribution.checked()
            label, confidence = distribution.top_label()
            accepted = confidence >= self.confidence_threshold
            if accepted and label == "ENTAILMENT":
                support_pages.add(item.page_id)
            elif accepted and label == "CONTRADICTION":
                refute_pages.add(item.page_id)

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
                    accepted=accepted,
                    probability_entailment=distribution.entailment,
                    probability_contradiction=distribution.contradiction,
                    probability_neutral=distribution.neutral,
                )
            )

        if support_pages and refute_pages:
            verdict = EvidenceVerdict.CONFLICTING_EVIDENCE
        elif support_pages:
            verdict = EvidenceVerdict.SUPPORTING_EVIDENCE
        elif refute_pages:
            verdict = EvidenceVerdict.REFUTING_EVIDENCE
        else:
            verdict = EvidenceVerdict.INSUFFICIENT_EVIDENCE

        return ClaimVerification(
            claim=normalized_claim,
            verdict=verdict,
            confidence_threshold=self.confidence_threshold,
            retrieved_count=len(retrieved),
            assessed_count=len(assessments),
            supporting_pages=sorted(support_pages),
            refuting_pages=sorted(refute_pages),
            evidence=assessments,
            latency_ms=(perf_counter() - started) * 1000,
        )
