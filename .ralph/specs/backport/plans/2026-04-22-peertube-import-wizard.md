# PeerTube Instance Import Wizard Implementation Plan

Created: 2026-04-22
Status: VERIFIED
Approved: Yes
Iterations: 1
Worktree: No
Type: Feature

## Summary

**Goal:** Admin-facing wizard (frontend-only) that lets an admin connect vidra to a running PeerTube instance, run a mandatory dry-run, start a real migration, and monitor it to completion against the existing vidra-core `/api/v1/admin/migrations/*` endpoints. After this ships, a vidra admin can import any PeerTube instance and browse the imported users/channels/videos/playlists/comments — which unblocks the product's stated goal.

**Architecture:** New admin sub-route `src/app/[locale]/(main)/admin/migrations` backed by a new page component `admin-migrations-page.tsx` and a stepped modal `migration-wizard-modal.tsx`. A new service `src/lib/api/services/migrations.ts` wraps the 6 backend endpoints. History + active-job state is driven by `useApi` with a 5-second poll while any job is non-terminal. Zero backend changes.

**Tech Stack:** Next.js 15 App Router, React 19, TypeScript, Tailwind v4, Radix primitives, Lucide icons, next-intl, Vitest, Playwright. pnpm (from `pnpm-lock.yaml`).

## Scope

### In Scope
- New admin route `/admin/migrations` and page component (list + active-job card + history).
- Service wrapper for the 6 migration endpoints with full TypeScript types.
- Stepped wizard modal: **Connection → Dry-Run → Confirm → Progress**.
- Mandatory dry-run before a real migration can be submitted.
- Polling (5 s) of active job status until terminal (completed / cancelled).
- Resume action for failed jobs; Cancel action for running/pending/resuming/validating.
- One-active-migration enforcement for **real** migrations, **frontend-side** (see note below).
- Admin nav entry gated on `user?.role === "admin"`.
- Unit tests (Vitest) for service + page + wizard modal + job card + nav.
- E2E test (Playwright) covering happy path and key error states.
- i18n keys for all user-visible strings (en, plus other active locales stay at key-level for later translation).
- Credential-redaction tests — password must never appear in logger context, DOM after close, or localStorage/sessionStorage.

### Out of Scope
- **Backend changes** — all endpoints exist and are used as-is.
- **"Select what to import" scope picker** — backend ETL migrates all entity types; no scope field in `MigrationRequest`. Defer.
- **WebSocket push** — backend has no migration WS channel; 5 s polling is sufficient for minutes-to-hours migrations.
- **Persisting DB credentials** — form-only; never written to any storage.
- **Multi-tenant / multi-concurrent real migrations** — backend's `StartMigration` enforces single-active via `GetRunning`. We also enforce in UI. **DryRun does NOT enforce single-active on the backend** — concurrent dry-runs and dry-run-during-real-migration are allowed server-side. Our UI still blocks the "New migration" button when any non-terminal job exists, as a conservative frontend policy.
- **PeerTube → vidra data delta / re-sync** — backend has `reverse_etl.go` but no exposed endpoint; ignored here.
- **Row deletion from history** — `DELETE /{id}` on a non-terminal job **cancels**; there is no separate delete endpoint. History rows are immutable from the UI.
- **Migration-triggered transcoding or thumbnail regeneration** — already handled by post-migration pipeline on vidra-core.

## Approach

**Chosen:** List page at `/admin/migrations` + stepped modal wizard.

**Why:** Mirrors the existing `admin-jobs-page.tsx` pattern (same polling/refresh idiom, same service/useApi shape) so there is zero invention at the component level. The wizard's stepped modal isolates the dry-run gate cleanly and the list page handles resume/cancel/history. This gives us a shippable surface with minimal new primitives at the cost of a richer modal component.

**Alternatives considered:**
- Dedicated multi-step route (`/admin/migrations/new`) — rejected: requires route refactor, URL-addressable steps add little value for an admin-only, infrequent flow.
- Single flat form + inline progress — rejected: would conflate dry-run and submit, losing the validation gate that the backend's two-call surface assumes.

## Context for Implementer

> You are implementing only the vidra-user frontend. The vidra-core backend is complete and stable — do not modify it.

