# Feature Wiring Audit — Runtime Gap Remediation

Created: 2026-04-28
Status: VERIFIED
Approved: Yes
Iterations: 1
Type: Feature
Worktree: No
Branch: main
Scope-cut: Phases 1–3 (Tasks 1–12) shipped in this plan; Phases 4–9 (Tasks 13–37) split per the plan's pre-declared cut point into `docs/plans/2026-04-29-feature-wiring-audit-runtime-gaps-part2.md`.

> Remediation plan promoted from audit-only to executable. All 9 phases now carry detailed implementation tasks. Execution order: Phase 1 → 9 (user-visible severity).

## Summary

**Goal:** Close all P0 + P1 wiring gaps surfaced by the 2026-04-28 live-stack audit so every feature listed in `docs/FEATURE_VISION.md` either reaches `implemented` status or is cleanly feature-flagged behind a backend dependency.

**Architecture:** Frontend-side fixes only. Backend-only items (vidra-core handlers, route conflicts, persistence bugs) are filed as cross-repo dependencies and gated behind feature flags or skip-with-blocker on the FE side until the corresponding vidra-core PR lands. Every fix is verified by Playwright driving the live `pnpm dev:full` stack with the audit's central assertion: *reload the page, assert UI reflects DB state*.

**Tech Stack:** Next.js 15 App Router · React 19 · TypeScript · Vitest · Playwright · Tailwind v4 · vidra-core (Go, sibling repo).

**Scope decision (recorded 2026-04-28 via /spec):** All 9 phases live in this single plan. Execution order P0 → P2 by user-visible severity. Worktree: No.

## Approach

**Chosen:** Single multi-phase plan with ordered tasks, executed sequentially by `spec-implement`.
**Why:** User explicitly chose this over per-phase split; gives a single source of truth for the runtime-gap remediation and lets the verification baseline (`/tmp/vidra-audit/*.json`) be re-run once per cycle. Cost: large task surface (~37 tasks) — implementer must be disciplined about per-task verification.

**Alternatives considered:**
- Per-phase decomposition (one plan per phase). Rejected per user choice — would have produced 9 smaller specs but multiplied review/approval overhead.
- Top-3 P0 phases bundled, rest deferred. Rejected — leaves the long tail of P1/P2 silently rotting.

**Decomposition rule for downstream specs:** if scope drifts beyond what fits a single TDD loop, the implementer SHOULD invoke `AskUserQuestion` to split a sub-phase into its own follow-up plan rather than balloon this one.

**Pre-declared cut point:** if context pressure or a blocker forces a split, **cut after Phase 3 (Tasks 1–12)**. Phases 1–3 are three independently-shippable P0 vertical slices (auth completeness · engagement loop · realtime auth). Phases 4–9 (Tasks 13–37) become a follow-up plan starting at Task 13. This avoids the silent "Phases 1-4 done, 5-9 partial" failure mode the Risks table flags.

## Context for Implementer

> Assume the implementer has never opened this codebase. Anchor every change to a concrete file:line.

### Patterns to follow

- **Frontend service pattern:** `src/lib/api/services/<domain>.ts` exports a singleton object; methods return typed promises; HTTP via the shared `apiClient`/`publicApi` from `src/lib/api/client.ts`. Every new method requires a matching test in `src/lib/api/services/__tests__/<domain>.test.ts` (stop hook enforces).
- **AuthContext extension:** `src/components/auth-context.tsx` (`AuthContextType` interface @ line 8; provider @ line 35). Each new method follows the `login`/`register`/`logout` pattern: `useCallback`, calls `authService.<method>`, updates `setUser` if needed, throws on error so callers can `try/catch`.
- **Page route shape:** `src/app/[locale]/(main)/<route>/page.tsx` is a thin wrapper; the real page lives at `src/components/pages/<name>-page.tsx` and is `'use client'`. Use `next/navigation` (`useRouter`, `useSearchParams`) — never `<a>` for app links, always `<Link>` from `@/i18n/routing`.
- **i18n:** every user-visible string MUST land in `src/messages/en.json` first; `pnpm i18n:check` enforces parity across the 13 locales. Stop hook blocks on missing keys.
- **Apple HIG:** every new UI page applies the design system in `CLAUDE.md` — clarity / deference / depth, 44 × 44 touch targets, WCAG AA contrast, `prefers-reduced-motion` honored.
- **Telemetry:** API errors logged via `logger.error()` from `@/lib/telemetry/logger` — never raw `console.log`.

### Key files

- `src/lib/api/client.ts` — fetch wrapper + token refresh + 401 retry. Auth race-condition lives at lines 160-201 (refresh flow).
- `src/lib/api/services/auth.ts:66` — `requestPasswordReset()` already exists; calls `/api/v1/users/ask-reset-password`. Verify a `resetPassword(token, password)` method exists or add it.
- `src/components/auth-context.tsx:71-110` — `login`/`register`/`logout` patterns to mimic for password-reset methods.
- `src/components/pages/login-page.tsx:132` — already links to `/forgot-password` via `router.push` — the route just doesn't exist.
- `src/lib/api/services/videos.ts:225-238` — `getRating` shape mismatch (Phase 2 Task 4 hot spot).
- `src/lib/api/types.ts:343-349` — `VideoRatingStats` type to align.
- `src/lib/api/services/admin.ts:33-38` — admin path shapes to fix (Phase 6).
- `src/lib/hooks/use-messages-ws.ts`, `src/lib/hooks/use-live-chat.ts`, `src/lib/hooks/use-notification-polling.ts`, `src/lib/hooks/use-unread-messages.ts` — current realtime hooks. **Note:** there is no `src/lib/realtime/` dir; WS clients live under hooks. Phase 3 patches handshake auth + reconnect across these hooks.
- `e2e/global-setup.ts`, `e2e/fixtures/`, `e2e/helpers/` — seeded-user setup for `pnpm dev:full`-driven Playwright runs.

### Conventions

- File names: kebab-case. Components: `PascalCase` exports. No `any`. Explicit return types on exports.
- Imports: Node built-ins (`node:`) → external → `@/...` → relative.
- Empty/loading/error states: per-page `<EmptyState/>` / `<ErrorState/>` from `src/components/`. Never silently mask errors with empty arrays — the audit's recurring failure pattern.

### Gotchas

- vidra-core is in `/Users/yosefgamble/github/vidra-core/` (sibling repo). Backend-dependent tasks must NOT edit vidra-core source — instead add a feature-flag/error-state on the FE and file a cross-repo issue.
- WebSocket auth: vidra-core's `/api/v1/notifications/ws` and `/messages/ws` reject the default `Authorization: Bearer` header; bearer must travel via `?token=...` query OR `Sec-WebSocket-Protocol`. Choose by probing both — match whatever vidra-core actually accepts; don't guess.
- Snake_case ↔ camelCase: vidra-core inconsistently uses both shapes. Map at the service layer, never in components. The audit's most common bug class.
- AuthContext race: `apiClient` is loaded at module-init; AuthContext hydrates on mount. First `/admin/*` fetch may fire pre-hydration and 401 → `clearTokens()` cascades a logout. Phase 6 Task 22 fixes this.
- Real-DB testing: every Playwright spec MUST be runnable against `pnpm dev:full` (not vitest mocks). Login as a seeded user (alice/bob/charlie/admin), perform action, **reload**, assert.

### Domain context

vidra-core extends PeerTube with: Bitcoin/BTCPay payments (replacing IOTA, dual-mode w/ Polar), Direct Messaging (E2EE), Real-time Stream Chat, Inner Circle memberships, ATProto federation, IPFS distribution, Video Studio, Auto-Captioning, Advanced Analytics. PeerTube parity is the floor; vidra-specific features layer on top. Every plan must explicitly call out which extension(s) are touched (stop hook enforces `## Vidra-Specific / Requested Features` section).

## Runtime Environment

- **Start command:** `pnpm dev:full` (from `vidra-user`) — boots vidra-core (`docker compose up -d`) + Next.js dev server. See `scripts/start-dev.sh`, `scripts/btcpay-bootstrap.sh`, `scripts/lnd-bootstrap.sh`, `scripts/wait-for-health.sh`.
- **Ports:** Next.js dev `http://localhost:3000` · vidra-core API `http://localhost:9000/api/v1` · BTCPay `http://localhost:14080` · IPFS gateway via `/static/web-videos/*`.
- **Health check:** `scripts/wait-for-health.sh` — backend, postgres, BTCPay, IPFS, ClamAV all `Up (healthy)`.
- **Seeded users:** `alice` (creator), `bob` (viewer), `charlie` (mod), `admin` — provisioned via `scripts/dev-seed.sh`.
- **Restart procedure:** `docker compose restart <service>` (in `vidra-core/`); `pnpm dev` for FE only.
- **Audit baseline:** `/tmp/vidra-audit/{viewer-bob,creator-alice,streamer-payments,admin}.json` — re-run the relevant slice after each phase; show fewer P0/P1 findings than baseline; do not introduce new failures.

## Goal Verification

### Truths

1. Every P0 entry in the Confirmed Bug Catalog is either resolved (FE) or feature-flagged with a tracked vidra-core dependency (BE).
2. After Phase 1, a fresh user can land on `/register`, `/forgot-password`, `/reset-password` directly and complete the flow end-to-end against the live stack — no Next.js root-layout runtime error anywhere.
3. After Phase 2, `like a video → reload` shows the like persisted; `subscribe to channel → reload` shows subscribed; `comment as bob on alice's video` succeeds; `Watch Later` is reachable from the Save dialog; `/library/likes` shows liked videos (not history).
4. After Phase 3, the WS console error stream during normal navigation is empty (no "HTTP Authentication failed" repeats).
5. After Phase 4, a creator can Go Live → see real RTMP URL + key → end stream → see it under `/live` discovery (or named blocker if vidra-core list handler still missing).
6. After Phase 5, `/studio` index renders without a runtime error and `/studio/wallet` either shows real balance or a clean feature-flagged empty state — never a wall of 404s.
7. After Phase 6, every `/admin/*` page renders real data on first navigation (no AuthContext race logout); ban/unban/role/hard-delete actions all reflect in DB on reload.
8. The full Playwright suite (`pnpm test:e2e`) runs green against `pnpm dev:full` — not just against mocks.
9. `docs/FEATURE_VISION.md` rows for every touched feature are promoted from `partial`/`planned` → `implemented` (or stay `partial` with the new blocker named).

### Artifacts

- `src/app/[locale]/(main)/{register,forgot-password,reset-password,signup,studio}/page.tsx` (created routes).
- `src/components/pages/{forgot-password,reset-password,studio}-page.tsx` (new pages).
- `src/components/auth-context.tsx` (extended with `requestPasswordReset` + `resetPassword`).
- `src/lib/api/services/{videos,channels,admin,runners,payments,playlists,streams,notifications,messages}.ts` (shape + path fixes).
- `src/lib/api/services/__tests__/<each-touched-service>.test.ts` (covered).
- `src/lib/hooks/use-messages-ws.ts`, `src/lib/hooks/use-live-chat.ts`, and (if needed) a new `src/lib/hooks/use-notifications-ws.ts` — WS handshake auth + reconnect on token refresh.
- `src/components/pages/{livestream,wallet,admin-page,admin-users-page,library-page,save-to-playlist-modal}.tsx` (wiring fixes).
- New Playwright specs under `e2e/`: `auth-password-reset.spec.ts`, `auth-register-direct.spec.ts`, `engagement-loop-persistence.spec.ts`, `realtime-ws-auth.spec.ts`, `live-streaming-flow.spec.ts`, `studio-wallet-gating.spec.ts`, `admin-contract.spec.ts`, `shape-mismatch-regression.spec.ts`.
- Updated `docs/FEATURE_VISION.md` rows for: USER-03, USER-04, USER-08, USER-10, CORE-04, CORE-05, CORE-06, CORE-10, CORE-11, CORE-12, CORE-14, LIVE-01, LIVE-02, LIVE-03, LIVE-04, ADMIN-01, ADMIN-02, ADMIN-03, ADMIN-06, ADMIN-07, ADMIN-11, ADMIN-12, ADMIN-14, UX-06, UX-07, PAY-02, PAY-05, PAY-07, PAY-08.

