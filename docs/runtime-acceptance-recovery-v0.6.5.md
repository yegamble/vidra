# v0.6.5 recovery drill: worker crash, outages, backup, replacement-host restore — 2026-09-14

**Full release scope stays NO-GO; the recovery objective is met.** The published
v0.6.5 images were run unmodified through a real crash, datastore outages, a
shipped backup, a failed backup, a simulated source loss and a restore onto a
**rebuilt blank AMD64 host**. The owner approved the recovery objective **RPO 24h
/ RTO 4h** on 2026-09-14 (session-reported), and this drill meets it, so
**REC-02 moves BLOCKED → PASS**. REC-01 stays BLOCKED — its blocker relabels
**B4 → B3** because encrypted offsite / independent-provider retrieval was not
exercised. OPS-01 stays UNVERIFIED with an expanded measured subset. Counts move
from **3 PASS / 45 UNVERIFIED / 11 BLOCKED** to **4 / 45 / 10**. Rows and
reasons: [disposition](evidence/release-v0.6.5-verification/recovery-runtime/disposition.json)
(baseline `docs/evidence/release-v0.6.5-verification/migration-runtime/disposition.json`,
sha256 `4987c6851f134f9a2e43b8c7b8a8d72c92493e673dc8776c778802fc0dfd8a32`).

## Candidate, hosts and tools

- **Candidate.** The [immutable manifest](evidence/release-v0.6.5-verification/manifest.json)
  is unchanged. Both hosts ran core `d13d40e6`
  (`ghcr.io/yegamble/vidra-core@sha256:a6e08b93…3bb1`), user `fdef1cec`
  (`vidra-user@sha256:08e920ba…3178`) and search `b7a7f55b`
  (`vidra-search@sha256:55196d27…a0f8`), verified by digest, platform and
  revision label at each host-side snapshot (baseline, faults, backup, source
  loss, restore). Ledgers `146|f` / `18|f` throughout.
- **Source.** `159.203.118.182` (droplet 599531580) is the retained v0.6.5
  B2/migration host from meta#206/#207. It was not wiped and its evidence
  directories were not touched; the baseline stage under drill is
  `/root/vidra-v065-runtime`. Media lives in the dedicated acceptance bucket
  `vidra-acceptance-v065-20260914-media`. Session-reported.
- **Replacement.** `159.65.249.255` (droplet 599514574), rebuilt blank by the
  operator at **12:11:57 UTC** (Ubuntu 24.04.4 x86_64, 8 vCPU / 15 GiB /
  309 GB; verified no `/opt/vidra`, no docker, no CLI). Session-reported.
