"""Lazy, CPU-safe access to the existing Phase 7E verification pipeline."""

from __future__ import annotations

from functools import lru_cache
from threading import Lock
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ml.verification.evidence_pipeline import ClaimVerification, ClaimVerificationPipeline


class VerificationUnavailableError(RuntimeError):
    """Required retrieval or calibrated-model artifacts are unavailable."""


class VerificationBusyError(RuntimeError):
    """Another verification is using the local CPU pipeline."""


_load_lock = Lock()
_inference_lock = Lock()


@lru_cache(maxsize=1)
def _build_pipeline() -> ClaimVerificationPipeline:
    # Import only when the first request arrives; no model load during app startup.
    from apps.api.services.retrieval import get_retrieval_pipeline
    from ml.verification.evidence_pipeline import ClaimVerificationPipeline
    from ml.verification.nli_inference import CalibratedNliVerifier

    return ClaimVerificationPipeline(
        retriever=get_retrieval_pipeline(),
        nli_predictor=CalibratedNliVerifier(device="cpu"),
        confidence_threshold=0.90,
    )


def get_verification_pipeline() -> ClaimVerificationPipeline:
    # lru_cache alone can compute the same entry in concurrent first requests.
    with _load_lock:
        try:
            return _build_pipeline()
        except (FileNotFoundError, OSError, ValueError) as exc:
            raise VerificationUnavailableError(
                "The verification model or retrieval artifacts cannot be loaded."
            ) from exc


def run_verification(claim: str, top_k: int) -> ClaimVerification:
    normalized_claim = claim.strip()
    if len(normalized_claim) < 3:
        raise ValueError("Claim must contain at least three characters.")
    if not 1 <= top_k <= 20:
        raise ValueError("top_k must be between 1 and 20.")

    # Fail fast instead of launching parallel heavyweight CPU inference requests.
    if not _inference_lock.acquire(blocking=False):
        raise VerificationBusyError("Another verification is already running.")

    try:
        pipeline = get_verification_pipeline()
        return pipeline.verify(normalized_claim, top_k=top_k)
    finally:
        _inference_lock.release()
