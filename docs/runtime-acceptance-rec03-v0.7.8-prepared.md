# REC03 v0.7.7 → v0.7.8 — prepared, not executed

After publishing all candidate images and core bundle assets, dispatch
`rec03.yml` with `record_commit` set to the immutable **meta record PR commit**
containing both release records. The workflow itself must already be on main.
The record PR stays unmerged until the resulting drill evidence is reviewed.

The disposable Ubuntu 24.04 runner permits existing Docker and runs all thirteen
phases plus report. Migration0152 injects `remote_videos.is_sensitive`: clean151
→ dirty152 → force151 → clean182; search stays18. Records/installer are frozen
at SHAs and image index digests checked. Failure facts, wrong ledgers/images,
failed probes, changed media, unproven refusal or missing worker fail the run.

Only `rec03-v0.7.8-verdict/summary.json` is uploaded: fixed labels, source SHAs,
ledgers and booleans. Raw logs, credentials, backups and config stay root-private;
never expose them to diagnose failures. Fix the driver and run again instead.

This proves the REC03 upgrade/rollback and worker-split subset only. It does
not prove replacement-host recovery, sealed-secret decryption, offsite storage,
browser decoding, production data timing, or the three-person stopwatch.
Write the actual result and workflow URL in a separate acceptance record after
execution; this page contains no runtime evidence.
