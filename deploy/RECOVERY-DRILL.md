# Rehearsing host-loss recovery

Use a separate machine to recover one UTC backup point using the credentials
available to the on-call operator if the application host is lost. Record the
newest recoverable write and elapsed time to playable service. Compare them with
the site's agreed recovery point and recovery time objectives.

## Before the drill

| Role | What to bring |
| --- | --- |
| Backup operator | The installed release and image pins, UTC backup stamp, database and configuration archive names, immutable storage version IDs if available, and trusted SHA-256 digests of the original archives. Retain the manifest privately outside the application host. |
| Recovery operator | An isolated recovery machine, read access to the backup and media recovery stores under independent credentials, and access to the decryption material for this generation. Confirm someone can obtain the credentials during an incident. |
| Service owner | The maximum tolerable data loss and downtime, the oldest media versions needed, and who can authorize a traffic switch or rollback. Record how to handle writes received after the chosen point. |

The nightly backup covers the bundled PostgreSQL database, including search,
and available installation configuration. Check the backup log for omitted
members. An external PostgreSQL deployment needs its provider's snapshot or
point-in-time recovery and a separately backed-up configuration. Capture
manually supplied TLS keys, custom proxy files, external service credentials,
remote infrastructure settings and independently managed media where applicable.
[Backup scope](README.md#backups--restore)

### Recovering the decryption material

| How the pair was uploaded | What the recovery operator needs |
| --- | --- |
| `BACKUP_AGE_RECIPIENTS` | The private identity matching a recipient used for **that backup**. Keep its public recipient on the sending host. Recover both `.age` files, decrypt them on the recovery machine, and verify the resulting gzip archives. |
| rclone `crypt` | The crypt password, the original `password2` salt if set, and the filename settings. Configure the underlying bucket or local ciphertext directory separately. Copy both names through the crypt remote to authenticate and decrypt them. |
| Both layers | Read both `.age` objects through the crypt remote, then decrypt each with the matching age identity. |
| Full install snapshot | The restic repository, its password and the credentials to read the backend. Use the snapshot's recovery procedure. [Install snapshots](SNAPSHOTS.md) |

Treat an export of rclone's obscured passwords as a decryption key. Keep only
the needed crypt settings in the recovery vault or encrypt them directly to a
verified operator recipient. Obtain the provider's read credentials separately.
Keep the private identity and the encrypted export under independent custody
from the application host. Record which generations each key covers and retain
older keys while those backups are required. Validate custody by decrypting a
selected backup on the second machine. [rclone crypt settings](https://rclone.org/crypt/)

## Verify the independent media copy

1. Freeze a source inventory for the selected point. Include original paths,
   object version identifiers, byte counts and available checksums. Record
   uploads and deletion or hide markers separately. Record later writes as a
   delta. A versioned listing can contain several entries with the same path.
2. Read the destination through the recovery account. Match historical uploads
   to their replicas using path, source version provenance, length and an
   available comparable checksum. Source and destination version IDs can differ.
   Count matched, missing and unverifiable files and bytes separately. For
   locked objects, inspect each required version's retention and retain-until
   date. A bucket default or a newly replicated test upload proves only part
   of this check. [Backblaze replication](https://www.backblaze.com/docs/cloud-storage-cloud-replication)
3. Retrieve an original that predates replication **by destination version**.
   Verify its bytes against the trusted source hash, place it at the original
   relative path in the recovery copy, and decode it. Recover its HLS master,
   variant playlists and referenced segments where applicable. A hide marker
   can make the current name return 404 while the retained version remains
   readable by ID. Preserve that visibility in the restored application.
   [Backblaze file versions](https://www.backblaze.com/docs/cloud-storage-file-versions) ·
   [S3 Object Lock](https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lock.html)

Keep recovery media private. Give the application or replication writer only
the permissions needed for its job. Reserve permanent version deletion and
retention overrides for a separate administrator according to site policy.
Align lifecycle expiry with the oldest retained database or rollback point
that still references those bytes.

## Restore and accept the selected point

1. **Isolate the replacement.** Use a separate Compose project and disposable
   database. Block public ingress and outbound delivery to real users, peers
   and production integrations. Disable media garbage collection
   (`MEDIA_GC_ENABLED=false`). Give any upload or playback test its own writable
   media copy. Configure these boundaries before starting services or workers.
2. **Retrieve the pair.** Fetch immutable versions where supported. On the
   isolated machine, decrypt both and check their SHA-256 against the trusted
   receipt for the same UTC stamp. A provider checksum verifies the downloaded
   object. The plaintext digest identifies the archive used for the restore.
   Use an owner-only directory on protected storage for any plaintext. Validate
   the configuration archive members before extracting them.
3. **Rebuild the isolated installation.** Install the pinned release without
   running the setup interview. Restore the configuration before the database
   to preserve the application encryption keys. Set the drill endpoints and
   media path before boot. Restore local media or configure the recovered
   object store before running the strict check. Follow the
   [replacement-host steps](README.md#disaster-recovery-rebuild-the-host-in-this-order).
4. **Run the strict verification.** On the disposable installation, as its
   service user, set `DUMP` to the verified database archive. The command
   replaces the configured bundled database and runs both migrators.

   ```bash
   RESTORE_MEDIA_TIMEOUT=36h ./deploy/restore.sh --yes --require-media-consistent "${DUMP:?set the verified scratch dump path}"
   ```

   Set the timeout for the size of the recovered store. The check runs
   `verify-blobs --hash --deep --json` and requires exit zero and
   `deep_verification_version=1`. Missing media, verification errors and an
   unsupported report leave the restored database in place with the application
   services stopped. Keep the report, identify the affected versions, and
   rerun after repair. An emergency restore using the default existence check
   can start services after a warning.
5. **Check service behavior.** Verify both migration ledgers are clean and
   compare application counts and visibility with the baseline. Check
   `/readyz` and inspect its dependency results. Open an existing public video,
   play and seek, sign in with a designated test account, and confirm signed-out
   requests for private media are denied. Exercise private upload, processing
   and playback on the isolated storage if those flows are in the site's
   acceptance criteria.
6. **Record the decision.** Save the tested stamp, pinned release, integrity
   counts, exception details, observed recovery point and duration, and who
   reviewed them. Keep filenames and logs containing user data in private
   evidence. Release temporary access and remove drill data after evidence
   collection. During an actual cutover, retain the current database, media,
   config and the pre-switch and pre-deploy dumps outside automatic pruning
   until the rollback period ends. Confirm new off-site backups succeed before
   retiring the prior install.

## Check the backup schedule and alerts

For the shipped systemd timer, inspect the next run and its last service result.
The timer starts at 03:15 host-local time with up to 15 minutes of randomized
delay. Set the external monitor's grace period to cover that delay and the
measured backup duration.

```bash
systemctl list-timers --all vidra-backup.timer
systemctl show vidra-backup.service --property=Result --property=ExecMainStatus
```

Configure the private `HEALTHCHECKS_URL` in the backup job's environment and
test a controlled failure on a rehearsal job, followed by a successful backup.
Verify that both notifications reach the designated inbox and that the external
monitor detects a missed schedule. Check the successful pair in the off-site
store. The local `backups/last_success` marker supplies backup age to
`vidra doctor`. The script treats ping delivery as best effort. Use the
provider's scheduled-backup monitor for a managed database.
