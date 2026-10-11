"""Register the new ORM model without replacing existing project model imports.

Run once at the repository root: uv run python scripts/apply_phase10b3_2_registry.py
"""

from pathlib import Path

path = Path("apps/api/db/models/__init__.py")
if not path.is_file():
    raise SystemExit(f"Missing {path}; run from the repository root")
text = path.read_text(encoding="utf-8")
import_line = "from apps.api.db.models.verification_usage import VerificationUsageEvent"
if import_line not in text:
    anchor = "from apps.api.db.models.verification import VerificationResult"
    if text.count(anchor) != 1:
        raise SystemExit("Cannot find expected model import; review __init__.py manually")
    text = text.replace(anchor, anchor + "\n" + import_line)

entry = '    "VerificationUsageEvent",'
if entry not in text:
    anchor = '    "VerificationResult",'
    if text.count(anchor) != 1:
        raise SystemExit("Cannot find expected __all__ entry; review __init__.py manually")
    text = text.replace(anchor, anchor + "\n" + entry)

path.write_text(text, encoding="utf-8")
print("ORM model registered:", path)
