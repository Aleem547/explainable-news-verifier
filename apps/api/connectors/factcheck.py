"""Google Fact Check Tools: retrieve published *third-party* claim reviews."""

from datetime import UTC, datetime
from typing import Any

from apps.api.connectors.contracts import (
    ContentKind,
    DiscoveryRequest,
    DiscoveryResult,
    ExternalDiscoveryHit,
    Provider,
)
from apps.api.connectors.http_client import ConnectorError, ProviderHttpClient
from apps.api.connectors.normalization import article_identity, string_value, timestamp

FACTCHECK_ENDPOINT = "https://factchecktools.googleapis.com/v1alpha1/claims:search"


class GoogleFactCheckConnector:
    def __init__(self, http: ProviderHttpClient, *, api_key: str):
        if not api_key.strip():
            raise ValueError("Google Fact Check Tools API key is required for live requests.")
        self._http = http
        self._api_key = api_key.strip()

    async def search(self, request: DiscoveryRequest) -> DiscoveryResult:
        data = await self._http.get_json(
            provider=Provider.GOOGLE_FACTCHECK,
            endpoint=FACTCHECK_ENDPOINT,
            parameters={
                "query": request.query.strip(),
                "pageSize": request.limit,
                "languageCode": request.language.lower(),
            },
            headers={"x-goog-api-key": self._api_key},
        )
        raw_claims: Any = data.get("claims", [])
        if not isinstance(raw_claims, list):
            raise ConnectorError(Provider.GOOGLE_FACTCHECK, "invalid_claims_structure")
        hits: list[ExternalDiscoveryHit] = []
        seen: set[str] = set()
        now = datetime.now(UTC)
        for claim in raw_claims:
            if not isinstance(claim, dict):
                continue
            review_list = claim.get("claimReview", [])
            if not isinstance(review_list, list):
                continue
            for review in review_list:
                if not isinstance(review, dict):
                    continue
                identity = article_identity(review.get("url"))
                if identity is None or identity[0] in seen:
                    continue
                seen.add(identity[0])
                publisher: Any = review.get("publisher")
                if not isinstance(publisher, dict):
                    publisher = {}
                claim_text = string_value(claim.get("text"), limit=4000)
                title = string_value(review.get("title")) or claim_text
                if title is None:
                    continue
                hits.append(
                    ExternalDiscoveryHit(
                        provider=Provider.GOOGLE_FACTCHECK,
                        kind=ContentKind.FACT_CHECK_REVIEW,
                        url=identity[0],
                        publisher_domain=identity[1],
                        publisher_name=(
                            string_value(publisher.get("name"), limit=255) or identity[1]
                        ),
                        title=title,
                        snippet=claim_text,
                        discovered_at=now,
                        published_at=timestamp(review.get("reviewDate")),
                        language=string_value(review.get("languageCode"), limit=16),
                        matched_claim=claim_text,
                        claimant=string_value(claim.get("claimant"), limit=500),
                        rating_text=string_value(review.get("textualRating"), limit=200),
                        claim_date=timestamp(claim.get("claimDate")),
                    )
                )
                if len(hits) >= request.limit:
                    break
            if len(hits) >= request.limit:
                break
        next_page_token = data.get("nextPageToken")
        return DiscoveryResult(
            provider=Provider.GOOGLE_FACTCHECK,
            query=request.query,
            hits=tuple(hits),
            next_page_token=next_page_token if isinstance(next_page_token, str) else None,
        )
