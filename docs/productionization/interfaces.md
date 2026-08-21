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

New `internal/delivery` package in vidra-core, consulted by `internal/httpapi` at URL-mint time
(hls.go `hlsDetail`, videos.go, downloads.go). Returns an ordered source list
(`api-proxy | presigned | cdn | ipfs-gateway`) with **api-proxy as the permanent authoritative
fallback** — modeled on `redirectPublicIPFS`'s fail-open-to-authoritative pattern. CDN providers
plug in here later; **purge hooks are part of the interface from day one** (precondition for
promoting versioned HLS from private to shared caching).

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
0083 lease columns remain trigger-fed display only. Still open from this section: the
worker-role flag port (phase-3 item 8).

## 8. Player engine adapter (Phase 4 prep; the cheap part is early)

Collapse the three hls.js lifecycles (`lib/use-hls-playback.ts`, `use-live-playback.ts`,
`use-remote-playback.ts`) into one engine-adapter module behind the existing narrow
`HlsPlayback` interface, and re-key quality identity from hls.js level *index* to
height/track-id (touches `lib/hls.ts` AUTO_LEVEL, `lib/player-settings.ts` matchQualityLevel,
QualityMenu). This is the entire prerequisite for a later Shaka/DASH/EME swap and gives QoE
instrumentation a single interception point. The bespoke shell (`components/player/`) is the
mandated UI; engines swap under it.

## 9. QoE event pipeline (Phase 4 seam; architecture decided now)

QoE is an **event/rollup stream, never Prometheus labels** (bounded-cardinality rule). Ride the
searchevents outbox pattern (`internal/searchevents`) with the `lib/search-events.ts`
batched-keepalive transport on the client, keyed by the playback-session id, with the sha256
viewerKey precedent for privacy. hls.js LEVEL_SWITCHED/FRAG_BUFFERED/error handlers in the
unified engine adapter are the capture points.

## 10. DRM provider interface (Phase 5; shape only)

```go
type DRMProvider interface {
    PrepareAsset(...)          // CENC keys/PSSH at packaging time
    GetProtectionMetadata(...) // what the player/manifest needs
    LicenseConfiguration(...)  // license-service endpoints for the session API
}
```

Providers: NoDRM (default), ClearKeyTest, ExternalMultiDRM, then Widevine/FairPlay/PlayReady
integrations. Hard prerequisites in order: CMAF packaging (Phase 3), engine abstraction with a
FairPlay path for the MSE-less iOS native-HLS branch, playback sessions for license issuance.
Content keys never in the normal DB; the existing KEK discipline (env-only, validated,
destructive-rotation warnings) is the pattern for content-key KEKs. Peers may exchange
encrypted segments; peers never exchange keys.
