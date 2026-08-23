# Phase 3 — Media pipeline modernization

**Outcome:** encode once, package many — CMAF/fMP4 as the preferred packaged representation
with HLS and DASH sharing segments; codec profiles beyond H.264 Main; hardware acceleration
offered when detected; workers that scale from 1 to many without redesign. Ordinary installs
keep getting compatible H.264 HLS by default.

## Status 2026-08-22 — all 8 items BUILT + E2E-VALIDATED; merges pending

Items 2, 9, 10, 11 are closed on main. Items 1, 3–8 are complete, adversarially verified, and
E2E-validated against a real stack, sitting as a PR set awaiting merge **in this order**:

1. **core#64** (carry-forwards: S3→S3 size hint + doctor bundled-Postgres fallback) and
   **core#71** (pre-existing: transcodes >10s left `running` 30 min — bookkeeping context
   created before the encode; found by this phase's validation) — independent, merge anytime.
2. **core#65** (item 8, VIDRA_ROLE worker split) **before meta#18** (its prod envelope —
   compose refuses an override naming an undefined service, so meta-ci is red until core#65).
3. The stacked chain in order: **core#66** (item 1 packager seam) → **core#67** (items 3+4
   backend, CMAF) → **core#68** (item 6 ladder) → **core#69** (item 5 codecs) → **core#70**
   (item 7 hardware) → **meta#19** (env template). Note: whichever of #65 / the chain merges
   second will hit one additive compose conflict (the x-api-env hoist vs the chain's new
   TRANSCODING_ keys) — resolution demonstrated during validation, both sides purely additive.
4. **user#58** (quality menu follows the engine's codec family) — anytime.

Exit criteria proven on a live stack (validation run 2026-08-22, core-only compose,
`-p phase3val`): CMAF upload playable via HLS **and** DASH with byte-identical shared segments
resolved from both manifests; TS rollback + back-catalog byte-identical across restarts;
api-role/worker×3 split with exactly one advisory-lock leader, ffmpeg only in workers, and
zero double-claims across 12 jobs (four independent evidence lines); all viewer-facing routes
200. Validation also surfaced and led to fixes for: TRANSCODING_PACKAGER missing from the
compose env allow-list (rollback was unreachable — fixed on the chain tip), the core dev
compose losing all media on `--force-recreate api` (mounts mirrored from prod — fixed), and
core#71 above. Caveats recorded: single-host worker scaling is core-bound (45.0s vs 57.3s for
6 jobs at scale 3 vs 1); poster/storyboard ffmpeg still runs on the api request path.

## Target pipeline (conceptual)

```text
Upload → Ingest → Probe → Transcode → Rendition ladder → CMAF packaging
                                        → HLS (.m3u8) + DASH (.mpd) + direct/original
                                        → optional CENC encryption (Phase 5)
                                        → canonical storage → delivery layer
```

## Hard truths from the audit

- Packaging is **fused into the per-rung encode** (hlsRungArgs emits MPEG-TS HLS directly);
  there is no packager seam. "HLS+DASH from shared segments" is structurally impossible until
  segments are CMAF and packaging is a separate step.
- `parseH264CodecString` **dead-letters any non-H.264-Main output** — silently blocking
  hardware encoders and all codec work until fixed (Phase 1/2 pre-cut, interfaces.md §6).
