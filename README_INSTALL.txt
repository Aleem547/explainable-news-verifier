PHASE 10A.5 - INTERACTIVE CLAIM VERIFICATION (Windows + VS Code)

IMPORTANT
- This archive only adds the new /verify page and two components, and REPLACES
  one file: apps/web/src/components/layout/app-sidebar.tsx.
- Existing dashboard app/page.tsx, globals.css, OpenAPI schema.d.ts, backend,
  environment files, and API routes remain untouched.
- The existing Phase 10A.4 Next.js /api/verification route deliberately blocks
  public verification in production mode. The UI can verify claims in npm run dev.
  Production authentication and distributed rate limiting come later.
- No Git commit or push until the end of Phase 10.

INSTALL (POWERSHELL; from C:\Projects\explainable-news-verifier):

  Copy-Item apps\web\src\components\layout\app-sidebar.tsx "$env:TEMP\phase10a5_app-sidebar_backup.tsx"

  Expand-Archive -LiteralPath "$HOME\Downloads\phase10a5_verification_ui.zip" -DestinationPath . -Force

VALIDATE (POWERSHELL; with Next.js dev server stopped):

  cd C:\Projects\explainable-news-verifier\apps\web
  npm run lint
  npx tsc --noEmit
  npm run build

RUN:
- Start FastAPI in separate PowerShell terminal:
  cd C:\Projects\explainable-news-verifier
  uv run uvicorn apps.api.main:app --host 127.0.0.1 --port 8000
- Start Next.js in another PowerShell terminal:
  cd C:\Projects\explainable-news-verifier\apps\web
  npm run dev
- Open http://localhost:3000/verify
- Try: The Indian Army is a military force.
- The first model invocation may be slower. An INSUFFICIENT_EVIDENCE
  verdict is valid and should not be treated as an API failure.

DO NOT:
- Run npm audit fix --force for unrelated dev-dependency advisories.
- Claim this UI establishes cross-publisher evidence independence.
- Publish the expensive verification route without production access controls.
