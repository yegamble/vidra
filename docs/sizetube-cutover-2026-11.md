# sizetube.com → Vidra: go-live readiness audit (2026-11-08)

A read-only audit of the beta (`beta.sizetube.com`, v0.7.15 = core `ce2ea05c`) against
runbook [§9](peertube-migration.md#9-reconcile-the-final-delta-and-domain-behavior) and
[§10](peertube-migration.md#10-accept-switch-traffic-and-retain-rollback), written before any
cutover action. Nothing was changed: no env, Caddyfile, DNS, database, bucket or prod write.
It complements the [beta migration record](sizetube-beta-migration-2026-11.md), which says
what ran; this says what still stands between the beta and `sizetube.com`. Execution status
of the open items is tracked in the [cutover checklist](sizetube-cutover-checklist.md).

**Evidence labels.** **RUNTIME** = observed on the beta or prod, with a UTC date (all RUNTIME
reads here were taken 2026-11-08 00:44–01:30 UTC unless dated otherwise; database reads ran
under `BEGIN READ ONLY`, env files were read with secret values masked to present/absent).
**CODE** = read in vidra-core / vidra-user source, cited as `file:line` from the `main`
mirror fetched 2026-11-07, which contains #523/#524 and so is ≥ v0.7.15. **DEDUCED** =
inferred from the two. **unverified** = not established by this audit. Raw outputs are kept
in the operator's private log (`cutover-audit-evidence.md`), never in this repo.

**One caveat on timing.** While this audit ran, the operator started import run `bff44fc2`
(`run`, gap-fill, 2026-11-08 01:03→01:15 UTC) from `/admin/import-peertube`. Ledger counts
below were read before it started (00:50) and re-read after it finished; it imported nothing
new and its failure set is identical to run `13d98e9d`'s (RUNTIME).

## 0. What this audit found that the plan did not already know

1. **The media GC deleted 38 objects from the beta bucket on 2026-11-07 19:12 UTC** —
   `mode=delete, scanned=218036, orphans=38, deleted=38, bucket_ownership=owned,
   breaker_tripped=false` (RUNTIME, api log). `MEDIA_GC_ENABLED=true` and
   `MEDIA_GC_MAX_ORPHAN_PERCENT=25` are the live values; the worker sweeps every 24 h after a
   first dry run (CODE `cmd/api/main.go:4083-4110`), so the next delete sweep is due
   **≈ 2026-11-08 19:12 UTC**. Deleted keys are not logged at INFO. Runbook §5 asks for GC
   off during the migration; the beta has had it on throughout. See §8 and D12.
   **Done 2026-11-08 02:55 UTC:** `MEDIA_GC_ENABLED=false` deployed via `deploy.sh` (pre-deploy dump
   `pre-deploy-2026-11-08T025518.dump.gz`); the new api logs "media gc worker disabled" (RUNTIME).
2. **Prod's outbound mail is broken.** PeerTube is configured for `127.0.0.1:2525` (TLS,
   from `no-reply@sizetube.com`), nothing listens on 2525, and the live log shows
   `connect ECONNREFUSED 127.0.0.1:2525` 28 times, the latest at 2026-11-08 01:00 UTC on a
   login-notification mail (RUNTIME prod). There is no working sender to copy for D4, and
   prod users have not been receiving password-reset mail either.
3. **The prod transcode/move race recurred.** `6f2fdd7e` and `892d1947` are back in state 8
   ("move to object storage failed") with 6 and 5 local renditions each; the move jobs
   failed with `ENOENT` on the HLS path (RUNTIME prod, redis `move-to-object-storage:failed`).
   `039ec94f` is published with 8 renditions in B2. Prod also has a **70-job prioritized
   transcoding backlog across 12 recent uploads** at concurrency 1 / threads 1 (RUNTIME).
   Four of those 12 are already on the beta as `published` with **one** 720p rendition each
   (RUNTIME), and the importer never re-copies a video that already has a ready HLS tree
   (CODE `hls_backfill.go:93-131`, `ImportVideoHasReadyPlaylist` `peertube_import.sql:476`).
   New decision D16.
4. **Eight videos are published on prod but `draft` on the beta** (`1e3eb193`, `49eca458`,
   `5ef97b36`, `6d6083eb`, `b765335e`, `bf3e5d17`, `eeba2cf5`, `f69f515a` — state 7/8 in the
   2026-11-04 snapshot, state 1 now), and **one is public on prod but private on the beta**
   (`7476ede8`) (RUNTIME, per-video diff of beta vs snapshot). The gap-fill rerun never
   rewrites state or privacy; `ImportUpdateVideo` under `source_authoritative=true` does
   (CODE `peertube_import.sql:749-764`). This decides D1.
5. **The reconciliation is otherwise clean.** Ledger vs the 2026-11-06 snapshot: users
   identical (5,539), live comments identical (789), video blacklist identical (410 = 410),
   all 11 prod-blocked users inactive here, the 10 MFA holds inactive, **zero prod-deleted
   videos still live on the beta** (the one ledger uuid missing from the snapshot,
   `86c97689`, failed to import and never existed here). No `done` HLS tree is missing a
   rendition the source has (RUNTIME §2.5).
6. **Audio is carried.** The 15,430 `rendition … unsupported ("audio-only rendition has no
   height")` rows are DB rows only: the audio-only `*-0.m3u8` / `*-0-fragmented.mp4` objects
   are in the beta bucket and the served master playlist carries
   `#EXT-X-MEDIA:TYPE=AUDIO … AUDIO="audio"` on every variant (RUNTIME, B2 listing + HTTPS).
7. **Legacy links work better than the plan recorded.** `/w/<PeerTube short uuid>`,
   `/videos/watch/<uuid>` and `/videos/embed/<uuid>` all 302 to the canonical page, and
   `?start=30` / `?start=1m30s` are rewritten to `?t=` (RUNTIME). What is still missing:
   `/c/<handle>/videos`, `/channels/<handle>/videos`, `/video-channels/<handle>` (PeerTube's
   channel URL) and `/accounts/<name>` are 404; account pages 404 because
   `profile_public=false` (RUNTIME; D5).
8. **Prod declares itself NSFW**: `/api/v1/config` → `instance.isNSFW=true`,
   `defaultNSFWPolicy=display`, and its terms open with "an NSFW content-sharing platform
   specializing in niche size fetish and giantess fetish content" (RUNTIME, public). The
   compliance intake question (1) is therefore not "is it NSFW" but "is it *pornographic /
   harmful to minors* under the statutes" — still LAWYER.
9. Minor: one imported account (ledger user 1787) has no actor keypair because its source
   actor has none (1 of 11,130 local actors); Vidra mints one lazily on first federation use
   (CODE `federation/actor.go:361-392`). Imported users have **no** `notification_prefs`
   rows, so code defaults govern their e-mail once mail is enabled (RUNTIME 0 rows).
   Prod also has 13 instance-actor followers and 30 outbound follows (RUNTIME snapshot)
   that the importer does not carry.
10. **The white-label switch is off.** `branding_hide_software_name` has no row on the beta
    (default false, CODE `instancesettings/service.go:196-208, 950`); `GET /api/v1/instance`
    reports `branding.hide_software_name=false`, `hide_instance_name=false`, and `/login`
    renders "Powered by …" (RUNTIME 2026-11-08 01:55 UTC). Every imagery slot (avatar, banner,
    favicon, header logos, OpenGraph) is `is_fallback=true`. Both are database-stored instance
    settings (Admin → General → Branding) that survive deploys, the hostname flip and the final
    rerun — they only need to be set once, before cutover (§5 step 0).

## 1. What flipping `PUBLIC_BASE_URL` does to imported data

**Answer (CODE, confirmed RUNTIME): nothing is rewritten and nothing imported breaks. No
import write persists an absolute URL, a local actor id or anything derived from
`PUBLIC_BASE_URL`.**

- Import writes (`internal/store/queries/peertube_import.sql:211-339, 445-470`): users (no
  URL; `storage_quota_bytes` literal 0), channels (no URL), videos (`peertube_uuid` = bare
  source uuid — the column exists to keep `/w/<short>` and `/videos/watch/<uuid>` alive
  "after an operator cuts their domain over", lines 255-259), video_files / captions /
  renditions (storage keys in the beta bucket), comments, playlists, channel_follows,
  video_blocks, view counts, history. Copied HLS playlists keep same-directory relative
  names; the source's absolute-VTT subtitle groups are stripped (`copyhls.go:19, 197-253`).
- **Actor keys** are PEMs keyed by `user_id` / `channel_id` (`account_actor_keys`,
  `channel_actor_keys`, `peertube_import.sql:327-339`; `entities.go:227-261, 370-394`),
  `ON CONFLICT DO NOTHING`, never rotated by a resync (`resync.go:61-65`). No host in them.
  RUNTIME: 5,537 account keys, 5,590 channel keys, 0 instance keys.
- **Local actor ids are never stored.** They are built per request from the federation
  service's `baseURL` (= `cfg.PublicBaseURL`): `federation/actor.go:175-182`,
  `deliver.go:253,279,297`, `collections.go:59,104`, `followers.go:169`, `inbox.go:413`.
  The one persisted "frozen identity", `channel_handle_aliases.is_actor_id`, stores a
  handle, not a host (migration `0142:90-120`); RUNTIME: the table has 0 rows.
- Everything else that reads the value is runtime-only: RSS/oEmbed/sitemap
  (`httpapi/distribution.go:35,68`), NodeInfo/WebFinger/host-meta (`federation.go:53`,
  `well_known.go:31-66`), legacy AP object redirect (`federation_objects.go:146`), OAuth
  callbacks (`oauth.go:96-99`), mail links (`mail/composer.go:533-536`), admin reset links
  (`admin_user_reset_link.go:74-76`), @-mention host (`comments.go:309-313`). RUNTIME: the
  sitemap (5,143 URLs), the RSS feed and oEmbed all carry `https://beta.sizetube.com` today,
  i.e. derived at request time. A restart applies the change; the frontend reads it at
  request time (`docker-compose.yml:117,131`).
- **The single import-time decision that reads `PUBLIC_BASE_URL` is remote followers**
  (`entities_remotefollowers.go`). Line 87: a follower is carried only if the source's
  `TargetURL == PUBLIC_BASE_URL + "/video-channels/" + handle`; otherwise `followerSkipActorID`
  ("another domain or a renamed handle"). Lines 45-51: a skip writes **no ledger row**, so it
  is re-decided on every run; only a `done` row short-circuits. RUNTIME: every `run` so far
  reports `remote_follower skipped=20, imported=0`, the two early runs carry the conflict
  line "20 remote follower(s) not carried: the channel's actor id here differs from the one
  they follow on the source", `remote_follows` has 0 rows, and the ledger has no
  `remote_follower` rows. All 20 source rows target `https://sizetube.com/video-channels/…`
  from 12 PeerTube hosts. Followers of ACCOUNT actors are `unsupported` (lines 40-44);
  the source has none.
- **Conclusion: the final rerun MUST run after the hostname flip** (and after `deploy.sh`
  has restarted the api with the new value). Only then does line 87 match, the resolver
  fetches each follower's actor (`remote_actor_resolution.go:41-65`, budget 500 per run,
  SSRF-guarded `federation/remote.go:98-109`) and `remote_follows` rows are written as
  `accepted` (`peertube_import.sql:318-325`). The resolver is wired regardless of
  `FEDERATION_ENABLED` (`cmd/api/main.go:2404, 3177`), so federation can stay off during
  the run as §5 demands; the rows only start receiving deliveries once it is enabled.
  Imported channels have `activitypub_enabled=true` by default (migration `0096:13`;
  RUNTIME: 0 channels with it off).
