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
`X-Correlation-ID` and maps the error envelope to `ApiError`.
Still TODO (later P1 slices): custom component primitives, the backend-backed Playwright
profile, and `instrumentation.ts` for OTel (real `traceparent` propagation).

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

## 🔴 Database-effect verification (required for data-mutating features)
Mocks are acceptable for UI scaffolding only. A feature that creates/updates/deletes
data is NOT done until proven end-to-end against a **real `vidra-core` backend with a
real PostgreSQL**:

```bash
# 1. Start the real backend + database (from ../vidra-core):
( cd ../vidra-core && make up )          # postgres + redis + migrations + api
# 2. Run the frontend against it:
NEXT_PUBLIC_API_BASE_URL=http://localhost:8080 npm run dev
# 3. Run the backend-backed Playwright profile (define this in playwright config):
npx playwright test --project=backend-backed
```
Each data-mutating e2e must: perform the UI action → assert the row exists/changed in
PostgreSQL (direct query or backend read endpoint) → assert the UI reflects it after a
refetch. Capture a Playwright trace/screenshot plus the DB/API read as evidence.

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
