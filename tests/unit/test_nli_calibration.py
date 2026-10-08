import numpy as np
import pytest

from ml.verification.calibration import (
    calibration_report,
    fit_temperature,
    probabilities_from_logits,
    stratified_calibration_split,
)


def test_probabilities_sum_to_one() -> None:
    logits = np.array(
        [
            [2.0, 1.0, 0.0],
            [0.0, 3.0, 1.0],
        ]
    )

    probabilities = probabilities_from_logits(logits, 1.5)

    np.testing.assert_allclose(
        probabilities.sum(axis=1),
        np.ones(2),
    )


def test_temperature_preserves_prediction_order() -> None:
    logits = np.array(
        [
            [4.0, 1.0, 2.0],
            [1.0, 5.0, 2.0],
            [1.0, 2.0, 6.0],
        ]
    )

    original = probabilities_from_logits(logits, 1.0)
    calibrated = probabilities_from_logits(logits, 2.0)

    assert np.array_equal(
        original.argmax(axis=1),
        calibrated.argmax(axis=1),
    )


def test_temperature_fit_reduces_overconfidence() -> None:
    logits = np.array(
        [
            [8.0, 0.0, 0.0],
            [8.0, 0.0, 0.0],
            [0.0, 8.0, 0.0],
            [0.0, 0.0, 8.0],
        ]
    )

    labels = np.array([0, 1, 1, 2])

    temperature = fit_temperature(logits, labels)

    assert temperature > 1.0

    before = calibration_report(logits, labels, temperature=1.0)

    after = calibration_report(logits, labels, temperature=temperature)

    assert after["nll"] < before["nll"]


def test_stratified_split_has_no_overlap() -> None:
    labels = np.repeat(np.arange(3), 20)

    calibration_ids, diagnostic_ids = stratified_calibration_split(
        labels,
        seed=42,
    )

    assert len(calibration_ids) == 30
    assert len(diagnostic_ids) == 30

    assert len(np.intersect1d(calibration_ids, diagnostic_ids)) == 0

    for label_id in (0, 1, 2):
        assert np.sum(labels[calibration_ids] == label_id) == 10
        assert np.sum(labels[diagnostic_ids] == label_id) == 10


def test_invalid_temperature_is_rejected() -> None:
    with pytest.raises(ValueError):
        probabilities_from_logits(
            np.array([[1.0, 2.0, 3.0]]),
            temperature=0.0,
        )
