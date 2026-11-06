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

As of run `b650966e` (2026-11-06 02:44 UTC). The later reruns and the current figures
are in [2026-11-06 reruns: v0.7.14 and v0.7.15](#2026-11-06-reruns-v0714-and-v0715).

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
  (`POST /api/v1/videos/{id}/transcoding`, `hls`, forced → 204 each). Each one's
  automatic move to object storage had failed mid-transcode (`ENOENT` on a replaced
  rendition) and PeerTube does not retry it, so once a video's own jobs were done the
  operator-approved `create-move-video-storage-job --to-object-storage -v <uuid>` moved it.
  Status at 2026-11-06 20:50 UTC:
  - `eeba2cf5`, `b765335e`: moved and Published; **imported** by run `0c6475c3`.
  - `039ec94f`: moved and Published at 20:15 (8 renditions on `cdn.sizetube.com`). Its new
    renditions postdate the 16:54 source snapshot, so a refresh and a rerun are still needed.
  - `6f2fdd7e`, `892d1947`: still "To transcode", 7 jobs each among 32 queued behind
    production's single worker (1–2 h per long rendition).

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

## v0.7.13 beta deployment (2026-11-06)

Before the deploy, no import run was pending or running. An off-site backup ran
first (`vidra-20261106T043842Z`).

- The first `pin-release.sh v0.7.13` **refused** (exit 1, nothing changed): it could
  not read a release record for v0.7.13 before #359 merged, and a bundle upgrade will
  not guess the pairing. That is the intended behaviour. After #359 merged, it fetched
  `releases/v0.7.13.json`, verified the bundle checksum and pinned
  `VIDRA_CORE_TAG=VIDRA_USER_TAG=VIDRA_SEARCH_TAG=v0.7.13`.
- `deploy.sh` ran in its fixed order and exited 0:
  1. pre-deploy dump `pre-deploy-2026-11-06T044341.dump.gz` (88M)
  2. pull
  3. migrate: core `schema already up to date version=188 dirty=false`, search `version=21 dirty=false`
  4. `up -d`
  5. Caddy reload
  6. health probes: api `/readyz`, frontend and edge `/healthz` all OK
- **Ledger assertion:** deploy.sh expected core schema `0188` from
  `vidra-bundle.manifest` and logged `core schema OK (version 188)`. An independent
  read afterwards: `schema_migrations` = `188|f`, `vidra_search_migrations` = `21|f`.
- **Running images:** `vidra-core:v0.7.13`, `vidra-user:v0.7.13`, `vidra-search:v0.7.13`.
  `deploy/Caddyfile.local` (IP gate and CDN block) is byte-identical to before.
- `GET https://beta.sizetube.com/healthz` → `200 {"status":"ok"}`.

### Rate limit: the 30-page signed-in browse

The check was headless Chromium signed in as a regular user, visiting 30 pages (home,
watch pages, channel pages, trending, recent, search, subscriptions, library, history,
playlists, notifications, settings). 429s were counted both in the browser and in the
API's own request log.

| `RATE_LIMIT_REQUESTS` | Pace | Duration | 429s (browser) | 429s (api log) |
|---|---|---|---|---|
| 120 (default) | 0.4 s/page | 18.4 s | **80** | 84 |
| 120 (default) | 3 s/page | 99.7 s | **23** | 25 |
| 300 | 0.4 s/page | 20.8 s | **0** | 0 |
| 300 | 3 s/page | 98.3 s | **0** | 0 |

**Why 120/min fails ordinary browsing:** each page costs about **8.4 requests on the
general API budget** (media is on its own 3,000/min budget). At one page every 3 s that
is ~170/min. The biggest per-page contributors, over 30 pages: `GET /instance` 34,
`POST /auth/refresh` 30, `GET /channels/:h/donation-addresses` 27, `GET /videos/resolve` 20,
`GET /channels/:h` 20, `GET /users/:u/donation-addresses` 17. PeerTube's shipped API
limit is 50 requests per 10 s (300/min), so the beta now sets `RATE_LIMIT_REQUESTS=300`
in its env (backup of the previous env in `/root/production.env.pre-ratelimit300-*`).
**The per-page request overhead itself is not fixed.** It is a frontend follow-up; until
it lands, 120/min is too low a default for a signed-in viewer.

## 2026-11-06 reruns: v0.7.14 and v0.7.15

Two importer defects kept 7 long videos out of HLS, and fixing them needed two releases:

- **v0.7.14** (core #521): repeated `EXT-X-BYTERANGE` lines counted toward the 10,000
  reference cap, so a 1.4–6.3 h byte-range ladder failed `tree/other`. #522 (echo v5) is
  in the same release because a govulncheck failure blocked every vidra-core merge.
- **v0.7.15** (core #523, #524): the beta has no server-copy key, so HLS objects stream
  through the API. Measured on the beta, B2 drops a download left unread for ~30 s (a
  15 s idle survived, 45 s did not), and a streamed copy leaves its source unread whenever
  a destination part upload waits on B2. `a2ed643c`'s 22.17 GB 4K ladder failed
  `stream_copy/other` 5 minutes into a 4.8 GB file. #523 resumes a dropped S3 body (ETag
  pinned, so a replaced object fails rather than splicing). #524 sizes the tree deadline
  to the recorded ladder instead of a fixed 30 minutes, which would need 36 MB/s to fill
  the 64 GiB tree cap.

**Source snapshot refreshed** before these runs. The production dump was streamed
16:54–16:59 UTC (349,731,375 bytes, identical SHA-256 at both ends), restored as a new
database, re-granted to the read-only role per the runbook, and checked as that role
(`default_transaction_read_only` on, `UPDATE` refused). It was then swapped in by
rename. The previous snapshot is kept as `peertube_source_snapshot_20261104`.

| Run | Mode | Release | Created (UTC) | Finished (UTC) | Attempts | Notes |
|---|---|---|---|---|---|---|
| `6f5cf154` | run | v0.7.13 | 2026-11-06 15:08 | 15:29 | 1 | retry: 1 HLS (`server_copy/deadline_exceeded`), ~580 storyboards |
| `3455fb00` | dry_run | v0.7.14 | 17:04 | 17:04 | 1 | clean preview on the refreshed snapshot |
| `0c6475c3` | run | v0.7.14 | 17:04 | 17:47 | 1 | +16 videos, +17 users and channels; HLS +30 (5 of the 6 byte-range ladders, `eeba2cf5`, `b765335e`) |
| `e7ba8be1` | dry_run | v0.7.15 | 19:12 | 19:13 | 1 | clean preview |
| `13d98e9d` | run | v0.7.15 | 19:14 | 20:49 | 1 | HLS +1: `a2ed643c`, 22.17 GB streamed |

All conflict policy `skip`, media mode `copy`, `source_authoritative=false`, launched
from `/admin/import-peertube`. Each run used the deployed release image named in its row.
During `13d98e9d` the API was seen opening a fresh source connection after a dropped one
(the #523 resume). B2's upload latency swung from about 10 s to under 1 s per 16 MiB part,
so the 2160p file alone took about 45 minutes. `a2ed643c` plays from the beta: 7 variants;
the 2160p init and its last byte-range segment, 11.67 GB in, both answer 206 with valid
ISOBMFF boxes.

Ledger after `13d98e9d`:

| Kind | Done | Failed |
|---|---|---|
| user / channel | 5,538 / 5,590 | 0 / 0 |
| video / video_file | 15,508 / 15,508 | 2 / 0 |
| hls_playlist | 14,775 | **687**, all `source_open/not_found` |
| thumbnail / caption | 14,825 / 14,102 | 683 / 669 |
| storyboard | 2,100 | 12,329 (source missing, as above) |
| comment / playlist / follow / rating | 789 / 2,141 / 6,434 / 20,592 | 0 |

No transient HLS failure remains: every one left is a source file that production
itself lacks. Running images: `vidra-core`, `vidra-user`, `vidra-search` **v0.7.15**
(record `releases/v0.7.15.json`). `deploy/Caddyfile.local` is unchanged.

Not done here: the 11 unfinished B2 large files (427.6 MB of parts) left in the beta
bucket by the 2026-11-05 09:18 API restart are still there. They are billable and invisible
to `b2 ls`.