- **What the flip needs changed together** (`deploy.sh` refuses otherwise):
  `PUBLIC_BASE_URL`, `NEXT_PUBLIC_API_BASE_URL`, `CORS_ALLOWED_ORIGINS` → `https://sizetube.com`;
  `deploy/Caddyfile.local` first site address → `sizetube.com` (`deploy.sh:246-283`
  `require_real_domain`), the `cdn-beta` block's `header_up Host` (line 360), removal of the
  operator-IP gate (line 86) and `X-Robots-Tag: noindex` (lines 84, 349); and the acme DNS
  preflight (`deploy.sh:389-414`), which dies while `sizetube.com` resolves to Cloudflare
  (RUNTIME: it does, `104.21.88.49` / `172.67.173.7`) — needs `VIDRA_SKIP_DNS_PREFLIGHT=1`
  in the env file (read via `env_get`, line 378; RUNTIME: key absent today) or DNS pointed
  first. Browser sessions are host-scoped: operator logins reset. `DELIVERY_CDN_BASE_URL`
  (`cdn-beta`) is unaffected. Beta TLS today: `VIDRA_TLS_MODE=acme`, Let's Encrypt cert for
  `beta.sizetube.com` valid to 2027-02-02; `cdn-beta` uses an Origin CA cert (RUNTIME).

## 2. Audit table — runbook §9 (reconcile the final delta and domain behaviour)

