"""ORM metadata checks, requiring no PostgreSQL connection."""

from sqlalchemy import CheckConstraint, ForeignKeyConstraint

from apps.api.db.base import Base
from apps.api.db.models import DocumentContextAssessment, SourceProfileObservation


def test_additive_model_names() -> None:
    assert SourceProfileObservation.__tablename__ == "source_profile_observations"
    assert DocumentContextAssessment.__tablename__ == "document_context_assessments"
    assert set(("documents", "document_versions", "sources", "retrieval_observations")) <= set(
        Base.metadata.tables
    )


def test_source_profile_fkey_and_constraints() -> None:
    table = Base.metadata.tables["source_profile_observations"]
    assert "source_id" in table.c
    assert "observed_url" in table.c
    assert any(isinstance(c, CheckConstraint) for c in table.constraints)
    assert any(isinstance(c, ForeignKeyConstraint) for c in table.constraints)


def test_assessment_keeps_context_without_truth_scores() -> None:
    table = Base.metadata.tables["document_context_assessments"]
    assert "temporal_relation" in table.c
    assert "warnings" in table.c
    assert "metadata_flags" in table.c
    assert "truth_probability" not in table.c
    assert "source_credibility_score" not in table.c


def test_models_use_uuid_for_relationships() -> None:
    column = Base.metadata.tables["document_context_assessments"].c.document_version_id
    assert "document_versions.id" in {key.target_fullname for key in column.foreign_keys}
