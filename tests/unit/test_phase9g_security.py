"""The experimental API has mandatory opt-in and a 32+ character secret."""

import pytest
from fastapi import HTTPException

from apps.api.security.multisource import require_multisource_access


@pytest.fixture(autouse=True)
def clear_security(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ENABLE_EXPERIMENTAL_MULTISOURCE_API", raising=False)
    monkeypatch.delenv("MULTISOURCE_INTERNAL_TOKEN", raising=False)


def test_disabled_by_default() -> None:
    with pytest.raises(HTTPException) as exc:
        require_multisource_access("anything")
    assert exc.value.status_code == 503


def test_secret_required_even_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENABLE_EXPERIMENTAL_MULTISOURCE_API", "1")
    with pytest.raises(HTTPException) as exc:
        require_multisource_access("anything")
    assert exc.value.status_code == 503


def test_wrong_secret_is_unauthorized(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENABLE_EXPERIMENTAL_MULTISOURCE_API", "1")
    monkeypatch.setenv("MULTISOURCE_INTERNAL_TOKEN", "a" * 40)
    with pytest.raises(HTTPException) as exc:
        require_multisource_access("b" * 40)
    assert exc.value.status_code == 401


def test_correct_secret_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENABLE_EXPERIMENTAL_MULTISOURCE_API", "1")
    monkeypatch.setenv("MULTISOURCE_INTERNAL_TOKEN", "a" * 40)
    assert require_multisource_access("a" * 40) is None
