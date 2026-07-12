# PeerTube Config-Parity Ledger — N/A, Deferred & Equivalence Record (W0)

Written 2026-07-11. Companion to `waves.md` (architecture notes 9/10 are binding) and
`gap-matrix.json`. This is the definitive record of every PeerTube admin setting vidra
**deliberately does not implement** (N/A), **defers**, treats as **env-only parity**, or
covers via a **documented equivalence** — with rationale and code evidence so future
audits stop re-litigating these deviations.

**Verdicts**
- **N/A** — deliberate deviation or upstream-dead knob; will not be built as specified.
- **deferred** — honest feature absence; no dormant registry key ships until the backing
  feature exists (dormant keys mislead admins and freeze naming — architecture note 7).
- **env-only-parity** — boot-yaml-only in PeerTube too, so an env knob (existing or
  if-ever) IS full parity; never moves to the DB registry.
- **equivalence** — vidra covers the need by a different, documented mechanism.

All evidence citations below were re-verified against the working trees on 2026-07-11
(line numbers checked, not copied from the gap matrix). Paths are relative to the
`vidra-core` and `vidra-user` repos.

---

## 1. Branding / client assets

| peertube_key | verdict | rationale | evidence | revisit-when |
|---|---|---|---|---|
| `storage.client_overrides` | N/A | Legacy boot-yaml file-drop mechanism for overriding client assets, superseded even in PeerTube by the logo/avatar upload API. Vidra ships the upload API route instead (W1 asset store + W4). | No analogue anywhere in vidra; branding assets go through the planned `POST/DELETE /api/v1/admin/instance-{avatar,banner,logo/{type}}` endpoints reusing `vidra-core/internal/profileimage` (migration 0040 pipeline). | Never — upstream considers it superseded too. |

## 2. Trending

| peertube_key | verdict | rationale | evidence | revisit-when |
|---|---|---|---|---|
| `trending.videos.algorithms.enabled` | deferred | Vidra has exactly ONE trending implementation (HN-style views-decayed-by-age gravity). A setting choosing among algorithms is meaningless with one option; the alternative algorithms (hot / most-viewed / most-liked windows) must be built first. | `vidra-core/internal/store/queries/videos.sql:87` ("trending -> views decayed by age (Hacker-News-style gravity)") and `:173` (the single `sort='trending'` CASE); sort universe is `recent|popular|trending` at `internal/video/service.go:1418`. | A second trending/browse algorithm is built. |
| `trending.videos.algorithms.default` | deferred | Bundled with the above — no choice to default among. | Same as above. | Same as above. |
| `trending.videos.interval_days` | env-only-parity (if ever) | Boot-yaml-only in PT (not in CustomConfig), so admin mutability is NOT required for parity. Only relevant if a windowed most-viewed algorithm is built; would land as `TRENDING_INTERVAL_DAYS` env. | Current gravity algorithm has no interval window: `internal/store/queries/videos.sql:87-173`. | A windowed algorithm exists. |

## 3. Imports

| peertube_key | verdict | rationale | evidence | revisit-when |
|---|---|---|---|---|
| `import.videos.torrent.enabled` | N/A | No torrent/magnet ingestion exists anywhere in vidra; building a BitTorrent client into `internal/videoimport` is out of proportion to demand. HTTP import (yt-dlp) is the supported import path. | `vidra-core/internal/videoimport/` contains only the yt-dlp/HTTP path (resolver + `DrainJobs` worker at `service.go:269`); no torrent code in the repo (grep-confirmed; only unrelated hits in `internal/donation`, `internal/ipfs` tests). | Concrete user demand for torrent import materializes. |

## 4. Remote runners (all four keys — one decision)

Vidra has **no remote-runner protocol at all**: every job (transcode, storyboard,
caption) is an in-process worker in the api binary. A PT-style runner registration/
dispatch subsystem is a whole product decision, not a knob.