### Confirmed backend surface (verified during planning)
- `POST /api/v1/admin/migrations/peertube` — body `MigrationRequest` → 201 with `MigrationJob`. Backend calls `GetRunning` first; if a non-terminal job exists, returns `ErrMigrationInProgress` → HTTP 409.
- `POST /api/v1/admin/migrations/{id}/dry-run` — body `MigrationRequest` → 201 with `MigrationJob` (status `pending`, `dry_run: true`). **Key quirk:** `{id}` path param is read by the handler but `service.DryRun` ignores it (see `vidra-core/internal/httpapi/handlers/migration/handlers.go:113-135` and `internal/usecase/migration_etl/service.go:205-245`). The endpoint always creates a NEW job. No `GetRunning` guard — concurrent dry-runs are allowed.
- `GET /api/v1/admin/migrations?count=&start=` → paginated `{data: MigrationJob[], total, limit, offset}`.
- `GET /api/v1/admin/migrations/{id}` → `MigrationJob`.
- `DELETE /api/v1/admin/migrations/{id}` → 204. Cancels running/pending; on terminal/cancelled → `ErrMigrationCantCancel` (HTTP 409).
- `POST /api/v1/admin/migrations/{id}/resume` → 200 with `MigrationJob`. Only valid on `failed`; otherwise `ErrMigrationCantResume` (HTTP 409).

### Confirmed domain types
From `vidra-core/internal/domain/migration.go`:

```ts
// MigrationStatus — exact values, one-to-one
type MigrationStatus =
  | "pending" | "validating" | "dry_run" | "running"
  | "resuming" | "completed" | "failed" | "cancelled";

// isTerminal → only "completed" or "cancelled". "failed" is retryable.

interface EntityStats {
  total: number;
  migrated: number;
  skipped: number;
  failed: number;
  errors?: string[];
}

interface MigrationStats {
  users: EntityStats;
  channels: EntityStats;
  videos: EntityStats;
  comments: EntityStats;
  playlists: EntityStats;
  captions: EntityStats;
  media: EntityStats;
}

// Response JSON key is "stats" (Go `json:"stats,omitempty"`), NOT "stats_json"
interface MigrationJob {
  id: string;
  admin_user_id: string;
  source_host: string;
  status: MigrationStatus;
  dry_run: boolean;
  error_message?: string;
  stats?: MigrationStats;
  source_db_host?: string;
  source_db_port?: number;
  source_db_name?: string;
  source_db_user?: string;
  // source_db_password NEVER appears on responses (Go tag json:"-")
  source_media_path?: string;
  created_at: string;   // ISO
  started_at?: string;  // ISO
  completed_at?: string; // ISO
  updated_at: string;   // ISO
}

interface MigrationRequest {
  source_host: string;      // required
  source_db_host: string;   // required
  source_db_port?: number;  // defaults to 5432 server-side when <=0
  source_db_name: string;   // required
  source_db_user: string;   // required
  source_db_password: string; // required
  source_media_path?: string;
}
```

### Patterns to follow
- Polling + auto-refresh toggle: `src/components/pages/admin-jobs-page.tsx:15-55` (use same `setInterval` + cleanup pattern).
- Federation page admin layout: `src/components/pages/admin-federation-page.tsx:1-80`.
- Service module shape: `src/lib/api/services/admin.ts:3-40`.
- Data fetching: `src/lib/hooks/use-api.ts` (`useApi` returns `{data, loading, error, refetch, setData}`; `useMutation` returns `{mutate, loading, error}`).
- Page route wrapper: `src/app/[locale]/(main)/admin/jobs/page.tsx`.
- i18n: `useTranslations("AdminFederation")` pattern — keys under `messages/*.json`.
- Toast: `sonner` `toast.success` / `toast.error`.
- Tests: `src/components/pages/__tests__/admin-jobs-page.test.tsx`.

### Admin navigation location (pre-identified)
- Mobile drawer: `src/components/sidebar.tsx:147-161`. Admin section opens on `isStaff`. Admin-only links inside `user?.role === "admin"` guard at `:154-159`.
- Desktop sidebar: `src/components/sidebar.tsx:204-218`. Same structure, same guards at `:211-216`.
- **The `/admin/migrations` entry must sit inside the `user?.role === "admin"` block at both `:154-159` and `:211-216`** (migration is admin-only, not moderator-accessible).

### Conventions
- Named exports for components (e.g., `export function AdminMigrationsPage()`).
- `'use client'` at top of interactive components.
- Service functions return **explicit typed promises**; no `any`. Use `unknown` or generics when needed.
- Tailwind utility classes; Apple HIG 4 px spacing scale.
- 44 × 44 minimum touch targets.
- kebab-case file names.
- Import order: external → `@/` internal → relative.
- No emojis in source.

### Telemetry / logging
- `@/lib/telemetry/logger` — `logger.error(message, context)` and `traceApiCall()`.
- **Implementer MUST read `src/lib/telemetry/logger.ts` in Task 1** to verify whether `traceApiCall` auto-captures request bodies. If it does, mutate the context to strip `source_db_password` before passing (or pass a sanitized copy). Never log the full `MigrationRequest`.
- `toast.error` messages must not echo the raw backend error if it contains credential fragments.

