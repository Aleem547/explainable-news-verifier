"""FastAPI contract tests using fake results; pretrained models are not loaded."""

from dataclasses import dataclass

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.routes import verification as verification_route
from apps.api.services.verification import (
    VerificationBusyError,
    VerificationUnavailableError,
)


@dataclass
class FakeEvidence:
    rank: int = 1
    page_id: str = "Eiffel_Tower"
    sentence_id: int = 0
    text: str = "The Eiffel Tower is in Paris, France."
    page_rank: int | None = 1
    bm25_score: float | None = 2.5
    dense_score: float | None = 0.81
    rrf_score: float = 0.03
    cross_encoder_score: float = 5.2
    nli_label: str = "ENTAILMENT"
    nli_confidence: float = 0.96
    accepted: bool = True
    probability_entailment: float = 0.96
    probability_contradiction: float = 0.02
    probability_neutral: float = 0.02


@dataclass
class FakeResult:
    claim: str
    verdict: str
    confidence_threshold: float
    retrieved_count: int
    assessed_count: int
    supporting_pages: list[str]
    refuting_pages: list[str]
    evidence: list[FakeEvidence]
    latency_ms: float
    warning: str


@pytest.fixture
def client() -> TestClient:
    application = FastAPI()
    application.include_router(verification_route.router, prefix="/api/v1")
    return TestClient(application)


def test_success(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[str, int]] = []

    def fake_run(claim: str, top_k: int) -> FakeResult:
        seen.append((claim, top_k))
        return FakeResult(
            claim=claim,
            verdict="SUPPORTING_EVIDENCE",
            confidence_threshold=0.90,
            retrieved_count=1,
            assessed_count=1,
            supporting_pages=["Eiffel_Tower"],
            refuting_pages=[],
            evidence=[FakeEvidence()],
            latency_ms=12.5,
            warning="Provisional evidence-based finding, not a truth probability.",
        )

    monkeypatch.setattr(verification_route, "run_verification", fake_run)
    response = client.post(
        "/api/v1/verify", json={"claim": "  Eiffel Tower is in Paris  ", "top_k": 3}
    )
    assert response.status_code == 200
    payload = response.json()
    assert seen == [("Eiffel Tower is in Paris", 3)]
    assert payload["verdict"] == "SUPPORTING_EVIDENCE"
    assert payload["supporting_pages"] == ["Eiffel_Tower"]
    assert payload["evidence"][0]["nli_label"] == "ENTAILMENT"
    assert payload["evidence"][0]["accepted"] is True
    assert "warning" in payload
    assert "claim_confidence" not in payload


@pytest.mark.parametrize(
    "payload",
    [
        {"claim": "  "},
        {"claim": "ab"},
        {"claim": "a" * 2001},
        {"claim": "The Eiffel Tower is in Paris", "top_k": 0},
        {"claim": "The Eiffel Tower is in Paris", "top_k": 21},
        {"top_k": 3},
    ],
)
def test_invalid_request_is_422(client: TestClient, payload: dict[str, object]) -> None:
    assert client.post("/api/v1/verify", json=payload).status_code == 422


def test_busy_is_429(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(claim: str, top_k: int) -> FakeResult:
        raise VerificationBusyError("Busy")

    monkeypatch.setattr(verification_route, "run_verification", fake_run)
    response = client.post("/api/v1/verify", json={"claim": "Is Paris in France?"})
    assert response.status_code == 429
    assert response.headers["retry-after"] == "5"


def test_missing_model_is_503(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(claim: str, top_k: int) -> FakeResult:
        raise VerificationUnavailableError("Model unavailable")

    monkeypatch.setattr(verification_route, "run_verification", fake_run)
    response = client.post("/api/v1/verify", json={"claim": "Is Paris in France?"})
    assert response.status_code == 503
    assert "Model unavailable" not in response.text


def test_unexpected_failure_is_500(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(claim: str, top_k: int) -> FakeResult:
        raise RuntimeError("Internal implementation detail")

    monkeypatch.setattr(verification_route, "run_verification", fake_run)
    response = client.post("/api/v1/verify", json={"claim": "Is Paris in France?"})
    assert response.status_code == 500
    assert "Internal implementation detail" not in response.text
