from collections.abc import Sequence

import pytest

from ml.retrieval.pipeline import RetrievedEvidence
from ml.verification.evidence_pipeline import (
    ClaimVerificationPipeline,
    EvidenceVerdict,
    NliProbabilities,
)


def evidence(page_id: str, rank: int) -> RetrievedEvidence:
    return RetrievedEvidence(
        rank=rank,
        page_id=page_id,
        sentence_id=rank,
        text=f"Sentence from {page_id}",
        page_rank=rank,
        bm25_score=1.0,
        dense_score=0.8,
        rrf_score=0.03,
        cross_encoder_score=6.0,
    )


class FakeRetriever:
    def __init__(self, results: list[RetrievedEvidence]) -> None:
        self.results = results

    def retrieve(self, claim: str, *, top_k: int = 10) -> list[RetrievedEvidence]:
        return self.results[:top_k]


class FakeNliPredictor:
    def __init__(self, results: list[NliProbabilities]) -> None:
        self.results = results
        self.calls = 0

    def predict(self, claim: str, evidence_texts: Sequence[str]) -> list[NliProbabilities]:
        self.calls += 1
        return self.results


def make_pipeline(
    results: list[RetrievedEvidence], predictions: list[NliProbabilities]
) -> ClaimVerificationPipeline:
    return ClaimVerificationPipeline(
        retriever=FakeRetriever(results),
        nli_predictor=FakeNliPredictor(predictions),
        confidence_threshold=0.90,
    )


def test_no_retrieved_evidence_abstains() -> None:
    predictor = FakeNliPredictor([])
    pipeline = ClaimVerificationPipeline(retriever=FakeRetriever([]), nli_predictor=predictor)
    result = pipeline.verify("The Eiffel Tower is in Paris")
    assert result.verdict == EvidenceVerdict.INSUFFICIENT_EVIDENCE
    assert result.evidence == []
    assert predictor.calls == 0


def test_entailing_evidence_yields_provisional_support() -> None:
    result = make_pipeline(
        [evidence("Eiffel_Tower", 1)], [NliProbabilities(0.96, 0.02, 0.02)]
    ).verify("The Eiffel Tower is in Paris")
    assert result.verdict == EvidenceVerdict.SUPPORTING_EVIDENCE
    assert result.supporting_pages == ["Eiffel_Tower"]
    assert result.evidence[0].accepted is True


def test_contradicting_evidence_yields_provisional_refutation() -> None:
    result = make_pipeline(
        [evidence("Eiffel_Tower", 1)], [NliProbabilities(0.02, 0.96, 0.02)]
    ).verify("The Eiffel Tower is in London")
    assert result.verdict == EvidenceVerdict.REFUTING_EVIDENCE
    assert result.refuting_pages == ["Eiffel_Tower"]


def test_conflicting_evidence_is_not_silently_resolved() -> None:
    result = make_pipeline(
        [evidence("Source_A", 1), evidence("Source_B", 2)],
        [NliProbabilities(0.97, 0.02, 0.01), NliProbabilities(0.03, 0.96, 0.01)],
    ).verify("Conflicting claim")
    assert result.verdict == EvidenceVerdict.CONFLICTING_EVIDENCE


def test_below_threshold_abstains() -> None:
    result = make_pipeline([evidence("Source_A", 1)], [NliProbabilities(0.86, 0.09, 0.05)]).verify(
        "Uncertain claim"
    )
    assert result.verdict == EvidenceVerdict.INSUFFICIENT_EVIDENCE
    assert result.evidence[0].accepted is False


def test_high_confidence_neutral_abstains() -> None:
    result = make_pipeline([evidence("Source_A", 1)], [NliProbabilities(0.01, 0.01, 0.98)]).verify(
        "Unrelated claim"
    )
    assert result.verdict == EvidenceVerdict.INSUFFICIENT_EVIDENCE


def test_bad_predictor_length_fails_closed() -> None:
    pipeline = make_pipeline([evidence("Source_A", 1)], [])
    with pytest.raises(ValueError, match="incorrect number"):
        pipeline.verify("Claim")


def test_bad_probability_vector_is_rejected() -> None:
    pipeline = make_pipeline([evidence("Source_A", 1)], [NliProbabilities(0.99, 0.5, 0.01)])
    with pytest.raises(ValueError, match="sum to one"):
        pipeline.verify("Claim")


def test_invalid_claim_and_top_k() -> None:
    pipeline = make_pipeline([], [])
    with pytest.raises(ValueError, match="empty"):
        pipeline.verify(" ")
    with pytest.raises(ValueError, match="top_k"):
        pipeline.verify("Claim", top_k=21)
