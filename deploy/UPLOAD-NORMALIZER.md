# Enabling local processing for large uploads

With core migration 0196, a creator can submit a resumable upload up to **21,474,836,480 bytes (20 GiB)**. Inputs larger than 2,147,483,645 bytes go through an isolated local encoder. Vidra scans the rebuilt MP4 before attaching it to the video and scans newly generated playback media and artwork before storing them. Downloads labelled `original` for this type of video serve the rebuilt MP4 under the video's download and visibility settings.

## Verify the release on the operator machine

Use the official release record and a passing [release preflight](./release-preflight.py). Set `RELEASE_RECORD` to the reviewed record and `PREFLIGHT` to the preflight's absolute output directory. The release record can be obtained after publication. The following commands target the official SizeTube/Vidra repositories and require `gh`, `jq` and `sha256sum`.

```bash
set -euo pipefail
meta_commit=$(jq -er '.meta_commit' "$RELEASE_RECORD")
core_commit=$(jq -er '.components.core.commit' "$RELEASE_RECORD")
core_tag=$(jq -er '.components.core.tag' "$RELEASE_RECORD")
image=$(jq -er '.components.core.image | .repository + "@" + .index_digest' "$RELEASE_RECORD")
jq -e --arg meta "$meta_commit" --arg core "$core_commit" --arg image "$image" \
  '.status == "PASS" and .repositories.vidra.revision == $meta
   and .repositories["vidra-core"].revision == $core and .images["vidra-core"].reference == $image
   and (.upload_normalizer_files | length == 4)' \
  "$PREFLIGHT/manifest.json" >/dev/null
test "$(gh api "repos/yegamble/vidra/git/commits/$meta_commit" --jq '.verification.verified')" = true
gh attestation verify "oci://$image" --repo yegamble/vidra-core \
  --signer-workflow yegamble/vidra-core/.github/workflows/publish-container.yml \
  --source-ref "refs/tags/$core_tag" --source-digest "$core_commit" --deny-self-hosted-runners
receipt=$(mktemp -d)
jq -er '.upload_normalizer_files | to_entries[] | "\(.value)  \(.key)"' \
  "$PREFLIGHT/manifest.json" > "$receipt/normalizer.sha256"
printf '%s\n' "$image" > "$receipt/core-image"
(cd "$PREFLIGHT/source/vidra" && sha256sum -c "$receipt/normalizer.sha256")
```

Preflight reads the broker, both systemd units and the Compose overlay inside the released bundle and compares their bytes with the files in the verified, signed meta commit. The image attestation binds the OCI digest to the core commit and publishing workflow. Transfer the four checked files with their relative paths, the verified checksum receipt and `core-image` through your approved operator channel.

## Prepare the Linux host

Use a Docker host with systemd and the fail-closed ClamAV profile. At 20 GiB the broker requires at least **45,097,156,605 bytes free** on `/var/lib/vidra-upload-normalizer` before it reads the input. This covers one source, one bounded MP4 and a 20 GiB reserve. The broker holds one exclusive job lock. Its encoder runs as UID 10001 with two CPUs, 2 GiB memory and swap combined, 96 PIDs, a read-only root and networking disabled. It sees only the input file and output file. Processing has a 24-hour deadline plus a one-minute allowance.

Budget the worker's `/scratch` volume, ClamAV temporary files and PostgreSQL separately, especially if they share this filesystem. The worker's default free-space floor is 10 GiB, with a per-source check of three times the stored source size. The [production environment](../env/production.env.example) gives the scanner a 10-minute client timeout, 2,147,483,645-byte stream and file limits, a 3,072 MiB expanded scan limit, alerts on exceeded limits, two threads and a 4 GiB memory budget. Check the actual host values and free capacity before raising admissions.

Run these commands from the transferred directory. `VIDRA_DIR` identifies the installation of the same meta release. Existing installations should close new large admissions and drain active normalizations before replacing the broker files.

```bash
set -euo pipefail
sha256sum -c normalizer.sha256
cmp docker-compose.processed-uploads.yml "$VIDRA_DIR/docker-compose.processed-uploads.yml"
image=$(cat core-image)
docker pull "$image"
docker run --rm --pull never --read-only --network none --cap-drop ALL \
  --security-opt no-new-privileges --entrypoint /bin/sh "$image" \
  -ec 'test -x /app/normalize-upload && sha256sum /app/normalize-upload'
sudo install -d -m 0755 /usr/local/lib/vidra /etc/vidra-upload-normalizer
sudo install -d -m 0700 /var/lib/vidra-upload-normalizer
sudo install -m 0644 deploy/upload-normalizer.py /usr/local/lib/vidra/upload-normalizer.py
sudo install -m 0644 deploy/vidra-upload-normalizer.socket deploy/vidra-upload-normalizer@.service /etc/systemd/system/
sudo install -m 0644 core-image /etc/vidra-upload-normalizer/core-image.new
sudo mv -f /etc/vidra-upload-normalizer/core-image.new /etc/vidra-upload-normalizer/core-image
cmp deploy/upload-normalizer.py /usr/local/lib/vidra/upload-normalizer.py
cmp deploy/vidra-upload-normalizer.socket /etc/systemd/system/vidra-upload-normalizer.socket
cmp deploy/vidra-upload-normalizer@.service /etc/systemd/system/vidra-upload-normalizer@.service
cmp core-image /etc/vidra-upload-normalizer/core-image
sudo systemd-analyze verify /etc/systemd/system/vidra-upload-normalizer{.socket,@.service}
sudo systemctl daemon-reload
sudo systemctl enable --now vidra-upload-normalizer.socket
systemctl is-active vidra-upload-normalizer.socket
test "$(stat -Lc '%u %a' /run/vidra-upload-normalizer/processor.sock)" = "10001 600"
df -B1 /var/lib/vidra-upload-normalizer
```

## Qualify admission and recovery

1. Keep the ordinary upload cap in place while deploying the reviewed core through the normal backup, migration and health checks. Set `UPLOAD_NORMALIZER_DIR=/run/vidra-upload-normalizer`. The Compose overlay mounts only that socket directory into API and worker. Start with transcode concurrency one and confirm ClamAV is in `fail-closed` mode.
2. On an isolated deployment with the intended S3 configuration and size limit, upload a private synthetic 20 GiB video. Interrupt and resume it. Verify that 20 GiB plus one byte is refused, processed playback decodes, the authorized download is the rebuilt MP4, anonymous access to the private video is denied, and completed staging is cleaned up. Check scanner behavior for a rejected file and a scanner outage.
3. Raw resumable pieces live under the private S3 `uploads/<session>/<index>` prefix. The worker streams them to the host broker, which temporarily writes a mode-restricted job directory. Successful completion and the upload sweeper remove staging objects. Bucket versioning and recovery retention can preserve older versions. Keep both buckets private. The scanner, public playback and normal download routes use rebuilt or generated bytes.
4. Rehearse recovery with a verified pre-onboarding dump and a schema-0196 dump. Restore into separate empty databases and verify active upload purpose, chunk ledger, queued finalizer, draft privacy, retained rebuilt source key and pending transcode. Database recovery also requires the corresponding media objects for resumed work or playback. Preserve the release-specific image digest and verified broker files in the recovery procedure.
5. After the creator, scanner, storage and recovery checks pass, set the effective `upload_max_size_bytes` to `21474836480` in instance settings, or set `UPLOAD_MAX_SIZE=21474836480` and redeploy if the instance has no database override. Ordinary direct upload routes keep the whole-file scanner limit. For an app rollback across 0196, follow the [rollback procedure](./README.md#reconstructed-uploads).