## E2E Test Scenarios

Each scenario must be runnable end-to-end against `pnpm dev:full` with seeded users.

### TS-001: Direct /register route loads and creates an account
**Priority:** Critical · **Preconditions:** logged out · **Mapped Tasks:** Task 1

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Navigate to `/register` (or `/signup`) | Page renders with sign-up form, no Next.js root-layout runtime error in console |
| 2 | Fill username/email/password, submit | API 200, redirected to `/`, user shown in header |
| 3 | Reload | Still authenticated, header still shows new user |

### TS-002: Forgot password — request flow
**Priority:** Critical · **Preconditions:** logged out · **Mapped Tasks:** Task 2

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | From `/login` click "Forgot password" | Lands on `/forgot-password` |
| 2 | Submit registered email | Toast "check your email"; network log shows POST `/api/v1/users/ask-reset-password` 200 |
| 3 | Submit unknown email | Same toast (no user enumeration), 200 |

### TS-003: Reset password — completion flow
**Priority:** Critical · **Preconditions:** valid reset token in URL · **Mapped Tasks:** Task 3

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Navigate to `/reset-password?token=<valid>` | Form renders |
| 2 | Submit new password | Toast success, redirected to `/login` |
| 3 | Login with new password | Authenticated |

### TS-004: Like persists across reload
**Priority:** Critical · **Preconditions:** logged in as alice · **Mapped Tasks:** Task 4

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Open a video, click Like | Like button shows pressed; count +1 |
| 2 | Hard-reload the page | Like still pressed; count still +1 |
| 3 | Click Dislike | Switches to dislike; reload — still dislike |

### TS-005: Subscribe-by-handle works and persists
**Priority:** Critical · **Preconditions:** logged in as alice; on bob's channel page · **Mapped Tasks:** Task 5

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Click Subscribe | Button shows Subscribed |
| 2 | Reload | Still Subscribed |

### TS-006: Cross-user comment posts successfully
**Priority:** Critical · **Preconditions:** logged in as bob; on alice's video · **Mapped Tasks:** Task 8

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Submit comment | 201, comment appears |
| 2 | Reload | Comment still there, by bob |

### TS-007: Watch Later from Save dialog
**Priority:** High · **Preconditions:** logged in as alice; on a video · **Mapped Tasks:** Task 10

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Click Save → modal opens | Watch Later option visible |
| 2 | Click Watch Later | Toast confirms |
| 3 | Navigate to `/library/watch-later` | Video listed |

### TS-008: /library/likes shows liked videos
**Priority:** High · **Preconditions:** alice has liked ≥1 video · **Mapped Tasks:** Task 9

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Navigate to `/library/likes` | Liked videos listed (NOT history) |

### TS-009: Notifications + messages WebSocket connects on first load
**Priority:** Critical · **Preconditions:** logged in fresh · **Mapped Tasks:** Tasks 11, 12

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Login fresh | No "HTTP Authentication failed" repeats in console |
| 2 | Trigger notification (admin posts) | New notification appears without page reload |
| 3 | Wait through token-refresh window | WS stays connected |

### TS-010: Go Live end-to-end
**Priority:** Critical · **Preconditions:** logged in as alice (creator) · **Mapped Tasks:** Tasks 13, 14, 15

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | `/livestream` → Go Live | Real RTMP URL + key shown (no `rtmp://your-server/...` placeholder) |
| 2 | Stream from OBS | `/live` lists the live stream |
| 3 | Click End | Stream ends, recording flag honored |

### TS-011: /studio loads without root-layout error
**Priority:** Critical · **Preconditions:** logged in as alice · **Mapped Tasks:** Task 17

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Navigate to `/studio` | Creator dashboard renders, no Next.js root-layout error |
| 2 | Click wallet quick-link | Lands on `/studio/wallet` |

### TS-012: Wallet endpoint resilience
**Priority:** Critical · **Preconditions:** logged in as alice · **Mapped Tasks:** Task 18

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Navigate `/studio/wallet` | Either real balance OR clean "not yet configured" empty state — never a wall of 404 errors |
| 2 | Open browser console | No uncaught 404 errors flooding log |

### TS-013: Admin contract sweep
**Priority:** Critical · **Preconditions:** logged in as admin (fresh session) · **Mapped Tasks:** Tasks 21, 22, 23, 24, 25, 27

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Login fresh, navigate `/admin/users` | Real user list renders; admin not logged out |
| 2 | Ban a user, reload | User shows banned; user can no longer log in |
| 3 | Hard-delete a user, reload | User removed from listing |
| 4 | Navigate `/admin/jobs`, `/admin/runners`, `/admin/federation` | Each renders real data |
| 5 | Navigate `/admin` dashboard | Federation pill shows real instance count, not "47" |

### TS-014: Admin settings decoupled from diagnostics
**Priority:** High · **Preconditions:** admin · **Mapped Tasks:** Task 26

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Navigate `/admin/settings` | Form renders even when `/admin/diagnostics` 404s |
| 2 | Toggle a setting, save, reload | Persisted |

### TS-015: Inner Circle UI gating
**Priority:** High · **Preconditions:** any logged-in user · **Mapped Tasks:** Task 20

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Navigate `/studio/inner-circle` with backend missing | UI shows feature-flagged "coming soon" — no console error storm |
| 2 | Set `NEXT_PUBLIC_INNER_CIRCLE_ENABLED=false` (default) | UI hidden / link not shown in nav |

### TS-016: Watch history reload-asserts (BE-blocked)
**Priority:** Critical (gating once BE ships) · **Preconditions:** logged in as alice · **Mapped Tasks:** Task 7

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Watch two distinct videos to completion | UI optimistic-updates show history |
| 2 | Hard-reload `/library/history` | While BE-blocked: `BackendNotImplementedError` surfaces a typed empty state with explanatory message; console clean. Once BE ships: both videos listed with progress |

> Currently `test.fixme()` until vidra-core fix lands; flips to expected-pass via `e2e/watch-history-persistence.spec.ts`.

### TS-017: Video view counter reload-asserts (BE-blocked)
**Priority:** Critical (gating once BE ships) · **Preconditions:** logged in as alice · **Mapped Tasks:** Task 6

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Open a video, capture initial `views` count | Count rendered |
| 2 | Wait through unique-session view threshold, hard-reload | While BE-blocked: views unchanged + UI surfaces no error (FE swallows known broken counter via typed catch). Once BE ships: count incremented by 1 |

> Currently `test.fixme()` until vidra-core fix lands; flips to expected-pass via `e2e/view-counter.spec.ts`.

## Assumptions

