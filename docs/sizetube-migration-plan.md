# Planning the SizeTube migration through a private beta

Planning date: **2026-11-03**. The operator selected a **private migration
rehearsal first** at `beta.sizetube.com`, hosted on DigitalOcean.
`sizetube.com` continues serving PeerTube throughout rehearsal.

**Production remains NO-GO.** A published beta API and the released frontend now
serve an operator-IP-only read trial. The target migrated cleanly to schema 188;
one source-built COPY continuation is still preparation work. Production
database, media and DNS remain unchanged. The
[2026-11-04 trial record](evidence/sizetube-private-read-trial-2026-11-04.md)
separates the observed passes from the remaining acceptance gates.
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
and are included in the published beta-only CORE image described below.
The image contains no standalone importer: the running COPY binary remains
source-built, and the coordinated release/bundle and production pins remain open.
Source tests and a disposable
upstream fixture do not supply representative SizeTube migration acceptance.
The existing synthetic B2 rehearsal is useful evidence within its
[explicit limits](runtime-acceptance-b2-migration-v0.7.8.md).

The new `sizetube-beta` droplet is provisioned in DigitalOcean NYC2:
Ubuntu 24.04, 4 vCPU, 16 GB RAM, 200 GB disk, quoted **$84/month** at creation.
Docker and Compose execute successfully. Beta DNS now points to the new host.
The Caddy edge has a trusted certificate and restricts application routes by
transport remote IP. The operator receives the homepage and exact runtime
version over HTTPS; non-operator and spoofed-forwarding probes return 403.
Host/gateway access is limited to `/healthz`, now 200. The trial permits
GET/HEAD/OPTIONS and exact POST login/refresh/logout routes; other mutations and
real HTTP/1.1 WebSocket upgrades return 403. No app, PostgreSQL or Redis port is
published. Responses carry noindex and no-store. This narrow trial disables
workers, mail, federation, search integration, scanning and ingestion; it does
not qualify those features.

### Authoritative inventory so far

The initial read-only inventory found 5,520 accounts and 5,571 local channels.
The later consistent PostgreSQL dump restored successfully in an isolated clone:
**5,521 accounts**, **5,572 local channels** and **15,492 local videos**.
The extra account/channel reflects continued source writes during rehearsal.
Another 44,978 videos are federated
cache records. The snapshot contains **11 active MFA-enrolled accounts**; all
eleven imported accounts are held inactive until target re-enrollment. Repeat
the hold check after each source-authoritative resync and before application access.
The sole imported administrator is among those held accounts. A reviewed host
repair seeded only a pending token hash, then the shipped claim flow created a
new beta-only owner. Imported-user, actor-key, ledger and block fingerprints
remained identical across migration and claim; none of the imported accounts
was reset or reactivated. The beta owner is excluded from source reconciliation
and is not production ownership.

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

The quiesced pre-migration point `20261104T043744Z-866a4441` and schema-188
beta-operator point `20261104T045318Z-ad90e914` are stored in that private backup
bucket. Each DB/config/encrypted-manifest triplet passed provider checksums and
complete authenticated exact-version SHA-256 readback; anonymous access returned
401. Both DB and config streams also decrypted under the operator-held key with
their original stream hashes, without persisted plaintext or the private identity
on beta. These are partial-media checkpoints, not a full matched recovery point.
The first 250 immutable primary-to-backup mappings, totaling 100,853,238 bytes,
also passed full byte verification. The observed plan still has 5,317 other
eligible objects and one deferred 16,527,038,005-byte object; later COPY writes
are outside that plan. Full media backup and replacement-host restore remain open.
The current account is authorized for this rehearsal; cross-region recovery
remains outside the demonstrated evidence.

The root-only database archive is 253,567,950 bytes and restored from PostgreSQL
18.6 at schema 1130 without publishing a database port. This proves a source
clone restore, not Vidra recovery or a matched DB/config/media capture.
The COPY binary remains merged core `b59b14c3`, source-built preparation. It was
stopped by signalling only its positively identified child; the wrapper exited,
all eleven MFA holds passed, and no target connections remained before the
encrypted checkpoint and discrete migration. The published API image's embedded
maximum and the independent source maximum are both 188; the ledger is clean
and all 24 transactional dirty triggers are present. A source/schema review and
an actual schema-188 dry run passed before one continuation resumed. The old
run record is retained. All 5,521 users and 5,572 channels have imported; media
and the final exception report remain incomplete.

