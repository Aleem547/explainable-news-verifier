"""Schema compatibility without requiring a running PostgreSQL instance."""

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from apps.api.db import models  # noqa: F401
from apps.api.db.base import Base


def test_phase9a_tables_added_without_replacing_legacy_schema() -> None:
    expected = {
        "sources",
        "documents",
        "evidence",
        "document_versions",
        "retrieval_observations",
        "evidence_provenance",
    }
    assert expected <= set(Base.metadata.tables)


def test_provenance_foreign_keys_are_present() -> None:
    version = Base.metadata.tables["document_versions"]
    observation = Base.metadata.tables["retrieval_observations"]
    provenance = Base.metadata.tables["evidence_provenance"]
    assert "documents.id" in {fk.target_fullname for fk in version.foreign_keys}
    assert "sources.id" in {fk.target_fullname for fk in observation.foreign_keys}
    assert "document_versions.id" in {fk.target_fullname for fk in provenance.foreign_keys}
    assert "evidence.id" in {fk.target_fullname for fk in provenance.foreign_keys}


def test_tables_compile_for_postgresql() -> None:
    for name in ("document_versions", "retrieval_observations", "evidence_provenance"):
        statement = str(
            CreateTable(Base.metadata.tables[name]).compile(dialect=postgresql.dialect())
        )
        assert f"CREATE TABLE {name}" in statement
