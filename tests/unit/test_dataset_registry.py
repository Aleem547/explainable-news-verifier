import pytest

from ml.datasets.registry import (
    AVERITEC,
    FEVER,
    get_dataset,
    list_datasets,
)


def test_fever_is_registered() -> None:
    dataset = get_dataset("fever")

    assert dataset.name == "fever"
    assert dataset == FEVER


def test_averitec_is_registered() -> None:
    dataset = get_dataset("averitec")

    assert dataset.name == "averitec"
    assert dataset == AVERITEC


def test_registry_contains_expected_datasets() -> None:
    names = {dataset.name for dataset in list_datasets()}

    assert "fever" in names
    assert "averitec" in names


def test_unknown_dataset_raises_error() -> None:
    with pytest.raises(ValueError, match="Unknown dataset"):
        get_dataset("does-not-exist")
