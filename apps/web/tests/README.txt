Phase 11C.4 complete benchmark replacement
==========================================

1. Keep Next.js on http://localhost:3000 and Docker API healthy.
2. Keep dedicated Chrome -Mode Benchmark running (127.0.0.1:9237).
3. In that SAME Chrome browser, open http://localhost:3000/api/auth/session
   and confirm a user ID exists. Leave the tab open. Do not copy/share ID.
4. From apps/web, run:

   node --check .\tests\phase11c4_concurrency.mjs
   node .\tests\phase11c4_concurrency.mjs --diagnose

   Expected: authenticated tab found, preflight PASSED.

5. To run only after diagnosis:
   node .\tests\phase11c4_concurrency.mjs --concurrency 2 --rounds 2 --execute

No auth bypasses, no retries, no cookie exports. Reports saved under
repository/benchmarks/results. Keep reports local until reviewed.

This script doesn't change your frontend or backend application files.
