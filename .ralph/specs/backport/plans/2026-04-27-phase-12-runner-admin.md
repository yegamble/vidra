# Phase 12 Runner De-stub + Admin UI Implementation Plan

Created: 2026-04-27
Author: yegamble@gmail.com
Status: VERIFIED
Approved: Yes
Iterations: 0
Worktree: No
Type: Feature

## Summary

**Goal:** Close B14 from `docs/plans/2026-04-22-feature-parity-audit.md` by (a) verifying and hardening the vidra-core runner subsystem with end-to-end integration tests, schema extensions for PeerTube-parity capability metadata, and a paginated/filterable jobs listing plus a health-aggregate endpoint, and (b) extending the Phase-7 vidra-user `/admin/runners` baseline page with a top-level health dashboard, filterable/paginated job monitor, runner detail drawer, token expiry presets, and capability/version/last-error surfacing.

**Architecture:**
- **vidra-core:** One additive migration (`104_add_runner_capabilities.sql`), domain extensions for `RemoteRunner` (runner_version, ip_address, capabilities), repository filtering on jobs, new `/api/v1/runners/health` aggregate endpoint, full register→request→accept→update→success integration test against an ephemeral Postgres (testcontainers pattern matching existing repo tests).
- **vidra-user:** `admin-runners-page.tsx` decomposes into `runner-health-cards.tsx`, `runner-job-filters.tsx`, `runner-detail-drawer.tsx`, plus existing list/jobs sub-sections. Filters URL-sync via `useSearchParams`. Polling consolidates into a single `Promise.all` tick. 13-locale i18n parity preserved.

**Tech Stack:** Go 1.22 (chi router, sqlx, goose migrations, testify) on the backend. Next.js 15 App Router + React 19 client components, Radix UI Sheet, Tailwind v4, `useApi` hook, `next-intl`, Vitest, Playwright on the frontend.

---

## Scope

### In Scope

**vidra-core:**
- Migration `104_add_runner_capabilities.sql` adding `runner_version TEXT NOT NULL DEFAULT ''`, `ip_address TEXT NOT NULL DEFAULT ''`, `capabilities JSONB NOT NULL DEFAULT '{}'::jsonb` to `remote_runners`.
- Domain `RemoteRunner` extended with the three fields (JSON tags `runnerVersion`, `ipAddress`, `capabilities`).
- `RunnerRepository.RegisterRunner` captures the new fields from the request payload + `r.RemoteAddr` / `X-Forwarded-For`.
- `RunnerRepository.ListAssignments(ctx, opts)` accepts `Start, Count int; State []domain.RemoteRunnerJobState; RunnerID *uuid.UUID` and returns `(items, total, error)`. Existing zero-arg call site becomes `opts.IsZero()` path returning everything (back-compat).
- New `RunnerRepository.HealthMetrics(ctx)` returning `{TotalRunners, OnlineRunners, OfflineRunners, JobsInFlight, JobsFailed24h, AvgCompletionMs}` — single SQL with CTEs.
- New admin handler `RunnerHealth` wired at `GET /api/v1/runners/health` (admin-only, returns the metrics struct).
- `ListJobs` handler accepts `start`, `count`, `state` (repeatable), `runnerId` query params and returns `{total, data}` where `total` is the filtered count.
- `RegisterRunner` handler decodes the new optional fields and persists them.
- Integration test `internal/httpapi/handlers/runner/lifecycle_integration_test.go` exercises the full lifecycle against a real Postgres via `database/runtest.NewTestDB(t)` (already used by other repo integration tests; see `internal/repository/encoding_repository_test.go`).
- Wiring tests assert the new health route is registered.

**vidra-user:**
- `RemoteRunner` type extended with optional `runnerVersion`, `ipAddress`, `capabilities` fields.
- `runnersService.listJobAssignments(opts)` accepts `{ start, count, state[], runnerId, q }` and forwards as query params (alphabetical, encoded).
- `runnersService.getHealthMetrics()` new method hitting `/api/v1/runners/health`.
- `runnersService.createRegistrationToken({ expiresAt })` already supports the field — UI now exposes preset chips (7d / 30d / 90d / Never / Custom).
- New component `RunnerHealthCards` rendering 4 summary cards (Total / Online / In-flight / Failed 24h) with skeleton loading states; participates in the page-level autoRefresh tick.
- New component `RunnerJobFilters`: multi-select state chips, runner dropdown (sourced from already-loaded `runnersData`), jobUUID `q` text input (debounced 300ms), URL-sync via `useSearchParams`.
- Pagination: default 50/page, "Load more" button when `loaded < total`, request appends to current list (matches PeerTube comment-list pattern at `src/components/comment-section.tsx:loadMore`).
- New component `RunnerDetailDrawer` (Radix `Sheet`, slides from right). Shows: name, description, status, lastSeenAt, registered date, runner_version, ip_address, capabilities (JSON tree, two levels deep), 10 most recent jobs for that runner (re-uses `listJobAssignments({ runnerId, count: 10 })`).
- Token-create dialog gains preset expiry chips + a custom date picker that opens behind "Custom".
- Runners table gains `Version` and `Last error` columns (when populated; empty cell when blank — no placeholder text).
- 13-locale i18n keys added for all new strings; `pnpm i18n:check` passes.
- `admin-runners-page.tsx` orchestrator stays under 500 lines after extracting subcomponents.
- Vitest unit coverage for the four new/extended subcomponents and the new service methods. Playwright extends `e2e/admin-runners.spec.ts` with TS-001..TS-005 from §E2E Test Scenarios.

### Out of Scope

