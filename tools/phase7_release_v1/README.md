# Explainable News Verifier — consolidated AWS + Vercel release (v4)

This package releases the application already accepted by your Phase 6 integration
run. It targets your existing Windows project and existing AWS EC2 + Vercel setup.
It adds no paid API, service, domain, or cloud resource. Existing hosting billing
continues under your current AWS and Vercel plans.

## What has been accepted

- Local Phase 6 receipt: 877a64ca8c5d4b989bdaeb0e608299a2.
- 924 backend/API/SQL checks, one skipped; 190 frontend checks; 27 production
  browser checks; production build and nine live HTTP controls passed.
- All 317 application source fingerprints match the accepted installer.
- AWS database is already at f13f2d8gin20261024.
- AWS calibration matches the accepted CPU model calibration.
- AWS currently runs verifier-api:phase13f-01777cf with article verification
  disabled. The new trusted review and corroboration modules are absent.

Local acceptance does not certify the production release. This package must still
run on your actual AWS host, and the final Vercel Google sign-in test must pass.
See preparation_validation.json for the checks actually executed while packaging.

## 1. Windows PowerShell: prepare and publish

Extract this ZIP into a new folder in Downloads. From PowerShell, run:

    & 'C:\Projects\explainable-news-verifier\.venv\Scripts\python.exe' 'FULL_PATH_TO_EXTRACTED_FOLDER\release_tool.py' prepare --repo 'C:\Projects\explainable-news-verifier' --publish

Use the full path to the extracted release_tool.py. The chat response includes
a complete block that extracts the ZIP and runs this command for you.

The preparer:

1. Verifies the accepted 317 application files, original Git checkout, base
   commit 01777cfc367f5dfc8d56ecfe10c1c828714d6c6e, and unchanged build dependencies.
2. Uses a separate temporary Git index to make a new release branch containing
   the accepted sources and this release tool. It preserves your current branch,
   working files, and staged changes; unrelated uncommitted work is excluded.
3. With --publish, pushes exactly that new branch to the existing
   Aleem547/explainable-news-verifier GitHub repository, using your existing Git
   authentication. It never force-pushes or updates main/master.
4. Prints AWS_RELEASE_COMMAND. It also saves a preparation receipt under
   artifacts/phase7_release in your Windows project.

Without --publish, it only prepares the local release branch. A GitHub-connected
Vercel project may build a Preview for the new branch; check the exact commit.

## 2. AWS Ubuntu browser terminal: run the complete API release

Paste the exact printed AWS_RELEASE_COMMAND into the AWS black terminal. Include
its final "; #" so a duplicate paste on the same line is ignored.

This one command stages the candidate, tests it, and replaces the API only after
the stage passes. Keep the terminal open until STATUS=AWS_API_RELEASED appears.
STAGED_API_READY is an intermediate result; the command continues automatically.
You do not need to paste the intermediate PROMOTE_COMMAND.

The staging tool fetches the pinned release commit, verifies its 317 sources, and
extracts build inputs outside the live server checkout. It preserves the dirty
calibration file and all five original Compose files, including the separate
phase13f-01777cf-api-runtime.yml override.

The recorded Compose launch directory is preserved for staging, replacement, and
rollback. It can differ from the Git checkout root. The tool captures the live
API's exact startup command into a private override and verifies the resolved
executable arguments, user, working directory, environment, and mounts before
building. Original Compose files are preserved. Compose null/default command
semantics are handled explicitly.

Before replacing anything, it:

- Checks the live image, production flags, database revision, calibration,
  disk space, and available memory.
- Resolves the five Compose files privately and verifies their API environment,
  mounts, user, and working directory against the running API. Adds the captured
  startup override, then verifies the complete effective process as well.
- Verifies the running API and ML Python files against the original Git commit.
  Reuses that working runtime image and replaces application code only. The
  Dockerfile, pyproject.toml and uv.lock must match the original build inputs.
  No dependency installation or network-enabled build step is added.
- Creates a persistent private review store outside Git, with a new operator
  key, or validates an already-created store. No reviews are signed or seeded.
  The API receives a read-only store mount.
- Saves an original-image tag and private rollback configuration. It verifies
  that the rollback configuration resolves to the original settings.
- Starts a separate candidate API on the existing Docker network without a
  public port. It limits candidate memory, checks real dependency readiness,
  confirms unauthenticated article requests are rejected, and sends two
  authorized internal operator requests through the real model and article API.
  These requests may create normal usage/audit records. They do not seed news
  evidence or source-origin approvals.

The stage requires MODEL_HTTP_200=true and ARTICLE_HTTP_200=true before promotion.
A failed stage leaves the production API running.
Do not share PRIVATE_* files: they contain runtime configuration or logs.
PUBLIC_RESULT.json and the printed status are safe diagnostic outputs.