| # | Criterion (§9) | Evidence | Status |
|---|---|---|---|
| 9.1 | Freeze source uploads/edits/account/moderation writes with a **tested** maintenance procedure | None exists or was rehearsed. PeerTube has no read-only mode. Prod nginx (RUNTIME) already uses `limit_except` on the upload locations, so a `limit_except GET HEAD OPTIONS { return 503; }` on `/api/v1/` is a natural shape; alternatives: stop `peertube.service` (kills the transcode backlog), or a Cloudflare rule blocking non-GET on `/api/v1`. Must wait for prod's queue to drain (finding 3). | **decision needed** (D2) |
| 9.2 | Refresh the snapshot and rerun against the **same** ledger | Procedure proven once (RUNTIME 2026-11-06: dump 16:54–16:59, SHA-256 equal both ends, restored, re-granted, swapped by rename; runs `0c6475c3`/`13d98e9d`/`bff44fc2` resumed the same ledger). Snapshot is already 8 videos / 6 users / 2 comments / 1 blacklist entry behind prod (RUNTIME prod 2026-11-08 00:57). | pass (procedure) / final one pending |
| 9.3 | Keep source storage and artwork reachable through the rerun | Read-only source key present in env (`PEERTUBE_SOURCE_S3_*` set, RUNTIME); artwork comes from prod `/lazy-static` (CODE `entities_actorimages.go:623-671`). Prod up (`peertube.service` active since 2026-10-27). Prod must stay up through the final run and the rollback window. | pass (as of now) |
| 9.4 | Rerun mode: gap-fill vs `source_authoritative=true` | Every run `source_authoritative=false` (RUNTIME, 10 runs). Not mirrored today: 8 state changes + 1 privacy flip (finding 4); prod `updatedAt` since 2026-11-04 10:16 on 3,876 videos, 24 channels, 139 playlists, 554 users (lastLogin bumps; 3 users changed beyond login = password/profile candidates) (RUNTIME snapshot). `ImportUpdateVideo` writes privacy/state/title/description/policies (CODE `peertube_import.sql:749-764`); `ImportUpdateUser` writes the password hash, role, email_verified, display_name, never `is_active` (`:721-738`); updates touch only import-created rows and never re-insert, rotate keys, assign views or overwrite renditions (`resync.go:38-80`). Beta-only edits worth keeping: none beyond settings (RUNTIME: 1 native video, 0 native channels besides `betatest`). | **decision needed** (D1; recommend `true`) |
| 9.5 | Source-deleted videos/accounts/comments need explicit reconciliation | RUNTIME `comm` of ledger ids vs snapshot: videos — 1 ledger uuid absent from the snapshot (`86c97689`, import *failed*, not on the beta); users identical; comments identical. **Nothing to reconcile as of the 2026-11-06 snapshot**; repeat the same three diffs after the final snapshot (no delete path exists in `resync.go`, CODE). | pass (now) / repeat at final |
| 9.6 | Later suspension / blacklist changes are not mirrored by reruns | CODE unchanged at v0.7.15 (`ImportUpdateUser` never writes `is_active`; no `video_blocks` resync). RUNTIME: the 11 prod-blocked users are all `is_active=false` here; blacklist 410 = 410 identical. Prod has since added 1 blacklist entry and 1 account-blocklist entry (RUNTIME prod); the final diff must be re-run and applied by hand. | pass (now) / **decision** at final run (D10) |
| 9.7 | Visibility mapping | RUNTIME beta imported: public 13,801 (13,792 published + 9 draft), private 1,638 (1,635 + 3 draft), unlisted 40, internal 29. Snapshot local: privacy 1 → 13,803, 2 → 40, 3 → 1,637, 4 → 29; the 2 failed videos are public, and `7476ede8` explains the private +1 / public −1. `videoPassword`: 1 row, its video is `private/published` here. Only state 1 → `published` (CODE `mapping.go:70-75`): the 12 drafts are the 4 genuinely unpublished + the 8 of finding 4. | pass (mapping) / drafts → D1 |
| 9.8 | Restricted access anonymously and as permitted/denied users | RUNTIME 2026-11-08 anon: imported **internal** video → API `401 sign_in_required`, page renders a "not found" shell; same for the password-protected video (now private). Beta-native private: anon 404 / owner 200 (RUNTIME 2026-11-04, Step 10). Permitted-user side (a signed-in imported account, internal = any account) **not tested**: no imported login was observed by this audit; the operator reports one succeeded (10.2a). | **partial** (permitted-user playback of internal/private media still untested) |
| 9.9 | Per-video download/comment policies | RUNTIME identical: `commentsPolicy` 1 → 15,507 / 2 → 2 vs beta `enabled` 15,506 (+1 failed) / `disabled` 2; `downloadEnabled` true 4,146 / false 11,363 vs beta 4,146 / 11,360 (+2 failed +1). No approval-only policy on the source. | pass |
| 9.10 | User sensitive-content preferences, category granularity | Source `nsfwPolicy`: display 5,533, do_not_list 4, warn 1, blur 1; beta: display 5,527, hide 9, warn 1, blur 1 (RUNTIME). 7 `user_sensitive_policy unsupported` → "granular or unknown … map conservatively to hide" (run `deferred` list). Instance default `display` matches prod. Lost granularity for the 7 is reported here. | pass with note |
| 9.11 | MFA: inventory only, hold accounts | Source `otpSecret`: 11 users (incl. root, which was skipped); beta: the other 10 are `is_active=false` (RUNTIME). A resync cannot release a hold (CODE). Re-enrolment process for the 10 undefined. | pass (hold) / **decision** (D11) |
| 9.12 | Personal account/server mutes; instance mutes; moderation reports | **Not carried** (run `deferred`: "moderation state (account/server blocklists, abuse reports…)"). Source now: `accountBlocklist` 172→173, `serverBlocklist` 1, `abuse` 233 (**215 open**, 207 on videos, 1 on a comment) (RUNTIME). | **fail** → decision (D10) |
| 9.13 | Old `/w/<short-id>` and UUID links, `resolve?legacy_uuid`, embeds, query strings, non-video routes | RUNTIME 2026-11-08 (anon): `/w/<pt-short>` 302 → `/v/<code>`; `?start=30` → `?t=30`, `?start=1m30s` → `?t=1m30s`; `/videos/watch/<uuid>` 302 (same rewrite); `/videos/embed/<uuid>` 302 → `/embed/<id>` (`?start` → `?t`); `resolve?legacy_uuid=` 200; final pages 200 (CODE vidra-user `app/w/[sid]/route.ts:39-47`, `app/videos/watch/[id]/route.ts:35-41`, `app/videos/embed/[id]/route.ts:23-28`). Not working: `/c/<h>/videos` 404, `/channels/<h>/videos` 404, `/video-channels/<h>` 404 (HTML and AP), `/accounts/<n>` 404, `/a/<n>` → 404 (profile_public). | **partial** (video links pass; channel/account links fail) |
| 9.14 | Federation continuity: same domain + same handles | RUNTIME: 20 followers skipped on every run (§1); `FEDERATION_ENABLED=false`; webfinger/nodeinfo/host-meta 404 today; `instance_followers`/`remote_actors` 0. Source also has 13 instance-actor followers and 30 outbound follows that the importer does not carry. §9 checks 1–3 not run. | pending the post-flip rerun; **decision** (D9) |
| — | Pending prod videos | RUNTIME prod 2026-11-08 00:57: `039ec94f` state 1 (8 B2 renditions; on the beta `draft`, no HLS); `6f2fdd7e` / `892d1947` **state 8 again** (move raced the re-transcode; 1 transcoding job still active for `892d1947`); `7e23b8d9` state 2 since 2026-08-30 and `967f57d6` state 8 since 2026-06-21 (source-side, local-only files, cannot import); new upload `0b8d6d54` state 2. Backlog: 70 prioritized jobs / 12 videos at concurrency 1. All need: prod queue drained → approved move script for the state-8 pair → snapshot refresh → final rerun (`source_authoritative` for their state). | pending → D16 |

