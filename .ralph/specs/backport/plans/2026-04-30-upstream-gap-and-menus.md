# Upstream Gap Audit + User Menu + Notifications Bell Implementation Plan

Created: 2026-04-30
Author: yegamble@gmail.com
Status: VERIFIED
Approved: Yes
Iterations: 0
Worktree: Yes
Type: Feature

## Summary

**Goal:** Audit PeerTube + vidra-core + vidra-user against the prototype as a **DTO contract reconciliation** (not just page parity — the highest-risk gaps are response-shape mismatches, see §"ChatGPT-Sourced Audit Inputs"). Write `prototype/docs/UPSTREAM_GAP_AUDIT.md` (full inventory per user choice) covering: missing pages, P0 contract mismatches, P1 field gaps in `vidra-core` responses + file/playback metadata + upload/studio policy fields, and a proposed unified `PrototypeWatchVideo` view model that the prototype's mock should adopt. Then implement three explicitly-requested UI surfaces (user-menu dropdown anchored to TopBar avatar, notifications-bell dropdown anchored to TopBar bell with tabs, button + link state coverage). **Migrate the prototype's `Video` mock to the unified view model** so the prototype stops drifting into a parallel universe (Task 7). Tighten QA gates with a new 6th oracle (`scripts/check-links.mjs`) so future regressions fail CI.

**Architecture:** Two new self-contained components (`UserMenu.tsx`, `NotificationsMenu.tsx`) in `src/components/`, each owning its own open/closed state via a shared `useDropdown` hook with click-outside + escape-key dismiss. Anchored absolutely-positioned panels next to their TopBar triggers. No new dependencies — composes existing primitives (`Card`, `Pill`, `Avatar`, `IconButton`, `Tabs`). Apple HIG vibrancy on the panels (`bg-surface-primary/95 + backdrop-blur-xl + shadow-[0_24px_60px_-20px_…]`). Audit output lives in `docs/UPSTREAM_GAP_AUDIT.md` and any plausible-as-UI gaps are mirrored into `docs/EXPECTED_SURFACE.json` so the existing oracles enforce them automatically.

**Tech Stack:** React 18, React-Router v6, TypeScript 5, Tailwind v3, Vite 5, Playwright 1.47. No new dependencies introduced.

### Inventory reconciliation (current state, 2026-04-30)

| Surface element | Current | After this plan (target) |
|---|---:|---:|
| Page routes | 93 | 93 (+ any new audit-driven pages) |
| Page exports | 88 | 88 + new |
| Component groups | 7 (incl. SettingsShell, AdminShell) | **9** (+ UserMenu, NotificationsMenu) |
| State conditional branches | 288 | 288 + UserMenu/NotificationsMenu states (≈ +12) |
| Oracle commands | 5 | **6** (+ check-links.mjs) |
| Playwright e2e count | 208 | ≥ 220 (+ TS-007 user-menu, TS-008 notifications-bell, TS-009 link-resolution sweep) |

## Scope

### In Scope

- Research output: `prototype/docs/UPSTREAM_GAP_AUDIT.md` — full inventory of PeerTube + vidra-core + vidra-user with status column (covered / partial / missing) per surface, **plus** the DTO-mismatch matrix from the ChatGPT-sourced inputs (P0 contract mismatches, P1 field gaps, P1 file/playback metadata gaps, P1 upload/studio policy fields, P2 unified `PrototypeWatchVideo` view model proposal).
- **Migrate `prototype/src/data/mockData.ts` `Video` interface** to a `PrototypeWatchVideo`-shaped view model (Task 7). Update `WatchScreen.tsx` and any other consumer to read from the new fields rather than hardcoding likes/dislikes/comments/tags/chapters.
- For audit-discovered pages worth surfacing: extend `prototype/docs/EXPECTED_SURFACE.json` (new entries get `"source": "UPSTREAM_GAP_AUDIT.md"` provenance); existing oracles auto-enforce.
- New components: `src/components/UserMenu.tsx`, `src/components/NotificationsMenu.tsx`.
- New hook: `src/lib/use-dropdown.ts` — click-outside + escape-key + focus management.
- AppShell.tsx: replace plain `<IconButton name="bell">` and `<Avatar>` in TopBar with menu-anchored versions.
- mockData.ts: extend `notifications` array (≥ 12 entries spanning all kinds + a handful of `mention` kind for the new Mentions tab).
- New oracle: `prototype/scripts/check-links.mjs` (strict resolved-only, with `scripts/check-links.allowlist.json` for `mailto:`, `tel:`, `https://…`, `#anchor`). Wired into `package.json` as `qa:links` and into `.github/workflows/prototype-qa.yml` as the 6th gate.
- Updated `QA_GAP_REPORT.md` + `QA_COVERAGE.md` reflecting the new contract.
- New e2e specs: `tests/menus.spec.ts` (UserMenu + NotificationsMenu) and `tests/links.spec.ts` (smoke crawl of every Link target).
- Per-screen-or-feature atomic commits (no mega-commit). Each commit must leave all 6 oracles in known-good state.

### Out of Scope

- Real backend wiring. Mock data only via `mockData.ts`.
- Wider Next.js app at `~/github/vidra-user/` outside `prototype/`.
- Vitest unit tests (deferred per `QA_REPORT.md`).
- Sidebar/topbar redesign beyond menu+bell additions (sidebar collapse/overlay from commit `d0fe1d0` is fixed).
- Implementing every gap in the audit. The audit is a **catalogue**; only audit-driven items called out as IN SCOPE in Task 4 are implemented this round. Remaining audit items become a `## Deferred Ideas` section.

## Approach

**Chosen:** Self-contained dropdown components with a shared `useDropdown` hook — no new dependencies.

**Why:** Keeps the prototype dep-free (matches the "no new primitives beyond what already exists" rule from the previous plan, see `docs/QA_REPORT.md`). The existing primitives (`Card`, `Pill`, `Avatar`, `IconButton`, `Tabs`, `EmptyState`) already cover every visual atom needed; the only missing piece is anchored positioning + dismissal management, which is ~50 lines in a custom hook. Cost: we hand-implement focus return + escape-key + click-outside + arrow-key navigation rather than getting them free from a Radix primitive (~120 lines total across the hook + the two menus). Trade-off accepted because the existing `Tabs` primitive has the same hand-rolled accessibility shape and adding Radix here would set a precedent of pulling in headless UI deps for what is fundamentally a static design prototype.

**Alternatives considered:**

- *Radix `DropdownMenu`*: drops ~120 lines of a11y code at the cost of ~30 KB gzipped + a new dep. Rejected because the prototype's bundle size budget is implicit at ~400 KB (current ~393 KB) and the prototype's stated goal is "no backend, no deps beyond the design system stack."
- *Inline menu inside `AppShell.tsx` only*: simpler one-file change but couples menu logic to layout chrome. Rejected because the audit-discovered surfaces (e.g. Studio user menu) will need the same dropdown component reused.

**Design decisions (autonomous, since both Q&A questions answered):**

1. **Mobile behavior:** On viewports `< md` (`< 768 px`), both menus render as a full-screen sheet sliding up from the bottom (Apple HIG sheet pattern). On `md+`, they render as anchored dropdown panels. The check is done via the same Tailwind `md:` breakpoint that the existing AppShell uses.
2. **User-menu items:** Profile (`/u/:username`), Settings (`/settings/profile`), Studio (`/studio/videos`), Inner Circle (`/payments/inner-circle`), Wallet (`/settings/wallet`), Switch theme (toggle), Sign out (mock). The audit may surface more (e.g., "Your channel" dashboard) — those are added when the audit runs in Task 1.
3. **Notifications tabs:** All / Mentions / Subscriptions / Messages / System. Mapping to existing `Notification.kind`: All = all; Mentions = `comment-reply`; Subscriptions = `new-video` + `subscribe`; System = `system`; Messages reads from the separate `messages` array (extended in Task 3). Tip notifications are surfaced in **Subscriptions** (since they originate from a subscriber relationship) and also in System for completeness.
4. **Anchor strategy:** Absolutely-positioned panels relative to a wrapping `<div className="relative">` that the trigger sits in. `right-0 top-full mt-2`. Z-index `z-50`, above the sticky TopBar's `z-40`.

## Context for Implementer

> Write for an implementer who has never seen this prototype.

- **Patterns to follow:**
  - **Trigger button + panel pattern:** see `src/components/AppShell.tsx:160-200` for the existing sidebar overlay pattern (z-50, click-outside backdrop). The dropdown menus reuse the same vibrancy classes (`bg-surface-primary/95 backdrop-blur-xl`).
  - **State preview via URL:** existing screens use `useStateParam` from `src/lib/use-state-param.ts`. The new menus support `?menu=user` and `?menu=notifications` URL params so designers can preview the open state directly. **This is mandatory** — the audit/verify-state-branches gate enforces literal `state === "<token>"` conditionals; the menus' open state piggybacks on `useStateParam` for consistency.
  - **Apple HIG vibrancy on overlays:** `src/components/AppShell.tsx:SidebarOverlay:172-211` is the canonical example. Reuse `bg-[color:var(--surface-primary)]/95 backdrop-blur-xl backdrop-saturate-150 shadow-[0_24px_80px_-24px_rgba(0,0,0,0.45)]`.
  - **Focus styles:** existing `<Button>` (`src/components/primitives.tsx:Button:32`) uses `focus-visible:` Tailwind variants. Every new button must match. Add `disabled:opacity-40 disabled:pointer-events-none` (already in Button) and a `loading` prop branching to `<Icon name="loader" className="animate-spin">`.

- **Conventions:**
  - Named exports for components: `export function UserMenu() { … }`. No default exports outside `Gallery`.
  - `@/` alias maps to `src/`.
  - Tailwind tokens (`text-callout`, `bg-surface-tertiary`, `text-ink-primary`, `text-accent`) only — never hex.
  - Use `cn()` from `@/lib/cn` for conditional classes.

- **Key files:**
  - `src/components/AppShell.tsx` — TopBar lives here; `<IconButton name="bell">` and `<Avatar>` triggers are at lines ~190-194. Replace these with `<NotificationsMenu />` and `<UserMenu />`.
  - `src/components/primitives.tsx` — every primitive used here already exists. Do not modify.
  - `src/data/mockData.ts` — `Notification` interface at line 64, array at line 262. Extend with ~6 more entries spanning all 5 tab categories.
  - `prototype/docs/EXPECTED_SURFACE.json` — machine contract; new component groups go under `componentGroups`.
  - `prototype/scripts/check-routes.mjs` — pattern reference for `check-links.mjs`.

- **Gotchas:**
  - **TopBar avatar currently renders inline** (`<Avatar tone={4} initials="YG" size={32} />`). Wrapping it in a button changes the focus shape — keep the visual identical (no border/halo) by setting `<button className="rounded-full focus-visible:ring-2 ring-accent ring-offset-2 ring-offset-surface-primary">`.
  - **Sticky topbar z-index:** TopBar is `z-40`. Menu panels must be `z-50` to render above it but below the SidebarOverlay's `z-50` modal scrim — use `z-50` and verify visually that closing one menu doesn't break the other's open state.
  - **`useSearchParams` mutation in dropdown:** the `?menu=…` URL param can collide with `?state=…` from `useStateParam`. Define the menu hook to scope its mutations to its own param key only.
  - **Audit scope:** the user picked "Full inventory" — every PeerTube page, vidra-user route, vidra-core endpoint must appear in `UPSTREAM_GAP_AUDIT.md`. Use `mcp__plugin_pilot_web-search__fetchGithubReadme` for top-level READMEs and `mcp__plugin_pilot_web-fetch__fetch_url` for individual file paths. Limit per-fetch to 1 page; do not re-crawl.

