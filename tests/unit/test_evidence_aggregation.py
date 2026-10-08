"""Phase 8C: deterministic verdict aggregation without counting correlated sentences."""

from collections.abc import Sequence
from dataclasses import asdict, dataclass

import pytest

from apps.api.schemas.verification import VerificationResponse
from ml.retrieval.pipeline import RetrievedEvidence
from ml.verification.evidence_aggregation import (
    AggregationReason,
    ContributionRole,
    aggregate_evidence,
    contribution_role,
)
from ml.verification.evidence_pipeline import (
    ClaimVerificationPipeline,
    EvidenceVerdict,
    NliProbabilities,
)


@dataclass(frozen=True)
class Item:
    rank: int
    page_id: str
    sentence_id: int
    nli_label: str
    nli_confidence: float
    accepted: bool


def sample(
    page: str,
    rank: int,
    label: str = "ENTAILMENT",
    score: float = 0.97,
    accepted: bool = True,
) -> Item:
    return Item(rank, page, rank, label, score, accepted)


def retrieval(page: str, rank: int) -> RetrievedEvidence:
    return RetrievedEvidence(
        rank=rank,
        page_id=page,
        sentence_id=rank,
        text=f"Distinct evidence sentence {rank} from {page}.",
        page_rank=rank,
        bm25_score=2.0,
        dense_score=0.8,
        rrf_score=0.03,
        cross_encoder_score=4.0,
    )


class Retriever:
    def __init__(self, candidates: list[RetrievedEvidence]) -> None:
        self.candidates = candidates

    def retrieve(self, claim: str, *, top_k: int = 10) -> list[RetrievedEvidence]:
        return self.candidates[:top_k]


class Predictor:
    def __init__(self, predictions: list[NliProbabilities]) -> None:
        self.predictions = predictions

    def predict(self, claim: str, evidence_texts: Sequence[str]) -> list[NliProbabilities]:
        return self.predictions


def test_no_accepted_decisive_evidence_abstains() -> None:
    result = aggregate_evidence(
        [sample("A", 1, "NEUTRAL", 0.98), sample("B", 2, "ENTAILMENT", 0.85, False)]
    )
    assert result.verdict == "INSUFFICIENT_EVIDENCE"
    assert result.reason == AggregationReason.NO_DECISIVE_EVIDENCE
    assert result.primary_count == 0


def test_multiple_sentences_from_same_page_have_one_primary() -> None:
    a = sample("Article_A", 1, score=0.91)
    b = sample("Article_A", 2, score=0.98)
    result = aggregate_evidence([a, b])
    assert result.verdict == "SUPPORTING_EVIDENCE"
    assert result.supporting_pages == ["Article_A"]
    assert result.supporting_evidence_count == 2
    assert result.primary_count == 1
    assert contribution_role(a, result) == ContributionRole.SAME_PAGE_ADDITIONAL
    assert contribution_role(b, result) == ContributionRole.PRIMARY_SUPPORT


def test_multiple_pages_are_not_claimed_as_independent_sources() -> None:
    result = aggregate_evidence([sample("Article_A", 1), sample("Article_B", 2)])
    assert result.supporting_pages == ["Article_A", "Article_B"]
    assert result.primary_count == 2
    assert result.reason == AggregationReason.SUPPORT_ONLY


def test_opposing_sentences_on_same_page_are_not_cancelled() -> None:
    result = aggregate_evidence([sample("A", 1), sample("A", 2, "CONTRADICTION", 0.95)])
    assert result.verdict == "CONFLICTING_EVIDENCE"
    assert result.reason == AggregationReason.OPPOSING_EVIDENCE
    assert result.supporting_pages == ["A"]
    assert result.refuting_pages == ["A"]
    assert result.primary_count == 2


def test_opposing_pages_are_conflicting_even_if_one_is_more_confident() -> None:
    result = aggregate_evidence(
        [sample("A", 1, "ENTAILMENT", 0.99), sample("B", 2, "CONTRADICTION", 0.90)]
    )
    assert result.verdict == "CONFLICTING_EVIDENCE"
    assert result.primary_count == 2


def test_only_refutation() -> None:
    result = aggregate_evidence([sample("A", 1, "CONTRADICTION")])
    assert result.verdict == "REFUTING_EVIDENCE"
    assert result.reason == AggregationReason.REFUTATION_ONLY
    assert result.primary_count == 1


def test_tied_confidence_picks_earlier_rank() -> None:
    a = sample("A", 1)
    b = sample("A", 2)
    result = aggregate_evidence([b, a])
    assert contribution_role(a, result) == ContributionRole.PRIMARY_SUPPORT
    assert contribution_role(b, result) == ContributionRole.SAME_PAGE_ADDITIONAL


def test_unaccepted_and_neutral_never_contribute() -> None:
    not_accepted = sample("A", 1, "ENTAILMENT", 0.89, False)
    neutral = sample("B", 2, "NEUTRAL", 0.99)
    summary = aggregate_evidence([not_accepted, neutral])
    assert contribution_role(not_accepted, summary) == ContributionRole.NOT_DECISIVE
    assert contribution_role(neutral, summary) == ContributionRole.NOT_DECISIVE


def test_pipeline_adds_auditable_roles_without_changing_original_fields() -> None:
    candidates = [retrieval("A", 1), retrieval("A", 2), retrieval("B", 3)]
    probabilities = [
        NliProbabilities(0.96, 0.02, 0.02),
        NliProbabilities(0.98, 0.01, 0.01),
        NliProbabilities(0.01, 0.97, 0.02),
    ]
    result = ClaimVerificationPipeline(
        retriever=Retriever(candidates), nli_predictor=Predictor(probabilities)
    ).verify("A claim about the event", top_k=3)
    assert result.verdict == EvidenceVerdict.CONFLICTING_EVIDENCE
    assert result.assessed_count == 3
    assert result.supporting_pages == ["A"]
    assert result.refuting_pages == ["B"]
    assert result.supporting_evidence_count == 2
    assert result.refuting_evidence_count == 1
    assert result.primary_evidence_count == 2
    assert [x.contribution_role for x in result.evidence] == [
        ContributionRole.SAME_PAGE_ADDITIONAL,
        ContributionRole.PRIMARY_SUPPORT,
        ContributionRole.PRIMARY_REFUTATION,
    ]
    assert result.corroboration_status == "NOT_ESTABLISHED_SINGLE_CORPUS"
    assert VerificationResponse.model_validate(asdict(result)).primary_evidence_count == 2


def test_pipeline_with_no_items_remains_insufficient() -> None:
    result = ClaimVerificationPipeline(retriever=Retriever([]), nli_predictor=Predictor([])).verify(
        "A verifiable claim"
    )
    assert result.aggregation_reason == AggregationReason.NO_DECISIVE_EVIDENCE
    assert result.primary_evidence_count == 0


@pytest.mark.parametrize(
    "vector",
    [NliProbabilities(-0.1, 0.6, 0.5), NliProbabilities(0.8, 0.8, -0.6)],
)
def test_invalid_probability_still_fails_closed(vector: NliProbabilities) -> None:
    pipeline = ClaimVerificationPipeline(
        retriever=Retriever([retrieval("A", 1)]), nli_predictor=Predictor([vector])
    )
    with pytest.raises(ValueError):
        pipeline.verify("A verifiable claim")
