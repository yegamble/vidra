# SizeTube → Vidra beta migration record (2026-11)

The production PeerTube instance at sizetube.com was migrated into a fresh Vidra
beta (`beta.sizetube.com`, DigitalOcean droplet `vidra-beta-st`, tor1). This
records what ran, on what bytes, what landed, and what did not. Everything below
is `RUNTIME` evidence from the beta's own database and logs unless marked otherwise.

## Source

- PeerTube 8.3.1, database schema **1130**. The importer verifies 1130 natively
  from v0.7.11, so no run carried `acknowledged_schema_version` and none used `--force`.
- Source DB: a read-only role on a snapshot restored onto the beta
  (`peertube_source_snapshot`). Source media: the Backblaze B2 bucket, read with a
  read-only key. Server-side copy used a second, temporary key scoped to the two
  buckets (no delete, expiring). That key was removed from the beta env and deleted
  in B2 on 2026-11-06.
- Production was not written to, apart from five operator-requested HLS re-transcode
  API calls (below).

## Runs

| Run | Mode | State | Created (UTC) | Finished (UTC) | Attempts | Notes |
|---|---|---|---|---|---|---|
| `3d7cae5c-517a-4016-ac3b-13343ce98db2` | dry_run | failed `unverified_schema` | 2026-11-04 11:08 | 11:09 | 1 | v0.7.8 refusing 1130 — the pre-v0.7.11 gate, correct at the time |
| `73a8bc92-d5b3-44cc-9f34-07b3b32735e0` | dry_run | done | 2026-11-05 03:13 | 03:13 | 1 | clean preview on v0.7.11 |
| `819a50b4-8a77-4a6c-b0f6-64bb7143d555` | **run** | done | 2026-11-05 03:15 | 19:10 | 5 | the migration; attempts > 1 are lease re-queues after env-only API restarts (copy concurrency 12 at ~09:18, server-side copy at ~12:09), each resuming from the ledger |
| `b650966e-226f-41c5-83fe-d6588c09e8ea` | run | done | 2026-11-06 02:16 | 02:44 | 1 | retry of transient failures |

All four: conflict policy `skip`, media mode `copy`, `source_authoritative=false`.

**Which bytes ran it: the published image, not a source build.** Both real runs
executed inside the API container of `ghcr.io/yegamble/vidra-core:v0.7.11`
(linux/amd64 `sha256:c78f0d39df396a03672cc6491c77ef55e586d7d7e69af8bab24fd4b2b06aef34`,
per `releases/v0.7.11.json`), launched from `/admin/import-peertube`. v0.7.11 was
deployed at 2026-11-05 02:55 UTC, before the first launch. v0.7.12 replaced it at
2026-11-06 03:40, after the retry finished. Source-built `peertube-import` CLI
binaries were used **only** for rehearsal dry runs against a disposable scratch copy
of the beta database (since dropped). They never wrote to the real `vidra` database.

## Final state of the beta database (after both runs)

| Entity | Count |
|---|---|
| users | 5,522 (21 inactive: 10 held for MFA re-enrolment, 11 suspended at source) |
| channels | 5,574 |
| videos | 15,492 |
| ready HLS playlists | 14,744 |
| originals | 1,920 |
| comments | 785 |
| playlists | 2,129 |

The source `root` account was skipped as a name conflict. The beta's own owner
`root` stayed active.

## Import ledger, by kind

| Kind | Done | Failed | Unsupported | Skipped |
|---|---|---|---|---|
| user | 5,521 | 0 | 0 | 1 (username/email exists) |
| channel | 5,573 | 0 | 0 | 0 |
| video | 15,491 | 9 | 0 | 0 |
| video_file | 15,491 | 0 | 0 | 0 |
| hls_playlist | 14,743 | 702 | 0 | 0 |
| rendition | 67,058 | 0 | 15,407 | 0 |
| thumbnail | 14,808 | 683 | 0 | 0 |
| storyboard | 2,083 | 13,053 | 0 | 336 (not import-owned) |
| caption | 14,101 | 669 | 0 | 0 |
| chapter | 45 | 0 | 47 | 0 |
| comment | 785 | 0 | 0 | 0 |
| playlist | 2,129 | 0 | 0 | 0 |
| follow | 6,387 | 0 | 0 | 0 |
| rating | 20,510 | 0 | 0 | 0 |
| view_count | 13,877 | 0 | 0 | 0 |
| watch_history | 325,766 | 0 | 0 | 0 |
| actor_avatar / actor_banner | 347 / 49 | 0 | 6 / 1 | 1 / 1 |
| video_original_date | 21 | 0 | 0 | 0 |

### Failure breakdown

| Kind | Failed | Cause |
|---|---|---|
| storyboard | 13,053 | **Source missing.** Production has 50,723 storyboard rows but ~2,100 files on disk and 166 in the bucket, and serves 404 for them. The oldest file on disk is from 2026-03-01, so most likely an earlier cleanup (unconfirmed). Effect: no seek-bar hover previews. Playback is unaffected. |
| hls_playlist | 702 | 695 source missing (`source_open/not_found`): 683 from one channel whose owner is banned (accepted by the operator), 5 stuck in PeerTube state 8 `TO_MOVE_TO_EXTERNAL_STORAGE_FAILED`, 1 duplicate (accepted), and 6 others. **7 are transient** (6 `tree/other`, 1 `server_copy/deadline_exceeded`) and need one more retry run. |
| thumbnail | 683 | Source missing (HTTP 404 at source). |
| caption | 669 | Source missing (`storage: object not found`). The 11 transient B2 failures from the main run were recovered by the retry. |
| video | 9 | Source missing. |

Unsupported by design: 15,407 web-video renditions (HLS covers playback) and 47
chapters (6 avatars and 1 banner whose actor is neither an account nor a channel).

## Production follow-ups

- The 5 state-8 videos were queued for HLS re-transcoding on production
  (`POST /api/v1/videos/{id}/transcoding`, `hls`, forced → 204 each). As of
  2026-11-06 04:04 UTC all 5 still read "To transcode" behind a single-worker queue.
  A further retry run picks them up once production finishes.

## Beta configuration decisions this migration required

- `sensitive_content_policy` set to `display`, matching production's
  `defaultNSFWPolicy: display`. 1,401 of 1,402 local uploads since mid-July are
  NSFW, and Vidra's default `hide` made the public feed end in July. The importer
  carries each user's NSFW preference but not the instance default. Per-video NSFW
  flags matched the source on all 15,490 compared videos.
- Access is restricted to the operator's IP plus `noindex`, via a hand-maintained
  `deploy/Caddyfile.local` that `vidra setup` does not manage.

## What this record does NOT establish

- Media disaster recovery. Database backups are encrypted, off-site and
  restore-drilled; the media bucket has no tested restore.
- Byte-level integrity of every copied object. The importer checks each copy;
  this record re-hashes nothing.
- That beta behaviour matches production feature by feature. That is the parity QA's job.
