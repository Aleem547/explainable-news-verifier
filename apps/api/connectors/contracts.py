"""Provider-independent discovery records. Discovery is not verification."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class Provider(StrEnum):
    NEWSAPI = "newsapi"
    GOOGLE_FACTCHECK = "google_factcheck"


class ContentKind(StrEnum):
    NEWS_ARTICLE = "NEWS_ARTICLE"
    FACT_CHECK_REVIEW = "FACT_CHECK_REVIEW"


@dataclass(frozen=True, slots=True)
class DiscoveryRequest:
    query: str
    limit: int = 10
    language: str = "en"

    def __post_init__(self) -> None:
        if not self.query.strip() or len(self.query) > 300:
            raise ValueError("Query must contain between 1 and 300 characters.")
        if not 1 <= self.limit <= 20:
            raise ValueError("Limit must be between 1 and 20.")
        if len(self.language) != 2 or not self.language.isalpha():
            raise ValueError("Language must be a two-letter ISO 639-1 code.")


@dataclass(frozen=True, slots=True)
class ExternalDiscoveryHit:
    provider: Provider
    kind: ContentKind
    url: str
    publisher_domain: str
    publisher_name: str
    title: str
    snippet: str | None
    discovered_at: datetime
    published_at: datetime | None
    language: str | None = None
    matched_claim: str | None = None
    claimant: str | None = None
    rating_text: str | None = None
    claim_date: datetime | None = None

    def __post_init__(self) -> None:
        if self.discovered_at.tzinfo is None or self.discovered_at.utcoffset() is None:
            raise ValueError("Discovery timestamp must be timezone-aware.")
        for stamp in (self.published_at, self.claim_date):
            if stamp is not None and (stamp.tzinfo is None or stamp.utcoffset() is None):
                raise ValueError("Publication and claim timestamps must be timezone-aware.")


@dataclass(frozen=True, slots=True)
class DiscoveryResult:
    provider: Provider
    query: str
    hits: tuple[ExternalDiscoveryHit, ...]
    reported_total: int | None = None
    next_page_token: str | None = None
    warning: str = (
        "Provider discovery metadata is not article full text or verified evidence. "
        "Published fact-check ratings are third-party statements, not model verdicts."
    )
