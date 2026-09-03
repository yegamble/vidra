# Phase 5 — Enterprise media

**Outcome:** the capabilities that make "Netflix-class" honest — multi-CDN with content
steering, DRM with real key management, distributed/multi-region topology — as optional
modules/providers on the same core. No fork: same interfaces, different providers, different
scale. An ordinary Vidra installation never sees any of this.

## Status 2026-08-28 — audit + honesty wave (evening)

**A 20-agent adversarial audit of the morning wave, then a ten-PR build wave closing what
it found — all MERGED same day** (core#118–121, user#96–101). Claim-by-claim, all 67
morning-wave claims held; every surviving gap was one level up — the UI/UX and
observability layer over correct backends. Ten findings survived adversarial verification
(zero refuted); all are closed:

- **Cross-replica mediagc adopt staleness — the one real backend bug (core#119):** bucket
  ownership is a boot-loaded cache the settings poller does not (and cannot) cover — the
  scheduled sweep runs in `RoleWorker` processes where no poller starts, so adopt-bucket
  flipped only the replica that served the POST and the leader worker's sweeps stayed
  forced-dry-run until restart. `Sweep` now re-reads the owner marker on the
  blocked-delete path only, and never claims (no marker leaves the state alone); the
  operations.md/openapi "from the next sweep onward" promise is true again.
- **Purge call-site completeness (core#120):** channel deletion (video cascade + the
  channel's own avatar/banner), avatar/banner set/delete, and playlist cover
  set/delete/visibility-flip all purge now (shared single-key helper; pre-mutation
  snapshot, detached, CDN-gated). Same-generation admin re-transcode is deliberately NOT
  purged — purge-at-enqueue would be wrong, the tracked fix is item 1a
  generation-addressed keys — and warns when a CDN is configured. The still-unpurged
  ledger now reads: **thumbnail/storyboard in-place replacement, account deletion,
  same-generation re-transcode** (`media_purge.go`'s header is the canonical copy).
- **Admin visibility round 2 (core#121, rendered by user#99+#100):** the DRM Active row
  now carries the test-provider warning (a green "content protection" pill had asserted
  protection that does not exist, with the honest note shown only when DRM was *off*);
  VIDRA_ROLE, `DELIVERY_CDN_BASE_URL`, live ingest coordinates, rate limits (shipped in
  the contract expressly for the status page, never rendered), settings-poller health
  (`settings_sync` component), drain status, CDN purge counters (the `cdn_purge` block —
  the "exercised" evidence header promotion waits on), and `GET /admin/media/gc` boot
  facts are all visible. `FEATURE_LIVE_ENABLED`'s code default now derives from
  `LIVE_RTMP_URL` (unset ⇒ on only when an ingest is configured) — a bare install no
  longer boots into a permanent "Needs setup" warning with dead stream creation.
- **Media page honesty (user#101):** the adopt-bucket action finally exists (unowned =
  arm+confirm; conflict = typed ADOPT naming the marker overwrite; never offered for
  unknown/healthy states); the false "nothing is deleted until you confirm a purge" copy
  now names the daily automatic destructive sweep; boot facts render read-only; the
  orphan preview caps at 500 rendered keys with a full-list download.
- **Delivery config UX (user#96):** on-but-unwired CDN/presign toggles carry a live,
  non-disabling warning driven by the admin infrastructure snapshot (the user#92 bootDep
  deferral was stale once core#116 reported both halves); presign help names the
  bucket-CORS prerequisite — the one misconfiguration that breaks playback instead of
  staying inert; QoE help states the verified privacy posture (no account id, no IP,
  keyed day-scoped viewer digest, 7-day raw retention).
- **Nav coherence (user#97 + fix-forward #98):** the global Admin entry lands on the
  console home; phones get an AccountMenu admin entry; the moderation surface adopts the
  registry vocabulary (Queues/Content) with an admin-only back-link; the mobile Select
  gains Console/More/Moderation groups. The lesson worth keeping: #97 updated only the
  mocked e2e suite and merged red — the backed suite navigates the same journeys and
  must move with any nav change; and an unscoped `getByRole("link", { name: "Content" })`
  resolves to the "Skip to content" skip-link first (substring matching), off-viewport
  forever.
- **Item 8b closed (core#118):** operations.md gained "Behind a load balancer" —
  /readyz + drain sizing, `TRUSTED_PROXY_CIDRS` rightmost-untrusted semantics, and
  rate-limit N-replica behavior, with one correction to this doc's premise: Redis is a
  fatal boot dependency, so shared limits never fall back to local counting — only the
  always-on fallback limiters multiply per-process.

Deferred, recorded: worker/leader liveness + latest-run-age surface (item 9's
worker-identity slice owns it); the infra search row's Advanced-page anchor (an e2e spec
pins the exact href — move both together); account-deletion and thumbnail/storyboard
purge fan-out (ledger above).

## Status 2026-08-28 (morning)

**Re-audit + admin-parity wave MERGED.** A claim-by-claim re-verification of every wave A/B/C
claim against `main` confirmed all 19 (zero stale). Seven PRs landed and merged same day:

- **Settings-cache invalidation (item 8a) — DONE** (core#115): migration 0121
  `settings_version` counter + a jittered 10s poller on every HTTP-serving replica, reloading
  the three boot-loaded caches (instance settings, ToS/privacy docs, branding) on version
  change. N-replica api is now **correct**, not just safe. Bumps are post-write ordered (the
  write paths are not transactional); a failed reload never advances the seen version.
- **Purge call-site wiring (the items-1–3 gate) — WIRED** (core#117): video delete, privacy
  flip away from public, and admin block now fan out best-effort single-key purges (the
  provider has no prefix purge) over the video's recorded objects plus the listed
  HLS/web-video trees — snapshotted pre-mutation, fired post-commit detached, capped at 5000
  keys. Corrected premise: playlists were never edge-cacheable (`Redirectable` excludes
  them) — segments are the cargo. Still unpurged: thumbnail/storyboard in-place replacement,
  account deletion. Header promotion stays gated until purge is exercised against a live edge.
- **Admin visibility (core#116):** the infrastructure feature vocabulary grew `cdn` and `drm`
  three-state rows (the stale "there is no CDN integration" contract text is gone; `cdn` is
  the one row that reads the runtime overlay, exception documented), the server block reports
  pool sizing + `HTTP_DRAIN_DELAY`, and `GET /api/v1/admin/system` gained a live pgx pool
  block (omitted entirely when unwired — 0/0 must not read as a checked-out pool).
- **Admin UI parity (user#92–95):** the five uncurated registry keys got labels/help and a
  real "Delivery" section on the Advanced page (CDN/presign/QoE toggles are no longer an
  unlabeled toggle forest); the media-GC page renders the six previously-ignored safety
  fields (a forced dry-run no longer shows as green "Purge complete" — the ownership-rail
  trap is now visible, with a breaker-tripped danger state); the three drifting admin navs
  collapsed onto one registry (mobile admins regained moderation; Overview gained the four
  missing pages); and the new pool/drain/CDN/DRM contract renders (Database panel, pool
  saturation warning, feature labels — the CDN row links to its Advanced-page control, DRM
  deliberately does not link since no admin control exists).

**Progressive-disclosure doctrine (decided this session):** advanced production features
surface through the three idioms the admin UI already has — the Advanced config page for
runtime toggles, the infrastructure feature list's `Off`/"Optional:" rows for discovery, and
read-only Panel/Row display for boot-env knobs — never a new "advanced mode". A simple
install sees one quiet row per module, not a control forest. Known deferred wiring: a
`bootDep` signal for `delivery_cdn_enabled` needs `/instance` (or the config view) to carry
CDN-configured state; an adopt-bucket action button on the media page (endpoint exists,
unwired).

## Status 2026-08-23

**Recon complete** — five parallel read-only audits (steering, DRM/CENC, multi-node API,
worker fleets, multi-region) verified every premise in this doc against the code before any
build. The corrections are recorded below; four premises were stale, one item lost its subject
entirely. **Three build waves MERGED same day:** core#80 (multi-node API floor), core#81
(worker fleet floor), core#82 (DRM slices 0+1) — each through the full `make ci` gate plus
real-Postgres integration tiers with RED-first proofs for every behavioral change. The
ClearKey bootstrap experiment also ran to a verdict (below), and the content-steering
research/design landed as [content-steering-decision.md](content-steering-decision.md).

The phase decomposes into a cheap floor and expensive modules. The floor — configurable pool
sizing, fleet-safe sweeps, drain/readiness for LBs, the DRM provider seam with sealed key
storage — is S/M-sized and landed first. The modules — steering, Shaka-packaged CENC, live-plane
externalization, multi-region replication — are each gated on a decision recorded here or in a
sibling decision doc.

## Prerequisite chain — audited 2026-08-23

The original prerequisite list, claim by claim:

| Claim | Verdict | Evidence |
|---|---|---|
| Phase-4 session API + delivery resolver exist | **CONFIRMED** | `internal/httpapi/playback_session.go` (+ live twin); `internal/delivery` with four source kinds |
| "today at most two sources exist; selection is a bespoke user toggle" | **STALE** | Four kinds implemented (`api-proxy \| presigned \| ipfs-gateway \| cdn`), server-side static-priority selection. The IPFS user toggle exists but is a parallel client-side system outside `internal/delivery`. The real gap: the only consumer 307s to `sources[0]` and discards the rest — no health, no failover, no signals |
| CMAF packaging (Phase 3) | **CONFIRMED** | `TRANSCODING_PACKAGER=cmaf` is the default; per-video format recorded |
| "engine adapter with a FairPlay path for the MSE-less iOS native-HLS branch" | **HALF-STALE** | The adapter and the native-HLS engine exist (`lib/player-engine.ts`). There is **zero** EME/DRM code in vidra-user, and FairPlay requires `cbcs`, which ffmpeg's mp4 muxer cannot produce — FairPlay is structurally gated on Shaka Packager, not on the adapter |
| playback sessions for license issuance | **CONFIRMED, better than assumed** | `playbackSessionResponse` and `playback.Scope` both carry explicit reserved-for-DRM extension points |
| worker lease retrofit (Phase 3) | **CONFIRMED** | 13 queue query files use `FOR UPDATE SKIP LOCKED` + lease; 2-replica soak: 406/406, 0 dupes |
| "single-process worker claims" blocks multi-region | **STALE — delete** | Fixed by the lease retrofit + leader election. (Two in-repo assertions still claimed this; fixed in wave B / this PR) |
| live HLS on a shared filesystem volume | **CONFIRMED, understated** | Three-way `live_hls` volume (rtmp writes, api reads via `os.Open` at `live_hls.go:183`, worker reads `rec/` for replay); the nginx ingest shim also hard-codes `proxy_pass http://api:8080` |
| hardcoded pool MaxConns=10 | **CONFIRMED** (wave A fixes) | `internal/store/store.go:53` — plus MinConns/lifetimes hardcoded, zero pool telemetry, and the cron-leader elector pins one of the ten |

**Additional prerequisites the original list omitted:** the QoE schema cannot distinguish CDNs
(see item 1), nothing calls `Purge` yet (phase-4 carry-forward gating items 1 and 3), and the
worker-role flag it would have needed **already landed** (`VIDRA_ROLE` = `all|api|worker`,
`config.go:28-67` — interfaces.md §7's "still open" note was stale).

## Ground truth 2026-08-23 (recon against the code, before any phase-5 build)

### Multi-CDN & steering (items 1–3)

- **The resolver is signal-free by design.** Selection inputs are boolean fences only
  (`Redirectable` class, `Eligible`, `!Credentialed`, runtime kill switch); its import list is
  stdlib + `internal/storage`, deliberately. Health/latency/region/cost/capacity have **no data
  source anywhere**; the only latency data in the system (QoE) is hourly-rolled and 24h-lagging —
  useless as a live steering input. The in-repo pattern to copy for health is
  `internal/searchclient/prober.go` (atomic flag, 2-failures-condemn/1-success-forgive, jittered
  probe).
- **CDN plumbing is structurally singular.** One `DELIVERY_CDN_BASE_URL`, one provider, one
  toggle, two scalar fields on `Server`. A second CDN cannot be configured at all today. (The
  settings service does have a `KindList`, so a list-shaped runtime setting needs no new
  machinery.)
- **QoE landmine — sequence first:** `qoe_rollups`' primary key holds `delivery_source` as a
  hard 6-value CHECK; **every CDN collapses into the single `cdn` bucket** and the classifier
  takes exactly one `cdnBase`. Per-pathway measurement has no storage until a migration adds a
  bounded pathway dimension. **Item 1's signals ship blind unless this lands first.**
- **Steering is a second delivery mode, not an increment on the 307 mode.** Today a client never
  sees a CDN URL in a manifest — only a per-object 307. Steering requires per-pathway URLs *in
  the master playlist*. The origin is route-addressed (`/api/v1/videos/{id}/hls/...`) while the
  edge is key-addressed (`streaming-playlists/{uuid}/...`), so `URI-REPLACEMENT: HOST` cannot
  work. The design is settled in
  [content-steering-decision.md](content-steering-decision.md): **shape B, pathway cloning** —
  today's ladder plus the tag, `PATHWAY-ID="VIDRA-ORIGIN"` and stable ids, with clones carrying
  `PER-VARIANT-URIS`/`PER-RENDITION-URIS` (which is a *field of* cloning, not an alternative to
  it). Sibling-pathway duplication (shape A) is rejected — it hands every non-steering client an
  N× duplicated ladder — and kept only as a documented escape hatch if AVPlayer cloning proves
  broken (the empirical Safari/iOS run is a first-slice deliverable; no source anywhere has
  tested `PER-VARIANT-URIS` on AVPlayer, and both public cloning field reports are failures).
- **The steering research surfaced a live shipped gap, steering aside — its P0:** `cdn.EdgeURL`
  carries **no query string at all**, so every segment the shipped CDN path already 307s is
  cached at the edge under an unversioned, in-place-mutable key — and an admin re-transcode of a
  version-0 source **overwrites the legacy prefix in place** (`HLSPrefixForSource` allocates a
  fresh `rN` only for source replacements). Fix: **generation-address every packaging run**;
  the object key becomes the version, edge URLs are immutable by construction, and content
  replacement stops needing purge entirely. This is a prerequisite for steering *and* a
  correctness fix for the CDN path that exists today.
- **Steering-URI rulings (fixed, whatever the design):** the steering manifest URI must be a
  **stable per-video path** with priority computed server-side per request — a session-scoped
  URI would be pinned for a year inside the `?v=`-immutable master. The `#EXT-X-CONTENT-STEERING`
  tag is injected at the existing per-request master rewrite (`serveHLSPlaylist` →
  `rewritePlaylistReferences`) **only when ≥2 pathways are configured** — ordinary installs stay
  byte-identical. The credentialed trap applies unchanged: the steering manifest for public
  videos must carry no credential (`_HLS_pathway`/`_HLS_throughput` are not credentials and are
  safe).
- **The `Eligible` fence bounds the whole feature:** `public AND published` only. Steering and
  multi-CDN apply structurally to public published media; private/password playback stays
  origin-only (signed-URL-at-the-edge would be a different mechanism — out of scope).
- **hls.js 1.6.16 (already shipped) implements Content Steering end to end** — the HLS client
  half of item 2 needs zero new dependency (the steering slice itself requires the bump to
  ≥1.7.1 for three URI-REPLACEMENT fixes; `^1.6.16` will not resolve to it). **DASH steering is
  structurally unavailable, not merely client-less:** ETSI TS 103 998 explicitly excludes the
  per-variant URI replacement Vidra's addressing mismatch requires, and the MPD is served
  verbatim with no rewrite path — landing Shaka (item 3c) does not change that.
- **Item 3 (origin shielding) is mostly configuration + docs:** the CDN origin is already a
  plain key-addressed base, so a shield tier is "point CDN A's origin at the shield". What needs
  code: per-pathway purge fan-out, and failover — which needs item 1's health signals first.
- ~~**Nothing calls `Purge`** (zero call sites).~~ **STALE as of core#117/#120 — corrected
  2026-09-03.** This line was the 2026-08-23 recon snapshot and was left standing when the wiring
  landed, so this document contradicted its own status section 130 lines above it. Eight call
  sites are verified present: video delete, privacy flip away from public, admin block, channel
  cascade (videos + the channel's own avatar/banner), avatar/banner set/delete, and playlist cover
  set/delete/visibility-flip — each snapshotting pre-mutation, firing post-commit and detached,
  capped at 5000 keys, and free when no CDN is configured (`internal/media/media_purge.go`).
  What is still true, and still the gate: every media response remains `private`, and header
  promotion waits on purge being **exercised against a live edge**, which has not happened.
  Multi-CDN multiplies the purge fan-out before single-CDN purge has ever fired for real.
  *One gap found in the canonical ledger while verifying this: the download-gate flip
  (`download_enabled` true→false) fires no purge and is not listed — see
  [../beta-readiness-2026-09.md](../beta-readiness-2026-09.md).*

### DRM (items 4–7)

- **ffmpeg CENC is real but disqualified.** Re-verified empirically on ffmpeg 8.1 (same major
  as the Alpine image): the dash muxer's `-format_options` forwards
  `encryption_scheme=cenc-aes-ctr` to the child mp4 muxers and produces genuine CENC
  (`encv`/`tenc`/`senc`/`saio`/`saiz`). But: **no `pssh`**, **no `<ContentProtection>` in the
  MPD**, **no `#EXT-X-KEY` in the playlists** (all signaling would be hand-built), **one key for
  the entire tree** (video and audio init segments carry byte-identical `tenc`; no per-track
  keys, no rotation), **no `cbcs`** (so no FairPlay, ever, on this path), and trick-play goes
  through the hls muxer which cannot CENC at all (encrypted content, clear scrub thumbnails).
- **The disqualifying landmine — silent derivative corruption:** Vidra builds progressive
  MP4s and `audio.m4a` by stream-copying *out of the packaged playlists*
  (`remuxCMAFDownloads` → `-c copy`). Against encrypted segments this **exits 0 and writes
  encrypted garbage** (verified: 57 KB file, decoder errors on stderr, success exit code) — and
  the `audio.m4a` path swallows errors, making it doubly silent. `-decryption_key` is a mov
  demuxer option and is rejected through the hls demuxer, so there is no workaround on this
  path. Encrypting *after* Finalize avoids the whole class.
- **Therefore: if CENC ships, Shaka Packager ships with it** — confirming
  [cmaf-packaging-decision.md](cmaf-packaging-decision.md), with one pricing correction in
  Vidra's favor: for the DRM case the encode has already happened, so Shaka's pass over the
  finalized clear tree is a **transmux+encrypt stream-copy, not a re-encode** — meaningfully
  cheaper than that doc's mezzanine headline. The `Packager` seam
  (`internal/media/packager.go`) anticipated exactly this third, post-package mode.
- **interfaces.md §10 amendment:** `PrepareAsset` implied packaging-time key injection (the
  ffmpeg-fused model). The Shaka reality is *post*-package: encrypt an already-finalized clear
  tree from `Finalize`'s tail. The interface landed with that meaning (wave C).
- **The CI-provable slice needs no media bytes.** Provider seam, NoDRM default, sealed key
  storage, `ScopeLicense`, and the ClearKey license endpoint (EME JWK set) are pure Go and gate
  in `make ci`. Everything asserting encrypted bytes is integration-tier (CI unit runners have
  no ffmpeg). This is why slices 0+1 (wave C) landed before any packager work.
- **Key management maps onto the existing KEK discipline exactly:** `internal/secretbox`
  (AES-256-GCM, `enc:` prefix, base64-of-32-bytes envs), validation in `config.validate()`,
  destructive-rotation guard in `cmd/vidra/setup.go` (`--rotate` + `--yes-i-know`). Decision:
  **`DRM_KEY_KEK` has no fallback to the federation KEK** — content keys are a separate trust
  domain. Content keys live sealed in a dedicated sidecar table (`video_drm_keys`, 0111);
  the plaintext never exists in a queryable column. KIDs are public and unsealed.
- **The one decisive unknown was tested, not assumed — verdict: ClearKey needs no Shaka.**
  A live Chrome experiment (2026-08-23, ffmpeg-8.1 CENC fixture, wrong-key negative control)
  proved hls.js 1.6.16 plays pssh-less CENC signaled only by a hand-injected `#EXT-X-KEY:...
  KEYFORMAT="org.w3.clearkey"`, via a ~6-line `drmSystems` `generateRequest` shim remapping
  `('cenc', null)` → `('keyids', {"kids":[...]})`. hls.js recovers the KID from the `tenc`
  box itself, so the EXT-X-KEY URI is an opaque identifier (never fetched for DRM keyformats).
  `SAMPLE-AES-CTR` and `SAMPLE-AES-CENC` behave identically (the `schm` box decides the
  scheme, not the method string). Findings that must shape slice 2: **every failure mode is
  silent** — no `hlsError`, buffer fills, `readyState` stays 0 — so ClearKey tests must
  assert decoded frames (`totalVideoFrames > 0`), never absence of errors; ffmpeg writes
  **no** EXT-X-KEY and **no** MPD ContentProtection even when encrypting, so Vidra injects
  the tag itself; and Chrome fires no `encrypted` DOM event for pssh-less CENC — the
  playlist-key route is the only ClearKey route. Shaka Packager buys ClearKey nothing; it
  remains required for Widevine/PlayReady (real pssh) and FairPlay (cbcs). Chromium-only
  proof; Safari ClearKey (sinf-preferring) is explicitly unpredicted. Experiment artifacts
  are preserved for the future integration fixture.
- **Item 7 (DRM + P2P) lost its subject.** The P2P research closed 2026-08-22 with DEFER — no
  `peer` source kind exists and phase 4 shipped no P2P. The item collapses to one standing
  invariant (recorded under item 7 below), not a work item.
- **The credentialed trap applies to DRM too:** the license request is a separate API call
  (headers fine); **media requests must stay bare** — a DRM design that attaches tokens to
  segment requests silently deletes CDN/presign delivery with no error and no failing test.

### Distributed topology (items 8–10)

- **Item 8 decomposes into S/S/M/L, not one lump:**
  - *Pool sizing (S — wave A):* `DB_MAX_CONNS`/`DB_MIN_CONNS`/lifetimes; validate `>= 2`
    because the leader elector pins a dedicated connection; pgx pool gauges (there were none —
    saturation was invisible); doctor check against server `max_connections`.
  - *Trusted-proxy/LB (S — mostly pre-existing):* `TRUSTED_PROXY_CIDRS` + rightmost-untrusted
    XFF walk landed earlier; every consumer goes through `c.RealIP()` (verified: rate limits,
    view counting, QoE digest; audit and logs deliberately carry no IP). What was missing:
    a **drain phase** (SIGTERM previously went straight to `Shutdown` while `/readyz` kept
    answering 200 — wave A adds a draining flag + `HTTP_DRAIN_DELAY`), and **`/readyz` treated
    Redis as fatal** — a Redis blip pulled *every* replica out of rotation simultaneously even
    though all rate limiters fail open on Redis (wave A: Redis degrades, PG still 503s, probe
    cached ~2s).
  - *Statelessness audit (M):* queues/leases/leader/JWT/OAuth-state/uploads/SSE are already
    replica-safe. **The real gap: three boot-loaded in-memory caches with no cross-process
    invalidation** — instance settings, ToS/privacy docs, branding — each reloads only on the
    replica that served the write; an admin change takes effect on 1 of N replicas until
    restart. Decision: a `settings_version` counter row + a 5–15s poller per replica (no new
    infrastructure, bounded staleness) — not LISTEN/NOTIFY (second pinned conn per replica),
    not Redis pub/sub (hard dependency on a correctness path). Also real: per-process
    rate-limit fallback multiplies budgets by N without Redis (document), and
    `STORAGE_BACKEND=local` requires a shared volume (wave A adds the boot warning for
    `role=worker` + `local`).
  - *Live-HLS externalization (L — the real cost of item 8):* the repackager the operations doc
    calls for **half-exists**: `internal/blobsink` (loopback HTTP origin streaming PUTs into
    `storage.Backend`, built because ffmpeg can PUT but not speak S3) + the ffmpeg HLS-muxer
    HTTP flags. Decision — **the bridge shape**: keep nginx-rtmp as pure RTMP ingest (`deny
    play`, no hls), push into a Vidra-supervised ffmpeg writing HLS through a blobsink **live
    mode that write-throughs playlists instead of coalescing them** (the exact opposite of the
    VOD mode), behind a `LIVE_STREAM_OUTPUT` toggle mirroring `TRANSCODING_STREAM_OUTPUT`.
    Rejected: sidecar volume-uploader (inherits inotify races, removes no coupling); native Go
    RTMP ingest is the honest long-term answer but is XL and belongs to item 10's "RTMP inside
    the managed edge". Non-negotiables: a **per-session ULID path component** (nginx-rtmp
    reuses segment names across broadcasts — any shared cache without it serves the *previous*
    broadcast's bytes), a live prefix **excluded from mediagc** (live objects have no video row
    and would read as 100% orphan to a destructive sweep), a versioned-bucket cost rule (a
    playlist write every 2s is a billable hidden version every 2s on B2 defaults), and the
    replay/recording path (`DirRecordingStore`, worker-side) migrating too or staying an
    explicit single-host opt-in. The nginx shim's hard-coded `proxy_pass http://api:8080` must
    become configurable regardless.
- **Item 9 ("hundreds of workers") — the claim path already scales; the periphery didn't.**
  Claims are correct at any N by construction (SKIP LOCKED + lease, soak-proven). What broke,
  fixed in wave B: lease sweeps were O(fleet × table) sequential scans (no `state='running'`
  index, not leader-gated, no LIMIT — concurrent sweepers serialized on row locks); no tick
  jitter anywhere (rolling deploys phase-lock the fleet); progress wrote one synchronous DB
  round-trip per percent (~1000 `job_events` rows/video, and DB latency back-pressured the
  ffmpeg stdout scanner — a positive feedback loop under load); and the `stale_running` gauge
  was a **permanent false-alarm generator** (`lease_expires_at` is never populated and renewals
  didn't touch `updated_at`, so every transcode >5 min reported stale). Still open, M/L-sized,
  in priority order: legacy queue tables have **no retention** (they grow forever and back
  every metric scan); worker identity (the `job_runs` worker/lease columns exist and are never
  written — you cannot ask "which worker has this job" or "which workers are alive");
  `VIDRA_WORKER_QUEUES` scoping (today every worker runs all ~23 pollers; GPU nodes cannot be
  dedicated); graceful drain for workers (SIGTERM burns one of five attempts per in-flight
  job per deploy — separate infra-abandonment from job failure before running spot fleets);
  cross-job scratch reservation (16 jobs can each "fit" in the same free bytes; `--scale`
  replicas share one `transcode_tmp` volume); fairness (strict FIFO — one bulk import
  monopolizes the fleet); LISTEN/NOTIFY wake (100 idle workers currently cost steady poll QPS);
  and PgBouncer guidance (advisory locks and the elector's session-scoped lock do **not**
  survive transaction pooling naively). **Segment-parallel encoding stays a documented later
  optimization:** the fan-out/join vocabulary already exists in the `job_runs`/`pipeline_runs`
  projection — but as a trigger-fed read-only projection; there is no claimable child-work
  table or join barrier, and `TranscodeAll` was deliberately fused into one decode pass —
  distributing it gives that saving back. Don't build it until a real fleet is starved.
- **Item 10 (multi-region) — the phase-2 machinery is a mover, not a replicator.** The
  migration engine is one-shot, single-active (partial unique index), phase-inferring, and
  ends by deleting the source. What transfers: `CopyOnce`'s SKIP-LOCKED+lease claim and
  `copyAndVerify`'s re-hash verification, reused over a new per-region ledger
  (`object_key × region`), fed by an event-driven enqueue seam (the ipfsmirror hook pattern),
  not by periodic re-enumeration. Three traps that must shape it: **never model permanent
  replication as a `STORAGE_MIGRATION_TARGET_*`** (configuring a migration target switches
  presign off entirely, forever, with only a boot log line); **a replica bucket filled without
  stamping `.vidra/owner` silently degrades media GC to dry-run forever** (the marker is only
  stamped by `adoptDestination` today — replication jobs must stamp it explicitly); and
  **storage keys must stay byte-identical across regions** (the pin ledger PKs on the key;
  a region prefix would force a coupled ledger migration). Region-aware *delivery* needs a
  viewer→region signal that does not exist (nothing maps IP→region) and a QoE dimension for
  it — both genuinely new. **RTMP inside the managed edge is XL and explicitly deferred** —
  it is the native-Go-ingest rewrite, and nothing smaller substitutes.

## Work items

### Multi-CDN & steering

- [ ] **1. Multiple delivery paths per asset** — *resequenced; the steering doc's P0–P3 are
  this item's true order.* (a) **P0: generation-addressed HLS keys** for every packaging run
  (fixes the live unversioned-edge-key gap; content replacement stops needing purge); (b)
  **P2: plurality** — `DELIVERY_CDN_*` becomes an id'd list capped at 8, boot-validated, N=1
  byte-identical to today; (c) **P3: QoE pathway dimension** (sparse `pathway` column,
  schema-CHECK backstop + boot-capped config as the real bound, ~2.2× rollup-row ceiling);
  (d) health via the `searchclient/prober` pattern behind a `func() Health` seam preserving
  `internal/delivery`'s import purity — **constraint from the steering doc: pathway health
  must be measurable without routing a viewer to a pathway believed broken** (server-side
  probes, never sacrificial viewers); (e) the consumer stops discarding the tail —
  server-side that means *choosing* better, not offering more. Latency/region/cost/capacity
  signals beyond health stay deferred until a data source exists.
- [ ] **2. Standards-based content steering** — **research half CLOSED 2026-08-23. Verdict:
  BUILD, conditional on P0–P3, sequenced behind item 1** —
  [content-steering-decision.md](content-steering-decision.md). Shape B (pathway cloning);
  attributes synthesized at the per-request rewrite in **both** master paths (native +
  imported-PeerTube), injected *after* the rewrite (the unanchored `URI="` regex would
  version-stamp the steering URI); stable per-video `steering.json` under the `Eligible`
  fence; runtime switch drains through `PATHWAY-PRIORITY: ["VIDRA-ORIGIN"]`, **never `410`
  and never `429`** (both permanently end steering for an hls.js session); the
  `VIDRA-ORIGIN` clone carries an explicit origin marker so a failed-over client isn't 307'd
  back to the CDN that just failed; hls.js bump to ≥1.7.1. **The minimal first slice is
  P2+P3 with no steering at all** — make "is the second CDN better?" answerable first.
  DASH steering: structurally out (see ground truth).
- [ ] **3. Origin shielding / regional failover** — shield tier is documentation + config
  (key-addressed CDN origin). Code: per-pathway purge fan-out; failover gated on item 1c
  health. **Gate for 1–3: wire and exercise `Purge` call sites** (delete + privacy flip) —
  the phase-4 carry-forward; nothing may become shared-cacheable before it. *Wired
  2026-08-28 (core#117: delete + privacy flip + block; core#120 completeness: channel
  cascade, avatars/banners, playlist covers; core#121: `cdn_purge` outcome counters on
  /admin/system as the exercise evidence); "exercised against a live edge" remains open,
  so header promotion stays gated.*

### DRM

- [ ] **4. `DRMProvider` interface** — **slices 0+1 BUILT (wave C, this session):**
  `internal/drm` modeled on `internal/cdn` (typed three-method §10 shape; `PrepareAsset`
  documented as post-package for the Shaka path), `NoDRM` default with a raw-body regression
  test that the session JSON is byte-identical to pre-DRM output, `ClearKeyTest` provider
  (inert until keys exist), migration 0111 `video_drm_keys` (sealed under `DRM_KEY_KEK`,
  no-fallback), `playback.ScopeLicense`, `POST /api/v1/videos/:id/license/clearkey` (EME JWK
  set, auth = `videoVisibleForMedia` parity). Remaining: slice 2 (manifest signaling + player
  `drmSystems` wiring — **unblocked: the ClearKey experiment proved the ffmpeg-CENC lane
  works**, see ground truth; the player shim is ~6 lines behind the DRM flag, tests must
  assert decoded frames). Scope boundary: the experiment licenses ffmpeg CENC for the **CI
  fixture and the ClearKeyTest lane only** — production encryption stays Shaka-gated (item
  5's disqualifiers stand: derivative corruption, one key per tree, clear trick-play; if
  ClearKeyTest ever encrypts a real video's tree, derivative/trick-play production must be
  disabled for that video first). Then ExternalMultiDRM / Widevine / PlayReady / FairPlay as
  config over slice 3.
- [ ] **5. Common Encryption (CENC) at the packager** — **rescoped: this is the Shaka
  Packager item.** A third `Packager` mode: post-package transmux+encrypt over the finalized
  clear tree (pinned ~10 MB static binary; stream-copy, not re-encode). This is where
  per-track keys, rotation, `pssh`, real `<ContentProtection>`/`#EXT-X-KEY` signaling, and
  `cbcs`/FairPlay all arrive at once. ffmpeg-fused CENC is **disqualified** (derivative
  corruption, one-key-per-tree, no signaling, no cbcs — see ground truth). Derivative
  production order (progressive MP4s, audio.m4a before encryption) is part of this item's
  correctness surface, as are the hls.go filename allowlist + mediagc key grammar (updated
  **together**, per doctrine) if any new file shape appears.
- [ ] **6. Key management** — **core BUILT (wave C):** sealed sidecar + `DRM_KEY_KEK` under
  the full KEK discipline (env-only, validated, `--rotate`+`--yes-i-know` guard, compose
  anchor). Remaining: external KMS/HSM providers as `ExternalMultiDRM` config (CPIX — Shaka
  speaks it natively), license issuance already wired through the session API by construction.
- [ ] **7. DRM + P2P compatibility** — **collapsed to an invariant** (P2P was deferred with no
  peer source kind): *peers may exchange already-encrypted segments; peers never exchange
  keys; license requests always hit the license service.* If P2P is ever revisited, its
  decision doc must test actual browser/platform EME behavior before claiming support. No
  work item remains.

### Distributed topology

- [ ] **8. Multi-node API** — **floor BUILT (wave A, this session):** pool sizing env keys +
  pool gauges + doctor check; drain phase (`HTTP_DRAIN_DELAY`, `/readyz` 503-while-draining);
  `/readyz` Redis-degrade + 2s probe cache; worker+local-storage boot warning. Remaining:
  (a) ~~settings/docs/branding cache invalidation via `settings_version` poller~~ **DONE
  2026-08-28 (core#115, migration 0121)**; (b) ~~an operations.md "behind a load balancer"
  section~~ **DONE 2026-08-28 (core#118)**; (c) live-HLS externalization via the **bridge
  shape** (L — see ground truth;
  includes the per-session path ULID, mediagc exclusion, replay path, and shim endpoint
  configurability).
- [ ] **9. Worker fleets** — **floor BUILT (wave B, this session):** running-state sweep
  indexes (0110), sweep LIMIT+SKIP LOCKED, leader-gated recovery sweep, ticker jitter,
  progress-write throttle, `stale_running` gauge fix, stale-comment corrections. Remaining
  (priority order): queue-table retention; worker identity (populate the dead `job_runs`
  worker/lease columns); `VIDRA_WORKER_QUEUES` scoping; worker graceful drain +
  infra-abandonment vs job-failure separation; cross-job scratch reservation (and admission
  control for `videoimport`, which has none); fairness; LISTEN/NOTIFY wake; PgBouncer
  guidance. Segment-parallel single-title encoding: documented later optimization, not
  scheduled.
- [ ] **10. Multi-region** — design constrained by ground truth above: per-region replication
  ledger reusing `CopyOnce`/`copyAndVerify`, event-driven enqueue, explicit `.vidra/owner`
  stamping, byte-identical keys, **never** modeled as a permanent migration target; regional
  delivery gated on a viewer→region signal + QoE dimension that don't exist yet; failover
  runbook extends the validated env-swap cutover motion (note: a multi-instance rolling
  cutover has never been exercised). **RTMP inside the managed edge: XL, explicitly
  deferred** — it is the native ingest rewrite.

## Build order (decided 2026-08-23 from the recon above)

```text
WAVE A  multi-node API floor ──┐  (pool, drain, readyz, warnings)          [landed this session]
WAVE B  worker fleet floor ────┤  (sweeps, jitter, throttle, gauge fix)    [landed this session]
WAVE C  DRM slices 0+1 ────────┤  (internal/drm, keys, license endpoint)   [landed this session]
                               │
   settings-cache invalidation ├─►  N-replica api is CORRECT, not just safe
   purge call-site wiring ─────┤    (gate for anything shared-cacheable)
   QoE pathway dimension ──────┤
                               ├─►  item 1  plurality + health ─► item 3 failover
   steering decision doc ──────┘         │
        (research done)                  └─►  item 2  first steering slice (HLS, ≥2 CDNs)
                                                    
   ClearKey experiment verdict ──►  item 4 slice 2 (signaling + player) ──►  item 5 Shaka CENC
                                                                                  │
   live bridge (8d) ── independent, L                                             └─► FairPlay et al.
   item 10 design doc ── after 8d lands (live is the hardest regional constraint)
```

- **The floor before the modules** — every module assumes replicas behave and measurements
  exist.
- **QoE pathway dimension before item 1's signals** — or the signals ship with no storage.
- **Purge wiring before anything becomes shared-cacheable** — unchanged phase-4 gate.
- **The steering slice after plurality** — a steering manifest with one pathway is a no-op.
- **Shaka (item 5) after the ClearKey slice proves the license plumbing end-to-end** — and
  FairPlay/multi-DRM only ever on top of Shaka.
- **Item 10 last** — it composes item 8's externalized live plane, item 9's fleet, and item
  1's delivery plurality; designing it earlier would re-litigate all three.

## Exit criteria

- A deployment can run: managed PG + S3 + 2 CDNs with steering + DRM-protected premium content +
  worker fleet — configured entirely through providers/config on stock Vidra images.
- The Simple tier install remains byte-identical in experience.
- *Measurability note (2026-08-23):* "2 CDNs with steering" is now demonstrable per-pathway only
  after the QoE pathway dimension lands; until then the admin playback-health page cannot
  distinguish the CDNs it is steering between.
