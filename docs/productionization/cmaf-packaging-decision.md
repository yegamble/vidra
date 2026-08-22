# Decision: CMAF/fMP4 packaging — ffmpeg vs. Shaka Packager

**Status:** Decided 2026-08-22 · **Phase:** 3, item 2 · **Evidence:** local A/B reproduction on
ffmpeg 8.1 (the major Alpine 3.24 ships) and Shaka Packager v3.9.3 (Docker), plus primary-source
reads of FFmpeg master (`doc/muxers.texi`, `dashenc.c`, `hlsenc.c`, `hlsplaylist.c`) and the Shaka
project docs/releases. All claims below were verified, not quoted from blogs.

## Decision

**Hybrid, phased:**

1. **Now (VOD CMAF, phase-3 item 3): ffmpeg's `dash` muxer with `-hls_playlist 1`.** One process,
   fused with the encode pass, zero intermediate files, one genuine shared CMAF segment set plus
   both manifests. No second binary — the single-binary install property holds for 100% of
   installs.
2. **The packager is a Go interface seam** (phase-3 item 1), so the implementation is swappable
   without touching the encode step or storage layer.
3. **Phase 5 (optional CENC): Shaka Packager becomes an opt-in, DRM-gated second implementation
   of that seam.** Do not attempt CENC on the ffmpeg path — it encrypts bytes but emits *zero*
   DRM signaling and cannot do `cbcs` at all (no FairPlay, ever).
