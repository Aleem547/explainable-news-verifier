"""Phase 13F.2A extra admission lifecycle regressions (no real ML/DB/network)."""

from __future__ import annotations

import asyncio
import threading
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from apps.api.routes import article_verification as route


class ArticleAdmissionCancellationFollowups(unittest.IsolatedAsyncioTestCase):
    def request(self) -> route.ArticleVerificationRequest:
        return route.ArticleVerificationRequest(kind="pasted", text="A" * 120)

    async def test_repeated_cancellation_keeps_slot_until_worker_and_session_finish(self) -> None:
        started = threading.Event()
        allow_finish = threading.Event()
        finished = threading.Event()
        observed_sessions: list[object] = []
        db_session = object()

        def cpu_work() -> None:
            started.set()
            try:
                if not allow_finish.wait(5):
                    raise TimeoutError("Synthetic worker timed out")
            finally:
                finished.set()

        async def fake_workflow(session: object, **kwargs: object) -> dict[str, bool]:
            observed_sessions.append(session)
            await asyncio.to_thread(cpu_work)
            return {"synthetic": True}

        first: asyncio.Task | None = None
        with (
            patch.dict("os.environ", {"ARTICLE_VERIFICATION_ENABLED": "true"}),
            patch.object(route, "_article_admission", asyncio.Semaphore(1)),
            patch.object(route, "verify_pasted_article", fake_workflow),
        ):
            try:
                first = asyncio.create_task(
                    route.verify_article_endpoint(self.request(), db_session, "test-user")
                )
                self.assertTrue(await asyncio.wait_for(asyncio.to_thread(started.wait, 2), 3))
                first.cancel()
                await asyncio.sleep(0)
                first.cancel()  # Second cancellation must not free admission.
                await asyncio.sleep(0.02)
                self.assertFalse(first.done(), "Request finished before the CPU thread did")
                with self.assertRaises(HTTPException) as denied:
                    await route.verify_article_endpoint(self.request(), db_session, "test-user")
                self.assertEqual(denied.exception.status_code, 429)
                self.assertFalse(finished.is_set())
                allow_finish.set()
                with self.assertRaises(asyncio.CancelledError):
                    await asyncio.wait_for(first, 3)
                self.assertTrue(finished.is_set())
                self.assertIs(observed_sessions[0], db_session)
                # Release must happen after thread completes, even on cancellation.
                response = await route.verify_article_endpoint(self.request(), db_session, "test-user")
                self.assertEqual(response.status_code, 200)
            finally:
                allow_finish.set()
                if first is not None and not first.done():
                    first.cancel()
                    try:
                        await asyncio.wait_for(first, 5)
                    except asyncio.CancelledError:
                        pass

    async def test_failed_workflow_releases_admission_for_retry(self) -> None:
        async def error(*args: object, **kwargs: object) -> None:
            raise RuntimeError("Sensitive backend failure")

        async def success(*args: object, **kwargs: object) -> dict[str, bool]:
            return {"synthetic": True}

        with (
            patch.dict("os.environ", {"ARTICLE_VERIFICATION_ENABLED": "true"}),
            patch.object(route, "_article_admission", asyncio.Semaphore(1)),
        ):
            with patch.object(route, "verify_pasted_article", error):
                with self.assertRaises(HTTPException) as unavailable:
                    await route.verify_article_endpoint(self.request(), object(), "test-user")
                self.assertEqual(unavailable.exception.status_code, 503)
                self.assertNotIn("Sensitive", unavailable.exception.detail)
            with patch.object(route, "verify_pasted_article", success):
                response = await route.verify_article_endpoint(self.request(), object(), "test-user")
                self.assertEqual(response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
