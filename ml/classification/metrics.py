from typing import Any

import numpy as np
from sklearn import metrics as sklearn_metrics  # type: ignore[import-untyped]


def compute_classification_metrics(
    evaluation_prediction: Any,
) -> dict[str, float]:
    logits = np.asarray(evaluation_prediction.predictions)

    labels = np.asarray(evaluation_prediction.label_ids)

    predictions = np.argmax(
        logits,
        axis=-1,
    )

    accuracy = sklearn_metrics.accuracy_score(
        labels,
        predictions,
    )

    macro_f1 = sklearn_metrics.f1_score(
        labels,
        predictions,
        average="macro",
    )

    weighted_f1 = sklearn_metrics.f1_score(
        labels,
        predictions,
        average="weighted",
    )

    macro_precision = sklearn_metrics.precision_score(
        labels,
        predictions,
        average="macro",
        zero_division=0,
    )

    macro_recall = sklearn_metrics.recall_score(
        labels,
        predictions,
        average="macro",
        zero_division=0,
    )

    return {
        "accuracy": float(accuracy),
        "macro_f1": float(macro_f1),
        "weighted_f1": float(weighted_f1),
        "macro_precision": float(macro_precision),
        "macro_recall": float(macro_recall),
    }
