"""Conservative source-metadata and temporal context signals, never truth scores.

All times are explicit, timezone-aware instants. A time relation is descriptive,
not an entailment/refutation decision. Missing metadata remains UNKNOWN.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum


class TemporalRelation(StrEnum):
    BEFORE_REFERENCE = "BEFORE_REFERENCE"
    SAME_REFERENCE_DAY = "SAME_REFERENCE_DAY"
    AFTER_REFERENCE = "AFTER_REFERENCE"
    UNKNOWN = "UNKNOWN"


class FreshnessStatus(StrEnum):
    NOT_REQUESTED = "NOT_REQUESTED"
    UNKNOWN = "UNKNOWN"
    WITHIN_WINDOW = "WITHIN_WINDOW"
    OLDER_THAN_WINDOW = "OLDER_THAN_WINDOW"
    FUTURE_DATED = "FUTURE_DATED"


class SourceObservationMethod(StrEnum):
    PUBLISHER_PAGE = "PUBLISHER_PAGE"
    PROVIDER_METADATA = "PROVIDER_METADATA"
    MANUAL_RECORD = "MANUAL_RECORD"


@dataclass(frozen=True, slots=True)
class SourceProfileSignals:
    method: SourceObservationMethod
    observed_at: datetime
    publisher_name_reported: str | None = None
    homepage_url: str | None = None
    editorial_policy_url: str | None = None
    corrections_policy_url: str | None = None
    ownership_disclosure_url: str | None = None


@dataclass(frozen=True, slots=True)
class DocumentContext:
    temporal_relation: TemporalRelation
    freshness_status: FreshnessStatus
    metadata_flags: tuple[str, ...]
    warnings: tuple[str, ...]
    # Never a claim truth probability or source trust score.


def require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("All timestamps must be timezone-aware")


def assess_context(
    *,
    published_at: datetime | None,
    retrieved_at: datetime,
    assessed_at: datetime,
    reference_at: datetime | None = None,
    max_age_days: int | None = None,
    content_sha256: str,
    retrieval_observed: bool,
    profile: SourceProfileSignals | None = None,
) -> DocumentContext:
    """Describe metadata coverage and timeline without judging factual truth.

    `reference_at` must be supplied explicitly when a claim's time matters.
    `max_age_days` is a caller-defined heuristic, not an automatic truth rule.
    """
    for item in (retrieved_at, assessed_at, published_at, reference_at):
        if item is not None:
            require_aware(item)
    if max_age_days is not None and not 1 <= max_age_days <= 36500:
        raise ValueError("max_age_days must be between 1 and 36500")
    if not re.fullmatch(r"[0-9a-f]{64}", content_sha256):
        raise ValueError("Expected a lowercase SHA-256 content hash")
    if profile is not None:
        require_aware(profile.observed_at)
        if profile.observed_at > assessed_at:
            raise ValueError("Profile observed after assessment; cannot use future metadata")

    flags: list[str] = ["IMMUTABLE_CONTENT_HASH"]
    warnings: list[str] = []

    if retrieval_observed:
        flags.append("MATCHED_FETCH_OBSERVATION")
    else:
        warnings.append("FETCH_OBSERVATION_NOT_FOUND")

    if published_at is None:
        warnings.append("PUBLICATION_TIME_UNKNOWN")
    else:
        flags.append("PUBLICATION_TIME_RECORDED")
        if published_at > retrieved_at:
            warnings.append("PUBLICATION_AFTER_RETRIEVAL")
        if published_at > assessed_at:
            warnings.append("PUBLICATION_AFTER_ASSESSMENT")

    if profile is None:
        warnings.append("SOURCE_PROFILE_NOT_OBSERVED")
    else:
        flags.append("SOURCE_PROFILE_OBSERVED")
        flags.append(f"PROFILE_METHOD_{profile.method.value}")
        for value, flag in (
            (profile.publisher_name_reported, "PUBLISHER_NAME_REPORTED"),
            (profile.homepage_url, "HOMEPAGE_URL_RECORDED"),
            (profile.editorial_policy_url, "EDITORIAL_POLICY_URL_RECORDED"),
            (profile.corrections_policy_url, "CORRECTIONS_POLICY_URL_RECORDED"),
            (profile.ownership_disclosure_url, "OWNERSHIP_DISCLOSURE_URL_RECORDED"),
        ):
            if value:
                flags.append(flag)

    if published_at is None or reference_at is None:
        relation = TemporalRelation.UNKNOWN
    else:
        publication_day = published_at.astimezone(UTC).date()
        reference_day = reference_at.astimezone(UTC).date()
        if publication_day < reference_day:
            relation = TemporalRelation.BEFORE_REFERENCE
        elif publication_day > reference_day:
            relation = TemporalRelation.AFTER_REFERENCE
        else:
            relation = TemporalRelation.SAME_REFERENCE_DAY

    if max_age_days is None:
        freshness = FreshnessStatus.NOT_REQUESTED
    elif published_at is None:
        freshness = FreshnessStatus.UNKNOWN
    elif published_at > assessed_at:
        freshness = FreshnessStatus.FUTURE_DATED
    elif (assessed_at.astimezone(UTC) - published_at.astimezone(UTC)).days > max_age_days:
        freshness = FreshnessStatus.OLDER_THAN_WINDOW
    else:
        freshness = FreshnessStatus.WITHIN_WINDOW

    if relation == TemporalRelation.AFTER_REFERENCE:
        warnings.append("EVIDENCE_POSTDATES_REFERENCE_REVIEW_REQUIRED")
    if freshness == FreshnessStatus.OLDER_THAN_WINDOW:
        warnings.append("OUTSIDE_CALLER_FRESHNESS_WINDOW")
    if freshness == FreshnessStatus.FUTURE_DATED:
        warnings.append("FUTURE_DATED_METADATA_REVIEW_REQUIRED")

    return DocumentContext(
        temporal_relation=relation,
        freshness_status=freshness,
        metadata_flags=tuple(flags),
        warnings=tuple(warnings),
    )
