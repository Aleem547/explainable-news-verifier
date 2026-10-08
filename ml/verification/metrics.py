from typing import Any

import numpy as np
from sklearn import metrics as sklearn_metrics  # type: ignore[import-untyped]


def compute_nli_metrics(
    evaluation_prediction: Any,
) -> dict[str, float]:
    logits = np.asarray(evaluation_prediction.predictions)

    labels = np.asarray(evaluation_prediction.label_ids)

    predictions = np.argmax(
        logits,
        axis=-1,
    )

    return {
        "accuracy": float(
            sklearn_metrics.accuracy_score(
                labels,
                predictions,
            )
        ),
        "macro_f1": float(
            sklearn_metrics.f1_score(
                labels,
                predictions,
                average="macro",
            )
        ),
        "weighted_f1": float(
            sklearn_metrics.f1_score(
                labels,
                predictions,
                average="weighted",
            )
        ),
        "macro_precision": float(
            sklearn_metrics.precision_score(
                labels,
                predictions,
                average="macro",
                zero_division=0,
            )
        ),
        "macro_recall": float(
            sklearn_metrics.recall_score(
                labels,
                predictions,
                average="macro",
                zero_division=0,
            )
        ),
    }