## 3. Audit table — runbook §10 (accept, switch traffic, retain rollback)

| # | Criterion (§10) | Evidence | Status |
|---|---|---|---|
| 10.1 | Final import counts; no unexplained failures or tombstones | RUNTIME after `bff44fc2` (2026-11-08 01:15): users 5,538, channels 5,590, videos 15,508 (+1 failed `7e23b8d9`, stuck at the source), hls 14,775 done / **687 failed, all `source_open/not_found`** (683 = one banned owner's private videos, 4 renditions each; the rest missing at source), thumbnails 683 and captions 669 failed (source missing), storyboards 10,982 failed (prod has no files) + 2,100 done + 4,507 skipped (beta-generated sheets). `video_no_media` 687. Every failure is explained; none is fixable from the source except the two state-8 videos once prod moves them. | pass (explained) / **decision** on the 687 media-less published videos (D7) and storyboards (D8) |
| 10.2a | Login with imported accounts | **Not observed by this audit.** QA used freshly created accounts; the owner `root` is beta-native; hash carry is proven on fixtures (release-readiness A19). Operator statement 2026-11-08: an imported-account login was tested and works. | operator-reported — record the account and date in the private log before cutover |
| 10.2b | Owner/admin permissions | All admin pages load (RUNTIME QA #28, v0.7.13). Beta has 1 admin/owner (native root); prod has 1 admin + 1 moderator (RUNTIME) — the prod moderator's role carries (`ImportUpdateUser` writes `role`), but no imported account is admin here (RUNTIME `admins=0` among imported). | pass / note |
| 10.2c | Password reset and mail delivery after deliberate SMTP enablement | `MAIL_ENABLED=false`, SMTP keys empty (RUNTIME env). Prod's own sender is a dead relay (finding 2), so there is nothing to copy. DigitalOcean blocks 25/465/587 (`docs/outbound-email.md:30`); use an HTTPS API transport or an SMTP relay on 2525/2587 via Admin → Email. RUNTIME 2026-11-08 03:05: `smtp.improvmx.com` 587/465/2525 are unreachable from **both** droplets (the operator's ImprovMX SMTP credential itself works from outside DigitalOcean); ImprovMX has no HTTPS API, so **Resend** was chosen (account created; domain records, API key and the Admin → Email test still pending). The settings secret is sealed with `MailKEK()` = `MFA_KEY_KEK` (falls back to `FEDERATION_KEY_KEK`) (CODE `config.go:2902-2924`); RUNTIME: `MFA_KEY_KEK` is set. Interim for ordinary users: admin-minted reset link `POST /api/v1/admin/users/:id/password-reset-link` (`server.go:2379`, needs `PUBLIC_BASE_URL`). | **fail** → D4 |
| 10.2d | Registration policy and quotas | Beta: `REGISTRATION_ENABLED=false`, `registration_enabled=false`, `REGISTRATION_REQUIRE_APPROVAL=false`, `INSTANCE_DEFAULT_QUOTA_BYTES=5368709120` (RUNTIME env) vs runbook §5 `0`. Prod (RUNTIME public config): signup allowed, `limit -1`, no approval, no e-mail verification, `minimumAge 18`, quotas unlimited (`-1`), 822 logins in the last 7 days. Imported accounts: all 5,538 have `storage_quota_bytes=0` (RUNTIME). No default channel after signup (QA #37). `registration_minimum_age` unset → 0 (CODE `instancesettings/service.go:1185`). | **decision** (D6) |
| 10.3 | Synthetic upload through the real scanner → transcode → playback → seek → captions → previews → search → delete | Upload → `published` (~20 s) → plays → delete 204 under `MALWARE_SCAN_MODE=fail-closed` (RUNTIME QA #38, v0.7.13). Seek, captions/previews and search indexing of that upload not asserted; EICAR rejection never run. `TRANSCODING_ENABLED=true` (RUNTIME env). | **partial** |
| 10.4 | Representative imported originals/HLS incl. restricted media; old links; mobile/browser playback; federation | HLS playback incl. 4K `a2ed643c` (RUNTIME 2026-11-06), quality switch and captions (QA #12-14); audio group present (finding 6). Imported originals (`/original` on 1,920 videos) and restricted imported media as a permitted user: not tested. Old links: 9.13. Mobile: shots captured, not reviewed (QA #18). Federation: off. | **partial** |
| 10.5 | Independent DB/config restore; media recovery; backup alerting; dependency-outage recovery | **Restore drill PASS on the post-import data (RUNTIME 2026-11-08 03:27–03:34 UTC):** newest off-site pair `vidra-20261108T032456Z` (112 MB) fetched from the crypt remote in 3 s, SHA-256 identical to the local copy, restored into a throwaway `postgres:18-alpine` container (same digest as the stack) with `pg_restore` rc 0 in 38 s, schema 188 / search 21, 164 of 165 table counts identical to live (`video_files` +8 from the live storyboard backfill), then `verify-blobs` on the restored DB: 55,260 referenced objects, 55,260 present, 0 missing, exit 0 in <4 min. **RTO ≈ 45 s for the database, ≈ 5 min with the blob check.** Caveats: same host as the stack (separate container and volume, not a separate machine); `--hash` not run. The earlier 2026-11-04 drill was pre-import, schema 182. Nightly backup ran 2026-11-07 03:16 UTC: dump + config archive, both uploaded to the rclone crypt remote, next 2026-11-08 03:24 (RUNTIME journal). **No `HEALTHCHECKS_URL`** in `/etc/vidra/backup.env` (RUNTIME) → silent on failure. Media DR open: bucket has no lifecycle, Object Lock or replication (RUNTIME `b2 bucket get`), the runtime key can delete, 11 unfinished large files (427.6 MB, 2026-11-05) still stranded (RUNTIME), lost-object restore untested. **GC deleted 38 objects live** (finding 1). Search-outage recovery (reconcile_orphan defect, AGENTS.md): not tested. | **partial / High** → D12 |
| 10.6 | Only then switch DNS/proxy; recheck TLS, API origin, cookies/CORS, playback, search, old URLs | Not started. RUNTIME DNS: `sizetube.com` and `cdn.sizetube.com` are Cloudflare-proxied (edge cert Google Trust Services, to 2026-12-15); `beta.sizetube.com` is DNS-only to 159.203.29.27 with a Let's Encrypt cert. Prod nginx has a `cloudflare-realip` snippet; the beta's `TRUSTED_PROXY_CIDRS` is already the Cloudflare range list (RUNTIME env). | pending → D3 |
| 10.7 | Enable mail/federation/background features deliberately | Pending D4, D8, D9. `TRANSCODING_ENABLED=true` throughout the import (RUNTIME env) — a §5 deviation, harmless for copy mode (the importer never enqueues transcodes), recorded here. `storyboards_enabled` has no override → default **on** (CODE `service.go:1049`): the beta generated 2,100 + 4,507 sheets the import then skipped (RUNTIME). | pending |
| 10.8 | Revoke importer access after the reconciliation window | `PEERTUBE_IMPORT_ENABLED=true`, source DSN and read-only S3 key present, `pt_import_reader` role and both snapshot DBs (1,384 MB each) in place (RUNTIME). | pending |
| 10.9 | Rollback: original service, pins, frozen snapshot and source media retained; what happens to new Vidra writes | PeerTube still serves `sizetube.com` with its bucket untouched (`sizetube`: allPublic, 30-day hide-to-delete lifecycle, RUNTIME). `rollback.sh` is for Vidra version rollback; platform rollback = DNS back. Write-preservation policy for the window: undefined. | **decision** (D14) |

## 4. Beta env — §5 pause set (live values, RUNTIME 2026-11-08)

| Key | Runbook §5 | Live value | Note |
|---|---|---|---|
| `REGISTRATION_ENABLED` | false | `false` (+ `registration_enabled=false`, `REGISTRATION_REQUIRE_APPROVAL=false`) | prod is open (10.2d) |
| `FEDERATION_ENABLED` | false | `false` | 20 followers wait on the post-flip rerun |
| `MAIL_ENABLED` | false, then deliberate | `false`; `SMTP_HOST/USERNAME/PASSWORD/FROM` empty, `SMTP_PORT=587` | D4 |
| `MEDIA_GC_ENABLED` | **false during migration** | `false` since 2026-11-08 02:55 UTC (was `true`; one live delete sweep on 11-07), `MEDIA_GC_MAX_ORPHAN_PERCENT=25` | D12 applied |
| `INSTANCE_DEFAULT_QUOTA_BYTES` | 0 | `5368709120` | prod unlimited; imported users 0 |
| `MALWARE_SCAN_MODE` | fail-closed | `fail-closed`, `CLAMAV_TIMEOUT=60s`, `QUARANTINE_NEW_UPLOADS=false` | |
| `storyboards_enabled` (runtime) | off before the run | unset → default on | generation ran during the import |
| `PUBLIC_BASE_URL` / `NEXT_PUBLIC_API_BASE_URL` / `CORS_ALLOWED_ORIGINS` | — | all `https://beta.sizetube.com` | §1 |
| `TRANSCODING_ENABLED` | off during import | `true` (`TRANSCODING_HW=off`, `cmaf`, VP9 off) | 10.7 |
| `FEATURE_LIVE_ENABLED` / `YTDLP_IMPORT_ENABLED` / `IPFS_MANAGED_NODE` | — | `false` / `false` / `false`; no `CHANNEL_SYNC` or `OAUTH_PROVIDERS` keys | |
| `VIDRA_TLS_MODE` | — | `acme` | D3 |
| `TRUSTED_PROXY_CIDRS` | — | the 22 Cloudflare ranges | ready for a proxied `sizetube.com` |
| `DELIVERY_CDN_BASE_URL` | — | `https://cdn-beta.sizetube.com` (+ `delivery_cdn_enabled=true`, purge worker URL set) | unaffected by the flip |
| `RATE_LIMIT_REQUESTS` | — | `300` (`MEDIA_RATE_LIMIT_REQUESTS=3000`) | |
| `PEERTUBE_IMPORT_*` | — | enabled, `skip`, `copy`, concurrency 12; source DSN + S3 key set; no server-copy key | 10.8 |
| KEKs | — | `MFA_KEY_KEK` set; no `FEDERATION_KEY_KEK` / `ATPROTO_KEY_KEK` | mail secret sealing works (10.2c) |
| `INSTANCE_TERMS_URL` / `INSTANCE_PRIVACY_URL` / `INSTANCE_CONTACT_EMAIL` | — | all empty | §8 compliance |
| `VIDRA_SKIP_DNS_PREFLIGHT` | — | absent | needed if D3 = proxied |
| `HEALTHCHECKS_URL` (backup.env) | — | absent | 10.5 |

## 5. Proposed cutover order

0. **Gates before any window:** D1–D16 answered; `MEDIA_GC_ENABLED=false` applied **before
   2026-11-08 19:12 UTC** (finding 1) and kept off through the rollback window; prod queue
   drained and `6f2fdd7e` / `892d1947` moved and published (approved script, only when their
   jobs are gone); mail configured on the beta and a reset mail received; imported-account
   login proven (D13); post-import restore re-drill on the current dump with `verify-blobs`;
   fresh off-site backup; if D3 = Cloudflare-proxied, an Origin CA cert for `sizetube.com`
   on the droplet and `VIDRA_SKIP_DNS_PREFLIGHT=1`; `profile_public`, quota, terms/privacy
   URLs and anonymous-NSFW decisions applied; `branding_hide_software_name` **on** and the
   instance imagery set in Admin → General → Branding (both off / fallback today, finding 10);
   this doc merged.
1. **Freeze prod** (D2 mechanism) at T0, verify a write is refused, record T0. Prod stays up
   read-only for artwork, rollback and `/lazy-static`.
2. **Snapshot** (Step 25 procedure): dump → SHA-256 both ends → restore as a new DB → §3
   grants → swap names; keep the previous snapshot.
3. **Hostname flip** on the beta: `backup.sh` → env (`PUBLIC_BASE_URL`,
   `NEXT_PUBLIC_API_BASE_URL`, `CORS_ALLOWED_ORIGINS`; `VIDRA_SKIP_DNS_PREFLIGHT=1` if
   proxied) → `Caddyfile.local` (site `sizetube.com`, cdn block `Host`, drop IP gate and
   `noindex`) → `vidra setup --check` → `deploy.sh` →
   `curl --resolve sizetube.com:443:159.203.29.27 https://sizetube.com/healthz` and the
   admin infra page's `public_base_url`.
4. **Final rerun**: dry run, then `run` with `source_authoritative` per D1 from
   `/admin/import-peertube`; confirm `remote_follower.imported=20` (or the deferred count),
   the state-8 pair's HLS, the 8 drafts now `published`, zero transient failures; re-run the
   9.5/9.6/9.12 diffs and apply D10 by hand through supported APIs.
5. **Re-accept on the real hostname** via a hosts override: login as the D13 account, reset
   mail, playback (public / private / internal as a permitted user), old links incl. embeds,
   admin pages, a synthetic upload.
6. **DNS**: Cloudflare `sizetube.com` → 159.203.29.27 (proxied per D3). Recheck TLS,
   cookies/CORS, playback, search, old URLs publicly; watch api logs for 429/5xx; then enable
   registration / mail / federation per decisions, each with its own check.
7. **Rollback window** (length per D14): PeerTube frozen-but-running, env pins v0.7.15, both
   snapshots and dumps kept, source bucket untouched, GC still off. Rollback = DNS back +
   unfreeze + a final `backup.sh` run. After the window: `PEERTUBE_IMPORT_ENABLED=false`,
   drop `pt_import_reader` and the snapshot DBs, delete the read-only B2 key, re-enable GC
   (after a dry-run sweep reads 0 unexpected orphans), decide the fate of `beta.` /
   `cdn-beta.` and `cdn.sizetube.com` (stays on B2 for rollback).

## 6. Operator decisions still open

- **D1** Final rerun mode: `source_authoritative=true` (**recommended** — it is the only way
  the 8 drafts, the privacy flip, 3,876 edited videos, 139 playlists and any password change
  reach the beta) or gap-fill.
- **D2** Prod freeze mechanism and window length; who owns rollback.
- **D3** TLS/DNS topology for `sizetube.com` on the droplet: Cloudflare-proxied + Origin CA
  cert in `Caddyfile.local` (cert exists before DNS moves; matches `cdn-beta` and prod today;
  needs `VIDRA_SKIP_DNS_PREFLIGHT=1`) **vs** DNS-only + Let's Encrypt `acme` (cert only
  obtainable after DNS points here → TLS gap + rate-limit risk). Also what `beta.` /
  `cdn-beta.` become.
- **D4** Mail provider: HTTPS API transport via Admin → Email or an SMTP relay on 2525/2587;
  SPF/DKIM/DMARC for `sizetube.com`. Prod's relay is dead (finding 2), so this is net-new
  and also fixes a prod outage.
- **D5** `profile_public=false` on all 5,538 imported accounts (importer never sets it;
  column default false, migration `0091`): one-off audited `UPDATE` on ledger users (approval
  + backup), an importer fix + release, or accept 404 account pages.
- **D6** New-signup policy: `INSTANCE_DEFAULT_QUOTA_BYTES` 0 vs 5 GiB, registration
  open/approval, e-mail verification, terms acceptance at signup, default channel,
  `registration_minimum_age` (prod shows 18).
- **D7** The 683 published-but-media-less videos (RUNTIME 2026-11-08: all belong to the one
  source-banned, inactive owner; all are already `private`; 394 already carry a `video_blocks` row,
  so 289 remain): block via `video_blocks`, leave as 404-on-play, or hide the owner's channel.
  The 4 other media-less videos are drafts pending prod (`039ec94f`, `6f2fdd7e`, `892d1947`, `967f57d6`).
- **D8** Storyboards: keep `storyboards_enabled` on and let `storyboardbackfill` render the
  ~11k missing sheets from HLS masters (`storyboard_backfill.sql.go:90-138`: eligible =
  published, no sheet, original or ready HLS; paused while an import is pending/running; one
  full decode per video, 5 bounded retries) — CPU and B2 egress — or leave previews absent.
- **D9** Federation at/after cutover (carries the 20 followers on the post-flip rerun; §9
  checks 1–3 then apply; the 13 instance-actor followers and 30 outbound follows are not
  carried) or stay off.
- **D10** Moderation state not carried (173 account mutes, 1 server mute, 233 abuse reports
  of which 215 open; suspension/blacklist deltas since the snapshot): export from PeerTube
  for the record, re-apply by hand, or accept.
- **D11** Re-enrolment process for the 10 MFA-held accounts (operator-restricted window;
  never a plain reset).
- **D12** Media DR and the GC: `MEDIA_GC_ENABLED=false` now (or
  `MEDIA_GC_MAX_ORPHAN_PERCENT=0`) through the window; B2 replication / Object Lock to a
  separate account; a media key without `deleteFiles`; a timed lost-object restore; the 11
  stranded uploads; a post-import restore re-drill with `verify-blobs`; `HEALTHCHECKS_URL`.
- **D13** Which imported account proves login (one whose password the operator legitimately
  holds, or a consenting user); it also covers the permitted-user half of 9.8.
- **D14** Rollback policy for writes made on Vidra during the window (accept loss / export /
  none).
- **D15** Compliance items (§8) — LAWYER-class, not code; the five intake answers below.
- **D16** (new) The prod transcode backlog: freeze only after the 70 jobs drain (days at
  concurrency 1), or freeze now and accept that up to 12 recent videos ship with partial
  rendition sets — 4 of them are already `done` here with a single 720p rendition and the
  importer will not re-copy a ready tree (CODE `hls_backfill.go:93-131`). A supported
  refresh path does not exist; the unsupported alternative is deleting those videos' HLS
  rows/ledger rows and re-running, which this audit does not recommend without a core change.

### Decisions recorded 2026-11-08 (operator answers, 01:40–02:05 UTC)

| # | Decision |
|---|---|
| D1 | `source_authoritative=true` for the final rerun |
| D2 | Freeze = nginx returns 503 for non-GET/HEAD on `/api/v1/` (reads stay up); operator owns rollback |
| D3 | Cloudflare-proxied + Origin CA cert in `Caddyfile.local`; `VIDRA_SKIP_DNS_PREFLIGHT=1` |
| D4 | **Resend** (HTTPS API) via Admin → Email — chosen 2026-11-08 after ImprovMX SMTP proved unreachable from DigitalOcean; domain verified, key sealed and one test delivered 2026-11-09; a password-reset mail to an imported account is still unproven. Free tier (100/day) covers resets, not a 5,538-user notice |
| D5 | One-off audited `UPDATE` of `profile_public` on ledger users, after a backup, with approval |
| D6 | Registration open at cutover with e-mail verification, `registration_minimum_age=18`, terms/privacy acceptance first; `INSTANCE_DEFAULT_QUOTA_BYTES=0` |
| D7 | Block the remaining 289 of the 683 media-less published videos via `video_blocks` (394 already blocked; all private; one owner) |
| D8 | Keep `storyboards_enabled` on; let the backfill run after cutover |
| D9 | Federation stays off through cutover and the rollback window; enable later with §9 checks 1–3 |
| D10 | Export moderation state from PeerTube for the record; re-apply suspension/blacklist deltas by hand; accept losing mutes and reports |
| D11 | Operator-restricted MFA re-enrolment window for the 10 held accounts |
| D12 | `MEDIA_GC_ENABLED=false` **applied 2026-11-08 02:55 UTC**, kept off through the rollback window; post-import restore drill PASS 03:34 UTC (10.5); replication/Object Lock, non-deleting key, `HEALTHCHECKS_URL` still open |
| D13 | Operator states an imported-account login was tested and works (not observed here) |
| D14 | Accept the loss of Vidra-side writes on rollback; registrations closed during the window; `backup.sh` at rollback time |
| D15 | **Open** — the five compliance intake questions were not answered |
| D16 | Wait for the prod transcoding queue to drain, move the state-8 pair, then freeze and snapshot |
| — | White-label: operator enables `branding_hide_software_name` and sets the instance imagery before cutover (finding 10). Switch on since 2026-11-11; imagery still the fallback |

Executed so far (each with the operator's explicit go-ahead):

- 2026-11-08 02:55 UTC — D12: `MEDIA_GC_ENABLED=false` deployed (env backup kept; `deploy.sh` exit 0).
- 2026-11-08 03:27–03:34 UTC — 10.5: post-import restore drill + `verify-blobs`, PASS (details in 10.5).
- 2026-11-08 — prepared, **not applied**, in the operator's private log (`cutover-prep/`): D5 and D7 audited SQL
  with dry-run counts, the D10 moderation export from the 2026-11-06 snapshot, the D2 nginx freeze snippet, the flip
  env patch and the target `Caddyfile.local` (the file is generated by `vidra setup`, so the flip is edit env →
  `vidra setup` → re-add the hand-added blocks), and the Resend → Admin → Email steps.
- 2026-11-08 03:23–09:34 UTC — D16: a read-only watcher followed prod's transcoding backlog (61 prioritized jobs at
  03:23 UTC, from 70; 49 at its last reading). It stopped at 09:34 UTC when the SSH agent lost its key, and nothing has
  watched the queue since.
- 2026-11-09 05:52–06:20 UTC — D4: mail set to Resend in Admin → Email with the key sealed, the three Resend DNS
  records added, the domain verified, one test message delivered.
- 2026-11-09 06:03–06:17 UTC — D16: prod's queue read empty at 06:03; the state-8 pair moved to object storage at
  06:13–06:17 (both state 1, 0 local files, 8 in the bucket).
- 2026-11-09 06:16 UTC — contact e-mail set in Admin → General.
- 2026-11-10 16:21–17:47 UTC — ads: the provider and the three policy switches written to the env file (16:21),
  v0.7.17 deployed (16:56), the ported custom script installed in Admin → Advanced → Custom JavaScript (17:47).
- 2026-11-10 14:13, 16:33 and 19:24 UTC — three gap-fill import runs started by the owner, none with
  `source_authoritative`. Each ended `done` with nothing imported or updated and the failure sets already known.
- 2026-11-11 — in-player VAST: v0.7.18 deployed 06:11 UTC (DEDUCED from the pre-deploy dump and the release record)
  and v0.7.19 at 22:20 UTC; the white-label switch turned on at 14:28 UTC; the VAST settings saved from 14:30 UTC.
- 2026-11-11 — planned: a dress rehearsal of window steps 1–5 and the rollback on a throwaway droplet, and one
  read-path load check (run 2026-11-12, below).
- 2026-11-12 10:20–10:31 UTC — read-only status re-read of the beta, DNS, the buckets and prod's public API; the
  per-item results are in the [checklist](sizetube-cutover-checklist.md). **Still not applied:** D5, D7, D6, the
  anonymous-NSFW policy, the terms and privacy URLs, the instance imagery, the D3 certificate and
  `VIDRA_SKIP_DNS_PREFLIGHT`, and the whole D12 tail (replication or Object Lock, a non-deleting media key,
  `HEALTHCHECKS_URL`, the 11 unfinished large files). Not read: prod's queue and request rate (prod SSH had not
  been approved).
- 2026-11-12 11:14–13:07 UTC — the dress rehearsal and the load check, on a throwaway droplet built from the beta's
  03:26 UTC backup and destroyed afterwards; per-step results are in the [checklist](sizetube-cutover-checklist.md),
  sections C and G. Steps 1–5 and the rollback ran: about 15 minutes of machine time for steps 2–5 without the
  rerun's media part, about 7 minutes for the rollback. Found and fixed: the D2 freeze snippet failed `nginx -t`.
  Found and open: the Origin CA certificate must name `sizetube.com` only; the final rerun in copy mode has still
  never run; three read endpoints take 0.5–1.2 s each, and the read path failed the load check at the estimated peak
  (270 page views a minute asked, 74 completed; it keeps up to roughly 120–150). D13 was proven on the copy, the
  operator typing the password. Nothing on prod or the beta was changed; the beta's bucket gained one test upload
  and some hidden write probes, and none of its own objects was overwritten or hidden.
- 2026-11-12 — operator decisions after the rehearsal: build both pieces of D15 code ahead of counsel's answers (the
  signup consent record, and the anonymous gate for sensitive videos shipped switched off); plan a fix for the three
  slow read endpoints before any code; leave the rehearsal's test objects in the bucket. Nothing is built yet.

Everything else above is still a change the operator (or a later, separately approved task) makes.

## 7. What this audit does NOT establish

Byte-level integrity beyond the importer's own checks; feature parity (the parity QA's job);
media disaster recovery; which 38 objects the GC deleted; that the cutover can run without a
maintenance window (the `acme` path cannot); anything legal — §8 is engineering guidance.
Login with an imported password was not established by this audit either; it was proven on a
rehearsal copy on 2026-11-12 (checklist D13).

