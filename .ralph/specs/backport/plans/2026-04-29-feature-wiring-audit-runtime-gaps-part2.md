# Feature Wiring Audit — Runtime Gap Remediation (Part 2: Phases 4–9)

Created: 2026-04-29
Status: VERIFIED
Approved: Yes
Iterations: 1
Type: Feature
Worktree: No
Branch: main
Predecessor: docs/plans/2026-04-28-feature-wiring-audit-runtime-gaps.md (Phases 1–3 shipped)

> Promoted via the predecessor plan's pre-declared cut point: "Phases 4–9 (Tasks 13–37) become a follow-up plan starting at Task 13." Same audit, same architecture, same conventions — only the task surface changes.

## Summary

**Goal:** Close the remaining P0/P1/P2 wiring gaps from `/tmp/vidra-audit/*.json` baseline (live streaming, studio + wallet, admin contract, shape mismatches, studio analytics, polish).

**Tech Stack / Patterns:** Identical to predecessor — Next.js 15, React 19, TS, Vitest, Playwright, Tailwind v4, vidra-core sibling repo. Reuse `BackendNotImplementedError` from `src/lib/api/errors.ts`, `auth:token-refresh` event from `src/lib/api/client.ts`, frontend service pattern, AuthContext extension pattern, page route shape, i18n parity check, Apple HIG, telemetry conventions.

**Pre-declared assumption:** All Phase 1–3 fixes from the predecessor plan are landed and green (1655/1655 Vitest, typecheck clean). This part 2 builds on top.

## Approach

Continue the per-task TDD loop. Each task ships its Vitest first, then implementation, then a Playwright reload-asserts spec where applicable. BE-blocked tasks ship a typed `BackendNotImplementedError` + cross-repo issue link + `test.fixme()` Playwright stub.

## Implementation Tasks

The full task definitions (objectives, files, verify commands) live in the predecessor plan under `## Implementation Tasks`. They are referenced here by number to avoid duplication. **Source of truth:** `docs/plans/2026-04-28-feature-wiring-audit-runtime-gaps.md` Tasks 13–37.

### Phase 4 — Live streaming (P0)

- [x] Task 13: POST `/streams` sends `channel_id`
- [x] Task 14: Real RTMP URL + stream key display
- [x] Task 15: End Live button
- [x] Task 16: `/live` discovery typed-error gating + BE list handler shipped (vidra-core `routes.go`: added `GET /api/v1/streams/` with `OptionalAuth` reusing `GetActiveStreams`)

### Phase 5 — Studio + Wallet (P0)

- [x] Task 17: `/studio` index page (creator dashboard)
- [x] Task 18: Wallet endpoint feature-flag gating
- [x] Task 19: BTCPay invoice typed-error gating + BE typed-503 (vidra-core `btcpay_handlers.go`: detects `domain.ErrBTCPayUnavailable`, returns 503 with code `BTCPAY_UNAVAILABLE` instead of opaque 500)
- [x] Task 20: Inner Circle UI gating (default `NEXT_PUBLIC_INNER_CIRCLE_ENABLED=false`)

### Phase 6 — Admin contract (P0/P1)

- [x] Task 21: Admin service paths (jobs/runners/server-following)
- [x] Task 22: AuthContext race fix (REPRODUCTION-FIRST — RED test reproduced ADMIN-G1 only under simulated latency; per plan tier 2, shipped defensive `retry-once-on-401-with-stored-token` in `apiRequest`; skipped deep `isReady` plumbing per plan caveat)
- [x] Task 23: User ban/unban/role wiring (probed live API; PUT/POST/DELETE all return 401 not 404 — backend supports them; flag default true; UI gated on `NEXT_PUBLIC_ADMIN_USER_MUTATIONS_ENABLED`)
- [x] Task 24: DELETE /admin/users/{id} (hard delete — backend already 204)
- [x] Task 25: Fix doubled-path bug in admin payouts
- [x] Task 26: Decouple `/admin/settings` from `/admin/diagnostics` (already structurally separate; added regression-lock test in `admin-settings-decoupled.test.tsx`)
- [x] Task 27: Real federation count on dashboard (replace hard-coded "47")

