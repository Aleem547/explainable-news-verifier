# Production Deployment Runbook

## Current deployment topology

- **User-facing frontend:** Next.js hosted on Vercel at `https://explainable-news-verifier.vercel.app`.
- **API and ML inference:** Python/FastAPI Docker container hosted on AWS EC2 (Ubuntu).
- **HTTPS edge:** Caddy, using the currently configured `sslip.io` hostname and a trusted TLS certificate.
- **Containers observed in production:** `api`, `postgres`, `redis`, `qdrant`, and `caddy`.
- **ML artifacts:** CPU NLI model, model cache, FEVER data and Tantivy index provisioned on the EC2 host / mounted into the API container.

## Deployment files

The running AWS deployment uses Docker Compose layering, including:

- `infra/docker/compose.prod.yml`
- `infra/docker/compose.aws.yml`
- `infra/docker/compose.aws.test.yml` (the committed runtime bind-mount override)
- `infra/docker/compose.aws.index.yml` (the FEVER index bind-mount override)
- `infra/docker/Caddyfile.prod`

The override `compose.aws.test.yml` mounts the host `apps/api` directory into the API container read-only. **It is a known deployment workaround**; a future image build should include the necessary application code so that the override can be removed only after a verified staged deployment. Do not remove it from the running service as part of submission cleanup.

The index override maps the host FEVER/Tantivy index into the API container. The required datasets, indexes and weights are **not captured by the Compose YAML alone**.

## Read-only health checks on AWS Ubuntu

```bash
cd ~/explainable-news-verifier

git status -sb
sudo docker ps --format 'table {{.Names}}\t{{.Status}}'
sudo docker stats --no-stream
df -h /
```

The user's confirmed healthy production baseline has the FastAPI, PostgreSQL and Redis containers healthy; Qdrant and Caddy running. The exact container names and uptime can change following recreation.

For an internal readiness check, use the service's container context:

```bash
sudo docker compose \
  --env-file .env.production \
  -f infra/docker/compose.prod.yml \
  -f infra/docker/compose.aws.yml \
  -f infra/docker/compose.aws.test.yml \
  -f infra/docker/compose.aws.index.yml \
  exec -T api python -c "import json; from urllib.request import urlopen; print(json.load(urlopen('http://127.0.0.1:8000/api/v1/ready',timeout=10)))"
```

This command is a read-only request; it does **not** start, replace or restart containers.

## HTTPS edge check

```bash
curl -4 -sS --connect-timeout 10 --max-time 25 \
  -o /dev/null \
  -w 'HTTP=%{http_code} TLS_VERIFY=%{ssl_verify_result}\n' \
  https://16-178-127-0.sslip.io/api/v1/ready
```

The Caddy configuration intentionally returns `404` for the public readiness endpoint. A result of `HTTP=404 TLS_VERIFY=0` has been observed and is the expected **TLS verification** outcome for that path, not an external API health assertion.

The currently used `sslip.io` hostname maps to an EC2 IPv4 address; **if the instance's public IP changes, the DNS alias, TLS issuance, Vercel `API_BASE_URL`, and operational configuration require review**. A reserved Elastic IP or owned domain is recommended for a durable production deployment.

## Vercel configuration

Configure **Production** environment variables in the Vercel dashboard:

| Name | Purpose |
| --- | --- |
| `API_BASE_URL` | HTTPS base URL of the Caddy proxy |
| `INTERNAL_API_TOKEN` | Secret shared with the FastAPI service |
| `AUTH_SECRET` | Auth.js signing/configuration secret |
| `AUTH_GOOGLE_ID` | Google OAuth client ID |
| `AUTH_GOOGLE_SECRET` | Google OAuth client secret |
| `VERIFY_REQUIRE_LOGIN` | `true` for the deployment's login policy |

Do not place confidential values in Git, logs, user-facing source, or screenshots. After changing Vercel variables, initiate a new production deployment and verify the sign-in and claim flow.

## Reproducibility caveat

The production repository and Compose files alone are **insufficient for clean-room deployment**. A reproducible build also requires a secure secret-distribution process, model-weight provisioning, FEVER passage data, the prebuilt Tantivy index, and a validated process for resolving source-code mount workarounds. Record hashes or artifact manifests for large assets when possible.

## Operational precautions

- **Avoid** `docker system prune --volumes`, `docker compose down -v`, forced rebases, or deleting model/index directories.
- Do not publish PostgreSQL, Redis, Qdrant or internal FastAPI ports to the open Internet.
- Do not use `/api/v1/ready` via public HTTPS as an application readiness probe; it is intentionally blocked by Caddy.
- Keep backups of persistent data and record EC2/public IP and TLS renewal arrangements.
- Use scoped credentials and rotate/revoke temporary GitHub access on the server after it is no longer needed.

## Known functional baseline

Three manual end-to-end demonstrations were observed via the Vercel website: supporting, refuting, and insufficient evidence. These checks do not establish production-scale performance or research-grade accuracy.
