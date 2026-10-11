"""Phase 10B3.1 audit tests; no database, network, or ML models required."""

from collections.abc import Iterator
from hashlib import sha256
from hmac import new as hmac_new

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from apps.api.security import verification_audit
from apps.api.security.verification_audit import VerificationAuditMiddleware

TEST_AUDIT_KEY = "test-audit-key-" + ("z" * 48)
TEST_USER = "google:123456789012345678901"


class CapturedLogger:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def info(self, event: str, **fields: object) -> None:
        self.events.append({"event": event, **fields})


@pytest.fixture
def audit_client(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, CapturedLogger]]:
    log = CapturedLogger()
    monkeypatch.setattr(verification_audit, "logger", log)
    app = FastAPI()

    @app.post("/api/v1/verify")
    async def verify(request: Request, outcome: str = "success") -> dict[str, str]:
        if outcome == "success":
            request.state.verified_user_id = TEST_USER
            return {"verdict": "SUPPORTING_EVIDENCE"}
        if outcome == "unauthorized":
            raise HTTPException(status_code=401, detail="Service token is missing")
        if outcome == "invalid":
            raise HTTPException(status_code=422, detail="Invalid claim")
        if outcome == "limited":
            raise HTTPException(status_code=429, detail="Quota exceeded")
        if outcome == "unavailable":
            raise HTTPException(status_code=503, detail="Rate limiter unavailable")
        raise RuntimeError("Unexpected secret model error")

    @app.get("/api/v1/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.add_middleware(VerificationAuditMiddleware, audit_key=TEST_AUDIT_KEY)
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, log


def test_success_is_correlated_without_exposing_identity(
    audit_client: tuple[TestClient, CapturedLogger],
) -> None:
    client, log = audit_client
    response = client.post("/api/v1/verify", json={"claim": "private claim"})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    request_id = response.headers["x-request-id"]
    assert len(request_id) == 24
    assert len(log.events) == 1

    event = log.events[0]
    assert event["event"] == "verification_request_audit"
    assert event["request_id"] == request_id
    assert event["outcome"] == "success"
    assert event["status_code"] == 200
    assert isinstance(event["elapsed_ms"], float)
    expected = hmac_new(TEST_AUDIT_KEY.encode(), TEST_USER.encode(), sha256).hexdigest()[:24]
    assert event["actor_fingerprint"] == expected
    assert TEST_USER not in str(event)
    assert "private claim" not in str(event)
    assert TEST_AUDIT_KEY not in str(event)


@pytest.mark.parametrize(
    ("case", "status", "outcome"),
    [
        ("unauthorized", 401, "unauthorized"),
        ("invalid", 422, "invalid_request"),
        ("limited", 429, "rate_limited"),
        ("unavailable", 503, "unavailable"),
        ("failure", 500, "server_error"),
    ],
)
def test_failure_categories_and_no_header_identity_trust(
    audit_client: tuple[TestClient, CapturedLogger],
    case: str,
    status: int,
    outcome: str,
) -> None:
    client, log = audit_client
    response = client.post(
        "/api/v1/verify",
        params={"outcome": case},
        headers={"X-Verified-User": "google:spoofed-identity"},
    )
    assert response.status_code == status
    assert log.events[-1]["status_code"] == status
    assert log.events[-1]["outcome"] == outcome
    assert log.events[-1]["actor_fingerprint"] is None
    assert "spoofed-identity" not in str(log.events[-1])
    if status != 500:
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-request-id"] == log.events[-1]["request_id"]


def test_health_is_not_audited(
    audit_client: tuple[TestClient, CapturedLogger],
) -> None:
    client, log = audit_client
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert "x-request-id" not in response.headers
    assert log.events == []


def test_every_request_gets_unique_correlation_id(
    audit_client: tuple[TestClient, CapturedLogger],
) -> None:
    client, log = audit_client
    one = client.post("/api/v1/verify")
    two = client.post("/api/v1/verify")
    assert one.headers["x-request-id"] != two.headers["x-request-id"]
    assert len(log.events) == 2
