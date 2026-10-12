# PeerTube v8.3.1 vs vidra: parity audit (2026-10-12)

## Scope and method

- **Compared:** PeerTube `develop` f0b0413 (v8.3.1, 2026-10-06) against vidra-core 368883a, vidra-user adaa149 and vidra-search e204ac5 (all at origin/main).
- **Method:** four read-only agents, one per domain:
  1. media and creator tools
  2. viewer and social features
  3. admin and moderation
  4. federation and protocols
- **What was run:** nothing. Every finding comes from reading the code statically.
- **Verified in-session:** the rows marked ✔ below. The orchestrator re-read the code on both sides for those.
- **Previous audit:** `docs/platform-audit-2026-07.md`, done against PeerTube v7.3.

## Tier 0: shipped defects that block migration (all small)

1. ✔ **The frontend never adopted list pagination.**
   - **Cause:** core 56d5af0 (2026-08-25, in every release since v0.4.0) made the list endpoints return 20 items by default (`internal/httpapi/videos.go:671,1018-1031`). The vidra-user callers still send no `limit` or `offset`.
   - **Affected pages:**
     - channel page (`components/ChannelView.tsx:57,79`, whose comment still says "backend returns full list")
     - Studio "My videos" (`components/studio/MyVideosSection.tsx:56`)
     - subscription feed (`SubscriptionsView.tsx:48`)
     - watch history (`WatchHistoryView.tsx:43`)
     - my playlists and playlist items (`PlaylistDetailView.tsx:34,44`; items are paged at `internal/httpapi/playlists.go:197`)
     - notifications (`NotificationsView.tsx:228`)
     - comments (one fetch with `limit=100`)
   - **Knock-on bug:** reordering a playlist with more than 20 items always fails. `internal/playlist/service.go:234` requires the exact full list of ids, and the client only ever has 20.
   - **Fix:** do it once in the shared seam (`ListTail`/`LoadMoreButton` already exist), not separately at each call site.
2. ✔ **The legacy embed URL `/videos/embed/{uuid}` returns 404.** `/videos/watch/{uuid}` has a lookup route (`app/videos/watch/[id]/route.ts`); embed doesn't. Every PeerTube iframe on a third-party site breaks after migration.
   - Also reported but not verified here: `/video-playlists/embed/*` is missing, and the PeerTube feed parameters (`?videoChannelId=`) are ignored, so feeds silently fall back to the whole instance.
3. ✔ **Descriptions and comments render as plain text.**
   - `WatchView.tsx:647` puts `TimestampedText` inside a `<p>`, so there is no markdown and no linkified URLs.
   - Imported PeerTube descriptions show raw `[x](url)` text.
   - `components/Markdown.tsx` exists but only renders instance documents.
4. ✔ **The About page overclaims.** `InstanceAboutView.tsx:729` says videos "federate to Mastodon, PeerTube". See Tier 1, item 1.

## Tier 1: critical feature gaps

1. ✔ **Federation interop with PeerTube is broken by construction.**
   - **Why PeerTube drops our videos:** the outbound Video object (`internal/federation/video_object.go:68-96`) has no `uuid` or `views`, and PeerTube's validator rejects an object without them (`server/core/helpers/custom-validators/activitypub/videos.ts:89,94`). Its icon also has no width or height.
   - **Proof:** INT-05 PASSED only vidra-to-vidra (`docs/evidence/a29-rehearsal-4.json`). No CI lane enables federation.
   - **Also missing:**
     - an instance actor and instance follows, PeerTube's main federation mechanism
     - inbound and outbound `Flag` (the `inbox.go:79` switch has no Flag case ✔)
     - migration of remote followers (no `Move`)
     - the `sensitive` flag in federated video objects
     - fetching a channel's back-catalogue when it is followed
   - **Context:** federation is off by default.
2. **Moderation gaps for a public instance.**
   - ✔ An instance-wide block of a remote account exists in the backend (`/admin/federation/blocked-actors`, `server.go:2087-2089`) but has no UI.
   - Moderators can't manage users or registrations; those routes are admin-only.
   - A ban carries no reason and sends the user no notice.
   - There is no reporter↔moderator messaging and no "My reports" page.
   - There is no bulk "remove all comments from this account".
   - Staff are notified only about `new_report`, not registrations, quarantine or follower requests.
   - There is no admin "create user".
3. ✔ **i18n.** The UI is English-only (`app/layout.tsx:86` hard-codes `lang="en"`; 46 keys extracted). PeerTube ships 63 locales.
4. **Notification emails.** There is no email for new videos or lives from subscriptions, for mentions or for comments. There are also no mention notifications at all.

## Tier 2: important gaps

**Creators**
- Audio uploads are refused by the allowlist (`internal/video/service.go:121-130`) even though the audio-only pipeline exists.
- There is no "internal" privacy level; the importer maps those videos to private (`peertubeimport/mapping.go:34`).
- PeerTube's support/donation text is dropped on import.
- There is no RTMPS and no scheduled lives.
- Creator stats lack watch time, retention, geography and devices.
- A video can't be moved to another channel and ownership can't be changed.
- There is no in-browser caption editor, and Whisper doesn't run automatically on upload.
- "My videos" has no search, filters or bulk actions.

**Viewers**
- Playlists have no play-all/watch mode, no tab on channel pages, no search and no embed.
- There is no comment approval queue.
- There is no remote-interaction/OStatus subscribe template.
- Users can't import a PeerTube account archive.

**Admins**
- There are no automatic tags and no held-for-review comments.
- Blocklist and watched-word subscriptions (v8.3) are missing.
- There is no LDAP/SAML, and OIDC is configured through env only.
- Blocking a video doesn't send a federated Delete.

**Protocols**
- There is no podcast RSS (no `<enclosure>`), no private-token subscription feed, and no Atom/JSON feeds.
- The embed has no JS player API and no URL options.
- There is no PeerTube-compatible REST/OAuth API, so the PeerTube app, NewPipe and Grayjay break.

**Large and deferred, not rejected**
- remote transcoding runners
- the web studio editor
- browser P2P (SCP-02)

## Rejected and staying rejected (cited)

- plugins/themes (`docs/platform-audit-2026-07.md:26,94`)
- torrent/magnet import and WebTorrent
- live latency modes (no P2P; `.ralph/specs/config-parity/ledger.md:67`)

## Where vidra is ahead

- **Upload quarantine** that holds a video before it publishes.
- **Admin mail provider UI.**
- **Owner model**, with owner recovery.
- **Storage migration campaigns, media GC** and `verify-blobs`.
- **Job traces.**
- **Search from vidra-search:** autosuggest and personalized recommendations.
- **Viewer features:** comment pin and heart, per-channel bell modes, the up-next queue, the sleep timer and audio tracks.
- **DMs** with E2EE.
- **ATProto** cross-posting and login.
- **IPFS mirror.**
- **PeerTube import** from the admin UI.

The per-domain detail is in Appendices A–D below. Those are the four agents' reports, edited only to remove scratch paths. Their rows without ✔ come from a static reading by one agent: re-grep before building on them. Ledgers in this repo have been wrong before (see `platform-audit-2026-07.md` §5).


---

## Appendix A. Media pipeline and creator tools

### PeerTube v8.3.1 vs vidra: video publishing and the media pipeline (creator side)

Read-only audit, 2026-10-12. PeerTube paths are relative to the v8.3.1 clone (`f0b0413`). Vidra paths are relative to `vidra-core/` (core) and `vidra-user/` (user), both at origin/main. Nothing was run.

#### 1. PeerTube inventory (this domain)

PeerTube's creator side has these parts:

- **Upload:** resumable uploads (uploadx) with total and daily quotas.
- **Import:** from URL/yt-dlp, torrent or magnet. An imports page lists them; the failed state and retry are new in 8.0, and the state filter in 8.3.
- **Channel sync:** sync is more reliable in 8.1, and 8.3 adds a per-sync default privacy.
- **Transcoding:** HLS plus web-video output, a 0p audio-only rung, fps caps, an original-resolution rung, keep-original, and merging an audio file into video (`.m4b` support new in 8.2).
- **Admin file controls:** re-transcode, delete variants or the source file, and cancel a job (cancel is new in 8.3).
- **Remote runners:** they take VOD, live, studio, transcription and storyboard jobs (storyboard runners are new in 8.0).
- **Studio editor:** cut, intro/outro and watermark, plus remove-segments (new in 8.2).
- **Captions:** upload, Whisper auto-transcription, and an in-browser segment editor (7.0).
- **Chapters:** set by hand, or extracted automatically from the description or the container.
- **Other video assets:** storyboards, thumbnails (png/webp new in 8.1), downloads and file replacement.
- **Privacy and publishing:** public, unlisted, private, internal and password privacy; scheduling and wait-for-transcoding; NSFW flags plus a summary (7.2); embed-domain restriction (8.1) and "nobody can embed" (8.3).
- **Ownership:** a better ownership-change UX (8.2), channel transfer (8.2), moving videos between channels (8.1) and channel collaboration (8.0).
- **Live:** normal and permanent lives, replay with its own privacy, latency modes, RTMPS, a live transcoding ladder, scheduled lives (7.3) and DVR (8.2).
- **Stats:** overall, timeseries, retention and user-agent stats (7.2), download stats (8.2) and date filters (8.3).
- **My Videos page:** redesigned in 7.2 with sort, paging and filters; a tag filter (8.2); bulk playlist and bulk metadata actions (8.3).

#### 2. Gap table

