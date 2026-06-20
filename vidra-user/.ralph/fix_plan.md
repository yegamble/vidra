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
- [ ] Implement search bar shell.
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
- [ ] Implement account settings page.
- [ ] Implement profile edit form.
- [ ] Implement avatar/banner upload UI.
- [ ] Implement import/export account UI placeholders backed by contract status.
- [~] Add unit tests for validation. (auth client + token store unit-tested — 6; form-field validation tests can follow.)
- [x] Add Playwright auth smoke tests with mocked API. (`e2e/auth.spec.ts`: login success → header shows account; bad-creds error; signup success → account; 422 field-error inline; registration-closed notice.)
- [ ] Add backend-backed auth e2e tests when backend contract exists, proving signup/login/profile-edit persist to the database and are reflected in the UI after refetch. (BLOCKED on running a real vidra-core+PostgreSQL in the gate — the backend-backed Playwright profile isn't wired into `npm run ci` yet; the login flow is therefore NOT `VERIFIED`, only mock-tested.)

---

# P4 — Public Video Browsing and Watch Page

## P4.1 Browse and Search

- [~] Implement local/recent videos page. (home `<VideoFeed/>` shows the recent public feed; a dedicated /local route + sort UI is a later slice.)
- [ ] Implement trending/popular page or documented intentional difference.
- [ ] Implement search results page.
- [ ] Implement filter/sort controls.
- [ ] Implement pagination or infinite scroll.
- [x] Implement video card component. (`components/VideoCard.tsx`: poster via `videoThumbnailUrl` with "No preview" fallback, title (clamped), `formatCount` views · `relativeTime`; links to `/videos/{id}`. `lib/format.ts` tested — 4 unit tests.)
- [ ] Implement channel/account card component.
- [ ] Implement playlist card component.
- [x] Implement empty/no-results states. (`components/ui/EmptyState.tsx`, used by `VideoFeed`.)
- [~] Implement search error states. (generic `components/ui/ErrorState.tsx` with retry exists + used by the feed; search-specific wiring lands with the search page.)
- [~] Add component tests for cards and filters. (card rendering covered by the route-mocked Playwright grid test; pure formatters unit-tested. RTL component-unit tests can follow.)
- [ ] Add Playwright smoke test for search route.

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
- [ ] Implement channel block with subscribe button.
- [ ] Implement share button/dialog.
- [ ] Implement download button/dialog.
- [ ] Implement save/watch-later/playlist button.
- [ ] Implement report button/dialog.
- [ ] Implement like/dislike/reaction controls if in-scope.
- [ ] Implement comments section.
- [ ] Implement related videos section.
- [ ] Implement watched progress/resume UI.
- [~] Implement private/unlisted/not-found/error states. (loading / 404 not-found / generic error (retry) handled; private→owner gating needs auth (P3) + the original endpoint already 404s non-owners.)
- [x] Add Playwright watch-page smoke test. (`e2e/watch.spec.ts`: route-mocked detail → asserts heading, views, duration, dimensions, description, and the `<video>` src; plus a 404 not-found case.)
- [ ] Add backend-backed e2e proving interactions that mutate data (comment, like, save, watch-progress) persist to the database and reappear after refetch.

## P4.3 Embed Player

- [ ] Implement embed route if in-scope.
- [ ] Implement minimal player chrome for embed.
- [ ] Implement embed privacy/sandbox behavior.
- [ ] Implement embed loading/error states.
- [ ] Add embed smoke test.

---

# P5 — Library, Playlists, Subscriptions, and Notifications

- [ ] Implement library dashboard.
- [ ] Implement watch history page.
- [ ] Implement resume progress bars on video cards.
- [ ] Implement watch later page.
- [ ] Implement playlists list page.
- [ ] Implement create playlist modal/page.
- [ ] Implement edit playlist page.
- [ ] Implement playlist detail page.
- [ ] Implement playlist visibility controls.
- [ ] Implement playlist thumbnail selection/upload UI.
- [ ] Implement add-to-playlist modal.
- [ ] Implement quick-add to watch later.
- [ ] Implement subscriptions page.
- [ ] Implement notifications page.
- [ ] Implement mark notification read/all-read controls.
- [ ] Add component tests for playlist controls.
- [ ] Add Playwright tests for playlist create/add/remove flows with mocked API.
- [ ] Add backend-backed e2e proving playlist create/add/remove and watch-later changes persist to the database and survive a refetch.

---

# P6 — Publishing and Upload UX

## P6.1 Shared Publish Flow

- [ ] Implement Publish route.
- [ ] Implement channel selector.
- [ ] Implement privacy selector.
- [ ] Implement metadata form: title, description, tags, category, language, license.
- [ ] Implement thumbnail upload/selection.
- [ ] Implement captions upload section.
- [ ] Implement scheduled publish field.
- [ ] Implement validation errors.
- [ ] Implement save draft/publish controls where backed by API.
- [ ] Implement upload/import status states.
- [ ] Implement cancellation UI.
- [ ] Add route/control inventory evidence for every publish control.

## P6.2 File Upload

- [ ] Implement file picker/dropzone.
- [ ] Implement upload progress.
- [ ] Implement virus scan pending/quarantine/failure states.
- [ ] Implement transcoding pending/progress/failure states.
- [ ] Implement success redirect.
- [ ] Add Playwright file-upload smoke test with small fixture/mocked API.
- [ ] Add backend-backed e2e proving an uploaded video and its edited metadata persist to the database and appear in the studio list after refetch.

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

- [ ] Implement My Videos page.
- [ ] Implement video status badges: draft, uploading, scanning, transcoding, published, failed, blocked, quarantined, scheduled.
- [ ] Implement quick edit controls.
- [ ] Implement full video edit page.
- [ ] Implement privacy editing.
- [ ] Implement thumbnail/caption editing.
- [ ] Implement delete video confirmation.
- [ ] Implement statistics page.
- [ ] Implement channel management page.
- [ ] Implement channel create/edit/delete.
- [ ] Implement channel sync page for remote channels if in-scope.
- [ ] Implement quota/storage usage display.
- [ ] Add Playwright creator smoke tests.
- [ ] Add backend-backed e2e proving video edit/delete and channel create/edit/delete persist to the database and are reflected in the UI after refetch.

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

- [ ] Implement report content dialog.
- [ ] Implement report account/channel/video/comment flows.
- [ ] Implement mute account action.
- [ ] Implement mute instance action.
- [ ] Implement moderation reports list.
- [ ] Implement report detail page.
- [ ] Implement accept/reject/delete report actions.
- [ ] Implement internal moderation note field.
- [ ] Implement video block list.
- [ ] Implement manual block/unblock controls.
- [ ] Implement quarantine approval controls.
- [ ] Implement watched words list page.
- [ ] Implement create/edit/delete watched words list.
- [ ] Implement comments moderation overview.
- [ ] Implement bulk moderation actions if backend supports them.
- [ ] Add Playwright moderation smoke tests with mocked API.
- [ ] Add backend-backed e2e proving moderation actions (report resolve, block/unblock, mute, watched-words edit) persist to the database and are reflected in the UI after refetch.

---

# P10 — Admin UI

- [ ] Implement admin overview.
- [ ] Implement users list/search/filter.
- [ ] Implement user detail/edit.
- [ ] Implement role/quota/status controls.
- [ ] Implement registration requests queue.
- [ ] Implement accept/reject registration requests.
- [ ] Implement instance configuration page.
- [ ] Implement feature toggle controls for uploads, imports, live, federation, registration.
- [ ] Implement federation settings page.
- [ ] Implement jobs/worker status page.
- [ ] Implement audit log page.
- [ ] Implement system status page.
- [ ] Implement a "Import from PeerTube" admin page that consumes the backend import contract (launch a dry-run, show the mapping/conflict report, start/resume an import, and stream progress + audit summary). Depends on the `vidra-core` P18 import endpoint; mark `BLOCKED` on that contract until it exists. Never display or store source DB credentials in the browser. See `../vidra-core/.ralph/specs/peertube-import.md`.
- [ ] Add admin route guards.
- [ ] Add Playwright admin smoke tests with mocked API.
- [ ] Add backend-backed e2e proving admin mutations (user edit, registration accept/reject, instance config, feature toggles) persist to the database and are reflected in the UI after refetch.

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
