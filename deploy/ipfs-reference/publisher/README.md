# Publishing an approved S3-backed IPFS video

The publisher reads one approved HLS generation from a private S3 reference origin
and gives Kubo a stable URL for each object. Kubo keeps the directory structure,
block hashes and offsets on disk. It reads media bytes from the exact S3 versions
when a peer requests them. Both the initial add and subsequent playback read from S3.
A reference pin depends on the origin, its read credential and those object versions.

## Publish one video

1. Obtain approval to distribute the specific video on the intended network.
   On the global network other peers can keep a copy after withdrawal.
2. Review the manifest for that video. It binds the video ID and master key to
   each object's key, S3 version ID, byte length and SHA-256. Install it as
   `<video-uuid>.json` in the origin's operator-controlled approval directory.
   The service must be able to read the file. Only the operator should be able
   to replace or remove it.
3. Start the dedicated reference origin and Kubo. Use URLStore, raw leaves and
   a fresh repository for the first adoption. Bind the authenticated RPC and
   reference origin to loopback. Start offline for initial verification. Keep
   regular catalogue copying disabled on this node.
4. Build and run the publisher with Go 1.22 or later. Set `APPROVAL_FILE` to the
   installed manifest and `KUBO_TOKEN_FILE` to the private bearer-token file.

   ```sh
   cd deploy/ipfs-reference/publisher
   go build -trimpath -o vidra-reference-publish .
   ./vidra-reference-publish -manifest "$APPROVAL_FILE" -rpc-token-file "$KUBO_TOKEN_FILE"
   ```

   The default RPC and origin ports are 5181 and 8785. The token needs Kubo
   `/api/v0/add` and `/api/v0/pin/add`. The publisher checks the HLS links and
   SHA-256 digests, rechecks approval, then prints the recursively pinned
   directory CID. The playback entry point is `/ipfs/<directory-cid>/master.m3u8`.
5. Restart the offline node. Read every HLS file by CID and compare its
   SHA-256 with the manifest. Seek into the video and decode frames. Inspect
   Kubo's URLStore entries and compare the repository size before and after.
   Temporarily deny access to the reference origin and verify a cold media
   read fails to return the expected bytes. Restore access and repeat the read.
   A gateway can return HTTP 200 before it encounters a source-read error.
6. For a video explicitly approved for the global network, enable public
   peering on the dedicated node and advertise the verified pin. Retrieve
   the CID from an independent peer and repeat the integrity and playback
   checks. Keep the Kubo RPC and reference origin private.

The synthetic test namespace accepts an operator-created HLS test pattern.
Catalogue videos use the live eligibility view and a native, versioned HLS
generation. The origin checks catalogue eligibility during block reads.
Installing a manifest or enabling the old catalogue backfill are separate
operations. The publisher accepts one manifest per invocation.

## Withdraw and recover

Remove the approval from the origin first. Confirm a cold read through the
operator's node can no longer retrieve that video's media. Remove its recursive
pin using the node's authenticated operator interface. Check for another
approved video using the same CID before removing a shared pin. Run garbage
collection on the dedicated node and repeat the cold read. If two approved
videos shared source blocks, verify the retained video after withdrawal.

Back up the approval manifests, the verified root CIDs, the node identity and
the origin configuration with the operator's encrypted recovery materials.
Preserve the corresponding immutable S3 versions. To rebuild, restore the
approvals and source access, repeat publication on an empty offline node and
compare each resulting CID to the saved CID before advertising it again.
