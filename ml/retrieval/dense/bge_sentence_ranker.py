from dataclasses import dataclass

import torch
from sentence_transformers import SentenceTransformer

from ml.retrieval.sparse.bm25_sentence_ranker import (
    SentenceDocument,
)

DEFAULT_MODEL_NAME = "BAAI/bge-small-en-v1.5"

QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "


@dataclass(frozen=True)
class DenseSentenceSearchResult:
    rank: int
    page_id: str
    sentence_id: int
    text: str
    score: float


def prepare_query(query: str) -> str:
    query = query.strip()

    if not query:
        return ""

    return QUERY_INSTRUCTION + query


class BGESentenceRanker:
    def __init__(
        self,
        *,
        model_name: str = DEFAULT_MODEL_NAME,
        device: str | None = None,
        batch_size: int = 32,
    ) -> None:
        if batch_size <= 0:
            raise ValueError("batch_size must be greater than zero.")

        self.model_name = model_name
        self.batch_size = batch_size

        self.model = SentenceTransformer(
            model_name,
            device=device,
        )

    @property
    def device(self) -> str:
        return str(self.model.device)

    def rank(
        self,
        query: str,
        documents: list[SentenceDocument],
        *,
        limit: int = 50,
    ) -> list[DenseSentenceSearchResult]:
        if limit <= 0:
            raise ValueError("limit must be greater than zero.")

        if not documents:
            return []

        prepared_query = prepare_query(query)

        if not prepared_query:
            return []

        query_embedding = self.model.encode(
            [prepared_query],
            batch_size=1,
            convert_to_tensor=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )[0]

        document_embeddings = self.model.encode(
            [document.text for document in documents],
            batch_size=self.batch_size,
            convert_to_tensor=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )

        scores: torch.Tensor = document_embeddings @ query_embedding

        result_limit = min(
            limit,
            len(documents),
        )

        ranked_indices = torch.argsort(
            scores,
            descending=True,
        )[:result_limit]

        results: list[DenseSentenceSearchResult] = []

        for rank, tensor_index in enumerate(
            ranked_indices,
            start=1,
        ):
            index = int(tensor_index.item())

            document = documents[index]

            results.append(
                DenseSentenceSearchResult(
                    rank=rank,
                    page_id=document.page_id,
                    sentence_id=(document.sentence_id),
                    text=document.text,
                    score=float(scores[index].item()),
                )
            )

        return results
