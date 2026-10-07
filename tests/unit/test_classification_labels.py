import pytest

from ml.classification.labels import (
    id_to_label,
    label_to_id,
)
from ml.datasets.loaders.fever import (
    FeverLabel,
)


def test_label_to_id() -> None:
    assert label_to_id(FeverLabel.SUPPORTS) == 0

    assert label_to_id(FeverLabel.REFUTES) == 1

    assert label_to_id(FeverLabel.NOT_ENOUGH_INFO) == 2


def test_id_to_label() -> None:
    assert id_to_label(0) == FeverLabel.SUPPORTS

    assert id_to_label(1) == FeverLabel.REFUTES

    assert id_to_label(2) == FeverLabel.NOT_ENOUGH_INFO


def test_invalid_label_id() -> None:
    with pytest.raises(ValueError):
        id_to_label(99)
