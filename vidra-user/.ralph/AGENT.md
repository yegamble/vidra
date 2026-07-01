# Agent Build Instructions — vidra-user (Next.js frontend)

> Scope: the `vidra-user` Next.js / TypeScript frontend only. Run all commands from
> the `vidra-user/` project root. Do not touch the sibling `../vidra-core/` project.

## Stack
Next.js · TypeScript (strict) · Tailwind CSS · custom components · minified inline
SVG icons · Playwright. No UI framework / component library unless the user approves.

## Status: scaffolded (P1 foundation)
The Next.js app is scaffolded: Next 16 (app router) · React 19 · TypeScript (strict) ·
Tailwind v4 · ESLint 9 flat config (`no-console` error, logger-only allow) · Vitest
(unit) · Playwright (e2e smoke). The canonical gate `npm run ci` is green
(typecheck + lint + unit + build + e2e). The structured logger lives in `lib/logger.ts`.
The typed API client is in `lib/api/` (`apiRequest` + `api.*` endpoint fns + provisional
`types.ts`) over `lib/config.ts` (`apiBaseUrl` from `NEXT_PUBLIC_API_BASE_URL`); it sends
`X-Correlation-ID` and maps the error envelope to `ApiError`. The app shell
(`components/Header.tsx`) + home discovery feed (`components/VideoFeed.tsx`, a client
component → route-mockable, with loading/error/empty/grid states; `components/VideoCard.tsx`;
`components/ui/*` primitives) render the public feed; the watch page
(`app/videos/[id]` → `components/WatchView.tsx`) plays the original via a native
Range-capable `<video>` with title/views/date/duration/dimensions/description and
loading/not-found/error states. `lib/format.ts` has display helpers (count, relative time,
duration). Auth: `components/auth/AuthProvider.tsx` (`useSession`) holds the session
client-side — the access token lives in the in-memory `lib/api/auth-store.ts` (auto-attached
by the API client, never persisted/logged), `lib/api/auth.ts` wraps register/login/logout/me,
the login + signup pages (`app/login`/`app/signup` → `LoginForm`/`SignupForm`) sign in /
register (signup maps 422 field errors inline and shows a registration-closed notice from
`instance.registration_enabled`), and the header `AccountMenu` shows sign in / username +
sign out. Search: header `SearchBox` → `/search?q=` (`app/search` → `components/SearchResults.tsx`,
client title search reusing the card + state primitives). The public channel page
(`app/channels/[handle]` → `components/ChannelView.tsx`) loads `api.getChannel` +
`api.listChannelVideos` and renders the channel header + a `VideoCard` grid with
loading/not-found/error/empty states. Moderation: the moderator/admin queue
(`app/moderation` → `components/ModerationQueue.tsx`, reached via the role-gated
`ModerationNavLink`) lists abuse reports (`GET /admin/reports`, Open/All filter) and
resolves them accept/reject with an internal note (`POST /admin/reports/:id/resolve`) —
DB-effect VERIFIED in `e2e-backed/moderation.spec.ts`. A moderator can **block** a reported video from the queue card (`POST /admin/videos/:id/block`),
and the moderation block-list (`app/moderation/blocked` → `components/BlockedVideosView.tsx`,
reached via the role-gated `ModerationTabs` sub-nav) lists blocked videos
(`GET /admin/videos/blocked`) and **unblocks** them (`DELETE /admin/videos/:id/block`) —
both DB-effect VERIFIED in `e2e-backed/blocked-videos.spec.ts`. The **All videos** tab
(`app/moderation/videos` → `components/AdminVideosView.tsx`) browses every video
(`GET /admin/videos`, any privacy/state, with a `blocked` flag + title search) and
block/unblocks any in place — DB-effect VERIFIED in `e2e-backed/admin-videos.spec.ts`.
The **Comments** tab (`app/moderation/comments` → `components/AdminCommentsView.tsx`)
browses every comment (`GET /admin/comments`, author + video link + body search) and
deletes any (`DELETE /comments/:id`, moderator-allowed) — DB-effect VERIFIED in
`e2e-backed/admin-comments.spec.ts`. The **Watched words** tab (`app/moderation/watched-words`
→ `components/WatchedWordsView.tsx`) adds/removes instance-wide watched terms
(`GET/POST/DELETE /admin/watched-words`, 409 on duplicate) — DB-effect VERIFIED in
`e2e-backed/watched-words.spec.ts`. Account mutes: a signed-in
viewer **Mutes** a comment's author (`CommentsSection` → `POST /me/mutes/accounts/:author_id`,
via `Comment.author_id`), hiding that account's comments; the muted-accounts page
(`app/settings/mutes` → `components/MutedAccountsView.tsx`, linked from `/settings`) lists
(`GET /me/mutes/accounts`) and **unmutes** (`DELETE …`) — DB-effect VERIFIED in
`e2e-backed/mutes.spec.ts`.
Admin: the admin-only users
page (`app/admin/users` → `components/AdminUsersView.tsx`, reached via the admin-only
`AdminNavLink`) lists/searches accounts (`GET /admin/users?q=`) and edits each user's
role + active flag (`PATCH /admin/users/:id`), disabling the admin's own row — DB-effect
VERIFIED in `e2e-backed/admin-users.spec.ts`. Still TODO: the rest of P3 (password
reset, MFA, settings/profile), more component primitives
(Card/Badge/Skeleton/Input), custom player controls, the backend-backed Playwright profile
(login/signup are mock-tested only — NOT `VERIFIED` until proven against a real backend+DB),
and `instrumentation.ts` for OTel.