After the stage passes, the same command automatically rechecks the live
container, staged image, database revision, calibration, and original files.

It removes its own temporary candidate, then recreates only the existing Compose
api service using the original five files plus the private startup and reviewed
API overrides. PostgreSQL,
Redis, Qdrant, Caddy, models, corpus, calibration, authentication, and existing
volumes are retained. The API restart can briefly interrupt requests.

The new override enables ARTICLE_VERIFICATION_ENABLED=true and points
ORIGIN_REVIEW_STORE at the read-only private store. Readiness, authentication
rejection, the real model, and article verification are checked again. If these
checks fail after replacement, the tool attempts to restore the saved original
API automatically.

Success is STATUS=AWS_API_RELEASED. Continue to the Vercel step below only after
that final status. A STOPPED or ROLLBACK_NEEDS_ATTENTION status requires inspecting
the safe terminal output before proceeding.

The terminal also prints ROLLBACK_COMMAND. It restores the old API image and
settings using the private snapshot. It does not delete review keys, database
records, models, corpus, or your original deployment files.

For an optional stage-only workflow, use aws_stage_command from the Windows
preparation receipt, then run the printed PROMOTE_COMMAND manually. To stop an
unpromoted candidate, replace "promote" with "cancel" in that command. Only this
release's temporary container is removed.

## 3. Existing Vercel project and final browser check

In the existing explainable-news-verifier project:

1. Keep your current AWS HTTPS API_BASE_URL, INTERNAL_API_TOKEN, Google OAuth
   configuration, and authentication secret.
2. Set the server-side ARTICLE_VERIFICATION_ENABLED variable to true for
   Production. Do not prefix it with NEXT_PUBLIC_.
3. Find the successful Preview deployment from the exact release branch/commit
   printed by the Windows preparer. Review its build result.
4. In Deployments, open that deployment's menu and choose Promote to Production.
   Vercel rebuilds using Production environment variables. Wait for success.
   Your existing production domain and Google callback domain stay the same.
5. On https://explainable-news-verifier.vercel.app, sign in with Google, check the
   existing single-claim verifier, then open /article and submit:

       Chandrayaan-3 landed on the Moon.
       This background paragraph explains the scope of this local check without adding independent evidence.

Expect one assessed claim. External results depend on the real evidence stored
in production. Pending review and insufficient evidence can be valid results;
do not copy temporary integration evidence or approvals into production.

If the new web deployment fails, use Vercel's rollback to the previous working
Production deployment. The AWS rollback command is separate.

Only certify the release after actual AWS and authenticated Vercel tests pass.
No preview build substitutes for the final Google sign-in test.

## Operator source-origin review

Review keys remain on AWS. A different operator container can write the private
store; the API container can only read it. The initial authorized label is
aleem.operator. No positive origin assessment is created by installation.

With the same release_tool.py and printed state file, run:

    python3 /path/to/release_tool.py review --state /path/to/state.json reviewers

Create a draft from the actual authenticated article JSON on Windows using the
already-installed tools/reporting_origin_review.py:

    .\.venv\Scripts\python.exe tools\reporting_origin_review.py template --report article.json --out draft.json --pair-index 0

Review the exact claim, paragraph hashes, reporting origin, editorial control,
syndication, and shared primary sources. An original-reporting assessment needs
the documented checks and reference hashes required by the existing tool.
Transfer only the public draft to AWS using your existing SSH/SCP access.

Sign a completed draft on AWS:

    python3 /path/to/release_tool.py review --state /path/to/state.json sign --draft /path/to/draft.json --key-id OPERATOR_KEY_ID --confirm-distinct-reporting-review --valid-days 7

Revoke an individual record or a reviewer:

    python3 /path/to/release_tool.py review --state /path/to/state.json revoke --record-id RECORD_UUID
    python3 /path/to/release_tool.py review --state /path/to/state.json revoke --key-id OPERATOR_KEY_ID

The confirmation flag is for a completed operator assessment. HMAC authenticates
the authorized operator record; it does not authenticate a publisher or prove
that a claim is true. Reviews bind to the exact claim and evidence inputs, expire,
and can be revoked. Repeated reporting stays pending unless separately reviewed.

The preview assesses one factual claim per request. It does not produce an
article-wide true/false verdict or a factual-truth probability. Agreement and NLI
confidence do not establish editorial independence.

## Primary documentation

- https://docs.docker.com/reference/cli/docker/compose/config/
- https://docs.docker.com/compose/how-tos/multiple-compose-files/merge/
- https://docs.docker.com/reference/cli/docker/compose/up/
- https://git-scm.com/docs/git-update-index
- https://git-scm.com/docs/git-commit-tree
- https://vercel.com/docs/deployments/promoting-a-deployment
