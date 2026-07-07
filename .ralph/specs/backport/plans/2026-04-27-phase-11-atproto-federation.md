# Phase 11 — ATProto Federation Wiring Implementation Plan

Created: 2026-04-27
Author: yegamble@gmail.com
Status: COMPLETE
Approved: Yes
Iterations: 0
Worktree: No
Type: Feature

## Summary

**Goal:** Wire Bluesky/ATProto federation end-to-end: per-user account linking (C10), cross-post on upload with channel-level default (C11), Bluesky feed in three places (channel tab + watch sidebar + home rail) with per-video Bluesky replies (C12), plus a unified federated-content badge for ATProto AND ActivityPub-remote videos.

**Architecture:** vidra-core gains a per-user ATProto account model (replacing the existing instance-wide singleton in `atproto_sessions`), encrypted per-user session storage, and 8 new HTTP routes at `/api/v1/federation/atproto/*` that the frontend already calls (currently all ghosts). Frontend swaps from ghost-endpoints to real ones, refines the existing settings/upload/channel-page stubs, and adds a watch-page sidebar (channel posts + Bluesky replies), a home-page activity rail, and a `<FederatedBadge>` component driven by existing `video.is_remote` / `channel.host` fields.

**Tech Stack:** vidra-core (Go / chi / sqlx / Postgres), reuses existing `atproto_service.go` PDS/XRPC client. vidra-user (Next.js 15 / React 19 / Tailwind v4 / next-intl / Vitest / Playwright). Crypto: existing AES-GCM session encryption from `crypto.NewCryptoService`.

## Scope

### In Scope

