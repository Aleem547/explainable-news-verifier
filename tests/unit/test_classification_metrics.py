from types import SimpleNamespace

import numpy as np

from ml.classification.metrics import (
    compute_classification_metrics,
)


def test_perfect_classification_metrics() -> None:
    prediction = SimpleNamespace(
        predictions=np.asarray(
            [
                [10.0, 0.0, 0.0],
                [0.0, 10.0, 0.0],
                [0.0, 0.0, 10.0],
            ]
        ),
        label_ids=np.asarray(
            [
                0,
                1,
                2,
            ]
        ),
    )

    metrics = compute_classification_metrics(prediction)

    assert metrics["accuracy"] == 1.0
    assert metrics["macro_f1"] == 1.0
