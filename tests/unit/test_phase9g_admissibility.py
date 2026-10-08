"""External subject linking must fail closed when title grounding is uncertain."""

import pytest

from ml.verification.external_admissibility import external_subject_grounded


@pytest.mark.parametrize(
    ("claim", "evidence", "expected"),
    [
        ("The Eiffel Tower is in Paris", "The Eiffel Tower stands in Paris.", True),
        ("The Eiffel Tower is in Paris", "Eiffel Tower replicas exist.", True),
        ("The Eiffel Tower is in Paris", "The Louvre is in Paris.", False),
        ("The Eiffel Tower is in Paris", "An unrelated Eiffel tower model exists.", True),
        ("Some towers are in Paris", "Some towers exist.", False),
        ("The Indian Army is an armed force", "The Indian Army is an armed force.", True),
        ("The Indian Army is an armed force", "The Indian Armed Forces exist.", False),
    ],
)
def test_subject_anchor(claim: str, evidence: str, expected: bool) -> None:
    assert external_subject_grounded(claim, evidence) is expected
