# Vidra User Ralph Fix Plan

> Repo target: `vidra-user` only.
> Ralph must not modify `vidra-core` from this repo. Backend tasks belong in the backend repository and are tracked here only as API contract dependencies.

## 🔴 Critical Verification Rule: Real Database Effects

A frontend feature that talks to the backend is **NOT done** until Ralph has proven
the change actually reached the database AND is reflected back in the UI. Mocked
API responses are acceptable for UI scaffolding only — never as completion evidence
for a feature that mutates real data.

For any feature that creates, updates, or deletes data, Ralph must demonstrate the
full round trip:

1. Perform the action in the running frontend (real `vidra-core` backend, not mocks).
2. Confirm the backend persisted it (query the database directly, or via a backend
   read endpoint) and capture that evidence.
3. Confirm the change is visible in the frontend after a fresh load/refetch
   (not just optimistic local state).
4. Capture evidence: a Playwright trace/screenshot showing the UI state plus the
   database row / API read confirming persistence.

If `vidra-core` does not yet expose the contract needed to prove persistence, mark
the item `BLOCKED` on the backend dependency — do not mark it `VERIFIED` on mocks.

## Operating Rules

- [ ] Before every loop, read `.ralph/PROMPT.md`, this `fix_plan.md`, `.ralph/AGENT.md`, and all files in `.ralph/specs/`.
- [ ] Work on one coherent vertical slice per loop.
- [ ] Search the codebase before adding routes, components, state, API clients, tests, or config.
- [ ] Keep PeerTube parity evidence current: feature ledger, UI/control inventory, route inventory, acceptance notes, and test evidence.
- [ ] Never mark a route/control `VERIFIED` without evidence: component tests, Playwright tests, screenshots/logs, backend contract, or manual QA notes.
- [ ] For any data-mutating feature, `VERIFIED` requires proof the change hit the real database AND is visible in the frontend after refetch (see Critical Verification Rule above). Mocks alone never satisfy `VERIFIED`.
- [ ] Never set `EXIT_SIGNAL: true` until every in-scope parity item and Vidra extension is `VERIFIED`, `INTENTIONAL_DIFFERENCE`, or explicitly deferred by the user.
- [ ] Keep commits small and descriptive.
- [ ] Do not store secrets, production credentials, OAuth secrets, stream keys, or wallet private keys in the repo.
- [ ] Do not copy PeerTube source code, assets, branding, screenshots, or exact styling. Use PeerTube only as behavioral reference.
- [ ] Avoid UI frameworks. Use custom components, Tailwind CSS, and minified inline/local SVG icons unless a dependency is clearly justified.

## Definition of Done for Any UI Feature

- [ ] Requirement is listed in the correct ledger.
- [ ] Route and controls are listed in `.ralph/specs/peertube-ui-inventory.md`.
- [ ] API contract dependency is documented.
- [ ] Loading, empty, success, error, and permission states are implemented.
- [ ] Keyboard and screen-reader behavior is considered.
- [ ] Responsive behavior is implemented.
- [ ] Component/unit tests cover logic.
- [ ] Integration tests cover API-client behavior.
- [ ] Playwright smoke/e2e tests cover critical path.
- [ ] For data-mutating features: end-to-end test against the real `vidra-core` backend proves the database changed and the change is visible in the UI after refetch (database/API read evidence + Playwright trace captured).
- [ ] `.ralph/fix_plan.md`, relevant ledger rows, and `.ralph/AGENT.md` are updated.
- [ ] Focused checks pass locally or the failure is documented as a blocker.

---

# P0 — Ralph Control Plane and Parity Tracking

## P0.1 Required Ralph Files

- [ ] Verify `.ralph/PROMPT.md` exists and includes Vidra-specific rules.
- [ ] Verify `.ralph/AGENT.md` exists and has accurate frontend commands.
- [ ] Verify `.ralph/specs/` exists.
- [ ] Verify `.ralph/specs/peertube-reference.md` exists.
- [ ] Verify `.ralph/specs/peertube-feature-ledger.md` exists.
- [ ] Verify `.ralph/specs/peertube-ui-inventory.md` exists.
- [ ] Verify `.ralph/specs/vidra-extensions-ledger.md` exists.
- [ ] Verify `.ralph/specs/parity-acceptance.md` exists.
- [ ] Add or update ledger status vocabulary: `TODO`, `IN_PROGRESS`, `IMPLEMENTED`, `TESTED`, `VERIFIED`, `INTENTIONAL_DIFFERENCE`, `DEFERRED`.
- [ ] Add evidence fields to ledgers: owner repo, routes, controls, API endpoints, tests, screenshots/logs, notes, verification date.

## P0.2 PeerTube UI and Feature Inventory

- [ ] Pin PeerTube reference version/date used for UI parity analysis.
- [ ] Inventory public routes: home, local videos, trending/popular/recent, search, watch, embed, account, channel, playlist, about.
- [ ] Inventory auth routes: login, signup, signup terms, email verification, password reset, MFA.
- [ ] Inventory user routes: library, history, watch later, playlists, subscriptions, notifications, settings.
- [ ] Inventory publishing routes: file upload, URL import, torrent/magnet import, live publishing.
- [ ] Inventory studio routes: my videos, quick edit, video detail edit, statistics, channel management, remote channel sync.
- [ ] Inventory moderation routes: reports, video blocks, comments, watched words, muted accounts, muted instances.
- [ ] Inventory admin routes: overview, users, registration requests, configuration, federation, jobs, logs/status.
- [ ] Inventory player controls: play/pause, seek, volume, captions, settings, quality, speed, fullscreen, theater/embed, share, download, report, save.
- [ ] Inventory list/card controls: subscribe, mute, report, playlist quick-add, watch later, overflow menu, pagination/infinite scroll.
- [ ] Inventory forms: field labels, validation, helper text, submit/cancel buttons, disabled states, error states.
- [ ] Map every route/control to required backend endpoint or mark backend dependency pending.

---

# P1 — Frontend Project Foundation

## P1.1 Next.js, TypeScript, Tailwind

> P1 foundation slice landed: Next 16 (app router) + React 19 + strict TS + Tailwind v4
> + ESLint 9 flat config + Vitest + Playwright, with a green canonical `npm run ci`
> (typecheck + lint + unit + build + e2e smoke). Structured logger in `lib/logger.ts`
> with a redaction denylist + `no-console` ESLint rule (observability spec). Component
> primitives, the typed API client, and the backend-backed Playwright profile are
> follow-up P1 slices.

- [x] Initialize or verify Next.js app. (Next 16 app router; scaffolded via create-next-app then adapted; `npm run dev|build|start`.)
- [x] Verify strict TypeScript configuration. (`tsconfig.json` `strict: true`; `npm run typecheck` = `tsc --noEmit`, green.)
- [x] Configure Tailwind CSS. (Tailwind v4 via `@tailwindcss/postcss`; `app/globals.css` `@import "tailwindcss"`.)
- [x] Add path aliases. (`@/*` → project root.)
- [x] Add ESLint configuration. (`eslint.config.mjs` flat config: next core-web-vitals + typescript + `no-console: error`.)
- [ ] Add Prettier or formatting command if desired.
- [x] Add app directory routing conventions. (`app/layout.tsx` + `app/page.tsx`.)
- [~] Add global styles and design tokens. (`app/globals.css` base + Tailwind theme tokens; full design-system tokens are a later slice.)
- [ ] Add custom component primitives: Button, LinkButton, IconButton, Input, Textarea, Select, Checkbox, Radio, Toggle, Modal, Dropdown, Tabs, Toast, Card, Badge, Avatar, Skeleton, EmptyState, ErrorState.
- [ ] Add accessible focus styles.
- [ ] Add minified SVG icon strategy.
- [x] Add no-framework dependency rule to docs. (`.ralph/AGENT.md` Stack: no UI framework / component library without user approval.)

## P1.2 Configuration and API Client

