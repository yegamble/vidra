# Beta readiness — feature flags for a PeerTube-sourced instance

**Audited 2026-09-03 against `main` (vidra-core/vidra-user at v0.6.1+3, vidra-search v0.6.1).**
Purpose: decide which features may be flagged ON for a beta instance standing over an import of a
live PeerTube instance, and which must stay off. Every row is derived from code, not from other
docs — see [productionization/risks.md](productionization/risks.md) item 17 for why that
distinction is load-bearing here.

## Verification evidence

| Gate | Result |
|---|---|
| `vidra-core` `make ci` | **pass** — fmt-check, vet, migrate-lint, openapi-verify, sqlc-verify, test-race |
| `vidra-user` `npm run typecheck` | **pass** |
| `vidra-user` `npm run lint` | **pass** — 0 errors, 2 warnings |
| `vidra-user` `npm run test` | **pass** — 2221 tests across 218 files |
| `bash -n` on all 11 `deploy/`, `tests/`, `install.sh` scripts | **pass** |
| `shellcheck` on the same 11 scripts | **pass**, exit 0 |
| prod compose render (`config -q`, `--profile core --profile frontend`) | **pass** |
| prod render port assertion | postgres / redis / search publish **nothing**; api + frontend on **127.0.0.1 only** |
| `:?` fail-loud asserts | verified firing — removing `JWT_SECRET` fails the render (exit 1) |

Compose on the audit host is 5.1.0, far past the 2.24 floor the `!reset`/`!override` merge tags
need. **The gate in AGENTS.md omits `--profile`, so its `config` output reads `services: {}`** —
alarming to eyeball, but harmless: Compose validates the whole model regardless of profiles and
profiles only filter the output. Verified by breaking a service key and a required secret; both
forms exit 1.

## What the beta is missing relative to `main`

The beta pins v0.6.1. Three real fixes and one correctness fix landed after that tag:

| Repo | Commit | Why it matters for the beta |
|---|---|---|
| vidra-core | `fa04baa` (#147) | Emits the canonical `/videos/{uuid}` watch URL in federation/ATProto objects. **Until this ships, every outbound ActivityPub object advertises an unrouted `/videos/watch/` path and remote clicks 404.** |
| vidra-user | `c5002b7` (#130) | Speed/quality menus were clipped by the `overflow-hidden` player stage — 7 of 12 speed rungs untappable |
| vidra-user | `64101ce` (#131) | Player control bar retiered on container queries |
| vidra-user | `aca1f68` (#132) | Navigation glass lit edge + radius scale |

**Recommendation: cut v0.6.2 before opening the beta.** #147 is the only one that is externally
visible to other servers, and federation cannot be safely enabled without it (below).

## Flag mechanisms — and which of them you can actually change on a running beta

There are four, not three, and the difference decides whether a decision costs a click, a
restart, or a rebuild.

| # | Mechanism | Change costs | Notes |
|---|---|---|---|
| a | Boot env → `Config` (`vidra-core/internal/config/config.go:1007`) | **restart** | |
| b | Runtime instance settings, DB overlay (`internal/instancesettings/service.go:597`) | **nothing, ≤10s** | `settings_version` poller, `internal/settingsversion/poller.go:56` |
| c | `NEXT_PUBLIC_*` build-inlined | — | **No live members.** See below |
| d | Compose `:-` fallbacks | restart | **Shadow the Go defaults.** See the trap below |

**Mechanism (c) is empty, which retires a long-standing program risk.**
`NEXT_PUBLIC_API_BASE_URL` is the only `NEXT_PUBLIC_*` in the codebase, and compose passes the
value as `PUBLIC_API_BASE_URL` (`vidra-core/docker-compose.yml:76`), which
`vidra-user/lib/config.ts:68` resolves *first*, per request, from `/runtime-config.js`. Changing
the API origin is a **restart, not a rebuild**, and no Vidra feature flag anywhere is build-baked.

**Two things that look runtime but are not:**

1. **The settings poller is role-gated.** It starts only when `cfg.Role.ServesHTTP()`
   (`cmd/api/main.go:1427`). A `VIDRA_ROLE=worker` process reads the same in-memory settings
   service but never refreshes it, so on a role-split topology every runtime toggle is
   boot-frozen on the worker *while the admin UI accepts the change*. Default `VIDRA_ROLE=all`
   is unaffected — relevant only if the beta splits roles.
2. **Search settings propagate to vidra-search at core startup only**
   (`cmd/api/main.go:2413-2424`). `search_mode`, suggestions, personalization, history and
   `instance_is_sensitive` go live in core within 10s but reach vidra-search only after a core
   restart.

**The compose-fallback trap.** `vidra-core/docker-compose.yml` supplies its own `:-` defaults
that override the Go defaults: `FEATURE_LIVE_ENABLED:-true` (`:220`), `TRANSCODING_ENABLED:-true`
(`:305`), `MEDIA_GC_ENABLED:-true` (`:515`), `DELIVERY_CDN_BASE_URL:-` (`:533`). The sharp edge is
live: `config.go:1089` derives `FEATURE_LIVE_ENABLED` from whether `LIVE_RTMP_URL` is set —
precisely to stop a bare install booting into dead stream creation — **and that derivation never
runs under compose.** Commenting the key out of the env file turns live ON with no ingest plane.
Set it explicitly.

## Keep OFF

| Flag | Why | Reversible? |
|---|---|---|
| `delivery_presign_enabled` (`service.go:955`, default false) | The bucket's CORS must allow the beta's origin; it currently allows only the production origin. Flipping this redirects viewers to signed object URLs and **every media fetch fails in the browser while the server stays silent** — platform-wide playback break with no server-side error. Fix CORS first. | Yes — flip off, next request returns to the API byte path |
| `delivery_cdn_enabled` (`:962`, default false) | Two independent reasons. (1) Silent no-op without `DELIVERY_CDN_BASE_URL`. (2) **`cdn.EdgeURL` carries no query string at all** (`internal/cdn/cdn.go:203`) while the origin mints a fresh `?v=` per transcode and 404s stale ones — so the 307 strips the very version token the origin validates. Any re-transcode of a video that has never had its source replaced re-uses the identical prefix and segment filenames (`internal/media/hls.go:984-989`, `HLSGenerationName` returns `""` for version ≤ 0), so a fresh manifest resolves through the edge to the **previous** transcode's bytes. That is keyframe/duration corruption, not stale-but-valid content. Only a log line guards it (`internal/httpapi/admin_videos.go:76-80`). | Partly — turning it off stops new redirects but **does not evict already-cached edge copies** |
| `FEDERATION_ENABLED` (`config.go:1049`) | On v0.6.1, outbound AP objects advertise the unrouted `/videos/watch/` path (`internal/federation/notes.go:243`); every remote click 404s. **Irreversible** — objects already delivered to other servers cannot be recalled. Needs core#147, i.e. v0.6.2. | **No** |
| Force-adopting the bucket for media GC | The import ran in reference mode, so the DB records **another live instance's** key layout. Adoption is refused by name (`ErrAdoptForeignLayoutMedia`, `internal/mediagc/service.go:52-58`). Overriding arms a destructive sweep against media that instance is still serving. | **No** |
| `MEDIA_GC_MAX_ORPHAN_PERCENT=100` | Disables the orphan-ratio breaker, the last of the four rails. | n/a |
| `DRM_PROVIDER=clearkey-test` | Protects nothing — serves the content key in the clear, and nothing in this build encrypts media. | Yes |
| `IPFS_ENABLED` (`:1150`) | Mirrors public media to a public swarm. Publishing an imported third-party catalogue there is **irreversible**. | **No** |
| `STORAGE_MIGRATION_TARGET_BACKEND` (`:1130`) | Starts a copy campaign **and disarms media GC** via the migration interlock. Only during a deliberate move. | n/a |
| `MALWARE_SCAN_ENABLED` + `MALWARE_SCAN_MODE=fail-closed` | A ClamAV outage blocks **every** upload. Only with monitoring. | Yes |
| `VIDRA_ALLOW_PLAIN_HTTP` (`:1047`) | Never on a public beta. | Yes |

## Safe to enable now

Runtime, ≤10s, reversible from `/admin/config`: `qoe_collection_enabled` (already on),
`downloads_enabled`, `messaging_enabled` / `messaging_e2ee_enabled`, `broadcast_enabled`,
`featured_enabled`, `search_service_enabled` + `search_suggestions_enabled` +
`search_history_enabled` + `personalized_search_enabled` + `personalized_recommendations_enabled`,
`user_import_enabled` / `user_export_enabled`, `video_replace_enabled`, and
`registration_enabled` together with `registration_require_approval`.

Boot, low risk: `METRICS_ENABLED`, `RATE_LIMIT_ENABLED` (keep true).

## Enable only after the paired work

| Flag | Paired prerequisite |
|---|---|
| `storyboards_enabled` (`:804`) | Gates the backfill worker, re-checked per tick (`cmd/api/main.go:1970-1979`) — turning it on makes it sweep the **entire imported catalogue** with ffmpeg. Non-destructive, but schedule it. |
| `delivery_cdn_enabled` | Generation-addressed keys (phase-5 item 1a) **first**, then `DELIVERY_CDN_BASE_URL` pointed at the object store (not the API) plus a mandatory `DELIVERY_CDN_PURGE_URL`. Verify one asset by hand: a wrong origin 404s everything and is indistinguishable from a cold cache. |
| `transcription_enabled` (`:813`) | `WHISPER_ENDPOINT` at boot, or the caption job 503s. |
| `channel_sync_enabled` (`:797`) | `YTDLP_IMPORT_ENABLED=true` at boot, or it is a **silent** no-op (`main.go:1550` logs it and nothing else). |

## Media GC and imported content — resolved safe

This was the audit's highest-stakes question: can the daily destructive sweep delete media the
source PeerTube instance is still serving? **No, on two independent rails.**

1. **Adoption is refused by name.** A reference-mode import is detected as "this instance
   references media stored under another system's key layout" and refused
   (`ErrAdoptForeignLayoutMedia` / `ReasonForeignLayoutMedia`). Without the ownership marker the
   sweep is forced to dry-run. All four rails degrade to a dry run rather than to an error, by
   design (`internal/mediagc/service.go:1-21`).
2. **Even if adopted, foreign keys are kept.** `isReferenced` applies one rule before every
   per-prefix question: a key whose id position holds something this install could not have
   minted is *unattributable, and unattributable means kept*
   (`internal/mediagc/service.go:543-569`). The comment names this exact scenario — delete an
   imported video in Vidra and the rows referencing those objects go with it, so a per-prefix
   orphan test would answer "orphan" for a running PeerTube's own originals and captions.

Also verified: the cross-replica adopt fix (core#119) is exactly as documented — `Sweep`
re-reads the owner marker **only on the already-blocked path** and never claims
(`service.go:420-437`), so ownership cannot be silently acquired by a sweep.

Six prefixes are swept: `web-videos`, `thumbnails`, `storyboards`, `captions`,
`streaming-playlists`, `playlist-thumbnails` (`service.go:376-383`). Avatars, banners, resumable
upload chunks, remote thumbnails and the ownership marker are never enumerated.

## Open code defects worth fixing before a wide beta

Ranked by what actually bites, with the flag posture that contains each one today.

1. **Unversioned CDN edge keys** (`internal/cdn/cdn.go:203` + `internal/media/hls.go:984-989`).
   Contained by keeping `delivery_cdn_enabled` off. The tracked fix is phase-5 item 1a,
   generation-addressed keys, which also makes content replacement stop needing purge at all.
2. **Download-gate revocation leaves the original at the edge.** Flipping `download_enabled`
   true→false fires no purge, for two independent reasons: `DownloadEnabled` is absent from the
   snapshot trigger list (`internal/httpapi/videos.go:1055`, which watches only `Privacy`,
   `PublishAt`, `PublishAfterTranscode`), and even with a snapshot the post-mutation gate
   `if !publicVideoForIPFS(v.Privacy, v.State)` (`:1092`) stays false for a still-public video.
   The instance-wide `downloads_enabled` setting has no purge path at all. **This path is missing
   from the canonical still-unpurged ledger** in `internal/media/media_purge.go:30-44`, which the
   header-promotion gate depends on being complete. Contained by keeping the CDN off.
3. **No failover after a 307** (`internal/httpapi/delivery.go:130-141`). The loop that reads like
   a fallback chain returns unconditionally on the first source, so a dead edge is a terminal
   media failure. Phase-5 item 3's failover premise depends on machinery that does not exist yet.
4. **`qoe_rollups.delivery_source` has no CHECK constraint** (migration `0109:131`) although
   `qoe_events` does (`0109:57-59`). The bounded-cardinality property the rollup design rests on
   is worker-convention only.
5. **One live QoE event poisons a whole VOD batch** — `buildQoEEvent` requires a parseable
   `video_id` and the handler is all-or-nothing (`internal/httpapi/qoe.go:127-138`). Unreachable
   today because the client emits neither live nor federated events.

## Corrections this audit made to the program docs

- `productionization/README.md`: phases 4 and 5 read "Not started" while both had merged waves —
  verified in `vidra-core` history (#74–#82, #115–#121).
- `productionization/risks.md`: **nine of seventeen entries were stale.** Five read "Fix in
  flight" while fixed (1, 2, 9, 14, 15); two more fully retired (5, 13); two carried stale
  clauses (12, 16). Both sections numbered an item 10.
- `productionization/phase-5-enterprise.md:209` asserts "**Nothing calls `Purge`** (zero call
  sites)" while the same document's own status section, 130 lines earlier, records the eight call
  sites that were wired. Eight verified present.
- `productionization/phase-4-delivery.md` names `qoeSubject` as the server-side gate to relax; no
  such symbol exists in vidra-core (it is a *frontend* function). The server gate is
  `buildQoEEvent`.
- `AGENTS.md` hard rule 3 describes a migrate service that "mounts `./vidra-core/migrations` from
  the nested checkout". **The rendered prod `migrate` service has no volumes at all** — it runs
  `migrate up` on the same pinned image, with migrations compiled into the binary. The trap is
  architecturally gone; the checkout still matters for the independent ledger assertion.
