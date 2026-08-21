# Phase 3 — Media pipeline modernization

**Outcome:** encode once, package many — CMAF/fMP4 as the preferred packaged representation
with HLS and DASH sharing segments; codec profiles beyond H.264 Main; hardware acceleration
offered when detected; workers that scale from 1 to many without redesign. Ordinary installs
keep getting compatible H.264 HLS by default.

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
- [ ] **2. Evaluate Shaka Packager vs ffmpeg CMAF muxing** for the CMAF implementation —
  research task with a written decision (criteria: CENC-readiness, LL-HLS trajectory,
  container-size/ops cost, maintenance). Don't reinvent standards-heavy packaging.
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

## Exit criteria

- A new upload produces CMAF segments playable via both HLS and DASH; an old upload keeps
  playing untouched.
- `docker compose up --scale worker=3` (or the profile equivalent) triples transcode throughput
  with zero double-claims.
- Default install output is unchanged from an ordinary viewer's perspective.
