# Phase 10C.2.1 install (Windows / VS Code)

**This patch adds files only.** It does not replace any production code. No Git commands are required.

1. From `C:\Projects\explainable-news-verifier`, run:

   ```powershell
   Expand-Archive -Path "$env:USERPROFILE\Downloads\phase10c2_1_patch.zip" -DestinationPath . -Force
   ```

2. Check:

   ```powershell
   uv run ruff format scripts\performance\phase10c2_benchmark.py tests\unit\test_phase10c2_benchmark.py
   uv run ruff check .
   uv run ruff format --check .
   uv run mypy apps ml scripts
   uv run pytest tests\unit\test_phase10c2_benchmark.py -v
   uv run pytest
   ```

3. Close or stop the running FastAPI process with Ctrl+C before starting the heavyweight CPU benchmark to avoid loading duplicate models in memory.

4. Run:

   ```powershell
   uv run python -m scripts.performance.phase10c2_benchmark --runs 3 --top-k 5
   ```

5. Send the terminal report. Only then choose which stage to optimize.

No commit or push until the user explicitly approves it.
