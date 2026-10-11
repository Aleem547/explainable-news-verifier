"""Read-only Phase 10C.3.1 check of the local inference artifact layout."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class ArtifactCheck:
    name: str
    relative_path: str
    present: bool
    detail: str


REQUIRED_ARTIFACTS: tuple[tuple[str, str, str], ...] = (
    ("NLI checkpoint", "models/nli_verifier/nli-deberta-v3-small_fever_nli_30k", "dir"),
    ("NLI calibration", "data/metadata/fever_nli_calibration_config.json", "file"),
    ("Tantivy page index", "data/indexes/fever/page_bm25", "dir"),
    ("FEVER sentence corpus", "data/processed/fever/wiki_sentences.parquet", "file"),
)


def inspect_artifacts(root: Path) -> list[ArtifactCheck]:
    """Check path existence and required checkpoint metadata without reading secrets."""
    checks: list[ArtifactCheck] = []
    for label, relative, expected_kind in REQUIRED_ARTIFACTS:
        path = root / relative
        present = path.is_file() if expected_kind == "file" else path.is_dir()
        detail = "present" if present else f"missing {expected_kind}"
        if present and expected_kind == "dir" and not any(path.iterdir()):
            present = False
            detail = "directory empty"
        checks.append(ArtifactCheck(label, relative, present, detail))

    checkpoint = root / REQUIRED_ARTIFACTS[0][1]
    if checkpoint.is_dir():
        has_config = (checkpoint / "config.json").is_file()
        has_weights = any(checkpoint.glob("*.safetensors")) or any(checkpoint.glob("*.bin"))
        checks.append(
            ArtifactCheck(
                "Checkpoint config",
                f"{REQUIRED_ARTIFACTS[0][1]}/config.json",
                has_config,
                "present" if has_config else "missing file",
            )
        )
        checks.append(
            ArtifactCheck(
                "Checkpoint weights",
                f"{REQUIRED_ARTIFACTS[0][1]}/*.safetensors or *.bin",
                has_weights,
                "present" if has_weights else "missing model weights",
            )
        )
    return checks


def render_report(checks: list[ArtifactCheck]) -> str:
    rows = ["Phase 10C.3.1 inference artifact preflight (read-only)"]
    for item in checks:
        rows.append(
            f"{'PASS' if item.present else 'FAIL'} | {item.name} | {item.relative_path} "
            f"| {item.detail}"
        )
    rows.append(f"Result: {sum(item.present for item in checks)}/{len(checks)} checks passed")
    rows.append(
        "Note: BGE and cross-encoder models must also be cached or downloadable at runtime."
    )
    return "\n".join(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT)
    args = parser.parse_args()
    checks = inspect_artifacts(args.root)
    print(render_report(checks))
    return 0 if all(item.present for item in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
