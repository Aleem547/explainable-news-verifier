"""Isolated retrieval profiling tests; no model artifacts or network required."""

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest

from scripts.performance.phase10c2_2_retrieval_benchmark import (
    STAGES,
    format_profile,
    profile_retrieval_once,
)


@dataclass
class FakeEvidence:
    page_id: str = "Test_Page"
    sentence_id: int = 7


class FakePageRetriever:
    def search(self, claim: str, *, limit: int = 20) -> list[FakeEvidence]:
        return [FakeEvidence()]


class FakeStore:
    def get_by_page_ids(self, pages: list[str]) -> list[FakeEvidence]:
        return [FakeEvidence()]


class FakeRanker:
    def rank(
        self, claim: str, documents: list[FakeEvidence], *, limit: int = 100
    ) -> list[FakeEvidence]:
        return documents


class FakeReranker:
    def rerank(
        self, claim: str, documents: list[FakeEvidence], *, limit: int = 10
    ) -> list[FakeEvidence]:
        return documents[:limit]


class FakePipeline:
    def __init__(self) -> None:
        self.page_retriever = FakePageRetriever()
        self.sentence_store = FakeStore()
        self.bm25_ranker = FakeRanker()
        self.dense_ranker = FakeRanker()
        self.reranker = FakeReranker()
        self.error = False

    def retrieve(self, claim: str, *, top_k: int) -> list[FakeEvidence]:
        pages = self.page_retriever.search(claim)
        documents = self.sentence_store.get_by_page_ids([page.page_id for page in pages])
        bm25 = self.bm25_ranker.rank(claim, documents)
        dense = self.dense_ranker.rank(claim, documents)
        if self.error:
            raise RuntimeError("test-only failure")
        fused = FUSION.reciprocal_rank_fusion([bm25, dense])
        return self.reranker.rerank(claim, fused, limit=top_k)


def fuse(inputs: list[list[FakeEvidence]]) -> list[FakeEvidence]:
    return inputs[0]


FUSION = SimpleNamespace(reciprocal_rank_fusion=fuse)


def test_counts_and_all_stage_timings() -> None:
    pipeline = FakePipeline()
    result = profile_retrieval_once(pipeline, "test claim", 5, retrieval_module=FUSION)
    assert result.output_count == 1
    assert result.evidence_signature == (("Test_Page", 7),)
    assert all(name in result.stage_ms for name in (*STAGES, "other"))
    assert all(duration >= 0 for duration in result.stage_ms.values())
    assert result.counts["page_search_calls"] == 1
    assert result.counts["pages_loaded"] == 1
    assert result.counts["source_sentences"] == 1
    assert result.counts["dense_input_sentences"] == 1
    assert result.counts["rerank_input_sentences"] == 1


def test_original_objects_restored_on_success() -> None:
    pipeline = FakePipeline()
    originals = [
        pipeline.page_retriever,
        pipeline.sentence_store,
        pipeline.bm25_ranker,
        pipeline.dense_ranker,
        pipeline.reranker,
    ]
    original_fusion = FUSION.reciprocal_rank_fusion
    profile_retrieval_once(pipeline, "test claim", 5, retrieval_module=FUSION)
    assert [
        pipeline.page_retriever,
        pipeline.sentence_store,
        pipeline.bm25_ranker,
        pipeline.dense_ranker,
        pipeline.reranker,
    ] == originals
    assert FUSION.reciprocal_rank_fusion is original_fusion


def test_restoration_on_error() -> None:
    pipeline = FakePipeline()
    pipeline.error = True
    original_ranker = pipeline.dense_ranker
    original_fusion = FUSION.reciprocal_rank_fusion
    with pytest.raises(RuntimeError, match="test-only failure"):
        profile_retrieval_once(pipeline, "test claim", 5, retrieval_module=FUSION)
    assert pipeline.dense_ranker is original_ranker
    assert FUSION.reciprocal_rank_fusion is original_fusion


@pytest.mark.parametrize("claim,top_k", [("", 5), ("  ", 5), ("valid", 0), ("valid", 21)])
def test_bad_inputs(claim: str, top_k: int) -> None:
    with pytest.raises(ValueError):
        profile_retrieval_once(FakePipeline(), claim, top_k, retrieval_module=FUSION)


def test_format_does_not_show_evidence_identity() -> None:
    result = profile_retrieval_once(FakePipeline(), "private claim", 5, retrieval_module=FUSION)
    report = format_profile("Sample", result)
    assert "Test_Page" not in report
    assert "private claim" not in report
    assert "page_search" in report
    assert "dense_input_sentences" in report


def test_no_net_change_to_results() -> None:
    pipeline = FakePipeline()
    baseline: list[Any] = pipeline.retrieve("test claim", top_k=5)
    observed = profile_retrieval_once(pipeline, "test claim", 5, retrieval_module=FUSION)
    after: list[Any] = pipeline.retrieve("test claim", top_k=5)
    assert baseline == after
    assert observed.evidence_signature == tuple((i.page_id, i.sentence_id) for i in baseline)
