"""Phase 13E.4: bounded, offline extraction of literal factual-claim *candidates*.

Rules are deliberately conservative heuristics, NOT an NLP fact-checker. Text is
never paraphrased, publisher claims never become verified, and source offsets
always point into the exact immutable prepared article text. This module makes
no HTTP, database, model or filesystem calls.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

from apps.api.services.article_extraction import ExtractedArticle
from apps.api.services.article_url_preparation import PreparedArticleUrl
from apps.api.services.pasted_article_preparation import (
    PreparedPastedArticle,
    validate_prepared_pasted_article,
)
from ml.provenance.identity import canonical_public_url, normalize_source_domain

POLICY_VERSION = "phase13e4-literal-claim-candidates-v1"
_TOKEN = re.compile(r"\b[\w]+(?:['’][\w]+)?\b", re.UNICODE)
_NUMERIC = re.compile(r"\b\d+(?:[.,]\d+)*\b")
_NAMED = re.compile(r"\b(?:[A-Z][a-z]{2,}|[A-Z]{2,})\b")
_WORDS = frozenset({
    "is", "are", "was", "were", "has", "have", "had", "will", "contains",
    "consists", "includes", "located", "recorded", "measured", "published",
    "released", "announced", "confirmed", "reported", "said", "stated",
    "launched", "signed", "approved", "rejected", "reached", "grew", "fell",
    "rose", "increased", "decreased", "opened", "closed", "began", "ended",
    "won", "lost", "started", "completed", "founded", "built", "developed",
    "issued", "operates", "operated", "serves", "served", "discovered",
    "identified", "found", "tested", "collected", "received", "cost",
    "costs", "sued", "voted", "elected", "died", "occurred", "took",
    "joined", "left", "created", "produced", "made", "located", "covers",
    "covered", "supplied", "shipped", "transferred", "funded", "purchased",
})
_OPINION = re.compile(
    r"\b(?:i think|i believe|in my opinion|in my view|we should|you should|"
    r"must surely|probably|perhaps|possibly|might|could|may be|seems to|"
    r"appears to|best ever|worst ever|amazing|wonderful|terrible)\b",
    re.IGNORECASE,
)
_ATTRIBUTION = re.compile(r"\b(?:said|stated|claimed|reported|according to)\b", re.IGNORECASE)
_DEICTIC = re.compile(r"^(?:it|this|that|these|those|they|he|she|we|i|you)\b", re.IGNORECASE)
_ABBREVIATIONS = frozenset({
    "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "vs", "etc", "inc",
    "ltd", "corp", "co", "approx", "fig", "no", "jan", "feb", "mar",
    "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec",
    "u.s", "u.k", "e.g", "i.e",
})


class ClaimCandidateExtractionError(ValueError):
    """Stable reason code without echoing confidential article text."""


@dataclass(frozen=True, slots=True)
class ClaimCandidatePolicy:
    max_article_chars: int = 500_000
    max_sentences_scanned: int = 3000
    max_claims: int = 20
    min_sentence_chars: int = 30
    max_sentence_chars: int = 500

    def __post_init__(self) -> None:
        values = (self.max_article_chars, self.max_sentences_scanned,
                  self.max_claims, self.min_sentence_chars, self.max_sentence_chars)
        if any(type(v) is not int for v in values):
            raise ValueError("invalid_claim_candidate_policy")
        if (not 100 <= self.max_article_chars <= 500_000
                or not 1 <= self.max_sentences_scanned <= 10_000
                or not 1 <= self.max_claims <= 50
                or not 10 <= self.min_sentence_chars <= self.max_sentence_chars <= 1000):
            raise ValueError("invalid_claim_candidate_policy")


@dataclass(frozen=True, slots=True)
class ClaimCandidate:
    candidate_id: str
    literal_text: str
    start_char: int                 # Python Unicode-character offset, not byte offset
    end_char: int                   # exclusive; article.text[start:end] == literal_text
    paragraph_index: int
    normalized_fingerprint: str
    duplicate_locations: tuple[tuple[int, int], ...]
    has_reporting_attribution: bool
    status: str = "UNVERIFIED_CANDIDATE"
    eligible_as_independent_evidence: bool = False


@dataclass(frozen=True, slots=True)
class ClaimCandidateReport:
    source_kind: str
    source_text_sha256: str
    source_url: str | None
    publisher_domain: str | None
    source_timestamp: datetime
    candidates: tuple[ClaimCandidate, ...]
    sentences_scanned: int
    omitted_for_limit: int
    filtered_reasons: tuple[tuple[str, int], ...]
    policy_version: str = POLICY_VERSION
    independently_verified: bool = False
    independent_corroboration_established: bool = False
    eligible_as_independent_evidence: bool = False


def _source_info(
    prepared: PreparedPastedArticle | PreparedArticleUrl,
) -> tuple[str, str, str, str | None, str | None, datetime]:
    if isinstance(prepared, PreparedPastedArticle):
        try:
            validate_prepared_pasted_article(prepared)
        except (ValueError, TypeError) as exc:
            raise ClaimCandidateExtractionError("invalid_pasted_article_provenance") from exc
        return (prepared.text, prepared.text_sha256, "USER_SUPPLIED_ONLY", None,
                None, prepared.received_at)
    if isinstance(prepared, PreparedArticleUrl):
        item = prepared.article
        if (not isinstance(item, ExtractedArticle) or not isinstance(item.text, str)
                or not 1 <= len(item.text) <= 500_000):
            raise ClaimCandidateExtractionError("invalid_fetched_article_provenance")
        try:
            actual_digest = hashlib.sha256(item.text.encode("utf-8")).hexdigest()
        except UnicodeError as exc:
            raise ClaimCandidateExtractionError("invalid_fetched_article_provenance") from exc
        try:
            parsed = urlsplit(prepared.canonical_url)
            safe_identity = (
                isinstance(prepared.canonical_url, str)
                and prepared.canonical_url == canonical_public_url(prepared.canonical_url)
                and parsed.scheme == "https"
                and parsed.port in (None, 443)
                and parsed.hostname == normalize_source_domain(prepared.publisher_domain)
            )
        except (ValueError, UnicodeError, TypeError, AttributeError):
            safe_identity = False
        if (not safe_identity
                or prepared.state != "READY_FOR_CLAIM_EXTRACTION"
                or prepared.independently_verified is not False
                or item.independently_verified is not False
                or not isinstance(item.text_sha256, str)
                or item.text_sha256 != actual_digest
                or not item.text.strip() or item.text != item.text.strip()
                or item.document_url != prepared.canonical_url
                or not isinstance(prepared.publisher_domain, str)
                or prepared.publisher_domain != item.publisher_domain
                or not isinstance(prepared.publisher_name, str)
                or prepared.publisher_name != item.publisher_name
                or item.content_type != "text/html"
                or not isinstance(item.html_sha256, str)
                or re.fullmatch(r"[0-9a-f]{64}", item.html_sha256) is None
                or any(unicodedata.category(ch) in {"Cf", "Cs"} for ch in item.text)
                or not isinstance(item.retrieved_at, datetime)
                or item.retrieved_at.tzinfo is None
                or item.retrieved_at.utcoffset() is None
                or item.retrieved_at > datetime.now(UTC) + timedelta(minutes=5)):
            raise ClaimCandidateExtractionError("invalid_fetched_article_provenance")
        return (item.text, item.text_sha256, "FETCHED_ARTICLE_UNVERIFIED",
                prepared.canonical_url, prepared.publisher_domain, item.retrieved_at)
    raise ClaimCandidateExtractionError("unsupported_prepared_article_type")


def _is_boundary(line: str, dot_index: int) -> tuple[bool, int]:
    """Return boundary and end index, retaining closing quotes with the sentence."""
    ch = line[dot_index]
    if ch not in ".?!":
        return False, dot_index + 1
    end = dot_index + 1
    while end < len(line) and line[end] in '\"\'”’)]}':
        end += 1
    if end < len(line) and not line[end].isspace():
        return False, end
    if ch == ".":
        if dot_index and dot_index + 1 < len(line) and line[dot_index - 1].isdigit() and line[dot_index + 1].isdigit():
            return False, end
        prefix = line[:dot_index]
        match = re.search(r"([\w.]+)$", prefix)
        token = match.group(1).casefold() if match else ""
        if token in _ABBREVIATIONS or (len(token) == 1 and token.isalpha()):
            return False, end
        # A trailing period is fine, but not one of the first dots in an ellipsis.
        if line[dot_index + 1: dot_index + 2] == ".":
            return False, end
    return True, end


def _iter_sentence_spans(text: str, *, max_sentences: int):
    count = 0
    paragraph_index = -1
    # A physical line is a paragraph boundary; pasted articles preserve blank
    # lines while extracted HTML may provide a line per paragraph.
    for line_match in re.finditer(r"[^\n]+", text):
        raw = line_match.group(0)
        if not raw.strip():
            continue
        paragraph_index += 1
        start = 0
        i = 0
        while i < len(raw):
            boundary, end = _is_boundary(raw, i)
            if boundary:
                if (span := raw[start:end]).strip():
                    left = len(span) - len(span.lstrip())
                    right = len(span.rstrip())
                    count += 1
                    if count > max_sentences:
                        raise ClaimCandidateExtractionError("too_many_article_sentences")
                    yield (line_match.start() + start + left,
                           line_match.start() + start + right, paragraph_index)
                start = end
                i = end
                continue
            i = max(i + 1, end)
        if raw[start:].strip():
            tail = raw[start:]
            left = len(tail) - len(tail.lstrip())
            right = len(tail.rstrip())
            count += 1
            if count > max_sentences:
                raise ClaimCandidateExtractionError("too_many_article_sentences")
            yield (line_match.start() + start + left,
                   line_match.start() + start + right, paragraph_index)


def _filter(text: str, settings: ClaimCandidatePolicy) -> str | None:
    if not settings.min_sentence_chars <= len(text) <= settings.max_sentence_chars:
        return "outside_sentence_length"
    if text.endswith("?") or text.endswith("!") or text.endswith("?”"):
        return "non_assertive_punctuation"
    if _DEICTIC.search(text):
        return "context_dependent_opening"
    if _OPINION.search(text):
        return "speculative_or_subjective"
    words = _TOKEN.findall(text)
    if len(words) < 6:
        return "too_few_words"
    if not any(w.casefold() in _WORDS for w in words):
        return "no_recognized_assertion"
    # A capitalized first word alone is not a named entity. Avoid silently
    # inventing an antecedent for context-dependent generic statements.
    if not _NUMERIC.search(text) and not _NAMED.search(text[len(words[0]):]):
        return "no_explicit_name_or_number"
    return None


def _dedup_fingerprint(text: str) -> str:
    # Exact lexical identity (punctuation/whitespace/case differences ignored),
    # not semantic equivalence; negation and changed numbers are retained.
    words = _TOKEN.findall(unicodedata.normalize("NFC", text).casefold())
    return hashlib.sha256(" ".join(words).encode("utf-8")).hexdigest()


def extract_article_claim_candidates(
    *,
    prepared: PreparedPastedArticle | PreparedArticleUrl,
    policy: ClaimCandidatePolicy | None = None,
) -> ClaimCandidateReport:
    """Produce literal, in-order, unverified candidates with auditable offsets.

    Caller must supply an object returned by an upstream trusted preparation
    service. PreparedArticleUrl metadata MUST NOT be assembled from client input.
    Do not treat these heuristics as recall/precision validated claim detection.
    """
    settings = policy or ClaimCandidatePolicy()
    if not isinstance(settings, ClaimCandidatePolicy):
        raise ClaimCandidateExtractionError("invalid_claim_candidate_policy")
    text, digest, source_kind, url, domain, timestamp = _source_info(prepared)
    if (not isinstance(text, str) or not text
            or len(text) > settings.max_article_chars
            or len(text.encode("utf-8")) > 2_000_000):
        raise ClaimCandidateExtractionError("article_text_outside_limit")
    reasons: Counter[str] = Counter()
    counts = 0
    keys: dict[str, int] = {}
    first: list[tuple[str, int, int, int, str, bool]] = []
    repeats: list[list[tuple[int, int]]] = []
    omitted = 0
    for start, end, para in _iter_sentence_spans(
        text, max_sentences=settings.max_sentences_scanned,
    ):
        counts += 1
        literal = text[start:end]
        why = _filter(literal, settings)
        if why:
            reasons[why] += 1
            continue
        normalized_hash = _dedup_fingerprint(literal)
        if normalized_hash in keys:
            repeats[keys[normalized_hash]].append((start, end))
            reasons["duplicate_candidate"] += 1
            continue
        if len(first) >= settings.max_claims:
            omitted += 1
            continue
        keys[normalized_hash] = len(first)
        first.append((literal, start, end, para, normalized_hash,
                      bool(_ATTRIBUTION.search(literal))))
        repeats.append([])
    candidates = tuple(
        ClaimCandidate(
            candidate_id=hashlib.sha256(
                f"{digest}:{start}:{end}:{literal}".encode("utf-8")
            ).hexdigest(),
            literal_text=literal, start_char=start, end_char=end,
            paragraph_index=para, normalized_fingerprint=fingerprint,
            duplicate_locations=tuple(repeats[i]),
            has_reporting_attribution=attributed,
        )
        for i, (literal, start, end, para, fingerprint, attributed) in enumerate(first)
    )
    return ClaimCandidateReport(
        source_kind=source_kind, source_text_sha256=digest,
        source_url=url, publisher_domain=domain, source_timestamp=timestamp,
        candidates=candidates, sentences_scanned=counts, omitted_for_limit=omitted,
        filtered_reasons=tuple(sorted(reasons.items())),
    )