- vidra-core's `/api/v1/users/ask-reset-password` and `/api/v1/users/reset-password` endpoints are live and accept the documented payload (supported by `migrations/068_create_password_reset_tokens_table.sql` + `internal/httpapi/password_reset.go`). Tasks 2, 3 depend on this.
- vidra-core's `/api/v1/users/login` and `/users/register` accept the OAuth2/PKCE shape currently in `authService` (verified by green `auth.spec.ts` baseline). Task 1 depends on this.
- The audit's `/tmp/vidra-audit/*.json` baseline is still representative of live-stack behavior on the current main branch. All phases verify against this baseline.
- The seeded users (`alice`, `bob`, `charlie`, `admin`) are reliably present after `pnpm dev:full` + `scripts/dev-seed.sh`. All E2E tasks depend on this.
- WebSocket auth is fixable from the FE alone (token via query param or subprotocol). Task 11 depends on this — if vidra-core requires a backend change, Task 11 is gated and FE adds graceful degradation.
- BTCPay invoice 500 (audit P0 #13) is a vidra-core wiring bug — Task 19 is BE-blocked from this repo. FE adds clean error state.
- Inner Circle backend is genuinely missing (audit P0 #15) — Task 20 chooses feature-flag gating until vidra-core ships, not local stubbing.
- `docs/FEATURE_VISION.md` exists and the per-feature IDs (CORE-NN, USER-NN, etc.) are stable for status-promotion references.

## Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| vidra-core backend dependencies (Tasks 6, 7, 8, 16, 19, 23, 29, 30) block FE phase completion | High | High | Each BE-blocked task ships a feature flag or graceful error state on the FE, files a cross-repo issue, and marks the task `blocked` with the issue link. Phase advances regardless. |
| WebSocket auth requires Sec-WebSocket-Protocol header (browser API limits ergonomics) | Medium | Medium | Probe both query-param and subprotocol — adopt whichever vidra-core accepts. If neither works without BE help, file BE issue and ship FE polling fallback for notifications. |
| Snake_case mappers introduced inconsistently → new shape bugs | Medium | High | Centralize mappers in `src/lib/api/helpers.ts`; every shape-fix task adds a Vitest case for both raw shapes (snake_case + camelCase tolerance). |
| AuthContext race fix breaks existing auth tests | Medium | High | Add `isReady` flag; gate `apiClient` calls behind it; run full `auth.spec.ts` + `auth-oauth.spec.ts` after Task 22; revert if regressions. |
| 37-task plan exceeds a single TDD cycle without focus | High | Medium | `spec-implement` updates Progress Tracking after EACH task; verifies green before moving on. If context pressures arise, the workflow handles compaction — quality gates do NOT relax. |
| Inner Circle feature flag accidentally ships ON in prod | Medium | Critical | Default `NEXT_PUBLIC_INNER_CIRCLE_ENABLED` to `false`; explicit env-var documentation; flag flip is part of vidra-core ship checklist, not FE PR. |
| `/tmp/vidra-audit/*.json` baseline drifts before all phases land | Medium | Medium | Re-snapshot baseline before each phase begins (`pnpm audit:run` or equivalent); compare current run to fresh-pre-phase baseline, not stale audit. |

## Autonomous Decisions

These were made without a Batch-2 design question because the user already chose scope in Batch 1.

- **Task numbering is global (1–37)**, not per-phase, so dependencies cross phases cleanly. Phase grouping shown in `## Implementation Tasks` for navigation.
- **Backend-blocked tasks remain in this plan** (rather than moved to a vidra-core spec) so the FE work — feature flags, error states, regression tests — is tracked here. The actual BE fix is a cross-repo dependency, not a deletion.
- **Per-task `Mapped Scenarios`** point to the TS-NNN scenarios above; one scenario can map multiple tasks where they share a flow (e.g. TS-013 maps Tasks 21–25, 27).
- **No worktree** per user choice — all edits land directly on the current branch.

## Progress Tracking

- [x] **Phase 1 — Auth completeness (P0)**
- [x] Task 1: Direct `/register` and `/signup` routes
- [x] Task 2: `/forgot-password` page + AuthContext.requestPasswordReset
- [x] Task 3: `/reset-password` page + AuthContext.resetPassword
- [ ] **Phase 2 — Engagement loop (P0)**
- [x] Task 4: Map `videoService.getRating()` snake_case → camelCase userRating
- [x] Task 5: Subscribe-by-handle resolution (handle→UUID OR backend handle support)
- [x] Task 6: Watch counter persistence (BE vidra-core; FE assertion only)
- [x] Task 7: Watch history persistence (BE vidra-core; FE assertion only)
- [x] Task 8: Comments POST 500 cross-user (BE vidra-core; FE regression spec)
- [x] Task 9: Fix `/library/likes` routing bug
- [x] Task 10: Watch Later in Save dialog + endpoint shape fix
- [x] **Phase 2 — Engagement loop (P0)**
- [ ] **Phase 3 — Real-time WS auth (P0)**
- [x] Task 11: Bearer token in WS handshake (notifications + messages)
- [x] Task 12: WS reconnect-with-fresh-token on token refresh
- [x] **Phase 3 — Real-time WS auth (P0)**
- [ ] **Phase 4 — Live streaming (P0)**
- [ ] Task 13: POST `/streams` sends `channel_id`
- [ ] Task 14: Real RTMP URL + stream key display
- [ ] Task 15: End Live button
- [ ] Task 16: `/live` discovery list (BE vidra-core list handler; FE consumes)
- [ ] **Phase 5 — Studio + Wallet (P0)**
- [ ] Task 17: `/studio` index page (creator dashboard)
- [ ] Task 18: Wallet endpoint feature-flag gating
- [ ] Task 19: BTCPay invoice 500 (BE vidra-core; FE retry verification)
- [ ] Task 20: Inner Circle UI gating until backend ships
- [ ] **Phase 6 — Admin contract fixes (P0/P1)**
- [ ] Task 21: Fix admin service paths (jobs/runners/server-following)
- [ ] Task 22: AuthContext race fix
- [ ] Task 23: User ban/unban/role wiring
- [ ] Task 24: Wire `DELETE /admin/users/{id}` (hard delete)
- [ ] Task 25: Fix doubled-path bug in admin payouts
- [ ] Task 26: Decouple `/admin/settings` from `/admin/diagnostics`
- [ ] Task 27: Real federation count on dashboard
- [ ] **Phase 7 — Shape mismatches sweep (P1)**
- [ ] Task 28: Channel `followersCount` mapping
- [ ] Task 29: Trending route bug (BE vidra-core route conflict)
- [ ] Task 30: Videos list shape regression
- [ ] **Phase 8 — Studio + analytics endpoints (P1)**
- [ ] Task 31: `/api/v1/videos/{id}/studio` graceful gating
- [ ] Task 32: `/api/v1/analytics/*` graceful gating
- [ ] **Phase 9 — Polish (P2)**
- [ ] Task 33: `/channel/{id}/edit` lands on edit form directly
- [ ] Task 34: Per-item history delete
- [ ] Task 35: `/settings/wallet` redirect → `/studio/wallet`
- [ ] Task 36: Login form `autocomplete` attributes
- [ ] Task 37: Resolve duplicate Go Live buttons
- [ ] **Cross-cutting verification (`spec-verify` phase)**
- [ ] Re-run `/tmp/vidra-audit/*.json` baseline; show fewer P0/P1 findings; no new failures
- [ ] `docs/FEATURE_VISION.md` rows promoted for every touched feature
- [ ] `pnpm lint` / `pnpm typecheck` / `pnpm test:run` / `pnpm test:e2e` / `pnpm build` all green
- [ ] All TS-NNN scenarios green against `pnpm dev:full`

**Total Tasks:** 37 · **Completed:** 12 · **Remaining:** 25

## Implementation Tasks

> Tasks are ordered by execution; dependencies cross phases.

### Task 1: Direct `/register` and `/signup` routes (Phase 1)

**Objective:** Visiting `/register` or `/signup` directly renders the existing register form and does not throw the Next.js "Missing `<html>` and `<body>` tags in the root layout" runtime error.
**Dependencies:** None
**Mapped Scenarios:** TS-001
**Audit reference:** P0 #7

**Files:**
- Create: `src/app/[locale]/(main)/register/page.tsx`
- Create: `src/app/[locale]/(main)/signup/page.tsx` (re-export of register page)
- Modify: `src/components/pages/login-page.tsx` (extract `<RegisterForm/>` if not already separable, OR use a `mode=register` prop pattern)

**Key Decisions / Notes:**
- Reuse the existing register form rather than fork — extract shared component if needed.
- Both routes go through the `(main)` layout group → root `<html>`/`<body>` provided by `src/app/layout.tsx`.

**Definition of Done:**
- [ ] `/register` and `/signup` render the form
- [ ] No Next.js root-layout runtime error in console
- [ ] Existing `/login?mode=register` still works
- [ ] Vitest covers route component

**Verify:**
- `pnpm test:run` (Vitest)
- `pnpm test:e2e -- e2e/auth-register-direct.spec.ts` against `pnpm dev:full`

---

### Task 2: `/forgot-password` page + `AuthContext.requestPasswordReset` (Phase 1)

**Objective:** Reach the existing `authService.requestPasswordReset` (`src/lib/api/services/auth.ts:66`) from a real route via AuthContext.
**Dependencies:** None
**Mapped Scenarios:** TS-002
**Audit reference:** P0 #6

**Files:**
- Create: `src/app/[locale]/(main)/forgot-password/page.tsx`
- Create: `src/components/pages/forgot-password-page.tsx`
- Modify: `src/components/auth-context.tsx` (add `requestPasswordReset(email)` to `AuthContextType` + provider + default)
- Test: `src/components/__tests__/auth-context.test.tsx` (new method coverage)
- Create: `e2e/auth-password-reset.spec.ts` (covers TS-002 + TS-003)

**Key Decisions / Notes:**
- Submit returns the same toast for known and unknown emails (no user enumeration).
- i18n keys under `ForgotPasswordPage.*` in `src/messages/en.json`, run `pnpm i18n:check` before commit.

**Definition of Done:**
- [ ] `/forgot-password` renders form, submit hits `POST /api/v1/users/ask-reset-password`
- [ ] `useAuth()` exposes `requestPasswordReset`
- [ ] No user-enumeration via toast difference
- [ ] Vitest covers AuthContext method
- [ ] i18n parity (13 locales)

**Verify:**
- `pnpm test:run`
- `pnpm test:e2e -- e2e/auth-password-reset.spec.ts` (TS-002 portion)
- `pnpm i18n:check`

---

### Task 3: `/reset-password` page + `AuthContext.resetPassword` (Phase 1)

**Objective:** Token-from-email completion flow. Submitting a valid token + new password sets the password and redirects to `/login`.
**Dependencies:** Task 2
**Mapped Scenarios:** TS-003
**Audit reference:** P0 #6

**Files:**
- Create: `src/app/[locale]/(main)/reset-password/page.tsx`
- Create: `src/components/pages/reset-password-page.tsx`
- Modify: `src/components/auth-context.tsx` (`resetPassword(token, newPassword)`)
- Modify: `src/lib/api/services/auth.ts` (verify or add `resetPassword`)
- Test: `src/lib/api/services/__tests__/auth.test.ts` (resetPassword unit)
- Test: same `e2e/auth-password-reset.spec.ts` (TS-003 portion)

**Key Decisions / Notes:**
- Read token from `useSearchParams()`; show error state if missing or 4xx.
- Confirm-password input with match validation (Apple HIG: clear error states).

**Definition of Done:**
- [ ] `/reset-password?token=<x>` form submits to `/api/v1/users/reset-password`
- [ ] Successful reset redirects to `/login`
- [ ] Login with new password works
- [ ] Vitest unit covers `authService.resetPassword`
- [ ] E2E covers full flow

**Verify:**
- `pnpm test:run`
- `pnpm test:e2e -- e2e/auth-password-reset.spec.ts`

---

### Task 4: Map `videoService.getRating()` snake_case → camelCase `userRating` (Phase 2)

**Objective:** Like/dislike persists in UI on reload.
**Dependencies:** None
**Mapped Scenarios:** TS-004
**Audit reference:** P0 #1

**Files:**
- Modify: `src/lib/api/services/videos.ts:225-238` (response mapping)
- Modify: `src/lib/api/types.ts:343-349` (align `VideoRatingStats`)
- Modify: `src/components/pages/watch-page.tsx:177-182` (consume new shape)
- Test: `src/lib/api/services/__tests__/videos.test.ts` (rating shape mapping for both numeric +1/-1/0 and string `"like"/"dislike"/"none"`)
- Create: `e2e/video-likes-persist.spec.ts` (extend existing `video-likes.spec.ts` with reload-assertion)

**Key Decisions / Notes:**
- Map `user_rating: 1 | -1 | 0` → `userRating: "like" | "dislike" | "none"`.
- Map `likes_count`/`dislikes_count` → `likes`/`dislikes`.
- Defensive coercion: handle both shapes for forward compatibility.

**Definition of Done:**
- [ ] Like → reload → still pressed, count persists
- [ ] Dislike → reload → still pressed
- [ ] Vitest covers shape mapping
- [ ] E2E reload-assertion green against live stack

**Verify:**
- `pnpm test:run -- src/lib/api/services/__tests__/videos.test.ts`
- `pnpm test:e2e -- e2e/video-likes-persist.spec.ts` against `pnpm dev:full`

---

### Task 5: Subscribe-by-handle resolution (Phase 2)

**Objective:** `POST /api/v1/channels/{handle}/subscribe` succeeds and persists.
**Dependencies:** None
**Mapped Scenarios:** TS-005
**Audit reference:** P0 #5

**Files:**
- Modify: `src/lib/api/services/channels.ts:57-64` (resolve handle→UUID first OR confirm backend accepts handle and adjust)
- Test: `src/lib/api/services/__tests__/channels.test.ts`
- Create: `e2e/subscribe-persist.spec.ts` (extend `subscribe.spec.ts`)

**Key Decisions / Notes:**
- Probe live API first: try `POST .../{handle}/subscribe` and `POST .../{uuid}/subscribe` to confirm which shape vidra-core accepts on current main.
- If handle accepted: fix payload. If only UUID: add `getChannelByHandle()` resolver.

**Definition of Done:**
- [ ] Subscribe → reload → still subscribed
- [ ] Unsubscribe round-trips
- [ ] Vitest covers method
- [ ] E2E reload-assertion green

**Verify:**
- `pnpm test:run -- src/lib/api/services/__tests__/channels.test.ts`
- `pnpm test:e2e -- e2e/subscribe-persist.spec.ts`

---

### Task 6: Watch counter persistence — BE-blocked, FE assertion only (Phase 2)

**Objective:** `POST /views` increments `video.views`. **This is a vidra-core bug** (audit P0 #3); FE work is typed-error gating + regression-spec.
**Dependencies:** None — but BE fix gate
**Mapped Scenarios:** TS-017
**Audit reference:** P0 #3

**Files:**
- Create: `src/lib/api/errors.ts` (or extend existing) — add `BackendNotImplementedError extends ApiError` with `code` field
- Modify: `src/lib/api/services/videos.ts:trackView` — catch BE 4xx responses and throw typed `BackendNotImplementedError` rather than letting raw fetch errors propagate
- Test: `src/lib/api/services/__tests__/videos.test.ts` — assert typed error on 400/404/500
- Create: `e2e/view-counter.spec.ts` (TS-017 — `test.fixme()` until BE ships)
- File cross-repo issue: `vidra-core` — link in this task's blocker note

**Key Decisions / Notes:**
- Do NOT change vidra-core source from this repo.
- Watch-page consumes typed error and silently no-ops the optimistic counter — never crashes the UI.
- E2E spec marked `test.fixme()` with comment + issue link until BE ships.

**Definition of Done:**
- [ ] `BackendNotImplementedError` class exported from `src/lib/api/errors.ts`
- [ ] `videoService.trackView` throws typed error on BE failure (Vitest asserts both fields)
- [ ] Watch page catches the typed error — no console error, no crash
- [ ] `e2e/view-counter.spec.ts` written, currently `test.fixme()` with cross-repo issue link
- [ ] Cross-repo issue filed and linked here
- [ ] FEATURE_VISION CORE-04 row updated: `partial → partial (BE-blocked: <issue link>)`

**Verify:**
- `pnpm test:run -- src/lib/api/services/__tests__/videos.test.ts`
- Manual stub run: `pnpm test:e2e -- e2e/view-counter.spec.ts` shows `test.fixme` (not failing)

---

### Task 7: Watch history persistence — BE-blocked, FE typed-error gating (Phase 2)

**Objective:** `GET /users/me/history/videos` returns populated history. BE-blocked → FE ships typed error + empty state so library page never crashes.
**Dependencies:** None — BE fix gate
**Mapped Scenarios:** TS-016
**Audit reference:** P0 #2

**Files:**
- Modify: `src/lib/api/services/videos.ts:getWatchHistory` — catch `null` views response and `BackendNotImplementedError` (reuses class from Task 6)
- Modify: `src/components/pages/library-page.tsx` (history section) — render typed empty state with explanatory message when BackendNotImplementedError thrown; render real list otherwise
- Test: `src/lib/api/services/__tests__/videos.test.ts` — null-response coercion + typed-error case
- Create: `e2e/watch-history-persistence.spec.ts` (TS-016 — `test.fixme()` until BE fix)
- File cross-repo issue

**Definition of Done:**
- [ ] `getWatchHistory` returns empty array OR throws `BackendNotImplementedError` — never `null`
- [ ] Library history section renders typed empty state on BackendNotImplementedError (NOT a 'No history yet' lie — the message says 'history persistence not yet available; see <issue>')
- [ ] Vitest covers both branches
- [ ] `e2e/watch-history-persistence.spec.ts` (TS-016) `test.fixme()` with issue link
- [ ] FEATURE_VISION CORE-05 updated: `partial → partial (BE-blocked: <issue link>)`

**Verify:**
- `pnpm test:run -- src/lib/api/services/__tests__/videos.test.ts`
- Manual run: `/library/history` while BE broken shows the typed empty message; flips to real list when BE ships
- Stub spec runs as `test.fixme`

---

### Task 8: Comments POST 500 cross-user — BE-blocked + FE typed-error gating (Phase 2)

**Objective:** Bob can comment on alice's video. BE-blocked → FE surfaces typed error so the comment composer shows a useful message rather than a generic toast.
**Dependencies:** None — BE fix gate
**Mapped Scenarios:** TS-006
**Audit reference:** P0 #4

**Files:**
- Modify: `src/lib/api/services/comments.ts:create` — wrap 500 response in `BackendNotImplementedError` with code `CROSS_USER_COMMENT_500`
- Modify: `src/components/comment-section.tsx` — typed-error catch surfaces an actionable message ('cross-user commenting is broken on this build; see <issue>') rather than the generic error toast
- Test: `src/lib/api/services/__tests__/comments.test.ts` — typed error case
- Create: `e2e/cross-user-comment.spec.ts` (TS-006 — `test.fixme()` until BE ships; flips to expected-pass)
- File cross-repo issue

**Definition of Done:**
- [ ] Typed `BackendNotImplementedError` thrown on 500; Vitest covers
- [ ] Comment composer renders the typed error message (not a generic toast)
- [ ] Vitest covers component branch
- [ ] `e2e/cross-user-comment.spec.ts` (TS-006) `test.fixme()` with issue link
- [ ] FEATURE_VISION CORE-10 updated: `partial → partial (BE-blocked: <issue link>)`

**Verify:**
- `pnpm test:run -- src/lib/api/services/__tests__/comments.test.ts`
- Stub spec runs as `test.fixme`

---

### Task 9: Fix `/library/likes` routing bug (Phase 2)

**Objective:** `/library/likes` shows liked videos, not history.
**Dependencies:** None
**Mapped Scenarios:** TS-008
**Audit reference:** P1 #16

**Files:**
- Modify: `src/components/pages/library-page.tsx` (`sectionConfig` map for `likes` section)
- Test: `src/components/__tests__/library-page.test.tsx` or section-specific test

**Definition of Done:**
- [ ] `/library/likes` lists liked videos (uses `videoService.getUserRatings()`)
- [ ] `/library/history` still works
- [ ] Vitest covers section routing

**Verify:**
- `pnpm test:run`
- `pnpm test:e2e -- e2e/library.spec.ts` extended

---

### Task 10: Watch Later in Save dialog + endpoint shape fix (Phase 2)

**Objective:** Save dialog offers Watch Later; `/library/watch-later` populates.
**Dependencies:** None
**Mapped Scenarios:** TS-007
**Audit reference:** P1 #17

**Files:**
- Modify: `src/components/save-to-playlist-modal.tsx` (Watch Later option)
- Modify: `src/lib/api/services/playlists.ts:getWatchLater` (probe current shape; align to whatever vidra-core returns)
- Test: `src/lib/api/services/__tests__/playlists.test.ts`
- Create: `e2e/watch-later-flow.spec.ts`

**Definition of Done:**
- [ ] Save → Watch Later → toast → appears in `/library/watch-later`
- [ ] Endpoint 400 resolved (probe + map)
- [ ] Vitest + E2E green

**Verify:**
- `pnpm test:run`
- `pnpm test:e2e -- e2e/watch-later-flow.spec.ts`

---

### Task 11: Bearer token in WS handshake (Phase 3)

**Objective:** `notifications/ws` and `messages/ws` connect on first page load.
**Dependencies:** None
**Mapped Scenarios:** TS-009
**Audit reference:** P0 #12

**Files:**
- Modify: `src/lib/hooks/use-messages-ws.ts` (WS client for messages)
- Modify: `src/lib/hooks/use-live-chat.ts` (WS client for live chat)
- Modify: `src/lib/hooks/use-notification-polling.ts` — likely needs to migrate to a `use-notifications-ws.ts` (verify by reading; may already proxy to a WS hook)
- Modify (if WS path lives there): `src/lib/api/services/notifications.ts`, `src/lib/api/services/messages.ts`
- Test: `src/lib/hooks/__tests__/use-messages-ws.test.ts` (extend), `src/lib/hooks/__tests__/use-live-chat.test.ts` (extend), add `use-notifications-ws.test.ts` if a new hook is created
- Create: `e2e/realtime-ws-auth.spec.ts`

**Key Decisions / Notes:**
- Probe both `?token=<jwt>` query and `Sec-WebSocket-Protocol` subprotocol — adopt whichever vidra-core accepts. Fallback: if neither works, file BE issue and ship polling for notifications (already partially present via `use-notification-polling.ts`); messages WS goes to typed empty state.
- Console log assertion: count "HTTP Authentication failed" repetitions over 30s — must be 0 after fix.

**Definition of Done:**
- [ ] **Either** (a) WS connects on fresh login + no auth-failure spam in console — Vitest + E2E green for WS path
- [ ] **OR** (b) graceful polling fallback installed for notifications (extend `use-notification-polling.ts`) + cross-repo BE issue filed for messages WS — E2E asserts no console flood in the polling case + messages page renders typed empty state
- [ ] Decision documented in commit / PR description: WS path or fallback path
- [ ] Vitest covers chosen path
- [ ] Task 12 only proceeds if branch (a) was taken

**Verify:**
- `pnpm test:run`
- `pnpm test:e2e -- e2e/realtime-ws-auth.spec.ts`

---

### Task 12: WS reconnect-with-fresh-token on token refresh (Phase 3)

**Objective:** WS stays alive across token refresh.
**Dependencies:** Task 11 — branch (a) only. If Task 11 took the polling fallback, Task 12 is **skipped** and FEATURE_VISION UX-06 stays at `partial (BE-blocked)`.
**Mapped Scenarios:** TS-009
**Audit reference:** P0 #12 (extension)

**Files:**
- Modify: `src/lib/hooks/use-messages-ws.ts`, `src/lib/hooks/use-live-chat.ts`, and (if created) `src/lib/hooks/use-notifications-ws.ts` — subscribe to `auth:token-refresh` event, close + reconnect with new token
- Modify: `src/lib/api/client.ts` (emit `auth:token-refresh` after successful refresh — currently only emits `auth:logout` on failure)
- Modify: `src/components/auth-context.tsx` (relay the event if useful for hooks-based consumers)
- Test: extend hook tests to cover refresh-driven reconnect

**Definition of Done:**
- [ ] On refresh → WS reconnects with new token, no duplicate connection
- [ ] Vitest covers reconnect

**Verify:**
- `pnpm test:run`
- E2E spec from Task 11 covers refresh window

---

### Task 13: POST `/streams` sends `channel_id` (Phase 4)

**Objective:** Go Live succeeds (no 400).
**Dependencies:** None
**Mapped Scenarios:** TS-010
**Audit reference:** P0 #11

**Files:**
- Modify: `src/lib/api/services/streams.ts:create` (resolve user's channel first via `channelService.getMyChannels()`)
- Modify: `src/components/pages/livestream-page.tsx`
- Test: `streams.test.ts`
- Create: `e2e/live-streaming-flow.spec.ts` (covers 13, 14, 15)

**Definition of Done:**
- [ ] `POST /streams` returns 201 with stream key
- [ ] Vitest covers payload shape
- [ ] E2E covers TS-010 step 1

**Verify:**
- `pnpm test:run`
- `pnpm test:e2e -- e2e/live-streaming-flow.spec.ts`

---

### Task 14: Real RTMP URL + stream key display (Phase 4)

**Objective:** No `rtmp://your-server/...` placeholder.
**Dependencies:** Task 13
**Mapped Scenarios:** TS-010
**Audit reference:** P0 #11

**Files:**
- Modify: `src/components/pages/livestream-page.tsx` (consume real `rtmp_url` + `stream_key` from response)
- Test: page-level Vitest

**Definition of Done:**
- [ ] After Go Live, real URL + key shown with copy button
- [ ] Vitest covers render

**Verify:**
- `pnpm test:run`
- `pnpm test:e2e -- e2e/live-streaming-flow.spec.ts` (step 1 expectation)

---

### Task 15: End Live button (Phase 4)

**Objective:** Creator can end live stream from UI.
**Dependencies:** Task 13
**Mapped Scenarios:** TS-010
**Audit reference:** P1 LIVE

**Files:**
- Modify: `src/components/pages/livestream-page.tsx`
- Modify: `src/lib/api/services/streams.ts:end`
- Test: `streams.test.ts`

**Definition of Done:**
- [ ] End button visible while live, calls `POST /streams/{id}/end`
- [ ] Save Recording flag honored
- [ ] Vitest covers method + render

**Verify:**
- `pnpm test:run`
- `pnpm test:e2e -- e2e/live-streaming-flow.spec.ts` (step 3)

---

### Task 16: `/live` discovery list — BE-blocked + FE typed-error gating (Phase 4)

**Objective:** `/live` page lists currently-live streams once vidra-core ships the list handler. While blocked, FE renders a typed empty state instead of letting 405s flood the console.
**Dependencies:** vidra-core ships `GET /api/v1/streams` list handler
**Mapped Scenarios:** TS-010
**Audit reference:** P0 LIVE

**Files:**
- Modify: `src/lib/api/services/streams.ts:list` — on 405/404 throw `BackendNotImplementedError`
- Modify: `src/components/pages/live-page.tsx` — typed-error catch renders 'live discovery coming soon' empty state with issue link
- Test: `streams.test.ts` — typed error path
- Create: extend `e2e/live-streaming-flow.spec.ts` — assert visible 'live discovery coming soon' empty state + zero console errors when list endpoint 405s
- File cross-repo issue (BE list handler)

**Definition of Done:**
- [ ] `streams.list()` throws `BackendNotImplementedError` on 405/404; Vitest asserts
- [ ] `/live` page renders the empty state (not a generic error) when BE blocked; Vitest covers
- [ ] E2E asserts no 405 console flood when BE missing
- [ ] If BE shipped: `/live` lists streams — same E2E flips assertion
- [ ] FEATURE_VISION LIVE-03 updated: `partial → partial (BE-blocked: <issue link>)` OR `→ implemented` once BE ships

**Verify:**
- `pnpm test:run -- src/lib/api/services/__tests__/streams.test.ts`
- `pnpm test:e2e -- e2e/live-streaming-flow.spec.ts`

---

### Task 17: `/studio` index page (creator dashboard) (Phase 5)

**Objective:** `/studio` renders without root-layout error; shows quick-link tiles.
**Dependencies:** None
**Mapped Scenarios:** TS-011
**Audit reference:** P0 #8

**Files:**
- Create: `src/app/[locale]/(main)/studio/page.tsx`
- Create: `src/components/pages/studio-page.tsx`
- Modify: `src/components/sidebar.tsx` (link visibility for creators)
- Test: `src/components/pages/__tests__/studio-page.test.tsx`

**Key Decisions / Notes:**
- HIG: card-grid layout, recent videos, channel stats summary, Go Live + Wallet quick-links.
- Pull stats from `analyticsService.getChannelAnalytics(my-channel)` (CORE-13 already implemented).

**Definition of Done:**
- [ ] `/studio` renders, no root-layout error
- [ ] Quick-links navigate
- [ ] Apple HIG applied (44 × 44 targets, WCAG AA, prefers-reduced-motion)
- [ ] Vitest covers render
- [ ] i18n keys present in 13 locales

**Verify:**
- `pnpm test:run`
- `pnpm i18n:check`
- `pnpm test:e2e -- e2e/studio-wallet-gating.spec.ts` (TS-011 step 1)

---

### Task 18: Wallet endpoint feature-flag gating (Phase 5)

**Objective:** `/studio/wallet` either renders real data or shows clean "not yet configured" state — never a 404 storm.
**Dependencies:** None
**Mapped Scenarios:** TS-012
**Audit reference:** P0 #14

**Files:**
- Modify: `src/lib/api/services/payments.ts` (gate calls behind `NEXT_PUBLIC_WALLET_ENABLED`; on 404 raise typed error caught by page)
- Modify: `src/components/pages/wallet-page.tsx` (graceful empty/error states)
- Test: `payments.test.ts`

**Definition of Done:**
- [ ] No 404 storm in console on `/studio/wallet`
- [ ] Empty state shown when feature disabled
- [ ] When enabled + BE ships, real data renders
- [ ] Vitest covers both branches

**Verify:**
- `pnpm test:run`
- `pnpm test:e2e -- e2e/studio-wallet-gating.spec.ts` (TS-012)

---

### Task 19: BTCPay invoice 500 — BE-blocked + FE typed-error gating (Phase 5)

**Objective:** Tip → invoice URL works once vidra-core BTCPay client is fixed. FE surfaces typed error to the tip modal so users see actionable copy instead of a generic 'something went wrong'.
**Dependencies:** vidra-core BTCPay client wiring fix
**Mapped Scenarios:** TS-018 (existing payments-tip-btcpay.spec re-run when BE ships)
**Audit reference:** P0 #13

**Files:**
- Modify: `src/lib/api/services/payments.ts:createInvoice` — wrap 500 in `BackendNotImplementedError` with code `BTCPAY_CREATE_INVOICE_FAILED`
- Modify: `src/components/tip-modal.tsx` (or equivalent) — typed-error catch surfaces 'Bitcoin payments temporarily unavailable; see <issue>' plus a Polar fallback CTA where applicable
- Test: `payments.test.ts` typed error case
- File cross-repo issue
- Re-run `e2e/payments-tip-btcpay.spec.ts` after BE fix

**Definition of Done:**
- [ ] Typed `BackendNotImplementedError` thrown on 500
- [ ] Tip modal renders typed message with issue link
- [ ] Vitest covers both
- [ ] Cross-repo issue filed, linked
- [ ] FEATURE_VISION PAY-02 updated: `partial → partial (BE-blocked: <issue link>)` OR `→ implemented` post-fix

**Verify:**
- `pnpm test:run -- src/lib/api/services/__tests__/payments.test.ts`
- After BE fix: `pnpm test:e2e -- e2e/payments-tip-btcpay.spec.ts` green

---

### Task 20: Inner Circle UI gating until backend ships (Phase 5)

**Objective:** No console-error storm; UI hidden behind `NEXT_PUBLIC_INNER_CIRCLE_ENABLED`.
**Dependencies:** None
**Mapped Scenarios:** TS-015
**Audit reference:** P0 #15

**Files:**
- Modify: `src/lib/api/services/inner-circle.ts` (gate calls; raise typed error)
- Modify: `src/components/pages/studio-inner-circle-page.tsx`, `src/components/pages/watch-page.tsx` (Inner Circle tabs/badges)
- Modify: `src/components/sidebar.tsx` (hide nav link when disabled)
- Test: `inner-circle.test.ts` (extend with disabled-flag branch)

**Key Decisions / Notes:**
- Default `NEXT_PUBLIC_INNER_CIRCLE_ENABLED` = `false`.
- Document flag in `.env.example`.

**Definition of Done:**
- [ ] Console clean on every page when flag off
- [ ] When flag on + BE ships, full flows work (covered by existing `inner-circle-*.spec.ts`)
- [ ] Vitest covers gating
- [ ] FEATURE_VISION PAY-08 updated

**Verify:**
- `pnpm test:run`
- `pnpm test:e2e -- e2e/inner-circle-tier-crud.spec.ts` (passes when flag on; skipped when off)

---

### Task 21: Fix admin service paths (jobs/runners/server-following) (Phase 6)

**Objective:** `/admin/jobs`, `/admin/runners`, `/admin/federation` render real data.
**Dependencies:** None
**Mapped Scenarios:** TS-013
**Audit reference:** P0 #10

**Files:**
- Modify: `src/lib/api/services/admin.ts` (`getJobs` → `/api/v1/jobs`; `getFollowing` → `/api/v1/server/following`)
- Modify: `src/lib/api/services/runners.ts` (paths to `/api/v1/runners`)
- Test: `admin.test.ts`, `runners.test.ts`
- Create: `e2e/admin-contract.spec.ts` (covers tasks 21–25, 27)

**Definition of Done:**
- [ ] All three pages render real data
- [ ] Vitest covers path corrections
- [ ] E2E spec asserts no 404s in network log

**Verify:**
- `pnpm test:run`
- `pnpm test:e2e -- e2e/admin-contract.spec.ts`

---

### Task 22: AuthContext race fix (Phase 6)

**Objective:** First `/admin/*` navigation post-login does not log admin out.

> **Audit caveat:** Audit catalogues this as **P2 #26** (polish/UX) AND lists `ADMIN-G1 (CANDIDATE)` with counter-evidence ("/admin/users + /admin/videos returned 6 + 15 rows of real data"). Treat as **REPRODUCTION-FIRST**: do not write the deeper `isReady` plumbing until the race is reliably reproduced on current main.

**Dependencies:** None
**Mapped Scenarios:** TS-013
**Audit reference:** P2 #26 (catalog) / ADMIN-G1 (candidate)

**Files (only after repro confirmed):**
- Modify: `src/lib/api/client.ts:160-201` (refresh flow)
- Modify: `src/components/auth-context.tsx` (expose `isReady` flag)
- Test: `src/lib/api/__tests__/client.test.ts` (race scenario — must FAIL on pre-fix main)

**Key Decisions / Notes:**
- **RED-step requirement:** before any production code change, write a Vitest case that simulates: clear `localStorage` → seed tokens → mount app → fire admin fetch within first event-loop tick. The test MUST fail on `main@HEAD` to prove the race is real.
- **Tiered fix:** if RED reproduces consistently → `await waitForAuthReady()` plumbing in `apiClient`. If RED is flaky / only repros under simulated latency → ship the lighter `retry-once-on-401-with-stored-token` only and skip the `isReady` plumbing.
- Either fix path: zero regression in `auth.spec.ts` + `auth-oauth.spec.ts`.

**Definition of Done:**
- [ ] RED repro test exists and FAILS on pre-fix `main` (commit the failing test first)
- [ ] After fix, RED test passes
- [ ] Tiered fix decision documented in commit message: `waitForAuthReady` (deep) OR `retry-once-on-401` (defensive)
- [ ] If RED never reproduces consistently after 30 min of debugging: downgrade to defensive retry-once + close ADMIN-G1 as 'candidate not reproducible'; do not ship the deep plumbing
- [ ] Existing `auth.spec.ts` + `auth-oauth.spec.ts` still green
- [ ] No regression in normal logout flow

**Verify:**
- `pnpm test:run`
- `pnpm test:e2e -- e2e/auth.spec.ts e2e/auth-oauth.spec.ts e2e/admin-contract.spec.ts`

---

### Task 23: User ban/unban/role wiring (Phase 6)

**Objective:** Ban toggles user's login result; role-change reflected in DB. If vidra-core has no working path, gate the UI behind a feature flag rather than ship silently-broken toasts.
**Dependencies:** Possibly BE
**Mapped Scenarios:** TS-013
**Audit reference:** ADMIN-G2

**Files:**
- Probe live API first: try `PUT /admin/users/{id}/status`, `PUT /admin/users/{id}/role`, and any alternate shapes (`POST /admin/users/{id}/ban`, etc.) against `pnpm dev:full`. Document the working path.
- Modify: `src/lib/api/services/admin.ts:33-38` — use the verified path, or throw `BackendNotImplementedError` if none works
- Modify: `src/components/pages/admin-users-page.tsx` — gate ban/role row actions behind `NEXT_PUBLIC_ADMIN_USER_MUTATIONS_ENABLED` (default: `false` until BE confirmed)
- Test: `admin.test.ts` — both branches (flag on with real path; flag off with disabled UI)

**Definition of Done:**
- [ ] Probe report committed in plan/PR description naming the working backend path or confirming none exists
- [ ] If working path: flag defaults `true`, UI live, ban+unban+role persist on reload (DB-verified second-tab login attempt)
- [ ] If no working path: flag defaults `false`, action menu shows disabled controls with tooltip 'admin user mutations not yet supported on this backend; see <issue>' — never a silently-failing success toast
- [ ] Vitest covers both flag branches
- [ ] FEATURE_VISION ADMIN-02 updated accordingly

**Verify:**
- `pnpm test:run`
- `pnpm test:e2e -- e2e/admin-contract.spec.ts` (TS-013 step 2)

---

### Task 24: Wire `DELETE /admin/users/{id}` (hard delete) (Phase 6)

**Objective:** Hard delete removes user from listing.
**Dependencies:** None — backend already returns 204
**Mapped Scenarios:** TS-013
**Audit reference:** ADMIN-G3

**Files:**
- Modify: `src/lib/api/services/admin.ts` (add `deleteUser(id)`)
- Modify: `src/components/pages/admin-users-page.tsx` (row menu → confirmation → call)
- Test: `admin.test.ts`

**Definition of Done:**
- [ ] Hard delete with typed-confirmation gate
- [ ] User removed from listing on reload
- [ ] Vitest covers method
- [ ] HIG: destructive confirm dialog with red action

**Verify:**
- `pnpm test:run`
- `pnpm test:e2e -- e2e/admin-contract.spec.ts` (TS-013 step 3)

---

### Task 25: Fix doubled-path bug in admin payouts (Phase 6)

**Objective:** Admin payouts page renders real data.
**Dependencies:** None
**Mapped Scenarios:** TS-013
**Audit reference:** ADMIN-payouts

**Files:**
- Modify: `src/lib/api/services/payments.ts` — search for `payments/admin/payments` and replace with the real prefix
- Test: `payments.test.ts`

**Definition of Done:**
- [ ] Payouts admin loads pending list
- [ ] Vitest covers corrected URL

**Verify:**
- `pnpm test:run`
- `pnpm test:e2e -- e2e/payments-payout-onchain-approve.spec.ts`

---

### Task 26: Decouple `/admin/settings` from `/admin/diagnostics` (Phase 6)

**Objective:** Settings form renders even when diagnostics 404s.
**Dependencies:** None
**Mapped Scenarios:** TS-014
**Audit reference:** ADMIN-config-custom-blocked

**Files:**
- Modify: `src/components/pages/admin-page.tsx` or `admin-settings-page.tsx` (split fetches; show diagnostics as a separate optional panel)
- Modify: `src/components/pages/admin-diagnostics-panel.tsx` (graceful empty)
- Test: page-level Vitest

**Definition of Done:**
- [ ] Settings form independent of diagnostics
- [ ] Diagnostics panel handles 404 gracefully

**Verify:**
- `pnpm test:run`
- `pnpm test:e2e -- e2e/admin-settings.spec.ts`

---

### Task 27: Real federation count on dashboard (Phase 6)

**Objective:** No hard-coded "Active (47 instances)".
**Dependencies:** Task 21 (federation path corrected)
**Mapped Scenarios:** TS-013
**Audit reference:** ADMIN-dashboard-fake-data

**Files:**
- Modify: `src/components/pages/admin-page.tsx` (consume `/api/v1/server/following` count)
- Test: `admin.test.ts` extension

**Definition of Done:**
- [ ] Pill count matches API count
- [ ] Vitest covers fetch + render

**Verify:**
- `pnpm test:run`
- `pnpm test:e2e -- e2e/admin-contract.spec.ts` (TS-013 step 5)

---

### Task 28: Channel `followersCount` mapping (Phase 7)

**Objective:** Channel page shows correct subscriber count everywhere.
**Dependencies:** None
**Mapped Scenarios:** N/A directly (extends existing `subscribe.spec.ts`)
**Audit reference:** P1 #18

**Files:**
- Modify: `src/lib/api/services/channels.ts` OR `src/lib/api/helpers.ts` (centralized mapper)
- Search: rg `subscribers` in channel context — replace reads with `followersCount` mapping
- Test: `channels.test.ts`

**Definition of Done:**
- [ ] Channel page shows real count
- [ ] Watch page channel info shows real count
- [ ] Vitest covers mapper

**Verify:**
- `pnpm test:run`
- `pnpm test:e2e -- e2e/subscribe.spec.ts`

---

### Task 29: Trending route bug — BE-blocked + FE typed-error gating (Phase 7)

**Objective:** `GET /api/v1/videos/trending` returns the trending list once vidra-core fixes the `/videos/{id}` route-conflict. While blocked, FE renders a typed empty state instead of crashing the home/discover sections.
**Dependencies:** vidra-core route conflict fix
**Mapped Scenarios:** N/A directly (covered by trending section in `e2e/home.spec.ts`)
**Audit reference:** P1 #24

**Files:**
- Modify: `src/lib/api/services/videos.ts:listTrending` — on 400 with body matching the route-conflict error, throw `BackendNotImplementedError` with code `TRENDING_ROUTE_CONFLICT`
- Modify: `src/components/pages/trending-page.tsx` and `discover-page.tsx` (trending sections) — render typed empty state with issue link when caught
- Test: `videos.test.ts` typed-error case
- File cross-repo issue
- After BE: re-run trending E2E

**Definition of Done:**
- [ ] Typed `BackendNotImplementedError` thrown when backend signals the route conflict
- [ ] Trending sections render a clean empty state, not a crashed list
- [ ] Vitest covers both branches
- [ ] Cross-repo issue filed
- [ ] FEATURE_VISION CORE-02 updated: `partial → partial (BE-blocked: <issue link>)` OR `→ implemented`

**Verify:**
- `pnpm test:run`
- After BE: `pnpm test:e2e -- e2e/home.spec.ts` (trending section)

---

### Task 30: Videos list shape regression (Phase 7)

**Objective:** `/api/v1/videos?count=10` returns array, not object-keyed shape.
**Dependencies:** Investigate — BE bug or FE coercion?
**Mapped Scenarios:** N/A directly
**Audit reference:** P1 #25

**Files:**
- Probe: hit endpoint, inspect raw response on current main
- If BE bug: file cross-repo issue + add defensive coercion in `videoService.list`
- If FE bug: fix coercion
- Test: `videos.test.ts` (both shapes)

**Definition of Done:**
- [ ] Defensive shape handling in service layer
- [ ] Vitest covers both shapes

**Verify:**
- `pnpm test:run`
- `pnpm test:e2e -- e2e/home.spec.ts`

---

### Task 31: `/api/v1/videos/{id}/studio` graceful gating (Phase 8)

**Objective:** Studio button hidden when 404; UI does not throw.
**Dependencies:** None
**Mapped Scenarios:** N/A
**Audit reference:** P1 #22

**Files:**
- Modify: `src/lib/api/services/studio.ts` (gate behind feature flag + 404 fallback)
- Modify: `src/components/pages/video-edit-page.tsx`
- Test: `studio.test.ts`

**Definition of Done:**
- [ ] No 404 console error on video edit page
- [ ] Studio link hidden when unavailable

**Verify:**
- `pnpm test:run`
- `pnpm test:e2e -- e2e/phase-13-studio-picker.spec.ts`

---

### Task 32: `/api/v1/analytics/*` graceful gating (Phase 8)

**Objective:** Analytics pages graceful when 404.
**Dependencies:** None
**Mapped Scenarios:** N/A
**Audit reference:** P1 #23

**Files:**
- Modify: `src/lib/api/services/analytics.ts` (404 → empty data)
- Modify: `src/components/pages/video-analytics-page.tsx`, `analytics-page.tsx`
- Test: `analytics.test.ts`

**Definition of Done:**
- [ ] Pages render with empty-state when BE 404
- [ ] No console flood

**Verify:**
- `pnpm test:run`
- `pnpm test:e2e -- e2e/phase-13-video-analytics.spec.ts`

---

### Task 33: `/channel/{id}/edit` lands on edit form directly (Phase 9)

**Objective:** Avoid the "Customize Channel" indirection.
**Dependencies:** None
**Mapped Scenarios:** N/A
**Audit reference:** P2 #27

**Files:**
- Modify: `src/app/[locale]/(main)/channel/[id]/edit/page.tsx`
- Modify: `src/components/pages/channel-edit-page.tsx`
- Test: page-level Vitest

**Definition of Done:**
- [ ] Route lands on form
- [ ] Existing `channel-create.spec.ts` / `channel-delete.spec.ts` still green

**Verify:**
- `pnpm test:run`
- `pnpm test:e2e -- e2e/channel-create.spec.ts e2e/channel-delete.spec.ts`

---

### Task 34: Per-item history delete (Phase 9)

**Objective:** Delete one watch-history entry.
**Dependencies:** None
**Mapped Scenarios:** N/A
**Audit reference:** P2 #28

**Files:**
- Modify: `src/lib/api/services/videos.ts` (`deleteHistoryEntry(videoId)`)
- Modify: `src/components/pages/library-page.tsx` (history section row menu)
- Test: `videos.test.ts`

**Definition of Done:**
- [ ] Delete one entry → row gone, others remain
- [ ] Vitest + E2E

**Verify:**
- `pnpm test:run`
- `pnpm test:e2e -- e2e/library.spec.ts`

---

### Task 35: `/settings/wallet` redirect → `/studio/wallet` (Phase 9)

**Objective:** Convenience redirect.
**Dependencies:** None
**Mapped Scenarios:** N/A
**Audit reference:** P2 #30

**Files:**
- Create: `src/app/[locale]/(main)/settings/wallet/page.tsx` — uses `redirect()` from `next/navigation`

**Definition of Done:**
- [ ] `/settings/wallet` 302s to `/studio/wallet`

**Verify:**
- Manual smoke + extend `e2e/settings-live.spec.ts`

---

### Task 36: Login form `autocomplete` attributes (Phase 9)

**Objective:** DOM warnings gone.
**Dependencies:** None
**Mapped Scenarios:** N/A
**Audit reference:** P2 #32

**Files:**
- Modify: `src/components/pages/login-page.tsx` (`autocomplete="username"`, `autocomplete="current-password"`, etc.)

**Definition of Done:**
- [ ] No DOM warnings on `/login`
- [ ] Browser password manager autofills

**Verify:**
- `pnpm test:run`
- Manual browser smoke

---

### Task 37: Resolve duplicate Go Live buttons (Phase 9)

**Objective:** Single Go Live button per page.
**Dependencies:** None
**Mapped Scenarios:** N/A
**Audit reference:** P2 #31

**Files:**
- Modify: `src/components/pages/livestream-page.tsx`

**Definition of Done:**
- [ ] One Go Live button
- [ ] Existing live-streaming E2E still green

**Verify:**
- `pnpm test:run`
- `pnpm test:e2e -- e2e/live-streaming-flow.spec.ts`

## Why

Product report: "a lot of features aren't wired to the frontend still — login flows, managing/deleting users, video history, likes, dislikes, comments. Plus likes don't persist, history doesn't work, logs don't work, can't see videos on my own channel despite count=1."

This plan documents the result of a deep runtime audit driven by Playwright + direct API probing against the live `pnpm dev:full` stack (frontend on :3000, vidra-core backend on :9000, real Postgres, BTCPay, IPFS, ClamAV, all healthy). Four parallel persona agents (viewer, creator, streamer-payments, admin) plus the lead reviewer drove every page and confirmed/refuted each report against the real database — not against mocks.

## PeerTube Parity Check

PeerTube reference (`client/src/app/`): https://github.com/Chocobozzz/PeerTube/tree/develop/client/src/app

| PeerTube area | Vidra status (audited) | Parity gap |
|---|---|---|
| Login | Wired and works | OK |
| Register (inline tab on login) | Wired and works | OK |
| Register (direct `/register`) | **404 + Next.js root-layout runtime error** | **P0** |
| Forgot password / reset password | **404 — login links to a route that doesn't exist** | **P0** |
| Email verification | Not visible in UI | P2 |
| Watch page video player | Renders, plays | OK |
| Like / Dislike on video | Frontend wired, backend writes — **never persists in UI on reload** | **P0 (response shape mismatch)** |
| Comments — list / post / edit / delete / reply / rate | Wired; **POST returns 500 for some users** | **P0 (backend)** |
| Subscribe to channel | Wired; **POST returns 400 for `/channels/{handle}/subscribe`** | **P0 (path or payload)** |
| Watch history | UI exists; **backend tracks `views` table but `GET /users/me/history/videos` returns `views: null` always** | **P0 (backend)** |
| View counter | POST `/views` returns 200 once then 400; **video.views never increments** | **P0 (backend)** |
| Watch later | UI shows "Save to playlist" with no Watch Later option; **`GET /api/v1/playlists/watch-later` returns 400** | **P0** |
| My videos / library | Works for alice (12/12) and bob (2/2) — bug report not reproduced | OK |
| My channel videos count | API total matches rendered count for tested users | OK |
| Search | Works (videos, channels, playlists tabs) | OK |
| Channel page (subscribers, video grid) | Renders; **`channel.subscribers` is undefined** because backend returns `followersCount` but frontend reads `subscribers` | **P1 (shape)** |
| Channel edit | Works end-to-end (display name persists in DB) | OK; minor: `/channel/{id}/edit` lands on channel page with "Customize Channel" button — P2 UX |
| Upload (file + import-from-URL) | Works end-to-end; channel `videosCount` increments | OK |
| Video edit (description, privacy, etc.) | Works end-to-end | OK |
| Studio dashboard `/studio` (creator hub) | **404 + Next.js root-layout runtime error** | **P0** |
| Studio wallet `/studio/wallet` | Shell renders; **every payments API endpoint 404s** | **P0 (backend)** |
| Live streaming "Go Live" | **POST omits `channel_id` → 400** | **P0** |
| Live stream key display after creation | **Hardcoded placeholder; never replaced** | **P0** |
| End live stream button | **Absent** | **P1** |
| Live discovery `/live` | **GET `/streams/?...` returns 405 — backend has no list handler** | **P0** |
| Live chat (real-time) | UI renders disabled; never enables (depends on broken Go Live) | P1 |
| Notifications page | Works (lists notifications) | OK |
| Notifications WebSocket (real-time) | **Bearer token not sent on WS handshake → auth failed every page load, every login** | **P0** |
| Direct messages page + WebSocket | **Same WS auth failure** | **P0** |
| Admin — users (list, ban, unban, role) | Works (6 rows render, ban/unban/role wired) | OK |
| Admin — users (HARD delete) | **No `DELETE /api/v1/users/:id` method on adminService**; only soft-status="deleted" via PUT | **P1** |
| Admin — videos (list, blacklist, remove) | Works (15 rows render) | OK |
| Admin — server logs `/admin/logs` | **`/api/v1/admin/logs` 404** | **P0** |
| Admin — jobs `/admin/jobs` | Frontend calls `/api/v1/admin/jobs` → **404**; real backend path is `/api/v1/jobs` | **P0 (frontend path)** |
| Admin — runners `/admin/runners` | Frontend calls `/api/v1/admin/runners` → **404**; real path `/api/v1/runners` | **P0 (frontend path)** |
| Admin — federation following/followers | Frontend calls `/api/v1/admin/server-following` → **404**; real `/api/v1/server/following` | **P0 (frontend path)** |
| Admin — moderation reports / abuses | Frontend calls `/api/v1/admin/abuses` → **404**; only `/api/v1/users/me/abuses` exists | **P1** |
| Admin — diagnostics | `GET /api/v1/admin/diagnostics` → 404 | P1 |
| Admin — registrations | Path matches; renders empty (no pending registrations) | OK |
| Admin — plugins | Renders | OK |
| Admin — migrations | Renders | OK |
| Admin — settings | Renders shell (toggle persistence not yet tested) | P2 |
| Admin — categories | Service exists; UI not surfaced | P2 |
| ATProto federation UI | Not audited; service `atproto.ts` exists | P2 |
| Per-item history delete | Not implemented (PeerTube has it) | P2 |
| Reports/abuse from a user perspective (My reports) | `/api/v1/users/me/abuses` exists; UI not visible | P2 |

## Vidra-Specific / Requested Features

Backend extension impact:

| Vidra extension | Status | Notes |
|---|---|---|
| **IOTA Crypto Payments** (legacy) | Migrated to Bitcoin/BTCPay (project memory) | Out of scope — see migration plans |
| **Bitcoin / BTCPay payments** | **Broken** | `POST /api/v1/payments/invoices` → 500 CREATE_INVOICE_FAILED. BTCPay container itself reachable on :14080. `vidra-core` BTCPay client wiring is the bug. |
| **Inner Circle** (memberships, tiers, badges) | **Backend missing entirely** | All `/api/v1/inner-circle/*` endpoints 404. Frontend service has full surface; backend has none. Console error every page load. |
| **Direct Messages (E2EE)** | UI wired; **WS auth broken** | Same WS handshake bug as notifications. |
| **Real-time stream chat** | UI wired; depends on broken Go Live + WS | Cascading P0 |
| **Wallet (`/studio/wallet`)** | **All endpoints 404** | `/payments/config`, `/wallet/balance`, `/wallet/transactions`, `/payouts/me`. Probably part of unfinished BTCPay migration. |
| **ATProto federation** | UI mention only; not audited | Defer |
| **IPFS distribution** | Transparent (player loads `/static/web-videos/...`) | Working for already-uploaded videos |
| **Video Studio** (cut, intro/outro, watermark) | Endpoint `/api/v1/videos/{id}/studio` → 404 | P1 |
| **Auto-Captioning** | `/api/v1/videos/{id}/captions` → 200 (empty list) | OK (works, no captions for test video) |
| **Advanced Analytics** | `/api/v1/analytics/videos/{id}` → 404, `/analytics/channels/{handle}` → 404 | P1 |

Backend extensions explicitly impacted by remediation: **IOTA→BTCPay migration tail, Inner Circle, Direct Messaging WS auth, Real-time Stream Chat, Live Streaming, Video Studio, Advanced Analytics**.

## Confirmed Bug Catalog (with evidence)

### P0 — Blockers (admin additions from late agent return)

**ADMIN-G1 (CANDIDATE) — Admin page renders may log admin out** (needs reproduction)
- Admin agent reports: visiting any `/admin/*` issues a fetch without `Authorization: Bearer`, gets 401, the api client refresh-fail clears tokens via `clearTokens()` + `auth:logout`, admin is logged out.
- **Counter-evidence:** my own /admin/users + /admin/videos runs returned 6 + 15 rows of real data, so the bearer IS attached in some flows. Likely a race on initial admin-page navigation (related to creator-alice's "first nav post-login → 401" finding).
- Action: investigate `src/lib/api/client.ts:160-201` refresh flow; reproduce the navigation timing.

**ADMIN-G2 (P0 — VERIFIED) — Every admin user-management write is dead**
- `PUT /api/v1/admin/users/{id}/status` → 404 NOT_FOUND on backend.
- `PUT /api/v1/admin/users/{id}/role` → 404 NOT_FOUND on backend.
- Means ban / unban / role-change / soft-delete in `/admin/users` ALL silently fail. Toast says success, DB unchanged.
- Either backend implements those routes OR frontend calls a different endpoint shape that vidra-core actually exposes.
- Files: `src/lib/api/services/admin.ts:33-38`, `src/components/pages/admin-users-page.tsx`.

**ADMIN-G3 (P0 — VERIFIED) — Hard-delete user: backend works, frontend never calls it**
- `DELETE /api/v1/admin/users/{id}` → 204 (backend works, user removed from listing).
- Frontend has zero callers. Add `adminService.deleteUser(id)` and wire it into the row menu.

**ADMIN-payouts (P0 — VERIFIED) — Doubled path in frontend service**
- Frontend calls `/api/v1/payments/admin/payments/payouts?status=pending` — note the doubled `payments/admin/payments/`. 404.
- Files: search `src/lib/api/services/payments.ts` for `payments/admin/payments` and fix the prefix.

**ADMIN-fed-block (P0) — Frontend mis-prefixes federation paths**
- `GET /api/v1/admin/server-following` → 404. Real path: `/api/v1/server/following` (verified 200).
- `GET /api/v1/blocklist/servers` works; frontend bearer probably the only issue there.
- Backend ATProto status: `GET /api/v1/federation/atproto/status` → 404 (route missing).

**ADMIN-dashboard-fake-data (P1) — `/admin` federation pill is hard-coded**
- "Active (47 instances)" is a literal string, not from API. Even when API works, dashboard lies.
- Files: `src/components/pages/admin-page.tsx`.

**ADMIN-roles (P1) — `/admin/roles` page issues no fetch and backend has no route**
- Frontend service doesn't call anything; `/api/v1/admin/roles` → 404. Page is decoration.

**ADMIN-config-custom-blocked (P0) — Site Settings save is reachable but UI gates on broken diagnostics**
- `PUT /api/v1/config/custom` → 200, round-trips. Backend works.
- UI is blocked because page also fetches `/api/v1/admin/diagnostics` → 404 and short-circuits the form. Decouple the diagnostics call so settings render even when diagnostics is missing.

### P0 — Blockers (original)

1. **Like/dislike never persists in UI on reload**
   - Evidence: `PUT /api/v1/videos/{id}/rating` → 200. Reload → `aria-pressed="false"`, count="0". `GET /api/v1/videos/{id}/rating` returns `{video_id, likes_count, dislikes_count, user_rating}` (snake_case + numeric). Frontend `VideoRatingStats` expects `{likes, dislikes, userRating: "like"|"dislike"|"none"}` (camelCase + string). **No `userRating` field is ever produced; the UI cannot display the user's persisted rating.**
   - Files: `src/lib/api/services/videos.ts:225-238`, `src/lib/api/types.ts:343-349`, `src/components/pages/watch-page.tsx:177-182`.
   - Fix: map response in `videoService.getRating()` from `{likes_count, dislikes_count, user_rating}` → `{likes, dislikes, userRating: user_rating===1?"like":user_rating===-1?"dislike":"none"}`.

2. **Watch history backend broken**
   - Evidence: full snake_case `/views` payload returns 200 OK; `GET /users/me/history/videos` always returns `{count: 0, views: null}`. Backend not populating user_history table.
   - Owner: `vidra-core` (Go backend). Frontend already correct.

3. **Video view counter never increments**
   - Evidence: 3 unique-session POSTs return 200, `video.views` stays at 0.
   - Owner: `vidra-core`.

4. **Comment POST 500 for non-channel-owners** (bob, possibly others)
   - Evidence: `POST /api/v1/videos/{id}/comments` → 500 Internal Server Error when posting to admin's video as bob. Same flow as alice (channel owner) → 201 OK.
   - Owner: `vidra-core` — investigate auth/policy path for cross-user commenting.

5. **Subscribe by handle returns 400**
   - Evidence: `POST /api/v1/channels/{handle}/subscribe` → 400 Bad Request. Likely needs channel UUID or different endpoint shape.
   - Files: `src/lib/api/services/channels.ts:57-64`. Needs frontend to resolve handle→UUID first OR backend to accept handle.

6. **`/forgot-password` and `/reset-password` routes don't exist**
   - Evidence: login page links to `/forgot-password` → 404. `authService.requestPasswordReset` exists but is unreachable.
   - Files: missing `src/app/[locale]/(main)/forgot-password/page.tsx` and `reset-password/page.tsx`. Need pages + UI flow + AuthContext exposure.

7. **`/register` and `/signup` direct routes 404 + root-layout runtime error**
   - Evidence: `/register` → 404 + Next.js error "Missing `<html>` and `<body>` tags in the root layout". The route is only available as a tab toggle on `/login`.
   - Fix: add a `/register` route that wraps the existing register form (or redirect to `/login?mode=register`).

8. **`/studio` index 404 + root-layout runtime error**
   - Evidence: only `/studio/wallet` and `/studio/inner-circle` exist; visiting `/studio` 404s and triggers Next.js runtime error.
   - Fix: add `src/app/[locale]/(main)/studio/page.tsx` with creator dashboard (PeerTube parity: stats, recent videos, quick links).

9. **`/admin/logs` calls `/api/v1/admin/logs` → 404**
   - Evidence: backend has no logs endpoint at this path. Confirmed by exhaustive probe (`/admin/logs/audit`, `/server/logs`, `/logs` all 404).
   - Owner: either implement endpoint in `vidra-core` OR update frontend to a real path. If unsupported by backend, hide the page.

10. **Frontend admin paths don't match backend**
    - `adminService.getJobs()` calls `/api/v1/admin/jobs` → 404. Real path: `/api/v1/jobs`.
    - `adminService.getRunners()` (or runners.ts) calls `/api/v1/admin/runners` → 404. Real: `/api/v1/runners`.
    - `adminService.getFollowing()` calls `/api/v1/admin/server-following` → 404. Real: `/api/v1/server/following`.
    - Files: `src/lib/api/services/admin.ts`, `src/lib/api/services/runners.ts`.

11. **Live streaming end-to-end broken**
    - `POST /api/v1/streams/` omits `channel_id` (frontend bug — must fetch user's channel first). Backend returns 400.
    - Stream key never replaces hardcoded `rtmp://your-server/...` placeholder (frontend bug).
    - `/live` discovery → `GET /api/v1/streams/?start=0&count=24` → 405. Backend missing list handler.
    - End live stream button absent on `/livestream`.
    - Files: `src/components/pages/livestream-page.tsx`, `src/lib/api/services/streams.ts`. Backend: vidra-core stream module needs GET list handler.

12. **WebSocket auth fails for notifications + messages**
    - Evidence: `ws://localhost:9000/api/v1/notifications/ws` and `messages/ws` fail with "HTTP Authentication failed; no valid credentials available" repeatedly (4+ retries per page).
    - Cause: WS handshake doesn't include the bearer token (likely needs `?token=...` query param or `Sec-WebSocket-Protocol` header).
    - Files: `src/lib/realtime/*` (need to find the WS client), `src/lib/api/services/notifications.ts`, `messages.ts`.

13. **Bitcoin invoice creation 500s for premium + tips**
    - Evidence: `POST /api/v1/payments/invoices` → 500 CREATE_INVOICE_FAILED. BTCPay (:14080) is healthy.
    - Owner: `vidra-core` BTCPay client wiring. See escape hatch in `docs/plans/2026-04-22-payment-reconciliation-dual-mode.md`.

14. **`/studio/wallet` all backing endpoints 404**
    - `/api/v1/payments/config`, `/wallet/balance`, `/wallet/transactions`, `/payouts/me`.
    - Owner: `vidra-core`. Either still in migration or wrong paths.

15. **Inner Circle backend entirely missing**
    - Every `/api/v1/inner-circle/*` and `/api/v1/payments/memberships/me` returns 404. Frontend has full service and pages. Console error every page.
    - Owner: `vidra-core` OR hide frontend until backend ships.

### P1 — Significant gaps

16. **`/library/likes` page renders Watch History UI** (component routing bug). Files: `src/components/pages/library-page.tsx` `sectionConfig`.
17. **Watch Later flow non-functional** — Save dialog shows only "Create new playlist" (no Watch Later option). `GET /api/v1/playlists/watch-later` → 400.
18. **Channel `subscribers` field name mismatch** — backend returns `followersCount`, frontend reads `subscribers`. Watch page shows "0 subscribers" always.
19. **Admin user hard delete missing** — only soft `status="deleted"` via PUT. PeerTube has `DELETE /api/v1/users/:id`.
20. **Admin abuse/reports endpoint mismatch** — `/api/v1/admin/abuses` → 404; only user-side `/users/me/abuses` exists.
21. **Admin diagnostics 404** — `/api/v1/admin/diagnostics` not on backend.
22. **Video Studio endpoints 404** — `/api/v1/videos/{id}/studio`. Frontend `studio.ts` service unreachable.
23. **Advanced analytics endpoints 404** — `/api/v1/analytics/videos/{id}`, `/analytics/channels/{handle}`.
24. **Trending endpoint route bug** — `GET /api/v1/videos/trending` → 400 "Invalid video ID format" (router treating "trending" as a UUID path param).
25. **`/api/v1/videos?count=10` shape regression** — returns `data` keyed `{"0":..., "1":...}` instead of an array. Some endpoint shape inconsistency vs. paginated channel videos.

### P2 — Polish / UX

26. AuthContext race on first navigation post-login → 401 retry needed (creator-alice finding).
27. `/channel/{id}/edit` lands on view page with "Customize Channel" button instead of form directly.
28. Per-item history delete missing.
29. Per-user public profile page missing (`/api/v1/users/:id`).
30. `/settings/wallet` → 404 (real route is `/studio/wallet`).
31. Two "Go Live" buttons with different behavior on `/livestream`.
32. Login form missing `autocomplete` attributes (DOM warning).

## Phased Remediation

Each phase below is a candidate for its own `/spec` cycle. Phases are ordered by user-visible severity, not by ease.

### Phase 1 — Auth completeness (P0)
- Add `/forgot-password` page wired to `authService.requestPasswordReset`.
- Add `/reset-password` page (token-from-email flow).
- Add direct `/register` route (or redirect to `/login?mode=register`).
- Fix `/register` Next.js root-layout runtime error.
- Add `requestPasswordReset` to AuthContext.

### Phase 2 — Engagement loop (P0)
- Fix `videoService.getRating()` shape mapping (snake_case + numeric → camelCase + string `userRating`).
- Investigate + fix `POST /comments` 500 for non-channel-owner case (likely backend, file under vidra-core).
- Fix subscribe by handle 400 (frontend resolves handle→UUID first).
- Fix watch counter persistence on backend (vidra-core).
- Fix watch history backend population (vidra-core).
- Fix `/library/likes` routing bug (uses History config).
- Fix Watch Later (UI dialog option + backend playlist endpoint).

### Phase 3 — Real-time (P0)
- Pass bearer token in WS handshake for `notifications/ws` and `messages/ws`.
- Add WS reconnect-with-fresh-token on token refresh.

### Phase 4 — Live streaming (P0)
- Fix Go Live: fetch current user's channel, send `channel_id` in `POST /streams`.
- Display real RTMP URL + stream key after creation.
- Add End Live button.
- Backend: add `GET /api/v1/streams` list handler (vidra-core).
- Wire `/live` discovery once backend list is available.

### Phase 5 — Studio + Wallet (P0)
- Add `/studio/page.tsx` index (creator dashboard with stats + quick links).
- Backend: implement `/api/v1/payments/config|wallet/*|payouts/me` OR remove the wallet UI until BTCPay migration completes.
- Fix `POST /api/v1/payments/invoices` 500 in vidra-core (BTCPay client wiring).
- Hide Inner Circle UI behind feature flag until backend ships, OR scope a vidra-core Inner Circle MVP.

### Phase 6 — Admin contract fixes (P0/P1)
- Fix `adminService.getJobs/getRunners/getFollowing` to call `/api/v1/jobs`, `/runners/`, `/server/following` (not the `/admin/...` prefixes).
- **NEW:** Investigate ADMIN-G1 race — does first `/admin/*` navigation fire fetch before AuthContext hydrates the bearer? Repro: clear localStorage, login, immediately navigate to `/admin/users`, watch `localStorage.getItem('vidra_access_token')` go null. Fix: make `apiClient` wait on AuthContext.isReady OR retry once on 401 with token from storage.
- **NEW:** Resolve ban/unban/role 404s — either implement `PUT /admin/users/{id}/status|role` in vidra-core, or change frontend to use whatever route vidra-core actually exposes (probe further).
- **NEW:** Wire `DELETE /api/v1/admin/users/{id}` (backend already returns 204) into `adminService.deleteUser` + row menu in `/admin/users`.
- **NEW:** Fix doubled-path bug `/api/v1/payments/admin/payments/payouts` → `/api/v1/payments/payouts` (or whatever vidra-core actually exposes).
- **NEW:** Decouple `/admin/settings` from broken `/admin/diagnostics` so config form renders.
- **NEW:** Replace hard-coded "Active (47 instances)" federation pill on `/admin` with real count from `/api/v1/server/following`.
- Decide: implement `/api/v1/admin/{logs,stats,system-health,diagnostics,roles}` in vidra-core, OR hide those pages until backend ships.
- Fix admin abuses path: frontend probably calls `/admin/abuses`; real backend path is `/admin/abuse-reports`.

### Phase 7 — Shape mismatches sweep (P1)
- Channel: read `followersCount` instead of `subscribers` everywhere (or add a mapper in `helpers.ts`).
- Trending: fix `/api/v1/videos/trending` 400 in vidra-core (route conflict with `/videos/{id}`).
- `/api/v1/videos` list shape regression: investigate why payload is keyed `{"0":...,"1":...}` not an array.

### Phase 8 — Studio (P1)
- Investigate `/api/v1/videos/{id}/studio` 404 — confirm whether feature shipped in vidra-core; gate UI accordingly.
- Same for `/api/v1/analytics/*`.

### Phase 9 — Polish (P2)
- AuthContext hydration race fix.
- `/channel/{id}/edit` lands on form directly.
- Per-item history delete.
- `/settings/wallet` redirect to `/studio/wallet`.
- Add `autocomplete` attributes to login fields.
- Resolve duplicate Go Live buttons.

## Verification Plan

**For each phase**, the `/spec` cycle MUST include:

### Per-phase
- New Vitest unit tests for any service shape mappings or new context methods (target ≥80% coverage on touched files).
- Playwright E2E test that drives the affected flow against the running dev stack (mirrors the audit methodology — login as a real user, perform the action, RELOAD, assert persistence in DB via API call or UI re-render).
- Manual browser walkthrough captured in the spec (Chrome devtools or playwright-cli snapshot).

### Cross-cutting (run after every phase)
- `pnpm lint` — must pass.
- `pnpm typecheck` — must pass.
- `pnpm test:run` — full Vitest suite, 0 failures.
- `pnpm test:e2e` — full Playwright suite, 0 failures.
- `pnpm build` — production build succeeds.

### Browser-verification protocol (Apple HIG + actual usage)
For every fixed page:
1. Login as a real seeded user (alice, bob, charlie, or admin) against `pnpm dev:full`.
2. Drive the fix through `playwright-cli` (or Claude-in-Chrome / chrome-devtools-mcp) end-to-end.
3. Capture network log — assert no new 4xx/5xx, no new console errors.
4. Reload the page and assert UI reflects DB state (the audit's central assertion).
5. Persist evidence in the spec verification scenario.

### Regression guard
The audit JSON reports at `/tmp/vidra-audit/{viewer-bob,creator-alice,streamer-payments,admin}.json` form a baseline. Each phase's `/spec` must:
- Re-run the relevant audit slice.
- Show fewer P0/P1 findings than the baseline.
- Not introduce new failures elsewhere.

## Out of scope

- Deep backend (`vidra-core`) source review. This plan documents required backend changes by external behavior; the actual Go fixes belong in the vidra-core repo.
- ATProto federation UI surfacing.
- Per-user public profile pages (`/u/:username`).
- Admin categories UI surfacing.
- Email verification UI flow.

<!-- Tasks moved to ## Progress Tracking + ## Implementation Tasks at the top of the file. -->


Done: 0 / 9 phases · Left: 9 / 9
