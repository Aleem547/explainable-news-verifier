# Phase 13E.4 — Literal factual-claim candidate extraction

**Status:** Offline implementation, pending validation on the Windows development branch. This is NOT a trained claim detector or a factual-truth classification system.

## Integration contract

`apps.api.services.article_claim_candidates.extract_article_claim_candidates(prepared=...)`
accepts **only** the in-memory trusted prepared objects produced by:

- Phase 13E.3 `prepare_pasted_article(...)`; or
- Phase 13E.2 `prepare_discovered_article_url(...)` after trusted discovery and publisher permission checks.

Never construct `PreparedArticleUrl` using arbitrary client input, never place publisher-approved flags in request JSON, and never expose this module directly as a public API endpoint. This phase performs **no external requests, no database changes, no model inference, no filesystem writes**. A public route, quotas and authentication are Phase 13E.7.

Output is a frozen `ClaimCandidateReport` containing `ClaimCandidate` items with exact, non-paraphrased `literal_text` and `start_char`/`end_char` offsets into the original prepared article text (Python Unicode codepoint offsets, end exclusive). Source SHA-256 identity, `source_kind`, source URL/domain if genuinely fetched, deterministic candidate fingerprint, repeat locations, and attributed-language flag are included. Do not display candidate IDs as confidence scores. Counts of omitted/filter categories do not reveal article contents.

**Security/provenance:** Pasted text has `USER_SUPPLIED_ONLY` provenance and is never eligible as independent evidence. Fetched text is still unverified content, and publisher information is valid only insofar as it originates from the trusted Phase 13E.2 preparation service. No confidence/probability of factual correctness, independence, source reliability, or corroboration is asserted. Hash integrity is checked, but a matching hash alone cannot authenticate publisher identity. Protect untrusted article text from becoming instructions to an LLM or shell.

## Heuristic behavior and limits

- Offline deterministic sentence splitting preserves source offsets. Handles ordinary sentences, paragraphs, decimals and a small list of common abbreviations. It is **not** a linguistic sentence tokenizer for arbitrary multilingual text.
- A conservative lexical heuristic selects assertive statements with an assertion word and a named entity or numeric anchor. Filters common speculative/opinion phrasing, questions, context-only pronouns, fragments, overly long sentences, and obvious repeats. Mentions of an assertion word do **not** prove a sentence is factual.
- The original source passage, including `According to ...` or other reporting attribution, is retained unchanged, preventing quoted assertions from becoming unconditional claims.
- Normalized lexical duplicates are grouped **within the same article only**. Negations and changed numerals remain distinct. This is not semantic equivalence, cross-publisher syndication analysis, or independence certification.
- Defaults: up to 500,000 article characters, 3,000 sentence spans, 20 retained candidates, 30–500 characters per sentence, and a 2,000,000-byte UTF-8 text limit. Too many sentence spans fails closed; exceeding the candidate cap records `omitted_for_limit`.
- Heuristics may miss real claims or accept unsuitable statements. The next steps (13E.5/13E.6) must support abstention, multi-claim verification, reporting, and later evaluation in Phase 13F.

## Local verification

In VS Code PowerShell from the repo root:

```powershell
& .\scripts\phase13e4\run_local_claim_candidates.ps1
& .\scripts\phase13e4\run_local_claim_candidates.ps1 -IncludeRegressions
git diff --check
git status -sb
```

Expected: **46** new unit tests. With regressions: **49** Phase 13E.3, **39** Phase 13E.2, and **36** Phase 13E.1 tests, for **170** test cases total if all are installed and passing. These are synthetic offline tests; they do not establish extraction accuracy, real news retrieval success, or source independence. Do not merge into `main` or deploy to AWS until all later phases and the final release checks pass.

## Example

Input prepared article text: `NASA launched the Artemis program in 2017. It was reviewed later.` (embedded in a sufficiently long article to pass upstream preparation rules).

Candidate: `NASA launched the Artemis program in 2017.` with offsets and `UNVERIFIED_CANDIDATE`. The pronoun-dependent second sentence is conservatively skipped. This is a **candidate** to verify against external evidence, not a verification result.
