# REC-03 / A38 on published v0.6.5 — upgrade from v0.6.4, dirty-ledger refusal, rollback, restore — 2026-09-13

**Verdict: REC-03 PASS on the published v0.6.4 → v0.6.5 images**, with the caveats
in "Not covered". **OPS-01 stays UNVERIFIED**; the passed subset (split topology
deploys, the worker transcodes) is recorded below.

This is the v0.6.5 run of the drill recorded for v0.6.3 → v0.6.4 in
[runtime-acceptance-rec03-v0.6.4.md](runtime-acceptance-rec03-v0.6.4.md), on a
host the operator rebuilt blank again. Two things differ because this pair ships
**no new migration** (core 146 → 146, search 18 → 18): the injected failure is a
**dirty ledger** rather than a column conflict, and the "restore refuses a dump
ahead of the pinned binary" case cannot exist, so it is recorded as not
applicable. Everything else is the same: git-path install, local storage (never
the shared bucket), the installer, `vidra setup` and `provision.sh` as root,
every `deploy.sh` / `rollback.sh` / `restore.sh` / `backup.sh` /
`pin-release.sh` invocation as the `vidra` user. Nothing here touched
production; beta stays on v0.6.4.

What this run exercises that the v0.6.4 run could not: **the exact upgrade
procedure beta will use** — a v0.6.4 tree carries no `pin-release.sh`, so the
README's one-time move (`git fetch --tags && git checkout --detach v0.6.5` as the
deploy user) followed by `./deploy/pin-release.sh v0.6.5` (the meta#192 fix:
snapshot before checkout) and `./deploy/deploy.sh` with its new release-mapping
preflight (meta#189).

Driver: [`tests/rec03-upgrade-rollback.sh`](../tests/rec03-upgrade-rollback.sh)
with `REC03_OLD=v0.6.4 REC03_NEW=v0.6.5 REC03_INJECT=dirty REC03_SAME_SCHEMA=1`
(the env overrides landed in this PR; the executed copy is sha256
`34af023958ac0ef7925a5aa7496e8d09c76ebdefb292aa10eaf329826e7e4ed0`, which
differs from the committed one only by shellcheck quoting and by calling the
scan-posture helper `tests/rec03-envfix.py` at `/root`). Evidence:
[`docs/evidence/release-v0.6.5-verification/rec03-runtime/`](evidence/release-v0.6.5-verification/rec03-runtime/)
— one log per phase, `facts/<phase>.json`, `split-worker-evidence.txt` (captured
by hand on the same host state after the run), `summary.json` (hand-authored
from those files; not machine output).

## Candidate

| Component | v0.6.4 (start) | v0.6.5 (candidate) |
|---|---|---|
| vidra-core | `ghcr.io/yegamble/vidra-core@sha256:f653962115c8f36857e237b9e0ec9c95d89fef5b1f23cdcea75c20d1582f42a0` | `…vidra-core@sha256:a6e08b93364924e40321a47d188ed08ddbc2b21aecd3f0dcc58f49bc1f2f3bb1` |
| vidra-user | `…vidra-user@sha256:443336d4945365337e9459c270d51c80d1f62f9923ba80efffd3130389f814a3` | `…vidra-user@sha256:08e920ba5d214a190c30796c9c7f877ad70a53ea2b1f2d10a5f47de679b03178` |
| vidra-search | `…vidra-search@sha256:afcdb8a4bba86adfc7c64c4ea8a5e6edd8411fbc97c3f1a5f31dfb999dafb2cc` | `…vidra-search@sha256:55196d278722d46c4454cc4f5f4d05b9e7cd35cc7712f2aeb6354e13f65ea0f8` |
| core schema / search schema | 146 / 18 | 146 / 18 |

The v0.6.5 digests are the index digests `releases/v0.6.5.json` records (the
host pulled by tag; `docker inspect` reports the index). Meta tree: `v0.6.4` tag
for the install, `v0.6.5` tag for the upgrade.

## Host

Droplet `599531580` (`vidra-beta-v064-b2-acceptance`, 159.203.118.182), rebuilt
by the operator (`doctl … rebuild`, action 3404848631, 14:51:07 → 14:51:36 UTC).
Blank on arrival (no Docker, no `/opt/vidra`); Ubuntu 24.04.4, x86_64, 8 vCPU.
Docker 29.8.0 + Compose 5.5.1 from the installer. `https://rec03.video.test`
through Caddy's internal CA. The acceptance firewall had to admit this
workstation's current egress address for the session (rule added by the
operator; value recorded privately).

## What ran, in order (UTC, 2026-09-13)

