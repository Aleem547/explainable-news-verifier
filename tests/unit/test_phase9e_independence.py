"""Conservative source-family matching without declaring truth or independence."""

from dataclasses import replace
from uuid import UUID

import pytest

from ml.verification.source_independence import (
    Relationship,
    Snapshot,
    assess_source_independence,
    normalized_tokens,
)

FIRST = UUID(int=1)
SECOND = UUID(int=2)
THIRD = UUID(int=3)
S1 = UUID(int=51)
S2 = UUID(int=52)
S3 = UUID(int=53)
COMMON = (
    "A detailed original reporting record was issued on Monday and then carried by other outlets. "
    * 5
)
OTHER = (
    "A separate item published interviews and an original account from eyewitnesses and reporters. "
    * 5
)


def snapshot(version: UUID, publisher: UUID, text: str = COMMON) -> Snapshot:
    return Snapshot(version_id=version, source_id=publisher, text=text)


def test_identical_long_text_different_publishers_groups() -> None:
    result = assess_source_independence([snapshot(SECOND, S2), snapshot(FIRST, S1)])
    assert result.family_count == 1
    assert result.pairs[0].relationship == Relationship.IDENTICAL_TEXT
    assert result.pairs[0].basis == "identical_normalized_full_snapshot_text"


def test_same_publisher_is_conservatively_one_family() -> None:
    result = assess_source_independence([snapshot(FIRST, S1), snapshot(SECOND, S1, OTHER)])
    assert result.family_count == 1
    assert result.pairs[0].relationship == Relationship.SAME_PUBLISHER


def test_different_domains_not_independent_proof() -> None:
    result = assess_source_independence([snapshot(FIRST, S1, COMMON), snapshot(SECOND, S2, OTHER)])
    assert result.family_count == 2
    assert result.pairs[0].relationship == Relationship.UNDETERMINED
    assert "INDEPENDENCE_NOT_PROVEN" in result.warnings


def test_reordering_input_is_deterministic() -> None:
    a = snapshot(FIRST, S1)
    b = snapshot(SECOND, S2)
    c = snapshot(THIRD, S3, OTHER)
    assert assess_source_independence([a, b, c]) == assess_source_independence([c, b, a])


def test_identical_short_text_not_sufficient() -> None:
    result = assess_source_independence(
        [snapshot(FIRST, S1, "Wire report"), snapshot(SECOND, S2, "Wire report")]
    )
    assert result.family_count == 2
    assert result.pairs[0].relationship == Relationship.UNDETERMINED


def test_case_punctuation_normalization_for_exact_text() -> None:
    assert normalized_tokens("Paris, is NOT in Germany!") == ("paris", "is", "not", "in", "germany")
    variant = (
        "a detailed original reporting record was issued on monday "
        "and then carried by other outlets! " * 5
    )
    result = assess_source_independence(
        [snapshot(FIRST, S1, COMMON), snapshot(SECOND, S2, variant)]
    )
    assert result.pairs[0].relationship == Relationship.IDENTICAL_TEXT


def test_negation_remains_distinguishing() -> None:
    assert normalized_tokens("The claim is true") != normalized_tokens("The claim is not true")


def test_near_duplicate_requires_review_not_merge() -> None:
    base = " ".join(f"term{i}" for i in range(110))
    edited = base.replace("term60", "revised")
    result = assess_source_independence([snapshot(FIRST, S1, base), snapshot(SECOND, S2, edited)])
    assert result.pairs[0].relationship == Relationship.POSSIBLE_TEXT_REUSE
    assert result.pairs[0].group_together is False
    assert result.family_count == 2
    assert "POSSIBLE_SYNDICATION_REQUIRES_REVIEW" in result.warnings


def test_near_nonmatching_long_text_remains_unknown() -> None:
    base = " ".join(f"foo{i}" for i in range(90))
    other = " ".join(f"bar{i}" for i in range(90))
    result = assess_source_independence([snapshot(FIRST, S1, base), snapshot(SECOND, S2, other)])
    assert result.pairs[0].relationship == Relationship.UNDETERMINED
    assert result.pairs[0].shared_5gram_jaccard == 0.0