- Everything downstream assumes the one-pass TS tree: storage layout, mediagc key grammar,
  httpapi/hls.go filename allowlists (404 on init.mp4/*.m4s on the canonical route), storeTree.
- ~2k PeerTube-imported videos depend on the fMP4 **pass-through route surviving** any
  packaging overhaul.
- AV1 is config-poisoned (boot-rejects TRANSCODING_AV1_ENABLED=true); yuv420p only (HDR
  silently crushed); probe captures no source codec/bit-depth.
- Master playlists are hand-rendered targeting HLS-v4 TS with no CODECS attribute.

## Work items

### Packaging

- [ ] **1. Packager abstraction** (interfaces.md §6) — split encode from package; ffmpeg-TS
  packager first (behavior-preserving refactor), proving the seam with byte-identical-ish
  output on the existing golden tests.
- [x] **2. Evaluate Shaka Packager vs ffmpeg CMAF muxing** — DONE 2026-08-22, decision written
  at [cmaf-packaging-decision.md](cmaf-packaging-decision.md). Verdict: ffmpeg dash muxer with
  `-hls_playlist 1` for VOD CMAF now (fused with the encode pass, no mezzanine, true shared
  segments, verified on ffmpeg 8.1); Shaka v3.9.x reserved as the phase-5 DRM-gated second
  packager (ffmpeg emits zero DRM signaling and can never do `cbcs`/FairPlay; Shaka's real cost
  is a pinned 10 MB static binary + a mezzanine pass). LL-HLS is a wash — neither tool has it.
- [ ] **3. CMAF packager** — fMP4 segments, HLS (.m3u8) + DASH (.mpd) from the same segments;
  new file shapes added to hls.go allowlists + mediagc grammar together; PeerTube pass-through
  route preserved; per-video packaging format recorded so old TS trees keep playing (no forced
  re-transcode of the back catalog; re-package as an optional background job).
- [ ] **4. DASH delivery route** + frontend consumption (needs Phase 4 engine adapter for
  playback; the backend/manifest side lands here).

### Encoding

- [ ] **5. Codec profiles** — profile registry (H.264 AVC baseline-compat default; HEVC; AV1)
  with browser-compat/encoding-cost/storage/bandwidth metadata; un-poison AV1 config; CODECS
  attributes in master manifests; multi-codec masters. Enterprise enables efficient codecs;
  default stays compatibility-first.
- [ ] **6. Ladder improvements** — fps-aware bitrates (60fps 1080p currently gets 24fps's
  budget); audio-only sources get an audio rung instead of dead-lettering; decode-once
  architecture (N-decodes-per-job + full web_video re-encode duplication wastes ~2–3× CPU);
  per-title/CRF/two-pass as a later optimization behind the profile registry.
- [ ] **7. Hardware transcode** — detection (NVENC/QSV/VAAPI/VideoToolbox) + opt-in offer at
  install ("NVIDIA GPU detected. Enable hardware video transcoding?"); requires the
  parseH264CodecString fix first; CPU remains the default and always works.

### Workers

- [ ] **8. Worker role flag** — same binary, `WORKERS_ENABLED`/role env (port the vidra-search
  seam); compose profile for a dedicated worker container; ffmpeg moves out of the API
  container's resource envelope.
- [x] **9. Lease retrofit** — DONE 2026-08-21 (core `5ead076`, `b57a1d1`). The 3 bare-SELECT
  queues (federation delivery, ATProto cross-post, search outbox) now lease; the 6 state-flip
  claims gained `FOR UPDATE SKIP LOCKED`. No migration was needed — every one of those tables
  already had `next_attempt_at`, and for a row being worked on "when may someone else touch this"
  and "when should this be retried" are the same question. Verified against real PostgreSQL: with
  SKIP LOCKED removed the double-claim reproduces 5 runs out of 5.
- [x] **10. Replace boot blanket-requeue** — DONE 2026-08-21. Both halves:
  - *Requeue* (core `2763495`): claim takes a 30-minute lease, `internal/lease` renews it every
    5 minutes while the worker works, and `jobrecovery.Sweep` returns only rows nobody is renewing,
    on a 2-minute ticker rather than once at boot.
  - *Leader election* (core `9a0ddbd`): the ~9 sweep-only workers are gated on a PostgreSQL
    advisory lock held on a dedicated connection — exactly one instance runs them, and the server
    releases the lock itself when that instance dies. Gating is per TICK, not per worker, because
    the IPFS mirror worker mixes a leased drain (must run everywhere) with a reconcile (must not).
    The key uses the two-int lock form specifically so it cannot collide with golang-migrate's
    one-bigint migration lock — verified by test rather than assumed.
- [x] **11. Scale story validation** — DONE 2026-08-21 (core `55bb877`,
  `deploy/docker-compose.soak.yml`). Two api replicas against one PostgreSQL: both serve, exactly
  one advisory-lock holder, `SIGKILL` on the leader drops holders to 0 and a new leader is elected
  ~11s later, and 400 outbox events drained concurrently produced **406 deliveries for 406 unique
  events, 0 duplicates**. Checked against a counterfactual — with the lease and `SKIP LOCKED`
  removed and the image rebuilt, the same run produced **423 deliveries, 17 duplicates** — so the
  harness demonstrably detects the failure it is asserting the absence of. Supported topology and
  its caveats documented in `vidra-core/docs/operations.md`.

## Carry-forwards out of the 2026-08-22 session (deliberate deferrals, not gaps)

- **Back-catalog re-package job** (TS→CMAF as optional background work) — item 3's optional half.
- **dash_url / format discovery on the video API** — clients currently probe
  `/hls/cmaf/stream.mpd`; phase 4's player work is the natural home.
- **.mp3/.m4a/.flac upload allowlist** — audio-only transcoding works (incl. cover-art files)
  but is only reachable via video containers; widening the allowlist is a product decision.
- **De-duplicate web-videos objects** — they are now byte-exact never-served copies of the HLS
  tree's per-rung MP4s; pointing the rows at the HLS keys would roughly halve progressive
  storage (evidence in core#68's derivation commit).
- **Audio-only posters + size ledger** — thumbnail/storyboard jobs fail silently on audio-only
  sources (no poster, no operator signal); audio-only trees have no rendition row to carry
  size_bytes.
- **worker_id attribution** — job_runs/job_events carry '' for transcodes; in a split topology
  DB-side job→container attribution needs it filled.
- **Sibling queue workers lack WithoutCancel bookkeeping** (captionjob, videoimport,
  ipfsmirror, channelsync, searchevents, storagemigration) — SIGTERM mid-job drops the outcome
  write; bounded by lease sweeps, unlike the transcode bug core#71 fixes.
- **Admin infrastructure page** shows VP9 but not HEVC/AV1/HW status; live-plane
  `buildLevelMenu` unwired for multi-codec; e2e-backed `hls-playback.spec` asserts
  renditions.length>0 (lands red if audio-only seed data is ever added).
- **Host-binary deployments on ffmpeg 6.x** emit bare `hvc1` CODECS (legal, weaker); the
  shipped Alpine image (8.1) writes the full form. Documented nowhere else.

## Exit criteria

- A new upload produces CMAF segments playable via both HLS and DASH; an old upload keeps
  playing untouched.
- `docker compose up --scale worker=3` (or the profile equivalent) triples transcode throughput
  with zero double-claims.
- Default install output is unchanged from an ordinary viewer's perspective.