### Phase 7 — Shape mismatches sweep (P1)

- [x] Task 28: Channel `followersCount` mapping
- [x] Task 29: Trending route typed-error gating + BE route conflict fixed (vidra-core `routes.go`: added `GET /api/v1/videos/trending` as static segment before `/{id}` so chi resolves correctly)
- [x] Task 30: Videos list shape regression (defensive coercion)

### Phase 8 — Studio analytics (P1)

- [x] Task 31: `/api/v1/videos/{id}/studio` graceful gating
- [x] Task 32: `/api/v1/analytics/*` graceful gating

### Phase 9 — Polish (P2)

- [x] Task 33: `/channel/{id}/edit` lands on form directly (already shipped — route renders ChannelEditPage form, no indirection)
- [x] Task 34: Per-item history delete
- [x] Task 35: `/settings/wallet` redirect → `/studio/wallet`
- [x] Task 36: Login form `autocomplete` attributes
- [x] Task 37: Resolve duplicate Go Live buttons (renamed mode-toggle "Go Live" tab → "Now" so the only literal "Go Live" CTA is the header action button)

### Cross-cutting verification (`spec-verify` phase)

- [x] Re-run `/tmp/vidra-audit/*.json` baseline; show fewer P0/P1 findings; no new failures (live console verified — single gated 405 for /streams instead of console flood; trending route conflict fixed in BE)
- [x] `docs/FEATURE_VISION.md` rows promoted: LIVE-01, LIVE-02, LIVE-03, ADMIN-02, PAY-02, PAY-05, PAY-07, PAY-08
- [x] `pnpm lint` / `pnpm typecheck` / `pnpm test:run` / `pnpm build` all green; `pnpm test:e2e` not run (full Playwright suite not driven; pre-existing integration warnings only)
- [x] Live browser verification against `pnpm dev:full`: `/live` typed empty state renders correctly with single (gated) 405 in console; `/studio` unauthenticated guard renders Apple-HIG copy; `/login` autocomplete attrs (`username`, `current-password`) confirmed via `document.querySelectorAll('input')`

**Total Tasks:** 25 · **Completed:** 25 · **Remaining:** 0

## PeerTube Parity Check

Same parity targets as the predecessor plan. Phases 4 (Live streaming) and 6 (Admin) are direct PeerTube ports — review `client/src/app/+videos/+video-watch/+video-live` and `client/src/app/+admin/users` before implementing.

## Vidra-Specific / Requested Features

Backend extensions touched in this part:
- **Live Streaming** — Tasks 13–16 (Go Live flow, RTMP URL, end-stream, /live discovery)
- **Bitcoin / BTCPay payments** — Task 19 (invoice 500 typed-error gate)
- **Wallet (`/studio/wallet`)** — Task 18 (feature-flag gate the 404 storm)
- **Inner Circle** — Task 20 (UI gating until backend ships)
- **Video Studio** — Task 31 (graceful 404 fallback on `/videos/{id}/studio`)
- **Advanced Analytics** — Task 32 (graceful 404 fallback on `/analytics/*`)
- **Real-time Stream Chat** — Indirectly fixed by Phase 3's WS auth in the predecessor; Task 16's `/live` discovery surfaces the chat experience

## Verification Plan

Identical to the predecessor plan's `## Verification Plan` section. Each phase: Vitest unit tests → Playwright reload-asserts → manual browser walkthrough → cross-cutting suite → audit baseline diff.

## Why

Phases 4–9 split out per pre-declared cut point in the predecessor plan to keep each `/spec` cycle within a single TDD loop's worth of context.

## Post-Verification User-Reported Bugs (Manual rounds during /spec-verify)

### Round 2 — admin/moderator video edit + comprehensive deep-dive

User reported: "admins and moderators cannot edit videos of regular users due to auth errors when they should be able to edit and delete videos any user uploads." Plus: "thoroughly test the full suite ... ensure changes persist information in the database and is retrieved back."

**Two BE bugs found and fixed in vidra-core `internal/httpapi/handlers/video/videos.go`:**

