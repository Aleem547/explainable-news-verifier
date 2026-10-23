"""Phase 13F.2A: deterministic cancellation/admission regression.

Run from repository root:
    python -m pytest tests/unit/test_phase13f2a_cancellation_admission.py -q

No HTTP server, model download, GPU, DB, or external service is needed.
Before the admission fix this test is expected to FAIL (red phase).
"""

from __future__ import annotations

import asyncio
import threading
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from apps.api.routes import article_verification as article_route


class ArticleAdmissionCancellationTests(unittest.IsolatedAsyncioTestCase):
    async def test_canceled_request_does_not_admit_overlapping_cpu_work(self) -> None:
        cpu_started = threading.Event()
        permit_finish = threading.Event()
        sync = threading.Lock()
        active = 0
        maximum_active = 0

        def blocking_cpu_work() -> None:
            nonlocal active, maximum_active
            with sync:
                active += 1
                maximum_active = max(maximum_active, active)
            try:
                cpu_started.set()
                # A finite bound prevents hanging even if the test fails.
                if not permit_finish.wait(timeout=5):
                    raise TimeoutError("Synthetic CPU worker was not released")
            finally:
                with sync:
                    active -= 1

        async def synthetic_article_verification(*_args: object, **_kwargs: object) -> dict[str, bool]:
            # Real thread semantics: task.cancel() does NOT terminate the thread.
            await asyncio.to_thread(blocking_cpu_work)
            return {"synthetic": True}

        def make_request() -> article_route.ArticleVerificationRequest:
            return article_route.ArticleVerificationRequest(kind="pasted", text="A" * 120)

        first: asyncio.Task | None = None
        second: asyncio.Task | None = None
        # Dedicated per-test semaphore prevents leakage between tests or event loops.
        with patch.dict("os.environ", {"ARTICLE_VERIFICATION_ENABLED": "true"}), patch.object(
            article_route, "_article_admission", asyncio.Semaphore(1)
        ), patch.object(article_route, "verify_pasted_article", synthetic_article_verification):
            try:
                first = asyncio.create_task(
                    article_route.verify_article_endpoint(
                        make_request(), session=None, authenticated_user="synthetic-test-user"
                    )
                )
                started = await asyncio.wait_for(asyncio.to_thread(cpu_started.wait, 2), timeout=3)
                self.assertTrue(started, "Synthetic CPU inference never started")

                # Simulate an aborted frontend request while CPU is still running.
                first.cancel()
                await asyncio.sleep(0.02)
                second = asyncio.create_task(
                    article_route.verify_article_endpoint(
                        make_request(), session=None, authenticated_user="synthetic-test-user"
                    )
                )
                # Admission policy must reject the second request promptly with 429.
                await asyncio.sleep(0.15)
                self.assertTrue(
                    second.done(),
                    "Second request was admitted while abandoned inference is active",
                )
                with self.assertRaises(HTTPException) as denied:
                    await second
                self.assertEqual(denied.exception.status_code, 429)
                with sync:
                    self.assertEqual(maximum_active, 1)
            finally:
                permit_finish.set()
                for task in (first, second):
                    if task is None:
                        continue
                    if not task.done():
                        task.cancel()
                    try:
                        await asyncio.wait_for(task, timeout=5)
                    except (asyncio.CancelledError, TimeoutError, HTTPException):
                        pass


if __name__ == "__main__":
    unittest.main()
