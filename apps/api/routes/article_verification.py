"""Restricted article-verification API (13E.7; explicit operator opt-in).

Only pasted plaintext is supported in this preview. URL verification requires a
trusted discovery record and explicit publisher permission; client-supplied URL
or pseudo-metadata is not a safe substitute.
"""

from __future__ import annotations

import asyncio
import os

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict, Field, StrictStr
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import JSONResponse

from apps.api.core.service_auth import require_internal_verification
from apps.api.db.session import get_db_session
from apps.api.services.article_api_workflow import verify_pasted_article

router = APIRouter(prefix="/article", tags=["article verification preview"])
# Per-process admission guard; does not add a second public inference queue.
_article_admission = asyncio.Semaphore(1)


class ArticleVerificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: str = Field(pattern=r"^pasted$")
    text: StrictStr = Field(min_length=100, max_length=8_000)
    title: StrictStr | None = Field(default=None, max_length=300)


@router.post("/verify", status_code=status.HTTP_200_OK)
async def verify_article_endpoint(
    payload: ArticleVerificationRequest,
    session: AsyncSession = Depends(get_db_session),
    authenticated_user: str = Depends(require_internal_verification),
) -> JSONResponse:
    """Build a claim-by-claim report without storing user text.

    Router is mounted with require_inference_access and
    require_verified_user_access, just like the existing /verify path.
    """
    _ = authenticated_user
    if os.getenv("ARTICLE_VERIFICATION_ENABLED", "").strip().lower() != "true":
        raise HTTPException(503, "Article verification preview is disabled.")
    if len(payload.text.encode("utf-8")) > 10_000:
        raise HTTPException(413, "Article text is too large.")

    # Fail promptly when already processing an article, without an unbounded
    # per-process waiting queue. Model execution may outlive the web timeout.
    try:
        await asyncio.wait_for(_article_admission.acquire(), timeout=0.05)
    except TimeoutError as exc:
        raise HTTPException(
            429, "Article verification is busy. Please retry shortly.",
            headers={"Retry-After": "20"},
        ) from exc
    try:
        # Model inference runs in worker threads, which Python cannot stop by
        # cancelling their awaiting task. Shield the complete article workflow
        # so its database session remains owned by this request until all work
        # finishes. In particular, don't release admission on disconnect while
        # inference could still be running.
        work = asyncio.create_task(
            verify_pasted_article(
                session, text=payload.text, title=payload.title, max_verifications=1,
            )
        )
        try:
            try:
                result = await asyncio.shield(work)
            except asyncio.CancelledError:
                # A client disconnect or proxy timeout must NOT admit another
                # CPU job while the current one is still running. Drain the
                # workflow before releasing admission or closing its DB session.
                # Repeat cancellations are also safe: admission stays held.
                while not work.done():
                    try:
                        await asyncio.shield(work)
                    except asyncio.CancelledError:
                        continue
                    except Exception:
                        break
                if not work.cancelled():
                    work.exception()  # retrieve any hidden exception
                raise
        except ValueError as exc:
            # Never echo the raw submitted article or internal exception details.
            raise HTTPException(422, "Article text could not be prepared.") from exc
        except Exception as exc:
            raise HTTPException(503, "Article verification is temporarily unavailable.") from exc
        return JSONResponse(
            jsonable_encoder(result),
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        )
    finally:
        _article_admission.release()
