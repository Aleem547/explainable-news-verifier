"""Phase 11B FIFO admission tests; do not load model weights."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import monotonic, sleep

import pytest

from apps.api.services import verification as service


def wait_until(predicate, timeout=3.0):
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        if predicate():
            return
        sleep(0.01)
    pytest.fail("Timed out waiting for a concurrency test state")


@pytest.fixture(autouse=True)
def isolate_queue(monkeypatch):
    status = service.get_verification_queue_status()
    assert status.active is False and status.waiting == 0
    monkeypatch.setattr(service, "_MAX_WAITERS", 2)
    monkeypatch.setattr(service, "_WAIT_TIMEOUT_SECONDS", 2.0)
    yield
    status = service.get_verification_queue_status()
    assert status.active is False and status.waiting == 0


def test_fifo_and_single_active_inference(monkeypatch):
    entered = []
    release_first = Event()

    class Pipeline:
        def verify(self, claim, top_k):
            entered.append(claim)
            if claim == "first":
                assert release_first.wait(5)
            return claim

    monkeypatch.setattr(service, "get_verification_pipeline", lambda: Pipeline())

    try:
        with ThreadPoolExecutor(max_workers=3) as pool:
            first = pool.submit(service.run_verification, "first", 5)
            wait_until(lambda: entered == ["first"])
            second = pool.submit(service.run_verification, "second", 5)
            wait_until(lambda: service.get_verification_queue_status().waiting == 1)
            third = pool.submit(service.run_verification, "third", 5)
            wait_until(lambda: service.get_verification_queue_status().waiting == 2)
            assert entered == ["first"]
            release_first.set()
            assert first.result(timeout=5) == "first"
            assert second.result(timeout=5) == "second"
            assert third.result(timeout=5) == "third"
    finally:
        release_first.set()
    assert entered == ["first", "second", "third"]


def test_full_queue_rejects_excess_requests(monkeypatch):
    monkeypatch.setattr(service, "_MAX_WAITERS", 1)
    release = Event()

    class Pipeline:
        def verify(self, claim, top_k):
            if claim == "first":
                assert release.wait(5)
            return claim

    monkeypatch.setattr(service, "get_verification_pipeline", lambda: Pipeline())

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(service.run_verification, "first", 5)
            wait_until(lambda: service.get_verification_queue_status().active)
            second = pool.submit(service.run_verification, "second", 5)
            wait_until(lambda: service.get_verification_queue_status().waiting == 1)
            with pytest.raises(service.VerificationBusyError, match="full"):
                service.run_verification("third", 5)
            release.set()
            assert first.result(timeout=5) == "first"
            assert second.result(timeout=5) == "second"
    finally:
        release.set()


def test_queue_timeout_does_not_block_following_requests(monkeypatch):
    monkeypatch.setattr(service, "_WAIT_TIMEOUT_SECONDS", 0.15)
    release = Event()

    class Pipeline:
        def verify(self, claim, top_k):
            if claim == "first":
                assert release.wait(5)
            return claim

    monkeypatch.setattr(service, "get_verification_pipeline", lambda: Pipeline())

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(service.run_verification, "first", 5)
            wait_until(lambda: service.get_verification_queue_status().active)
            second = pool.submit(service.run_verification, "second", 5)
            with pytest.raises(service.VerificationBusyError, match="timed out"):
                second.result(timeout=3)
            assert service.get_verification_queue_status().waiting == 0
            release.set()
            assert first.result(timeout=5) == "first"
    finally:
        release.set()

    assert service.run_verification("third", 5) == "third"


def test_inference_error_releases_slot(monkeypatch):
    class Pipeline:
        def verify(self, claim, top_k):
            if claim == "first":
                raise RuntimeError("test inference failure")
            return claim

    monkeypatch.setattr(service, "get_verification_pipeline", lambda: Pipeline())
    with pytest.raises(RuntimeError, match="test inference failure"):
        service.run_verification("first", 5)

    assert service.get_verification_queue_status().active is False
    assert service.run_verification("second", 5) == "second"


def test_zero_waiters_keeps_fail_fast_behavior(monkeypatch):
    monkeypatch.setattr(service, "_MAX_WAITERS", 0)
    release = Event()

    class Pipeline:
        def verify(self, claim, top_k):
            if claim == "first":
                assert release.wait(5)
            return claim

    monkeypatch.setattr(service, "get_verification_pipeline", lambda: Pipeline())
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            first = pool.submit(service.run_verification, "first", 5)
            wait_until(lambda: service.get_verification_queue_status().active)
            with pytest.raises(service.VerificationBusyError, match="full"):
                service.run_verification("second", 5)
            release.set()
            assert first.result(timeout=5) == "first"
    finally:
        release.set()