- **Tools.** [`tests/recovery_release_acceptance.py`](../tests/recovery_release_acceptance.py)
  (host, run with `--baseline /root/vidra-v065-runtime`) and
  [`tests/recovery-release-acceptance.mjs`](../tests/recovery-release-acceptance.mjs)
  (Chromium 153.0.8010.12, Node v26.8.1) are a stage on the existing release
  harness: its Recorder, runtime snapshot and ledger checks. The drill tools at
  `/root/vidra-v065-drill-tools` are the `tests/` files from meta `main`
  **ef1614f** (#202–#205), checksummed. Test-only Node and Chromium were
  installed on the replacement host **after** the product install and restore.
- **Limits.** Rate limits and fail-closed ClamAV stayed **on**. The **inline
  worker** topology (the release default) was used throughout. This is desktop
  Chromium evidence, not Safari, iOS or human-usability proof.

## Executed evidence

Every value below is read from the committed files under
`evidence/release-v0.6.5-verification/recovery-runtime/`.

| Stage (UTC) | Result | Evidence |
|---|---|---|
| Baseline 12:13:47–12:13:58 | Images by digest, ledgers `146\|f` / `18\|f`, catalogue fingerprints captured. | `source/py-000-baseline` |
| Worker crash 12:13:58–12:15:54 | Browser upload of a 180 s 720p clip (`testsrc2` made by the released core image's ffmpeg; fixture sha256 `8b3d271e…97af`). `SIGKILL` of the api at 12:15:44 → `exited`, exit 137, not OOM. The harness ran `compose up -d api`; `/readyz` answered 200 and the api was ready again 12:15:54. The transcode job was untouched by the operator: at restart it was `running`, attempts 0, created 12:15:38. | `source/upload-kill` |
| Recovered job + playback 12:15:54–12:48:20 | **No intervention.** The orphaned lease lapsed and the sweep reclaimed the job on the second worker (attempts 0→1); `done` 12:48:09. `recovery_wait_seconds` **1938** (≈32.3 min), bounded by the fixed 30-minute lease. The recovered 480p rendition advances 0→3.77 s (8→123 frames, audio 7840→66014 B). | `source/recovered-playback` |
| Search outage with a write 12:48:20–12:49:01 | Public search stayed 200 (`found: true`) through the local fallback while search was down; the title edit's `video.upsert` stayed pending, attempts 1. The index caught up 12:48:59 and the UI query was served by vidra-search (service requests 0→1). | `source/search-catchup` |
| PostgreSQL outage 12:49:21–12:49:37 | Recovered **without an api container restart** in **6.543 s** (`restart_count` 0→0); catalogue unchanged. | `source/py-fault-postgres` |
| Redis outage 12:50:02–12:50:20 | Recovered **without an api restart** in **7.157 s**; same container; unchanged. | `source/py-fault-redis` |
| Search outage 12:50:40–12:50:57 | Recovered **without an api restart** in **7.483 s**; same container; unchanged. | `source/py-fault-search` |
| Sealed-secret fixture 12:50:57–12:51:31 | Owner TOTP enrolled and verified (`enabled: true`, 10 recovery codes); a real password + TOTP browser sign-in passed **before** the backup. | `source/mfa-enroll` |
| Backup (dump 12:51:40; stage 12:51:31–12:51:50) | Shipped `backup.sh`: the dump data point lists 16 catalogue/MFA tables (incl. `user_mfa` 1, `mfa_recovery_codes` 10, `search.documents` 5) and both ledgers `146\|f` / `18\|f`; the config archive holds `env/production.env` + `deploy/Caddyfile.local` (per-member sha256 recorded). Marker `vidra-20260914T125140Z.dump.gz`; dump + config handoff hashes recorded (`9d08aaf1…`, `8db945e2…`). | `source/py-backup` |
| Failed backup 12:51:50–12:51:51 | The real contract: an injected missing-database dump exits **1**, publishes nothing, and leaves only a private `.part` (`vidra-20260914T125151Z.dump.gz.part`). | `source/py-failed-backup` |
| RPO marker — attempt 1 **(retained FAIL)** 12:51:51–12:51:53 | `write-after-backup` failed with a TOTP **401** ("the restored TOTP secret did not verify"): the harness `freshCode` generated a code for the **same 30-second TOTP step** the mfa-enroll sign-in had just consumed (cross-process replay). Harness-timing artifact, **not a v0.6.5 defect**. | `source/rpo-marker-fail-1-totp-replay` |
| RPO marker 12:54:04–12:54:07 | Re-run **passed immediately**: post-backup owner display-name marker (`RPO marker 3ad570c5`, written 12:54:07.143Z) that a correct restore must lose. | `source/rpo-marker` |
| Source loss 12:54:17–12:54:19 | The whole source stack stopped, **0 containers left** (`compose stop`; no volume removed). | `source/py-source-loss` |
| Replacement restore 12:56:28→12:59:21 | Released installer → config archive **first** → six application-digest pin (scripts unchanged) → postgres → `restore.sh --yes` → `deploy.sh`. `verify-blobs` **MISSING 0**. Ledgers `146\|f` / `18\|f`. Restored catalogue + ledgers **equal the backup data point exactly**. | `replacement/py-restore` |
| Browser verification 13:40:45–13:41:07 | **4 of 5 phases PASS:** restored password + sealed TOTP (wrong code **401**, right accepted — an undecryptable secret also answers 401, so acceptance proves `MFA_KEY_KEK` decrypts the restored secret); the post-backup marker is **absent**; the legacy-B2 upload (`cded6735…`) and the recovered drill video (`c053388e…`) decode and advance; the drill video is found through the UI with vidra-search (0→1). The 5th phase (`new-upload`) is a **retained FAIL** (below). | `replacement/verify-restore` |
| New write after restore **(retained FAIL → separate PASS)** 13:45:24–13:45:58 | verify-restore's `new-upload` phase hit the request limiter on the draft-upload POST and surfaced as a `uuid(undefined)` TypeError; rate limits were kept **on**. After a cooldown, the dedicated `verify-restore-write` action **PASSED**: new video `5a9e26c7-4d90-496a-9486-2c8c6e65dbc5` transcoded (job `done`, attempts 0) and decoded (0→3.85 s, 121 frames). | `replacement/verify-restore-write` |

### Measurements, judged against the approved objective

The owner approved **RPO 24h / RTO 4h** on 2026-09-14 (session-reported). All
values are from `replacement/py-restore` and the source stage files.

| Measure | Value | Against objective |
|---|---|---|
| Simulated source loss → replacement ready (across two host clocks; includes Docker + product install and a host-to-host transfer) | **304.653 s** (≈5.08 min) | **RTO 4h — met** |
| Installer start → ready | 173.664 s | — |
| `restore.sh` alone | 70.879 s | — |
| Data lost (RPO) | writes after the 12:51:40Z dump (the 12:54:07Z marker, confirmed absent after restore); in production this equals the backup cadence | **RPO 24h — met** |
| Crash → orphaned job recovered | **1938 s** (≈32.3 min), dominated by the fixed 30-minute lease; no operator knob | measurement |
| PostgreSQL / Redis / search outage recovered without an api restart | **6.543 / 7.157 / 7.483 s** | measurement |

## The two retained harness-artifact failures

Both are harness-timing artifacts, retained exactly as v0.6.4 retained its
equivalents; **neither is a v0.6.5 defect**, and each has a separate PASS.

1. **`source/rpo-marker-fail-1-totp-replay` (TOTP replay).** The first
   `write-after-backup` sign-in reused the 30-second TOTP step the mfa-enroll
   sign-in had just consumed, so the code was rejected 401. The immediate re-run
   (`source/rpo-marker`) passed. The restored TOTP secret is proven good by the
   replacement-host verification, where a wrong code is 401 and the right one is
   accepted.
2. **`replacement/verify-restore` new-upload (rate limit).** Under the many
   requests the restored-host verification makes in a few minutes, the
   draft-upload POST hit the request limiter, and the harness `uploadAndPublish`
   does not 429-retry the draft POST (only the channel POST), so an undefined
   response id surfaced as a `uuid(undefined)` TypeError. Rate limits were kept
   **on**. The dedicated `verify-restore-write` action passed after a cooldown.
   This mirrors v0.6.4, which also retained a rate-limited verify-restore and
   passed verify-restore-write separately.

**Operator/harness follow-up, not a product defect.** The blank replacement
host lacked `libatomic.so.1`; the recovery-drill browser provisioning had to
`apt-get install -y libatomic1` before Node ran (the runtime `execute` step
installs it, the recovery path did not). The restore itself was unaffected.

## What this proves and does not

**Proves, on the published v0.6.5 images:**
- A real replacement-host restore yields usable **accounts** (password + sealed
  TOTP), **media** (legacy and recovered video decode from the dedicated
  bucket) and **search** (index serves the UI), on an exact backup data-point
  match with 0 missing blobs, within the owner-approved RPO/RTO — **REC-02
  PASS**.
- Backup completeness (both schemas, both ledgers, `user_mfa` /
  `mfa_recovery_codes`, `search.documents`, byte-equal config archive) and the
  failed-backup nonzero contract — the REC-01 **backup-integrity subset**.
- Inline single-worker crash + orphaned-lease recovery with no operator job
  intervention, and PostgreSQL / Redis / search outage recovery without an api
  container restart — the OPS-01 **inline-topology subset**.

**Does not prove:**
- **Desktop Chromium only** — no WebKit, Safari, iOS or mobile viewport.
- **No offsite / independent-provider retrieval.** The backup moved host to
  host; the encrypted offsite mechanism (A36/A37, blocker **B3**) was not
  exercised, so **REC-01 stays BLOCKED (B3)**. The replacement host's own
  exporter recorded the acceptance bucket key as `declared-absent`.
- **Inline worker only.** No API/worker split, two-worker interruption,
  settings propagation or leader failover, so **OPS-01 stays UNVERIFIED**.
- **Single-worker crash only**; no forced index rebuild; no decryption of
  federation / ATProto / DRM / OAuth secrets (none configured on this instance).

## Disposition delta

- **REC-02** ("Restore on replacement host yields usable accounts/media/search"):
  BLOCKED [B4] → **PASS**. Owner-approved recovery objective met by a real
  replacement-host restore.
- **REC-01** ("Backup includes DB, settings/sealing keys and required media"):
  BLOCKED [B4] → BLOCKED [**B3**]. B4 resolved, but offsite / independent-provider
  retrieval was not exercised. Still BLOCKED; no count change.
- **OPS-01** ("API/worker split updates settings and recovers leased jobs"):
  UNVERIFIED, measured subset expanded; **not promoted** (two-worker
  interruption, settings propagation and leader failover remain).
- **B4** added to `resolved_blockers`; **B3** remains open for the offsite /
  independent-provider inputs. Nothing else moves. Counts **3/45/11 → 4/45/10**.

## Evidence integrity and export

The export was written by the drill exporter that records `secrets_loaded` and
refuses when a loaded secret appears in the export. Source export **22 files**,
replacement **8 files**; per-file sha256 are in each host's
`artifact-hashes.json` (kept byte-verbatim; each entry re-verified against the
copied bytes at commit time). One
[`committed-hashes.json`](evidence/release-v0.6.5-verification/recovery-runtime/committed-hashes.json)
is the independent sha256 index recomputed over **every committed file in the
`recovery-runtime` tree except itself** (31 entries: the 30 exported files plus
`disposition.json`).

Next executable: the owner inputs still open — the offsite backup
destination/credentials (B3), the browser/Safari/iOS matrix, and the remaining
OPS-01 clauses (API/worker split, two-worker interruption, settings
propagation, leader failover).