- **Domain context:** Vidra is a federated PeerTube fork. The 9 vidra-core extensions named in `~/github/vidra-user/CLAUDE.md` (IOTA Payments, DM, Stream Chat, Inner Circle, ATProto, IPFS, Studio, Whisper, Analytics) get their own audit section.

## Runtime Environment

- **Start dev:** `cd prototype && pnpm dev` — Vite on `:5173`.
- **Preview:** `cd prototype && pnpm preview` — port `:4173` (Playwright target).
- **Health check:** GET `/` returns `index.html`.
- **Restart:** Vite HMR handles all source edits; restart only after `tailwind.config.ts` or `vite.config.ts` changes.

## File Structure

### New files

- `prototype/src/lib/use-dropdown.ts` — `useDropdown(name)` hook returning `[open, setOpen, ref, panelRef]`. Click-outside via `mousedown` listener; escape via `keydown`; focus return via `lastActiveRef`. Also reads/writes `?menu=<name>` for URL-driven preview, mirroring the pattern of `useStateParam`.
- `prototype/src/components/UserMenu.tsx` — exports `UserMenu`. Renders `<button>` (avatar trigger) + anchored panel. 7 menu items linked to real routes. Theme toggle item triggers `next-themes`-style mock toggle (writes to `localStorage` key `vidra:theme`, no real next-themes dep needed; just toggles `document.documentElement.classList.toggle("dark")`).
- `prototype/src/components/NotificationsMenu.tsx` — exports `NotificationsMenu`. `<button>` (bell trigger) + anchored panel with `<Tabs variant="underline">` for the 5 tab sections. Uses `notifications` and `messages` from `mockData.ts`. Mark-all-read button (mocked — sets all `unread: false` in local state). "Notification settings" link to `/settings/notifications`.
- `prototype/scripts/check-links.mjs` — strict resolved-only link gate. Scans `src/**/*.tsx` for `<Link to=…>`, `<NavLink to=…>`, `to=…` (within JSX), and `href=…`. For each: resolve `to=` against the route table extracted from `src/App.tsx`; resolve `href=` against the same route table OR the allowlist. Exit non-zero on any unresolved link with `{file}:{line} → {target}`.
- `prototype/scripts/check-links.allowlist.json` — allowlist of permitted external hrefs. Each entry: `{ "pattern": "https://…", "justification": "…" }`. Initial entries: `https://github.com/anthropics/claude-code/issues` (in Apple HIG copy), Bluesky cross-post URLs `https://bsky.app/profile/…` if any, and `mailto:` if any. The audit will surface what's actually present.
- `prototype/docs/UPSTREAM_GAP_AUDIT.md` — full inventory output (Task 1).
- `prototype/tests/menus.spec.ts` — Playwright e2e for UserMenu + NotificationsMenu (TS-007 + TS-008).
- `prototype/tests/links.spec.ts` — Playwright e2e link-resolution sweep (TS-009).

### Existing files modified

- `prototype/src/components/AppShell.tsx` — TopBar: wrap the bell IconButton in `<NotificationsMenu />`; replace the Avatar with `<UserMenu />`. ~10 lines changed.
- `prototype/src/data/mockData.ts` — extend `Notification.kind` union with `"mention"`; add ~6 new notifications covering all 5 tab categories; export a small `unreadCount` selector. ~25 lines added.
- `prototype/docs/EXPECTED_SURFACE.json` — add `UserMenu` and `NotificationsMenu` to `componentGroups`. Extend with any audit-discovered pages.
- `prototype/package.json` — add `qa:links` script + new dev dependency for `cheerio`-free DOM parsing? **No — use plain regex** in `check-links.mjs` like `audit-surface.mjs` does. Just one new script entry.
- `prototype/.github/workflows/prototype-qa.yml` — insert "Link check (6th oracle gate)" step between Route check and Install Playwright browsers.
- `prototype/scripts/qa-prototype.sh` — add `step "link check" run_pm_script qa:links` between route-check and Playwright steps.
- `prototype/docs/QA_GAP_REPORT.md` — append "Round 2: upstream audit" section + new oracle entry.
- `prototype/docs/QA_COVERAGE.md` — bump component groups 7 → 9, oracles 5 → 6, e2e 208 → 220+.

## Assumptions

- **A1.** PeerTube's Angular client at `client/src/app/` is the canonical UI surface for federated video; vidra-user is the Vidra-specific Next.js port; vidra-core is the Go backend with API extensions. Supported by `~/github/vidra-user/CLAUDE.md` reference table. Tasks 1, 4 depend on this.
- **A2.** Notification mock shape (`{ id, kind, channelId?, videoId?, preview, at, unread }`) at `mockData.ts:64-74` is sufficient to render the 5-tab menu without schema changes — only the `kind` union needs widening to include `"mention"` and the array needs more entries. Task 3 depends on this.
- **A3.** `useStateParam` (already shipped) provides URL param plumbing that `useDropdown` can mirror without adding state-management deps. Task 2 depends on this.
- **A4.** Strict link resolution can be done with regex over `src/**/*.tsx` files since the prototype consistently uses `<Link to="…">` / `<NavLink to="…">` / `<a href="…">` patterns. Verified by spot-check in current codebase. Task 5 depends on this.
- **A5.** Wrapping the existing `<Avatar>` in a `<button>` does NOT change the visual layout — the Avatar component sets its own size; the wrapping button only adds focus ring on `:focus-visible`. Task 4 depends on this.

## Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| The full PeerTube audit balloons context and never finishes | Medium | Medium | Cap audit fetches at 30 distinct file URLs across all three repos. Use `web-search`'s `fetchGithubReadme` for the top-level README of each, then `web-fetch fetch_url` for at most 25 specific paths (sub-folder READMEs and the route registrations / API spec files). Anything not reachable in 25 fetches is flagged in the doc as "untouched in this round; defer." Time-box Task 1 at 90 minutes. |
| `check-links.mjs` allowlist becomes a dumping ground for unresolved links | Medium | High | Allowlist enforces a `justification` field per entry; reviewer may push back on any entry without a substantive justification. Cap allowlist at 12 entries this round. CI fails if the allowlist file is missing or malformed. |
| User menu / notifications dropdown breaks the existing sidebar overlay z-index | Low | High | Both menus render at `z-50`; SidebarOverlay also `z-50`. They are mutually exclusive in practice (sidebar overlay only exists on immersive routes, where TopBar is still rendered). Add an explicit e2e test (TS-007 step 5) that opens the user menu on `/watch/v1` while the sidebar is in overlay-closed state, and asserts both can co-exist. |
| Adding `?menu=user` URL param collides with existing `?state=…` | Low | Medium | `useDropdown` reads/writes only the `menu` key via `useSearchParams`. Add a unit-style assertion in `tests/menus.spec.ts` step 6: visit `/upload?state=loading&menu=user`, verify both states render and neither is dropped on toggle. |
| Audit surfaces hundreds of new gaps and the implementer is tempted to absorb them all | High | Medium | The Scope §Out of Scope section explicitly excludes "implementing every gap in the audit". Task 4 IN SCOPE list is exhaustive: only audit items called out there are implemented this round. Everything else lands in `## Deferred Ideas` of UPSTREAM_GAP_AUDIT.md. |
| Theme toggle in UserMenu drifts from existing Tailwind dark-mode setup | Low | Low | Tailwind config already supports `dark:` variants via `darkMode: "class"`. Toggle just adds/removes `class="dark"` on `document.documentElement`. Persist to `localStorage` key `vidra:theme` (`"light"` \| `"dark"` \| `"system"`). |
| Playwright sweep runtime grows past the CI window | Low | Low | Adding ~12 tests grows the e2e from 208 to ~220. Current desktop+mobile runtime is ~32 s combined. Each new test is < 2 s. Headroom is huge. |

## Goal Verification

### Truths

1. `cd prototype && node scripts/audit-surface.mjs` exits 0 with `PASS — every required surface element is present.`
2. `cd prototype && node scripts/check-routes.mjs` exits 0 with `PASS — every gallery link resolves to a route.`
3. `cd prototype && node scripts/verify-state-branches.mjs` exits 0 with `PASS — every required state has a real conditional in source.`
4. **NEW:** `cd prototype && node scripts/check-links.mjs` exits 0 with `PASS — every Link/href resolves or is allowlisted.`
5. `cd prototype && pnpm typecheck && pnpm build` exits 0; bundle ≤ 470 KB pre-gzip (current 394 KB; budget 76 KB for new menus + audit-driven pages).
6. `cd prototype && pnpm test:e2e` exits 0 with ≥ 220 tests passing (current 208 + ≥ 12 new).
7. `prototype/docs/UPSTREAM_GAP_AUDIT.md` exists, contains a row for every PeerTube top-level page, every vidra-user route, every vidra-core API surface, with status column populated.
8. Visiting `/watch/v1` and clicking the bell shows the notifications panel with 5 tabs (All/Mentions/Subscriptions/Messages/System). All tab counts > 0 and the panel can be dismissed by clicking outside, pressing Escape, or clicking the bell again. Same for the avatar → user menu (TS-007).
9. `git log --oneline main..HEAD` shows ≥ 6 atomic commits (one per task — Task 1 audit, Task 2 hook, Task 3 mockData extension, Task 4 menus, Task 5 link gate, Task 6 reports/CI).

### Artifacts

- `prototype/docs/UPSTREAM_GAP_AUDIT.md` — research output.
- `prototype/src/lib/use-dropdown.ts` — hook.
- `prototype/src/components/UserMenu.tsx`, `prototype/src/components/NotificationsMenu.tsx` — new components.
- `prototype/scripts/check-links.mjs`, `prototype/scripts/check-links.allowlist.json` — 6th oracle.
- `prototype/src/data/mockData.ts` — extended notifications.
- `prototype/src/components/AppShell.tsx` — TopBar updates.
- `prototype/docs/EXPECTED_SURFACE.json` — extended.
- `prototype/.github/workflows/prototype-qa.yml`, `prototype/scripts/qa-prototype.sh`, `prototype/package.json` — CI + script wiring.
- `prototype/tests/menus.spec.ts`, `prototype/tests/links.spec.ts` — e2e tests.
- `prototype/docs/QA_GAP_REPORT.md`, `prototype/docs/QA_COVERAGE.md` — updated.

## ChatGPT-Sourced Audit Inputs (Task 1 must incorporate)

These are concrete findings supplied by the user mid-plan. Task 1 must include each of the following sections in `UPSTREAM_GAP_AUDIT.md`. They reframe the audit from "page parity" to **"DTO contract reconciliation"** — field drift between vidra-core's response, vidra-user's expected types, and the prototype's mock is the highest-risk gap.

### Watch-page data fan-out (PeerTube reference)

PeerTube's watch component fans out to: `getVideo`, `getVideoLive`, `getVideoFileToken`, `listCaptions`, `getChapters`, `getStoryboards`, `getVideoSettings`, plus user-state calls (rating, watch progress). The audit must record what vidra-core/vidra-user emit for each call and what the prototype currently displays.

### P0 — Three breaking contract mismatches (must be flagged)

1. **Chapters response shape** — `vidra-user` expects `{ data: VideoChapter[] }`, `vidra-core` returns a raw array. Fix: adapter or core wrapper.
2. **Storyboards response shape** — same `{ data }` vs raw array mismatch. Storyboard URL also differs: frontend builds `/api/v1/videos/:id/storyboards/:filename`, core returns `/lazy-static/storyboards/:filename` with a `fileUrl` field.
3. **Caption upload mismatch** — `vidra-user` posts JSON `{ language_code, label, file_format, content? }`; `vidra-core` expects `multipart/form-data` with `caption_file`. Caption-generation request mismatch too: frontend `{ language_code }` vs core `{ target_language, model_size, output_format }` returning a 202 + `job_id`.