- A new `/admin/runners/dashboard` or `/admin/runners/{id}` route — drawer + cards-above-tabs is the chosen UX (see Approach).
- Charts/graphs (sparklines, retention curves) on the dashboard — cards-only for this phase. Captured as Deferred Idea.
- Runner-side software (the actual encoder daemon) — that lives outside both repos.
- Per-runner job throttling controls (concurrency limit, priority bias) — backend doesn't expose them today and no compelling need now. Deferred Idea.
- Notification preferences for runner failures — `notifications` system already covers admin alerts via existing channels; tying runner-failure events into it is its own scope.
- Editing runners (rename, change description) — PeerTube doesn't expose that in admin UI either; out of scope.
- Auth-token rotation for already-registered runners — runners must be re-registered if rotation is needed; matches PeerTube.

---

## Approach

**Chosen:** Cards-above-tabs + right-side detail drawer + paginated/filtered jobs + extension subcomponents (no new routes).

**Why:** Single-page admin surface minimizes nav round-trips. Drawer keeps the runner-list table primary while exposing detail on demand. URL-synced filters via `useSearchParams` make state shareable and survive reloads. Cost: `admin-runners-page.tsx` orchestrator must split into subcomponents to stay under the 800-line guideline; we lose deep-linkability for individual runners (mitigated by drawer-state-in-URL via `?detailRunner=<id>`).

**Alternatives considered:**
- *Dedicated `/admin/runners/dashboard` + `/admin/runners/{id}` routes* — cleaner URLs and natural deep-linking, but quadruples sidebar/nav surface and forces a page-level data refetch when admins context-switch between list and detail (the most common flow). Rejected.
- *Inline row-expand for detail* — saves the drawer component but cramps the table at narrow viewports and conflicts with the existing horizontal-scroll layout. Rejected.
- *Cards as a separate tab ("Health")* — keeps the existing two-tab structure pure but hides what should be the always-visible signal. Rejected.

---

## Context for Implementer

> Write for an implementer who has never seen the codebase. Both repos contribute.

- **Patterns to follow:**
  - Existing tab layout: `src/components/pages/admin-runners-page.tsx:233-250`. Keep the tablist contract (`role="tab"`, `aria-selected`).
  - Existing `useApi` hook usage: `src/components/pages/admin-runners-page.tsx:64-75`. The hook returns `{data, error, refetch}` and surfaces `ApiError.message` as `"<status> <statusText>"` (see `isNotEnabledError` at `:48-50`).
  - i18n usage: `useTranslations("Runners")` then `t("key")`. Add new keys under the same namespace; add the same keys to all 13 locale files in `messages/`. CI script `pnpm i18n:check` (see `scripts/i18n-check.mjs`) enforces parity.
  - Radix Sheet for drawer: existing usage at `src/components/ui/sheet.tsx` (already in repo). Use `Sheet`, `SheetContent side="right"`, `SheetHeader`, `SheetTitle`.
  - URL-synced filters: `useSearchParams` + `useRouter` from `next/navigation`. See `src/components/pages/search-page.tsx` filter wiring for an existing pattern (debounced URL writes via `router.replace(`${pathname}?${params}`, { scroll: false })`).
  - Backend handler pattern: `internal/httpapi/handlers/runner/handlers.go` — use `shared.WriteJSON` / `shared.WriteError` from `internal/httpapi/shared`. URL params via `chi.URLParam`. Auth context via `middleware.GetUserIDFromContext`.
  - Backend repo pattern: `internal/repository/runner_repository.go` — sqlx with named queries, returns `domain.*` structs, errors mapped to `domain.ErrNotFound` / `domain.ErrConflict` / `domain.ErrForbidden`.
  - Backend integration test pattern: `internal/repository/encoding_repository_test.go` uses `database/runtest.NewTestDB(t)` for ephemeral Postgres + auto-migration.
- **Conventions:**
  - File names kebab-case. New components: `runner-health-cards.tsx`, `runner-job-filters.tsx`, `runner-detail-drawer.tsx`.
  - All API errors logged via `logger.error()` from `@/lib/telemetry/logger`; toast on user-visible failures (existing pattern).
  - No `any` — extend `RemoteRunner` with concrete optional fields. `capabilities: Record<string, unknown>` is the ONLY exception (JSONB).
  - 13 locales: `en, es, fr, de, ja, zh, ko, pt, ru, ar, it, pl, nl`. New keys go in every file.
  - Backend JSON tags: camelCase (matches existing `lastSeenAt`, `expiresAt` etc.). Backend column names: snake_case.
  - Migrations: numbered three-digit prefix matching existing run (`104_*.sql`). Use `-- +goose Up` / `-- +goose Down` blocks. `ADD COLUMN IF NOT EXISTS` with `DEFAULT` for back-compat.
- **Key files:**
  - `src/components/pages/admin-runners-page.tsx` — orchestrator (extracted into subcomponents).
  - `src/lib/api/services/runners.ts` — service module (extended).
  - `src/lib/api/types.ts:895-949` — runner types (extended).
  - `messages/en.json:538-599` — Runners namespace (extended in all 13 files).
  - `e2e/admin-runners.spec.ts` — extended for new scenarios.
  - `internal/httpapi/handlers/runner/handlers.go` — new `RunnerHealth` handler, `ListJobs` accepts query params, `RegisterRunner` decodes new fields.
  - `internal/repository/runner_repository.go` — `ListAssignments` becomes filtered, new `HealthMetrics`.
  - `internal/httpapi/routes.go:297-353` — wire `GET /runners/health`.
  - `internal/domain/peertube_compat.go:37-47` — extend `RemoteRunner`.
  - `migrations/104_add_runner_capabilities.sql` — new migration.