## 8. Skill reviews (durable, compliance-guard)

Two read-only reviews. Neither touched a host, database or bucket beyond the reads above.

### Durable (data loss) — feeds 10.5 and D12

- **RPO (CODE + RUNTIME):** one `pg_dump` a day at 03:15 (+≤15 min)
  (`deploy/vidra-backup.timer:12,15`) plus pre-deploy dumps; Redis and media are
  deliberately not dumped (`deploy/backup.sh:21-27`). The 2026-11-07 03:16 run succeeded,
  102 MB, uploaded off-site (RUNTIME). Up to ~24 h of Vidra-side writes are exposed.
  **RTO:** one restore of a 75 KB schema-182 dump (RUNTIME 2026-11-04), no wall-clock
  recorded, `verify-blobs` not run — no RTO exists for the real DB.
- **Critical:** media has one copy, deletable by the runtime key (bucket: no lifecycle,
  Object Lock or replication — RUNTIME `b2 bucket get`; key …028 has `deleteFiles` — RUNTIME
  Step 13). The only second copy is prod's `sizetube` bucket, which decays (30-day
  hide-to-delete lifecycle, RUNTIME). Control: B2 replication or Object Lock to a separate
  account, then a timed hide-and-restore drill.
- **High — MEDIA_GC is live and has already deleted (finding 1).** The empty bucket was
  claimed at first boot (`.vidra/owner` uploaded 2026-11-04 10:22 UTC, RUNTIME;
  `cmd/api/main.go:4678-4698`), so `AllowsDelete()` is true (`mediagc/service.go:99-101`).
  The remaining rail is the breaker: deletes unless orphans > 100 **and** >
  `MEDIA_GC_MAX_ORPHAN_PERCENT` of scanned (`service.go:105-114`). A restore from any
  mid-import dump would leave a 1–24 % orphan share, under the breaker, deleted within 24 h.
  Control for the window: `MEDIA_GC_ENABLED=false` (what §5 asks) or
  `MEDIA_GC_MAX_ORPHAN_PERCENT=0`; apply before the next sweep (~2026-11-08 19:12 UTC).
