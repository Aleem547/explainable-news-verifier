"""Phase 13E.8: offline release contracts and isolated HTTP tests.

No network, live inference, databases, model loading or deployment. The
isolated FastAPI tests explicitly override service dependencies; they test
request validation and handler behavior, NOT real authentication. Actual
unauthenticated protection is checked separately by the opt-in loopback tests.
"""
from __future__ import annotations

import ast
import asyncio
import hashlib
import json
import os
import re
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


SYNTHETIC_ARTICLE = (
    "The Eiffel Tower is located in Paris, France. "
    "Its construction was associated with engineer Gustave Eiffel and his company. "
    "The Eiffel Tower is an internationally recognized landmark in France. "
    "This is synthetic test text and must not be used as independent evidence."
)


class ReleaseSourceContracts(unittest.TestCase):
    """Non-mutating checks of the committed production boundaries."""

    def test_main_has_protected_article_mount(self):
        tree = ast.parse(read("apps/api/main.py"))
        calls = (
            n for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "include_router"
        )
        article = [call for call in calls if call.args and
                   isinstance(call.args[0], ast.Name) and
                   call.args[0].id == "article_verification_router"]
        self.assertEqual(len(article), 1, "Article router must be mounted once")
        call = article[0]
        deps = next((x.value for x in call.keywords if x.arg == "dependencies"), None)
        self.assertIsNotNone(deps, "Article mount must have auth dependencies")
        dump = ast.dump(deps)
        self.assertIn("secured", dump)
        self.assertIn("require_verified_user_access", dump)

    def test_pasted_only_and_fail_closed_flags(self):
        api = read("apps/api/routes/article_verification.py")
        web = read("apps/web/src/app/api/article-verification/route.ts")
        self.assertIn('r"^pasted$"', api)
        self.assertIn('extra="forbid"', api)
        self.assertIn('ARTICLE_VERIFICATION_ENABLED', api)
        self.assertIn('ARTICLE_VERIFICATION_ENABLED', web)
        self.assertIn('data.kind !== "pasted"', web)
        self.assertNotIn('method: "GET", headers: {', web)  # no URL fetch path

    def test_model_work_has_cpu_admission_and_small_budget(self):
        api = read("apps/api/routes/article_verification.py")
        self.assertIn("asyncio.Semaphore(1)", api)
        self.assertIn("max_verifications=1", api)
        self.assertIn("_article_admission.release()", api)
        self.assertIn('Retry-After', api)
        self.assertIn("len(payload.text.encode(\"utf-8\")) > 10_000", api)

    def test_article_request_never_becomes_independent_evidence(self):
        workflow = read("apps/api/services/article_api_workflow.py")
        report = read("apps/api/services/article_level_reporting.py")
        self.assertIn("prepare_pasted_article", workflow)
        self.assertIn("verify_article_claims", workflow)
        self.assertIn("build_article_level_report", workflow)
        self.assertIn('"ARTICLE_INPUT_NOT_INDEPENDENT_EVIDENCE"', report)
        self.assertIn('"NOT_ESTABLISHED"', report)
        self.assertIn("overall_article_truth_probability: None", report)

    def test_no_untrusted_article_to_evidence_store_in_workflow(self):
        workflow = read("apps/api/services/article_api_workflow.py")
        # Workflow adapter must perform preparation, model calls and reporting;
        # it must not create or insert publisher/source records from input.
        tree = ast.parse(workflow)
        functions = [n for n in tree.body if isinstance(n, ast.AsyncFunctionDef)]
        self.assertEqual([f.name for f in functions], ["verify_pasted_article"])
        self.assertNotIn("session.add(", workflow)
        self.assertNotIn("session.execute(", workflow)

    def test_proxy_requires_session_same_origin_and_bounded_json(self):
        route = read("apps/web/src/app/api/article-verification/route.ts")
        for phrase in ('await auth()', '"AUTH_REQUIRED"',
                       'request.headers.get("origin")',
                       'request.headers.get("sec-fetch-site")',
                       'readBoundedJson(request, 12_000)',
                       'isArticleVerificationReport(result.data)',
                       '"Cache-Control": "no-store"'):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, route)

    def test_server_transport_uses_only_private_service_credentials(self):
        server = read("apps/web/src/lib/api/server.ts")
        self.assertIn('"/api/v1/article/verify"', server)
        self.assertIn('headers["X-Service-Token"] = token', server)
        self.assertIn('headers["X-Verified-User"] = options.verifiedUserId', server)
        self.assertIn('redirect: "error"', server)
        self.assertIn('cache: "no-store"', server)
        self.assertIn('process.env.NODE_ENV === "production"', server)

    def test_article_audit_never_logs_user_content_or_tokens(self):
        audit = read("apps/api/security/verification_audit.py")
        self.assertIn('"/api/v1/article/verify"', audit)
        self.assertIn('"cache-control", b"no-store"', audit)
        for name in ("request_body=", "claim_text=", "article_text=", "token=", "user_id="):
            self.assertNotIn(name, audit)

    def test_preserve_existing_claim_endpoint_and_page(self):
        api = read("apps/api/routes/verification.py")
        self.assertIn('router = APIRouter(prefix="/verify"', api)
        self.assertIn('@router.post(""', api)
        self.assertTrue((ROOT / "apps/web/src/app/verify/page.tsx").is_file())
        self.assertTrue((ROOT / "apps/web/src/app/api/verification/route.ts").is_file())
        self.assertTrue((ROOT / "apps/web/src/app/article/page.tsx").is_file())

    def test_frontend_separates_skipped_claims_and_no_truth_score(self):
        ui = read("apps/web/src/components/verification/article-verification-workspace.tsx")
        self.assertIn("claim.execution_status", ui)
        self.assertIn("claim.wikipedia_verdict", ui)
        self.assertIn("claim.external_verdict", ui)
        self.assertIn("Article-wide truth verdict unavailable", ui)
        self.assertIn("URL verification is not enabled", ui)

    def test_frontend_report_validator_rejects_fabricated_independence(self):
        validation = read("apps/web/src/lib/api/article-contracts.ts")
        for phrase in ('value.independent_corroboration_established !== false',
                       'value.overall_article_truth_verdict !== null',
                       'value.overall_article_truth_probability !== null',
                       'claim.independent_corroboration_established === false',
                       'ref.independence_status === "NOT_ESTABLISHED"'):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, validation)


