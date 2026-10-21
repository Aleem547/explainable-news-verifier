"""Phase 13E.7 bounded integration contracts; no HTTP, model, DB or AWS."""

from __future__ import annotations

import asyncio
import importlib
import os
import subprocess
import sys
import types
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

from apps.api.services.article_api_workflow import verify_pasted_article


class WorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def test_pasted_workflow_uses_existing_modules_and_small_budget(self):
        from apps.api.services import article_api_workflow
        calls: list[tuple[str, object]] = []
        prepared = object()
        multi = object()
        final = object()
        fake_pasted = types.ModuleType("apps.api.services.pasted_article_preparation")
        fake_pasted.PastedArticlePolicy = lambda **kw: kw
        def prepare_pasted_article(**kwargs):
            calls.append(("prepare", kwargs))
            return prepared
        fake_pasted.prepare_pasted_article = prepare_pasted_article
        fake_multi = types.ModuleType("apps.api.services.article_multi_claim_verification")
        fake_multi.MultiClaimPolicy = lambda **kw: kw
        async def verify_article_claims(session, **kwargs):
            calls.append(("verify", kwargs))
            self.assertIs(session, self)
            await asyncio.sleep(0)
            return multi
        fake_multi.verify_article_claims = verify_article_claims
        fake_reporting = types.ModuleType("apps.api.services.article_level_reporting")
        def build_article_level_report(**kwargs):
            calls.append(("report", kwargs))
            return final
        fake_reporting.build_article_level_report = build_article_level_report
        with patch.dict(sys.modules, {
            fake_pasted.__name__: fake_pasted,
            fake_multi.__name__: fake_multi,
            fake_reporting.__name__: fake_reporting,
        }):
            response = await article_api_workflow.verify_pasted_article(
                self, text="a" * 120, title="News sample", max_verifications=1,
            )
        self.assertIs(response, final)
        self.assertEqual([x[0] for x in calls], ["prepare", "verify", "report"])
        self.assertIs(calls[1][1]["prepared"], prepared)
        self.assertEqual(calls[1][1]["policy"]["max_verifications"], 1)
        self.assertEqual(calls[0][1]["policy"]["max_input_utf8_bytes"], 10000)
        self.assertIs(calls[2][1]["verification"], multi)

    async def test_invalid_budgets_do_not_start_work(self):
        for budget in (0, 3, True, 1.5, "2", -1):
            with self.subTest(budget=budget):
                with self.assertRaises(ValueError):
                    await verify_pasted_article(None, text="z" * 200, max_verifications=budget)


class RouterContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # The partial review ZIP doesn't contain core/service_auth or DB modules.
        # Provide minimal imports and test the real new FastAPI request model.
        from fastapi import Request, Response
        dummy_auth = types.ModuleType("apps.api.core.service_auth")
        dummy_auth.require_internal_verification = lambda: "google:test-user"
        dummy_db = types.ModuleType("apps.api.db.session")
        dummy_db.get_db_session = lambda: object()
        cls._sys = patch.dict(sys.modules, {
            dummy_auth.__name__: dummy_auth, dummy_db.__name__: dummy_db,
        })
        cls._sys.start()
        cls.route = importlib.import_module("apps.api.routes.article_verification")

    @classmethod
    def tearDownClass(cls):
        cls._sys.stop()
        sys.modules.pop("apps.api.routes.article_verification", None)

    def test_strict_input_cannot_forge_publisher_or_mode(self):
        from pydantic import ValidationError
        Model = self.route.ArticleVerificationRequest
        valid = Model(kind="pasted", text="x" * 120)
        self.assertEqual(valid.kind, "pasted")
        for data in (
            {"kind": "url", "text": "x" * 120},
            {"kind": "pasted", "text": "x" * 120, "publisher": "trusted"},
            {"kind": "pasted", "text": "x" * 99},
            {"kind": "pasted", "text": "x" * 8001},
            {"kind": "pasted", "text": "x" * 120, "title": "a" * 301},
            {"kind": "pasted", "text": 100},
        ):
            with self.subTest(data=str(data)[:40]):
                with self.assertRaises(ValidationError):
                    Model.model_validate(data)

    def test_feature_flag_fail_closed(self):
        from fastapi import HTTPException
        payload = self.route.ArticleVerificationRequest(kind="pasted", text="x" * 120)
        with patch.dict(os.environ, {"ARTICLE_VERIFICATION_ENABLED": "false"}):
            with self.assertRaises(HTTPException) as error:
                asyncio.run(self.route.verify_article_endpoint(payload, object(), "google:test"))
            self.assertEqual(error.exception.status_code, 503)

    def test_request_exceeds_unicode_bytes(self):
        from fastapi import HTTPException
        payload = self.route.ArticleVerificationRequest(kind="pasted", text="é" * 7000)
        with patch.dict(os.environ, {"ARTICLE_VERIFICATION_ENABLED": "true"}):
            with self.assertRaises(HTTPException) as error:
                asyncio.run(self.route.verify_article_endpoint(payload, object(), "google:test"))
            self.assertEqual(error.exception.status_code, 413)

    def test_503_hides_exception_details(self):
        from fastapi import HTTPException
        payload = self.route.ArticleVerificationRequest(kind="pasted", text="x" * 120)
        async def failure(*args, **kwargs):
            raise RuntimeError("do not echo raw article contents")
        with patch.dict(os.environ, {"ARTICLE_VERIFICATION_ENABLED": "true"}), patch.object(
            self.route, "verify_pasted_article", failure
        ):
            with self.assertRaises(HTTPException) as error:
                asyncio.run(self.route.verify_article_endpoint(payload, object(), "google:test"))
        self.assertEqual(error.exception.status_code, 503)
        self.assertNotIn("raw article", error.exception.detail)

    def test_admission_serialized(self):
        payload = self.route.ArticleVerificationRequest(kind="pasted", text="x" * 120)
        first_started = asyncio.Event()
        release = asyncio.Event()
        @dataclass
        class Report:
            article_sha256: str = "f" * 64
            candidate_count: int = 0
        async def slow(*args, **kwargs):
            first_started.set()
            await release.wait()
            return Report()
        async def check():
            from fastapi import HTTPException
            with patch.dict(os.environ, {"ARTICLE_VERIFICATION_ENABLED": "true"}), patch.object(
                self.route, "verify_pasted_article", slow
            ):
                one = asyncio.create_task(self.route.verify_article_endpoint(payload, object(), "google:test"))
                await first_started.wait()
                with self.assertRaises(HTTPException) as error:
                    await self.route.verify_article_endpoint(payload, object(), "google:test")
                self.assertEqual(error.exception.status_code, 429)
                release.set()
                response = await one
                self.assertEqual(response.status_code, 200)
        asyncio.run(check())


class SourceSafetyTests(unittest.TestCase):
    def test_main_mounts_same_protection(self):
        root = Path(__file__).resolve().parents[2]
        main = (root / "apps/api/main.py").read_text()
        self.assertIn("article_verification_router", main)
        self.assertIn("Depends(require_verified_user_access)", main)
        self.assertIn("*secured", main)

    def test_server_transport_never_forwards_browser_token(self):
        root = Path(__file__).resolve().parents[2]
        server = (root / "apps/web/src/lib/api/server.ts").read_text()
        self.assertIn('path === "/api/v1/article/verify"', server)
        self.assertIn('headers["X-Service-Token"] = token', server)
        self.assertIn('headers["X-Verified-User"] = options.verifiedUserId', server)
        route = (root / "apps/web/src/app/api/article-verification/route.ts").read_text()
        self.assertIn("const origin = request.headers.get", route)
        self.assertIn("const reader = request.body.getReader()", route)
        self.assertIn('await auth()', route)
        self.assertIn('data.kind !== "pasted"', route)
        self.assertIn("process.env.ARTICLE_VERIFICATION_ENABLED", route)

    def test_existing_claim_route_unchanged_in_package(self):
        """Phase 13E.7 must preserve both previously deployed claim routes."""
        root = Path(__file__).resolve().parents[2]
        existing_routes = (
            "apps/api/routes/verification.py",
            "apps/web/src/app/api/verification/route.ts",
        )

        for relative in existing_routes:
            with self.subTest(path=relative):
                path = root / relative
                self.assertTrue(path.is_file(), f"Existing claim route is missing: {relative}")

                baseline = subprocess.run(
                    ["git", "show", f"HEAD:{relative}"],
                    cwd=root,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(
                    baseline.returncode, 0,
                    f"Unable to read committed baseline for {relative}: "
                    f"{baseline.stderr.decode('utf-8', errors='replace')}",
                )

                # Git stores LF while Windows working trees may use CRLF.
                committed = baseline.stdout.replace(b"\r\n", b"\n")
                working = path.read_bytes().replace(b"\r\n", b"\n")
                self.assertEqual(
                    working,
                    committed,
                    f"Existing claim route changed unexpectedly: {relative}",
                )


if __name__ == "__main__":
    unittest.main()
