"""Production per-user quota tests; external Redis/network not required."""

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Request, Response

from apps.api.security import user_quota


class FakeRedis:
    def __init__(self, count: int = 1, ttl: int = 34, fail: bool = False) -> None:
        self.count = count
        self.ttl = ttl
        self.fail = fail
        self.closed = False
        self.key = ""

    async def eval(self, script: str, numkeys: int, key: str, ttl: int) -> list[int]:
        assert numkeys == 1
        assert ttl == 60
        assert "INCR" in script and "EXPIRE" in script
        self.key = key
        if self.fail:
            raise ConnectionError("Redis unavailable")
        return [self.count, self.ttl]

    async def aclose(self) -> None:
        self.closed = True


def configure(monkeypatch: pytest.MonkeyPatch, fake: FakeRedis, *, env: str = "production") -> None:
    monkeypatch.setattr(
        user_quota,
        "get_settings",
        lambda: SimpleNamespace(app_env=env, inference_user_requests_per_minute=3),
    )
    monkeypatch.setattr(user_quota, "get_redis_client", lambda: fake)


def run_user(subject: str = "google:123456789012345678901") -> Response:
    headers = [(b"x-verified-user", subject.encode("ascii"))] if subject else []
    request = Request(
        {"type": "http", "method": "POST", "path": "/api/v1/verify", "headers": headers}
    )
    response = Response()
    asyncio.run(user_quota.require_verified_user_access(request, response))
    return response


def test_dev_mode_keeps_existing_local_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch, FakeRedis(), env="development")
    assert "x-user-ratelimit-limit" not in run_user().headers


def test_production_without_subject_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch, FakeRedis())
    with pytest.raises(HTTPException) as exc:
        run_user("")
    assert exc.value.status_code == 401


@pytest.mark.parametrize("subject", ["eve@example.com", "x\nfoo:bar", "", "google:"])
def test_invalid_subjects_are_rejected(monkeypatch: pytest.MonkeyPatch, subject: str) -> None:
    configure(monkeypatch, FakeRedis())
    with pytest.raises(HTTPException) as exc:
        run_user(subject)
    assert exc.value.status_code == 401


def test_valid_user_is_accepted_and_subject_is_hashed(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeRedis(count=2)
    configure(monkeypatch, fake)
    response = run_user()
    assert response.headers["x-user-ratelimit-limit"] == "3"
    assert response.headers["x-user-ratelimit-remaining"] == "1"
    assert "1234567890" not in fake.key
    assert fake.closed


def test_user_quota_returns_429_and_retry_after(monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch, FakeRedis(count=4, ttl=23))
    with pytest.raises(HTTPException) as exc:
        run_user()
    assert exc.value.status_code == 429
    assert (exc.value.headers or {})["Retry-After"] == "23"


def test_redis_outage_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeRedis(fail=True)
    configure(monkeypatch, fake)
    with pytest.raises(HTTPException) as exc:
        run_user()
    assert exc.value.status_code == 503
    assert fake.closed
