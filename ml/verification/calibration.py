import numpy as np
from sklearn.metrics import f1_score  # type: ignore[import-untyped]


def validate_inputs(
    logits: np.ndarray,
    labels: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    scores = np.asarray(logits, dtype=np.float64)
    targets = np.asarray(labels, dtype=np.int64)

    if scores.ndim != 2 or scores.shape[1] != 3:
        raise ValueError("Expected logits with shape (N, 3).")

    if targets.ndim != 1 or len(targets) != len(scores):
        raise ValueError("Labels must match the logit rows.")

    if len(targets) == 0:
        raise ValueError("Dataset cannot be empty.")

    if not np.isfinite(scores).all():
        raise ValueError("Logits contain invalid values.")

    if np.any((targets < 0) | (targets > 2)):
        raise ValueError("NLI labels must be 0, 1 or 2.")

    return scores, targets


def probabilities_from_logits(
    logits: np.ndarray,
    temperature: float = 1.0,
) -> np.ndarray:
    if not np.isfinite(temperature) or temperature <= 0:
        raise ValueError("Temperature must be positive and finite.")

    scores = np.asarray(logits, dtype=np.float64)

    if scores.ndim != 2 or scores.shape[1] != 3:
        raise ValueError("Expected three NLI logits per example.")

    if not np.isfinite(scores).all():
        raise ValueError("Logits contain invalid values.")

    scaled = scores / temperature
    scaled -= np.max(scaled, axis=1, keepdims=True)

    exponentials = np.exp(scaled)

    return exponentials / exponentials.sum(axis=1, keepdims=True)


def negative_log_likelihood(
    probabilities: np.ndarray,
    labels: np.ndarray,
) -> float:
    indices = np.arange(len(labels))

    selected = probabilities[indices, labels]
    selected = np.clip(selected, 1e-15, 1.0)

    return float(-np.mean(np.log(selected)))


def expected_calibration_error(
    probabilities: np.ndarray,
    labels: np.ndarray,
    *,
    bins: int = 15,
) -> float:
    if bins <= 0:
        raise ValueError("Number of bins must be positive.")

    confidence = np.max(probabilities, axis=1)
    predictions = np.argmax(probabilities, axis=1)
    correctness = (predictions == labels).astype(np.float64)

    bin_ids = np.minimum(
        (confidence * bins).astype(np.int64),
        bins - 1,
    )

    ece = 0.0

    for bin_id in range(bins):
        mask = bin_ids == bin_id

        if not np.any(mask):
            continue

        bin_accuracy = float(np.mean(correctness[mask]))
        bin_confidence = float(np.mean(confidence[mask]))
        bin_weight = float(np.mean(mask))

        ece += bin_weight * abs(bin_accuracy - bin_confidence)

    return float(ece)


def multiclass_brier_score(
    probabilities: np.ndarray,
    labels: np.ndarray,
) -> float:
    targets = np.eye(3, dtype=np.float64)[labels]

    return float(np.mean(np.sum((probabilities - targets) ** 2, axis=1)))


def fit_temperature(
    logits: np.ndarray,
    labels: np.ndarray,
) -> float:
    scores, targets = validate_inputs(logits, labels)

    def objective(log_temperature: float) -> float:
        temperature = float(np.exp(log_temperature))

        probabilities = probabilities_from_logits(
            scores,
            temperature,
        )

        return negative_log_likelihood(probabilities, targets)

    # Golden-section search in log-temperature space.
    # Temperature is constrained to [0.05, 10.0].
    left = float(np.log(0.05))
    right = float(np.log(10.0))
    ratio = (np.sqrt(5.0) - 1.0) / 2.0

    first = right - ratio * (right - left)
    second = left + ratio * (right - left)

    for _ in range(100):
        if objective(first) < objective(second):
            right = second
        else:
            left = first

        first = right - ratio * (right - left)
        second = left + ratio * (right - left)

    candidates = [
        float(np.log(0.05)),
        float((left + right) / 2.0),
        float(np.log(10.0)),
    ]

    best = min(candidates, key=objective)

    return float(np.exp(best))


def stratified_calibration_split(
    labels: np.ndarray,
    *,
    seed: int = 42,
) -> tuple[np.ndarray, np.ndarray]:
    targets = np.asarray(labels, dtype=np.int64)
    generator = np.random.default_rng(seed)

    calibration_indices: list[int] = []
    diagnostic_indices: list[int] = []

    for label_id in (0, 1, 2):
        indices = np.flatnonzero(targets == label_id)

        if len(indices) < 2:
            raise ValueError(f"Not enough examples for NLI label {label_id}.")

        generator.shuffle(indices)
        midpoint = len(indices) // 2

        calibration_indices.extend(indices[:midpoint].tolist())
        diagnostic_indices.extend(indices[midpoint:].tolist())

    return (
        np.asarray(sorted(calibration_indices), dtype=np.int64),
        np.asarray(sorted(diagnostic_indices), dtype=np.int64),
    )


def calibration_report(
    logits: np.ndarray,
    labels: np.ndarray,
    *,
    temperature: float,
) -> dict[str, object]:
    scores, targets = validate_inputs(logits, labels)

    probabilities = probabilities_from_logits(
        scores,
        temperature,
    )

    predictions = np.argmax(probabilities, axis=1)
    confidence = np.max(probabilities, axis=1)

    thresholds = (0.5, 0.7, 0.8, 0.9, 0.95)

    selective_results: list[dict[str, float | int | None]] = []

    for threshold in thresholds:
        accepted = confidence >= threshold
        accepted_count = int(np.sum(accepted))

        accepted_accuracy = (
            float(np.mean(predictions[accepted] == targets[accepted]))
            if accepted_count > 0
            else None
        )

        selective_results.append(
            {
                "threshold": threshold,
                "accepted": accepted_count,
                "coverage": float(np.mean(accepted)),
                "accepted_accuracy": accepted_accuracy,
            }
        )

    return {
        "examples": len(targets),
        "temperature": temperature,
        "accuracy": float(np.mean(predictions == targets)),
        "macro_f1": float(
            f1_score(
                targets,
                predictions,
                labels=[0, 1, 2],
                average="macro",
                zero_division=0,
            )
        ),
        "nll": negative_log_likelihood(probabilities, targets),
        "ece_15_bins": expected_calibration_error(
            probabilities,
            targets,
            bins=15,
        ),
        "brier_score": multiclass_brier_score(
            probabilities,
            targets,
        ),
        "mean_confidence": float(np.mean(confidence)),
        "selective_results": selective_results,
    }