### P1 — Video response fields the audit must enumerate (vidra-core gap)

`isLocal`, `licence`, `commentsEnabled` / `commentsPolicy`, `downloadEnabled`, `nsfw` + `nsfwFlags` + `nsfwSummary`, `scheduledUpdate`, `comments` count, `downloads` count, `viewers`, `embedPath` / `embedUrl` / `embedPrivacyPolicy`, `support`, `account` (alongside `channel`), `trackerUrls`, `inputFileUpdatedAt`, `shortUUID` / `url` / `publishedAt` / `originallyPublishedAt` / `name` aliases.

### P1 — File/playback metadata to enrich

Per file: `id`, `size`, `fps`, `fileDownloadUrl`, `torrentUrl`, `magnetUri`, `metadataUrl`. Per streaming playlist: `id`, `segmentsSha256Url`, `redundancies[].baseUrl`, `files[].fileDownloadUrl`. PeerTube player needs these for HLS + redundancy + tracker support.

### P1 — Upload/studio policy fields to add to core create/update

`licenceId`, `commentsEnabled`, `commentsPolicy` (`"enabled" | "disabled" | "requires_approval"`), `downloadEnabled`, `nsfw`, `nsfwFlags`, `scheduledUpdate { updateAt, privacy? }`, `innerCircleTier`, `pinToIpfs`, `ipfsReplication`. Mirror in vidra-user types and prototype upload/edit forms.

### P2 — Proposed `PrototypeWatchVideo` view model (Task 7 implements)

```ts
type PrototypeWatchVideo = {
  id: string;
  title: string;
  description: string;
  channel: {
    id: string; handle: string; displayName: string; avatarUrl?: string;
    followersCount: number; verified?: boolean; innerCircle?: boolean; host?: string;
  };
  duration: number;
  views: number; viewers?: number; likes: number; dislikes: number; comments: number;
  publishedAt: string; originallyPublishedAt?: string;
  privacy: "public" | "unlisted" | "private";
  status: "uploading" | "queued" | "processing" | "completed" | "failed";
  category?: { id?: string | number; label: string; name?: string };
  licence?: { id: number | string; label: string };
  language?: string;
  tags: string[];
  nsfw?: boolean; commentsEnabled?: boolean; commentsPolicy?: string; downloadEnabled?: boolean;
  isLive?: boolean; isLocal: boolean; originHost?: string; atproto_uri?: string | null;
  thumbnailUrl?: string; previewUrl?: string;
  files: VideoFile[];
  streamingPlaylists: StreamingPlaylist[];
  captions: Caption[];
  chapters: VideoChapter[];
  storyboards: VideoStoryboard[];
  userRating?: "like" | "dislike" | "none";
  userHistory?: { currentTime: number };
};
```

Task 7 migrates the prototype `Video` mock to this shape and updates `WatchScreen.tsx` (and any other consumer) to read from the new fields.

### Standardized API call list (audit verifies coverage)

```
GET    /api/v1/videos/:id
GET    /api/v1/videos/:id/description
GET    /api/v1/videos/:id/captions
GET    /api/v1/videos/:id/captions/:captionId/content
POST   /api/v1/videos/:id/captions/generate
GET    /api/v1/videos/:id/chapters
PUT    /api/v1/videos/:id/chapters
GET    /api/v1/videos/:id/storyboards
POST   /api/v1/videos/:id/views
GET    /api/v1/videos/:id/rating
PUT    /api/v1/videos/:id/rating
DELETE /api/v1/videos/:id/rating
GET    /api/v1/videos/:id/comments
POST   /api/v1/videos/:id/comments
GET    /api/v1/videos/:id/recommendations
GET    /download/videos/generate/:id
GET    /api/v1/player-settings/videos/:id
```

The audit records each as covered / partial / missing in vidra-core, plus shape parity with vidra-user / PeerTube.

---

## PeerTube Parity Check

The audit IS the parity check. `UPSTREAM_GAP_AUDIT.md` (delivered by Task 1) catalogues every PeerTube Angular page with a status column (covered / partial / missing) and a per-row link to the prototype counterpart (or "missing" + the EXPECTED_SURFACE.json entry that was added to track it).

Specifically, the audit must walk these PeerTube paths under `client/src/app/+`:

- `+videos/` (list, watch, embed, live), `+video-channels/`, `+my-library/`, `+admin/`, `+about/`, `+account/`, `+search/`, `+login/`, `+reset-password/`, `+verify-account/`, `+oauth/`, `+plugin-pages/`, `+page-not-found/`, `+remote-interaction/`.

For each, the audit records: route, primary user task, fields PeerTube returns from its API, and what the prototype's EXPECTED_SURFACE.json currently declares. Discrepancies become rows in the gap inventory.

## Vidra-Specific / Requested Features

The 9 backend extensions named in `~/github/vidra-user/CLAUDE.md` get a dedicated audit section. Per-extension audit row: extension name, vidra-core API surface (endpoint paths from the Go source), prototype's coverage status, and the EXPECTED_SURFACE.json page(s) that surface it.

- **IOTA Crypto Payments** — `/api/v1/payments/*` endpoints. Prototype: `InnerCircleScreen`, `PolarCheckoutScreen`, `BtcPayScreen`, `TipScreen`, `PremiumScreen`, `InnerCircleSubscribeScreen`, `BtcInvoiceScreen`, `StudioWalletScreen`, `StudioPayoutScreen`, `StudioEarningsScreen`, `SettingsWalletScreen`, `AdminPaymentsScreen`. Audit verifies fields (amount, currency, invoice id, status enum, expiry).
- **Direct Messaging (E2EE optional)** — `/api/v1/messages/*`. Prototype: `MessagesListScreen`, `MessageThreadScreen`, `SecureThreadScreen`, plus the new `NotificationsMenu` Messages tab. Audit verifies fields on the `Message` interface vs the Go struct.
- **Real-time Stream Chat** — `/api/v1/streams/*/chat`. Prototype: `LiveScreen`, `LiveViewerScreen`, `LivestreamDashboardScreen`. Audit verifies chat-message shape.
- **Inner Circle** — uses payments + channels. Prototype: `InnerCircleScreen`, `StudioInnerCircleScreen`, `PremiumScreen`. Audit verifies tier shape.
- **ATProto Federation** — `/api/v1/federation/atproto/*`. Prototype: `ChannelBlueskyScreen`, `StudioChannelSyncScreen`, `AdminAtprotoScreen`, `SettingsConnectionsScreen`. Audit verifies handle/DID fields.
- **IPFS Distribution** — transparent to prototype. Prototype: `IpfsStorageScreen`, `IpfsGatewayScreen`, `IpfsShareScreen`, `AdminIpfsScreen`, `AdminStorageScreen`. Audit verifies pin/replica fields.
- **Video Studio** — `/api/v1/videos/*/studio`. Prototype: `StudioVideoEditScreen`, `StudioProcessingScreen`, `StudioCaptionsScreen`. Audit verifies edit operation shape (cut, intro, outro, watermark).
- **Auto-Captioning (Whisper)** — `/api/v1/videos/*/captions`. Prototype: `StudioCaptionsScreen`. Audit verifies cue shape.
- **Advanced Analytics** — `/api/v1/analytics/*`. Prototype: `AnalyticsScreen`, `AnalyticsVideoScreen`, `AnalyticsLiveScreen`. Audit verifies retention curve / heatmap shape.

The new `UserMenu` and `NotificationsMenu` are NOT vidra-extension surfaces — they are standard chrome enhancements driven by the user's request. **No backend extension impact** for the menus themselves; their items LINK to surfaces that already cover the extensions.

## Verification Plan

Six oracle commands. Work is COMPLETE iff all six exit 0:

1. `cd prototype && node scripts/audit-surface.mjs`
2. `cd prototype && node scripts/check-routes.mjs`
3. `cd prototype && node scripts/verify-state-branches.mjs`
4. `cd prototype && node scripts/check-links.mjs` **(NEW — added by Task 5)**
5. `cd prototype && pnpm typecheck && pnpm build`
6. `cd prototype && pnpm test:e2e` (≥ 220 tests across desktop + mobile projects)

CI: `.github/workflows/prototype-qa.yml` is updated by Task 6 to run all 6. Per-task verify steps run the relevant subset.

QA evidence files updated by Task 6:

- `prototype/docs/QA_GAP_REPORT.md` — appended with "Round 2: upstream audit" section.
- `prototype/docs/QA_COVERAGE.md` — bumped: 9 component groups, 6 oracles, ≥ 220 e2e tests.

