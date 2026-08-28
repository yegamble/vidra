# Interface seams

The seams that must be cut early (mostly Phase 1–2) so Phases 3–5 are additions rather than
rewrites. Each entry says where the seam lives given the *existing* code, and which phase
consumes it. "Cut now" means: define the interface and route existing behavior through it, even
if only one implementation exists.

## 1. Setup/config engine boundary (Phase 1, permanent)

`internal/config/config.go` remains the **single boot-time engine**. The setup engine
**generates env files** in the existing fail-loud template format — it never becomes a fourth
live config source. `internal/instancesettings` remains the single metadata backbone for wizard
*and* admin-UI field rendering. The env-vs-DB doctrine (secrets/boot-unsafe values never enter a
queryable table; effective = setting AND boot) is a hard line every new area (storage creds,
CDN keys, DRM KEKs) must respect — new infra admin pages are read-only visibility + guidance,
not hot-editable credentials.

Conceptually the engine is:

```go
type SetupService struct {
    Validator             // callable per-field validation (extracted from config.validate() + instancesettings validators)
    DependencyManager     // docker/compose/disk/DNS preflights (shared with doctor)
    ConfigurationManager  // generates env/production.env + Caddyfile; never regenerates KEKs
    StorageConfigurator   // local | s3 answers → env + compose profiles
    DatabaseConfigurator  // local | external postgres answers → env + compose profiles
    ProxyConfigurator     // managed-caddy | external | nginx-template | plain-http
    MediaConfigurator     // ladder/codec/hw-accel policy defaults
}
```

Web wizard, CLI wizard, and non-interactive installer all call this one service.

## 2. Storage `Presigner` capability (Phase 2 seam; cut with Phase 2's first change)

*Shipped 2026-08-20 (lean-S3 wave, `1485eac`), ahead of phase 2.* `Presigner` sits next to
PathProvider/ObjectLister/PrefixDeleter/SizedPutter in
`vidra-core/internal/storage/storage.go`; s3.go implements it via minio `PresignedGetObject`;
local.go simply doesn't. First consumer is ffprobe's source-open ladder
(`internal/media/ffprobe.go` — local path → presigned URL → download, presign failure
non-fatal), which is the feature-detect + fail-open shape the §4 resolver should copy.
**Never fold delivery/CDN concerns into `Backend` itself.**

## 3. Per-object location record (Phase 2 schema seam)

Keep `storage_key` columns opaque/relative (migration 0008 doctrine). Plan an object-location
record (table or column) rather than URLs in the DB — URLs are already always minted at
response time, so delivery-source changes need zero data migration if this rule is preserved.
Storage-migration jobs and dual-read logic hang off this record. Also required first:
content hashes (nothing computes/stores a checksum today — integrity-verified migration has no
foundation without them).

## 4. Delivery-source resolver (Phase 2/4 seam)

