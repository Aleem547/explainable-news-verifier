"""Phase 8E: named-subject grounding and non-decisive evidence audit."""

from collections.abc import Sequence
from dataclasses import asdict

import pytest

from apps.api.schemas.verification import VerificationResponse
from ml.retrieval.pipeline import RetrievedEvidence
from ml.verification.decisive_admissibility import (
    AdmissibilityReason,
    check_decisive_admissibility,
    named_subject_anchor,
)
from ml.verification.evidence_pipeline import (
    ClaimVerificationPipeline,
    EvidenceVerdict,
    NliProbabilities,
)


def retrieved(page: str, rank: int, text: str) -> RetrievedEvidence:
    return RetrievedEvidence(
        rank=rank,
        page_id=page,
        sentence_id=rank,
        text=text,
        page_rank=rank,
        bm25_score=1.0,
        dense_score=0.8,
        rrf_score=0.05,
        cross_encoder_score=3.0,
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
        return self.predictions[: len(evidence_texts)]


@pytest.mark.parametrize(
    ("claim", "expected"),
    [
        ("Rio's sequel is an American musical comedy film.", "rio"),
        ("The Eiffel Tower is located in Paris", "eiffel tower"),
        ("The Eiffel Tower in Paris, Texas is a replica", "eiffel tower"),
        ("The King and I is based on a novel", "king and i"),
        ("Paris, Texas has an Eiffel Tower replica", "paris texas"),
        ("Most of the territory of Central Serbia was included in Moesia", None),
        ("A claim about an event is true", None),
        ("Something happened somewhere", None),
    ],
)
def test_subject_parser(claim: str, expected: str | None) -> None:
    assert named_subject_anchor(claim) == expected


def test_wrong_sequel_does_not_ground_rio_subject() -> None:
    decision = check_decisive_admissibility(
        "Rio's sequel is an American musical comedy film.",
        "An_Inconvenient_Sequel-COLON-_Truth_to_Power",
        "An Inconvenient Sequel: Truth to Power is a documentary about Al Gore.",
        "CONTRADICTION",
    )
    assert decision.reason is AdmissibilityReason.SUBJECT_NOT_GROUNDED
    assert not decision.permitted
    assert decision.named_subject == "rio"


def test_rio_two_page_is_admissible_even_if_sentence_uses_pronoun() -> None:
    decision = check_decisive_admissibility(
        "Rio's sequel is an American musical comedy film.",
        "Rio_2",
        "It is a 2014 American animated musical comedy film.",
        "ENTAILMENT",
    )
    assert decision.permitted


def test_subject_in_sentence_allows_contextual_article() -> None:
    decision = check_decisive_admissibility(
        "Rio's sequel is an American musical comedy film.",
        "Animated_musical_film",
        "Rio 2 is an animated musical comedy film.",
        "ENTAILMENT",
    )
    assert decision.permitted


def test_genuine_eiffel_page_remains_admissible() -> None:
    assert check_decisive_admissibility(
        "The Eiffel Tower is located in Berlin",
        "Eiffel_Tower",
        "The Eiffel Tower is a landmark in Paris, France.",
        "CONTRADICTION",
    ).permitted


def test_ambiguous_claim_keeps_existing_behavior() -> None:
    assert check_decisive_admissibility(
        "A comedy film is popular",
        "Other_film",
        "An unrelated film exists.",
        "CONTRADICTION",
    ).permitted


def test_neutral_predictions_are_unaffected() -> None:
    assert check_decisive_admissibility(
        "Rio's sequel is an American musical comedy film.",
        "An_Inconvenient_Sequel",
        "A documentary about another topic.",
        "NEUTRAL",
    ).permitted


def test_pipeline_blocks_unrelated_primary_refutation() -> None:
    evidence = [
        retrieved(
            "An_Inconvenient_Sequel-COLON-_Truth_to_Power",
            7,
            "An Inconvenient Sequel: Truth to Power is a documentary about Al Gore.",
        )
    ]
    pipeline = ClaimVerificationPipeline(
        retriever=Retriever(evidence),
        nli_predictor=Predictor([NliProbabilities(0.02, 0.903, 0.077)]),
    )
    result = pipeline.verify("Rio's sequel is an American musical comedy film.", top_k=5)
    assert result.verdict is EvidenceVerdict.INSUFFICIENT_EVIDENCE
    assert result.admissibility_blocked_count == 1
    assert result.evidence[0].nli_label == "CONTRADICTION"
    assert result.evidence[0].accepted is False
    assert result.evidence[0].admissibility_reason == "SUBJECT_NOT_GROUNDED"
    assert result.evidence[0].contribution_role == "NOT_DECISIVE"
    parsed = VerificationResponse.model_validate(asdict(result))
    assert parsed.admissibility_blocked_count == 1
    assert parsed.evidence[0].admissibility_reason == "SUBJECT_NOT_GROUNDED"


def test_pipeline_accepts_relevant_refutation() -> None:
    evidence = [retrieved("Eiffel_Tower", 1, "The Eiffel Tower stands in Paris, France.")]
    result = ClaimVerificationPipeline(
        retriever=Retriever(evidence),
        nli_predictor=Predictor([NliProbabilities(0.02, 0.96, 0.02)]),
    ).verify("The Eiffel Tower is located in Berlin", top_k=5)
    assert result.verdict == EvidenceVerdict.REFUTING_EVIDENCE
    assert result.admissibility_blocked_count == 0
    assert result.primary_evidence_count == 1


def test_pipeline_accepts_relevant_support() -> None:
    evidence = [retrieved("Rio_2", 1, "Rio 2 is a 2014 American musical comedy film.")]
    result = ClaimVerificationPipeline(
        retriever=Retriever(evidence),
        nli_predictor=Predictor([NliProbabilities(0.98, 0.01, 0.01)]),
    ).verify("Rio's sequel is an American musical comedy film.", top_k=5)
    assert result.verdict == EvidenceVerdict.SUPPORTING_EVIDENCE
    assert result.admissibility_blocked_count == 0


def test_unaccepted_pair_does_not_inflate_block_count() -> None:
    evidence = [retrieved("An_Inconvenient_Sequel", 1, "An unrelated film.")]
    result = ClaimVerificationPipeline(
        retriever=Retriever(evidence),
        nli_predictor=Predictor([NliProbabilities(0.20, 0.79, 0.01)]),
    ).verify("Rio's sequel is an American musical comedy film.", top_k=5)
    assert result.admissibility_blocked_count == 0
    assert result.evidence[0].admissibility_reason is None


def test_guard_can_be_disabled_for_reproducible_ablation() -> None:
    evidence = [
        retrieved(
            "An_Inconvenient_Sequel",
            1,
            "An unrelated documentary about Al Gore.",
        )
    ]
    result = ClaimVerificationPipeline(
        retriever=Retriever(evidence),
        nli_predictor=Predictor([NliProbabilities(0.02, 0.96, 0.02)]),
        enforce_subject_grounding=False,
    ).verify("Rio's sequel is an American musical comedy film.", top_k=5)
    assert result.verdict == EvidenceVerdict.REFUTING_EVIDENCE
    assert result.admissibility_blocked_count == 0