| Feature | PeerTube evidence | Vidra backend | Vidra frontend | Status | Severity | Note |
|---|---|---|---|---|---|---|
| Resumable chunked upload, quota/size checks, multi-file | `server/core/controllers/api/videos/upload.ts` | `internal/httpapi/server.go:1889-1897`, `internal/quota/service.go` | `components/studio/UploadSection.tsx:624,1126`; `BatchUploadQueue` `:1054` | PRESENT | – | Also `/me/uploads` + recovery card |
| **Studio "My videos" + public channel list** | `client/src/app/+my-library/my-videos` | `internal/httpapi/videos.go:1018-1031` (paginated, default 20 at `:671`) | `components/studio/MyVideosSection.tsx:56`, `components/ChannelView.tsx:57,79-81` | PARTIAL (**defect**) | **CRITICAL** | Both callers fetch page 1 with no limit/offset, so only the newest 20 videos per channel are listed (details in §3, item 1) |
| My-videos search/filter/sort/bulk (7.2, 8.2, 8.3) | same | list endpoint has `?sort` only | none | MISSING | IMPORTANT | No bulk delete, bulk playlist, bulk metadata or filters |
| URL import (direct + yt-dlp) with metadata prefill | `controllers/api/videos/import.ts` | `internal/httpapi/imports.go:82`, `internal/videoimport/service.go:522` | UploadSection (`api.importVideoFile`) | PRESENT | – | yt-dlp is OFF by default (`internal/config/config.go:1356`) |
| Torrent/magnet import | `import.ts` | none | none | REJECTED | – | `docs/platform-audit-2026-07.md:94`; `.ralph/specs/config-parity/ledger.md:41` |
| Imports page (list, state filter, retry, cancel) | `+my-library/my-video-imports`; `import.ts` `/imports/:id/retry` | per-video GET only (`imports.go:136`); auto-retry with backoff | per-video status only | PARTIAL | NICE | |
| Channel sync | `server/core/lib/sync-channel.ts` | `internal/channelsync/service.go`; `server.go:1948-1951` | `components/studio/ChannelManage.tsx:271` | PARTIAL | NICE | Always creates private drafts (`channelsync/service.go:44`); needs yt-dlp turned on |
| HLS ladder, web videos, fps cap, original-res rung, threads | `server/core/lib/transcoding/` | `internal/instancesettings/service.go:218-224`; `internal/transcode/service.go:55` | admin config | PRESENT | – | |
| Audio-file upload (mp3/m4a/flac/wav/m4b), podcasts | runner `vod-audio-merge-transcoding` (`packages/models/src/runners/runner-jobs/runner-job-type.type.ts`) | the pipeline handles audio-only sources (`internal/media/media.go:86`, `internal/media/cmaf.go:149`), but the upload allowlist is video containers only (`internal/video/service.go:121-130`) | same allowlist | PARTIAL | IMPORTANT | Only `.ogg` audio gets through. The RSS feed (`internal/httpapi/distribution.go:147`) has no enclosure or itunes tags |
| Hardware-accelerated transcoding | plugin only; Docker image gets `va-driver-all` (CHANGELOG 8.1) | `TRANSCODING_HW` vaapi/qsv/nvenc/videotoolbox (`config.go:1250,2569`) | env only | PRESENT | – | Vidra goes further here: it is built in |
| Admin re-transcode (HLS / web video) | `controllers/api/videos/transcoding.ts` | `server.go:2025` | `components/AdminVideosView.tsx:650-655` | PRESENT | – | No job cancel (8.3) |
| Delete HLS/web-video variants; delete source file | `controllers/api/videos/files.ts`, `source.ts` | none; delete-original deferred (`ledger.md:77`) | none | MISSING | NICE | |
| Remote runners (VOD/live/studio/transcription/storyboard) | `apps/peertube-runner`, `controllers/api/runners/` | none. `VIDRA_ROLE=worker` (`config.go:61-71`) is a trusted scale-out that needs DB and storage credentials | none | MISSING | IMPORTANT | Deferred "LATER" (`docs/platform-audit-2026-07.md:92`; `ledger.md:43-55`) |
| Studio editor (cut, intro/outro, watermark, remove-segments) | `controllers/api/videos/studio.ts`; `packages/models/src/videos/studio/video-studio-create-edit.model.ts` | none | none | MISSING | IMPORTANT | Deferred (`ledger.md:86`) |
| Caption upload/delete | `controllers/api/videos/captions.ts` | `server.go:1915-1918` | `components/CaptionsManager.tsx` | PRESENT | – | |
| Whisper auto-transcription | `server/core/lib/video-captions.ts:125` (runs on every new video and replay) | only on demand; the sole enqueue caller is `internal/httpapi/captions_auto.go:99` | CaptionsManager (`requestAutoCaption`) | PARTIAL | NICE | No "transcribe every upload" setting |
| Caption segment editor (7.0) | `.../shared-manage/captions/video-caption-edit-modal.component.ts` | none (replace by re-upload) | none | MISSING | IMPORTANT | Whisper output can't be corrected in the browser |
| Caption translation | none in PeerTube core | – | – | n/a | – | Not a parity gap |
| Chapters | `controllers/api/videos/chapters.ts`; auto-extraction at `lib/video-chapters.ts:45`, `job-queue/handlers/video-import.ts:220` | `server.go:1831-1832` | `components/ChaptersManager.tsx` | PARTIAL | NICE | Manual only; nothing taken from the description or container |
| Storyboards | `server/core/lib/storyboard.ts` | `internal/media/storyboard.go`; `server.go:1827-1828` | `components/player/SeekBar.tsx` | PRESENT | – | |
| Thumbnails (upload, frame pick, png/webp) | `.../common/thumbnail-manager.component.ts` | `server.go:1824` | `components/ThumbnailManager.tsx:105` | PRESENT | – | |
| Downloads (source, per-height, audio, subtitles) + per-video toggle | `server/core/lib/video-download.ts` | `server.go:1809-1814` | `components/DownloadButton.tsx` | PRESENT | – | |
| Replace video file | `.../shared-manage/replace-file/` | `internal/httpapi/replace.go`; `server.go:1882,1892` | `components/studio/VideoRow.tsx:351` | PRESENT | – | Default off (`video_replace_enabled`) |
| Privacy: public/unlisted/private/password | `packages/models/src/videos/video-privacy.enum.ts` | `internal/httpapi/videos.go:34` | VideoRow; `components/PasswordManager.tsx` | PRESENT | – | |
| Privacy: internal (logged-in users only) | same | none; the importer maps INTERNAL to private (`internal/peertubeimport/mapping.go:34-35`) | none | MISSING | IMPORTANT | Lossy migration for institutional instances |
| Scheduled publish | `video-schedule-update.model.ts` | `internal/video/service.go:1434` (`PublishDue`) | VideoRow, UploadSection | PRESENT | – | |
| Wait for transcoding | `waitTranscoding` | `videos.go:1087` | `UploadSection.tsx:1521` | PRESENT | – | |
| Manage form: category, licence, language, tags, comments, download, sensitive + reason | `video-create-update-common.model.ts` | `videos.go:1061-1083` | `VideoRow.tsx:71-153` | PRESENT | – | |
| Originally-published date | same | `videos.go:1074` | none (zero hits in user) | BACKEND-ONLY | NICE | Size S |
| Support text (video/channel) | same (`support`) | none | none | MISSING | NICE | Replaced by verified donation addresses; the PeerTube importer drops it |
| NSFW flags (violent/explicitSex) | `nsfw-flag.enum.ts` | boolean + reason only (`videos.go:1075-1079`) | VideoRow | PARTIAL | NICE | Viewer-policy side belongs to the other agent |
| Comments policy "requires approval" | same | deferred (`internal/video/service.go:592-597`) | – | PARTIAL | NICE | Straddles moderation |
| Move a video to another channel | `channelId` on update; 8.1 editors, 8.3 admin picker | none (no `channel_id` in `updateVideoRequest`) | none | MISSING | IMPORTANT | Uploading to the wrong channel means deleting and re-uploading |
| Video ownership change (give/accept/refuse) | `controllers/api/videos/ownership.ts`; `+my-library/my-ownership-changes` | none (`/admin/owner/transfer` is the instance-owner role) | none | MISSING | IMPORTANT | |
| Channel transfer (8.2) | `controllers/api/video-channels/ownership.ts` | none | none | MISSING | NICE | |
| Channel collaboration (editors, 8.0) | `video-channels/video-channel-collaborators.ts` | `internal/httpapi/channel_members.go:86` | `components/studio/CollaboratorsCard.tsx` | PRESENT | – | Invitation flow not compared |
| Quotas, total + daily | `config/default.yaml` user quotas | `internal/httpapi/quota.go:44-47`; `instancesettings/service.go:291` | `components/StudioStorageCard.tsx` | PARTIAL | NICE | No per-user daily override (`internal/httpapi/admin_users.go:40` covers total only) |
| Live: normal/permanent, replay, key, end, viewer count | `controllers/api/videos/live.ts` | `internal/httpapi/live.go:23-27,91`; `server.go:2354-2383` | `components/LiveStreamsSection.tsx:123-128` | PRESENT | – | |
| Live scheduling (7.3) | live `schedules` | none | none | MISSING | IMPORTANT | |
| Live transcoding ladder | `server/core/lib/live/` | passthrough nginx-rtmp, deferred (`ledger.md:135`) | – | MISSING | IMPORTANT | Viewers get only the ingest bitrate |
| RTMPS ingest | `config/default.yaml:851` | none | none | MISSING | IMPORTANT | Stream key travels in cleartext |
| Live latency modes | `config/default.yaml:834` | – | – | REJECTED | – | N/A, no P2P (`ledger.md:67`) |
| Live DVR (8.2) | `config/default.yaml:828` | deferred (`ledger.md:141`) | – | MISSING | NICE | |
| Replay privacy, session history | `replaySettings`; `/live/:id/sessions` | the replay inherits the stream's privacy (`internal/live/service.go:728-732`) | – | PARTIAL | NICE | |
| Creator stats | `controllers/api/videos/stats.ts`; `packages/models/src/videos/stats/` | views/likes/dislikes/comments + 30-day daily views (`internal/httpapi/stats.go:15-36`) | `components/studio/AnalyticsView.tsx:356` | PARTIAL | IMPORTANT | No watch time, retention, peak viewers, countries/regions, devices/clients/OS, downloads or date range |
| Move to object storage | `server/core/lib/move-storage/` | instance-wide storage migrations (`server.go:2021`) | `components/StorageMigrationControls.tsx` | PRESENT | – | Different shape: the whole instance moves, not one video |
| Account archive including media | `server/core/lib/user-import-export/` | metadata only (`api/openapi.yaml:3036-3045`) | settings | PARTIAL | NICE | Straddles another domain |

