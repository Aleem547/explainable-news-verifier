# Authenticated operator reviews of reporting origins

This feature adds a qualified operator assessment for an exact claim and pair of
captured evidence inputs. It does not certify the publisher, establish factual
truth, or change NLI admission. `REVIEWED_DISTINCT_REPORTING` means an authorized
operator recorded a documented reporting-origin judgment. The legacy factual
corroboration and independently-verified flags remain false, and article-wide
truth verdicts and probabilities remain unavailable.

## Trust and evidence binding

The API reads a private server-side store selected by `ORIGIN_REVIEW_STORE`.
Without this variable, existing behavior is preserved. Each record is protected
by HMAC-SHA256 using a locally generated random per-operator key. Authority comes
from the OS-protected registry of keys and its access controls; it does not come
from a label supplied by a browser or an authenticated publisher identity.
The API and operator registry share a verification secret. This is not a public
key signature or independent third-party attestation.

The record binds the exact claim hash, stance, passage and document-version IDs,
parent passage and fetch-observation IDs, input and snapshot hashes, offsets,
URLs, and domains. Only eligible admitted paragraphs in distinct candidate
groups can receive this assessment. New claim text or snapshots require a new
record. Missing records are pending. Invalid, expired, revoked, or superseded
records cannot produce a positive assessment. The presentation contract checks
the current private record again before serializing the report.

The browser receives the qualified decision, aggregate counts, binding and
record fingerprints, and validity dates. It receives no signing key, MAC,
operator identity, private notes, or private reference checklist. The frontend
validates the response structure; cryptographic authority is checked by the API.

## Private store setup

Use an absolute private directory outside every Git checkout. Restrict access
to the operator and API service account using OS permissions. On Windows,
review the directory's NTFS ACLs; Python chmod does not establish an NTFS access
policy. On production Linux, provision a protected directory and mount the
review store read-only for the API process where practical. Do not commit or
upload trust.json, history, signing records, or private review drafts.

From the project root, using the project's Python interpreter:

```powershell
$reviewStore = Join-Path $env:LOCALAPPDATA "ExplainableVerifier\origin-review-store"
& .\.venv\Scripts\python.exe tools/reporting_origin_review.py init --store $reviewStore --reviewer-label aleem.operator
```

Initialization prints a key ID, never its secret. Configure `ORIGIN_REVIEW_STORE`
only in the intended API service environment and restart that API normally.
The installer and test runner do not edit environment files or production
settings. Persistent production activation is a separate deployment step.

## Draft, review, sign, and revoke

Generate a fresh public report with this feature enabled. Older reports without
the exact pair metadata cannot be approved by this tool. `template` accepts a
public report JSON or a completed result ZIP containing integration_report.json.
Keep the draft in the protected review directory.

```powershell
& .\.venv\Scripts\python.exe tools/reporting_origin_review.py template --report "C:\path\result.zip" --out "$reviewStore\draft.json"
& .\.venv\Scripts\python.exe tools/reporting_origin_review.py reviewers --store $reviewStore
& .\.venv\Scripts\python.exe tools/reporting_origin_review.py sign --store $reviewStore --draft "$reviewStore\draft.json" --key-id "KEY_ID_FROM_SETUP" --valid-days 7
```

The draft defaults to INCONCLUSIVE. Distinct-reporting approval requires an
explicit decision, a reason, and all five documented checklist sections:
left_original_reporting, right_original_reporting, editorial_control,
syndication_and_wire, and shared_primary_source. Each section requires a written
explanation and HTTPS references with captured reference SHA-256 hashes. The
operator must actually inspect and preserve those supporting captures privately.
The tool validates the checklist structure; it does not download references or
decide whether their contents establish independence. Different domains or
similar statements alone are insufficient. Approval additionally requires the
`--confirm-distinct-reporting-review` flag. Validity is 1 to 30 days, default 7.

`DEPENDENCY_DOCUMENTED` requires documented supporting references. Keep the
decision INCONCLUSIVE when the source history cannot be established.
Obtain a new report after signing or revoking; an already displayed report is a
snapshot of the checks performed when the server constructed it.

```powershell
& .\.venv\Scripts\python.exe tools/reporting_origin_review.py revoke --store $reviewStore --record-id "RECORD_UUID"
& .\.venv\Scripts\python.exe tools/reporting_origin_review.py revoke --store $reviewStore --key-id "KEY_ID_FROM_SETUP"
```

Replacements invalidate prior records for that scope. Revoked keys remain
inactive. Back up the protected store according to the service's backup policy.
For key rotation, revoke the old key, provision a new protected store/key, and
reissue needed reviews; approvals are not silently transferred. A stale writer
lock requires an operator to confirm no writer remains before removing it.

## Validation and limits

The delivered batch uses a private temporary test store outside the repository,
passes its path only to the real local API child, and deletes it after that API
has stopped. Live TPR/WSWS requests receive only a signed INCONCLUSIVE test record
to exercise binding and authentication. This is test metadata, not a completed
human source review. Positive approval fixtures use fictional example domains.

The combined runner separately checks the production build and browser UI, then
uses Next development mode for the local HTTP Google-signed-in flow while the
API retains staging authentication and quotas. No production HTTPS requirement
is weakened. Temporary article storage uses a real PostgreSQL rollback
transaction. Real publisher independence, benchmark quality, production load,
and public release readiness are not certified by this feature or its tests.
