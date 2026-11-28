# Run an isolated IPFS reference node

Use this deployment to rehearse publication of an individually approved synthetic HLS directory. The node runs on Linux with systemd. Its URLStore records point to an origin on the same host that reads immutable versions from an S3-compatible primary bucket. Kubo stores directory and file metadata locally. A cold read of the content requires both the origin and primary storage.

Prepare a new service account, node identity and empty repository for this deployment. Sharing another node's repository can expose blocks outside the approval. External peers may retain any material they receive from a public swarm.

For an individually approved native upload, use the [separate native origin](native/README.md).

## Install the offline services

1. Install Python 3 with botocore, the reference origin, and Kubo 0.43.0. Verify the upstream archive digest for the target architecture. The official Linux amd64 archive SHA-256 is `2ccb2c16c4ed0c893858dc6ac8a062d789e36a03339a7164459a917b64354c3d`. Install executables and scripts under root ownership in `/usr/local/lib/vidra-ipfs-reference/`. Use the filenames `kubo-v0.43.0`, `origin.py`, `init-node.py`, `network-mode.py` and `publish`.
2. Create the system users `vidra-ref-node` and `vidra-ref-origin`, each with its own group and a nologin shell. Create `/var/lib/vidra-ipfs-reference/node` with owner `vidra-ref-node` and mode 0700. Its parent needs traverse permission for that account.
3. Create `/etc/vidra-ipfs-reference/` under root ownership. Give its `approvals/` directory owner `root:vidra-ref-origin` and mode 0750. Install the single approved synthetic manifest as `approvals/<video-uuid>.json` with the same owner and mode 0440. It must describe only the HLS files for this UUID under `operator-readiness/ipfs-reference/<video-uuid>/`.
4. Give the origin a credential restricted to reading the synthetic prefix in the primary bucket. Put `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `S3_ENDPOINT` (HTTPS), `S3_BUCKET` and `S3_REGION` in the root-owned, mode-0600 `/etc/vidra-ipfs-reference/origin.env`. Systemd reads this file before starting the unprivileged origin.
5. Generate the RPC token once and initialize the dedicated repository. Run the following as root on a fresh installation.

```sh
umask 077
python3 -c 'import pathlib,secrets; p=pathlib.Path("/etc/vidra-ipfs-reference/rpc.token"); f=p.open("x"); f.write(secrets.token_urlsafe(40)+"\n"); f.close()'
runuser -u vidra-ref-node -- env IPFS_PATH=/var/lib/vidra-ipfs-reference/node \
  python3 /usr/local/lib/vidra-ipfs-reference/init-node.py \
  </etc/vidra-ipfs-reference/rpc.token
```

6. Install the two systemd units in this directory into `/etc/systemd/system/`. Run `systemd-analyze verify` on the two installed unit paths, then `systemctl daemon-reload` and `systemctl enable --now vidra-reference-origin.service vidra-reference-node.service`.

| Component | Address | Access |
| --- | --- | --- |
| Kubo RPC | `127.0.0.1:5181` | Bearer token restricted to publish, pin, withdrawal, inventory and verification |
| Kubo gateway | `127.0.0.1:8185` | Local reads with `Gateway.NoFetch=true` |
| Reference origin | `127.0.0.1:8785` | Only approved objects, at their recorded version and within the range budget |

The node starts with URLStore enabled, local filestore disabled, no swarm listeners, and a systemd loopback-only network policy. Keep all three management and read endpoints on loopback during any later publication.

## Verify before publishing

1. Confirm both units are active and enabled, and check the three loopback listeners. An unauthenticated or incorrect bearer request to `POST /api/v0/pin/ls` must be denied. Read the token from its file for authenticated local tests. Keep it out of shell arguments, command history and logs.
2. Check the fresh node's pin and URLStore inventories. Kubo can bootstrap with a recursive pin to its canonical four-byte empty directory `QmUNLLsPACCz1vLxQVkXqqLX5R1X345qqfHbsf67hvA3Nn`. If this is the only pin, verify its empty link list and four-byte block size, remove that exact bootstrap pin using authenticated RPC, and restart offline. Inspect any other unexpected pin before proceeding.
3. Request an approved byte range from the origin and compare it with the immutable source. An unknown reference must return 404. The source reader should be able to recover its credentials and manifest after an origin restart.
4. Use the reference publisher to build the approved directory. Compare its root CID to an independent build, cold-read every object by hash, seek and decode the media, and verify that withholding the origin prevents a cold read. Check actual bytes and frames. Streaming RPC can return HTTP 200 and an empty body when the origin cannot serve a block.

## Verify and switch a synthetic node to public peering

Run the read-only check with the approved video UUID and independently verified directory CID. The helper checks that this is the only explicit pin, every reference belongs to the approved manifest, and each local block belongs to that directory or Kubo's canonical empty directory.

```sh
python3 /usr/local/lib/vidra-ipfs-reference/network-mode.py online \
  --video-id "$approved_video_uuid" --cid "$approved_root_cid" \
  --swarm-port 4201 --check-only