| peertube_key | verdict | rationale | evidence | revisit-when |
|---|---|---|---|---|
| `transcoding.remote_runners.enabled` | N/A | No runner protocol; VOD transcoding is the in-process worker enqueued at publish. | `vidra-core/internal/config/config.go:118-122` (TranscodingEnabled doc: "an in-process worker produces an H.264/AAC HLS ladder"); worker in `internal/transcode/service.go`. | A remote-runner subsystem is designed. |
| `live.transcoding.remote_runners.enabled` | N/A | Doubly absent: no runner protocol AND no live transcoding at all (see §12). | `deploy/media/nginx.conf.template:39-40` — live is nginx-rtmp passthrough packaging, no ffmpeg ladder to offload. | Same, plus a live ladder existing. |
| `video_studio.remote_runners.enabled` | N/A | Doubly absent: no runner protocol AND no video studio (see §8). | No editing pipeline exists in `internal/media`; vidra "studio" pages are metadata-only (`vidra-user` StudioView). | Same, plus a studio existing. |
| `video_transcription.remote_runners.enabled` | N/A | Vidra's Whisper is ALREADY an external HTTP service the instance pushes audio to — architecturally it is always "offloaded". A runner toggle on top of an already-remote endpoint is meaningless. | `vidra-core/internal/config/config.go:554` (`WHISPER_ENDPOINT` env, validated `:877`); client in `internal/media/whisper.go`; jobs in `internal/captionjob`. | Never (the deviation is structural and strictly better). |
| `storyboards.remote_runners.enabled` | N/A | Same no-runner rationale; storyboard generation is in-process. | Feature exists in-process: `vidra-core/internal/media/storyboard.go` + `internal/httpapi/storyboard.go` (migration 0060). The `storyboards_enabled` knob itself IS buildable (W8). | A remote-runner subsystem is designed. |

## 5. P2P / tracker / latency

Deliberate architectural deviation: vidra's custom-built player is **plain HLS** with
zero P2P/webtorrent code, by design (W1 backport mandate: custom player).

| peertube_key | verdict | rationale | evidence | revisit-when |
|---|---|---|---|---|
| `defaults.p2p.webapp.enabled` | N/A | No P2P layer exists in the web player. | `vidra-user/components/player/VideoPlayer.tsx` (hls.js-based custom player); zero `p2p`/`webtorrent` hits across `vidra-user/components/` and `lib/` (grep-confirmed 2026-07-11). | A P2P layer is ever built (no plans). |
| `defaults.p2p.embed.enabled` | N/A | Same; embeds (embed privacy exists, migration 0074) share the same plain-HLS player. | Same as above. | Same. |
| `tracker.enabled` | N/A | BitTorrent tracker is predicated on P2P; also boot-yaml-only even in PT. | No tracker code in vidra-core (grep-confirmed). | Same. |
| `live.latency_setting.enabled` | N/A | PT's latency modes are P2P-ratio tradeoffs; vidra has neither P2P nor latency modes in its nginx-rtmp passthrough packaging. | `vidra-core/deploy/media/nginx.conf.template:39-40` (`on_publish`/`on_publish_done` callbacks; passthrough HLS packaging, no mode switching). | A live transcoding/latency subsystem is designed (§12). |

## 6. Transcoding profiles & outputs (VOD)

