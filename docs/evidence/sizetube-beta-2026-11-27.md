# SizeTube private beta qualification, November 27, 2026

**Hold public traffic on PeerTube.** Private beta upgraded to Vidra v0.7.32 at
03:46 UTC. At 03:48:52 UTC, the public apex's configuration API returned HTTP
200 and identified PeerTube 8.3.1. Media recovery, the final import from a
frozen source and cutover acceptance remain open. [Cutover checklist](../sizetube-cutover-checklist.md)

## Release and deployment

Beta's core image matched the published v0.7.32 index and its API reported the
tagged core commit. The frontend and search image digests matched their v0.7.31
pins. The database reported clean core and search migration ledgers at 194 and
21, respectively. The readiness and HTTPS edge checks passed.
[v0.7.32 release record](../../releases/v0.7.32.json)

On published images the upgrade rehearsal induced a real failure applying
migration 194, then recovered the dirty ledger, rolled back, refused an
incompatible restore and restored under the correct pins. Media hashes matched.
A separate, empty runner restored a synthetic backup and matched the schema
and data catalogue, including the new eligibility view. The service rejected
an incorrect recovery key and MFA code, and accepted the correct MFA code.
The pinned media end-to-end test also passed. [Upgrade and rollback](https://github.com/yegamble/vidra/runs/140298780560)
· [Replacement-host restore](https://github.com/yegamble/vidra/runs/140298645305)
· [Pinned media test](https://github.com/yegamble/vidra/actions/runs/45935455660/job/140297511818)

The latest capacity test used v0.7.31 at 2,192 synthetic origin API
requests per minute for ten minutes. All 21,920 requests succeeded, with
109 ms aggregate p95 and 399 ms search p95. A repeat on v0.7.32 would be
needed to claim those figures for this release. [November 25 test and scope](../sizetube-cutover-checklist.md#november-25-publication-date-acceptance-on-private-beta)

## Playback and backups on beta

At 03:46:31 UTC, the imported video's detail, master playlist and variant
playlist returned HTTP 200. A media range returned HTTP 206 with the expected
128 header bytes. The legacy watch link redirected to a canonical page that
returned HTTP 200. An anonymous request for a private master playlist
returned HTTP 404.

The pre-deployment database and configuration backup ran at 03:23:51 UTC.
At 03:24:53 UTC both files matched the SHA-256 hashes of their decrypted
off-site copies. A second backup ran at 03:49:33 UTC after the view reader
was activated. The database archive was 183,086,166 bytes and the configuration
archive was 44,411 bytes. At 03:50:38 UTC both decrypted off-site copies
matched their source SHA-256 hashes.

At 03:54 UTC, the post-deployment backup restored into independent PostgreSQL
using the escrowed reader credentials. With the reader role created before
restore, the view grant survived. The restored reader could neither read the
protected user table nor create objects in the public schema. PostgreSQL's
per-database role settings needed to be reapplied after restore. A fresh reader
connection then verified read-only transactions, a two-second statement timeout
and zero eligible rows. The clean 194/21 ledgers, catalogue and source aggregates
matched, including 15,721 videos, 14,956 publication dates and 778 video blocks.

## IPFS distribution

At 03:29 UTC an isolated v0.7.32 deployment ingested an operator-generated
native upload and produced a CMAF rendition. An offline Kubo node opened
all 11 approved files using 13 URLStore records and retained zero raw media
blocks. After a three-second seek it decoded three frames. Changing either
privacy or the active transcode generation made the origin return HTTP 404,
prevented a fresh approval and removed the recursive pin. An intervening
reapproval of the same content reproduced its original content identifier (CID).
[Native reference runbook](../../deploy/ipfs-reference/runtime/native/README.md)

At 03:46 UTC, the `ipfs_public_reference_videos` database view returned zero
eligible native video generations and had zero grants to PostgreSQL's `PUBLIC`
role. At 03:49:08 UTC, the native reference reader could select that view and
PostgreSQL refused its read of the protected user table. The private native
service held zero approved manifests and zero media-storage credentials.

The sole public IPFS reference was the previously approved operator-generated
clip. Its seven objects had already been restored independently and reproduced
the original directory CID. At 03:46:58 UTC, a fresh
independent Kubo node discovered beta through the public distributed hash table
and retrieved all seven files.
All hashes matched across 1,969,881 bytes in 7.72 seconds. Playback decoded
three frames after a four-second seek. Legacy imported files remain outside
this native approval path.
[November 26 independent rebuild](sizetube-recovery-2026-11-26.md)

## Media recovery

At 03:56:20 UTC all 15 objects for the older private upload were available
from the recovery account. Each matched the source SHA-256 and had SSE-B2
encryption and 30-day governance retention. The four playlists resolved to
their referenced files. Destination-only playback decoded three frames after
a four-second seek.

At 03:56:49 UTC the recovery account held 246,218 of 251,042 historical
upload versions. The remaining 4,824 versions totaled 182,529,231,836 bytes.
All matched versions had the expected encryption and retention. Among them,
13,870 had no comparable checksum and 177,920 matched a provider checksum
marked unverified. Comparable checksums had zero mismatches. The remaining
versions, source visibility and subsequent uploads through the recorded
cutoff still require reconciliation.
[November 26 recovery checks](sizetube-recovery-2026-11-26.md)