class OfflinePipelineTests(unittest.IsolatedAsyncioTestCase):
    """Real 13E.3→13E.4→13E.5→13E.6 chain; fake NLI raises, so no inference."""

    async def test_failed_first_claim_and_skipped_rest_report_truthfully(self):
        from apps.api.services.pasted_article_preparation import prepare_pasted_article
        from apps.api.services.article_claim_candidates import extract_article_claim_candidates
        from apps.api.services.article_multi_claim_verification import MultiClaimPolicy, verify_article_claims
        from apps.api.services.article_level_reporting import build_article_level_report

        prepared = prepare_pasted_article(pasted_text=SYNTHETIC_ARTICLE)
        extracted = extract_article_claim_candidates(prepared=prepared)
        self.assertGreaterEqual(len(extracted.candidates), 2)
        calls = []

        async def failed_model(_session, **kwargs):
            calls.append(kwargs["claim"])
            raise RuntimeError("SENSITIVE_INTERNAL_ERROR_DO_NOT_SHOW")

        verification = await verify_article_claims(
            None, prepared=prepared, policy=MultiClaimPolicy(max_verifications=1),
            unified_runner=failed_model,
        )
        final = build_article_level_report(prepared=prepared, verification=verification)
        self.assertEqual(len(calls), 1)
        self.assertEqual(final.candidate_count, len(extracted.candidates))
        self.assertEqual(final.failed_count, 1)
        self.assertEqual(final.skipped_count, len(extracted.candidates) - 1)
        self.assertEqual(final.assessed_count, 0)
        self.assertEqual(final.article_sha256, hashlib.sha256(prepared.text.encode()).hexdigest())
        self.assertIsNone(final.overall_article_truth_probability)
        self.assertIsNone(final.overall_article_truth_verdict)
        self.assertFalse(final.independent_corroboration_established)
        self.assertNotIn("SENSITIVE_INTERNAL", str(final))
        for claim in final.claims:
            self.assertEqual(prepared.text[claim.start_char:claim.end_char], claim.literal_text)
            self.assertEqual(claim.wikipedia_status, None)
            self.assertEqual(claim.external_status, None)

    async def test_wikipedia_support_with_no_external_sources_remains_provisional(self):
        from apps.api.services.pasted_article_preparation import prepare_pasted_article
        from apps.api.services.article_multi_claim_verification import MultiClaimPolicy, verify_article_claims
        from apps.api.services.article_level_reporting import build_article_level_report
        from apps.api.services.unified_verification import (
            WikipediaFinding, ExternalFinding, UnifiedVerificationReport,
        )
        prepared = prepare_pasted_article(pasted_text=SYNTHETIC_ARTICLE)

        async def offline_verifier(_session, **kwargs):
            return UnifiedVerificationReport(
                claim=kwargs["claim"], assessed_at=kwargs["assessed_at"],
                wikipedia=WikipediaFinding(
                    status="AVAILABLE", evidence_verdict="SUPPORTING_EVIDENCE",
                    retrieved_count=2, assessed_count=1,
                    supporting_pages=("Eiffel Tower",), refuting_pages=(), warnings=(),
                ),
                external=ExternalFinding(
                    status="INSUFFICIENT_STORED_EVIDENCE", evidence_verdict=None,
                    retrieved_count=0, assessed_count=0, provisional_agreement_units=0,
                    provenance=(), warnings=("NOT_ENOUGH_EXTERNAL_SOURCES",),
                ),
                relationship="WIKIPEDIA_ONLY", warnings=(),
            )

        verification = await verify_article_claims(
            None, prepared=prepared, policy=MultiClaimPolicy(max_verifications=1),
            unified_runner=offline_verifier,
        )
        final = build_article_level_report(prepared=prepared, verification=verification)
        self.assertEqual(final.assessed_count, 1)
        self.assertEqual(final.skipped_count, final.candidate_count - 1)
        first = final.claims[0]
        self.assertEqual(first.wikipedia_verdict, "SUPPORTING_EVIDENCE")
        self.assertEqual(first.external_status, "INSUFFICIENT_STORED_EVIDENCE")
        self.assertEqual(first.cross_corpus_relationship, "WIKIPEDIA_ONLY")
        self.assertFalse(final.independent_corroboration_established)
        self.assertIsNone(final.overall_article_truth_verdict)
        self.assertIsNone(final.overall_article_truth_probability)

    async def test_forged_article_source_is_rejected(self):
        from apps.api.services.pasted_article_preparation import prepare_pasted_article
        from apps.api.services.article_multi_claim_verification import MultiClaimPolicy, verify_article_claims
        prepared = prepare_pasted_article(pasted_text=SYNTHETIC_ARTICLE)
        forged = replace(prepared, text=prepared.text.replace("Paris", "London"))
        calls = []
        async def runner(*_args, **_kwargs):
            calls.append(1)
            raise AssertionError("must never execute")
        with self.assertRaises(ValueError):
            await verify_article_claims(
                None, prepared=forged, policy=MultiClaimPolicy(max_verifications=1),
                unified_runner=runner,
            )
        self.assertFalse(calls)


