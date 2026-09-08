#!/usr/bin/env bash
#
# A24 / STO-02 — plant a synthetic "reference-mode import" into a SHARED bucket.
#
# What this reproduces, and why it has to be synthetic: a reference-mode PeerTube
# import (`--media-mode=reference`, docs/peertube-migration.md §4) points
# STORAGE_S3_* at the SOURCE instance's own bucket and records that instance's
# object keys verbatim, copying no bytes. The importer needs a live PeerTube
# database to run, which no lab has (MIG-01/A18 is blocked on exactly that), so
# this script writes the objects and the rows the importer WOULD have left
# behind, in the shapes taken from internal/peertubeimport/sourcestorage.go:
#
#   web-videos/<pt-filename>.mp4                 sourceWebVideoKey  -> video_files.storage_key
#   captions/<pt-filename>-<lang>.vtt            sourceCaptionKey   -> captions.storage_key
#   streaming-playlists/hls/<pt-uuid>/<file>     sourceHLSKey       -> streaming_playlists.master_key
#
# plus two families of foreign objects NO Vidra row references at all: a
# PeerTube-shaped `videos/<uuid>/…` tree and an unrelated `foreign/…` prefix.
# Those two exist to separate the sweep's two protections — prefix scoping and
# the minted-key shape test (internal/mediagc.isMintedKey) — which a single
# fixture would conflate.
#
# Everything written here is inert: text bodies, no real media, obviously fake
# identifiers. It is destructive only to the disposable lab bucket it is aimed at.
#
# Usage (all values come from the environment; nothing is baked in):
#   PGURL='postgres://user@127.0.0.1:5432/vidra?sslmode=disable' \
#   MC=/path/to/mc ALIAS=lab BUCKET=vidra-a24 CHANNEL_ID=<uuid> \
#   ./a24-plant-foreign-media.sh
#
# WORK_ROOT names where the staging files are written before they are uploaded.
# It matters when MC is a containerised client: the staging directory has to be
# one the client can see, and the system temp dir usually is not.
#
set -euo pipefail

: "${PGURL:?PGURL is required (a libpq URL for the lab database)}"
: "${MC:?MC is required (path to an mc binary or wrapper)}"
: "${ALIAS:=lab}"
: "${BUCKET:?BUCKET is required (the shared lab bucket)}"
: "${CHANNEL_ID:?CHANNEL_ID is required (an existing channel to hang the imported video off)}"

WORK="$(mktemp -d "${WORK_ROOT:-${TMPDIR:-/tmp}}/a24-plant-XXXXXX")"
trap 'rm -rf "$WORK"' EXIT

# Fake, obviously-not-real source identifiers. The UUIDs are the SOURCE
# instance's, not Vidra's; that is the whole point of reference mode.
PT_VIDEO_UUID="aaaaaaaa-0000-4000-8000-00000000f001"   # source video uuid
PT_FILE_BASE="deadbeef-0000-4000-8000-00000000c0de-720" # PeerTube web-video filename stem
PT_CAPTION_BASE="deadbeef-0000-4000-8000-00000000c0de-en"
ORPHAN_VIDEO_UUID="bbbbbbbb-0000-4000-8000-00000000f002" # foreign, referenced by nothing

VIDRA_VIDEO_ID="${VIDRA_VIDEO_ID:-cccccccc-0000-4000-8000-00000000f003}"

say() { printf '%s\n' "$*"; }

# ---------------------------------------------------------------- objects ----
# 1. Referenced foreign media (the reference-mode import's own three families).
printf 'foreign source original — not vidra bytes\n'      > "$WORK/original.mp4"
printf 'WEBVTT\n\n00:00.000 --> 00:02.000\nforeign\n'      > "$WORK/caption.vtt"
printf '#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1\n0.m3u8\n'  > "$WORK/master.m3u8"
printf '#EXTM3U\n#EXTINF:2,\nseg-0.ts\n#EXT-X-ENDLIST\n'   > "$WORK/variant.m3u8"
printf 'foreign hls segment bytes\n'                       > "$WORK/segment.ts"

