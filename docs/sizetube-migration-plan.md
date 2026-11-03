# Planning the SizeTube migration through a private beta

Planning date: **2026-11-03**. The operator selected a **private migration
rehearsal first** at `beta.sizetube.com`, hosted on DigitalOcean.
`sizetube.com` continues serving PeerTube throughout rehearsal.

**Production remains NO-GO.** This plan is not a deployment record. No
production database, media bucket or DNS record was changed for this review.
The current [qualification record](release-readiness.md) and
[PeerTube migration runbook](peertube-migration.md) define the acceptance gates.

## Current findings

The public SizeTube configuration reports **PeerTube 8.3.1**, split-audio HLS
enabled and web-video generation disabled. Upstream 8.3.1 targets schema
**1130**, while the released Vidra **v0.7.8** importer accepts **700–1040**.
Confirm the actual marker from a restored source snapshot; the public version
does not prove the deployed database's state. Do not rewrite its marker or
acknowledge an unsupported version to make an automated rehearsal proceed.

The newer importer compatibility work must be merged, published and pinned
before it can replace the released baseline. Source tests and a disposable
upstream fixture do not supply representative SizeTube migration acceptance.
The existing synthetic B2 rehearsal is useful evidence within its
[explicit limits](runtime-acceptance-b2-migration-v0.7.8.md).

The beta hostname currently resolves, but public HTTPS version/readiness probes
timed out during this review. Identify the intended host and DNS ownership
before installation; an old beta address is not proof of a usable candidate.

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
security finding disposition, full UI-copy extraction/native French review,
representative per-user ZIP import, and refreshing the endpoint inventory after
the newer scanner policy. Older six-endpoint findings must not be repeated as
six current missing product features without rerunning that inventory.
