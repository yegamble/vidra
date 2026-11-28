# Run a separate native S3 reference origin

This optional Compose project serves immutable S3 byte ranges for **one operator-selected Vidra video and generation**. An operator must also install an approval manifest. Each approved read checks the current native public eligibility view before and after storage I/O. Removing the manifest withdraws the next read. The service starts dormant with an empty scope and approval directory. Dormant operation requires zero storage credentials.

Use a Linux Docker host with the standard private Compose PostgreSQL service (`postgres`, database `vidra`), migration 194 or later, a verified database/configuration backup, and Python 3 on the host. The origin joins the database's existing network. Docker publishes its HTTP listener on loopback. Other containers on that private bridge can reach the listener and encounter the same approval checks. The project does not publish a database port, mount the Docker socket or start a Kubo node.

## Install and verify the dormant origin

Run these commands as root from `deploy/ipfs-reference` in the reviewed checkout or bundle. For another host, load the independently verified image archive and compare its image ID with the saved build record.

```sh
umask 077
app=/etc/vidra-native-reference
image=vidra-native-reference-origin:reviewed
useradd --system --user-group --no-create-home --shell /usr/sbin/nologin vidra-native-ref
install -d -m 0700 "$app"
install -d -m 0750 -o root -g vidra-native-ref "$app/config" "$app/approvals"
install -m 0600 runtime/native/compose.yml "$app/compose.yml"
install -m 0700 runtime/native/init-reader.py runtime/native/verify-dormant.py "$app/"
docker build -f runtime/native/Dockerfile -t "$image" .
docker image inspect --format '{{.Id}}' "$image" > "$app/image.id"
```

Confirm the application database container belongs to the intended project and determine its private Docker network name. Use that network in the environment file. These examples use the standard names. Create the empty scope once on a fresh installation.

```sh
docker inspect --format '{{.Config.Labels}} {{range $name, $net := .NetworkSettings.Networks}}{{$name}} {{end}}' vidra-postgres-1
test ! -e "$app/config/scope.json"
printf '{}\n' | install -m 0440 -o root -g vidra-native-ref /dev/stdin "$app/config/scope.json"
cat > "$app/compose.env" <<ENV
NATIVE_ORIGIN_IMAGE=$image
NATIVE_UID=$(id -u vidra-native-ref)
NATIVE_GID=$(id -g vidra-native-ref)
NATIVE_CONFIG_DIR=$app/config
NATIVE_APPROVAL_DIR=$app/approvals
NATIVE_DB_NETWORK=vidra_default
NATIVE_PORT=8786
ENV
python3 "$app/init-reader.py" --dir "$app/config" \
  --uid "$(id -u vidra-native-ref)" --gid "$(id -g vidra-native-ref)"
native() { docker compose --env-file "$app/compose.env" -f "$app/compose.yml" "$@"; }
native config -q
native up -d --no-build
python3 "$app/verify-dormant.py" --env-file "$app/compose.env" --image-id-file "$app/image.id"
```

The provisioning command stores a random reader password in a service-owned, mode-0400 `pgpass`, then creates the dedicated login and grants SELECT on the eligibility view. It checks for unexpected application privileges and refuses to adopt an existing role with another credential. Repeated runs verify the saved credential. PostgreSQL's usual `PUBLIC` temporary-table and built-in function privileges still apply. The command leaves application roles and cluster-wide grants alone.

The verifier checks the running image ID, loopback publishing, read-only mounts and restart policy. It queries the view as the reader, verifies a protected-table permission denial, checks that approvals and storage credentials are absent, and requires an unknown reference to return HTTP 404 with an empty body for both HEAD and GET. Keep this result separate from an approved playback test.

## Prepare and withdraw a single approval

1. Obtain approval to **prepare** one canonical native video UUID and HLS generation for review. The catalogue view excludes imported paths, blocked, sensitive or unpublished videos and ineligible owners. Read the currently eligible master using the installed reader and a psql variable.

   ```sh
   printf "%s\n" "SELECT master_key FROM public.ipfs_public_reference_videos WHERE video_id = :'video'::uuid;" | \
     native exec -T origin psql -XAtq --no-password -v ON_ERROR_STOP=1 -v "video=$video_uuid"
   ```

