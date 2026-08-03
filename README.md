# Vidra

A clean-room, PeerTube-inspired federated video platform. Vidra is split across
**three independent repositories**, tied together by this lightweight **meta-repo**:

| Repo | What | Stack |
|------|------|-------|
| [`vidra-core`](https://github.com/yegamble/vidra-core) | Backend / HTTP API | Go, Echo, PostgreSQL, sqlc, Redis, Docker |
| [`vidra-user`](https://github.com/yegamble/vidra-user) | Frontend | Next.js, TypeScript, Tailwind |
| [`vidra-search`](https://github.com/yegamble/vidra-search) | Search, autosuggest & recommendations service | Go, PostgreSQL, Redis |

Each repo is self-contained — its own `go.mod` / `package.json`, Docker setup, and
GitHub Actions CI. The frontend consumes the backend's HTTP API at runtime via
`NEXT_PUBLIC_API_BASE_URL`, with no build-time coupling. `vidra-search` is an
**internal-only** service — HMAC-authenticated, called only by `vidra-core`, never
exposed to the browser.

## Prerequisites

- **Docker** with Compose **v2.20+** (the root compose uses `include:` and profiles).
  Deploying with `docker-compose.prod.yml` additionally needs **v2.24+** — it uses
  the `!reset`/`!override` merge tags, without which the production overlay
  silently fails to close the published database ports
  (see [`deploy/README.md`](deploy/README.md#host-prerequisites)).
- **GNU make** and **git**.
- **Node.js 20+** and **npm**, for host-side frontend dev.

`bootstrap.sh` clones the three sibling checkouts (`vidra-core`, `vidra-user`,
`vidra-search`) automatically; they are git-ignored by this repo.

## Quick start

```bash
git clone https://github.com/yegamble/vidra.git
cd vidra
make dev                  # bootstrap + backend stack (postgres, redis, migrate, api :8080, search :8081)

# Frontend (in another shell) — Next.js dev with HMR against the live backend:
cd vidra-user && npm ci && NEXT_PUBLIC_API_BASE_URL=http://localhost:8080 npm run dev

make seed                 # optional: demo account (demo@vidra.local / demo-password-123) + @demo channel
```

Run the whole stack in containers (frontend on :3000) with `make up`. The local
stack disables the global API rate limiter by default — re-enable it with
`RATE_LIMIT_ENABLED=true make dev`.

## Everyday commands

| Command | What it does |
|---------|--------------|
| `make dev` | Backend + search stack (postgres, redis, migrate, api :8080, search :8081); run the frontend on the host for HMR. |
| `make up` | Full stack in containers, including the frontend on :3000. |
| `make dev-hot` | Full stack in Docker with live reload (see below); tail with `make dev-hot-logs`. |
| `make dev-hot-down` | Stop the hot-reload stack; data volumes preserved. |
| `make dev-hot-nuke` | **Destructive.** Stop hot-reload stack and delete all volumes (db data + caches). |
| `make seed` | Seed a demo account (`demo@vidra.local` / `demo-password-123`) + `@demo` channel. |
| `make test` | Run **all three** repos' canonical CI gates: `vidra-core` `make ci`, `vidra-search` `make ci`, `vidra-user` `npm run ci`. |
| `make e2e-backed` | Run the backend-backed Playwright suite against **`vidra-core`'s own compose stack** (no search service). |
| `make logs` | Tail all service logs. |
| `make down` | Stop the stack; data volumes preserved. |
| `make nuke` | **Destructive.** Stop the stack and delete data volumes (fresh start). Prompts, or needs `CONFIRM=1`. |
| `make ipfs-live` | Core stack + live public IPFS mirror + separate private mirror (see below). |
| `make env-check` | Show which env template the compose commands would use. |
| `make help` | List all targets. |

Production/staging operations (all honour `PROD_ENV_FILE=env/staging.env`):

| Command | What it does |
|---------|--------------|
| `make release VERSION=v0.2.0` | `deploy/release.sh`: guarded `gh release create` in all three repos → watch each `publish-container` run → verify the GHCR image. Prompts, or needs `CONFIRM=1`. |
| `make prod-config` | Render + validate the production compose chain; catches missing required secrets. |
| `make deploy` | `deploy/deploy.sh`: pre-deploy dump → pull → gated migrations → `up -d --no-build` → probe. |
| `make rollback TAG=v0.1.0` | Rewrite the three `VIDRA_*_TAG` values, pull, restart, re-probe. App only — no schema change. |
| `make backup` | `deploy/backup.sh`: `pg_dump -Fc` → gzip → optional off-site → 14 daily + 8 weekly retention. |
| `make restore DUMP=… CONFIRM=1` | **Destructive.** `deploy/restore.sh`: drop, recreate, `pg_restore -j4`, migrate, probe. Prompts, or needs `CONFIRM=1`. |
| `make prod-logs` / `make prod-down` | Tail / stop the production stack. |

## Hot reload (`make dev-hot`)

`make dev-hot` runs the **whole stack in Docker with live reload** — no image
rebuilds while developing:

- **api**: `air` on the bind-mounted `vidra-core/` tree recompiles and restarts
  in ~1–3s, on the same port `:8080`.
- **search**: same `air` pattern on `:8081`; it shares the core Postgres (schema
  `search`) and Redis (DB 1), migrated by a one-shot `search-migrate` service.
- **frontend**: `next dev` (webpack + polling) on bind-mounted `vidra-user/` HMRs
  instantly; `node_modules` and `.next` live in named volumes.

**First run is slow** (once): volume seed, `go mod download`, cold compile — a few
minutes; later starts are fast. `NEXT_PUBLIC_API_BASE_URL` is a **runtime** env
here and must be a browser-reachable host URL, **not** `http://api:8080`; if you
override `HTTP_PORT`, match it:
`HTTP_PORT=8088 NEXT_PUBLIC_API_BASE_URL=http://localhost:8088 make dev-hot`. The
dev overlay only applies when `-f docker-compose.dev.yml` is passed; `make up`,
`make dev`, and both Dockerfiles are untouched.

## IPFS live mode

`make ipfs-live` enables the public mirror on a live Kubo node — the client gateway
defaults to `https://ipfs.io` (override with
`IPFS_PUBLIC_GATEWAY_URL=https://your-gateway.example make ipfs-live`) — and starts
the swarm-keyed private mirror alongside it. Kubo's RPC ports are loopback-only;
only the libp2p swarm port is public. This is an intentional disclosure boundary:
**a public CID may remain retrievable after the local node unpins it.**

## Environments

The canonical environment matrix lives in
[`.ralph/specs/environments.md`](.ralph/specs/environments.md), with ready-to-copy
per-environment templates under [`env/`](env/) and a reference single-host TLS
deployment (compose overlay + Caddy + deploy/backup/rollback scripts) under
[`deploy/`](deploy/).

A **real deployment never builds on the box** — it pulls tagged images from GHCR
and applies [`docker-compose.prod.yml`](docker-compose.prod.yml), which is what
binds the api/frontend to `127.0.0.1`, removes the Postgres/Redis/search port
publishes entirely, and adds restart policies, log caps and TLS:

```bash
cp env/production.env.example env/production.env   # fill in secrets; it is git-ignored
git check-ignore -v env/production.env             # must match, or stop

docker compose -f docker-compose.yml -f docker-compose.prod.yml \
  --env-file env/production.env --profile core --profile frontend pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml \
  --env-file env/production.env --profile core --profile frontend up -d --no-build
```

In practice use `./deploy/deploy.sh` (= `make deploy`), which wraps that with a
pre-deploy dump, exit-code-gated migrations and health probes. Note the explicit
`-f` chain **disables** auto-loading of `docker-compose.override.yml` — intended,
but it means production must set `SEARCH_SERVICE_URL` and `SEARCH_INTERNAL_SECRET`
in the env file itself.

Three rules worth internalizing: **staging is production config with throwaway
data** (promote the exact image tags); the containerized frontend bakes
`NEXT_PUBLIC_API_BASE_URL` at **build** time, so a restart cannot repoint it; and
**register the owner account before opening registration** — the first account on
an empty `users` table is auto-granted admin. Production is fail-secure
(`VIDRA_ENV=production` refuses dev secrets and dev mail capture); see
[`deploy/README.md`](deploy/README.md) for first-boot ordering, host
prerequisites, the firewall caveat, backups/restore, secret rotation, and the
dirty-migration runbook.

## The API contract

`vidra-core/api/openapi.yaml` is the source of truth for the HTTP API. `vidra-user`
regenerates `lib/api/generated.ts` from it with `npm run codegen`, and
`lib/api/types.ts` is derived from that — **never hand-edit shapes**. `contract-ci`
guards drift twice: `scripts/check-contract.mjs` asserts every `/api/` path the
frontend calls exists in the spec, and a codegen step fails if `generated.ts` is
stale. In CI the spec is fetched from the public `vidra-core` repo; locally the
sibling `../vidra-core` checkout is used.

A breaking API change spans two repos with no atomic commit — stage it back-compat:

1. Land the additive, back-compat change in `vidra-core` (its `openapi` CI publishes the updated spec).
2. Update `vidra-user` to the new shape.
3. Remove the old endpoint in a later `vidra-core` change.

`vidra-search` exposes a **separate, internal** contract at
`vidra-search/api/openapi.yaml` (all under `/internal/v1`, HMAC-authenticated),
consumed only by `vidra-core`, staged the same back-compat way.

## CI

Each repo runs its own GitHub Actions:
- **vidra-core** — `backend-ci` (`make ci`), `backend-integration`, `openapi`, `ci-guard`.
- **vidra-user** — `frontend-ci` (`npm run ci`), `contract-ci`, `frontend-e2e-backed`, `ci-guard`.
- **vidra-search** — `search-ci` (`make ci`), `search-integration`, `openapi`, `ci-guard`.

Each repo also carries additional workflows (fuzzing, IPFS integration, container
publishing, search model training) — see each repo's `.github/workflows/`. This
meta-repo runs `meta-ci` (validates `bootstrap.sh` and the full-stack compose config).

## Repo layout & docs

`bootstrap.sh` is idempotent: it clones each component if missing, otherwise
`git pull --ff-only`. The `./vidra-core`, `./vidra-user`, and `./vidra-search`
directories are independent git checkouts, git-ignored by this repo.

| Doc | What |
|-----|------|
| [`.ralph/specs/architecture.md`](.ralph/specs/architecture.md) | Living architecture doc: subsystems and the shared Postgres/Redis topology across the three services. |
| [`.ralph/specs/security.md`](.ralph/specs/security.md) | Security posture and planned controls (CORS allow-list, config hygiene, token hashing, fail-secure prod). |
| [`.ralph/specs/testing.md`](.ralph/specs/testing.md) | Test strategy: unit / integration / migration / fuzz / benchmark layers and how to run them. |
| [`.ralph/specs/search.md`](.ralph/specs/search.md) | Cross-repo map of the `vidra-search` service and how it plugs into core and user. |
| [`.ralph/specs/peertube-feature-ledger.md`](.ralph/specs/peertube-feature-ledger.md) | PeerTube feature-parity ledger with per-feature status and evidence. |
| [`.ralph/specs/environments.md`](.ralph/specs/environments.md) | Canonical environment matrix (local / dev / QA / staging / production) and the DX contract. |
| [`deploy/README.md`](deploy/README.md) | Reference single-host deployment: first-boot ordering, host prerequisites + firewall, droplet sizing, the prod compose overlay + Caddy TLS, deploy/rollback/backup/restore scripts, dirty-migration runbook, secret-rotation table, email. |
| [`docs/production-readiness-2026-07.md`](docs/production-readiness-2026-07.md) | Launch-gate audit: what must be done before a public deploy, and what is already handled. |

## Autonomous development (Ralph)

Run a **per-repo loop** inside each component checkout (`vidra-search` has no Ralph
control plane):

```bash
cd vidra-core && ralph --live
cd vidra-user && ralph --live
```

Each loop commits and pushes its own repo's `main` — no cross-repo pointer to bump.
For an API change that spans both, run the loops sequentially, backend first (see
[The API contract](#the-api-contract)). The root `.ralphrc`, `.ralph/PROMPT.md`,
and `.ralph/fix_plan.md` are **legacy** and drive nothing; `.ralph/specs/` is
preserved here as product docs.

## Why a meta-repo, not submodules?

The components talk only over HTTP at runtime, and each repo's loop commits and
pushes independently. A submodule pins a commit SHA and forces a
commit-child → bump-pointer → push-parent transaction on every sync. The meta-repo
gives the same "one place to clone and run" without any of that.

## License
Vidra is free software licensed under the [GNU Affero General Public License v3.0](LICENSE).
Each component repo (vidra-core, vidra-user, vidra-search) carries the same license.
