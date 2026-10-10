"""Tests for internal service authentication."""

from collections.abc import Iterator
from types import SimpleNamespace
from typing import Annotated

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from apps.api.core.config import get_settings
from apps.api.core.service_auth import require_internal_verification
from apps.api.routes.verification import router

TEST_TOKEN = "test-only-service-token-" + ("a" * 48)
TEST_CLAIM = {
    "claim": "The Eiffel Tower is located in Paris.",
    "top_k": 5,
}


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    app.dependency_overrides[get_settings] = lambda: SimpleNamespace(internal_api_token=TEST_TOKEN)

    @app.get("/test/identity")
    def identity(
        user_id: Annotated[str, Depends(require_internal_verification)],
    ) -> dict[str, str]:
        return {"user_id": user_id}

    with TestClient(app) as test_client:
        yield test_client


def test_direct_verification_without_token_is_rejected(
    client: TestClient,
) -> None:
    response = client.post("/api/v1/verify", json=TEST_CLAIM)
    assert response.status_code == 401


def test_invalid_service_token_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/v1/verify",
        json=TEST_CLAIM,
        headers={
            "X-Service-Token": "invalid-token",
            "X-Verified-User": "test-user",
        },
    )
    assert response.status_code == 401


def test_missing_verified_user_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/v1/verify",
        json=TEST_CLAIM,
        headers={"X-Service-Token": TEST_TOKEN},
    )
    assert response.status_code == 401


def test_valid_service_identity_is_accepted(client: TestClient) -> None:
    response = client.get(
        "/test/identity",
        headers={
            "X-Service-Token": TEST_TOKEN,
            "X-Verified-User": "test-user",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"user_id": "test-user"}


def test_missing_server_configuration_fails_closed(
    client: TestClient,
) -> None:
    client.app.dependency_overrides[get_settings] = lambda: SimpleNamespace(internal_api_token="")

    response = client.post(
        "/api/v1/verify",
        json=TEST_CLAIM,
        headers={
            "X-Service-Token": TEST_TOKEN,
            "X-Verified-User": "test-user",
        },
    )
    assert response.status_code == 503
