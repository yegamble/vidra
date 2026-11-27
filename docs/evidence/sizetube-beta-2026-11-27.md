# SizeTube private beta qualification, November 27, 2026

**Vidra v0.7.32 began serving public SizeTube traffic on November 27.**
The operator approved the switch after the frozen import, account and media
checks, independent restore and physical recovery-kit readback passed.
Cloudflare updated the apex at 16:35:51 UTC. PeerTube remains available
read-only for rollback through at least November 28 at 16:35:52 UTC.
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

The released importer completed its dry run and source-authoritative copy
against the frozen snapshot. By 15:54 UTC all 13,890 eligible production
video IDs matched the public beta catalogue and search index. Every eligible
video had a ready playlist or original, and all 14,956 imported publication
dates matched. The 764 retained imports excluded from the filtered source
were still blocked and suppressed in search. All 5,629 approved imported
profiles retained their public visibility.

The importer's only failed operations were 12,702 storyboard fetches. Their
source IDs matched the previously recorded set exactly, and the corresponding
seek-preview files were absent from the frozen production disk. D8 assigns
their regeneration to the post-cutover backfill. The repaired private draft
still had seven valid manifests and six media dependencies. Its two repaired
files matched the source across 28,896,084 bytes. Anonymous detail and
playlist requests returned 404 for the draft and both manually blocked videos.

Of the original 411 video blacklist decisions, 410 videos had beta records.
All 410 were blocked and excluded from search. The remaining video had no
beta record. The frozen moderation archive preserved the source reports,
mutes, blacklist decisions and suspension records. All 14 suspended source
accounts remained excluded from login and public profiles. All ten imported
MFA accounts remained held.

All 20 source remote-follow targets matched canonical Vidra channel URLs.
Thirteen accepted relationships preserved the follower, target and original
Follow activity ID. The other seven had remote actor documents the importer
could not fetch or recognize. The report defers those seven to a later run.

### Final acceptance on the production hostname

At 16:27:45 UTC Chrome completed the post-import account and media checks
through the private route for `sizetube.com`. The operator received the
reset email. The account audit recorded a redemption at 16:18:56 UTC, and
the imported user signed in with the new password, reloaded and signed out.
The owner then signed in, reloaded and opened the Overview and Infrastructure
admin pages.

Studio accepted one 309,625-byte private upload. The downloaded original
matched the fixture's SHA-256. Chrome decoded 31 frames of the new video
and played past 4.31 seconds after seeking. It decoded 46 frames of an
existing internal video and played past 12.33 seconds. All 25 media
responses across the two playbacks succeeded. The browser checks used the
refresh cookie's actual path and the session token in effect after navigation.
After the owner signed out, the private detail, original and playlist returned
404. The internal detail and admin endpoint returned 401.

### Final recovery point

The post-acceptance media inventory closed at 16:28:57 UTC. It covered
251,675 upload versions totaling 4,562,446,315,574 bytes, plus 6,836 hide
records. The recovery map assigns 251,070 uploads to exact native replicas,
584 to SHA-256-verified supplemental copies, nine to individually verified
protected copies of identical operational probe content and twelve to
62-byte hidden operational probes preserved in the encrypted map.

All 24 application versions added after the earlier recovery point were
read from the independent account. Two initialization files totaling
1,594 bytes required supplemental copies. Their complete source and
destination SHA-256 digests matched. Both copies had server-side encryption
and at least 30 days of governance retention. The temporary restricted
writer was revoked, and a new authentication attempt failed. The new
private upload restored from 15 independent immutable versions totaling
2,794,455 bytes. All hashes matched, all 18 playlist references resolved,
and playback decoded three frames after a four-second seek.

A second listing at 16:31:33 UTC found zero changes across the final media
point and the database backup. The comparison of current objects changed
since the earlier verified baseline matched 272 full objects totaling
1,144,066,594 bytes on each side. Eight previously changed names were hidden.

The database and configuration backup started at 16:29 UTC. The independent
reader fetched two immutable ciphertexts and verified both decrypted hashes
across 185,011,824 bytes. At 16:32 UTC a fresh PostgreSQL instance restored
5,658 users, 15,722 videos, 5,714 channels, 778 blocks and 13,890 eligible
search entries, with clean migration ledgers at 194 and 21. The restored
configuration decrypted all 5,654 account and 5,713 channel signing keys.
Each key matched its public identity. The new owner upload was playable and
excluded from search on the restored database.

All eleven storage-reference inventories matched the live database. The
released verifier checked all 18 changed references, including seven stored
digests and eleven HLS-listed objects, with zero errors. These checks extend
the earlier full-library verification to the final point. A fresh full scan
of the historical library was still running at 16:32 UTC.

At 16:32:18 UTC PeerTube still matched the frozen source fingerprint across
all 91 tables and 5,379,895 row versions. The original configuration, dump
and reopening procedure remained available.

At 16:34:32 UTC all 28 members of the encrypted companion reopened from
the external WD_BLACK drive. The readback checked every media binding and
hide record, restored a hidden operational probe by source ID and refused
its hidden filename. All four decrypted database and configuration files
from the pre-window and final pairs matched their hashes. The frozen
moderation archive contained all 2,250 records. The copy in Downloads
matched the external ciphertext byte for byte.

### Public switch and rollback hold

Following operator approval, the public apex ingress opened at 16:35:28
UTC. At 16:35:51 UTC Cloudflare updated the proxied apex A record. Readback
confirmed the intended origin and preserved the proxy flag, TTL and record
metadata. The first public Chrome check at 16:36:18 UTC decoded the
reported legacy video and played past 30.73 seconds after seeking, with
23 media responses and zero media errors. During propagation the same
Cloudflare location briefly served both releases.

By 16:38 UTC all eight tested legacy watch, channel, account and embed
links redirected to canonical pages returning HTTP 200. The legacy embed
retained its start time. The apex received a credentialed 204 preflight,
and the unrelated origin received no allow-origin header. The public
catalogue contained 13,890 videos. Search returned the reported video,
and its publication timestamp matched November 22 at 22:15:51.369 UTC.
Signed-out detail, original and playlist requests for the private upload
returned 404. Internal-video and admin requests returned 401.

The first post-switch database and configuration backup ran at 16:36:11
UTC. Both immutable off-site copies were retrieved and decrypted. Their
SHA-256 digests matched across 185,012,589 bytes. The next scheduled backup
is due November 28 at 03:29 UTC.

Direct checks of the incumbent after the switch returned a playable media
range, refused a write at both the HTTP and database layers, and confirmed
all 27 deferred queues stayed paused with zero active jobs. The source dump
still matched its SHA-256. Keep the incumbent intact until at least
November 28 at 16:35:52 UTC, the first scheduled post-switch off-site backup
passes verification, and any incident affecting access or data is resolved.

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