class IsolatedHttpContracts(unittest.TestCase):
    """Real Pydantic/ASGI boundary with explicit auth/DB test substitutes."""

    @classmethod
    def setUpClass(cls):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from apps.api.routes import article_verification
        from apps.api.db.session import get_db_session
        from apps.api.core.service_auth import require_internal_verification

        cls.route = article_verification
        app = FastAPI()
        app.include_router(article_verification.router, prefix="/api/v1")
        app.dependency_overrides[get_db_session] = lambda: object()
        app.dependency_overrides[require_internal_verification] = lambda: "synthetic-test-user"
        cls.client = TestClient(app, follow_redirects=False)
        cls.url = "/api/v1/article/verify"

    @classmethod
    def tearDownClass(cls):
        cls.client.close()

    def request(self, **overrides):
        return {"kind": "pasted", "text": "a" * 120, **overrides}

    def test_get_is_post_only(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 405)
        self.assertIn("POST", response.headers.get("allow", ""))

    def test_flag_disabled_prevents_work(self):
        async def forbidden(*_a, **_kw):
            self.fail("model invoked when preview disabled")
        with patch.dict(os.environ, {"ARTICLE_VERIFICATION_ENABLED": "false"}), patch.object(
            self.route, "verify_pasted_article", forbidden
        ):
            response = self.client.post(self.url, json=self.request())
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("a" * 120, response.text)

    def test_reject_url_and_forged_publisher(self):
        with patch.dict(os.environ, {"ARTICLE_VERIFICATION_ENABLED": "true"}):
            for data in (self.request(kind="url"), self.request(publisher="trusted"),
                         self.request(text="too short")):
                with self.subTest(data=list(data)):
                    response = self.client.post(self.url, json=data)
                    self.assertEqual(response.status_code, 422)

    def test_byte_limit_before_model(self):
        async def forbidden(*_a, **_kw):
            self.fail("model invoked for oversized UTF-8 input")
        with patch.dict(os.environ, {"ARTICLE_VERIFICATION_ENABLED": "true"}), patch.object(
            self.route, "verify_pasted_article", forbidden
        ):
            response = self.client.post(self.url, json=self.request(text="é" * 7000))
        self.assertEqual(response.status_code, 413)

    def test_success_is_no_store_and_plaintext_not_echoed(self):
        async def synthetic_report(*_a, **_kw):
            return {"synthetic": True, "source_kind": "USER_SUPPLIED_ONLY"}
        with patch.dict(os.environ, {"ARTICLE_VERIFICATION_ENABLED": "true"}), patch.object(
            self.route, "verify_pasted_article", synthetic_report
        ):
            response = self.client.post(self.url, json=self.request())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("cache-control"), "no-store")
        self.assertEqual(response.headers.get("x-content-type-options"), "nosniff")
        self.assertNotIn("a" * 120, response.text)

    def test_backend_failure_is_sanitized(self):
        async def fails(*_a, **_kw):
            raise RuntimeError("SECRET_ARTICLE_CONTENT_PRIVATE")
        with patch.dict(os.environ, {"ARTICLE_VERIFICATION_ENABLED": "true"}), patch.object(
            self.route, "verify_pasted_article", fails
        ):
            response = self.client.post(self.url, json=self.request())
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("SECRET_ARTICLE", response.text)


if __name__ == "__main__":
    unittest.main()