### Key files (will be created/modified)
- **Create:** `src/lib/api/services/migrations.ts`
- **Create:** `src/lib/api/services/__tests__/migrations.test.ts`
- **Modify:** `src/lib/api/types.ts` (append `MigrationStatus`, `MigrationRequest`, `MigrationJob`, `MigrationStats`, `EntityStats` at end of file)
- **Create:** `src/app/[locale]/(main)/admin/migrations/page.tsx`
- **Create:** `src/components/pages/admin-migrations-page.tsx`
- **Create:** `src/components/pages/__tests__/admin-migrations-page.test.tsx`
- **Create:** `src/components/admin/migration-wizard-modal.tsx`
- **Create:** `src/components/admin/__tests__/migration-wizard-modal.test.tsx`
- **Create:** `src/components/admin/migration-job-card.tsx`
- **Create:** `src/components/admin/__tests__/migration-job-card.test.tsx`
- **Modify:** `src/components/sidebar.tsx` (add nav entry at `:154-159` and `:211-216`)
- **Modify:** `src/components/__tests__/sidebar.test.tsx` (or create if missing) — asserts admin link visibility gating
- **Modify:** `messages/en.json` (add `AdminMigrations` + `AdminNav.migrations` keys); copy keys to other locales with English placeholder values
- **Create:** `e2e/admin-migrations.spec.ts`

### Gotchas
- **Dry-run endpoint ignores `{id}`.** Client should call `POST /api/v1/admin/migrations/new/dry-run` with the full `MigrationRequest` body. `"new"` is an arbitrary placeholder — any non-empty id would work, but keep it descriptive. Document this in the service file with a comment.
- **Backend `StartMigration` returns HTTP 409** (`ErrMigrationInProgress`) if another migration is already running. UI must show a friendly "another migration is already in progress" message, not a raw error.
- **`MigrationJob.stats` may be absent** on freshly created jobs (empty body or unmarshalled to zero). Progress panel must handle `stats === undefined`.
- **Concurrency guard:** before enabling "New migration", the page checks if any returned job has a non-terminal status. If yes, disable the button and surface the active job card.
- **Credentials:** form has `source_db_password` as `type="password"` with `autocomplete="new-password"`. Never persisted to any storage. Wizard state lives in component state only, wiped on close.
- **Response envelope:** list endpoints return `{data, total, limit, offset}` (see `src/lib/api/helpers.ts` for unwrap pattern). Single-resource GETs return the object directly.
- **Date fields:** Go serializes `time.Time` as RFC3339. Parse with `new Date(...)` for display.

### Domain context
A PeerTube instance stores its data in a PostgreSQL database plus a media directory. The ETL service connects directly to that DB (read-only), extracts users/channels/videos/playlists/comments, and writes them into the vidra schema. Media files are copied from `source_media_path` into vidra's storage. The admin supplies:
- `source_host` — public URL of the PeerTube instance (e.g., `https://peertube.example.com`) — used for activity metadata.
- `source_db_*` — direct PostgreSQL connection credentials to the PeerTube DB.
- `source_media_path` — absolute path on the vidra-core host where PeerTube's media is mounted.

## Runtime Environment

- **Frontend dev server:** `pnpm dev` (Next.js Turbopack, port 3000 by default).
- **Backend:** vidra-core must be running — see `scripts/start-dev.sh`.
- **Health check:** `curl http://localhost:3000/admin/migrations` returns 200 when admin session is present.
- **E2E:** `pnpm test:e2e` — runs Playwright against a fresh dev server.

## Assumptions

- Backend endpoints behave as documented in `internal/httpapi/handlers/migration/handlers.go` and `internal/usecase/migration_etl/service.go` (verified during planning). Tasks 1, 3, 4, 5 depend on this.
- Admin routes are protected by existing auth/middleware (server returns 401/403 on non-admin) — we do not re-implement RBAC. Task 2 depends on this. Frontend nav gating uses the `user?.role === "admin"` pattern already in `sidebar.tsx:154`.
- `admin-jobs-page.tsx` polling cleanup works under React 19 strict mode in this codebase. Task 3 depends on this.
- `traceApiCall` in `src/lib/telemetry/logger.ts` does NOT auto-capture request bodies — to be verified in Task 1. If it does, Task 4 adds redaction logic.
- No active locale other than `en` blocks this feature's shipping; other locales can be filled in later.

## Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Dry-run endpoint quirk (decorative `{id}`) misused by future maintainers | Medium | Wasted debugging | Comment in `migrations.ts` above `dryRun()` explaining the backend quirk; link to `service.go:205-245`. Unit test asserts path is `/admin/migrations/new/dry-run`. |
| Long-running migration polls indefinitely if admin closes tab | Low | Wasted requests | Polling only runs while `AdminMigrationsPage` is mounted; `useEffect` cleanup clears the interval on unmount. Unit test covers unmount cleanup. |
| Credentials leak: React devtools, network panel, logger, toast error echo | High | Security | (a) Strip `source_db_password` from any `logger.error` / `traceApiCall` context; (b) never include raw backend response in toast text; (c) on modal close, password field unmounts and component state resets; (d) Playwright test asserts the password substring does not appear in `document.body.innerText` after wizard dismissal. |
| Admin triggers a second real migration → backend 409 | Medium | Poor UX | "New migration" button disabled when any listed job is non-terminal; backend 409 also surfaces friendly toast as belt-and-suspenders. Covered by TS-007. |
| `stats` shape changes or missing | Low | Progress panel crashes | Type as optional `MigrationStats`; render each entity row defensively; unknown keys ignored. |
| Polling 5 s causes throttling in background tabs | Low | Delayed progress | Acceptable — terminal detection still happens on tab focus. |

## Goal Verification

### Truths
1. An admin can open `/admin/migrations` and sees a history list populated from `GET /api/v1/admin/migrations` — TS-001, TS-003 pass.
2. An admin cannot submit a real migration without a successful (non-failed) dry-run first — TS-002 passes.
3. A non-terminal job is reflected in the UI within 5 s of backend status change and disables the "New migration" button — TS-001, TS-003 pass.
4. A failed job can be resumed; a running job can be cancelled — TS-004, TS-005 pass.
5. Form validation matches backend required fields (`source_host`, `source_db_host`, `source_db_name`, `source_db_user`, `source_db_password`) before any network call — TS-006 passes.
6. On backend HTTP 409 (`ErrMigrationInProgress`), UI shows a friendly message, not a raw error — TS-007 passes.
7. A failed dry-run with a populated `error_message` renders that message to the admin without leaking the password — TS-008 passes.
8. Password substring does not appear in `document.body.innerText`, `localStorage`, or `sessionStorage` after the wizard closes — enforced in TS-002 + unit tests.

### Artifacts
- `src/components/pages/admin-migrations-page.tsx`
- `src/components/admin/migration-wizard-modal.tsx`
- `src/components/admin/migration-job-card.tsx`
- `src/lib/api/services/migrations.ts`
- `src/components/sidebar.tsx` (modified)
- `e2e/admin-migrations.spec.ts` covering TS-001, TS-002, TS-003, TS-005, TS-007, TS-008

## E2E Test Scenarios

### TS-001: Happy-path migration
**Priority:** Critical
**Preconditions:** Admin logged in; no migration jobs exist.
**Mapped Tasks:** 2, 3, 4, 5, 6

| Step | Action | Expected Result |
|---|---|---|
| 1 | Navigate to `/admin/migrations`. | Page heading "Migrations" renders; history table shows empty state. |
| 2 | Click "New migration". | Wizard modal opens on step "Connection". |
| 3 | Fill all required fields with valid mock values; click "Continue". | Modal transitions to "Dry-run"; request: `POST /admin/migrations/new/dry-run`; status poll begins. |
| 4 | Mock dry-run reaches `completed` within 3 s. | Dry-run results panel shows per-entity counts from `stats`. "Start migration" button becomes enabled. |
| 5 | Click "Start migration". | Request: `POST /admin/migrations/peertube`; modal transitions to "Progress". |
| 6 | Mock migration reaches `completed`. | Modal closes; history shows one completed row; success toast appears. |

### TS-002: Dry-run failure blocks real migration + credential safety
**Priority:** Critical
**Preconditions:** Admin logged in.
**Mapped Tasks:** 4

| Step | Action | Expected Result |
|---|---|---|
| 1 | Open wizard; fill with credentials; mock dry-run reaches `failed` with `error_message: "could not connect to source DB"`. | Dry-run step shows the error message inline. |
| 2 | Inspect the "Start real migration" button. | Button disabled. |
| 3 | Close modal. Inspect `localStorage`, `sessionStorage`, and `document.body.innerText`. | The password value does not appear anywhere. |

### TS-003: Active job blocks new-migration button
**Priority:** High
**Preconditions:** Admin logged in; one running migration exists (mocked).
**Mapped Tasks:** 3

| Step | Action | Expected Result |
|---|---|---|
| 1 | Navigate to `/admin/migrations`. | Active-job card visible; "New migration" button disabled; tooltip explains. |
| 2 | Mock the running job transitions to `completed` on next poll (≤ 6 s). | Active-job card moves to history; button re-enables. |