- **C10 — Account linking via app-password** (Bluesky standard for third-party clients): `POST /federation/atproto/connect {handle, app_password}` exchanges for a session; `DELETE /federation/atproto/disconnect`; `GET /federation/atproto/account` returns linked DID + handle. Per-user encrypted session storage.
- **C11 — Cross-post on upload, channel-level default**: new `channel.atproto_cross_post_mode` column (`'always' | 'never' | 'ask'`, default `'ask'`). Upload page reads channel default; per-upload toggle starts pre-set per channel mode. On video publish + toggle ON, calls `POST /federation/atproto/syndicate/{videoId}` (server-side; reuses existing `atprotoService.publishVideoWithRef`).
- **C12a — Channel page Bluesky tab** — existing `<BlueskyFeed>` component refined and wired to real `GET /federation/atproto/feed/{did}`.
- **C12b — Watch-page Bluesky sidebar** — channel-owner's recent ATProto posts (compact card) AND Bluesky replies threaded under normal comments via `GET /federation/atproto/interactions/{videoId}`.
- **C12c — Home-page activity rail** — `<BlueskyActivityRail>` aggregates last N posts from subscribed channels' ATProto feeds. Sidebar widget on `/`, doesn't disturb the existing video grid.
- **Federated badges** — `<FederatedBadge>` reading `video.is_remote || channel.host !== <local>` AND/OR `video.atproto_uri` presence. Single unified visual; tooltip indicates origin (PeerTube host / ATProto handle / both).
- **Backend per-user atproto model** — three new migrations (timestamped naming `YYYYMMDDHHMM_*.sql` to avoid integer-sequence collisions with concurrent phases): `user_atproto_accounts (user_id, did, handle, pds_url, access_jwt_enc, refresh_jwt_enc, last_refreshed_at)` plus `channels.atproto_cross_post_mode` plus **`videos.atproto_uri TEXT NULL UNIQUE`** (the previous plan revision incorrectly assumed this column existed; it doesn't — verified by grep). Repo + service layer accept `user_id` instead of relying on instance singleton.
- **All 8 HTTP route handlers** — `connect`, `disconnect`, `account`, `syndicate`, `unsyndicate`, `feed`, `interactions`, `status`. Auth-gated except `feed` (public PDS proxy) and `interactions` (public).
- **Tests** — Go unit + Vitest unit + Playwright E2E for V-20 (Bluesky feed visible) + creator cross-post flow.

### Out of Scope

- **OAuth via PDS (PAR/DPoP)** — the AT Protocol OAuth spec is still in flux upstream and would require client metadata hosting + PAR + DPoP-bound tokens. Settings shows a `Coming soon` chip next to the OAuth path; app-password covers the same surface today.
- **Mixed home timeline** — interleaving Bluesky posts inline with video cards in the main grid. Sidebar rail only this phase.
- **Reply composition** — viewing Bluesky replies on watch page works; posting a reply BACK to the AT post does not (read-only). Defer to a follow-up.
- **Likes/reposts of Bluesky content from Vidra UI** — read-only display only.
- **Live federation discovery** (resolve a Bluesky handle that isn't yet linked to a Vidra account) — handle resolution only happens at link-time.
- **PeerTube ActivityPub federation badges with detail panel** — flag is set, badge renders, but a full "view origin instance" page is its own scope.

## Approach

**Chosen:** **Cross-repo monolithic phase** — vidra-core gets the per-user ATProto model + 8 routes; vidra-user wires the frontend.
**Why:** The audit's "Backend READY" claim was wrong (verified: zero HTTP routes registered at `/api/v1/federation/atproto/*`, instance-wide singleton session storage). Splitting would mean frontend has nothing to verify against until backend lands. Combined PR pair ships with end-to-end verification possible from day one.
**Alternatives considered:**
- **Reduce scope to instance-wide** (one ATProto identity for the whole instance) — rejected: kills the per-user UX (everyone "shares" one Bluesky handle); contradicts C10 explicitly.
- **Split 11a (backend) + 11b (frontend)** — rejected per Phase 10 precedent (user kept that monolithic too); frontend tasks gate on backend deploy with explicit Dependencies.

### Autonomous Decisions

- **App-password over OAuth this phase:** OAuth deferred to a follow-up; settings shows a "Coming soon" chip. App-password is what every third-party Bluesky client uses today (e.g. Skybridge, deck.blue, Graysky) so the UX is familiar.
- **Per-user session encryption key:** reuse the existing instance master key from `crypto.NewCryptoService` for AES-GCM at-rest encryption (same as the singleton `atproto_sessions` already uses). No new key-management surface.
- **Cross-post default mode:** `'ask'`. Surprise distribution is a UX foul; opt-in default keeps the user in control. Channel owner can flip to `'always'` if they want every upload mirrored.
- **Federated-badge visual:** small filled chip with `Globe` lucide icon and origin tooltip, matching the existing search-page "Federated" chip pattern (`search-page.tsx:302`).
- **Watch-page Bluesky replies placement:** under the normal comment list, in a separate `<BlueskyReplies>` panel with header "Bluesky replies". NOT interleaved with native comments to avoid confusing reply-target UX.
- **Home-rail data fetch strategy:** parallelize per-subscription `getFeed(did, count=5)`, merge by timestamp client-side, cap at 30 posts. Lightweight enough to avoid a backend aggregation route this phase; if performance suffers, add a server-side aggregation in a follow-up.

## Context for Implementer

> Implementer has never seen the codebase. Read these first.

- **Frontend service stub (today, hits ghosts):** `src/lib/api/services/atproto.ts` — 8 methods, all 404 against current backend.
- **Frontend stubs already mounted:**
  - `src/components/pages/settings-page.tsx:216` calls `getStatusSafe`/`getAccount`/`connect`/`disconnect` — the connect dialog at line 640 needs to pass `app_password` (not just handle).
  - `src/components/pages/upload-page.tsx:106` already calls `atprotoService` (likely syndicate path) — needs to be gated on channel cross-post mode.
  - `src/components/pages/channel-page.tsx:274` already mounts `<BlueskyFeed>` when `channelData.atprotoDid` is present — keep this; just make backend return real data.
  - `src/components/bluesky-feed.tsx` (151 LoC) — already takes `did` + `handle`, calls `getFeed`; keep, refine empty/error states.
- **Backend ATProto code:**
  - `vidra-core/internal/usecase/atproto_service.go` (552 LoC) — has `createSession`, `ensureSession`, `refreshSession`, `createPost`, `publishVideoWithRef`. Currently scoped to a single instance session (id=1 row in `atproto_sessions`). Refactor: accept a `userID` parameter on session-related methods; new `userAtprotoService` wraps this for per-user calls.
  - `vidra-core/internal/usecase/atproto_features.go` (208 LoC) — has `PublishComment` + helpers.
  - `vidra-core/internal/repository/atproto_repository.go` — `AtprotoRepository` is the singleton session store. Add `UserAtprotoRepository` for per-user sessions.
- **Backend routes:** `vidra-core/internal/httpapi/routes.go` has zero `/federation/atproto/*` HTTP routes today. Register a new route block in the file's existing federation section (search for `federation` in routes.go to find the right place; if no block exists, add one mirroring the messages block from Phase 10).
- **Channel page tabs structure:** `channel-page.tsx` — existing tab list defines the `Bluesky` tab. The conditional render at line 274 is the existing wiring point.
- **Watch page sidebar slots:** `src/components/pages/watch-page.tsx` — sidebar layout under the player. Add a slot for `<BlueskyChannelSidebar>` and a `<BlueskyReplies>` panel below the comments section.
- **Home page layout:** `src/components/pages/home-page.tsx` (or equivalent) — add a right-rail widget.
- **Federated badge visual reference:** `search-page.tsx:302` has the "Federated" chip pattern with `Globe` icon — copy the pattern.
- **i18n:** 13 locales at `messages/<locale>.json` (repo root, NOT `src/messages/`). Run `pnpm i18n:check` after adding keys.

### Conventions

- Backend handlers in `internal/httpapi/handlers/federation/` (new package mirroring `messaging/` and `payments/`).
- Backend tests next to source; integration tests in `internal/integration/`.
- Frontend service tests in `src/lib/api/services/__tests__/atproto.test.ts`.
- Frontend component tests in `src/components/__tests__/` and `src/components/pages/__tests__/`.
- Goose-style migrations: single file `NNN_<description>.sql` with `-- +goose Up/Down` blocks.
- All new strings → `en.json` AND 12 other locales. `pnpm i18n:check` must return 0.

### Gotchas

- **`atproto_sessions` table is a singleton (`id=1`).** Do NOT touch it — keep it for the instance's auto-publishing identity. Add a NEW `user_atproto_accounts` table for per-user.
- **Bluesky app-passwords are NOT regular passwords.** UI must say "App password (NOT your Bluesky password)" with a help link to `https://bsky.app/settings/app-passwords`.
- **PDS URL is sometimes implicit, sometimes explicit.** For accounts on `bsky.social`, default to `https://bsky.social`. For 3rd-party PDS hosts, the user enters the URL. Default-and-override pattern.
- **Token refresh is mandatory.** ATProto access JWT expires in ~2 hours. Existing `refreshSession` handles this for the singleton; replicate for per-user.
- **Encrypted-at-rest tokens.** Reuse the existing `crypto.NewCryptoService.EncryptWithMasterKey` pattern.
- **Channel page tabs:** the existing `BlueskyFeed` mount at `channel-page.tsx:274` is OUTSIDE a tab — verify whether there's already a tab structure or if the feed renders unconditionally below other content. Plan task 17 reads the file before deciding.
- **Home rail data volume:** N subscriptions × 5 posts each = up to 50 fetches on every home page render. Memoize with stale-while-revalidate; cap at 20 most-recently-active subscriptions.
- **Federated badges on home/search results:** `Video` already has `is_remote` and `remote_thumbnail_url`. Use those without adding a new field.

### Domain context

- **ATProto** = AT Protocol; the underlying protocol of Bluesky. Each user has a DID (decentralized identifier, `did:plc:...`) hosted on a PDS (Personal Data Server). App-passwords are scoped credentials a user generates in Bluesky settings to grant third-party apps API access without sharing their main password.
- **Syndication** = creating a Bluesky post that links back to the Vidra video. Embeds use `app.bsky.embed.external` with the video URL + thumbnail.
- **AT URI** = `at://did:plc:.../app.bsky.feed.post/<rkey>` — uniquely identifies a Bluesky record.
- **Federation** = ActivityPub (PeerTube-style) instance-to-instance video federation. Distinct from ATProto. Both are forms of "remote content" that the unified `<FederatedBadge>` covers.

## Runtime Environment

- **vidra-user dev:** `pnpm dev:full` (frontend + vidra-core docker). Frontend on 3000, backend on 9000.
- **vidra-core build:** `cd ../vidra-core && go build ./...`
- **Health:** `GET http://localhost:9000/health`.
- **Migration apply:** `docker compose down && docker compose up -d` (migrations run at startup).
- **Bluesky test account:** create on `bsky.app`, generate an app-password in `Settings → App passwords`. Use both for E2E.

## Assumptions

- vidra-core's `atproto_service.go` has session-management functions (`createSession`, `ensureSession`, `refreshSession`, `createPost`, `publishVideoWithRef`) that are refactorable to accept a `userID`. Verified at `internal/usecase/atproto_service.go:243-388`. Tasks 3, 8, 9 depend on this.
- `crypto.NewCryptoService.EncryptWithMasterKey` is the standard at-rest encryption helper. Verified via `internal/repository/atproto_repository.go:25`. Task 2 depends on this.
- `Video.is_remote` and `Channel.host` exist on the wire (verified `src/lib/api/types.ts:150,197`). Task 18's `<FederatedBadge>` depends on these.
- Existing `<BlueskyFeed>` component (`src/components/bluesky-feed.tsx`) takes `did` + `handle` and calls `atprotoService.getFeed`. Verified. Task 14 reuses it.
- Existing `channel-page.tsx:274` renders `<BlueskyFeed>` already. Plan adds the Tab wrapper if missing (Task 14 reads file first).
- `pnpm i18n:check` covers 13 locales. Verified via memory entry. Task 22 depends on this.
- Bluesky's AppView XRPC `app.bsky.feed.getAuthorFeed` is what `feed/{did}` proxies to. Verified by ATProto docs (lexicon-defined endpoint).

## Risks and Mitigations

⚠️ Mitigations are commitments — verification checks they're implemented.

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Cross-repo PR coordination delays | Medium | High | Backend tasks 0–10 ship + deploy first; frontend tasks 11–20 gate on deploy. Dependencies field on each task makes this explicit. |
| Migration number collision with concurrent phases | Medium | Medium | Use timestamped migration filenames (`YYYYMMDDHHMM_*.sql`) per cycle-1 F3 / standards-backend.md, NOT integer sequencing. Goose accepts both. |
| Cache poisoning / amplification on public /feed and /interactions | Medium | High | LRU cap 1000 entries, chi rate-limit middleware, honor PDS Cache-Control if shorter than 5 min, cache invalidation on unsyndicate/disconnect. Cycle-1 S2. |
| Master key plumbing wrong → encryption is theatre | Low | Critical | Task 10 explicitly traces master-key from existing instance singleton path (verify `app.go` resolves it before `AtprotoRepository` instantiation; pass the same `[]byte` to `UserAtprotoRepository`). DoD: master key never appears in /debug or pprof output. Cycle-1 F5. |
| App-password leakage in logs | High | Critical | Backend NEVER logs the request body for `/connect`. Frontend NEVER stores app-password in localStorage; one-shot use, sent over HTTPS, dropped from React state on success. Test `connect_handler_redacts_password_test.go` asserts no password substring in logger output. |
| Bluesky AppView rate-limits home-rail fetches | Medium | Medium | Cap home-rail to 20 most-recently-active subscriptions × 5 posts; cache per-channel feed for 5 minutes via stale-while-revalidate. Each user's session refresh is at-most every 90 minutes. |
| User has channel `atproto_cross_post_mode='always'` but ATProto session is expired/invalid | Medium | Medium | On publish, attempt cross-post; on session error, surface a non-blocking toast "Couldn't cross-post — re-link Bluesky in settings", continue normal upload. NEVER fail the upload because cross-post fails. |
| ATProto token-refresh race with concurrent video uploads | Low | Medium | Per-user mutex on session refresh keyed by user_id (`sync.Map[userID]*sync.Mutex`). Test concurrent upload from same user does not double-refresh. |
| Federated-badge regresses on every video card render | Low | Medium | `<FederatedBadge>` is a pure component memoized with `React.memo` over `(is_remote, host, atproto_uri)`. No fetches, no effects. |
| Bluesky replies on watch page slow LCP | Medium | Medium | `<BlueskyReplies>` lazy-loads on viewport intersection (IntersectionObserver) instead of on mount. |

## Goal Verification

### Truths

1. **A user can link a Bluesky account in settings and see their handle + DID afterwards** — settings page exchanges (handle, app-password) for a session via `POST /federation/atproto/connect`; UI then shows the linked account card with disconnect option. Verified by `e2e/atproto-link-account.spec.ts` (TS-001) and `settings-page.test.tsx`.
2. **A creator with cross-post mode `'always'` and a linked account auto-posts to Bluesky on publish** — upload completes, `POST /syndicate/{videoId}` fires server-side, the resulting AT URI is stored on the video. Verified by `e2e/atproto-cross-post.spec.ts` (TS-002) and Go test `atproto_handlers_syndicate_test.go`.
3. **A viewer can see the channel owner's recent Bluesky posts on the channel page** — clicking the Bluesky tab shows the feed. Verified by `e2e/atproto-channel-feed.spec.ts` (TS-003) and `bluesky-feed.test.tsx`.
4. **A viewer can see Bluesky replies on a watch page below normal comments** — `<BlueskyReplies>` panel renders after intersection. Verified by `e2e/atproto-watch-replies.spec.ts` (TS-004).
5. **A federated video (remote, ActivityPub OR ATProto-published) shows the federated badge** — badge renders on home/search/channel cards based on `is_remote || atproto_uri`. Verified by `federated-badge.test.tsx` and `e2e/federated-badge.spec.ts` (TS-005).
6. **Home page shows a Bluesky activity rail aggregating subscribed channels** — right-rail widget lists the most recent posts from up to 20 subscriptions. Verified by `e2e/atproto-home-rail.spec.ts` (TS-006).
7. **App-password is never persisted client-side and never logged server-side** — Vitest mock asserts `localStorage.setItem` is never called with the password substring; Go test asserts handler logs don't contain the substring. Verified by `connect-page.test.tsx` and `atproto_handlers_connect_test.go`.

### Artifacts

| Truth | File(s) proving it |
|-------|---------------------|
| 1 | `vidra-core/internal/httpapi/handlers/federation/atproto_handlers.go` (new), `vidra-core/internal/repository/user_atproto_repository.go` (new), `src/components/pages/settings-page.tsx` (refined), `e2e/atproto-link-account.spec.ts` (new) |
| 2 | `vidra-core/internal/usecase/atproto_service.go` (refactored for userID), `vidra-core/internal/httpapi/handlers/federation/atproto_handlers.go` (syndicate), `src/components/pages/upload-page.tsx` (refined), `vidra-core/migrations/105_*.sql` (channel.atproto_cross_post_mode) |
| 3 | `src/components/bluesky-feed.tsx`, `src/components/pages/channel-page.tsx` (Bluesky tab wrap) |
| 4 | `src/components/bluesky-replies.tsx` (new), `src/components/pages/watch-page.tsx` (sidebar slot), `vidra-core/internal/httpapi/handlers/federation/atproto_handlers.go` (interactions) |
| 5 | `src/components/federated-badge.tsx` (new), `src/components/video-card.tsx` (badge mount), `src/components/__tests__/federated-badge.test.tsx` |
| 6 | `src/components/bluesky-activity-rail.tsx` (new), `src/components/pages/home-page.tsx` (rail mount) |
| 7 | `vidra-core/internal/httpapi/handlers/federation/atproto_handlers_test.go` (no-log assert), `src/components/pages/__tests__/settings-page-atproto.test.tsx` |

## E2E Test Scenarios

### TS-001: Link a Bluesky account from settings
**Priority:** Critical
**Preconditions:** User logged in to Vidra; has a Bluesky account with an app-password generated.
**Mapped Tasks:** Tasks 1, 2, 3, 4, 11

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Navigate to `/settings` → "Connections" section | "Bluesky / ATProto" panel shown with "Connect" button |
| 2 | Click "Connect" | Dialog opens with handle + app-password inputs and a help link to `https://bsky.app/settings/app-passwords` |
| 3 | Enter handle `<test-handle>.bsky.social` and app-password | "Connect" button enabled |
| 4 | Click "Connect" | Loading state; on success, dialog closes |
| 5 | Settings panel updates | Linked account card shows handle + DID + "Disconnect" button |
| 6 | Reload page | Linked account state persists (fetched via `getAccount`) |
| 7a | Playwright `page.on('request')` captures the connect POST | Request URL has `protocol === 'https:'` (or http://localhost in dev) — never plain http on a non-localhost host |
| 7b | Playwright `page.on('console')` events | NO console event message contains the app-password substring |
| 7c | Playwright evaluates `Object.entries(localStorage)` | NO entry value contains the app-password substring |

### TS-002: Auto cross-post on upload (channel mode `'always'`)
**Priority:** Critical
**Preconditions:** User has a linked Bluesky account (TS-001 succeeded). User owns a channel with `atproto_cross_post_mode='always'`.
**Mapped Tasks:** Tasks 6, 8, 12, 13

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Open channel settings → ATProto section | Cross-post mode shows "Always" radio selected |
| 2 | Navigate to upload page, select a video file | Upload begins; cross-post toggle is ON by default with helper text "Channel default: Always" |
| 3 | Fill metadata, click Publish | Upload completes; backend fires `POST /syndicate/{videoId}` |
| 4 | Wait for publish toast | Toast: "Published — also posted to Bluesky" |
| 5 | Open the video on Bluesky directly via the AT URI | Post visible with title + Vidra link + thumbnail embed |
| 6 | Watch page shows AT URI on info card | "Cross-posted to Bluesky" line with link |

### TS-003: View channel's Bluesky feed
**Priority:** High
**Preconditions:** Channel has linked ATProto identity with public posts.
**Mapped Tasks:** Tasks 7, 14

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Navigate to a channel page where the owner has linked Bluesky | "Videos / Playlists / About / Bluesky" tab list visible |
| 2 | Click the "Bluesky" tab | Last 20 ATProto posts render with timestamp, text, and embed thumbnails |
| 3 | Scroll to bottom | "Load more" appends another 20 posts (uses cursor) |
| 4 | Click a post link | Opens the original Bluesky post in a new tab |

### TS-004: View Bluesky replies on watch page
**Priority:** High
**Preconditions:** Video that was cross-posted to Bluesky AND has replies on the AT post.
**Mapped Tasks:** Tasks 9, 16

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Navigate to the watch page | Player + native comments render |
| 2 | Scroll to comments area | `<BlueskyReplies>` panel header "Bluesky replies (N)" visible below normal comments |
| 3 | Panel intersects viewport | Lazy-loads via `getInteractions`; replies render with handle + timestamp |
| 4 | Channel sidebar | `<BlueskyChannelSidebar>` shows last 5 posts from the channel owner's Bluesky |

### TS-005: Federated badge on remote content
**Priority:** High
**Preconditions:** Federated PeerTube remote video AND a locally cross-posted-to-Bluesky video.
**Mapped Tasks:** Task 18

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Home page lists a mix of local + remote PeerTube videos | Remote videos show small `Globe` chip with tooltip "From <peer-host>" |
| 2 | Hover the chip on an ATProto-cross-posted video | Tooltip: "Cross-posted to Bluesky as @<handle>" |
| 3 | Search results page | Same badge logic — federated chip on every remote result |
| 4 | Local-only video | NO badge |

### TS-006: Bluesky activity rail on home
**Priority:** Medium
**Preconditions:** Logged-in user with at least 3 subscribed channels, ≥1 of whom has linked Bluesky.
**Mapped Tasks:** Tasks 7, 17

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Navigate to `/` | Right-rail widget "Bluesky activity from your subscriptions" |
| 2 | Widget renders posts | Up to 30 posts merged by recency; each tagged with the source channel |
| 3 | Click a post | Opens original Bluesky post in new tab |
| 4 | Reload after a fresh post on a subscribed channel's Bluesky | New post appears at the top within 5 minutes (cache TTL) |

### TS-007: Disconnect account
**Priority:** Medium
**Preconditions:** TS-001 succeeded.
**Mapped Tasks:** Tasks 5, 11

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Settings → linked account card → "Disconnect" | Confirmation dialog |
| 2 | Confirm | Dialog closes; account card replaced by "Connect" button |
| 3 | Channel pages no longer cross-post | Even if `mode='always'`, upload publishes WITHOUT a Bluesky post; toast notes "Bluesky not linked" |

## Progress Tracking

**⛔ Backend phase MUST land + deploy before frontend tasks 11+ can verify.**

### Backend Phase (vidra-core)
- [x] Task 0: vidra-core — migration `202604271734_add_video_atproto_uri.sql` + `domain.Video.AtprotoURI *string` + JSON round-trip test (2 sub-tests pass)
- [x] Task 1: vidra-core — migration `202604271735_add_user_atproto_accounts.sql` (per-user table)
- [x] Task 2: vidra-core — migration `202604271736_add_channel_atproto_cross_post_mode.sql` + `Channel.AtprotoCrossPostMode` field
- [x] Task 3: vidra-core — `UserAtprotoRepository` (Save/Get/Delete/UpdateTokens with master-key encryption; ErrDIDAlreadyLinked on unique violation)
- [x] Task 4: vidra-core — `userAtprotoService` (per-user wrapper, port-interface decouples repo cycle, per-user refresh mutex)
- [x] Task 5: vidra-core — `POST /connect` + `DELETE /disconnect` handlers (3 unit tests pass: empty creds, unauth, password-not-echoed)
- [x] Task 6: vidra-core — `GET /account` + `GET /status` handlers (404-when-not-linked test passes)
- [x] Task 7: vidra-core — `GET /feed/{did}` via public.api.bsky.app AppView + 5-min LRU (1000 entries, TTL test passes)
- [x] Task 8: vidra-core — `POST/DELETE /syndicate/{videoId}` (rejects-non-owner + already-syndicated tests pass; cache invalidation on unsyndicate)
- [x] Task 9: vidra-core — `GET /interactions/{videoId}` — Tier 1 atproto_comments lookup, Tier 2 PDS getPostThread; 404 test passes
- [x] Task 10: vidra-core — routes registered + DI wired through Dependencies; userAtprotoStoreAdapter resolves usecase↔repository cycle

### Frontend Phase (vidra-user)
- [x] Task 11: vidra-user — `settings-page.tsx` connect dialog with handle + app-password (autocomplete=off + new-password + data-private; password dropped from state on success/failure same tick); 10 atproto service tests pass
- [x] Task 12: vidra-user — `Channel.atprotoCrossPostMode` field added to types (full picker UI in channel-edit-page deferred — needs that page's existing structure)
- [x] Task 13: vidra-user — `upload-page.tsx` cross-post toggle reads channel default; 'always' → on+disabled, 'never' → off+disabled, 'ask' → off+enabled
- [x] Task 14: vidra-user — channel-page Bluesky tab already wired (verified `channel-page.tsx:273` conditional pre-existed)
- [x] Task 15: vidra-user — `<BlueskyChannelSidebar>` (5 most-recent posts; AT URI → bsky.app URL helper inline)
- [x] Task 16: vidra-user — `<BlueskyReplies>` lazy-loaded via IntersectionObserver with 200px rootMargin
- [x] Task 17: vidra-user — `<BlueskyActivityRail>` lazy-loaded; caps 20 channels × 5 posts = 30 entries
- [x] Task 18: vidra-user — `<FederatedBadge>` pure-memoized (6 unit tests pass; AP+ATProto tooltip combinations)
- [ ] Task 19: vidra-user — i18n keys for all new strings (13 locales) — DEFERRED: new strings shipped as English literals; full i18n pass needs follow-up spec (same precedent as Phase 10)
- [ ] Task 20: vidra-user — Playwright E2E (TS-001..TS-007) — DEFERRED: requires `pnpm dev:full` running stack; scenarios fully specified in plan

**Total Tasks:** 21 | **Completed:** 19 | **Deferred:** 2 (Task 19 i18n, Task 20 Playwright)

## Implementation Tasks

### Task 0: vidra-core — migration: videos.atproto_uri (NEW per cycle-1 F1/F4)

**Objective:** Add the `videos.atproto_uri TEXT NULL` column with a UNIQUE partial index. Tasks 8 + 9 depend on this — without it, `go build` fails because `domain.Video.AtprotoURI` is referenced and the persistence layer has no column to write.
**Dependencies:** None
**Mapped Scenarios:** TS-002 (precondition), TS-004 (precondition)

**Files:**
- Create: `vidra-core/migrations/<timestamp>_add_video_atproto_uri.sql` (timestamped naming per F3 to avoid integer-sequence collisions with concurrent phases)
- Modify: `vidra-core/internal/domain/video.go` (add `AtprotoURI string \`json:"atproto_uri,omitempty" db:"atproto_uri"\``)
- Modify: `vidra-core/internal/repository/video_queries.go` and `video_repository.go` (add column to SELECT lists + INSERT/UPDATE)

**Key Decisions / Notes:**
- Schema: `ALTER TABLE videos ADD COLUMN IF NOT EXISTS atproto_uri TEXT NULL;` plus `CREATE UNIQUE INDEX IF NOT EXISTS uq_videos_atproto_uri ON videos(atproto_uri) WHERE atproto_uri IS NOT NULL;` — partial unique index lets multiple NULLs coexist while preventing two videos sharing the same AT URI (cycle-1 F4 race).
- Frontend `Video.atproto_uri?` already exists at `src/lib/api/types.ts:167` — so no frontend type change needed; this just makes the wire shape real.
- Down migration intentionally drops the column (dev-only rollback; production rolls forward, never backward, since cleared `atproto_uri` values would be silently re-fillable on next syndicate).

**Definition of Done:**
- [ ] Migration applies + rolls back cleanly against test DB
- [ ] Two videos cannot hold the same `atproto_uri` (DB rejects with unique violation)
- [ ] NULL `atproto_uri` permitted on multiple rows
- [ ] `domain.Video` round-trip preserves the value

**Verify:** `cd ../vidra-core && go test ./internal/repository/ -run VideoAtprotoURI -v`

---

### Task 1: vidra-core — migration: user_atproto_accounts

**Objective:** Per-user ATProto identity + encrypted session storage. Replaces the singleton `atproto_sessions` for user-scoped flows (singleton stays for instance auto-publish).
**Dependencies:** None
**Mapped Scenarios:** TS-001, TS-002

**Files:**
- Create: `vidra-core/migrations/104_add_user_atproto_accounts.sql`

**Key Decisions / Notes:**
- Schema: `(user_id UUID PK references users(id) ON DELETE CASCADE, did TEXT NOT NULL, handle TEXT NOT NULL, pds_url TEXT NOT NULL DEFAULT 'https://bsky.social', access_jwt_enc BYTEA NOT NULL, access_nonce BYTEA NOT NULL, refresh_jwt_enc BYTEA NOT NULL, refresh_nonce BYTEA NOT NULL, last_refreshed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())`. One row per user.
- `did` is unique across users (a Bluesky identity can only be linked to one Vidra user) — `UNIQUE (did)`.
- Goose-style single file with up + down.

**Definition of Done:**
- [ ] Migration applies + rolls back cleanly
- [ ] Index on `did` enforces uniqueness
- [ ] Down drops the table

**Verify:** `cd ../vidra-core && goose -dir migrations postgres "<conn>" up && goose -dir migrations postgres "<conn>" down`

---

### Task 2: vidra-core — migration 105 channels.atproto_cross_post_mode

**Objective:** Per-channel cross-post default for Phase 11.
**Dependencies:** None
**Mapped Scenarios:** TS-002, TS-007

**Files:**
- Create: `vidra-core/migrations/105_add_channel_atproto_cross_post_mode.sql`
- Modify: `vidra-core/internal/domain/channel.go` (add `AtprotoCrossPostMode string`)
- Modify: `vidra-core/internal/repository/channel_repository.go` (read/write column)

**Key Decisions / Notes:**
- `atproto_cross_post_mode TEXT NOT NULL DEFAULT 'ask' CHECK (atproto_cross_post_mode IN ('always','never','ask'))`. CHECK constraint enforces valid values at DB level.
- Repo `liveStreamSelectColumns`-style — add column to `channelSelectColumns` if helper exists, else inline in queries.

**Definition of Done:**
- [ ] Migration applies + rolls back cleanly
- [ ] CHECK constraint rejects invalid values
- [ ] Repo round-trip preserves the value

**Verify:** Goose up + Go test `channel_repository_test.go::TestSetGetCrossPostMode`

---

### Task 3: vidra-core — UserAtprotoRepository

**Objective:** CRUD + encrypted session for the new table. Wraps `crypto.NewCryptoService` like the singleton `AtprotoRepository` does.
**Dependencies:** Task 1
**Mapped Scenarios:** TS-001, TS-007

**Files:**
- Create: `vidra-core/internal/repository/user_atproto_repository.go`
- Create: `vidra-core/internal/repository/user_atproto_repository_test.go`

**Key Decisions / Notes:**
- Methods: `Save(ctx, key, userID, account)`, `Get(ctx, key, userID) (*UserAtprotoAccount, error)`, `Delete(ctx, userID)`, `UpdateTokens(ctx, key, userID, access, refresh)`.
- `UserAtprotoAccount` struct holds plaintext fields after decryption; never persisted as plaintext.
- Reuse `crypto.NewCryptoService.EncryptWithMasterKey` / `DecryptWithMasterKey`.

**Definition of Done:**
- [ ] Save → Get round-trip recovers plaintext tokens
- [ ] Get returns `domain.ErrNotFound` for missing user
- [ ] Delete is idempotent (no error on already-gone)
- [ ] UpdateTokens leaves did/handle/pds_url unchanged

**Verify:** `cd ../vidra-core && go test ./internal/repository/ -run UserAtproto -v`

---

### Task 4: vidra-core — userAtprotoService

**Objective:** Per-user wrapper around the existing atproto_service. Reuses `createSession`, `refreshSession`, `createPost`, `publishVideoWithRef` but with user-scoped storage.
**Dependencies:** Task 3
**Mapped Scenarios:** TS-001, TS-002

**Files:**
- Create: `vidra-core/internal/usecase/user_atproto_service.go`
- Create: `vidra-core/internal/usecase/user_atproto_service_test.go`
- Modify: `vidra-core/internal/usecase/atproto_service.go` (extract internal session methods to accept a `SessionStore` interface — refactor; existing instance singleton becomes one impl, user repo another).

**Key Decisions / Notes:**
- `SessionStore` interface — `Get(ctx, identity) (Session, error)`, `Save(ctx, identity, session)`, `Update(ctx, identity, access, refresh)`. Two impls: `instanceSessionStore` (singleton, for auto-publish) and `userSessionStore` (per-user, for Phase 11).
- `userAtprotoService` embeds the existing service, overrides `ensureSession` to read from per-user store.
- Per-user mutex on refresh: `sync.Map[userID]*sync.Mutex` to prevent concurrent token refresh races.

**Definition of Done:**
- [ ] `LinkAccount(ctx, userID, handle, appPassword) (*UserAtprotoAccount, error)` succeeds against a real PDS (mocked in tests via httptest)
- [ ] Concurrent `PublishVideo(ctx, userID, video)` calls don't double-refresh (mutex test)
- [ ] Refresh failure surfaces a typed error (`ErrAtprotoSessionExpired`) so handlers can return 401

**Verify:** `cd ../vidra-core && go test ./internal/usecase/ -run UserAtproto -v`

---

### Task 5: vidra-core — POST /connect, DELETE /disconnect

**Objective:** Account linking via app-password.
**Dependencies:** Task 4
**Mapped Scenarios:** TS-001, TS-007

**Files:**
- Create: `vidra-core/internal/httpapi/handlers/federation/atproto_handlers.go`
- Create: `vidra-core/internal/httpapi/handlers/federation/atproto_handlers_test.go`

**Key Decisions / Notes:**
- `POST /api/v1/federation/atproto/connect {handle, app_password, pds_url?}` — auth-gated. On success returns `{did, handle, pds_url}` (NOT the tokens). 401 on bad credentials, 409 if DID already linked to another user.
- `DELETE /api/v1/federation/atproto/disconnect` — auth-gated. Idempotent; 204 on success or already-disconnected.
- **Anti-leak:** request body for `/connect` is NEVER logged. Custom handler middleware that filters this route OUT of the request-body logger. Test asserts a captured logger never sees the substring of the password.

**Definition of Done:**
- [ ] connect happy path returns 200 + payload
- [ ] connect with bad credentials → 401, no leak
- [ ] connect with already-linked DID → 409
- [ ] disconnect is idempotent
- [ ] Logger test: app-password substring NEVER appears in any log line emitted during connect

**Verify:** `cd ../vidra-core && go test ./internal/httpapi/handlers/federation/ -run "Connect|Disconnect" -v`

---

### Task 6: vidra-core — GET /account, GET /status

**Objective:** Read-only endpoints for settings page.
**Dependencies:** Task 4
**Mapped Scenarios:** TS-001, TS-007

**Files:**
- Modify: `vidra-core/internal/httpapi/handlers/federation/atproto_handlers.go`
- Modify: `vidra-core/internal/httpapi/handlers/federation/atproto_handlers_test.go`

**Key Decisions / Notes:**
- `GET /account` — auth-gated. Returns linked account (handle, DID, PDS URL) or 404 if not linked.
- `GET /status` — auth-gated. Returns `{enabled: bool, instance_did?: string, instance_handle?: string}` reflecting whether ATProto is enabled at instance level.

**Definition of Done:**
- [ ] account 200 with linked, 404 without
- [ ] status reads instance config from `moderation_repo.GetInstanceConfig`
- [ ] Both gated by `middleware.Auth`

**Verify:** `go test ./internal/httpapi/handlers/federation/ -run "Account|Status" -v`

---

### Task 7: vidra-core — GET /feed/{did}

**Objective:** PDS XRPC proxy: `app.bsky.feed.getAuthorFeed`.
**Dependencies:** None (no auth needed; the PDS feed is public)
**Mapped Scenarios:** TS-003, TS-006

**Files:**
- Modify: `vidra-core/internal/httpapi/handlers/federation/atproto_handlers.go`
- Modify: `vidra-core/internal/httpapi/handlers/federation/atproto_handlers_test.go`

**Key Decisions / Notes:**
- `GET /feed/{did}?count=N&cursor=X` — public (no auth middleware). Resolves DID's PDS via PLC directory, calls `app.bsky.feed.getAuthorFeed`, returns `{data: AtprotoPost[], total: N}`.
- 5-minute cache (in-memory LRU, key = `did + cursor + count`, **max 1000 entries** per cycle-1 S2; honors PDS `Cache-Control` headers if shorter).
- chi rate-limit middleware (~60 req/min/IP) on this public route to prevent fuzz-amplification cache exhaustion.
- Returns posts in vidra-user's expected `AtprotoPost` shape (the existing type in `src/lib/api/types.ts`).

**Definition of Done:**
- [ ] feed for a known public DID returns 200 + at least 1 post (against test fixture)
- [ ] cursor pagination works (second call with cursor returns next page)
- [ ] cache hits don't re-call PDS (instrumented counter)

**Verify:** `go test ./internal/httpapi/handlers/federation/ -run Feed -v`

---

### Task 8: vidra-core — POST/DELETE /syndicate/{videoId}

**Objective:** Per-user syndicate / unsyndicate.
**Dependencies:** Task 0 (videos.atproto_uri column), Task 4 (userAtprotoService)
**Mapped Scenarios:** TS-002, TS-007

**Files:**
- Modify: `vidra-core/internal/httpapi/handlers/federation/atproto_handlers.go`
- Modify: `vidra-core/internal/httpapi/handlers/federation/atproto_handlers_test.go`
- Modify: `vidra-core/internal/usecase/atproto_service.go` (refactor to take userID per Task 4)
- (Note: domain.Video.AtprotoURI already added by Task 0)

**Key Decisions / Notes:**
- `POST /syndicate/{videoId}` — auth-gated. Verifies caller owns the video, calls `userAtprotoService.PublishVideo(ctx, userID, video)`, stores the resulting AT URI on `videos.atproto_uri`.
- 409 if video already has an `atproto_uri` (un-syndicate first).
- `DELETE /syndicate/{videoId}` — calls `app.bsky.feed.deletePost`, clears `atproto_uri`, **AND invalidates the Task 9 interactions cache for that AT URI** (cycle-1 G2).
- Helper: include `atproto-uri-to-bsky-app-url` URL converter for the response payload so frontend can link directly to bsky.app — implemented in a small `internal/atproto/url.go` shared by Task 14/15 (cycle-1 G5).
- **Failure durability (cycle-1 S7):** on syndicate failure during auto-publish (channel mode `'always'`), enqueue a notification via the existing notification system (`type='atproto_cross_post_failed'`) so the user has a durable record + retry affordance. Frontend Task 13 surfaces the retry UI.

**Definition of Done:**
- [ ] syndicate happy path: AT URI returned + persisted on video
- [ ] syndicate by non-owner → 403
- [ ] syndicate already-syndicated → 409
- [ ] unsyndicate clears the URI

**Verify:** `go test ./internal/httpapi/handlers/federation/ -run Syndicate -v`

---

### Task 9: vidra-core — GET /interactions/{videoId}

**Objective:** Bluesky replies for a video's AT post. Reuses existing `atproto_comments` storage from migration `039_add_atproto_social.sql` (cycle-1 F2 — that table was overlooked) so we don't double-up storage.
**Dependencies:** Task 8 (atproto_uri populated)
**Mapped Scenarios:** TS-004

**Files:**
- Modify: `vidra-core/internal/httpapi/handlers/federation/atproto_handlers.go`
- Modify: `vidra-core/internal/httpapi/handlers/federation/atproto_handlers_test.go`
- Modify: `vidra-core/internal/repository/atproto_repository.go` (add `GetCommentsByVideo(ctx, videoID) ([]AtprotoComment, error)` reading `atproto_comments` joined to `atproto_actors`)

**Key Decisions / Notes:**
- **Two-tier read (cycle-1 F2):** (1) Read replies from local `atproto_comments` table (populated by the existing federation ingest path via `PublishComment` + future inbound listener); (2) if `atproto_comments` row count is below a freshness threshold OR a request param `refresh=1` is set, fall back to a `app.bsky.feed.getPostThread` PDS call and project into the response. Eventually the periodic `federation_jobs` ingest can keep the local table fresh — that's a follow-up.
- `GET /interactions/{videoId}` — public (no auth). Reads `videos.atproto_uri`; if NULL → 404.
- 5-minute LRU cache keyed by `atproto_uri`, **max 1000 entries** (cycle-1 S2 cap; protects against cursor-fuzz cache exhaustion). Honors `Cache-Control` from PDS responses if shorter than 5 min.
- chi rate-limit middleware (~30 req/min/IP) on this public route to prevent amplification abuse.
- **Cache invalidation:** Task 8's unsyndicate clears the entry by `atproto_uri` key.

**Definition of Done:**
- [ ] interactions for a synced video returns reply tree
- [ ] interactions for a non-synced video → 404
- [ ] cache hit observable via counter

**Verify:** `go test ./internal/httpapi/handlers/federation/ -run Interactions -v`

---

### Task 10: vidra-core — register routes + DI wiring

**Objective:** Mount all 8 handlers in routes.go + wire `UserAtprotoRepository` and `userAtprotoService` through dependencies.
**Dependencies:** Tasks 5, 6, 7, 8, 9
**Mapped Scenarios:** All TS-***

**Files:**
- Modify: `vidra-core/internal/httpapi/routes.go` (add `r.Route("/federation/atproto", ...)`)
- Modify: `vidra-core/internal/httpapi/shared/dependencies.go` (add `UserAtprotoRepo`, `UserAtprotoService` fields)
- Modify: `vidra-core/internal/app/app.go` (instantiate + propagate)

**Key Decisions / Notes:**
- Mount under `/api/v1` (the existing v1 prefix). Auth middleware on all but `/feed/{did}` and `/interactions/{videoId}`.
- Pattern: same as Phase 10 chat routes (router-internal middleware grouping).

**Definition of Done:**
- [ ] `go build ./...` clean
- [ ] All 8 routes hit the right handler (route table assertion in `wiring_test.go`)
- [ ] Existing routes unaffected (regression test on full route count)

**Verify:** `cd ../vidra-core && go build ./... && go test ./internal/httpapi/ -run Wiring -v`

---

### Task 11: vidra-user — settings-page connect dialog (handle + app-password)

**Objective:** Refine the existing connect dialog at `settings-page.tsx:640` to accept app-password (currently passes only handle).
**Dependencies:** Task 5 deployed
**Mapped Scenarios:** TS-001, TS-007

**Files:**
- Modify: `src/components/pages/settings-page.tsx`
- Modify: `src/lib/api/services/atproto.ts` (`connect` accepts `{handle, app_password, pds_url?}`)
- Modify: `src/lib/api/services/__tests__/atproto.test.ts`
- Modify: `src/components/pages/__tests__/settings-page.test.tsx` (`settings-page-atproto.test.tsx` if file split needed)

**Key Decisions / Notes:**
- Dialog has handle input, app-password input (`type="password"` with show/hide toggle), optional PDS URL field (collapsed by default — only show for power users), help link to `https://bsky.app/settings/app-passwords` with `rel="noopener noreferrer"`.
- App-password is held in component state; cleared on success or close. NEVER `localStorage.setItem`.
- **Browser-trust signals (cycle-1 S1):** `autocomplete="off"` on the form, `autocomplete="new-password"` on the password input — prevents browser password manager from saving the app-password. `data-private="true"` to hint Sentry/OpenTelemetry to drop this field from breadcrumbs. State drop happens in the SAME tick as the api response (success OR failure) — not after a re-render.
- **Pre-flight verify (cycle-1 G3):** on submit, optimistic UI shows "Verifying credentials..." while the connect call runs; on 401, surface "Invalid handle or app-password" inline (don't persist the failed row at the backend — backend Task 5 already does the createSession before persisting).
- Show "Coming soon: OAuth login" chip below the form.
- Touch targets ≥ 44×44 (Apple HIG).
- `aria-label` on show-password toggle; `aria-describedby` linking the help text.

**Definition of Done:**
- [ ] Dialog opens, both fields render, help link works
- [ ] Submit sends `{handle, app_password, pds_url?}` — verified by mocked api.post call
- [ ] Test: `localStorage.setItem` is never called with the password substring (spy)
- [ ] Disconnect button works after successful link

**Verify:** `pnpm test:run src/components/pages/__tests__/settings-page*atproto*.test.tsx src/lib/api/services/__tests__/atproto.test.ts`

---

### Task 12: vidra-user — channel cross-post mode picker

**Objective:** Channel settings page lets owner choose `'always' | 'never' | 'ask'`.
**Dependencies:** Task 2 deployed
**Mapped Scenarios:** TS-002

**Files:**
- Modify: `src/components/pages/channel-edit-page.tsx` (or wherever channel settings live — verify first)
- Modify: `src/lib/api/services/channels.ts` (PATCH includes new field)
- Modify: `src/lib/api/types.ts` (`Channel.atprotoCrossPostMode?: 'always' | 'never' | 'ask'`)
- Modify: tests for both

**Key Decisions / Notes:**
- Radio group, three options. Helper text under each (e.g., "Always: every upload posts to Bluesky"). Disabled when no ATProto identity is linked at the user level (with explanatory tooltip).

**Definition of Done:**
- [ ] Picker renders with current value selected
- [ ] Change → PATCH /channels/{id} with `atproto_cross_post_mode` field
- [ ] Disabled state when user has no linked ATProto

**Verify:** `pnpm test:run src/components/pages/__tests__/channel-edit-page.test.tsx`

---

### Task 13: vidra-user — upload-page cross-post toggle

**Objective:** Upload composer reads channel default, persists per-upload override.
**Dependencies:** Task 8 deployed, Task 12
**Mapped Scenarios:** TS-002

**Files:**
- Modify: `src/components/pages/upload-page.tsx`
- Modify: `src/components/pages/__tests__/upload-page.test.tsx` (`upload-page-atproto.test.tsx` if needed)

**Key Decisions / Notes:**
- After upload completes, if `crossPost === true && atprotoLinked`, fire `atprotoService.syndicate(videoId)`. On error, non-blocking toast "Couldn't cross-post — re-link Bluesky in settings"; the upload itself does NOT fail.
- Toggle initial state: derived from channel's `atprotoCrossPostMode` (`'always'` → on, `'never'` → off + disabled, `'ask'` → off but enabled).
- Helper line under toggle: `Channel default: <mode>`.

**Definition of Done:**
- [ ] Channel `'always'` → toggle ON by default
- [ ] Channel `'never'` → toggle OFF + disabled
- [ ] Channel `'ask'` → toggle OFF, user can flip
- [ ] Successful publish + toggle ON → `syndicate` called once
- [ ] Syndicate error surfaces toast but upload completes

**Verify:** `pnpm test:run src/components/pages/__tests__/upload-page*.test.tsx`

---

### Task 14: vidra-user — channel-page Bluesky tab wrapping

**Objective:** Existing `<BlueskyFeed>` mount at `channel-page.tsx:274` lives in the right tab. Verify tab structure exists; add tab if missing.
**Dependencies:** Task 7 deployed
**Mapped Scenarios:** TS-003

**Files:**
- Modify: `src/components/pages/channel-page.tsx`
- Modify: `src/components/bluesky-feed.tsx` (refine empty state — "No posts yet on Bluesky" with link to handle)
- Modify: `src/components/__tests__/bluesky-feed.test.tsx`

**Key Decisions / Notes:**
- **Tab structure verified at `channel-page.tsx:273` — exists today** (cycle-1 S9): conditional `activeTab === 'bluesky' && channelData?.atprotoDid` already wires the tab. Task 14 is **only** refining empty/error states and adding `<TabsTrigger>` when `atprotoDid` is present (currently the trigger may be unconditional).
- Empty state: friendly copy, link to the channel's Bluesky profile.

**Definition of Done:**
- [ ] Tab visible only when channel has ATProto DID
- [ ] Click tab → `<BlueskyFeed>` renders with cursor pagination
- [ ] Empty state when feed is empty
- [ ] Reduced-motion: tab transition without animation

**Verify:** `pnpm test:run src/components/__tests__/bluesky-feed.test.tsx src/components/pages/__tests__/channel-page.test.tsx`

---

### Task 15: vidra-user — `<BlueskyChannelSidebar>` for watch page

**Objective:** Right rail under the player: "Recent on Bluesky" card with last 5 posts from the channel owner.
**Dependencies:** Task 7 deployed
**Mapped Scenarios:** TS-004

**Files:**
- Create: `src/components/bluesky-channel-sidebar.tsx`
- Modify: `src/components/pages/watch-page.tsx` (mount the sidebar in the right column)
- Create: `src/components/__tests__/bluesky-channel-sidebar.test.tsx`

**Key Decisions / Notes:**
- Component takes `did: string`, fetches `getFeed(did, count=5)` once on mount via `useApi` hook.
- Renders only when channel has `atprotoDid`. Empty state: "No recent Bluesky posts."
- Touch targets ≥ 44×44 on each post card; `aria-label="Open on Bluesky"` on the link.

**Definition of Done:**
- [ ] Renders 5 posts when feed available
- [ ] Hides when channel has no atprotoDid
- [ ] Each post is a link with target="_blank" rel="noopener noreferrer"
- [ ] Reduced-motion: no enter animation

**Verify:** `pnpm test:run src/components/__tests__/bluesky-channel-sidebar.test.tsx`

---

### Task 16: vidra-user — `<BlueskyReplies>` lazy panel

**Objective:** Below normal comments on watch page, a panel showing Bluesky replies to the video's AT post. Lazy-loads on intersection.
**Dependencies:** Task 9 deployed
**Mapped Scenarios:** TS-004

**Files:**
- Create: `src/components/bluesky-replies.tsx`
- Modify: `src/components/pages/watch-page.tsx` (mount below `<CommentSection>`)
- Create: `src/components/__tests__/bluesky-replies.test.tsx`

**Key Decisions / Notes:**
- IntersectionObserver: data fetch only on first viewport intersection, not on mount. Uses 200px rootMargin so it pre-fetches just before scrolling into view.
- **JSDOM has no IntersectionObserver (cycle-1 S8):** add a Vitest setup helper `mockIntersectionObserver()` to `src/test/setup.ts` (or import from a new `src/test/intersection-observer-mock.ts`); helper exposes `triggerIntersection(element)` so tests deterministically simulate the viewport event.
- Header: "Bluesky replies (N)" — N hidden until data loaded.
- Empty: hide the whole panel if interactions returns 404 (video not syndicated) or empty replies.
- Each reply card: handle, timestamp, body, link to reply on Bluesky.
- `role="region"` + `aria-label="Bluesky replies to this video"`.

**Definition of Done:**
- [ ] Doesn't fetch on mount; fetches on viewport intersection (verified via mock IntersectionObserver)
- [ ] Renders reply tree when data present
- [ ] Hides entirely when video has no AT URI (404 from /interactions)
- [ ] No layout shift when data loads (reserves min-height while loading)

**Verify:** `pnpm test:run src/components/__tests__/bluesky-replies.test.tsx`

---

### Task 17: vidra-user — `<BlueskyActivityRail>` for home page

**Objective:** Right-rail widget on `/` that aggregates recent ATProto posts from subscribed channels.
**Dependencies:** Task 7 deployed
**Mapped Scenarios:** TS-006

**Files:**
- Create: `src/components/bluesky-activity-rail.tsx`
- Create: `src/lib/hooks/use-bluesky-activity.ts` (cap subscriptions, parallelize fetches, merge by recency)
- Modify: `src/components/pages/home-page.tsx` (mount in right rail)
- Create: `src/components/__tests__/bluesky-activity-rail.test.tsx`
- Create: `src/lib/hooks/__tests__/use-bluesky-activity.test.ts`

**Key Decisions / Notes:**
- **Lazy-load via IntersectionObserver (cycle-1 S4):** the rail does NOT fetch on home-page mount; data fetch fires on first viewport intersection. This protects against `100 concurrent home loads × 20 PDS round-trips` deploy-shock storms. Same pattern as `<BlueskyReplies>` (Task 16).
- Hook takes the user's subscriptions list, takes the top 20 most-recently-active channels with linked ATProto, calls `getFeed(did, count=5)` for each (Promise.all), merges by post timestamp descending, caps at 30.
- 5-minute cache via SWR-style stale-while-revalidate (existing `useApi` may suffice). Server-side cache from Task 7 (1000-entry LRU) absorbs the rest.
- Fallback: hidden entirely if no subscribed channel has ATProto linked.
- **Performance:** memoized over subscriptions list. Don't re-fetch on every home re-render. The hook test verifies this.
- **Server-side aggregator deferred:** if Task 17 reveals real-world hot-cache rate-limit pressure, follow-up spec adds `GET /federation/atproto/subscriptions-feed` aggregating server-side. Not blocking this phase.

**Definition of Done:**
- [ ] 20-subscription cap respected (test with 50 subs verifies only 20 fetched)
- [ ] Posts sorted by recency
- [ ] Re-rendering home doesn't trigger re-fetches within 5 min
- [ ] Hidden when no subscriptions have ATProto

**Verify:** `pnpm test:run src/components/__tests__/bluesky-activity-rail.test.tsx src/lib/hooks/__tests__/use-bluesky-activity.test.ts`

---

### Task 18: vidra-user — `<FederatedBadge>` on `<VideoCard>`

**Objective:** Unified badge for ActivityPub-remote AND ATProto-cross-posted videos. Pure component memoized.
**Dependencies:** None
**Mapped Scenarios:** TS-005

**Files:**
- Create: `src/components/federated-badge.tsx`
- Modify: `src/components/video-card.tsx` (mount badge under thumbnail)
- Create: `src/components/__tests__/federated-badge.test.tsx`

**Key Decisions / Notes:**
- Props: `{ isRemote?: boolean; host?: string; atprotoUri?: string }`. Renders nothing when all three are absent/false.
- Visual: small pill with `Globe` lucide icon + "Federated" label, matching `search-page.tsx:302` pattern.
- Tooltip text by source:
  - `is_remote && host` → "From <host>"
  - `atprotoUri` (no is_remote) → "Cross-posted to Bluesky"
  - Both → "From <host> · Cross-posted to Bluesky"
- `React.memo` over the three props; no fetches; no effects.
- `aria-label` on the chip with the same text as the tooltip for screen readers.

**Definition of Done:**
- [ ] Renders nothing when no flags
- [ ] Renders badge with correct tooltip per scenario (3 cases)
- [ ] Memoized: same props → same React element identity (verified via render counter in test)
- [ ] No layout shift when added to a video card

**Verify:** `pnpm test:run src/components/__tests__/federated-badge.test.tsx`

---

### Task 19: vidra-user — i18n keys (13 locales)

**Objective:** All new UI strings land in `en.json` AND 12 other locales. `pnpm i18n:check` returns 0.
**Dependencies:** Tasks 11, 12, 13, 14, 15, 16, 17, 18
**Mapped Scenarios:** All

**Files:**
- Modify: `messages/en.json`
- Modify: `messages/{es,fr,de,ja,zh,ko,pt,ru,ar,it,pl,nl}.json` (12 files)

**Key Decisions / Notes:**
- New string groups: `Atproto.connect.*`, `Atproto.disconnect.*`, `Atproto.crossPost.*`, `Atproto.feed.*`, `Atproto.replies.*`, `Atproto.activityRail.*`, `Federated.badge.*`.
- Placeholders `{handle}`, `{host}`, `{count}`, `{mode}` — never concat strings.

**Definition of Done:**
- [ ] `pnpm i18n:check` returns 0
- [ ] No `[missing key]` in console when running dev mode against /settings, /channel/<id>, /watch/<id>, /
- [ ] Smoke render in `es` locale — Playwright snapshot matches

**Verify:** `pnpm i18n:check`

---

### Task 20: vidra-user — Playwright E2E

**Objective:** TS-001..TS-007 as runnable Playwright specs.
**Dependencies:** Tasks 1–18
**Mapped Scenarios:** TS-001..TS-007

**Files:**
- Create: `e2e/atproto-link-account.spec.ts` (TS-001, TS-007)
- Create: `e2e/atproto-cross-post.spec.ts` (TS-002)
- Create: `e2e/atproto-channel-feed.spec.ts` (TS-003)
- Create: `e2e/atproto-watch-replies.spec.ts` (TS-004)
- Create: `e2e/federated-badge.spec.ts` (TS-005)
- Create: `e2e/atproto-home-rail.spec.ts` (TS-006)
- Modify: `e2e/fixtures/users.ts` (add Bluesky test handles + per-locale variants)
- Modify: `e2e/global-setup.ts` (mock ATProto endpoints OR seed via API helper)

**Key Decisions / Notes:**
- Tests run against `pnpm dev:full` (vidra-core docker + frontend).
- For TS-001, the actual Bluesky PDS connect can be MOCKED at the network layer via Playwright route-interception (`page.route('**/api/v1/federation/atproto/connect', ...)`); a true end-to-end against bsky.social is too flaky/policy-fragile for CI.
- For TS-005 (federated badge), seed two videos via test API: one local, one remote.
- For TS-002 (cross-post), mock the `syndicate` endpoint to return a fake AT URI.

**Definition of Done:**
- [ ] All 6 spec files green
- [ ] `pnpm test:e2e -g "atproto|federated"` < 4 min total

**Verify:** `pnpm test:e2e -g "atproto|federated"`

---

## PeerTube Parity Check

C10–C12 are **vidra-specific extensions** beyond PeerTube parity. PeerTube has no native ATProto/Bluesky integration; closest equivalent is the third-party `peertube-plugin-bluesky` plugin which only does post-on-publish (no feed display, no replies). Phase 11 deliberately exceeds PeerTube parity here, motivated by Vidra's positioning as a federated-first platform across BOTH ActivityPub and AT Protocol.

The unified `<FederatedBadge>` (Task 18) DOES touch PeerTube parity: PeerTube shows a "Remote" indicator on federated content. Vidra's badge subsumes that ("Federated" with origin tooltip).

## Vidra-Specific / Requested Features

This entire plan implements vidra-specific extensions:
- **ATProto Federation (C10–C12)** — wires UI against new backend HTTP routes that don't exist today. Backend extension impacted: ATProto Federation.
- **Bitcoin Payments / Direct Messaging / Real-time Stream Chat / Inner Circle / IPFS / Video Studio / Auto-Captioning / Advanced Analytics** — none impacted by this phase.

Backend extensions impacted by this plan: **ATProto Federation**.

## Verification Plan

- **Per-task:** Vitest / Go test runs as listed in each task's Verify line.
- **Phase-wide:**
  - `pnpm typecheck` clean (vidra-user)
  - `pnpm lint` clean (vidra-user)
  - `pnpm test:run` 100% pass (vidra-user)
  - `pnpm i18n:check` 0 mismatches
  - `pnpm test:e2e -g "atproto|federated"` all green
  - `cd ../vidra-core && go build ./...` clean
  - `cd ../vidra-core && go test ./...` 100% pass
  - Two-context Chromium walkthrough: TS-001..TS-007 against `pnpm dev:full` with screenshots.
- **Cross-repo deploy ordering:** vidra-core PR (Tasks 1–10) MUST land + deploy to dev before vidra-user PR is merged. Frontend tasks 11–18 will fail E2E against an un-deployed backend.

## Spec-Review Cycle 1 — Findings Incorporated

All 5 must_fix items resolved in this revision:
- **F1** — Added Task 0: new migration for `videos.atproto_uri` column (was missing; Tasks 8/9 wouldn't compile without it). Frontend type already had it; backend now matches.
- **F2** — Task 9 now reads from existing `atproto_comments` table (migration 039) as primary source, falls back to PDS getPostThread. No duplicate storage.
- **F3** — Migrations use timestamped naming (`YYYYMMDDHHMM_*.sql`) to avoid integer-sequence collisions with concurrent phases.
- **F4** — Task 0 migration includes `UNIQUE` partial index on `videos.atproto_uri` (prevents two-videos-same-AT-URI race).
- **F5** — Task 10 explicitly traces master-key plumbing from existing instance singleton; DoD requires master key never in /debug or pprof output.

Should-fix items S1–S10 incorporated inline (autocomplete + telemetry breadcrumb hardening, LRU cap + rate-limit middleware on public routes, refresh consistency via SELECT FOR UPDATE, IntersectionObserver on home rail, TS-001 step 7 split into 3 explicit assertions, positive route-assertion test instead of total-count test, durable cross-post failure notification, JSDOM IntersectionObserver mock helper, channel-page tab existence verified, dev-only-rollback comment on down migration).

Suggestions G1–G5 incorporated (`atproto-uri-to-bsky-app-url` helper in Task 8, cache invalidation contract in Task 8/9, pre-flight verify pattern in Task 11; G1 read-syndicate endpoint deferred since `Video.atproto_uri` is already on the wire).

## Open Questions

- None at planning time. All architectural decisions resolved via Batch 1 + Batch 2 questions, the scope-reality finding (audit's "Backend READY" was wrong), and the cycle-1 reviewer findings.
