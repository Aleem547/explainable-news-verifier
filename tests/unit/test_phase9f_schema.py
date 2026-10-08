"""Phase 9F ORM/migration compatibility checks; no database required."""

from apps.api.db import models  # noqa: F401
from apps.api.db.base import Base


def test_cross_source_models_are_registered() -> None:
    assert "cross_source_assessments" in Base.metadata.tables
    assert "cross_source_evidence" in Base.metadata.tables


def test_assessment_has_independence_reference_and_no_truth_score() -> None:
    table = Base.metadata.tables["cross_source_assessments"]
    assert {"claim_sha256", "independence_assessment_id", "outcome", "warnings"} <= set(
        table.c.keys()
    )
    assert len(table.foreign_keys) == 1
    assert "truth_probability" not in table.c


def test_evidence_has_snapshot_passage_and_context_references() -> None:
    table = Base.metadata.tables["cross_source_evidence"]
    assert {
        "assessment_id",
        "document_version_id",
        "passage_id",
        "family_id",
        "context_assessment_id",
        "decision",
        "nli_confidence",
    } <= set(table.c.keys())
    assert len(table.foreign_keys) == 5
