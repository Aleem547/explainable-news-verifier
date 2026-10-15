"""Check optional timing without loading any model or calling external services."""

from types import SimpleNamespace

import pytest

from ml.verification import evidence_pipeline as ep


def _make_pipeline(monkeypatch, observer=None):
    item = SimpleNamespace(
        rank=1,
        page_id="Paris",
        sentence_id=1,
        text="The Eiffel Tower is located in Paris.",
        page_rank=1,
        bm25_score=0.9,
        dense_score=0.9,
        rrf_score=0.9,
        cross_encoder_score=0.9,
    )
    monkeypatch.setattr(
        ep,
        "screen_evidence",
        lambda claim, items, top_k: SimpleNamespace(
            selected=items[:top_k], excluded=[], unused_candidate_count=0
        ),
    )
    monkeypatch.setattr(
        ep,
        "aggregate_evidence",
        lambda assessments: SimpleNamespace(
            verdict="REFUTING_EVIDENCE",
            supporting_pages=[],
            refuting_pages=["Paris"],
            reason=ep.AggregationReason.NO_DECISIVE_EVIDENCE,
            supporting_evidence_count=0,
            refuting_evidence_count=1,
            primary_count=1,
        ),
    )
    monkeypatch.setattr(
        ep, "contribution_role", lambda assessment, summary: ep.ContributionRole.NOT_DECISIVE
    )
    monkeypatch.setattr(
        ep,
        "check_decisive_admissibility",
        lambda *args: ep.AdmissibilityDecision(permitted=True),
    )
    retriever = SimpleNamespace(retrieve=lambda claim, top_k: [item])
    nli = SimpleNamespace(
        predict=lambda claim, evidence: [ep.NliProbabilities(0.01, 0.98, 0.01)]
    )
    return ep.ClaimVerificationPipeline(
        retriever=retriever,
        nli_predictor=nli,
        stage_observer=observer,
    )


def test_opt_in_timing_preserves_result(monkeypatch):
    observed = []
    baseline = _make_pipeline(monkeypatch).verify("Eiffel Tower is in Berlin", top_k=5)
    measured = _make_pipeline(monkeypatch, observer=observed.append).verify(
        "Eiffel Tower is in Berlin", top_k=5
    )
    assert measured.verdict == baseline.verdict
    assert measured.retrieved_count == baseline.retrieved_count
    assert measured.assessed_count == baseline.assessed_count
    assert measured.evidence == baseline.evidence
    assert len(observed) == 1
    metrics = observed[0]
    assert metrics["retrieved_count"] == 1
    assert metrics["assessed_count"] == 1
    for key in (
        "retrieval_ms", "quality_ms", "nli_ms", "decision_ms",
        "aggregation_ms", "annotation_ms", "measured_total_ms"
    ):
        assert metrics[key] >= 0


def test_timing_observer_failure_does_not_change_verdict(monkeypatch):
    def broken_observer(stages):
        raise RuntimeError("metrics unavailable")

    pipeline = _make_pipeline(monkeypatch, observer=broken_observer)
    result = pipeline.verify("Eiffel Tower is in Berlin")
    assert result.verdict == ep.EvidenceVerdict.REFUTING_EVIDENCE


def test_timing_is_optional(monkeypatch):
    pipeline = _make_pipeline(monkeypatch)
    assert pipeline.stage_observer is None
    assert pipeline.verify("Eiffel Tower is in Berlin").assessed_count == 1