- **High:** the restore drill is stale (pre-import, schema 182) — re-drill the newest
  off-site pair with the same postgres digest, time it, run `verify-blobs` read-only.
- **High:** rollback-window write loss (DNS back discards Vidra writes; `resync.go` flows
  source → Vidra only). Control: registrations stay closed during the window; a final
  `backup.sh` run at rollback time; keep the bucket (→ D14).
- **Medium:** `rollback.sh` rolls the app tag only and refuses older cores while `internal`
  videos exist (29 imported) — irrelevant to a DNS rollback, relevant to any v0.7.8 rollback
  (schema 182 = pre-import data). **Medium:** `HEALTHCHECKS_URL` is opt-in and silent when
  unset (`backup.sh:111-119`) — absent (RUNTIME). **Medium:** the crypt password/salt is a
  single point of failure (copy count unverified). **Low:** off-site never pruned; the 11
  unfinished large files are invisible to GC.

### Compliance-guard (engineering guidance, not legal advice; nothing certified) — feeds D15

Intake defaults applied, assumption-based: anyone on the internet, worldwide, real data,
under-18s possible with no age gate (`registration_minimum_age` defaults to 0, CODE
`instancesettings/service.go:1185`; the signup form has an age checkbox, never
verification), no registered company. The operator must answer: (1) is any of the catalogue
*pornographic / "sexual material harmful to minors"* under the laws of the US states and the
UK it reaches — prod's own terms call it "an NSFW content-sharing platform specializing in
niche size fetish and giantess fetish content" and `isNSFW=true` (RUNTIME), so the
classification question is live, not hypothetical; (2) entity, jurisdiction, address, privacy
contact (`INSTANCE_CONTACT_EMAIL` empty, RUNTIME); (3) EU/UK traffic blocked or served;
(4) will imported users be notified before login reopens, and will new-video e-mails be sent
(prod: 15 of 5,539 users have the e-mail bit set for that notification; the beta has no
preference rows, RUNTIME); (5) keep `sensitive_content_policy=display` for anonymous visitors?

