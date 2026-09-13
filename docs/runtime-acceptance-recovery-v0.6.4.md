# v0.6.4 recovery drill: worker crash, outages, backup, replacement-host restore — 2026-09-13

**NO-GO for the unchanged full release scope.** The published v0.6.4 images were
run unmodified. A real crash, datastore outages, a shipped backup, a failed
backup, a simulated host loss and a restore onto a **rebuilt blank AMD64 host**
all ran to their measured results. No workflow row is promoted to PASS: REC-01
still needs offsite retrieval (B3), REC-02 approved recovery objectives (B4),
and REC-03 was not executed. Counts move from **2 PASS / 45 UNVERIFIED / 12
BLOCKED** to **2 / 46 / 11** only because REC-03's missing destination now
exists. Rows and reasons: [disposition delta](evidence/release-v0.6.4-verification/recovery-runtime/disposition-delta.json).

## Candidate, hosts and tools

- **Candidate.** The [immutable manifest](evidence/release-v0.6.4-verification/manifest.json)
  is unchanged. Both hosts ran core `ed55a6d`, user `e584069` and search `1f8b854`,
  verified by digest, platform and revision label before and after every stage.
- **Source.** `159.203.118.182` (droplet 599531580) is the populated B2/migration
  host from #186/#187. It was not wiped, and its evidence directories were not
  touched. Media lives in the dedicated test bucket `vidra-acceptance-v064-20260911-media`.
- **Replacement.** `159.65.249.255` (droplet 599514574), rebuilt blank by the
  operator after its native-runtime evidence, dump, config and media volume were
  preserved privately (`env/acceptance-hosts-v064-20260913/`, hashes verified).
  It passed the runtime milestone's blank-host guard: Ubuntu 24.04.4 x86_64, no
  `/opt/vidra`, CLI, Docker or listeners beyond sshd/resolved.
- **Tools.** [`tests/recovery_release_acceptance.py`](../tests/recovery_release_acceptance.py)
  (host) and [`tests/recovery-release-acceptance.mjs`](../tests/recovery-release-acceptance.mjs)
  (Chromium 153.0.8010.12) are a stage on the existing harness: its Recorder,
  runtime snapshot and ledger checks. Test-only Node and Chromium were installed
  on the replacement host **after** the product install and restore. Every tool
  hash and mid-drill revision is in `TOOLS.SHA256`/`PROVENANCE` beside each host's
  evidence; stages record the hash they ran with.
- **Limits.** Rate limits and fail-closed ClamAV stayed on. The inline worker
  topology (the release default) was used. This is desktop Chromium evidence,
  not Safari, iOS or human usability proof.

## Executed evidence

