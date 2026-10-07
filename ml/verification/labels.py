from enum import StrEnum


class NliLabel(StrEnum):
    ENTAILMENT = "ENTAILMENT"
    CONTRADICTION = "CONTRADICTION"
    NEUTRAL = "NEUTRAL"


NLI_LABEL_TO_ID: dict[NliLabel, int] = {
    NliLabel.ENTAILMENT: 0,
    NliLabel.CONTRADICTION: 1,
    NliLabel.NEUTRAL: 2,
}


NLI_ID_TO_LABEL: dict[int, NliLabel] = {
    label_id: label for label, label_id in NLI_LABEL_TO_ID.items()
}


def nli_label_to_id(
    label: NliLabel,
) -> int:
    return NLI_LABEL_TO_ID[label]


def nli_id_to_label(
    label_id: int,
) -> NliLabel:
    try:
        return NLI_ID_TO_LABEL[label_id]

    except KeyError as exc:
        raise ValueError(f"Unknown NLI label id: {label_id}") from exc
