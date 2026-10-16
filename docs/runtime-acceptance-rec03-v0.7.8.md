# REC-03 published-image acceptance: v0.7.7 → v0.7.8

Date: 2026-10-16. **Verdict: PASS for the synthetic REC-03 subset below.**
No production deployment occurred. This is an actual disposable GitHub-hosted
Ubuntu 24.04 drill using published images and CLI/bundle assets.

Immutable record: `da049b6e07f59d2e5e51d7152ade4857f3d89bf6`. Latest tool:
`07afa5a4d9c9ab5d137a1c7875d3a1e3a999c238`. Component digests and source
commits are in [the release record](../releases/v0.7.8.json).

## Actual attempts

| Run | Tool | Result | Last accepted checks | Failure |
| --- | --- | --- | --- | --- |
| [38933507608](https://github.com/yegamble/vidra/actions/runs/38933507608) | `fabaac46` | FAIL | 0 | `install`: missing running image services |
| [38937708685](https://github.com/yegamble/vidra/actions/runs/38937708685) | `94bed8fa` | FAIL | 5 | `upgrade-fail`: migration conflict not observed |
| [38940381561](https://github.com/yegamble/vidra/actions/runs/38940381561) | `8950662a` | FAIL | 12 | `split`: split worker not proven |
| [38944885813](https://github.com/yegamble/vidra/actions/runs/38944885813) | `07afa5a4` | PASS | All 13 operational phases and report | None |

The fourth run accepted all the following checks using published component bytes.
There are thirteen operational phases plus the final report phase.

| Phase | Verdict | Evidence |
| --- | --- | --- |
| `install` | PASS | core=151:false search=18:false |
| `data` | PASS | core=151:false search=18:false; media fingerprints match |
| `fp` | PASS | core=151:false search=18:false; media fingerprints match |
| `backup` | PASS | command/data assertions |
| `inject` | PASS | core=151:false search=18:false |
| `upgrade-fail` | PASS | core=152:true search=18:false; media fingerprints match |
| `recover` | PASS | core=182:false search=18:false; media fingerprints match |
| `backup2` | PASS | command/data assertions |
| `rollback` | PASS | core=182:false search=18:false; media fingerprints match |
| `restore-refuse` | PASS | core=182:false search=18:false |
| `repin` | PASS | core=182:false search=18:false |
| `restore-ok` | PASS | core=182:false search=18:false; media fingerprints match |
| `split` | PASS | Fresh second video published as CMAF; persisted jobs, runs, events and process heartbeats attribute execution to the current worker, with no current API executor jobs. |
| `report` | PASS | All preceding phase assertions accepted. |

The accepted migration-failure phase used the real unchanged v0.7.8 migrator,
observed the injected duplicate column and dirty schema 152, and retained the
old running images. Recovery forced the recorded last clean version 151, then
migrated to 182. App-only rollback preserved schema 182; an ahead-of-binary dump
was refused without data changes. Forward restore removed the post-backup
marker and preserved the original media fingerprints. Each accepted image phase
also checked actual running image digests, architecture and source revisions.

The third attempt's generic FFmpeg log check was replaced by persisted execution
attribution. The fourth run bound fresh video/job identities and time boundaries
to the digest-verified API and worker containers, their live process heartbeats,
successful worker runs and job events. API startup capability logs and inline
thumbnail helpers do not count as executor jobs. This does not claim that no
FFmpeg process can run in the API container.

The successful source job and overall workflow both concluded success. Its
original allowlisted verdict SHA-256 is
`4b5aaef8099825c802d8fd6ca0c1cd7aca5cf30a1341ade28d9be0b19ae1c1c3`.
Independent verification checked the exact run/attempt/tool/record context,
actual job results, all required fields and the reconstructed original hash.

## Evidence boundary

The [sanitized attempt record](evidence/release-v0.7.8-verification/runtime-attempts.json)
retains exact run/attempt/tool/record context, real job conclusions and the
SHA-256 of each original allowlisted verdict. Neutral informational Check Runs
are evidence transport; failed source jobs remain failed. Raw logs, credentials,
API tokens and backup contents are not committed.

This tests synthetic local-storage media, with scanning disabled. It does not
qualify replacement-host sealed-secret recovery, B2/S3 storage, off-site retrieval, real PeerTube migration fidelity,
browser playback, human installation timing or production traffic. Overall
readiness remains [NO-GO](release-readiness.md).