- **Gotchas:**
  - `routes.go:298` already conditionally wires real handlers when `deps.RunnerRepo != nil`; production `app.go:371` always sets it. The conditional 501 fallback is reachable only in tests without a DB. Phase 12 keeps the conditional intact and ADDS routes inside the `if` branch only.
  - `RegisterRunner` returns the runner's `runnerToken` ONLY on first creation (`handlers.go:151-156`); subsequent reads strip `Token`. Don't store `runnerToken` on the FE — runners pass it as `X-Runner-Token` header on every request, not the FE.
  - `remote_runner_job_assignments.encoding_job_id` is a UUID FK to `encoding_jobs`, but the JSON field is named `jobUUID` (string). Match the existing tag.
  - `ListAssignments` response includes a hydrated `runner` and `job` per row — preserved when filtering. Don't break the hydration loop in `ListJobs`.
  - PeerTube's `/api/v1/runners` returns `{total, data}` where `total` is the GLOBAL total when no filter applied; with filters, `total` is the FILTERED total. Backend must compute count via the same WHERE clause as the page query.
  - `useSearchParams` returns a URLSearchParams-like object. Debounce URL writes (300ms) to avoid history thrash on chip toggling.
  - Existing E2E `admin-runners.spec.ts` was authored under "Phase 7" but the file lives in `e2e/`. Keep the file name; extend its describe block.
  - i18n: `messages/en.json:32` exposes `Admin.runners`; sidebar already references `t("runners")`. New top-level keys under `Runners` namespace.
- **Domain context:** A "remote runner" is an out-of-process worker (typically another machine) that polls vidra-core for encoding jobs, processes them with FFmpeg, and uploads the resulting media. PeerTube's runner protocol defines `register / unregister / jobs/request / jobs/{jobUUID}/{accept,abort,update,error,success}` plus file uploads. vidra-core implements that protocol verbatim (see `routes.go:302-324`). Admins generate registration tokens, hand them to runner operators out-of-band, runners self-register, then poll for work. The admin UI surfaces the resulting state.

## Runtime Environment

- **Start command (FE):** `pnpm dev` (Turbopack, port 3000)
- **Start command (BE):** `pnpm dev:full` from `vidra-user` (boots `vidra-core` Docker stack incl. Postgres) per `docs/plans/2026-04-22-payment-reconciliation-dual-mode.md`
- **Health check:** `curl -fs http://localhost:8080/api/v1/runners/health` (Admin auth required); returns aggregate JSON
- **Restart procedure:** `pnpm test:run` for vidra-user; `cd ../vidra-core && go test ./internal/httpapi/handlers/runner/... && go test ./internal/repository/...` for vidra-core; `pnpm test:e2e` for browser flows

## Assumptions

- `app.DB` is non-nil in production (Postgres connection succeeds); confirmed at `internal/app/app.go:371` always sets `RunnerRepo`. Tasks 1–4 depend on this — Task 4 verifies via integration test.
- `database/runtest.NewTestDB(t)` exists and runs migrations; confirmed by usage in existing tests like `encoding_repository_test.go`. Task 4 depends on this.
- The 13-locale i18n parity guard (`pnpm i18n:check`) is already CI-enforced per `2026-04-24-phases-1-6-audit-remediation.md` (commit `9bfde5d`). Task 10 depends on this.
- Radix `Sheet` component is already in `src/components/ui/sheet.tsx`. Task 8 depends on this. Verified via `find src/components/ui -name "sheet*"`.
- `useSearchParams` + `useRouter` URL-sync pattern with debounce already exists in `search-page.tsx`. Task 7 mirrors this. If the search-page implementation differs significantly, Task 7 implements its own debounce helper.
- PeerTube's documented runner schema does NOT include version/IP — those are vidra-core extensions. Backwards compatibility with PeerTube-style runner clients is preserved because the new fields are optional in `RegisterRunner`.

## Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Schema migration on `remote_runners` blocks if table is hot | Low | Medium | `ADD COLUMN IF NOT EXISTS` + `DEFAULT` so writes continue without backfill. No constraint changes. |
| Filter param parsing accepts garbage and crashes handler | Medium | Medium | Strict validation: `state` matches the enum; unknown `runnerId` returns empty data; `start`/`count` clamped to `[0, 500]`. |
| Drawer breaks ARIA/focus trap | Low | Medium | Reuse Radix Sheet primitives — focus trap, escape close, aria-labelled headers all built-in. |
| URL-sync thrashes browser history on chip toggling | High | Low | Debounce 300ms, use `router.replace` not `router.push` so back-button skips intermediate states. |
| `pnpm i18n:check` parity drift across 13 locales | High | High | DoD on Task 10 explicitly runs `pnpm i18n:check`; new keys added in batches across all 13 files in the same commit. |
| Polling 3 endpoints simultaneously triples request load | Medium | Low | Single `Promise.all([listRunners, listJobAssignments(currentFilters), getHealthMetrics])` per autoRefresh tick — same network volume as one tick today, just fanned out. |
| Capabilities JSONB shape ambiguity (different runner versions emit different structures) | Medium | Low | Render generic key-value tree (`Object.entries` recursion, depth=2). No schema enforcement on FE. |
| Backend integration test against testcontainers Postgres exceeds CI memory budget | Low | Medium | Reuse `runtest.NewTestDB(t)` which is already used by other tests in CI; no new infra. |
| Backend `ip_address` capture from `r.RemoteAddr` returns `127.0.0.1` behind proxy | Medium | Low | Honor `X-Forwarded-For` (first hop) when present; documented in handler comment. |
| FE drawer fetches `listJobAssignments({ runnerId, count: 10 })` but backend returns ALL when filter not implemented yet | High | Medium | Task 3 (filter param support) is a dependency of Task 8. DoD on Task 3 verifies `?runnerId=` narrows results. |

⚠️ Mitigations are commitments — verification checks they're implemented.

## Goal Verification

### Truths

