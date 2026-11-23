# Manage backups in a browser

From the Vidra install directory on the server, run the console as the installation owner. Use the same restic repository, credentials and `ENV_FILE` as the snapshot command. If the encrypted repository still needs to be initialized, follow the [install snapshot guide](SNAPSHOTS.md).

```sh
vidra backups web
```

If the deployment tree contains the console and the installed CLI predates `vidra backups`, run `python3 deploy/snapshot_ui.py` from the same directory. For a terminal listing of backup dates and versions, use `vidra backups list`.

The console prints a private browser link and an SSH tunnel command. On your computer, start the tunnel, substituting your SSH account and host.

```sh
ssh -N -L 8384:127.0.0.1:8384 USER@HOST
```

Open the printed link in your local browser. The console listens on the server’s loopback interface and the browser keeps its credential in the current tab. To choose a different port, pass `--port` and use the printed tunnel command.

## Create or recover a snapshot

- Choose **Create snapshot** to capture the running installation. Services pause during capture. The activity panel shows the current step and elapsed time.
- Filter history by release, date or trigger. Select a backup to inspect its storage and component versions. Older database archives remain visible with their scope and available version information.
- Choose **Review rollback** on a full install snapshot. For S3 media, supply a separate provisioned empty bucket. Leave **Save current data first** checked to retain newer uploads, messages, settings and files in another recoverable snapshot.
- Preview the operation and type the displayed release and UTC date to apply it. Plan for downtime and enough local space to stage the restored installation and volumes. Account suspensions, video blocks and sessions also return to the selected date.

The recovery command survives closing the browser tab. If recovery stops, consult the [recovery and retention instructions](SNAPSHOTS.md) before retrying. Stop the console from its terminal when finished. The next launch generates a new private link.

Choose **Retire this snapshot** to remove an obsolete recovery point. Preview the retirement and enter the snapshot-specific confirmation. The operation forgets the archive parts that belong to that snapshot. Run `restic prune` during your normal repository maintenance window to reclaim unused storage.
