# Deploying Vidra (dev-remote / QA / staging / production)

Canonical environment matrix: [`.ralph/specs/environments.md`](../.ralph/specs/environments.md).
This directory holds the reference single-host deployment: the meta-repo compose
stack behind a TLS reverse proxy.

## Reference deployment (one host per environment)

```bash
git clone https://github.com/yegamble/vidra.git && cd vidra
./bootstrap.sh
cp env/staging.env.example env/staging.env       # fill in secrets from your store
docker compose --env-file env/staging.env --profile core --profile frontend up -d --build
```

Put TLS in front with the provided [`Caddyfile`](./Caddyfile) (or any proxy):
the api serves plain HTTP on `HTTP_PORT`, the frontend on `FRONTEND_PORT`.
`PUBLIC_BASE_URL`/`CORS_ALLOWED_ORIGINS` must match the public domains.

**`vidra-search` is an internal service** — only `vidra-core` talks to it, over the
compose network (HMAC-authenticated). Do **not** add a Caddyfile site for it or
publish its port past the host; it stays behind the api gateway. Its host port
(`SEARCH_HTTP_PORT`, default `:8081`) is for local inspection only.

Environment rules that the backend enforces for you (fail-secure):
- `VIDRA_ENV=production` refuses the dev `JWT_SECRET`, refuses `DEV_MAIL_CAPTURE_ENABLED`,
  requires `FEDERATION_KEY_KEK` when federation is enabled, and marks auth cookies `Secure`.
- `SEARCH_INTERNAL_SECRET` is a shared HMAC secret (core ⇄ search); set a strong
  (≥32-byte) value from the secret store when the search integration is enabled, and
  keep it identical on both services. Never commit a real value.
- The frontend image bakes `NEXT_PUBLIC_API_BASE_URL` at **build** time — build one
  image per environment (CI tags `vidra-user:<env>-<sha>`); a restart does not repoint it.

## Staging → production promotion

Staging runs production config with throwaway data. Promote by deploying the **exact
image tags** staging validated — rebuild nothing between staging and production
except the frontend image if the API URL differs (unavoidable with build-time baking).

## Backups & restore (staging/production)

- **PostgreSQL**: nightly `docker exec <postgres> pg_dump -U vidra -Fc vidra > vidra-$(date +%F).dump`;
  restore with `pg_restore -U vidra -d vidra --clean`. Keep 14 daily + 8 weekly.
  This whole-database dump already includes `vidra-search`'s `search` schema (it
  shares the `vidra` DB), so no separate search backup is needed.
- **Media**: `STORAGE_BACKEND=s3` → use the object store's replication/lifecycle;
  `local` → snapshot the media volume (`docker volume`/filesystem snapshot) on the
  same cadence as the DB so references stay consistent.
- **Redis** is a cache + rate-limit/dedup store: no backup needed; it may be flushed.
- **Restore drill** (quarterly): restore the latest dump + media snapshot into a fresh
  stack (`make nuke` on a scratch host), boot, and click through login/watch/upload.

## Health & monitoring

- Probes: `GET /healthz` (liveness), `GET /readyz` (readiness incl. postgres/redis).
- Operator snapshot: `GET /api/v1/admin/system` (admin JWT) — status, versions, uptime,
  dependency health, effective non-secret config.
- Optional OTel: set the `OTEL_*` env vars to point at your collector.

## QA environment

QA mirrors `vidra-user/.github/workflows/frontend-e2e-backed.yml` exactly — that
workflow is the QA contract (flags in `env/qa.env.example`). A QA host exists to run
the same backed suite against long-lived data and for manual exploratory testing.