1. **`UpdateVideoHandler` ownership check** (line 442) only allowed `existingVideo.UserID != userID` to proceed; admins/mods got 403. Fixed: now reads `middleware.UserRoleKey` from context, sets `isStaff = role == "admin" || role == "moderator"`, allows staff bypass: `if existingVideo.UserID != userID && !isStaff { 403 }`.
2. **`UpdateVideoHandler` ownership transfer** (line 488) had `video.UserID = userID` which when staff edited would silently transfer ownership — and in combination with the repo's `WHERE id = $1 AND user_id = $15` filter, caused a 0-rows-affected → `VIDEO_NOT_FOUND` 404 instead of a successful update. Fixed: removed the assignment so the original owner is preserved (verified live: alice's video stays owned by alice after admin/moderator edits).
3. **`DeleteVideoHandler`** had similar issue. Fixed: handler reads `middleware.UserRoleKey`, sets `deleteAs = existingForDelete.UserID` when staff so the repo's `WHERE id = $1 AND user_id = $2` SQL still matches.

**Live verification against rebuilt Docker container (`docker compose up -d --build app`):**

| Scenario | Expected | Actual | Evidence |
|----------|----------|--------|----------|
| Admin (admin@example.com) PUT alice's video | 200, owner unchanged | 200, owner stays alice (5d804330) | DB read-back via `GET /videos/{id}` |
| Admin DELETE alice's video | 204, GET returns 404 after | 204 + post-GET 404 | Two fetches in single eval |
| Moderator (charlie@example.com) PUT alice's video | 200, owner unchanged | 200, owner stays alice (5d804330) | DB read-back |
| Regular user (bob@example.com) PUT alice's video | 403 | 403 UNAUTHORIZED | Negative test passes |
| Watch page renders persisted edit | "Moderator Edit OK" title shown | ✅ rendered | Browser snapshot |
| Account creation (`POST /auth/register`) → login → /me | full flow round-trips | reg 201, login 200, /me returns new user | DB row visible via `psql` |

**Verified:**
- `pnpm test:run`: **1697/1697 passing**
- `pnpm typecheck`: clean
- `pnpm build`: production build green
- `vidra-core go test ./internal/httpapi/handlers/{video,channel}/`: ok (channel cached, video re-ran)
- `vidra-core go build ./...`: EXIT=0
- `docker compose up -d --build app`: container running with new binary on `:9000`

Operational artifact: added `docker-compose.override.yml` (port `9000:8080` + container-internal DATABASE_URL/REDIS_URL/IPFS_API/ENABLE_IPFS) so the BE container can be rebuilt + run cleanly without the host `.env` `localhost:5432` clobbering compose's network-internal hostnames.

### Round 3 — video watch history (earlier rounds dragged it in too)

User reported: "Video history doesn't work still." Three independent bugs found and fixed end-to-end via instrumentation + DB inspection.

1. **FE session_id was not a UUID** (`videos.ts:createClientTrackingId`). The function emitted `session-${randomUUID()}` (with literal `session-` prefix). Backend's `user_views.session_id` column is UUID and rejects anything else, so the async track-view worker failed silently after the handler returned 200. Fixed: emit a bare UUID; added a `UUID_RE` guard in `getOrCreateStorageValue` to drop legacy `session-…` values from sessionStorage so users with stale browser state recover automatically.
2. **BE swallowed insert errors** (`internal/usecase/views/service.go:processViewTask`). The async worker's two failure points (`GetUserViewBySessionAndVideo` and `CreateUserView`) returned silently. Added `slog.Error` logging that surfaced the underlying `pq: invalid input syntax for type uuid` — which immediately pointed at bug #1.
3. **BE history query ignored user_id filter** (`internal/repository/views_repository.go:GetViewsByDateRange`). The SQL was `SELECT * FROM user_views WHERE 1=1` and only conditionally added `video_id`/`start_date`/`end_date` — the handler set `filter.UserID = callerID` but the repo never applied it. Added the missing `AND user_id = $N` branch.

**Live end-to-end verification (with rebuilt BE binary on `:9000`):**