```

One additional native generation can share this node after explicit global approval and an independent offline rehearsal. Verify its original bytes, eligible public state, exact generation-scoped S3 reader, reviewed manifest and offline directory CID using the [native procedure](native/README.md#prepare-and-withdraw-a-single-approval). Run the original one-root check before publication. After adding only the rehearsed native CID, supply all three native arguments together. The generation is the positive integer from the reviewed master key.

```sh
python3 /usr/local/lib/vidra-ipfs-reference/network-mode.py online \
  --video-id "$approved_video_uuid" --cid "$approved_root_cid" \
  --native "$native_video_uuid" "$native_generation" "$native_root_cid" --check-only
```

This check requires exactly the two named recursive pins. Every raw leaf must resolve through the URLStore references for its own video's manifest, and every local block must belong to an approved directory or Kubo's empty directory. Keep both identities, CIDs and the native generation with the recovery journals. For withdrawal, remove the native approval, reconcile its journal, and verify the one-root inventory again on a clean node. Unpinning can leave unreferenced blocks locally until garbage collection. Keep the node offline if it retains any block outside the remaining approval.

After explicit approval for global publication, run that command again without `--check-only`. The helper saves the offline config in `/etc/vidra-ipfs-reference/node.offline.json`, enables bootstrap and TCP peering on the selected port, and creates a systemd override for the dedicated node. The online override allows `AF_NETLINK` so libp2p can enumerate the node's external address. The service runs with an empty capability set. Check its advertised multiaddress and peer count and verify retrieval from a second independent peer with an empty cache. For direct connections, a separately authorized firewall rule may admit the selected swarm TCP port on this node. Record the target, source scope and rule identity so that rule can be removed independently.

## Withdraw, roll back and recover

- Stop public peering with `python3 /usr/local/lib/vidra-ipfs-reference/network-mode.py offline`. It restores the saved node config, removes the dedicated networking override and restarts offline. If a dedicated ingress rule was added, remove only the rule for that node and its selected swarm TCP port. Verify that the swarm has no listener, the cloud rule is gone and RPC, gateway and origin still bind to loopback.
- Withdraw approval and unpin using the publisher's withdrawal procedure. Check that further origin reads are refused. Once public peers have received content, withdrawal controls this operator's services. Those peers retain control over their copies.
- For a full service rollback, disable and stop both units. Preserve the primary media and its version history. Record the trigger and verification results before retiring credentials or the Kubo peer identity.
- Back up both unit files and any active override, `origin.env`, `rpc.token`, approval manifests, the Kubo `config` and `node.offline.json` when present. The node config contains its private peer identity. Also preserve the publication journal, origin program version, verified release digests, publisher version, expected root CID per manifest and any verified source-to-replica version map. Encrypt these together for independent operator custody and compare checksums after a test decrypt. On a replacement machine, start offline, restore the identity and credentials, rebuild approved directories from their exact source versions and compare CIDs and decoded playback before authorizing peering again.

If the primary bucket is lost, keep peering disabled and the origin bound to
loopback while restoring. Configure the origin with scoped read access to the
replacement store and install only manifests reviewed against its immutable
versions. Rebuild on an empty repository, then verify the saved CIDs, pin
inventory and playback before requesting authorization to reconnect.
[Publisher procedure for replacement versions](../publisher/README.md#rebuild-with-replacement-object-versions)

## Reporting reference pin health in Vidra

On the reference-node host, an optional timer compares the approval manifests and
publisher receipts with the dedicated Kubo node's recursive and direct pins. For
each approved video it reads and hashes the master and variant playlists through
the local no-fetch gateway, follows a media segment named by `#EXTINF`, and
compares up to 8 KiB of that segment with its immutable version through the
reference origin. Native origins check live video eligibility and generation at
read time. The publisher's dedicated reference node can run this check while
swarm peering is disabled.

