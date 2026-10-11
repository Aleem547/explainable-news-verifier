"""Phase 10B3.2 tests: isolated database writer and authenticated audit path."""

import asyncio
from collections.abc import Iterator

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from apps.api.db.models.verification_usage import VerificationUsageEvent
from apps.api.security import verification_audit
from apps.api.security.verification_audit import VerificationAuditMiddleware
from apps.api.services import verification_usage


class FakeSession:
    def __init__(self) -> None:
        self.saved: list[VerificationUsageEvent] = []
        self.committed = False

    async def __aenter__(self) -> "FakeSession":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    def add(self, event: VerificationUsageEvent) -> None:
        self.saved.append(event)

    async def commit(self) -> None:
        self.committed = True


def test_persists_only_pseudonymous_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.api.db import session as db_session

    fake = FakeSession()
    monkeypatch.setattr(db_session, "AsyncSessionLocal", lambda: fake)
    asyncio.run(
        verification_usage.persist_usage_event(
            request_id="a" * 24,
            actor_fingerprint="b" * 24,
            status_code=200,
            outcome="success",
            latency_ms=12.4,
        )
    )
    assert fake.committed is True
    assert len(fake.saved) == 1
    event = fake.saved[0]
    assert event.request_id == "a" * 24
    assert event.actor_fingerprint == "b" * 24
    assert event.status_code == 200
    assert event.outcome == "success"
    assert event.latency_ms == 12.4
    assert not hasattr(event, "claim")
    assert not hasattr(event, "email")


class CapturedLogger:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def info(self, event: str, **fields: object) -> None:
        self.events.append({"event": event, **fields})

    def warning(self, event: str, **fields: object) -> None:
        self.events.append({"event": event, **fields})


@pytest.fixture
def client_with_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, list[dict[str, object]], CapturedLogger]]:
    log = CapturedLogger()
    records: list[dict[str, object]] = []
    monkeypatch.setattr(verification_audit, "logger", log)

    async def fake_write(**kwargs: object) -> None:
        records.append(kwargs)

    monkeypatch.setattr(verification_usage, "persist_usage_event", fake_write)
    app = FastAPI()

    @app.post("/api/v1/verify")
    async def verify(request: Request, authenticated: bool = True) -> dict[str, str]:
        if authenticated:
            request.state.verified_user_id = "google:real-user"
        return {"result": "ok"}

    app.add_middleware(
        VerificationAuditMiddleware, audit_key="test-key-" + ("x" * 48), persist_usage=True
    )
    with TestClient(app) as client:
        yield client, records, log


def test_authenticated_usage_is_written_once(
    client_with_usage: tuple[TestClient, list[dict[str, object]], CapturedLogger],
) -> None:
    client, records, _ = client_with_usage
    response = client.post("/api/v1/verify")
    assert response.status_code == 200
    assert len(records) == 1
    assert records[0]["request_id"] == response.headers["x-request-id"]
    assert records[0]["status_code"] == 200
    assert records[0]["outcome"] == "success"
    assert records[0]["actor_fingerprint"] != "google:real-user"
    assert "google:real-user" not in str(records)


def test_anonymous_user_is_never_persisted(
    client_with_usage: tuple[TestClient, list[dict[str, object]], CapturedLogger],
) -> None:
    client, records, _ = client_with_usage
    response = client.post("/api/v1/verify?authenticated=false")
    assert response.status_code == 200
    assert records == []


def test_database_failure_does_not_change_http_response(
    client_with_usage: tuple[TestClient, list[dict[str, object]], CapturedLogger],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, records, log = client_with_usage

    async def fail(**kwargs: object) -> None:
        raise ConnectionError("database private details")

    monkeypatch.setattr(verification_usage, "persist_usage_event", fail)
    response = client.post("/api/v1/verify")
    assert response.status_code == 200
    assert records == []
    failure = [e for e in log.events if e["event"] == "verification_usage_persist_failed"]
    assert len(failure) == 1
    assert failure[0]["error_type"] == "ConnectionError"
    assert "database private details" not in str(log.events)