### TS-004: Resume failed migration
**Priority:** High
**Preconditions:** One migration in `failed` state.
**Mapped Tasks:** 5, 6

| Step | Action | Expected Result |
|---|---|---|
| 1 | Locate the failed row. | "Resume" button visible; "Cancel" hidden. |
| 2 | Click "Resume". | Request: `POST /admin/migrations/{id}/resume`; status transitions to `resuming` → `running`; polling resumes. |

### TS-005: Cancel running migration
**Priority:** High
**Preconditions:** One running migration.
**Mapped Tasks:** 5, 6

| Step | Action | Expected Result |
|---|---|---|
| 1 | Click "Cancel" on the active-job card; confirm. | Request: `DELETE /admin/migrations/{id}`; status transitions to `cancelled`; confirmation toast; card moves to history. |

### TS-006: Client-side validation
**Priority:** Medium
**Preconditions:** Wizard open on Connection step.
**Mapped Tasks:** 4

| Step | Action | Expected Result |
|---|---|---|
| 1 | Leave `source_host` empty; click "Continue". | Inline error "Source host is required"; no network call. |
| 2 | Enter `not-a-url` for `source_host`. | Inline URL-format error. |
| 3 | Fix fields; click "Continue". | Proceeds to Dry-run step. |

### TS-007: Backend 409 on concurrent start
**Priority:** High
**Preconditions:** Admin already has a non-terminal migration running; somehow bypasses UI guard (e.g., stale state).
**Mapped Tasks:** 4

| Step | Action | Expected Result |
|---|---|---|
| 1 | Mock `POST /admin/migrations/peertube` to return `409 { error: "migration already in progress" }`. Submit from confirm step. | Friendly toast renders (no raw payload); wizard stays on confirm step; page refetches list and shows active job; "Start migration" button disables. |

### TS-008: Dry-run failure surfaces error_message without leaking credentials
**Priority:** High
**Preconditions:** Admin logged in.
**Mapped Tasks:** 4

| Step | Action | Expected Result |
|---|---|---|
| 1 | Mock dry-run → `failed` with `error_message: "pg: password authentication failed for user 'peertube'"`. | Error text renders inline. |
| 2 | Check that the submitted password substring does not appear in rendered text, toast messages, or any captured network log visible in the DOM. | No password leak. |

## Progress Tracking

- [x] Task 1: Migrations API service + types + telemetry audit
- [x] Task 2: Admin route + nav entry (sidebar.tsx)
- [x] Task 3: AdminMigrationsPage (list + active-job + polling + unmount cleanup)
- [x] Task 4: MigrationWizardModal (stepped wizard, dry-run gate, credential scrubbing)
- [x] Task 5: MigrationJobCard (status badge, actions, progress panel)
- [x] Task 6: i18n strings + E2E Playwright (TS-001, TS-002, TS-003, TS-005, TS-007, TS-008)

**Total Tasks:** 6 | **Completed:** 6 | **Remaining:** 0

## Implementation Tasks

### Task 1: Migrations API service + types + telemetry audit

**Objective:** Typed wrapper over the 6 backend migration endpoints, with verified telemetry behavior so credentials never reach the logger.
**Dependencies:** None
**Mapped Scenarios:** TS-001, TS-002, TS-003, TS-004, TS-005, TS-007, TS-008

**Files:**
- Create: `src/lib/api/services/migrations.ts`
- Create: `src/lib/api/services/__tests__/migrations.test.ts`
- Modify: `src/lib/api/types.ts`

**Key Decisions / Notes:**
- Export exact types matching backend:
  - `type MigrationStatus = "pending" | "validating" | "dry_run" | "running" | "resuming" | "completed" | "failed" | "cancelled"`
  - `interface EntityStats { total: number; migrated: number; skipped: number; failed: number; errors?: string[] }`
  - `interface MigrationStats { users: EntityStats; channels: EntityStats; videos: EntityStats; comments: EntityStats; playlists: EntityStats; captions: EntityStats; media: EntityStats }`
  - `interface MigrationJob { id: string; admin_user_id: string; source_host: string; status: MigrationStatus; dry_run: boolean; error_message?: string; stats?: MigrationStats; source_db_host?: string; source_db_port?: number; source_db_name?: string; source_db_user?: string; source_media_path?: string; created_at: string; started_at?: string; completed_at?: string; updated_at: string }`
  - `interface MigrationRequest { source_host: string; source_db_host: string; source_db_port?: number; source_db_name: string; source_db_user: string; source_db_password: string; source_media_path?: string }`