New `internal/delivery` package in vidra-core. *Corrected 2026-08-23 (was stale):* the resolver
is consulted at **byte-serve time** in `serveMediaAsset` (11 call sites), **not** at URL-mint
time — `hlsDetail`, videos.go and downloads.go still mint plain origin-relative paths. Returns
an ordered source list (`api-proxy | presigned | cdn | ipfs-gateway`) with **api-proxy as the
permanent authoritative fallback** — modeled on `redirectPublicIPFS`'s
fail-open-to-authoritative pattern. CDN providers plug in here (landed core#76); **purge hooks
are part of the interface from day one** (precondition for promoting versioned HLS from private
to shared caching). *Updated 2026-08-28:* `Purge` call sites LANDED — core#117 wired the three
moments (video delete, privacy flip away from public, admin block) and core#120 completed the
seam (channel-deletion cascade incl. the channel's images, avatar/banner set/delete, playlist
cover set/delete/visibility-flip; `media_purge.go`'s header carries the canonical still-unpurged
ledger: thumbnail/storyboard replacement, account deletion, same-generation re-transcode).
Outcome counters surface on `GET /api/v1/admin/system` (`cdn_purge`, core#121). The remaining
gate on header promotion is purge being **exercised against a live edge** plus phase-5 item 1a
(generation-addressed keys) — no longer purge wiring.

## 5. Playback session endpoint (Phase 4 consumer; stub early)

`POST /api/v1/videos/:id/playback-session` in `internal/httpapi`, generalizing the
password-unlock flow and extending `internal/playback/token.go` with scope/session claims
(not replacing its HMAC design). Initially it returns today's `hls_url` + optional token — the
point is that `vidra-user/lib/api/endpoints.ts` and the player consume a **session object** from
day one, so signed URLs, CDN steering, DRM license context, and QoE session ids all land behind
an API the player already calls. Mint-time auth must reproduce `videoVisibleForMedia` /
`videoForDownload` semantics exactly.

## 6. Packager interface (Phase 3 seam; two pre-cuts land earlier)

Split encode from package inside `vidra-core/internal/media` — encode produces per-rung
outputs; a `Packager` interface (ffmpeg-TS default first, CMAF/Shaka-style later) owns segment
tree + manifest emission. Keep the pure-argv-builder + integration-tag test pattern.

Two cheap pre-cuts to make **before** Phase 3 so it isn't a rewrite:
- (a) route all master-manifest emission through `renderMasterPlaylist` behind an interface
  that can carry CODECS attributes;
- (b) kill the hidden H.264-Main coupling in `parseH264CodecString` (media/hls.go), which
  currently dead-letters any non-Main output — this also unblocks hardware encoders.

Downstream contract: URIs stay relative so the `httpapi/hls.go` rewrite proxy keeps working;
new file shapes must be added to the hls.go filename allowlists and the mediagc key grammar
**together**.

## 7. Worker claim + role convention (cut now, before any new queue is born)

Every **new** queue standardizes on the `media_ipfs_pins.sql` pattern
(`FOR UPDATE SKIP LOCKED` + lease-seconds visibility timeout + state-guarded terminal writes).
Port vidra-search's `SEARCH_WORKERS_ENABLED` / `SEARCH_RUN_JOB` env seams into vidra-core as
the worker-role flag (same binary, role env). Phase 2 storage-migration jobs and Phase 3
packaging jobs must be *born* on this convention.
*Update 2026-08-21: the retrofit already landed* — the 9 legacy claims lease
(`5ead076`/`b57a1d1`), the boot blanket-requeue became lease-expiry sweeps (`2763495`), the
sweep-only crons are leader-elected (`9a0ddbd`), and claim ORDER BYs are total orders
(core#56: `created_at, id` on UUID-keyed queues — `ORDER BY id` alone would be random there).
Note the leases live on the *legacy queue tables* as `next_attempt_at` pushes; `job_runs`'s
0083 lease columns are declared but unpopulated — nothing writes them, not even the projection
triggers; populating them is phase-5 item 9's worker-identity work. *Update 2026-08-23:* the worker-role flag
port **also landed** — `VIDRA_ROLE` = `all|api|worker` (`internal/config/config.go:28-67`,
`RunsWorkers()`/`ServesHTTP()`), documented in operations.md; api-only processes deliberately
do not stand for cron leader election. Nothing from this section remains open. (Fleet-scale
follow-ups — sweep indexes, jitter, `stale_running` gauge fix — are phase-5 item 9.)

## 8. Player engine adapter (Phase 4 prep; the cheap part is early)

Collapse the three hls.js lifecycles (`lib/use-hls-playback.ts`, `use-live-playback.ts`,
`use-remote-playback.ts`) into one engine-adapter module behind the existing narrow
`HlsPlayback` interface, and re-key quality identity from hls.js level *index* to
height/track-id (touches `lib/hls.ts` AUTO_LEVEL, `lib/player-settings.ts` matchQualityLevel,
QualityMenu). This is the entire prerequisite for a later Shaka/DASH/EME swap and gives QoE
instrumentation a single interception point. The bespoke shell (`components/player/`) is the
mandated UI; engines swap under it.

## 9. QoE event pipeline (Phase 4 seam; BUILT 2026-08-23, core#77)

QoE is an **event/rollup stream, never Prometheus labels** (bounded-cardinality rule). That part
held. **All three of this section's other prescriptions turned out to be wrong when checked against
the code, so they are corrected here rather than left to mislead:**

- ~~"Ride the searchevents outbox pattern"~~ — `search_outbox` is an *egress queue to an external
  service* and **prunes nothing**; there is no DELETE against it anywhere. Fine at search volume,
  not at playback volume. The shipped shape is **raw (7d) → hourly rollup (90d) → leader-elected
  prune**, with retention modelled on `jobstatus.Prune`, not on searchevents.
- ~~"the sha256 viewerKey precedent for privacy"~~ — that is not a precedent to follow. `viewerKey`
  is a bare **unsalted** `sha256("ip:"+RealIP)`, trivially reversible against a known IP, and it is
  safe only because it is **never persisted** (a Redis key fragment with a 1h TTL). What shipped is
  a **keyed** digest off `JWT_SECRET`, scoped to a single UTC day: within a day two events from one
  viewer are recognisable as one viewer, across days nothing links, and rotating the secret
  re-derives the key so digests either side of a rotation never correlate.
- ~~"keyed by the playback-session id"~~ — sound, with a caveat the section could not have known:
  core#74 created no session table, so on a non-password video the session id is **client-asserted**.
  The beacon may carry the playback token, and the server records `session_verified` so an admin can
  see what fraction of the numbers are attested. On a normal public catalogue that fraction is 0 —
  and being visibly 0 is the honest form of the same fact.

The client transport prescription **does** hold: the `lib/search-events.ts` batched-keepalive shape
is the right one to copy.

**Percentiles do not merge** — the one arithmetic fact this seam turns on. "Per source for the last
24h" spans 24 hourly rows × engines × formats, so rollup rows store a **fixed-boundary histogram**
alongside the p50/p95/p99 columns. Averaging percentiles would be meaningless and re-scanning raw
would defeat the rollup; histograms merge exactly, cost O(1) memory with no sampling cap, and keep
the arithmetic in Go where CI can prove it without a database.

**Capture point:** the unified engine adapter (`lib/use-playback-engine.ts`, user#61) — which did
not exist when this section was written and is why item 4's client half was sequenced behind item 3.
Note one dimension is structurally unknowable: on native HLS the browser owns variant selection via
the manifest `SCORE` attribute, so **"selected rendition" is permanently null for that engine** and
must be modelled as a first-class unknown rather than a missing value.

## 10. DRM provider interface (Phase 5; shape landed 2026-08-23)

```go
type DRMProvider interface {
    PrepareAsset(...)          // CENC keys at packaging time — see amendment below
    GetProtectionMetadata(...) // what the player/manifest needs (nil = clear)
    LicenseConfiguration(...)  // license-service endpoints for the session API (nil = none)
}
```

Providers: NoDRM (default), ClearKeyTest, ExternalMultiDRM, then Widevine/FairPlay/PlayReady
integrations. Content keys never in the normal DB; the existing KEK discipline (env-only,
validated, destructive-rotation warnings) is the pattern for content-key KEKs — with **no
fallback to the federation KEK** (content keys are a separate trust domain).

*Amendments 2026-08-23, from recon + empirical ffmpeg verification (phase-5 doc has the full
evidence):*
- **`PrepareAsset` is post-package, not packaging-time.** ffmpeg-fused CENC is disqualified
  (one key per tree, no `pssh`, no manifest signaling, no `cbcs`, and the derivative
  remux chain silently emits encrypted garbage with exit 0). If CENC ships, Shaka Packager
  ships with it, as a transmux+encrypt pass over the finalized clear tree from `Finalize`'s
  tail — cheaper than the cmaf-decision doc's mezzanine headline because the encode already
  happened.
- **FairPlay requires `cbcs` and is therefore Shaka-gated**, not engine-adapter-gated. The
  "engine abstraction with a FairPlay path" prerequisite was half-stale: the adapter and the
  native-HLS branch exist; zero EME code exists in vidra-user.
- The former "peers never exchange keys" clause is the sole survivor of phase-5 item 7 (P2P
  was deferred with no peer source kind): *peers may exchange already-encrypted segments;
  peers never exchange keys; license requests always hit the license service.*
- Slices 0+1 landed (phase-5 wave C): `internal/drm` modeled on `internal/cdn`, `NoDRM`
  byte-identical session JSON, sealed `video_drm_keys` sidecar under `DRM_KEY_KEK`,
  `playback.ScopeLicense`, ClearKey license endpoint.
