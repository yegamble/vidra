# Phase 13 — Captions, Studio Finish, and Analytics Wiring Implementation Plan

Created: 2026-04-28
Author: yegamble@gmail.com
Status: VERIFIED
Approved: Yes
Iterations: 1
Worktree: No
Type: Feature

## Summary

**Goal:** Close C16–C19 from `docs/plans/2026-04-22-feature-parity-audit.md` by finishing the Studio editor (cut/intro/watermark) with a video picker for intro/outro, loading existing caption content into the in-browser VTT/SRT editor, switching the auto-caption Whisper trigger to studio-job polling, and upgrading the analytics dashboard with a channel selector, date-range presets, compare-period deltas, and live retention-curve verification — all browser-verified end-to-end with full 13-locale i18n parity.

**Architecture:** Pure frontend phase. All vidra-core endpoints already exist (`/api/v1/videos/{id}/studio/cut|intro|watermark|jobs`, `/api/v1/videos/{id}/captions{/generate,/{id},/{id}/content}`, `/api/v1/channels/{id}/analytics`, `/api/v1/videos/{id}/analytics`, `/api/v1/videos/{id}/stats/retention`). Existing service layer (`studioService`, `captionService`, `analyticsService`) already maps to those endpoints; gaps are in component logic, UX polish, i18n coverage, and verification — not API plumbing. New surface: in-house `parseVtt()`/`parseSrt()` utilities, a `<VideoPickerDialog/>` reusing `videoService.getMyVideos`, a `<DateRangePresets/>` chip group beside `AnalyticsDatePicker`, and a `<ComparePeriodCard/>` wrapper computing delta from two parallel `getChannelAnalytics` / `getVideoAnalytics` calls.

**Tech Stack:** Next.js 15 App Router + React 19 client components, `useApi` hook, Radix UI Dialog (for the video picker modal), `next-intl` for i18n, `sonner` for toasts, Tailwind v4 + cyan-500 accent per Apple HIG. Vitest for unit, Playwright for E2E. No new runtime dependencies.

---

## Scope

### In Scope

**C16 — Video Studio finish**
- Replace the two free-form "Video ID" `<input/>`s in `src/components/studio-editor.tsx` (intro + outro) with a `<VideoPickerDialog/>` that lists `videoService.getMyVideos({ start, count: 20 })` paginated, supports title filter, returns the selected video's id + title.
- New component `src/components/video-picker-dialog.tsx` (Radix `Dialog`). Selected video displayed as a chip with title + thumbnail above the "Add intro" / "Add outro" buttons.
- Studio active-job polling already correct (5s interval against `studioService.getJob`). No change there beyond extracting the polling hook into `src/lib/hooks/use-studio-job.ts` for reuse by `AutoCaptionButton`.
- Unify watermark URL validation: keep current HTTPS check, add early-return when `image_url` is empty after trim, surface validation errors via the existing `<ErrorState/>` toast pattern (currently uses `toast.error`).
- Studio editor `<input type="range"/>` cut/trim controls keep behavior, gain `aria-valuetext` for screen readers (currently only `aria-valuenow`).

**C17 — Auto-caption polling switch**
- `AutoCaptionButton` already calls `captionService.generate()` which returns a `StudioJob`. Currently it ignores the returned job and polls `captionService.getForVideo()` every 5 s up to 5 min looking for `is_auto_generated`. Switch to polling `studioService.getJob(videoId, job.id)` via the shared `useStudioJob` hook from C16.
- On job `completed`: refetch caption list, surface success toast (existing copy keeps), close dropdown.
- On job `failed`: show error toast with `job.error` (currently silent).
- The progress bar element already exists at `auto-caption-button.tsx:106-110`, but it's driven by an `activeJob` set once at line 39 from the initial `generate()` response and never updated. The fix is to swap that source to the polling job from `useStudioJob` so the existing bar starts updating every 5 s.

**C18 — Caption editor content loading**
- Add `parseVtt(text: string): CaptionCue[]` and `parseSrt(text: string): CaptionCue[]` exports to `src/components/caption-editor.tsx`, sibling to existing `cuesToVtt` / `cuesToSrt`. Handlers: `WEBVTT` header skip, blank-line cue separator, optional cue-id line (numeric for SRT, free-form for VTT), `HH:MM:SS.mmm --> HH:MM:SS.mmm` (VTT) / `HH:MM:SS,mmm --> HH:MM:SS,mmm` (SRT) timestamp line, multi-line text body. Round-trip property: `parseVtt(cuesToVtt(cues)) === cues` for cues with valid time spans.
- Update `CaptionLanguageList.handleEdit` (`src/components/caption-language-list.tsx:40-45`): fetch `captionService.getContentUrl(videoId, caption.id)` via `fetch()` (no auth header — captions are public for public videos, follow `publicApi` precedent), parse by `caption.file_format`, populate `editingCues` before rendering `<CaptionEditor/>`. Show `<CaptionEditorSkeleton/>` while loading. Handle 404 (caption track exists but no content yet — start with empty cues), 5xx (toast + bail).
- Implementer note: the existing `caption.is_auto_generated` flag survives auto-caption + manual edit (kept for filter UI); editing an auto-caption persists with that flag still set unless backend strips it.

**C19 — Analytics dashboard upgrades**
- **Channel selector:** Replace "use first channel" line in `src/components/pages/analytics-page.tsx:21` (`primaryChannelId = myChannels?.data?.[0]?.id`) with a `<ChannelSelect/>` dropdown sourced from the existing `channelService.getMyChannels()` call. Persist selection in `localStorage` key `vidra.analytics.channelId`. Default to first channel on first visit. Single-channel users still see the same view (selector renders disabled when `channels.length === 1`).
- **Date-range presets:** New `src/components/analytics-date-presets.tsx`. Five chips: `7d / 30d / 90d / 1y / All time`. Renders above `<AnalyticsDatePicker/>`. Selecting a chip computes `start_date` / `end_date` and calls existing `onChange` prop. "All time" sends an empty range (existing path). The custom date picker remains for ad-hoc ranges.
- **Compare-period delta:** Stat cards gain a small "↑/↓ N%" badge under the value when both current and prior values are non-zero. Coverage is constrained by the current backend response shape:
  - **Channel page** — `analyticsService.getChannelAnalytics` adapter at `analytics.ts:42-49` hard-codes `total_watch_time`, `subscriber_count`, `video_count` to 0 because the backend's `ChannelAnalyticsBackendResponse` only returns `{total_views, daily}` (per audit Still-Broken #5). Compare-period therefore only renders on the **Total Views** card. The other three cards render no badge until vidra-core enriches the response — out of scope for this phase, tracked in audit #5.
  - **Video page** — `getVideoAnalytics` returns the full `{views, watch_time, avg_watch_duration, likes, dislikes, comments}` set, so all six video stat cards get a badge.
- Compute by issuing a parallel `analyticsService.getChannelAnalytics(channelId, prevRange)` (or `getVideoAnalytics`) where `prevRange` is the immediately-prior equal-length window. Hide the delta when prev-period total is 0 (avoids `Infinity%`), when current is 0 (no real data), and when no date range is selected (defaults to all-time). New helper `src/lib/analytics/compare-period.ts` exporting `computePrevRange(range)` and `computeDelta(curr, prev)`.
- **Retention curve verification:** existing `<LineChart/>` rendering `retention` from `getRetention()` is the surface; this phase adds a Playwright E2E (TS-005) that uploads a video, watches partway, reloads the analytics page, and asserts the curve is non-flat (≥ 1 point with `audience_percent > 0`). Backend `GET /api/v1/videos/{id}/stats/retention` is already wired; verification proves it works in production conditions.

