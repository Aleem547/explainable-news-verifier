"""Phase 8B: narrow entity-title safeguards, including integration with NLI."""

from collections.abc import Sequence

from apps.api.schemas.verification import QualityExclusionResponse
from ml.retrieval.pipeline import RetrievedEvidence
from ml.verification.entity_relevance import (
    EntityMismatch,
    entity_mismatch,
    parse_page_title,
)
from ml.verification.evidence_pipeline import (
    ClaimVerificationPipeline,
    EvidenceVerdict,
    NliProbabilities,
)
from ml.verification.evidence_quality import ExclusionReason, screen_evidence

ORIGINAL = "Eiffel_Tower"
TEXAS = "Eiffel_Tower_-LRB-Paris,_Texas-RRB-"
TENNESSEE = "Eiffel_Tower_-LRB-Paris,_Tennessee-RRB-"
CEDAR_FAIR = "Eiffel_Tower_-LRB-Cedar_Fair-RRB-"


def evidence(page_id: str, rank: int) -> RetrievedEvidence:
    return RetrievedEvidence(
        rank=rank,
        page_id=page_id,
        sentence_id=rank,
        text=f"Relevant sentence from page {rank} mentioning the Eiffel Tower.",
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
    def __init__(self) -> None:
        self.calls: list[str] = []

    def predict(self, claim: str, evidence_texts: Sequence[str]) -> list[NliProbabilities]:
        self.calls = list(evidence_texts)
        return [NliProbabilities(0.97, 0.02, 0.01) for _ in evidence_texts]


def test_fever_title_parsing() -> None:
    assert parse_page_title(TEXAS).base == "eiffel tower"
    assert parse_page_title(TEXAS).qualifier == "paris texas"
    assert parse_page_title("Eiffel_Tower_(Paris,_Texas)").qualifier == "paris texas"
    assert parse_page_title(ORIGINAL).qualifier is None


def test_unqualified_location_claim_discards_sibling_variants() -> None:
    items = [evidence(TEXAS, 1), evidence(CEDAR_FAIR, 2), evidence(ORIGINAL, 3)]
    output = screen_evidence("The Eiffel Tower is located in Paris", items, top_k=3)
    assert output.selected == [items[2]]
    assert [item.reason for item in output.excluded] == [
        ExclusionReason.ENTITY_VARIANT_MISMATCH,
        ExclusionReason.ENTITY_VARIANT_MISMATCH,
    ]


def test_unqualified_location_claim_does_not_need_canonical_page_to_abstain() -> None:
    assert entity_mismatch("The Eiffel Tower is in Berlin", TEXAS, [TEXAS]) == (
        EntityMismatch.ENTITY_VARIANT_MISMATCH
    )


def test_claimed_destination_does_not_disambiguate_the_subject() -> None:
    # "located in Paris, Texas" asserts a destination for the original tower;
    # it is not the same as "the Eiffel Tower in Paris, Texas".
    claim = "The Eiffel Tower is located in Paris, Texas"
    assert entity_mismatch(claim, TEXAS, [ORIGINAL, TEXAS]) == (
        EntityMismatch.ENTITY_VARIANT_MISMATCH
    )


def test_nongeographic_qualifier_with_no_canonical_page_is_not_guessed() -> None:
    assert entity_mismatch("The Eiffel Tower is in Paris", CEDAR_FAIR, [CEDAR_FAIR]) is None


def test_explicit_replica_claim_keeps_variant() -> None:
    items = [evidence(TEXAS, 1), evidence(TENNESSEE, 2)]
    result = screen_evidence("Paris Texas has an Eiffel Tower replica", items, top_k=5)
    assert result.selected == items
    assert result.excluded == []


def test_nonlocative_claim_retains_variant_for_nli() -> None:
    items = [evidence(TEXAS, 1), evidence(ORIGINAL, 2)]
    result = screen_evidence("The Eiffel Tower was completed in 1889", items, top_k=5)
    assert result.selected == items


def test_explicit_scoped_variant_avoids_canonical_page() -> None:
    claim = "The Eiffel Tower in Paris, Texas is located in Paris, Texas"
    items = [evidence(ORIGINAL, 1), evidence(TEXAS, 2), evidence(TENNESSEE, 3)]
    result = screen_evidence(claim, items, top_k=3)
    assert result.selected == [items[1]]
    assert [e.reason for e in result.excluded] == [
        ExclusionReason.CANONICAL_PAGE_FOR_QUALIFIED_ENTITY,
        ExclusionReason.ENTITY_VARIANT_MISMATCH,
    ]


def test_other_subject_page_is_untouched() -> None:
    assert (
        entity_mismatch(
            "The Eiffel Tower is located in Paris",
            "Statue_of_Liberty_-LRB-New_York,_USA-RRB-",
            [ORIGINAL, "Statue_of_Liberty_-LRB-New_York,_USA-RRB-"],
        )
        is None
    )


def test_filtered_variants_cannot_influence_supporting_pages() -> None:
    items = [evidence(TEXAS, 1), evidence(ORIGINAL, 2)]
    predictor = Predictor()
    result = ClaimVerificationPipeline(retriever=Retriever(items), nli_predictor=predictor).verify(
        "The Eiffel Tower is located in Paris", top_k=2
    )
    assert result.verdict == EvidenceVerdict.SUPPORTING_EVIDENCE
    assert result.supporting_pages == [ORIGINAL]
    assert result.assessed_count == 1
    assert predictor.calls == [items[1].text]
    assert result.quality_exclusions[0].reason == ExclusionReason.ENTITY_VARIANT_MISMATCH


def test_no_relevant_page_leads_to_abstention() -> None:
    predictor = Predictor()
    result = ClaimVerificationPipeline(
        retriever=Retriever([evidence(TEXAS, 1)]), nli_predictor=predictor
    ).verify("The Eiffel Tower is located in Berlin", top_k=5)
    assert result.verdict == EvidenceVerdict.INSUFFICIENT_EVIDENCE
    assert predictor.calls == []
    assert result.quality_excluded_count == 1


def test_api_schema_admits_new_exclusion_reasons() -> None:
    assert (
        QualityExclusionResponse(
            rank=1, page_id=TEXAS, sentence_id=0, reason="ENTITY_VARIANT_MISMATCH"
        ).reason
        == "ENTITY_VARIANT_MISMATCH"
    )
    assert (
        QualityExclusionResponse(
            rank=1,
            page_id=ORIGINAL,
            sentence_id=0,
            reason="CANONICAL_PAGE_FOR_QUALIFIED_ENTITY",
        ).reason
        == "CANONICAL_PAGE_FOR_QUALIFIED_ENTITY"
    )