#### 3. Top gaps, ranked

1. **Channel video list capped at 20 (CRITICAL, S).** This is a regression, not missing parity. Core commit `56d5af0` (2026-08-25) paginated `/channels/{handle}/videos`, but `vidra-user` still calls it with no `limit` or `offset`. The effects:
   - The Studio content list stops at the newest 20 videos.
   - The public channel page's "Load more" is a client-side reveal of those same 20.
   - The channel page's "Oldest" sort reorders those 20 rather than fetching the oldest videos.

   Creators with 21 or more videos lose the manager, and viewers lose the back catalogue. Follow-ups are search, filters and bulk actions (M).
2. **Live maturity (IMPORTANT).** Scheduled lives (S–M) and RTMPS (S–M, infra) are cheap. A live transcoding ladder (L) is what makes live watchable on weak connections.
3. **Creator analytics depth (IMPORTANT, M–L).** PeerTube creators lose watch time, retention, geography and devices. The 2026-07 audit already queued a watch-position beacon for this.
4. **Audio-file uploads (IMPORTANT, S).** The audio-only HLS/CMAF path already exists, so this mostly means widening the allowlist and the `accept` attribute. A podcast RSS feed is a follow-up (M).
5. **Move a video to another channel, plus ownership transfer (IMPORTANT, S then M).** This is a common fix-a-mistake or hand-over job, and there is no workaround short of re-uploading.
6. **Internal privacy (IMPORTANT, M).** Institutional PeerTube instances depend on it, and the importer silently downgrades these videos to private. The visibility check spans feeds, search and federation.
7. **Caption segment editor (IMPORTANT, M).** On-demand Whisper output is only useful if it can be corrected.
8. **Studio editor (IMPORTANT, L)** and **remote runners (IMPORTANT, L).** Both are documented as deferred, not rejected. `VIDRA_ROLE=worker` and built-in hardware acceleration soften the runner gap only for trusted hosts.

#### 4. Things vidra does that PeerTube doesn't

- Optional HEVC and AV1 renditions in CMAF, with DASH (`internal/config/config.go:386-400`).
- Built-in hardware acceleration: VAAPI, QSV, NVENC and VideoToolbox.
- ClamAV scan gate plus a moderator quarantine queue for uploads.
- ClearKey DRM.
- A one-shot PeerTube instance importer.
- An IPFS mirror.
- Verified crypto donation addresses.
- Per-channel ATProto cross-posting.
- An upload-session list with browser-restart recovery.
- `VIDRA_ROLE` api/worker split.

#### 5. Unknowns

