"""Instrumentation tests without loading transformers or a model checkpoint."""

from types import SimpleNamespace

import pytest

from scripts.performance.phase10c2_benchmark import (
    STAGES,
    format_sample,
    profile_once,
)


class FakeRetriever:
    def __init__(self) -> None:
        self.top_k: int | None = None

    def retrieve(self, claim: str, *, top_k: int = 10) -> list[str]:
        self.top_k = top_k
        return ["evidence"]


class FakeNli:
    def predict(self, claim: str, evidence_texts: list[str]) -> list[str]:
        return ["ENTAILMENT"]


class FakePipeline:
    def __init__(self, module: SimpleNamespace, *, fail: bool = False) -> None:
        self.retriever = FakeRetriever()
        self.nli_predictor = FakeNli()
        self.module = module
        self.fail = fail

    def verify(self, claim: str, *, top_k: int) -> SimpleNamespace:
        evidence = self.retriever.retrieve(claim, top_k=top_k)
        screened = self.module.screen_evidence(claim, evidence, top_k=top_k)
        labels = self.nli_predictor.predict(claim, screened)
        self.module.check_decisive_admissibility(claim, "Eiffel_Tower", "text", labels[0])
        self.module.aggregate_evidence(labels)
        self.module.contribution_role(labels)
        if self.fail:
            raise RuntimeError("simulated model error")
        item = SimpleNamespace(
            page_id="Eiffel_Tower",
            sentence_id=0,
            nli_label="ENTAILMENT",
            accepted=True,
        )
        return SimpleNamespace(verdict="SUPPORTING_EVIDENCE", evidence=[item])


def make_module() -> SimpleNamespace:
    return SimpleNamespace(
        screen_evidence=lambda claim, items, *, top_k: items,
        check_decisive_admissibility=lambda *args: True,
        aggregate_evidence=lambda *args: True,
        contribution_role=lambda *args: True,
    )


def test_profiles_all_stages_and_preserves_result() -> None:
    module = make_module()
    pipeline = FakePipeline(module)
    original_retriever = pipeline.retriever
    original_predictor = pipeline.nli_predictor
    original_screen = module.screen_evidence

    sample = profile_once(pipeline, "Eiffel Tower is in Paris", 3, instrumentation_module=module)

    assert sample.verdict == "SUPPORTING_EVIDENCE"
    assert sample.assessed_count == 1
    assert sample.evidence_signature == (("Eiffel_Tower", 0, "ENTAILMENT", True),)
    assert sample.total_ms >= 0
    assert set(sample.stage_ms) == {*STAGES, "other"}
    assert all(value >= 0 for value in sample.stage_ms.values())
    assert original_retriever.top_k == 3
    assert pipeline.retriever is original_retriever
    assert pipeline.nli_predictor is original_predictor
    assert module.screen_evidence is original_screen


def test_restores_objects_after_failure() -> None:
    module = make_module()
    pipeline = FakePipeline(module, fail=True)
    original_retriever = pipeline.retriever
    original_predictor = pipeline.nli_predictor
    original_aggregation = module.aggregate_evidence

    with pytest.raises(RuntimeError, match="simulated model error"):
        profile_once(pipeline, "Eiffel Tower is in Paris", 5, instrumentation_module=module)

    assert pipeline.retriever is original_retriever
    assert pipeline.nli_predictor is original_predictor
    assert module.aggregate_evidence is original_aggregation


@pytest.mark.parametrize("top_k", [0, -2, 21])
def test_invalid_top_k_rejected(top_k: int) -> None:
    with pytest.raises(ValueError, match="top_k"):
        profile_once(FakePipeline(make_module()), "A valid claim", top_k)


def test_blank_claim_rejected() -> None:
    with pytest.raises(ValueError, match="claim"):
        profile_once(FakePipeline(make_module()), "    ", 5)


def test_report_does_not_include_claim_or_evidence_text() -> None:
    module = make_module()
    sample = profile_once(
        FakePipeline(module), "Private claim text", 5, instrumentation_module=module
    )
    report = format_sample("Warm request 1", sample)
    assert "Private claim text" not in report
    assert "Eiffel_Tower" not in report
    assert "retrieval" in report
    assert "nli" in report
