# Submission and Live Demo Guide

## One-minute introduction

"Explainable News Verifier is an evidence-first AI application that takes a factual claim, retrieves candidate passages from an indexed FEVER/Wikipedia corpus, and uses a DeBERTa-based natural-language inference model to classify how each passage relates to the claim. Unlike an opaque true/false classifier, it displays the retrieved evidence, which passages were accepted, why others were rejected, and when the evidence is insufficient. The Next.js frontend is deployed on Vercel and the FastAPI inference system is deployed on AWS EC2 behind HTTPS."

## Recommended demo sequence

1. Open https://explainable-news-verifier.vercel.app and sign in using the configured Google authentication.
2. Navigate to **Verify a Claim**.
3. Enter `The Eiffel Tower is located in Paris.` and show **Supporting evidence**, the source page, the accepted passage and scoring explanation.
4. Enter `The Eiffel Tower is located in London.` and show **Refuting evidence** with the accepted contradiction.
5. Enter `The Eiffel Tower contains a secret laboratory on its 200th underground floor.` and show **Insufficient evidence** (abstention, not a verified truth assertion).
6. Point to the **Evidence limitation** notice: the live verdict is provisional and does not establish independent external corroboration.

If a live request is slow or a rate limit occurs, use screenshots captured during the verified functioning state rather than disabling security or bypassing the backend.

## Observed manual test results

| Test | Verdict observed | Inference time shown |
| --- | --- | ---: |
| Eiffel Tower — Paris | `SUPPORTING_EVIDENCE` | 5.1 seconds |
| Eiffel Tower — London | `REFUTING_EVIDENCE` | 4.9 seconds |
| Eiffel Tower — imaginary underground laboratory | `INSUFFICIENT_EVIDENCE` | 8.2 seconds |

These are examples from one round of live tests; they are **not** statistically meaningful performance measurements.

## Suggested screenshots to include in the report

1. Homepage with production deployment label and verification pipeline section.
2. Supporting-evidence result with accepted passage and reason.
3. Refuting-evidence result with accepted contradiction.
4. Insufficient-evidence result showing abstention and neutral passages.
5. Vercel deployment dashboard showing latest successful `main` production deployment.
6. Sanitized AWS `docker ps` showing the five running containers. Do not capture `.env.production` contents or secrets.
7. GitHub repository and final documentation commit.

## Submission checklist

- [ ] Live production URL works in a fresh browser session.
- [ ] Google sign-in and claim verification tested once after the last deployment.
- [ ] README accurately explains what is implemented and what remains limited.
- [ ] Architecture diagram included and renders correctly on GitHub.
- [ ] No secrets, private keys, credentials or raw model artifacts committed accidentally.
- [ ] Repository `main` contains the final frontend and deployment documentation.
- [ ] Demonstration screenshots saved in a labeled folder.
- [ ] Final project report exported to the format required by the institution.
- [ ] Source archive or repository URL included with submission.
- [ ] Known limitation (single-corpus provenance, no independent cross-source corroboration) explained clearly.

## Viva / interview questions

**Why not simply classify news as true or false?** A retrieved evidence trail is easier to audit and makes uncertainty explicit.

**What is NLI?** Natural-language inference assesses whether a passage entails, contradicts or is neutral toward the input claim.

**What does a score of 0.94 mean?** It describes the model's per-pair relation prediction, **not** a 94% probability that the claim is true.

**What is the main research limitation?** The currently demonstrated evidence originates from a single Wikipedia-derived corpus; independent publisher-level corroboration has not been established.

**How does your production stack work?** Vercel serves Next.js and handles user authentication and the server-side verification request. Caddy terminates HTTPS on AWS EC2 and forwards authorized requests to the FastAPI service, which performs retrieval, NLI and aggregation.

**Why have an insufficient-evidence verdict?** Absence of admissible decisive evidence should not be treated as confirmation or refutation.
