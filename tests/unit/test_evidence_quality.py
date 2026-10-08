"""Phase 8A evidence hygiene: deliberately conservative, no model calls."""

from collections.abc import Sequence

from ml.retrieval.pipeline import RetrievedEvidence
from ml.verification.evidence_pipeline import (
    ClaimVerificationPipeline,
    EvidenceVerdict,
    NliProbabilities,
)
from ml.verification.evidence_quality import (
    ExclusionReason,
    canonical_text,
    is_disambiguation_page,
    screen_evidence,
)


def candidate(
    page: str,
    sentence_id: int,
    text: str,
    rank: int,
) -> RetrievedEvidence:
    return RetrievedEvidence(
        rank=rank,
        page_id=page,
        sentence_id=sentence_id,
        text=text,
        page_rank=rank,
        bm25_score=2.0,
        dense_score=0.8,
        rrf_score=0.03,
        cross_encoder_score=5.0,
    )


class Retriever:
    def __init__(self, items: list[RetrievedEvidence]) -> None:
        self.items = items
        self.called_with: list[int] = []

    def retrieve(self, claim: str, *, top_k: int = 10) -> list[RetrievedEvidence]:
        self.called_with.append(top_k)
        return self.items[:top_k]


class Predictor:
    def __init__(self, responses: list[NliProbabilities]) -> None:
        self.responses = responses
        self.last_texts: list[str] | None = None

    def predict(self, claim: str, evidence_texts: Sequence[str]) -> list[NliProbabilities]:
        self.last_texts = list(evidence_texts)
        return self.responses


def test_fever_normalization_preserves_words_and_numbers() -> None:
    assert canonical_text("The  Eiffel-Tower -LRB-France-RRB- 1889!") == (
        "the eiffel tower france 1889"
    )


def test_fever_disambiguation_detection() -> None:
    assert is_disambiguation_page("Eiffel_Tower_-LRB-disambiguation-RRB-")
    assert is_disambiguation_page("Eiffel_Tower_(disambiguation)")
    assert not is_disambiguation_page("Eiffel_Tower")
    assert not is_disambiguation_page("Eiffel_Tower_-LRB-Paris,_Texas-RRB-")


def test_disambiguation_filtered_before_nli() -> None:
    nav = candidate("Eiffel_Tower_-LRB-disambiguation-RRB-", 0, "Eiffel Tower may refer to", 1)
    real = candidate("Eiffel_Tower", 0, "The Eiffel Tower is in Paris France.", 2)
    retrieval = Retriever([nav, real])
    predictor = Predictor([NliProbabilities(0.98, 0.01, 0.01)])
    result = ClaimVerificationPipeline(retriever=retrieval, nli_predictor=predictor).verify(
        "The Eiffel Tower is located in Paris", top_k=1
    )
    assert retrieval.called_with == [2]  # overfetch fills after filtering
    assert result.verdict is EvidenceVerdict.SUPPORTING_EVIDENCE
    assert predictor.last_texts == [real.text]
    assert result.quality_excluded_count == 1
    assert result.quality_exclusions[0].reason is ExclusionReason.DISAMBIGUATION_PAGE
    assert result.supporting_pages == ["Eiffel_Tower"]
    assert result.retrieved_count == 2
    assert result.assessed_count == 1


def test_disambiguation_article_can_be_the_actual_claim_topic() -> None:
    nav = candidate("Eiffel_Tower_-LRB-disambiguation-RRB-", 0, "Eiffel Tower may refer to", 1)
    screened = screen_evidence("Eiffel Tower disambiguation page", [nav], top_k=5)
    assert screened.selected == [nav]
    assert screened.excluded == []


def test_repeated_id_and_repeated_text_do_not_inflate_support() -> None:
    a = candidate("Eiffel_Tower", 0, "The Eiffel Tower is in Paris, France.", 1)
    b = candidate("Eiffel_Tower", 0, "The Eiffel Tower is in Paris, France.", 2)
    c = candidate("Another_Page", 1, "THE Eiffel Tower is in Paris France", 3)
    d = candidate("Eiffel_Tower", 2, "The original tower stands on the Champ de Mars.", 4)
    result = screen_evidence("Eiffel Tower in Paris", [a, b, c, d], top_k=5)
    assert result.selected == [a, d]
    assert [x.reason for x in result.excluded] == [
        ExclusionReason.DUPLICATE_EVIDENCE_ID,
        ExclusionReason.DUPLICATE_TEXT,
    ]


def test_similar_but_contradictory_cities_are_not_merged() -> None:
    a = candidate(
        "Example_Page",
        1,
        "The massive historical structure was located in Paris, France, near the river "
        "and has been visible from across the city since 1889.",
        1,
    )
    b = candidate(
        "Example_Page",
        2,
        "The massive historical structure was located in Berlin, France, near the river "
        "and has been visible from across the city since 1889.",
        2,
    )
    result = screen_evidence("The tower is located in Berlin", [a, b], top_k=5)
    assert result.selected == [a, b]


def test_high_similarity_same_page_same_words_can_be_deduplicated() -> None:
    a_text = (
        "The historic monument in Paris France near the river is known as a famous "
        "public attraction for international visitors and local residents alike. "
        "The site welcomes tourists and residents every single day of the year."
    )
    a_text = a_text * 4  # Enough matching context for conservative 0.98 cutoff.
    b_text = a_text.replace("tourists and residents", "residents and tourists", 1)
    a = candidate("Site", 4, a_text, 1)
    b = candidate("Site", 5, b_text, 2)
    screened = screen_evidence("Paris attraction", [a, b], top_k=5)
    assert screened.selected == [a]
    assert screened.excluded[0].reason is ExclusionReason.NEAR_DUPLICATE_SAME_PAGE


def test_location_qualified_article_not_blindly_discarded() -> None:
    replica = candidate(
        "Eiffel_Tower_-LRB-Paris,_Texas-RRB-",
        0,
        "Texas's Eiffel Tower is a landmark in Paris, Texas.",
        1,
    )
    screened = screen_evidence("Paris Texas has an Eiffel Tower replica", [replica], top_k=5)
    assert screened.selected == [replica]


def test_remaining_good_candidates_are_unused_not_rejected() -> None:
    items = [candidate(f"Page_{i}", 0, f"Distinct fact {i}", i) for i in range(1, 4)]
    screened = screen_evidence("A claim", items, top_k=1)
    assert len(screened.selected) == 1
    assert screened.unused_candidate_count == 2
    assert screened.excluded == []


def test_empty_candidates_are_excluded_and_predictor_is_not_called() -> None:
    a = candidate("Eiffel_Tower", 0, "    ", 1)
    predictor = Predictor([])
    result = ClaimVerificationPipeline(retriever=Retriever([a]), nli_predictor=predictor).verify(
        "The Eiffel Tower is in Paris"
    )
    assert result.verdict is EvidenceVerdict.INSUFFICIENT_EVIDENCE
    assert result.quality_excluded_count == 1
    assert predictor.last_texts is None


def test_conflicting_sources_remain_conflicting_after_hygiene() -> None:
    a = candidate("First", 1, "The event took place in Paris.", 1)
    b = candidate("Second", 1, "The event took place in Berlin.", 2)
    predictor = Predictor([NliProbabilities(0.98, 0.01, 0.01), NliProbabilities(0.01, 0.98, 0.01)])
    result = ClaimVerificationPipeline(retriever=Retriever([a, b]), nli_predictor=predictor).verify(
        "The event took place in Paris", top_k=2
    )
    assert result.verdict is EvidenceVerdict.CONFLICTING_EVIDENCE
    assert result.quality_excluded_count == 0
