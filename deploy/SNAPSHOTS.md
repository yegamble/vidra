# Install snapshots

A full install snapshot lets a single-host Vidra operator recover the database, media, configuration and running software together. It records both clean database migration ledgers and saves the exact Docker image IDs for the API, frontend, search and their dependencies. It also saves the installation tree, project-owned Docker volumes (including PostgreSQL), dedicated writable directories under `data/`, and every current object in the configured S3 bucket. Restic encrypts and deduplicates these backups. Use storage independent of the Vidra host and media bucket. When using an rclone or other indirect backend, verify that its destination is a different bucket from the live media.

The snapshot commands and this release’s backup, restore, pin, deploy and rollback scripts share one lock per installation. A competing operation exits before changing the install. Retry it when the active operation finishes. The operating system releases the lock when the command exits. Leave the lock file in place.

## Set up a recovery repository

Install Python 3.9+, Docker Compose, rsync and restic 0.18.1 or newer on the operator host. Use the installation owner with access to Docker. For S3, install boto3 and botocore with support for conditional multipart completion in that Python environment. boto3 1.44.9 was used in the S3 rehearsal.

Set the repository and password file in the shell that launches the tools. Keep an independent copy of the password. The following example assumes an independently mounted backup disk and an existing private password file. Run `restic init` once per new repository.

```sh
export RESTIC_REPOSITORY=/mnt/vidra-backup/install
export RESTIC_PASSWORD_FILE=/etc/vidra/restic.password
restic init
cd /opt/vidra
python3 deploy/snapshots.py create
python3 deploy/snapshots.py list
```

Use a maintenance window. Snapshot creation stops the active Compose services, including the public edge, while it saves the data. On S3 the first capture reads the entire bucket across the network, including pre-existing unreferenced objects. Allow for that downtime, storage and retrieval cost. Quiesce any independent S3 writers, host synchronizers and additional machines writing to the same installation. Avoid concurrent manual deploys, restores or direct Docker commands during a snapshot or recovery. Schedule full snapshots using the same environment with `python3 deploy/snapshots.py create --reason scheduled`. The existing online nightly database backup can continue on its own schedule outside this window.

## Schedule a full backup

Single-host Linux installs can enable the optional systemd timer. It runs Sundays at 03:00 in the host timezone. Select a maintenance window appropriate to the size of the installation before enabling it. Missed windows wait until the next scheduled time. Nothing enables this timer during a normal install.

Provide `RESTIC_REPOSITORY` and `RESTIC_PASSWORD_FILE` in the protected file `/etc/vidra/snapshots.env`. The `vidra` service user must be able to access its password file, installation and Docker engine. Adjust the service account, installation path or Python executable in a systemd override when they differ.

```sh
sudo install -m 0644 deploy/vidra-snapshot.service deploy/vidra-snapshot.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now vidra-snapshot.timer
systemctl list-timers vidra-snapshot.timer
```

Scheduled runs appear in the same backup history. View a failed run with `journalctl -u vidra-snapshot.service`. To change the time, use a timer override that clears `OnCalendar=` and then sets the new schedule.

## Select and restore a date

`list` shows UTC dates, versions and full snapshot IDs. It also lists local nightly and pre-deploy database dumps. A paired legacy configuration archive can supply the configured core tag. A dump without version evidence is marked `unknown`. Database-only entries use the existing `restore.sh` procedure.

```sh
python3 deploy/snapshots.py restore FULL_SNAPSHOT_ID
python3 deploy/snapshots.py restore FULL_SNAPSHOT_ID --apply
# For an S3 snapshot, substitute the name of a separately provisioned empty bucket
python3 deploy/snapshots.py restore FULL_SNAPSHOT_ID --apply --media-bucket NEW_BUCKET
```

The first command previews the change. Applying the snapshot verifies a staged copy of the installation and Docker archives before switching the live data. The preview shows the checkout and volume staging estimate. The restore checks space under `backups/` before staging and leaves a default 1 GiB reserve (adjustable with `VIDRA_RESTORE_RESERVE_BYTES`). Allow additional space in the Docker engine for loaded images and recovered volumes. S3 media streams directly into the destination bucket. Images reload by their saved IDs. The database and Redis start first. Vidra checks the recovered database against both recorded ledgers, then hashes media and checks its dependencies before the saved application services start.

**Preserve current data** is the default. Vidra stops writers and takes a second complete snapshot, labeled `before-restore`, before replacing anything live. Newer messages, videos and photos remain recoverable by selecting that second date. This preserves both timelines separately. The selected snapshot determines which messages, moderation decisions, sessions, and files the restarted site serves. Review account suspensions, takedowns and revoked sessions that happened after that date before reopening public access.

Choose `--discard-current` for explicit replacement without creating the second point. This option can recover a failed upgrade whose mixed-version services cannot form a consistent new snapshot. Confirm the pre-upgrade snapshot ID first. The former S3 bucket remains intact in both modes. The last recovery receipt in `backups/last-install-recovery.json` names the previous bucket and any volumes or writable data directories used only by the newer install. Review those resources before retiring them.

A failed recovery keeps its private staging data and journal under `backups/`. Repeating the same command resumes the switch. To abandon an interrupted switch, restore its recorded safety snapshot with `--apply --discard-current`. S3 recovery needs another fresh destination bucket for that switch. If a failure occurs while preparing a fresh S3 bucket, inspect that destination separately and use an empty bucket for the retry.

## Coverage and retention

- The automatic restore targets the same installation path, Compose project and hostname. Store the recovery password, operator instructions and the host's infrastructure settings independently for host-loss recovery. Other hosts can inspect and extract the encrypted archive with the restic CLI.
- External PostgreSQL/Redis, shared or externally mounted volumes and an active two-store migration need their own coordinated recovery policy. A managed IPFS control socket outside the checkout and a PeerTube importer in reference mode also require separate handling. Remote peers, public pins, external PDS accounts, CDN configuration and external source buckets can retain independent copies or references.
- For a new S3 bucket, provision the required IAM permissions, CORS, encryption, public-delivery policy and CDN wiring. The archived credentials need permission to read and upload objects, verify contents, inspect versions and handle multipart uploads. The restore checks for existing objects, versions and unfinished uploads and verifies each restored object's bytes. Keep the old bucket until playback and any stored external URLs have been checked.
- The encrypted repository contains secrets, private conversations, keys, deleted historical media and service images. Restrict access and establish retention for both manual and automatic safety snapshots. Each recovery point consists of several restic snapshots with the same `vidra-capture-…` group tag. Preview retirement with `python3 deploy/snapshots.py retire FULL_SNAPSHOT_ID`. Add `--apply` to forget the complete group, then run `restic prune` to reclaim unreferenced chunks. If retirement is interrupted, repeat the same command to finish removing the remaining parts. Independent generic keep-last policies can remove one part of a recovery point. Use `restic check --read-data` and rehearse a selected snapshot periodically on an isolated copy.