2. For Backblaze B2, create a new application key scoped to the **primary** bucket and exactly `streaming-playlists/<video-uuid>/r<generation>/`, including the trailing slash. Verify the returned bucket and prefix restrictions and that the only capability is `readFiles`. Other S3 implementations must restrict immutable GET and HEAD to that same generation. Install the key ID and secret into `config/b2.key-id` and `config/b2.read-key`, owned by the service UID with mode 0400. Use a protected credential source. The origin and preparer do not require a write, delete, recovery-bucket or whole-library credential.

3. Under the root-controlled configuration directory, atomically replace `scope.json` with a mode-0440 file owned by root and the service group. Use the real bucket, fixed HTTPS endpoint and region. The example values are placeholders.

   ```json
   {"video_id":"<video-uuid>","generation":1,"endpoint":"https://<s3-endpoint>","bucket":"<primary-bucket>","region":"<region>"}
   ```

4. Restart only this origin to load the selected scope. With the approval directory still empty, prepare the candidate **outside** it. The preparer rechecks the generation and current object versions after hashing every HLS object.

   ```sh
   native restart origin
   mkdir -p -m 0700 "$app/review"
   native run --rm --no-deps -T origin prepare > "$app/review/$video_uuid.json"
   ```

5. Review the complete HLS graph, sizes, per-object SHA-256 digests and immutable version IDs. After separate approval for that candidate, install it atomically.

   ```sh
   install -m 0440 -o root -g vidra-native-ref "$app/review/$video_uuid.json" "$app/approvals/.approved.tmp"
   mv -T "$app/approvals/.approved.tmp" "$app/approvals/$video_uuid.json"
   ```

6. Verify a known object range through the origin against the reviewed immutable bytes. To rehearse publication, use a **separate offline Kubo repository**, its own token, RPC port and publication receipt directory, and the publisher's `--origin-port 8786`. Record the expected CID, cold restart, digest checks and decoded playback. For example, with a separately initialized offline native node on RPC port 5182, use the following command. Configure that node's loopback API and gateway to distinct free ports before starting it. Keep its swarm addresses and bootstrap list empty and start it with `daemon --offline`.

   ```sh
   publisher=/usr/local/lib/vidra-ipfs-reference/publish
   "$publisher" --manifest "$app/approvals/$video_uuid.json" \
     --origin-port 8786 --rpc-port 5182 --rpc-token-file "$app/native-node.token" \
     --state-dir /var/lib/vidra-native-reference/publications
   ```

   The existing synthetic-only peering guard admits its approved synthetic root. Global native peering requires a separate reviewed admission procedure and explicit per-video permission. [Publisher and withdrawal procedure](../../publisher/README.md)

7. To withdraw, unlink the one approved manifest from `approvals/` and require HTTP 404 with zero bytes for previously approved references. Reconcile or withdraw the managed pin on its own offline node. Revoke the scoped storage credential, restore `scope.json` to `{}`, remove its two credential files and restart only this origin. Repeat the dormant checks. Independently held public copies remain under the control of their peers.

## Restart and recover

Docker's `unless-stopped` policy restarts the service with the daemon after a normal host reboot. Ordinary PostgreSQL container recreation can change its private address. Every eligibility query uses the `postgres` service name and a fresh connection. A database outage fails approved reads closed. If the application stack's private network is deliberately removed, recreate that network with the stack and run `native up -d --force-recreate origin`.

Record the reviewed source commit, the package versions from `docker run --rm --entrypoint apk "$image" info -v`, image ID and SHA-256 of an exported image archive (`docker image save "$image" | gzip -n`). Encrypt these with the Compose file and environment, the adapter and shipped origin/preparer source, grant and verification scripts, service UID/GID, `config/pgpass`, scope, approval manifests and any active per-generation storage credentials. Include the offline node's separate identity, token, publication receipts and expected CID when provisioned. Keep credentials out of source control. On restoration verify the archive hash and loaded image ID. Recreate service ownership, verify role privileges, restore the selected scope and use the offline recovery procedure before any separately authorized peering. [Rebuilding references after primary loss](../../publisher/README.md)


### Restore a database that grants the native reader access

A database dump records the grant on the view. PostgreSQL stores logins in the cluster, outside that dump. On a fresh recovery host, create the reader **before** replaying the dump. Keep the native origin stopped and the replacement host off public traffic during recovery.

