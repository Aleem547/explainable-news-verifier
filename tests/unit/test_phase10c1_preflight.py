"""Phase 10C.1 security preflight unit tests; no network or cloud access."""

from pathlib import Path

from scripts.security.phase10c1_preflight import _is_private_file, audit


def _root(tmp_path: Path, *, secure: bool = True) -> Path:
    path = tmp_path / "apps/web/src/lib/api/server.ts"
    path.parent.mkdir(parents=True)
    path.write_text(
        (
            'process.env.NODE_ENV === "production"; base.protocol !== "https:"; redirect: "error";'
            if secure
            else "const insecure = true;"
        ),
        encoding="utf-8",
    )
    return tmp_path


def test_private_env_filenames() -> None:
    assert _is_private_file("apps/web/.env.local")
    assert _is_private_file(".env")
    assert not _is_private_file("apps/web/.env.example")
    assert not _is_private_file("docs/.env.production.template")


def test_local_mode_passes_without_prod_env(tmp_path: Path) -> None:
    checks = audit(_root(tmp_path), environ={}, tracked=[])
    assert all(item.level != "FAIL" for item in checks)


def test_insecure_transport_fails(tmp_path: Path) -> None:
    checks = audit(_root(tmp_path, secure=False), environ={}, tracked=[])
    assert any(item.level == "FAIL" and item.check == "backend-transport" for item in checks)


def test_tracked_secrets_fail_without_exposing_values(tmp_path: Path) -> None:
    checks = audit(_root(tmp_path), environ={}, tracked=["apps/web/.env.local"])
    assert any(item.level == "FAIL" and item.check == "tracked-files" for item in checks)


def test_rejects_private_next_public_environment(tmp_path: Path) -> None:
    root = _root(tmp_path)
    source = root / "apps/web/src/app/page.tsx"
    source.parent.mkdir(parents=True)
    source.write_text("process.env.NEXT_PUBLIC_INTERNAL_API_TOKEN", encoding="utf-8")
    checks = audit(root, environ={}, tracked=[])
    assert any(item.level == "FAIL" and item.check == "public-env" for item in checks)


def test_production_web_requires_https_and_secrets(tmp_path: Path) -> None:
    checks = audit(
        _root(tmp_path),
        mode="production",
        service="web",
        environ={"NODE_ENV": "production", "API_BASE_URL": "http://example.org"},
        tracked=[],
    )
    assert any(item.level == "FAIL" and item.check == "web-backend" for item in checks)
    assert any(item.level == "FAIL" and item.check == "INTERNAL_API_TOKEN" for item in checks)


def test_valid_web_deployment_configuration(tmp_path: Path) -> None:
    checks = audit(
        _root(tmp_path),
        mode="production",
        service="web",
        environ={
            "NODE_ENV": "production",
            "API_BASE_URL": "https://api.example.org",
            "AUTH_SECRET": "x" * 32,
            "INTERNAL_API_TOKEN": "y" * 40,
            "AUTH_GOOGLE_ID": "example-id",
            "AUTH_GOOGLE_SECRET": "example-secret",
        },
        tracked=[],
    )
    assert all(item.level != "FAIL" for item in checks)


def test_production_api_requires_explicit_app_env(tmp_path: Path) -> None:
    checks = audit(
        _root(tmp_path),
        mode="production",
        service="api",
        environ={"INTERNAL_API_TOKEN": "x" * 40},
        tracked=[],
    )
    assert any(item.level == "FAIL" and item.check == "api-mode" for item in checks)
