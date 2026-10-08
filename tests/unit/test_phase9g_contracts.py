"""Strict input validation protects expensive inference and temporal semantics."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from apps.api.schemas.multisource import ExternalDiscoveryRequest, MultiSourceAssessmentRequest


def valid() -> dict[str, object]:
    return {"claim": "The Eiffel Tower is in Paris", "passage_ids": [uuid4(), uuid4()]}


def test_accepts_aware_reference_time_and_window() -> None:
    request = MultiSourceAssessmentRequest.model_validate(
        {**valid(), "reference_at": datetime.now(UTC), "max_age_days": 30}
    )
    assert request.max_age_days == 30


@pytest.mark.parametrize("claim", ["  ", "a ", "\n"])
def test_blank_claim_rejected(claim: str) -> None:
    with pytest.raises(ValidationError):
        MultiSourceAssessmentRequest.model_validate({**valid(), "claim": claim})


def test_duplicate_passage_ids_rejected() -> None:
    pid = uuid4()
    with pytest.raises(ValidationError, match="distinct"):
        MultiSourceAssessmentRequest.model_validate({**valid(), "passage_ids": [pid, pid]})


def test_window_requires_reference_time() -> None:
    with pytest.raises(ValidationError, match="reference"):
        MultiSourceAssessmentRequest.model_validate({**valid(), "max_age_days": 5})


def test_naive_reference_rejected() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        MultiSourceAssessmentRequest.model_validate(
            {**valid(), "reference_at": datetime(2026, 10, 8)}
        )


def test_nonfinite_threshold_rejected() -> None:
    with pytest.raises(ValidationError):
        MultiSourceAssessmentRequest.model_validate(
            {**valid(), "confidence_threshold": float("nan")}
        )


def test_discovery_query_trimmed() -> None:
    assert ExternalDiscoveryRequest(query="  example  ").query == "example"


def test_empty_discovery_query_rejected() -> None:
    with pytest.raises(ValidationError):
        ExternalDiscoveryRequest(query="   ")