- **BLOCKER / LAWYER — NSFW catalogue shown to anonymous visitors with no age assurance.**
  12,401 of 15,508 imported videos are `is_sensitive` (RUNTIME). Under `display` the player
  plays normally; the client gate exists only for blur/warn/hide (vidra-user
  `components/WatchView.tsx:200-211, 508-511`), and `hide` is the only server-enforced mode
  (`sqlcgen/catalog_read_proof.sql.go:18-24`). Regimes: 26 US state age-verification laws,
  several with private suits **[V]**; UK Online Safety Act — no small-service exemption,
  Ofcom fines for missing age assurance on pornographic services **[V]/[S]**. Same exposure
  exists on prod today (`defaultNSFWPolicy: display`, RUNTIME). Interim control: `hide` (or
  `warn`/`blur` + login) for anonymous viewers until counsel answers; `hide` re-creates the
  empty anonymous feed seen in Step 22.
- **BLOCKER — signup has no terms/privacy acceptance and keeps no consent record**
  (`SignupForm.tsx` has username/email/password/age only; `INSTANCE_TERMS_URL` /
  `INSTANCE_PRIVACY_URL` empty on the beta, RUNTIME). Prod's wizard has a Terms step (5,172
  chars, plus a 2,679-char code of conduct; no privacy policy text — RUNTIME). Control before
  reopening registration: both URLs set, an unchecked "I agree" with live links,
  `{user, ts, terms_version}` stored. GDPR Art 13 **[V]**.
