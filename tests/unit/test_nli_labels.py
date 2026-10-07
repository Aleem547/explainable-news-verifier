import pytest

from ml.verification.labels import (
    NliLabel,
    nli_id_to_label,
    nli_label_to_id,
)


def test_nli_label_to_id() -> None:
    assert nli_label_to_id(NliLabel.ENTAILMENT) == 0

    assert nli_label_to_id(NliLabel.CONTRADICTION) == 1

    assert nli_label_to_id(NliLabel.NEUTRAL) == 2


def test_nli_id_to_label() -> None:
    assert nli_id_to_label(0) == NliLabel.ENTAILMENT

    assert nli_id_to_label(1) == NliLabel.CONTRADICTION

    assert nli_id_to_label(2) == NliLabel.NEUTRAL


def test_invalid_nli_id() -> None:
    with pytest.raises(ValueError):
        nli_id_to_label(99)