1. Recover the reviewed image archive, the protected native configuration and the release-matched application stack on the replacement host. Restore `config/pgpass` from encrypted escrow with the native service UID/GID and mode 0400. Keep its parent root-controlled and mode 0750. Hold saved approvals and storage credentials outside the dormant configuration while verifying the restore.
2. Start the isolated bundled database and run the compatible release's ordinary core migrations on its empty application database. Migration 194 supplies the view the reader bootstrap checks. From the installed meta repository root, use the replacement host’s configured production Compose project.

   ```bash
   sudo -u vidra ./deploy/compose.sh up -d --wait postgres
   sudo -u vidra ./deploy/compose.sh run --rm --no-deps migrate
   ```

3. Provision the cluster login using the recovered password. Pass `--container` and `--project` to the reader command when the recovery names differ from the defaults.

   ```sh
   app=/etc/vidra-native-reference
   reader() { python3 "$app/init-reader.py" --dir "$app/config" --uid "$(id -u vidra-native-ref)" --gid "$(id -g vidra-native-ref)"; }
   reader
   ```

4. Run the standard restore against the intended recovery database, retaining its access-control entries. The script stops application writers, drops and recreates the database, and runs `pg_restore`. The cluster login survives, so PostgreSQL can replay the view grant. If a previous restore failed while granting access to a missing login, repeat the restore from a clean target after provisioning the login. With recovery acceptance enabled the script also checks referenced media before it starts applications. [Database restore procedure](../../../README.md)

   ```sh
   sudo -u vidra ./deploy/restore.sh --require-media-consistent "$recovery_dump"
   ```

5. Run `reader` again after restore. Database recreation also removes the per-database login settings. Reapplying the bootstrap restores the reader's read-only default and statement timeout, then checks its effective application privileges. Start the origin in dormant mode and verify its protected-table and HTTP denials. Restore selected scopes and approvals individually after that check.

   ```sh
   reader
   docker compose --env-file "$app/compose.env" -f "$app/compose.yml" up -d --no-build
   python3 "$app/verify-dormant.py" --env-file "$app/compose.env" --image-id-file "$app/image.id"
   ```

## Offer IPFS on approved watch pages

Use this bridge with a Vidra core release that accepts `IPFS_REFERENCE_PLAYBACK_SOCKET`. The existing **Use IPFS** player control takes its URL from the playback session for the current public video and generation. Viewers choose it manually. The normal HLS source remains available for fallback.

1. Configure the reference reporter for the same Kubo node and include the native approval directory, publication journal and native origin port in its sources. The bridge uses the same local gateway and the restricted `pin/ls` token. Keep the gateway in NoFetch mode, keep the gateway, origin and RPC on loopback and keep their credentials on the host. The already-approved external synthetic rehearsal has its own manifest format and no native watch record.
2. Build the matching publisher binary using the [publisher guide](../../publisher/README.md). Install that build at `/usr/local/lib/vidra-ipfs-reference/playback` with mode `0755`. This gives playback its own release and rollback path while the existing publisher keeps running. Install `vidra-reference-playback.service` and `vidra-reference-playback.socket` from the parent directory under `/etc/systemd/system/`. Run `systemctl daemon-reload` and `systemctl enable --now vidra-reference-playback.socket`. Systemd creates `/run/vidra-reference-playback/playback.sock` for UID 10001, the standard production API user. Adjust the socket owner through a unit override if the API runs under another host UID.
3. Set `IPFS_REFERENCE_PLAYBACK_DIR=/run/vidra-reference-playback` in the production environment and use the standard guarded deployment. The optional Compose overlay mounts only this socket directory into the API. A fresh installation can start with empty approvals. With an approved native publication, open that video's watch page, select **Use IPFS** and confirm the browser retrieves the approved generation's master, variant and media and decodes frames. Check an unapproved watch page for normal playback without a reference option.
4. Each file request requires the exact generation in the native eligibility view and membership in the installed HLS manifest, a matching published receipt and a live recursive pin. The gateway reads the CID selected by that receipt. Withdrawing the approval removes the URL from new sessions and denies subsequent file requests, including from previously issued links. Follow the withdrawal procedure above for the pin and its restricted S3 reader.

To remove the watch option for all reference pins, clear `IPFS_REFERENCE_PLAYBACK_DIR`, redeploy the API and disable both the socket and service. The separate aggregate status reporter can continue monitoring the node. Include the bridge units and config in the operator recovery kit alongside the node's existing approval and publication records.