4. **LL-HLS is not a tiebreaker** — neither tool supports Apple LL-HLS (ffmpeg's `lhls` option is
   the abandoned pre-Apple draft; Shaka's docs: "Only LL-DASH is supported"). Blog posts
   documenting `-hls_part_size` in ffmpeg are wrong; no such option exists upstream.

## Key evidence

### Shared-segment HLS+DASH (ffmpeg): verified working

Reproduced on ffmpeg 8.1: a 2-rung + audio ladder through
`-f dash -dash_segment_type mp4 -use_template 1 -use_timeline 1 -hls_playlist 1` produced
`init-N.mp4` + `.m4s` segments + `stream.mpd` + `master.m3u8` + per-rung media playlists, where
the MPD's `SegmentTemplate` and the HLS playlists resolve to the **same files**. Concatenated
init+segments ffprobe as valid h264 with exact duration. `-format_options movflags=+cmaf` yields
the `cmfc` CMAF brand (Shaka's init lacks it). VOD MPD is correctly `type="static"` by default
(Shaka needs `--generate_static_live_mpd` to avoid a dynamic-MPD footgun).

ffmpeg's own HLS manifests are weaker than Shaka's (no `EXT-X-INDEPENDENT-SEGMENTS`,
`AVERAGE-BANDWIDTH`, `FRAME-RATE`, `EXT-X-PLAYLIST-TYPE:VOD`; no `EXT-X-I-FRAME-STREAM-INF`;
wall-clock `EXT-X-PROGRAM-DATE-TIME` per segment) — **but Vidra already authors its master
playlist in Go** (`renderMasterPlaylist`) and discards ffmpeg's, so the polish gap closes in the
Go writer we own. Trick-play stays a separate pass as today (`-hls_segment_type fmp4
-hls_flags single_file` verified to produce a valid byte-range I-frame playlist).

Two real gaps regardless of tool choice on the ffmpeg path:
- **WebVTT hard-fails the dash muxer** (verified: mux aborts). Captions stay out-of-band:
  Go-authored `EXT-X-MEDIA:TYPE=SUBTITLES` on the HLS side, Go-injected
  `<AdaptationSet contentType="text">` on the DASH side.
- The MPD and each media playlist are **rewritten once per segment** in non-streaming mode
  (dashenc.c `dash_flush` → `write_manifest`); over blobsink this means N extra PUTs per
  manifest — extend blobsink's `.m3u8` coalescing to `.mpd` before enabling direct-to-S3.

### CENC — the decisive criterion

ffmpeg's `encryption_scheme=cenc-aes-ctr` through the dash muxer produces genuinely encrypted
CMAF (verified `encv/sinf/schm/tenc` + `senc/saio/saiz` boxes) that is **unplayable by any DRM
client**: zero `ContentProtection` in the MPD, zero `EXT-X-KEY`, and **no `pssh` box at all**.
ffmpeg's MP4 muxer supports exactly `none` and `cenc-aes-ctr` — no `cbcs` (FairPlay), no key
rotation. Shaka in one invocation emitted verified Widevine/PlayReady/FairPlay/CommonSystem
signaling in both manifests, supports `cenc|cbc1|cens|cbcs`, key rotation, and CPIX (v3.9.0).
**If CENC ships, Shaka ships with it.**

### Ops cost — folklore corrected

- The official `google/shaka-packager` image is 349 MB because it ships a **debug build**
  (131 MB binary). The GitHub release asset `packager-linux-x64` v3.9.3 is a **10.3 MB stripped
  static-PIE binary with zero deps**. Cost of adding Shaka later ≈ a pinned 10 MB curl.
- Shaka is actively maintained (8 releases 2026-03→2026-07, community `shaka-project` org).
  Maintenance risk is NOT a reason to avoid it.
- The real Shaka cost: it cannot encode, so every rung needs a **mezzanine intermediate + a full
  second pass** — a direct regression against the lean-S3 scratch/IO work for clear content.

### Multi-codec CODECS strings

ffmpeg emits correct, HLS/DASH-consistent CODECS via shared `ff_make_codec_str()`:
`avc1.42c01f`, `hvc1.1.6.L93.90` (**requires `-tag:v hvc1`** or Safari-breaking `hev1` is
written with only a warning), `av01.0.05M.08`, `mp4a.40.2`. Under CMAF, the hand-rolled
`avc1.4d40%02x` + extra ffprobe in `parseH264CodecString` can be retired by parsing ffmpeg's own
manifest output — unblocking HEVC/AV1/hardware encoders (items 5/7).

### Host-process obligations (for item 3's implementer)

`ignore_io_errors` must stay 0 (exit codes are then trustworthy); `setsar=1` after every scale
(else SAR artifacts pollute the MPD); `-init_seg_name`/`-media_seg_name` give the
`init-$RepresentationID$.mp4` + `.m4s` layout (rung→representation-index mapping lives in Go);
strip per-segment `EXT-X-PROGRAM-DATE-TIME`; inject `EXT-X-PLAYLIST-TYPE:VOD`; master playlist
moves to `#EXT-X-VERSION:7` with `CODECS` on every `EXT-X-STREAM-INF` (mandatory in practice for
fMP4 on Safari); audio/video segment durations differ at AAC frame granularity — correct, do not
"fix".

## Revival conditions — switch/add Shaka if any becomes true

1. CENC ships (non-negotiable), or FairPlay/`cbcs` is required at all, or key rotation is
   required.
2. In-manifest DASH subtitles prove fragile in real players under the Go-injected workaround.
3. A conformance gate (DASH-IF, `mediastreamvalidator`) fails ffmpeg manifests in ways the Go
   post-processor cannot repair.
4. Multi-period / ad insertion / SCTE-35 enters scope (ffmpeg dash muxer is single-period).

**Not** revival conditions: LL-HLS (neither tool), image size (10 MB), maintenance risk.

## Sources (fetched/verified 2026-08-22)

FFmpeg master `doc/muxers.texi` (dash §, hls §, MOV encryption §), `libavformat/dashenc.c`
(manifest rewrite :1922, io-error handling :266; zero hits for iframe/webvtt/ContentProtection),
`libavformat/hlsenc.c` (hvc1 warning :2357), `libavformat/hlsplaylist.c`; local repros: shared-
segment CMAF run, CENC box-tree dump (tenc present / pssh absent), HEVC+AV1 CODECS runs, WebVTT
failure, fMP4 single-file trick-play; Shaka releases page (v3.7.0–v3.9.3), DRM/HLS/low-latency
tutorials, issue #745 (LL-HLS, closed/locked); Alpine 3.24 ships ffmpeg 8.1.2-r0;
`google/shaka-packager:latest` measured 349 MB with `v3.9.3-…-debug` binary vs 10,289,600-byte
stripped static release asset.
