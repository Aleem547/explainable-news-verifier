"""Claim-scoped textual corroboration backed by current authorized origin reviews.

This additional policy does not issue factual truth probabilities, article-wide
verdicts, or a publisher authenticity certificate. Legacy verdicts stay intact.
"""
from dataclasses import dataclass
from hashlib import sha256

from apps.api.services.trusted_reporting_review import (
    TrustedOriginReviewSummary, require, validate_trusted_origin_review,
)

POLICY = 'reviewed-claim-corroboration-v1'


@dataclass(frozen=True, slots=True)
class ReviewedCorroboration:
    status: str
    corroboration_established: bool
    claim_sha256: str
    supporting_pair_count: int
    refuting_pair_count: int
    review_scope_sha256s: tuple[str, ...]
    review_record_sha256s: tuple[str, ...]
    evidence_passage_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]
    policy_version: str = POLICY


def decide_reviewed_corroboration(review, *, claim, refs, candidate_count):
    if review is None:
        return None
    # Re-read the active private record rather than trusting a copied summary.
    validate_trusted_origin_review(review, claim=claim, refs=refs, candidate_count=candidate_count)
    approved = tuple(p for p in review.pairs if p.decision == 'REVIEWED_DISTINCT_REPORTING')
    support = sum(p.stance == 'SUPPORT_ONLY' for p in approved)
    refute = sum(p.stance == 'REFUTE_ONLY' for p in approved)
    admitted = {r.nli_label for r in refs if r.decisive_evidence_admitted is True}
    codes = {'CLAIM_SCOPED_TEXTUAL_CORROBORATION', 'NO_ARTICLE_WIDE_TRUTH_VERDICT',
             'NLI_CONFIDENCE_IS_NOT_FACTUAL_TRUTH_PROBABILITY'}
    status = 'NOT_ESTABLISHED'
    if review.unavailable_pair_count:
        codes.add('CURRENT_ORIGIN_REVIEW_UNAVAILABLE')
    elif review.dependency_documented_pair_count:
        codes.add('DOCUMENTED_DEPENDENCY_REQUIRES_RESOLUTION')
    elif not approved:
        codes.add('NO_CURRENT_DISTINCT_REPORTING_REVIEW')
    elif admitted == {'ENTAILMENT', 'CONTRADICTION'}:
        status = 'CONFLICTING_EVIDENCE'
        codes.add('ADMITTED_COUNTEREVIDENCE_BLOCKS_ONE_SIDED_CORROBORATION')
    elif support and not refute and admitted == {'ENTAILMENT'}:
        status = 'REVIEWED_SUPPORT'
        codes.add('AUTHORIZED_DISTINCT_REPORTING_AND_ADMITTED_SUPPORT')
    elif refute and not support and admitted == {'CONTRADICTION'}:
        status = 'REVIEWED_REFUTATION'
        codes.add('AUTHORIZED_DISTINCT_REPORTING_AND_ADMITTED_REFUTATION')
    else:
        codes.add('REVIEWED_PAIRS_AND_ADMITTED_STANCES_NOT_CONSISTENT')
    return ReviewedCorroboration(
        status, status in {'REVIEWED_SUPPORT', 'REVIEWED_REFUTATION'},
        sha256(claim.encode()).hexdigest(), support, refute,
        tuple(sorted(p.scope_sha256 for p in approved)),
        tuple(sorted(p.record_sha256 for p in approved)),
        tuple(sorted({identity for p in approved for identity in (p.left_passage_id, p.right_passage_id)})),
        tuple(sorted(codes)),
    )


def validate_reviewed_corroboration(value, *, review, claim, refs, candidate_count):
    if review is None:
        require(value is None, 'corroboration_without_authorized_review')
        return
    require(type(review) is TrustedOriginReviewSummary and type(value) is ReviewedCorroboration,
            'invalid_reviewed_corroboration')
    require(type(value.corroboration_established) is bool
            and all(type(n) is int for n in (value.supporting_pair_count, value.refuting_pair_count)),
            'invalid_reviewed_corroboration_types')
    fresh = decide_reviewed_corroboration(review, claim=claim, refs=refs, candidate_count=candidate_count)
    require(value == fresh, 'reviewed_corroboration_replay_mismatch')
