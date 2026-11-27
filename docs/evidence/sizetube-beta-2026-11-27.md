# SizeTube private beta qualification, November 27, 2026

**Go to schedule and open a controlled cutover window for Vidra v0.7.32.**
The verified point satisfies the operator-approved supplemental recovery
method. The external recovery kit passed readback at 14:37 UTC. The public apex still served PeerTube 8.3.1 at
that time. Switching public traffic requires a verified write freeze, a fresh source
snapshot and authoritative import, recovery coverage for changes since the
cutoff, final acceptance and an explicit switch decision.
[Cutover checklist](../sizetube-cutover-checklist.md)

## Controlled cutover window

At 15:01 UTC the beta backup service captured the database and configuration.
An independent reader fetched the encrypted versions from off-site storage and
verified the SHA-256 digests of the restored pair. The operator retained the
pair and rollback dump outside automatic pruning. A disposable PostgreSQL
instance restored the pair with clean core and search schemas at 194 and 21.

The released verifier's eleven database queries found five new file/hash
references, one new video and one new HLS root relative to the previously
verified restore. No previous references disappeared. The focused deep check
on the fresh restore found all 236 affected objects, matched all 199 recorded
hashes and traversed all three affected HLS trees. In a separate storage
comparison, all 251 current application objects touched since November 24
matched their independent recovery versions by full SHA-256 across
1,139,374,746 bytes. Four additional affected names were hidden.

PeerTube's public write freeze began at **15:17:02 UTC**. A public write
request returned HTTP 503 with a retry interval. Video detail, master and
variant playlists still returned HTTP 200. The first media range returned
HTTP 206 with an MP4 header. At 15:17:27 UTC the application database role
refused a write and the 27 paused worker queues had zero active jobs.

The frozen PostgreSQL dump and its reference fingerprint came from the same
repeatable-read snapshot. A separate transaction matched all 91 tables
and 5,379,895 row versions, including visibility and publication data for
15,748 local videos. The 218,537,930-byte archive matched by SHA-256 on
both hosts. By 15:27:35 UTC beta had restored the filtered source into a
fresh database containing 14,956 local videos and retained the previous
snapshot. The importer could read the new snapshot and its role had no
update grant.

At 15:28:38 UTC the ordinary deployment finished with the canonical
`sizetube.com` configuration behind private admission. All application
containers were healthy, and the IPFS node and origin were active. The
actual pre-deployment dump was retained outside pruning. All eight tested
legacy watch, channel, account and embed links reached canonical pages with
HTTP 200. The browser preflight admitted credentialed requests from the
apex and withheld that permission from an unrelated origin. Chrome followed
the reported legacy watch URL, sought past 30 seconds and decoded successive
frames, with zero media HTTP errors.

## Release and deployment

Private beta upgraded at 03:46 UTC. At 03:48:52 UTC, the public apex still
served PeerTube 8.3.1. Beta's core image matched the published v0.7.32
index and its API reported the
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
versions, source visibility and subsequent uploads through the cutoff
were still outstanding at that check.
[November 26 recovery checks](sizetube-recovery-2026-11-26.md)

At 14:33:04 UTC the supplemental transfer finished. An independent recovery
reader fetched all 582 historical uploads by their destination version IDs.
Their SHA-256 digests and lengths matched the source versions across
32,925,589,285 bytes. Six uploads used multipart transfers. Two destination
retention periods were extended and verified. All 582 originals were accounted
for, with zero substitutions or unresolved transfers. The operator Mac sent
the files directly to the private recovery bucket. At 14:37:53 UTC both
temporary transfer keys were absent from their account inventories and failed
fresh authentication.
[Supplemental media recovery procedure](https://vidra.yosef.app/docs/install/production#recovering-media-while-b2-replication-is-pending)

At 14:35:46 UTC the encrypted recovery map covered all 251,513 upload versions
and 4,562,441,091,133 bytes recorded before the 05:11:06.780 UTC cutoff.
Each upload mapped to a distinct immutable destination version. The map
preserved all 6,694 source hide actions.

| Recovery route | Upload versions | Bytes | Verification |
| --- | ---: | ---: | --- |
| Native B2 replicas | 250,922 | 4,529,515,501,290 | Source name, original upload time, length and available provider checksum. All had the expected SSE-B2 encryption and governance retention. |
| Supplemental copies of historical uploads | 582 | 32,925,589,285 | Full source and independent destination SHA-256 matched. At final verification, all used SSE-B2 and had at least 30 days of governance retention measured from their upload timestamps. |
| Copies of hidden operational write probes | 9 | 558 | Each 62-byte source mapped to a distinct newer recovery probe with identical bytes and SHA-256. The nine original native replicas were pending. Their source names remain hidden. |

The native checksums comprised 55,632 provider-verified SHA-1 matches, 181,400
matches marked unverified by the provider and 13,890 versions without a
comparable checksum. There were zero comparable mismatches. The native
replication queue remained open. Of the 251,042 historical uploads, 250,460
had native replicas and 582 used the supplemental route. The other 471
uploads in the selected point comprised 462 native replicas and nine probes.

At 14:36:39 UTC an independent check reopened the encrypted map and matched
every upload and hide record to the frozen inventory. The last recorded source
action left 240,907 names current and 6,691 hidden. A recovery reader retrieved
the private playback fixture's 15 objects through the final map and decoded
three frames after a four-second seek. A 1,713,981-byte public supplemental video
also matched its source SHA-256 and decoded three frames at the same seek.

At 14:36:56 UTC the operator restore helper refused a hidden name. Given the
original names, the existing recovery reader retrieved a 430-byte private HLS
master and a 1,036-byte supplemental object with the expected SHA-256. At
14:37:45 UTC the encrypted archive was independently reopened on the
operator’s external recovery drive. All 49 files passed verification, the protected
identity matched the previously tested copy, and the external map reopened
with all 251,513 destination IDs and 6,694 hide actions. The local operator
kit also passed verification.

## Live catalogue and queues

At 13:50 and 14:36 UTC, read-only queries matched all 13,890 publicly eligible
PeerTube video IDs to the public beta catalogue and its search index. Both sets had zero
missing or extra IDs. Each eligible video had a ready HLS playlist or an
original file recorded on beta. All 14,956 imported publication timestamps
matched production exactly. The live source had 792 local rows absent from
the saved import snapshot. All 792 belonged to blocked accounts or were
themselves blocked. The common rows showed no changes in video privacy,
publication state or time, moderation, account or channel assignment.

Production's four media queues had zero runnable or active jobs at both
13:50:43 and 14:36:50 UTC. The transcoding builder retained 41 waiting
parent entries whose child jobs were all absent. Of their source videos, 28 were published and 13 were
absent. The four queues also retained five historical failed jobs.

At 13:51 and 14:37 UTC both sites' anonymous APIs returned 13,890 local
public videos.
All twelve newest production videos resolved by their source IDs on beta,
with identical publication times and list order. The reported legacy watch
link redirected once to its canonical page, which returned HTTP 200.
The admitted beta readiness endpoint returned HTTP 200 and reported healthy.
The public apex configuration API returned HTTP 200 and identified PeerTube
8.3.1. Production was still writable when these checks ran.
