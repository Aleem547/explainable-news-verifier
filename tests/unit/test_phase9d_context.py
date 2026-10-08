"""Offline tests for claim-independent temporal and provenance metadata signals."""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from ml.provenance.identity import sha256_text
from ml.verification.source_context import (
    FreshnessStatus,
    SourceObservationMethod,
    SourceProfileSignals,
    TemporalRelation,
    assess_context,
)

STAMP = datetime(2026, 5, 10, 12, tzinfo=UTC)
HASH = sha256_text("an immutable sample")


def evaluate(**overrides: object):  # type: ignore[no-untyped-def]
    arguments: dict[str, object] = {
        "published_at": STAMP - timedelta(days=40),
        "retrieved_at": STAMP - timedelta(hours=1),
        "assessed_at": STAMP,
        "reference_at": STAMP - timedelta(days=30),
        "max_age_days": 10,
        "content_sha256": HASH,
        "retrieval_observed": True,
    }
    arguments.update(overrides)
    return assess_context(**arguments)  # type: ignore[arg-type]


def test_evidence_before_reference_not_a_truth_verdict() -> None:
    outcome = evaluate()
    assert outcome.temporal_relation == TemporalRelation.BEFORE_REFERENCE
    assert outcome.freshness_status == FreshnessStatus.OLDER_THAN_WINDOW
    assert "OUTSIDE_CALLER_FRESHNESS_WINDOW" in outcome.warnings
    assert not hasattr(outcome, "truth_score")


def test_same_day_in_utc() -> None:
    outcome = evaluate(published_at=STAMP - timedelta(hours=1), reference_at=STAMP)
    assert outcome.temporal_relation == TemporalRelation.SAME_REFERENCE_DAY


def test_utc_normalizes_across_offsets() -> None:
    offset = timezone(timedelta(hours=-8))
    publication = datetime(2025, 2, 1, 20, tzinfo=offset)
    reference = datetime(2025, 2, 2, 10, tzinfo=UTC)
    outcome = evaluate(published_at=publication, reference_at=reference)
    assert outcome.temporal_relation == TemporalRelation.SAME_REFERENCE_DAY


def test_evidence_after_reference_is_review_not_refutation() -> None:
    outcome = evaluate(reference_at=STAMP - timedelta(days=100))
    assert outcome.temporal_relation == TemporalRelation.AFTER_REFERENCE
    assert "EVIDENCE_POSTDATES_REFERENCE_REVIEW_REQUIRED" in outcome.warnings


def test_unknown_publication_does_not_look_fresh() -> None:
    outcome = evaluate(published_at=None)
    assert outcome.temporal_relation == TemporalRelation.UNKNOWN
    assert outcome.freshness_status == FreshnessStatus.UNKNOWN
    assert "PUBLICATION_TIME_UNKNOWN" in outcome.warnings


def test_missing_reference_does_not_infer_claim_date() -> None:
    assert evaluate(reference_at=None).temporal_relation == TemporalRelation.UNKNOWN


def test_no_age_window_means_not_requested() -> None:
    assert evaluate(max_age_days=None).freshness_status == FreshnessStatus.NOT_REQUESTED


def test_fresh_within_explicit_window() -> None:
    assert evaluate(max_age_days=90).freshness_status == FreshnessStatus.WITHIN_WINDOW


def test_future_publication_is_flagged() -> None:
    result = evaluate(published_at=STAMP + timedelta(days=1))
    assert result.freshness_status == FreshnessStatus.FUTURE_DATED
    assert "PUBLICATION_AFTER_ASSESSMENT" in result.warnings
    assert "PUBLICATION_AFTER_RETRIEVAL" in result.warnings


def test_after_fetch_but_not_after_assessment() -> None:
    result = evaluate(published_at=STAMP - timedelta(minutes=2))
    assert "PUBLICATION_AFTER_RETRIEVAL" in result.warnings
    assert "PUBLICATION_AFTER_ASSESSMENT" not in result.warnings


def test_unobserved_fetch_is_explicit() -> None:
    result = evaluate(retrieval_observed=False)
    assert "FETCH_OBSERVATION_NOT_FOUND" in result.warnings


def test_absent_profile_is_unknown_not_low_trust() -> None:
    result = evaluate(profile=None)
    assert "SOURCE_PROFILE_NOT_OBSERVED" in result.warnings
    assert "SOURCE_PROFILE_OBSERVED" not in result.metadata_flags


def test_reported_profile_metadata_is_not_a_rating() -> None:
    profile = SourceProfileSignals(
        method=SourceObservationMethod.PUBLISHER_PAGE,
        observed_at=STAMP - timedelta(days=1),
        corrections_policy_url="https://example.org/corrections",
        publisher_name_reported="Example News",
    )
    result = evaluate(profile=profile)
    assert "CORRECTIONS_POLICY_URL_RECORDED" in result.metadata_flags
    assert "PUBLISHER_NAME_REPORTED" in result.metadata_flags
    assert not hasattr(result, "source_reliability")


def test_profile_observed_in_future_rejected() -> None:
    profile = SourceProfileSignals(
        method=SourceObservationMethod.MANUAL_RECORD,
        observed_at=STAMP + timedelta(days=1),
    )
    with pytest.raises(ValueError, match="future"):
        evaluate(profile=profile)


@pytest.mark.parametrize("field", ["published_at", "retrieved_at", "assessed_at", "reference_at"])
def test_naive_datetime_rejected(field: str) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        evaluate(**{field: datetime(2026, 1, 1)})


@pytest.mark.parametrize("max_age_days", [0, -3, 36501])
def test_bad_age_window_rejected(max_age_days: int) -> None:
    with pytest.raises(ValueError, match="max_age_days"):
        evaluate(max_age_days=max_age_days)


@pytest.mark.parametrize("hash_value", ["", "0" * 63, "G" * 64])
def test_bad_hash_rejected(hash_value: str) -> None:
    with pytest.raises(ValueError, match="SHA-256"):
        evaluate(content_sha256=hash_value)
