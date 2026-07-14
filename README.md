# Vidra

A clean-room, PeerTube-inspired federated video platform. Vidra is split across
**three independent repositories**, tied together by this lightweight **meta-repo**:

| Repo | What | Stack |
|------|------|-------|
| [`vidra-core`](https://github.com/yegamble/vidra-core) | Backend / HTTP API | Go, Echo, PostgreSQL, sqlc, Redis, Docker |
| [`vidra-user`](https://github.com/yegamble/vidra-user) | Frontend | Next.js, TypeScript, Tailwind |
| [`vidra-search`](https://github.com/yegamble/vidra-search) | Search, autosuggest & recommendations service | Go, PostgreSQL, Redis |

Each repo is self-contained — its own `go.mod` / `package.json`, its own Docker
setup, its own GitHub Actions CI, and its own Ralph control plane (`.ralphrc` +
`.ralph/`). The frontend consumes the backend's HTTP API **contract** at runtime
(`NEXT_PUBLIC_API_BASE_URL`); there is no build-time coupling. `vidra-search` is an
**internal** service that only `vidra-core` calls (HMAC-authenticated, over the
compose network) — it is never exposed to the browser.

> **Why a meta-repo and not git submodules?** The components talk only over
> HTTP at runtime, and the autonomous Ralph loop commits many times per hour. A
> submodule pins a commit SHA and requires a strict commit-child → push-child →
> bump-pointer → push-parent transaction on every sync, which fights the loop and
> risks dangling pointers. The meta-repo gives the same "one place to clone and
> run" without any of that: each repo's loop just commits and pushes its own tree.

## Getting started

```bash
git clone https://github.com/yegamble/vidra.git
cd vidra
make dev                  # bootstrap + backend stack (postgres, redis, migrate, api :8080, search :8081)

# Frontend (in another shell) — Next.js dev with HMR against the live backend:
cd vidra-user && npm ci && NEXT_PUBLIC_API_BASE_URL=http://localhost:8080 npm run dev

make seed                 # optional: demo account (demo@vidra.local) + @demo channel
```

The local stack disables the global API rate limiter so HMR and repeated server
renders do not exhaust one shared localhost bucket. To exercise rate limiting
manually, start it with `RATE_LIMIT_ENABLED=true make dev` (or `make dev-hot`).
Dedicated backend limiter tests remain enabled and are unaffected.

Or run the **whole stack in containers** (frontend included, on :3000):

```bash
make up                   # == docker compose --profile core --profile frontend up -d --build
```

### Hot-reload dev stack (`make dev-hot`)

`make dev-hot` runs the **whole stack in Docker with live reload** — no image
rebuilds while developing:

- **api**: `air` watches the bind-mounted `vidra-core/` tree; saving a `.go`
  file recompiles (`go build ./cmd/api`, caches in named volumes) and restarts
  the server in ~1–3s. Same postgres/redis/migrate deps, same port (`:8080`).
- **search**: same `air` pattern for the bind-mounted `vidra-search/` tree
  (own go build/module cache volumes); reachable on `:8081`. It shares the core
  Postgres (schema `search`) and Redis (DB 1) and is migrated by a one-shot
  `search-migrate` service before it starts.
- **frontend**: `next dev` (webpack + polling, for macOS bind-mount reliability)
  against bind-mounted `vidra-user/`; saving a `.tsx` HMRs instantly.
  `node_modules` and `.next` live in named volumes so the host's macOS-arch
  installs never leak into the Linux container; a `package-lock.json` change is
  auto-detected and reinstalled on container start, and the olm-wasm prebuild
  runs automatically.
- `NEXT_PUBLIC_API_BASE_URL` is a **runtime** env in dev (default
  `http://localhost:8080`, a browser-reachable host URL — not `http://api:8080`).
  If you override `HTTP_PORT`, match it:
  `HTTP_PORT=8088 NEXT_PUBLIC_API_BASE_URL=http://localhost:8088 make dev-hot`.

Commands: `make dev-hot` / `make dev-hot-logs` / `make dev-hot-down` /
`make dev-hot-nuke` (also deletes db data + caches). **First run is slow** (once):
npm volume seed, `go mod download`, cold compile — a few minutes; later starts
and rebuilds are fast. The production paths (`make up`, `make dev`, both
Dockerfiles, the base compose files) are untouched — the overlay only applies
when `-f docker-compose.dev.yml` is passed.

Other meta-repo commands: `make test` (both repos' canonical CI gates),
`make e2e-backed` (the backend-backed Playwright suite against a fresh stack),
`make logs`, `make down`, `make nuke` (also deletes data volumes). Run `make help`
for the full list.

`bootstrap.sh` is idempotent: it clones each component if missing, otherwise
`git pull --ff-only`. The `./vidra-core`, `./vidra-user` and `./vidra-search`
directories are independent git checkouts and are **git-ignored by this repo**.

## Environments

The canonical environment matrix — **local, dev (remote), testing/QA (remote),
staging, production** — lives in [`.ralph/specs/environments.md`](.ralph/specs/environments.md),
with ready-to-copy per-environment templates under [`env/`](env/) and a reference
single-host TLS deployment (compose + Caddy, backups, promotion rules) under
[`deploy/`](deploy/):

```bash
cp env/staging.env.example env/staging.env   # fill in secrets
docker compose --env-file env/staging.env --profile core --profile frontend up -d --build
```

Two rules worth internalizing: **staging is production config with throwaway
data** (promote the exact image tags), and the frontend bakes
`NEXT_PUBLIC_API_BASE_URL` at **build** time — one frontend image per environment.

## The frontend ⇄ backend contract

`vidra-core/api/openapi.yaml` is the source of truth for the HTTP API. `vidra-user`
hand-maintains `lib/api/types.ts` against it (no codegen yet) and guards drift with
`scripts/check-contract.mjs`, which asserts every `/api/` path the frontend calls
exists in the spec. In CI, `vidra-user`'s `contract-ci` fetches the spec from the
public `vidra-core` repo; locally it resolves the sibling `../vidra-core` checkout.

**Making a breaking API change spans two repos** — there is no longer one atomic
commit. Stage it back-compat: land the additive backend change in `vidra-core`
first (its `openapi` CI publishes the updated spec), then update `vidra-user`, then
remove the old endpoint in a later `vidra-core` change.

`vidra-search` exposes a **separate, internal** contract at
`vidra-search/api/openapi.yaml` (all under `/internal/v1`, HMAC-authenticated). It
is consumed **only by `vidra-core`** — never the frontend — so changes there are a
`vidra-core` ⇄ `vidra-search` two-repo concern, staged the same back-compat way.

## CI

Each repo runs its own GitHub Actions:
- **vidra-core** — `backend-ci` (`make ci`), `backend-integration`, `openapi`, `ci-guard`.
- **vidra-user** — `frontend-ci` (`npm run ci`), `contract-ci`, `frontend-e2e-backed`
  (checks out `vidra-core` and runs the UI against the live backend), `ci-guard`.
- **vidra-search** — `search-ci` (`make ci`), `search-integration`, `openapi`, `ci-guard`.

This meta-repo runs `meta-ci` (validates `bootstrap.sh` and the full-stack compose).

## Autonomous development (Ralph)

Run a **per-repo loop** inside each component checkout — this is Ralph's native
single-working-tree model:

```bash
cd vidra-core && ralph --live      # uses vidra-core/.ralphrc
cd vidra-user && ralph --live      # uses vidra-user/.ralphrc
```

Each loop's terminal step is a plain `git add -A && git commit && git push` against
that repo's own `main` — no cross-repo pointer to bump. For a change that spans both
(e.g. an API endpoint), run the two loops **sequentially, backend first** (see the
contract note above).

The former monorepo root orchestrator (`.ralphrc`, `.ralph/PROMPT.md`,
`.ralph/fix_plan.md`) is **legacy** and no longer drives a loop from here. The
cross-cutting product specs under [`.ralph/specs/`](.ralph/specs/) (architecture,
PeerTube parity ledger, security, testing) are **preserved here as product docs**,
since they describe the whole platform rather than either component.

## License
TBD.