- Export helper: `export const isTerminalMigrationStatus = (s: MigrationStatus): boolean => s === "completed" || s === "cancelled";`
- Service methods (all return typed promises):
  - `startMigration(req: MigrationRequest): Promise<MigrationJob>` — `POST /api/v1/admin/migrations/peertube`
  - `dryRun(req: MigrationRequest): Promise<MigrationJob>` — `POST /api/v1/admin/migrations/new/dry-run` (path comment: "`new` is a decorative placeholder — backend ignores `{id}` for dry-run, see service.go:205")
  - `listMigrations(params?: { start?: number; count?: number }): Promise<PaginatedResponse<MigrationJob>>` — `GET /api/v1/admin/migrations`
  - `getMigration(id: string): Promise<MigrationJob>` — `GET /api/v1/admin/migrations/{id}`
  - `cancelMigration(id: string): Promise<void>` — `DELETE /api/v1/admin/migrations/{id}`
  - `resumeMigration(id: string): Promise<MigrationJob>` — `POST /api/v1/admin/migrations/{id}/resume`
- **Telemetry audit** (required, documented in file comment):
  - Read `src/lib/telemetry/logger.ts` to confirm whether `traceApiCall` or `logger.error` auto-capture request bodies.
  - If they do, add a `scrubCredentials(req: MigrationRequest): Partial<MigrationRequest>` helper that drops `source_db_password` and returns a redacted copy. Export it for use in Task 4.
  - If they don't, document that finding in a file comment and skip the scrubber.

**Definition of Done:**
- [ ] `pnpm tsc --noEmit` clean.
- [ ] `pnpm lint` clean.
- [ ] Unit tests cover every method — assert HTTP method, path, and body shape (Vitest `vi.fn()` against the `api` client, matching the existing service-test pattern).
- [ ] Unit test asserts `listMigrations` returns the paginated envelope unwrapped the same way other services in `src/lib/api/services/__tests__/` do.
- [ ] Unit test asserts `dryRun` posts to `/api/v1/admin/migrations/new/dry-run`.
- [ ] `isTerminalMigrationStatus` returns `true` only for `"completed"` and `"cancelled"` (table-driven test over all 8 values).
- [ ] Telemetry audit finding documented in file comment (either "bodies not captured" or "scrubber added").
- [ ] If scrubber added: unit test asserts `source_db_password` is absent from the returned object.

**Verify:** `pnpm test:run src/lib/api/services/__tests__/migrations.test.ts && pnpm tsc --noEmit`

---

### Task 2: Admin route + nav entry

**Objective:** Register `/admin/migrations` route and add sidebar entries at the two existing admin blocks, gated for admin role only.
**Dependencies:** None
**Mapped Scenarios:** TS-001

**Files:**
- Create: `src/app/[locale]/(main)/admin/migrations/page.tsx`
- Modify: `src/components/sidebar.tsx` — add entry at `:154-159` (mobile) and `:211-216` (desktop), inside the `user?.role === "admin"` block (admin-only, not moderator-visible).
- Modify or create: `src/components/__tests__/sidebar.test.tsx` — assert migration link renders when `user.role === "admin"`, not when `user.role === "moderator"` or `null`.

**Key Decisions / Notes:**
- Route file (5 lines):
  ```tsx
  "use client";
  export { AdminMigrationsPage as default } from "@/components/pages/admin-migrations-page";
  ```
- Nav entry uses Lucide icon `DatabaseBackup`; label via `t("migrations")` under the existing `Sidebar` / admin-nav namespace (inspect current namespace in `sidebar.tsx` header).
- Add the translation key inside the same namespace already used by "roles" / "payments".

**Definition of Done:**
- [ ] Visiting `/admin/migrations` as admin renders the page (no 404).
- [ ] Sidebar unit test: link renders when `user?.role === "admin"`.
- [ ] Sidebar unit test: link absent when `user?.role === "moderator"`.
- [ ] Sidebar unit test: link absent when `user` is `null`.
- [ ] `pnpm tsc --noEmit` + `pnpm lint` clean.

**Verify:** `pnpm test:run src/components/__tests__/sidebar.test.tsx`, then browser test through TS-001 step 1.

---

### Task 3: AdminMigrationsPage (list + active-job + polling)

**Objective:** Page component that lists migrations, surfaces the active job, and drives the polling loop.
**Dependencies:** Task 1, Task 2
**Mapped Scenarios:** TS-001, TS-003, TS-005

**Files:**
- Create: `src/components/pages/admin-migrations-page.tsx`
- Create: `src/components/pages/__tests__/admin-migrations-page.test.tsx`

