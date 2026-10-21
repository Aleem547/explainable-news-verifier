"""13E.7: Pasted-article request adapter for existing Phase 13E services.

The user-supplied text is NEVER stored, logged, or added to evidence retrieval.
Keep expensive calls behind the caller's authentication, quotas, and CPU limits.
"""

from __future__ import annotations

from typing import Any


async def verify_pasted_article(
    session: Any,
    *,
    text: str,
    title: str | None = None,
    max_verifications: int = 1,
) -> Any:
    """Return Phase 13E.6 report. No aggregate factual truth decision.

    Imports are local so clients importing the API module don't eagerly load ML.
    Injectable runner is deliberately NOT exposed to untrusted API callers.
    """
    if type(max_verifications) is not int or not 1 <= max_verifications <= 2:
        raise ValueError("invalid_article_verification_budget")
    from apps.api.services.pasted_article_preparation import (  # noqa: PLC0415
        PastedArticlePolicy,
        prepare_pasted_article,
    )
    from apps.api.services.article_multi_claim_verification import (  # noqa: PLC0415
        MultiClaimPolicy,
        verify_article_claims,
    )
    from apps.api.services.article_level_reporting import (  # noqa: PLC0415
        build_article_level_report,
    )

    prepared = prepare_pasted_article(
        pasted_text=text,
        user_supplied_title=title,
        policy=PastedArticlePolicy(
            min_text_chars=100,
            max_text_chars=8_000,
            max_input_utf8_bytes=10_000,
        ),
    )
    report = await verify_article_claims(
        session,
        prepared=prepared,
        policy=MultiClaimPolicy(
            max_verifications=max_verifications,
            wikipedia_top_k=3,
            external_top_k=4,
            nli_threshold=0.90,
        ),
    )
    return build_article_level_report(prepared=prepared, verification=report)