### 1. Install v0.6.4 and create data — `install.log`, `data.log`, `fp.log`

- Released installer `raw.githubusercontent.com/yegamble/vidra/v0.6.4/install.sh`
  (sha256 `6b7a6152…fc06` — byte-identical to the v0.6.3 installer) with
  `--git --ref v0.6.4 --yes`; `vidra setup --non-interactive … --tls-mode
  internal --storage local --scan=false --release-tag v0.6.4`; the scan-posture
  helper applied beta's posture (`MALWARE_SCAN_MODE=disabled`, `CLAMAV_ADDR`
  unset — finding F2 of the v0.6.4 record, still present on v0.6.4's `vidra
  setup`); `provision.sh --yes`; **`deploy.sh` exit 0 at 14:59:13**, health
  step passed (api `/readyz`, frontend, edge), v0.6.4 images, ledgers 146 / 18.
- Data: the same 12 s fixture (sha256 `8ff2dfde…936a`) rendered by the v0.6.4
  api image's ffmpeg; owner claimed via the boot token (201); channel `drill`
  (201); upload (201); state `published` within 5 s.
- **Timing note, recorded rather than hidden:** the first fingerprint runs
  (`facts/data.json` at 14:59:4x and the first `fp` at ~14:59:55) caught the
  video **before its transcode drained** (renditions empty, HLS master = the
  hash of an empty fetch); `job_runs` shows all seven transcode rows
  `succeeded` and the api logged `transcode drain completed jobs count=1` at
  14:59:58. The reference fingerprint was retaken at ~15:01 (`facts/fp.json`):
  original `8ff2dfde3770360f`, HLS master `72e2bc264737003b`, renditions
  720/480/360, first CMAF segment `chunk-0-00001.m4s` `84f5c71f3af6f316`.
  Because the first `backup.sh` (14:59:59) and the first injection had already
  run against the mid-transcode state, the ledger was cleared, **`backup.sh`
  was re-run at 15:01:02** (the dump every later step uses) and the dirty
  ledger re-injected. `facts/fp.json` therefore shows the ledger dirty: it was
  taken between the first injection and the clear.

### 2. Inject the failure — `inject.log`

`UPDATE schema_migrations SET dirty = true` at version 146: with no migration to
run, a dirty ledger is what the v0.6.5 migrator must refuse.

### 3. Upgrade attempt — `upgrade-fail.log`

- As `vidra`: `git fetch --tags --force origin && git checkout --detach v0.6.5`
  (the README's one-time move for a pre-v0.6.5 tree), then
  **`./deploy/pin-release.sh v0.6.5` → exit 0**: env snapshot taken FIRST
  (`~/.local/state/vidra/env-history/…`), checkout, three pins set. This is the
  meta#192 order, proven on the real procedure.
- **`deploy.sh` (v0.6.5's)**: the new release-mapping preflight printed the
  documented WARNING for a tree's own release (no `releases/v0.6.5.json` in a
  tree at tag v0.6.5 — the record landed on `main` afterwards) and continued;
  checkouts synced to v0.6.5; pre-deploy dump `pre-deploy-2026-09-13T150110`;
  images pulled; then the core migrator refused: `dbmigrate: apply migrations:
  Dirty database version 146. Fix and force version.` → **`CORE MIGRATION
  FAILED (exit 1). The stack has NOT been restarted; the previous release is
  still serving.`** (exit 1, 15:01:19). After the abort: v0.6.4 containers
  serving, all probes 200, fingerprint identical, ledger 146 dirty / 18 clean.

### 4. Recover per the runbook — `recover.log`

`./deploy/compose.sh run --rm migrate migrate version` → `version=146
dirty=true` (v0.6.5's message: `schema_migrations is dirty at version 146: a
migration failed halfway and the schema state is unknown`); nothing partial to
undo; `migrate force 146 --yes-i-know` → `before: version=146 dirty=true` /
`after: version=146 dirty=false`; `deploy.sh` again → `core schema OK (version
146)`, search 18, `up -d`, probes OK, **exit 0 at 15:02:13**. v0.6.5 images
serving; fingerprint and counts identical.

### 5. Backup at v0.6.5 with a marker — `backup2.log`

`backup.sh` (v0.6.5) → `vidra-20260913T150221Z.dump.gz`; then the video's title
renamed through the API (200) so the two later restores are distinguishable.

### 6. App-only rollback — `rollback.log`

`./deploy/rollback.sh v0.6.4`: the release-mapping check **accepted v0.6.4 as a
recorded release** (`is release v0.6.4 (releases/v0.6.4.json): core schema 146,
search schema 18`), env snapshot, pins to v0.6.4, checkouts synced, pull,
restart, probes OK, **exit 0 at 15:02:43**. v0.6.4 on schema 146, ledger clean,
fingerprint identical, marker rename present. The one `curl: (56)` line during
the frontend wait appeared on the run console again; as in the v0.6.4 run it
is not in the committed `rollback.log` (the probe loop's stderr bypasses the
phase's `tee`), so it stays a console observation.

### 7. Restore across an incompatible schema — not applicable

v0.6.4 and v0.6.5 carry the same schema, so no dump can be ahead of the pinned
binary; the refusal branch was exercised on the v0.6.3 → v0.6.4 pair
(`restore-refuse.log` records the skip).

### 8. Re-pin and the forward restore — `repin.log`, `restore-ok.log`

- Pins back to v0.6.5 (a plain rewrite; `pin-release.sh` is for tree moves),
  `deploy.sh` → 146 already up to date, exit 0 at 15:03:11.
- `./deploy/restore.sh --yes vidra-20260913T150102Z.dump.gz` (the pre-upgrade
  dump) under v0.6.5: preflight `dump schema 146 matches what
  VIDRA_CORE_TAG=v0.6.5 carries — nothing to apply` (and search 18); services
  stopped; database dropped and recreated; restored with 4 jobs; both migrators
  ran with nothing to apply; media consistency `checked 8 referenced object(s)
  … present: 8, MISSING: 0`; services started; `/readyz` 200; **exit 0 at
  15:03:38**. Marker rename gone (title back to the pre-upgrade value),
  fingerprint identical, ledger 146 clean.

### 9. OPS-01 subset: API/worker split — `split.log`, `split-worker-evidence.txt`

`EXTRA_COMPOSE_PROFILES=worker` + `API_ROLE=api`, `deploy.sh` → exit 0 at
15:04:06; `vidra-worker-1` (`VIDRA_ROLE=worker`) beside the api
(`VIDRA_ROLE=api`); a second upload published within 5 s; every `job_runs` row
for it carries `worker_id 132e5a6bf4c1:1`, the worker container's id; the
worker logged `transcode worker started` (15:04:00) and `transcode drain
completed jobs count=1` (15:04:26); the api logged zero completed transcodes.
Not run: settings-edit propagation, kill-mid-transcode recovery, redis /
PostgreSQL outage, leader failover, a second worker or host — OPS-01 keeps its
UNVERIFIED disposition.

## Findings

- **F1 closed.** `pin-release.sh v0.6.5` from a v0.6.4 tree worked (snapshot →
  checkout → pins). The v0.6.4 record's F1 (pinning a pre-helper target from a
  newer tree) was fixed in meta#192 and is not exercised by this direction.
- **F2 still open on v0.6.4's `vidra setup`** — `--scan=false` leaves
  `CLAMAV_ADDR` + `MALWARE_SCAN_MODE=fail-closed`; the driver applied the
  posture before the first deploy this time. Low.
- **Observation — the tree's-own-release WARNING is what a v0.6.5 upgrade
  prints today.** `releases/v0.6.5.json` exists on `main` (meta#196) but not in
  the v0.6.5 tag's tree, so `deploy.sh` at v0.6.5 verified tag strings only.
  Expected per meta#189; closes when a release record ships inside the
  artifact.
- **Observation — the driver's fingerprint must wait for the transcode drain**;
  this run's first fingerprint was a race, corrected by re-fingerprinting. The
  committed driver is unchanged in that respect (the `fp <label>` phase exists
  for exactly this); a `job_runs`-based wait is a follow-up.

## Not covered

The bundle (no-git) upgrade path; S3 storage; a search-ledger change; ACME /
public DNS; browser decode (segments fetched through the api proxy only);
populated-table migration timing; and — for this pair — the ahead-of-binary
restore refusal, which has no input.

## Acceptance mapping

| Row | Requirement clause | Where it was shown |
|---|---|---|
| REC-03 | upgrade the previous compatible release with data | steps 1–4: v0.6.4 + data → v0.6.5, fingerprint identical |
| REC-03 | injected migration failure aborts before restart, previous release keeps serving | step 3 (dirty ledger) |
| REC-03 | supported app-only rollback | step 6 |
| REC-03 | incompatible schema uses tested backup restoration | step 8 forward restore; the refusal case is not applicable for this pair (proven on v0.6.3 → v0.6.4) |
| REC-03 | no blind `force` / automatic down migrations | `migrate force 146` was operator-invoked with `--yes-i-know` after `migrate version` (step 4); no down migration ran |
| OPS-01 | API-only + workers; transcode on the worker | step 9 (one worker; the rest not run) |
