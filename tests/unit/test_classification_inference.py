import pytest
import torch

from ml.classification.inference import (
    logits_to_probabilities,
)
from ml.datasets.loaders.fever import (
    FeverLabel,
)


def test_logits_to_probabilities() -> None:
    result = logits_to_probabilities(
        torch.tensor(
            [
                5.0,
                1.0,
                0.0,
            ]
        )
    )

    assert result.label == FeverLabel.SUPPORTS

    assert result.label_id == 0

    assert result.confidence > 0.9

    assert sum(result.probabilities.values()) == pytest.approx(1.0)


def test_invalid_logits_shape() -> None:
    with pytest.raises(ValueError):
        logits_to_probabilities(
            torch.tensor(
                [
                    [
                        1.0,
                        2.0,
                        3.0,
                    ]
                ]
            )
        )
