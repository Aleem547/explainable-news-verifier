"""BGE sentence ranking with optional bounded, per-model document embedding reuse."""

from collections import OrderedDict
from dataclasses import dataclass
from threading import Lock

import torch
from sentence_transformers import SentenceTransformer

from ml.retrieval.sparse.bm25_sentence_ranker import SentenceDocument

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
        document_cache_size: int = 0,
    ) -> None:
        if batch_size <= 0:
            raise ValueError("batch_size must be greater than zero.")
        if document_cache_size < 0:
            raise ValueError("document_cache_size must not be negative.")

        self.model_name = model_name
        self.batch_size = batch_size
        self.document_cache_size = document_cache_size
        # Separate per-instance cache: never mix embeddings from different models.
        self._document_cache: OrderedDict[tuple[str, int, str], torch.Tensor] = OrderedDict()
        self._cache_lock = Lock()
        self.model = SentenceTransformer(model_name, device=device)

    @property
    def device(self) -> str:
        return str(self.model.device)

    def clear_document_cache(self) -> None:
        """Discard in-memory embeddings, e.g. after updating model weights."""
        with self._cache_lock:
            self._document_cache.clear()

    def _encode_documents(self, documents: list[SentenceDocument]) -> torch.Tensor:
        if self.document_cache_size == 0:
            # Exact existing behavior when the opt-in cache is disabled.
            result: torch.Tensor = self.model.encode(
                [document.text for document in documents],
                batch_size=self.batch_size,
                convert_to_tensor=True,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
            return result

        keys = [(doc.page_id, doc.sentence_id, doc.text) for doc in documents]
        with self._cache_lock:
            resolved: dict[tuple[str, int, str], torch.Tensor] = {}
            misses: dict[tuple[str, int, str], str] = {}

            for key, doc in zip(keys, documents, strict=True):
                existing = self._document_cache.get(key)
                if existing is not None:
                    self._document_cache.move_to_end(key)
                    resolved[key] = existing
                elif key not in misses:
                    misses[key] = doc.text

            if misses:
                fresh: torch.Tensor = self.model.encode(
                    list(misses.values()),
                    batch_size=self.batch_size,
                    convert_to_tensor=True,
                    normalize_embeddings=True,
                    show_progress_bar=False,
                )
                if fresh.ndim != 2 or fresh.shape[0] != len(misses):
                    raise ValueError("BGE encoder returned an unexpected embedding shape.")

                for index, key in enumerate(misses):
                    vector = fresh[index].detach().clone()
                    resolved[key] = vector
                    self._document_cache[key] = vector
                    self._document_cache.move_to_end(key)
                    while len(self._document_cache) > self.document_cache_size:
                        self._document_cache.popitem(last=False)

            # "resolved" keeps all vectors for this call, even when the current
            # document batch contains more items than the cache's capacity.
            return torch.stack([resolved[key] for key in keys])

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
        document_embeddings = self._encode_documents(documents)
        scores: torch.Tensor = document_embeddings @ query_embedding

        result_limit = min(limit, len(documents))
        ranked_indices = torch.argsort(scores, descending=True)[:result_limit]
        results: list[DenseSentenceSearchResult] = []

        for rank, tensor_index in enumerate(ranked_indices, start=1):
            index = int(tensor_index.item())
            document = documents[index]
            results.append(
                DenseSentenceSearchResult(
                    rank=rank,
                    page_id=document.page_id,
                    sentence_id=document.sentence_id,
                    text=document.text,
                    score=float(scores[index].item()),
                )
            )
        return results
