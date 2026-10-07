from dataclasses import dataclass
from pathlib import Path

import torch
from transformers import (
    AutoModelForSequenceClassification,
    AutoTokenizer,
)

from ml.classification.labels import (
    ID_TO_LABEL,
)
from ml.datasets.loaders.fever import (
    FeverLabel,
)


@dataclass(frozen=True)
class ClaimPrediction:
    label: FeverLabel
    label_id: int
    confidence: float
    probabilities: dict[str, float]


def logits_to_probabilities(
    logits: torch.Tensor,
) -> ClaimPrediction:
    if logits.ndim != 1:
        raise ValueError("Classification logits must be one-dimensional.")

    if logits.shape[0] != 3:
        raise ValueError("Expected exactly three classification logits.")

    probabilities_tensor = (
        torch.softmax(
            logits.float(),
            dim=-1,
        )
        .detach()
        .cpu()
    )

    label_id = int(torch.argmax(probabilities_tensor).item())

    label = ID_TO_LABEL[label_id]

    probabilities = {
        ID_TO_LABEL[index].value: float(probabilities_tensor[index].item()) for index in range(3)
    }

    return ClaimPrediction(
        label=label,
        label_id=label_id,
        confidence=probabilities[label.value],
        probabilities=probabilities,
    )


class ClaimClassifier:
    def __init__(
        self,
        *,
        model_directory: Path,
        device: str = "cpu",
        max_length: int = 128,
    ) -> None:
        if not model_directory.exists():
            raise FileNotFoundError(f"Claim classifier model does not exist: {model_directory}")

        if max_length <= 0:
            raise ValueError("max_length must be greater than zero.")

        self.model_directory = model_directory

        self.device = torch.device(device)

        self.max_length = max_length

        self.tokenizer = AutoTokenizer.from_pretrained(str(model_directory))

        self.model = AutoModelForSequenceClassification.from_pretrained(str(model_directory))

        self.model.to(self.device)

        self.model.eval()

    def predict(
        self,
        claim: str,
    ) -> ClaimPrediction:
        normalized_claim = claim.strip()

        if not normalized_claim:
            raise ValueError("Claim cannot be empty.")

        encoded = self.tokenizer(
            normalized_claim,
            truncation=True,
            max_length=self.max_length,
            return_tensors="pt",
        )

        model_inputs = {key: value.to(self.device) for key, value in encoded.items()}

        with torch.inference_mode():
            output = self.model(**model_inputs)

        logits = output.logits[0]

        return logits_to_probabilities(logits)