| peertube_key | verdict | rationale | evidence | revisit-when |
|---|---|---|---|---|
| `transcoding.profile` | N/A | PT profiles are plugin-extensible; vidra has no plugin system and hardcodes x264 `veryfast`. (The vidra-specific VP9 side-output stays env-only via `TRANSCODING_VP9_ENABLED`.) | `vidra-core/internal/media/hls.go:129` (`"-preset", "veryfast"`). | A plugin/profile system is ever designed (no plans). |
| `live.transcoding.profile` | N/A | Same no-plugin rationale, and no live transcoding exists at all (§12). | Same + `deploy/media/nginx.conf.template` passthrough. | Same. |
| `transcoding.hls.enabled` | N/A | HLS is vidra's ONLY ABR format — a toggle to disable HLS while "transcoding" stays on is meaningless. **`transcoding_enabled` IS the HLS toggle in vidra.** | `internal/config/config.go:118-122`: TranscodingEnabled is documented as "turns on the HLS transcoding pipeline"; ladder in `internal/media/hls.go:37-40`. | A second ABR output format exists. |
| `transcoding.web_videos.enabled` | equivalence (N/A-for-now) | Vidra serves the retained ORIGINAL file progressively (Range/206 via `http.ServeContent`) — this covers what PT's transcoded progressive-MP4 renditions provide, without doubling storage. Documented equivalence, not a gap. | `vidra-core/internal/httpapi/videos.go:956` (`handleStreamVideoOriginal`) and `:1039` (`http.ServeContent` → Range/conditional/206 for free); original also in the download list at `internal/httpapi/downloads.go:91-99` and `:184`. | Demand appears for multi-resolution progressive MP4s specifically (e.g. clients that can't play the source codec). Decide jointly with `original_file.keep` (below). |
| `transcoding.original_file.keep` | equivalence / deferred (delete option) | INVERTED DEVIATION: vidra ALWAYS keeps the original and serves it progressively + downloadable; PT defaults to deleting it. The buildable remainder is a delete-after-transcode option for disk savings — but deleting the original breaks vidra's progressive playback of the source (its web_videos substitute). Defer the delete option; decide jointly with the web_videos equivalence (W10 note). | Original retained and served: `internal/httpapi/videos.go:956` + `internal/httpapi/downloads.go:184` (`handleDownloadVideoOriginal`). | W10, if disk pressure creates demand — requires resolving what serves progressive playback afterwards. |
| `transcoding.always_transcode_podcast_optimized_audio` | deferred | PT-develop-only; vidra has no audio-only transcode outputs pipeline step to hang this on. (An HLS audio download asset exists, but no podcast-optimized encode path.) | `internal/media/hls.go:28-29` (`HLSAudioDownloadFilename = "audio.m4a"` — a packaging artifact, not a podcast-optimized encode). | Audio-only output work is scheduled. |
| `transcoding.hls.split_audio_and_video` | deferred | Vidra packages muxed HLS only; PT itself flags compatibility caveats on split A/V. | `internal/media/hls.go:26-27` (muxed `video.mp4` + video-only as download artifacts; playlist packaging is muxed). | Player/packaging work makes split streams worthwhile. |
| `transcoding.allow_audio_files` | deferred | Audio-file upload (merge with still image into a video) requires a new merge step in `internal/media`; capability absent. Upload validation is a video-extension allowlist today. | `vidra-core/internal/httpapi/uploads.go:171` (`video.AcceptedVideoExt` gate; allowlist defined at `internal/video/service.go:1096`). | Deep transcoding wave follow-up after W10, on demand. |

## 7. Video studio

| peertube_key | verdict | rationale | evidence | revisit-when |
|---|---|---|---|---|
| `video_studio.enabled` | deferred | No editing pipeline (cut / intro-outro / watermark) exists — vidra's "studio" pages are metadata editing only (chapters exist but are metadata). An entire subsystem, explicitly deferred in program memory. | No editing code in `vidra-core/internal/media`; `vidra-user` StudioView is metadata CRUD. | Product decision to build server-side editing. |
| `video_studio.remote_runners.enabled` | N/A | See §4 (doubly absent). | — | — |

## 8. Cache counts (deprecated upstream)

PeerTube REMOVED the whole `cache.*` block on develop (post-7.2). Implementing
count-based eviction to match a deprecated knob is wasted work.