- **HIGH — 5,538 imported users move to a new controller/system with no notice** and no
  mail to send one (→ D4 first; prod's mail is also down, finding 2). GDPR Art 13/14 **[V]**;
  B2 in the US → transfer basis **[S]**. LAWYER for the notice text.
- **HIGH — notification mail has no `List-Unsubscribe` header** (none anywhere in core —
  grep), and imported users have no `notification_prefs` rows, so code defaults decide what
  5,538 people receive the day mail is enabled (RUNTIME). CAN-SPAM / Gmail bulk rules
  **[S]**; CASL (host in Toronto) is **not covered** by the references → LAWYER.
- **HIGH — abuse reporting needs a login** (`server.go:2162` `requireAuth`); no non-user
  NCII / DSA notice path or published DMCA agent found (DEDUCED from absence). 215 open prod
  reports are not carried (RUNTIME; D10). TAKE IT DOWN §3 reaches non-users, 48 h **[V]**;
  DSA notice-and-action **[V]**.
- **MEDIUM:** data export routes exist (`server.go:1768-1770`, setting default true
  `service.go:1068`) but QA saw 404 on `GET /me/export` without a prior `POST` — verify the
  flow, not the build. **MEDIUM:** account deletion's blob cleanup is best-effort
  (`internal/account/delete.go:194`); placeholder row retained. **MEDIUM:** Google Analytics
  is consent-gated, default denied, DNT/GPC honoured (`GoogleAnalytics.tsx:8-49`); no
  measurement id is set on the beta (RUNTIME env) — prod runs a `google-analytics` plugin and
  a `vast-ads` plugin (RUNTIME public config), neither of which carries over. **LAWYER:**
  18 U.S.C. §2257 if the content is sexually explicit (references carry no material — [U]);
  entity/representatives (Art 27 **[V]**).
- Not checked by either review: the PeerTube admin panel, mobile, accessibility, the
  security baseline, Canadian law, Cloudflare settings.
