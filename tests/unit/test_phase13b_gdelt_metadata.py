"""Offline tests: python -m unittest discover -s tests/unit -p 'test_phase13b_gdelt_metadata.py' -v"""

import json
import unittest
from urllib.parse import parse_qs, urlsplit

from apps.api.services.gdelt_metadata import (
    ArticleCandidate,
    DiscoveryFormatError,
    build_article_list_url,
    parse_article_list,
)


class GdeltMetadataTests(unittest.TestCase):
    def test_fixed_endpoint_and_encoded_query(self):
        url = build_article_list_url("The Eiffel Tower is located in Paris", limit=4)
        parsed = urlsplit(url)
        self.assertEqual(parsed.hostname, "api.gdeltproject.org")
        self.assertEqual(parsed.scheme, "https")
        query = parse_qs(parsed.query)
        self.assertEqual(query["mode"], ["artlist"])
        self.assertEqual(query["format"], ["json"])
        self.assertEqual(query["maxrecords"], ["4"])
        self.assertEqual(query["query"], ["Eiffel Tower located Paris"])

    def test_query_cannot_override_endpoint(self):
        url = build_article_list_url("Paris?mode=html&format=xml")
        self.assertEqual(urlsplit(url).hostname, "api.gdeltproject.org")
        self.assertEqual(parse_qs(urlsplit(url).query)["mode"], ["artlist"])

    def test_query_bounds(self):
        for claim in ("  ", "x" * 301, "the and the"):
            with self.subTest(claim=claim[:10]), self.assertRaises(ValueError):
                build_article_list_url(claim)
        for limit in (0, 21, True, -1):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                build_article_list_url("Eiffel Tower Paris", limit=limit)
        with self.assertRaises(ValueError):
            build_article_list_url("Eiffel Tower Paris", timespan="alltime")

    def test_only_public_https_metadata_candidates(self):
        articles = [
            {"url": "https://news.example.com/story?ref=1#section", "title": " Example story ",
             "domain": "attacker.net", "seendate": "20261018T090000Z", "language": "English"},
            {"url": "https://news.example.com/story?ref=1", "title": "Duplicate"},
            {"url": "http://other.example.com/story", "title": "Insecure"},
            {"url": "https://localhost/private", "title": "Localhost"},
            {"url": "https://127.0.0.1/private", "title": "IP"},
            {"url": "https://u:p@news.example.com/article", "title": "Credential URL"},
            {"url": "https://news.example.com:8080/admin", "title": "Unexpected port"},
        ]
        result = parse_article_list(json.dumps({"articles": articles}))
        self.assertEqual(len(result), 1)
        candidate = result[0]
        self.assertIsInstance(candidate, ArticleCandidate)
        self.assertEqual(candidate.url, "https://news.example.com/story?ref=1")
        self.assertEqual(candidate.publisher_domain, "news.example.com")
        self.assertEqual(candidate.title, "Example story")
        self.assertEqual(candidate.seen_at.year, 2026)
        self.assertEqual(candidate.seen_at.tzinfo.utcoffset(None).total_seconds(), 0)
        self.assertFalse(candidate.content_obtained)
        self.assertFalse(candidate.evidence_accepted)
        self.assertFalse(candidate.source_independence_verified)

    def test_malformed_provider_response_is_not_no_evidence(self):
        for body in (b"<html>Too Many Requests</html>", "{}", '[]', '{"error":"rate limit"}', ""):
            with self.subTest(body=body), self.assertRaises(DiscoveryFormatError):
                parse_article_list(body)
        with self.assertRaises(DiscoveryFormatError):
            parse_article_list(b" " * 1_000_001)

    def test_empty_article_list_is_valid(self):
        self.assertEqual(parse_article_list('{"articles": []}'), [])

    def test_result_cap(self):
        items = [{"url": f"https://news.example.com/{i}", "title": str(i)} for i in range(6)]
        result = parse_article_list(json.dumps({"articles": items}), limit=3)
        self.assertEqual(len(result), 3)

    def test_unavailable_timestamp_is_not_invented(self):
        result = parse_article_list('{"articles":[{"url":"https://example.com/a","title":"A","seendate":"bad"}]}')
        self.assertIsNone(result[0].seen_at)


if __name__ == "__main__":
    unittest.main()