**i18n parity (all 13 locales)**
- Extract every hardcoded user-facing string in: `studio-editor.tsx` (~28 strings), `caption-editor.tsx` (~12), `caption-language-list.tsx` (~14), `auto-caption-button.tsx` (~10 incl. language labels), `analytics-page.tsx` (~14), `video-analytics-page.tsx` (~16), new `video-picker-dialog.tsx` (~6), `analytics-date-presets.tsx` (~6). Total ≈ 106 keys.
- Namespace the keys under `Studio.*`, `Captions.*`, `AnalyticsPage.*`, `VideoAnalyticsPage.*`, `VideoPicker.*`, `AnalyticsPresets.*`. Existing related keys to **reuse rather than duplicate**: `VideoEdit.studio` (`messages/en.json:795`) and `VideoEdit.captions` (`messages/en.json:796`) — these are the existing video-edit tab labels; reuse via `t("VideoEdit.studio")`/`t("VideoEdit.captions")` rather than re-translating "Studio"/"Captions" across 13 locales. The sidebar `Analytics` label at `messages/en.json:715` is also already translated and unaffected.
- Translate all keys across `ar, de, es, fr, it, ja, ko, nl, pl, pt, ru, zh`. Run `pnpm i18n:check` — must pass.

**Tests**
- Vitest unit tests: `parseVtt` / `parseSrt` round-trip (≥ 4 cases each, incl. multi-line cue, empty text, hours field, optional cue id), `<VideoPickerDialog/>` (open/select/cancel/empty state), `<AnalyticsDatePresets/>` (each chip computes the correct range), `compute-period.ts` (delta math incl. zero-division and negative-delta), updated `<CaptionLanguageList/>` (fetch + parse path), updated `<AutoCaptionButton/>` (job-poll path), updated `<AnalyticsPage/>` (channel-select + compare-period + presets), updated `<VideoAnalyticsPage/>` (compare-period).
- Playwright E2E: TS-001 through TS-006 below.
- Existing tests stay green: `pnpm test:run` 0 failures.

### Out of Scope

