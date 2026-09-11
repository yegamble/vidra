# Packaged v0.6.4 migration and restart execution — 2026-09-11

**NO-GO for the unchanged full release scope.** The generated-source COPY
milestone passed through the released setup CLI, deployment scripts, admin UI,
import worker and real B2/search services. No application binary was rebuilt or
replaced. This extends [PR #186](https://github.com/yegamble/vidra/pull/186), which
is **merged**, at `67840abed3c7181703d7bd17b1b7800cf78a9702`.

Workflow counts remain **2 PASS, 45 UNVERIFIED, 12 BLOCKED**. Of the 40 A-items,
only the previously accepted A01 and A02 are fully passed for this candidate;
38 remain unclosed. These new subsets do not close MIG-01–06/A18–23 or recovery.
All original workflow procedures, A-items, ten scope families and approved
provider deferrals remain authoritative. See the
[continuation disposition](evidence/release-v0.6.4-verification/migration-runtime/disposition.json).

## Candidate and execution boundary

The [immutable manifest](evidence/release-v0.6.4-verification/manifest.json) is
unchanged: core `ed55a6d`, user `e584069`, search `1f8b854`, released meta
`0da1846`; images are the same recorded digest references. The API executable
extracted from that exact running image has SHA-256
`0ec31451232a5869d11a54212f73f0c175e561e04ed5b6f5f5b3c29a087ba90a`
and embedded Go **1.27.1**. The released CLI hash and 14 shipped deployment-file
hashes were independently verified. The only deployment adaptations were the
existing digest pins and temporary read-only source mount/`PEERTUBE_*` settings.

Live component mains were newer than the release: core `0261b59`, search
`5f7a3a3`, user `dc4f164`, site `7f9f7bf`; these are **not** the runtime candidate.
The component releases remain v0.6.4. The meta repository's latest GitHub
release entry remains v0.5.0; v0.6.4 CLI/bundle artifacts are published in core.
No next version or promotion was selected by inference from the old report.

The retained B2 host `159.203.118.182` (droplet 599531580), Ubuntu 24.04 AMD64,
was reused without wiping it. The earlier upload and evidence remain present.
Chromium 153.0.8010.12 / Playwright 1.63 / Node 26.8.1 ran inside that host at
the isolated origin `https://secure.video.test`. This is desktop Chromium
evidence, not WebKit, Safari, iOS, mobile or independent human usability proof.
The default inline worker, real search and fail-closed ClamAV were retained.
No rate limits were disabled. Both retained acceptance hosts are accessible;
local Docker is running on ARM64. This is an execution-capable session.

SSH access initially failed because the test firewall allowed the former
workstation address. The session added only TCP/22 from `185.244.215.14/32` to
the existing acceptance firewall, retaining the old rule. No DNS, public web
ingress, production resource or public federation traffic was changed.

## Executed evidence

Source inputs are copies of the previously generated PeerTube **8.0.0 / schema
970** fixture. The 323,141-byte dump and 75,002,357-byte media/config archive
match the hashes in [the retained fixture record](evidence/a18-a23-peertube-fixture.json).
Their originals were not modified. Explicit operator approval authorized
transfer to this host after automatic approval review initially refused it.
Source configuration/logs were excluded from extracted media. The source DB
was restored into a new private container; the importer received a SELECT-only
role and a read-only media mount.

This is **seven generated eight-second 640×360 videos**, six users/channels,
progressive/HLS-only/private/password/unlisted/blocked/split-audio cases. The
split-audio tree is a generated compatibility fixture. There are no source
actor images, custom categories or preexisting remote followers. It does not
establish representative source fidelity, scale or production cutover.

| Procedure | Newly executed result and retained proof |
|---|---|
| Shipped operator path | Released `vidra setup` → released `deploy.sh` → admin `/admin/import-peertube`. No standalone importer or development build. [Preparation](evidence/release-v0.6.4-verification/migration-runtime/prepare-ready.json) |
| Source access | Read-only role refuses a read-write transaction's UPDATE with permission denied; source media mounted `:ro`. Non-PeerTube configuration preserved. |
| Preview | Admin clicks Preview; real worker completes schema 970 dry-run; plans six users/seven videos; catalogue counts unchanged. [Original preview](evidence/release-v0.6.4-verification/migration-runtime/preview-browser.json). This run predates the stronger content-fingerprint assertions. |
| Import | Admin clicks Start import; worker completes **13:15:23.673517–13:15:32.602635 UTC (8.929 s)**. Six users/channels, seven videos, five originals, six HLS playlists, four comments, one caption, two chapters, twelve tag links and the fixture relationships imported; zero failed/no-media counts. [Run](evidence/release-v0.6.4-verification/migration-runtime/import-browser.json) |
| Repeat | Two separate zero-change repeats. The strengthened repeat checks all thirteen catalogue/media tables by full-row aggregate fingerprints, validates run mode/counters, and compares every displayed report cell after reload. No imported/updated entities. [Repeat](evidence/release-v0.6.4-verification/migration-runtime/repeat-v4-browser.json) |
| Schema guard | Change only clone's version marker 970→1040; actual UI preview fails `unverified_schema`, no acknowledgement, controls disabled after reload, thirteen table fingerprints unchanged. Restore marker 970. This tests the marker guard, not a genuinely newer schema layout. [Refusal](evidence/release-v0.6.4-verification/migration-runtime/schema-refusal-browser.json) |
| Reconciliation | Seven source UUID/title/privacy mappings; per-video original/HLS/caption assignment; **30 distinct B2 downloads byte-equal to source**: five originals, 24 HLS dependencies, one caption. Thumbnails/storyboards are counted but not byte-qualified here. [Successful fourth attempt](evidence/release-v0.6.4-verification/migration-runtime/reconcile-v4.json) |
| Search delivery | Import's actual `reconcile.begin/page/end` outbox events delivered and received by real search; exactly three eligible public imported IDs indexed/returned. No preseeded index rows. Same reconciliation proof above. |
| Browser search | Type query in actual search control; service success counter **4→5**; exactly three public fixture results; click HLS-only result and reload. [Search](evidence/release-v0.6.4-verification/migration-runtime/search-browser.json) |
| COPY independence | Released setup disables integration, source DB stopped, media unmounted, same released deployment succeeds. [Disconnect](evidence/release-v0.6.4-verification/migration-runtime/disconnect.json) |
| Disconnected decode | Admin browser plays progressive, HLS-only and split-audio from B2: each advances >2.88 s with increasing frames/audio bytes, unmuted, no media error. Private/password/unlisted/blocked playback and caption UI remain required. [Playback](evidence/release-v0.6.4-verification/migration-runtime/playback-browser.json) |
| Host restart | Real reboot changes kernel boot ID. Separate post-readiness check compares identical full-row fingerprints for thirteen tables and clean ledgers **146 / 18**. Subsequent owner login, decoded playback and search pass in the [restart supplement](evidence/release-v0.6.4-verification/migration-runtime/restart/summary.json). This is restart persistence, not replacement-host restoration. |

Screenshots and exact commands/exits/timestamps are in the evidence directory.
Health outputs are represented by hashes; raw logs, DSNs, credentials, hashes of
account passwords and private actor keys are excluded. The first export's
literal PEM-marker test rejected its own scanner source; a regression now
distinguishes marker literals from PEM content. The refused export remains
private. The successful pre-restart export SHA-256 is
`03902df83225c3cd0539a3dc366c737473e1de34871409f733653591fdf9ea5d`.
The separate restart export hash is
`552d1048f9bbf4a857ccee6bb0069365a1db03c736e7deb35f75f647972b241a`.
The recovered data point is the pre-reboot thirteen-table snapshot; the interval
to the successful comparison was **208.873 seconds**, an observed upper bound
including scheduling and investigation of the early health refusal. This is
not a precise minimum RTO. Approved candidate RPO/RTO were not supplied, so no
recovery-objective acceptance is claimed.

## Failures retained and harness corrections

None of these failed attempts was overwritten or relabelled PASS:

1. Original preparation's UPDATE was refused, but the harness expected a
   different read-only error and misleadingly reported “source role could
   write.” The corrected explicit read-write transaction also receives
   permission denied.
2. Continuation preparation matched the nested prep-volume indentation as
   well as the shared volume anchor. Anchored matching plus regression permits
   exactly one additional read-only mount and preserves existing volumes.
3. First reconciliation counted thumbnails/storyboards as originals. The
   regression requires exactly five `kind=original` rows while retaining all
   metadata. The second and third reconciliation attempts assumed individual
   `video.upsert` events; the released importer actually emits a full reconcile
   sweep. All failed JSON and original tool revisions are retained.
4. The first post-reboot snapshot correctly refused an unready ClamAV service.
   It later became healthy with no configuration change; the separate ready
   snapshot proves data preservation. No recovery target was invented.

A fresh-context verifier reviewed the harness and operator path, independently
ran local syntax/unit checks, and identified weak aggregate/media-association,
report/UI, repeat-table and disconnect-prerequisite assertions. These were
strengthened before the corresponding supplementary runs. The verifier did
not operate the host; no independent human usability claim is made.

## CI and security observations

The newer search workflow is valid and creates a real job. Its
[successful run](https://github.com/yegamble/vidra-search/actions/runs/34485406355)
explicitly **did not execute the ahead-schema probe**: HEAD and v0.6.4 both
embed migration 18. The [log review](evidence/release-v0.6.4-verification/migration-runtime/search-floor-review.json)
preserves that distinction. It does not turn the historical zero-job failure
or release rollback acceptance into PASS. No workflow/gate repair is claimed
by this PR; failure propagation, all required scans and exact-candidate gates
remain required.

Final local gates passed: **98 Python tests, zero skips**, JavaScript syntax,
four Python AST parses, production Compose validation with dummy values and
diff whitespace checks. No shell script changed. Commands, timestamps, exits
and log hashes are in [local verification](evidence/release-v0.6.4-verification/migration-runtime/local-verification.json).

Four [govulncheck records](evidence/release-v0.6.4-verification/migration-runtime/security/summary.json)
retain scanner **v1.3.0**, fresh database timestamp **2026-09-10 14:48:42 UTC**,
all findings and a scanner incompatibility error. The source scan using the
workstation's Go 1.26.2 reports reachable stdlib advisories; that is not the
published Go 1.27.1 binary. With scanner and target toolchain both Go 1.27.1,
the exact API source reports one module-level OpenPGP advisory and zero affected
imported packages/reachable symbols; its package graph contains no OpenPGP.
The stripped-binary scan emits OpenPGP wildcard findings. Both results remain
reviewable, with no suppression or security exception. This is not a clean
full-image scan: search/CLI/frontend/OS packages, JS checks and gating remain
UNVERIFIED. JSON-mode exit zero alone is not a security verdict.

## Remaining execution backlog and operator inputs

| Type | Criteria | Next concrete work or missing input |
|---|---|---|
| Operator documentation defect, corrected in this branch | MIG-01 / A18, REL-01 | Review the supported packaged path in `deploy/README.md`; current published bundle still contains its historical instructions. Qualification must use distributable corrected instructions. |
| Missing source input | MIG-01–06 / A18–23 | Approved representative sanitized source/snapshot location, inventory and domain/cutover requirements. Generated proof remains separate. |
| Specific credential-transfer approval pending | MIG-02 / A19 | Approve the five generated fixture passwords into the named private test-host file; no production credentials or old tokens. Without it, imported-password login/roles/suspension checks are unexecuted. |
| Missing execution evidence | MIG-02–06 / A19–23 | Collisions/Vidra-owned edits, public actor identity/images, interruption/resume, all private media/unauthorized cases, metadata ordering/dispositions, old links and isolated federation continuity. |
| Missing recovery input | A36–38, INS-04/05 | Approved independent restore destination/profile, required offsite transport/object, approved RPO/RTO. Retained original hosts cannot be wiped or used as replacement-host proof by restoring over them. |
| Missing execution evidence | OPS-01, A17/A34; A36–38 | Job leases/two-worker interruption, DB/Redis/search outages, failed backup, independent decrypting restore, supported upgrade/app rollback and incompatible-schema recovery. |
| Missing execution evidence and dependent provider inputs | Other required workflow rows, A03–17/A24–35/A39–40 | Continue the existing control inventory, negative cases, mobile/themes/keyboard/accessibility, WebKit and actual Safari/iOS separately; provider-specific cases wait only for their own approved inputs. |
| Missing implementation/execution | REL-01 / A39 | Fail-closed missing/zero-job gate regression, scan coverage/gating and exact release mapping preflight remain to be closed; no next candidate is frozen or qualified by these results. |

The host, copied source archives/media/DB, imported test catalogue, B2 objects
and private raw evidence are retained. B2 access remains restricted to
`vidra-acceptance-v064-20260911-media`; the seven-day key created September 11
expires September 18 (exact provider expiry was not re-queried). No Sizetube
production/live/backup data was read or changed. The original generated fixture
archives were read for their approved copies and were not modified or deleted.
Do not clean retained resources without explicit authorization.

Host tools and private evidence are under
`/root/vidra-v064-migration-20260911{,-continuation,-ready}`. Do **not** rerun
preparation over these populated directories. Future acceptance uses a new
attempt label and preserves the source-disconnected state unless reconnection
is the declared procedure. The test harness's Python/Playwright/Node tools are
acceptance prerequisites only; ordinary installation/import uses the released
CLI, deployment scripts and web application.

Merge, stable release publication, tag movement, production deployment/migration,
public DNS/federation, new infrastructure spending, host rebuilds and evidence
deletion remain unauthorized. This branch is open for review; nothing is merged
or published by this session.
