"""Service transaction boundary and input validation, no PostgreSQL required."""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from apps.api.db.models.independence_assessment import IndependenceAssessment
from apps.api.db.models.independence_pair import IndependencePair
from apps.api.services.source_independence import record_independence_assessment


class FakeResult:
    def __init__(self, rows: list[tuple[SimpleNamespace, UUID]]) -> None:
        self.rows = rows

    def all(self) -> list[tuple[SimpleNamespace, UUID]]:
        return self.rows


class FakeSession:
    def __init__(self, rows: list[tuple[SimpleNamespace, UUID]]) -> None:
        self.rows = rows
        self.added: list[object] = []
        self.commits = 0

    async def execute(self, _statement: object) -> FakeResult:
        return FakeResult(self.rows)

    def add(self, model: object) -> None:
        self.added.append(model)
        if isinstance(model, IndependenceAssessment):
            model.id = uuid4()

    async def flush(self) -> None:
        pass


def make_session(
    text: str = "A full snapshot was published with reproducible evidence. " * 5,
) -> FakeSession:
    return FakeSession(
        [
            (SimpleNamespace(id=UUID(int=1), content_text=text), UUID(int=81)),
            (SimpleNamespace(id=UUID(int=2), content_text=text), UUID(int=82)),
        ]
    )


def test_service_persists_auditable_pair_without_commit() -> None:
    session = make_session()
    assessment = asyncio.run(
        record_independence_assessment(
            session,  # type: ignore[arg-type]
            version_ids=[UUID(int=1), UUID(int=2)],
            assessed_at=datetime.now(UTC),
        )
    )
    pairs = [item for item in session.added if isinstance(item, IndependencePair)]
    assert assessment.family_count == 1
    assert assessment.snapshot_count == 2
    assert len(pairs) == 1
    assert pairs[0].relationship == "IDENTICAL_TEXT"
    assert session.commits == 0


def test_missing_versions_rejected_before_persistence() -> None:
    session = FakeSession([])
    with pytest.raises(ValueError, match="do not exist"):
        asyncio.run(
            record_independence_assessment(
                session,  # type: ignore[arg-type]
                version_ids=[UUID(int=1), UUID(int=2)],
                assessed_at=datetime.now(UTC),
            )
        )
    assert not session.added


def test_naive_assessed_time_rejected() -> None:
    session = make_session()
    with pytest.raises(ValueError, match="timezone-aware"):
        asyncio.run(
            record_independence_assessment(
                session,  # type: ignore[arg-type]
                version_ids=[UUID(int=1), UUID(int=2)],
                assessed_at=datetime(2026, 10, 1),
            )
        )


def test_unknown_origin_version_rejected() -> None:
    from apps.api.services.source_independence import ReportedOrigin

    session = make_session()
    with pytest.raises(ValueError, match="unrequested"):
        asyncio.run(
            record_independence_assessment(
                session,  # type: ignore[arg-type]
                version_ids=[UUID(int=1), UUID(int=2)],
                assessed_at=datetime.now(UTC),
                reported_origins={
                    UUID(int=3): ReportedOrigin(
                        origin_url="https://agency.example.com/story",
                        observation_url="https://publisher.example.com/citation",
                    )
                },
            )
        )