- A new `/studio` top-level dashboard route — chosen Approach is "wire missing flows + browser-verify" (no new top-level pages). Captured as Deferred Idea.
- Multi-track timeline cue editor (waveform scrubbing, drag-resize cues over the player). Deferred Idea.
- Demographics + view-heatmap widgets — vidra-core handlers do not exist (per `analytics.ts:21-22` comment and the audit's resolved tech-debt item #4). Out of Scope, no task. Will become its own spec when backend ships.
- Backend changes — no vidra-core PR. All endpoints are already implemented and verified against migrations 90e634e, 7596116.
- A `/captions/{id}/cues` JSON endpoint on vidra-core (rejected during design) — caption content stays as VTT/SRT text over the existing `/content` route, frontend parses.
- Outro support in vidra-core — `studioService.addIntro` is reused with `position: "after"` (already does this), no new route needed.
- Multi-channel comparison view (channel A vs channel B side-by-side) — single-channel-at-a-time per the chosen channel selector UX.
- Plugin-driven custom analytics widgets — depends on plugin system (separate phase).
- **Caption file upload** (drag-drop or `<input type="file"/>` for `.vtt`/`.srt`) — audit user-story C-7 covers upload + auto-generate + edit; this phase ships auto-generate (C17) and edit (C18) only. `captionService.create` already accepts inline `content`, but no file picker UI is added. Tracked as Deferred Idea — users compose new captions cue-by-cue in the editor today or use auto-generate.
- **Channel-page Watch Time / Subscribers / Videos compare-period delta** — depends on vidra-core enriching `ChannelAnalyticsBackendResponse` with those fields (audit Still-Broken #5). When backend ships, compare-period extends automatically because the `getChannelAnalytics` adapter will return real numbers and the existing badge logic re-engages.

## Approach

**Chosen:** Wire missing flows + browser-verify (Option 1 from Batch 1).
**Why:** Services, components, and routes already exist — the audit's "UI ONLY" claim is a verification gap, not an implementation gap. Adding a top-level `/studio` dashboard or a timeline editor would multiply scope without closing the actual gaps (empty caption editor, raw video-ID inputs, missing analytics polish, no browser evidence). Cost: this phase does not introduce a creator-wide studio overview — power users still need to navigate to a specific video to use the editor. Captured as Deferred Idea.

**Alternatives considered:**
- **`/studio` dashboard route + multi-track timeline** — rejected: adds a top-level page and a complex player overlay for a phase whose goal is closing parity gaps, not introducing new surfaces.
- **Three split PRs (per C16, C17+C18, C19)** — rejected for shared i18n + e2e infra; the bundled PR matches Phase 12 cadence and avoids three verification passes.

## Context for Implementer

> Write for an implementer who has never seen the codebase.

- **Patterns to follow:**
  - Service shape: `src/lib/api/services/studio.ts:10-30` and `captions.ts:6-43` — every method calls `api.post|get|put|delete` and returns the typed response. Add no auth headers manually; `api` injects them.
  - Page composition: `src/components/pages/analytics-page.tsx:1-137` — page-level component wraps `useApi`, renders skeleton/error/data states, exports a single named function.
  - Polling hook precedent: `src/components/studio-editor.tsx:48-68` — 5 s interval, clear interval on `completed | failed`, depend on the active job. Extract to `src/lib/hooks/use-studio-job.ts` as `useStudioJob(videoId, jobId)` returning `{ job, status, progress, error }`. Existing `StudioEditor` then `const { job } = useStudioJob(videoId, activeJob?.id)`.
  - i18n: `src/components/pages/admin-runners-page.tsx` (Phase 12) — `const t = useTranslations("AdminRunners")`. Keys grouped under one namespace per page/component. `pnpm i18n:check` runs in CI and blocks merges with missing keys.
  - Modal/Dialog: Radix `<Dialog/>` already used elsewhere — find the Phase 9 Inner Circle tier dialog at `src/components/pages/studio-inner-circle-page.tsx` for styling parity.
- **Conventions:**
  - File naming: kebab-case (`video-picker-dialog.tsx`).
  - Component naming: PascalCase nouns; default named export.
  - State: local `useState`; lift only when shared. No new context.
  - Errors: log via `logger.error` from `@/lib/telemetry/logger` for API failures, then `toast.error` user-facing — see `src/components/pages/library-page.tsx` (Phase 6 remediation) for the pattern.
  - File size: keep production files under 800 lines (HIG project rule). `analytics-page.tsx` and `video-analytics-page.tsx` stay tiny — no risk. `studio-editor.tsx` will grow ~50 LOC adding picker integration; still under cap.
- **Key files:**
  - `src/components/studio-editor.tsx` — the C16 surface. 356 lines. Replace lines 28-29 (intro/outro state), 86-112 (handlers), 244-282 (UI) with picker-driven equivalents.
  - `src/components/caption-editor.tsx` — sibling for parsers. Add `parseVtt`/`parseSrt` next to `cuesToVtt`/`cuesToSrt` exports.
  - `src/components/caption-language-list.tsx:40-45` — the `handleEdit` TODO. Replace with fetch + parse.
  - `src/components/auto-caption-button.tsx:46-72` — the polling block. Swap for `useStudioJob`.
  - `src/components/pages/analytics-page.tsx` — channel selector + presets + compare insertion points.
  - `src/components/pages/video-analytics-page.tsx` — compare-period for video-level cards.
  - `src/lib/api/services/videos.ts:334` — `getMyVideos` for picker.
  - `messages/en.json` and 12 sibling locale files.
  - `e2e/` — new specs land beside `video-edit-roles.spec.ts`.
- **Gotchas:**
  - **Caption content URL is unauthenticated** for public videos but private videos need a Bearer token. The existing `captionService.getContentUrl` returns a bare URL string (no auth). For private videos the editor will 401 — implementer must use `fetch` with `Authorization` header derived from `getAccessToken()` (see `analyticsService.exportCsv` at `analytics.ts:75-77` for the pattern). Do NOT extend the public URL helper; create a sibling `captionService.getContent(videoId, captionId): Promise<string>` that uses `api.get` with `Accept: text/plain` (or fall back to `fetch` + auth). Test against both a public and a private video in TS-002.
  - **`getMyVideos` pagination** — the `<VideoPickerDialog/>` must support "Load more" or it caps at 20. Reuse the `Load more comments` button pattern from `src/components/comment-section.tsx` (Phase 6 remediation).
  - **`channelService.getMyChannels()` may return zero channels** for users who haven't created one — `<AnalyticsPage/>` already handles `primaryChannelId === undefined`. The new `<ChannelSelect/>` must keep that path: render an empty state ("Create a channel to see analytics") instead of a disabled dropdown.
  - **Compare-period for "All time"** is meaningless (no prior period exists). Hide the delta badge when `dateRange.start_date === ""`. Likewise hide when `prev` returns zero (no historical data — would render `Infinity%`).
  - **Caption polling job-id might 404 briefly** — vidra-core may create the job lazily. The polling hook should treat 404 as "still pending" for the first 10 s then surface "job not found" after that.
  - **Auto-caption flag persistence** — when the user edits an auto-generated caption track (TS-003), check whether the backend resets `is_auto_generated` to `false` on PUT. If it does, the "Auto" badge will disappear post-edit; this is acceptable. Note in TS-003 that the badge state after save is whatever vidra-core returns (do not assert badge state).
- **Domain context:**
  - **Whisper auto-captioning** runs as a server-side studio job (same job table as cut/intro/watermark) on vidra-core. The frontend treats it as a normal `StudioJob` — type is `"caption"` or similar (see `StudioJobType` at `types.ts:513`; if `"caption"` is not in the union, vidra-core may emit a different type — verify via TS-002 and add the literal to the union if needed).
  - **Compare-period semantics** — "previous 30 days vs prior 30 days." If user picks 2026-04-01 → 2026-04-30, prev = 2026-03-02 → 2026-03-31 (30-day window ending the day before `start_date`).
  - **Retention curve x-axis** is `time_percent` 0-100 — meaning a 10-min video and a 1-hour video both render on the same axis. Already correct in `video-analytics-page.tsx:36`.

## Runtime Environment

- **Start:** `pnpm dev` (frontend, port 3000, Turbopack) + `pnpm dev:full` to also boot vidra-core docker stack (BTCPay, IPFS, Postgres) per `feedback_payment_reconciliation.md`. For Phase 13 the relevant containers are `vidra-core` (port 9000) and `postgres`.
- **Health check:** `curl -fsS http://localhost:3000/api/health` (frontend) and `curl -fsS http://localhost:9000/api/v1/health` (backend).
- **Restart:** `pnpm dev` reloads on change. For backend changes (none in this phase): `docker compose -f compose.dev.yml restart vidra-core`.

## Assumptions

- vidra-core endpoint `POST /api/v1/videos/{id}/captions/generate` returns a `StudioJob` whose `id` is queryable at `GET /api/v1/videos/{id}/studio/jobs/{jobId}`. Supported by `captionService.generate` returning `StudioJob` (`captions.ts:40`) and the existing `studioService.getJob` (`studio.ts:27`). Tasks 4, 5 depend on this.
- Caption content endpoint `GET /api/v1/videos/{id}/captions/{id}/content` returns plain VTT or SRT text matching the `caption.file_format` field. Supported by audit line 213. Task 3 depends on this.
- For private videos, the captions/content endpoint accepts `Authorization: Bearer <token>` (same auth shape as the rest of the API). Supported by the api client pattern. Task 3 depends on this; if the endpoint actually requires no auth even for private videos (i.e., URL-signed), implementer pivots to `captionService.getContentUrl` + plain `fetch`.
- `analyticsService.getChannelAnalytics` and `getVideoAnalytics` accept arbitrary date ranges (not just paged ones) and return totals over the requested window. Supported by `analytics.ts:30-57`. Task 8 depends on this.
- `videoService.getMyVideos` returns videos where the calling user is the uploader, paginated. Supported by `videos.ts:334`. Task 1 depends on this.
- `pnpm i18n:check` enforces parity across `messages/*.json` and runs in CI. Supported by `package.json:28` + `feedback_service_test_coverage.md` cadence. Task 9 depends on this.
- `<LineChart/>` at `src/components/charts/line-chart.tsx` accepts arbitrary `{x, y}[]` and an `ariaLabel` — already used by retention + views-over-time. Tasks 6, 7 depend on this.

## Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| Caption content endpoint returns 401 for private videos with no auth header | Medium | High | Task 3 starts with the curl smoke test that picks the correct auth strategy (bearer header vs. signed URL) once, before writing any service code. TS-002 tests both private and public videos. |
| Auto-caption job type literal differs from `"caption"` (e.g., `"transcribe"`) and breaks the existing `StudioJobType` union | Medium | Medium | Task 5 verifies the literal first via the documented browser-console snippet (logs `j.type` from the `generate` response), then extends `StudioJobType` in the same task if needed before swapping the polling source. |
| `getMyVideos` returns videos for *all* user channels (not just current) — picker shows wrong videos for multi-channel users picking intro for channel A | Low | Medium | Task 1 confirms the response contains a `channel_id` field; if so, the picker filters client-side by the video's owning channel. If not, document as known limitation and surface the channel name on each row. |
| Compare-period parallel fetch doubles analytics API load and hits a vidra-core rate limit | Low | Low | Both calls run in `Promise.all` — single round-trip for the user. Backend is currently uncapped on analytics endpoints; if a future limit emerges, switch to a single `compare=true` query param when the endpoint supports it. |
| VTT files with cue settings or styling cues (`STYLE`, `NOTE` blocks) crash the in-house parser | Medium | Medium | `parseVtt` skips `WEBVTT`/`STYLE`/`NOTE`/`REGION` blocks and unknown headers. Test fixture in task 2 includes a real PeerTube-exported VTT with `NOTE` blocks. Cue-settings line (e.g., `align:start`) is preserved as text suffix on the timestamp line and stripped. |
| Auto-caption job 404s briefly after submission → polling loop reports "not found" too soon | Medium | Low | `useStudioJob` treats 404 as `pending` for the first 10 s, then surfaces error. Matches vidra-core's lazy-job-creation behavior. |
| Channel-selector localStorage key collides with another feature using `vidra.analytics.*` | Low | Low | Use `vidra.analytics.channelId` (already namespaced); grep confirms no other consumer. |
| 13-locale translations drift on follow-up edits | Low | Medium | `pnpm i18n:check` blocks merges; CI already runs it. |

## Goal Verification

### Truths

1. **Caption editor opens populated.** Clicking Edit on an existing caption track loads its content via the captions/content endpoint, parses it, and renders one row per cue in the table — regardless of whether the track was uploaded manually or auto-generated. (TS-002, TS-003)
2. **Studio intro/outro pick a real video.** The user clicks "Choose video" instead of typing an ID; a modal opens, lists their videos with thumbnails, supports search and "Load more"; selection populates the chip; "Add intro" submits with the correct `intro_video_id`. (TS-001)
3. **Auto-caption progress is real.** After clicking "Auto-generate → English," the button shows a real progress percentage (not just a spinner) and surfaces job errors when generation fails. (TS-004)
4. **Analytics dashboard is multi-channel-aware.** A user with two channels can switch between them via a dropdown; the dashboard re-fetches and the URL/localStorage persists the selection across reload. (TS-005)
5. **Date-range presets work.** Clicking "30d" updates both stat cards and the line chart; the underlying request includes the correct `start_date` 30 days before today. (TS-005)
6. **Compare-period delta renders where the backend has data.** On the channel page, the **Total Views** card shows a `↑/↓ N%` badge. On the video page, all six stat cards (`Views`, `Watch Time`, `Avg Duration`, `Likes`, `Dislikes`, `Comments`) show a badge. Each badge matches `(curr - prev) / prev * 100` rounded to 1 decimal, computed from a parallel call for the prior equal-length window (one Promise.all on the page). Hidden when no range is selected, when prev is zero, or when current is zero. The channel page's Watch Time / Subscribers / Videos cards intentionally render no badge until vidra-core enriches the backend response (audit Still-Broken #5). (TS-005, TS-006)
7. **Retention curve renders against real data.** Browsing to `/analytics/video/{id}` for a video that has accumulated retention events produces a non-flat line chart with at least one point > 0% audience. (TS-006)
8. **All new strings translate.** `pnpm i18n:check` exits 0; switching locale to `ja`, `ar`, `de` shows translated copy in studio editor, caption editor, video picker, analytics dashboard.
9. **No regressions.** `pnpm test:run`, `pnpm lint`, `pnpm typecheck`, `pnpm build` all green; existing E2E specs stay green.

### Artifacts

- `src/components/video-picker-dialog.tsx` — new component (Truth 2)
- `src/components/studio-editor.tsx` — modified (Truth 2)
- `src/components/caption-editor.tsx` — `parseVtt` + `parseSrt` exports added (Truth 1)
- `src/components/caption-language-list.tsx` — `handleEdit` rewritten (Truth 1)
- `src/components/auto-caption-button.tsx` — polling rewritten (Truth 3)
- `src/lib/hooks/use-studio-job.ts` — new hook (Truths 2, 3)
- `src/lib/analytics/compare-period.ts` — new helper (Truth 6)
- `src/components/analytics-date-presets.tsx` — new component (Truth 5)
- `src/components/channel-select.tsx` — new component (Truth 4)
- `src/components/pages/analytics-page.tsx` — modified (Truths 4, 5, 6)
- `src/components/pages/video-analytics-page.tsx` — modified (Truth 6)
- `src/lib/api/services/captions.ts` — `getContent()` method added (Truth 1)
- `messages/{ar,de,en,es,fr,it,ja,ko,nl,pl,pt,ru,zh}.json` — new keys (Truth 8)
- `e2e/phase-13-*.spec.ts` — TS-001..TS-006 (Truths 1-7)
- All matching `__tests__/*.test.tsx` Vitest files (Truth 9)

## E2E Test Scenarios

### TS-001: Studio video picker for intro/outro
**Priority:** Critical
**Preconditions:** Logged-in user has uploaded ≥ 3 videos (call them V1, V2, V3). Currently editing V1.
**Mapped Tasks:** Task 1

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Navigate to `/videos/{V1.id}/edit`, click `Studio` tab | Studio editor renders with Cut, Intro/Outro, Watermark cards |
| 2 | Click `Choose intro video` button under Intro/Outro card | Dialog opens with title "Pick a video", lists V1, V2, V3 with thumbnails |
| 3 | Type "V2" in the search input | List filters to V2 only |
| 4 | Click V2 row | Dialog closes; chip showing "V2" + thumbnail appears next to `Add intro` |
| 5 | Click `Add intro` | Toast "Intro queued"; active-job card appears with type `intro`, status transitions from `pending` → `processing` within 10 s |
| 6 | Wait for completion | **Default CI:** assert only the `pending → processing` transition (step 5). **Gated on `process.env.E2E_STUDIO_FULL=1`:** wait ≤ 90 s for `completed`, success toast appears. Real ffmpeg stitching can exceed 30 s on slow runners — the full path runs only when the env flag is set. |

### TS-002: Caption editor loads existing content
**Priority:** Critical
**Preconditions:** Logged-in user owns video V1; V1 has one English caption track with content `WEBVTT\n\n00:00:00.000 --> 00:00:05.000\nHello world\n\n00:00:05.000 --> 00:00:10.000\nLine two\n`.
**Mapped Tasks:** Tasks 2, 3

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Navigate to `/videos/{V1.id}/edit`, click `Captions` tab | Caption track list renders with the English row |
| 2 | Click the pencil (Edit) button on the English row | Skeleton appears briefly; then editor renders with **two** cue rows |
| 3 | Inspect row 1 | Start `00:00:00.000`, End `00:00:05.000`, Text `Hello world` |
| 4 | Inspect row 2 | Start `00:00:05.000`, End `00:00:10.000`, Text `Line two` |
| 5 | Edit row 1 text to `Hello world!`, click Save | Toast "Captions saved"; track stays selected |
| 6 | Click Edit again on the same row | Editor re-loads with row 1 text now `Hello world!` (round-trip persists) |

### TS-003: Caption editor with private video and auto-generated track
**Priority:** High
**Preconditions:** Logged-in user owns a **private** video V_priv with one auto-generated caption track (`is_auto_generated: true`).
**Mapped Tasks:** Tasks 2, 3

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Navigate to `/videos/{V_priv.id}/edit`, click `Captions` tab | Track row visible with the purple "Auto" badge |
| 2 | Click Edit on the track | Editor loads with parsed cues (no 401 error) |
| 3 | Add a new cue, click Save | Toast "Captions saved"; no error in console |
| 4 | Re-open Edit | New cue persists; existing cues retained |

### TS-004: Auto-caption real progress
**Priority:** High
**Preconditions:** Logged-in user owns video V_new with no captions.
**Mapped Tasks:** Tasks 4, 5

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Navigate to `/videos/{V_new.id}/edit`, click `Captions` tab | Empty-state "No captions yet" |
| 2 | Click `Auto-generate → English` | Dropdown closes; button label shows "Generating… N%" with progress > 0% within 10 s |
| 3 | Wait for completion (≤ 90 s on test fixtures) | Toast "Captions generated successfully"; track list refetches; English row appears with the "Auto" badge |
| 4 | Click Edit on the new row | Editor loads with parsed cues (≥ 1 cue) |

### TS-005: Channel analytics dashboard upgrades
**Priority:** Critical
**Preconditions:** User owns two channels (CH-A with 100+ views, CH-B with views).
**Mapped Tasks:** Tasks 6, 8

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Navigate to `/analytics` | Dashboard renders with CH-A selected (or whichever was last picked); preset chips visible |
| 2 | Click `30d` preset chip | Stat cards update; line chart redraws; `start_date` in the request equals (today − 30 days) |
| 3 | Inspect the **Total Views** stat card | Below the value, a `↑ N%` or `↓ N%` badge renders matching the compare-period delta. The other three channel stat cards render no badge (intentional — backend doesn't return those fields yet). |
| 4 | Open channel selector dropdown, choose CH-B | A network request to `/api/v1/channels/{CH-B.id}/analytics` fires (assert via `page.waitForRequest`); `localStorage.vidra.analytics.channelId === CH-B.id` (assert via `page.evaluate`); the dashboard root has `data-testid="analytics-channel"` with `data-channel-id={CH-B.id}` |
| 5 | Reload page | CH-B is still selected; `data-channel-id={CH-B.id}` on the dashboard root |
| 6 | Click `All time` preset | Compare-period badge on Total Views hides (no prior period for all-time) |

### TS-006: Video analytics retention curve + compare
**Priority:** High
**Preconditions:** Video V_pop has accumulated retention events from at least 5 viewers reaching different points; views_over_time non-empty.
**Mapped Tasks:** Tasks 7, 8

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Navigate to `/analytics/video/{V_pop.id}` | Page renders with stats grid + retention curve + views-over-time |
| 2 | Inspect retention curve SVG | The serialized data points (read via `data-testid="line-chart-data"`) satisfy `max(audience_percent) > min(audience_percent)` — i.e., the curve has variation, not a flat plateau. At least one point has `audience_percent > 0`. |
| 3 | Pick `7d` preset | Retention re-fetches for the 7-day window; curve re-renders |
| 4 | Inspect a stat card | Compare-period `↑/↓ N%` badge shows; matches `(curr - prev) / prev * 100` rounded to 1 decimal |
| 5 | Click `Export CSV` | Downloads `video-{V_pop.id}-analytics.csv` containing the period's data |

## Progress Tracking

- [x] Task 1: Video picker dialog + studio editor integration (C16)
- [x] Task 2: VTT/SRT parsers in `caption-editor.tsx` (C18)
- [x] Task 3: Caption content fetch + populate editor (C18)
- [x] Task 4: `useStudioJob` hook extracted from StudioEditor
- [x] Task 5: Auto-caption polling switch (C17)
- [x] Task 6: Channel selector + date-range presets (C19)
- [x] Task 7: Retention curve verification (E2E only) (C19)
- [x] Task 8: Compare-period delta on stat cards (C19)
- [x] Task 9: Full 13-locale i18n extraction
- [x] Task 10: E2E suite (TS-001..TS-006) + verification

**Total Tasks:** 10 | **Completed:** 10 | **Remaining:** 0

## Implementation Tasks

### Task 1: Video picker dialog + studio editor integration

**Objective:** Replace the two free-form Video-ID `<input/>`s in `studio-editor.tsx` with a reusable `<VideoPickerDialog/>` modal sourced from `videoService.getMyVideos`.
**Dependencies:** None
**Mapped Scenarios:** TS-001

**Files:**
- Create: `src/components/video-picker-dialog.tsx`
- Create: `src/components/__tests__/video-picker-dialog.test.tsx`
- Modify: `src/components/studio-editor.tsx`
- Modify: `src/components/__tests__/studio-editor.test.tsx`

**Key Decisions / Notes:**
- Use Radix `Dialog` (already in deps via shadcn). Style: `Dialog.Content` with `bg-card`, `border-border/30`, `rounded-2xl`, max width `max-w-2xl`. Match Phase 9 Inner Circle dialog (`studio-inner-circle-page.tsx`).
- Dialog state local to `studio-editor.tsx` (`introPickerOpen`, `outroPickerOpen`). Picker calls `onSelect({ id, title, thumbnailUrl })`.
- "Load more" pattern: re-use comment-section approach (`src/components/comment-section.tsx`) — `start += count`, append on click, hide when `loaded >= total`.
- Search input filters client-side over loaded pages (server-side search would require a different endpoint; not present today). To make this scope visible to users: render a footer hint inside the dialog, `Showing {N} of {total} videos. Load more to expand search.` Document the limitation in an implementer comment. (Server-side video search is captured as a Deferred Idea.)
- Selected video chip shows thumbnail (40×24px), title (truncate), and a small "Change" button that re-opens the picker.
- Keyboard: Tab focus traps inside Dialog (Radix default); Escape closes; Enter selects focused row.
- Performance: Memoize the filtered list — large channels can have 100+ videos in memory.

**Definition of Done:**
- [ ] `<VideoPickerDialog/>` opens, lists user's videos, supports filter + Load more, returns selection
- [ ] Studio editor renders selected video as a chip; submitting "Add intro" passes the selected `id` to `studioService.addIntro`
- [ ] Vitest covers: open/close, select, cancel, empty-state (no videos), Load more, filter
- [ ] No console warnings; no regressions in existing studio-editor tests
- [ ] All new strings extracted to `Studio.*` and `VideoPicker.*` namespaces (translation deferred to Task 9)

**Verify:**
- `pnpm test:run src/components/__tests__/video-picker-dialog.test.tsx src/components/__tests__/studio-editor.test.tsx`

### Task 2: VTT/SRT parsers in `caption-editor.tsx`

**Objective:** Add `parseVtt(text): CaptionCue[]` and `parseSrt(text): CaptionCue[]` exports next to the existing `cuesToVtt` / `cuesToSrt` writers.
**Dependencies:** None
**Mapped Scenarios:** TS-002, TS-003 (indirectly)

**Files:**
- Modify: `src/components/caption-editor.tsx`
- Create: `src/components/__tests__/caption-editor-parsers.test.tsx`

**Key Decisions / Notes:**
- Pure functions, no React, no async. Each returns `CaptionCue[]` (id = cryptographically-random or `cue_<index>`; index is acceptable here since cues are re-keyed on save).
- VTT parser: split on `\n\n`, skip blocks where the first non-blank line is `WEBVTT`, `STYLE`, `NOTE`, or `REGION`. For data blocks: optional first line is cue id, next line must contain `-->` (parse with the same `parseCueTime` already in the file), remaining lines are joined with `\n` as the text. Strip `align:start position:50%` cue settings from the timestamp line.
- SRT parser: same block split, optional first line is numeric id, second line is `HH:MM:SS,mmm --> HH:MM:SS,mmm` (replace `,` with `.` before reusing `parseCueTime`), remaining lines are text.
- Round-trip property: `parseVtt(cuesToVtt(cues)).map(stripIds) === cues.map(stripIds)` for cues with valid time spans (`stripIds` removes the `id` field since it's regenerated).
- Error handling: malformed timestamp → skip that cue (return remaining valid cues, no throw). Empty input → return `[]`.

**Definition of Done:**
- [ ] `parseVtt` handles: simple cues, multi-line text, cue id present, cue id absent, `NOTE` block, `STYLE` block, hours field, cue settings on timestamp line
- [ ] `parseSrt` handles: simple cues, multi-line text, hours field, comma-formatted milliseconds
- [ ] Round-trip property test: `parseVtt(cuesToVtt(cues))` re-produces equivalent cues for ≥ 4 fixture inputs
- [ ] Round-trip property test: `parseSrt(cuesToSrt(cues))` re-produces equivalent cues for ≥ 4 fixture inputs (mirrors VTT case)
- [ ] Empty / malformed input does not throw
- [ ] No new dependencies added

**Verify:**
- `pnpm test:run src/components/__tests__/caption-editor-parsers.test.tsx`

### Task 3: Caption content fetch + populate editor

**Objective:** Replace the empty-cues TODO at `src/components/caption-language-list.tsx:40-45` with a real fetch + parse path that populates `editingCues` before opening the editor.
**Dependencies:** Task 2
**Mapped Scenarios:** TS-002, TS-003

**Files:**
- Modify: `src/lib/api/services/captions.ts`
- Modify: `src/lib/api/services/__tests__/captions.test.ts`
- Modify: `src/components/caption-language-list.tsx`
- Modify: `src/components/__tests__/caption-language-list.test.tsx`

**Key Decisions / Notes:**
- **Smoke-test the auth strategy before writing the service method.** Run the following against a private video + the user's bearer token to determine which path applies:
  ```bash
  curl -i -H "Authorization: Bearer $TOKEN" "$API/api/v1/videos/$VID/captions/$CID/content"
  curl -i                                   "$API/api/v1/videos/$VID/captions/$CID/content"
  ```
  **Decision matrix:**
  - 200 with auth header / 401 without → use authed `fetch` (the strategy below). This is the expected path.
  - 200 without auth (signed URL or cookie auth) → use `captionService.getContentUrl` + plain `fetch` and drop the `Authorization` header (some object-store backends reject it).
  Pick ONE strategy based on this evidence and commit. Document the chosen path in the closeout.
- Imports follow the `analytics.ts:1-2` pattern (use `API_BASE` from `../client`, do **not** keep the `process.env.NEXT_PUBLIC_API_BASE_URL` line at `captions.ts:4` — remove it):
  ```ts
  import { api, publicApi, getAccessToken, API_BASE } from "../client";
  ```
- Default service method (assumes the bearer-auth path won the smoke test):
  ```ts
  async getContent(videoId: string, captionId: string, _format: "vtt" | "srt"): Promise<string> {
    const token = getAccessToken();
    const headers: Record<string, string> = { Accept: "text/plain" };
    if (token) headers["Authorization"] = `Bearer ${token}`;
    const res = await fetch(`${API_BASE}/api/v1/videos/${videoId}/captions/${captionId}/content`, { headers });
    if (!res.ok) {
      if (res.status === 404) return "";
      throw new Error(`Caption content fetch failed: ${res.status}`);
    }
    return res.text();
  }
  ```
- `handleEdit` becomes async: set loading state, `await captionService.getContent(...)`, parse by `caption.file_format`, set cues. Error → log + toast + open editor with empty cues (do not block edit).
- Add `editingLoading: boolean` state to `CaptionLanguageList`. Render `<div className="h-32 bg-accent/10 animate-pulse rounded-xl"/>` skeleton while loading.
- Update existing tests: mock `fetch` for the content endpoint; assert cues render after the await resolves.

**Definition of Done:**
- [ ] Clicking Edit fetches content via `captionService.getContent`, parses, populates editor
- [ ] 404 (no content yet) → editor opens with empty cues, no error toast
- [ ] 5xx → toast + editor opens with empty cues
- [ ] Private-video Edit succeeds when user has access
- [ ] Round-trip works: load → edit → save → re-load shows updated text
- [ ] `__tests__/captions.test.ts` covers `getContent` happy path + 404 + 401

**Verify:**
- `pnpm test:run src/lib/api/services/__tests__/captions.test.ts src/components/__tests__/caption-language-list.test.tsx`

### Task 4: `useStudioJob` hook extracted from StudioEditor

**Objective:** Extract the active-job polling pattern at `studio-editor.tsx:48-68` into a reusable hook so `AutoCaptionButton` can share it.
**Dependencies:** None
**Mapped Scenarios:** TS-001 (regression), TS-004

**Files:**
- Create: `src/lib/hooks/use-studio-job.ts`
- Create: `src/lib/hooks/__tests__/use-studio-job.test.ts`
- Modify: `src/components/studio-editor.tsx`
- Modify: `src/components/__tests__/studio-editor.test.tsx`

**Key Decisions / Notes:**
- Signature: `useStudioJob(videoId: string, jobId: string | null): { job: StudioJob | null; status: StudioJobStatus | null; progress: number; error: string | null }`.
- 5 s polling interval; clears on `completed | failed`; clears on unmount.
- 404 handling: count consecutive 404s; treat as `pending` for the first 2 polls (≤10 s), then surface as `error: "Job not found"`.
- Returns `null` cleanly when `jobId` is null (caller hasn't started a job yet).
- Existing `<StudioEditor/>` keeps its `activeJob` state for the initial `listJobs` mount-check, then hands the active job's `id` to `useStudioJob`.

**Definition of Done:**
- [ ] Hook polls `studioService.getJob` every 5 s when `jobId` non-null
- [ ] Polling stops on `completed | failed`
- [ ] 404 handling: pending for ≤ 10 s, then surfaces error
- [ ] Cleanup on unmount
- [ ] Studio editor uses the hook; existing tests still pass
- [ ] Vitest with fake timers covers polling, completion, failure, 404 grace, unmount

**Verify:**
- `pnpm test:run src/lib/hooks/__tests__/use-studio-job.test.ts src/components/__tests__/studio-editor.test.tsx`

### Task 5: Auto-caption polling switch

**Objective:** Replace the captions-list polling in `auto-caption-button.tsx:46-72` with `useStudioJob` so the button shows real progress and surfaces job errors.
**Dependencies:** Task 4
**Mapped Scenarios:** TS-004

**Files:**
- Modify: `src/components/auto-caption-button.tsx`
- Modify: `src/components/__tests__/auto-caption-button.test.tsx`
- Modify: `src/lib/api/types.ts` (only if `StudioJobType` does not include the literal vidra-core returns for caption jobs)

**Key Decisions / Notes:**
- After `captionService.generate(...)` resolves with a `StudioJob`, store the job id in local state and pass to `useStudioJob`. Render button label as `"Generating… {progress}%"` while `status in {pending, processing}`.
- On `status === "completed"`: refetch caption list, success toast, clear job id.
- On `status === "failed"`: error toast with `job.error`, clear job id.
- **Verify the literal `job.type` returns from vidra-core before swapping the polling source.** Concrete steps:
  1. With dev server running, log in as a creator with a video that has no captions.
  2. From the browser console: `await fetch("/api/v1/videos/$VID/captions/generate", { method: "POST", headers: { "Content-Type": "application/json", "Authorization": "Bearer "+localStorage.getItem("access_token") }, body: JSON.stringify({ language_code: "en" }) }).then(r => r.json()).then(j => console.log(j.type))`
  3. The logged literal is the actual `StudioJobType` value vidra-core emits for caption jobs.
  4. If it is **not** in `"cut" | "intro" | "outro" | "watermark"`, extend the union in `src/lib/api/types.ts:513` (e.g., add `"caption"` or `"transcribe"` — whatever was logged) **in this same task** before swapping the polling source.
  5. Add a unit test fixture in `__tests__/auto-caption-button.test.tsx` covering the actual literal returned.
- Existing 5-minute timeout becomes redundant (polling is bounded by job state); remove it.

**Definition of Done:**
- [ ] Button shows real progress percentage during generation
- [ ] On completion → list refetches, "Auto" badge appears on new row
- [ ] On failure → error toast surfaces `job.error`
- [ ] Existing test suite extended with: progress display, failure toast, list refetch on completion
- [ ] No regression: dropdown opens/closes, generation only triggers once per click, button disables while generating

**Verify:**
- `pnpm test:run src/components/__tests__/auto-caption-button.test.tsx`

### Task 6: Channel selector + date-range presets

**Objective:** Replace `primaryChannelId = myChannels?.data?.[0]?.id` with a dropdown selector and add 5 date-range preset chips above the existing date picker.
**Dependencies:** None
**Mapped Scenarios:** TS-005

**Files:**
- Create: `src/components/channel-select.tsx`
- Create: `src/components/__tests__/channel-select.test.tsx`
- Create: `src/components/analytics-date-presets.tsx`
- Create: `src/components/__tests__/analytics-date-presets.test.tsx`
- Modify: `src/components/pages/analytics-page.tsx`
- Modify: `src/components/pages/__tests__/analytics-page.test.tsx`

**Key Decisions / Notes:**
- `<ChannelSelect/>`: Radix `Select` (or simple `<select/>` with HIG styling — Phase 12 used native `<select/>` for runner filters, match that). Renders disabled when only one channel exists.
- localStorage key: `vidra.analytics.channelId`. On mount, read; if value matches a channel id in the list, use it; else fall back to first channel **and call `localStorage.removeItem("vidra.analytics.channelId")`** so we don't carry a dead pointer across reloads (e.g., after a channel deletion).
- Render `data-testid="analytics-channel"` with `data-channel-id={selectedId}` on the dashboard root for E2E assertions (TS-005 step 4).
- `<AnalyticsDatePresets/>`: 5 buttons (`7d / 30d / 90d / 1y / All time`). Active chip styled with `bg-cyan-500/20 text-cyan-400` (HIG accent). Selecting a chip computes `start_date = today - N days` (ISO date), `end_date = today`. "All time" sends `{ start_date: "", end_date: "" }`.
- Preset selection clears any custom range from `<AnalyticsDatePicker/>`. Custom-range entry clears the active preset chip. Both are "controlled" by the parent's `dateRange` state.
- Performance: `useMemo` the chip → range mapping (cheap but conventional).

**Definition of Done:**
- [ ] Channel selector renders, persists to localStorage, drives the dashboard fetch
- [ ] Single-channel users see disabled selector with the channel name; no zero-channels regression
- [ ] Five preset chips render; clicking each sets the correct date range; line chart and stat cards update
- [ ] "All time" hides compare-period badges (per Task 8 wiring)
- [ ] Existing custom date picker still works
- [ ] All new strings under `AnalyticsPage.*` and `AnalyticsPresets.*` (translations in Task 9)

**Verify:**
- `pnpm test:run src/components/__tests__/channel-select.test.tsx src/components/__tests__/analytics-date-presets.test.tsx src/components/pages/__tests__/analytics-page.test.tsx`

### Task 7: Retention curve verification (E2E only)

**Objective:** Browser-verify that retention data flows from vidra-core through `analyticsService.getRetention` to the line chart on `/analytics/video/{id}`. No code changes — this task is purely a Playwright spec.
**Dependencies:** None
**Mapped Scenarios:** TS-006

**Files:**
- Create: `e2e/phase-13-video-analytics.spec.ts`

**Key Decisions / Notes:**
- **Task 7 owns seeding the retention fixture so the spec never skips.** Two viable seed paths:
  1. **Programmatic seed (preferred):** POST view-events directly to vidra-core (`POST /api/v1/videos/{id}/view` or whichever endpoint records the watch-time signal — verify against the running backend during planning) with varied `position` values to produce a non-flat retention curve. Run as a `test.beforeAll` step.
  2. **Fallback playback seed:** in `test.beforeAll`, log in as two distinct viewer fixtures (existing `e2e/fixtures/auth-*.ts` patterns), each navigates to the video and watches with `setCurrentTime` jumps to different points, producing the retention signal.
- Assertions (always run, never skip):
  - `<svg/>` for retention chart is present.
  - At least one `<polyline/>` or `<path/>` element renders with non-trivial geometry (≥ 2 points).
  - Programmatic check: read the underlying chart data via the `data-testid="line-chart-data"` attribute (add to `<LineChart/>` in this task) — assert `max(audience_percent) > min(audience_percent)` AND at least one point has `audience_percent > 0`.
- If seeding fails, the test must FAIL (not skip) — silent skip masks real regressions.

**Definition of Done:**
- [ ] `<LineChart/>` exposes `data-testid="line-chart-data"` with serialized points (read-only attribute)
- [ ] `e2e/phase-13-video-analytics.spec.ts` runs **and asserts** every CI run — never skips. If seeding fails, the test fails with a clear seed-error message.
- [ ] Programmatic chart-data check: `max(audience_percent) > min(audience_percent)` AND at least one point > 0
- [ ] Manual browser verification documented in TS-006 evidence

**Verify:**
- `pnpm test:e2e e2e/phase-13-video-analytics.spec.ts`

### Task 8: Compare-period delta on stat cards

**Objective:** Add a small `↑/↓ N%` badge under the value on stat cards backed by real backend data — Total Views (channel page) and all six video stat cards (video page) — computed from a parallel "previous equal-length window" fetch. Channel page Watch Time / Subscribers / Videos render no badge until vidra-core enriches the response.
**Dependencies:** Task 6
**Mapped Scenarios:** TS-005, TS-006

**Files:**
- Create: `src/lib/analytics/compare-period.ts`
- Create: `src/lib/analytics/__tests__/compare-period.test.ts`
- Modify: `src/components/pages/analytics-page.tsx`
- Modify: `src/components/pages/video-analytics-page.tsx`
- Modify: `src/components/pages/__tests__/analytics-page.test.tsx`
- Modify: `src/components/pages/__tests__/video-analytics-page.test.tsx`

**Key Decisions / Notes:**
- `compute-period.ts` exports:
  - `computePrevRange(range: AnalyticsDateRange): AnalyticsDateRange | null` — null when range has no start/end (all-time). Otherwise returns `{ start_date: range.start_date - N, end_date: range.start_date - 1 day }` where N = end - start.
  - `computeDelta(curr: number, prev: number): { pct: number; direction: "up" | "down" | "flat" } | null` — null when prev is 0; flat when curr === prev.
- Page-level: when `dateRange.start_date` is non-empty, issue both fetches in `Promise.all`. Pass the prev result to each stat card via a `prevValue` prop. Each card renders the badge below the value when both values are present and `computeDelta` returns non-null.
- Performance: gate the prev fetch behind `useMemo` on the `prevRange` key so it only re-fetches when the range changes.
- Edge: zero values render no badge (avoid `Infinity%`); negative-going deltas render `↓ N%` in red, positive in green.

**Definition of Done:**
- [ ] `compute-period.ts` handles: equal-length window, leap-year edges, "All time" returns null, zero-prev returns null, **prev window predates account/video creation (returns zero data) → delta returns null → badge hidden** (covers new accounts on long ranges)
- [ ] Channel page renders a compare badge **only on the Total Views card** (other 3 cards intentionally render no badge)
- [ ] Video page renders compare badges on all 6 stat cards when range is set
- [ ] "All time" hides all compare badges
- [ ] Visual: ↑ green, ↓ red, hidden on zero-prev or zero-curr
- [ ] Initial render fires exactly two analytics calls (current + previous window) wrapped in `Promise.all` — no third or duplicate call from re-render churn (assert via `vi.spyOn` on the service in unit tests)
- [ ] Existing tests in both page test suites updated for the new prop shape

**Verify:**
- `pnpm test:run src/lib/analytics/__tests__/compare-period.test.ts src/components/pages/__tests__/analytics-page.test.tsx src/components/pages/__tests__/video-analytics-page.test.tsx`

### Task 9: Full 13-locale i18n extraction

**Objective:** Extract every user-facing string introduced or touched in this phase to `messages/en.json`, then translate across 12 sibling locales. Pass `pnpm i18n:check`.
**Dependencies:** Tasks 1, 2, 3, 4, 5, 6, 8
**Mapped Scenarios:** Truth 8

**Files:**
- Modify: `messages/en.json`
- Modify: `messages/{ar,de,es,fr,it,ja,ko,nl,pl,pt,ru,zh}.json` (12 files)
- Modify: every `.tsx` from prior tasks (replace literal strings with `t("Key.path")` calls)

**Key Decisions / Notes:**
- Namespaces: `Studio.*` (cut/trim/intro/outro/watermark/job-status/buttons), `Captions.*` (track list, editor table headers, errors), `VideoPicker.*` (modal title/search/empty/load-more), `AnalyticsPage.*` (channel-level), `VideoAnalyticsPage.*` (video-level), `AnalyticsPresets.*` (chip labels), `AutoCaption.*` (button label, language menu).
- Pluralization: where counts are involved (`captions.length`, retention point count), use `next-intl`'s `t("Key", { count })` ICU MessageFormat plural form.
- Translations: aim for native-speaker quality where possible; for languages where exact term coverage is uncertain (e.g., "Watermark" in `ja`, `ko`), default to the most common rendering used in PeerTube's locale files (PeerTube is Apache-2.0; we can lift translations as long as the file headers remain compatible — review `client/src/locale/*.xlf` in PeerTube, transcribe relevant strings).
- **Explicit reuse list** (do NOT duplicate these under the new namespaces):
  - `VideoEdit.studio` (`messages/en.json:795`) — tab label "Studio"
  - `VideoEdit.captions` (`messages/en.json:796`) — tab label "Captions"
  - The sidebar `Analytics` label (`messages/en.json:715`) — already translated
  - `Common.save`, `Common.cancel`, `Common.delete` (if they exist — verify with `grep "^  \"Common\":" messages/en.json` first)
- Re-use: any other existing key that already conveys the same meaning — do not duplicate.

**Definition of Done:**
- [ ] All hardcoded strings in C16/C17/C18/C19 surfaces extracted
- [ ] `messages/en.json` keys grouped under the namespaces listed
- [ ] All 12 sibling locales have matching keys (no missing or extra)
- [ ] `pnpm i18n:check` exits 0
- [ ] Manual smoke: switch locale to `ja`, navigate to `/analytics` and `/videos/{id}/edit`, confirm text translates

**Verify:**
- `pnpm i18n:check`
- `pnpm dev` then manual locale switch via `/ja/analytics`

### Task 10: E2E suite (TS-001..TS-006) + verification

**Objective:** Land Playwright specs for every TS scenario, then run the full quality gate.
**Dependencies:** All prior tasks
**Mapped Scenarios:** TS-001..TS-006

**Files:**
- Create: `e2e/phase-13-studio-picker.spec.ts` (TS-001)
- Create: `e2e/phase-13-caption-editor.spec.ts` (TS-002, TS-003)
- Create: `e2e/phase-13-auto-caption.spec.ts` (TS-004)
- Create: `e2e/phase-13-channel-analytics.spec.ts` (TS-005)
- Already created in Task 7: `e2e/phase-13-video-analytics.spec.ts` (TS-006)

**Key Decisions / Notes:**
- Use `playwright-cli` for thorough verification per the rule — `agent-browser` for any quick sanity check.
- Test fixtures: re-use `e2e/fixtures/auth-creator.ts` if present (Phase 12 pattern); otherwise create a minimal helper that logs in via the existing `seed:test-creator` script.
- Each spec begins with `test.beforeEach` setting the locale to `en` to avoid translation flakes.
- Auto-caption spec (TS-004) requires Whisper backend running. Gate behind `process.env.E2E_WHISPER === "1"` so CI without the worker still passes.
- Final verification command sequence:
  1. `pnpm test:run` (Vitest unit) → 0 failures
  2. `pnpm lint` → 0 errors
  3. `pnpm typecheck` → 0 errors
  4. `pnpm i18n:check` → 0 errors
  5. `pnpm build` → succeeds
  6. `pnpm test:e2e e2e/phase-13-*.spec.ts` → 6 specs pass (auto-caption may skip if Whisper not running)
  7. Manual browser walkthrough of each TS via `playwright-cli` recording
- Report a verification summary in the final response listing each command + exit status.

**Definition of Done:**
- [ ] 5 new Playwright specs land (TS-001..TS-006, with TS-006 from Task 7)
- [ ] Each spec encodes the exact steps from the corresponding TS table
- [ ] Verification command sequence above all passes (or auto-caption skipped with explicit reason)
- [ ] Browser-verified evidence captured for at least TS-001, TS-002, TS-005 (screenshots or console output noted in the closeout)
- [ ] No regressions in pre-existing E2E specs

**Verify:**
- `pnpm test:run && pnpm lint && pnpm typecheck && pnpm i18n:check && pnpm build && pnpm test:e2e e2e/phase-13-*.spec.ts`

## PeerTube Parity Check

PeerTube's Studio is structurally similar (cut/intro/outro/watermark, per-video tab inside the video edit screen at `client/src/app/+my-library/+my-video-channels/.../edit/video-update.component.ts`). PeerTube's intro/outro flow uses a **video picker** modal listing the user's videos — Task 1 mirrors that UX. PeerTube's caption editor (`my-account-video-captions/`) loads existing VTT/SRT content into a list of cues — Tasks 2 and 3 mirror that flow. PeerTube's analytics dashboard (`+stats/`) supports channel selection and date-range presets — Task 6 mirrors that. Compare-period delta is **a Vidra extension** (PeerTube does not show period-over-period comparison) — captured under Vidra-Specific below.

## Vidra-Specific / Requested Features

This phase impacts these vidra-core extensions:
- **Video Studio** — finishes the frontend integration of the existing `7596116` route wrappers (cut/intro/watermark). No backend changes.
- **Auto-Captioning (Whisper)** — switches the frontend polling source to the studio-job endpoint, surfacing real progress. No backend changes.
- **Advanced Analytics** — adds compare-period delta, channel selector, and presets. No backend changes (uses existing `/api/v1/channels/{id}/analytics`, `/api/v1/videos/{id}/analytics`, `/stats/retention`).

Compare-period delta is a Vidra-specific UX addition (no PeerTube equivalent). Channel selector matches the PeerTube pattern. Date-range presets match the PeerTube pattern.

## Verification Plan

Per the project rule (`Autonomous Mode Guardrails` in `CLAUDE.md`):

- **Unit:** Vitest run after each task's DoD; full suite before approval. `pnpm test:run` exits 0.
- **Type + lint:** `pnpm typecheck` and `pnpm lint` exit 0.
- **i18n:** `pnpm i18n:check` exits 0.
- **Build:** `pnpm build` succeeds.
- **E2E:** `pnpm test:e2e e2e/phase-13-*.spec.ts` runs all 5 specs (TS-001, TS-002+003, TS-004, TS-005, TS-006). Auto-caption spec gated on `E2E_WHISPER=1`; document if skipped.
- **Manual browser walkthrough** via `playwright-cli` for each TS — record screenshots in the closeout for the 3 critical scenarios (TS-001, TS-002, TS-005).

Final response in the closeout names every verification command run with its exit status, plus the screenshots/snapshots captured.

## Open Questions

None at planning time. All Batch 1 + Batch 2 decisions captured in Approach + Scope.

## Deferred Ideas

- **`/studio` top-level dashboard** — listing recent jobs across all the user's videos with retry/cancel.
- **Multi-track timeline editor** — waveform scrub + drag-resize cues over the player.
- **Demographics + view-heatmap widgets** — depends on vidra-core handlers shipping.
- **Multi-channel comparison view** — A vs B side-by-side analytics.
- **Per-job notification when a long-running studio operation completes** — depends on the notification system.
- **Plugin-driven custom analytics widgets** — depends on the plugin system.
