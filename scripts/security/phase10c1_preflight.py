"""Read-only pre-deployment checks for Phase 10C.1.

No secrets or environment-variable values are printed. Checks are conservative:
passing this tool is not a replacement for a manual security review.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


@dataclass(frozen=True)
class Finding:
    level: str
    check: str
    message: str


_PRIVATE_PUBLIC_ENV = re.compile(
    r"\bNEXT_PUBLIC_(?:INTERNAL_API_TOKEN|AUTH_SECRET|AUTH_GOOGLE_SECRET|"
    r"DATABASE_URL|REDIS_URL|QDRANT_URL)\b"
)


def _is_private_file(path: str) -> bool:
    name = Path(path).name.lower()
    if name in {"credentials.json", "service-account.json", "service_account.json"}:
        return True
    if name == ".env" or name.startswith(".env."):
        return not name.endswith((".example", ".sample", ".template"))
    return False


def _git_tracked(root: Path) -> Sequence[str] | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z"],
            capture_output=True,
            check=True,
            timeout=10,
        )
        return [
            name.decode("utf-8", errors="replace") for name in result.stdout.split(b"\x00") if name
        ]
    except (FileNotFoundError, OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None


def audit(
    root: Path,
    *,
    mode: str = "local",
    service: str = "both",
    environ: Mapping[str, str] | None = None,
    tracked: Sequence[str] | None = None,
) -> list[Finding]:
    """Inspect source and deployment environment; never mutate the project."""
    if mode not in {"local", "production"}:
        raise ValueError("mode must be local or production")
    if service not in {"web", "api", "both"}:
        raise ValueError("service must be web, api, or both")

    env = dict(os.environ if environ is None else environ)
    findings: list[Finding] = []

    def add(level: str, check: str, message: str) -> None:
        findings.append(Finding(level, check, message))

    tracked_names = list(tracked) if tracked is not None else _git_tracked(root)
    if tracked_names is None:
        add("WARN", "tracked-files", "Git tracked-file inspection unavailable; check manually.")
    else:
        private = [name for name in tracked_names if _is_private_file(name)]
        if private:
            # File names only. Never show file contents or env values.
            add("FAIL", "tracked-files", "Potential private files tracked: " + ", ".join(private))
        else:
            add("PASS", "tracked-files", "No private env/credential filenames tracked.")

    transport = root / "apps/web/src/lib/api/server.ts"
    if not transport.is_file():
        add("FAIL", "backend-transport", "Server-only backend transport file not found.")
    else:
        code = transport.read_text(encoding="utf-8")
        if (
            'base.protocol !== "https:"' in code
            and 'process.env.NODE_ENV === "production"' in code
            and 'redirect: "error"' in code
        ):
            add("PASS", "backend-transport", "Production HTTPS and no-redirect safeguards present.")
        else:
            add("FAIL", "backend-transport", "Production HTTPS/no-redirect safeguard is missing.")

    frontend_source = root / "apps/web/src"
    leaks: list[str] = []
    if frontend_source.is_dir():
        for item in frontend_source.rglob("*"):
            if item.is_file() and item.suffix in {".js", ".jsx", ".ts", ".tsx"}:
                try:
                    content = item.read_text(encoding="utf-8")
                except (OSError, UnicodeError):
                    continue
                if _PRIVATE_PUBLIC_ENV.search(content):
                    leaks.append(item.relative_to(root).as_posix())
    if leaks:
        add(
            "FAIL",
            "public-env",
            "Private variable names in client-exposable namespace: " + ", ".join(leaks),
        )
    else:
        add("PASS", "public-env", "No flagged NEXT_PUBLIC_ secret variable names in web sources.")

    if mode == "local":
        add("PASS", "mode", "Local review only; production environment variables not required.")
        return findings

    if service in {"web", "both"}:
        if env.get("NODE_ENV") == "production":
            add("PASS", "web-mode", "Next.js production mode enabled.")
        else:
            add("FAIL", "web-mode", "NODE_ENV must equal production for a deployment check.")

        backend_url = env.get("API_BASE_URL", "")
        parsed = urlparse(backend_url)
        if (
            parsed.scheme == "https"
            and bool(parsed.hostname)
            and not (parsed.username or parsed.password or parsed.query or parsed.fragment)
            and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
        ):
            add("PASS", "web-backend", "Configured backend URL uses public HTTPS.")
        else:
            add("FAIL", "web-backend", "API_BASE_URL must be a valid non-loopback HTTPS URL.")

        for key in ("AUTH_SECRET", "INTERNAL_API_TOKEN"):
            if len(env.get(key, "")) >= 32:
                add("PASS", key, "Configured (length check passed).")
            else:
                add("FAIL", key, "Missing or too short (minimum 32 characters).")
        for key in ("AUTH_GOOGLE_ID", "AUTH_GOOGLE_SECRET"):
            if env.get(key):
                add("PASS", key, "Configured.")
            else:
                add("FAIL", key, "Not configured.")

    if service in {"api", "both"}:
        if env.get("APP_ENV", "").casefold() == "production":
            add("PASS", "api-mode", "APP_ENV explicitly set to production.")
        else:
            add("FAIL", "api-mode", "APP_ENV must equal production (default is development).")
        if env.get("DEBUG", "false").lower() in {"1", "true", "yes", "on"}:
            add("FAIL", "api-debug", "DEBUG must be disabled in production.")
        else:
            add("PASS", "api-debug", "Debug not enabled.")
        if len(env.get("INTERNAL_API_TOKEN", "")) >= 32:
            add("PASS", "api-service-token", "Service token configured (length check passed).")
        else:
            add("FAIL", "api-service-token", "INTERNAL_API_TOKEN missing or too short.")
        for key in ("DATABASE_URL", "REDIS_URL", "QDRANT_URL", "MLFLOW_TRACKING_URI"):
            if env.get(key):
                add("PASS", key, "Configured.")
            else:
                add("FAIL", key, "Not configured.")

    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("local", "production"), default="local")
    parser.add_argument("--service", choices=("web", "api", "both"), default="both")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    checks = audit(root, mode=args.mode, service=args.service)
    for finding in checks:
        print(f"{finding.level:4} | {finding.check:20} | {finding.message}")
    failures = sum(check.level == "FAIL" for check in checks)
    print(f"Security preflight: {len(checks)} checks, {failures} failures.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
