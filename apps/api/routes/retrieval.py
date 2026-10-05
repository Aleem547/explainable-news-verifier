import structlog
from fastapi import (
    APIRouter,
    HTTPException,
    status,
)
from starlette.concurrency import (
    run_in_threadpool,
)

from apps.api.schemas.retrieval import (
    RetrievalRequest,
    RetrievalResponse,
)
from apps.api.services.retrieval import (
    run_retrieval,
)

logger = structlog.get_logger(__name__)


router = APIRouter(
    prefix="/retrieval",
    tags=["retrieval"],
)


@router.post(
    "",
    response_model=RetrievalResponse,
    status_code=status.HTTP_200_OK,
)
async def retrieve_evidence(
    request: RetrievalRequest,
) -> RetrievalResponse:
    try:
        response = await run_in_threadpool(
            run_retrieval,
            request.claim,
            request.top_k,
        )

    except FileNotFoundError as exc:
        logger.exception(
            "retrieval_artifact_missing",
            error=str(exc),
        )

        raise HTTPException(
            status_code=(status.HTTP_503_SERVICE_UNAVAILABLE),
            detail=("Retrieval artifacts are unavailable."),
        ) from exc

    except ValueError as exc:
        logger.warning(
            "invalid_retrieval_request",
            error=str(exc),
        )

        raise HTTPException(
            status_code=(status.HTTP_400_BAD_REQUEST),
            detail=str(exc),
        ) from exc

    except Exception as exc:
        logger.exception(
            "retrieval_failed",
            error=str(exc),
        )

        raise HTTPException(
            status_code=(status.HTTP_500_INTERNAL_SERVER_ERROR),
            detail=("Evidence retrieval failed."),
        ) from exc

    logger.info(
        "retrieval_completed",
        claim_length=len(request.claim),
        requested_top_k=(request.top_k),
        returned_evidence=(response.returned_evidence),
        latency_ms=(response.latency_ms),
    )

    return response
