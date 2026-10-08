"""Unit tests for opt-in supplemental page discovery, no real models needed."""

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest

from ml.retrieval.pipeline import EvidenceRetrievalPipeline, RetrievalPipelineConfig


@dataclass
class FakePage:
    page_id: str
    rank: int


@dataclass
class FakeSentence:
    page_id: str
    sentence_id: int
    text: str


class FakePages:
    def __init__(self, mapping: dict[str, list[str]]) -> None:
        self.mapping = mapping
        self.queries: list[tuple[str, int]] = []

    def search(self, query_text: str, *, limit: int = 10) -> list[Any]:
        self.queries.append((query_text, limit))
        return [
            FakePage(page_id=name, rank=i + 1)
            for i, name in enumerate(self.mapping.get(query_text, [])[:limit])
        ]


class FakeStore:
    def __init__(self, mapping: dict[str, str]) -> None:
        self.mapping = mapping
        self.requested: list[str] = []

    def get_by_page_ids(self, page_ids: list[str]) -> list[Any]:
        self.requested = list(page_ids)
        return [
            FakeSentence(page_id=pid, sentence_id=0, text=self.mapping[pid])
            for pid in page_ids
            if pid in self.mapping
        ]


class FakeRanker:
    def __init__(self) -> None:
        self.query: str | None = None

    def rank(self, query: str, documents: list[Any], *, limit: int = 50) -> list[Any]:
        self.query = query
        return [
            SimpleNamespace(
                page_id=doc.page_id,
                sentence_id=doc.sentence_id,
                score=float(len(documents) - i),
                rank=i + 1,
            )
            for i, doc in enumerate(documents[:limit])
        ]


class FakeReranker:
    def __init__(self) -> None:
        self.query: str | None = None

    def rerank(self, query: str, documents: list[Any], *, limit: int = 50) -> list[Any]:
        self.query = query
        return [
            SimpleNamespace(
                page_id=doc.page_id,
                sentence_id=doc.sentence_id,
                text=doc.text,
                score=1.0,
                rank=i + 1,
            )
            for i, doc in enumerate(documents[:limit])
        ]


def make_pipeline(
    mapping: dict[str, list[str]],
    texts: dict[str, str],
    *,
    enabled: bool,
    max_pages: int = 32,
) -> tuple[EvidenceRetrievalPipeline, FakePages, FakeStore, FakeRanker, FakeReranker]:
    pages = FakePages(mapping)
    store = FakeStore(texts)
    dense = FakeRanker()
    reranker = FakeReranker()
    pipeline = EvidenceRetrievalPipeline(
        page_retriever=pages,
        sentence_store=store,
        bm25_ranker=FakeRanker(),  # type: ignore[arg-type]
        dense_ranker=dense,
        reranker=reranker,
        config=RetrievalPipelineConfig(
            enable_subject_query_expansion=enabled,
            max_pages_with_expansion=max_pages,
        ),
    )
    return pipeline, pages, store, dense, reranker


def test_off_mode_preserves_single_original_query(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VERIFIER_SUBJECT_QUERY_EXPANSION", raising=False)
    claim = "Rio's sequel is an American musical comedy film."
    pipeline, pages, store, _, _ = make_pipeline(
        {claim: ["An_Inconvenient_Sequel"], "Rio 2": ["Rio_2"]},
        {"An_Inconvenient_Sequel": "A documentary", "Rio_2": "Animated film"},
        enabled=False,
    )
    assert [item.page_id for item in pipeline.retrieve(claim, top_k=5)] == [
        "An_Inconvenient_Sequel"
    ]
    assert pages.queries == [(claim, 20)]
    assert store.requested == ["An_Inconvenient_Sequel"]


def test_on_mode_adds_rio_candidate_but_original_query_scores(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("VERIFIER_SUBJECT_QUERY_EXPANSION", raising=False)
    claim = "Rio's sequel is an American musical comedy film."
    pipeline, pages, store, dense, reranker = make_pipeline(
        {
            claim: ["An_Inconvenient_Sequel"],
            "Rio 2": ["Rio_2"],
            "Rio sequel film": ["Rio_2", "Rio"],
        },
        {
            "An_Inconvenient_Sequel": "A documentary",
            "Rio_2": "Rio 2 is an animated sequel",
            "Rio": "Rio is an animated film",
        },
        enabled=True,
    )
    results = pipeline.retrieve(claim, top_k=5)
    assert pages.queries == [
        (claim, 20),
        ("Rio 2", 10),
        ("Rio sequel film", 10),
    ]
    assert store.requested == ["An_Inconvenient_Sequel", "Rio_2", "Rio"]
    assert any(item.page_id == "Rio_2" for item in results)
    assert dense.query == claim
    assert reranker.query == claim
    assert next(item.page_rank for item in results if item.page_id == "Rio_2") == 2


def test_env_switch_enables_expansion_without_factory_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claim = "Due Date was only shot in Maine."
    monkeypatch.setenv("VERIFIER_SUBJECT_QUERY_EXPANSION", "1")
    pipeline, pages, _, _, _ = make_pipeline(
        {claim: ["In_Due_Time"], "Due Date film": ["Due_Date_(film)"]},
        {"In_Due_Time": "An album", "Due_Date_(film)": "A film"},
        enabled=False,
    )
    assert len(pipeline.retrieve(claim, top_k=5)) == 2
    assert ("Due Date film", 10) in pages.queries


def test_page_budget_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VERIFIER_SUBJECT_QUERY_EXPANSION", raising=False)
    claim = "Due Date was only shot in Maine."
    mapping = {
        claim: ["P0", "P1"],
        "Due Date": ["P1", "P2", "P3"],
        "Due Date film": ["P4", "P5"],
    }
    pipeline, _, store, _, _ = make_pipeline(
        mapping,
        {f"P{i}": f"sentence {i}" for i in range(6)},
        enabled=True,
        max_pages=3,
    )
    pipeline.retrieve(claim, top_k=5)
    assert store.requested == ["P0", "P1", "P2"]


def test_can_recover_pages_even_when_primary_query_finds_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("VERIFIER_SUBJECT_QUERY_EXPANSION", raising=False)
    claim = "The Indian Army is an armed force."
    pipeline, _, store, _, _ = make_pipeline(
        {claim: [], "The Indian Army": ["Indian_Army"]},
        {"Indian_Army": "The Indian Army is a branch"},
        enabled=True,
    )
    assert len(pipeline.retrieve(claim, top_k=5)) == 1
    assert store.requested == ["Indian_Army"]


def test_empty_claim_and_invalid_k_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VERIFIER_SUBJECT_QUERY_EXPANSION", raising=False)
    pipeline, pages, _, _, _ = make_pipeline({}, {}, enabled=True)
    assert pipeline.retrieve(" ") == []
    with pytest.raises(ValueError, match="top_k"):
        pipeline.retrieve("A claim", top_k=0)
    assert pages.queries == []