1. Admin loading `/admin/runners` sees 4 health cards above the tabs that reflect live backend aggregates and update on the auto-refresh tick. (TS-001)
2. Admin can generate a registration token with a preset expiry (7d / 30d / 90d / Never / Custom date), and the backend stores `expires_at` as a non-null timestamp for the chosen preset. (TS-002)
3. Admin can filter the jobs tab by state (multi-select chips), by runner (dropdown), and by jobUUID search text; URL search params reflect the active filters; pagination "Load more" appends the next 50. (TS-003, TS-005)
4. Admin clicking a runner row opens a right-side drawer showing the runner's name, version, IP, capabilities, registered/last-seen dates, and the 10 most recent job assignments. Drawer state is reflected in the URL via `?detailRunner=<id>`. (TS-004)
5. Non-admin users navigating to `/admin/runners` get `notFound`. (TS-006)
6. When `deps.RunnerRepo` is nil (test fixture), all admin runner endpoints return 501 and the FE shows the "not enabled" banner without crashing. (TS-007)
7. The full runner lifecycle (token generate → runner register → job request → accept → progress update → success) succeeds end-to-end against a real Postgres in `lifecycle_integration_test.go` and persists expected state at each step.
8. `pnpm test:run`, `pnpm test:e2e`, `pnpm lint`, `pnpm typecheck`, `pnpm build` all pass; `pnpm i18n:check` passes; `cd ../vidra-core && go test ./...` passes.

### Artifacts

- `src/components/pages/admin-runners-page.tsx` (orchestrator, ≤500 lines after extraction)
- `src/components/runner-health-cards.tsx` (new)
- `src/components/runner-job-filters.tsx` (new)
- `src/components/runner-detail-drawer.tsx` (new)
- `src/lib/api/services/runners.ts` (extended)
- `src/lib/api/types.ts` (extended)
- `messages/{13 locales}.json` (extended)
- `e2e/admin-runners.spec.ts` (extended)
- Backend: `migrations/104_add_runner_capabilities.sql`, `internal/domain/peertube_compat.go`, `internal/repository/runner_repository.go`, `internal/httpapi/handlers/runner/handlers.go`, `internal/httpapi/routes.go`, `internal/httpapi/handlers/runner/lifecycle_integration_test.go`

## E2E Test Scenarios

### TS-001: Health dashboard renders aggregates
**Priority:** Critical
**Preconditions:** Admin authenticated; backend has at least one runner registered + one assigned job
**Mapped Tasks:** Task 6, Task 3 (backend health endpoint)

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Navigate to `/admin/runners` | 4 cards visible above tabs: Total runners, Online, In-flight jobs, Failed (24h) |
| 2 | Read each card's number | Numeric values render (no skeleton); match the backend health response |
| 3 | Toggle Auto-refresh ON | Cards re-fetch on the 10s tick (network call observed) |

### TS-002: Generate token with preset expiry
**Priority:** Critical
**Preconditions:** Admin authenticated; backend has runner endpoints enabled
**Mapped Tasks:** Task 9 (frontend), Task 1/3 (backend stores expiresAt)

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Click "Generate token" button | Dialog opens with preset chips: 7d, 30d, 90d, Never, Custom |
| 2 | Click "30d" chip | Chip is selected (visual highlight) |
| 3 | Click "Generate" | Dialog shows the new token string and Copy button |
| 4 | Refresh tokens list | New token appears with "Expires {date 30 days from now}" |

### TS-003: Filter jobs by state
**Priority:** High
**Preconditions:** Admin authenticated; backend has jobs in multiple states
**Mapped Tasks:** Task 7 (frontend), Task 3 (backend filter)

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Navigate to `/admin/runners` Jobs tab | All jobs render |
| 2 | Click "Failed" state chip | URL updates to `?state=failed`; only failed jobs render |
| 3 | Click "Aborted" state chip (without unselecting Failed) | URL updates to `?state=failed&state=aborted`; both states render |
| 4 | Click "Clear filters" link | URL strips state params; all jobs re-render |

### TS-004: Open runner detail drawer
**Priority:** High
**Preconditions:** Admin authenticated; ≥1 runner registered with version + capabilities
**Mapped Tasks:** Task 8 (drawer), Task 1+3 (backend fields)

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Navigate to `/admin/runners` Runners tab | Runner table renders with rows |
| 2 | Click first runner's row | Right-side drawer slides in showing: name, version, IP, capabilities tree (key-value), registered date, last seen |
| 3 | Read URL | URL includes `?detailRunner=<id>` |
| 4 | Read "Recent jobs" section in drawer | Up to 10 most recent assignments for THAT runner only |
| 5 | Press Escape | Drawer closes; URL strips `?detailRunner=` |

### TS-005: Job pagination Load more
**Priority:** Medium
**Preconditions:** Admin authenticated; ≥51 jobs exist
**Mapped Tasks:** Task 7 (frontend), Task 3 (backend pagination)

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Navigate to `/admin/runners` Jobs tab | First 50 jobs render; "Load more" button visible |
| 2 | Click "Load more" | Next 50 append below; button disappears when total reached |
| 3 | Apply state filter | List resets to page 1; total count updates from backend |

### TS-006: Non-admin gating
**Priority:** Critical
**Preconditions:** Moderator (charlie_mod) authenticated
**Mapped Tasks:** existing (no change)

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Navigate to `/admin/runners` as moderator | `notFound()` triggers; no Runners heading rendered |

### TS-007: 501 not-enabled fallback
**Priority:** High
**Preconditions:** Admin authenticated; backend started without `deps.RunnerRepo` (test config)
**Mapped Tasks:** existing (no regression)

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Navigate to `/admin/runners` | "Remote runners are not enabled on this instance." banner renders; tabs still present; no console errors |

---

## PeerTube Parity Check

PeerTube's runner admin UI (Angular `client/src/app/+admin/system/runners/`) ships:
- A registration tokens table with generate / copy / delete (✓ matched).
- A runners table with name / description / status / lastContact / delete (✓ matched + extended with version/IP/capabilities columns).
- A jobs table with state filter, runner filter, jobUUID search, pagination, cancel/delete actions (matched in Phase 12 — Phase 7 shipped only the cancel/delete; this phase adds filtering + pagination + search).

PeerTube does NOT expose a top-level health-metrics dashboard — that is a vidra extension. PeerTube does NOT track runner version / IP / capabilities at the schema level — also a vidra extension. PeerTube's runner protocol (`/api/v1/runners/jobs/request|accept|abort|update|error|success` + file upload paths) is preserved verbatim and unchanged by this phase.

