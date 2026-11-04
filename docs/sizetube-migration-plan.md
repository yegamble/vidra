# Planning the SizeTube migration through a private beta

Planning date: **2026-11-03**. The operator selected a **private migration
rehearsal first** at `beta.sizetube.com`, hosted on DigitalOcean.
`sizetube.com` continues serving PeerTube throughout rehearsal.

**Production remains NO-GO.** The private edge and source database clone are prepared.
A source-built COPY preparation is running against an isolated target; the web
application remains undeployed and the edge continues serving restricted maintenance.
Production database, media and DNS remain unchanged.
The current [qualification record](release-readiness.md) and
[PeerTube migration runbook](peertube-migration.md) define the acceptance gates.

## Current findings

Read-only SSH inventory confirms native **PeerTube 8.3.1**, actual database
schema **1130**, split-audio HLS enabled and web-video generation disabled.
The released Vidra **v0.7.8** importer accepts **700–1040**. Do not rewrite the marker or
acknowledge an unsupported version to make an automated rehearsal proceed.

The [schema-1130 support](https://github.com/yegamble/vidra-core/pull/458)
and [retained-original COPY fix](https://github.com/yegamble/vidra-core/pull/457)
are merged, as is the [encoded search-page bound](https://github.com/yegamble/vidra-core/pull/459),
but must still be published and pinned
before replacing that released baseline. Source tests and a disposable
upstream fixture do not supply representative SizeTube migration acceptance.
The existing synthetic B2 rehearsal is useful evidence within its
[explicit limits](runtime-acceptance-b2-migration-v0.7.8.md).

The new `sizetube-beta` droplet is provisioned in DigitalOcean NYC2:
Ubuntu 24.04, 4 vCPU, 16 GB RAM, 200 GB disk, quoted **$84/month** at creation.
Docker and Compose execute successfully. Beta DNS now points to the new host.
The Caddy maintenance edge has a trusted certificate and restricts application
routes by transport remote IP. Independent probes returned 403 for frontend,
API, media, lazy-static and federation paths, including spoofed forwarding
headers. Host/gateway access is limited to `/healthz`; it reports 503 because
no application candidate is deployed. The authorized operator also sees a 503
setup-in-progress response. Repeat these checks after the real stack is installed.

### Authoritative inventory so far

The initial read-only inventory found 5,520 accounts and 5,571 local channels.
The later consistent PostgreSQL dump restored successfully in an isolated clone:
**5,521 accounts**, **5,572 local channels** and **15,492 local videos**.
The extra account/channel reflects continued source writes during rehearsal.
Another 44,978 videos are federated
cache records. The snapshot contains **11 active MFA-enrolled accounts**; all
eleven imported accounts are held inactive until target re-enrollment. Repeat
the hold check after each source-authoritative resync and before application access.
The sole imported administrator is among those held accounts. The target has no
instance owner or owner-claim row, so private operator bootstrap is still required;
do not reset or reactivate an imported account merely to obtain rehearsal access.

Local video-file metadata totals **4,260,245,274,200 bytes** across 85,219 HLS
and 1,927 progressive rows. Exhausted B2 version pagination found **223,313
live objects**, totaling **4,171,350,894,839 bytes**, across the configured
HLS, progressive and caption prefixes. These independent totals differ;
metadata rows are not object counts. Reference reconciliation identified
unavailable source assets. The operator confirmed the affected cohort was
intentionally purged: preserve its restrictions and record unavailable media;
do not recover those bytes. The exact snapshot, affected IDs and owner decision
are retained privately. This does not waive unrelated missing or failed assets.
Playlist dependencies, artwork and available bytes still need full reconciliation.

Exact filesystem checks found 12,706 unavailable storyboard references outside
the confirmed purge, plus one playlist-cover thumbnail. PeerTube 8.3.1 treats these local
storyboards as direct files: their rows have no remote URL, and the serving path
does not regenerate them. Recover or regenerate the non-purged assets on beta
and verify their playback integration; do not extend the purge exception.
The [read-only fallback](https://github.com/yegamble/vidra-core/pull/467) and
[complete mixed-storage wiring](https://github.com/yegamble/vidra-core/pull/468)
are merged. A read-only local capture transferred 83,574 files, totaling
8,021,627,453 bytes, to restricted beta staging with matching per-file hashes.
The source-built resume carried all four available local progressive files,
including the private subdirectory; independent exact-version B2 reads matched
their complete source SHA-256 values. This proves that slice, not candidate playback.

A beta-only walk of nine mixed-storage masters found nine required variant
playlists unavailable across six masters. Both B2 path forms returned 404;
the recorded history contains no recovery versions, and the local capture has
no matching files. The eight B2 master versions remain unchanged since inventory.
Other media dependencies exist for the affected videos, but decoding and repair
remain unproven. Missing playlists also hide their descendant dependencies;
do not call nine a complete count of missing media or waive them as purged.

Two missing local progressive references are a separate snapshot-drift case:
both videos were still transcoding in the dump. Read-only current production
checks show both now published with HLS records and without those old web-file
rows. Refresh or apply a controlled delta; do not classify the obsolete files as
lost published videos or pretend this is a matched media freeze.

The database has zero retained-original filename rows, and the configured
`original-video-files/` prefix has zero provider versions. The configured local
originals directory also contains zero files. This source therefore supplies
no positive retained-original acquisition case; keep the upstream/native-original
regressions separately. Local storage additionally contains progressive/HLS
files and artwork that must be captured and reconciled independently of B2.

The source bucket is public, hidden versions expire after 30 days and object
lock is absent. A version manifest alone is not an immutable recovery copy.
The approved private beta bucket is created. A live probe verified a bucket-scoped
read-only source key, a separate destination-only writable key, destination
write/read/delete and anonymous denial (401). These temporary keys expire
**2026-12-03**; rotate them if rehearsal continues beyond that date. The original
unrestricted credential stays on production. A separate private B2 backup bucket
uses a thirty-day bucket-only read/write key without delete permission, retained
separately in operator recovery storage. The operator selected the current B2
account for rehearsal. Encrypted source-DB and preparation-config archives passed
provider checksum and complete authenticated read-back verification; anonymous
access returned 401. This does not prove target-media recovery or cross-region
recovery. Raw snapshots, account details,
credentials and object manifests stay outside Git with restricted permissions.

The root-only database archive is 253,567,950 bytes and restored from PostgreSQL
18.6 at schema 1130 without publishing a database port. This proves a source
clone restore, not Vidra recovery or a matched DB/config/media capture.
The running COPY resume uses merged core `b59b14c3` and embedded schema 183;
it is source-built preparation, not published-candidate acceptance. The prior
process was stopped gracefully, all eleven MFA holds were verified, and the
new dry-run left target counts unchanged. One importer resumed from the existing
ledger using the completed local capture; 55 completed HLS records survived the
handoff. All 5,521 users and 5,572 channels have imported. Media work and its
exception report are incomplete. No candidate playback or replacement-host
restore is accepted yet.

One official PeerTube ZIP was generated offline from the isolated source clone.
Native metadata, captions and actual artwork passed independent checks; its
muxed video and audio decoded completely with encoded packet payloads preserved.
Importing that archive into the published Vidra candidate, persisted read-back
and owner/job isolation remain open.
The released ZIP path is synchronous metadata import. Media ingestion and an
asynchronous ZIP-import job are not supplied by that path; an account-export
job test must not be presented as proof of either capability.

### Current production gate board

| Gate | Current state | Evidence still required |
|---|---|---|
| Importer compatibility | Merged; unreleased | Exact published images, embedded schema maxima and release pins |
| Source snapshot and bytes | DB clone restored; source purge disposition recorded | Matched immutable DB/config/media inputs and full available-reference/hash reconciliation |
| Private beta | Restricted maintenance edge and TLS verified; no application deployed | Install exact candidate and repeat route/direct-port/access proofs |
| COPY and repeat | Source-built preparation running; candidate acceptance open | Stable identities, restrictions, asset hashes, repeat and explicit exception dispositions |
| Playback and new publication | Not run on candidate | Source-disconnected decoded browser playback and scanned multi-chunk upload/transcode |
| Search recovery | Receiver implementation merged; producer integration open | Complete paired-runtime observations, safe compatibility fallback and full eligible-ID set equality after outage |
| Media and sealed recovery | Encrypted source DB/config B2 read-back verified | Candidate media restoration on empty replacement host, correct/wrong-key tests and measured RPO/RTO; cross-region recovery unproven |
| Installation | Conservative defaults merged; generated configuration verified | Actual scanned hardware-floor run and three unfamiliar-human timed trials |
| ZIP import | Official source archive generated and decoded | Candidate import, persisted results and owner isolation |
| English usability | Required | Accurate preview effects, reachable recovery states, mobile and accessibility proof |
| Security dispositions | Candidate proof open | Fresh exact-digest/dependency evidence and accountable residual-risk dispositions |
| Final origin and rollback | Open | Private owner bootstrap, MFA re-enrollment, old URLs/identity, final freeze/delta and preservation of new Vidra writes |

The operator explicitly selected **English only**. Native French review and
full French UI-copy extraction are excluded from this cutover's requirements.
Existing locale infrastructure is retained; English usability and actual human
installation trials remain required. Historical records are not new acceptance.

## 1. Inventory the authoritative source

Capture a database snapshot and source configuration without changing the
running instance. Record the snapshot time and SHA-256, actual schema marker,
accounts, channels, local videos, privacy/moderation states and source MFA.
Separate local content from federated records when reconciling totals.

Inventory originals, HLS manifests and every dependency, captions, posters,
storyboards and actor artwork by object count, bytes and location. PeerTube's
retained upload originals are separate from playable HLS and may be separate
from `videoFile` progressive downloads. Record mixed local/S3 storage, custom
prefixes, unavailable objects and objects beyond importer limits.
Keep a media snapshot or immutable version manifest aligned with the database
snapshot. Reading newer live storage or HTTP artwork against an older database
can mix revisions while PeerTube continues accepting writes.

List required workflows: login, moderation, quotas, old watch/embed links,
search, creator uploads, current custom categories, branding, plugins and
advertising customizations. Imported data does not reproduce plugin behavior
or all instance configuration. Agree which workflows are required for cutover.

## 2. Prepare the isolated DigitalOcean candidate

Use a separate Ubuntu 24.04 host, database, media bucket and keys. A planning
candidate is **4 vCPU / 16 GB RAM**, with one transcode at a time and sufficient
scratch space. Verify regional availability and current pricing before
provisioning. The [sizing guide](../deploy/README.md#sizing) explains memory and
scratch needs; its historical prices are not a current quote.

Set CPU/memory limits for the selected host; the shipped larger-host CPU
defaults cannot be used unchanged on four cores. Retain healthy ClamAV for
scanned-upload acceptance. Use the production Compose overlay and Caddy TLS,
with public access limited to HTTP/HTTPS and administration restricted. Verify
that Postgres, Redis and search publish no ports.

Use `https://beta.sizetube.com` consistently for public/API/CORS origins.
Restrict access to rehearsal operators, close registration and prevent search
indexing. Apply access restrictions to every frontend, API, media and lazy-static
route before importing private data. Verify Caddy's TLS challenge handling while
application routes remain restricted. Pause outbound mail, federation, IPFS,
channel sync and destructive
media jobs during import. Configure and test an HTTPS mail provider separately;
DigitalOcean blocks standard outbound SMTP submission ports.

Keep encrypted database/config backups with a separate provider and region, and
preserve recovery keys separately. Media recovery requires its own copy/versioning policy;
database and configuration archives do not contain object-store media.

## 3. Qualify compatibility and freeze a release

Qualify schema 1130 against a real upstream-created database and the selected
source snapshot. Preserve the refusal for later unknown schemas. Verify
retained-original handling independently of HLS playback, including missing
bytes, retries and repeated imports.

Publish the reviewed compatibility changes as a new coordinated release.
Record component commits, bundle, image digests and schema maxima, then run
artifact preflight and the required CI set. Install those immutable artifacts
on beta; do not use floating `main` or manually advance release-pinned nested
checkouts. Update the runbook's release-specific statements only when that
release exists.

## 4. Rehearse COPY and prove independence

Restore the snapshot to a source database with a SELECT-only importer role.
Use read-only source-media credentials or mounts and a separate writable
destination. Keep the source HTTP artwork origin available while acquiring
avatars, banners and any HTTP fallback assets.

Run preview, review every exception, then COPY. Reconcile identities,
relationships, restrictions, asset counts and SHA-256 values. Repeat against
the same import ledger and verify stable IDs without duplicate catalogue rows.
Treat missing media and unsupported families as explicit unresolved outcomes,
even if the job reaches `done`.

Disconnect source database, storage and HTTP access. In real browsers, verify
public/private HLS-only playback, separate audio, seeking, captions, chapters,
storyboards, login and access controls. Verify retained-original downloads
separately. Test a new scanned upload through transcode and search.

Exercise a search outage during publication, then verify indexed results after
the outbox drains with no dead letters. The open
[search reconciliation defect](https://github.com/yegamble/vidra-core/issues/267)
means healthy-startup search results alone are insufficient.

Restore database/configuration **and media** onto an empty replacement host,
including sealed-secret recovery and authenticated private playback. Measure
import duration, transfer cost, scratch use, recovery time and acceptable data
loss from actual results.

## 5. Approve and execute production cutover

Use beta as a disposable rehearsal. Its different hostname does not prove
same-domain federation continuity, and its activity does not automatically
merge back into PeerTube or into a fresh production candidate.

Define the final same-domain installation, source-MFA holds/re-enrollment,
actor-key/follower handling, URL redirects, maintenance window and rollback
owner. PeerTube MFA enrollment is not preserved automatically; hold affected
target accounts until approved re-enrollment. Freeze PeerTube writes, refresh
the snapshot/media and perform final
reconciliation. Repeated import is not complete synchronization of deletions,
restrictions and changed assets.

Switch traffic only after the final candidate passes acceptance. Retain the
frozen PeerTube instance and its media for the agreed rollback window. Define
how to preserve writes accepted by Vidra before a rollback: DNS reversal cannot
merge those writes back into PeerTube.

## Remaining project work

The migration-critical work is source compatibility, representative COPY,
media recovery, same-domain identity/URL checks, degraded-search recovery and
qualification of the release actually deployed. Current-main CI success is
useful evidence, but does not close these runtime gates.

Broader completion work remains: human blank-host installation measurements,
security finding disposition, English usability and representative per-user
ZIP import. French certification is excluded by the operator's scope decision.

The full mechanical inventory was rerun on **2026-11-03** with
`--strict-migrations`, core checkout `88409417` (API and migration inputs
identical to main `07ddf1b0`) and frontend main `4f4f0b01`. It reports **zero
failures and zero migration findings** after auditing schema 183. That migration
adds a helper function and repairs cached inbox values, with no new tables.
The recovery catalogue now records that reviewed empty table inventory;
schema 184 remains refused. This supplies no schema-183 recovery drill or
production acceptance. The older six-endpoint inventory is superseded by this
current static result under the scanner's present policy.

The same frontend lockfile was audited under Node **26.12.0** and npm
**11.20.0**. Non-dev dependencies report **zero advisories**; the full tree
reports **17 moderate, zero high and zero critical** findings. The repository's
unchanged dependency policy passes, examining **714 packages** against its
400-package floor. These are current source-lockfile results, not a scan of a
deployed image. No dependency versions or lockfile entries were changed.
