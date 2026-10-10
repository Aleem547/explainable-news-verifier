"""Phase 10B.1 security tests; no real Redis or pretrained models required."""

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.testclient import TestClient

from apps.api.security import inference
from apps.api.security.body_limit import InferenceBodyLimitMiddleware


class FakeRedis:
    def __init__(self, count: int = 1, ttl: int = 42, fail: bool = False) -> None:
        self.count = count
        self.ttl = ttl
        self.fail = fail
        self.closed = False
        self.script = ""
        self.key = ""

    async def eval(self, script: str, numkeys: int, key: str, ttl: int) -> list[int]:
        assert numkeys == 1
        assert ttl == 60
        self.script = script
        self.key = key
        if self.fail:
            raise ConnectionError("Redis unavailable")
        return [self.count, self.ttl]

    async def aclose(self) -> None:
        self.closed = True


def make_request(token: str = "") -> Request:
    headers = [(b"x-service-token", token.encode("ascii"))] if token else []
    return Request({"type": "http", "method": "POST", "path": "/api/v1/verify", "headers": headers})


def configure(
    monkeypatch: pytest.MonkeyPatch,
    *,
    environment: str = "production",
    secret: str = "s" * 48,
    redis_client: FakeRedis | None = None,
) -> FakeRedis:
    fake = redis_client or FakeRedis()
    monkeypatch.setattr(
        inference,
        "get_settings",
        lambda: SimpleNamespace(
            app_env=environment,
            internal_api_token=secret,
            inference_requests_per_minute=3,
        ),
    )
    monkeypatch.setattr(inference, "get_redis_client", lambda: fake)
    return fake


def authorize(token: str = "") -> Response:
    response = Response()
    asyncio.run(inference.require_inference_access(make_request(token), response))
    return response


def test_development_keeps_local_verification_working(monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch, environment="development")
    assert authorize().headers.get("x-ratelimit-limit") is None


def test_missing_production_secret_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch, secret="")
    with pytest.raises(HTTPException) as exc:
        authorize()
    assert exc.value.status_code == 503


def test_wrong_or_missing_token_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch)
    for token in ("", "wrong"):
        with pytest.raises(HTTPException) as exc:
            authorize(token)
        assert exc.value.status_code == 401


def test_production_access_is_rate_limited_atomically(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = configure(monkeypatch, redis_client=FakeRedis(count=2))
    response = authorize("s" * 48)
    assert response.headers["x-ratelimit-limit"] == "3"
    assert response.headers["x-ratelimit-remaining"] == "1"
    assert fake.closed
    assert "INCR" in fake.script and "EXPIRE" in fake.script
    assert "s" * 48 not in fake.key


def test_quota_exceeded_returns_retry_after(monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch, redis_client=FakeRedis(count=4, ttl=32))
    with pytest.raises(HTTPException) as exc:
        authorize("s" * 48)
    assert exc.value.status_code == 429
    assert (exc.value.headers or {}).get("Retry-After") == "32"


def test_redis_failure_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = configure(monkeypatch, redis_client=FakeRedis(fail=True))
    with pytest.raises(HTTPException) as exc:
        authorize("s" * 48)
    assert exc.value.status_code == 503
    assert fake.closed


def make_test_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(InferenceBodyLimitMiddleware, max_bytes=128)

    @app.post("/api/v1/verify")
    async def verify(request: Request) -> dict[str, object]:
        return {"payload": await request.json()}

    return app


def test_small_json_request_is_passed_through() -> None:
    with TestClient(make_test_app()) as client:
        response = client.post("/api/v1/verify", json={"claim": "Paris"})
    assert response.status_code == 200
    assert response.json() == {"payload": {"claim": "Paris"}}


def test_non_json_payload_is_rejected() -> None:
    with TestClient(make_test_app()) as client:
        response = client.post("/api/v1/verify", content=b"hello")
    assert response.status_code == 415


def test_declared_oversized_payload_is_rejected() -> None:
    with TestClient(make_test_app()) as client:
        response = client.post("/api/v1/verify", json={"claim": "x" * 500})
    assert response.status_code == 413


def test_actual_oversized_body_rejected_even_with_forged_length() -> None:
    app = make_test_app()
    messages: list[dict[str, object]] = []
    chunks = iter(
        [
            {"type": "http.request", "body": b"{" + b"a" * 90, "more_body": True},
            {"type": "http.request", "body": b"b" * 90, "more_body": False},
        ]
    )

    async def receive() -> dict[str, object]:
        return next(chunks)

    async def send(message: dict[str, object]) -> None:
        messages.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "method": "POST",
        "scheme": "http",
        "path": "/api/v1/verify",
        "raw_path": b"/api/v1/verify",
        "query_string": b"",
        "root_path": "",
        "headers": [(b"content-type", b"application/json"), (b"content-length", b"10")],
        "server": ("testserver", 80),
        "client": ("127.0.0.1", 12345),
        "http_version": "1.1",
    }
    asyncio.run(app(scope, receive, send))  # type: ignore[arg-type]
    assert messages[0]["status"] == 413