## Vidra-Specific / Requested Features

No backend extension impact for the nine canonical extensions (IOTA Crypto Payments, Direct Messaging, Real-time Stream Chat, Inner Circle, ATProto Federation, IPFS Distribution, Video Studio, Auto-Captioning, Advanced Analytics) — runners are PeerTube-parity infrastructure, not a vidra extension. The capability/version/IP columns and the `/runners/health` aggregate are vidra-specific UX additions on the parity baseline.

## Verification Plan

- `pnpm test:run` — Vitest unit suite (must end at 0 failures; coverage ≥ 80%).
- `pnpm test:e2e` — Playwright (TS-001..TS-007 from §E2E Test Scenarios).
- `pnpm lint && pnpm typecheck && pnpm build` — gating checks (must each exit 0).
- `pnpm i18n:check` — locale parity guard (must exit 0).
- `cd ../vidra-core && go test ./...` — backend unit + integration tests (must end at 0 failures).
- `cd ../vidra-core && go vet ./... && goose -dir migrations status` — schema parity check (migration 104 listed as Applied after `goose up`).
- Manual browser verification (Claude Code Chrome or playwright-cli) for TS-001..TS-005 against `pnpm dev:full` stack — confirms cards/drawer/filters render correctly with real backend data.

## Progress Tracking

- [x] Task 1: vidra-core schema + domain — runner capabilities migration & struct
- [x] Task 2: vidra-core repository extensions — filtered ListAssignments + HealthMetrics
- [x] Task 3: vidra-core handlers — ListJobs filters + RunnerHealth + RegisterRunner enrichment + route wiring
- [x] Task 4: vidra-core integration test — full runner lifecycle against real Postgres
- [x] Task 5: vidra-user types + service extensions — listJobAssignments(opts) + getHealthMetrics
- [x] Task 6: vidra-user health dashboard cards
- [x] Task 7: vidra-user job filters + pagination
- [x] Task 8: vidra-user runner detail drawer
- [x] Task 9: vidra-user token expiry presets + last-error + capabilities/version columns
- [x] Task 10: vidra-user page assembly + 13-locale i18n parity
- [x] Task 11: vidra-user E2E coverage (TS-001..TS-007)

**Total Tasks:** 11 | **Completed:** 11 | **Remaining:** 0

---

## Implementation Tasks

### Task 1: vidra-core schema + domain — runner capabilities migration & struct

**Objective:** Add `runner_version`, `ip_address`, `capabilities` columns to `remote_runners` table; extend the domain struct.
**Dependencies:** None
**Mapped Scenarios:** TS-004

**Files:**
- Create: `migrations/104_add_runner_capabilities.sql` (vidra-core repo)
- Modify: `internal/domain/peertube_compat.go` (vidra-core)

**Key Decisions / Notes:**
- `ADD COLUMN IF NOT EXISTS` with `DEFAULT '' / '{}'::jsonb` — back-compat for existing rows.
- JSON tags: `runnerVersion`, `ipAddress`, `capabilities` (camelCase, matches existing struct).
- `capabilities` typed as `map[string]any`. Down migration drops the columns.

**Definition of Done:**
- [ ] `goose -dir migrations up` adds the three columns; `goose down` removes them.
- [ ] `go build ./...` succeeds.
- [ ] `go vet ./...` reports nothing.

**Verify:**
- `cd /Users/yosefgamble/github/vidra-core && goose -dir migrations up && goose -dir migrations down && goose -dir migrations up && go build ./...`

---

### Task 2: vidra-core repository extensions — filtered ListAssignments + HealthMetrics + RegisterRunner enrichment

**Objective:** Extend `RunnerRepository` so the handler layer can paginate/filter jobs and emit aggregate health metrics, and capture new fields on register.
**Dependencies:** Task 1
**Mapped Scenarios:** TS-001, TS-003, TS-004, TS-005

**Files:**
- Modify: `internal/repository/runner_repository.go`
- Test: `internal/repository/runner_repository_test.go` (or add new `_unit_test.go` if missing)

**Key Decisions / Notes:**
- New struct `ListAssignmentsOpts { Start int; Count int; State []domain.RemoteRunnerJobState; RunnerID *uuid.UUID }`. `Count == 0` returns all (back-compat with current zero-arg call site, which we update to pass `ListAssignmentsOpts{}`).
- `ListAssignments(ctx, opts)` builds `WHERE` dynamically with parameterized placeholders (no string concat); `ORDER BY created_at DESC` then `LIMIT $n OFFSET $m`. Returns `(items, total, error)` where `total` is `SELECT COUNT(*)` over the same WHERE. Two queries in one method, both parameterized.
- New `HealthMetrics(ctx)` returns `domain.RemoteRunnerHealth { TotalRunners, OnlineRunners (lastSeen ≥ now-5m), OfflineRunners, JobsInFlight (state in accepted/running), JobsFailed24h, AvgCompletionMs (from completed_at - accepted_at over last 24h) }`. One CTE-backed SQL.
- `RegisterRunner(ctx, token, name, description, runnerVersion, ipAddress, capabilities)` accepts the new fields; INSERT writes them. Default `''` / `{}` if empty.
- Add `domain.RemoteRunnerHealth` struct in `peertube_compat.go`.

**Definition of Done:**
- [ ] All existing tests still pass (`go test ./internal/repository/...`).
- [ ] New unit tests cover: empty filter returns all; state filter narrows; runnerId filter narrows; start/count paginates; HealthMetrics on empty DB returns all-zero; HealthMetrics with seeded data returns correct counts.
- [ ] No SQL injection vectors (all params placeholdered).

**Verify:**
- `cd /Users/yosefgamble/github/vidra-core && go test ./internal/repository/... -run RunnerRepo -v`

---

