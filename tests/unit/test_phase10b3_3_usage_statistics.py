"""Phase 10B3.3 usage statistics: privacy, authentication, windows and failures."""

from collections.abc import Iterator
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.core.config import get_settings
from apps.api.routes import usage_statistics as usage_route
from apps.api.schemas.usage_statistics import UsageStatistics
from apps.api.services.usage_statistics import (
    DailyAggregate,
    summarize_usage,
    verified_actor_fingerprint,
)

TEST_TOKEN = "phase10b3-test-only-" + ("t" * 48)
HEADERS = {"X-Service-Token": TEST_TOKEN, "X-Verified-User": "google:user-one"}


@pytest.fixture
def client() -> Iterator[TestClient]:
    application = FastAPI()
    application.include_router(usage_route.router, prefix="/api/v1")
    application.dependency_overrides[get_settings] = lambda: SimpleNamespace(
        internal_api_token=TEST_TOKEN
    )
    with TestClient(application) as test_client:
        yield test_client


def test_anonymous_request_is_rejected(client: TestClient) -> None:
    response = client.get("/api/v1/account/usage")
    assert response.status_code == 401


def test_untrusted_identity_without_service_token_is_rejected(client: TestClient) -> None:
    response = client.get("/api/v1/account/usage", headers={"X-Verified-User": "google:other-user"})
    assert response.status_code == 401


def test_bad_service_token_is_rejected(client: TestClient) -> None:
    response = client.get(
        "/api/v1/account/usage",
        headers={"X-Service-Token": "wrong", "X-Verified-User": "google:other-user"},
    )
    assert response.status_code == 401


def test_request_without_verified_subject_is_rejected(client: TestClient) -> None:
    response = client.get("/api/v1/account/usage", headers={"X-Service-Token": TEST_TOKEN})
    assert response.status_code == 401


def test_validated_days_reject_unsupported_values(client: TestClient) -> None:
    for days in ("0", "14", "91", "foo"):
        response = client.get(f"/api/v1/account/usage?days={days}", headers=HEADERS)
        assert response.status_code == 422


def test_identity_is_derived_from_authenticated_service_context(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[tuple[str, str, int]] = []

    async def fake_stats(*, verified_user: str, audit_key: str, days: int) -> UsageStatistics:
        seen.append((verified_user, audit_key, days))
        return summarize_usage([], days=days, today=date(2026, 10, 11))

    monkeypatch.setattr(usage_route, "get_usage_statistics", fake_stats)
    response = client.get("/api/v1/account/usage?days=7", headers=HEADERS)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["window_days"] == 7
    assert len(response.json()["daily"]) == 7
    assert seen == [("google:user-one", TEST_TOKEN, 7)]
    assert "google:user-one" not in response.text
    assert TEST_TOKEN not in response.text


def test_browser_query_cannot_override_actor(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str] = []

    async def fake_stats(*, verified_user: str, audit_key: str, days: int) -> UsageStatistics:
        seen.append(verified_user)
        return summarize_usage([], days=days, today=date(2026, 10, 11))

    monkeypatch.setattr(usage_route, "get_usage_statistics", fake_stats)
    response = client.get("/api/v1/account/usage?days=30&user=google:another-user", headers=HEADERS)
    assert response.status_code == 200
    assert seen == ["google:user-one"]


def test_database_failure_is_sanitized(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_stats(*, verified_user: str, audit_key: str, days: int) -> UsageStatistics:
        raise RuntimeError("postgres-password=do-not-show")

    monkeypatch.setattr(usage_route, "get_usage_statistics", fake_stats)
    response = client.get("/api/v1/account/usage", headers=HEADERS)
    assert response.status_code == 503
    assert response.headers["cache-control"] == "no-store"
    assert "postgres-password" not in response.text


def test_hmac_fingerprints_are_distinct_and_not_raw_subjects() -> None:
    first = verified_actor_fingerprint("google:user-one", TEST_TOKEN)
    second = verified_actor_fingerprint("google:user-two", TEST_TOKEN)
    assert first != second
    assert first == verified_actor_fingerprint("google:user-one", TEST_TOKEN)
    assert len(first) == 24
    assert "user-one" not in first


def test_summarize_is_gap_filled_in_utc_and_limits_days() -> None:
    today = date(2026, 10, 11)
    report = summarize_usage(
        [
            DailyAggregate(
                day=today,
                total=4,
                successful=2,
                failed=1,
                rate_limited=1,
                latency_sum_ms=140.0,
            ),
            DailyAggregate(
                day=today - timedelta(days=3),
                total=2,
                successful=2,
                failed=0,
                rate_limited=0,
                latency_sum_ms=80.0,
            ),
            DailyAggregate(
                day=today - timedelta(days=20),
                total=5,
                successful=5,
                failed=0,
                rate_limited=0,
                latency_sum_ms=200.0,
            ),
        ],
        days=7,
        today=today,
    )
    assert report.total_requests == 6
    assert report.successful_requests == 4
    assert report.failed_requests == 1
    assert report.rate_limited_requests == 1
    assert report.average_latency_ms == 36.67
    assert len(report.daily) == 7
    assert report.daily[0].date == "2026-10-05"
    assert report.daily[-1].date == "2026-10-11"
    assert report.daily[1].total == 0


def test_empty_usage_is_valid() -> None:
    report = summarize_usage([], days=90, today=date(2026, 10, 11))
    assert report.total_requests == 0
    assert report.average_latency_ms == 0
    assert len(report.daily) == 90
    assert all(day.total == 0 for day in report.daily)


def test_unsupported_window_never_summarizes() -> None:
    with pytest.raises(ValueError):
        summarize_usage([], days=14, today=date(2026, 10, 11))
