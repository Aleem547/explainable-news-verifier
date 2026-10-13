"""Authenticated API for the evidence verification pipeline."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import asdict
from threading import Event
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from starlette.concurrency import run_in_threadpool

from apps.api.core.service_auth import require_internal_verification
from apps.api.schemas.verification import VerificationRequest, VerificationResponse
from apps.api.services.verification import (
    VerificationBusyError,
    VerificationCancelledError,
    VerificationUnavailableError,
    run_verification,
    verification_cancellation_context,
)

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/verify", tags=["verification"])


async def _watch_client_disconnect(http_request: Request, cancel_event: Event) -> None:
    """Signal abandoned queued work; running inference is allowed to finish."""
    while not cancel_event.is_set():
        try:
            disconnected = await http_request.is_disconnected()
        except Exception as exc:
            # Disconnect polling must not make a valid verification fail.
            logger.warning("verification_disconnect_poll_failed", error_type=type(exc).__name__)
            return
        if disconnected:
            cancel_event.set()
            return
        await asyncio.sleep(0.2)


@router.post("", response_model=VerificationResponse, status_code=status.HTTP_200_OK)
async def verify_claim(
    request: VerificationRequest,
    http_request: Request,
    verified_user: Annotated[str, Depends(require_internal_verification)],
) -> VerificationResponse:
    """Verify a claim only when submitted by the trusted web service."""
    _ = verified_user
    cancel_event = Event()
    watcher = asyncio.create_task(_watch_client_disconnect(http_request, cancel_event))

    try:
        try:
            # AnyIO propagates ContextVar values to the worker thread.
            # Preserve the existing two-argument service contract and test mocks.
            with verification_cancellation_context(cancel_event):
                result = await run_in_threadpool(
                    run_verification,
                    request.claim,
                    request.top_k,
                )
            response = VerificationResponse.model_validate(asdict(result))

        except VerificationCancelledError as exc:
            # 499 is a conventional log status; the disconnected client won't receive it.
            logger.info("verification_waiter_cancelled")
            raise HTTPException(status_code=499, detail="Client disconnected.") from exc

        except VerificationBusyError as exc:
            logger.warning("verification_busy")
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Verification is busy. Please retry shortly.",
                headers={"Retry-After": "5"},
            ) from exc

        except (FileNotFoundError, VerificationUnavailableError) as exc:
            logger.exception("verification_artifacts_unavailable")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="The verification model or evidence index is unavailable.",
            ) from exc

        except Exception as exc:
            logger.exception("verification_failed", error_type=type(exc).__name__)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Claim verification failed.",
            ) from exc

        logger.info(
            "verification_completed",
            claim_length=len(response.claim),
            verdict=response.verdict,
            retrieved_count=response.retrieved_count,
            assessed_count=response.assessed_count,
            latency_ms=response.latency_ms,
        )
        return response

    finally:
        # A cancelled ASGI task must also abandon its place in the waiting queue.
        cancel_event.set()
        watcher.cancel()
        with suppress(asyncio.CancelledError):
            await watcher