- [x] Add `.env.example`. (`NEXT_PUBLIC_API_BASE_URL`, `LOG_LEVEL`, `OTEL_ENABLED`.)
- [x] Add `NEXT_PUBLIC_API_BASE_URL`. (in `.env.example`; the typed config module that reads it is a follow-up.)
- [~] Add server-side API base URL option if needed. (one `apiBaseUrl` from `NEXT_PUBLIC_API_BASE_URL` works server + client; a separate internal URL can be added if SSR needs it.)
- [x] Add typed config module. (`lib/config.ts` — `apiBaseUrl` (trailing-slash trimmed), `otelEnabled`.)
- [x] Add API client foundation. (`lib/api/client.ts` `apiRequest<T>` fetch wrapper + typed `api.*` endpoint fns in `lib/api/endpoints.ts`: instance, feed (sort/page), video detail, search, channel, channel videos; plus `videoOriginalUrl`/`videoThumbnailUrl` helpers. Vitest-covered with mocked fetch — 16 tests.)
- [~] Add auth token storage strategy. (the client accepts an optional bearer `token` per call and never logs it; token *storage*/refresh is P3.)
- [ ] Add refresh/session handling strategy.
- [x] Add standardized error mapping. (`ApiError` maps the `{error:{code,message,request_id,fields}}` envelope; non-envelope → generic `http_error`; network failure → `network_error`.)
- [x] Add request ID propagation if backend supports it. (every call sends `X-Correlation-ID`, which vidra-core accepts/echoes; W3C `traceparent` lands with the OTel instrumentation slice.)
- [x] Add generated or hand-maintained API types until backend OpenAPI exists. (`lib/api/types.ts` mirrors the OpenAPI schemas: Instance, Video, feed/list/search responses, Channel, error envelope.)
- [x] Mark all provisional API types as pending backend contract. (`lib/api/types.ts` header: PROVISIONAL — keep in lock-step with the backend OpenAPI.)

## P1.3 Docker-First Development

- [ ] Add Dockerfile.
- [ ] Add Docker Compose service for frontend.
- [ ] Add Compose override or profile to run frontend with local backend containers.
- [ ] Add env option to point to remote backend.
- [ ] Add Makefile or task runner commands: `dev`, `build`, `test`, `lint`, `playwright`, `docker-up`, `docker-down`.
- [ ] Document how to run frontend only.
- [ ] Document how to run frontend against local backend.
- [ ] Document how to run frontend against remote backend.

## P1.4 CI Skeleton

> NOTE (monorepo): GitHub Actions workflows live at the repository root in
> `../.github/workflows/` (GitHub does not read workflows from subdirectories).
> Frontend workflows must use `vidra-user/**` path filters and a `vidra-user`
> working directory. This is the one allowed cross-boundary edit from this repo.

- [ ] Add a canonical `ci` package script = typecheck + lint + unit + build + Playwright smoke (the single source of truth gate).
- [ ] Add `frontend-ci.yml` that runs **exactly** `npm run ci` (path-scoped `vidra-user/**`) so local and CI are the same gate — do not duplicate/weaken steps in the workflow.
- [ ] Keep `ci-guard.yml` green (it enforces that `frontend-ci.yml` invokes `npm run ci` and uses no unmarked `continue-on-error`).
- [ ] Add Docker build check.
- [ ] Add shared/reusable workflow or composite action for Node setup.
- [ ] Add npm/pnpm/yarn cache.
- [ ] Add Playwright browser cache.
- [ ] Add artifact upload for Playwright traces/screenshots.

## P1.5 Observability and Logging (see `.ralph/specs/observability.md`)

- [ ] Add a single structured logger module (`lib/logger`): JSON server-side, browser-safe client path, configurable level.
- [ ] Add ESLint `no-console` (error) with a narrow allow-list only inside the logger module; wire `lint` into `npm run ci`.
- [ ] Add a redaction helper + denylist; never log tokens/cookies/secrets/PII/message plaintext; never write tokens to `localStorage`.
- [ ] Add a secrets-in-logs / token-in-storage check (lint rule or test/grep).
- [ ] Bind a `request_id`/`correlation_id` per request and thread it through server logs.
- [ ] Add OpenTelemetry via `instrumentation.ts` (OTel JS SDK), disabled by default; config `OTEL_ENABLED`, `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_SERVICE_NAME` in `.env.example`.
- [ ] Inject W3C `traceparent` (+ correlation header) on every server-side fetch to `vidra-core`; add a test asserting propagation.
- [ ] Stamp `trace_id`/`span_id` into server logs when OTel is enabled.

---

# P2 — App Shell and Navigation

- [x] Implement root layout. (`app/layout.tsx` renders `<Header/>` + page; sticky header, flex column shell.)
- [~] Implement responsive header. (`components/Header.tsx`: brand link + Home nav, sticky/backdrop. Full responsive nav + collapse is a later slice.)
- [ ] Implement left navigation.
- [ ] Implement mobile navigation.
- [x] Implement search bar shell. (`components/SearchBox.tsx` in the header → navigates to `/search?q=`.)
- [ ] Implement user menu shell.
- [x] Implement theme/accessibility-friendly base styles. (Tailwind base + dark-mode-aware tokens in `globals.css`; focus-visible rings on interactive elements.)
- [x] Implement public home route. (`app/page.tsx` → `<VideoFeed/>` discovery grid.)
- [~] Implement loading and error boundaries. (`VideoFeed` handles loading/error/empty/ready inline via `ui/Spinner`, `ui/ErrorState` (retry), `ui/EmptyState`; route-level error.tsx/loading.tsx boundaries still TODO.)
- [ ] Implement 404 page.
- [x] Add Playwright smoke test for app loading. (`e2e/home.spec.ts`: header brand present; route-mocked feed renders cards; empty + error states — 4 tests.)
- [ ] Add accessibility smoke test for navigation landmarks.

---

# P3 — Auth and Account UI

- [x] Implement login page. (`app/login/page.tsx` → `components/auth/LoginForm.tsx`: email/password, loading + error states, 401 → "Invalid email or password", redirects home on success. Session plumbing: `components/auth/AuthProvider.tsx` (context + `useSession`), in-memory `lib/api/auth-store.ts` access token auto-attached by the API client, `lib/api/auth.ts` (register/login/logout/me), header `AccountMenu` (sign in / username + sign out).)
- [x] Implement signup page. (`app/signup/page.tsx` → `components/auth/SignupForm.tsx`: username/email/password via `useSession().register`; 422 `ApiError.fields` mapped to inline per-field messages (aria-invalid/aria-describedby); redirects home on success.)
- [x] Implement signup disabled/closed registration state. (SignupForm reads `GET /api/v1/instance` `registration_enabled`; when false shows a "Registration is closed" notice instead of the form; instance-fetch failure falls back to showing the form.)
- [ ] Implement terms-of-use signup step.
- [ ] Implement email verification pending state.
- [ ] Implement password reset request page.
- [ ] Implement password reset complete page.
- [ ] Implement TOTP/MFA challenge page.
- [ ] Implement TOTP enrollment page.
- [ ] Implement recovery codes UI.
- [~] Implement logout flow. (`AccountMenu` sign-out → `useSession().logout()` clears the in-memory token/user and best-effort POSTs /auth/logout with the refresh token.)
- [x] Implement account settings page. (`app/settings/page.tsx` → `components/auth/SettingsView.tsx`, auth-gated: shows a sign-in prompt when the in-memory session is gone (hard reload), else the profile form + a deactivate "danger zone". Reached via the header username link (`AccountMenu` → `/settings`, client-side nav so the session survives).)
- [x] Implement account deactivation UI. (`SettingsView` `DeactivateSection`: a password-confirmed danger zone → `POST /api/v1/auth/me/deactivate` via new `authApi.deactivate` + `useSession().deactivate` (clears the local session); on success redirects home signed out, wrong password → "Incorrect password." **VERIFIED** end-to-end — see the backed e2e below. Mocked: signs-out-on-success + wrong-password-error in `e2e/settings.spec.ts`.)
- [x] Implement profile edit form. (`SettingsView` `ProfileForm`: display name + bio, prefilled from the session user (`key={user.id}`); `PATCH /api/v1/auth/me` via new `authApi.updateMe` + `useSession().updateProfile`; idle/saving/saved states, 422 field errors mapped inline, "Profile saved." confirmation. **VERIFIED** end-to-end — see the backed e2e below. Mocked tests `e2e/settings.spec.ts` (save confirmation, 422 inline, signed-out prompt — 3).)
- [ ] Implement avatar/banner upload UI.
- [ ] Implement import/export account UI placeholders backed by contract status.
- [~] Add unit tests for validation. (auth client + token store unit-tested — 6; form-field validation tests can follow.)
- [x] Add Playwright auth smoke tests with mocked API. (`e2e/auth.spec.ts`: login success → header shows account; bad-creds error; signup success → account; 422 field-error inline; registration-closed notice.)
- [~] Add backend-backed auth e2e tests when backend contract exists, proving signup/login/profile-edit persist to the database and are reflected in the UI after refetch. **Signup + login VERIFIED**: the `backend-backed` Playwright project (`e2e-backed/auth-persistence.spec.ts`, `npm run e2e:backed`) drives the UI against a real vidra-core + PostgreSQL (docker compose `core` profile), signs up → signs out → logs back in with the same credentials (a fresh DB round-trip), and passes. Evidence captured: the UI-created row in Postgres (`psql … users WHERE email LIKE 'e2e-%'`) + a Playwright trace (`trace: "on"`). **Profile-edit also VERIFIED**: `e2e-backed/profile-edit.spec.ts` signs up → edits the display name on the settings page → saves → signs out → signs back in → the new display name is still shown (a fresh DB round-trip); DB evidence captured (`psql … display_name`). The profile is intentionally NOT part of `npm run ci` (kept mocked/fast); see `.ralph/AGENT.md` for the run procedure. **Deactivate also VERIFIED**: `e2e-backed/deactivate.spec.ts` signs up → deactivates (password confirm) → a fresh login with the same credentials is refused ("account is disabled"); DB evidence captured (`psql … is_active=f`). All backed specs use a `randomUUID` email/username so they're collision-free under parallel runs. **CI-automated**: the root `frontend-e2e-backed.yml` workflow stands up the compose `core` stack and runs `npm run e2e:backed` on every push/PR touching either project, so the backed coverage is enforced (not just local). The auth rate-limit headroom that previously capped the backed suite is RESOLVED: the compose api now honours `RATE_LIMIT_ENABLED` (env-overridable, default true) and `frontend-e2e-backed.yml` + the local procedure set `RATE_LIMIT_ENABLED=false`, so the suite can grow without throttling (verified: 3 back-to-back local runs pass without a redis flush, where run 2 previously failed). Still pending: backed coverage for the email-token flows (password-reset/email-verify), BLOCKED on a dev-only token-retrieval affordance in vidra-core.

