# Vidra environments & developer experience (canonical, cross-repo)

> Canonical definition of how vidra-core + vidra-user run in every environment:
> **local**, **dev (remote)**, **testing/QA (remote)**, **staging**, **production**.
> Lives in the meta-repo because it spans both codebases; each sub-repo's AGENT.md
> and README point here. Decided 2026-07-03.

## 0. One-command local development (the meta-repo promise)

From a fresh clone of the meta-repo:

```bash
./bootstrap.sh                # clone/update both sub-repos
make dev                      # full stack: postgres+redis+migrate+api+frontend (dev flags)
```

The meta-repo `docker-compose.yml` becomes the FULL-STACK compose: it includes
vidra-core's services (build context `./vidra-core`) and adds a `frontend` service
(build context `./vidra-user`, build-arg `NEXT_PUBLIC_API_BASE_URL`). Profiles:

- *(default / `core`)*: postgres, redis, migrate, api
- `frontend`: the Next.js production container (dev iteration still uses `npm run dev`
  on the host for HMR — document both)
- `storage`: MinIO; `media`: RTMP media server; `scan`: clamd; `captions`: whisper;
  `otel`: collector+Jaeger — mirroring/reusing vidra-core's profiles so
  `docker compose --profile core --profile media up` composes them.

Meta-repo `Makefile` targets (all delegating, never duplicating logic):
`make dev` (core in docker + `npm run dev` hint), `make up` / `down` / `logs`,
`make test` (both repos' canonical gates), `make e2e-backed` (the documented backed
procedure), `make seed` (demo user/channel/video via the API).

## 1. Environment matrix

| Concern | local | dev (remote) | testing/QA (remote) | staging | production |
|---|---|---|---|---|---|
| Purpose | day-to-day dev | shared dev sandbox | backed e2e/QA runs | prod rehearsal | live |
| `VIDRA_ENV` | development | development | test | production | production |
| TLS | none (localhost) | proxy TLS | proxy TLS | required | required |
| `PUBLIC_BASE_URL` | http://localhost:8088 | https://dev-api.… | https://qa-api.… | https://stg-api.… | https://api.… |
| Frontend API URL (build arg) | http://localhost:8088 | https://dev-api.… | https://qa-api.… | https://stg-api.… | https://api.… |
| `RATE_LIMIT_ENABLED` | true (false for backed runs) | true | **false** | true | true |
| `DEV_MAIL_CAPTURE_ENABLED` | opt-in | opt-in | **true** | **false (prod refuses)** | **false (prod refuses)** |
| `HTTP_IMPORT_ALLOW_PRIVATE_URLS` | opt-in | false | **true** | false | false |
| `MAIL_ENABLED` (SMTP) | false | optional | false | true | true |
| `TRANSCODING_ENABLED` | opt-in | true | true | true | true |
| `MALWARE_SCAN_ENABLED` | false | optional | optional | true (+clamd) | true (+clamd) |
| `STORAGE_BACKEND` | local | local or s3 | local | s3 | s3 |
| `FEDERATION_ENABLED` (+KEK) | opt-in | opt-in | true (loop tests) | per rollout | per rollout |
| Registration | open | open | open (approval-mode job flips it) | per policy | per policy |
| Secrets source | `.env` (gitignored) | host env / secret store | CI secrets | secret store | secret store |

Per-environment templates live as `env/<env>.env.example` in the meta-repo (values
above, placeholders for secrets). `config.Load` already refuses dev defaults in
production (JWT secret, dev seams); keep extending that fail-secure list.

## 2. The frontend build-time URL problem (explicit)

`NEXT_PUBLIC_API_BASE_URL` is baked at build time. Policy: **one image per
environment**, built by CI with the env's URL as a build arg (the Dockerfile already
accepts it). Do NOT chase runtime-config hacks in v1; document the rebuild rule in
vidra-user's README. CI publishes `vidra-user:<env>-<sha>` images per environment.

## 3. Remote environments (dev / QA / staging / production)

- Reference deployment: a single host (or VM per env) running the meta-repo compose
  with the env's `env/<env>.env` file: `docker compose --env-file env/qa.env
  --profile core --profile frontend up -d`, behind a TLS reverse proxy (Caddy or
  nginx; example config committed under `deploy/`). Postgres/Redis containers with
  named volumes for dev/QA; managed Postgres recommended for staging/prod (DSN is
  just config).
- **QA** is the environment CI's backed suite models: its flag column above matches
  `frontend-e2e-backed.yml` exactly (that workflow IS the QA contract).
- **Staging = production config with throwaway data**: same flags, same image tags
  as the prod candidate, separate secrets/domains. Promotion = retag the exact
  images.
- Backup/restore (prod/staging): `pg_dump` nightly + media volume/bucket sync;
  restore drill documented in `deploy/README.md` (vidra-core P17.4 items point here).
- Health/monitoring: `/healthz` `/readyz` probes; `GET /api/v1/admin/system` for the
  operator dashboard; OTel collector profile optional per env.

## 4. Developer experience guarantees (each is a testable claim)

1. Fresh machine → running full stack: `git clone …/vidra && cd vidra &&
   ./bootstrap.sh && make dev` (documented time budget: < 10 min incl. image builds).
2. Backend-only iteration: `cd vidra-core && make dev` (compose deps + `go run`).
3. Frontend-only iteration against any env: `cd vidra-user &&
   NEXT_PUBLIC_API_BASE_URL=<env url> npm run dev`.
4. The three canonical gates never change names: `make ci` (core),
   `npm run ci` (user), `npm run e2e:backed` (user, backed).
5. Every flag in §1 is documented in the owning repo's `.env.example` and the
   meta-repo env templates — no tribal knowledge.