### Task 3: vidra-core handlers — ListJobs filters + RunnerHealth + RegisterRunner enrichment + route wiring

**Objective:** Surface the new repository capabilities at the HTTP boundary; wire `/runners/health`.
**Dependencies:** Task 2
**Mapped Scenarios:** TS-001, TS-003, TS-004, TS-005

**Files:**
- Modify: `internal/httpapi/handlers/runner/handlers.go`
- Modify: `internal/httpapi/routes.go`
- Test: `internal/httpapi/handlers/runner/handlers_test.go`
- Test: `internal/httpapi/wiring_test.go`

**Key Decisions / Notes:**
- `ListJobs` parses `start`, `count` (clamp `[0, 500]`, default 0/50), repeated `state` values (`r.URL.Query()["state"]` — validate against the enum, drop unknowns), `runnerId` (validate UUID; error 400 on malformed). Pass to `repo.ListAssignments` as `ListAssignmentsOpts`.
- New `RunnerHealth(w, r)` handler: calls `repo.HealthMetrics(ctx)`, writes `shared.WriteJSON` with the struct.
- `RegisterRunner` decodes `runnerVersion`, `capabilities`. `ipAddress` derived from `X-Forwarded-For` (first comma-separated value, trimmed) or `r.RemoteAddr` host portion as fallback. Persists via the extended `repo.RegisterRunner`.
- Route wiring: inside the `if deps.RunnerRepo != nil` block at `routes.go:298`, add `adminRunners.Get("/health", runnerHandlers.RunnerHealth)`. Also add a `runnersNotImplemented` line in the else block for symmetry.
- Keep the response shape `{total, data}` unchanged for `ListJobs` — `total` is the FILTERED total (matches PeerTube).
- Hydration loop in `ListJobs` (runner + job per assignment) preserved.

**Definition of Done:**
- [ ] `handlers_test.go` covers: filter param parsing (good and bad), pagination clamps, RunnerHealth happy path, RegisterRunner with new fields, RegisterRunner with X-Forwarded-For header captures the right IP.
- [ ] `wiring_test.go` asserts `GET /api/v1/runners/health` is registered when RunnerRepo is wired.
- [ ] `go test ./internal/httpapi/...` passes.

**Verify:**
- `cd /Users/yosefgamble/github/vidra-core && go test ./internal/httpapi/handlers/runner/... ./internal/httpapi/...  -v`

---

### Task 4: vidra-core integration test — full runner lifecycle against real Postgres

**Objective:** Prove the runner subsystem works end-to-end. This is the actual "de-stub" verification.
**Dependencies:** Task 3
**Mapped Scenarios:** All TS — guards against regressions.

**Files:**
- Test: `internal/httpapi/handlers/runner/lifecycle_integration_test.go` (new)

**Key Decisions / Notes:**
- Use `database/runtest.NewTestDB(t)` (same as `encoding_repository_test.go`) for ephemeral Postgres + auto-migration.
- Build a router via `httpapi.NewRouter(deps)` or direct chi mounting of the runner subroute (whichever pattern existing wiring tests use).
- Steps (each with assertions):
  1. Admin POSTs `/runners/registration-tokens/generate` → 201 + token returned.
  2. Pre-create an `encoding_jobs` row in DB (status `pending`).
  3. Anonymous (runner) POSTs `/runners/register` with the token + name + version + capabilities → 201 + `runnerToken` returned. DB row in `remote_runners` has version/IP/capabilities populated.
  4. Runner POSTs `/runners/jobs/request` with `X-Runner-Token` → 200 + assignment + job (or 204 if no jobs; we pre-create one in step 2).
  5. Runner POSTs `/runners/jobs/{jobUUID}/accept` → 204; assignment state == `accepted`, `accepted_at` set.
  6. Runner POSTs `/runners/jobs/{jobUUID}/update` with progress 50 → 200; assignment progress == 50, state == `running`.
  7. Runner POSTs `/runners/jobs/{jobUUID}/success` → 204; assignment state == `completed`, `completed_at` set, `progress == 100`; encoding_job status == `completed`.
  8. Admin GETs `/runners/` → 200 + 1 runner with `Token` redacted.
  9. Admin GETs `/runners/health` → 200 + metrics reflect 1 total runner, 1 online (lastSeen recently touched), 0 in-flight, 0 failed-24h.
  10. Admin GETs `/runners/jobs?state=completed` → 200 + 1 result.
  11. Admin DELETEs the runner → 204; subsequent list returns 0 runners.
- Use `httptest` not real network. Auth admin with a JWT signed via `cfg.JWTSecret` and a user fixture promoted to `RoleAdmin`.

**Definition of Done:**
- [ ] All 11 steps pass.
- [ ] Test runs in CI with the existing testcontainers/runtest setup (no new infra).
- [ ] Test cleanup: `t.Cleanup(func(){ db.Close() })`.

**Verify:**
- `cd /Users/yosefgamble/github/vidra-core && go test ./internal/httpapi/handlers/runner/... -run Lifecycle -v`

---

### Task 5: vidra-user types + service extensions

**Objective:** Mirror backend changes in TS types + extend `runnersService`.
**Dependencies:** Task 3 (backend contract finalized)
**Mapped Scenarios:** TS-001, TS-003, TS-004

**Files:**
- Modify: `src/lib/api/types.ts`
- Modify: `src/lib/api/services/runners.ts`
- Test: `src/lib/api/services/__tests__/runners.test.ts`

