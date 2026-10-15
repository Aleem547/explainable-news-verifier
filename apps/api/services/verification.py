"""Lazy, CPU-safe verification with bounded, cancellable, process-local FIFO waiting."""

from __future__ import annotations

import os
from collections import deque
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from functools import lru_cache
from threading import Condition, Event, Lock
from time import monotonic
from typing import TYPE_CHECKING, Iterator

import structlog

if TYPE_CHECKING:
    from ml.verification.evidence_pipeline import ClaimVerification, ClaimVerificationPipeline

logger = structlog.get_logger(__name__)


class VerificationUnavailableError(RuntimeError):
    """Required artifacts are unavailable, or this worker is shutting down."""


class VerificationBusyError(RuntimeError):
    """The bounded inference queue is full or its wait deadline elapsed."""


class VerificationCancelledError(RuntimeError):
    """A disconnected caller abandoned its place in the waiting queue."""


def _max_waiters_from_env() -> int:
    value = int(os.getenv("VERIFICATION_MAX_WAITERS", "3"))
    if not 0 <= value <= 8:
        raise ValueError("VERIFICATION_MAX_WAITERS must be between 0 and 8")
    return value


def _wait_timeout_from_env() -> float:
    value = float(os.getenv("VERIFICATION_QUEUE_WAIT_SECONDS", "20"))
    if not 0 < value <= 60:
        raise ValueError("VERIFICATION_QUEUE_WAIT_SECONDS must be greater than 0 and at most 60")
    return value


_MAX_WAITERS = _max_waiters_from_env()
_WAIT_TIMEOUT_SECONDS = _wait_timeout_from_env()
_POLL_SECONDS = 0.2

_load_lock = Lock()
_queue_condition = Condition(Lock())
_waiting_tickets: deque[object] = deque()
_inference_active = False
_accepting_requests = True
_request_cancel_event: ContextVar[Event | None] = ContextVar(
    "verification_request_cancel_event", default=None
)


@contextmanager
def verification_cancellation_context(event: Event) -> Iterator[None]:
    """Propagate per-request cancellation into AnyIO worker threads.

    Keeping run_verification(claim, top_k) callable preserves API compatibility.
    AnyIO copies the request context when dispatching run_in_threadpool.
    """
    token = _request_cancel_event.set(event)
    try:
        yield
    finally:
        _request_cancel_event.reset(token)


@dataclass(frozen=True)
class VerificationQueueStatus:
    """Snapshot of this process only, not a distributed queue metric."""

    active: bool
    waiting: int
    max_waiters: int
    wait_timeout_seconds: float
    accepting: bool


def get_verification_queue_status() -> VerificationQueueStatus:
    with _queue_condition:
        return VerificationQueueStatus(
            active=_inference_active,
            waiting=len(_waiting_tickets),
            max_waiters=_MAX_WAITERS,
            wait_timeout_seconds=_WAIT_TIMEOUT_SECONDS,
            accepting=_accepting_requests,
        )


def start_verification_queue() -> None:
    """Open admission for a new application lifespan (without interrupting work)."""
    global _accepting_requests
    with _queue_condition:
        if _inference_active or _waiting_tickets:
            raise RuntimeError("Cannot reopen the queue while jobs are present")
        _accepting_requests = True


def shutdown_verification_queue() -> None:
    """Close admission and wake waiting jobs so they can exit without inference."""
    global _accepting_requests
    with _queue_condition:
        _accepting_requests = False
        _queue_condition.notify_all()


def wait_for_verification_idle(timeout_seconds: float) -> bool:
    """Wait for the active inference and all departing waiters, up to a deadline."""
    deadline = monotonic() + max(0.0, timeout_seconds)
    with _queue_condition:
        while _inference_active or _waiting_tickets:
            remaining = deadline - monotonic()
            if remaining <= 0:
                return False
            _queue_condition.wait(timeout=remaining)
        return True