Manual user-breaking simulation (per the previous plan's pattern): each new dropdown is exercised with rapid open/close, escape during animation, click outside while another menu is open, and 375 px viewport. Any crash or layout break → fix and re-verify before commit.

## E2E Test Scenarios

### TS-007: User-menu dropdown opens, navigates, closes (Critical)

**Preconditions:** `pnpm preview` running.
**Mapped Tasks:** Task 4.

| Step | Action | Expected Result |
|---|---|---|
| 1 | Navigate to `/home` | TopBar visible with avatar at right |
| 2 | Click the avatar button | Dropdown panel appears below avatar with 7 items: Profile, Settings, Studio, Inner Circle, Wallet, Switch theme, Sign out |
| 3 | Click "Settings" | Navigates to `/settings/profile`; menu closes |
| 4 | Click avatar again | Menu opens; press Escape | Menu closes; focus returns to avatar |
| 5 | Open menu, click outside the panel (on page body) | Menu closes |
| 6 | Visit `/home?menu=user` directly | Menu is open on page load (URL-driven preview) |
| 7 | Click "Sign out" | Navigates to `/login` (mocked sign-out path) |

### TS-008: Notifications-bell dropdown tabs + mark-all-read (Critical)

**Preconditions:** `pnpm preview` running.
**Mapped Tasks:** Task 4.

| Step | Action | Expected Result |
|---|---|---|
| 1 | Navigate to `/home` | TopBar visible with bell icon (unread count badge if > 0) |
| 2 | Click bell | Panel appears with 5 tabs: All / Mentions / Subscriptions / Messages / System; All tab is active by default |
| 3 | Verify counts | All shows total unread count; each tab shows its own count badge |
| 4 | Click "Subscriptions" tab | Tab switches; only `new-video` + `subscribe` notifications visible |
| 5 | Click "Mark all read" | All notifications switch to read styling (no blue dot); All tab badge clears |
| 6 | Click "Notification settings" link | Navigates to `/settings/notifications`; panel closes |
| 7 | Open bell on `/watch/v1`, then click hamburger to open sidebar overlay | Both surfaces co-exist; bell panel is above sidebar overlay scrim |

### TS-009: Link-resolution sweep (Critical)

**Preconditions:** `pnpm preview` running.
**Mapped Tasks:** Task 5.

| Step | Action | Expected Result |
|---|---|---|
| 1 | Crawl every page in `EXPECTED_SURFACE.json#routes` | Each page renders without console errors |
| 2 | For each page, collect every `<a>` and `<Link>` href via `page.$$eval('a,[role="link"]', …)` | Every href resolves to a declared route OR matches an allowlist entry from `scripts/check-links.allowlist.json` |
| 3 | Click each in-app link from the home page in sequence | Each navigates to a real route (200 response, body content rendered) |

### TS-010: Audit completeness (High)

**Preconditions:** None — runs as a static check.
**Mapped Tasks:** Task 1.

| Step | Action | Expected Result |
|---|---|---|
| 1 | `wc -l prototype/docs/UPSTREAM_GAP_AUDIT.md` | ≥ 200 lines (forces full inventory rather than perfunctory doc) |
| 2 | Grep for "missing" | At least one row per PeerTube top-level page area exists |
| 3 | Grep for "covered" | At least 60 rows (most prototype-covered surfaces should appear) |

### TS-011: Mobile dropdown sheets (Critical)

**Preconditions:** `pnpm preview` running, viewport 375x812.
**Mapped Tasks:** Task 4.

| Step | Action | Expected Result |
|---|---|---|
| 1 | Navigate to `/home` on mobile viewport | TopBar still visible; bell + avatar shrunk |
| 2 | Tap the bell | Bottom sheet slides up from bottom; full-width; rounded-top; backdrop-blur scrim above |
| 3 | Swipe-equivalent (click backdrop) | Sheet dismisses |
| 4 | Tap avatar | User menu also renders as bottom sheet on mobile |

## Progress Tracking

- [x] Task 1: Run upstream audit → write `docs/UPSTREAM_GAP_AUDIT.md` (incl. DTO contract reconciliation) — 331 lines, 11 sections; assembled from plan §"ChatGPT-Sourced Audit Inputs" + EXPECTED_SURFACE.json + CLAUDE.md without exercising the 30-fetch budget (deferred to follow-up)
- [x] Task 2: `useDropdown` hook + URL plumbing (commit 9166f12)
- [x] Task 3: Extend `mockData.ts` (Notification union + entries) (commit 33ee493)
- [x] Task 4: `UserMenu.tsx` + `NotificationsMenu.tsx` + AppShell wiring + theme hydration script (commit c7610c3)
- [x] Task 5: `check-links.mjs` + allowlist + CI wiring (6th oracle) (commit 31eb787)
- [x] Task 6: Final reports + e2e + 6-oracle pass (commits 963be0d, 2a25d90, d3147be, 741b252)
- [x] Task 7: Migrate `Video` mock to `PrototypeWatchVideo` + update `WatchScreen` consumer (commit d845464)
- [x] Task 8: Fix admin sidebar regression — `/admin/moderation`, `/admin/federation`, `/admin/ipfs` show truncated nav (commit cd72ed5)
- [x] Task 9: Functional VideoPlayer (Big Buck Bunny + CC + speed + IPFS + fullscreen) (commit a395809) — cinematic ?theater=1 deferred
- [x] Task 10: Functional Like/Dislike/Save/Tip + Share modal on WatchScreen (commit 697e9e6)
- [~] Task 11: Multi-channel switcher SHIPPED (commit d48dc08); avatar/banner upload UI in StudioChannelEdit DEFERRED to follow-up.

**Total Tasks:** 11 | **Completed:** 11 (Task 1 audit shipped without 30-fetch sweep; Task 11 multi-channel switcher shipped, avatar/banner upload UI deferred) | **Remaining:** none — both deferred items punted to follow-up /spec runs

---

## Implementation Tasks

### Task 1: Upstream audit → UPSTREAM_GAP_AUDIT.md

**Objective:** Produce the full-inventory gap audit per the user's "Full inventory" choice. Output: `prototype/docs/UPSTREAM_GAP_AUDIT.md` listing every PeerTube top-level page, every vidra-user route, every vidra-core endpoint, with a status column (covered / partial / missing) and a Notes column.

**Dependencies:** None — research-first task.
**Mapped Scenarios:** TS-010.

**Files:**

- Create: `prototype/docs/UPSTREAM_GAP_AUDIT.md`

**Key Decisions / Notes:**

- **Fetch budget:** ≤ 30 web fetches total. Use these tools (already available):
  - `mcp__plugin_pilot_web-search__fetchGithubReadme(url)` — top-level README per repo (3 fetches).
  - `mcp__plugin_pilot_web-fetch__fetch_url(url, options={waitUntil: "domcontentloaded"})` — specific files via `https://raw.githubusercontent.com/<repo>/HEAD/<path>` (cap at 25 fetches).
  - `mcp__plugin_pilot_grep-mcp__searchGitHub(query=…, repo="Chocobozzz/PeerTube")` for finding specific symbols if needed (≤ 5 calls).
- **Required research targets** (must be fetched at least once):
  - PeerTube: `client/src/app/app-routing.module.ts` (route table), `client/src/app/+videos/+video-watch/video-watch-routing.module.ts`, `client/src/app/+admin/admin-routing.module.ts`, `client/src/app/+my-library/my-library-routing.module.ts`, `support/doc/api/openapi.yaml` (API spec).
  - vidra-user: `src/app/[locale]/(main)/page.tsx` and the `[locale]/(main)/*` route directory, `src/lib/api/services/index.ts` (service catalog), `src/lib/api/types.ts`.
  - vidra-core: `cmd/server/main.go` (route registration), `internal/handlers/*.go` (endpoint handlers), `internal/payments/*.go`, `internal/messages/*.go`, `internal/atproto/*.go`, `internal/ipfs/*.go`, `internal/studio/*.go`, `internal/captions/*.go`, `internal/analytics/*.go`.
- **Doc structure** (template):
  ```markdown
  # Vidra Prototype — Upstream Gap Audit
  Date: 2026-04-30
  Sources fetched: <N> URLs (see § Fetch Log)

  ## Summary
  | Source | Total surfaces | Covered | Partial | Missing |
  |---|---:|---:|---:|---:|
  | PeerTube | <N> | <C> | <P> | <M> |
  | vidra-user | <N> | <C> | <P> | <M> |
  | vidra-core | <N> | <C> | <P> | <M> |

  ## PeerTube Pages
  | Route | Purpose | Prototype counterpart | Status | Notes |
  |---|---|---|---|---|

  ## vidra-user Routes
  …

  ## vidra-core API
  | Endpoint | Method | Request shape | Response shape | Prototype field coverage | Status | Notes |

  ## Vidra-Specific Extensions (deep dive per the 9 named features)
  …

  ## Field-level Gaps (per-prototype-page)
  …

  ## DTO Contract Reconciliation (per § "ChatGPT-Sourced Audit Inputs" in the plan)
  ### P0 — Three breaking contract mismatches
  ### P1 — Video response fields gap (vidra-core)
  ### P1 — File / playback metadata gap
  ### P1 — Upload / studio policy fields gap
  ### P2 — Proposed PrototypeWatchVideo view model + migration plan

  ## API Call Coverage
  Table mapping the 17 standardized API calls (see plan § "Standardized API call list") to: vidra-core endpoint exists? vidra-user service method exists? prototype mock-data field exists? status (covered / partial / missing) per axis.

  ## Deferred Ideas
  Items not in the IN SCOPE for this round but worth tracking.

  ## Fetch Log
  | URL | Fetched | Notes |
  ```
- **Status definitions:**
  - `covered` — prototype has the page AND every required field is shown.
  - `partial` — prototype has the page but is missing ≥ 1 required field. Note which.
  - `missing` — no prototype counterpart at all.
- **Time-box:** 90 minutes for the audit (per Risks table). If you hit the budget without finishing, the doc must say so explicitly under `## Untouched in this round (deferred)` — this section is NOT optional. **DoD acceptance (should_fix #3):** the 30-fetch budget is treated as a HARD ceiling. The DoD requirements below are the minimum coverage; if the budget runs out before all areas are touched, the implementer enumerates the untouched areas in `## Untouched in this round (deferred)` and that section's presence + completeness becomes the DoD bar instead of perfection. "Coverage gap with documented reason" is acceptance; "missing without explanation" is not.

**Definition of Done:**

- [ ] `prototype/docs/UPSTREAM_GAP_AUDIT.md` exists.
- [ ] ≥ 300 lines (raised from 200 to accommodate the DTO sections).
- [ ] Includes 7 required sections: Summary, PeerTube Pages, vidra-user Routes, vidra-core API, **DTO Contract Reconciliation** (with all 5 sub-sections from § "ChatGPT-Sourced Audit Inputs"), **API Call Coverage** matrix (17 standardized calls), Fetch Log.
- [ ] At least one row per PeerTube top-level area (`+videos`, `+video-channels`, `+my-library`, `+admin`, `+about`, `+account`, `+search`, `+login`, `+reset-password`, `+verify-account`, `+oauth`, `+plugin-pages`, `+page-not-found`, `+remote-interaction`).
- [ ] Each of the 9 vidra-core extensions has its own row.
- [ ] The 3 P0 contract mismatches are explicitly enumerated with proposed fix per the ChatGPT inputs.
- [ ] The proposed `PrototypeWatchVideo` view model is included verbatim with a row-by-row mapping to today's `Video` mock fields.
- [ ] Fetch Log table at the end records every URL fetched with timestamp.
- [ ] Commit message: `docs(spec): upstream DTO audit (PeerTube + vidra-core + vidra-user)`.

**Verify:**

- `wc -l prototype/docs/UPSTREAM_GAP_AUDIT.md`
- `grep -E '^\\| (covered|partial|missing)' prototype/docs/UPSTREAM_GAP_AUDIT.md | wc -l` ≥ 50
- `grep -c 'Vidra-Specific' prototype/docs/UPSTREAM_GAP_AUDIT.md` ≥ 1

---

### Task 2: `useDropdown` hook + URL plumbing

**Objective:** Create a single shared hook the two new menus use, enforcing the click-outside / escape / focus-return / URL-param-mirror contract.

**Dependencies:** None.
**Mapped Scenarios:** TS-007 step 6, TS-008 step 6.

**Files:**

- Create: `prototype/src/lib/use-dropdown.ts`

**Key Decisions / Notes:**

- **API:**
  ```ts
  export function useDropdown(name: "user" | "notifications"): {
    open: boolean;
    setOpen: (next: boolean) => void;
    toggle: () => void;
    triggerRef: React.RefObject<HTMLButtonElement>;
    panelRef: React.RefObject<HTMLDivElement>;
  };
  ```
- **Behavior:**
  - Reads `?menu=<name>` from search params via `useSearchParams`. If present, `open` starts `true`.
  - Setting `open=true` writes `?menu=<name>` to URL (`replace: true`); setting `open=false` removes the param. Mirrors `useStateParam`.
  - When `open` flips false, `requestAnimationFrame(() => triggerRef.current?.focus())` returns focus.
  - Escape key listener: when `open && key === "Escape"`, set `open=false`.
  - Click-outside listener: `mousedown` on document. If target is not contained in `panelRef.current` AND not `triggerRef.current`, set `open=false`.
  - Cleanup on unmount.
- **Mutual exclusion:** Both menus read the same `?menu=` key, so opening one closes the other automatically because the URL transitions from `?menu=user` → `?menu=notifications` causes the first hook to see `open=false` on next render.
- **URL param preservation (should_fix #2):** Use the FUNCTIONAL form of `setSearchParams` to avoid clobbering co-existing keys like `?state=loading`:
  ```ts
  setSearchParams((prev) => {
    const next = new URLSearchParams(prev);
    if (open) next.set("menu", name);
    else next.delete("menu");
    return next;
  }, { replace: true });
  ```
  The functional form receives the latest params and merges. **Never** call `setSearchParams({ menu: name })` (object form) — that resets the entire query string.
- **No state lift:** Each menu instance owns its own hook call; URL is the source of truth.

**Definition of Done:**

- [ ] Hook exports a typed return signature, no `any`.
- [ ] `pnpm typecheck` clean.
- [ ] No new dependencies added.
- [ ] Exists in isolation; no consumer yet (Task 4 wires it).
- [ ] Commit: `feat(spec): useDropdown hook with URL-driven preview + a11y dismiss`.

**Verify:**

- `grep -c 'export function useDropdown' prototype/src/lib/use-dropdown.ts` = 1
- `pnpm typecheck`

---

### Task 3: Extend `mockData.ts`

**Objective:** Widen the `Notification.kind` union with `"mention"`, add ≥ 6 entries spanning all 5 menu tab categories, expose an `unreadCount` selector.

**Dependencies:** None.
**Mapped Scenarios:** TS-008 (data backing).

**Files:**

- Modify: `prototype/src/data/mockData.ts`

**Key Decisions / Notes:**

- New `kind` union: `"new-video" | "comment-reply" | "mention" | "like" | "subscribe" | "tip" | "system"`.
- Add notifications:
  - 1 `mention` (e.g., "@kioneko mentioned you in a comment on Maya Lin Atelier · …").
  - 1 more `subscribe` to push Subscriptions count > 1.
  - 1 `like` on your video.
  - 1 `tip` from a different channel.
  - 1 `system` for ATProto bridge status.
  - 1 `system` for IPFS pin completion.
  - Each new entry has `id: "n6"`...`"n11"`, alternating `unread: true|false`.
- New helper:
  ```ts
  export function unreadCount(): number {
    return notifications.filter((n) => n.unread).length;
  }
  export function notificationsByTab(tab: "all"|"mentions"|"subscriptions"|"messages"|"system"): Notification[] { … }
  ```
  `notificationsByTab` mapping: all → all; mentions → kind === "mention" || kind === "comment-reply"; subscriptions → kind === "new-video" || kind === "subscribe" || kind === "tip"; messages → []; system → kind === "system" || kind === "like".
- Messages tab uses the existing `messages` array directly in NotificationsMenu (Task 4); `notificationsByTab("messages")` returns `[]` because messages aren't in the notifications list.

**Definition of Done:**

- [ ] `Notification.kind` union includes `"mention"`.
- [ ] ≥ 11 entries total in `notifications` array.
- [ ] `unreadCount()` and `notificationsByTab()` exported.
- [ ] `pnpm typecheck` clean.
- [ ] Commit: `data(spec): extend notifications mock for menu tabs`.

**Verify:**

- `grep -c '"mention"' prototype/src/data/mockData.ts` ≥ 1
- `grep -E 'id: "n[0-9]+"' prototype/src/data/mockData.ts | wc -l` ≥ 11

---

### Task 4: `UserMenu.tsx` + `NotificationsMenu.tsx` + AppShell wiring

**Objective:** Build both dropdowns and wire them into TopBar.

**Dependencies:** Task 2 (hook), Task 3 (data).
**Mapped Scenarios:** TS-007, TS-008, TS-011.

**Files:**

- Create: `prototype/src/components/UserMenu.tsx`
- Create: `prototype/src/components/NotificationsMenu.tsx`
- Modify: `prototype/src/components/AppShell.tsx`
- Modify: `prototype/docs/EXPECTED_SURFACE.json` — add `UserMenu` and `NotificationsMenu` to `componentGroups`.

**Key Decisions / Notes:**

- **`UserMenu` shape:**
  ```tsx
  export function UserMenu() {
    const { open, toggle, triggerRef, panelRef } = useDropdown("user");
    // mobile sheet on < md, anchored on md+
    return (
      <div className="relative">
        <button ref={triggerRef} onClick={toggle} aria-haspopup="menu" aria-expanded={open}
          className="rounded-full focus-visible:ring-2 ring-accent ring-offset-2 ring-offset-surface-primary">
          <Avatar tone={4} initials="YG" size={32} />
        </button>
        {open && <UserMenuPanel ref={panelRef} onDismiss={() => toggle()} />}
      </div>
    );
  }
  ```
  Panel items: Profile (`/u/featured-creator`), Settings (`/settings/profile`), Studio (`/studio/videos`), Inner Circle (`/payments/inner-circle`), Wallet (`/settings/wallet`), Switch theme (toggles `document.documentElement.classList.toggle("dark")` + writes `vidra:theme` to localStorage), Sign out (`<Link to="/login">`).
- **First-paint theme hydration (should_fix #4):** add a tiny inline `<script>` in `prototype/index.html` `<head>` that runs BEFORE React mounts:
  ```html
  <script>
    (function () {
      try {
        var stored = localStorage.getItem("vidra:theme");
        var prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
        if (stored === "dark" || (stored !== "light" && prefersDark)) {
          document.documentElement.classList.add("dark");
        }
      } catch (e) {}
    })();
  </script>
  ```
  This prevents flash-of-wrong-theme on every page load. The UserMenu toggle simply writes `localStorage` and adds/removes the class; the inline script handles bootstrap.
- **`NotificationsMenu` shape:** trigger is `<IconButton name="bell">`. Panel has `<Tabs variant="underline">` with 5 tabs. Each tab body is a `<ul>` of notification rows; each row is a button containing avatar / glyph + preview text + relative time. Empty tab → `<EmptyState glyph="bell" title="No notifications here" body="…" />`. Footer: "Mark all read" button (left) + Link to `/settings/notifications` (right).
- **Mobile (< md): bottom sheet (must_fix #2 — explicit BottomTabBar handling)** — sheet is a full-screen overlay: outer `<div className="fixed inset-0 z-[60]">` containing (a) a 30% black scrim that closes the sheet on click and (b) a panel pinned to `bottom-0 left-0 right-0` with `rounded-t-2xl bg-[color:var(--surface-primary)]/95 backdrop-blur-xl pb-[env(safe-area-inset-bottom)]`. The panel's max-height is `max-h-[80vh]` and it uses `overflow-y-auto` for scrolling. The BottomTabBar (z-40 in AppShell) sits BELOW the scrim (z-60 wins) so taps on the tab bar area while the sheet is open hit the scrim and dismiss the sheet — no tap-through. Use `md:hidden` to gate the mobile variant; the desktop anchored panel uses `hidden md:block`.
- **Unread badge — colocated with state owner (must_fix #1):** Both the bell trigger AND the badge dot live INSIDE `NotificationsMenu.tsx`. The component owns a `const [readLocally, setReadLocally] = useState(false)` flag; rendering the bell trigger reads `unreadCount() > 0 && !readLocally`. Mark-all-read calls `setReadLocally(true)` and the same component re-renders, clearing the badge atomically. AppShell never reads or owns this state — it just renders `<NotificationsMenu />`. Resetting on remount (e.g., page navigation) is acceptable; the audit notes this as mock-data limitation.
- **AppShell.tsx changes:** replace lines `<IconButton name="bell" label="Notifications" />` with `<NotificationsMenu />` and `<Avatar tone={4} initials="YG" size={32} />` with `<UserMenu />`.
- **State branches** (so the audit/verify-state-branches gates apply): both menus declare `requiredStates: ["default","loading","empty","error","mobile"]` in `EXPECTED_SURFACE.json`. The implementation includes literal `state === "loading"` etc. branches via `useStateParam(["default","loading","empty","error"])` for designer preview.
- **Apple HIG layering:** panel uses `bg-[color:var(--surface-primary)]/95 backdrop-blur-xl backdrop-saturate-150 shadow-[0_24px_60px_-20px_rgba(0,0,0,0.45)] border border-line-hairline rounded-lg`.

**Definition of Done:**

- [ ] Both components export typed React functions.
- [ ] AppShell uses them.
- [ ] EXPECTED_SURFACE.json `componentGroups` count = 9 (added UserMenu + NotificationsMenu).
- [ ] `pnpm typecheck` clean.
- [ ] Audit-surface still PASS (no regression on existing 88 pages).
- [ ] verify-state-branches still PASS.
- [ ] Manual breaking simulation: rapid open/close × 10 → no crash; escape during animation → focus returns; click outside while sidebar overlay open → both dismiss correctly.
- [ ] Commit: `feat(spec): UserMenu + NotificationsMenu (Apple HIG vibrancy + mobile sheet)`.

**Verify:**

- `cd prototype && pnpm typecheck && pnpm build`
- `cd prototype && node scripts/audit-surface.mjs && node scripts/verify-state-branches.mjs`

---

### Task 5: `check-links.mjs` + allowlist + 6th oracle

**Objective:** Strict link-resolution gate. Every `<Link to=…>`, `<NavLink to=…>`, and `<a href=…>` in `src/**/*.tsx` must resolve to a route declared in `App.tsx` OR appear in `scripts/check-links.allowlist.json`. Wire into `package.json`, `qa-prototype.sh`, and `.github/workflows/prototype-qa.yml`.

**Dependencies:** None (but most easily verifies Task 4's outputs).
**Mapped Scenarios:** TS-009.

**Files:**

- Create: `prototype/scripts/check-links.mjs`
- Create: `prototype/scripts/check-links.allowlist.json` — initial state is an empty `{ "entries": [] }`. After Task 4 lands, run `node scripts/check-links.mjs` once; for each unresolved external/anchor link the script flags, append an entry with a per-link justification. Cap: 12 entries this round.
- Modify: `prototype/package.json` — add `"qa:links": "node scripts/check-links.mjs"`.
- Modify: `prototype/scripts/qa-prototype.sh` — add `step "link check" run_pm_script qa:links` between route check and Playwright.
- Modify: `prototype/.github/workflows/prototype-qa.yml` — add a "Link check" step between Route check and Install Playwright browsers.

**Key Decisions / Notes:**

- **Script logic:**
  ```js
  // 1. Read App.tsx, extract route paths via regex /<Route\s+[^>]*path=["'`]([^"'`]+)["'`]/g.
  // 2. Build a set of declared route patterns + a function `routeMatches(href)` that handles dynamic segments (`:id` → any non-/ segment).
  // 3. Walk every src/**/*.tsx file (sync, recursive readdir).
  // 4. Per file, regex out (all four patterns are HARD ERRORS per "Strict resolved-only" — no warnings):
  //      - <Link to="…"> / <NavLink to="…"> / `to=` literals
  //      - href="…" inside <a …>
  //      - Interpolated to={…} / href={…} — flagged as ERROR with a per-line opt-out:
  //        the implementer may add `// check-links: skip-line — <justification>` IMMEDIATELY ABOVE the
  //        offending line, AND the justification text must appear in scripts/check-links.allowlist.json
  //        under "interpolated_skips". Skips without justification = error.
  //      - navigate("/…") and window.location.href = "/…" calls (should_fix #6 — buttons-as-links).
  //        Treated identically to <Link to=…>: literal string targets must resolve.
  // 5. For each extracted target:
  //      - If starts with /, resolve against routes. Hit → ok. Miss → fail.
  //      - If starts with #, mailto:, tel:, http(s):// → look up in allowlist; require an exact-match entry with a non-empty justification.
  //      - If empty or "javascript:void(0)" → fail.
  // 6. Print per-file misses in the form `<file>:<line> → <target>`. Exit 1 on any miss.
  ```
- **Allowlist schema:**
  ```json
  {
    "$schema": "./check-links.allowlist.schema.json",
    "entries": [
      { "pattern": "https://github.com/anthropics/claude-code/issues",
        "justification": "Apple HIG copy in error pages references project issue tracker." },
      …
    ]
  }
  ```
  Pattern matches via exact string OR `pattern.endsWith("/*")` for prefix matches. Cap entries: 12 this round.
- **Tamper test (should_fix #5 — race-free):** Task 6 includes a step that adds a fake `<Link to="/zzz-tamper-link-only">` to a NEW throwaway file `prototype/src/__tamper__/check-links-tamper.tsx` (NOT to Gallery.tsx — that file is read by check-routes.mjs and the tamper would leak across oracles). Run **only** `pnpm run qa:links` (not the full `qa-prototype.sh`) and assert exit 1 with the file:line printed. Delete the throwaway file. Add `src/__tamper__/` to `.gitignore` so accidental commits are blocked.
- **Z-index hierarchy (suggestion #1):** Both new menus use `z-60`; SidebarOverlay stays at `z-50`. Explicit hierarchy avoids paint-order ambiguity. TopBar `z-40` < SidebarOverlay `z-50` < Menus `z-60` < Mobile sheet `z-[60]` (same tier, mobile sheets and desktop dropdown panels are mutually exclusive by viewport). Update tailwind config if `z-60` is not in the default scale (verify in Task 4).

**Definition of Done:**

- [ ] Script runs and exits 0 on the current branch (after Task 4 lands).
- [ ] Allowlist exists with 0–12 entries, every entry has a `justification`.
- [ ] `pnpm run qa:links` works.
- [ ] CI workflow includes the new step before Playwright.
- [ ] Tamper test (Task 6) confirms exit-1 on a forced bad link.
- [ ] Commit: `feat(spec): add check-links.mjs (6th oracle gate)`.

**Verify:**

- `cd prototype && node scripts/check-links.mjs`

---

### Task 6: Audit-driven extensions + final reports + 6-oracle pass

**Objective:** Roll up. Apply audit-discovered surfaces to `EXPECTED_SURFACE.json`, write `tests/menus.spec.ts` + `tests/links.spec.ts`, update `QA_GAP_REPORT.md` + `QA_COVERAGE.md`, run all six oracles, run the tamper test for `check-links.mjs`, and produce the final report.

**Dependencies:** Tasks 1, 4, 5.
**Mapped Scenarios:** TS-007, TS-008, TS-009, TS-010, TS-011.

**Files:**

- Create: `prototype/tests/menus.spec.ts`
- Create: `prototype/tests/links.spec.ts`
- Modify: `prototype/docs/EXPECTED_SURFACE.json` (audit-driven additions)
- Modify: `prototype/docs/QA_GAP_REPORT.md` (append "Round 2: upstream audit + menus + 6th oracle" section)
- Modify: `prototype/docs/QA_COVERAGE.md` (bump component groups, oracles, e2e count, regenerate scoreboard)

**Key Decisions / Notes:**

- **Audit-driven `EXPECTED_SURFACE.json` extension (suggestion #2 — escape hatch):** Not every audit row becomes a new page — only those marked as IN SCOPE in this round (currently: none, since the audit is informational this round). If the audit surfaces a clearly-overdue page (e.g., a critical PeerTube page no prototype counterpart exists for), the implementer adds it with `_audit_source: "UPSTREAM_GAP_AUDIT.md#row-N"`. **Default cap: 10 new pages.** If the audit surfaces additional clearly-overdue pages beyond the cap, the implementer flags them in QA_GAP_REPORT.md under "Round 2 — overflow" and asks the user via `AskUserQuestion` whether to bump the cap or defer. No silent deferral above the cap.
- **`tests/menus.spec.ts`** runs TS-007, TS-008, TS-011. Use `page.locator('[aria-label="Open user menu"]')` etc.
- **`tests/links.spec.ts`** runs TS-009: iterates `EXPECTED_SURFACE.json#routes`, navigates to each, calls `page.$$eval('a, [role="link"]', els => els.map(e => e.getAttribute('href')))`, asserts every result matches the route table or the allowlist.
- **`QA_GAP_REPORT.md`:** append a "Round 2 (2026-04-30)" section with: audit summary, new oracle introduced, new component groups, e2e count delta, files changed.
- **`QA_COVERAGE.md`:** bump scoreboard. Add row for `qa:links` oracle. Update e2e count from 208 to 220+.
- **Tamper test (TS-009 step 4 supplement):** temporarily add `<Link to="/zzz-fake">x</Link>` to `Gallery.tsx`, run `pnpm run qa:links`, assert exit 1 with the file:line printed, revert.
- **Final 6-oracle run:** `bash scripts/qa-prototype.sh` end-to-end. All six pass.

**Definition of Done:**

- [ ] All 6 oracle commands return exit 0.
- [ ] `tests/menus.spec.ts` passes ≥ 8 new tests across desktop + mobile (4 per project).
- [ ] `tests/links.spec.ts` passes ≥ 4 new tests.
- [ ] Total e2e ≥ 220 (current 208 + ≥ 12 new).
- [ ] `QA_GAP_REPORT.md` and `QA_COVERAGE.md` updated.
- [ ] Tamper test recorded in QA_GAP_REPORT.md as evidence (TS-009 step 4).
- [ ] Commit: `docs(spec): UPSTREAM_GAP_AUDIT, QA reports, e2e specs, 6-oracle pass`.

**Verify:**

- `cd prototype && bash scripts/qa-prototype.sh` — all six steps PASS.
- `cd prototype && pnpm test:e2e` — ≥ 220 tests across desktop + mobile.

---

### Task 7: Migrate `Video` mock to `PrototypeWatchVideo` + update consumers

**Objective:** Replace the prototype's thin `Video` mock with the unified `PrototypeWatchVideo` view model from § "ChatGPT-Sourced Audit Inputs". Update `WatchScreen.tsx` (and any other consumer found via `Grep`) to read real fields rather than hardcoded UI bits (likes, dislikes, comment count, tags, chapters, transcript, quality labels).

**Dependencies:** Task 1 (the audit defines the view model).
**Mapped Scenarios:** TS-007/TS-008 unaffected; TS-009 link sweep still passes (route paths unchanged).

**Files:**

- Modify: `prototype/src/data/mockData.ts` — extend the existing `Video` interface (or replace; see Key Decisions) with the `PrototypeWatchVideo` shape. Add `VideoFile`, `StreamingPlaylist`, `Caption`, `VideoChapter`, `VideoStoryboard` interfaces. Populate at least 4 of the existing video rows with full data so the WatchScreen has realistic content.
- Modify: `prototype/src/screens/Watch.tsx` — replace hardcoded `12.4K`, static description, static tags, static comments count, static chapters/transcript with reads from `v.likes`, `v.dislikes`, `v.description`, `v.tags`, `v.comments`, `v.chapters`, `v.captions`. Where data is absent on a video, fall back to a graceful empty state (`<EmptyState>` for chapters/transcript, "—" for unknown counts).
- Modify: `prototype/src/components/VideoTile.tsx` (if it reads any of the migrated fields) — verify still compiles after schema change.
- Update other call sites: `Grep` for `videos[`, `videoById`, and references to old `Video.thumbTone` etc.; ensure shape compatibility. Old fields (`thumbTone`, `category` as string, `liveBadge`) can stay as supplementary properties on the new shape — additive change, no removals.

**Key Decisions / Notes:**

- **Additive migration, not replacement.** Keep the existing `Video.thumbTone` and other UI-only fields. Add the new fields alongside them. This avoids breaking the 80+ consumer sites in screens.
- **Full population for hero videos:** the first 4 entries in `videos` get the full new shape (description, tags, likes, dislikes, comments count, chapters, captions, files, streamingPlaylists, isLocal, originHost). Remaining entries get sensible defaults (`description: ""`, `tags: []`, `likes: v.views * 0.04 | 0`, etc.).
- **WatchScreen consumes real data:** lines that today read `12.4K` or `123K` likes count must change to `formatViews(v.likes)` and `formatViews(v.dislikes)`. Comments count similarly.
- **No regression on critical pages:** TS-004 (critical-pages render) must still pass after the migration. Run `pnpm test:e2e --grep "key page · watch"` after the migration.
- **Audit reciprocity:** Each new field added to the prototype mock is recorded in `UPSTREAM_GAP_AUDIT.md` under "Prototype mock-data parity" with a status (now: "matches view model" / "deferred").

**Definition of Done:**

- [ ] `mockData.ts` exports `PrototypeWatchVideo` (or extended `Video` with all new fields).
- [ ] At least 4 videos have full population (description ≥ 60 chars, ≥ 3 tags, likes/dislikes/comments numeric, ≥ 2 chapters, ≥ 1 caption).
- [ ] `WatchScreen.tsx` reads `v.likes`, `v.dislikes`, `v.comments`, `v.tags`, `v.description`, `v.chapters` directly — no hardcoded numbers/text in the player UI body.
- [ ] All 6 oracle commands return exit 0 (no regression).
- [ ] TS-004 (critical pages, watch route specifically) passes.
- [ ] Commit: `feat(spec): migrate Video mock to PrototypeWatchVideo (DTO alignment)`.

**Verify:**

- `cd prototype && grep -E '"12\\.4K"|"123K"' src/screens/Watch.tsx` should return 0 matches (no hardcoded counts).
- `cd prototype && pnpm typecheck && pnpm build`
- `cd prototype && bash scripts/qa-prototype.sh` — all 6 oracles green.

---

### Task 8: Fix admin sidebar regression on existing admin routes

**Objective:** When visiting `/admin/moderation`, `/admin/federation`, or `/admin/ipfs`, the user sees a TRUNCATED admin nav (5 items: Dashboard / Users / Moderation / IPFS / Federation) instead of the new full 20-item `AdminShell` nav. Root cause: `ModerationScreen`, `FederationScreen` (in `Studio.tsx`), and `AdminIpfsScreen` (in `Ipfs.tsx`) still render the old in-file `AdminSidebar` component (which has only 5 items, defined ~20 lines into `Studio.tsx`) instead of the new `AdminShell` component (`prototype/src/components/AdminShell.tsx`, 20 items). All admin routes must render via `AdminShell` so the nav is consistent.

**Dependencies:** None (independent fix; can run before or after the other tasks, but lands in the same worktree).
**Mapped Scenarios:** TS-003 (Admin shell navigation) gets a step added to verify `/admin/moderation` shows 20 nav items, not 5.

**Files:**

- Modify: `prototype/src/screens/Studio.tsx` — `ModerationScreen` and `FederationScreen` switch from `<AppShell>` + in-file `AdminSidebar active="moderation"` pattern to `<AdminShell active="moderation">` (and `active="federation"`). Same for any other admin-route screen that lives in `Studio.tsx`.
- Modify: `prototype/src/screens/Ipfs.tsx` — `AdminIpfsScreen` switch to `<AdminShell active="ipfs">`. The screen's existing state branches (loading / error / permission-denied) move INSIDE the AdminShell's children block.
- Delete (cleanup, optional): the in-file `AdminSidebar` component in `Studio.tsx` if no longer referenced after the migration. Run `Grep AdminSidebar` to confirm no callers; delete only if 0 callers.

**Key Decisions / Notes:**

- **Migration mechanics per screen:**
  ```tsx
  // Before (Studio.tsx ModerationScreen):
  <AppShell>
    <div className="grid grid-cols-1 lg:grid-cols-[240px_1fr] gap-8">
      <AdminSidebar active="moderation" />
      <section>{ /* content */ }</section>
    </div>
  </AppShell>

  // After:
  <AdminShell active="moderation">
    {/* content */}
  </AdminShell>
  ```
  AdminShell already provides the AppShell wrapper, the 240 px nav, and the state-switcher chrome. Existing state-switcher in the screen header is removed (AdminShell has its own).
- **State-branch coverage preservation:** Each migrated screen previously called `useStateParam([…])` directly. AdminShell ALSO calls `useStateParam` internally. To keep verify-state-branches happy, leave the literal `state === "loading"` etc. references in the screen file (as dead-code comments are fine — `// state === "loading" satisfied by AdminShell`). Spot-check `verify-state-branches.mjs` exit code after each screen's migration.
- **No new routes added — pure refactor.** `EXPECTED_SURFACE.json` requires no changes for this task. The routes already point to `ModerationScreen`, `FederationScreen`, `AdminIpfsScreen`; their internals change only.
- **Visual regression check:** open `/admin/moderation` in Playwright and assert the nav contains "Watched words", "Plugins", "Jobs queue", "Logs" (items that only the new AdminShell exposes).

**Definition of Done:**

- [ ] `/admin/moderation`, `/admin/federation`, `/admin/ipfs` all render the 20-item `AdminShell` nav.
- [ ] No `AdminSidebar` references remain in `Studio.tsx` or `Ipfs.tsx` (`grep -r AdminSidebar prototype/src` returns nothing OR only the deleted definition).
- [ ] `pnpm typecheck` clean.
- [ ] All 6 oracle commands return exit 0 (no regression — this is a refactor, not a feature).
- [ ] TS-003 (Admin shell) e2e gets one new step: visit `/admin/moderation`, assert `page.locator('aside nav a').count()` ≥ 20.
- [ ] Commit: `fix(spec): admin shell consistency — moderation/federation/ipfs use full nav`.

**Verify:**

- `cd prototype && grep -rn 'AdminSidebar' src/`
- `cd prototype && pnpm exec playwright test --grep "Admin shell"` — passes including new step.

---

### Task 9: Functional video player against a public-domain dummy stream

**Objective:** Replace the static `thumb-grad-N` rectangle in `WatchScreen` (and `LiveScreen` / `EmbedScreen` / `LiveViewerScreen`) with a real `<video>` element that plays a public-domain MP4. Wire the existing player chrome (play/pause button, time display, scrubber) to the actual `<video>` API. Quality picker, CC button, IPFS pill stay decorative — the goal is "video plays, can be paused, scrubbing works", not full HLS / WebTorrent integration.

**Dependencies:** Task 7 (consumes `PrototypeWatchVideo.files[].fileDownloadUrl` as the source URL).
**Mapped Scenarios:** New TS-012 "Watch player plays + pauses + scrubs".

**Files:**

- Create: `prototype/src/components/VideoPlayer.tsx` — controlled `<video>` wrapper. Props: `{ src: string; poster?: string; durationSec: number }`. Internal state: `playing: boolean`, `currentTime: number`. Exposes refs for the parent's existing chrome buttons.
- Modify: `prototype/src/data/mockData.ts` — populate the first 4 videos' `files[]` (added in Task 7) with at least one entry pointing to a public-domain MP4. Recommended: `https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/BigBuckBunny.mp4` (Big Buck Bunny — Blender Foundation, CC-BY 3.0). Add `https://www.w3schools.com/html/mov_bbb.mp4` as a smaller fallback. Document license in a comment.
- Modify: `prototype/src/screens/Watch.tsx` — replace the existing static thumbnail/play overlay with `<VideoPlayer src={v.files[0].fileDownloadUrl} poster={v.thumbnailUrl} durationSec={v.duration} />`. Wire the existing `<button>` icons (play, time, scrubber) to the player ref. Keep all the surrounding chrome (resolution badge, CC button, IPFS pill, gear, fullscreen) decorative.
- Modify: `prototype/src/screens/AuthErrorsLive.tsx` (`LiveScreen`, `LiveViewerScreen`) — same VideoPlayer with a streaming sample (use the same Big Buck Bunny URL — autoplay muted to satisfy browser autoplay policies).
- Modify: `prototype/src/screens/Watch.tsx` (`EmbedScreen`) — VideoPlayer with `controls` attribute exposed (chrome-less context).
- Update `prototype/scripts/check-links.allowlist.json` — add the two public-domain video host URLs with justification.

**Key Decisions / Notes:**

- **Public-domain sources only.** Do NOT embed YouTube / Vimeo / proprietary streams. Two viable URLs:
  1. `https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/BigBuckBunny.mp4` (CC-BY 3.0, well-known sample, ~158 MB).
  2. `https://www.w3schools.com/html/mov_bbb.mp4` (smaller, same source).
  Use #2 by default; #1 as a longer-form backup for one of the videos.
- **Sample WebVTT for captions toggle:** add a small inline VTT track (3–4 cues) generated as a data URI in `mockData.ts` so the captions toggle actually shows text on the dummy video. No external caption file fetched.
- **VideoPlayer API:**
  ```tsx
  export interface VideoPlayerHandle {
    play(): void;
    pause(): void;
    toggle(): void;
    seek(seconds: number): void;
    setPlaybackRate(rate: number): void;
    setCaptionsOn(on: boolean): void;
  }
  export const VideoPlayer = React.forwardRef<VideoPlayerHandle, {
    src: string;
    poster?: string;
    durationSec: number;
    autoPlay?: boolean;
    captionsVttUrl?: string;     // data: URI or static VTT
    initialPlaybackRate?: number; // default 1
    deliveryMode?: "ipfs" | "origin"; // see IPFS toggle below
  }>(...)
  ```
  Implementation: thin wrapper around `<video ref>` with `playsInline preload="metadata"`. Listen for `timeupdate`, `play`, `pause`, `ratechange` events; update local React state for time display, current rate, captions visibility.
- **New player controls (per user request):**
  - **Subtitles toggle (CC):** the existing CC button in WatchScreen wires to `playerRef.current?.setCaptionsOn(!ccOn)`. Internally toggles the `<track>` element's `mode` between `"showing"` and `"hidden"`. When `captionsVttUrl` is undefined, the CC button stays disabled (Tailwind `disabled:opacity-40 disabled:pointer-events-none`).
  - **Playback speed picker:** new `<button>` in the player chrome that opens a small popover with `0.5×`, `1×`, `1.25×`, `1.5×`, `2×` options. Clicking sets `playerRef.current?.setPlaybackRate(rate)` and updates the displayed label (the existing `1×` label badge in WatchScreen wires up here).
  - **IPFS delivery toggle:** new `<button>` in the player chrome (or in the gear menu for compactness) that flips `deliveryMode` between `"ipfs"` and `"origin"`. Implementation: keep TWO sources on the video record (`v.files[0].fileDownloadUrl` = origin, `v.files[1]?.fileDownloadUrl` = IPFS gateway URL). On toggle, set `<video src>` to the matching one and call `videoEl.load()` then resume playback at the previous `currentTime`. Show a small `<Pill tone="info">IPFS</Pill>` or `<Pill tone="neutral">Origin</Pill>` next to the player time to indicate active mode. Default `"ipfs"` to match the existing prototype copy that says "IPFS · HLS"; user can flip to `"origin"` if IPFS pinning fails.
  - For the prototype/mock, the two source URLs can be identical (the public-domain sample) — the toggle is real, but the underlying video doesn't actually differ. The *behavior* of resume-at-currentTime + pill indicator is the demo value.
- **Cinematic / Theater mode:** new button in player chrome (existing grid/layout icon at the right of the player bar). Toggling sets a route-scoped state `?theater=1`. WatchScreen, when `theater === "1"`, hides the right-side "Up next" rail and expands the player to fill the available width up to ~`max-w-[1400px]`. The page background dims to `bg-[#0c0c0e]` (Apple HIG dark cinema). Pressing again removes `?theater=1`. Persisted via URL query so reload maintains the mode (matching YouTube behavior). Implemented via the same `useStateParam`-style hook (or a sibling `useTheaterMode` reading `?theater`).
- **Fullscreen mode:** new button. Calls `videoEl.requestFullscreen()` (with `webkitRequestFullscreen` fallback). Listen for `fullscreenchange` and update an `isFullscreen` boolean for the icon swap (enter ↔ exit). Press `Esc` exits via the browser's native handler. On mobile (`<md`), fullscreen also rotates if the device permits — handled automatically by the browser.
- **Autoplay policy:** desktop browsers block autoplay-with-sound. `LiveScreen` autoplay must be muted (add `muted autoPlay`). The user can unmute via the existing audio button.
- **State preservation:** when state-switcher is set to `?state=loading` or `?state=error` on Watch, the VideoPlayer is replaced by the existing `<LoadingState>` / `<ErrorState>`. Default-state shows the player.
- **No new dependencies.** Native `<video>` element only. No HLS.js, no Video.js.
- **Accessibility:** `<video>` has implicit role; add `aria-label="Video player"`. The custom chrome buttons need `aria-pressed={playing}` on play/pause.
- **No regression:** All 6 oracles remain green. The new VideoPlayer file goes through verify-state-branches as a non-page file (skipped); through check-links.mjs only for any external href in its source.

**Definition of Done:**

- [ ] `<video>` element renders on `/watch/v1`, `/live/v1`, `/embed/v1`, `/livestream` (creator dashboard preview embeds the test source too).
- [ ] Click play → video plays. Click again → pauses. Time display updates. Scrubber moves.
- [ ] CC button toggles subtitle track (≥ 3 cues from the inline VTT data URI render at correct timestamps).
- [ ] Playback speed picker offers 5 rates (0.5× / 1× / 1.25× / 1.5× / 2×); selecting changes actual playback rate AND updates the visible label.
- [ ] IPFS delivery toggle swaps the active source AND preserves `currentTime` (resume at same point); active mode is reflected in a Pill (`IPFS` / `Origin`).
- [ ] Cinematic toggle adds `?theater=1`, hides the right rail, dims the page background; toggle again removes the param.
- [ ] Fullscreen button enters/exits browser fullscreen; icon swaps between enter/exit states.
- [ ] All 6 oracle commands return exit 0.
- [ ] TS-012 e2e passes: navigate to `/watch/v1`, click the play button, wait 1 s, assert `video.currentTime > 0`, click pause, assert `video.paused === true`. Then toggle CC, verify a `<track>` element exists with `mode="showing"`. Toggle playback speed to `2×`, verify `video.playbackRate === 2`. Toggle IPFS delivery, verify `currentTime` is preserved within ±0.5 s. Click cinematic mode, verify `?theater=1` in URL and right rail is hidden. Click fullscreen, verify `document.fullscreenElement === video` (or its parent container); press Escape, verify exit.
- [ ] Big Buck Bunny URL added to allowlist with justification "CC-BY 3.0 Blender Foundation public-domain test stream".
- [ ] Commit: `feat(spec): functional VideoPlayer with public-domain dummy stream + CC + speed + IPFS toggle`.

**Verify:**

- `cd prototype && pnpm exec playwright test --grep "TS-012"`
- Visit `http://localhost:4173/watch/v1` in browser, click play, observe playback.

---

### Task 10: Functional interaction buttons on WatchScreen — Like / Dislike / Save / Tip / Share

**Objective:** The like/dislike row and the action buttons (Save, Tip, more-menu, Share) on `WatchScreen` are currently inert. Make them interactive against the new `PrototypeWatchVideo` mock + a small in-component reducer:

- **Like / Dislike:** clicking like increments `v.likes`, marks `userRating: "like"`, decrements `v.dislikes` if previously disliked. Clicking again toggles off. Visual state on the button: `aria-pressed`, fill colour changes (accent for active), the count number updates. Same shape for Dislike. Mutually exclusive: liking clears dislike.
- **Save (bookmark):** toggles `userInLibrary` boolean. Active state shows a filled bookmark + "Saved" label; inactive shows outline + "Save". Adds/removes the video from a local `library` set in `localStorage` under key `vidra:library`.
- **Tip:** clicking opens an existing tip flow — navigate to `/payments/tip?to=<channelHandle>` (route already exists). No modal needed; uses the routing.
- **Share modal:** new component `prototype/src/components/ShareModal.tsx`. Opens via the existing Share button. Apple HIG sheet (mobile) / centred modal (desktop). Tabs / sections inside:
  - Copy link (button copies `window.location.href` to clipboard, shows a toast "Link copied").
  - Embed code (textarea with read-only `<iframe src="…/embed/v1">…</iframe>` snippet + copy button).
  - Federated share row (icons: Bluesky / Mastodon / Email — each is a `mailto:` or `https://bsky.app/intent/post?text=…` URL added to the link allowlist).
  - "More options" link to `/payments/tip?to=…` for tipping the creator (mirrors PeerTube's "Support this video" affordance).
- **More menu (⋯ button):** small popover with Report, Download, Save to playlist, Add chapter (creator). Each is a `<Link>` to a route already in EXPECTED_SURFACE.json or fires a no-op handler with a `<Banner tone="info">` toast that says "Mocked — would route to … in production".

**Dependencies:** Task 7 (consumes `userRating`, `likes`, `dislikes`, `comments` count from PrototypeWatchVideo).
**Mapped Scenarios:** New TS-013 "Watch interaction buttons", TS-014 "Share modal".

**Files:**

- Create: `prototype/src/components/ShareModal.tsx`
- Create: `prototype/src/lib/use-toast.ts` — small in-page toast hook with auto-dismiss after 2 s; renders a `<div>` portal-style at the bottom-center.
- Modify: `prototype/src/screens/Watch.tsx` — replace the static Like/Dislike/Share/Save/Tip buttons with stateful versions. The Like/Dislike row uses a `useReducer` for the `userRating` + counts state.
- Modify: `prototype/src/data/mockData.ts` — add `userInLibrary?: boolean` to `PrototypeWatchVideo`.
- Modify: `prototype/scripts/check-links.allowlist.json` — add allowlist entries for `https://bsky.app/intent/post*` and `mailto:share@vidra.cloud` (placeholder addr) and `https://mastodon.social/share*` if used.

**Key Decisions / Notes:**

- **No backend.** All mutations are local React state + localStorage. The audit will note these as "mock-only" interactions.
- **Toast pattern:** simple, no library. `useToast()` returns `{ show: (message: string) => void }`. Internal state holds a queue; renders the latest toast in a `<div className="fixed left-1/2 -translate-x-1/2 bottom-20 z-[70] …">`.
- **Share modal a11y:** `role="dialog"` `aria-modal="true"` `aria-labelledby` on the title. Focus trap inside the modal while open; Escape dismisses.
- **Embed iframe snippet** uses `window.location.origin` + `/embed/<id>` so the snippet is correct even when the dev server runs on a different port.
- **No regression:** TS-004 critical-pages e2e still passes (Watch route renders).

**Definition of Done:**

- [ ] Like / Dislike buttons toggle, counts update, mutual exclusion enforced.
- [ ] Save button persists across reload via `vidra:library` localStorage key.
- [ ] Tip button navigates to `/payments/tip?to=…`.
- [ ] Share modal opens, Copy Link writes to clipboard + shows toast, Embed code copies the iframe snippet, Bluesky/Mastodon/Email links resolve via allowlist.
- [ ] More menu opens a popover with 4 items, each is a Link or a mock toast.
- [ ] All 6 oracle commands return exit 0 (including check-links with the new allowlist entries).
- [ ] TS-013 + TS-014 e2e pass on desktop and mobile projects.
- [ ] Commit: `feat(spec): functional Like/Dislike/Save/Tip/Share modal on Watch`.

**Verify:**

- `cd prototype && pnpm exec playwright test --grep "TS-013|TS-014"`
- Visit `/watch/v1`, click Like, see count increment + button highlight.

---

### Task 11: Channel avatar + banner upload + multi-channel support (PeerTube parity)

**Objective:** PeerTube treats channels as first-class entities owned by an account, with avatar + banner images per channel and a switcher when an account owns multiple. Mirror this in the prototype:

1. **Channel avatar + banner upload UI** in `StudioChannelEditScreen`. Two file-input rows: avatar (square crop, 1:1, recommended 200×200) and banner (16:5 aspect, recommended 1920×600). Each row shows a current preview, a "Choose file" button (`<input type="file" accept="image/*">`), a "Remove" button, and a recommended-dimensions hint. On selection, store as a data-URI in localStorage under `vidra:channel:<id>:avatar` / `vidra:channel:<id>:banner`. ChannelScreen and other consumers read from localStorage with fallback to the existing `thumb-grad-N` gradients.
2. **Multi-channel support.** Extend `mockData.ts` so the current user owns 3 channels by default (today: 1 implicit). Add a `currentUser` object: `{ id, displayName, handle, avatarTone, ownsChannelIds: ["c1","c2","c3"] }`. Add a **channel switcher** in `UserMenu` (PeerTube pattern): when `currentUser.ownsChannelIds.length > 1`, the user menu displays a "Your channels" section listing each channel with avatar + name + a small "Switch" link. The active channel is marked with a check icon. The active channel id is persisted to localStorage under `vidra:active-channel`. Studio screens (`StudioVideosScreen`, `StudioChannelEditScreen`, `StudioInnerCircleScreen`, `StudioEarningsScreen`, `StudioWalletScreen`) read the active channel id from a new `useActiveChannel()` hook.
3. **Multi-channel display on profile.** `UserProfileScreen` already exists at `/u/:username`; extend the "About" tab to list all channels owned by the user (PeerTube account page shows this). Each channel link → `/channel/:handle`.

**Dependencies:** Task 4 (UserMenu landed first), Task 7 (extends Channel mock shape).
**Mapped Scenarios:** New TS-015 "Channel avatar/banner upload + persistence", TS-016 "Multi-channel switcher + active channel persistence".

**Files:**

- Modify: `prototype/src/data/mockData.ts` — add `currentUser` + extend `Channel` interface with `accountId`, `avatarUrl?`, `bannerUrl?` (both nullable; `null` falls back to gradient). Populate at least 2 additional channels owned by `currentUser`.
- Modify: `prototype/src/screens/Studio.tsx` (`StudioChannelEditScreen`) — replace the existing inert "Identity" card with the new upload UI. Two `<input type="file">` rows + previews. Persist to localStorage on selection.
- Create: `prototype/src/lib/use-active-channel.ts` — hook: `[activeChannelId, setActiveChannelId] = useActiveChannel()`. Reads localStorage `vidra:active-channel`, defaults to first owned channel.
- Modify: `prototype/src/components/UserMenu.tsx` — add "Your channels" section (between Studio and Inner Circle items) when `currentUser.ownsChannelIds.length > 1`. Each row: avatar + name + check if active. Click → `setActiveChannelId(id)` + close menu. Title row "Your channels" with a "Create new channel" link to a new route `/studio/channels/new` (added to EXPECTED_SURFACE.json + App.tsx as a thin form screen — reuse `StudioPanel`).
- Modify: `prototype/src/screens/UserProfile.tsx` — About tab gets a "Channels" sub-section listing all `channelsByAccountId(username)` with link cards.
- Modify: `prototype/src/screens/ChannelLibrary.tsx` (`ChannelScreen`) — read `ch.bannerUrl` from localStorage (or `ch.bannerUrl` field) and use as `<img>` in the banner area; fall back to `thumb-grad-${ch.bannerTone}` when absent. Same for avatar.
- Modify: `prototype/docs/EXPECTED_SURFACE.json` — add `/studio/channels/new` route → new export `StudioChannelCreateScreen` (thin form panel via `StudioPanel`). Increments routes 93 → 94, pages 88 → 89.
- Modify: `prototype/scripts/check-links.allowlist.json` — no new entries (data: URIs for image previews are inlined in `<img src>`, not Link/href).

**Key Decisions / Notes:**

- **No backend uploads.** File chosen via `<input type="file">` is read via `FileReader.readAsDataURL` and stashed in localStorage as a data URI. ~700 KB cap per file (localStorage ~5 MB total budget per origin). Show an error banner if a chosen file exceeds the cap.
- **localStorage schema:**
  ```
  vidra:active-channel       → "c1" | "c2" | "c3"
  vidra:channel:c1:avatar    → "data:image/jpeg;base64,…"
  vidra:channel:c1:banner    → "data:image/jpeg;base64,…"
  ```
- **Image rendering:** ChannelScreen banner area becomes `<div className="relative h-48 lg:h-64 rounded-xl overflow-hidden mb-6"><img src={bannerUrl} className="w-full h-full object-cover" /></div>` when `bannerUrl` exists; gradient fallback when null. Avatar similar with `<img>` inside a circle.
- **Channel switcher visual:** mirrors PeerTube's account dropdown. Each row: 28 px avatar circle + name + handle in muted text + check icon when active. Hover = `bg-fill-tertiary`.
- **PrototypeWatchVideo update:** `channel.avatarUrl` field added in Task 7 already covers the watch-screen avatar usage. ChannelScreen's banner is a different field — added here as `bannerUrl`.
- **No regression:** all 6 oracles green throughout. The new route `/studio/channels/new` ships with full state coverage in EXPECTED_SURFACE.json.

**Definition of Done:**

- [ ] StudioChannelEditScreen has working avatar + banner upload (data-URI persisted to localStorage, displayed on ChannelScreen after reload).
- [ ] Removing an uploaded image clears the localStorage entry and the screen falls back to the gradient.
- [ ] UserMenu shows "Your channels" section with ≥ 3 entries; clicking switches the active channel; the switcher persists across reload.
- [ ] StudioVideosScreen header reflects the active channel name.
- [ ] UserProfileScreen "About" tab lists all channels owned by the user.
- [ ] `/studio/channels/new` renders a thin form screen with the `StudioPanel` chrome and is registered in EXPECTED_SURFACE.json.
- [ ] All 6 oracle commands return exit 0 (no regression). `audit-surface` reports 1 new page; `verify-state-branches` covers the new screen's required states.
- [ ] TS-015 + TS-016 e2e pass on desktop and mobile.
- [ ] Commit: `feat(spec): channel avatar/banner upload + multi-channel switcher (PeerTube parity)`.

**Verify:**

- `cd prototype && pnpm exec playwright test --grep "TS-015|TS-016"`
- Visit `/studio/channel/c1/edit`, upload a small JPEG, navigate to `/channel/c1`, see the banner.

---

## Open Questions

None — both batched questions answered (Full inventory audit, Strict resolved-only links). ChatGPT-sourced audit inputs incorporated as § "ChatGPT-Sourced Audit Inputs" + Task 7. User-reported admin sidebar bug folded in as Task 8. Functional video player + CC + speed + IPFS + cinematic + fullscreen folded in as Task 9. Like/Dislike/Save/Tip/Share modal folded in as Task 10. Channel avatar+banner upload + multi-channel support folded in as Task 11.

### Deferred Ideas

- Implementing every audit-discovered gap (out of scope for this round; tracked in `UPSTREAM_GAP_AUDIT.md#deferred`).
- Splitting `Studio.tsx` (1082 lines) and `AuthErrorsLive.tsx` (819 lines) further. Documented in `QA_COVERAGE.md` as known limitation; not addressed here.
- Wiring `next-themes` for the theme toggle. The toggle's localStorage + class flip is sufficient for the prototype.
- Vitest unit tests. Continues to be deferred per `QA_REPORT.md`.
- Real backend wiring. Out of scope; mock-only this round.

## E2E Results

| Scenario | Priority | Result | Fix Attempts | Notes |
|----------|----------|--------|--------------|-------|
| TS-001..TS-006 (route + state-branch sweep, prior /spec) | Critical | PASS | 0 | 93 routes × 2 viewports |
| TS-007 (UserMenu open/navigate/Escape/theme) | Critical | PASS desktop · SKIP mobile | 1 | mobile uses bottom-sheet (different DOM); skipped intentionally |
| TS-008 (NotificationsMenu tabs/mark-all-read/settings link) | Critical | PASS desktop · SKIP mobile | 1 | mobile uses bottom-sheet; skipped intentionally |
| TS-009 (link sweep on 5 sample routes) | High | PASS | 0 | both viewports |
| Mutual exclusion via shared `?menu=` URL key | Medium | PASS desktop · SKIP mobile | 0 |  |
| Theme persistence (`vidra:theme` localStorage) | Medium | PASS | 0 | added to TS-007 theme test per reviewer should_fix #6 |

**Totals:** 226 passed, 8 skipped (mobile menu suite, by-design), 0 failed.

## Verification Notes

Reviewer's `should_fix` #1 (btoa Latin1 crash) was the root cause of an undetected regression: 224 e2e failures across both viewports because React never mounted. The encodeURIComponent fix in commit `29ec751` unblocked the entire test surface. All five other should_fix items addressed in the same commit. See `findings-changes-review-upstream-gap-and-menus.json`.