def test_same_text_but_not_corroboration_count() -> None:
    result = assess_source_independence(
        [snapshot(FIRST, S1), snapshot(SECOND, S2), snapshot(THIRD, S3)]
    )
    assert result.family_count == 1
    assert len(result.pairs) == 3
    assert "NO_CLAIM_TRUTH_INFERENCE" in result.warnings


def test_transitive_grouping() -> None:
    result = assess_source_independence(
        [
            snapshot(FIRST, S1, COMMON),
            snapshot(SECOND, S2, COMMON),
            snapshot(THIRD, S2, OTHER),
        ]
    )
    assert result.family_count == 1


@pytest.mark.parametrize("count", [0, 1, 51])
def test_invalid_count(count: int) -> None:
    items = [snapshot(UUID(int=i + 1), UUID(int=i + 101)) for i in range(count)]
    with pytest.raises(ValueError, match="between 2 and 50"):
        assess_source_independence(items)


def test_duplicate_version_rejected() -> None:
    with pytest.raises(ValueError, match="unique"):
        assess_source_independence([snapshot(FIRST, S1), snapshot(FIRST, S2)])


@pytest.mark.parametrize("text", ["", "  ", "\n"])
def test_blank_article_rejected(text: str) -> None:
    with pytest.raises(ValueError, match="Full snapshot"):
        assess_source_independence([snapshot(FIRST, S1, text), snapshot(SECOND, S2)])


def test_different_source_and_same_text_uses_content_rule() -> None:
    original = snapshot(FIRST, S1)
    copied = replace(original, version_id=SECOND, source_id=S2)
    result = assess_source_independence([original, copied])
    assert result.pairs[0].relationship == Relationship.IDENTICAL_TEXT


def test_excessive_text_and_punctuation_not_false_independence() -> None:
    first = snapshot(FIRST, S1, "An event was not confirmed by the agency. " * 10)
    second = snapshot(SECOND, S2, "An event was confirmed by the agency. " * 10)
    result = assess_source_independence([first, second])
    assert result.pairs[0].relationship != Relationship.IDENTICAL_TEXT


def test_three_different_texts_three_families() -> None:
    result = assess_source_independence(
        [
            snapshot(FIRST, S1, COMMON),
            snapshot(SECOND, S2, OTHER),
            snapshot(
                THIRD, S3, "An unrelated documented primary source described a different case. " * 7
            ),
        ]
    )
    assert result.family_count == 3


def test_unverified_origins_do_not_automatically_merge() -> None:
    result = assess_source_independence([snapshot(FIRST, S1, COMMON), snapshot(SECOND, S2, OTHER)])
    assert all(f.relationship != Relationship.DECLARED_COMMON_ORIGIN for f in result.pairs)


def test_matching_reported_origin_grouped_but_not_independence_proof() -> None:
    common_origin = "https://original.example.com/story"
    rows = [
        replace(
            snapshot(FIRST, S1, COMMON),
            reported_origin_url=common_origin,
            origin_observation_url="https://first.example.com/source-disclosure",
        ),
        replace(
            snapshot(SECOND, S2, OTHER),
            reported_origin_url=common_origin,
            origin_observation_url="https://second.example.com/source-disclosure",
        ),
    ]
    result = assess_source_independence(rows)
    assert result.pairs[0].relationship == Relationship.DECLARED_COMMON_ORIGIN
    assert result.family_count == 1
    assert "ORIGIN_ATTRIBUTION_NOT_INDEPENDENTLY_VERIFIED" in result.warnings


def test_missing_origin_observation_rejected() -> None:
    with pytest.raises(ValueError, match="observation URL"):
        assess_source_independence(
            [
                replace(
                    snapshot(FIRST, S1), reported_origin_url="https://agency.example.net/article"
                ),
                snapshot(SECOND, S2, OTHER),
            ]
        )
