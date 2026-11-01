# Reviewed claim-scoped corroboration

The optional `external_reviewed_corroboration` field adds a bounded claim-level decision. It combines the server's current authenticated origin review with the existing admitted NLI evidence. It does not change the legacy verdict, certify publishers, provide a factual-truth probability or issue an article-wide verdict.

| Status | Meaning |
| --- | --- |
| REVIEWED_SUPPORT | At least one current reviewed pair supports this exact claim, with no admitted refutation. |
| REVIEWED_REFUTATION | At least one current reviewed pair refutes this exact claim, with no admitted support. |
| CONFLICTING_EVIDENCE | Admitted opposing evidence blocks a one-direction decision. |
| NOT_ESTABLISHED | Required current origin review or consistent admitted evidence is missing. |

`corroboration_established` belongs to this qualified textual decision only. The existing `independent_corroboration_established` and `independently_verified` fields remain false, and article-wide truth fields remain null. Consumers must retain that distinction.

The decision includes the claim fingerprint, reviewed evidence IDs, authenticated record and scope fingerprints, counts and policy/reason codes. Backend presentation replays review authentication, scope, expiry, revocation and admission. Revoked or changed records cannot be reused through a cached summary. The browser checks the structural decision against the supplied references and review; cryptographic authentication remains the server's responsibility.

Public requests cannot supply review authority, this result, or the extraction policy. Existing thresholds and model calibration are retained. Default HTML extraction continues to favor precision; the integration runner explicitly selects the recall profile only for its fixed ISRO release and records the method separately.

## Documented integration case

The installer includes a fixed assistant-prepared review of separate observation streams for “Chandrayaan-3 landed on the Moon.” `SOURCE_REVIEW.md` in the installer explains the evidence, shared context, and limits. The case is chosen before inference. It may produce reviewed support only if both actual captured snapshots yield an eligible admitted support pair under the unchanged model policy.

The local runner first exercises a genuine Google-signed-in Next proxy request against the real staging-mode API and local services. It then signs the bounded review in an isolated private test store, reissues the authenticated API call, checks the positive decision, revokes the record and verifies removal of corroboration. These follow-up calls reuse the earlier validated identity in process memory; they do not perform fresh OAuth handshakes.

Temporary database content is rolled back. The retained NASA/NIST baselines and source registry are verified afterward. Public source captures remain locally under the run artifacts for audit. Ephemeral signing keys are deleted after the API exits; exported results contain no secret keys, cookies or raw identity. Consequently this validation does not leave a persistent approved review in the application's normal review store.

The package changes development source and tests only. AWS, Vercel, environment files, dependency locks and deployment settings are not modified. Production rollout remains a separate release step.
