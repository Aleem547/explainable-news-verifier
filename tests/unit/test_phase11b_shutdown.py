"""Isolated Phase 11B tests for request cancellation and graceful queue closing."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import monotonic, sleep

import pytest

from apps.api.services import verification as service


@pytest.fixture(autouse=True)
def reset_local_queue():
    # Do not let shutdown state leak into unrelated tests.
    service.start_verification_queue()
    yield
    service.shutdown_verification_queue()
    assert service.wait_for_verification_idle(2.0)
    service.start_verification_queue()


def _wait_until(predicate, timeout=3.0):
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        if predicate():
            return
        sleep(0.01)
    raise AssertionError("Expected queue state was not reached")


def test_cancelled_waiter_leaves_queue_and_next_request_can_run(monkeypatch):
    entered = Event()
    release = Event()

    class FakePipeline:
        def verify(self, claim, top_k):
            if claim == "first":
                entered.set()
                assert release.wait(timeout=3)
            return claim

    monkeypatch.setattr(service, "get_verification_pipeline", lambda: FakePipeline())
    cancel = Event()

    with ThreadPoolExecutor(max_workers=3) as executor:
        first = executor.submit(service.run_verification, "first", 5)
        assert entered.wait(2)
        waiting = executor.submit(service.run_verification, "second", 5, cancel)
        _wait_until(lambda: service.get_verification_queue_status().waiting == 1)
        cancel.set()
        with pytest.raises(service.VerificationCancelledError):
            waiting.result(timeout=2)
        assert service.get_verification_queue_status().waiting == 0
        release.set()
        assert first.result(timeout=2) == "first"
        assert executor.submit(service.run_verification, "third", 5).result(timeout=2) == "third"


def test_shutdown_wakes_waiters_rejects_new_requests_and_drains(monkeypatch):
    entered = Event()
    release = Event()

    class FakePipeline:
        def verify(self, claim, top_k):
            entered.set()
            assert release.wait(timeout=3)
            return claim

    monkeypatch.setattr(service, "get_verification_pipeline", lambda: FakePipeline())

    with ThreadPoolExecutor(max_workers=2) as executor:
        active = executor.submit(service.run_verification, "active", 5)
        assert entered.wait(2)
        waiting = executor.submit(service.run_verification, "waiting", 5)
        _wait_until(lambda: service.get_verification_queue_status().waiting == 1)
        service.shutdown_verification_queue()
        assert service.get_verification_queue_status().accepting is False
        with pytest.raises(service.VerificationUnavailableError):
            waiting.result(timeout=2)
        with pytest.raises(service.VerificationUnavailableError):
            service.run_verification("rejected", 5)
        assert service.wait_for_verification_idle(0.02) is False
        release.set()
        assert active.result(timeout=2) == "active"
        assert service.wait_for_verification_idle(1.0) is True


def test_cancel_before_admission(monkeypatch):
    monkeypatch.setattr(service, "get_verification_pipeline", lambda: None)
    cancel = Event()
    cancel.set()
    with pytest.raises(service.VerificationCancelledError):
        service.run_verification("claim", 5, cancel)
    assert service.get_verification_queue_status().active is False


def test_shutdown_empty_queue_then_restart(monkeypatch):
    monkeypatch.setattr(
        service,
        "get_verification_pipeline",
        lambda: type("Pipeline", (), {"verify": lambda self, claim, top_k: claim})(),
    )
    service.shutdown_verification_queue()
    assert service.wait_for_verification_idle(0) is True
    service.start_verification_queue()
    assert service.run_verification("hello", 5) == "hello"