**Key Decisions / Notes:**
- `useApi(() => migrationsService.listMigrations({ count: 20, start: 0 }), [])` for initial fetch.
- Compute `const hasActiveJob = jobs.some(j => !isTerminalMigrationStatus(j.status))`.
- Poll every 5 s while `hasActiveJob`. Same `setInterval` + cleanup pattern as `admin-jobs-page.tsx:33-44`. Wrap the tick callback in `useCallback` so the effect is stable.
- Active job card at top; history table below, filtered to terminal jobs.
- "New migration" button disabled when `hasActiveJob`; visible reason surfaced via aria-describedby.
- Cancel / resume via `useMutation`; refetch list on success.
- Performance: memoize `jobs.filter(j => isTerminalMigrationStatus(j.status))` and `hasActiveJob` with `useMemo` keyed on `jobs`.

**Definition of Done:**
- [ ] Unit test: empty state renders when list is empty.
- [ ] Unit test: active-job card renders iff `hasActiveJob`, and "New migration" is disabled.
- [ ] Unit test: poll interval **clears on unmount** (mount → unmount → assert `clearInterval` called / no further fetches).
- [ ] Unit test: poll **stops when all jobs become terminal** (mock jobs list transitions to all-terminal, assert no further fetches after next tick).
- [ ] Unit test: clicking cancel fires `cancelMigration` and refetches on success.
- [ ] `pnpm tsc --noEmit` + `pnpm lint` clean.

**Verify:** `pnpm test:run src/components/pages/__tests__/admin-migrations-page.test.tsx`

---

### Task 4: MigrationWizardModal (stepped, dry-run gate, credential safety)

**Objective:** Multi-step modal enforcing `Connection → Dry-run → Confirm → Progress` with client-side validation, mandatory dry-run, and strict credential handling.
**Dependencies:** Task 1, Task 3
**Mapped Scenarios:** TS-001, TS-002, TS-006, TS-007, TS-008

**Files:**
- Create: `src/components/admin/migration-wizard-modal.tsx`
- Create: `src/components/admin/__tests__/migration-wizard-modal.test.tsx`

**Key Decisions / Notes:**
- Step state: `"connection" | "dry-run" | "confirm" | "progress"`.
- Connection step: controlled inputs for `source_host`, `source_db_host`, `source_db_port` (number input, placeholder `5432`), `source_db_name`, `source_db_user`, `source_db_password` (`type="password"`, `autocomplete="new-password"`), `source_media_path`.
- Validation: required fields mirror backend (`source_host`, `source_db_host`, `source_db_name`, `source_db_user`, `source_db_password`). URL format check on `source_host`. Validation runs before any network call.
- Dry-run step: calls `migrationsService.dryRun(request)`, stores returned job id, polls `getMigration(id)` every 5 s until `failed` or `completed`.
- On dry-run success (`completed`) → enable "Start real migration".
- On dry-run failure (`failed`) → render `error_message` inline, keep "Start real migration" disabled, allow back-edit.
- Confirm step: short summary (`source_host` only — do NOT echo credentials) + "Start real migration" button.
- Start call: `migrationsService.startMigration(request)`. On 409 (`ErrMigrationInProgress`) → friendly toast, return to confirm step, parent page refetches list.
- Progress step: polls job id until terminal, shows live `stats`.
- **Credential safety (must implement):**
  - All error paths pass a scrubbed request to `logger.error` / `traceApiCall` (use `scrubCredentials` from Task 1 if telemetry captures bodies).
  - `toast.error` messages show a generic + backend-provided `error_message` only if backend message does NOT contain the password substring (string-contains guard).
  - On modal close (any path), reset all form state, including password.
- Keyboard: Escape closes only on terminal / connection step; disabled during active dry-run / real migration.

**Definition of Done:**
- [ ] Unit tests cover: validation blocks "Continue" with each missing field; successful dry-run transitions to confirm; failed dry-run keeps "Start real migration" disabled and renders `error_message`; backend 409 on start renders a friendly toast and refetches.
- [ ] Unit test asserts: after close, no component state references the password string **and no DOM input contains it**.
- [ ] Unit test asserts: `logger.error` (or `traceApiCall`) is called with a context object that does NOT contain the password value on any error path.
- [ ] `role="dialog" aria-modal="true"` + labelled title.
- [ ] `pnpm tsc --noEmit` + `pnpm lint` clean.

**Verify:** `pnpm test:run src/components/admin/__tests__/migration-wizard-modal.test.tsx`

---

### Task 5: MigrationJobCard (status + actions + progress)

