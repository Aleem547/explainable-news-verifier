"""Optional local checkpoint smoke test. No HTTP, PostgreSQL or AWS required.

Run only where the frozen model artifacts, calibration metadata, torch and
transformers are installed. Tests genuine existing CPU model inference.
"""
from __future__ import annotations

import os
import unittest

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")


class FrozenNliCheckpointSmoke(unittest.TestCase):
    def test_existing_calibrated_model_returns_valid_probabilities(self):
        from apps.api.services.multisource import _model_predict

        result = _model_predict(
            "The Eiffel Tower is located in Paris.",
            ["The Eiffel Tower is a landmark located in Paris."],
        )
        self.assertEqual(len(result), 1)
        probabilities = result[0].checked()
        self.assertAlmostEqual(
            probabilities.entailment + probabilities.contradiction + probabilities.neutral,
            1.0, places=4,
        )
        self.assertIn(probabilities.top_label()[0], ("ENTAILMENT", "CONTRADICTION", "NEUTRAL"))
        # Do not assert the factual truth of a synthetic test from one NLI output.


if __name__ == "__main__":
    unittest.main()