| peertube_key | verdict | rationale | evidence | revisit-when |
|---|---|---|---|---|
| `cache.previews.size` | N/A | Deprecated upstream. Vidra's remote-thumbnail cache is per-file size-capped, not count-capped; if disk use ever matters, add eviction to mediagc as vidra-native design, not PT parity. | `vidra-core/internal/federation/ingest.go:29-30` (`maxThumbnailBytes = 2 MiB` per-file cap, stored at `remote-thumbnails/<id>.jpg` per `:207`); `internal/mediagc/service.go` is the eviction home. | Remote-thumbnail disk usage becomes a real problem (then vidra-native eviction, not this knob). |
| `cache.captions.size` | N/A | Deprecated upstream AND vidra does not cache remote captions at all. | No remote-caption caching in `internal/federation/ingest.go`. | Never. |
| `cache.storyboards.size` | N/A | Deprecated upstream; local storyboards exist but remote-storyboard caching does not. | Local only: `internal/media/storyboard.go`; no remote-storyboard fetch in `internal/federation`. | Never. |
| `cache.torrents.size` | N/A | Deprecated upstream AND no torrents anywhere in vidra (§3). | — | Never. |

## 9. Player & client cosmetics

| peertube_key | verdict | rationale | evidence | revisit-when |
|---|---|---|---|---|
| `defaults.player.theme` | N/A | Vidra's custom-built player is styled by the global `light-dark()` token system; PT's galaxy/lucide player skins have no analogue and would violate the redesign guardrails (no colors outside tokens). | `vidra-user/components/player/VideoPlayer.tsx` (token-styled custom player). | Distinct player skins are ever designed (no plans). |

## 10. Channels & users

| peertube_key | verdict | rationale | evidence | revisit-when |
|---|---|---|---|---|
| `video_channels.max_collaborators_per_channel` | N/A | PT-develop-only, boot-yaml-only there, and vidra has no channel-collaborators feature at all — channels have a single owner. | `vidra-core/internal/channel/` has no collaborator model. | A channel-collaborators feature is built. |
| `user.default_channel_name` | N/A | VERIFIED (architecture note 9a): vidra signup does NOT auto-create a channel — there is nothing channel-related in the registration path — so a template for the auto-created channel's name has nothing to apply to. | `vidra-core/internal/auth/registration.go`: zero occurrences of "channel" (grep-confirmed 2026-07-11; file handles user row, approval queue, verification only). | Signup auto-channel-creation is introduced. |
| `signup.filters.cidr.whitelist` / `.blacklist` | env-only-parity (if ever) | Boot-yaml-only in PT (not admin-editable), so env-only IS full parity. Would land as `REGISTRATION_CIDR_ALLOW`/`REGISTRATION_CIDR_DENY` at the registration remote-IP check (optional W7 ride-along). | Apply point would be `internal/auth/registration.go`; no CIDR filtering exists today. | Operator demand; W7 ride-along slot. |
| `history.videos.max_age` | env-only-parity (if ever) | Boot-yaml-only in PT; env-only (`HISTORY_MAX_AGE`) is parity. History table exists (migration 0017) but the pruning sweeper does not — pattern to copy is the export sweeper. | Sweeper pattern: `vidra-core/internal/account/export.go:36-37` (`ExportTTL = 7 * 24 * time.Hour` + `SweepExpiredExports`). | W7 ride-along slot. |

## 11. Federation

