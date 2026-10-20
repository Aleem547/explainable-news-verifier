# Phase 13E.3 — Pasted Article Preparation

## Scope

Pure, in-memory preparation of **user-supplied plain text** for future factual claim extraction (13E.4).
This is a preparation component, **not** a completed public article verification feature.

### Inputs and limits

- Plain-text article and optional user-supplied title; article text is required.
- Default policy: 100–100,000 normalized characters, up to 400,000 raw UTF-8 bytes, at most 500 paragraphs. Title is at most 300 characters.
- Normalize Unicode (NFC), whitespace and paragraph separators while retaining paragraph boundaries.
- Reject HTML markup, unsafe control/format characters, malformed Unicode, invalid policy bounds, and oversized input. The API must independently impose request-body limits before buffering an HTTP request.

### Output and provenance

- Immutable `PreparedPastedArticle` with normalized text, exact-input and normalized-content SHA-256 digests, paragraph count, normalized title (optional), and server-side time.
- Explicit `USER_PASTED_PLAIN_TEXT` / `USER_SUPPLIED_ONLY` provenance.
- No publisher domain, document URL, independently-verified flag, or eligibility as independent evidence.
- `find_duplicate_pasted_articles` detects exact normalized duplicates **only among up to 20 supplied items in a local batch**. This is not web-scale deduplication or publisher-dependency proof.
- `validate_prepared_pasted_article` checks integrity and rejects forged verified/source metadata. A hash is an integrity fingerprint, **not** proof of authorship or truth.

### Security and privacy boundaries

- No network requests, database writes, model inference, telemetry, or logging of input text.
- This module does not interpret user text as instructions; future NLI/claim-extraction steps must continue treating it as untrusted data.
- Caller must enforce authentication, body-size limits, rate/concurrency quotas, privacy retention, and user consent in 13E.7.
- Pasted content must never be promoted into independently published news evidence, regardless of copied URLs or source claims inside the text.
- `received_at` is server-controlled; don't expose it as a user-provided field.
- Users may paste copyrighted text; the production product requires an appropriate retention and rights policy.

### Local verification

```powershell
& .\scripts\phase13e3\run_local_pasted_article_tests.ps1
& .\scripts\phase13e3\run_local_pasted_article_tests.ps1 -IncludeRegressions

git diff --check
git status -sb
```

All tests use synthetic text, are offline, and require no Docker, AWS, or APIs.
Next: Phase **13E.4 Factual Claim Extraction**.
