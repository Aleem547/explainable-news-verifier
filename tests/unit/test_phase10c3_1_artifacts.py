"""Lightweight, offline tests for the Phase 10C.3.1 deployment artifact checks."""

from pathlib import Path

from scripts.deployment.phase10c3_1_artifacts import inspect_artifacts, render_report


def _make_layout(root: Path) -> None:
    model = root / "models/nli_verifier/nli-deberta-v3-small_fever_nli_30k"
    model.mkdir(parents=True)
    (model / "config.json").write_text("{}", encoding="utf-8")
    (model / "model.safetensors").write_bytes(b"placeholder")
    calibration = root / "data/metadata/fever_nli_calibration_config.json"
    calibration.parent.mkdir(parents=True)
    calibration.write_text("{}", encoding="utf-8")
    index = root / "data/indexes/fever/page_bm25"
    index.mkdir(parents=True)
    (index / "metadata.json").write_text("{}", encoding="utf-8")
    corpus = root / "data/processed/fever/wiki_sentences.parquet"
    corpus.parent.mkdir(parents=True)
    corpus.write_bytes(b"placeholder")


def test_all_required_paths_present(tmp_path: Path) -> None:
    _make_layout(tmp_path)
    assert all(check.present for check in inspect_artifacts(tmp_path))


def test_missing_corpus_is_flagged(tmp_path: Path) -> None:
    _make_layout(tmp_path)
    (tmp_path / "data/processed/fever/wiki_sentences.parquet").unlink()
    checks = inspect_artifacts(tmp_path)
    assert any(check.name == "FEVER sentence corpus" and not check.present for check in checks)


def test_missing_calibration_is_flagged(tmp_path: Path) -> None:
    _make_layout(tmp_path)
    (tmp_path / "data/metadata/fever_nli_calibration_config.json").unlink()
    checks = inspect_artifacts(tmp_path)
    assert any(check.name == "NLI calibration" and not check.present for check in checks)


def test_empty_index_is_flagged(tmp_path: Path) -> None:
    _make_layout(tmp_path)
    (tmp_path / "data/indexes/fever/page_bm25/metadata.json").unlink()
    checks = inspect_artifacts(tmp_path)
    assert any(check.name == "Tantivy page index" and not check.present for check in checks)


def test_missing_checkpoint_weights_is_flagged(tmp_path: Path) -> None:
    _make_layout(tmp_path)
    (tmp_path / "models/nli_verifier/nli-deberta-v3-small_fever_nli_30k/model.safetensors").unlink()
    checks = inspect_artifacts(tmp_path)
    assert any(check.name == "Checkpoint weights" and not check.present for check in checks)


def test_bin_checkpoint_weights_are_supported(tmp_path: Path) -> None:
    _make_layout(tmp_path)
    model = tmp_path / "models/nli_verifier/nli-deberta-v3-small_fever_nli_30k"
    (model / "model.safetensors").unlink()
    (model / "pytorch_model.bin").write_bytes(b"placeholder")
    assert all(check.present for check in inspect_artifacts(tmp_path))


def test_missing_model_dir_is_flagged(tmp_path: Path) -> None:
    checks = inspect_artifacts(tmp_path)
    assert any(check.name == "NLI checkpoint" and not check.present for check in checks)


def test_report_is_path_only(tmp_path: Path) -> None:
    _make_layout(tmp_path)
    content = render_report(inspect_artifacts(tmp_path))
    assert "6/6 checks passed" in content
    assert "model.safetensors" not in content
    assert "placeholder" not in content


def test_source_docker_security_invariants() -> None:
    project_root = Path(__file__).resolve().parents[2]
    dockerfile = (project_root / "infra/docker/api/Dockerfile").read_text(encoding="utf-8")
    ignored = (project_root / ".dockerignore").read_text(encoding="utf-8")
    assert "USER verifier" in dockerfile
    assert "APP_ENV=production" in dockerfile
    assert '--workers", "1' in dockerfile
    assert "!apps/api/**" in ignored
    assert "**/.env.*" in ignored
    assert "!uv.lock" in ignored
