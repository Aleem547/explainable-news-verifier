# Phase 11C.5 — Rollback and Recovery Validation

## Objective

Validate that a reconstructed rollback API can start,
authenticate verification requests, recover after restart,
and preserve the tested inference behavior.

## Test Environment

- Original API: port 8001
- Optimized API: port 8002
- Rollback API: port 8003
- Rollback image: verifier-api:rollback-source-11c5
- Rollback container: verifier-api-11c5-rollback-test
- Dataset: FEVER Wikipedia-derived sentence corpus
- Corpus records: 4,204,186
- Execution environment: Docker, FastAPI, CPU inference

## Validation Results

| Test | Result |
|---|---|
| Source snapshot integrity | Passed |
| Rollback Docker image build | Passed |
| Rollback image source verification | Passed |
| Application import | Passed |
| Authenticated API inference | Passed |
| Original/rollback behavioral parity | Passed for tested claim |
| Container restart | Passed |
| PostgreSQL readiness | Passed |
| Redis readiness | Passed |
| Qdrant readiness | Passed |
| Post-restart authenticated inference | Passed |
| Three API readiness checks | Passed |

## Test Claim

The Eiffel Tower is located in Berlin, Germany.

Expected and observed results:

- HTTP status: 200
- Verdict: INSUFFICIENT_EVIDENCE
- Retrieved candidates: 2
- Assessed evidence: 1
- NLI label: NEUTRAL
- Accepted evidence: false
- Contribution role: NOT_DECISIVE

An insufficient-evidence verdict is not an assertion
that the claim is true.

## Recovery Procedure Validated

1. Verify the rollback image and container identity.
2. Restart only the isolated rollback test container.
3. Poll GET /api/v1/ready until dependencies are healthy.
4. Confirm PostgreSQL, Redis and Qdrant report OK.
5. Perform authenticated POST /api/v1/verify.
6. Check the verdict and selected evidence fields.
7. Confirm the original and optimized APIs remain healthy.

Rollback test endpoint:
http://127.0.0.1:8003

Readiness endpoint:
/api/v1/ready

## Recovery Observations

- The rollback container restarted successfully.
- All three API instances passed readiness checks.
- Post-restart authenticated inference passed twice.
- No behavioral differences were found in the
  selected fields for the tested claim.

## Limitations

This validates an isolated rollback exercise.
It is not a production traffic-switch test.

The parity test covers one claim and selected response
fields, not all possible claims or failure conditions.

No production recovery time objective has been certified.
Startup, authentication and dependency configuration must
be checked independently in the target environment.

Inference accuracy and cross-source corroboration were
not established by this rollback exercise.

## Safety

- Do not commit service tokens or environment secrets.
- Preserve verified recovery snapshots.
- Do not delete the original running API during testing.
- Validate production rollback separately before deployment.

## Conclusion

The reconstructed rollback API passed the scoped
functional, source-integrity, behavioral-parity and
post-restart recovery checks.

Phase 11C.5 isolated rollback validation: PASSED.
Production cutover readiness: NOT YET CERTIFIED.
