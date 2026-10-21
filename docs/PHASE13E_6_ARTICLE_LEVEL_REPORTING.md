# Phase 13E.6 — Explainable article-level reporting

## Goal and scope

Produce a **read-only, immutable article report** from a trusted Phase 13E.5
`MultiClaimVerificationReport` and the same original prepared article. The
report organizes per-claim execution results, separated Wikipedia and stored
external-evidence findings, source references, and caveats. **It is not** an
article truth classifier, a numerical factuality score, a new model, a public
API endpoint, or evidence of editorial source independence.

Implementation:
`apps/api/services/article_level_reporting.py`

Public entry point:

```python
build_article_level_report(
    prepared=prepared_article,
    verification=multi_claim_report,
    extraction_policy=original_extraction_policy,  # optional if default used
)
```

Both arguments must come from trusted backend components. Use the same
`ClaimCandidatePolicy` that was used during Phase 13E.5 candidate extraction;
otherwise recomputed source candidates will not match and the report rejects
input. This function does not download pages, call NLI or other models, or
write to PostgreSQL. The API integration and user-level authorization/rate
limits are scheduled for 13E.7.

## Data contract

- `ArticleLevelReport`: article SHA-256, source type, optional URL/publisher,
  source and assessment timestamps; counts of candidate, assessed, unavailable,
  failed, skipped, filtered and omitted items; and an ordered claim list.
- `ArticleClaimFinding`: exact literal source text with Unicode-character
  offsets, candidate ID, duplicate locations, execution status, per-corpus
  verdict and availability, relationship, and sanitized warning codes.
- `ArticleEvidenceReference`: claim-specific reference IDs, passage UUID,
  immutable document-version UUID, original HTTPS article URL, publisher
  domain, NLI label/score, threshold decision, dependency-risk family and
  duplicate group. Source-risk groups are **not** independent-source counts.
- Wikipedia page references are **page names**, not fabricated source URLs.
- All outputs are frozen dataclasses with tuple-based collections. Do not
  treat Python object immutability as authentication, storage security, or
  evidence of correctness.

The report's `wikipedia_available_count`, `external_available_count`,
`opposing_corpus_count` and `conflicting_corpus_count` are *counts of claim
findings* only. They are **not numbers of verified claims** or a source-
independence estimate. `overall_article_truth_verdict` and
`overall_article_truth_probability` remain `None`. `independently_verified`,
`independent_corroboration_established`, and
`eligible_as_independent_evidence` remain `False`.

## Trust and failure handling

The builder recomputes Phase 13E.4 candidates from the prepared article and
rejects mismatched source fingerprints, URLs, original timestamps, offsets,
claim identifiers, counts and claim order. It revalidates each assessed or
unavailable `UnifiedVerificationReport` using the existing Phase 13E.5
validator, including the rule that editorial independence is not established.
Rejected inputs raise `ArticleReportingError` with a stable reason code; no
submitted source text is inserted into the error message.

Failed and skipped claims remain explicit and retain their exact article span.
Their underlying exceptions are never copied into the report. An unavailable
claim retains its validated evidence-path statuses, and opposing corpus
findings trigger a review warning without producing a combined truth verdict.
The article itself is never added to an external evidence corpus.

For external citations the same passage may appear in more than one claim
with different NLI results. Citation IDs include *both* the claim candidate
identity and passage UUID, so later consumers must not deduplicate them by
passage alone when displaying claim-specific NLI findings.

## Example flow

```python
prepared = prepare_pasted_article(pasted_text=article_text)
verification = await verify_article_claims(db_session, prepared=prepared)
report = build_article_level_report(prepared=prepared, verification=verification)

for claim in report.claims:
    print(claim.execution_status, claim.wikipedia_verdict,
          claim.external_verdict, claim.cross_corpus_relationship)
```

This code assumes server authorization, quotas and inference concurrency
controls are enforced by the caller. **Do not log raw pasted article text or
publish it without user authorization.** Phase 13E.6 intentionally does not
serialize or expose article content over an endpoint.

## Local validation

From Windows VS Code PowerShell in the project root:

```powershell
& .\scripts\phase13e6\run_local_article_reporting_tests.ps1
& .\scripts\phase13e6\run_local_article_reporting_tests.ps1 -IncludeRegressions
git diff --check
git status -sb
```

The runner executes 41 new tests and optionally the existing 13E.5 through
13E.1 unit suites. Tests cover claim-order and source-span consistency, valid
and opposing evidence, missing/failed/skipped claims, canonical URL
provenance, claim-specific citations, forged independence and altered hashes,
plus inheritance of earlier-phase validation. No cloud or DB test is needed
for this pure reporting layer. Full API and browser tests are in 13E.7–13E.8.

## Limitations and next steps

- Phase 13E.4's heuristic factual-claim candidate extractor can omit useful
  claims or include non-verifiable sentences; these reports reflect that input.
- NLI probabilities reflect model outputs, **not factual truth probabilities**.
- Reused or syndicated reports and unknown editorial relationships prevent
  definitive independent corroboration claims.
- Per-claim evidence references are not proof that the source is correct.
- **13E.7**: authenticated, quota-controlled API and frontend presentation,
  response-schema and privacy review.
- **13E.8**: complete real-model + PostgreSQL + browser regression and
  performance/security testing before production release.

Do not merge this Phase 13 development branch into `main` or redeploy the AWS
service until full release validation is complete.
