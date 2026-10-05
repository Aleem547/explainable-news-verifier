import re
from functools import lru_cache
from pathlib import Path
from time import perf_counter

from apps.api.schemas.retrieval import (
    EvidenceResponse,
    RetrievalResponse,
)
from ml.retrieval.factory import (
    build_fever_retrieval_pipeline,
)
from ml.retrieval.pipeline import (
    EvidenceRetrievalPipeline,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]


FEVER_REPLACEMENTS = {
    "-LRB-": "(",
    "-RRB-": ")",
    "-LSB-": "[",
    "-RSB-": "]",
    "-LCB-": "{",
    "-RCB-": "}",
}

WHITESPACE_PATTERN = re.compile(r"\s+")

SPACE_BEFORE_PUNCTUATION = re.compile(r"\s+([,.;:!?])")


def clean_fever_text(
    value: str,
) -> str:
    cleaned = value

    for source, replacement in FEVER_REPLACEMENTS.items():
        cleaned = cleaned.replace(
            source,
            replacement,
        )

    cleaned = WHITESPACE_PATTERN.sub(
        " ",
        cleaned,
    )

    cleaned = SPACE_BEFORE_PUNCTUATION.sub(
        r"\1",
        cleaned,
    )

    return cleaned.strip()


@lru_cache(maxsize=1)
def get_retrieval_pipeline() -> EvidenceRetrievalPipeline:
    return build_fever_retrieval_pipeline(
        PROJECT_ROOT,
        device="cpu",
    )


def run_retrieval(
    claim: str,
    top_k: int,
) -> RetrievalResponse:
    normalized_claim = claim.strip()

    if not normalized_claim:
        raise ValueError("Claim cannot be empty.")

    started = perf_counter()

    pipeline = get_retrieval_pipeline()

    results = pipeline.retrieve(
        normalized_claim,
        top_k=top_k,
    )

    latency_ms = (perf_counter() - started) * 1000

    evidence = [
        EvidenceResponse(
            rank=result.rank,
            page_id=result.page_id,
            sentence_id=(result.sentence_id),
            text=clean_fever_text(result.text),
            page_rank=(result.page_rank),
            bm25_score=(result.bm25_score),
            dense_score=(result.dense_score),
            rrf_score=(result.rrf_score),
            cross_encoder_score=(result.cross_encoder_score),
        )
        for result in results
    ]

    return RetrievalResponse(
        claim=normalized_claim,
        requested_top_k=top_k,
        returned_evidence=len(evidence),
        latency_ms=latency_ms,
        evidence=evidence,
    )
