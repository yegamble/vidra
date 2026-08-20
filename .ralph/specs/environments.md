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
vidra-core's services (build context `./vidra-core`), adds a `frontend` service
(build context `./vidra-user`, build-arg `NEXT_PUBLIC_API_BASE_URL`), and adds the
`vidra-search` service + its one-shot `search-migrate` (build context
`./vidra-search`). Profiles:

- *(default / `core`)*: postgres, redis, migrate, api, **search-migrate, search**
  (search shares the `vidra` DB via schema `search` and Redis DB 1; the api gets
  `SEARCH_SERVICE_URL=http://search:8080` + `SEARCH_INTERNAL_SECRET`)
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
| `RATE_LIMIT_ENABLED` | **false** (opt in for limiter testing) | true | **false** | true | true |
| `DEV_MAIL_CAPTURE_ENABLED` | opt-in | opt-in | **true** | **false (prod refuses)** | **false (prod refuses)** |
| `HTTP_IMPORT_ALLOW_PRIVATE_URLS` | opt-in | false | **true** | false | false |
| `MAIL_ENABLED` (SMTP) | false | optional | false | true | true |
| `TRANSCODING_ENABLED` | opt-in | true | true | true | true |
| `MALWARE_SCAN_ENABLED` | false | optional | optional | true (+clamd) | true (+clamd) |
| `STORAGE_BACKEND` | local | local or s3 | local | s3 | s3 |
| `FEDERATION_ENABLED` (+KEK) | opt-in | opt-in | true (loop tests) | per rollout | per rollout |
| Registration | open | open | open (approval-mode job flips it) | per policy | per policy |
| `SEARCH_HTTP_PORT` | 8081 | 8081 | 8081 | 8081 | 8081 |
| `SEARCH_INTERNAL_SECRET` | dev default | secret store | dev default (test) | secret store | secret store |
| Secrets source | `.env` (gitignored) | host env / secret store | CI secrets | secret store | secret store |

Per-environment templates live as `env/<env>.env.example` in the meta-repo (values
above, placeholders for secrets). `config.Load` already refuses dev defaults in
production (JWT secret, dev seams); keep extending that fail-secure list.

## 2. The frontend build-time URL problem (explicit)

`NEXT_PUBLIC_API_BASE_URL` is baked at build time. Policy: **one image per
environment**, built with the env's URL as a build arg (the Dockerfile already
accepts it). Do NOT chase runtime-config hacks in v1; document the rebuild rule in
vidra-user's README.

