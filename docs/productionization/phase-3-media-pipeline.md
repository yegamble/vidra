# Phase 3 — Media pipeline modernization

**Outcome:** encode once, package many — CMAF/fMP4 as the preferred packaged representation
with HLS and DASH sharing segments; codec profiles beyond H.264 Main; hardware acceleration
offered when detected; workers that scale from 1 to many without redesign. Ordinary installs
keep getting compatible H.264 HLS by default.

## Status 2026-08-23 — PHASE COMPLETE; all 11 items merged to main

Every work item is closed and on `main` in all three repos. The merge queue described below
was executed 2026-08-23 01:50–02:15 UTC in the planned order:

| Item | PR | Merge commit |
|---|---|---|
| 1 — packager seam | core#66 | `ef05c63` |
| 3 + 4 — CMAF packaging + DASH route | core#67 → re-opened as core#72 | landed via the stacked chain (see note) |
| 5 — codec profiles | core#69 | `176ae2a` |
| 6 — ladder improvements | core#68 | `ba5ccf4` |
| 7 — hardware transcode | core#70 | `8625c7e` |
| 8 — worker role flag | core#65 | `d31595e` |
| carry-forwards (S3→S3 size hint, doctor bundled-Postgres) | core#64 | `9b11a92` |
| pre-existing fix: transcodes >10s stuck `running` | core#71 | `09fe2e3` |
| prod envelope + worker-profile wiring | meta#18 | `96a1f76` |
| TRANSCODING_HW env template | meta#19 | `6c26e37` |
| multi-codec quality menu | user#58 | `f3559ee` |

**Note on the CMAF PR.** core#67 auto-closed the moment core#66 merged and its stacked base
branch was deleted; core#72 was opened to supersede it and was closed too. Neither carries a
merge commit, which reads like the item never landed — it did. The chain's later PRs (#68/#69/#70)
were branched on top of the CMAF branch, so merging them carried its commits, and all seven
(`4773159`, `a956e75`, `503039c`, `96abc8a`, `c6a55c9`, `12d50be`, `f953ab1`) are ancestors of
`main`; `internal/media/cmaf.go` and the CMAF integration tests are present on `main`.
*Lesson for future stacked sets: merge bottom-up without deleting intermediate branches, or the
audit trail for the middle of the chain disappears.*

### Post-merge verification 2026-08-23

- **vidra-core `main` (`176ae2a`) green.** `make ci` passes — that target is
  `fmt-check vet migrate-lint openapi-verify sqlc-verify test-race`, and backend-ci.yml runs
  exactly it. 66 packages, 2211 tests, 0 failures, run with `-count=1` so the cache proves nothing
  on our behalf.
- **The ffmpeg pipeline is *not* covered by that gate, by design.** Every ffmpeg-dependent media
  test sits behind `//go:build integration` so CI stays green on ffmpeg-less runners. Run
  separately on a host with ffmpeg 8.1: `go test -tags=integration -count=1 ./internal/media/` →
  196 pass, 0 fail, 2 skips (both ClamAV, `CLAMAV_TEST_ADDR` unset). No ffmpeg-capability skips
  fired, so the CMAF/DASH, ladder, codec-family and HEVC/AV1 assertions genuinely executed.
  **Anyone reading a green backend CI badge has learned nothing about this phase's work.**
- **vidra-user `main` green** — typecheck, lint, icon-lint, and 1538 unit tests in 164 files.
  Playwright e2e not re-run post-merge (see the flakiness note in the program README).
- **meta-ci red on `main`, and it is NOT phase 3.** Two separate things were confused here, so both
  are written down:
  - *The scary one that was a mirage.* `docker compose --profile core config -q` failed with
    `service "worker" has neither an image nor a build context specified`. That looks exactly like
    item 8 shipping broken. It was a merge-order race: meta-ci checks out vidra-core's **default
    branch with no `ref:`** (meta-ci.yml), the run fired 01:51, and core#65 defined `worker` on
    core main at 02:00. The next run (02:23) passes that step. meta#18's commit message predicted
    this failure verbatim. **A meta-ci red is not evidence about the meta commit that triggered
    it — it is evidence about whatever vidra-core main happened to be nine minutes earlier.**
  - *The real red underneath*, which has been failing since phase 2 (2026-08-21, `ca99818`) and
    which the worker mirage was hiding: `Every config key vidra-core reads has a compose consumer`
    lists 7 `STORAGE_MIGRATION_TARGET_*` keys with no consumer. See the phase-2 doc; fix in flight.
