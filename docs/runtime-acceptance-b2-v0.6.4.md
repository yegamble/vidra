# v0.6.4 Backblaze B2 runtime continuation

**Executable handoff ready; runtime blocked on test-key transfer approval.
Full release remains NO-GO.** The operator requires
Backblaze B2 for test media and excludes all Sizetube live and backup buckets.
The [completed local-storage run](runtime-acceptance-v0.6.4.md) is retained as
historical, bounded evidence. No B2 result is inferred from that run or MinIO CI.

[Preparation evidence](evidence/release-v0.6.4-verification/b2-runtime/preparation.json)
records the actual B2 scope/empty-version inventory, bucket configuration,
new host/firewall, prepared input hashes and 52 local checks (89 Python tests,
zero skips). Harness commit `c589d3d9dc3f07bfe01898f3b16c84da424a69c6` is pushed
to draft PR #186. The nonsecret archive is staged on the new host; its local
and remote SHA-256 match, and native blank-host preflight passes.

Automatic approval review rejected sending the new scoped key to
`159.203.118.182`, because it requires explicit user authorization for that
credential transfer to that specific destination. The key has **not** been
transferred, the installer/runtime has **not** started, and no workaround was
used. The precise remaining input is approval to copy this seven-day key,
restricted to the named new test bucket, to this disposable host. This blocks
only B2-dependent runtime execution; all independent preparation is complete.

## Storage isolation

Only a newly created, empty private bucket is used:
`vidra-acceptance-v064-20260911-media`, ID `e565124b996984e8a7070215`, endpoint
`s3.us-east-005.backblazeb2.com`, region `us-east-005`. Creation enabled SSE-B2
encryption. A seven-day key is restricted to exactly this bucket with
`listBuckets,readBuckets,listFiles,readFiles,writeFiles,deleteFiles` only.
It cannot manage keys, bucket policies, encryption, retention or other buckets.
The account credential stays on the operator workstation; only the restricted
test key goes to the disposable application host. Backblaze's own authorization
response confirmed the exact bucket ID/name and capabilities, and its version
inventory was empty before deployment.

All existing buckets are excluded, including Sizetube live/backup and the
historical `vidra-acceptance-20260905-a36` recovery evidence. A prefix inside an
existing bucket is not acceptable isolation. No existing bucket's objects,
versions, lifecycle, retention, CORS or policy were changed. No deletion probe
against an excluded bucket is needed or authorized: validate the provider's
key scope before any bucket operation.

The [B2 guard](../tests/release_acceptance_b2.py) rejects broad or multiple-bucket
keys, unexpected capabilities, mismatched IDs/endpoints, old bucket names and
nonempty buckets including hidden versions. It does not clean a bucket for
reuse. After the browser run, it requires B2's original-file SHA-1/length to
match the fixture and real playlists/fragments plus Vidra's ownership marker
to exist in this same bucket. The original downloaded through Vidra must still
match SHA-256 and Chromium must decode advancing video/audio. These checks
establish canonical B2 media with API-proxied delivery; presigned/CDN delivery,
version-retention billing, destructive GC and recovery are separate requirements.