**Objective:** Reusable card for a single job: status badge, actions (Cancel / Resume), expandable per-entity progress panel.
**Dependencies:** Task 1
**Mapped Scenarios:** TS-003, TS-004, TS-005

**Files:**
- Create: `src/components/admin/migration-job-card.tsx`
- Create: `src/components/admin/__tests__/migration-job-card.test.tsx`

**Key Decisions / Notes:**
- Status → color: `pending → yellow`, `validating|dry_run|running|resuming → cyan`, `completed → green`, `failed → red`, `cancelled → gray`.
- Actions visibility:
  - Cancel → `pending | validating | dry_run | running | resuming`.
  - Resume → `failed` only.
  - No actions on `completed | cancelled`.
- Progress panel renders `stats` entries (`users`, `channels`, `videos`, `comments`, `playlists`, `captions`, `media`) as a simple entity → `migrated / total` table. If `stats` is undefined, render a "Awaiting first status update" placeholder.
- `error_message` visible inline (red text) when present.

**Definition of Done:**
- [ ] Unit test: each action appears only in its allowed status set (table-driven over all 8 statuses).
- [ ] Unit test: `error_message` renders when present; absent otherwise.
- [ ] Unit test: progress panel renders all 7 entity rows when `stats` present.
- [ ] `pnpm tsc --noEmit` + `pnpm lint` clean.

**Verify:** `pnpm test:run src/components/admin/__tests__/migration-job-card.test.tsx`

---

### Task 6: i18n strings + E2E Playwright

**Objective:** Add every user-visible string under `AdminMigrations` namespace and ship the critical E2E scenarios.
**Dependencies:** Tasks 1–5
**Mapped Scenarios:** TS-001, TS-002, TS-003, TS-005, TS-007, TS-008

**Files:**
- Modify: `messages/en.json` — add `AdminMigrations` namespace (title, subtitle, newMigration, activeJob, history, noHistory, step labels, action labels, field labels, validation messages, toast messages). Add `AdminNav.migrations`.
- Other locales in `messages/*.json`: copy `en` values as placeholders (translation is a separate concern).
- Create: `tests/e2e/admin-migrations.spec.ts` — implements TS-001, TS-002, TS-003, TS-005, TS-007, TS-008 via Playwright `page.route("**/api/v1/admin/migrations/**")` stubs that advance job status across sequential fetches.

**Key Decisions / Notes:**
- All hard-coded English strings in new components replaced with `t(...)` calls.
- Playwright stubs return realistic `MigrationJob` shapes (verify against Task 1 types).
- TS-002 and TS-008 include assertions that the submitted password substring is absent from the rendered DOM text after close.

**Definition of Done:**
- [ ] No hard-coded English strings in new components (grep check).
- [ ] `pnpm test:e2e tests/e2e/admin-migrations.spec.ts` passes all 6 scenarios.
- [ ] `pnpm test:run` (full unit suite) still green.
- [ ] `pnpm lint` clean.
- [ ] Manual verification: `pnpm dev` + browser automation walks TS-001 end-to-end.

**Verify:**
- `pnpm test:run`
- `pnpm test:e2e tests/e2e/admin-migrations.spec.ts`
- Browser walkthrough of TS-001.

---

## PeerTube Parity Check

This plan implements feature **B1** from `docs/plans/2026-04-22-feature-parity-audit.md` — the admin wizard for PeerTube instance import. No direct PeerTube frontend equivalent exists (PeerTube's own migration tooling is CLI/backend-driven); this is a vidra-specific admin tool consuming vidra-core's existing ETL. After this phase, the audit's critical admin user story **A-1** ("Run the PeerTube instance import wizard") is satisfied end-to-end.

## Vidra-Specific / Requested Features

Backend extensions impacted: **PeerTube Import**. (No impact on IOTA/Bitcoin Payments, Direct Messaging, Real-time Stream Chat, Inner Circle, ATProto Federation, IPFS Distribution, Video Studio, Auto-Captioning, or Advanced Analytics — this is pure frontend-on-existing-backend work.)

## Open Questions

None remaining. All four design decisions resolved in Batch 2:
- UX shape → list page + stepped modal
- Dry-run → mandatory
- Polling → 5 s while non-terminal
- Concurrency → one active real migration, resume for failed

Reviewer findings from 2026-04-22 spec-review (11 items) were incorporated into this iteration.

### Deferred Ideas
- Per-entity scope selector (users / videos / channels / playlists / comments) — needs backend `MigrationRequest` extension.
- WebSocket progress channel — needs backend work.
- "Undo import" / reverse-ETL admin UI — backend has `reverse_etl.go` without HTTP surface.
- Credential presets / saved connections — security implications; defer.
- Row deletion from history — no backend endpoint; defer.
