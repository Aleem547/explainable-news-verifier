"""Restricted Phase 9G diagnostic API. Disabled without explicit operator opt-in."""

from __future__ import annotations

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.connectors.http_client import ProviderHttpClient, new_provider_http_client
from apps.api.connectors.registry import ConnectorConfiguration
from apps.api.db.session import get_db_session
from apps.api.schemas.multisource import (
    ExternalDiscoveryRequest,
    ExternalDiscoveryResponse,
    MultiSourceAssessmentRequest,
    MultiSourceAssessmentResponse,
)
from apps.api.security.multisource import require_multisource_access
from apps.api.services.multisource import (
    MultiSourceBusyError,
    MultiSourceModelUnavailable,
    evaluate_captured_evidence,
)
from apps.api.services.multisource_discovery import (
    NoConfiguredProviderError,
    discover_external_metadata,
)

logger = structlog.get_logger(__name__)


router = APIRouter(
    prefix="/multisource",
    tags=["experimental multi-source diagnostics"],
    dependencies=[Depends(require_multisource_access)],
)


@router.post("/assess", response_model=MultiSourceAssessmentResponse)
async def assess_multisource_claim(
    request: MultiSourceAssessmentRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> MultiSourceAssessmentResponse:
    """Run NLI on stored, licensed snapshot passages; persist auditable diagnostics."""
    try:
        async with session.begin():
            result = await evaluate_captured_evidence(session, request)
        logger.info("multisource_assessment_completed", evidence_count=len(result.evidence))
        return result
    except MultiSourceBusyError as exc:
        raise HTTPException(429, "Local NLI is busy", headers={"Retry-After": "5"}) from exc
    except MultiSourceModelUnavailable as exc:
        raise HTTPException(503, "Calibrated NLI model is unavailable") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        logger.exception("multisource_assessment_failed", error_type=type(exc).__name__)
        raise HTTPException(500, "Multi-source assessment failed") from exc


@router.post("/discover", response_model=ExternalDiscoveryResponse)
async def discover_multisource_metadata(
    request: ExternalDiscoveryRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ExternalDiscoveryResponse:
    """Opt-in NewsAPI/fact-check search; stores discovery metadata, not full content."""
    try:
        async with new_provider_http_client() as client:
            async with session.begin():
                result = await discover_external_metadata(
                    session,
                    request,
                    ProviderHttpClient(client),
                    ConnectorConfiguration.from_environment(),
                )
        logger.info(
            "multisource_discovery_completed", provider_count=len(result.searched_providers)
        )
        return result
    except NoConfiguredProviderError as exc:
        raise HTTPException(503, "No available discovery providers") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        logger.exception("multisource_discovery_failed", error_type=type(exc).__name__)
        raise HTTPException(502, "External discovery failed") from exc
