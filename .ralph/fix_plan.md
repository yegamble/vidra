# Ralph Fix Plan — Vidra Core (backend)

This checkout is **vidra-core** (Go backend). Frontend parity work belongs to the
separate `vidra-user` repo. Items here track backend + API + contract work and
the backend half of PeerTube parity ledger rows.

Priorities follow the Implementation Order in `.ralph/PROMPT.md`. Build one
vertical slice per loop. Do not flip an item to done without passing tests/evidence.

## P0 — Foundation (bootstrap)
- [x] Compileable Go module + Echo HTTP server (`cmd/api`, `internal/httpapi`)
- [x] Config loading from env with validation + `.env.example` (`internal/config`)
- [x] Health (`/healthz`) and readiness (`/readyz`) endpoints + tests
- [x] Postgres pool (`internal/store`) and Redis client (`internal/cache`)
- [x] Numbered migrations: extensions + minimal users/sessions foundation
- [x] sqlc config + first query set (`internal/store/queries/users.sql`)
- [x] Dockerfile + docker-compose (postgres, redis, migrate, api) + Makefile
- [x] Backend CI skeleton (`.github/workflows/backend-ci.yml`)
- [x] Foundation specs: architecture, security, testing
- [ ] Generate sqlc code and wire a real DB-backed query into `/readyz` or a
      `/api/v1/stats` endpoint (requires sqlc + a CI/integration DB)
- [ ] Add integration test that runs against the Compose Postgres/Redis

## P1 — Auth foundation (PT-AUTH-ACCOUNT-SETUP, backend)
- [ ] Password hashing (argon2id) + user registration service + handler
- [ ] Login issuing short-lived JWT access token
- [ ] Refresh-token rotation + revocation backed by `sessions`
- [ ] Email-verification token model + flow (stub email transport)
- [ ] Rate limiting (Redis) on auth endpoints
- [ ] TOTP 2FA enrollment + verification
- [ ] OpenAPI for auth endpoints + Newman smoke collection
- [ ] Unit + integration + security tests for auth

## P2 — API contract
- [ ] Establish `api/openapi.yaml` covering health + auth; generate/validate types
- [ ] Contract CI (`contract-ci.yml`): OpenAPI diff + client check

## P3 — Video upload + storage foundation (PT-PUBLISH-UPLOAD-FILE, backend)
- [ ] Storage interface + local filesystem adapter (path-traversal safe)
- [ ] Upload endpoint (direct), upload-status tracking, size/content-type validation
- [ ] ClamAV scan stage (configurable, fail-closed default) — may BLOCK on infra
- [ ] FFmpeg probe stage with sanitized arg arrays + context timeouts
- [ ] S3-compatible adapter; IPFS adapter (later)

## P4 — Playback, channels, search, moderation, federation, messaging
- [ ] Tracked per PeerTube feature ledger rows as each slice is surveyed/built.
- [ ] ActivityPub first; ATProto modular; SSRF-safe HTTP client shared across all
      remote-fetch paths.

## Notes / learnings
- Repo is empty-bootstrapped as vidra-core. Go 1.26, Docker, migrate v4.17.1.
- Local gate: `make check`. Full gate adds integration/migration via Compose/CI.
- sqlcgen output (`internal/store/sqlcgen`) is not yet generated; no Go code
  imports it, so the module compiles without it. Generate before wiring queries.

## Optional (non-blocking)
<!-- Issue #239: unchecked items here do NOT block Ralph's exit. -->
- [ ] Nice-to-have developer-experience polish

## Completed
- [x] Project initialization (Ralph scaffold)
- [x] PeerTube parity tracking files created (`.ralph/specs/peertube-*`, extensions, acceptance)