"$MC" cp -q "$WORK/original.mp4" "$ALIAS/$BUCKET/web-videos/${PT_FILE_BASE}.mp4"
"$MC" cp -q "$WORK/caption.vtt"  "$ALIAS/$BUCKET/captions/${PT_CAPTION_BASE}.vtt"
"$MC" cp -q "$WORK/master.m3u8"  "$ALIAS/$BUCKET/streaming-playlists/hls/${PT_VIDEO_UUID}/master.m3u8"
"$MC" cp -q "$WORK/variant.m3u8" "$ALIAS/$BUCKET/streaming-playlists/hls/${PT_VIDEO_UUID}/0.m3u8"
"$MC" cp -q "$WORK/segment.ts"   "$ALIAS/$BUCKET/streaming-playlists/hls/${PT_VIDEO_UUID}/seg-0.ts"

# 2. Foreign media NO row references, INSIDE a swept prefix. Only the
#    minted-key shape test can save these: their id position is a PeerTube
#    filename, not a Vidra entity id.
"$MC" cp -q "$WORK/original.mp4" "$ALIAS/$BUCKET/web-videos/${ORPHAN_VIDEO_UUID}-1080.mp4"
"$MC" cp -q "$WORK/caption.vtt"  "$ALIAS/$BUCKET/captions/${ORPHAN_VIDEO_UUID}-fr.vtt"
"$MC" cp -q "$WORK/master.m3u8"  "$ALIAS/$BUCKET/streaming-playlists/hls/${ORPHAN_VIDEO_UUID}/master.m3u8"

# 3. Foreign media OUTSIDE every swept prefix. Only prefix scoping saves these.
"$MC" cp -q "$WORK/original.mp4" "$ALIAS/$BUCKET/videos/${ORPHAN_VIDEO_UUID}/source.mp4"
"$MC" cp -q "$WORK/original.mp4" "$ALIAS/$BUCKET/foreign/site-backup/archive.tar"
"$MC" cp -q "$WORK/caption.vtt"  "$ALIAS/$BUCKET/avatars/users/${ORPHAN_VIDEO_UUID}.png"

# -------------------------------------------------------------------- rows ---
# One video row whose media all points at keys this install did not lay out.
# `peertube_uuid` is what an import stamps; the storage keys are the evidence
# CountForeignLayoutMediaRefs actually counts.
psql "$PGURL" -v ON_ERROR_STOP=1 <<SQL
INSERT INTO videos (id, channel_id, title, description, privacy, state, peertube_uuid)
VALUES ('${VIDRA_VIDEO_ID}', '${CHANNEL_ID}',
        'A24 reference-mode import fixture', 'synthetic; no bytes were copied',
        'public', 'published', '${PT_VIDEO_UUID}')
ON CONFLICT (id) DO NOTHING;

INSERT INTO video_files (video_id, kind, storage_key, content_type, original_name, size_bytes, sha256)
VALUES ('${VIDRA_VIDEO_ID}', 'original', 'web-videos/${PT_FILE_BASE}.mp4',
        'video/mp4', '${PT_FILE_BASE}.mp4', 42, '')
ON CONFLICT DO NOTHING;

INSERT INTO captions (video_id, language, label, storage_key)
VALUES ('${VIDRA_VIDEO_ID}', 'en', 'English', 'captions/${PT_CAPTION_BASE}.vtt')
ON CONFLICT (video_id, language) DO NOTHING;

INSERT INTO streaming_playlists (video_id, master_key, state, format)
VALUES ('${VIDRA_VIDEO_ID}',
        'streaming-playlists/hls/${PT_VIDEO_UUID}/master.m3u8', 'ready', 'hls-ts')
ON CONFLICT (video_id) DO NOTHING;
SQL

say "planted reference-mode video ${VIDRA_VIDEO_ID} (source uuid ${PT_VIDEO_UUID})"
say "foreign-layout refs now: $(psql "$PGURL" -tAc "
  SELECT (SELECT count(*) FROM video_files
            WHERE storage_key LIKE 'web-videos/%'
              AND storage_key NOT LIKE 'web-videos/' || video_id::text || '%')
       + (SELECT count(*) FROM streaming_playlists
            WHERE master_key <> ''
              AND master_key NOT LIKE 'streaming-playlists/' || video_id::text || '/%')")"
