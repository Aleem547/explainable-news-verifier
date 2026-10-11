"""BGE document-cache tests using a fake encoder; no model downloads."""

from __future__ import annotations

import pytest
import torch
import torch.nn.functional as F

from ml.retrieval.dense import bge_sentence_ranker as bge
from ml.retrieval.sparse.bm25_sentence_ranker import SentenceDocument


class FakeEncoder:
    def __init__(self, model_name: str, device: str | None = None) -> None:
        self.model_name = model_name
        self.device = device or "cpu"
        self.document_batches: list[list[str]] = []
        self.query_calls = 0

    def encode(
        self,
        texts: list[str],
        *,
        batch_size: int,
        convert_to_tensor: bool,
        normalize_embeddings: bool,
        show_progress_bar: bool,
    ) -> torch.Tensor:
        assert convert_to_tensor and normalize_embeddings and not show_progress_bar
        assert batch_size > 0
        if texts[0].startswith(bge.QUERY_INSTRUCTION):
            self.query_calls += 1
        else:
            self.document_batches.append(list(texts))
        vectors = torch.tensor(
            [
                [float(len(text)), float(sum(map(ord, text)) % 101), float(ord(text[0]))]
                for text in texts
            ],
            dtype=torch.float32,
        )
        return F.normalize(vectors, dim=1)


def doc(page: str, text: str, sentence: int = 0) -> SentenceDocument:
    return SentenceDocument(page_id=page, sentence_id=sentence, text=text)


@pytest.fixture
def factory(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(bge, "SentenceTransformer", FakeEncoder)
    return bge.BGESentenceRanker


def test_default_disabled_reencodes_every_time(factory) -> None:
    ranker = factory()
    docs = [doc("A", "Paris Eiffel Tower"), doc("B", "Berlin Germany")]
    ranker.rank("capital city", docs)
    ranker.rank("capital city", docs)
    assert len(ranker.model.document_batches) == 2
    assert ranker.model.query_calls == 2


def test_cache_reuses_documents_across_different_claims(factory) -> None:
    ranker = factory(document_cache_size=4)
    docs = [doc("A", "Paris Eiffel Tower"), doc("B", "Berlin Germany")]
    first = ranker.rank("tower in Paris", docs)
    second = ranker.rank("city in Germany", docs)
    assert len(ranker.model.document_batches) == 1
    assert ranker.model.query_calls == 2
    assert len(first) == len(second) == 2


def test_cache_preserves_ranking_and_scores(factory) -> None:
    docs = [doc("A", "Paris Eiffel Tower"), doc("B", "Berlin Germany")]
    disabled = factory()
    enabled = factory(document_cache_size=4)
    baseline = disabled.rank("famous tower", docs)
    enabled.rank("famous tower", docs)
    hit = enabled.rank("famous tower", docs)
    assert [(r.page_id, r.sentence_id, r.text) for r in hit] == [
        (r.page_id, r.sentence_id, r.text) for r in baseline
    ]
    for a, b in zip(baseline, hit, strict=True):
        assert a.score == pytest.approx(b.score, abs=1e-6)


def test_lru_evicts_oldest_entry(factory) -> None:
    ranker = factory(document_cache_size=2)
    a, b, c = doc("A", "Paris Eiffel Tower"), doc("B", "Berlin Germany"), doc("C", "Rome Italy")
    ranker.rank("tower", [a, b])
    ranker.rank("tower", [a])
    ranker.rank("tower", [c])
    ranker.rank("tower", [a, b])
    assert ranker.model.document_batches == [[a.text, b.text], [c.text], [b.text]]
    assert len(ranker._document_cache) <= 2


def test_text_change_invalidates_cached_document(factory) -> None:
    ranker = factory(document_cache_size=4)
    ranker.rank("tower", [doc("A", "Paris Eiffel Tower")])
    ranker.rank("tower", [doc("A", "Paris Eiffel Tower revised")])
    assert len(ranker.model.document_batches) == 2


def test_capacity_smaller_than_batch_still_returns_all(factory) -> None:
    ranker = factory(document_cache_size=1)
    docs = [doc("A", "Paris Eiffel Tower"), doc("B", "Berlin Germany"), doc("C", "Rome Italy")]
    assert len(ranker.rank("city", docs, limit=10)) == 3
    assert len(ranker._document_cache) == 1


def test_duplicate_documents_do_not_need_duplicate_encoding(factory) -> None:
    ranker = factory(document_cache_size=10)
    repeated = doc("A", "Paris Eiffel Tower")
    assert len(ranker.rank("city", [repeated, repeated])) == 2
    assert ranker.model.document_batches == [[repeated.text]]


def test_clear_cache_recomputes_embeddings(factory) -> None:
    ranker = factory(document_cache_size=4)
    ranker.rank("tower", [doc("A", "Paris Eiffel Tower")])
    ranker.clear_document_cache()
    ranker.rank("tower", [doc("A", "Paris Eiffel Tower")])
    assert len(ranker.model.document_batches) == 2


def test_rejects_negative_cache_size(factory) -> None:
    with pytest.raises(ValueError, match="document_cache_size"):
        factory(document_cache_size=-1)


def test_empty_documents_never_calls_model(factory) -> None:
    ranker = factory(document_cache_size=4)
    assert ranker.rank("tower", []) == []
    assert ranker.model.query_calls == 0


def test_cache_is_per_model_instance(factory) -> None:
    ranker1 = factory(document_cache_size=4)
    ranker2 = factory(document_cache_size=4)
    d = doc("A", "Paris Eiffel Tower")
    ranker1.rank("tower", [d])
    ranker2.rank("tower", [d])
    assert len(ranker1.model.document_batches) == 1
    assert len(ranker2.model.document_batches) == 1


def test_invalid_encoder_shape_is_rejected(factory) -> None:
    ranker = factory(document_cache_size=4)
    ranker.model.encode = lambda *args, **kwargs: torch.zeros(3)  # type: ignore[method-assign]
    with pytest.raises((IndexError, ValueError)):
        ranker.rank("tower", [doc("A", "Paris Eiffel Tower")])


def test_valid_cache_config(monkeypatch: pytest.MonkeyPatch) -> None:
    from ml.retrieval.factory import get_bge_cache_size

    monkeypatch.setenv("VERIFIER_BGE_DOCUMENT_CACHE_SIZE", "2048")
    assert get_bge_cache_size() == 2048
    monkeypatch.setenv("VERIFIER_BGE_DOCUMENT_CACHE_SIZE", "0")
    assert get_bge_cache_size() == 0
    monkeypatch.setenv("VERIFIER_BGE_DOCUMENT_CACHE_SIZE", "8192")
    assert get_bge_cache_size() == 8192


@pytest.mark.parametrize("value", ["-1", "not-a-number", "8193", "1.5", ""])
def test_invalid_cache_config(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    from ml.retrieval.factory import get_bge_cache_size

    monkeypatch.setenv("VERIFIER_BGE_DOCUMENT_CACHE_SIZE", value)
    with pytest.raises(ValueError, match="VERIFIER_BGE_DOCUMENT_CACHE_SIZE"):
        get_bge_cache_size()