| Stage (UTC) | Result | Evidence |
|---|---|---|
| Baseline 03:20 | Images, ledgers 146/18, catalogue fingerprints | `source/py-000-baseline` |
| Worker crash 03:22–03:56 | Browser upload of a 180 s 720p clip (made by the released core image's ffmpeg). `SIGKILL` of the api under a second after its transcode job was claimed (exit 137); api ready 9.6 s later. The orphaned lease lapsed 03:52:39, the sweep reclaimed 03:52:50 (attempts 0→1), job `done` 03:55:58. The recovered 480p rendition advances 0→3.83 s with frames and audio increasing. **No intervention; bounded by the fixed 30-minute lease.** | `source/upload-kill`, `source/recovered-playback` |
| Search outage with a write 03:56–03:57 | Public search stayed 200 through the local fallback. The title edit's `video.upsert` was pending with attempts 1. The index caught up 21 s after restart, and the UI query was served by vidra-search (2xx counter 0→1). | `source/search-catchup` |
| PostgreSQL outage 03:57 | `/readyz`, list and search returned 503 `database_unavailable`; ready 5.97 s after start. Same api container; catalogue unchanged. | `source/py-fault-postgres` |
| Redis outage 03:58 | `/readyz` `degraded`, reads served; ready 6.07 s after start. Same container; unchanged. | `source/py-fault-redis` |
| Search outage 03:59 | Reads served; ready 7.48 s after start. Same container; unchanged. `/readyz` still said `ok` 10 s in (observation). | `source/py-fault-search` |
| Sealed-secret fixture 03:59 | Owner TOTP enrolled and verified (10 recovery codes); a real password + TOTP browser sign-in passed **before** the backup. The secret stays private on the hosts. | `source/mfa-enroll` |
| Backup 04:00:13–04:00:37 | Shipped `backup.sh`: the dump lists the `search` schema, `users`, `user_mfa`, both ledgers and `search.documents`. The config archive holds exactly `env/production.env` + `deploy/Caddyfile.local`, byte-equal to the live files, mode 0600. `last_success` names the dump. Fingerprints were identical before and after, so the data point is exact. | `source/py-backup` |
| Failed backup | Attempt 1 **FAIL (harness)**: it demanded a byte-identical `backups/` and rejected the private `.part` that `tests/backup_test.py` requires. Attempt 2 checks the real contract: exit 1, no dump or config published, `last_success` unchanged, only the private `.part` left. PASS. | `source/py-failed-backup`, `-v2` |
| Post-backup write 04:02:00 | Owner display name set to a marker a correct restore must lose. | `source/rpo-marker` |
| Host loss 04:02:11 | Source stack stopped; all 8 volumes kept. | `source/py-source-loss` |
| Replacement restore 04:02:53–04:05:41 | Released installer → config archive **first** → digest pin (the same six-image adaptation every v0.6.4 run used) → postgres → `restore.sh --yes` → `deploy.sh`. `verify-blobs` MISSING 0. Ledgers 146/18. All 15 catalogue and MFA table fingerprints plus `search.documents` equal the backup data point. | `replacement/py-restore` |
| Browser verification 04:06–04:13 | Password sign-in; a wrong TOTP code gives **401** and the right one **200**, proving `MFA_KEY_KEK` decrypts the restored secret (an undecryptable secret also answers 401, so the refusal alone proves nothing). The post-backup marker is absent. The legacy B2 upload and the recovered drill video decode and advance. The drill video is found through the UI with vidra-search's counter 0→1. | `replacement/verify-restore` |
| New write after restore | Attempt 1's last phase got **429** on `POST /api/v1/channels` and is retained. The rerun honoured Retry-After: upload published, transcoded on the first attempt, decodes. A supplementary `SELECT` shows both `video.upsert` events delivered and the document indexed. | `replacement/verify-restore-write`, `post-restore-index-readback.json` |

### Measurements (no approved objective, so none is asserted)

| Measure | Value |
|---|---|
| Simulated host loss → replacement ready (includes Docker + product install) | **209.9 s** |
| Installer start → ready | 167.8 s |
| `restore.sh` alone | 67.7 s |
| Data lost | Writes after the 04:00:37 backup (the 04:02:00 marker). In production this equals the backup cadence; the shipped timer is nightly. |
| Crash → orphaned job recovered | 33 min 18 s, dominated by the fixed 30-minute lease; there is no operator knob |

## Boundaries and what remains

- **Not certified here.**
  - Offsite retrieval: the backup moved host to host through the operator workstation (B3).
  - Local-storage media snapshots.
  - Decryption of federation/ATProto/DRM/OAuth secrets: none are configured on this instance.
  - A forced index rebuild.
  - The API/worker split, settings propagation and leader failover (OPS-01).
  - Upgrade from v0.6.3, migration-failure refusal, app rollback and incompatible-schema restore (REC-03/A38).
- **Observations, not claimed defects.**
  - Rendition `job_runs` completed after the crash still name the killed container's `worker_id`.
  - `/readyz` did not reflect a 10-second search outage.
  - Recovery of a crashed job waits the whole 30-minute lease.
- **Resources.**
  - The source stack is **stopped**; the replacement stack is **running**. Both have `MEDIA_GC_ENABLED=true` against one bucket, so never run both.
  - Restart the source only after stopping the replacement: `cd /opt/vidra && COMPOSE_PROJECT_NAME=vidra-release-acceptance bash deploy/compose.sh stop`, then `… start` on the source.
  - Raw logs, the backup handoff and test credentials stay private under `/root/vidra-v064-recovery-20260913` on each host. The bucket key expires 2026-09-18.
- **Export.** Reviewed exports were written by [`tests/recovery_release_export.py`](../tests/recovery_release_export.py). It hashes command output and health-probe output instead of exporting them, and refuses on any host secret: env secrets, bucket key, owner password, TOTP secret, recovery codes. Source export 22 files, replacement 7; per-file hashes are in each `artifact-hashes.json`.

Next executable milestone: REC-03/A38 on a disposable host — install v0.6.3, create
data, upgrade to v0.6.4 through `deploy.sh`, inject a migration failure, roll the
app back, and restore across an incompatible schema. That needs no new input
beyond another operator rebuild. REC-01/REC-02 wait on an offsite backup
destination and approved RPO/RTO.
