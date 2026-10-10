"""Authenticated API for the evidence verification pipeline."""

from dataclasses import asdict
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from starlette.concurrency import run_in_threadpool

from apps.api.core.service_auth import require_internal_verification
from apps.api.schemas.verification import VerificationRequest, VerificationResponse
from apps.api.services.verification import (
    VerificationBusyError,
    VerificationUnavailableError,
    run_verification,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/verify", tags=["verification"])


@router.post(
    "",
    response_model=VerificationResponse,
    status_code=status.HTTP_200_OK,
)
async def verify_claim(
    request: VerificationRequest,
    verified_user: Annotated[str, Depends(require_internal_verification)],
) -> VerificationResponse:
    """Verify a claim only when submitted by the trusted web service."""

    # The dependency has already authenticated this user identity.
    # It is available here for future authorization and audit controls.
    _ = verified_user

    try:
        result = await run_in_threadpool(
            run_verification,
            request.claim,
            request.top_k,
        )

        response = VerificationResponse.model_validate(asdict(result))

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
        logger.exception(
            "verification_failed",
            error_type=type(exc).__name__,
        )
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
