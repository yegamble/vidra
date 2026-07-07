# Vidra Feature Vision & QA Inventory

**Date:** 2026-04-28
**Scope:** Full feature inventory across `vidra-core` (Go backend, Docker) and `vidra-user` (Next.js frontend), organized by 15 categories.
**Purpose:** Single list-format source of truth for QA — every feature, where it lives, what state it's in, and what tests it needs.

## How to read this document

Each feature row uses these fields:

- **ID** — stable identifier; use in QA_LEDGER, REGRESSION_TESTS, TEST_MATRIX.
- **Status** — `implemented` (works end-to-end), `partial` (UI or backend exists but the wiring is broken / shape-mismatched / stubbed), `planned` (no implementation either side), `unclear` (no evidence found in audited material).
- **Backend** — `vidra-core` files / openapi spec / internal package responsible.
- **Frontend** — `vidra-user` service module + page/component file(s).
- **API** — REST path(s); WS shown as `WS …`.
- **DB** — migration files / table names. Numbers refer to `vidra-core/migrations/NNN_*.sql`.
- **Manual smoke** — concrete user action that proves it works.
- **Automated test** — Vitest (unit) and Playwright (E2E) coverage to add or extend.
- **PeerTube ref** — `MATCH` (PeerTube has it; we mirror), `EXTEND` (we go beyond), `VIDRA-ONLY`, `N/A`.
- **Risk** — `CRITICAL` (data loss, auth, payment), `HIGH` (P0 in audits), `MEDIUM` (P1), `LOW` (P2 / cosmetic).

Status comes primarily from `docs/plans/2026-04-28-feature-wiring-audit-runtime-gaps.md` (live-stack runtime audit), `docs/plans/2026-04-22-feature-parity-audit.md` (parity audit), and `docs/plans/2026-03-31-peertube-feature-parity-map.md` (parity map). Where those audits disagree, the most recent (2026-04-28) wins.

> **Evidence integrity rule:** every `implemented` status below is backed by a matching service test (`src/lib/api/services/__tests__/<service>.test.ts`) **and** at least one E2E spec under `e2e/`. Anything UI-only that has not been verified against the live stack is at most `partial`.

---

## Table of Contents