At **2026-11-04 04:48 UTC**, the paused target had 462 ready HLS entries and 31
failed ledger entries. These are observations, not final exception dispositions.
A 13-failed-HLS investigation found all 169 discovered source dependencies still
present by exact immutable ID/size; 91 frozen playlist bodies also passed the
actual old parser. The discarded original I/O errors remain undiagnosed; do not
waive these failures as purged. The two obsolete progressive references still
require the controlled source refresh described above.

The exact beta API served a ready public HLS master and decoded 60 video frames
(1,966,667 microseconds) through its private API origin with no source credential
in the app, no media saved and no HTTPS enabled in the decoder. Browser
homepage/navigation also rendered. This is one short host-decoder
sample, not browser playback, separate-audio/seek/caption coverage, a whole-corpus
deep verification, or a source-disconnected rehearsal.

One official PeerTube ZIP was generated offline from the isolated source clone.
Native metadata, captions and actual artwork passed independent checks; its
muxed video and audio decoded completely with encoded packet payloads preserved.
An isolated diagnostic using cached published CORE v0.7.8 passed synchronous
metadata import of that actual archive: channel, private playlist and settings
persisted across API replacement, repeat import created no duplicates, and
cross-user reads/writes were refused. Its carried video and captions were
explicitly skipped; no video or caption rows were created. The released ZIP
path supplies neither media ingestion nor an asynchronous ZIP-import job.
A separate account-export job persisted across process replacement and returned
identical downloads while its storage stayed continuously mounted. This does
not prove volume remount or host recovery. The initial failed run is preserved:
stopping both processes released the last tmpfs mount and lost export bytes.
Repeat the supported tests on the eventual published candidate with its actual
storage and scanner; these diagnostic passes do not qualify that candidate.

### Current production gate board

| Gate | Current state | Evidence still required |
|---|---|---|
| Importer compatibility | Beta API published at frozen digest; standalone COPY remains source-built | Coordinated operator artifacts/bundle, release pins and actual candidate COPY acceptance |
| Source snapshot and bytes | DB clone restored; source purge disposition recorded | Matched immutable DB/config/media inputs and full available-reference/hash reconciliation |
| Private beta | Operator-only read trial running; runtime version, readiness body and edge/access checks passed | Full application and ingestion acceptance on the selected release |
| COPY and repeat | Source-built preparation running; candidate acceptance open | Stable identities, restrictions, asset hashes, repeat and explicit exception dispositions |
| Playback and new publication | One short host-decoded HLS sample; browser homepage rendered | Source-disconnected browser playback and scanned multi-chunk upload/transcode |
| Search recovery | Receiver implementation merged; producer integration open | Complete paired-runtime observations, safe compatibility fallback and full eligible-ID set equality after outage |
| Media and sealed recovery | Two target checkpoints decrypted; first 250 backup objects byte-proven | Full media map/copy, strict empty replacement-host restore, actual imported-key correct/wrong-key proofs and measured RPO/RTO; cross-region recovery unproven |
| Installation | Conservative defaults merged; generated configuration verified | Actual scanned hardware-floor run and three unfamiliar-human timed trials |
| ZIP import | Official source archive generated and decoded | Candidate import, persisted results and owner isolation |
| English usability | Required | Accurate preview effects, reachable recovery states, mobile and accessibility proof |
| Security dispositions | Candidate proof open | Fresh exact-digest/dependency evidence and accountable residual-risk dispositions |
| Final origin and rollback | Beta-only owner claimed; production design open | MFA re-enrollment, same-domain URLs/identity, final freeze/delta and preservation of new Vidra writes |

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
That is historical schema-183 static evidence. The recovery catalogue has since
been extended through schema 188, and the
[strict restore option](https://github.com/yegamble/vidra/pull/350) now refuses
media inconsistencies or an absent exact dependency-verification marker before
app startup. Neither change supplies an actual schema-188 replacement-host drill
or production acceptance. Rerun the mechanical inventory against the final
frozen component set.

The same frontend lockfile was audited under Node **26.12.0** and npm
**11.20.0**. Non-dev dependencies report **zero advisories**; the full tree
reports **17 moderate, zero high and zero critical** findings. The repository's
unchanged dependency policy passes, examining **714 packages** against its
400-package floor. These are current source-lockfile results, not a scan of a
deployed image. No dependency versions or lockfile entries were changed.