---

# P4 — Public Video Browsing and Watch Page

## P4.1 Browse and Search

- [~] Implement local/recent videos page. (home `<VideoFeed/>` shows the recent public feed; a dedicated /local route + sort UI is a later slice.)
- [ ] Implement trending/popular page or documented intentional difference.
- [x] Implement search results page. (`app/search/page.tsx` (reads `?q`) → `components/SearchResults.tsx`: client title search via `api.searchVideos`, with idle/loading/error(retry)/empty/grid states reusing `VideoCard` + the ui primitives.)
- [ ] Implement filter/sort controls.
- [ ] Implement pagination or infinite scroll.
- [x] Implement video card component. (`components/VideoCard.tsx`: poster via `videoThumbnailUrl` with "No preview" fallback, title (clamped), `formatCount` views · `relativeTime`; links to `/videos/{id}`. **Now also links to the owning channel**: when the card carries `channel_handle` (all card/feed endpoints provide it), it renders the channel name (`channel_display_name || channel_handle`) as a sibling link to `/channels/{handle}` — the card is a `<div>` with separate video + channel links (no nested anchors). This makes channel pages reachable from the UI. `lib/format.ts` tested — 4 unit tests; `e2e/home.spec.ts` asserts each card links to `/channels/{handle}` with the channel name.)
- [x] Implement public channel page. (`app/channels/[handle]/page.tsx` → `components/ChannelView.tsx`: client load of `api.getChannel` + `api.listChannelVideos`, header (display name, `@handle · N followers`, description) + `VideoCard` grid, with loading / not-found (404) / error(retry) / empty states. `e2e/channel.spec.ts` route-mocks header+videos and the 404 case — 2 tests. Following is a later auth-gated slice.)
- [ ] Implement channel/account card component.
- [ ] Implement playlist card component.
- [x] Implement empty/no-results states. (`components/ui/EmptyState.tsx`, used by `VideoFeed`.)
- [x] Implement search error states. (`SearchResults` renders `ErrorState` with retry on a failed search.)
- [~] Add component tests for cards and filters. (card rendering covered by the route-mocked Playwright grid + search tests; pure formatters unit-tested. RTL component-unit tests can follow.)
- [x] Add Playwright smoke test for search route. (`e2e/search.spec.ts`: results, empty, blank-query prompt, and header-search navigation — 4 tests.)

## P4.2 Watch Page

- [x] Implement video watch route. (`app/videos/[id]/page.tsx` → `components/WatchView.tsx`, the destination feed cards link to.)
- [~] Implement custom video player wrapper. (native `<video controls playsInline>` over the Range-capable `videoOriginalUrl`, with `has_thumbnail` poster; a custom-controls wrapper (quality/speed/captions/shortcuts) is a later slice.)
- [x] Implement play/pause. (native controls)
- [x] Implement timeline/seek. (native controls; backend serves HTTP Range so seeking works)
- [x] Implement volume/mute. (native controls)
- [ ] Implement captions toggle.
- [ ] Implement quality selector.
- [ ] Implement speed selector.
- [x] Implement fullscreen. (native controls)
- [ ] Implement keyboard shortcuts where specified.
- [~] Implement title/description/tags/category/license/language display. (title, description, views · date, duration + dimensions chips shown; tags/category/license/language need backend fields/contract.)
- [x] Implement channel block with subscribe button. (`ChannelView` renders a `SubscribeButton` in the channel header: anonymous → a "Sign in to subscribe" link (mock-tested in `e2e/channel.spec.ts`); authenticated → a Subscribe/Subscribed toggle calling `api.followChannel`/`unfollowChannel` (`POST`/`DELETE /channels/:handle/follow`) with an optimistic follower-count nudge. **VERIFIED** end-to-end: `e2e-backed/subscribe.spec.ts` seeds a channel + published video via the API (`e2e-backed/fixtures.ts` — a base64 tiny H.264 mp4 the real ffprobe accepts), a fresh viewer signs up in the UI, reaches the channel page by clicking the video card's channel link (client-side nav), clicks Subscribe → button shows "Subscribed" and the channel's `follower_count` goes **0 → 1 in Postgres** (asserted via the API; `channel_follows` rows confirmed by `psql`). Runs in CI via `frontend-e2e-backed.yml`.)
- [ ] Implement share button/dialog.
- [ ] Implement download button/dialog.
- [x] Implement save/watch-later/playlist button. (save/watch-later done; named playlists deferred.) VERIFIED end-to-end against a real backend. `components/SaveButton.tsx` on the watch page (next to the rating controls): a ★ Save / Saved toggle reflecting `aria-pressed`; on mount (authed) it reads `GET /me/saved` (limit 100) to show the correct initial state, then toggles via `POST`/`DELETE /videos/:id/save`; anon viewers get a "Sign in to save" link. API client gained `saveVideo`/`unsaveVideo`/`getSavedVideos`. Mocked: `e2e/save.spec.ts` (library anon prompt; library lists saved; watch-page Save → Saved). Persistence proof: `e2e-backed/save.spec.ts` — signup → watch page → Save → button flips AND the video appears in `/library` after a fresh refetch; also confirmed via direct `psql` (the `saved_videos` row by `fan<id>`).
- [x] Implement report button/dialog. (`components/ReportButton.tsx` on the watch-page controls row (`kind="video"`) + per-comment (`kind="comment"`): authed → accessible report modal (reason textarea → `POST /videos|comments/:id/report`); anon → "Sign in to report". **VERIFIED** end-to-end via the admin moderation queue read-back — see P9 + `e2e-backed/report.spec.ts`.)
- [x] Implement like/dislike/reaction controls if in-scope. VERIFIED end-to-end against a real backend. `components/RatingControls.tsx` on the watch page (under the title): 👍/👎 buttons with counts (`formatCount`), the held rating highlighted via `aria-pressed`; clicking toggles (set → switch → clear) with the server's returned summary as source of truth; anon viewers see read-only counts + a "Sign in to rate" link (buttons disabled). API client gained `getVideoRating`/`setVideoRating`/`clearVideoRating` + `RatingValue`/`VideoRating` types (and `PUT` added to the request method union). Mocked: `e2e/rating.spec.ts` (anon disabled + prompt; authed like → `aria-pressed` flips). Persistence proof: `e2e-backed/rating.spec.ts` — signup → watch page → Like → button reflects it AND `like_count` reads back 1 via the API; also confirmed via direct `psql` (the `like` row by `fan<id>`).
- [x] Implement comments section. VERIFIED end-to-end against a real backend. `components/CommentsSection.tsx` on the watch page: lists a public video's comments newest-first (`Comments (N)` heading, author display name + relative time), an auth-gated post form (anon → "Sign in to leave a comment"; authed → textarea + Post, optimistic prepend from the API response), and a Delete control on your own comments (filtered out on success). API client gained `getVideoComments`/`postComment`/`deleteComment` + `Comment`/`CommentListResponse` types. Mocked coverage: `e2e/comments.spec.ts` (render + anon prompt; authed post). Persistence proof: `e2e-backed/comments.spec.ts` — signup → watch page (client-side nav) → post → comment appears AND is read back via the API; also confirmed via direct `psql` (the `lovely clip <id>` row authored by `fan<id>`).
- [ ] Implement related videos section.
- [x] Implement watched progress/resume UI. VERIFIED end-to-end against a real backend. The watch page (`components/WatchView.tsx` → `Player`) reports playback progress for a signed-in viewer — throttled `timeupdate` (≤1/10s), plus on `pause` and on unmount — via `PUT /api/v1/videos/:id/watch-progress`, so the video enters their history and its resume position is saved. On mount it reads `GET /api/v1/videos/:id/watch-progress` and, when the saved position ≥ 5s, surfaces a "Resume from m:ss" button that seeks the `<video>` to that position. API client gained `recordWatchProgress`/`getWatchProgress` + `WatchProgress` type. Mocked: `e2e/history.spec.ts` (resume button shows "Resume from 1:35" from a mocked position and hides after clicking). Persistence proof: `e2e-backed/history.spec.ts` — signup → watch page → drive playback → the PUT lands (awaited) → the video appears in `/history` after a fresh authed refetch.
- [~] Implement private/unlisted/not-found/error states. (loading / 404 not-found / generic error (retry) handled; private→owner gating needs auth (P3) + the original endpoint already 404s non-owners.)
- [x] Add Playwright watch-page smoke test. (`e2e/watch.spec.ts`: route-mocked detail → asserts heading, views, duration, dimensions, description, and the `<video>` src; plus a 404 not-found case.)
- [x] Add backend-backed e2e proving interactions that mutate data (comment, like, save, watch-progress) persist to the database and reappear after refetch. (comment + like + save + **watch-progress** DONE — `e2e-backed/comments.spec.ts`, `rating.spec.ts`, `save.spec.ts`, and `history.spec.ts` drive the UI and confirm the row via API/UI-refetch + psql. `history.spec.ts`: playback on the watch page records progress (awaited PUT) → the video appears in `/history` after a fresh authed refetch → removing it persists (gone after navigate-away-and-back).)