| peertube_key | verdict | rationale | evidence | revisit-when |
|---|---|---|---|---|
| `federation.enabled` | env-only-parity (ALREADY at parity) | PT keeps this boot-yaml-only too (read-only in ServerConfig, not in CustomConfig). Vidra's `FEDERATION_ENABLED` env unmounts AP routes at boot and is exposed read-only in `GET /instance` — that IS full parity. Do NOT move to registry: route mounting is inherently boot-time. | `FEDERATION_ENABLED` in `vidra-core/internal/config/config.go`; exposed as `federation_enabled` in `GET /instance` (`internal/httpapi/instance.go`). | Never — this row exists so audits stop flagging it as a gap. |
| `followers.instance.enabled` | deferred | VERIFIED (architecture note 9c): vidra has NO instance-level AP actor — only Person (account) and Group (channel) actors exist. "Remote actors may follow the platform" cannot be gated until an instance actor is designed. Channel-follower gating (`followers.channels.enabled`) IS buildable and ships in W12. | `vidra-core/internal/federation/actor.go:87` (`buildActor(base, "Person", ...)`) and `:105` (`buildActor(base, "Group", ...)`) — the only actor constructors; no Application/Service actor. Inbound follows of non-channel objects are ignored: `internal/federation/inbox.go:135`. | An instance AP actor is designed (prerequisite for PT-style instance follows). |
| `followers.instance.manual_approval` | deferred (re-scoped) | Depends on the missing instance actor above. W12 ships `federation_follower_approval` applied to CHANNEL followers instead — a recorded vidra deviation (pending-follower state + admin queue) — because channel follows are the only inbound follows vidra has, and they are auto-accepted today. | Auto-accept site: `internal/federation/inbox.go:128-151` (`handleFollow` → `enqueueAcceptFollow`, "(auto-accepted)" per the doc comment at `inbox.go:31-32`). | Instance actor exists → extend approval to instance followers. |
| `followings.instance.auto_follow_index.enabled` | deferred | Requires an index-consumer subsystem (polling a public PeerTube index) that has no analogue in vidra; inbound-federation expansion is design-gated per project memory. Note: vidra also federates over ATProto (`ATPROTO_ENABLED`), which has no PT analogue — federation settings must label which protocol each key governs (W12 rule). | No index-polling job exists in `vidra-core/internal/federation`. | An index-consumer subsystem is designed. |
| `followings.instance.auto_follow_index.index_url` | deferred | Bundled with the above — the URL is meaningless without the consumer. | Same. | Same. |

## 12. Live transcoding cluster

Architecture note 7 (binding): ship ONLY live knobs with real enforcement points
(replay gates, caps, duration watchdog — W11). Do NOT ship dormant registry keys for
the unbuilt live-transcoding ladder: keys without apply points mislead admins and
freeze naming before the subsystem is designed.

| peertube_key | verdict | rationale | evidence | revisit-when |
|---|---|---|---|---|
| `live.transcoding.enabled` | deferred | Vidra live is ingest-passthrough HLS packaging via nginx-rtmp; there is no live ffmpeg ladder subsystem. The whole `live.transcoding.*` cluster is one L-sized feature decision. | `vidra-core/deploy/media/nginx.conf.template:39-40` (`on_publish`/`on_publish_done` → local shim → api callbacks; packaging only, no transcode step). | A live ffmpeg ladder is designed/built. |
| `live.transcoding.fps.max` | deferred | Bundled with the cluster. | Same. | Same. |
| `live.transcoding.resolutions.{0p..2160p}` | deferred | Bundled with the cluster. | Same. | Same. |
| `live.transcoding.always_transcode_original_resolution` | deferred + partial equivalence | Bundled — but note passthrough ALREADY delivers the original ingest resolution to viewers, which is what this PT key guarantees; the gap is only the missing lower rungs. | Same passthrough evidence. | Same. |
| `live.transcoding.threads` | deferred | Bundled with the cluster. | Same. | Same. |
| `live.transcoding.profile` | N/A | No-plugin rationale (§6) on top of the missing subsystem. | Same. | Plugin system (never planned). |
| `live.dvr.max_window` | deferred | No DVR/seekable-live exists (passthrough HLS window is fixed); PT-develop feature. Needs nginx HLS-window config + player seekable-live support. | `deploy/media/nginx.conf.template` (no DVR window config); `vidra-user/components/player/VideoPlayer.tsx` has no seekable-live mode. | Live subsystem design pass (with the transcoding cluster). |

## 13. Comments