| Action | Status | DB Verified |
|--------|--------|-------------|
| `POST /api/v1/videos/{id}/views` with bare-UUID `session_id` | 200 OK | New row in `user_views`, async worker drained queue successfully |
| `GET /api/v1/users/me/history/videos` after view recorded | 200 with `count: 1, views: [...]` | Returns alice's view with correct `video_id`, `user_id` |
| Pre-fix probe: same flow with `session-XYZ` id | view returns 200 but `slog.Error` logs `pq: invalid input syntax for type uuid` and history stays `views: null` | confirmed in `docker logs vidra-core-app-1` |

**Verified:** `pnpm test:run` 1697/1697 ✅. `go test ./internal/usecase/views/ ./internal/httpapi/handlers/video/ ./internal/httpapi/handlers/channel/` all ok. (One pre-existing failure in `./internal/repository/` `TestVideoRepository_Unit_Create` — argument-count mismatch from prior commits unrelated to Part 2 changes; documented but not in this plan's scope.)

### Round 1 — channel customize fixes (earlier in this verify)

User reported: "customise channel is still broken, cannot upload banner or user photo. Fix this and also ensure every field can be saved." Three independent bugs found and fixed via live Playwright + DB-persistence verification:

1. **Channel edit page redirected legitimate owner away** — `channel-edit-page.tsx` ownership guard fired before `useAuth().user` finished loading (`user?.id` was undefined → `user?.id !== channel.accountId` was true → redirect). Fixed by reading `loading: authLoading` from `useAuth()` and gating the guard + render-time skeleton on it.
2. **Avatar/banner uploaded but never displayed** — backend serializes `avatarFilename` / `bannerFilename` (raw filename), frontend `Channel` type uses `avatarUrl` / `bannerUrl`. Added `coerceChannelMediaUrls` in `channels.ts` that maps `avatarFilename` → `${API_BASE}/lazy-static/avatars/{filename}` (and banners) on every channel read (`getById`, `list`, `getMyChannels`, `update`).
3. **Backend channel_media handler never wrote bytes to disk + no static serving** — `channel_media.go:uploadMedia` only stored the filename in DB, dropping the file body. Fixed: handler now `os.MkdirAll` + `io.Copy` to `paths.AvatarsDir()` / `paths.BannersDir()` with crypto-random filename + canonical extension (security: prevents path traversal + caller-controlled collisions). Added `ServeAvatar` / `ServeBanner` routes at `GET /lazy-static/{avatars,banners}/{filename}` reusing `paths.{Avatars,Banners}Dir()`. Added `paths.BannersDir()` helper. Updated `channel_media_test.go` (`NewChannelMediaHandlers` now requires `*config.Config`) — all 30 tests pass.

**DB-persistence verified live:**

| Field | Set via UI | DB read-back | Reload reads back into form |
|-------|-----------|--------------|----------------------------|
| `displayName` | "Alice — Customize Test 2026-04-29" | ✅ `updatedAt` fresh | ✅ |
| `description` | "Browser-driven persistence test 2026-04-29" | ✅ | ✅ |
| `support` | "Tip me at lightning:..." | ✅ | ✅ |
| Avatar URL field | resolved to absolute `http://localhost:9000/lazy-static/avatars/...` | ✅ DB stores `avatarFilename` | ✅ FE coerce maps it back to URL |

## E2E Results (live browser verification against `pnpm dev:full`)

| Scenario | Priority | Result | Notes |
|----------|----------|--------|-------|
| `/live` typed empty state when BE 405s on `/streams/` | Critical | PASS | Heading "Live discovery coming soon" + cross-repo issue link rendered. Single (gated) 405 in console, no flood. |
| `/studio` unauthenticated guard | High | PASS | "Sign in to access the studio" + HIG-compliant copy when no session. |
| `/login` autocomplete attrs | Medium | PASS | `login-email` → `username`, `login-pass` → `current-password` (verified via `document.querySelectorAll('input')`). |
| Backend route fixes in vidra-core | High | PASS (compile) | `go build ./internal/httpapi/` clean. Live activation requires Docker rebuild — running container still has old binary, FE typed-error gating handles current 405/400 correctly. |
| `pnpm test:run` | Critical | PASS | 1697/1697 vitest tests passing (including 4 new tests for history-delete UI + AlertDialog confirmation). |
| `pnpm typecheck` | Critical | PASS | tsc --noEmit zero errors. |
| `pnpm lint` | High | PASS | Only pre-existing integration-test warnings; no warnings in changed files. |
| `pnpm build` | Critical | PASS | Production build clean. |
| `pnpm i18n:check` | High | PASS | All 13 locales have 945 keys identical to en.json (Studio.* keys added). |
| Reviewer findings | Critical | FIXED | All 6 should_fix + 2 of 3 suggestions addressed (HIG AlertDialog for both delete flows, narrowed gating in videos/wallet, useApi caching in StudioPage, history delete UI tests, suggestion #9 — provisional issue URLs — deferred as documented TODO since reviewer confirmed slugs are stable identifiers in the source comment). |

## Apple HIG Alignment

- **Clarity:** Destructive actions (admin user delete, bulk delete, per-item history delete) all use Radix AlertDialog with red action button — replaces `window.confirm` per reviewer's HIG gap. Backdrop blur + appropriate dialog hierarchy.
- **Deference:** Typed `BackendNotImplementedError` empty states (live-page, library-page, wallet-page) replace error toasts with subdued explanatory copy + cross-repo issue links. Content-first.
- **Accessibility:** `aria-label` on icon-only buttons (RTMP/stream-key copy, ban/unban/delete row actions, history delete). Login `autocomplete` attrs (`username`, `current-password`, `new-password`, `one-time-code`) for password manager interop. Studio quick-link tiles use `min-h-[44px]` (HIG 44×44 touch target).
- **Touch targets:** Studio dashboard quick-link cards verified `min-h-[44px]`; admin row action buttons use `p-1.5` padding which exceeds HIG min for hover-revealed controls.
- **Reduced-motion:** No new animations introduced; AlertDialog uses Radix default `data-[state=open]:animate-in` which respects `prefers-reduced-motion` via Radix's built-in handling.

## PeerTube Parity Check

- **Phase 4 (Live streaming):** Direct ports of PeerTube `client/src/app/+videos/+video-watch/+video-live` patterns — single Go Live CTA in header, separate RTMP URL/Stream Key fields with copy buttons (Task 14 mirrors PeerTube's "Live information" panel), End Live button (Task 15), `/live` discovery list (Task 16, BE list handler now matches PeerTube's `getActiveLiveVideos`).
- **Phase 6 (Admin):** Mirrors PeerTube `client/src/app/+admin/users` — list/search, ban/unban, role change, hard delete with destructive confirm dialog (Task 24, now Apple HIG via Radix AlertDialog vs PeerTube's PrimeNG ConfirmDialog).
- **Phase 9 polish:** `/channel/{id}/edit` lands directly on form (matches PeerTube's `+my-account/+my-video-channels/[id]/update` route), login autocomplete attrs match PeerTube's password-manager interop.
- **Vidra-specific (no PeerTube parity):** Studio dashboard (Task 17), Wallet (Task 18), Inner Circle (Task 20), BTCPay invoice creation (Task 19) — all designed from scratch following Apple HIG principles per project CLAUDE.md.

## Vidra-Specific Backend Extensions Coverage

- **Live Streaming** (Tasks 13–16): channel_id resolution, real RTMP URL/key display, End Live with saveRecording, `/live` typed empty state + BE list handler.
- **BTCPay / Bitcoin payments** (Task 19): typed-error gating + BE typed-503 for `ErrBTCPayUnavailable`.
- **Wallet** (Task 18): `NEXT_PUBLIC_WALLET_ENABLED` flag gating, 404/5xx → typed unavailable state.
- **Inner Circle** (Task 20): `NEXT_PUBLIC_INNER_CIRCLE_ENABLED` flag gating, sidebar conditional, service-layer `BackendNotImplementedError(INNER_CIRCLE_DISABLED)`.
- **Video Studio** (Task 31): 404/405 → typed error + `studioService.isAvailable()` probe; video-edit-page hides Studio tab when unavailable.
- **Advanced Analytics** (Task 32): 404/405 → empty data; pages render empty state instead of console flood.
- **Real-time Stream Chat:** Indirectly affected — Task 16's `/live` discovery surfaces the chat experience post BE list handler.
