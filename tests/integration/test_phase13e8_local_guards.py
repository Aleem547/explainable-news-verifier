"""Opt-in loopback-only HTTP smoke tests. No cookies, secrets, models or writes.

Run only when a LOCAL API and Next.js are already running. Requests without
credentials must be rejected before any expensive model work can start.
"""
from __future__ import annotations

import json
import os
import unittest
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


def local_base(env: str, default: str) -> str:
    value = os.getenv(env, default).rstrip("/")
    parsed = urlsplit(value)
    if parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "localhost") or parsed.username or parsed.password or parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise ValueError(f"{env} must use a loopback http://127.0.0.1:PORT address")
    return value


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


OPENER = build_opener(ProxyHandler({}), NoRedirect())
API = local_base("PHASE13E8_LOCAL_API", "http://127.0.0.1:8001")
WEB = local_base("PHASE13E8_LOCAL_WEB", "http://127.0.0.1:3000")
ARTICLE = {
    "kind": "pasted",
    "text": "The Eiffel Tower is located in Paris, France. " * 4,
}


def request(base: str, path: str, method: str, *, data=None, headers=None):
    payload = None if data is None else json.dumps(data).encode("utf-8")
    hdrs = {"Content-Type": "application/json", **(headers or {})}
    req = Request(base + path, data=payload, headers=hdrs, method=method)
    try:
        with OPENER.open(req, timeout=15) as response:
            return response.status, dict(response.headers), response.read(4096)
    except HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read(4096)
    except URLError as exc:
        raise AssertionError(f"Local server not reachable: {base}; start Docker/Next.js first") from exc


class LocalUnauthenticatedGuards(unittest.TestCase):
    def test_backend_health_is_ok(self):
        status, _headers, body = request(API, "/api/v1/ready", "GET")
        self.assertEqual(status, 200, body.decode(errors="replace"))
        self.assertTrue(json.loads(body)["ready"])

    def test_backend_article_get_not_allowed(self):
        status, headers, _body = request(API, "/api/v1/article/verify", "GET")
        self.assertEqual(status, 405)
        self.assertIn("POST", headers.get("Allow", headers.get("allow", "")))

    def test_backend_rejects_unauthenticated_article_post(self):
        status, _headers, body = request(API, "/api/v1/article/verify", "POST", data=ARTICLE)
        self.assertIn(status, (401, 403), f"Backend did not enforce service auth: {status} {body[:150]!r}")

    def test_existing_claim_endpoint_still_post_only(self):
        status, _headers, _body = request(API, "/api/v1/verify", "GET")
        self.assertEqual(status, 405)

    def test_web_rejects_unauthenticated_article_post(self):
        status, _headers, body = request(WEB, "/api/article-verification", "POST", data=ARTICLE)
        self.assertEqual(status, 401, f"Web article guard not enforced: {status} {body[:150]!r}")

    def test_web_rejects_cross_origin(self):
        status, _headers, body = request(
            WEB, "/api/article-verification", "POST", data=ARTICLE,
            headers={"Origin": "https://untrusted.example", "Sec-Fetch-Site": "cross-site"},
        )
        self.assertEqual(status, 403, f"Cross-origin response unsafe: {status} {body[:150]!r}")


if __name__ == "__main__":
    unittest.main()
