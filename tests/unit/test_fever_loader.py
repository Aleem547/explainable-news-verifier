import pytest

from ml.datasets.loaders.fever import (
    FeverLabel,
    parse_fever_record,
)


def test_parse_supporting_record() -> None:
    payload = {
        "id": 62037,
        "label": "SUPPORTS",
        "claim": "Oliver Reed was a film actor.",
        "evidence": [
            [
                [
                    1,
                    2,
                    "Oliver_Reed",
                    0,
                ]
            ]
        ],
    }

    record = parse_fever_record(payload)

    assert record.claim_id == 62037
    assert record.label == FeverLabel.SUPPORTS
    assert record.claim == "Oliver Reed was a film actor."

    assert len(record.evidence) == 1
    assert record.evidence[0][0].wiki_page == "Oliver_Reed"
    assert record.evidence[0][0].sentence_id == 0


def test_parse_not_enough_info_record() -> None:
    payload = {
        "id": 137637,
        "label": "NOT ENOUGH INFO",
        "claim": "Example claim.",
        "evidence": [
            [
                [
                    1,
                    2,
                    None,
                    None,
                ]
            ]
        ],
    }

    record = parse_fever_record(payload)

    assert record.label == FeverLabel.NOT_ENOUGH_INFO
    assert record.evidence[0][0].wiki_page is None
    assert record.evidence[0][0].sentence_id is None


def test_empty_claim_is_rejected() -> None:
    payload = {
        "id": 1,
        "label": "SUPPORTS",
        "claim": "   ",
        "evidence": [],
    }

    with pytest.raises(
        ValueError,
        match="claim cannot be empty",
    ):
        parse_fever_record(payload)


def test_invalid_evidence_shape_is_rejected() -> None:
    payload = {
        "id": 1,
        "label": "REFUTES",
        "claim": "Example claim.",
        "evidence": [
            [
                [
                    1,
                    2,
                    "Wikipedia_Page",
                ]
            ]
        ],
    }

    with pytest.raises(
        ValueError,
        match="exactly 4 values",
    ):
        parse_fever_record(payload)
