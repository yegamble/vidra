# REC-03 published-image acceptance: v0.7.7 → v0.7.8

Date: 2026-10-16. **Verdict: INCOMPLETE; release acceptance is not established.**
No production deployment occurred. This is an actual disposable GitHub-hosted
Ubuntu 24.04 drill using published images and CLI/bundle assets.

Immutable record: `da049b6e07f59d2e5e51d7152ade4857f3d89bf6`. Latest tool:
`8950662a4a26b196e04416e8ee532dd619a195f3`. Component digests and source
commits are in [the release record](../releases/v0.7.8.json).

## Actual attempts

| Run | Tool | Result | Last accepted checks | Failure |
| --- | --- | --- | --- | --- |
| [38933507608](https://github.com/yegamble/vidra/actions/runs/38933507608) | `fabaac46` | FAIL | 0 | `install`: missing running image services |
| [38937708685](https://github.com/yegamble/vidra/actions/runs/38937708685) | `94bed8fa` | FAIL | 5 | `upgrade-fail`: migration conflict not observed |
| [38940381561](https://github.com/yegamble/vidra/actions/runs/38940381561) | `8950662a` | FAIL | 12 | `split`: split worker not proven |

The newest run accepted these facts before rejecting the split-worker proof.
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
| `split` | NOT ACCEPTED | Second video published and worker was running, but split execution attribution failed. |
| `report` | NOT RUN | No accepted phase verdict. |

The accepted migration-failure phase used the real unchanged v0.7.8 migrator,
observed the injected duplicate column and dirty schema 152, and retained the
old running images. Recovery forced the recorded last clean version 151, then
migrated to 182. App-only rollback preserved schema 182; an ahead-of-binary dump
was refused without data changes. Forward restore removed the post-backup
marker and preserved the original media fingerprints. Each accepted image phase
also checked actual running image digests, architecture and source revisions.

The split check currently counts generic FFmpeg mentions in API logs. That is
not reliable execution attribution because API startup also reports FFmpeg
capabilities. A stronger worker-job proof is under review; this report does not
treat the existing rejected phase as a pass.

## Evidence boundary

The [sanitized attempt record](evidence/release-v0.7.8-verification/runtime-attempts.json)
retains exact run/attempt/tool/record context, real job conclusions and the
SHA-256 of each original allowlisted verdict. Neutral informational Check Runs
are evidence transport; failed source jobs remain failed. Raw logs, credentials,
API tokens and backup contents are not committed.

This tests synthetic local-storage media, with scanning disabled. It does not
qualify B2/S3 storage, off-site retrieval, real PeerTube migration fidelity,
browser playback, human installation timing or production traffic. Overall
readiness remains [NO-GO](release-readiness.md).
