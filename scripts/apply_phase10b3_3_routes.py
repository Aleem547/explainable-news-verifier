"""Register the Phase 10B3.3 account-usage API without overwriting main.py."""

from pathlib import Path

path = Path("apps/api/main.py")
source = path.read_text(encoding="utf-8")
import_line = "from apps.api.routes.usage_statistics import router as usage_statistics_router\n"
include_line = 'app.include_router(usage_statistics_router, prefix="/api/v1")\n'

if import_line in source and include_line in source:
    print("Phase 10B3.3 route already registered.")
else:
    anchor_import = "from apps.api.routes.verification import router as verification_router\n"
    anchor_include = 'app.include_router(health_router, prefix="/api/v1")\n'
    if anchor_import not in source or anchor_include not in source:
        raise SystemExit("Unrecognized main.py. No changes made; send the file for review.")
    if import_line in source or include_line in source:
        raise SystemExit("Partial route registration detected. No changes made.")

    source = source.replace(anchor_import, anchor_import + import_line, 1)
    source = source.replace(anchor_include, anchor_include + include_line, 1)
    path.write_text(source, encoding="utf-8")
    print("Phase 10B3.3 usage endpoint registered in apps/api/main.py.")
