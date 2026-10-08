"""Public development API for the provisional evidence verification pipeline."""

from dataclasses import asdict

import structlog
from fastapi import APIRouter, HTTPException, status
from starlette.concurrency import run_in_threadpool

from apps.api.schemas.verification import VerificationRequest, VerificationResponse
from apps.api.services.verification import (
    VerificationBusyError,
    VerificationUnavailableError,
    run_verification,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/verify", tags=["verification"])


@router.post("", response_model=VerificationResponse, status_code=status.HTTP_200_OK)
async def verify_claim(request: VerificationRequest) -> VerificationResponse:
    try:
        result = await run_in_threadpool(run_verification, request.claim, request.top_k)
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
