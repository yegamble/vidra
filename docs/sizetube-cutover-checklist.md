# sizetube.com cutover — tracked checklist (living)

A working checklist for cutting `sizetube.com` over from PeerTube to the Vidra beta
(`beta.sizetube.com`). On November 25, private beta ran v0.7.31 and public
SizeTube served PeerTube 8.3.1. The [v0.7.31 acceptance results](#november-25-publication-date-acceptance-on-private-beta)
record the current deployment and the remaining production gates.
It tracks **execution status**. The reasoning, evidence and decisions
live in the audit ([`sizetube-cutover-2026-11.md`](sizetube-cutover-2026-11.md)) and the run
record ([`sizetube-beta-migration-2026-11.md`](sizetube-beta-migration-2026-11.md)). When an
item here and the audit disagree, fix one of them in the same change — do not let them drift.

Update an item's status and date in the same commit that changes the fact. Keep the IDs
(`Dx`, `finding n`, `§x.y`) so every line ties back to the audit.

**Owners:** `OPERATOR` = a live prod / droplet / DNS / provider action (I will prepare, not
run). `LAWYER` = counsel. `AGENT` = code or an in-repo artifact I can produce. `WATCHER` = a
read-only monitor (none is running today: the queue watcher stopped 2026-11-08 09:34 UTC).

**Status:** `[ ]` open · `[~]` in progress / prepared-but-not-applied · `[x]` done (dated).

**Last full status re-read: 2026-11-12 10:20–10:31 UTC, read-only.** Sources: the beta's public
API; its env file with secrets shown only as set or empty; its database in a read-only
session; the Caddy certificate directory; DNS; Backblaze bucket and key listings; prod's
public API. Nothing was changed anywhere. Evidence tags: `RUNTIME` = observed in that re-read
unless another date is given; `CODE` = read in the released source; `RECORD` = taken from the
run record or an earlier session, not observed again; `DEDUCED` = inferred. What is still not
checked is listed in section H.

**Rehearsed 2026-11-12 11:14–13:07 UTC** on a throwaway droplet built from that morning's beta
backup, with mail removed and its own secrets: window steps 1–5, the rollback, and one
read-path load check. Results are in section G and under each step in section C. The droplet,
its firewall and its temporary storage key were removed the same day; nothing on prod or the
beta was changed. `REHEARSAL` = observed in that run.

**Reviewed 2026-11-13, files only.** Two read-only reviews, one for data loss and one for
legal exposure, read this checklist against the audit and the released source. Nothing was
run against a host, a database or a bucket, so no status in sections A–H changed. What they
found is section I.

**RUNTIME 2026-11-19 19:21–19:30 UTC (partial).** Public prod reported
PeerTube 8.3.1. DNS, B2 listings and the beta edge were readable. `/healthz` returned 200;
`/version`, `/readyz` and `/api/v1/instance` returned 403. SSH timed out: no env, database
or Caddy certificate-directory read ran. The gate and all infrastructure were left as found.

### November 25 launch policy and recovery decision

**Hold public traffic on PeerTube.** The operator approved D15 on November 25.
Beta now enforces the approved signup settings. Independent recovery, authenticated
apex acceptance, and reconciliation against a frozen source remain open.

| Gate | Verified on November 25 | Work remaining |
|---|---|---|
| D15 / D6 · Visitor policies | Signed-out Chrome reached terms, privacy, DMCA and compliance on production and private beta before the age prompt. The terms matched byte for byte. Beta’s privacy page now uses the existing contact address in place of its placeholder. All four pages served the expected text on the private apex. | Keep the canonical links reachable during the switch. The incumbent PeerTube privacy page still contains the placeholder. |
| D15 / D6 · Consent | The beta API returned the canonical terms and privacy URLs and their versions. The browser confirmed the effective policy. Email verification is required, minimum age is 18, the default quota is zero, and registration is closed. The isolated release rehearsal below exercised signup, consent and activation. | Keep registration closed through rollback and verify signup before opening it. Delivery of the imported-user notice and independent legal review have no recorded evidence. |
| D5 · Imported profiles | At 15:51 UTC the public account directory contained 10,577 rows, including 5,656 local source user IDs. After backup, 5,629 exact source ID and handle matches became public on beta. Anonymous checks through the private apex returned 200 for an eligible profile and 404 for an excluded one. | Repeat the same eligibility checks for accounts created or changed by the final import. |
| D12 · Media recovery | On the private media bucket a 1 MiB synthetic object was hidden. The named read failed, the previous version was readable by ID, and unhiding restored the original bytes in 3.01 seconds. Cleanup left zero versions of the fixture. The provider reported 4,562,434,484,596 bytes across all versions. Both beta buckets had Object Lock off and no replication configured. | Recover a sample from an independently controlled media copy and restore an actual encrypted database/configuration backup on another host using an independently held key. |
| D14 · Rollback | The operator previously accepted loss of Vidra-side writes if traffic rolls back to PeerTube. Keep registrations closed, preserve PeerTube, and take the rollback backup as agreed. | Use the delegated default of at least 24 hours after the switch. Extend the window until the first post-switch off-site backup is verified and any incident affecting data or access is resolved. |
| C2–C5 · Cutover | Of 15,748 local production video rows, all 13,890 public videos matched playable, indexed beta entries. The comparison found zero extra anonymous or search-visible candidates. | At the window, verify the source write freeze and queue state, refresh the snapshot, reconcile the final authoritative import, and test authenticated workflows on the production hostname. |

The canonical visitor documents work on the current and staged services.
[Terms of service](https://sizetube.com/about/instance/home#terms) ·
[Privacy policy](https://sizetube.com/p/privacy-policy) ·
[DMCA](https://sizetube.com/p/dmca) ·
[Compliance notice](https://sizetube.com/p/compliance-notice)

**Isolated release rehearsal.** The v0.7.31 source commits ran against fresh
PostgreSQL and Redis instances. The signup policy used the canonical document URLs,
dated versions, minimum age 18 and email verification. Closed registration returned
403. With registration open in the fixture, missing consent returned 422 and created
zero accounts. A consenting signup recorded the terms, privacy and age rows and
returned 202. Login returned 403 until the confirmation sent to a loopback-only
mailbox was redeemed, then returned 200. The focused release suite also passed
21 consent-path tests.

Chrome used the hostname `sizetube.com` with its connection pinned to a loopback
TLS proxy. The released login form succeeded. The host-only, Secure, HttpOnly,
SameSite=Lax refresh cookie rotated on reload and cleared on logout. In another
fresh instance, an authenticated browser uploaded a 75,815-byte private video.
The local scanner ran with test signatures and the transcoder produced CMAF.
The owner retrieved the original with matching SHA-256 and the HLS master with
HTTP 200. Anonymous detail, original and master requests all returned 404. Separately,
14 Chromium session and ad-break tests passed with zero skips. They used simulated
ad tags and beacons. The live apex still needs authenticated acceptance and provider
reporting. The released mail transports also passed the notification-only unsubscribe
header tests with local transports.

**Live access checks.** A signed-out visitor opened the four-field contact form
from the beta About page before age confirmation. The check ended before submission.
For a bounded private rehearsal, the released API ran in HTTP-only mode with the
apex public URL and CORS origin. The matched frontend used that API for
server-side requests. Through the actual Origin CA route, the homepage returned
200, the API allowed credentials for the apex, and preflight returned 204. An
untrusted origin received no allow-origin header. An unlisted client received
403 and an admitted POST received 405. The original preview was restored after
the probes. Authenticated browser actions and ad-provider reporting remain open.

**Post-change recovery.** The 16:03 UTC database and configuration files matched
their SHA-256 digests after download from the encrypted off-site store. The
database restored into a network-isolated PostgreSQL container on beta. Both
migration ledgers were clean. The restored profile UUID set matched all 5,629
updated profiles. The six signup settings, corrected privacy page, 14,956
imported publication dates, 13,890 eligible search entries and 778 video blocks
also matched. The production recovery drill still needs an independent machine,
key custody and a media copy.

**Draft notice for the source site before the migration window.** Publication
and delivery remain open.

> SizeTube is moving from PeerTube to Vidra at the same address. We are moving
> existing accounts, channels and videos. During the migration you can continue
> watching public videos while uploads and account changes are paused. After
> sign-in reopens, use your current SizeTube credentials. If you need help with
> your password or two-factor authentication, use **Contact us** on the About
> page. You can read the [privacy policy](https://sizetube.com/p/privacy-policy)
> and [terms of service](https://sizetube.com/about/instance/home#terms) before
> signing in.

### November 24 private apex rehearsal — hold production traffic

- **D3 · Origin TLS passed.** The beta host generated its key and received a
  Cloudflare Origin CA certificate for `sizetube.com` alone, valid through
  2027-11-24. Caddy's private apex route admits the beta operator IPs and
  permits GET and HEAD. With the connection directed to beta and the
  Cloudflare origin root trusted, the homepage, `/version` and `/readyz`
  returned 200. An unlisted client received 403 on `/healthz` and an admitted
  OPTIONS request received 405. Normal public DNS still served PeerTube 8.3.1.
  The shared beta frontend, core public URL and CORS still point to beta. The window
  must replace the private apex block when applying the production config.
  Preserve the operator's pre-reload Caddyfile for rollback and arrange
  certificate recovery for a replacement host. The config archive contains
  the Caddyfile and env. The origin key lives in Caddy's data volume.
- **C5 · Browser playback depends on the frontend API origin.** On v0.7.29,
  Chrome followed a public PeerTube watch link on beta, confirmed the age
  prompt, decoded video and sought to 33.9 seconds. The same link on the
  staged apex returned a page and set the age cookie, but the browser called
  the beta API. CORS blocked the requests and the player stayed at zero.
  A loopback-only copy of the same frontend and proxy used
  `PUBLIC_API_BASE_URL=https://sizetube.com` and
  `PUBLIC_BASE_URL=https://sizetube.com`, with beta's CSP settings. The
  browser then decoded 51 frames and sought to 33.9 seconds. The media CDN
  returned HTTP 206. At the window, set `NEXT_PUBLIC_API_BASE_URL` in the
  Compose env, apply the site URL and CORS settings, then repeat this check
  on the production route. The private apex now has its own frontend using the
  released v0.7.29 image and the tested settings. Chrome repeated the 51-frame
  decode and 33.9-second seek on that route. Beta still served its own API
  origin. A separate address received 403 on the private apex and an admitted
  OPTIONS request received 405. The operator's current browser reached beta's
  age prompt after its exact address was added to the beta website gate.
  Recheck or replace the preview frontend when changing the release. The
  rehearsal covered anonymous reads. Authenticated writes and ads still
  need verification.
- **C2/C4 · The configured source is newer than the last import.** The active
  source database contained local video updates through Nov 22 at 18:29 UTC.
  All 91 public local UUIDs listed on production since Nov 15 at 18:42 UTC
  were in that snapshot. None had a completed beta video mapping. The last
  successful copy finished Nov 17. All 17 runs were non-authoritative.
  Of 14,956 local source videos and 15,622 mapped beta videos, 14,858 UUIDs
  matched. The 98 source-only rows included 90 public published videos, two
  public state-2 videos and six private published videos. A network-isolated
  copy of the released worker ran a source-authoritative dry run in 191 seconds
  and applied metadata changes in 236 seconds with media copying disabled.
  It mapped all 98 videos, updated 44 existing videos and imported 55 users.
  The 98 new mappings had no ready HLS on the copy.
- **C4 · Source media changed after the snapshot.** Of 96 master filenames in
  the Nov 22 snapshot for those 98 videos, only three existed at the recorded
  paths in source storage. A directory check found a complete HLS tree for each
  of the 96 videos, covering 580 playlists and 484 nonempty media objects.
  Live PeerTube's database referenced those 96 verified masters and also
  recorded a master for the two videos that had none in the snapshot. Refresh
  the filtered snapshot before copying media. Verify the exact master names
  and dependencies again after the production write freeze.
- **D16 · Production queue inventory at 14:56 UTC.** Across the 16 monitored
  queues there were 41 outstanding jobs, all transcoding-job-builder parents
  waiting for child records that Redis no longer held. Of their 41 video UUIDs,
  28 were published and 13 were absent from production. One separate eligible
  video remained in state 2. It was private with one HLS playlist and six
  recorded HLS files. Record its disposition and repeat the queue and state
  checks at freeze.
- **D5/D7 · Recount.** All 683 private, published imports lacking both a ready
  HLS playlist and an original already had video blocks. The broader prepared
  D7 predicate matched zero unblocked rows. Repeat the count after the final
  import. There were 5,600 private import-owned profiles, 685 failed HLS ledger
  entries and two failed video entries. Of the 685 failed HLS entries, 683
  were absent from the active source and blocked on beta. The remaining two
  were beta drafts in source states 7 and 8.
- **D7 · Two visibility mismatches blocked on beta.** Of 764
  mapped beta videos absent from the active local source, 763 had a video
  block. The remaining one returned 200 with an HLS URL to an anonymous beta
  API request and 404 from production. A second UUID present on both sides
  was private in the source and unblocked and public on beta. Its anonymous
  API responses were 200 with an HLS URL on beta and 401 on production. The
  metadata rehearsal corrected the second video's privacy and left the first
  one public. With operator approval, both received reversible beta video
  blocks, audit records and search suppression events. The anonymous detail
  and HLS endpoints then returned 404 for each. Repeat the comparison on the
  frozen source before opening traffic.
- **D12/D14 · Off-site database restore passed.** Both files from the Nov 24
  03:26 UTC backup matched their local copies byte for byte after retrieval
  from the encrypted remote. A separate, network-isolated PostgreSQL container
  on beta, using the running database image, restored the dump in 76 seconds.
  Core ledger 191 and search ledger 21 were clean. The restored database had
  5,603 users, 15,622 videos, 776 video blocks and one user ban. The temporary
  database was removed. A fresh restore of the same dump found all 74,275
  distinct top-level object keys in 326 seconds. A separate strict sample
  covered nine imported videos across public, unlisted, internal and private
  visibility. All nine HLS trees were complete. All 124 objects were present
  and all 28 recorded hashes matched, including one original. The sample took
  30 seconds. The final dump still needs full hash and deep HLS verification,
  separate-host recovery and retention through the rollback window.
- **D4/D15 · Account and visitor checks.** The named owner account has no
  completed PeerTube user ledger entry. The imported-account reset test still
  needs a controlled imported mailbox. The browser age setting was 18,
  anonymous sensitive access was open, registration was closed, both policy
  URL settings were empty and the consent table had zero rows.

### November 24 v0.7.30 private beta verification

- **Release and browser access.** The three published images passed release
  preflight. The recovery drill upgraded from v0.7.29, rolled back and
  restored the media fingerprint. The sealed-secret recovery drill passed
  on a replacement host. The guarded beta deployment completed and the
  private apex frontend uses the new frontend image. Chrome reached the
  age prompt from the operator's connection. A separate connection received
  403 on the beta homepage. [Release record and checks](https://github.com/yegamble/vidra/pull/440)
- **C5 · Legacy browser links.** On both beta and the privately routed apex,
  Chrome followed `/c/{handle}/videos`, `/channels/{handle}/videos` and
  `/video-channels/{handle}` to the canonical channel page. A private
  imported account's legacy profile returned 404. Beta had zero active
  public profiles to exercise the positive account case. From a legacy
  watch link, clicking Play decoded frames and seeking to 23 seconds passed
  on both hosts. The temporary apex admission was revoked and returned 403
  on retest. Public SizeTube continued serving PeerTube 8.3.1.
- **D4 · Imported-account reset passed.** Beta and the source had the same
  mailbox for the operator's active, import-owned account. One request
  returned HTTP 202. The mailbox owner completed the reset, and the beta
  token record showed that exact request redeemed before expiry at 15:17 UTC.
  At 15:37 UTC the source-authoritative import resynced the same account.
  That operation writes the source password hash, so the production
  credential superseded the beta-only reset. A reset intended to carry
  into production belongs after the final source-authoritative import.
- **C2/C4 · Source and media rehearsal.** The filtered source refresh
  retained the previous snapshot and selected 14,956 local videos on schema
  1130 after excluding 792 videos belonging to suspended owners. All 98
  previously missing videos had their recorded master in source storage.
  Walking 591 manifests found 493 nonempty media dependencies and zero
  unresolved references at measurement time. The public source API
  advertised the same masters for all 92 public videos. The released
  importer's read-only plan completed in 54 seconds. Seven granular
  sensitive-content preferences map to hide, and 33 remote watch-history
  entries cannot be represented locally. A disconnected two-video copy
  staged 25,304,536 bytes, published both playlists, matched all nine
  referenced media hashes and decoded three frames of each video.
- **Signing keys and backup.** The restored beta database had 5,599 account
  and 5,657 channel signing keys stored as raw PEM. With operator approval,
  the release's encryption implementation sealed them first on the restored
  copy and then in one live transaction. Independent decryption with the key
  recovered from encrypted off-site storage reproduced every original private
  key and public identity. The running API uses that key with federation
  disabled. Both files of the 15:35:56 UTC post-sealing backup matched their
  retained copies after retrieval from the encrypted remote. Earlier backup
  contents and the source snapshot retain their original key representation.
- **D15 · Operator decision.** The operator confirmed the launch-policy
  review is pending. Keep production traffic on PeerTube while this decision
  and the frozen-source and recovery checks are open.

### November 24 private beta import

The v0.7.30 source-authoritative import ran from 15:37 to 16:08 UTC against
the refreshed, filtered PeerTube snapshot. It added 55 users, 56 channels and
98 videos, updated 44 videos and reconciled 29,829 existing playlist items.
Beta finished with 5,658 users, 15,720 videos, 778 video blocks and one user
ban. The post-import database and configuration backup completed at 16:09 UTC.
After the playback repair and search reconciliation, both files from the
16:13 UTC backup were retrieved from the encrypted off-site remote. Both
SHA-256 digests matched their on-host copies.

- **Privacy.** All 14,956 source video UUIDs had a beta mapping with the
  expected visibility. All 764 mapped videos absent from the filtered source
  were blocked. Both previously exposed records returned 404 on the detail
  and HLS master routes and were suppressed in search. The unpublished
  private source video remained a private draft and returned 404 on both routes.
- **Playback.** A single-video retry recovered the one new public video
  whose initial media transfer failed. Across the 98 additions, all 591
  playback manifests and 493 media dependencies resolved in source and
  destination. All dependency sizes matched, totalling 16,027,464,789
  media bytes. There were 279 matching single-part ETags and nine independent
  SHA-256 comparisons. Chrome decoded 97 frames of the retried video before
  seeking to 23 seconds. Every unblocked, published imported video had a
  ready HLS playlist or an original file.
- **Private draft exception.** A separate, older draft had a playlist and a
  media file on the PeerTube host that were absent from its source bucket.
  Together they measured 28,896,084 bytes. At this check its beta draft still
  needed both objects.
- **Search.** After the standalone import, the 92 public additions were
  absent from the search index. The released API's startup reconciliation
  indexed all 92. All six private additions stayed out of the index, and the
  outbox had zero pending or dead events. The anonymous search API returned
  the retried public video with both service-specific paging fields.
- **Preview images.** The importer reported 12,702 source-missing seek
  previews. Regeneration is enabled through the release default. D8 assigns
  the remaining preview generation to the post-cutover backfill.
- **Release identity.** The running core, frontend and search containers
  matched all three release index digests, Linux/amd64 manifest digests and
  source revisions.
- **Signing keys.** Independent decryption against the running deployment
  succeeded for all 5,654 account and 5,713 channel signing keys, including
  the newly imported keys. Zero rows contained plaintext key material.

### November 25 private draft and recovery checks

- **Browser access.** The operator's browser egress changed. Replacing its old
  single-address entry in the beta gate restored access. A fresh Chrome session
  confirmed the new address and reached the age prompt. The homepage and
  readiness endpoint returned 200. A separate connection received 403 on beta
  and the public apex continued serving PeerTube 8.3.1.
- **Private draft repair passed.** The released importer recovered the older
  private draft's HLS playlist on November 24 at 16:35 UTC. An independent
  readback matched both repaired files to their source SHA-256 digests
  (28,896,084 bytes). All seven manifests and six media objects resolved.
  FFmpeg decoded three frames of the repaired video file. Anonymous detail
  and HLS master requests both returned 404, search had zero eligible
  documents for the draft, and the media bucket had zero public grants. The
  verified temporary fallback copies were removed.
- **Backup coverage.** The 16:13 UTC November 24 backup predates the repair.
  The 03:21 UTC November 25 database and configuration backups matched their
  on-host digests after retrieval from the encrypted off-site remote. The
  database restored into an isolated PostgreSQL instance on beta with clean
  core and search ledgers (191 and 21). It contained the private draft with
  its playlist ready. Across the two restored databases, the only addition
  to the media verifier's reference inputs was this draft's HLS tree. There
  were no removals.
- **Full-library check and retry.** The November 24 restore finished its
  integrity check at 06:57 UTC on November 25. The verifier checked 240,796
  objects across 14,990 HLS trees and matched all 45,179 recorded checksums.
  It reported zero missing objects, zero checksum mismatches and one playlist
  read error. That tree was incomplete and the command exited 3. Two later
  reads of the 24,264-byte manifest from beta matched the production source
  byte for byte. A focused run of the same released verifier on the November
  25 restore checked that entire tree and the repaired draft. It found all
  32 objects, matched four recorded hashes and exited 0. Comparing the two
  terminal reports accounted for every incomplete tree in the first run.
  Across both runs all 14,991 HLS trees in the newer backup were covered.
  The separate-host recovery drill remains open at the operator's request.
- **Public catalogue and dates.** All 13,890 videos in the live PeerTube
  public listing mapped to unblocked, published public beta records. Each
  had a ready HLS playlist or an original and was eligible for search.
  On v0.7.30 the watch page and channel cards use the creation timestamp.
  For 10,966 of the 13,890 matched public videos the PeerTube publication
  date falls on a different UTC calendar day. The operator requires watch
  pages and newest-first listings to preserve publication dates before cutover.

### November 25 publication-date acceptance on private beta

**Private beta passed the publication-date rehearsal. Hold public traffic on PeerTube.**
The deployed core, frontend and search image digests and revisions matched v0.7.31.
The release passed the published-image upgrade and rollback drill, synthetic
sealed-secret recovery on a replacement runner, and 1,140 Linux tests.
[Release record and checks](https://github.com/yegamble/vidra/pull/448)

- **Dates and discovery.** All 14,956 eligible source UUIDs in the saved snapshot
  matched completed video mappings. One transaction set their PeerTube publication
  timestamps. It checked every other video field before committing. All 14,956
  dates matched afterward, with zero dates written outside that set. After search
  reconciliation, all 13,890 eligible documents had the expected date and the
  search outbox had zero pending or dead events.
- **Viewer checks.** Chrome followed the reported legacy link, displayed the
  November 22 publication age, and found the video in both the recent feed and
  its channel's newest-first listing. Its creation timestamp remained August 30.
  The private apex, using its Origin CA certificate, redirected the same link
  within `sizetube.com` and served the correct date. An outside connection
  received 403 on beta. Public DNS still served PeerTube.
- **Media and recovery.** On the deployed release the repaired private draft
  matched both saved source hashes, resolved seven playlists and six media
  objects, and decoded three frames. Anonymous detail and playlist requests
  returned 404. The 08:06 UTC pre-deploy and 08:23 UTC post-backfill database
  and configuration backups each matched their encrypted off-site copies.
  The post-backfill database restored into an isolated PostgreSQL instance on
  beta with clean ledgers 193 and 21, all 14,956 corrected timestamps, 13,890
  eligible search documents and all 778 video blocks.
- **Capacity.** The tested core source tree matched the merged release source.
  At 2,192 synthetic origin API requests per minute for ten minutes, all
  21,920 requests succeeded. Aggregate p95 was 109 ms and search p95 was
  399 ms. With the beta limit enabled, a one-minute 6,213-request burst from
  one address produced 300 successes and 5,913 HTTP 429 responses. The
  production-sized test droplet was deleted. See the
  [workload and route coverage](#november-25-api-capacity-rehearsal-on-v0730).
- **Before public traffic.** The operator subsequently approved D15. The
  [November 25 launch decision](#november-25-launch-policy-and-recovery-decision)
  records the settings, remaining recovery checks and rollback window.
  The cutover window also requires a source write freeze, fresh queue and
  visibility reconciliation, and real-host acceptance of authenticated
  workflows, cookies, uploads and ad delivery. Recheck newly imported profiles
  against the D5 criteria after the final import.

### November 22 go-live decision

**Hold production DNS.** The operator's browser reached SizeTube's 18+ prompt on beta.
The homepage returned 200 with `noindex`, an unlisted source received 403, and `/readyz`
reported healthy. The three running image digests match the [v0.7.24 release record](../releases/v0.7.24.json).

| Gate | Evidence on November 22 | Remaining action |
|---|---|---|
| D3 · Production hostname | A direct TLS connection to the beta origin with SNI `sizetube.com` failed. Caddy's Origin CA directory contains only the CDN certificate pair. Public URL, frontend API URL and CORS still use beta. | Stage the apex-only certificate and key. Verify the real hostname at the beta origin before switching Cloudflare. |
| C2/C4 · Final import | Beta has 5,603 users and 15,622 videos. The snapshot has 15,622 local videos. The last copy run finished Nov 17 at 16:13 UTC. All 17 runs used `source_authoritative=false`. Production reported 5,655 users. Its newest-first public local listing crossed the Nov 15 refresh cutoff and contained 90 videos created since. A UUID lookup found zero of those 90 on beta. | At the window, drain the production queue, verify the write freeze, take a fresh snapshot, switch the target hostname and run the authoritative dry run and copy. Reconcile moderation, privacy, deletes, followers and media failures against the frozen source. |
| D5/D7 · Profiles and media | Read-only counts found 5,600 import-owned, non-deleted private profiles and 289 unblocked, private, published imports without a ready HLS playlist or original. The ledger has 685 failed HLS entries and two failed video entries. | Recount after the final import and approve the exact affected rows. For each remaining media failure, confirm a source exception or recover it. |
| D15/D6 · Visitor and signup policy | The browser asks visitors to declare they are 18. Anonymous sensitive access is `open`, terms and privacy URLs are empty, and the consent table has zero rows. Registration is closed and email verification is off. | Resolve the D15 intake with counsel, publish the policies, and settle the imported-user notice, non-user reporting, ad consent, and signup timing during rollback. |
| D4/C5 · Account and link acceptance | Resend is configured. One imported account has a redeemed reset token. The token row does not identify the delivery channel. A sampled legacy watch URL redirected to HTTP 200. The corresponding legacy channel and account URLs returned 404. | Test reset delivery and redemption together on a controlled imported account. Verify redirects, playback, upload, search, and cookie/CORS behavior on the real hostname. |
| D12/D14 · Recovery | The Nov 22 backup job uploaded the database and configuration through the encrypted off-site remote and exited successfully at 03:25 UTC. Media GC is off. The backup heartbeat is unset. Both beta B2 buckets have Object Lock off and no replication. | Run the strict restore on a copy, retain the rollback dumps outside pruning, confirm recovery-key custody and decide the rollback duration and acceptable write loss. Record independent media recovery or the operator's acceptance of that risk. |

The latest production queue depth, real-mail delivery, ad-provider reporting, and a restore
of the current backup still need independent evidence. The rehearsal results in section G
remain the baseline for the window.

---

## A. Launch policy

- [x] **D15 · Operator approval received November 25.** The current
  [launch policy and recovery decision](#november-25-launch-policy-and-recovery-decision)
  records verification and outstanding implementation. The dated intake below
  describes conditions at the time of each review.

- **November 8 compliance intake (five questions) — `LAWYER`.** Two blockers identified at the time:
  (a) NSFW catalogue plays for anonymous visitors with no age assurance (12,401 of 15,508
  videos `is_sensitive`; only `hide` is server-enforced); (b) signup records no terms/privacy
  consent (`INSTANCE_TERMS_URL` / `INSTANCE_PRIVACY_URL` empty). Plus HIGH: GDPR Art 13/14
  notice to 5,538 imported users, missing `List-Unsubscribe`, no non-user abuse/DMCA path.
  See audit §8. *Blocks the whole window.*
  **Still open 2026-11-12.** No answer is recorded. On the beta `terms_url` and `privacy_url`
  are empty, `sensitive_content_policy=display`, `registration_minimum_age=0`; the counts are
  unchanged at 12,401 of 15,508 (RUNTIME).
  **RUNTIME 2026-11-19 — open; unverified on the beta:** none of the settings below could be
  re-read (the beta's API and database were not reachable). No counsel answer is recorded in
  either file. Last observed 2026-11-15 (RUNTIME that day, below): the age gate on at 18,
  `terms_url` and `privacy_url` empty, registration closed. The counts above are from
  2026-11-12; the catalogue has grown since (15,613 videos on 2026-11-15, audit §6) and the
  sensitive share was not re-counted. Prod, where that catalogue is public today, still has
  signup open, minimum age 18, no e-mail verification, `isNSFW=true` and default policy
  `display` (RUNTIME 2026-11-19, public API). Of the five intake questions only the first,
  how the catalogue is classified, is counsel's; the other four ask the operator for facts
  and choices (audit §8: the entity and contact, EU and UK traffic, notice and mail to
  imported users, the anonymous policy). No answer to those is recorded either, beyond the
  contact e-mail and the age-gate answer below.
  Code needed whichever way counsel answers — **built, released in v0.7.20 and deployed to
  the beta 2026-11-12 18:06 UTC; both pieces are switched off there.** On the beta (RUNTIME):
  migration `0189` applied in 76 ms, `user_consents` exists and is empty, `terms_url`,
  `privacy_url` and both version labels are empty, `sensitive_anonymous_access` reads `open`,
  an anonymous read of a sensitive public video still answers 200 and no list card carries
  `sign_in_required`. **Neither the signup refusal nor the sign-in wall has been exercised on
  the beta**: registration is closed there and the wall is off, so both rest on their PRs'
  tests (CODE). What exists (engineering guidance, not legal advice):
  - *Signup consent record* (core #545–#549, user #470). Migration `0189` adds `user_consents`
    (document `terms` / `privacy` / `age`, the operator's version label, URL, source,
    accepted-at; append-only by trigger; removed with the account). While `terms_url` or
    `privacy_url` is set, `POST /auth/register` without `terms_accepted` is a 422 and no
    account is created; the approval queue keeps the applicant's acceptance and its time; a
    first sign-in through OIDC or ATProto without it returns `oauth_error=terms_required`;
    an existing account is never asked. The record is in the account export. New settings
    `terms_version` / `privacy_version` (Admin → General → About). **Does nothing until the
    two URLs are set**, which is still the case on the beta. Not built: asking the existing
    5,541 accounts to accept on their next sign-in (the `reaccept` source exists for it).
    Also found: a provider signup is not asked for the age attestation the form requires.
    Fixed 2026-11-14, released in v0.7.21 and deployed to the beta the same day (I7).
  - *Sign-in wall for sensitive videos* (core #550, #551, user #471). Setting
    `sensitive_anonymous_access`: `open` (default, today's behaviour) or `sign_in` (Admin →
    General → Moderation). With `sign_in`, every read of a sensitive video by a visitor
    without an account answers 401 `sign_in_required` (detail, embed policy, captions,
    chapters, downloads, poster, storyboard, HLS, original), its bytes are no longer sent to
    the CDN, RSS / podcast / sitemap / oEmbed leave it out, and a listed card carries
    `sign_in_required` and no poster. Switching it on is refused while CDN delivery is on
    with no purge endpoint; with one, the response says to purge the CDN zone. **Shipped
    `open`.** A sign-in wall, not age verification. Not covered: the IPFS mirror (a gated
    video's CIDs stay on a public gateway), and playlist item cards.
  - *Age gate for visitors* (core #553 `0c06a81f`, user #473 `0d8b5105`; **released in v0.7.21
    and deployed to the beta 2026-11-14 17:03 UTC, switched off there**). Setting
    `age_gate_enabled` (Admin → General → Moderation), off by default and effective only while
    `registration_minimum_age` is above 0; the admin settings refuse it on without an age.
    With it on, a visitor without an account is asked "I am N or older" instead of any page or
    embed; sign-in, sign-up and the about page stay open, and a signed-in account passes. The
    operator's custom script (the ad script), ads and analytics are left out of a page until
    the visitor confirms. A 30-day cookie holds the confirmed age, so raising the age asks
    again. It is **self-declared and enforced in the browser**: it refuses no API or media
    request, so it is not the age verification D15(a) asks about. It is one answer to
    "Anonymous-NSFW policy" in section B, if counsel finds self-declaration enough. On a local
    dev server against a stub API (2026-11-14), nothing from the custom script was requested
    before the visitor confirmed. It has not been switched on on the beta: after the deploy
    `age_gate_enabled=false` and `registration_minimum_age=0` (RUNTIME 2026-11-14).
    **Switched on on the beta 2026-11-15, 14:22 UTC, by the operator** (RUNTIME, read-only
    the same day): `age_gate_enabled=true`, `registration_minimum_age=18`. The operator's
    answer to D15(a), in their words: "we already have age assurance, it asks age or
    blocks". That is the operator's decision to rely on self-declaration; no counsel answer
    is recorded, and the limits above still hold (browser-enforced, refuses no API or media
    request). Not checked in a browser on the beta. D15(b) is unchanged: `terms_url` and
    `privacy_url` are not set, so a signup would record no consent; registration is closed
    there, so nobody can sign up today. The box stays open.
  The scoping notes of 2026-11-11 that this replaced:
  - *Signup consent record.* The only consent field signup sends is `age_attestation`, which
    the api checks and does not store (CODE core `e6d83aa4`
    `internal/httpapi/auth.go:100-103,358`; user `ef1cb9c6`
    `components/auth/SignupForm.tsx:133`). Needs an additive migration for a
    consent record, `terms_accepted` on every registration path, the record in the account
    export, and an unticked checkbox with live links. One core PR, one user PR, one release.
  - *Anonymous gate for sensitive videos.* Only `hide` is enforced, and only on browse,
    search, RSS and the sitemap; a direct watch page is never filtered and `warn` / `blur` are
    browser-only (CODE `internal/httpapi/instance.go:699-706`). Needs a separate anonymous
    policy enforced where `internal` privacy is (`videos.go:1866-1890`), with gated videos off
    the publicly cached CDN path. Larger than the consent record. Switched on, it makes 12,401
    of 15,508 videos sign-in-only for visitors. The age-verification vendor, per-region
    routing and wording wait for counsel.

## B. Gates before the window (§5 step 0)

- [x] **D12 · `MEDIA_GC_ENABLED=false`** — applied 2026-11-08 02:55 UTC, kept off through the
  rollback window. `OPERATOR`. Still `false` in the env file and in the running api container
  (RUNTIME 2026-11-12).
- [x] **10.5 · Post-import restore drill + `verify-blobs`** — PASS 2026-11-08 03:34 UTC
  (RTO ≈ 45 s DB / ≈ 5 min with blob check). `OPERATOR`. *Re-drill on the final pre-cutover
  dump before T0 — see F.*
- [x] **D16 · Prod transcode backlog drains, then move + publish the state-8 pair**
  (`6f2fdd7e`, `892d1947`) — done 2026-11-09: queue read empty at 06:03 UTC; the pair moved
  to object storage 06:13–06:17 UTC, both state 1 with 0 local files and 8 in the bucket
  (RECORD). `OPERATOR`. **Not re-read since:** the watcher stopped 2026-11-08 09:34 UTC and
  uploads after 2026-11-09 may have refilled the queue. Read it again before the freeze
  (needs prod SSH — section H).
  On November 25, 31 source queue definitions were read. The transcode and
  move queues had zero runnable or active jobs. All 41 waiting transcoding
  parents referenced missing children. Their video UUIDs resolved to 28
  published videos and 13 absent ones. Repeat at freeze.
- [x] **D4 · Private-beta mail and imported-account reset.** The operator
  completed the reset and beta recorded redemption on November 24. The
  following source-authoritative import restored the production password hash.
  Recheck mail and credentials on the real hostname during the window.
  [Imported-account verification](#november-24-v0730-private-beta-verification)
- [~] **Finding 10 · White-label on.** `branding_hide_software_name=true` since 2026-11-11
  14:28 UTC (RUNTIME). **Open:** the imagery — avatar, banner, favicon, both header logos and
  OpenGraph are all still the fallback, and no instance image is stored (RUNTIME). Set them in
  Admin → General → Branding. Survives deploys and the flip. `OPERATOR`.
  **RUNTIME 2026-11-19 — unverified** (the instance document is behind the gate and the database was
  not reachable); last observed 2026-11-12.
- [x] **D5 · Imported profile visibility applied to the November 25 beta catalogue.**
  The reviewed transaction changed exactly 5,629 flags. It excluded 24 inactive,
  deleted or banned accounts, one unlisted or privileged account, and one
  account with beta activity. It verified every other visibility flag after the
  update. See the [restore and acceptance record](#november-25-launch-policy-and-recovery-decision).
- [~] **D7 · Block the remaining 289 media-less published videos** via `video_blocks` (394 of
  683 already blocked; all one inactive owner, all private). SQL prepared, **not applied** —
  the dry-run still counts 289 of 683 (RUNTIME 2026-11-12). `OPERATOR`.
  **RUNTIME 2026-11-19 — unverified** (DB unreachable). The 2026-11-14 catch-up run added 105
  videos (audit §6), so run the dry run again, and confirm the rows are still that one
  owner's, before applying.
- [~] **D6 · New-signup policy applied:** registration open with e-mail verification,
  `registration_minimum_age=18`, terms/privacy acceptance first, `INSTANCE_DEFAULT_QUOTA_BYTES=0`.
  **Nothing applied** (RUNTIME 2026-11-12): registration off, e-mail verification off,
  minimum age 0, quota `5368709120`. The acceptance step needs code — the consent record under
  D15. `OPERATOR` + `AGENT`.
  **RUNTIME 2026-11-19 — unverified** (env and DB unreachable). On 2026-11-15 the minimum
  age was 18, registration was closed and both policy URLs were empty (section A); consent
  code shipped in v0.7.20. Verification and quota were last read on 2026-11-12.
  November 25: the six settings are applied and verified on beta. D14 keeps
  signup closed until the rollback window ends and signup acceptance passes.
- [~] **Anonymous-NSFW policy decided + applied** (`display` vs `hide`/`warn`/`blur` + login)
  pending D15. Still `display`, last set 2026-11-06 (RUNTIME 2026-11-12). `OPERATOR`.
  **RUNTIME 2026-11-19 — unverified** (settings unreachable). On 2026-11-15 the browser
  gate was set to 18. That was the operator’s answer, not verification of age on API or
  media requests, a browser acceptance test, or counsel’s answer to D15(a).
- [~] **Instance metadata set.** Contact e-mail set in Admin → General on 2026-11-09 and
  served by the instance (RUNTIME). **Open:** terms and privacy URLs, both empty (RUNTIME
  2026-11-12); they wait for counsel's texts. `OPERATOR`.
  **RUNTIME 2026-11-19 — unverified** (instance API and DB unreachable); both URLs were still empty on 2026-11-15 (RUNTIME that day,
  section A).
- [x] **D13 · Record the proven imported-account login** (account + date) in the private log.
  Done 2026-11-12 12:17 UTC: the operator named an imported moderator account and signed in
  with its existing PeerTube password on the first attempt, typing it into a browser pointed
  at the rehearsal copy (REHEARSAL; account and time are in the private log). The copy was
  restored from the beta's 2026-11-12 03:26 UTC backup and ran the same release, so the
  password hash and the code are the beta's. It was not repeated on the beta itself.
  `OPERATOR`.
- [~] **D3 prerequisite · Origin CA cert for `sizetube.com`** on the droplet and
  `VIDRA_SKIP_DNS_PREFLIGHT=1` in the env file (Cloudflare-proxied path). The
  certificate and private origin test passed Nov 24. The preflight flag remains
  unset for the current beta hostname. **Neither was there**
  (RUNTIME 2026-11-12): the certificate directory holds only the `cdn-beta` pair, the key is
  absent from the env file, and the origin refuses a TLS handshake for `sizetube.com`.
  `OPERATOR`.
  **2026-11-19:** from outside, the origin still serves no certificate for `sizetube.com` or
  `www.sizetube.com` (TLS alert on the handshake). It serves the Let's Encrypt certificate
  for `beta.` (that name only, to 2027-02-02) and the Origin CA certificate for `cdn-beta.`
  (that name only), and `sizetube.com` still resolves to Cloudflare (RUNTIME 2026-11-19). The
  certificate directory and the env key are **unverified 2026-11-19** (not reachable): a
  certificate placed there but not yet named in the Caddy file would not show from outside.
  **When issuing it, name `sizetube.com` only** (REHEARSAL 2026-11-12). Cloudflare's form
  pre-fills `*.sizetube.com` as well. With a wildcard certificate loaded, Caddy logged
  "skipping automatic certificate management because one or more matching certificates are
  already loaded" for `beta.sizetube.com` and served the loaded certificate on that name. On
  the beta that would replace the Let's Encrypt certificate on the DNS-only `beta.` redirect
  with one browsers do not trust. The existing `cdn-beta` certificate is single-name (RUNTIME).
- [x] **Read-path capacity — found 2026-11-12; fixed in v0.7.20, deployed and re-measured the
  same day.** `AGENT`. What follows is the finding, then the fix, then the re-measurement.
  Three anonymous endpoints took
  about a second each with nobody else on the box, and a repeat call cost the same:
  `GET /api/v1/videos?sort=trending` 1.1–1.2 s, `GET /api/v1/videos/search` 0.5–0.7 s,
  `GET /api/v1/recommendations/home` 0.5–0.7 s (RUNTIME 2026-11-12, the beta itself, one
  request at a time; every other path a page uses answers in 0.1 s or less). Under load the
  database is what runs out (section G). Either make those three cheaper (`AGENT`, then a
  release) or accept the measured ceiling for the window (`OPERATOR`). Prod's real peak is
  still unknown (section H), so how close that ceiling is cannot be said.
  Operator decision 2026-11-12: a plan to make the three cheaper first; no code before the
  plan is approved.
  **Explained and fixed in code, 2026-11-12** (plan approved the same day). Read-only
  `EXPLAIN (ANALYZE, BUFFERS)` on the beta (RUNTIME): the list built all 13,776 public rows to
  keep 20 and counted them again in a second statement (246 ms); 10,702 of the 13,792 public
  rows are sensitive and each called a policy function the planner cannot inline (about 190 ms
  per statement); trending used numeric `power()` (about 350 ms; the home rail's 426 ms is the
  same expression in vidra-search); JIT compiled each statement (74–94 ms). v0.7.20 changes:
  statements for the anonymous unfiltered feed (core #542), the per-row costs (#539, search
  #103), a 15-second shared cache for anonymous lists, search totals and the home rail, with
  publish, edit, delete and block effective at once (#540, #543, #544), and `jit=off` for the
  bundled Postgres (meta #379; the first deploy that carries it restarts Postgres once).
  The new statements on the beta's data, by EXPLAIN only (RUNTIME): recent page 5 ms (was
  467), trending 56 ms (was 807), the total 15 ms (was 246), search total 56 ms with JIT off
  (was 334). On a 15,000-video fixture (Apple M2, PostgreSQL 18.6, each call = list + total):
  trending 932.7 → 70.2 ms with JIT on and 378.3 → 27.7 ms with it off; a cached call is under
  0.02 ms.
  **Re-measured on the beta after the deploy** (RUNTIME 2026-11-12 18:07–18:11 UTC, the api's
  loopback, one request at a time, each round 16 s after the last so the cache had expired;
  v0.7.19 timed the same way an hour earlier in brackets): trending 60–108 ms, 4–10 ms when
  repeated [0.92–1.83 s]; recent 26–39 ms [0.55–1.26 s]; search 170–214 ms, 85–122 ms when
  repeated [0.40–0.47 s]; home rail 92–135 ms, the same when repeated [0.42–0.48 s]. The
  plan's target of 150 ms for a first call is met by the list and the home rail and **missed
  by search**: each search asks vidra-search for its page (85–120 ms, not cached) and only the
  total is cached. The home rail's cache does nothing on this instance: it is shared only
  when `search_mode` is `simple`, and the beta's is `advanced` (ranked per session).
  **Under load:** the rerun in section G passes at 270 page views a minute for 10 minutes.
  Still true: the cache is per process (a second api container would need shared
  invalidation); signed-in callers and filtered lists run the general statement.
- [x] **This checklist + the audit merged to `main`** — #369, 2026-11-10. `AGENT`.
- [~] **Ads parity.** Prod earns from HilltopAds + ExoClick through a PeerTube custom script,
  a PHP anti-adblock file and the `vast-ads` plugin (still registered on prod, RUNTIME
  2026-11-12); none of it carries over by itself. Two tracks.
  **Display and popunder** (HilltopAds, ExoClick banners). Done: the vidra-core ad proxy
  (core #530, #531, #536) and the frontend policy switches `CSP_ALLOW_EVAL` / `CSP_FRAME_SRC`
  / `CSP_ALLOW_INLINE_EVENT_HANDLERS` (vidra-user #465, passthrough #371), all in v0.7.17 and
  applied on the beta 2026-11-10; the ported custom script installed in Admin → Advanced →
  Custom JavaScript on 2026-11-10 17:47 UTC. Confirmed 2026-11-12 (RUNTIME): the installed
  script's SHA-256 equals the prepared `cutover-prep/ads-custom.js` less its final newline;
  the provider path returns JavaScript through Caddy; the enforced page policy carries all
  three allowances. **Open:** real ad fill and a real blocker on the six formats.
  2026-11-15: the operator reports ads on the beta, in their words: "ads are showing".
  Not read back by anyone else, and it does not say which of the six formats, or how the
  page behaves with a blocker on.
  **In-player VAST** (replaces the `vast-ads` plugin). Done: core #537 and vidra-user #466 in
  v0.7.18, the progress-beacon fix vidra-user #467 in v0.7.19; pre-roll, mid-roll and
  post-roll tags are set and enabled on the beta (RUNTIME 2026-11-12). Checked on the beta
  2026-11-11 (RECORD, that day's session): pre-roll, skip, mid-roll at 300 s repeating every
  60 s, post-roll, embed on and off, cooldown; one filled pre-roll sent its five ExoClick view
  beacons once each, HTTP 200. **Open:** mid-roll and post-roll beacons, and the ExoClick
  dashboard showing the impressions.
  The script's consent and Global Privacy Control defaults are the cautious ones and belong
  to D15. `OPERATOR` (admin).
  **2026-11-19:** prod still registers the `vast-ads` plugin (RUNTIME 2026-11-19, public
  config). Everything on the beta's side is **unverified 2026-11-19**: the installed script,
  the provider path, the page policy and the VAST settings are behind the gate or in the
  database. The open points are as they were: no read-back of real fill by format or with a
  blocker on, the mid-roll and post-roll beacons, and the ExoClick dashboard.

### D12 media-DR tail (open, not all window-blocking)

All four re-read 2026-11-12 and all four still open. Read again 2026-11-19 from the Backblaze
listings, which cover three of them; all four are still open.

- [ ] B2 replication **or** Object Lock to a separate account. Neither bucket replicates and
  file lock is off on both (RUNTIME). `OPERATOR`.
  Unchanged 2026-11-19: no replication, file lock off and no lifecycle rule on either
  bucket, and both are at the bucket revision they had on 2026-11-12 (RUNTIME 2026-11-19).
- [ ] A media key **without** `deleteFiles`. The key the beta runs with still carries it
  (RUNTIME). `OPERATOR`.
  Unchanged 2026-11-19: the account has the same 16 keys, the one key scoped to the media
  bucket still carries `deleteFiles`, and no other key for that bucket has been made
  (RUNTIME 2026-11-19, key listing). The key actually in the beta env is unverified.
  Such a key protects less than its name suggests (REHEARSAL 2026-11-12): the api's own
  storage probe hid its test object with a key that had no `deleteFiles`, because hiding and
  overwriting need only `writeFiles`. Nothing is destroyed, but a hidden or overwritten
  object stops being served until someone with a delete-capable key removes the marker or
  the newer version, and only while no lifecycle rule has cleared the old versions.
- [ ] `HEALTHCHECKS_URL` in `/etc/vidra/backup.env` (silent on failure today). Absent: the
  file sets only the rclone remote and config path. The nightly backup itself last succeeded
  2026-11-12 03:26 UTC (RUNTIME). `OPERATOR`.
  **Unverified 2026-11-19** (`backup.env` not reachable); still unset on 2026-11-15 (RUNTIME
  that day, I1). The backup bucket showed uploads in the nightly slot every night from
  2026-11-05 through 2026-11-19, most recently at 03:43 and 03:56 UTC (RUNTIME 2026-11-19).
  On November 25 the timer was active and the backup service reported success.
  Both backup configuration files lacked the heartbeat setting, and the unit
  had no failure handler. Delivery of an external failure alert remains open.
- [x] **Abandoned media uploads cleared November 25.** All 26 stored parts of
  the 11 November 5 unfinished uploads matched the provider checksums for the
  corresponding byte ranges of their completed versions (427,563,053 bytes).
  Only the unfinished IDs were cancelled. All 11 completed versions remained
  current, and a fresh listing found zero unfinished uploads in the media bucket.

## C. The cutover window (§5 steps 1–7)

Not started on prod or the beta. Steps 1–5 and the rollback in step 7 were rehearsed on a
throwaway copy on 2026-11-12; what each showed is under the step. Measured times are in G.

- [ ] **1 · Freeze prod (D2):** nginx returns 503 for non-GET/HEAD on `/api/v1/`; verify a
  write is refused; record T0. Snippet prepared in `cutover-prep/`. `OPERATOR`.
  The prepared snippet is wider than that wording: it refuses every request that is not
  GET, HEAD or OPTIONS on the whole site, so logins, view pings and the ActivityPub inbox
  answer 503 too (read 2026-11-12). That is what a consistent snapshot needs; expect it.
  **The first prepared snippet does not load** (REHEARSAL 2026-11-12): `nginx -t` rejects it
  with `"add_header" directive is not allowed here`, because a server-level `if` may hold only
  rewrite directives. The reload would never have happened: no outage, but no freeze either.
  The corrected snippet (the `if` only returns 503; the headers are added in a named location
  reached through `error_page 503`) passed all 26 checks on a throwaway nginx: POST, PUT,
  PATCH and DELETE on four paths answer 503 with `Retry-After`, GET and HEAD reach the
  upstream, OPTIONS is not refused, and removing or restoring the include line takes effect
  within a second of the reload. It replaced the first one in `cutover-prep/` the same day.
  On November 25 the installed production nginx parsed both its current model and
  an in-memory copy with the corrected snippet in the actual apex TLS server.
  The candidate contained exactly one 503 handler. The serving file digest and
  master PID matched their initial values. Enforce and verify the freeze at T0.
- [ ] **2 · Snapshot (Step 25):** dump → SHA-256 both ends → restore as a new DB → §3 grants →
  swap names; keep the previous snapshot. `OPERATOR`.
  Rehearsed 2026-11-12 with the 2026-11-06 dump: restore into a new database 117 s; grants,
  rename swap and check 4 s. Through the importer's own connection string the reader could
  read, and an `UPDATE` was refused twice: by the read-only default, then by the missing
  grant once that default was switched off. The role's read-only setting followed the rename.
- [ ] **3 · Hostname flip on the beta:** `backup.sh` → env (`PUBLIC_BASE_URL`,
  `NEXT_PUBLIC_API_BASE_URL`, `CORS_ALLOWED_ORIGINS` → `https://sizetube.com`;
  `VIDRA_SKIP_DNS_PREFLIGHT=1`) → `vidra setup` → re-add the hand-added Caddy blocks (site
  `sizetube.com`, cdn `Host`, drop the IP gate and `noindex`) → `deploy.sh` → verify
  `/healthz` via `--resolve` and the admin infra `public_base_url`. `OPERATOR`.
  Today all three URLs are `https://beta.sizetube.com` and the hand-edited `Caddyfile.local`
  is unchanged since 2026-11-05 (RUNTIME 2026-11-12).
  Rehearsed 2026-11-12. The command the prepared notes did not spell out is
  `vidra setup --template env/production.env.example --non-interactive --yes`. At v0.7.19 it
  rewrites the env file from the current template (1,576 → 1,621 lines), keeps every value
  and secret, **adds two blank keys** new in the template (`PEERTUBE_IMPORT_S3_COPY_ACCESS_KEY`,
  `PEERTUBE_IMPORT_S3_COPY_SECRET_KEY`) and drops keys whose value is empty, so the env diff
  is the patch plus those two. It regenerates `Caddyfile.local` **without** the hand-added
  parts; the prepared target file differs from its output by 40 added lines and nothing else,
  so it is still valid for this release. `vidra setup --check` passed (103 variables).
  `deploy.sh` took 76 s and **recreated the Caddy container** (the regenerated file is a new
  inode, so the bind mount was stale): a few seconds with no edge, inside the freeze.
  Afterwards `/healthz` answered on `sizetube.com`, the admin infrastructure page reported
  `public_base_url=https://sizetube.com`, the sitemap and the RSS feed carried only the new
  origin (5,143 and 152 occurrences, none of the old), and `beta.sizetube.com` answered 301.
- [ ] **4 · Final rerun:** dry run, then `run` with `source_authoritative=true` (D1); confirm
  `remote_follower.imported=20`, the state-8 pair's HLS, the 8 drafts now `published`, zero
  transient failures; re-run the §9.5 / §9.6 / §9.12 diffs and apply D10 by hand. `OPERATOR`.
  No run has used `source_authoritative=true` yet; `remote_follows` is empty (RUNTIME
  2026-11-12). **Runs between now and the window import nothing new, and that is expected:**
  the importer reads `peertube_source_snapshot`, a copy on the beta's own Postgres restored
  2026-11-06 16:59 UTC, whose newest video is from 11-06 15:06; the beta already holds all
  15,508 of its videos, and the run after the last swap did import the 10 that copy had
  gained. Prod's public API shows 38 public videos created since (RUNTIME 2026-11-12 14:16
  UTC). Step 2 of this window is what refreshes the copy. From v0.7.20 the import report and
  the admin import page show the newest video date in the source (core #541, user #469).
  Prod has moved on since the 2026-11-06 snapshot: its public stats show 5,577
  accounts against 5,539 on the beta.
  **2026-11-19:** the two paragraphs above describe the 2026-11-06 copy, which has been
  replaced since: a catch-up run on 2026-11-14 brought the beta to 15,613 videos, and the
  copy was refreshed on 2026-11-15 at 18:42 UTC (15,614 → 15,622 local videos) with no run
  started after it, as of that entry (audit §6). Whether it has been refreshed or run since
  is **unverified 2026-11-19**. Prod's public API shows 25 public videos created after that
  refresh, and 5,634 accounts (RUNTIME 2026-11-19).
  Rehearsed 2026-11-12 on the copy, against the 2026-11-06 snapshot. Dry run with
  `source_authoritative=true`: 79 s. It lists planned totals per kind and **does not say what
  a real run will change**. Real run with `source_authoritative=true` and `media_mode=none`:
  334 s, `done`, no failure in any kind; 10 videos and 18,970 playlist entries updated,
  146 playlist entries and 1 follow added, users and channels unchanged.
  **`remote_follower.imported` was 13, not 20**: seven followers' servers did not answer
  ("retried on the next run"). Expect a number below 20 on the day and read the report's
  note rather than failing the step on it.
  **Not rehearsed: the same run in copy mode**, the form the window uses. From a second box
  sharing the beta's bucket it could overwrite objects the beta serves: posters and
  storyboards sit at keys derived from the video id, the importer's writes overwrite, and in
  this mode a poster changed on Vidra since import is replaced (CODE core `e6d83aa4`
  `internal/peertubeimport/importer.go:865`, `entities_videoimages.go`). The operator decided
  against it. Its media part therefore has no measured time: the earlier gap-fill runs on the
  beta took 12–43 min, and each run retries about 9,900 fetches that are known to fail.
- [ ] **5 · Re-accept on the real hostname** via a hosts override: D13 login, reset mail,
  playback (public / private / internal as a permitted user), old links incl. embeds, admin
  pages, a synthetic upload. `OPERATOR`.
  Rehearsed 2026-11-12 from a real browser with the site's names mapped to the copy.
  Passed: sign-in with an imported account's existing password (D13); public playback with a
  seek; a private video (anonymous 404, plays for its owner); an internal video (anonymous
  401 `sign_in_required`, plays signed in); `/w/<short id>`, `/videos/watch/<uuid>`,
  `/videos/embed/<uuid>?start=` and `/video-playlists/embed/<uuid>` (each 302 to a page that
  loads); a synthetic upload (published in about 6 s, plays, found through the search
  service); the ad proxy script, no policy violation, VAST tag requests answered.
  **Still 404, as on 2026-11-08:** `/c/<handle>/videos`, `/channels/<handle>/videos`,
  `/video-channels/<handle>` and `/accounts/<name>`.
  Not rehearsed: the reset mail (the copy had mail removed) and the admin pages beyond the
  infrastructure and import pages. The upload ran as the copy's owner, not as the imported
  account.
- [ ] **6 · DNS:** Cloudflare `sizetube.com` → 159.203.29.27 (proxied, D3). Recheck TLS,
  cookies/CORS, playback, search, old URLs publicly; watch api logs for 429/5xx; then enable
  registration / mail / federation per decisions, each with its own check. `OPERATOR`.
- [ ] **7 · Rollback window (at least 24 hours per the November 25 decision):** PeerTube frozen-but-running, env pinned at
  the release deployed on the day (v0.7.20 when this was written; see the header), both
  snapshots + dumps kept, source bucket untouched, GC still off. Rollback = DNS back +
  unfreeze + a final `backup.sh`. `OPERATOR`.
  The beta's side of a rollback was rehearsed 2026-11-12 on the copy: `restore.sh` with the
  pre-flip backup 340 s including its media existence pass (every referenced object
  present), the saved env and `Caddyfile.local` back, `deploy.sh` 91 s: about 7 minutes.
  Everything written after the backup was gone (13 remote follows, the test upload, two
  import runs), and 163 of 165 tables had exactly the row counts the backup held; the other
  two are written by the apps as they start.

## D. Post-window cleanup (after the rollback window)

- [ ] `PEERTUBE_IMPORT_ENABLED=false`; drop `pt_import_reader` and both snapshot DBs; delete
  the read-only B2 key. `OPERATOR`.
- [ ] Re-enable GC only after a dry-run sweep reads 0 unexpected orphans. `OPERATOR`.
- [ ] Decide the fate of `beta.sizetube.com`, `cdn-beta.sizetube.com` and `cdn.sizetube.com`
  (stays on B2 for rollback). `OPERATOR`.

## E. Operator decisions

D1–D14 and D16 were answered on November 8 (audit §6 table). The operator
approved D15 on November 25. Section A records the policy implementation status.

## F. Standing reminders

- Re-drill the restore on the **final** pre-cutover dump (10.5 passed on the 2026-11-08 dump).
  Run it with `--require-media-consistent` (I3): without the flag `restore.sh` warns and
  exits 0 when referenced media is missing or could not be checked, so its exit code says
  nothing about media. The strict pass hashes every referenced object, so it is slow (the
  runbook's example allows `RESTORE_MEDIA_TIMEOUT=36h`): run it on a copy ahead of the
  window, not inside it. `deploy/README.md`, "For a recovery acceptance drill".
- Keep `MEDIA_GC_ENABLED=false` for the entire rollback window.
- A fresh off-site backup immediately before T0.

## G. Rehearsal and load check — run 2026-11-12

- [x] **Dress rehearsal of window steps 1–5 and the rollback** — 2026-11-12 11:14–13:07 UTC
  on a throwaway droplet of the beta's size, built from the beta's 03:26 UTC backup. Mail
  configuration deleted before the api first started; storyboards, registration and GC off;
  new JWT, database and Redis secrets; no backup remote; a firewall admitting one address;
  a temporary storage key without `deleteFiles`. `AGENT` ran, `OPERATOR` approved and typed
  one password. Per-step results are in section C.
  **Measured machine time** (REHEARSAL): freeze reload, seconds · snapshot restore, grants,
  swap and check 121 s · backup 33 s · env patch, `vidra setup`, hand-added Caddy parts and
  `--check`, seconds of commands · deploy 76 s · dry run 79 s · authoritative rerun without
  media 334 s · acceptance driver about 3.5 min. **About 15 minutes for steps 2–5.**
  **Not in that figure:** the prod dump and its transfer (the dump took about 5 min on
  2026-11-06); the media part of the rerun in copy mode (12–43 min on earlier gap-fill runs,
  never run in authoritative mode); reading results and typing; the Origin CA certificate;
  Cloudflare and DNS. So the earlier 75–125 min freeze-to-DNS estimate is narrowed, not
  replaced: the rerun's media part is still the unknown that dominates it.
  **Rollback:** about 7 minutes (section C, step 7).
  **Found:** the freeze snippet did not load (C1, fixed); the Origin CA certificate must be
  single-name (B, D3); `vidra setup` adds two keys and the deploy recreates Caddy (C3); the
  dry run does not show what will change, and 13 of 20 remote followers were reachable (C4);
  four old channel and account URL forms still 404 (C5); a key without `deleteFiles` can
  still overwrite and hide (B, D12 tail).
  **What it touched outside itself:** public GETs only: follower profiles on 12 other
  servers and a handful to prod's public site. In the beta's media bucket: one test upload
  (27 object versions, 13.6 MB) and about 20 hidden 62-byte write probes, listed in the
  private log. A listing of
  every version written to that bucket during the run shows nothing else from the
  rehearsal: none of the beta's own objects was overwritten or hidden. Removing the test
  objects needs a delete-capable key; the operator decided on 2026-11-12 to leave them.
  **It could not rehearse** the real Origin CA certificate, Cloudflare in front, the DNS
  change, prod's own nginx config around the freeze snippet, or the reset mail.
- [x] **One read-path load check — run 2026-11-12 on v0.7.19; FAILED at the estimated peak.**
  `AGENT`. Rerun on v0.7.20 the same day: next item.
  Method: anonymous page views replayed from a browser recording, about 25 requests each
  (1 page, about 10 api calls, about 15 thumbnails; watch pages add playlists and three
  media segments), every view under its own visitor address so the per-address limit sees
  many visitors. One generator on a home line; no Cloudflare in front, so thumbnails and
  media are heavier than they will be.
  Sizing: prod's request rate is unknown (section H). "1×" is the page rate at which this mix
  produces prod's 68.7 Mbps bandwidth peak: **270 page views a minute**. Its 7.1 Mbps average
  is 28 a minute; prod reports 318 daily active accounts.

  | Page views / min asked | Completed | Page p50 / p95 | Api p50 / p95 | Timeouts |
  |---|---|---|---|---|
  | 30 | 32 | 0.35 / 1.42 s | 0.08 / 0.72 s | 0 |
  | 58 (90 s, caches cold) | 58 | 0.40 / 1.77 s | 0.08 / 0.57 s | 0 |
  | 90 | 95 | 0.58 / 2.88 s | 0.12 / 1.06 s | 0 |
  | 120 | 115 | 1.27 / 3.71 s | 0.21 / 1.93 s | 0 |
  | 150 | 140 | 1.15 / 3.23 s | 0.20 / 1.85 s | 0 |
  | **270 (1×)** | **74** | over 60 s | over 60 s | **15,358** |

  The 270 row ran 10 minutes, the others 3 unless marked. Passing needed page p95 ≤ 1.5 s and
  api p95 ≤ 0.4 s at 1×. At 1× the box completed 74 of 270 page views a minute, 15,358
  requests timed out at 30 s and 1,893 views were still waiting at the end; Postgres held all
  8 vCPUs, running the public video list, its count and the search count. **3× was not run.**
  No 5xx, no container restart, and no visitor other than the deliberately over-limit one
  was rate-limited at any level: the limiter does key on the visitor's own address behind a
  trusted proxy, which had not been shown before.
  Reading: the box keeps up to roughly 120–150 page views a minute with page p95 near 3 s,
  and falls over between 150 and 270. The api p95 limit is missed at every level because of
  the three slow endpoints (section B, read-path capacity).
  Also measured: a page view makes 19–31 requests under `/api/v1` (7–20 of them thumbnails),
  not the 8.4 the parity QA recorded; thumbnails average 137 KB.
  Limits: the 1× figure is an estimate from bandwidth, not prod's measured peak; ladder steps
  were 3 minutes; latencies include the generator's own line.
- [x] **The load check rerun on v0.7.20 — 2026-11-12 18:39–19:15 UTC; PASSED at the estimated
  peak.** `AGENT`. A second throwaway droplet (same size; `nyc1`, because `tor1` had none of
  that size free), the beta's 18:05 UTC backup restored and neutered as before, v0.7.20, the
  same driver, mix and pass marks. Its storage key could only read, so the copy could write
  nothing to the beta's bucket. Destroyed afterwards with its firewall and key (52 minutes,
  about $0.13).
  **Two generators, because the first one's line is too small.** The home line carried
  52 Mbps from the copy (measured); the 270 mix needs about 69. So the rungs up to 150 were
  run from the home line as before, and 30, 150 and 270 from a generator in a container on
  the copy itself, through the same Caddy. Those on-box figures have no internet in them and
  the generator shares the 8 vCPUs.

  | Page views / min | Generator | Page p50 / p95 | Api p50 / p95 | Timeouts | Result |
  |---|---|---|---|---|---|
  | 30 | home line | 0.17 / 0.43 s | 0.05 / 0.23 s | 0 | pass |
  | 90 | home line | 0.13 / 0.35 s | 0.05 / 0.21 s | 0 | pass |
  | 120 | home line | 0.13 / 0.33 s | 0.05 / 0.21 s | 0 | pass |
  | 150 | home line | 0.64 / 5.44 s | 0.24 / 2.29 s | 0 | **line-limited** |
  | 30 | on the box | 0.05 / 0.11 s | 0.01 / 0.12 s | 0 | pass |
  | 150 | on the box | 0.06 / 0.23 s | 0.01 / 0.14 s | 0 | pass |
  | 270 | on the box | 0.04 / 0.12 s | 0.01 / 0.10 s | 0 | pass |
  | **270 (1×), 10 min** | on the box | **0.05 / 0.14 s** | **0.01 / 0.12 s** | **0** | **pass** |

  The 10-minute row: 2,600 page views completed, 4 still in flight at the end, none dropped,
  no 5xx, nobody but the deliberately over-limit visitor refused; thumbnails p95 0.17 s, media
  segments p95 0.39 s. The box averaged 32 % CPU busy (peak 57 %) and no container restarted.
  The api's own request log for those 10 minutes: every api call p95 105 ms; the video list
  p95 36 ms; search p50 142 / p95 358 ms; the home rail p50 132 / p95 269 ms. On v0.7.19 the
  same row completed 74 a minute with 15,358 timeouts.
  The 150 row from the home line failed on latency for the generator's reasons, not the
  box's: in that window the api's own log shows every api call p95 83 ms and the box at most
  31 % busy, and the over-limit visitor's tiny requests were slow too. The morning's rungs at
  120 and above went through the same line, so part of what they showed may have been the
  line; its 1× collapse was the database (all 8 vCPUs), which is what v0.7.20 fixed.
  Limits: at 150 and above the generator was on the box it loaded; `nyc1` is nearer the media
  bucket than the beta is, so thumbnails and media may be quicker here than there; no
  Cloudflare in front; 1× is still the bandwidth estimate; **3× was not run**, so where it
  falls over now is not known; ladder steps were 3 minutes.

### November 24 production traffic measurement

Cloudflare's adaptive HTTP analytics for the apex recorded about 6.52 million
eyeball requests in the 24 hours ending at 16:00 UTC on November 24. About
2.50 million reported an origin response, including 1.40 million under
`/api/`. The query grouped counts by UTC minute and used a positive origin
response status for the origin series. Counts are sampling estimates.
[Cloudflare hostname analytics](https://developers.cloudflare.com/analytics/graphql-api/tutorials/end-customer-analytics/)

| Busiest one-minute interval in the seven days ending November 24 at 16:00 UTC | Requests per minute |
| --- | ---: |
| Apex edge, all responses | 11,113 |
| Apex with an origin response, all statuses | 7,543 |
| Apex with an origin response, HTTP 200–399 | 3,452 |
| Apex API with an origin response, all statuses | 6,213 |
| Apex API with an origin response, HTTP 200–399 | 2,192 |

Each row has its own peak minute. At the API peak on November 18 at
18:09 UTC, about 4,939 of 6,213 requests received an origin 429 (80%).
The v0.7.20 rehearsal above completed 2,600 synthetic page views in ten
minutes. Qualifying v0.7.30 at this measured demand still requires a
representative route mix and separate measurements for successful responses
and rate-limited requests. Page views and HTTP requests have different units.

### November 25 API capacity rehearsal on v0.7.30

The rehearsal used a temporary DigitalOcean host in San Francisco with the
same 8-vCPU, 16-GB size and the same core, frontend, search, PostgreSQL and
Redis image digests as beta. The synthetic catalogue held 15,720 videos,
5,654 owners and 13,894 eligible search documents. The API and load generator
ran on the host. The generator called only the loopback API.

Cloudflare estimated 2,192 successful apex API origin requests at the
November 21 peak minute. The production request mix included plugin and
configuration requests as well as lists, search, channel pages, view events,
video details, comments and captions. The fixture used Vidra's corresponding
read routes and view writes. It represented plugin reads with instance reads
and represented other API routes with discovery requests.

| Workload | Completed | Result |
| --- | ---: | --- |
| Successful-request capacity, 2,192/min for ten minutes, per-IP limiter disabled on the fixture | 21,920 of 21,920 | All HTTP 200/204. Aggregate p95 137.3 ms. Search p95 392.8 ms across 2,500 searches. |
| Concentrated demand, 6,213 requests in one minute from one client, beta's 300/min limit enabled | 6,213 of 6,213 | 300 successful responses and 5,913 HTTP 429s. Aggregate p95 2.1 ms. |

Both runs had zero dropped requests, timeouts and 5xx responses.
This qualifies the synthetic origin API workload on v0.7.30. The traffic
it measured excludes browser rendering, media delivery, CDN behavior, ad
providers and authenticated uploads. The second run measured the single-IP
limit. Production's observed 429 fraction depends on its visitor mix.

## H. What is still not checked (after the 2026-11-12 re-read and rehearsal)

- **Anything on the beta itself, as of 2026-11-19.** That day's partial re-read reached no
  source on the box (see the top of this file): the deployed release, the env file, the
  database and the certificate directory. The items it left unverified say so in sections A,
  B and I, each with the date it was last observed.
- **Prod's transcoding queue now, and prod's real request rate.** Both need read-only SSH to
  prod, which the operator declined on 2026-11-12. D16 therefore rests on the 2026-11-09
  reading, and the load check's "1×" is an estimate (section G).
  The November 24 queue check and the Cloudflare measurement in section G
  supersede this historical gap. The final queue read belongs at the freeze.
- **Where the read path gives out on v0.7.20.** The rerun stopped at the estimated 1× and
  passed; 3× was not run, and at 150 a minute and above the generator sat on the box it was
  loading (section G).
- **The final rerun in copy mode with `source_authoritative=true`.** Never run anywhere
  (section C, step 4).
- **The admin infrastructure page on the beta.** Read on the rehearsal copy only; on the beta
  `public_base_url` was read from the running api container's environment.
- **Whether counsel has answered D15.** The operator's to supply.
- **What `www.sizetube.com` should do.** It answers 526 (public GET 2026-11-12, and again
  2026-11-19) and the prepared Caddy file has no `www` block, so it stays broken after the
  cutover unless one is added. No decision covers it.
- **Ads:** real fill and a real blocker on the six display formats; mid-roll and post-roll
  beacons; the ExoClick dashboard.
- **Why three more import runs happened on 2026-11-10** (14:13, 16:33 and 19:24 UTC, started
  by the owner; the last with conflict policy `merge`). What they did is known: each ended
  `done` with nothing imported or updated, and the same failure sets as the 2026-11-08 run
  (HLS 687, captions 669, thumbnails 683, one video, and storyboards with a missing source
  image, falling 8,082 → 7,983 → 7,861). The "imported 687" in the 16:33 run's audit line is
  the media-less-video counter, not new content (RUNTIME 2026-11-12).

## I. Gaps recorded by the 2026-11-13 review

Read 2026-11-13 from files only: this checklist, the audit, and the released source at meta
`6b5aead` and core `5b7c22aa` (v0.7.20), cited below as `CODE`. No host, database or bucket
was read, so the original findings are not runtime observations. Subsequent dated notes distinguish live
reads from source review and unavailable evidence. The legal items are engineering guidance, not legal
advice. I1–I6 were recorded nowhere in this file. I7–I10 were notes inside section A's text
with no checkbox and no owner; they get one here and section A is unchanged. Whether any of
I6–I10 blocks the window is for counsel and the operator, and is not decided here.

**Data loss**

- [~] **I1 · A hand-run `backup.sh` can keep its copy on the box and still report success
  (bears on C3, C7 and F).** The script takes the off-site remote from its own process
  environment or from the env file (CODE `deploy/backup.sh:91`). With neither it logs
  `LOCAL COPY ONLY`, writes `last_success` and exits 0 (`backup.sh:365,470-471`). Section B
  records the beta's remote in `/etc/vidra/backup.env`. A shell does not load that file, and
  in the repository's unit the line that would is commented out
  (`deploy/vidra-backup.service:36`). **Unverified:** whether the beta's env file also carries
  `BACKUP_RCLONE_REMOTE`, and how the installed unit loads the file. The rehearsal could not
  show this, because its copy had no backup remote (section G). Before the window, read
  which file holds the remote. Then either take the window's backups through the unit
  (`systemctl start vidra-backup.service`), or read each run's log for the upload line and
  treat `LOCAL COPY ONLY` as a failed step. `OPERATOR`.
  *Note 2026-11-15:* `deploy/backup.sh` now refuses to call a hand run a success on a host
  configured for off-site: when a hand run has no target and `/etc/vidra/backup.env` names
  one (or cannot be read), it writes the local pair, exits non-zero, leaves `last_success`
  alone and points at putting the target in the env file or running the unit. It does not upload, and
  the nightly unit is unchanged. This is CODE only. The host still has to be checked: which
  file holds the beta's remote, that the installed script is this version, and how the
  installed unit loads the file. Not ticked.
  *Read on the beta 2026-11-15 (RUNTIME, read-only):* the remote is in
  `/etc/vidra/backup.env` only; the installed unit runs as `vidra` and a drop-in loads that
  file (`EnvironmentFile=/etc/vidra/backup.env`); the 03:17 UTC nightly uploaded the dump and
  the config archive. So on the beta a hand run has no remote, and
  `systemctl start vidra-backup.service` is the run that uploads. The script change merged
  as meta #393 and is NOT on the beta until its next bundle; until then a hand run there
  still reports success with a local copy only. `HEALTHCHECKS_URL` is not set, so a failed
  nightly alerts nobody. Not ticked.
  **RUNTIME 2026-11-19 — partial:** B2 shows nightly uploads; the installed guard, unit and
  logs are unverified. The v0.7.23 guard was read on 2026-11-15, not exercised by hand.
  For window backups use the configured unit and verify its off-site upload, not a local
  exit code. A fresh pre-flip run is still required.
- [ ] **I2 · Nothing pins the rollback dumps (C7).** Step 7 says "both snapshots + dumps
  kept" and names no mechanism, and no rollback-window length is recorded (D14 records the
  write-loss policy only). On the box, the pre-flip `vidra-<stamp>.dump.gz` leaves the daily
  keep once 14 later days have a dump (CODE `deploy/backup.sh:66,435`). The pre-deploy dump
  that step 3's `deploy.sh` writes is pruned after 10 later deploys and is never uploaded
  (`deploy/deploy.sh:46,620,644`). An off-site copy of the pre-flip pair exists only if I1
  holds. Either record a window shorter than 14 days, or copy the pre-flip dump, its config
  archive and the step 3 pre-deploy dump to somewhere the scripts do not prune. `OPERATOR`.
  **RUNTIME 2026-11-19 — partial:** the backup bucket listed 60 objects and no lifecycle
  rule. That does not pin a dump. No rollback length or pinned pair is documented; on-host
  copies are unverified. Set the window length and retain both dumps outside local pruning.
- [ ] **I3 · The restore re-drill in F can pass with media missing.** By default
  `restore.sh` warns and continues when referenced media is missing or cannot be verified
  (CODE `deploy/restore.sh:457-463`); only `--require-media-consistent` refuses
  (`restore.sh:84,471,489`). F does not name the flag, and whether 10.5 and the rehearsal
  used it is not recorded here. Run the re-drill on the final dump with the flag, or read
  the media pass's own result instead of the exit code. `OPERATOR`.
  **2026-11-15:** section F now names the flag and where the command is. The box stays open
  until the re-drill on the final dump has been run that way.
  **RUNTIME 2026-11-19 — unverified:** no final strict restore is recorded; the host was
  unreachable. B2 listings cannot demonstrate a restore.
- [~] **I4 · Timed lost-object restore.** The same-bucket version recovery passed on
  November 25 in 3.01 seconds. Restoration from an independent copy remains open.
  Repeat the timed read from the separate D12 destination once it holds a verified copy.
  `OPERATOR`.
  **RUNTIME 2026-11-19:** neither replication nor Object Lock was configured (B2, D12 tail).
  No timed restore or waiver is recorded; neither was verified.
- [ ] **I5 · How many copies of the backup encryption secret exist is still unverified.**
  The audit rated it Medium: "the crypt password/salt is a single point of failure (copy
  count unverified)" (audit §8 Durable). If the off-site copies are encrypted with it, they
  cannot be read without it (DEDUCED). Confirm a copy is held off the droplet. `OPERATOR`.
  **RUNTIME 2026-11-19 — unverified:** the B2 listing cannot establish custody of a working
  off-droplet crypt password and salt. No secrets were opened and no decryption was run.
  Verify recovery on a separate machine.

**Legal exposure**

- [ ] **I6 · Ads and tracking consent has no question in the D15 intake.** Section B assigns
  the ad script's consent and Global Privacy Control defaults to D15, but none of the five
  intake questions asks what consent the HilltopAds and ExoClick display, popunder and VAST
  formats need (audit §8, questions 1–5). Add it to what counsel is asked. `LAWYER`.
  **RUNTIME 2026-11-19 — partial:** prod lists the Analytics and VAST plugins. Beta consent
  and tag behaviour are unverified. The last beta read showed Analytics enabled without a
  consent prompt (2026-11-15, audit §6). The five-question intake in §8 still has no ad or
  tracking question; no answer is documented.
- [x] **I7 · A signup through OIDC or ATProto is not asked for the age attestation.** Both
  provider paths pass the terms acceptance only (CODE core `internal/auth/oauth.go:831`,
  `internal/auth/atproto.go:459`); the minimum-age check is in the form's handler alone
  (`internal/httpapi/auth.go:363`). Once D6 sets `registration_minimum_age=18`, a provider
  signup does not meet it. **Unverified:** whether any provider is enabled on the beta. Fix
  it in code, or keep providers off until it is fixed. `AGENT`, then `OPERATOR`.
  **Fixed 2026-11-14; released in v0.7.21 and deployed to the beta 2026-11-14 17:03 UTC.**
  Core #552 (`c9ab3cb8`): the one check every account-creating path calls now refuses without
  the attestation while a minimum age is set. That covers the form, the approval queue and a
  provider's first sign-in, which lands back on the signup page with
  `oauth_error=age_required` and creates nothing. The age is recorded with the account. User
  #472 (`712b2a92`) carries the tick from the signup form to both provider buttons. After the
  deploy the beta answers `/version` v0.7.21 `0c06a81` (RUNTIME). **Not exercised on the
  beta:** registration is closed and `registration_minimum_age` is 0 there, so no refusal can
  fire yet; it rests on the two PRs' tests (CODE). Whether any provider is enabled is still
  unverified.
- [~] **I8 · The sign-in wall's two uncovered surfaces.** These matter only if `sign_in` is
  switched on. The IPFS mirror's eligibility test reads privacy and state, not the sensitive
  flag (CODE core `internal/httpapi/ipfs_assets.go:24`); **unverified:** whether the beta
  mirrors to IPFS at all. Playlist item cards are built without the card gate
  (`internal/httpapi/playlists.go:84,265`; the file has no `gateCards` call), so a sensitive
  card there carries no `sign_in_required` mark. The video's own reads are refused by the
  wall's design (`internal/httpapi/sensitive_gate.go:9-16`); that was not checked end to end.
  `AGENT`.
  *2026-11-15:* the playlist half is fixed on core main and NOT released: item cards go
  through the card gate (core #555), and the item list and its counts leave out
  moderator-blocked videos and, under the `hide` policy, sensitive ones (core #557). The
  IPFS half is open. Read on the beta the same day (RUNTIME): `IPFS_MANAGED_NODE=false`.
  Not ticked.
  **RUNTIME 2026-11-19 — unverified:** the beta settings, including IPFS, were unreachable;
  neither anonymous playlist delivery nor the mirror was exercised. RECORD: v0.7.23 carried
  the playlist fix on 2026-11-15. CODE: IPFS eligibility is unchanged through v0.7.25 and
  core main `21b37034`. The mirror half remains open if `sign_in` is chosen.
- [ ] **I9 · Existing accounts are never asked to accept the terms.** The `reaccept` source
  exists only in the migration's allowed values and a comment (CODE core
  `migrations/0189_user_consents.up.sql:28`, `internal/account/archive.go:45`); no handler
  writes it. Whether the 5,541 existing accounts must accept is a question for counsel, and
  the code follows the answer. `LAWYER`, then `AGENT`.
  **RUNTIME 2026-11-19 — unverified:** no beta login or DB session. Counsel has not given
  a recorded decision. CODE: through v0.7.25 and main `21b37034`, no handler writes
  `reaccept` (schema, comments and tests mention it).
- [~] **I10 · The mail and reporting items rated HIGH in D15 have no owner.** No
  `List-Unsubscribe` header is set anywhere in core (CODE: a search of `internal/` and
  `cmd/` finds none). Filing an abuse report needs an account: all three report routes
  require sign-in (`internal/httpapi/server.go:2177-2179`), so a non-user has no route for
  a DMCA notice or an intimate-image takedown. The header is `AGENT`; what the non-user
  route must be is `LAWYER`, then `AGENT`.
  *2026-11-15:* the header half is merged on core main and NOT released (core #556):
  notification email carries `List-Unsubscribe` and `List-Unsubscribe-Post` (RFC 8058) and a
  signed one-click endpoint turns that user's notification email off. Not checked against a
  real mailbox provider. Brevo documents that it adds its own header, so one-click through
  Brevo is not claimed; a relay must DKIM-sign both headers. The non-user report route is
  unchanged. Not ticked.
  *Correction, 2026-11-15:* this note first said the beta has no mail transport, from the
  env file alone (`SMTP_HOST` empty, `MAIL_ENABLED=false`). That was wrong. The admin panel
  holds a mail configuration (RUNTIME, read-only: one `mail_config` row, transport `resend`,
  a secret stored, saved 2026-11-09). The operator sent a password-reset email from the beta
  by hand the same day and it arrived, so the panel configuration sends with
  `MAIL_ENABLED=false` in the env file. Not checked: notification email, and whether Resend
  passes the two unsubscribe headers through; the headers of the first notification email
  after the next release answer both.
  **RUNTIME 2026-11-19 — unverified:** no mailbox, beta DB or notification test. RECORD:
  v0.7.23 deployed the header on 2026-11-15; that does not prove Resend delivers it. CODE:
  report routes still require sign-in on core main (`21b37034`, `server.go:2204-2206`).
  Assign an owner for a public takedown route; neither half is accepted end to end.

Not covered by either review: the beta's live configuration, prod, the private
`cutover-prep/` files (including the ad script), Canadian law, Cloudflare settings, and
accessibility.