Provider semantics: [Backblaze application-key restrictions](https://www.backblaze.com/docs/cloud-storage-application-keys)
and [S3-compatible API](https://www.backblaze.com/docs/cloud-storage-s3-compatible-api).

## Reproduce on a fresh host

Use the same frozen manifest, native Ubuntu 24.04 AMD64 host preparation and
SSH-only firewall from the [local runbook](runtime-acceptance-v0.6.4.md#provision-the-host).
The new B2 host is DigitalOcean `599531580`, `159.203.118.182`, Ubuntu 24.04
AMD64, 8 vCPUs/16 GiB/320 GiB, created `2026-09-11T03:50:54Z`. The earlier
local run and private evidence remain on `159.65.249.255`. No production
host, shared lab or mounted production disk is involved. Each disposable host
costs approximately $0.14286/hour while retained.

For a subsequent run, create another **new** acceptance bucket and restricted
key; never reuse/empty this bucket automatically. On the operator workstation:

```bash
umask 077
mkdir /tmp/vidra-v064-b2-next
b2 bucket create vidra-acceptance-v064-YYYYMMDD-media-NONCE allPrivate \
  --default-server-side-encryption SSE-B2 > /tmp/vidra-v064-b2-next/bucket-id
b2 key create --bucket vidra-acceptance-v064-YYYYMMDD-media-NONCE \
  --duration 604800 vidra-v064-media-acceptance \
  listBuckets,readBuckets,listFiles,readFiles,writeFiles,deleteFiles \
  > /tmp/vidra-v064-b2-next/key.txt
```

Use an actual date/lowercase nonce. Convert the two whitespace-separated key
values into a mode-0600 JSON file with `access_key` and `secret_key` fields;
never print it, put it in Git, or include it in the public handoff archive.
Put only `bucket`, `bucket_id`, `region`, `endpoint` in `storage-spec.json`.
For this run these private inputs are in `/tmp/vidra-v064-b2-test/`.

```bash
python3 tests/release_acceptance.py prepare \
  --frozen /tmp/vidra-release-verification-20260910/v0.6.4/preflight \
  --node-archive /tmp/vidra-v064-acceptance-toolchain/node-v26.8.1-linux-x64.tar.xz \
  --node-sums /tmp/vidra-v064-acceptance-toolchain/SHASUMS256.txt \
  --b2-spec /tmp/vidra-v064-b2-test/storage-spec.json \
  --out /tmp/vidra-v064-b2-handoff
tar -C /tmp/vidra-v064-b2-handoff -czf /tmp/vidra-v064-b2-handoff.tar.gz .
```

Transfer the archive and separately the scoped key via SSH to the **new B2
host**. Compare archive hashes, extract into a new mode-0700
`/root/vidra-v064-runtime`, and keep the key at
`/root/vidra-v064-b2-key.json` mode 0600. The same host preflight applies. Then:

```bash
systemd-run --unit=vidra-v064-acceptance \
  /usr/bin/env -i PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
  LANG=C.UTF-8 /usr/bin/python3 /root/vidra-v064-runtime/release_acceptance.py run \
  /root/vidra-v064-runtime --acknowledge fresh-disposable-host \
  --b2-credentials /root/vidra-v064-b2-key.json
journalctl -u vidra-v064-acceptance --no-pager -n 30
systemctl show vidra-v064-acceptance -p ActiveState -p ExecMainStatus
```

The harness uses the released `vidra setup --storage s3` engine and checks
both API and worker configuration. Credentials are omitted from command
evidence; the setup secret uses the released environment-input mechanism.
Deployment scripts, migrations, application digests, fail-closed scanner,
transcoding and request limits remain unchanged. Apply the same on-host
sanitized evidence export after PASS. Keep raw outputs/credentials private.

Only dependent object-storage checks gain evidence here. All other provider,
representative-source, recovery and launch-scope decisions remain as recorded.
The draft PR remains unmerged by explicit instruction.

## Resume the already staged run after approval

The archive already on `159.203.118.182` has SHA-256
`ce19ec2bdccea21e882c8f72158e4a2e1b6d3bcd6e99470539f7cdcca01d9ce4`;
`handoff.json` has SHA-256
`b65238af8f6fa07ddf2573e5f281be516bab38e40e0209c95e680cf5632f5d92`.
Do not recreate the bucket, regenerate inputs or extract over this stage.
The only pending transfer and launch, from the operator workstation, are:

```bash
scp -F /dev/null -i /Users/yosefgamble/.ssh/id_rsa \
  -o IdentitiesOnly=yes -o BatchMode=yes \
  -o UserKnownHostsFile=/tmp/vidra-v064-b2-test/known_hosts \
  /tmp/vidra-v064-b2-test/scoped-key.json \
  root@159.203.118.182:/root/vidra-v064-b2-key.json
ssh -F /dev/null -i /Users/yosefgamble/.ssh/id_rsa \
  -o IdentitiesOnly=yes -o BatchMode=yes \
  -o UserKnownHostsFile=/tmp/vidra-v064-b2-test/known_hosts root@159.203.118.182 \
  'chmod 600 /root/vidra-v064-b2-key.json &&
   systemd-run --unit=vidra-v064-acceptance \
   /usr/bin/env -i PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
   LANG=C.UTF-8 /usr/bin/python3 /root/vidra-v064-runtime/release_acceptance.py run \
   /root/vidra-v064-runtime --acknowledge fresh-disposable-host \
   --b2-credentials /root/vidra-v064-b2-key.json'
```

Key expiry, later bucket contents or changed host prerequisites must produce
a new explicit blocker or new isolated run, never a broader credential or
automatic cleanup of retained evidence.
