# Architecture today (audit snapshot, 2026-08-19)

Produced by a 12-area repository audit. Derive planning from this document plus the code, not
from older prose. Paths are relative to the meta-repo unless prefixed with a repo name.

**Corrections since the snapshot (2026-08-23):** the queue-claim sentence below is stale — the
lease retrofit landed 2026-08-21 (all 13 durable queues now claim with `FOR UPDATE SKIP
LOCKED` + lease; ~11 sweep-only crons are leader-elected; 2-replica soak: 406/406, 0 dupes),
and `VIDRA_ROLE` (`all|api|worker`) landed with it. The delivery sentence is also stale —
phase 4 shipped playback sessions, a CDN provider behind the resolver, the unified engine
adapter, and QoE beacons/rollups (six of seven items merged 2026-08-23; still true: no P2P —
deferred by decision — and no EME/DRM in the player). Phase-5 recon corrections live in
`phase-5-enterprise.md`.

## System shape

Three standalone public repos — `vidra-core` (Go API), `vidra-user` (Next.js), `vidra-search`
(Go) — tied by this meta-repo, whose `docker-compose.yml` `include:`s
`vidra-core/docker-compose.yml` (with a load-bearing `env_file: /dev/null` guard so a stray
`vidra-core/.env` cannot poison substitutions) and adds the frontend, search, and search-migrate
services.

**Deployment today** (operator-heavy; bash + make + compose expertise is load-bearing):
git clone meta-repo → `bootstrap.sh` clones the three sub-repos (`VIDRA_REF` pins release tags)
→ hand-edit the 386-line `env/production.env` (6+ openssl-generated secrets, 3 image tags) and
the `deploy/Caddyfile` domain → `deploy/deploy.sh` runs the gated pipeline: Compose ≥ 2.24
refusal, integrity-checked pre-deploy pg_dump that **aborts on failure**, pull-before-stop, two
exit-code-gated golang-migrate one-shots with `schema_migrations` version+dirty verification,
`up -d --no-build`, `/readyz` probes. No auto-rollback — failed probes leave the broken release
running.

**Images:** `ghcr.io/yegamble/{vidra-core,vidra-user,vidra-search}:vX.Y.Z`, built only from
tags. The vidra-user image is permanently baked to one origin at build time
(`NEXT_PUBLIC_API_BASE_URL` inlined by `next build`; gated in its publish workflow) — the
single biggest no-fork blocker, being fixed first in Phase 1.

**Edge:** Caddy is the only internet-facing service (80/443). Single-origin path routing:
`/api/*` + federation surfaces → api:8080, everything else → frontend:3000. Postgres/redis/
search are unpublished; api/frontend loopback-only via `!reset`/`!override` compose tags
(silently ignored by Compose < 2.24 — hence the hard version refusals). Exception: live RTMP
publishes raw 0.0.0.0:1935 around the edge (see risks).

**Config:** env-only `config.Load` (~120-field monolith with strong fail-fast `validate()`,
production hard-refusals) plus `internal/instancesettings` — a 109-key typed, validated,
runtime-mutable DB-overlay registry with page/section metadata that auto-renders the admin
config UI. Secrets and boot-unsafe values deliberately stay env-only. Runtime knobs reach
workers through provider-func closures, never boot-baked.

**First admin:** whoever registers first on an empty users table
(`internal/auth/service.go`) — a live security race. Being replaced by an owner-claim token in
Phase 1.

**Media:** chunked resumable upload or yt-dlp import → ClamAV scan + ffprobe → durable Postgres
transcode queue → in-process ffmpeg encodes: fixed-bitrate H.264 Main ladder emitted directly
as MPEG-TS HLS (packaging fused into the encode pass in `internal/media/hls.go`), plus
progressive MP4s, trick-play I-frame rendition, optional VP9 download. No CMAF/fMP4 (except
pass-through PeerTube imports), no DASH, no hardware acceleration. Ladder planning is
input-aware (never upscales, native fallback rung, fps cap).

**Storage:** one global `storage.Backend` (local | s3 via minio-go) under opaque relative keys.
A destructive daily media-GC sweep runs unconditionally (Phase 2 landmine).

**Delivery/playback:** every media byte proxies through the Go API
(`serveStoredObjectNamed`, per-request DB-backed auth); playlists rewritten in flight
(`?pt=` HMAC token for password videos, `?v=` generation cache keys; Cache-Control deliberately
private). IPFS is a mirror sidecar with a gateway-override player path. The frontend player is
a bespoke shell (`components/player/`) over dynamically-imported hls.js with tuned ABR,
progressive fallback and per-user settings. No playback sessions, signed URLs, CDN, P2P,
EME/DRM, or QoE beacons.

**Workers:** ~17 ticker-driven workers run as goroutines inside the single api process. Durable
Postgres queues with backoff/dead-letter, but 9 of ~11 queues have single-process-only claim
queries; one queue (`media_ipfs_pins`) already uses the multi-node-safe
`FOR UPDATE SKIP LOCKED` + lease pattern and is the documented template.

**Ops:** nightly DB-only backup (integrity-checked, retention, off-site, dead-man ping);
tag-flip rollback protected only by a documentation-only one-release schema-compat policy;
strong bounded-cardinality metrics/audit/job-run observability (shipped 2026-07).