- **Verification blind spots this exposed**, all real and none phase-3-specific: meta-ci never
  renders `--profile worker` at all (the profile whose merge order broke CI has no coverage of its
  own), and its config-consumer assert inspects only the `api` service's environment, so a key that
  reaches api but not worker would pass. The 2026-08-22 E2E validation also ran against vidra-core's
  own compose under `-p phase3val` rather than the meta-repo compose operators actually use.

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

- [x] **1. Packager abstraction** (interfaces.md §6) — DONE 2026-08-23 (core#66 `ef05c63`).
  Encode split from package; ffmpeg-TS packager first (behavior-preserving refactor), proving the
  seam with byte-identical-ish output on the existing golden tests.
- [x] **2. Evaluate Shaka Packager vs ffmpeg CMAF muxing** — DONE 2026-08-22, decision written
  at [cmaf-packaging-decision.md](cmaf-packaging-decision.md). Verdict: ffmpeg dash muxer with
  `-hls_playlist 1` for VOD CMAF now (fused with the encode pass, no mezzanine, true shared
  segments, verified on ffmpeg 8.1); Shaka v3.9.x reserved as the phase-5 DRM-gated second
  packager (ffmpeg emits zero DRM signaling and can never do `cbcs`/FairPlay; Shaka's real cost
  is a pinned 10 MB static binary + a mezzanine pass). LL-HLS is a wash — neither tool has it.
- [x] **3. CMAF packager** — DONE 2026-08-23 (core#67/#72, landed via the stacked chain).
  fMP4 segments, HLS (.m3u8) + DASH (.mpd) from the same segments;
  new file shapes added to hls.go allowlists + mediagc grammar together; PeerTube pass-through
  route preserved; per-video packaging format recorded so old TS trees keep playing (no forced
  re-transcode of the back catalog; re-package as an optional background job).
- [x] **4. DASH delivery route** — DONE 2026-08-23 (same chain as item 3). The backend/manifest
  side landed here and is served from the CMAF tree; frontend consumption still needs the Phase 4
  engine adapter, and clients currently probe `/hls/cmaf/stream.mpd` because format discovery on
  the video API is a deliberate phase-4 carry-forward (below).

### Encoding

- [x] **5. Codec profiles** — DONE 2026-08-23 (core#69 `176ae2a`). Profile registry (H.264 AVC baseline-compat default; HEVC; AV1)
  with browser-compat/encoding-cost/storage/bandwidth metadata; un-poison AV1 config; CODECS
  attributes in master manifests; multi-codec masters. Enterprise enables efficient codecs;
  default stays compatibility-first.
- [x] **6. Ladder improvements** — DONE 2026-08-23 (core#68 `ba5ccf4`). fps-aware bitrates (60fps 1080p currently gets 24fps's
  budget); audio-only sources get an audio rung instead of dead-lettering; decode-once
  architecture (N-decodes-per-job + full web_video re-encode duplication wastes ~2–3× CPU);
  per-title/CRF/two-pass as a later optimization behind the profile registry.
- [x] **7. Hardware transcode** — DONE 2026-08-23 (core#70 `8625c7e`, env template meta#19
  `6c26e37`). Detection (NVENC/QSV/VAAPI/VideoToolbox) + opt-in offer at
  install ("NVIDIA GPU detected. Enable hardware video transcoding?"); requires the
  parseH264CodecString fix first; CPU remains the default and always works.

### Workers

- [x] **8. Worker role flag** — DONE 2026-08-23 (core#65 `d31595e`, prod envelope meta#18
  `96a1f76`). Same binary, `WORKERS_ENABLED`/role env (port the vidra-search
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
- **dash_url / format discovery on the video API** — phase 4's player work is the natural home.
  *Corrected 2026-08-23:* the "clients currently probe `/hls/cmaf/stream.mpd`" claim in this list
  was never true — vidra-user has no DASH code at all, so the DASH route phase 3 shipped is served
  and entirely unconsumed. `streaming_playlists.format` (migration 0108) is read in exactly one
  place, the route cross-check at `hls.go:170`, and is exposed to no client.
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