| peertube_key | verdict | rationale | evidence | revisit-when |
|---|---|---|---|---|
| `defaults.publish.comments_policy` — `requires_approval` value | deferred (deviation) | W9 builds per-video comment policy as **enabled\|disabled only**. PT's third value `requires_approval` implies a per-video comment-approval queue (held comments + reviewer UI) that vidra does not have; shipping the enum value without the queue would be a dormant lie. Deliberate v1 deviation, signed off in W9's design gate. | Only instance-wide `comments_enabled` exists today: `vidra-core/internal/instancesettings/service.go:54` (`KeyCommentsEnabled`); no per-video policy column, no approval queue. | Demand for comment pre-moderation → build the approval queue, then add the enum value. |

## 14. Email

| peertube_key | verdict | rationale | evidence | revisit-when |
|---|---|---|---|---|
| Email HTML templates (PT's customizable HTML email layer) | deferred | Vidra mail is plaintext-only with a single sender seam; there is no HTML template layer to customize. W6 ships the two strings PT exposes as config (`email.subject.prefix`, `email.body.signature`) at that seam; full template/HTML customization is out of scope until an HTML mail layer exists (architecture note 5). | `vidra-core/internal/mail/smtp.go:125` (`send(ctx, to, replyTo, subject, body string)` — the single seam all senders at `:81/:95/:110` funnel through; plaintext body, no MIME/HTML parts, header assembly at `:195`). | An HTML mail layer is built. |

## 15. Global search index (quartet — one decision)

| peertube_key | verdict | rationale | evidence | revisit-when |
|---|---|---|---|---|
| `search.search_index.enabled` | deferred | Requires a Sepia-compatible external search-index client — a whole subsystem, absent entirely. All four keys land together if ever built (W13 note: do NOT ship the two cheap UI flags standalone). | No index client in `vidra-core`; search is local + cached remote videos (`internal/httpapi/videos.go` handleSearchVideos). | A Sepia-compatible index client is built. |
| `search.search_index.url` | deferred | Bundled. | Same. | Same. |
| `search.search_index.disable_local_search` | deferred | Trivially cheap UI flag but meaningless without the index — shipping it standalone would let an admin disable local search with no replacement. | Same. | Same. |
| `search.search_index.is_default_search` | deferred | Same dependency. | Same. | Same. |

## 16. Login / external auth (W5 as-built correction, 2026-07-12)

| peertube_key | verdict | rationale | evidence | revisit-when |
|---|---|---|---|---|
| `client.menu.login.redirect_on_single_external_auth` (planned `login_redirect_single_oauth`) | deferred | waves.md W5 (line 129) said "implement the branch, note dependency", but vidra has NO OAuth/external-auth subsystem to redirect to, and shipping the key would violate the no-dormant-keys rule (architecture note 7) every other wave held. As built, W5 shipped nothing for this key; this row supersedes the waves.md instruction so the ledger matches the code. | No OAuth/external-auth code under `vidra-core/internal/auth`; no `login_redirect_single_oauth` key in `internal/instancesettings/service.go` (grep-confirmed 2026-07-12 at 74cecb1). | OAuth/external-auth ships — implement the redirect branch then. |

## As-built deviations recorded at program close (2026-07-12)

| item | as-built deviation | evidence |
|---|---|---|
| W6 `CUSTOM_JS_ALLOWED` kill-switch | The OPTIONAL boot env kill-switch described in waves.md (notes 6 and W6 items) was NOT built. Custom JS is gated instead by admin-only auth + the typed-confirmation warning flow + audit-enveloped writes with hash. Not a shipped-but-missing control. | No `CUSTOM_JS_ALLOWED` in `internal/config/config.go` (grep-confirmed); confirmation flow + audit in the W6 slice (fdd02d6). |
| W10 `transcoding_max_fps` semantics | Applied UNIFORMLY to all rungs (not per-rung like PeerTube), and only when the KNOWN source fps exceeds the cap. Documented in code but previously absent here. | `internal/media/hls.go:73-77`. |
| W11 `live_max_duration_secs` force-close | waves.md (W11 lines 223/228) says force-close "via nginx-rtmp control"; AS BUILT there is NO nginx-rtmp control/drop endpoint (`deploy/media/nginx.conf.template:39-40` has only on_publish/on_publish_done). The watchdog is a SERVER-SIDE state flip: it immediately stops live HLS serving and delists the session; the publisher's RTMP ingest socket lingers until disconnect, which then drives the normal stop/replay path. Enforcement is real and effective for its documented scope. | `internal/live/service.go:648-658`; `cmd/api/main.go:1484-1487`. |
| W2/W4 layout.tsx seam invariant | The "later waves never edit layout.tsx" invariant (layout.tsx:19, waves.md:85) was contradicted ONCE: W4 (`a2965c6`) made a sanctioned 2-line wiring edit (`<Header />` → `<Header instance={instance} />` + a seam comment) because the header-branding seam was not in W2's pre-provisioned list. The seam design otherwise held for all waves; the in-code comment is being softened to "edits here are limited to wiring a new seam consumer's props". | `git log -- app/layout.tsx` shows only a464b5f (W2) and a2965c6 (W4). |
| W8 storyboards gate location | The runtime gate for `storyboards_enabled` is the `storyboardGate` seam consulted at `internal/video/service.go:918` (and the duplicate publish path at `:826`), wired in `cmd/api/main.go:529-531`. `internal/media/storyboard.go` is only the generator implementation — citations pointing at it as the gate are stale. | as cited. |

---

## Corrections to gap-matrix/spec line numbers (verified 2026-07-11)

The following citations in `gap-matrix.json`/`waves.md` had drifted; this ledger uses
the verified numbers:

- Extension allowlist gate: `internal/httpapi/uploads.go:171` (spec said 170); allowlist
  function `video.AcceptedVideoExt` at `internal/video/service.go:1096`.
- HLS ladder: `internal/media/hls.go:37-40` (spec said 24-28); x264 preset at
  `hls.go:129` (spec said 117).
- Export TTL: `internal/account/export.go:36-37` (`ExportTTL = 7 * 24 * time.Hour`).
- Import single-ticker worker: `internal/videoimport/service.go:269` (`DrainJobs`,
  "Intended to be called on a ticker by a single worker"; spec said 268).
- Inbox comment ingest: dispatch at `internal/federation/inbox.go:71` → implementation
  `internal/federation/notes.go:38` (`handleCreateNote`); spec's "inbox.go:42" is stale.
- Follow auto-accept: `internal/federation/inbox.go:128-151` (spec's ":31" points at the
  doc comment, not the code site).

## Corrections re-verified at the W14 tip (2026-07-12)

The 2026-07-11 corrections block above has itself gone stale — every cited file grew during
W8–W14. Verified against vidra-core `74cecb1` / vidra-user `3d03c23`:

- Extension allowlist gate: `internal/httpapi/uploads.go:172`, now calling
  `video.AcceptedVideoExtGated` (the W10 gated variant honoring
  `upload_additional_extensions_enabled`), not plain `AcceptedVideoExt`; `AcceptedVideoExt`
  at `internal/video/service.go:1406`, `AcceptedVideoExtGated` at `:1415`.
- HLS ladder: `DefaultHLSResolutionHeights` at `internal/media/hls.go:57` (W10 parameterized
  it); x264 preset at `hls.go:265`.
- Import single-ticker worker: `DrainJobs` at `internal/videoimport/service.go:312`.
- Inbox comment ingest implementation: `handleCreateNote` at `internal/federation/notes.go:43`.
- Follow auto-accept: `handleFollow` at `internal/federation/inbox.go:147-189` (W12 gates now
  inline; auto-accept branch at `:178-188`); §11's "non-channel follows ignored" is `inbox.go:154`.
- §6 web_videos equivalence: `handleStreamVideoOriginal` at `internal/httpapi/videos.go:1083`;
  `http.ServeContent` at `:1154`/`:1168`. §6/§14 original download:
  `handleDownloadVideoOriginal` at `internal/httpapi/downloads.go:194`.
- §13: `KeyCommentsEnabled` at `internal/instancesettings/service.go:56`.
- §14: mail send seam at `internal/mail/smtp.go:156`.
- §8: `maxThumbnailBytes` still `internal/federation/ingest.go:29-30`; the storage cite is now `:247`.
- waves.md architecture notes 2/6 write the public document routes without the API prefix
  (`/instance/custom.css` etc.); AS BUILT all public routes live under `/api/v1/instance/...`
  (contract "Documents" section — the contract examples are already fully prefixed).
- `gap-matrix.json` `vidra_status` fields are the FROZEN 2026-07-11 pre-implementation snapshot
  that fed this wave plan. They are superseded by W1–W15 as shipped (e.g. broadcast_*,
  default_* publish, storyboards_enabled, live_allow_replay, federation_* gates all read
  "missing" there but exist in the registry) and MUST NOT be read as a live tracker.

## W9 decisions (2026-07-12)

| item | decision | rationale |
|---|---|---|
| `default_video_privacy` registry default | `private` (NOT PeerTube's `public`) | omit-means-private was the shipped API behaviour; loosening it silently as a side effect of adding the knob was rejected in W9 review (vidra-core d2b8cd9). Admins opt into public-by-default via the setting. |
| `default_download_enabled` registry default | `true` | shipped behaviour: every video downloadable while the instance-wide `downloads_enabled` gate (84b5a38) is on; per-video flag layers under it. |
| Federation `pt:commentsPolicy`/`pt:downloadEnabled` | not emitted | vidra emits plain-AS video objects; rationale documented at videoObject in internal/federation/outbox.go; goldens unchanged. |
| PT comment `requires_approval` tier | still deferred | no comment-approval queue in v1 (see §13). |

## W14 + W15 as-built record (2026-07-12)

| item | as built |
|---|---|
| `video_replace_enabled` (W14) | Registry bool, default **false** (PT parity with `video_file.update.enabled`), page `vod`, section `uploads`. Enforcement: `internal/httpapi/replace.go` — `POST /videos/{id}/replace` + `POST /videos/{id}/replace-session`, gated by `videoReplaceAvailable()` (`replace.go:35-38`; 403 `feature_disabled`, also requires uploads on) with owner/moderator auth and state/extension gates. Source-version model in `internal/media/hls.go` + `ReplaceSource` in `internal/video/service.go`; re-transcode re-enqueues through the W10 parameterized pipeline (atomic promotion, invalidate fallback); `internal/mediagc` collects old generations + the old source blob; quota on replacement is charged to the video OWNER. `features.video_replace` on GET /instance mirrors the gate; URL/id/metadata stay stable across replacement and mid-swap playback is addressed. Shipped: vidra-core `74cecb1` + vidra-user `3d03c23` (StudioView replace flow incl. prefill-race fix). |
| W15 reconciliation | vidra-user `b216134`: (a) follower-approval admin queue UI (`app/admin/federation/follower-requests/page.tsx` + `AdminFederationFollowerRequestsView.tsx` + AdminTabs/AdminConsole nav + `e2e/admin-federation-followers.spec.ts`) — closes the W12 contract note "pending frontend slice"; (b) watch-page SSR metadata (`app/videos/[id]/page.tsx` generateMetadata via `lib/video.server.ts` + `lib/watch-metadata.ts`; og:image prefers the video thumbnail, falls back to the instance opengraph logo; missing/private videos emit nothing) — closes the W4 precedence item. The W4 deviation comment in `lib/layout-metadata.ts:18-22` ("watch page has no server-side generateMetadata") is now stale; fix queued. |
