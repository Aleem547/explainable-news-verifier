import math
import re
import unicodedata
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

TOKEN_PATTERN = re.compile(r"\w+", re.UNICODE)


@dataclass(frozen=True)
class SentenceDocument:
    page_id: str
    sentence_id: int
    text: str


@dataclass(frozen=True)
class SentenceSearchResult:
    rank: int
    page_id: str
    sentence_id: int
    text: str
    score: float


def tokenize(value: str) -> list[str]:
    normalized = unicodedata.normalize(
        "NFKC",
        value,
    ).lower()

    return TOKEN_PATTERN.findall(normalized)


class BM25SentenceRanker:
    def __init__(
        self,
        *,
        k1: float = 1.5,
        b: float = 0.75,
    ) -> None:
        if k1 <= 0:
            raise ValueError("k1 must be greater than zero.")

        if not 0 <= b <= 1:
            raise ValueError("b must be between 0 and 1.")

        self.k1 = k1
        self.b = b

    def rank(
        self,
        query: str,
        documents: Sequence[SentenceDocument],
        *,
        limit: int = 50,
    ) -> list[SentenceSearchResult]:
        if limit <= 0:
            raise ValueError("limit must be greater than zero.")

        if not documents:
            return []

        query_tokens = tokenize(query)

        if not query_tokens:
            return []

        tokenized_documents = [tokenize(document.text) for document in documents]

        document_count = len(tokenized_documents)

        total_length = sum(len(tokens) for tokens in tokenized_documents)

        average_document_length = total_length / document_count if document_count else 0.0

        document_frequencies: Counter[str] = Counter()

        for tokens in tokenized_documents:
            document_frequencies.update(set(tokens))

        query_frequency = Counter(query_tokens)

        scored_documents: list[tuple[float, SentenceDocument]] = []

        for document, tokens in zip(
            documents,
            tokenized_documents,
            strict=True,
        ):
            term_frequencies = Counter(tokens)

            document_length = len(tokens)

            score = 0.0

            for term, query_count in query_frequency.items():
                term_frequency = term_frequencies.get(
                    term,
                    0,
                )

                if term_frequency == 0:
                    continue

                document_frequency = document_frequencies.get(
                    term,
                    0,
                )

                idf = math.log(
                    1.0 + (document_count - document_frequency + 0.5) / (document_frequency + 0.5)
                )

                if average_document_length > 0:
                    length_ratio = document_length / average_document_length
                else:
                    length_ratio = 0.0

                denominator = term_frequency + self.k1 * (1.0 - self.b + self.b * length_ratio)

                numerator = term_frequency * (self.k1 + 1.0)

                score += idf * numerator / denominator * query_count

            scored_documents.append(
                (
                    score,
                    document,
                )
            )

        scored_documents.sort(
            key=lambda item: (
                -item[0],
                item[1].page_id,
                item[1].sentence_id,
            )
        )

        results: list[SentenceSearchResult] = []

        for rank, (
            score,
            document,
        ) in enumerate(
            scored_documents[:limit],
            start=1,
        ):
            results.append(
                SentenceSearchResult(
                    rank=rank,
                    page_id=document.page_id,
                    sentence_id=(document.sentence_id),
                    text=document.text,
                    score=score,
                )
            )

        return results