- **Nothing was run.** Every status comes from reading code. yt-dlp import, channel sync (which needs `YTDLP_IMPORT_ENABLED`), Whisper and the live replay pipeline were not exercised. The channel-list defect is inferred from code and not reproduced against a live stack.
- **CMAF audio-only listening mode.** I did not check whether the player exposes the separate audio track as an audio-only option (PeerTube's 0p rung equivalent).
- **Collaboration and live viewer counts.** I did not compare the channel-collaboration invitation/acceptance flow or the accuracy of live viewer counts.
- **v8.3.1 security fixes.** They are undisclosed, so any that touch upload or import paths can't be assessed.

---

## Appendix B. Viewer and social experience

### Viewer & social experience: PeerTube v8.3.1 vs vidra (audit 2026-10-12)

Path conventions: `PT/` is the PeerTube clone root. `core/` is `vidra-core`, `user/` is `vidra-user`, and `meta/` is the vidra meta repo. All three vidra repos were read at their origin/main heads (core 368883a, user adaa149).

#### 1. PeerTube domain inventory

PeerTube's viewer surface has these parts:
- **Player.** A video.js player with quality, speed (up to 3x since v8.1), captions, chapters, storyboard previews, theater mode, hotkeys, up-next, loop, "stats for nerds", copy-URL-at-time, P2P (p2p-media-loader) and `?start=/?stop=` links. It also has a searchable transcript widget and a playlist watch widget.
- **Discovery.** Browse with local/federated scope, language/category/live filters and recent/trending/hot/likes/views/original-date/name sorts. There is a Discover overview by category, tag and channel, and an optional global search index (SepiaSearch). Local search covers videos, channels and playlists, with filters.
- **Accounts and channels.** Account and channel pages carry banners, avatars and free-text "support" text. Channels have playlists.
- **Subscriptions.** You can subscribe to local or remote channels, there is a subscription feed, and a personal RSS feed token is available.
- **Playlists.** Watch Later, public/unlisted/private privacy, reordering, per-element start/stop times and playlist embeds.
- **Comments.** Markdown comments with mentions, nested threads, an enabled/disabled/requires-approval policy and a held-comments queue.
- **Engagement and account.** Likes/dislikes; notifications (32 types, each set to web and/or email); watch history (pause, clear, delete, search, resume); the four-mode NSFW policy plus per-flag settings; a video-language filter; themes; signup with approval and email verification; 2FA; account export/import archives; deletion; user-level mutes; abuse reports with a "my reports" page and moderator messaging; remote interaction (`/remote-interaction`, OStatus template); 63 UI locale catalogs; an Angular service worker.

**New since v7.3:**
- v8.0: player redesign with Lucide/Galaxy themes, set per instance, channel or video through the new `player-settings` API. Notifications redesigned. Channel collaboration.
- v8.1: 3x speed and the `g l` hotkey. Notifications grouped by date.
- v8.2: flip/mirror video, rate and resolution remembered across sessions, `g p` hotkey, Korean and Romanian locales.
- v8.3: a paginated comment-replies endpoint, `host-meta` for remote subscribe, new-device login email and account lockout, transcript-widget refinements, and "nobody can embed".

#### 2. Gap table

| Feature | PeerTube evidence | Vidra backend | Vidra frontend | Status | Severity | Note |
|---|---|---|---|---|---|---|
| Core player: quality, speed, captions + language, audio track, chapters, storyboard, theater, PiP, hotkeys, autoplay-next/end card | `PT/client/src/standalone/player/src/shared/{control-bar,hotkeys,upnext,resolutions}` | `/videos/{id}/chapters`, `storyboard.vtt`, `/me/player-settings` (`core/internal/httpapi/player_settings.go:17-22`) | `user/components/player/VideoPlayer.tsx:206-211,845-900,944-1006`; `EndCard.tsx`; `UpNextQueue.tsx` | PRESENT | — | Speed goes up to 4x. Per-user defaults are persisted. |
| Start-at `?t=`, share at time, embed snippet, download | `PT/.../peertube-player.ts:569-584` | `/videos/{id}/download/*` | `user/lib/start-time.ts:13`; `ShareButton.tsx:115`; `DownloadButton` | PRESENT | — | |
| Stop-at, loop, embed URL options (autoplay/muted/loop/title/controls), embed JS API | `PT/.../peertube-player.ts:563`; `PT/client/src/standalone/embed-player-api/player.ts` | none | `user/components/EmbedPlayer.tsx:64` (`?t=` only) | MISSING | NICE | |
| Stats-for-nerds overlay | `PT/.../shared/stats/stats-card.ts`; `peertube-player.ts:596` | admin QoE only | none | MISSING | NICE | |
| Mirror/flip video (v8.2) | `PT/.../video-filter/video-filter-menu-button.ts:21` | — | none | MISSING | NICE | |
| P2P toggle and info | `PT/.../p2p-media-loader/`; `UserUpdateMe.p2pEnabled` | none | none | MISSING (deferred) | NICE | Deferred, not rejected: `meta/docs/release-readiness.md:1140` (SCP-02). |
| Player theme per instance/channel/video (v8) | `PT/server/core/controllers/api/player-settings.ts:24-52` | none (vidra's player-settings are per-viewer defaults) | none | MISSING | NICE | Cosmetic and creator-owned. |
| Transcript widget | `PT/client/src/app/+video-watch/shared/player-widgets/video-transcription.component.ts` | captions exist | none | MISSING | NICE | |
| Markdown and clickable URLs in descriptions, comments, channel descriptions and bios | `PT/client/src/app/core/renderer/markdown.service.ts:66-107`, `linkifier.service.ts` | raw text stored | `WatchView.tsx:647-655`, `CommentsSection.tsx:923`, `ChannelView.tsx:196-199`: plain text, only timestamps become links | PARTIAL | **CRITICAL** | Imported PeerTube descriptions show literal `[x](url)` and no URL is clickable. `components/Markdown.tsx` exists but only renders instance documents. |
| Browse: local/all scope, category/language/tag filters | `PT/.../video-filters.model.ts:33-45` | `/api/v1/videos` (sort/scope/tag/category/language) | `app/page.tsx`, `FeedFilters`, `FeedScopeToggle` | PRESENT | — | |
| Hot/likes/original-date/name sorts, live filter, Discover overview | `PT/.../select-videos-sort.component.ts:48-65`; `PT/server/core/controllers/api/overviews.ts` | sort enum is recent, popular, trending only; no overview endpoint | `FeedSortTabs.tsx:8-11` | PARTIAL | NICE | The home rails and recommendations partly replace Discover. |
| Search: videos with duration/date/category/licence/language/tags filters; channel and account search; remote URI/handle lookup | `PT/client/src/app/+search/search-filters.component.ts`; `PT/server/core/controllers/api/search/` | `/videos/search`, `/search/channels`, `/search/accounts`, `search_remote.go:1-16` | `SearchFilters.tsx:133-227`, `SearchResults` | PRESENT | — | No live, NSFW or host filters. |
| Playlist search; global search index (SepiaSearch) | `PT/.../search/search-video-playlists.ts`; `PT/config/default.yaml:1298` (default off) | none | none | MISSING | NICE | |
| Channel page: banner, avatar, about, follow, bell | `PT/client/src/app/+video-channels` | `core/internal/httpapi/channels.go:49-83` | `ChannelView.tsx` | PRESENT | — | |
| Channel playlists tab, account videos tab, search inside a channel | `PT/.../+video-channels/video-channel-playlists`; `+accounts/account-videos` | playlists are user-owned only (`migrations/0019`) | `ChannelView.tsx:271-272` says the tab is absent; `UserProfileView.tsx:49` shows channels and about only | MISSING | IMPORTANT | |
| Support text on channels and videos | `PT/packages/models/src/videos/channel/video-channel.model.ts:39`, `video.model.ts:123` | no column; the importer drops it | `SupportButton` shows crypto addresses only | MISSING | IMPORTANT | Liberapay/Patreon text is lost on migration. |
| Subscribe, per-channel bell, remote-channel follow | `PT/.../shared-user-subscription/` | `/channels/{h}/follow[/notifications]`, `/me/remote-follows` | `FollowButton`, `FollowBell`, `RemoteFollowsSection` | PRESENT | — | Remote follows need federation, which is off by default. |
| **List surfaces show only the first page**: subscription feed, history, Watch Later, my playlists, playlist items, notifications | `PT/server/core/controllers/api/users/{my-subscriptions,my-history,my-notifications}.ts` | paginated (default 20, `core/internal/httpapi/videos.go:671`; `playlists.go:197`) | `SubscriptionsView.tsx:47-48`, `WatchHistoryView.tsx:43`, `LibraryView.tsx:331`, `PlaylistsView.tsx:40`, `PlaylistDetailView.tsx:34`, `NotificationsView.tsx:228`: no limit and no pager | PARTIAL | **CRITICAL** | Only 20 items are reachable. Reordering a playlist with more than 20 items sends only 20 ids, which the server rejects (`internal/playlist/service.go:234`). The owner check at `PlaylistDetailView.tsx:44` only sees the first 20 playlists. |
| Subscription list management | `PT/client/src/app/+my-library/my-follows/my-subscriptions.component.ts` | `GET /me/subscriptions` (paginated) | only `SidebarFollowing.tsx:41` (limit 15) | PARTIAL | IMPORTANT | |
| Remote interaction (follow/comment from your home instance, OStatus template, `/remote-interaction`) | `PT/client/src/app/+remote-interaction`; `PT/server/core/controllers/well-known.ts:125` | none (WebFinger `federation.go:149` has no subscribe template) | none | MISSING | IMPORTANT | Depends on federation. |
| Personal subscription RSS (feed token) | `PT/client/src/app/+my-account/my-account-applications` | `/feeds/videos.xml` covers instance and channel only (`server.go:1511`) | none | MISSING | NICE | |
| Playlists: CRUD, privacy, reorder, cover, Watch Later | `PT/server/core/controllers/api/video-playlist.ts` | `migrations/0019`, `0016_saved_videos` | `PlaylistsView`, `PlaylistDetailView`, `SaveButton` | PRESENT | — | Truncated; see the list-surfaces row. |
| Playlist watch mode (play all, next in playlist, `playlistPosition`) | `PT/.../player-widgets/video-watch-playlist.component.ts` | none | none (only an ad-hoc queue) | MISSING | IMPORTANT | |
| Per-element start/stop; playlist embed | `PT/packages/models/src/videos/playlist/video-playlist-element.model.ts:15-16` | none | `/embed/[id]` is video-only | MISSING | NICE | |
| Comments: reply, edit, delete, mute/report author | `PT/server/core/controllers/api/videos/comment.ts` | `server.go:1922-1931` | `CommentsSection.tsx` | PARTIAL | IMPORTANT | One fetch with limit 100 (`CommentsSection.tsx:102`) and no "load more", so older comments are unreachable. Newest-first only. |
| Comment policy enabled/disabled | `comment.ts` | `migrations/0089_video_publish_policies.up.sql` | `WatchView.tsx:661` | PRESENT | — | |
| Requires-approval policy and held-comments queue | `comment.ts` (`/approve`); `PT/.../+my-library/comments-on-my-videos` | deferred (`migrations/0089:5-9`; SCP-09) | none | MISSING | IMPORTANT | |
| Mentions and mention notifications | `PT/packages/models/src/users/user-notification.model.ts` (`COMMENT_MENTION`) | none | a "Replying to @x" chip only | MISSING | IMPORTANT | |
| Like/dislike | `PT/server/core/controllers/api/videos/rate.ts` | `/videos/{id}/rating` | `RatingControls` | PRESENT | — | |
| Notifications: in-app list, per-type on/off | `PT/client/src/app/+my-account/my-account-notifications` | `core/internal/notification/service.go:22-57` (11 types) | `NotificationsView`, `NotificationPrefsView.tsx:19` | PRESENT | — | |
| Email notifications per type; missing types (new live from subscription, abuse message, published/imported) | `PT/packages/models/src/users/user-notification-setting.model.ts` | `core/internal/mail/composer.go:180-423`: transactional mail plus staff report alerts only | in-app toggles only | MISSING | IMPORTANT | |
| Watch history: pause, clear, delete entry, resume | `PT/server/core/controllers/api/users/my-history.ts` | `/me/history[/{id}]`, `history_enabled`, `/watch-progress` | `WatchHistoryView.tsx:48-124`, `SettingsView.tsx:141` | PRESENT | — | No search inside history. Truncated (see above). |
| NSFW display/warn/blur/hide | `PT/packages/models/src/videos/nsfw-policy.type.ts` | `migrations/0100_granular_sensitive.up.sql` | `ContentSettingsView.tsx:20-23` | PRESENT | — | |
| Per-flag NSFW policy (violent/explicit); video-language filter | `PT/packages/models/src/videos/nsfw-flag.enum.ts`; `PT/packages/models/src/users/user-update-me.model.ts` | none | none | MISSING | NICE | |
| i18n | `PT/client/src/locale` (63 catalogs) | n/a | `user/lib/i18n/en.ts` (46 keys, used in 13 of 370 files); `app/layout.tsx:86` hard-codes `lang="en"` | MISSING | **CRITICAL** | Retained, not rejected (`release-readiness.md:1145`, SCP-07). |
| Theme | `user-update-me.model.ts` (`theme`) | — | `ThemeToggle.tsx:14-25` (light/system/dark) | PRESENT / REJECTED | — | Plugin themes are rejected (`meta/docs/platform-audit-2026-07.md:94`). |
| Signup (approval note, email verification, age); login (password, OIDC, ATProto); TOTP and recovery codes; reset; email change; deletion | `PT/client/src/app/+signup`, `+login`, `PT/server/core/controllers/api/users/two-factor.ts` | `api/openapi.yaml:417-1952`; `DELETE /auth/me` | `SignupForm.tsx:42-135`, `components/auth/*` | PRESENT | — | |
| New-device login email, account lockout (v8.3) | `PT/CHANGELOG.md` v8.3.0 | none | — | MISSING | NICE | |
| Account export/import | `PT/server/core/lib/user-import-export/{exporters,importers}` | `/me/export`, `/me/import`; `core/internal/account/archive.go:21-25` (no media); `import.go` restores profile, playlists, local follows and prefs only | `AccountDataSection` | PARTIAL | IMPORTANT | Cannot ingest a PeerTube archive. Remote follows, likes, blocklist and history are skipped. |
| Mute/block accounts and instances | `PT/server/core/controllers/api/users/my-blocklist.ts` | `/me/mutes/*`, `/me/blocks*` | `app/settings/{mutes,blocks}` | PRESENT | — | |
| Report a video, comment or account | `PT/packages/models/src/moderation/abuse/abuse-create.model.ts:6-15` | `server.go:2032-2034` | `ReportButton.tsx:93-161` | PARTIAL | NICE | Free text only. No predefined reasons or timestamp range. |
| "My reports" page and reporter-moderator messaging | `PT/server/core/controllers/api/users/my-abuses.ts`; `PT/server/core/controllers/api/abuse.ts` (`/:id/messages`) | none | none | MISSING | IMPORTANT | |
| PWA and accessibility | `PT/client/src/ngsw-config.json` | — | `app/manifest.ts`, no service worker; `e2e/a11y.spec.ts` (axe) | PARTIAL | NICE | |

#### 3. Top gaps, ranked

1. **List surfaces stop at the first page (CRITICAL, S–M).** Subscriptions, history, Watch Later, playlists, playlist items and notifications each stop at 20 items, and comments stop at 100. Playlist reordering breaks above 20 items. A migrated PeerTube user silently loses access to their own library. The `ListTail`/`LoadMoreButton` seam already exists, and the fix belongs in that one shared seam, not at each call site.
2. **No rendering of user text (CRITICAL, S).** Every imported PeerTube description is markdown, and none of it renders. Clickable links in descriptions are table-stakes for a video platform. The fix is to sanitize and linkify through the existing `Markdown` component together with `TimestampedText`.
3. **i18n (CRITICAL, L).** The UI is English-only, with 46 extracted keys. A French or German PeerTube instance's viewers would lose their interface language.
4. **Email notifications and missing notification types (IMPORTANT, M).** This covers new videos and lives from subscriptions, mentions, and comments on your videos. Email is PeerTube's main channel for bringing users back, and vidra has no mail path for it.
5. **Playlist parity (IMPORTANT, M–L).** No play-all/watch mode, no channel or account playlist listing, no playlist search or embed. Playlists can be stored but not consumed as playlists.
6. **"My reports" and moderator messaging (IMPORTANT, M).** Reporters get only a resolved notification. There is no status page and no two-way thread.
7. **Comment approval queue and mentions (IMPORTANT, M).** Approval is deferred in migration 0089. Without it, creators who relied on "requires approval" have to fall back to disabling comments.
8. **Remote interaction (IMPORTANT, M).** Fediverse users can't follow a vidra channel from their home server. This also depends on federation proving out (INT-05 is currently FAIL). *[Orchestrator correction: stale. INT-05 PASSED vidra↔vidra on 2026-09-09 (`docs/evidence/a29-rehearsal-4.json`); it has never been run against PeerTube or Mastodon.]*
9. **Support text (IMPORTANT, S).** It is a dropped import column and a missing viewer affordance.
10. **Account archive import of PeerTube archives and remote follows (IMPORTANT, L).** Per-user migration is impossible. Only the operator-level instance importer exists.
11. **Channel playlists and account videos tabs, and a full subscription list (IMPORTANT, S–M each).**

#### 4. What vidra has that PeerTube doesn't (this domain)

- Comment pin and creator heart, plus reply notifications.
- Per-channel bell modes.
- A viewer-built up-next queue.
- A sleep timer, ambient mode and audio-track switching. Speed goes up to 4x.
- Search from vidra-search: autosuggest, search history and personalized home recommendations.
- A Continue-watching rail.
- Restricted mode.
- Verified crypto donation addresses.
- 1:1 DMs with optional E2EE.
- Short `/v/{code}` URLs.
- Video-card hover previews.
- TOTP recovery codes, "sign out everywhere" and Bluesky (ATProto) login.

#### 5. Unknowns

- I checked runtime behaviour statically only. I did not run a browser. Autoplay-next navigation, PiP and chapter UX are supported by code and mocked tests, not by live playback.
- Federated features (remote follows, remote comments, remote URI search) are gated by `FEDERATION_ENABLED`, which defaults to off, and INT-05 is a measured FAIL *[orchestrator correction: stale. It PASSED vidra↔vidra on 2026-09-09; it is unproven only against non-vidra software]*. I counted them PRESENT on code, not on proof.
- Live-viewer features (DVR seeking, new-live notifications, live chat) overlap the media agent's domain and were not audited deeply.
- I couldn't assess accessibility depth beyond the axe e2e specs. There is no screen-reader or VPAT evidence.
- I don't know which PeerTube transcript-widget behaviours landed in v7.x versus v8.x. Only the v8.3 refinements are certain.
- Mobile/PWA install on iOS was not exercised.

---

## Appendix C. Instance administration, moderation and operations

### 3: Instance administration, moderation and operations (PeerTube v8.3.1 vs vidra)

Path abbreviations: **PT** = PeerTube clone (`develop` f0b0413, labelled 8.3.1); **S** = `vidra-core/internal/httpapi/server.go`; **c/** = `vidra-core/`; **u/** = `vidra-user/` (u/components/... unless noted). vidra heads checked: core 368883a, user adaa149.

#### 1. PeerTube inventory (this domain)

PeerTube's admin has these areas:

- **Config**: 8 pages (information, general, homepage, customization, logo, VOD, live, advanced). They cover signup, quotas, defaults, imports, auto-block, followers, broadcast, search, theme/email strings and custom CSS/JS.
- **Overview**: users (create, edit, ban with a reason, resend verification), admin videos (file deletion, run transcoding) and comments.
- **Moderation**: abuse reports (state workflow, internal note, **reporter↔moderator messages**, predefined reasons, federated `Flag`), video blocks (with unfederate), registration requests, watched-word lists (server and per-account), automatic-tag policies, and the instance account/server blocklists.
- **Follows and redundancy.**
- **System**: jobs (pause/resume/cancel), server and audit logs, debug, remote runners (tokens, runners, jobs).
- **Plugins.**
- **Plumbing**: `/server/stats`, OTel/Prometheus, and the `server/scripts` CLI.

**New since v7.3:**

- v8.0: resend-verification button.
- v8.2: bulk actions on abuses, video blocks and registrations, plus mute badges and filters.
- v8.3:
  - **Blocklist subscriptions** with a public log, **watched-word subscriptions**, and auto-tag policy **auto-block videos**.
  - An internal note on video blocks, cancelling a local transcoding job, and bulk metadata/channel moves.
  - Moderators can no longer change roles.
- develop only: `video_file.lifecycle` pruning, which is in `config/default.yaml:954` but not in the CHANGELOG.

`oauth-clients.ts` is not a management feature. It only has `GET /local` (PT `server/core/controllers/api/oauth-clients.ts:15`), which returns the web client's credentials.

#### 2. Gap table

| Feature | PeerTube evidence | Vidra backend | Vidra frontend | Status | Sev | Note |
|---|---|---|---|---|---|---|
| Instance info/about (name, descriptions, terms, CoC, moderation info, admin, creation reason, maintenance, business model, hardware, country, languages, categories, support, social, NSFW) | PT client `+admin/config/pages/admin-config-information.component.html` | S:2272-2277; c/internal/instancesettings/service.go (124 keys) | AdminInstanceConfigView.tsx:116 auto-renders every server key; `app/about/instance/*` | PRESENT | — | Includes reset-to-default and validation. |
| Signup modes (open/approval/closed, email verification, limit, minimum age) | general page; `users/registrations.ts:70` | settings `registration_*`; S:1664-1666 | AdminRegistrationRequestsView.tsx:186,205 | PARTIAL | NICE | No bulk accept/reject (v8.2), no request delete, admin-only. |
| User and publish defaults, imports, channel sync, storyboards, transcription, file replace, user import/export | general page | instancesettings keys | config UI | PRESENT | — | |
| VOD transcoding config | `admin-config-vod` | `transcoding_*` keys | config UI | PRESENT | — | profile, HLS/web toggles and runners are ledger N/A (`.ralph/specs/config-parity/ledger.md:51,73,75`). |
| Live config | `admin-config-live` | `live_*` keys | config UI | PARTIAL | NICE | The live transcoding ladder and DVR are deferred (ledger §12, creator domain). |
| Broadcast message, contact form | general/information | `broadcast_*`, `contact_form_enabled`; S:1535 | InstanceBanner.tsx:11; InstanceContactModal.tsx:9 | PRESENT | — | |
| Custom homepage | `custom-page.ts` | S:1542-1546 | AdminInstanceConfigView.tsx:611; `app/page.tsx:77` | PARTIAL | NICE | Markdown only. No custom-markup blocks (video/playlist/channel embeds). |
| Custom CSS/JS, logos, avatar, banner, opengraph | customization/logo | S:1543-1546,1765-1773 | AdminInstanceConfigView.tsx:622,633; InstanceBrandingManager.tsx:48 | PRESENT | — | |
| Theme colours | `theme.customization.*` | `theme_primary_color` only | config UI | PARTIAL | NICE | PeerTube has about 10 colour tokens; vidra has custom CSS as a workaround. |
| Email strings / HTML templates | customization | `email_subject_prefix`, `email_body_signature`; admin mail config S:2242-2256 | AdminEmailConfigView.tsx:185 | PARTIAL | NICE | Mail is plaintext; HTML templates are deferred (ledger §14). |
| SSO-only login redirect (`redirectOnSingleExternalAuth`) | general page | none | none | MISSING | NICE | |
| Global search index (Sepia), auto-follow-index | general page | none | none | MISSING | NICE | Deferred (ledger §11, §15). |
| Roles and moderator rights | PT `packages/core-utils/src/users/user-role.ts` | admin/moderator/user plus owner flag | RoleGate | PARTIAL | IMPORTANT | PeerTube moderators have MANAGE_USERS and MANAGE_REGISTRATIONS. In vidra, `/admin/users*` and registrations are **admin-only** (S:2173, S:1664). |
| Admin user edit (role, quota, verified, bypass auto-block, delete, reset password) | `users/index.ts` | S:1675,2173-2185; admin_users.go:134 | AdminUsersView.tsx:129,477,494,1021 | PRESENT | — | Adds MFA removal and ownership transfer. |
| Create user from admin | `users/index.ts:123` | none (openapi has only get/patch on `/admin/users`) | none | MISSING | IMPORTANT | Closed instances can't hand out accounts. Approval mode is the only workaround. |
| Ban with reason, and email to the user | `users/index.ts:373-385` | `is_active` only; sessions revoked at c/internal/admin/service.go:209 | AdminUsersView.tsx:957 | PARTIAL | IMPORTANT | No reason and no notice to the user (relevant to the DSA "statement of reasons" duty). |
| Per-user daily quota, admin resend-verification, bulk user actions | user-edit/list | instance-wide daily default only | none | MISSING | NICE | |
| Abuse reports (video/comment/account), accepted/rejected with internal note, delete | `abuse.ts` | S:2032-2038; c/internal/moderation/service.go:29-35,257 | ModerationQueue.tsx:313,328 | PRESENT | — | Also covers DM and remote-video reports. |
| **Reporter↔moderator messages, and "My reports"** | `abuse.ts:87-95`; `users/my-abuses.ts` | none | none | MISSING | IMPORTANT | The reporter only gets a `report_resolved` notification. |
| Predefined reasons, timestamps, type/reason filters | `packages/models/src/moderation/abuse/abuse-reason.model.ts` | free text; status filter only (reports.go:229) | ReportButton.tsx:146 | PARTIAL | NICE | |
| **Federated reports (`Flag` in and out)** | `lib/activitypub/process/process.ts:39` | no Flag case in c/internal/federation/inbox.go:79 | none | MISSING | CRITICAL | Fediverse users can't report vidra content, and vidra reports never reach origin admins (overlaps the federation domain). |
| Video block/unblock with reason, owner notified | `videos/blacklist.ts` | S:2040-2042; videos.go:1842 | BlockedVideosView.tsx:83; VideoActionsMenu.tsx:137 | PRESENT | — | |
| Unfederate on block | `lib/video-blacklist.ts:261` | handleBlockVideo purges CDN and search only; sends no AP Delete | none | MISSING | IMPORTANT | Remote instances keep the title and thumbnail of a blocked video. |
| Block internal note (v8.3), bulk unblock/delete (v8.2) | video-block-list | none | none | MISSING | NICE | |
| Auto-block new users' videos, per-user bypass | `autoBlacklist` config | `quarantine_new_uploads`; S:2050-2052 | QuarantineQueueView.tsx:86 | PRESENT | — | Vidra holds the video before it publishes. |
| Admin comments list and delete | `+admin/overview/comments` | S:1932; comments.go:276 | AdminCommentsView.tsx:94 | PRESENT | — | |
| **Bulk remove all comments of an account** | `bulk.ts:12` | none | none | MISSING | IMPORTANT | Spam-wave cleanup. Abuse/block/registration bulk actions are also missing. |
| Held-for-review comments (auto-tag REVIEW_COMMENT) | `automatic-tag-policy.enum.ts` | none (ledger §13 deferred; migrations/0089) | none | MISSING | IMPORTANT | |
| Automatic tags and policies (external-link, list tags, auto-block video in v8.3) | `automatic-tags.ts`; `lib/automatic-tags/` | none | none | MISSING | IMPORTANT | |
| Watched-word lists | `watched-words.ts` | one instance list, flag-only (S:2164-2168; watchword/service.go:1-7) | WatchedWordsView.tsx:70; WatchedWordMatchesView.tsx:213 | PARTIAL | NICE | No named or per-account lists. |
| Watched-word subscriptions (v8.3) | `lib/watched-words-subscriptions.ts` | none | none | MISSING | NICE | |
| Instance server blocklist | `server/server-blocklist.ts` | S:2070-2072 (moderator allowed) | AdminInstancesView.tsx:94 | PRESENT | — | |
| **Instance account blocklist (remote accounts)** | `instance-account-blocklist.component.ts` | S:2087-2089 | none: BlockedRemoteAccountsView is viewer-scoped (`app/settings/blocks/remote`) | BACKEND-ONLY | CRITICAL | A moderator has to defederate a whole server or call the API by hand. |
| Local account "muted by instance" (hide without banning), in-context mod menus | same | none (deactivate only) | AccountModerationMenu is personal only | MISSING | NICE | |
| Blocklist subscriptions and public log (v8.3) | `lib/blocklist-subscriptions.ts`; `server-blocklist.ts` | none | none | MISSING | IMPORTANT | |
| Jobs UI | `jobs.ts:26` (pause/resume/cancel) | S:2261-2266, GET only | AdminJobRunsView.tsx:178 | PARTIAL | NICE | Read-only, but richer traces than PeerTube. |
| Logs | `server/logs.ts` | audit log S:2217; no server-log API | AdminAuditLogView.tsx:69 | PARTIAL | NICE | `vidra logs` CLI covers server logs. |
| Debug/system | `server/debug.ts` | S:2232,2236 | AdminSystemStatusView.tsx:128 | PRESENT | — | |
| Remote runners | `controllers/api/runners/*` | none; `VIDRA_ROLE` worker split (c/internal/config/config.go:1201) | none | PARTIAL | IMPORTANT | Workers need DB and storage access, and there are no tokens or admin UI. Platform audit lists this as LATER, not rejected. |
| Server stats | `server/stats.ts` | admin-only, 5 counters (S:2188; admin_stats.go:15-26) plus nodeinfo | AdminOverview.tsx:126 | PARTIAL | NICE | |
| Metrics | `lib/opentelemetry` | Prometheus S:1460; OTel tracing observability/otel.go | — | PRESENT | — | |
| Staff notifications (registration request, new user, auto-blocked video, instance follower, new version) | `user-notification.model.ts` | only `new_report` (c/internal/notification/service.go:62) | AdminConsole.tsx:79 pending-count badge (pull only) | PARTIAL | IMPORTANT | Approval queues stall unseen. |
| Follows/followers/redundancy admin | `server/follows.ts`, `redundancy.ts` | channel follower requests only (S:2139-2141); no instance actor | AdminFederationFollowerRequestsView.tsx:98 | PARTIAL | — | Federation agent's call. |
| Admin video list and file management | `videos/files.ts`, `transcoding.ts` | S:2025,2039 | AdminVideosView.tsx:650 | PARTIAL | NICE | No per-rendition delete, transcode cancel, or bulk metadata/channel move (v8.3). |
| Storage move and prune | scripts `create-move-*`, `prune-storage` | S:2002-2021 | StorageMigrationControls.tsx:175; AdminMediaView.tsx:80 | PRESENT | — | Stronger than PeerTube. |
| CLI tooling | `server/scripts/*` | cmd/api/main.go:120-131 (migrate, verify-blobs, owner-recovery); cmd/vidra (setup/doctor/logs/backup/...) | — | PARTIAL | NICE | Missing: regenerate-thumbnails, update-host, house-keeping. |
| Plugins/themes | `plugins.ts` | — | — | REJECTED | — | `docs/platform-audit-2026-07.md:94`. |
| Auth that plugins provide | auth-openid-connect, ldap, saml2 plugins | OIDC via env `OAUTH_PROVIDERS` only (config.go:604); no LDAP/SAML | none | PARTIAL | IMPORTANT | Institutional instances depend on LDAP/SAML. |
| OAuth clients | `oauth-clients.ts:15` | n/a | n/a | n/a | — | Not an admin feature in PeerTube. |
| Video file lifecycle pruning | `config/default.yaml:954` | none | none | MISSING | NICE | Unreleased in PeerTube. |

#### 3. Ranked top gaps

1. **Instance-wide remote account block has no UI** (CRITICAL, **S**). The backend already exists (S:2087-2089). Without the UI, moderators have no proportionate response to a single remote harasser short of defederating the whole server.
2. **No federated abuse reports (`Flag`)** (CRITICAL, **M**). Fediverse users and admins can't report vidra-hosted content, and vidra can't escalate to origin instances. That is table-stakes for a public federated instance (shared with the federation agent).
3. **Moderators can't act on users or registrations, and bans carry no reason or notice** (IMPORTANT, **S**). A moderator on shift can't stop a spam account. Affected users get no statement of reasons.
4. **No reporter↔moderator messaging and no "My reports"** (IMPORTANT, **M**). Takedown and harassment reports often need follow-up questions. DMs or email are a workaround, but they leave no trail tied to the report.
5. **No bulk moderation** (IMPORTANT, **M**). There is no "remove all comments of account" (`bulk.ts`) and no bulk abuse, block or registration actions. Spam cleanup becomes one click per item.
6. **No automatic tags or held-for-review comments** (IMPORTANT, **L**). Watched words only flag. PeerTube can hold comments containing links or listed words, and since v8.3 can auto-block videos.
7. **Block doesn't unfederate** (IMPORTANT, **S**). A blocked video's metadata stays listed on peers.
8. **Staff notifications for registrations, quarantine and follower requests** (IMPORTANT, **S**). Approval-mode instances silently accumulate pending queues.
9. **Admin create user** (IMPORTANT, **S**). This is the standard way closed instances onboard people.
10. **Blocklist subscriptions** (IMPORTANT, **M**). Shared denylists are a fediverse norm, and PeerTube made them core in v8.3.
11. **LDAP/SAML, and admin UI for OIDC** (IMPORTANT, **M**). These are the plugin capabilities institutional admins would miss most.
12. **Remote runners** (IMPORTANT, **L**). They would offload transcoding without sharing the database. The `VIDRA_ROLE` worker split covers part of this.

#### 4. What vidra has that PeerTube doesn't (this domain)

- **Upload quarantine** that holds a video before it publishes, with an approve/reject queue.
- **Watched-word match triage queue.**
- **Admin mail config UI** (SMTP, Mailgun, Resend, Brevo, Postmark) with a test send. PeerTube's SMTP is YAML-only.
- **Owner model**: an owner flag, owner transfer, `owner-recovery` CLI and a last-admin guard.
- **Account recovery for admins**: removing a user's MFA, and one-time password reset links behind password step-up.
- **Live stream termination** by moderators, with reason codes.
- **Autosuggest bans.**
- **DM reports.**
- **Operational pages**: job-run traces with an SSE event stream, system and infrastructure pages, and QoE playback health.
- **Storage migration campaigns** (pause/resume/switch/abort), media GC with bucket adoption, and `verify-blobs`.
- **PeerTube instance import** from the admin UI.
- **IPFS mirror control.**
- **Settings validation**, with override badges and reset-to-default.
- **Operator CLI**: `vidra doctor`, setup, backup, restore and rollback.

#### 5. Unknowns

- **Not run:** I didn't run either stack. "Reachable" means a route file imports the component and the component calls the endpoint; it is not click-tested.
- **Blocked videos on peers:** I didn't verify whether peers can still play a blocked local video. Vidra likely refuses the media, so the visible leak would be metadata and thumbnail only.
- **Deactivated users' content:** I didn't check whether a deactivated user's public videos stay visible.
- **Registration emails:** I didn't verify vidra's registration-rejection email content.
- **PeerTube 8.3.1 security fixes:** these are undisclosed in the CHANGELOG, so their admin impact is unknown.
- **PeerTube version:** the clone is `develop`, so the lifecycle feature may change before release.
- **Domain overlap:** per-account (creator) watched words and comment approval overlap the creator domain. Instance follow and redundancy belong to the federation agent.

---

## Appendix D. Federation, protocols and distribution

### 4. Federation, protocols, distribution and the integration surface: PeerTube v8.3.1 vs vidra

Paths: PeerTube is relative to the v8.3.1 clone (`PT/`); vidra is `core/` (vidra-core), `user/` (vidra-user) and `meta/`. All vidra repos were read at origin/main (core 368883a, user adaa149).

#### 1. PeerTube inventory (this domain)

PeerTube federates three actor types: Person (accounts), Group (channels) and an Application instance actor (`peertube@host`). The instance actor drives **instance-to-instance follows**, along with auto-follow-back and an auto-follow index. The activity set covers Follow/Accept/Reject/Undo; Create/Update/Delete for Video, Note, Playlist and CacheFile; Like/Dislike; Announce (channel and instance shares); View (with local-viewer stats); Download; Flag; and ApproveReply/RejectReply (`PT/server/core/lib/activitypub/{process,send}/*`). Every one of these is dereferenceable, and PeerTube also serves likes, dislikes, announces, comments, playlists, chapters and player-settings collections (`PT/server/core/controllers/activitypub/client.ts:62-272`). The protocol layer adds signed fetches (`config/default.yaml:554`), actor and video refresh, outbox crawl, and a follow-health cache. The well-known surface is WebFinger with an ostatus subscribe template, `/remote-interaction`, NodeInfo, `security.txt`, `change-password` and `host-meta`. Distribution covers:
- RSS, Atom and JSON feeds per instance, account and channel
- a private-token subscription feed and comment feeds
- a podcast feed with `podcast:` tags and live items
- oEmbed for videos and playlists, a sitemap and robots
- video and playlist embeds with URL params and a postMessage JS API (`client/src/standalone/embed-player-api`)

On the delivery side PeerTube has redundancy, p2p-media-loader with WebRTC and trackers, object storage plus CDN, and horizontal scaling. The integration surface is a REST API with OAuth password grant, used by the official app, NewPipe and Grayjay, and a SepiaSearch global index. It has **no ATProto** (only a `bluesky_link` social field, `controllers/api/config.ts:339`).

**New since v7.3:**
- v8.1: embed-domain restriction, FEP-1b12 (Lemmy) compatibility, a remote-asset cache, and S3 path-style/per-type prefixes
- v8.2: playlist podcast feeds, the actor `indexable` field, and periodic Follow re-send
- v8.3: "nobody can embed", `host-meta`, a channel Podcast page, the remote blocklist subscription plus a public blocklist log, delivery to inboxes without `sharedInbox`, and sitemap `lastmod`

#### 2. Gap table

| Feature | PeerTube evidence | Vidra backend | Vidra frontend | Status | Sev | Note |
|---|---|---|---|---|---|---|
| Federation on by default | `config/default.yaml:547` (`enabled: true`) | `core/internal/config/config.go:1229` (default false); routes gated `server.go:1467` | `user/lib/admin-config-ia.ts:137` disabled banner | PARTIAL | CRITICAL | Off by default; `meta/env/production.env.example:1272` false |
| **Proof against a real remote** | upstream tests | A29 rehearsal-4 PASS, **vidra↔vidra lab only** (`meta/docs/evidence/a29-rehearsal-4.json` `not_run`: "Interop with any non-vidra ActivityPub implementation"); integration tests use httptest peers | n/a | PARTIAL | CRITICAL | No CI lane: `meta/.github/workflows/stack-e2e.yml:115` sets `FEDERATION_ENABLED=false` |
| Person/Group actors, WebFinger, NodeInfo 2.1 | `well-known.ts:21`, `misc.ts:19` | `federation/actor.go:200-293`, `httpapi/federation.go:47-110` | n/a | PRESENT | — | Actors carry **no icon/image**; `url` = AP id, which Caddy sends to the api, so a browser gets **406** (`federation.go:134`) |
| Application/instance actor and instance follows, auto-follow-back/index | `default.yaml:1223-1249`, FEP-2677 | none: "vidra has no instance actor" (`federation/service.go:254,262`) | none | MISSING | CRITICAL | A PeerTube admin cannot follow a vidra instance, and vidra cannot follow an instance |
| Follow/Accept/Reject/Undo on **channels** | `process-follow.ts` | `federation/inbox.go:166-231`, `follow.go:371-387` | `user/components/RemoteFollowsSection.tsx:20`, `AdminFederationFollowerRequestsView.tsx:23` | PRESENT | — | Includes approval, auto-follow-back and a signed Reject when the sender's instance is blocked |
| Follow of an **account** (Person) | `client.ts:62` | ignored: `inbox.go:173` ("ignore for now") | none | MISSING | IMPORTANT | Mastodon users following `@user@vidra` stay pending forever (`follow.go:241` comment) |
| Create/Update/Delete Video, outbound | `send-create.ts:37` | `federation/outbox.go:21-177`, `video_object.go:68-96` | n/a | PARTIAL | CRITICAL | **Fails PeerTube's validator** (`helpers/custom-validators/activitypub/videos.ts:58,89,94`): no `uuid`, no `views`, and icon has no width/height. PeerTube followers ingest nothing |
| Create/Update/Delete/Announce Video, inbound | `process-create.ts`, `process-announce.ts` | `federation/ingest.go:50-125`; PeerTube fixtures `testdata/inbound/peertube_*.json` | `user/app/remote/[id]/page.tsx:7`, `RemoteWatchView.tsx:29` | PARTIAL | IMPORTANT | Same-origin Announces only (`ingest.go:88`), so instance/third-party shares are dropped. The ingest subset (`ingest.go:33-44`) has no `sensitive`, captions, language or tags |
| `sensitive` flag | `videos.ts:69` | none in either direction | none | MISSING | IMPORTANT | Remote NSFW plays with no warning and bypasses the instance "hide" policy |
| Comments (Note) both ways, incl. authoring on remote videos | `video-comments.ts` | `outbox_comments.go`, `notes.go`, `authored_remote_comments.go`; `server.go:2103-2110` | `RemoteVideoComments.tsx`, `RemoteCommentDeliveryBadge.tsx` | PRESENT | — | No `replies` collection or crawl; third-instance thread parents still missing (A29 residual) |
| Like/Dislike, View, Download federation and collections | `process-like.ts`, `process-view.ts`, `client.ts:90-176` | none (unknown types accepted and ignored, `inbox.go:118`) | none | MISSING | IMPORTANT | Remote viewers and ratings never reach the origin; remote videos cannot be rated |
| Announce (channel share) outbound | `send-announce.ts`, `share.ts:79,102` | none (publishing emits Create only) | none | MISSING | NICE | The spec planned it (`core/.ralph/specs/federation.md:148`) |
| Flag (abuse) federation | `process-flag.ts`, `send-flag.ts` | none; remote reports stay local (`httpapi/admin_remote_videos.go:23`) | report UI is local only | MISSING | IMPORTANT | Inbound Flags from Mastodon/PeerTube are dropped silently |
| Playlist federation | `client.ts:83,234,257` | none | none | MISSING | NICE | |
| Live-video federation | `videos.ts:63-69` | none (`core/internal/live` has no federation hook) | none | MISSING | NICE | |
| CacheFile / redundancy | `lib/redundancy.ts`, `cache-file.ts` | none | none | MISSING | NICE | Undecided: SCP-06 (`meta/docs/release-readiness.md:1144`) |
| HTTP signatures | `constants.ts:1012` | `core/internal/httpsig/httpsig.go:27-30`; key refresh `federation/remote.go:108` | n/a | PARTIAL | IMPORTANT | Inbound is fine. Outbound GETs are **unsigned** (`remote.go:187`, `ingest.go:190`), so authorized-fetch Mastodon objects cannot be fetched. No LD signatures |
| Actor/video refresh, outbox crawl, follow-health | `crawl.ts`, `actor-follow-health-cache.ts` | key refresh only; no Update{Person/Group}; no backfill; dead-letter but no follower pruning (`deliver.go:144`) | none | PARTIAL | IMPORTANT | A newly followed channel shows **0 videos** until it next uploads |
| Collections | `client.ts` | followers/following/outbox only (`server.go:1480-1485`); object ids dereferenceable (`federation_objects.go`, Caddy `@ap_object` `meta/deploy/Caddyfile:224`) | n/a | PARTIAL | NICE | Activity ids `…/activities/{uuid}` 404. A migrated `/videos/watch/{uuid}` AP id 404s |
| Follower continuity after migration (Move, keys, followers) | AP Move | keys imported (`peertubeimport/entities.go:227-255`); **only local→local follows imported** (`source.go:1072-1092`); no `Move`/`alsoKnownAs` | n/a | PARTIAL | CRITICAL | Remote followers are lost even on the same domain. `meta/docs/peertube-migration.md:764-766` says keep federation off |
| Remote URI/handle search | `default.yaml:1289` | `httpapi/search_remote.go:16-35`, `federation/search.go` | `SearchResults.tsx:442` | PRESENT | — | |
| Remote interaction, `host-meta`, ostatus subscribe, fediverse handle on channel page | `well-known.ts:82-125` | none | `ChannelView.tsx:148` shows `@handle` with no domain | MISSING | IMPORTANT | No way for a Mastodon user to start a follow from a vidra page |
| `security.txt`, `change-password` | `well-known.ts:27,75` | none | none | MISSING | NICE | |
| RSS 2.0 instance and channel feeds | `video-feeds.ts:37` | `httpapi/distribution.go:147-224` (gated on `PUBLIC_BASE_URL`, `server.go:1510`) | discovery `app/page.tsx:108`, `channels/[handle]/page.tsx:14` | PARTIAL | IMPORTANT | No `<enclosure>`, no Atom/JSON, no account feed. **PeerTube params (`videoChannelId`/`videoChannelName`) are ignored, so the whole-instance feed is served silently** |
| Subscription feed with private token | `video-feeds.ts:49` | none | none | MISSING | IMPORTANT | |
| Comment feeds | `comment-feeds.ts:27` | none | none | MISSING | NICE | |
| Podcast feed (`podcast:` namespace, live items, playlists) | `video-podcast-feeds.ts:82-197` | none | none | MISSING | CRITICAL | Podcast clients lose the feed outright (`/feeds/podcast/videos.xml` 404s) |
| oEmbed | `services.ts:21` | `distribution.go:249` (videos only, JSON) | discovery `lib/watch-metadata.ts:42` | PARTIAL | NICE | No playlist oEmbed. No `og:video`/`twitter:player` card (`watch-metadata.ts:93-103`) |
| Sitemap, robots | `sitemap.ts`, `misc.ts:22` | `distribution.go:422` (capped at 5000, has lastmod) | `user/app/robots.ts` | PRESENT | — | |
| Embed iframe and domain restriction | `client.ts:61-62` | `httpapi/video_embed_privacy.go` | `app/embed/[id]/page.tsx:6`, `EmbedPrivacyManager.tsx:26` | PARTIAL | CRITICAL | **The legacy `/videos/embed/{uuid}` and `/video-playlists/embed/*` routes do not exist**, so every third-party embed of a migrated instance 404s. No playlist embed |
| Embed URL params and JS player API | `player-options-builder.ts:130-168`, `embed-player-api/player.ts` | n/a | only `?t=` (`lib/start-time.ts:14`) | MISSING | IMPORTANT | No autoplay/muted/loop/start/stop/controls params; no postMessage API |
| REST API and OAuth for third-party/mobile clients | `controllers/api/oauth-clients.ts`, `/users/token` | own JSON auth (`openapi.yaml:417-711`); no PeerTube-shaped endpoints; no OAuth provider | n/a | MISSING | IMPORTANT | The PeerTube app, NewPipe and Grayjay stop working. Retained in SCP-07 (`release-readiness.md:1145`) |
| Plugins/hooks | `lib/plugins` | none | none | REJECTED | — | `meta/docs/platform-audit-2026-07.md:26,94` |
| SepiaSearch global index | `default.yaml:1298-1310` | none | none | MISSING | IMPORTANT | Vidra can neither consume the index nor be indexed (the index crawls the PeerTube REST API). Retained in SCP-09 (`release-readiness.md:1147`) |
| P2P (p2p-media-loader/WebRTC, trackers) | `tracker.ts`, `default.yaml:644` | none; IPFS gateway mirror is the closest thing | none | MISSING | IMPORTANT | Browser P2P is **deferred** (SCP-02, `release-readiness.md:1140`), not rejected |
| WebTorrent (legacy) and torrent import | `lib/webtorrent.ts` | none | none | REJECTED | — | `core/.ralph/specs/ipfs-media.md:26`; `platform-audit-2026-07.md:94` |
| Object storage, CDN, horizontal scale | `lib/object-storage`, `horizontal-scalability-storage.ts` | `storage/s3.go`, `cdn/cdn.go`, `cdnpurge`, `VIDRA_ROLE` (`config.go:1201`), `leaderlock` | admin storage views | PRESENT | — | |
| ATProto/Bluesky | none (link field only) | `internal/atproto/*` (cross-post), `server.go:1652` (login) | `ConnectionsView.tsx:37` | PRESENT (vidra-only) | — | Off by default (`config.go:1231`) |
| FEP-1b12, `indexable`, Follow re-send | CHANGELOG 599, 359, 361 | none | none | MISSING | NICE | |

#### 3. Ranked critical and important gaps

1. **The outbound Video object fails PeerTube's validator (CRITICAL, M).** The validator returns false on a missing `uuid` or `views`, or when no icon carries width/height. So a PeerTube user who follows a vidra channel sees nothing. Vidra's own About page (`InstanceAboutView.tsx:729`) still claims videos "federate to Mastodon, PeerTube". Fix the object shape (attributedTo with Person and Group, `sensitive`, language, captions) and add a golden test that checks it against PeerTube's validator.
2. **No interop proof and no CI lane (CRITICAL, M).** INT-05 passed only vidra↔vidra on 2026-09-09. Nothing exercises a real PeerTube or Mastodon, which is how defect 1 went unnoticed. A nightly lane with PeerTube and Mastodon containers is the gate to turning federation on.
3. **Followers are lost on migration (CRITICAL, M).** Remote followers are not imported (`source.go:1072`), there is no `Move`, and the legacy object ids 404. A migrating instance goes silent to its whole fediverse audience even with the same domain and imported keys.
4. **No instance actor and no instance follows (CRITICAL, L).** This is PeerTube's main federation mechanism, and the auto-follow index depends on it. Without it, PeerTube admins cannot federate with vidra as an instance.
5. **Legacy URLs break on third-party sites (CRITICAL, S).** The `/videos/embed/{uuid}` and `/video-playlists/embed/` routes are missing, and PeerTube feed query params fall through to the whole-instance feed. Both are cheap redirects or aliases that keep existing embeds and feed subscriptions working.
6. **Podcast feed (CRITICAL for podcasters, M).** There is no `/feeds/podcast/videos.xml`, no `<enclosure>` and no `podcast:` tags, and the subscription-token feed is missing too (IMPORTANT).
7. **Mastodon UX defects (IMPORTANT, S).** Account follows hang, the actor profile link returns 406 to browsers, actors have no avatar or banner, and there is no remote-follow affordance on vidra pages.
8. **`sensitive` is not federated (IMPORTANT, S).** This is a safety hole: remote NSFW content bypasses the instance policy.
9. **No outbox backfill on follow (IMPORTANT, M).** Followed channels look empty until they next upload.
10. **Flag, Like/Dislike and View federation (IMPORTANT, M).** Moderation interop and creator stats are cut off at the instance boundary.
11. **Embed params and JS API (IMPORTANT, M).** Sites that script the PeerTube player break.
12. **Client API and global index (IMPORTANT, L).** Mobile and third-party clients lose access, and SepiaSearch cannot list the instance. Both sit in the SCP-07 and SCP-09 backlogs.

#### 4. What vidra does that PeerTube doesn't (in this domain)

- **ATProto/Bluesky:** auto cross-posting with a thumbnail card, and ATProto OAuth login.
- **Per-channel protocol switches:** `activitypub_enabled` and `atproto_enabled` on each channel.
- **Follow handling:** a signed Reject when a blocked instance follows, with all other activities left silent; follower approval at channel level; per-user blocks of remote accounts.
- **Stable identity:** actor ids stay frozen across channel renames (migrations 0142/0143).
- **Delivery visibility:** request ids on every delivery, a `cancelled_by_policy` state distinct from dead letters, and federation queue health on `/admin/system`.
- **Remote-comment authoring:** local users can comment on remote videos, with a delivery-state badge.
- **IPFS dual-tier mirror delivery.**

#### 5. Unknowns

- **Mastodon rendering of vidra's `Create{Video}`:** unknown, because no Mastodon was run. It is probably shown as a link post with no avatar.
- **PeerTube playback of vidra HLS:** even with a fixed object shape, PeerTube might not play a vidra HLS stream that has no `tag` file or segment-hash entries. I could not confirm this without running PeerTube, which the brief forbids.
- **PeerTube to vidra ingest:** only checked against fixtures (`testdata/inbound/peertube_*`), never against a live instance.
- **Live replays:** I did not trace whether a live replay federates through the VOD publish hook.
- **Production federation:** whether any deployed instance runs with federation on is unverified. A memory note says it is off on beta.