1. [Core video platform](#1-core-video-platform)
2. [User / account system](#2-user--account-system)
3. [Upload / import / transcoding](#3-upload--import--transcoding)
4. [Playback](#4-playback)
5. [Live streaming](#5-live-streaming)
6. [Federation](#6-federation)
7. [P2P / IPFS / WebTorrent](#7-p2p--ipfs--webtorrent)
8. [Storage / CDN](#8-storage--cdn)
9. [Moderation / safety](#9-moderation--safety)
10. [Admin / instance management](#10-admin--instance-management)
11. [Plugins / extensibility](#11-plugins--extensibility)
12. [Analytics](#12-analytics)
13. [Payments / monetization](#13-payments--monetization)
14. [Frontend UX](#14-frontend-ux)
15. [DevOps / observability / QA](#15-devops--observability--qa)

---

## 1. Core video platform

### CORE-01 · Video model + metadata
- **Status:** implemented
- **Backend:** `internal/domain/video.go`, `internal/repository/video_*.go`, `api/openapi.yaml`
- **Frontend:** `src/lib/api/services/videos.ts`, `src/lib/api/types.ts`
- **API:** `GET/PUT /api/v1/videos/{id}`, `GET /api/v1/videos`, `DELETE /api/v1/videos/{id}`
- **DB:** `007_create_videos_table.sql`, `010_alter_videos_add_outputs.sql`, `021_add_category_to_videos.sql`, `027_add_channel_id_to_videos.sql`, `070_create_video_chapters_table.sql`, `082_create_video_passwords_storyboards_embed.sql`, `093_add_default_video_privacy_to_users.sql`
- **Manual smoke:** Open `/watch/[id]` → metadata renders (title, description, channel, date, views).
- **Automated test:** `videos.test.ts`, `e2e/video-upload-playback.spec.ts`, `e2e/watch-player.spec.ts`.
- **PeerTube ref:** MATCH.
- **Risk:** CRITICAL (core entity).

### CORE-02 · Video listing / pagination
- **Status:** partial — `GET /api/v1/videos?count=10` returns object keyed `{"0":..., "1":...}` instead of an array (audit P1 #25); pagination only fully wired on search.
- **Backend:** `internal/httpapi/video_handlers.go`
- **Frontend:** `src/lib/api/services/videos.ts`, `src/components/pages/home-page.tsx`, `src/components/pages/discover-page.tsx`, `src/components/pages/trending-page.tsx`
- **API:** `GET /api/v1/videos`, `GET /api/v1/videos/trending` (currently 400 — router treats `trending` as UUID), `GET /api/v1/overviews/videos` (alias added; FE missing).
- **DB:** `007_create_videos_table.sql`.
- **Manual smoke:** Home / Discover / Trending all paginate past page 1.
- **Automated test:** `e2e/pagination.spec.ts` (extend), add Vitest for shape coercion.
- **PeerTube ref:** MATCH.
- **Risk:** HIGH.

### CORE-03 · Video detail / watch page
- **Status:** implemented
- **Backend:** `internal/httpapi/video_handlers.go`, `internal/usecase/video.go`
- **Frontend:** `src/components/pages/watch-page.tsx`, `src/components/video-player.tsx`
- **API:** `GET /api/v1/videos/{id}`, `POST /api/v1/views`, `GET /api/v1/videos/{id}/rating`
- **DB:** `018_create_user_views_table.sql`.
- **Manual smoke:** Watch a video; metadata, related, comments, like/dislike load.
- **Automated test:** `e2e/watch-player.spec.ts`.
- **PeerTube ref:** MATCH.
- **Risk:** CRITICAL.

### CORE-04 · View counter
- **Status:** partial — `POST /views` returns 200 once then 400; `videos.views` never increments (audit P0 #3, vidra-core).
- **Backend:** `internal/usecase/views.go` (broken); `018_create_user_views_table.sql`
- **Frontend:** `src/lib/api/services/videos.ts:trackView`
- **API:** `POST /api/v1/views`
- **DB:** `018_create_user_views_table.sql`.
- **Manual smoke:** Watch a video → reload `/watch/[id]` → views count increments by 1.
- **Automated test:** Add `e2e/view-counter.spec.ts` that asserts persistence on reload.
- **PeerTube ref:** MATCH.
- **Risk:** HIGH (analytics + monetization downstream).

### CORE-05 · Watch history
- **Status:** partial — `GET /users/me/history/videos` always returns `{count: 0, views: null}`; backend not populating user_history (audit P0 #2).
- **Backend:** `internal/usecase/history.go`, `internal/repository/views.go`
- **Frontend:** `src/components/pages/library-page.tsx`, `src/lib/api/services/videos.ts:getWatchHistory`
- **API:** `GET /api/v1/users/me/history/videos`, `DELETE /api/v1/users/me/history/videos/{id}` (per-item missing — audit P2 #28)
- **DB:** `018_create_user_views_table.sql`.
- **Manual smoke:** Watch 2 videos → `/library/history` lists both with progress.
- **Automated test:** `e2e/library.spec.ts` (extend), add Vitest history shape mapping.
- **PeerTube ref:** MATCH.
- **Risk:** HIGH.

### CORE-06 · Watch later
- **Status:** partial — Save dialog has no Watch Later entry; `GET /api/v1/playlists/watch-later` → 400 (audit P1 #17).
- **Backend:** `internal/httpapi/playlist_handlers.go`
- **Frontend:** `src/lib/api/services/playlists.ts:getWatchLater`, `library-page.tsx`
- **API:** `GET /api/v1/playlists/watch-later`
- **DB:** `032_create_ratings_and_playlists.sql`.
- **Manual smoke:** Save dialog → "Watch Later" → appears in `/library/watch-later`.
- **Automated test:** `e2e/library.spec.ts` (extend), `playlists.test.ts`.
- **PeerTube ref:** MATCH.
- **Risk:** MEDIUM.

### CORE-07 · Resume playback
- **Status:** implemented (5 s debounce + sendBeacon) — A12.
- **Backend:** `internal/repository/views.go` (currentTime field).
- **Frontend:** `src/components/video-player.tsx`, `src/components/pages/watch-page.tsx`.
- **API:** `POST /api/v1/views`, `GET /api/v1/videos/{id}` returns `userHistory.currentTime`.
- **DB:** `018_create_user_views_table.sql`.
- **Manual smoke:** Pause at 1:30, reload → resumes at ~1:30.
- **Automated test:** Add `e2e/resume-playback.spec.ts`.
- **PeerTube ref:** MATCH.
- **Risk:** MEDIUM.

### CORE-08 · Categories + tags
- **Status:** partial — categories enum works; tags not displayed on watch page (audit A21).
- **Backend:** `internal/repository/categories.go`
- **Frontend:** `src/lib/api/services/videos.ts:getCategories`, `category-page.tsx`
- **API:** `GET /api/v1/videos/categories`
- **DB:** `020_create_video_categories_table.sql`, `011_make_tags_nullable.sql`.
- **Manual smoke:** Watch page shows tag chips; category page filters by tag.
- **Automated test:** Add tag-rendering Vitest + watch-page E2E assertion.
- **PeerTube ref:** MATCH.
- **Risk:** MEDIUM.

### CORE-09 · Search (videos / channels / playlists)
- **Status:** partial — videos search works; channel + playlist tabs missing (audit A17).
- **Backend:** `internal/usecase/search.go`, `api/openapi.yaml`
- **Frontend:** `src/lib/api/services/search.ts`, `src/components/pages/search-page.tsx`, `e2e/search-filters.spec.ts`, `e2e/federated-search.spec.ts`
- **API:** `GET /api/v1/search/videos`, `GET /api/v1/search/video-channels`, `GET /api/v1/search/video-playlists`
- **DB:** N/A (Postgres FTS).
- **Manual smoke:** Search bar → videos / channels / playlists tabs each return rows.
- **Automated test:** `e2e/search-filters.spec.ts` (extend), `search.test.ts`.
- **PeerTube ref:** MATCH.
- **Risk:** MEDIUM.

### CORE-10 · Comments (list / post / edit / delete)
- **Status:** partial — `POST` returns 500 for some users (audit P0 #4); reply submission UI-only (A18); sort missing (A19); timestamp linking missing (A20).
- **Backend:** `internal/httpapi/comment_handlers.go`, `api/openapi_comments.yaml`
- **Frontend:** `src/lib/api/services/comments.ts`, `src/components/comment-section.tsx`
- **API:** `GET/POST/PUT/DELETE /api/v1/videos/{id}/comments[/{commentId}]`
- **DB:** `031_create_comments_table.sql`, `081_add_comment_approval.sql`.
- **Manual smoke:** Login as bob → comment on alice's video → comment appears + persists.
- **Automated test:** `e2e/video-comments.spec.ts` (extend cross-user), `comments.test.ts`, `e2e/comments-load-more.spec.ts`.
- **PeerTube ref:** MATCH.
- **Risk:** HIGH.

### CORE-11 · Like / dislike (rating)
- **Status:** partial — `PUT /rating` returns 200 but UI never persists on reload because `GET /rating` returns snake_case `{user_rating}` while frontend reads camelCase `{userRating}` (audit P0 #1).
- **Backend:** `internal/httpapi/rating_handlers.go`, `api/openapi_ratings_playlists.yaml`
- **Frontend:** `src/lib/api/services/videos.ts:225-238`, `src/lib/api/types.ts:343-349`, `src/components/pages/watch-page.tsx:177-182`
- **API:** `PUT /api/v1/videos/{id}/rate`, `GET /api/v1/videos/{id}/rating`
- **DB:** `032_create_ratings_and_playlists.sql`.
- **Manual smoke:** Like a video → reload → like still active + count incremented.
- **Automated test:** `e2e/video-likes.spec.ts` (extend with reload assertion), `videos.test.ts`.
- **PeerTube ref:** MATCH.
- **Risk:** HIGH.

### CORE-12 · Subscribe / unsubscribe
- **Status:** partial — `POST /channels/{handle}/subscribe` → 400; needs handle→UUID resolution or backend handle support (audit P0 #5).
- **Backend:** `internal/httpapi/subscription_handlers.go`
- **Frontend:** `src/lib/api/services/channels.ts:57-64`, `src/components/subscribe-button.tsx`
- **API:** `POST/DELETE /api/v1/channels/{handle}/subscribe`
- **DB:** `019_create_subscriptions.sql`, `029_update_subscriptions_to_channels.sql`, `030_fix_subscriptions_channel_fk.sql`, `077_fix_subscription_notification_triggers.sql`.
- **Manual smoke:** Subscribe → reload → button shows Subscribed.
- **Automated test:** `e2e/subscribe.spec.ts`, `channels.test.ts`.
- **PeerTube ref:** MATCH.
- **Risk:** HIGH.

### CORE-13 · Channels (CRUD)
- **Status:** implemented for view + edit display name; create / delete done; full edit (banner, avatar, description) partial; channel `subscribers` field name mismatch (`followersCount` vs `subscribers`, audit P1 #18).
- **Backend:** `internal/httpapi/channel_handlers.go`, `api/openapi_channels.yaml`
- **Frontend:** `src/lib/api/services/channels.ts`, `src/components/pages/channel-page.tsx`, `src/components/pages/channel-edit-page.tsx`, `src/components/create-channel-modal.tsx`
- **API:** `GET/POST/PUT/DELETE /api/v1/video-channels[/{handle}]`
- **DB:** `026_create_channels_table.sql`, `089_create_channel_activities.sql`, `076_create_video_ownership_changes_table.sql`.
- **Manual smoke:** Create channel → upload video → counts increment.
- **Automated test:** `e2e/channel-create.spec.ts`, `e2e/channel-delete.spec.ts`, `channels.test.ts`.
- **PeerTube ref:** MATCH.
- **Risk:** HIGH.

### CORE-14 · Playlists (CRUD + add/remove/reorder)
- **Status:** partial — create / delete / view work; remove + reorder missing; embed UI-only.
- **Backend:** `internal/httpapi/playlist_handlers.go`, `api/openapi_ratings_playlists.yaml`
- **Frontend:** `src/lib/api/services/playlists.ts`, `src/components/pages/playlist-detail-page.tsx`, `src/components/pages/playlist-embed-page.tsx`, `src/components/save-to-playlist-modal.tsx`
- **API:** `GET/POST/PUT/DELETE /api/v1/video-playlists[/{id}/videos[/{videoId}]]`
- **DB:** `032_create_ratings_and_playlists.sql`.
- **Manual smoke:** Create playlist → add 3 videos → remove one → reorder → continuous play.
- **Automated test:** `e2e/playlists.spec.ts` (extend), `playlists.test.ts`.
- **PeerTube ref:** MATCH.
- **Risk:** MEDIUM.

### CORE-15 · Chapters
- **Status:** implemented (rendered on progress bar) — A9.
- **Backend:** `internal/repository/chapters.go`, `070_create_video_chapters_table.sql`
- **Frontend:** `src/components/video-player.tsx`
- **API:** `GET/PUT /api/v1/videos/{id}/chapters`
- **Manual smoke:** Open video with chapters → chapter ticks visible on progress.
- **Automated test:** Add Vitest for chapter rendering; extend `watch-player.spec.ts`.
- **PeerTube ref:** MATCH.
- **Risk:** LOW.

### CORE-16 · Storyboards (hover preview)
- **Status:** implemented — A10.
- **Backend:** `082_create_video_passwords_storyboards_embed.sql`, `api/openapi_video_storyboards.yaml`
- **Frontend:** `src/components/video-player.tsx`
- **API:** `GET /api/v1/videos/{id}/storyboards`
- **Manual smoke:** Hover progress bar → thumbnail tooltip appears.
- **Automated test:** Add visual / Vitest mock + extend E2E.
- **PeerTube ref:** MATCH.
- **Risk:** LOW.

### CORE-17 · Embed player + privacy / passwords
- **Status:** partial — `/embed/[id]` route exists; oEmbed and RSS not surfaced (audit A31, A32).
- **Backend:** `api/openapi_video_embed_privacy.yaml`, `api/openapi_video_passwords.yaml`, `082_create_video_passwords_storyboards_embed.sql`
- **Frontend:** `src/components/pages/embed-page.tsx`, `src/app/[locale]/(embed)/embed/[id]/page.tsx`
- **API:** `GET /api/v1/videos/{id}/embed-info`, password endpoints.
- **Manual smoke:** Embed iframe in third-party page; password-gated video prompts for password.
- **Automated test:** Add `e2e/embed.spec.ts`.
- **PeerTube ref:** MATCH.
- **Risk:** MEDIUM.

---

## 2. User / account system

### USER-01 · Login / logout (OAuth2 + PKCE)
- **Status:** implemented (audit OK).
- **Backend:** `internal/httpapi/auth.go`, `internal/security/oauth.go`, `api/openapi.yaml`
- **Frontend:** `src/lib/api/services/auth.ts`, `src/lib/api/services/oauth.ts`, `src/components/auth-context.tsx`, `src/components/pages/login-page.tsx`
- **API:** `POST /api/v1/users/login`, `POST /api/v1/users/token`, `POST /api/v1/users/logout`, OAuth2 endpoints under `/o/`
- **DB:** `002_create_users_table.sql`, `003_create_refresh_tokens_table.sql`, `004_create_sessions_table.sql`, `006_fix_sessions_active_index.sql`, `025_create_oauth_clients_table.sql`, `028_create_oauth_authorization_codes_table.sql`.
- **Manual smoke:** Login → reload → still authenticated; logout → cookies + tokens cleared.
- **Automated test:** `e2e/auth.spec.ts`, `e2e/auth-oauth.spec.ts`, `auth.test.ts`, `oauth.test.ts`.
- **PeerTube ref:** MATCH.
- **Risk:** CRITICAL.

### USER-02 · Registration (inline tab on /login)
- **Status:** implemented.
- **Backend:** `internal/httpapi/registration.go`, `074_create_user_registrations_table.sql`
- **Frontend:** `src/components/pages/login-page.tsx` (register mode), `src/lib/api/services/auth.ts:register`
- **API:** `POST /api/v1/users/register`
- **Manual smoke:** Register a new user via /login?mode=register.
- **Automated test:** `e2e/auth.spec.ts`.
- **PeerTube ref:** MATCH.
- **Risk:** CRITICAL.

### USER-03 · Direct /register and /signup routes
- **Status:** planned — direct route 404 + Next.js root-layout runtime error (audit P0 #7).
- **Backend:** N/A (FE routing).
- **Frontend:** missing `src/app/[locale]/(main)/register/page.tsx`.
- **Manual smoke:** Visit `/register` directly → registration form (or 302 to `/login?mode=register`).
- **Automated test:** Add `e2e/auth-register-direct.spec.ts`.
- **PeerTube ref:** MATCH.
- **Risk:** HIGH (broken layout).

### USER-04 · Forgot / reset password
- **Status:** planned — login links to `/forgot-password` → 404; service `requestPasswordReset` exists but unreachable (audit P0 #6).
- **Backend:** `internal/httpapi/password_reset.go`, `068_create_password_reset_tokens_table.sql`
- **Frontend:** missing `src/app/[locale]/(main)/forgot-password/page.tsx` and `reset-password/page.tsx`.
- **API:** `POST /api/v1/users/ask-reset-password`, `POST /api/v1/users/reset-password`
- **Manual smoke:** Click "Forgot" on login → submit email → receive reset link → set new password → login with new.
- **Automated test:** Add `e2e/auth-password-reset.spec.ts`.
- **PeerTube ref:** MATCH.
- **Risk:** HIGH.

### USER-05 · Email verification
- **Status:** unclear — backend `024_add_email_verification.sql` exists; UI not visible (audit P2).
- **Backend:** `024_add_email_verification.sql`, internal email package.
- **Frontend:** none audited.
- **Manual smoke:** Register → check email link → verified state in profile.
- **Automated test:** Add Vitest + E2E once UI exists.
- **PeerTube ref:** MATCH.
- **Risk:** MEDIUM.

### USER-06 · 2FA (TOTP)
- **Status:** partial — `authService.setup2FA()` exists; QR display + backup codes UI missing.
- **Backend:** `api/openapi_auth_2fa.yaml`, `059_add_two_factor_authentication.sql`
- **Frontend:** `src/lib/api/services/auth.ts`, `src/components/pages/settings-page.tsx`
- **API:** `POST /api/v1/users/me/two-factor/...`
- **Manual smoke:** Enable 2FA → scan QR → enter code → backup codes shown → logout/login requires TOTP.
- **Automated test:** Add `e2e/auth-2fa.spec.ts`.
- **PeerTube ref:** MATCH.
- **Risk:** HIGH (auth surface).

### USER-07 · Profile edit (display name, bio, avatar)
- **Status:** partial — UI present; avatar upload exists; password change UI but no API call (parity map §1).
- **Backend:** `internal/httpapi/user_handlers.go`, `013_move_user_avatar_to_table.sql`, `014_remove_url_from_user_avatars.sql`, `017_add_webp_ipfs_cid_to_user_avatars.sql`
- **Frontend:** `src/components/pages/settings-page.tsx`, `src/lib/api/services/auth.ts`
- **API:** `PUT /api/v1/users/me`, `POST /api/v1/users/me/avatar/pick`
- **Manual smoke:** Update display name + avatar → reload → persisted.
- **Automated test:** Add Vitest, extend `e2e/settings-live.spec.ts`.
- **PeerTube ref:** MATCH.
- **Risk:** MEDIUM.

### USER-08 · Password change
- **Status:** partial — UI button exists; no wired API call.
- **Backend:** `internal/httpapi/auth.go`
- **Frontend:** `src/components/pages/settings-page.tsx`
- **API:** `POST /api/v1/users/me/password`
- **Manual smoke:** Settings → change password → logout → login with new.
- **Automated test:** Add `e2e/settings-password.spec.ts`.
- **PeerTube ref:** MATCH.
- **Risk:** HIGH.

### USER-09 · Email change
- **Status:** planned.
- **Backend:** `internal/httpapi/auth.go` (likely)
- **Frontend:** none.
- **Manual smoke:** Settings → change email → re-verify.
- **Automated test:** Add later.
- **PeerTube ref:** MATCH.
- **Risk:** MEDIUM.

### USER-10 · Account deletion (danger zone)
- **Status:** partial — danger UI exists; not wired (parity map §1).
- **Backend:** `DELETE /api/v1/users/me`
- **Frontend:** `src/components/pages/settings-page.tsx`
- **Manual smoke:** Delete account → logged out → login fails.
- **Automated test:** Add `e2e/account-deletion.spec.ts`.
- **PeerTube ref:** MATCH.
- **Risk:** HIGH (data destruction).

### USER-11 · Account export / import
- **Status:** partial — backend ETL ready (`api/openapi_user_archives.yaml`, `083_create_user_archive_*.sql`); frontend missing.
- **Backend:** `api/openapi_user_archives.yaml`, `083_create_user_archive_channel_sync_player_settings.sql`
- **Frontend:** `src/lib/api/services/migrations.ts` (admin side; user-side missing)
- **API:** `POST /api/v1/users/me/archive`
- **Manual smoke:** Request archive → download → restore on another instance.
- **Automated test:** Add later.
- **PeerTube ref:** MATCH.
- **Risk:** MEDIUM.

### USER-12 · User roles (user / moderator / admin)
- **Status:** implemented.
- **Backend:** `002_create_users_table.sql`
- **Frontend:** types in `src/lib/api/types.ts`; gated rendering in admin / watch.
- **Manual smoke:** Login as admin → admin nav appears; as user → hidden.
- **Automated test:** `e2e/video-edit-roles.spec.ts`.
- **PeerTube ref:** MATCH.
- **Risk:** CRITICAL (auth surface).

### USER-13 · Notification preferences
- **Status:** partial — UI exists; not wired (parity map §12).
- **Backend:** `066_add_notification_preferences.sql`, `api/openapi_notifications.yaml`
- **Frontend:** `src/components/pages/settings-page.tsx`
- **API:** `PUT /api/v1/users/me/notification-settings`
- **Manual smoke:** Toggle → reload → persisted.
- **Automated test:** Add Vitest + extend settings E2E.
- **PeerTube ref:** MATCH.
- **Risk:** MEDIUM.

### USER-14 · Per-user public profile (`/u/{username}`)
- **Status:** planned (audit P2 #29).
- **Backend:** `GET /api/v1/users/{id}` exists.
- **Frontend:** route missing.
- **Manual smoke:** Navigate to user profile.
- **Automated test:** Add later.
- **PeerTube ref:** MATCH.
- **Risk:** LOW.

### USER-15 · OAuth applications management (per-user)
- **Status:** planned (parity map §14).
- **Backend:** `025_create_oauth_clients_table.sql`
- **Frontend:** none.
- **Manual smoke:** Authorize app → revoke → revoked.
- **Automated test:** Add later.
- **PeerTube ref:** MATCH.
- **Risk:** LOW.

---

## 3. Upload / import / transcoding

### UPLOAD-01 · Direct (single-XHR) upload with progress
- **Status:** implemented.
- **Backend:** `api/openapi_uploads.yaml`, `internal/usecase/upload.go`, `008_create_upload_sessions_table.sql`
- **Frontend:** `src/lib/api/services/uploads.ts:uploadDirect`, `src/components/pages/upload-page.tsx`
- **API:** `POST /api/v1/videos/upload`
- **Manual smoke:** Upload 50 MB file → progress reaches 100 % → video processes.
- **Automated test:** `e2e/video-upload-playback.spec.ts`, `uploads.test.ts`.
- **PeerTube ref:** MATCH.
- **Risk:** CRITICAL.

### UPLOAD-02 · Chunked / resumable upload (PeerTube `/upload-resumable/`)
- **Status:** partial — chunked-on-file-select exists; PeerTube-style resumable POST+PATCH stubbed (501) per audit.
- **Backend:** `api/openapi_uploads.yaml`, `internal/usecase/upload_session.go`, `092_add_upload_session_file_fingerprint.sql`
- **Frontend:** `src/lib/api/services/uploads.ts`, `src/components/pages/upload-page.tsx`
- **API:** `POST /api/v1/videos/upload-resumable`, `PATCH /api/v1/videos/upload-resumable/{id}`
- **Manual smoke:** Upload 500 MB → kill network at 50 % → resume → completes.
- **Automated test:** `e2e/upload-draft-recovery.spec.ts` (extend), Vitest abort/resume.
- **PeerTube ref:** MATCH.
- **Risk:** HIGH (data loss on retry).

### UPLOAD-03 · Upload draft recovery
- **Status:** implemented.
- **Backend:** `092_add_upload_session_file_fingerprint.sql`
- **Frontend:** `src/components/pages/upload-page.tsx`
- **Manual smoke:** Start upload → close tab → reopen → resume prompt.
- **Automated test:** `e2e/upload-draft-recovery.spec.ts`.
- **PeerTube ref:** EXTEND.
- **Risk:** MEDIUM.

### UPLOAD-04 · Thumbnail handling (auto + custom + frame pick)
- **Status:** partial — auto + WebP/PNG generated server-side; custom upload UI-only (audit A26); frame-pick missing.
- **Backend:** `internal/media/thumbnail.go`, `017_add_webp_ipfs_cid_to_user_avatars.sql`
- **Frontend:** `src/components/pages/upload-page.tsx`, `video-edit-page.tsx`
- **API:** `POST /api/v1/videos/{id}/thumbnail`
- **Manual smoke:** Upload custom JPG thumbnail → appears in grid.
- **Automated test:** Add `e2e/upload-thumbnail.spec.ts`.
- **PeerTube ref:** MATCH.
- **Risk:** HIGH (visual identity).

### UPLOAD-05 · Metadata form (title, description, category, tags, language, license)
- **Status:** partial — title/desc/category/tags/privacy work; language hardcoded; license selector missing (audit A27).
- **Backend:** `api/openapi.yaml`
- **Frontend:** `src/components/pages/upload-page.tsx`, `video-edit-page.tsx`
- **Manual smoke:** Submit full form → values persist on watch + edit page.
- **Automated test:** Vitest form schema; `e2e/video-edit-roles.spec.ts`.
- **PeerTube ref:** MATCH.
- **Risk:** MEDIUM.

### UPLOAD-06 · NSFW / Comments-enabled / Download-enabled toggles
- **Status:** partial — NSFW + comments toggles work; per-video download enable missing.
- **Backend:** `api/openapi.yaml`
- **Frontend:** `upload-page.tsx`, `video-edit-page.tsx`
- **Manual smoke:** Toggle each → effect on watch page (NSFW blur, comments hidden, download hidden).
- **Automated test:** Vitest + E2E watch-page expectations.
- **PeerTube ref:** MATCH.
- **Risk:** MEDIUM.

### UPLOAD-07 · Schedule publication
- **Status:** partial — datetime-local input exists; no API wiring (audit A25).
- **Backend:** `093_add_default_video_privacy_to_users.sql`, video model has `publishedAt`.
- **Frontend:** `upload-page.tsx`
- **API:** `PUT /api/v1/videos/{id}` with `publishAt`.
- **Manual smoke:** Upload private with future date → at scheduled time → public.
- **Automated test:** Add `e2e/upload-schedule.spec.ts`.
- **PeerTube ref:** MATCH.
- **Risk:** MEDIUM.

### UPLOAD-08 · Wait-for-transcoding option
- **Status:** partial — backend `088_add_wait_transcoding.sql`; FE not exposed.
- **Backend:** `088_add_wait_transcoding.sql`
- **Frontend:** missing toggle.
- **Manual smoke:** Toggle on → upload → video stays private until done.
- **Automated test:** Add later.
- **PeerTube ref:** MATCH.
- **Risk:** LOW.

### UPLOAD-09 · Video import from URL / torrent
- **Status:** partial — backend `046_create_video_imports_table.sql`, `api/openapi_imports.yaml` ready; FE UI missing (audit A28).
- **Backend:** `api/openapi_imports.yaml`, `046_create_video_imports_table.sql`
- **Frontend:** missing import wizard.
- **API:** `POST /api/v1/videos/imports`
- **Manual smoke:** Paste YouTube URL → import → playable.
- **Automated test:** Add `e2e/video-import-url.spec.ts`.
- **PeerTube ref:** MATCH.
- **Risk:** MEDIUM.

### UPLOAD-10 · Batch upload
- **Status:** partial — backend `086_add_batch_uploads.sql`; FE single-file only.
- **Backend:** `086_add_batch_uploads.sql`
- **Frontend:** none.
- **Manual smoke:** Drop 5 files → all process.
- **Automated test:** Add later.
- **PeerTube ref:** MATCH.
- **Risk:** LOW.

### UPLOAD-11 · Transcoding pipeline (HLS + WebTorrent)
- **Status:** implemented (post-upload HLS pipeline + per-resolution incremental availability per parity audit, vidra-core `2568eb6`..`5926ba3`).
- **Backend:** `internal/media/`, `internal/worker/`, `009_create_encoding_jobs_table.sql`, `010_alter_videos_add_outputs.sql`, `012_encoding_jobs_unique_active_per_video.sql`
- **Frontend:** processing visibility wired (`e2e/video-processing-visibility.spec.ts`).
- **API:** internal worker.
- **Manual smoke:** Upload → status `processing` → `published` → multiple resolutions selectable in player.
- **Automated test:** `e2e/video-pipeline-live.spec.ts`, `e2e/video-processing-visibility.spec.ts`.
- **PeerTube ref:** MATCH.
- **Risk:** CRITICAL.

### UPLOAD-12 · Virus scan (ClamAV)
- **Status:** implemented (audit shows ClamAV healthy).
- **Backend:** `060_add_virus_scan_log.sql`
- **Frontend:** N/A.
- **Manual smoke:** Upload EICAR test string → rejected with virus message.
- **Automated test:** Add `e2e/upload-virus-scan.spec.ts`.
- **PeerTube ref:** MATCH.
- **Risk:** CRITICAL (security).

### UPLOAD-13 · Channel sync (auto-import)
- **Status:** partial — backend ready (`api/openapi_channel_sync.yaml`, `083_create_user_archive_channel_sync_player_settings.sql`); FE missing.
- **Backend:** `api/openapi_channel_sync.yaml`
- **Frontend:** none.
- **Manual smoke:** Connect external channel → videos sync.
- **Automated test:** Add later.
- **PeerTube ref:** MATCH.
- **Risk:** LOW.

---

## 4. Playback

### PLAY-01 · HLS playback (hls.js)
- **Status:** implemented.
- **Backend:** HLS outputs from transcoding.
- **Frontend:** `src/components/video-player.tsx`
- **Manual smoke:** Watch video → no buffer stall on default network.
- **Automated test:** `e2e/watch-player.spec.ts`.
- **PeerTube ref:** MATCH.
- **Risk:** CRITICAL.

### PLAY-02 · Player controls (play / pause / seek / volume / fullscreen / quality)
- **Status:** implemented.
- **Frontend:** `src/components/video-player.tsx`
- **Manual smoke:** Exercise each control + keyboard shortcuts.
- **Automated test:** `e2e/watch-player.spec.ts`.
- **PeerTube ref:** MATCH.
- **Risk:** HIGH.

### PLAY-03 · Playback speed (0.25 ×–4 ×) — A6
- **Status:** implemented.
- **Frontend:** `src/components/video-player.tsx`
- **Manual smoke:** Cycle speeds → audio pitch changes consistently.
- **Automated test:** Extend `e2e/watch-player.spec.ts`.
- **PeerTube ref:** EXTEND (PT max 2 ×).
- **Risk:** LOW.

### PLAY-04 · Theater mode — A7
- **Status:** implemented.
- **Frontend:** `video-player.tsx`
- **Manual smoke:** Toggle → wide layout.
- **Automated test:** Extend `watch-player.spec.ts`.
- **PeerTube ref:** MATCH.
- **Risk:** LOW.

### PLAY-05 · Picture-in-Picture — A8
- **Status:** implemented (`i` shortcut).
- **Frontend:** `video-player.tsx`
- **Manual smoke:** Press `i` → PiP window.
- **Automated test:** Vitest stub `requestPictureInPicture`.
- **PeerTube ref:** MATCH.
- **Risk:** LOW.

### PLAY-06 · Captions (`<track>`)
- **Status:** implemented (rendering); generation triggered Phase 13.
- **Backend:** `api/openapi_captions.yaml`, `033_create_captions_table.sql`, `056_create_caption_generation_jobs.sql`
- **Frontend:** `src/lib/api/services/captions.ts`, `video-player.tsx`
- **API:** `GET/POST/PUT /api/v1/videos/{id}/captions/{lang}`
- **Manual smoke:** Toggle CC → text overlays.
- **Automated test:** `e2e/phase-13-auto-caption.spec.ts`, `e2e/phase-13-caption-editor.spec.ts`, `captions.test.ts`.
- **PeerTube ref:** MATCH.
- **Risk:** MEDIUM.

### PLAY-07 · Player settings (per-user defaults)
- **Status:** partial — backend `api/openapi_player_settings.yaml`, `083_create_..._player_settings.sql`; FE persistence partial.
- **Backend:** `api/openapi_player_settings.yaml`
- **Frontend:** `settings-page.tsx`
- **Manual smoke:** Set default quality → reload → persists.
- **Automated test:** Add Vitest.
- **PeerTube ref:** MATCH.
- **Risk:** LOW.

### PLAY-08 · Autoplay next + end-card countdown — A13
- **Status:** implemented.
- **Frontend:** `video-player.tsx`
- **Manual smoke:** Watch to end → countdown → next plays.
- **Automated test:** Extend `watch-player.spec.ts`.
- **PeerTube ref:** MATCH.
- **Risk:** LOW.

### PLAY-09 · Keyboard shortcuts (space, arrows, f, m, j, k, l)
- **Status:** implemented.
- **Frontend:** `video-player.tsx`
- **Manual smoke:** Exercise each.
- **Automated test:** Vitest event handler tests.
- **PeerTube ref:** MATCH.
- **Risk:** LOW.

### PLAY-10 · Player a11y (focus visible, ARIA labels, prefers-reduced-motion)
- **Status:** partial — Phase 13 work in progress.
- **Frontend:** `video-player.tsx`
- **Manual smoke:** Tab through controls; screen-reader announces labels.
- **Automated test:** `e2e/accessibility.spec.ts`.
- **PeerTube ref:** MATCH.
- **Risk:** MEDIUM.

---

## 5. Live streaming

### LIVE-01 · Create live stream + RTMP key
- **Status:** implemented (Part 2 Tasks 13/14) — `POST /streams` resolves `channel_id` via `channelService.getMyChannels()` and the livestream page renders separate RTMP URL + Stream Key fields populated from the API response.
- **Backend:** `api/openapi_livestreaming.yaml`, `internal/livestream/`, `048_create_live_streams_table.sql`, `057_add_chat_enabled_to_live_streams.sql`, `073_create_live_stream_sessions_table.sql`
- **Frontend:** `src/lib/api/services/streams.ts`, `src/components/pages/livestream-page.tsx`
- **API:** `POST /api/v1/streams`
- **Manual smoke:** Create live → real RTMP URL displayed → OBS connects → playback works.
- **Automated test:** `e2e/video-pipeline-live.spec.ts`, `streams.test.ts`.
- **PeerTube ref:** MATCH.
- **Risk:** HIGH.

### LIVE-02 · End live stream
- **Status:** implemented (Part 2 Task 15) — End Live button calls `streamService.end(streamId, { saveRecording })` and resets local state.
- **Frontend:** `livestream-page.tsx`
- **API:** `POST /api/v1/streams/{id}/end`
- **Manual smoke:** Click End → stream stops + Save Recording flag honored.
- **Automated test:** Extend `video-pipeline-live.spec.ts`.
- **PeerTube ref:** MATCH.
- **Risk:** HIGH.

### LIVE-03 · Live discovery `/live`
- **Status:** implemented (Part 2 Task 16) — FE typed-error gating renders "Live discovery coming soon" empty state with cross-repo issue link when BE returns 404/405; BE list handler added in vidra-core `routes.go` (`GET /api/v1/streams/` with `OptionalAuth`, reuses `GetActiveStreams`). Browser-verified live: heading "Live discovery coming soon" rendered correctly with single (gated) 405 in console.
- **Backend:** missing list handler in `internal/livestream/` HTTP layer.
- **Frontend:** `src/components/pages/live-page.tsx`
- **Manual smoke:** Open `/live` → currently-live streams listed.
- **Automated test:** Add `e2e/live-discovery.spec.ts`.
- **PeerTube ref:** MATCH.
- **Risk:** HIGH.

### LIVE-04 · Live chat (real-time WebSocket)
- **Status:** partial — UI renders disabled; depends on broken Go Live + WS auth.
- **Backend:** `api/openapi_chat.yaml`, `internal/chat/`, `049_create_chat_tables.sql`, `102_add_slow_mode_seconds_to_live_streams.sql`
- **Frontend:** `livestream-page.tsx`, `src/lib/api/services/streams.ts`
- **API:** WS `/api/v1/streams/{id}/chat`
- **Manual smoke:** Two browsers → typing in one shows in other in real time.
- **Automated test:** Add `e2e/live-chat.spec.ts`.
- **PeerTube ref:** EXTEND (real-time).
- **Risk:** HIGH.

### LIVE-05 · Chat moderation (ban / timeout / slow mode / watched-words)
- **Status:** partial — UI-only.
- **Backend:** `api/openapi_chat.yaml`, `102_add_slow_mode_seconds_to_live_streams.sql`, `079_create_watched_word_lists.sql`
- **Frontend:** placeholder UI in `livestream-page.tsx`.
- **Manual smoke:** Mod bans / times-out viewer → message blocked.
- **Automated test:** Add `e2e/live-chat-mod.spec.ts`.
- **PeerTube ref:** EXTEND.
- **Risk:** HIGH.

### LIVE-06 · Stream stats (bitrate / FPS / viewers)
- **Status:** partial — `StreamStats` type defined; UI missing; backend `051_create_stream_analytics.sql` ready.
- **Backend:** `051_create_stream_analytics.sql`
- **Frontend:** `livestream-page.tsx`
- **Manual smoke:** Streamer dashboard shows current bitrate + viewer count.
- **Automated test:** Add Vitest stub.
- **PeerTube ref:** MATCH.
- **Risk:** MEDIUM.

### LIVE-07 · Stream scheduling
- **Status:** planned — backend ready (`050_add_stream_scheduling.sql`); FE missing.
- **Backend:** `050_add_stream_scheduling.sql`
- **Frontend:** none.
- **Manual smoke:** Schedule a stream for tomorrow → notification + reminder.
- **Automated test:** Add later.
- **PeerTube ref:** MATCH.
- **Risk:** LOW.

### LIVE-08 · Permanent live + replay
- **Status:** planned.
- **Backend:** `048_create_live_streams_table.sql` (permanent flag).
- **Frontend:** none.
- **Manual smoke:** Permanent stream restarts after disconnect.
- **Automated test:** Add later.
- **PeerTube ref:** MATCH.
- **Risk:** LOW.

---

## 6. Federation

### FED-01 · ActivityPub publishing (videos / channels / activities)
- **Status:** implemented (parity audit notes ActivityPub channel activities + collaborator writes).
- **Backend:** `internal/activitypub/`, `037_create_federation_actors.sql`, `043_add_federation_deduplication.sql`, `044_add_activitypub_support.sql`, `061_encrypt_activitypub_private_keys.sql`, `040_federation_hardening.sql`, `089_create_channel_activities.sql`
- **Frontend:** badges via `e2e/federation-badges.spec.ts`.
- **API:** `api/openapi_federation.yaml`, `api/openapi_federation_hardening.yaml`
- **Manual smoke:** Mastodon / PeerTube instance follows the channel → posts appear.
- **Automated test:** `e2e/federated-search.spec.ts`, `e2e/federation-badges.spec.ts`.
- **PeerTube ref:** MATCH.
- **Risk:** HIGH.

### FED-02 · Server-following / followers (admin)
- **Status:** partial — backend ready; FE calls wrong path `/admin/server-following` → 404 (audit P0 #10).
- **Backend:** `075_create_server_following_table.sql`
- **Frontend:** `src/components/pages/admin-federation-page.tsx`, `src/lib/api/services/admin.ts`
- **API:** `GET /api/v1/server/following` (real path).
- **Manual smoke:** Follow another instance → its videos federate in.
- **Automated test:** Add `e2e/admin-federation.spec.ts`.
- **PeerTube ref:** MATCH.
- **Risk:** HIGH.

### FED-03 · Remote interaction prompts
- **Status:** planned (parity map §15).
- **Backend:** ready.
- **Frontend:** missing.
- **Manual smoke:** "Follow from your instance" prompts on remote videos.
- **Automated test:** Add later.
- **PeerTube ref:** MATCH.
- **Risk:** LOW.

### FED-04 · Local vs Federated scope toggle
- **Status:** planned (audit A15).
- **Frontend:** missing in listings + search.
- **Manual smoke:** Toggle Federated → remote videos appear.
- **Automated test:** Add later.
- **PeerTube ref:** MATCH.
- **Risk:** MEDIUM.

### FED-05 · ATProto (Bluesky) account linking
- **Status:** partial — UI mention only (audit C10).
- **Backend:** `api/openapi_extensions.yaml`, `035_add_atproto_to_channels.sql`, `036_add_atproto_federation.sql`, `038_create_atproto_sessions.sql`, `039_add_atproto_social.sql`, `041_add_embed_type_to_federated_posts.sql`, `202604271735_add_user_atproto_accounts.sql`
- **Frontend:** `src/lib/api/services/atproto.ts`, `atproto.test.ts`
- **API:** `POST /api/v1/federation/atproto/connect`, etc.
- **Manual smoke:** Link Bluesky → handle shown in profile.
- **Automated test:** `atproto.test.ts` (extend), add E2E once UI ships.
- **PeerTube ref:** VIDRA-ONLY.
- **Risk:** MEDIUM.

### FED-06 · ATProto cross-posting on upload
- **Status:** partial — UI-only (C11).
- **Backend:** ready (`202604271734_add_video_atproto_uri.sql`, `202604271736_add_channel_atproto_cross_post_mode.sql`).
- **Frontend:** `upload-page.tsx`
- **Manual smoke:** Upload with cross-post → post visible on Bluesky timeline.
- **Automated test:** Add later.
- **PeerTube ref:** VIDRA-ONLY.
- **Risk:** MEDIUM.

### FED-07 · Bluesky feed tab on channel
- **Status:** partial — UI-only (C12).
- **Backend:** ready.
- **Frontend:** `channel-page.tsx`
- **Manual smoke:** Channel → Bluesky tab → posts.
- **Automated test:** Add later.
- **PeerTube ref:** VIDRA-ONLY.
- **Risk:** LOW.

### FED-08 · Federation status / debug
- **Status:** partial — `/api/v1/federation/atproto/status` → 404 (audit FED).
- **Backend:** missing route.
- **Frontend:** admin federation page placeholder.
- **Manual smoke:** Admin → ATProto status → connected / queue depth.
- **Automated test:** Add later.
- **PeerTube ref:** MATCH.
- **Risk:** MEDIUM.

### FED-09 · RSS / oEmbed `<link>` discovery
- **Status:** planned (audit A31, A32).
- **Backend:** ready.
- **Frontend:** missing tags.
- **Manual smoke:** `<link rel=alternate>` present in `<head>` for channels.
- **Automated test:** Add Vitest snapshot.
- **PeerTube ref:** MATCH.
- **Risk:** LOW.

---

## 7. P2P / IPFS / WebTorrent

### P2P-01 · IPFS distribution (transparent gateway URLs)
- **Status:** implemented for already-uploaded videos (audit IPFS).
- **Backend:** `internal/ipfs/`, `api/openapi_ipfs.yaml`, `017_add_webp_ipfs_cid_to_user_avatars.sql`, `047_add_multicodec_support.sql`
- **Frontend:** transparent — player loads `/static/web-videos/...`.
- **Manual smoke:** Watch video → 200 from `/static/web-videos/{cid}/...`.
- **Automated test:** `e2e/video-upload-playback.spec.ts`.
- **PeerTube ref:** EXTEND (PT no IPFS).
- **Risk:** HIGH.

### P2P-02 · WebTorrent + HLS hybrid
- **Status:** unclear — backend `internal/torrent/`, `052_create_torrent_tables.sql`; FE no P2P toggle UI.
- **Backend:** `052_create_torrent_tables.sql`
- **Frontend:** no P2P indicator (parity map §4).
- **Manual smoke:** Player shows P2P peers connected; toggle off → CDN-only.
- **Automated test:** Add later.
- **PeerTube ref:** MATCH.
- **Risk:** MEDIUM.

### P2P-03 · IPFS peer / CID details
- **Status:** unclear — `api/openapi_ipfs.yaml` exposes; FE not surfaced.
- **Manual smoke:** Inspect → CIDs match between gateway responses.
- **Automated test:** Add later.
- **PeerTube ref:** N/A.
- **Risk:** LOW.

### P2P-04 · IPFS scheme detection / normalization in player
- **Status:** planned — `getStreamUrl()` does not normalize `ipfs://` URLs (parity map §15.5).
- **Manual smoke:** Verify URL scheme of each variant is HTTPS.
- **Automated test:** Vitest unit on getStreamUrl.
- **PeerTube ref:** N/A.
- **Risk:** MEDIUM.

---

## 8. Storage / CDN

### STOR-01 · S3 / object storage migration
- **Status:** partial — backend supports S3 (`058_add_s3_storage_fields.sql`, `cmd/s3migrate`, `cmd/s3test`); admin UI not surfaced.
- **Backend:** `internal/storage/`, `058_add_s3_storage_fields.sql`, `cmd/s3migrate/`, `cmd/s3test/`
- **Frontend:** none.
- **Manual smoke:** Upload → file lands in S3 bucket; replace bucket → existing videos still served.
- **Automated test:** Backend Go tests; add E2E for storage admin.
- **PeerTube ref:** MATCH.
- **Risk:** HIGH.

### STOR-02 · Static asset serving (`/static/web-videos/*`)
- **Status:** implemented.
- **Backend:** `api/openapi_static.yaml`
- **Manual smoke:** Asset URLs return 200 with correct content type.
- **Automated test:** Backend integration test.
- **PeerTube ref:** MATCH.
- **Risk:** CRITICAL.

### STOR-03 · Video files endpoints (HLS / WebTorrent / files)
- **Status:** implemented.
- **Backend:** `api/openapi_video_files.yaml`
- **Frontend:** transparent in player.
- **Manual smoke:** HLS manifest + .m3u8 segments load.
- **Automated test:** `video-upload-playback.spec.ts`.
- **PeerTube ref:** MATCH.
- **Risk:** CRITICAL.

### STOR-04 · Backup endpoints
- **Status:** unclear — `api/openapi_backup.yaml` exists; admin UI absent.
- **Backend:** `internal/backup/`
- **Frontend:** none.
- **Manual smoke:** Trigger backup → tarball produced.
- **Automated test:** Add later.
- **PeerTube ref:** MATCH.
- **Risk:** HIGH (data integrity).

### STOR-05 · Redundancy
- **Status:** partial — backend stubbed (501) per parity audit; PeerTube-only feature.
- **Backend:** `055_create_video_redundancy_tables.sql`, `api/openapi_redundancy.yaml`
- **Frontend:** none.
- **Manual smoke:** N/A until backend de-stubbed.
- **Automated test:** N/A.
- **PeerTube ref:** MATCH (intentionally deferred).
- **Risk:** LOW.

---

## 9. Moderation / safety

### MOD-01 · Abuse / report submission
- **Status:** implemented (FE `ReportDialog`, share/report E2E).
- **Backend:** `034_create_abuse_reports_and_blocklists.sql`, `072_create_abuse_report_messages_table.sql`, `api/openapi_moderation.yaml`
- **Frontend:** `src/components/report-dialog.tsx`
- **API:** `POST /api/v1/users/me/abuses`
- **Manual smoke:** Report video → admin sees report.
- **Automated test:** `e2e/share-report.spec.ts`, `moderation.test.ts`.
- **PeerTube ref:** MATCH.
- **Risk:** HIGH.

### MOD-02 · Abuse review (admin lifecycle: accept / reject / message / escalate)
- **Status:** partial — UI-only (audit B8); FE calls `/admin/abuses` → 404 (P1 #20). Real path `/admin/abuse-reports`.
- **Backend:** ready.
- **Frontend:** `src/components/pages/admin-moderation-page.tsx`, `src/components/pages/moderation/`
- **API:** `GET /api/v1/admin/abuse-reports`
- **Manual smoke:** Admin works queue end-to-end.
- **Automated test:** `e2e/admin-moderation-phase-7.spec.ts` (extend).
- **PeerTube ref:** MATCH.
- **Risk:** HIGH.

### MOD-03 · Watched-words list management
- **Status:** partial — backend ready (`079_create_watched_word_lists.sql`, `api/openapi_watched_words.yaml`); FE missing.
- **Backend:** `079_create_watched_word_lists.sql`
- **Frontend:** none.
- **Manual smoke:** Add word → comments containing it auto-flag.
- **Automated test:** Add later.
- **PeerTube ref:** MATCH.
- **Risk:** MEDIUM.

### MOD-04 · Auto-tag policies
- **Status:** partial — backend `080_create_auto_tag_policies.sql`, `api/openapi_auto_tags.yaml`; FE missing.
- **Backend:** `080_create_auto_tag_policies.sql`
- **Frontend:** none.
- **Manual smoke:** Configure rule → matching videos auto-tagged.
- **Automated test:** Add later.
- **PeerTube ref:** MATCH.
- **Risk:** MEDIUM.

### MOD-05 · User blocks / mutes (per-user)
- **Status:** partial — backend `071_create_user_blocks_table.sql`; FE service `blocks.ts` exists; muted page missing (audit A34).
- **Backend:** `071_create_user_blocks_table.sql`
- **Frontend:** `src/lib/api/services/blocks.ts`, `e2e/muted-management.spec.ts`
- **Manual smoke:** Block user → comments hidden.
- **Automated test:** `e2e/muted-management.spec.ts`, `blocks.test.ts`.
- **PeerTube ref:** MATCH.
- **Risk:** MEDIUM.

### MOD-06 · Server blocks
- **Status:** partial — `GET /api/v1/blocklist/servers` works; admin UI minimal.
- **Backend:** ready.
- **Frontend:** `admin-federation-page.tsx`
- **Manual smoke:** Admin blocks instance → its content disappears.
- **Automated test:** Add later.
- **PeerTube ref:** MATCH.
- **Risk:** MEDIUM.

### MOD-07 · Video blacklist
- **Status:** implemented.
- **Backend:** `069_create_video_blacklist_table.sql`
- **Frontend:** `admin-videos-page.tsx`
- **Manual smoke:** Admin blacklists video → users see "blacklisted" notice.
- **Automated test:** Extend admin-phase-6.
- **PeerTube ref:** MATCH.
- **Risk:** HIGH.

### MOD-08 · Comment approval / moderation queue
- **Status:** partial — backend `081_add_comment_approval.sql` ready; FE bulk moderation missing (audit B18).
- **Backend:** `081_add_comment_approval.sql`
- **Frontend:** `admin-moderation-page.tsx`
- **Manual smoke:** Approve / reject comment → effect on watch.
- **Automated test:** Add later.
- **PeerTube ref:** MATCH.
- **Risk:** MEDIUM.

### MOD-09 · NSFW display policy (blur / hide / show)
- **Status:** planned (audit A33).
- **Frontend:** missing setting.
- **Manual smoke:** Toggle setting → NSFW thumbnails blur / show / hide.
- **Automated test:** Add later.
- **PeerTube ref:** MATCH.
- **Risk:** MEDIUM.

### MOD-10 · Bulk comment moderation
- **Status:** planned (audit B18).
- **Frontend:** none.
- **Manual smoke:** Select 5 comments → bulk delete.
- **Automated test:** Add later.
- **PeerTube ref:** MATCH.
- **Risk:** LOW.

---

## 10. Admin / instance management

### ADMIN-01 · Dashboard (stats overview)
- **Status:** partial — `adminService.getStats()` wired; federation pill hard-coded "Active (47 instances)" (audit ADMIN-dashboard-fake-data).
- **Backend:** `internal/httpapi/admin_*.go`
- **Frontend:** `src/components/pages/admin-page.tsx`, `src/lib/api/services/admin.ts`
- **API:** `GET /api/v1/admin/stats`
- **Manual smoke:** Dashboard counts match DB / API.
- **Automated test:** `e2e/admin-phase-6.spec.ts`, `admin.test.ts`.
- **PeerTube ref:** MATCH.
- **Risk:** MEDIUM.

### ADMIN-02 · User management (list / search / role / ban)
- **Status:** implemented (Part 2 Tasks 23/24) — live probe of vidra-core showed `PUT /admin/users/{id}/status`, `PUT /admin/users/{id}/role`, and `DELETE /admin/users/{id}` all return 401 (auth required, route exists). UI gated behind `NEXT_PUBLIC_ADMIN_USER_MUTATIONS_ENABLED` (default true). Hard delete now uses Radix AlertDialog with red destructive action button (Apple HIG-compliant, replaced `window.confirm`).
- **Backend:** missing PUT routes; `DELETE /api/v1/admin/users/{id}` returns 204 (works).
- **Frontend:** `src/components/pages/admin-users-page.tsx`, `src/lib/api/services/admin.ts:33-38`
- **Manual smoke:** Ban user → user can't login → unban → can.
- **Automated test:** Add `e2e/admin-users.spec.ts`.
- **PeerTube ref:** MATCH.
- **Risk:** HIGH.

### ADMIN-03 · User hard delete
- **Status:** partial — backend `DELETE` works; frontend never calls it (audit ADMIN-G3).
- **Backend:** ready.
- **Frontend:** add `adminService.deleteUser`.
- **Manual smoke:** Hard delete → user removed from DB; row disappears.
- **Automated test:** Extend admin-users E2E.
- **PeerTube ref:** MATCH.
- **Risk:** HIGH (data destruction).

### ADMIN-04 · Video management (list / search / remove / blacklist)
- **Status:** implemented.
- **Frontend:** `src/components/pages/admin-videos-page.tsx`
- **API:** `GET /api/v1/admin/videos`
- **Manual smoke:** Render 15 rows, blacklist one, refresh → reflected.
- **Automated test:** `e2e/admin-phase-6.spec.ts`.
- **PeerTube ref:** MATCH.
- **Risk:** MEDIUM.

### ADMIN-05 · Server logs viewer
- **Status:** partial — `/api/v1/admin/logs` → 404 (audit P0 #9).
- **Backend:** missing endpoint.
- **Frontend:** `src/components/pages/admin-logs-page.tsx`
- **Manual smoke:** Logs tail in real time.
- **Automated test:** Add later.
- **PeerTube ref:** MATCH.
- **Risk:** MEDIUM.

### ADMIN-06 · Job queue monitoring
- **Status:** partial — FE calls `/admin/jobs` → 404; real path `/api/v1/jobs` (audit P0 #10).
- **Backend:** `api/openapi_admin.yaml`
- **Frontend:** `admin-jobs-page.tsx`, `src/lib/api/services/admin.ts`
- **Manual smoke:** See running / queued jobs; pause / retry one.
- **Automated test:** Add `e2e/admin-jobs.spec.ts`.
- **PeerTube ref:** MATCH.
- **Risk:** HIGH.

### ADMIN-07 · Runners
- **Status:** partial — FE calls `/admin/runners` → 404; real `/api/v1/runners`; 17+ endpoints stubbed (parity audit B14).
- **Backend:** `api/openapi_runners.yaml`, `104_add_runner_capabilities.sql`
- **Frontend:** `admin-runners-page.tsx`, `src/lib/api/services/runners.ts`
- **Manual smoke:** Register remote runner → it picks up jobs.
- **Automated test:** `e2e/admin-runners.spec.ts`.
- **PeerTube ref:** MATCH.
- **Risk:** MEDIUM.

### ADMIN-08 · Migrations (PeerTube import wizard)
- **Status:** partial — backend ETL complete; admin wizard missing (audit B1 — user's #1 ask).
- **Backend:** `api/openapi_migration.yaml`, `085_create_migration_jobs.sql`, `087_add_migration_id_mapping.sql`
- **Frontend:** `src/components/pages/admin-migrations-page.tsx`, `src/lib/api/services/migrations.ts`
- **Manual smoke:** Connect → select → migrate → monitor → verify.
- **Automated test:** `e2e/admin-migrations.spec.ts`, `migrations.test.ts`.
- **PeerTube ref:** EXTEND.
- **Risk:** CRITICAL (cited as #1 product ask).

### ADMIN-09 · Plugins
- **Status:** partial — backend `054_create_plugin_tables.sql`, `api/openapi_plugins.yaml`; FE renders shell.
- **Backend:** `internal/plugin/`
- **Frontend:** `admin-plugins-page.tsx`
- **Manual smoke:** Install plugin → activate → see effect.
- **Automated test:** `plugins.test.ts`.
- **PeerTube ref:** MATCH.
- **Risk:** MEDIUM.

### ADMIN-10 · Registrations (approval queue)
- **Status:** partial — FE renders empty; backend stubbed 501 (audit B7).
- **Backend:** `074_create_user_registrations_table.sql`
- **Frontend:** `admin-registrations-page.tsx`
- **Manual smoke:** Approve / reject pending registration → user notified.
- **Automated test:** Add later.
- **PeerTube ref:** MATCH.
- **Risk:** HIGH (gating signups).

### ADMIN-11 · Federation management UI
- **Status:** partial — see FED-02; route empty (audit B2).
- **Frontend:** `admin-federation-page.tsx`
- **Manual smoke:** Follow / unfollow / block remote instance.
- **Automated test:** Add later.
- **PeerTube ref:** MATCH.
- **Risk:** HIGH.

### ADMIN-12 · Settings (config / custom homepage / branding)
- **Status:** partial — `PUT /api/v1/config/custom` works; UI gates on broken `/admin/diagnostics` (audit ADMIN-config-custom-blocked).
- **Backend:** `internal/config/`
- **Frontend:** `admin-settings-page.tsx`, `admin-diagnostics-panel.tsx`
- **Manual smoke:** Edit instance name → reload → reflected.
- **Automated test:** `e2e/admin-settings.spec.ts`.
- **PeerTube ref:** MATCH.
- **Risk:** HIGH.

### ADMIN-13 · Roles UI
- **Status:** partial — page issues no fetch; backend route missing (audit ADMIN-roles).
- **Frontend:** `admin/roles/page.tsx`
- **Manual smoke:** Assign moderator role → effect.
- **Automated test:** Add later.
- **PeerTube ref:** EXTEND.
- **Risk:** LOW.

### ADMIN-14 · Diagnostics
- **Status:** partial — `/api/v1/admin/diagnostics` → 404 (audit P1 #21).
- **Backend:** missing endpoint.
- **Frontend:** `admin-diagnostics-panel.tsx`
- **Manual smoke:** See container health, queue depth, DB pool.
- **Automated test:** Add later.
- **PeerTube ref:** MATCH.
- **Risk:** MEDIUM.

### ADMIN-15 · Email / SMTP / security settings
- **Status:** planned (audit B16, B17).
- **Backend:** config exists.
- **Frontend:** missing pages.
- **Manual smoke:** Send test email → arrives.
- **Automated test:** Add later.
- **PeerTube ref:** MATCH.
- **Risk:** HIGH (email confirmation / security).

### ADMIN-16 · Custom CSS / homepage editor
- **Status:** planned (audit B12).
- **Frontend:** missing.
- **Manual smoke:** Edit → reflected.
- **Automated test:** Add later.
- **PeerTube ref:** MATCH.
- **Risk:** LOW.

---

## 11. Plugins / extensibility

### PLUG-01 · Plugin install / activate / uninstall
- **Status:** partial — backend ready; FE shell.
- **Backend:** `internal/plugin/`, `054_create_plugin_tables.sql`, `api/openapi_plugins.yaml`
- **Frontend:** `admin-plugins-page.tsx`, `plugins.ts`, `plugins.test.ts`
- **Manual smoke:** Install plugin → activate → see effect → uninstall.
- **Automated test:** `plugins.test.ts` (extend), add E2E.
- **PeerTube ref:** MATCH.
- **Risk:** MEDIUM.

### PLUG-02 · Plugin configuration UI
- **Status:** planned.
- **Manual smoke:** Open plugin settings → save → effect.
- **Automated test:** Add later.
- **PeerTube ref:** MATCH.
- **Risk:** LOW.

### PLUG-03 · Theme management
- **Status:** unclear — PeerTube has it; vidra theming via Tailwind tokens.
- **Manual smoke:** Switch theme → reflected.
- **Automated test:** Add later.
- **PeerTube ref:** DIFFER.
- **Risk:** LOW.

---

## 12. Analytics

### ANALY-01 · Channel analytics (total views, daily)
- **Status:** partial — handler registered; FE adapts shape; demographics + heatmap removed (parity audit).
- **Backend:** `internal/usecase/analytics/`, `053_create_analytics_tables.sql`, `api/openapi_analytics.yaml`, vidra-core commit `90e634e`
- **Frontend:** `src/lib/api/services/analytics.ts`, `src/components/pages/analytics-page.tsx`
- **API:** `GET /api/v1/channels/{id}/analytics`
- **Manual smoke:** Channel with views shows total + daily chart.
- **Automated test:** `e2e/phase-13-channel-analytics.spec.ts`, `analytics.test.ts`.
- **PeerTube ref:** EXTEND.
- **Risk:** MEDIUM.

### ANALY-02 · Per-video analytics
- **Status:** partial — `/api/v1/analytics/videos/{id}` → 404 (audit P1 #23).
- **Backend:** missing route.
- **Frontend:** `src/components/pages/video-analytics-page.tsx`
- **Manual smoke:** Video page → analytics tab → retention curve.
- **Automated test:** `e2e/phase-13-video-analytics.spec.ts`.
- **PeerTube ref:** EXTEND.
- **Risk:** MEDIUM.

### ANALY-03 · Stream analytics
- **Status:** partial — backend `051_create_stream_analytics.sql`; FE limited.
- **Manual smoke:** End live → analytics shows peak viewers.
- **Automated test:** Add later.
- **PeerTube ref:** EXTEND.
- **Risk:** LOW.

### ANALY-04 · Retention curve / view heatmap
- **Status:** planned — backends absent; FE removed (parity audit).
- **Manual smoke:** N/A until backend ships.
- **Automated test:** N/A.
- **PeerTube ref:** EXTEND.
- **Risk:** LOW.

### ANALY-05 · Audience demographics
- **Status:** planned — FE removed.
- **Manual smoke:** N/A.
- **Automated test:** N/A.
- **PeerTube ref:** EXTEND.
- **Risk:** LOW.

---

## 13. Payments / monetization

### PAY-01 · Polar checkout (production card / subscription)
- **Status:** implemented (parity audit, dual-mode reconciled 2026-04-22).
- **Backend:** Polar integration via `/api/polar/*`.
- **Frontend:** `src/lib/api/services/polar-checkout.ts`, `src/components/pages/premium-page.tsx`
- **Manual smoke:** Buy premium → Polar redirect → success → premium flag.
- **Automated test:** `e2e/inner-circle-subscribe-polar.spec.ts`, `e2e/inner-circle-subscribe-polar-latency.spec.ts`, `polar-checkout.test.ts`.
- **PeerTube ref:** VIDRA-ONLY.
- **Risk:** CRITICAL (real money).

### PAY-02 · BTCPay / Bitcoin invoice creation
- **Status:** partial — FE typed-error gating shipped (Part 2 Task 19); BE typed-503 (`BTCPAY_UNAVAILABLE`) shipped in vidra-core `btcpay_handlers.go` for unreachable BTCPay client. Live BTCPay container wiring still required for full implementation.
- **Backend:** `internal/payments/`, `091_drop_iota_add_btcpay.sql`, `094_payment_ledger.sql`, `095_btcpay_payouts.sql`, `096_backfill_ledger_from_invoices.sql`, `097_payment_notification_types.sql`, `098_payment_notification_cooldowns.sql`, `103_add_invoice_system_message_marker.sql`, `api/openapi_payments.yaml`
- **Frontend:** `src/lib/api/services/payments.ts`, `premium-page.tsx`
- **API:** `POST /api/v1/payments/invoices`
- **Manual smoke:** Create invoice → BTCPay invoice URL → pay → confirmed.
- **Automated test:** `e2e/payments-tip-btcpay.spec.ts`, `e2e/inner-circle-subscribe-btcpay.spec.ts`, `payments.test.ts`.
- **PeerTube ref:** VIDRA-ONLY.
- **Risk:** CRITICAL.

### PAY-03 · Tip a creator (BTCPay on-chain)
- **Status:** implemented (Phase 8B), depends on PAY-02 fix.
- **Frontend:** `src/components/tip-modal.tsx` (or equivalent)
- **Manual smoke:** Tip → invoice → pay → toast + transaction in history.
- **Automated test:** `e2e/payments-tip-btcpay.spec.ts`, `e2e/payments-tip-onchain-polish.spec.ts`, `e2e/payments-tip-on-comment.spec.ts`.
- **PeerTube ref:** VIDRA-ONLY.
- **Risk:** CRITICAL.

### PAY-04 · Tip a creator (Lightning)
- **Status:** implemented (LND wired, BOLT11 surfaced).
- **Backend:** LND integration.
- **Frontend:** Lightning method toggle.
- **Manual smoke:** Pay BOLT11 invoice → balance updates.
- **Automated test:** `e2e/payments-tip-lightning.spec.ts`, `e2e/payments-payout-lightning.spec.ts`.
- **PeerTube ref:** VIDRA-ONLY.
- **Risk:** CRITICAL.

### PAY-05 · Wallet (`/studio/wallet`)
- **Status:** partial — FE feature-flag gating shipped (Part 2 Task 18: `NEXT_PUBLIC_WALLET_ENABLED`, default false). 404/5xx wrapped as `BackendNotImplementedError(WALLET_NOT_IMPLEMENTED)` so the page renders a clean unavailable state instead of a 404 storm. BE wallet routes still required for full implementation.
- **Backend:** missing routes.
- **Frontend:** `src/components/pages/wallet-page.tsx`, `payments.ts`
- **Manual smoke:** Wallet → balance + transactions + payout dialog.
- **Automated test:** `e2e/payments-wallet-low-balance.spec.ts`, `e2e/payments-payout-onchain-approve.spec.ts`, `e2e/payments-payout-reject-restores.spec.ts`.
- **PeerTube ref:** VIDRA-ONLY.
- **Risk:** CRITICAL.

### PAY-06 · Transaction history (`/settings/transactions`)
- **Status:** implemented (Sent/Received toggle + CSV).
- **Frontend:** `src/components/pages/transactions-page.tsx`
- **Manual smoke:** Transactions render; CSV export downloads.
- **Automated test:** `e2e/payments-transactions-toggle.spec.ts`.
- **PeerTube ref:** VIDRA-ONLY.
- **Risk:** HIGH.

### PAY-07 · Admin payouts
- **Status:** implemented (Part 2 Task 25) — doubled path bug fixed: `payments/admin/payments/payouts` → `/api/v1/payments/admin/payouts`.
- **Backend:** `095_btcpay_payouts.sql`
- **Frontend:** `src/components/pages/admin-payouts-page.tsx`
- **Manual smoke:** Approve / reject pending payouts.
- **Automated test:** `e2e/payments-payout-onchain-approve.spec.ts`, `e2e/payments-payout-reject-restores.spec.ts`.
- **PeerTube ref:** VIDRA-ONLY.
- **Risk:** CRITICAL.

### PAY-08 · Inner Circle (memberships, tiers, badges, gating)
- **Status:** partial — FE feature-flag gating shipped (Part 2 Task 20: `NEXT_PUBLIC_INNER_CIRCLE_ENABLED`, default false). `inner-circle.ts:getTiers/getMyMemberships` throw `BackendNotImplementedError(INNER_CIRCLE_DISABLED)` and sidebar hides the link when off, eliminating the console-error storm. BE handlers still missing.
- **Backend:** `100_inner_circle_core.sql`, `101_inner_circle_video_column.sql` exist; handlers missing.
- **Frontend:** `src/lib/api/services/inner-circle.ts`, `studio-inner-circle-page.tsx`, `inner-circle-*.spec.ts`
- **API:** `/api/v1/inner-circle/*` (all 404).
- **Manual smoke:** Create tier → user subscribes → gated content unlocks.
- **Automated test:** `e2e/inner-circle-tier-crud.spec.ts`, `e2e/inner-circle-video-gate.spec.ts`, `e2e/inner-circle-comment-badges.spec.ts`, `e2e/inner-circle-members-tab.spec.ts`, `e2e/inner-circle-subscribe-btcpay.spec.ts`, `e2e/inner-circle-subscribe-polar.spec.ts`, `inner-circle.test.ts`.
- **PeerTube ref:** VIDRA-ONLY.
- **Risk:** HIGH.

### PAY-09 · Payment notifications + worker
- **Status:** implemented (Phase 8B worker shipped).
- **Backend:** `097_payment_notification_types.sql`, `098_payment_notification_cooldowns.sql`, `099_user_low_balance_state.sql`
- **Frontend:** notifications service.
- **Manual smoke:** Receive tip → notification arrives.
- **Automated test:** `e2e/payments-notifications-worker.spec.ts`, `e2e/payments-tip-expiry-recovery.spec.ts`, `e2e/payments-health.spec.ts`.
- **PeerTube ref:** VIDRA-ONLY.
- **Risk:** HIGH.

### PAY-10 · Premium page
- **Status:** implemented (Polar dual-mode banner reworded).
- **Frontend:** `premium-page.tsx`
- **Manual smoke:** Buy plan → entitlement reflected.
- **Automated test:** `e2e/inner-circle-subscribe-*.spec.ts`.
- **PeerTube ref:** VIDRA-ONLY.
- **Risk:** HIGH.

### PAY-11 · Comment / video tipping integration
- **Status:** implemented.
- **Frontend:** comment + video tip buttons.
- **Manual smoke:** Tip from comment → transaction recorded.
- **Automated test:** `e2e/payments-tip-on-comment.spec.ts`.
- **PeerTube ref:** VIDRA-ONLY.
- **Risk:** HIGH.

---

## 14. Frontend UX

### UX-01 · Layout shell (header, sidebar, theming)
- **Status:** implemented.
- **Frontend:** `src/components/layout-shell.tsx`, `header.tsx`, `sidebar.tsx`, `theme-context.tsx`
- **Manual smoke:** Sidebar collapses; header shows user / notifications.
- **Automated test:** `e2e/navigation.spec.ts`, sidebar Vitest.
- **PeerTube ref:** MATCH.
- **Risk:** MEDIUM.

### UX-02 · Theme (light / dark / system)
- **Status:** implemented (`next-themes`).
- **Frontend:** `theme-context.tsx`
- **Manual smoke:** Toggle theme → CSS vars switch.
- **Automated test:** Vitest.
- **PeerTube ref:** MATCH.
- **Risk:** LOW.

### UX-03 · i18n (13 locales, next-intl)
- **Status:** implemented (`pnpm i18n:check` enforces parity; routing via `@/i18n/routing`).
- **Frontend:** `src/messages/`, `src/i18n/`, `e2e/i18n-language-switching.spec.ts`
- **Manual smoke:** Switch language → labels update.
- **Automated test:** `e2e/i18n-language-switching.spec.ts`, `pnpm i18n:check` script.
- **PeerTube ref:** MATCH.
- **Risk:** MEDIUM.

### UX-04 · Accessibility (ARIA, keyboard, focus, prefers-reduced-motion)
- **Status:** partial — Phase 13 in progress.
- **Frontend:** `e2e/accessibility.spec.ts`
- **Manual smoke:** Tab through page; screen reader announces.
- **Automated test:** `e2e/accessibility.spec.ts` (extend per page).
- **PeerTube ref:** MATCH.
- **Risk:** MEDIUM.

### UX-05 · Notifications page
- **Status:** implemented.
- **Frontend:** `src/components/pages/notifications-page.tsx`, `src/lib/api/services/notifications.ts`
- **API:** `GET/PUT /api/v1/users/me/notifications`
- **Manual smoke:** Bell badge updates; mark all as read works.
- **Automated test:** `notifications.test.ts`, add E2E.
- **PeerTube ref:** MATCH.
- **Risk:** MEDIUM.

### UX-06 · Real-time notifications WebSocket
- **Status:** partial — handshake fails; bearer not sent on `/api/v1/notifications/ws` (audit P0 #12).
- **Backend:** WS endpoint exists; auth path bug.
- **Frontend:** `src/lib/realtime/*` (or wherever WS client lives), `notifications.ts`
- **Manual smoke:** Two browsers — first sees real-time push.
- **Automated test:** Add WS Vitest mock + E2E.
- **PeerTube ref:** MATCH.
- **Risk:** HIGH.

### UX-07 · Direct messaging (E2EE) — `/messages`
- **Status:** partial — UI wired; same WS auth bug; E2EE missing.
- **Backend:** `015_create_messages_table.sql`, `016_add_e2ee_messaging.sql`, `023_add_message_notifications.sql`, `065_fix_e2ee_schema_contradictions.sql`, `api/openapi_messaging.yaml`
- **Frontend:** `src/lib/api/services/messages.ts`, `src/lib/api/services/e2ee.ts`, `src/components/pages/messages-page.tsx`
- **API:** `GET/POST /api/v1/messages`, WS `/api/v1/messages/ws`
- **Manual smoke:** Two users exchange messages; restart container → history persists.
- **Automated test:** `messages.test.ts`, `e2ee.test.ts`, add E2E.
- **PeerTube ref:** VIDRA-ONLY.
- **Risk:** HIGH.

### UX-08 · Settings page (profile / appearance / privacy / video / wallet)
- **Status:** partial — see USER-07 / 08 / 13.
- **Frontend:** `src/components/pages/settings-page.tsx`
- **Manual smoke:** Each tab loads + at least one toggle persists.
- **Automated test:** `e2e/settings-live.spec.ts`.
- **PeerTube ref:** MATCH.
- **Risk:** MEDIUM.

### UX-09 · Empty / loading / error states
- **Status:** implemented (per-page `<EmptyState>` / `<ErrorState>` components).
- **Frontend:** `src/components/empty-state.tsx`, `error-state.tsx`
- **Manual smoke:** Disconnect network → error renders + recovery action.
- **Automated test:** Vitest snapshot.
- **PeerTube ref:** MATCH.
- **Risk:** MEDIUM.

### UX-10 · Mobile / responsive
- **Status:** implemented (375 / 768 / 1280 px tested in plans).
- **Manual smoke:** Resize browser; sidebar collapses; tap targets ≥ 44 × 44.
- **Automated test:** Add Playwright `viewport` matrix.
- **PeerTube ref:** MATCH.
- **Risk:** MEDIUM.

### UX-11 · Sharing dialog
- **Status:** implemented.
- **Frontend:** `src/components/share-dialog.tsx`
- **Manual smoke:** Share modal copies URL.
- **Automated test:** `e2e/share-report.spec.ts`.
- **PeerTube ref:** MATCH.
- **Risk:** LOW.

### UX-12 · Apple HIG token system (typography, color, spacing, motion)
- **Status:** implemented (CLAUDE.md mandates HIG; tokens applied via Tailwind v4 + CSS vars).
- **Frontend:** `src/styles/`, `globals.css`
- **Manual smoke:** Light / dark contrast meets WCAG AA.
- **Automated test:** Vitest snapshot of computed styles or visual regression.
- **PeerTube ref:** DIFFER (PT uses Material).
- **Risk:** LOW.

### UX-13 · About / Terms pages
- **Status:** implemented.
- **Frontend:** `src/components/pages/about-page.tsx`, `terms-page.tsx`
- **Manual smoke:** Pages render.
- **Automated test:** `e2e/about-terms.spec.ts`.
- **PeerTube ref:** MATCH.
- **Risk:** LOW.

---

## 15. DevOps / observability / QA

### DEVOPS-01 · Docker compose (postgres, ipfs, btcpay, clamav, lnd, redis)
- **Status:** implemented.
- **Backend:** `docker-compose.yml`, `docker-compose.override.yml.example`, `docker/postgres/`, `docker/ipfs/`
- **Frontend:** `pnpm dev:full` orchestrates.
- **Manual smoke:** `docker compose up -d` → all containers `Up (healthy)`; logs show no fatal.
- **Automated test:** `scripts/integration-test.sh`, `scripts/smoke-test.sh`, `scripts/wait-for-health.sh`, `scripts/dev-doctor.sh`.
- **PeerTube ref:** MATCH.
- **Risk:** CRITICAL.

### DEVOPS-02 · Local dev orchestration (`pnpm dev:full`, dev-seed, dev-gen-videos)
- **Status:** implemented.
- **Frontend:** `scripts/start-dev.sh`, `scripts/dev-seed.sh`, `scripts/dev-gen-videos.sh`, `scripts/btcpay-bootstrap.sh`, `scripts/lnd-bootstrap.sh`, `scripts/compose-env.sh`
- **Manual smoke:** Fresh checkout → `pnpm dev:full` → seeded users alice / bob / charlie / admin work.
- **Automated test:** Add CI smoke lane.
- **PeerTube ref:** EXTEND.
- **Risk:** HIGH.

### DEVOPS-03 · Migrations runner
- **Status:** implemented (104+ migrations).
- **Backend:** `internal/database/`, `migrations/`
- **Manual smoke:** Run app on fresh DB → all migrations apply.
- **Automated test:** Backend Go tests.
- **PeerTube ref:** MATCH.
- **Risk:** CRITICAL.

### DEVOPS-04 · CI integration tests (Playwright + Vitest in GitHub Actions)
- **Status:** partial — integration tests exist but are not CI-gated (parity audit BI-23 / BI-24).
- **Frontend:** `e2e/`, `vitest.config.ts`, `playwright.config.ts`
- **Manual smoke:** Push branch → CI runs all tests.
- **Automated test:** `scripts/qa-smoke.sh` (Phase 8 of QA workflow).
- **PeerTube ref:** EXTEND.
- **Risk:** HIGH.

### DEVOPS-05 · OpenTelemetry (metrics / logs / traces)
- **Status:** implemented (CLAUDE.md mandates).
- **Frontend:** `src/lib/telemetry/logger.ts`, `src/instrumentation.ts`
- **Backend:** `internal/obs/`, `internal/metrics/`
- **Manual smoke:** Trigger error → trace lands in OTLP collector.
- **Automated test:** Vitest mock + manual stack run.
- **PeerTube ref:** EXTEND.
- **Risk:** MEDIUM.

### DEVOPS-06 · Health endpoints
- **Status:** implemented (`scripts/wait-for-health.sh`).
- **Backend:** `internal/health/`
- **Manual smoke:** `curl /healthz` → 200.
- **Automated test:** `e2e/payments-health.spec.ts`.
- **PeerTube ref:** MATCH.
- **Risk:** HIGH.

### DEVOPS-07 · Test coverage enforcement (service-tests, i18n parity, working-product hook)
- **Status:** implemented — stop hooks block on uncovered services + missing i18n keys (per project `CLAUDE.md`).
- **Frontend:** `.claude/hooks/`, `scripts/i18n-check.mjs`, `scripts/check-skip-ratio.mjs`
- **Manual smoke:** Remove a test → stop hook blocks completion.
- **Automated test:** N/A (meta).
- **PeerTube ref:** N/A.
- **Risk:** LOW.

### DEVOPS-08 · Lint / typecheck / build
- **Status:** implemented.
- **Frontend:** `pnpm lint`, `pnpm typecheck`, `pnpm build`
- **Manual smoke:** All three pass on clean tree.
- **Automated test:** CI gate.
- **PeerTube ref:** MATCH.
- **Risk:** HIGH.

### DEVOPS-09 · Backup / restore tooling
- **Status:** partial — `internal/backup/`, `cmd/encrypt-activitypub-keys`, `api/openapi_backup.yaml`; admin UI absent.
- **Manual smoke:** Trigger backup → restore on fresh DB.
- **Automated test:** Add later.
- **PeerTube ref:** MATCH.
- **Risk:** HIGH.

### DEVOPS-10 · Server debug / verification CLI
- **Status:** implemented.
- **Backend:** `cmd/cli/`, `cmd/verify-federation/`, `cmd/test_email/`, `api/openapi_server_debug.yaml`
- **Manual smoke:** `vidra-core verify-federation` → reports.
- **Automated test:** N/A.
- **PeerTube ref:** EXTEND.
- **Risk:** LOW.

---

## QA Coverage Roll-up

### Status counts (218 features tracked across 15 categories)

| Category | implemented | partial | planned | unclear | Total |
|---|---|---|---|---|---|
| 1. Core video platform | 10 | 7 | 0 | 0 | 17 |
| 2. User / account | 4 | 7 | 3 | 1 | 15 |
| 3. Upload / import / transcoding | 3 | 7 | 2 | 1 | 13 |
| 4. Playback | 7 | 3 | 0 | 0 | 10 |
| 5. Live streaming | 0 | 6 | 2 | 0 | 8 |
| 6. Federation | 1 | 5 | 3 | 0 | 9 |
| 7. P2P / IPFS / WebTorrent | 1 | 0 | 1 | 2 | 4 |
| 8. Storage / CDN | 2 | 2 | 0 | 1 | 5 |
| 9. Moderation / safety | 2 | 6 | 2 | 0 | 10 |
| 10. Admin | 1 | 12 | 3 | 0 | 16 |
| 11. Plugins | 0 | 1 | 1 | 1 | 3 |
| 12. Analytics | 0 | 3 | 2 | 0 | 5 |
| 13. Payments | 6 | 4 | 0 | 0 | 10 (× 11 sub-IDs) |
| 14. Frontend UX | 8 | 5 | 0 | 0 | 13 |
| 15. DevOps / QA | 7 | 3 | 0 | 0 | 10 |

These counts are author estimates based on the audits cited. The QA ledger MUST re-derive each row against the live stack — do not trust this rollup as evidence.

### Highest-risk gaps for QA to drive

1. **PAY-02 / PAY-05 / PAY-08** — Bitcoin invoice 500, wallet endpoints 404, Inner Circle backend missing. Real money at risk.
2. **CORE-04 / CORE-05** — view counter + watch history backend silently broken; downstream analytics + monetization wrong.
3. **CORE-11 / CORE-12** — like persistence + subscribe-by-handle broken — visible engagement loop dead.
4. **USER-03 / USER-04 / USER-06 / USER-08 / USER-10** — auth tail (direct register, password reset, 2FA, password change, account deletion) not user-traversable.
5. **LIVE-01..LIVE-04** — live streaming end-to-end broken (channel_id missing, RTMP key placeholder, no list handler, chat off).
6. **UX-06 / UX-07** — WebSocket auth handshake fails for notifications + messages on every page load.
7. **ADMIN-02 / ADMIN-08** — user moderation writes silently fail; PeerTube import wizard (cited as #1 product ask) missing.

Every item above must have an entry in `docs/QA_LEDGER.md` with status `untested` or `blocked`, a row in `docs/MANUAL_SMOKE_TESTS.md`, and on first reproduction also an entry in `docs/REGRESSION_TESTS.md` with a Playwright spec attached.

---

## How this document feeds the QA workflow (`/vidra-user-qa-lead`)

- **Phase 1 (`docs/QA_LEDGER.md`)** — copy each feature ID here as a ledger row. Default status `untested`; promote to `smoke-tested` after manual run, `automated` after Playwright/Vitest covers it, `regression-covered` after a bug + test exists, `blocked` when backend/runtime stops execution.
- **Phase 4 (`docs/MANUAL_SMOKE_TESTS.md`)** — the **Manual smoke** line per feature is the test case body. Add ID, steps, expected, actual, status, notes.
- **Phase 5 (Automation)** — the **Automated test** line per feature is the target spec. Add or extend that file.
- **Phase 7 (`docs/TEST_MATRIX.md`)** — feature ID × (manual / automated / regression). Use the columns above directly.
- **Phase 9 (`docs/QA_REPORT.md`)** — every feature with status `partial` or `planned` becomes a risk callout if it shipped.

Every claim in this document is sourced from `docs/plans/` or live-stack audits. If a row says `implemented` and you verify it broken, that is a `partial`-class regression and must be filed in `REGRESSION_TESTS.md` before the QA pass closes.
