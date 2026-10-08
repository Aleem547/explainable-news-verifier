"""Serve the frozen DeBERTa NLI checkpoint with validation-fitted temperature."""

import hashlib
import json
import math
from collections.abc import Sequence
from pathlib import Path

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

from ml.verification.evidence_pipeline import NliProbabilities

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL_DIRECTORY = (
    PROJECT_ROOT / "models" / "nli_verifier" / "nli-deberta-v3-small_fever_nli_30k"
)
DEFAULT_CALIBRATION_PATH = PROJECT_ROOT / "data" / "metadata" / "fever_nli_calibration_config.json"
LABEL_ORDER = ["ENTAILMENT", "CONTRADICTION", "NEUTRAL"]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalized_model_label_order(label2id: dict[str, int]) -> list[int]:
    mapping = {str(name).strip().lower(): int(idx) for name, idx in label2id.items()}
    if set(mapping) != {"entailment", "contradiction", "neutral"}:
        raise ValueError(f"Unexpected checkpoint NLI labels: {label2id}")
    order = [mapping["entailment"], mapping["contradiction"], mapping["neutral"]]
    if sorted(order) != [0, 1, 2]:
        raise ValueError("Checkpoint NLI label IDs must be exactly 0, 1, and 2.")
    return order


class CalibratedNliVerifier:
    def __init__(
        self,
        *,
        model_directory: Path = DEFAULT_MODEL_DIRECTORY,
        calibration_path: Path = DEFAULT_CALIBRATION_PATH,
        batch_size: int = 8,
        max_length: int = 256,
        device: str = "cpu",
    ) -> None:
        if batch_size <= 0 or max_length <= 0:
            raise ValueError("batch_size and max_length must be positive.")
        if not model_directory.is_dir():
            raise FileNotFoundError(f"Trained model directory missing: {model_directory}")
        if not calibration_path.is_file():
            raise FileNotFoundError(f"Calibration metadata missing: {calibration_path}")

        calibration = json.loads(calibration_path.read_text(encoding="utf-8"))
        if calibration.get("method") != "temperature_scaling":
            raise ValueError("Unexpected calibration method.")
        if calibration.get("model") != model_directory.name:
            raise ValueError("Calibration does not match selected model.")
        if calibration.get("source_split") != "validation":
            raise ValueError("Calibration must be fitted on validation data.")
        if calibration.get("project_label_order") != LABEL_ORDER:
            raise ValueError("Calibration label order is incompatible.")

        expected_fingerprints = calibration.get("model_fingerprints")
        if not isinstance(expected_fingerprints, dict) or not expected_fingerprints:
            raise ValueError("Calibration lacks model fingerprints.")
        files = [model_directory / "config.json"]
        files.extend(sorted(model_directory.glob("*.safetensors")))
        files.extend(sorted(model_directory.glob("*.bin")))
        if len(files) < 2 or any(not path.is_file() for path in files):
            raise FileNotFoundError("Trained checkpoint config/weights are missing.")
        actual_fingerprints = {file.name: sha256_file(file) for file in files}
        if actual_fingerprints != expected_fingerprints:
            raise ValueError("Checkpoint differs from the calibration-frozen model.")

        temperature = float(calibration["temperature"])
        if not math.isfinite(temperature) or temperature <= 0:
            raise ValueError("Invalid calibration temperature.")
        self.temperature = temperature
        self.batch_size = batch_size
        self.max_length = max_length
        self.device = torch.device(device)

        self.tokenizer = AutoTokenizer.from_pretrained(str(model_directory), use_fast=True)
        self.model = AutoModelForSequenceClassification.from_pretrained(str(model_directory))
        self.model.to(self.device)
        self.model.eval()
        self.logit_order = normalized_model_label_order(self.model.config.label2id)

    def predict(self, claim: str, evidence_texts: Sequence[str]) -> list[NliProbabilities]:
        if not claim.strip():
            raise ValueError("Claim cannot be empty.")
        if not evidence_texts:
            return []
        if any(not text.strip() for text in evidence_texts):
            raise ValueError("Evidence sentences cannot be empty.")

        predictions: list[NliProbabilities] = []
        with torch.inference_mode():
            for start in range(0, len(evidence_texts), self.batch_size):
                texts = list(evidence_texts[start : start + self.batch_size])
                encoded = self.tokenizer(
                    texts,
                    [claim] * len(texts),
                    padding=True,
                    truncation=True,
                    max_length=self.max_length,
                    return_tensors="pt",
                )
                inputs = {name: value.to(self.device) for name, value in encoded.items()}
                logits = self.model(**inputs).logits[:, self.logit_order]
                probabilities = torch.softmax(logits / self.temperature, dim=-1)
                for entailment, contradiction, neutral in probabilities.cpu().tolist():
                    predictions.append(
                        NliProbabilities(
                            entailment=float(entailment),
                            contradiction=float(contradiction),
                            neutral=float(neutral),
                        ).checked()
                    )
        return predictions
