# REC-03 / A38 on published v0.6.4 — upgrade, injected failure, rollback, restore — 2026-09-13

**Verdict: REC-03 PASS on the published v0.6.3 → v0.6.4 images**, with the caveats
in "Not covered". **OPS-01 stays UNVERIFIED**; the passed subset (split topology
deploys, the worker transcodes) is recorded below.

This is the "next milestone" the 2026-09-13 continuation named: REC-03/A38 on
one more disposable host, rebuilt by the operator. Every step ran the released
scripts as the `vidra` user on a git-path install — the topology beta runs —
against the published GHCR images, with **local** media storage so the drill
could never touch the shared B2 test bucket. Nothing here touched production.

Driver: [`tests/rec03-upgrade-rollback.sh`](../tests/rec03-upgrade-rollback.sh)
(phases `install → data → backup → inject → upgrade-fail → recover → backup2 →
rollback → restore-refuse → repin → restore-ok → split → report`). The copy that
executed is sha256 `1a327ae9e5c12eae14c895273444fc866f35de5b40988d31764b57089756fc06`;
the committed copy differs only by shellcheck quoting and `find`-for-`ls`
substitutions made afterwards so it passes `meta-ci`'s lint. Evidence:
[`docs/evidence/release-v0.6.4-verification/rec03-runtime/`](evidence/release-v0.6.4-verification/rec03-runtime/)
— one log per phase plus `facts/<phase>.json` (the verdict inputs) and
`summary.json` (digests, host, verdicts).

## Candidate

| Component | v0.6.3 (start) | v0.6.4 (candidate) |
|---|---|---|
| vidra-core | `ghcr.io/yegamble/vidra-core@sha256:8636d5daf37674c6fa867294f47e615bbbb9b0ef6ca65984201ea32ef3f7c64e` | `…vidra-core@sha256:f653962115c8f36857e237b9e0ec9c95d89fef5b1f23cdcea75c20d1582f42a0` |
| vidra-user | `…vidra-user@sha256:083d399408b64b268ce8cef44185e5dc56ebe4e710457e5dfbcd1cd252ad680d` | `…vidra-user@sha256:443336d4945365337e9459c270d51c80d1f62f9923ba80efffd3130389f814a3` |
| vidra-search | `…vidra-search@sha256:fc6bdd6fcc4abc65858bb9f3394f4a1f85a4337977b2e973311fbf9769675ee9` | `…vidra-search@sha256:afcdb8a4bba86adfc7c64c4ea8a5e6edd8411fbc97c3f1a5f31dfb999dafb2cc` |
| core schema / search schema | 144 / 18 | 146 / 18 |

The v0.6.4 core digest is the same `f653962115c8…` the recovery drill's runtime
snapshots recorded, so both drills ran the same bytes. Meta tree: `v0.6.3` tag
for the install, `v0.6.4` tag for the upgrade (via `origin/main` at `67840ab`,
see the pin-release finding).

## Host

Droplet `599531580` (`vidra-beta-v064-b2-acceptance`, 159.203.118.182), rebuilt
by the operator with `doctl compute droplet-action rebuild … --image
ubuntu-24-04-x64` (action 3404163963, 05:05:38 → 05:06:09 UTC). Blank on
arrival: Ubuntu 24.04.4, x86_64, 8 vCPU, 15 GiB, 309 GB disk, no Docker, no
`/opt`, Python 3.12.3. The installer put Docker 29.8.0 + Compose 5.5.1 on it.
The stack served `https://rec03.video.test` through Caddy's internal CA
(`VIDRA_TLS_MODE=internal`, `/etc/hosts` pin, `VIDRA_SKIP_DNS_PREFLIGHT=1`).

## What ran, in order

Times are UTC on 2026-09-13. Every phase's full output is in its log.

### 1. Install v0.6.3 and create data — `install.log`, `data.log`, `fp.log`

- Released installer `raw.githubusercontent.com/yegamble/vidra/v0.6.3/install.sh`
  (sha256 `6b7a6152015dd404c2d3b8410a1de70a8911ecad0a68e468aed9bb92c0572674`)
  with `--git --ref v0.6.3 --yes`: Docker from Docker's apt repo, meta clone at
  `v0.6.3`, three component checkouts bootstrapped at `v0.6.3`, CLI
  `vidra_v0.6.3_linux_amd64` checksum-verified.
- `vidra setup --non-interactive --yes --domain rec03.video.test --instance-name
  "REC-03 drill" --registration closed --tls-mode internal --storage local
  --scan=false --release-tag v0.6.3 --template env/production.env.example`, then
  `vidra setup --check` OK.
- `deploy/provision.sh --yes`: `vidra` user (uid 1001, `docker` group),
  `/opt/vidra` chowned, Docker log cap, unattended upgrades, nightly backup
  timer. It warned that sshd still permits root login (expected on a lab box).
