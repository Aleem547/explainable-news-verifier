import structlog
from fastapi import (
    APIRouter,
    HTTPException,
    status,
)
from starlette.concurrency import (
    run_in_threadpool,
)

from apps.api.schemas.classification import (
    ClassificationRequest,
    ClassificationResponse,
)
from apps.api.services.classification import (
    classify_claim,
)

logger = structlog.get_logger(__name__)


router = APIRouter(
    prefix="/classification",
    tags=["classification"],
)


@router.post(
    "",
    response_model=ClassificationResponse,
)
async def classify(
    request: ClassificationRequest,
) -> ClassificationResponse:
    try:
        response = await run_in_threadpool(
            classify_claim,
            request.claim,
        )

    except FileNotFoundError as exc:
        logger.exception(
            "classifier_model_missing",
            error=str(exc),
        )

        raise HTTPException(
            status_code=(status.HTTP_503_SERVICE_UNAVAILABLE),
            detail=("Claim classifier is unavailable."),
        ) from exc

    except ValueError as exc:
        raise HTTPException(
            status_code=(status.HTTP_400_BAD_REQUEST),
            detail=str(exc),
        ) from exc

    except Exception as exc:
        logger.exception(
            "classification_failed",
            error=str(exc),
        )

        raise HTTPException(
            status_code=(status.HTTP_500_INTERNAL_SERVER_ERROR),
            detail=("Claim classification failed."),
        ) from exc

    logger.info(
        "classification_completed",
        label=response.label,
        confidence=response.confidence,
        latency_ms=response.latency_ms,
    )

    return response