@lru_cache(maxsize=1)
def _build_pipeline() -> ClaimVerificationPipeline:
    # Keep model loading lazy; no heavyweight model during startup.
    from apps.api.services.retrieval import get_retrieval_pipeline
    from ml.verification.evidence_pipeline import ClaimVerificationPipeline
    from ml.verification.nli_inference import CalibratedNliVerifier

    # Profiling is opt-in. Model initialization remains lazy and serialized by
    # the existing inference slot. This patch does not change admission logic.
    profile_stages = os.getenv("VERIFICATION_STAGE_TIMING", "0") == "1"
    init_started = monotonic() if profile_stages else None
    retriever = get_retrieval_pipeline()
    retrieval_loaded = monotonic() if profile_stages else None
    nli_predictor = CalibratedNliVerifier(device="cpu")
    nli_loaded = monotonic() if profile_stages else None

    if profile_stages:
        assert init_started is not None
        assert retrieval_loaded is not None
        assert nli_loaded is not None
        logger.info(
            "verification_model_initialization_timing",
            retrieval_init_ms=round((retrieval_loaded - init_started) * 1000, 2),
            nli_init_ms=round((nli_loaded - retrieval_loaded) * 1000, 2),
            total_init_ms=round((nli_loaded - init_started) * 1000, 2),
        )
        # Only aggregate timings and counts; never emit claim text or user data.
        return ClaimVerificationPipeline(
            retriever=retriever,
            nli_predictor=nli_predictor,
            confidence_threshold=0.90,
            stage_observer=lambda stages: logger.info("verification_stage_timing", **stages),
        )
    return ClaimVerificationPipeline(
        retriever=retriever,
        nli_predictor=nli_predictor,
        confidence_threshold=0.90,
    )


def get_verification_pipeline() -> ClaimVerificationPipeline:
    with _load_lock:
        try:
            return _build_pipeline()
        except (FileNotFoundError, OSError, ValueError) as exc:
            raise VerificationUnavailableError(
                "The verification model or retrieval artifacts cannot be loaded."
            ) from exc


def _acquire_inference_slot(cancel_event: Event | None = None) -> float:
    """Admit one job or wait FIFO. Designed to run in a worker thread."""
    global _inference_active

    with _queue_condition:
        if not _accepting_requests:
            raise VerificationUnavailableError("The verification worker is shutting down.")
        if cancel_event is not None and cancel_event.is_set():
            raise VerificationCancelledError("The request was cancelled before inference.")

        if not _inference_active and not _waiting_tickets:
            _inference_active = True
            return 0.0

        if len(_waiting_tickets) >= _MAX_WAITERS:
            logger.warning("verification_queue_full", waiting=len(_waiting_tickets))
            raise VerificationBusyError("The verification queue is full.")

        ticket = object()
        started = monotonic()
        deadline = started + _WAIT_TIMEOUT_SECONDS
        _waiting_tickets.append(ticket)
        try:
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    raise VerificationCancelledError("Client disconnected while waiting.")
                if not _accepting_requests:
                    raise VerificationUnavailableError("The verification worker is shutting down.")

                remaining = deadline - monotonic()
                if remaining <= 0:
                    logger.warning(
                        "verification_queue_timeout",
                        wait_ms=round((monotonic() - started) * 1000, 2),
                    )
                    raise VerificationBusyError("The verification queue wait timed out.")

                if not _inference_active and _waiting_tickets[0] is ticket:
                    _waiting_tickets.popleft()
                    _inference_active = True
                    return monotonic() - started

                # Poll cancellation, since a threading.Event alone doesn't wake a Condition.
                _queue_condition.wait(timeout=min(remaining, _POLL_SECONDS))
        except BaseException:
            if ticket in _waiting_tickets:
                _waiting_tickets.remove(ticket)
                _queue_condition.notify_all()
            raise


def _release_inference_slot() -> None:
    global _inference_active
    with _queue_condition:
        _inference_active = False
        _queue_condition.notify_all()


def run_verification(
    claim: str, top_k: int, cancel_event: Event | None = None
) -> ClaimVerification:
    normalized_claim = claim.strip()
    if len(normalized_claim) < 3:
        raise ValueError("Claim must contain at least three characters.")
    if not 1 <= top_k <= 20:
        raise ValueError("top_k must be between 1 and 20.")

    effective_cancel_event = (
        cancel_event if cancel_event is not None else _request_cancel_event.get()
    )
    waited_seconds = _acquire_inference_slot(effective_cancel_event)
    try:
        # A queued request may disconnect exactly as it acquires the slot.
        if effective_cancel_event is not None and effective_cancel_event.is_set():
            raise VerificationCancelledError("Client disconnected before inference began.")
        if waited_seconds > 0:
            logger.info("verification_queue_admitted", wait_ms=round(waited_seconds * 1000, 2))
        # Once inference begins, a disconnect does NOT terminate CPU inference.
        # The slot is held until model work returns, to protect model state.
        pipeline = get_verification_pipeline()
        return pipeline.verify(normalized_claim, top_k=top_k)
    finally:
        _release_inference_slot()