- **First `deploy.sh` was refused by its own preflight** (exit 1, 05:07:37):
  `--scan=false` had removed the `scan` profile but `vidra setup` still wrote
  `CLAMAV_ADDR=clamav:3310` with `MALWARE_SCAN_MODE=fail-closed`, and deploy.sh
  named the consequence ("the api would come up healthy and then refuse every
  upload"). Applied its third option — `MALWARE_SCAN_MODE=disabled`,
  `CLAMAV_ADDR` unset, which is beta's posture — and re-ran: **exit 0 at
  05:10:05**, all six probes OK, `v0.6.3` images, ledgers 144 / 18. See
  finding F2.
- Data: a 12 s 1280×720 `testsrc2` + 440 Hz fixture rendered by the v0.6.3 api
  image's own ffmpeg (sha256 `8ff2dfde…936a`); owner claimed by redeeming the
  boot-logged token at `POST /api/v1/setup/claim-owner` (201); channel `drill`
  (201); a public video created and uploaded through `POST /videos/{id}/file`
  (201); **published within 5 s** with renditions 720/480/360 (3
  `video_renditions`, 7 `video_files` rows).
- **Fingerprint** (recomputed after every later step): original
  `8ff2dfde3770360f`, HLS master `0b8854fa8721cd9e`, first CMAF segment
  `chunk-0-00001.m4s` `bddbd11c7fc3638a`, state `published`; counts users=1
  channels=1 videos=1.

### 2. Backup at schema 144 and inject the failure — `backup.log`, `inject.log`

- `deploy/backup.sh` (v0.6.3): `backups/vidra-20260913T051158Z.dump.gz` (60 KB)
  + config archive; local copy only (no off-site target on this lab box).
- Injection: `ALTER TABLE storage_migrations ADD COLUMN paused_reason TEXT NOT
  NULL DEFAULT ''` — migration 0145's `ADD COLUMN paused_reason` carries no `IF
  NOT EXISTS`, so the real, unmodified v0.6.4 migrator must fail on it. Ledger
  still 144 clean.

### 3. Upgrade attempt with the injected failure — `upgrade-fail.log`

- Tree moved to `origin/main` (`67840ab`, `v0.6.4-6-g67840ab`) to obtain
  `deploy/pin-release.sh`, then **`pin-release.sh v0.6.4` (as `vidra`) failed**:
  it checked out `v0.6.4`, then `bash: /opt/vidra/deploy/backup-env.sh: No such
  file or directory` — `ERROR: env snapshot failed — the tree is at v0.6.4, the
  env file is untouched`. Tree moved, pins not (still `v0.6.3`). Finding F1;
  fixed by meta#192 (snapshot before checkout), not merged when this ran.
- Fallback, the v0.6.4-era runbook: tree at `v0.6.4`, the three pins rewritten
  to `v0.6.4` as `vidra` (temp file + rename).
- **`deploy.sh` (as `vidra`)**: preflight OK, nested checkouts synced to
  `v0.6.4`, pre-deploy dump `pre-deploy-2026-09-13T051218.dump.gz`, images
  pulled, then migration 0145 failed with `column "paused_reason" of relation
  "storage_migrations" already exists` and deploy.sh stopped at 3/6: **`CORE
  MIGRATION FAILED (exit 1). The stack has NOT been restarted; the previous
  release is still serving.`** (exit 1, 05:12:30). Verified after the abort:
  `v0.6.3` containers serving, all probes 200, fingerprint identical, ledger
  **core 145 dirty**, search 18 clean.

### 4. Recover per the runbook — `recover.log`

Exactly `deploy/README.md` "Migration failed mid-deploy":
`./deploy/compose.sh run --rm migrate migrate version` → `version=145
dirty=true`; the partial effect undone by hand (`DROP COLUMN paused_reason`);
`migrate force 144 --yes-i-know` → `before: version=145 dirty=true` / `after:
version=144 dirty=false`; `deploy.sh` again → `145/u` and `146/u` applied,
`core schema OK (version 146)`, search 18, `up -d`, probes OK, **exit 0 at
05:13:16**. `v0.6.4` images serving; fingerprint and counts identical to step 1.

### 5. Backup at schema 146 with a post-backup marker — `backup2.log`

`backup.sh` (v0.6.4) → `backups/vidra-20260913T051341Z.dump.gz`; then the
video's title was renamed through the API (`PATCH /videos/{id}`, 200) so a later
restore of this dump would visibly keep the rename and a restore of the 144 dump
would visibly lose it.

### 6. App-only rollback — `rollback.log`

`./deploy/rollback.sh v0.6.3` (as `vidra`, tree still at `v0.6.4`): env snapshot
`backups/env-history/production.env.20260913T051346Z`, pins set to `v0.6.3`,
checkouts synced, pull, restart, api and frontend probes OK, **exit 0 at
05:14:01**. After it: `v0.6.3` images on **schema 146, ledger clean**, all
probes 200, fingerprint identical, the marker rename present (no data touched).
The v0.6.3 migrator's own "schema version 146 is newer than this binary's
newest migration 144; nothing to apply" line was not captured: it goes to the
one-shot container's log, which the later re-pin recreated. The ledger staying
146/clean with a healthy v0.6.3 api is the observable consequence.

### 7. Restore across an incompatible schema — refused — `restore-refuse.log`

`./deploy/restore.sh --yes backups/vidra-20260913T051341Z.dump.gz` (the 146
dump) under the `v0.6.3` pins: after decompressing and staging the archive, the
schema preflight refused **before the drop**: `ERROR: core: the dump is at 146;
pinned VIDRA_CORE_TAG=v0.6.3 carries up to 144. The migrator runs AFTER the drop
and the reload, and it cannot walk a ledger that is ahead of it … this is
exactly A38 run 13. Set VIDRA_CORE_TAG … or pass --allow-schema-mismatch`.
Exit 1 at 05:14:13; counts byte-identical before/after; stack still serving.

### 8. Re-pin and the supported restore — `repin.log`, `restore-ok.log`

- Pins back to `v0.6.4`, `deploy.sh` → `schema already up to date` (146), exit 0
  at 05:14:53.
- `./deploy/restore.sh --yes backups/vidra-20260913T051158Z.dump.gz` (the 144
  dump) under `v0.6.4`: preflight `dump schema 144, pinned VIDRA_CORE_TAG=v0.6.4
  carries up to 146 — the migrator step below will apply the difference. This is
  the documented forward path`; api/search/frontend stopped; database dropped
  and recreated; restored with 4 jobs; **migrations applied 144 → 146**; search
  18; media consistency `checked 8 referenced object(s) … present: 8, MISSING:
  0`; services started; `/readyz` 200; **exit 0 at 05:15:23**. The marker rename
  is gone (title back to the v0.6.3 value), fingerprint identical, ledger 146
  clean.

### 9. OPS-01 subset: API/worker split — `split.log`

`EXTRA_COMPOSE_PROFILES=worker` + `API_ROLE=api` in the env, `deploy.sh` → exit
0 at 05:15:51; `vidra-worker-1` up with `VIDRA_ROLE=worker` beside the api with
`VIDRA_ROLE=api`. A second upload published within 5 s; the worker logged
`transcode worker started` and `transcode drain completed jobs count=1`; every
`job_runs` row for that video carries `worker_id 466f0964f713:1`, which is the
worker container's ID; the api container logged zero completed transcodes after
the split. Not run on this host: the settings-edit-reaches-both-processes check,
kill-mid-transcode recovery, redis/PostgreSQL outage, leader failover, a second
worker or a second host — so OPS-01 keeps its UNVERIFIED disposition.

## Findings

- **F1 — `pin-release.sh` cannot pin a release that predates its own helper
  (meta#192).** The snapshot helper (`deploy/backup-env.sh` +
  `deploy/checkout-hygiene.py`) landed after v0.6.4, and the script took its
  snapshot after the checkout, so pinning v0.6.3/v0.6.4 from a newer tree died
  with the tree moved and the pins not — the REL-01 skew the script exists to
  prevent. Reproduced live here (step 3). meta#192 moves the snapshot before the
  checkout with a RED/GREEN test; until it is released, the v0.6.4-era manual
  steps work and are what this drill used.
- **F2 — `vidra setup --scan=false` leaves a fail-closed scanner address behind.**
  The env it writes keeps `CLAMAV_ADDR=clamav:3310` and
  `MALWARE_SCAN_MODE=fail-closed` while removing the profile that would start
  clamav. `deploy.sh`'s preflight catches the contradiction (it did, with the
  right explanation), but the setup should not write it. Low; not fixed here.
- **Observation** — `rollback.sh`'s frontend wait printed one `curl: (56) Recv
  failure: Connection reset by peer` line before `frontend OK` (the loop
  retried, as designed). Cosmetic noise in an otherwise clean rollback log.

## Not covered

- The bundle (no-git) upgrade path — unpack the new bundle, bump pins, `vidra
  deploy` — was not exercised; this drill is the git path beta uses.
- S3 storage and the media half of a restore across stores (local disk only).
- A search-ledger rollback: search stayed at 18 in both releases.
- ACME/public DNS (internal CA), a second host, real browser decode (segments
  were fetched and hashed through the api proxy, not decoded in a browser).
- The sweep of deploy-time timing: this was a one-video catalogue, so no
  migration ran against populated tables.

## Acceptance mapping

| Row | Requirement clause | Where it was shown |
|---|---|---|
| REC-03 | upgrade the previous compatible release with data | steps 1–4: v0.6.3 + data → v0.6.4, fingerprint identical |
| REC-03 | injected migration failure aborts before restart, previous release keeps serving | step 3 |
| REC-03 | supported app-only rollback | step 6 |
| REC-03 | incompatible schema uses tested backup restoration | steps 7 (refused ahead-of-binary dump) and 8 (forward restore + migrate) |
| REC-03 | no blind `force` / automatic down migrations | `migrate force` was operator-invoked with `--yes-i-know` after the manual repair (step 4); no down migration ran anywhere |
| OPS-01 | API-only + workers; transcode on the worker | step 9 (one worker; the rest of the row not run) |
