from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from apps.api.db.base import Base
from apps.api.db.models import DiscoveryRecord, DocumentPassage, IndexOutbox


def test_new_schema_registered() -> None:
    for table in ("discovery_records", "document_passages", "index_outbox"):
        assert table in Base.metadata.tables


def test_fk_to_existing_phase9a_tables() -> None:
    tables = Base.metadata.tables
    assert tables["discovery_records"].c.document_id.references(tables["documents"].c.id)
    assert tables["document_passages"].c.document_version_id.references(
        tables["document_versions"].c.id
    )
    assert tables["index_outbox"].c.document_version_id.references(tables["document_versions"].c.id)


def test_schema_compiles_in_postgres() -> None:
    for model in (DiscoveryRecord, DocumentPassage, IndexOutbox):
        statement = str(CreateTable(model.__table__).compile(dialect=postgresql.dialect()))
        assert "CREATE TABLE" in statement
        assert "FOREIGN KEY" in statement
