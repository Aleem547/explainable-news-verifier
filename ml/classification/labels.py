from ml.datasets.loaders.fever import (
    FeverLabel,
)

LABEL_TO_ID: dict[FeverLabel, int] = {
    FeverLabel.SUPPORTS: 0,
    FeverLabel.REFUTES: 1,
    FeverLabel.NOT_ENOUGH_INFO: 2,
}


ID_TO_LABEL: dict[int, FeverLabel] = {label_id: label for label, label_id in LABEL_TO_ID.items()}


def label_to_id(
    label: FeverLabel,
) -> int:
    return LABEL_TO_ID[label]


def id_to_label(
    label_id: int,
) -> FeverLabel:
    try:
        return ID_TO_LABEL[label_id]
    except KeyError as exc:
        raise ValueError(f"Unknown verification label id: {label_id}") from exc