**What CI actually publishes** (corrected 2026-07-28 — the previous claim that "CI
publishes `vidra-user:<env>-<sha>` images per environment" was never true).
`vidra-user/.github/workflows/publish-container.yml` runs **only** on
`release: published` and builds exactly **one** image, using the single
`NEXT_PUBLIC_API_BASE_URL` *repository variable* — i.e. the production origin. It
pushes two tags:

- `ghcr.io/yegamble/vidra-user:<release-tag>` (e.g. `:v0.1.0`)
- `ghcr.io/yegamble/vidra-user:sha-<full-40-char-sha>`

There is no `<env>-<sha>` tag and no per-environment matrix, and there is
deliberately no fallback for the repository variable: if it is unset, blank,
scheme-less or loopback the release build **fails** rather than shipping a browser
bundle that calls `localhost:8080`. So the "one image per environment" policy is
satisfied by CI **for production only**; any other environment whose API origin
differs must build its own image today — either on that host
(`docker compose --profile frontend build`, which is what `deploy/README.md`'s
`up -d --build` already does) or manually:

```bash
docker build --build-arg NEXT_PUBLIC_API_BASE_URL=https://qa-api.example.com \
  -t ghcr.io/yegamble/vidra-user:qa-$(git rev-parse --short HEAD) ./vidra-user
```

A per-environment matrix in CI was considered and rejected for v1: the release
event carries no environment, each env would need its own repository variable, and
it contradicts §3's promotion rule ("promote by deploying the exact image tags
staging validated") for every environment that shares production's API origin.
Revisit only when a second long-lived remote environment actually exists.

The same release workflow in `vidra-core` and `vidra-search` publishes
`ghcr.io/yegamble/vidra-core:<release-tag>` / `:sha-<full-sha>` and
`ghcr.io/yegamble/vidra-search:<release-tag>` / `:sha-<full-sha>` — those images
take no environment-specific build args at all, so one build serves every
environment.

## 3. Remote environments (dev / QA / staging / production)

- Reference deployment: a single host (or VM per env) running the meta-repo compose
  with the env's `env/<env>.env` file. **Staging and production use an explicit
  `-f` chain that applies the production overlay**, and nothing else is supported:
  ```bash
  docker compose -f docker-compose.yml -f docker-compose.prod.yml \
    --env-file env/production.env --profile core --profile frontend up -d --no-build
  ```
  The overlay (`docker-compose.prod.yml`) is what closes Postgres/Redis/search
  (`ports: !reset []`, needs Compose ≥ 2.24), binds api/frontend to `127.0.0.1`,
  pulls GHCR images by tag instead of building, sets restart policies, caps logs,
  and adds the Caddy TLS terminator. An explicit chain also **disables**
  auto-loading of `docker-compose.override.yml` — deliberate (that file carries
  dev defaults such as `RATE_LIMIT_ENABLED=false`), at the cost that
  `SEARCH_SERVICE_URL` / `SEARCH_INTERNAL_SECRET` must be set in the env file.
  Dev/QA hosts stay on the plain `docker compose --env-file env/<env>.env
  --profile core --profile frontend up -d --build` (no overlay: they build
  locally, and QA's flags require the override file's dev seams).
- **Nothing is run by hand in prod.** `deploy/deploy.sh` (pre-deploy dump → pull →
  exit-code-gated `migrate` + `search-migrate` → `up -d --no-build` → `/readyz` +
  frontend probes), `deploy/rollback.sh <tag>` (rewrite the three `VIDRA_*_TAG`
  values, pull, restart, re-probe — app only, no schema change),
  `deploy/backup.sh` (`pg_dump -Fc` → gzip → verify → optional off-site → 14
  daily + 8 weekly → `last_success` marker) and `deploy/restore.sh` (destructive;
  stop, drop, recreate, `pg_restore -j4`, migrate, probe). `deploy/vidra-backup.timer`
  + `.service` run the nightly backup; `make deploy` / `rollback` / `backup` /
  `restore` are thin wrappers honouring `PROD_ENV_FILE=env/staging.env`.
- **QA** is the environment CI's backed suite models: its flag column above matches
  `frontend-e2e-backed.yml` exactly (that workflow IS the QA contract). It is also
  the only template that enables `DEV_MAIL_CAPTURE_ENABLED` and
  `HTTP_IMPORT_ALLOW_PRIVATE_URLS`; both are takeover/SSRF primitives, the api's
  refusals only fire when `VIDRA_ENV=production`, so a QA host must not be
  internet-reachable.
- **Staging = production config with throwaway data**: same flags, same overlay,
  same image tags as the prod candidate, separate secrets/domains. Promotion =
  deploy the exact tags staging validated.
- **Postgres runs in the compose stack, not managed** — including staging and
  production. `internal/store/store.go:53` hardcodes `MaxConns=10` after
  `ParseConfig`, so core + search + the import pool total 24 connections, above
  the smallest DO Managed plan's cap. The DSN indirection is in place — a single
  `DATABASE_URL` overrides the constructed default for the api, the search
  service and BOTH migration one-shots (the search migrator carries its
  `vidra_search_migrations` ledger name in the binary, so the second
  `SEARCH_MIGRATE_DATABASE_URL` variable that used to append
  `&x-migrations-table=…` is gone) — so the move is a config change once a
  `DATABASE_MAX_CONNS` knob exists; see "Managed Postgres — not at launch" in
  `deploy/README.md`.
- Backup/restore (prod/staging): nightly `deploy/backup.sh` via the systemd timer,
  plus media volume/bucket sync (the dump covers vidra-search too — it shares the
  database in the `search` schema). Restore drill and the dirty-migration runbook
  are in `deploy/README.md` (vidra-core P17.4 items point here).
- Health/monitoring: `/healthz` `/readyz` probes; `GET /api/v1/admin/system` for the
  operator dashboard; OTel collector profile optional per env.

## 4. Developer experience guarantees (each is a testable claim)

1. Fresh machine → running full stack: `git clone …/vidra && cd vidra &&
   ./bootstrap.sh && make dev` (documented time budget: < 10 min incl. image builds).
   `make dev`/`make dev-hot` bring up the `vidra-search` service in the `core`
   profile automatically (migrated by `search-migrate`); no extra profile or step —
   the api is wired to it out of the box.
2. Backend-only iteration: `cd vidra-core && make dev` (compose deps + `go run`).
3. Frontend-only iteration against any env: `cd vidra-user &&
   NEXT_PUBLIC_API_BASE_URL=<env url> npm run dev`.
4. The three canonical gates never change names: `make ci` (core),
   `npm run ci` (user), `npm run e2e:backed` (user, backed).
5. Every flag in §1 is documented in the owning repo's `.env.example` and the
   meta-repo env templates — no tribal knowledge.
