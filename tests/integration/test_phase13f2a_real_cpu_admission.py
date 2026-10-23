"""Offline, opt-in real CPU admission test for Phase 13F.2A.

Runs one genuine local NLI inference through the SAME model used in the
Phase 13D.5 smoke test, while exercising the Phase 13F.2A article-route
cancellation/admission behavior. No HTTP server, DB, cloud, or user data.

Run explicitly (model artifacts and CPU resources required):
  uv run --frozen python -m unittest discover -s tests/integration \
      -p "test_phase13f2a_real_cpu_admission.py" -v
"""
from __future__ import annotations

import asyncio
import os
import sys
import threading
import time
import unittest
from unittest.mock import patch

from fastapi import HTTPException

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")


def _working_set_mib() -> tuple[float | None, float | None]:
    """Best-effort current/peak Windows process working set (not GPU/host RAM)."""
    if sys.platform != "win32":
        return None, None
    try:
        import ctypes
        from ctypes import wintypes

        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = (
            wintypes.HANDLE,
            ctypes.POINTER(ProcessMemoryCounters),
            wintypes.DWORD,
        )
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        handle = kernel32.GetCurrentProcess()
        if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
            return None, None
        mib = 1024 * 1024
        return counters.WorkingSetSize / mib, counters.PeakWorkingSetSize / mib
    except (OSError, AttributeError, ValueError):
        return None, None


async def _wait_for(event: threading.Event, seconds: float = 12) -> bool:
    return await asyncio.wait_for(asyncio.to_thread(event.wait, seconds), seconds + 2)


class RealCpuArticleCancellationAdmissionTest(unittest.IsolatedAsyncioTestCase):
    async def test_cancelled_article_request_does_not_overlap_real_nli_cpu_work(self) -> None:
        from apps.api.routes import article_verification as route

        worker_entered = threading.Event()
        model_started = threading.Event()
        model_finished = threading.Event()
        allow_worker_to_exit = threading.Event()
        worker_exited = threading.Event()
        measurements: dict[str, object] = {}
        errors: list[BaseException] = []

        def real_cpu_worker() -> None:
            worker_entered.set()
            try:
                model_started.set()
                measurements["rss_before_mib"] = _working_set_mib()[0]
                tic = time.perf_counter()
                # Exactly the same real model entry point as Phase 13D.5.
                from apps.api.services.multisource import _model_predict

                outputs = _model_predict(
                    "The Eiffel Tower is located in Paris.",
                    ["The Eiffel Tower is a landmark located in Paris."],
                )
                duration = time.perf_counter() - tic
                if len(outputs) != 1:
                    raise AssertionError("NLI model returned an unexpected result count")
                probabilities = outputs[0].checked()
                if abs(sum((
                    probabilities.entailment,
                    probabilities.contradiction,
                    probabilities.neutral,
                )) - 1.0) > 1e-4:
                    raise AssertionError("NLI probabilities do not sum to one")
                measurements["inference_seconds"] = round(duration, 3)
                measurements["prediction_valid"] = True
                measurements["rss_after_mib"], measurements["peak_rss_mib"] = _working_set_mib()
                model_finished.set()
                # Keep the underlying thread alive until the test authorizes
                # completion. This makes the admission assertion deterministic
                # even if the model is very fast on a particular machine.
                if not allow_worker_to_exit.wait(15):
                    raise TimeoutError("Controlled CPU worker release timed out")
            except BaseException as exc:
                errors.append(exc)
                raise
            finally:
                worker_exited.set()

        async def real_workflow(session: object, **kwargs: object) -> dict[str, bool]:
            await asyncio.to_thread(real_cpu_worker)
            return {"smoke": True}

        async def quick_success(session: object, **kwargs: object) -> dict[str, bool]:
            return {"recovered": True}

        request = route.ArticleVerificationRequest(kind="pasted", text="A" * 120)
        first: asyncio.Task | None = None
        with (
            patch.dict(os.environ, {"ARTICLE_VERIFICATION_ENABLED": "true"}),
            patch.object(route, "_article_admission", asyncio.Semaphore(1)),
            patch.object(route, "verify_pasted_article", real_workflow),
        ):
            try:
                first = asyncio.create_task(route.verify_article_endpoint(
                    request, session=None, authenticated_user="local-test-user",
                ))
                self.assertTrue(await _wait_for(worker_entered), "CPU worker did not start")
                self.assertTrue(await _wait_for(model_started), "CPU inference did not begin")
                first.cancel()  # Simulates client/proxy cancellation.
                await asyncio.sleep(0.02)
                self.assertFalse(first.done(), "Cancelled request dropped CPU admission early")

                with self.assertRaises(HTTPException) as denied:
                    await route.verify_article_endpoint(
                        request, session=None, authenticated_user="local-test-user",
                    )
                self.assertEqual(denied.exception.status_code, 429)
                self.assertFalse(first.done(), "First workflow finished before worker drain")
                self.assertTrue(await _wait_for(model_finished, 220), "Real model inference did not finish")
                self.assertFalse(first.done(), "Slot released before CPU thread exit")
            finally:
                allow_worker_to_exit.set()
                if first is not None:
                    try:
                        await asyncio.wait_for(first, timeout=45)
                    except asyncio.CancelledError:
                        pass

            self.assertTrue(worker_exited.is_set(), "CPU worker did not exit")
            self.assertEqual(errors, [], f"CPU worker raised: {[type(e).__name__ for e in errors]}")
            self.assertTrue(measurements.get("prediction_valid"), "No valid real prediction")

            with patch.object(route, "verify_pasted_article", quick_success):
                recovered = await route.verify_article_endpoint(
                    request, session=None, authenticated_user="local-test-user",
                )
            self.assertEqual(recovered.status_code, 200, "Admission was not restored")

        print("\nPHASE13F2A_REAL_CPU_TEST_PASS")
        print("Busy request: HTTP 429 during cancelled in-flight inference")
        print("Post-completion request: HTTP 200")
        print(f"Actual NLI call duration (incl. lazy init): {measurements.get('inference_seconds')}s")
        print(f"Working set before model: {measurements.get('rss_before_mib')} MiB")
        print(f"Working set after model: {measurements.get('rss_after_mib')} MiB")
        print(f"Peak process working set: {measurements.get('peak_rss_mib')} MiB")
        print("NOTE: This is a one-process offline smoke test, not a production load test.")


if __name__ == "__main__":
    unittest.main()