## Project setup (after scaffold)
```bash
cp .env.example .env        # set NEXT_PUBLIC_API_BASE_URL to the vidra-core API
npm install                 # or pnpm install
```

## Local development
```bash
npm run dev                 # Next.js dev server
```
Point the app at a backend with `NEXT_PUBLIC_API_BASE_URL`:
- Mocked API (UI scaffolding only).
- Local `vidra-core` via Docker Compose (required for data-effect verification).
- A configured remote backend URL.

## Build
```bash
npm run build               # production build (must pass before completion)
npm run start               # serve the production build
```

## Tests
```bash
npm run test                # unit / component tests
npm run lint                # eslint
npm run typecheck           # tsc --noEmit (strict)
npx playwright test         # e2e / smoke
```
Playwright serves the app on port 3000 by default (what CI + these docs assume). If
3000 is taken locally (e.g. another project's dev server), override the port:
`E2E_PORT=3100 npm run e2e` (and `E2E_PORT=3100 npm run e2e:backed`). The default is
unchanged, so CI parity holds. **Caveat for backed runs at a non-3000 port:** the
backend's CORS allowlist must include that origin or the browser blocks mutations
(signup/report/etc.). Bring up the api with `CORS_ALLOWED_ORIGINS=http://localhost:3100`
(see `vidra-core/docker-compose.yml` — it honours that env). CI runs on :3000, which
the compose default already allows.

### Backed admin harness (deterministic admin)
Admin-gated backed verification (e.g. reading the moderation queue) uses a Playwright
**setup project**: `backed-setup` (`e2e-backed/admin.setup.ts`, `testMatch *.setup.ts`)
is a `dependencies` of `backend-backed`, so it runs FIRST and registers a deterministic
admin (the backend grants admin to the first account on a fresh instance). Specs then
call `adminToken()` / `reportsQueue()` from `e2e-backed/fixtures.ts`. This works against
a **fresh** DB only — locally `docker compose --profile core down -v` first; CI brings up
a fresh stack per run. `backed-setup` never runs under `npm run ci` (that's `--project=chromium`).

## 🔴 Database-effect verification (required for data-mutating features)
Mocks are acceptable for UI scaffolding only. A feature that creates/updates/deletes
data is NOT done until proven end-to-end against a **real `vidra-core` backend with a
real PostgreSQL**. The `backend-backed` Playwright project (`./e2e-backed`, run via
`npm run e2e:backed`) is exactly this — no `page.route` mocks; it drives the UI against
a live backend. It is **never** part of `npm run ci` (which stays mocked and fast).

```bash
# 1. Start the real backend + database (from ../vidra-core), detached. Disable
#    rate limiting so the suite's many register/login calls aren't throttled:
( cd ../vidra-core && RATE_LIMIT_ENABLED=false docker compose --profile core up -d --build )  # pg+redis+migrate+api → :8080
#    If host :8080 is taken, map another host port: RATE_LIMIT_ENABLED=false HTTP_PORT=8088 docker compose --profile core up -d
#    (stale PG-version volume? `docker compose --profile core down -v` to reset the dev data.)
# 2. Build the frontend pointed at it — NEXT_PUBLIC_* is baked at BUILD time, so a
#    plain `npm run dev`/`start` will NOT pick up a new API URL; you must rebuild:
NEXT_PUBLIC_API_BASE_URL=http://localhost:8080 npm run build
# 3. Run the backend-backed project (Playwright starts `next start` and drives a real browser).
#    Some specs seed data via the API directly (e2e-backed/fixtures.ts); set E2E_API_URL
#    to the backend (defaults to :8080; use :8088 if you mapped a different host port):
E2E_API_URL=http://localhost:8080 npm run e2e:backed
```
Each data-mutating e2e must: perform the UI action → assert the row exists/changed in
PostgreSQL (direct query or backend read endpoint) → assert the UI reflects it after a
refetch. Capture a Playwright trace (the `backend-backed` project sets `trace: "on"`)
plus the DB/API read as evidence. Example DB read:
`docker exec vidra-core-postgres-1 psql -U vidra -d vidra -c "SELECT email FROM users WHERE …"`.

This profile also runs in CI: the root `frontend-e2e-backed.yml` workflow stands up
the same compose `core` stack (api on :8080 — free on the runner, no port override)
and runs `npm run e2e:backed` on every push/PR touching either project. It is a
separate job from the canonical `npm run ci` gate (which stays mocked/fast).

## Frontend quality gate (run before declaring completion)
1. `npm run ci` is green — the CANONICAL gate = typecheck + lint + unit test +
   build + Playwright smoke. `frontend-ci.yml` runs this exact script, so
   "passes locally" == "passes in GitHub". Add new required checks to the `ci`
   script, never only to the workflow (`ci-guard.yml` enforces this).
2. backend-backed Playwright profile for every data-mutating flow (DB effect proven)
3. observability checks pass: ESLint `no-console`, no secrets/PII/plaintext in
   logs/analytics/URLs/traces, `traceparent`/correlation propagated to
   `vidra-core` (see `.ralph/specs/observability.md`)
4. branch CI is green (same `npm run ci`); `ci-guard.yml` passes — a local green
   alone is not done

(Individual scripts — `npm run typecheck|lint|test|build`, `npx playwright test`
— remain available for focused runs.)

## Key learnings
- Frontend lives in `vidra-user/` (monorepo subdir).
- CI workflows live at the monorepo root `../.github/workflows/` (GitHub ignores
  workflows in subdirectories); scope frontend jobs with `vidra-user/**` path filters.
- Consume the backend contract; never invent response shapes — record a backend
  dependency instead.
- Update this file with the real commands once the app is scaffolded.