1. As a host administrator, build and install the release's `publish` binary using
   the [publisher build instructions](../publisher/README.md). Keep the
   reference gateway and origins bound to loopback. Configure a Kubo bearer
   with `AllowedPaths` containing only `/api/v0/pin/ls`. Store its raw token in
   the root-owned, mode-0600 file named by `token_file`.
2. Copy [status.example.json](status.example.json) to
   `/etc/vidra-ipfs-reference/status.json` with root ownership and mode 0600.
   List every approval directory and publication journal served by this Kubo
   node. Add native approvals as a separate source using their private journal
   and eligibility-checking reader port. For a newly installed source that has
   never published, set `"allow_unpublished": true` until its first journal is
   created. Only an empty, readable approval directory can pass in that state.
3. Install the service and timer, run the first check, and inspect the aggregate.

   ```sh
   install -m 0644 deploy/ipfs-reference/runtime/vidra-reference-status.{service,timer} /etc/systemd/system/
   systemctl daemon-reload
   systemctl start vidra-reference-status.service
   cat /var/lib/vidra-reference-status/status.json
   systemctl enable --now vidra-reference-status.timer
   ```

4. With a Vidra core release that supports reference status, set
   `IPFS_REFERENCE_STATUS_DIR=/var/lib/vidra-reference-status` in the stack
   environment. Run the standard deployment and inspect the admin connection
   status. The API receives a read-only mount of the directory so atomic file
   replacements are visible. Keep this directory dedicated to aggregate status.
   If the API runs on a different host, deliver this single file via an
   authenticated channel and replace it atomically there. Preserve the
   node's original observation time.

| State and reason | Interpretation and operator action |
| --- | --- |
| `ok / verified` | The verified count is the number of unique approved recursive roots. Zero means both the configured approvals and observed pin inventory are empty. |
| `degraded / pin_set_mismatch` | Inspect missing, unfinished, withdrawn or unexpected pins and any native eligibility refusal. Reconcile through the normal publisher workflow. |
| `degraded / media_unverified` | Check gateway, playlists, immutable origin access and probe limits. |
| `down / approval_unavailable` | Check the configured approval and journal paths, permissions and native eligibility reader. |
| `down / node_unavailable` | Check the Kubo service, local RPC port and inventory bearer. |

The report refreshes every minute and contains only its schema version, UTC
observation time, state, reason and count when verified. The API treats a report
older than five minutes as stale. A check allows 40 seconds, at most 64
approvals, 256 KiB per playlist, eight playlist levels and 4 MiB of aggregate
media reads. It samples one rendition per approval. Decoding, whole-library
integrity and retrieval by an independent swarm peer require separate tests.

To remove the integration, clear `IPFS_REFERENCE_STATUS_DIR`, redeploy the API
and disable the timer with `systemctl disable --now vidra-reference-status.timer`.
