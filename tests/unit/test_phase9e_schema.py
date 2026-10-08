"""Schema registration and migration matching checks."""

from apps.api.db import models  # noqa: F401
from apps.api.db.base import Base


def test_model_tables_registered() -> None:
    assert "independence_assessments" in Base.metadata.tables
    assert "independence_pairs" in Base.metadata.tables


def test_pair_reference_constraints_and_columns() -> None:
    table = Base.metadata.tables["independence_pairs"]
    columns = {"assessment_id", "left_version_id", "right_version_id", "relationship"}
    assert columns <= set(table.c.keys())
    assert len(table.foreign_keys) == 3


def test_summary_structure() -> None:
    table = Base.metadata.tables["independence_assessments"]
    assert {"rule_version", "version_ids", "families", "warnings"} <= set(table.c.keys())