**CLI:** `vidra-core/cmd` carries `api`, `peertube-import` and `vidra` — the operator CLI
(`setup`, `doctor`, `status`, `logs`, `restart`, `update`, plus thin wrappers over the deploy
scripts), shipped as a checksum-verified release asset. The meta repo has `install.sh`
(`curl … | sh`), `deploy/provision.sh` and a cloud-init template. The terminal setup wizard is
done; the *web* wizard is still only its owner-claim step. See the phase-1 worklist for what
each command does and what remains open.

## Do-not-touch inventory

Battle-tested code and decisions that the program wraps or extends, never rewrites:

### Deploy & compose
- `deploy/deploy.sh` ordering and gating (dump-abort → pull-before-stop → discrete gated
  migrators → ledger assertion → `up -d --no-build` → probe-or-fail). Wrap in the CLI.
- `docker-compose.prod.yml` security architecture: `!reset`/`!override` loopback/closed
  publishes as the real firewall, Caddy-only 80/443, redis requirepass, `${VAR:?}` render
  asserts, prep-volumes uid-10001, log caps, named volumes incl. `caddy_data` (Let's Encrypt
  rate-limit protection).
- The Compose ≥ 2.24 hard refusal replicated across deploy.sh/rollback.sh/restore.sh — guards a
  silent database-on-the-internet failure. **Every new entrypoint must carry it.**
- meta-ci's rendered-config assertions (prod-ports-closed PyYAML check, every-Go-config-key-
  has-a-compose-consumer check, production-mode boot job). Installer changes keep these green.
- Single-origin path-routing (`deploy/Caddyfile` + `PUBLIC_BASE_URL` rationale) and its
  `/metrics` + `/api/v1/dev/*` edge 404s and no-compression-on-api-routes rule. Template the
  domain in; never re-architect.
- The `env_file: /dev/null` include guard and the fail-loud env-template design. Wizard
  generates *into* this format.
- `deploy/backup.sh` (.part-then-rename, pg_restore -l verification, retention, last_success,
  dead-man ping); restore.sh's validate-before-drop; the read-never-source `env_get` pattern;
  Makefile CONFIRM/typed-word destructive-target conventions.
- `release.sh` preflight-then-verify (tag-free-everywhere, GHCR manifest-inspect) and
  publish-container.yml's tag-only/never-main guarantee with deterministic version ldflags
  (vidra-core's is the template to copy to vidra-search).
- Two-ledger migration design (`schema_migrations` vs `vidra_search_migrations`) and sqlc.yaml's
  schema-from-migrations single source of truth.

### Backend
- `internal/storage/storage.go` Backend interface + optional-capability pattern
  (PathProvider/ObjectLister/PrefixDeleter); s3.go's deliberate non-PathProvider stance with
  the temp-download fallback. New providers/capabilities slot in.
- Relative, backend-opaque `storage_key` columns ("opaque to the database", migration 0008) and
  the key-layout authority at `vidra-core/.ralph/specs/storage-layout.md` incl. the
  sweptPrefixes+reference-query GC rule.
- `internal/store/queries/media_ipfs_pins.sql` claim pattern (FOR UPDATE SKIP LOCKED + lease
  visibility-timeout + state-guarded terminal writes) — canonical template for every new queue.
- `internal/instancesettings` specs registry and the env-vs-DB doctrine (secrets/boot-unsafe
  values env-only; effective capability = setting AND boot). The wizard's metadata backbone.
- The provider-func seam pattern in `cmd/api/main.go` (runtime settings read at request/job
  time through closures, never boot-baked).
- `internal/playback/token.go` (HMAC domain separation, constant-time verify) — extend with
  claims, don't replace.
- The `httpapi/hls.go` m3u8 rewrite pipeline: `?pt=` propagation + `?v=` generation-versioned
  immutable cache keys — exactly what makes future shared-CDN caching possible.
- `internal/httpapi/routeclass.go` template-based media-route classification with its
  registration-proving test.
- The layered auth gates `videoVisibleForMedia` / `videoForDownload` (leak-safe check order) —
  any signed-URL/session scheme reproduces these at mint time.
- The source-version/HLS-generation key scheme (`web-videos/<id>.rN<ext>` →
  `streaming-playlists/<id>/rN/` with DB promotion in `transcode.storeResult`).
- `internal/transcode/service.go` durable queue design (detached bookkeeping context,
  backoff/dead-letter, per-tick runtime gates, publish-after-transcode hold hooks) and
  `upload/service.go`'s chunked-resume protocol.
- Observability discipline: bounded-cardinality private registries, audit envelope allowlists +
  sensitiveKeys denylist with static guard test, jobstatus REST+SSE cursor-replay + redaction,
  end-to-end correlation-id chain.
- The IPFS mirror's authority-vs-distribution split (default-deny eligibility, fail-closed
  network routing) — this IS the separated peer-delivery concept; never collapse into Backend.
- `internal/httpapi/server.go` trusted-proxy IP extraction and credentialed-CORS allow-list;
  `secure_headers.go` semantics (the deliberate plain-HTTP-mode change is an explicit, gated
  modification).

### Frontend
- The bespoke VideoPlayer shell (`components/player/*`) — mandated custom player; engines swap
  *under* it. Also `lib/hls-bandwidth.ts` (persisted ABR seed + data-saver caps) and the
  degrade-not-die fallback ladders.