## P4.3 Embed Player

- [ ] Implement embed route if in-scope.
- [ ] Implement minimal player chrome for embed.
- [ ] Implement embed privacy/sandbox behavior.
- [ ] Implement embed loading/error states.
- [ ] Add embed smoke test.

---

# P5 — Library, Playlists, Subscriptions, and Notifications

- [x] Implement library dashboard. (`app/library/page.tsx` + `components/SavedVideosView.tsx`: the signed-in user's saved videos ("watch later") as a card grid via `GET /me/saved`, mirroring `/subscriptions` (loading / error-retry / empty / grid; anon → "Sign in to see your library"). Linked from the header nav. VERIFIED via the save round-trip backed test above. Named playlists are a later slice.)
- [x] Implement watch history page. (`app/history/page.tsx` + `components/WatchHistoryView.tsx`: the signed-in user's watch history as a card grid via `GET /api/v1/me/history`, most-recently-watched first, mirroring `/library` and `/subscriptions` (loading / error-retry / empty / grid; anon → "Sign in to see your history"). Each card carries a "Resume at m:ss · {watched ago}" label and a Remove control (`DELETE /api/v1/me/history/:id`, optimistic), plus a "Clear all history" control (`DELETE /api/v1/me/history`). Linked from the header nav. VERIFIED via the watch-history backed round trip below. API client gained `getWatchHistory`/`deleteHistoryEntry`/`clearWatchHistory` + `HistoryItem`/`WatchHistoryResponse` types. Mocked `e2e/history.spec.ts` (anon prompt, list + resume label, remove, clear). Backed `e2e-backed/history.spec.ts` proves record→appears→remove.)
- [~] Implement resume progress bars on video cards. (The history page surfaces the saved resume position as a "Resume at m:ss" label per card. A graphical progress *bar* needs the video duration on the card, which the backend feed/card `Video` does not yet carry — DEFERRED on that backend dependency (`duration_seconds` on card/feed rows).)
- [ ] Implement watch later page.
- [x] Implement playlists list page. (`app/playlists/page.tsx` → `components/PlaylistsView.tsx`, auth-gated, reached via a header "Playlists" link. Loads `api.getMyPlaylists` (`GET /api/v1/me/playlists`) into a list (title + `N videos · visibility`, each a link to `/playlists/{id}`) with loading / error(retry) / empty states.)
- [x] Implement create playlist modal/page. (Inline create form on `/playlists`: title input + visibility `<select>` (private/unlisted/public) + Create → `api.createPlaylist` (`POST /api/v1/playlists`), prepends the new playlist to the list. A dedicated modal is not needed — inline is simpler and fully tested. Also creatable from the watch-page "Save to playlist" menu, see below.)
- [~] Implement edit playlist page. (Create + delete + add/remove items done; renaming/visibility *editing* of an existing playlist (the `updatePlaylist` client method exists, `PATCH`) has no dedicated UI yet — DEFERRED to an edit-playlist slice.)
- [x] Implement playlist detail page. (`app/playlists/[id]/page.tsx` → `components/PlaylistDetailView.tsx`: loads `api.getPlaylist` (`GET /api/v1/playlists/:id`), header (title, `N videos · visibility`, description) + a `VideoCard` grid, with loading / not-found(404, e.g. private as non-owner) / error(retry) / empty states. Owner-only controls (Delete playlist, per-card Remove → `removeFromPlaylist`) shown only when the playlist is in the viewer's own `GET /me/playlists` (ownership inferred client-side; detail response carries no owner_id). Delete → `api.deletePlaylist` → redirect to `/playlists`.)
- [x] Implement playlist visibility controls. (Create form exposes the visibility selector (private default); the detail page surfaces the current visibility. The backend gates private playlists (404 to non-owner). Changing an existing playlist's visibility is part of the deferred edit slice.)
- [ ] Implement playlist thumbnail selection/upload UI. (DEFERRED — needs a backend playlist-thumbnail contract.)
- [x] Implement add-to-playlist modal. (`components/AddToPlaylistButton.tsx` on the watch page (next to Save/rating): a "Save to playlist" button opens a menu that lazy-loads the user's playlists; clicking one adds the current video (`POST /playlists/:id/videos`, `aria-pressed` reflects added), plus an inline "New playlist" input that creates a playlist AND adds the video in one go. Anon → "Sign in to save to a playlist".)
- [x] Implement quick-add to watch later. (Watch-later quick-add is the ★ Save button (saved-videos); the playlist quick-add is the "Save to playlist" menu above. Both are on every watch page.)
- [x] Implement subscriptions page. (`app/subscriptions/page.tsx` → `components/SubscriptionsView.tsx`, auth-gated (sign-in prompt when the in-memory session is gone), reached via a header "Subscriptions" link. Loads `api.getSubscriptionVideos` (`GET /api/v1/me/subscriptions/videos`) into a `VideoCard` grid with loading / error(retry) / empty states. Mocked `e2e/subscriptions.spec.ts` (anon prompt, empty, grid — 3). **Backed-VERIFIED** (empty case): `e2e-backed/subscriptions.spec.ts` signs up → opens Subscriptions → the real endpoint returns no videos and the empty state renders. The populated round-trip (follow → video appears) is pending channel-page reachability + a video-upload seed.)
- [x] Implement notifications page. (`app/notifications/page.tsx` → `components/NotificationsView.tsx`, auth-gated (sign-in prompt when the in-memory session is gone). Loads `api.getNotifications` (`GET /api/v1/me/notifications`) into a list with a per-type message + link (follow → "{actor} started following {channel}" → `/channels/{handle}`; comment → "{actor} commented on {video}" → `/videos/{id}`), an unread dot + highlight, relative time, and loading / error(retry) / empty states. **Also adds the header notifications bell** (`components/NotificationsBell.tsx`): a bell icon → `/notifications` with an unread-count badge, refetched via `GET /me/notifications/unread-count` on mount and on every route change (so it reflects reads made on the page after navigating away); renders nothing for anon. API client gained `getNotifications`/`getUnreadNotificationCount`/`markNotificationRead`/`markAllNotificationsRead` + `Notification`/`NotificationListResponse`/`UnreadCountResponse` types. Mocked `e2e/notifications.spec.ts` (anon prompt, bell badge + opens list, mark-one, mark-all, empty — 5). **Backed-VERIFIED**: see below.)
- [x] Implement mark notification read/all-read controls. (`NotificationsView` per-item "Mark read" (`POST /me/notifications/:id/read`, optimistic, removes the unread control) + a "Mark all as read" header button (`POST /me/notifications/read-all`, disabled at 0 unread); clicking a notification's link also marks it read. **VERIFIED end-to-end against a real backend**: `e2e-backed/notifications.spec.ts` API-seeds a fan→channel follow (creating a notification for the owner), the owner logs in through the UI, sees the unread bell badge + the "started following {channel}" notification, marks it read (awaited POST), and a fresh authed refetch (navigate away + back) keeps it read — proving the `notifications.read_at` flip persisted (psql evidence captured). Runs in CI via `frontend-e2e-backed.yml`.)
- [~] Add component tests for playlist controls. (API-client unit tests cover all 7 playlist endpoint methods; the Playwright specs cover the controls. Dedicated RTL component-unit tests can follow.)
- [x] Add Playwright tests for playlist create/add/remove flows with mocked API. (`e2e/playlists.spec.ts` — anon prompt, create→appears in list, detail shows videos + owner remove, owner delete→redirect, watch-page add-to-playlist (open menu → add → `aria-pressed`) — 5 tests.)
- [x] Add backend-backed e2e proving playlist create/add/remove and watch-later changes persist to the database and survive a refetch. (**VERIFIED**: `e2e-backed/playlists.spec.ts` — signup → seeded public video's watch page → "Save to playlist" creates a playlist AND adds the video (awaited POSTs) → `/playlists/:id` shows the video after a fresh refetch → Remove (awaited DELETE) → empty after navigate-away-and-back. DB evidence captured: the `playlist_items` row (position 1) + `GET /playlists/:id` `video_count=1` via psql/API. Runs in CI via `frontend-e2e-backed.yml`. Watch-later persistence was already proven in `e2e-backed/save.spec.ts`.)

---

# P6 — Publishing and Upload UX

## P6.1 Shared Publish Flow

- [x] Implement Publish route. (`app/studio/page.tsx` → `components/StudioView.tsx`, the creator surface reached via a header "Studio" link, auth-gated (sign-in prompt). Loads `api.getMyChannels` (`GET /api/v1/me/channels`); a creator with no channel sees a create-channel form, and once they have ≥1 channel an upload form appears. VERIFIED end-to-end below.)
- [x] Implement channel selector. (`StudioView` `UploadSection` renders a channel `<select>` when the user owns >1 channel (defaults to the first); a single-channel creator skips the selector. The `ChannelSection` also lists owned channels (link to `/channels/:handle`) and a create-channel form (handle + display name → `POST /api/v1/channels` via new `api.createChannel`; 409 → "handle already taken").)
- [x] Implement privacy selector. (`UploadSection` privacy `<select>` public/unlisted/private, default public — sent as `CreateVideoRequest.privacy` on `POST /api/v1/channels/:handle/videos`.)
- [~] Implement metadata form: title, description, tags, category, language, license. (Title + privacy + channel done (the fields the backend create-draft accepts). Description and tags/category/language/license need backend contract fields — DEFERRED.)
- [ ] Implement thumbnail upload/selection.
- [ ] Implement captions upload section.
- [ ] Implement scheduled publish field.
- [ ] Implement validation errors.
- [ ] Implement save draft/publish controls where backed by API.
- [ ] Implement upload/import status states.
- [ ] Implement cancellation UI.
- [ ] Add route/control inventory evidence for every publish control.

## P6.2 File Upload

- [x] Implement file picker. (`UploadSection` `<input type="file" accept="video/*">`; on Publish it creates a draft (`api.createVideoDraft`) then uploads the file (`api.uploadVideoFile`, multipart via `apiRequest` FormData support) which the backend probes + publishes. 415 → "not a supported video" message. A drag-and-drop dropzone is a later polish.)
- [ ] Implement upload progress. (DEFERRED — needs streamed/XHR progress; the current upload is a single awaited fetch with an "Uploading…" button state.)
- [ ] Implement virus scan pending/quarantine/failure states. (DEFERRED — backend ClamAV not wired.)
- [ ] Implement transcoding pending/progress/failure states. (DEFERRED — backend publishes synchronously today; no async transcode states yet.)
- [x] Implement success redirect. (On publish the form shows "Published!" with a link to the new video's watch page (`/videos/:id`); a hard auto-redirect is intentionally avoided so the creator can upload another.)
- [x] Add Playwright file-upload smoke test with small fixture/mocked API. (`e2e/studio.spec.ts` — anon prompt, create channel → upload form appears, upload (setInputFiles) → "Published!" + view link — 3 tests.)
- [x] Add backend-backed e2e proving an uploaded video and its edited metadata persist to the database and appear in the studio list after refetch. (**VERIFIED**: `e2e-backed/studio.spec.ts` — signup → studio → create channel → upload the tiny H.264 mp4 (real ffprobe accepts it) → "Published!" → the video appears on the public channel page after a fresh refetch. DB evidence: the `videos` row (`state=published`, `privacy=public`) + `video_files` (original + generated thumbnail) via psql; channel API returns it published. Runs in CI via `frontend-e2e-backed.yml`.)

## P6.3 URL Import

- [ ] Implement Import with URL tab.
- [ ] Implement URL input and validation.
- [ ] Implement rights/legal warning text.
- [ ] Implement import submit/progress/error states.
- [ ] Add tests for URL import form behavior.

## P6.4 Torrent/Magnet Import

- [ ] Implement Import with torrent tab if in-scope.
- [ ] Implement torrent file picker.
- [ ] Implement magnet URI input.
- [ ] Implement rights/legal warning text.
- [ ] Implement import submit/progress/error states.
- [ ] If deferred, mark explicit intentional difference and keep control hidden or disabled by config.

## P6.5 Live Publishing

- [ ] Implement Go Live tab.
- [ ] Implement normal vs permanent/recurring live selector.
- [ ] Implement RTMP URL display.
- [ ] Implement private stream key display/copy/regenerate behavior according to backend contract.
- [ ] Implement stream key warning text.
- [ ] Implement live status display.
- [ ] Implement replay behavior UI.
- [ ] Add tests for live form and sensitive key visibility.

---

# P7 — Studio and Creator Tools

- [~] Implement My Videos page. (Studio now has a **"Your videos"** section (`MyVideosSection` in `components/StudioView.tsx`): for the selected channel it lists the owner's videos via `GET /api/v1/channels/:handle/videos` (the owner view returns drafts/private too), each row showing the title (link to the watch page), a lifecycle **status badge**, and the privacy label, with loading / error(retry) / empty states and a **Refresh** control (refetch after a new upload, since the upload form is a sibling section). A multi-channel creator gets a channel selector. A dedicated `/studio/videos` route + pagination/sort is a later polish; this is the embedded my-videos list.)
- [~] Implement video status badges: draft, uploading, scanning, transcoding, published, failed, blocked, quarantined, scheduled. (`StateBadge` renders the four backend lifecycle states — draft / processing / published / failed — with distinct colors. The scanning/transcoding/blocked/quarantined/scheduled states need backend states/fields that do not exist yet — DEFERRED on those backend dependencies.)
- [x] Implement quick edit controls. (Per-row inline **Edit** in "Your videos" → title + privacy form → `PATCH /api/v1/videos/:id`; the server result replaces the row. Save/Cancel, disabled-while-saving, blank-title guard, 422/error message. **VERIFIED** end-to-end — see the backed e2e below.)
- [~] Implement full video edit page. (Title + privacy editable inline today. A dedicated full-edit page with description/tags/category/language/license needs those backend metadata fields (the create-draft + `UpdateVideoRequest` only accept title/description/privacy) — DEFERRED to a metadata-fields slice; description editing can land once the studio surfaces it.)
- [x] Implement privacy editing. (Inline Edit form's privacy `<select>` public/unlisted/private → `PATCH /api/v1/videos/:id` `{privacy}`. VERIFIED end-to-end below.)
- [ ] Implement thumbnail/caption editing. (DEFERRED — needs backend thumbnail-replace / captions contracts.)
- [x] Implement delete video confirmation. (Per-row two-step **Delete → Confirm** (inline, no `window.confirm`) → `DELETE /api/v1/videos/:id`; the row is removed on success. **VERIFIED** end-to-end below.)
- [ ] Implement statistics page.
- [ ] Implement channel management page.
- [~] Implement channel create/edit/delete. (Create DONE (P6 studio `ChannelSection` → `POST /channels`). Channel **edit/delete** UI is not built yet — the backend exposes `PATCH`/`DELETE /channels/:handle`; DEFERRED to a channel-management slice.)
- [ ] Implement channel sync page for remote channels if in-scope.
- [ ] Implement quota/storage usage display.
- [x] Add Playwright creator smoke tests. (`e2e/studio.spec.ts` mocked: anon prompt, create channel → empty "Your videos", upload → Published, **edit title+privacy**, **delete** — 5 tests. API client unit tests cover `updateVideo`/`deleteVideo` — `lib/api/endpoints.test.ts`.)
- [~] Add backend-backed e2e proving video edit/delete and channel create/edit/delete persist to the database and are reflected in the UI after refetch. (**Video edit + delete VERIFIED**: `e2e-backed/studio.spec.ts` "a creator can edit and delete their video" signs up → creates a channel → uploads the tiny H.264 mp4 → in "Your videos" edits the title (awaited PATCH) → the new title is read back via the **public channel-videos API** (`channelVideos` fixture; old title absent) → deletes it (awaited DELETE) → the public list no longer contains it. Run locally against the compose `core` stack on :8088 (`E2E_API_URL=http://localhost:8088 E2E_PORT=3100 npm run e2e:backed`) — both backed studio tests pass; the deleted rows are gone from the real `videos` table (psql). Runs in CI via `frontend-e2e-backed.yml`. **Channel edit/delete** backed coverage is DEFERRED with that UI.)

---

# P8 — Messaging UX

## P8.1 Normal Messaging

- [ ] Implement conversations list.
- [ ] Implement conversation detail.
- [ ] Implement message compose box.
- [ ] Implement attachment upload UI.
- [ ] Implement link preview display.
- [ ] Implement read receipt display if in-scope.
- [ ] Implement message deletion/reporting/blocking controls.
- [ ] Implement empty/error/loading states.
- [ ] Add Playwright messaging smoke test with mocked API.
- [ ] Add backend-backed e2e proving a sent message persists to the database and appears in the thread after refetch.

## P8.2 Encrypted Messaging

- [ ] Display encrypted mode availability only when backend contract supports it.
- [ ] Implement device setup/onboarding UI.
- [ ] Implement encrypted conversation indicator.
- [ ] Implement disappearing message timer control.
- [ ] Implement ciphertext-safe attachment warnings where needed.
- [ ] Do not pretend E2EE exists unless backend storage/protocol evidence exists.
- [ ] Add tests for encrypted-mode UI states.

---

# P9 — Moderation and Reporting UI

- [x] Implement report content dialog. (`components/ReportButton.tsx`: an authed viewer gets a **Report** control that opens an accessible modal (`role="dialog"` + `aria-modal`, Escape/backdrop to close, focuses the reason field) with a required reason textarea (≤2000) → `POST /videos|comments/:id/report` → success confirmation; anon viewers get a "Sign in to report" link. **VERIFIED** end-to-end — see the backed e2e below.)
- [~] Implement report account/channel/video/comment flows. (**Video + comment DONE & VERIFIED**: `ReportButton kind="video"` on the watch page controls row (`WatchView`); `kind="comment"` per non-authored comment (`CommentsSection`). API client gained `reportVideo`/`reportComment` + `CreateReportRequest` type (unit-tested). Account/channel report flows are DEFERRED — the backend `reports` target_type is `video|comment` only (no account/channel target yet).)
- [x] Implement mute account action. (**VERIFIED** end-to-end against a real backend. A signed-in viewer gets a **Mute** control on every comment authored by another account (`components/CommentsSection.tsx` `CommentItem`, next to Report) → `POST /api/v1/me/mutes/accounts/:author_id` (`api.muteAccount`, using the comment's new `author_id`); on success the muted author's comments are dropped from the list (and the backend hides them on any refetch). A **muted-accounts management page** (`app/settings/mutes` → `components/MutedAccountsView.tsx`, auth-gated, linked from `/settings`) lists the accounts you've muted (`GET /me/mutes/accounts`) with an **Unmute** control (`DELETE /me/mutes/accounts/:id`). API client gained `muteAccount`/`unmuteAccount`/`getMutedAccounts` + `MutedAccount`/`MutedAccountListResponse` types + `Comment.author_id` (unit-tested). Mocked `e2e/mutes.spec.ts` (mute-from-comment hides it; management page lists + unmutes — 2). Backed `e2e-backed/mutes.spec.ts` proves the full round trip: a viewer mutes a seeded commenter from the watch page → the comment disappears → the muted account shows on the management page (fresh API read) → unmute → the comment reappears on a fresh watch-page refetch (migration 0022 `muted_accounts` confirmed via psql).)
- [ ] Implement mute instance action.
- [x] Implement moderation reports list. (`app/moderation/page.tsx` → `components/ModerationQueue.tsx`, gated to moderator/admin (anon/regular users see a "Moderators only" prompt; the session is in-memory so a hard reload also shows the gate). Loads `api.getReports({openOnly})` (`GET /api/v1/admin/reports`, `status=open` filter) into a list of report cards: a status badge (open/accepted/rejected), target-type badge, reporter username, relative time, the reported target (a link to the video for video reports, the quoted body for comment reports), and the reason. An **Open / All** filter toggle (`aria-pressed`) switches `status=open` vs the full queue. Loading / error(retry) / empty states. Reached via a role-gated header "Moderation" nav link (`components/ModerationNavLink.tsx`, renders nothing for anon/regular). API client gained `getReports`/`resolveReport` + `Report`/`ReportReporter`/`ReportListResponse`/`ResolveReportRequest`/`ReportStatus`/`ReportTargetType` types (unit-tested — `endpoints.test.ts`).)
- [~] Implement report detail page. (Inline per-row resolve controls cover the moderation action today; a dedicated `/moderation/:id` detail route is DEFERRED — the queue card already shows full reason/target/reporter/note context.)
- [~] Implement accept/reject/delete report actions. (**Accept + Reject DONE & VERIFIED**: each open report card has Accept / Reject buttons → `POST /api/v1/admin/reports/:id/resolve` `{status, note}`; on success the row drops out of the open-only view (optimistic) and a fresh refetch keeps it out. **Report delete** is DEFERRED — the backend has no report-delete endpoint (a hard-delete of a report row), per `vidra-core` P9.)
- [x] Implement internal moderation note field. (Each open report card has an optional "Internal note" textarea (≤2000) sent as the `note` on resolve; the backed test fills it and the note persists (psql: `moderator_note='confirmed abuse'`).)
- [x] Implement video block list. (`app/moderation/blocked/page.tsx` → `components/BlockedVideosView.tsx`, gated to moderator/admin (anon/regular see a "Moderators only" prompt and never fetch). Loads `api.getBlockedVideos({limit:100})` (`GET /api/v1/admin/videos/blocked`) into a list of blocked-video cards: the title (link to the watch page), the owning channel (link to `/channels/{handle}`), the block reason, who blocked it (`blocked_by`, omitted if absent), and a "blocked {relative}" timestamp, with loading / error(retry) / empty states. Reached via a new role-gated `ModerationTabs` sub-nav (Reports ↔ Blocked videos) shown on both moderation surfaces. API client gained `getBlockedVideos` + `BlockedVideo`/`BlockedVideoListResponse` types (unit-tested — `endpoints.test.ts`). **VERIFIED** end-to-end — see the backed e2e below.)
- [x] Implement manual block/unblock controls. (Both halves DONE & VERIFIED. **Block**: a `Block video` button on each open video-report card in the moderation queue (`components/ModerationQueue.tsx` `ReportRow`) → `POST /api/v1/admin/videos/:id/block` (`api.blockVideo`, recording the report's reason for the audit trail); on success the card shows a "Video blocked · Manage" confirmation linking to the block-list. **Unblock**: each block-list card has an **Unblock** button → `DELETE /api/v1/admin/videos/:id/block` (`api.unblockVideo`), optimistically dropping the row; a fresh refetch keeps it gone and the video returns to public surfaces. API client gained `blockVideo` + `BlockVideoRequest` (unit-tested). Mocked: `e2e/blocked-videos.spec.ts` (unblock — 3) + `e2e/moderation.spec.ts` "an admin blocks the video from a report card". Backed `e2e-backed/blocked-videos.spec.ts` proves BOTH round trips. DEFERRED: a block control on the watch page itself (the queue is the moderation surface today) — would benefit from a `blocked` flag on the video detail to show a toggle.)
- [x] Implement admin videos overview (browse-all + block/unblock any). (**VERIFIED** end-to-end against a real backend. `app/moderation/videos/page.tsx` → `components/AdminVideosView.tsx`, gated to moderator/admin, reached via a new **All videos** `ModerationTabs` entry (Reports · Blocked videos · All videos). Loads `api.getAdminVideos({q})` (`GET /api/v1/admin/videos`) into rows showing the title (→ watch), owning channel (→ `/channels/{handle}`), views, relative date, privacy + state badges, a `blocked` badge, and a **Block/Unblock** toggle (`POST`/`DELETE /admin/videos/:id/block`) that flips the row in place. A title search box (`q`) filters. Loading / error(retry) / empty states. This is the general moderation surface (all videos, any privacy/state) complementing the blocked-only list. API client gained `getAdminVideos` + `AdminVideo`/`AdminVideoListResponse` types (unit-tested). Mocked `e2e/admin-videos.spec.ts` (anon gated, admin browses + sees a blocked badge/Unblock on a blocked video, blocks a fresh one → row flips — 2). Backed `e2e-backed/admin-videos.spec.ts` proves the round trip: the admin searches the seeded video in All videos → **Block** → the row flips AND the video enters the block-list + is hidden from the public detail endpoint → **Unblock** → the row flips back AND the video is public again (DB-confirmed via the admin block-list API + the public video-detail endpoint + psql).)
- [ ] Implement quarantine approval controls.
- [ ] Implement watched words list page.
- [ ] Implement create/edit/delete watched words list.
- [x] Implement comments moderation overview. (**VERIFIED** end-to-end against a real backend. `app/moderation/comments/page.tsx` → `components/AdminCommentsView.tsx`, gated to moderator/admin, reached via a new **Comments** `ModerationTabs` entry (Reports · Blocked videos · All videos · Comments). Loads `api.getAdminComments({q})` (`GET /api/v1/admin/comments`) into rows showing the comment body, author, a link to the video (`video_title` → `/videos/{id}`), relative time, and a two-step **Delete → Confirm delete** control (`DELETE /api/v1/comments/:id`, which the backend now allows a moderator/admin to use on any comment) that drops the row on success. A body search box (`q`) filters. Loading / error(retry) / empty states. API client gained `getAdminComments` + `AdminComment`/`AdminCommentListResponse` types (unit-tested). Mocked `e2e/admin-comments.spec.ts` (anon gated; admin browses, deletes one via confirm → row drops, the other stays — 2). Backed `e2e-backed/admin-comments.spec.ts` proves the round trip: a moderator searches a seeded comment in Comments → Delete → Confirm → the row disappears AND the comment is gone from the video's public comment list (DB-confirmed via the public comments read + psql: 0 leftover test comments).)
- [ ] Implement bulk moderation actions if backend supports them.
- [~] Add Playwright moderation smoke tests with mocked API. (Reporting + queue DONE: `e2e/report.spec.ts` — anon prompt, authed video report (dialog → submit → confirmation), authed comment report — 3 tests. `e2e/moderation.spec.ts` — anon gated out (no fetch), regular users see no Moderation nav, admin sees the open queue (video + comment cards), Accept drops a report from the open view, the All filter shows resolved reports without resolve actions — 5 tests. Block/mute/watched-words smoke tests await those UIs.)
- [x] Add backend-backed e2e proving moderation actions (report resolve, block/unblock, mute, watched-words edit) persist to the database and are reflected in the UI after refetch. (**Report filing + resolve VERIFIED**: `e2e-backed/report.spec.ts` — a viewer files a video/comment report from the watch page; each is read back from the **admin moderation queue** (`GET /admin/reports`) as a deterministic admin, proving the `reports` row persisted. `e2e-backed/moderation.spec.ts` — a report is seeded via the API (`fixtures.fileVideoReport`), the deterministic admin logs in through the UI, opens the moderation queue, **resolves** it (accept, with an internal note) → the row drops out of the open queue AND stays out after a fresh refetch (navigate away+back), proving the `reports.status` flip persisted; a second test proves Reject flips to `rejected`. DB-confirmed via the admin API read in-test AND direct psql: `reports` rows `video|accepted|note="confirmed abuse"` and `video|rejected`, both with a resolver. The reusable deterministic-admin backed harness (`backed-setup` project + `adminToken()`/`reportsQueue()`) drives it; runs in CI via `frontend-e2e-backed.yml`. **Video block/unblock now VERIFIED too**: `e2e-backed/blocked-videos.spec.ts` seeds a published video, blocks it via the API (`fixtures.blockVideo`), confirms it is in the block-list AND hidden from the public detail endpoint, then the deterministic admin logs in through the UI, opens Moderation → Blocked videos, **unblocks** it → the row drops out AND stays out after a fresh refetch (tab away+back), proving the `video_blocks` row was deleted; persistence DB-confirmed via the admin block-list API read, the now-public video detail (200), AND direct psql (`SELECT count(*) FROM video_blocks` = 0). A second test proves the **block-from-queue** round trip: a viewer reports a video, the admin opens the moderation queue and clicks **Block video** on the card → the video becomes hidden from the public detail AND appears in the block-list (DB-confirmed via the admin block-list API + the now-404 public detail + direct psql: a `video_blocks` row whose `reason` is the report's reason). **Account mute now VERIFIED too**: `e2e-backed/mutes.spec.ts` — a viewer mutes a seeded commenter from the watch page → the comment is hidden (backend filters it for the viewer) → the muted account appears on the `/settings/mutes` management page (a fresh `GET /me/mutes/accounts` read) → unmute → the comment reappears on a fresh watch-page refetch (migration 0022 `muted_accounts` confirmed via psql). **Watched-words** awaits that admin UI.)

---

# P10 — Admin UI

- [ ] Implement admin overview.
- [x] Implement users list/search/filter. (`app/admin/users/page.tsx` → `components/AdminUsersView.tsx`, admin-only (anon/regular/moderator see an "Administrators only" prompt and never fetch). Loads `api.getAdminUsers({q})` (`GET /api/v1/admin/users`) into a list of user cards (username, email, verified/unverified + active/deactivated badges, joined relative time). A search form (`role="search"`) sends the `q` substring filter (with a Clear control); loading / error(retry) / empty states. Reached via a role-gated header "Admin" nav link (`components/AdminNavLink.tsx`). API client gained `getAdminUsers`/`updateAdminUser` + `AdminUser`/`AdminUserListResponse`/`UpdateUserRequest` types (unit-tested).)
- [~] Implement user detail/edit. (Inline per-row edit (role + active) covers the management action today; a dedicated `/admin/users/:id` detail page is DEFERRED — the row already shows username/email/role/status/verified/joined.)
- [~] Implement role/quota/status controls. (**Role + active status DONE & VERIFIED**: each row has a role `<select>` (user/moderator/admin) → `PATCH /admin/users/:id {role}` and a Deactivate/Reactivate toggle → `{is_active}`; the PATCH returns the updated user and the row reflects it. The admin's **own** row is detected (`id === session user.id`) and its controls are disabled with a "you" badge + explanation, matching the backend's self-demote/deactivate guard (422). **Quota** is DEFERRED — the backend has no per-user quota field yet.)
- [ ] Implement registration requests queue.
- [ ] Implement accept/reject registration requests.
- [ ] Implement instance configuration page.
- [ ] Implement feature toggle controls for uploads, imports, live, federation, registration.
- [ ] Implement federation settings page.
- [ ] Implement jobs/worker status page.
- [ ] Implement audit log page.
- [ ] Implement system status page.
- [ ] Implement a "Import from PeerTube" admin page that consumes the backend import contract (launch a dry-run, show the mapping/conflict report, start/resume an import, and stream progress + audit summary). Depends on the `vidra-core` P18 import endpoint; mark `BLOCKED` on that contract until it exists. Never display or store source DB credentials in the browser. See `../vidra-core/.ralph/specs/peertube-import.md`.
- [~] Add admin route guards. (The client-side role-gate pattern is now used by three surfaces: `ModerationQueue`/`ModerationNavLink` (moderator/admin), `BlockedVideosView` + the role-gated `ModerationTabs` sub-nav (moderator/admin), and `AdminUsersView`/`AdminNavLink` (admin-only) — each renders a permission prompt for an under-privileged/anon session (never fetches → no 403) and the nav entry only shows for the allowed role(s). Now that a third surface has landed, a shared `<RoleGate>` wrapper is worth extracting to dedup the prompt; tracked as a small refactor.)
- [x] Add Playwright admin smoke tests with mocked API. (`e2e/admin-users.spec.ts` — anon gated out (no fetch), moderators see Moderation but not Admin nav, admin sees the list with a self badge + disabled self controls, search filters by `q`, change role, deactivate — 6 tests. API client unit tests cover `getAdminUsers`/`updateAdminUser`.)
- [~] Add backend-backed e2e proving admin mutations (user edit, registration accept/reject, instance config, feature toggles) persist to the database and are reflected in the UI after refetch. (**User edit VERIFIED**: `e2e-backed/admin-users.spec.ts` — a fresh account is seeded via the API, the deterministic admin logs in through the UI, searches for it, promotes it to moderator and deactivates it; a fresh refetch (navigate away+back, re-search) shows both changes AND the admin API read confirms `role=moderator`, `is_active=false`. DB-confirmed via psql (`users` row `moderator`/`is_active=f`). Runs in CI via `frontend-e2e-backed.yml`. Registration accept/reject, instance config, and feature toggles await those admin UIs + backend contracts.)

---

# P11 — Federation, Search, and External Identity UI

- [ ] Implement remote account/channel/video display states.
- [ ] Implement remote instance badges/labels.
- [ ] Implement follow/unfollow remote channel/account controls.
- [ ] Implement federated search result states.
- [ ] Implement WebFinger-style lookup UI if in-scope.
- [ ] Implement ActivityPub visibility labels where needed.
- [ ] Implement ATProto/Bluesky connection settings as Vidra extension.
- [ ] Implement clear protocol labeling: ActivityPub, ATProto, both, or local-only.
- [ ] Add tests for protocol labels and disabled states.

---

# P12 — Captions, Accessibility, and Internationalization Readiness

- [ ] Implement captions management UI.
- [ ] Implement captions language selector.
- [ ] Implement Whisper auto-caption request UI if backend supports it.
- [ ] Implement caption processing status states.
- [ ] Audit keyboard navigation for core routes.
- [ ] Audit focus management for dialogs/dropdowns.
- [ ] Add ARIA labels to icon-only buttons.
- [ ] Add reduced-motion friendly interactions.
- [ ] Add basic responsive coverage for mobile/tablet/desktop.
- [ ] Add accessibility checks to Playwright where feasible.

---

# P13 — Simple Crypto Donation UI

- [ ] Implement donation wallet display on bio/channel pages.
- [ ] Implement add/edit wallet address settings UI.
- [ ] Implement network/address type selector.
- [ ] Implement verification status badge.
- [ ] Implement verification challenge UI if backend supports it.
- [ ] Do not implement custody, balances, payouts, premium subscriptions, or payment processing.
- [ ] Add component tests for verified/unverified display.
- [ ] Add backend-backed e2e proving a saved/edited wallet address and its verification state persist to the database and are reflected in the UI after refetch.

---

# P14 — Testing Strategy

- [ ] Add unit test framework.
- [ ] Add component test examples.
- [ ] Add integration test strategy for API client.
- [ ] Add MSW or equivalent API mocking if chosen.
- [ ] Add Playwright configuration.
- [ ] Add Playwright smoke tests for app shell.
- [ ] Add Playwright smoke tests for auth.
- [ ] Add Playwright smoke tests for watch page.
- [ ] Add Playwright smoke tests for publish flow.
- [ ] Add Playwright smoke tests for admin/moderation.
- [ ] Add backend-backed Playwright profile that runs against a real `vidra-core` instance (Docker Compose) with a real PostgreSQL.
- [ ] Add a database-effect assertion helper: after a mutating UI action, assert the row exists/changed in PostgreSQL (or via a backend read endpoint) and assert the UI reflects it after refetch.
- [ ] Define which flows MUST run under the backend-backed profile (every data-mutating flow) vs which may stay mocked (pure presentational/UI-state).
- [ ] Add visual/screenshot test strategy or documented defer.
- [ ] Document when Ralph should run focused vs full suites.

---

# P15 — Release Gates

- [ ] All P0 tracking files exist and are current.
- [ ] All frontend required sections above are either complete or explicitly deferred by user.
- [ ] PeerTube UI inventory has no unclassified in-scope routes.
- [ ] PeerTube UI inventory has no unclassified in-scope controls.
- [ ] Feature ledger has no unclassified in-scope frontend items.
- [ ] Vidra extensions ledger has no unclassified in-scope frontend items.
- [ ] API contract dependencies are either implemented, mocked with pending backend status, or intentionally deferred.
- [ ] Every in-scope data-mutating flow has a backend-backed e2e proving the database changed and the UI reflects it after refetch.
- [ ] Docker can build frontend.
- [ ] Frontend can run against mocked API.
- [ ] Frontend can run against configured backend URL.
- [ ] Unit tests pass.
- [ ] Component/integration tests pass.
- [ ] Playwright smoke tests pass.
- [ ] Backend-backed Playwright profile passes (or the unavailable backend dependency is documented).
- [ ] Lint/typecheck passes.
- [ ] Structured logger in place; ESLint `no-console` enforced; no secrets/PII/plaintext in logs, analytics, URLs, or traces; no tokens in `localStorage`.
- [ ] OpenTelemetry + `traceparent`/correlation propagation to `vidra-core` works (or is behind a documented flag); see `.ralph/specs/observability.md`.
- [ ] `npm run ci` passes locally and CI is green running the same `npm run ci` gate (local↔CI parity); `ci-guard.yml` passes.
- [ ] `.ralph/AGENT.md` is accurate.
- [ ] No secrets are committed.

---

# Optional / Deferred / Non-Blocking

These items do not block Ralph exit if configured as optional in `.ralphrc` and explicitly kept in this section.

- [ ] Premium subscriptions.
- [ ] Creator payouts.
- [ ] Custodial crypto payments.
- [ ] Native mobile apps.
- [ ] Full plugin/theme marketplace.
- [ ] Advanced recommendation engine.
- [ ] Advanced analytics dashboard beyond PeerTube parity.
- [ ] Full visual regression suite.
- [ ] Internationalized UI strings for many languages.
- [ ] WebTorrent/P2P playback if intentionally replaced by IPFS/S3/HLS architecture.

---

# Completed

- [x] Project initialization.
- [x] Repo split: frontend lives in `vidra-user/` (monorepo subdir) with its own Ralph control plane.

---

# Notes for Ralph

- The frontend follows backend contracts. If a backend endpoint is missing, mark the dependency and use mocks only for UI scaffolding.
- A data-mutating feature on mocks is scaffolding, not done. `VERIFIED` requires a real database effect proven end-to-end and visible in the UI.
- Build custom components. Avoid importing heavy UI frameworks.
- Every tiny button matters: dropdowns, modals, tabs, icon buttons, empty states, disabled states, and error messages must be tracked.
- Keep parity ledgers brutally honest.
- If the same failure repeats for multiple loops, stop and report `BLOCKED`.