**Key Decisions / Notes:**
- Extend `RemoteRunner` with optional `runnerVersion?: string`, `ipAddress?: string`, `capabilities?: Record<string, unknown>`.
- New type `RemoteRunnerHealthMetrics { totalRunners, onlineRunners, offlineRunners, jobsInFlight, jobsFailed24h, avgCompletionMs }`.
- `runnersService.listJobAssignments(opts?: ListJobAssignmentsOpts)` where `ListJobAssignmentsOpts = { start?: number; count?: number; state?: RemoteRunnerJobState[]; runnerId?: string; q?: string }`. Build query string via `URLSearchParams` (state passed as repeated `state=foo&state=bar`).
- `runnersService.getHealthMetrics()` GETs `/api/v1/runners/health`.
- `q` (jobUUID search) is FE-only filter — backend `runnerId` + `state` are server-side; jobUUID `q` filters client-side after fetch (since `jobUUID` is per-row identifier and search would be a `LIKE` query the backend doesn't support). Document this clearly in a code comment.

**Definition of Done:**
- [ ] Service tests cover: listJobAssignments with no opts hits `/api/v1/runners/jobs` (back-compat); with state[] forwards repeated params; with runnerId forwards single param; with start/count forwards them; getHealthMetrics hits `/health`.
- [ ] `pnpm typecheck` passes.

**Verify:**
- `pnpm vitest run src/lib/api/services/__tests__/runners.test.ts && pnpm typecheck`

---

### Task 6: vidra-user health dashboard cards

**Objective:** New `runner-health-cards.tsx` rendering 4 summary cards above the tabs; integrates with the page-level autoRefresh.
**Dependencies:** Task 5
**Mapped Scenarios:** TS-001

**Files:**
- Create: `src/components/runner-health-cards.tsx`
- Test: `src/components/__tests__/runner-health-cards.test.tsx`
- Modify: `src/components/pages/admin-runners-page.tsx` (mount cards above tab list)

**Key Decisions / Notes:**
- Cards: Total runners, Online (lastSeen ≥ now-5m), In-flight jobs, Failed (24h). Each card: heading (i18n), large number, optional sublabel (e.g. "of {total}").
- Skeleton loading state for first paint.
- Error state: muted card with "—" and `aria-label` per i18n.
- `useApi(() => runnersService.getHealthMetrics(), [])` for data; refetch hooked into the autoRefresh timer (lift `refetchHealth` into the page like `refetchRunners`).
- Layout: `grid-cols-2 md:grid-cols-4 gap-3` — Apple HIG, generous spacing.

**Definition of Done:**
- [ ] Test renders cards with mocked metrics; renders skeleton while loading; renders dash on error.
- [ ] Cards visually align with existing page styling (rounded-2xl, accent/20 bg, border-border/30 — matches `admin-runners-page.tsx:255-272`).
- [ ] Page passes refetchHealth into the autoRefresh interval.

**Verify:**
- `pnpm vitest run src/components/__tests__/runner-health-cards.test.tsx`

---

### Task 7: vidra-user job filters + pagination

**Objective:** New `runner-job-filters.tsx` with multi-select state chips, runner dropdown, jobUUID search; pagination "Load more" wiring.
**Dependencies:** Task 5
**Mapped Scenarios:** TS-003, TS-005

**Files:**
- Create: `src/components/runner-job-filters.tsx`
- Test: `src/components/__tests__/runner-job-filters.test.tsx`
- Modify: `src/components/pages/admin-runners-page.tsx` (replace static jobs render with filtered/paginated list)

**Key Decisions / Notes:**
- State chips: 7 chips (assigned/accepted/running/completed/failed/aborted/cancelled). Toggling a chip flips it on/off in the URL `?state=` array.
- Runner dropdown: sourced from `runnersData.data` (already loaded by parent); selecting clears job list and refetches with `runnerId`.
- jobUUID search: text input, debounced 300ms, filters CLIENT-SIDE on the loaded list (documented per Task 5 note); URL-syncs as `?q=`.
- URL sync: `useSearchParams()` + `useRouter().replace()` with `scroll: false`. Custom hook `useFilterUrl(filters, setFilters)` to centralize.
- Pagination: parent component owns `[loaded, total]` derived from response; "Load more" calls `listJobAssignments({ ...filters, start: loaded, count: 50 })` and APPENDS to current list; button hides when `loaded >= total`. State filter changes reset to start=0.
- Reset: "Clear filters" link clears all params, refetches.

**Definition of Done:**
- [ ] Test covers: chip toggle updates URL; runner dropdown updates URL; debounced search input writes URL after 300ms; "Load more" appends; clear filters resets.
- [ ] No URL thrash (assert `router.replace` called with `scroll: false`).

**Verify:**
- `pnpm vitest run src/components/__tests__/runner-job-filters.test.tsx`

---

### Task 8: vidra-user runner detail drawer

**Objective:** New `runner-detail-drawer.tsx` Radix Sheet showing runner metadata + recent 10 jobs for that runner.
**Dependencies:** Task 5
**Mapped Scenarios:** TS-004

**Files:**
- Create: `src/components/runner-detail-drawer.tsx`
- Test: `src/components/__tests__/runner-detail-drawer.test.tsx`
- Modify: `src/components/pages/admin-runners-page.tsx` (open drawer on row click, sync `?detailRunner=`)

**Key Decisions / Notes:**
- Drawer state: lifted to page via `[detailRunnerId, setDetailRunnerId]`; URL-synced via `?detailRunner=`.
- Sections: Header (name, status pill), Identity (description, runnerVersion, ipAddress, registered date, lastSeenAt, "Token redacted"), Capabilities (recursive Object.entries depth=2 — render as `<dt>/<dd>` pairs), Recent Jobs (calls `listJobAssignments({ runnerId, count: 10 })`; reuse the existing job-row markup but pass `compact` flag).
- Loading skeleton for jobs.
- Sheet `side="right"` `className="w-full md:w-[480px]"`.
- Esc / overlay click / X button all close + clear URL param.

**Definition of Done:**
- [ ] Test renders drawer with mocked runner + jobs; closes on Escape; URL syncs.
- [ ] Capabilities render gracefully when missing/empty (dash).
- [ ] Recent jobs render in compact mode.

**Verify:**
- `pnpm vitest run src/components/__tests__/runner-detail-drawer.test.tsx`

---

### Task 9: vidra-user token expiry presets + last-error display + capabilities/version columns

**Objective:** Polish the existing list and dialog with PeerTube-parity columns and the preset expiry chips.
**Dependencies:** Task 5
**Mapped Scenarios:** TS-002, TS-004 (last-error rows)

**Files:**
- Modify: `src/components/pages/admin-runners-page.tsx`
- (Optionally) Create small helper `src/components/token-expiry-picker.tsx` if the dialog gets ≥ 60 lines of new logic
- Test: `src/components/pages/__tests__/admin-runners-page.test.tsx` (extend)

**Key Decisions / Notes:**
- Token-create dialog: 5 chips (7d / 30d / 90d / Never / Custom). Selecting a preset sets `expiresAt = new Date(now + presetMs).toISOString()`. "Never" sends `undefined`. "Custom" reveals a `<input type="date">`.
- Runners table gains "Version" column (renders `r.runnerVersion ?? '—'`).
- Job rows surface `lastError` as a tooltip (truncate to 40 chars; on hover/focus show full string via Radix `Tooltip`).
- Existing i18n keys `jobsLastError`, `listVersion` (NEW key) covered.

**Definition of Done:**
- [ ] Test covers preset chip selection produces correct expiresAt ISO string for 7d/30d/90d; Never sends undefined; Custom reveals date input.
- [ ] Existing 5 admin-runners-page tests still pass.

**Verify:**
- `pnpm vitest run src/components/pages/__tests__/admin-runners-page.test.tsx`

---

### Task 10: vidra-user page assembly + 13-locale i18n parity

**Objective:** Wire all subcomponents into `admin-runners-page.tsx`; add new i18n keys to all 13 locales.
**Dependencies:** Tasks 6, 7, 8, 9
**Mapped Scenarios:** All TS

**Files:**
- Modify: `src/components/pages/admin-runners-page.tsx` (final orchestrator)
- Modify: `messages/en.json` (add new keys under `Runners`)
- Modify: `messages/{es,fr,de,ja,zh,ko,pt,ru,ar,it,pl,nl}.json` (parity)

**Key Decisions / Notes:**
- Final page structure: Header → 4 health cards → tab list → (Runners tab: tokens section + filters? + runners table + drawer mount) | (Jobs tab: filters + paginated jobs).
- Keep page under 500 lines after extraction. If it creeps past 500, extract `runners-tab.tsx` and `jobs-tab.tsx`.
- New i18n keys (under `Runners`):
  - `dashTotal`, `dashOnline`, `dashInFlight`, `dashFailed24h`, `dashLoading`, `dashError`
  - `filtersTitle`, `filtersClear`, `filtersStateLabel`, `filtersRunnerLabel`, `filtersSearchLabel`, `filtersSearchPlaceholder`, `filtersLoadMore`, `filtersTotalCount`
  - `tokensExpiry7d`, `tokensExpiry30d`, `tokensExpiry90d`, `tokensExpiryNever`, `tokensExpiryCustom`
  - `drawerTitle`, `drawerVersion`, `drawerIP`, `drawerCapabilities`, `drawerCapabilitiesEmpty`, `drawerRegistered`, `drawerLastSeen`, `drawerRecentJobs`, `drawerRecentJobsEmpty`, `drawerClose`
  - `listVersion`
- Update sidebar i18n if needed (already references `runners`, no change required).

**Definition of Done:**
- [ ] `pnpm i18n:check` exits 0.
- [ ] All `useTranslations("Runners")` keys defined in every locale.
- [ ] Page line count < 500.

**Verify:**
- `pnpm i18n:check && pnpm typecheck && pnpm lint`

---

### Task 11: vidra-user E2E coverage

**Objective:** Extend `e2e/admin-runners.spec.ts` with TS-001..TS-005 (TS-006/TS-007 already covered or trivial).
**Dependencies:** Tasks 6–10
**Mapped Scenarios:** TS-001, TS-002, TS-003, TS-004, TS-005

**Files:**
- Modify: `e2e/admin-runners.spec.ts`

**Key Decisions / Notes:**
- Use existing `adminPage` and `modPage` fixtures from `e2e/fixtures/auth.ts`.
- Tests must be resilient to backend not being seeded with runners — when runner list is empty, the chip-toggle / drawer scenarios assert appropriately (e.g., button disabled, empty state visible) rather than fail.
- For TS-001 (health cards): assert the 4 card headings render; numeric content is best-effort (≥ 0).
- For TS-002 (token preset): click "30d" chip, click Generate, assert dialog shows token + "Expires {30 days from now}" line in the tokens list after closing.
- For TS-003 (state filter): generate two synthetic jobs via API in `beforeAll` if backend supports it; otherwise assert URL change behavior alone (smoke test).
- For TS-004 (drawer): if a runner exists, click row and assert drawer; if not, skip with reason.
- For TS-005 (Load more): synthetic data dependent — skip with reason if < 51 jobs exist.

**Definition of Done:**
- [ ] `pnpm test:e2e e2e/admin-runners.spec.ts` exits 0.
- [ ] All Playwright assertions are explicit (no soft-assert without comment).

**Verify:**
- `pnpm test:e2e e2e/admin-runners.spec.ts`

---

## Open Questions

None — Batch 1 + Batch 2 covered the gray areas.

### Deferred Ideas

- **Charts on dashboard:** Sparklines for jobs-per-hour, completion-time histogram, per-runner throughput. Held until product signal that admins watch this dashboard regularly.
- **Per-runner concurrency/priority controls:** Backend doesn't expose them; would need a `runner_settings` table.
- **Runner-failure notifications:** Wire runner-error events into the existing notification channel (admin alert on N consecutive failures from one runner).
- **Runner edit:** Rename / change description from admin UI. PeerTube also doesn't expose this — reasonable to defer.
- **OAuth-protected runner registration:** Phase 12 keeps the registration-token pattern. Future hardening could move to short-lived signed tokens.
