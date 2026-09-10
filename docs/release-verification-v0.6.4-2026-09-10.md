# Vidra v0.6.4 release verification — 2026-09-10

**NO-GO. The requested deployment and migration rehearsal is BLOCKED.** No clean disposable server matching Ubuntu 24.04 / Linux AMD64 was supplied or identified. No application workflow was executed in this rehearsal; no production deployment, traffic switch, source shutdown, public federation action or shared-lab mutation occurred.

The current published component release is **v0.6.4**, discovered during live registry/release inspection (published September 10, 12:08–12:14 UTC). The checklist's last release-image record names v0.6.3, which was checked first and is retained only as the previous-release baseline. v0.6.4 includes the subsequent authentication, HLS/private-copy and signer fixes. Their absence in v0.6.3 is **not** reported as a defect in v0.6.4.

The checklist's historical “59 PASS / all 40 closed” combines different source builds, release images, fixtures and provider deferrals. It does not certify this exact release on the requested target. This independent assessment applies every verification procedure without promoting historical or mocked success: **59 workflow rows: 1 static PASS, 57 BLOCKED, 1 UNVERIFIED**. **A01–A40: 1 PASS, 38 BLOCKED, 1 UNVERIFIED**. The ten decision-dependent scope families remain visible separately. Any required FAIL, BLOCKED or UNVERIFIED means NO-GO.

[Machine-readable assessment](evidence/release-v0.6.4-verification/assessment.json) retains all 59 verification procedures, all 40 acceptance criteria, all 10 scope families, blocker mapping, commands, exits, test names, checks, run/job URLs and artifact inventories. [Immutable manifest](evidence/release-v0.6.4-verification/manifest.json) records downloaded asset hashes, provenance, tooling and both image index and platform digests.

## Frozen candidate and checks that ran

| Repository | Released revision |
|---|---|
| vidra | `0da18462b009b3710ceac7e60d2e88653bebbc37` |
| vidra-core | `ed55a6d946dad3f2e72a47b2518ac095352c795d` |
| vidra-user | `e584069ee724b49af3d3f3d944efc34d3be6da75` |
| vidra-search | `1f8b85425e7d4dbb039edca56850282df9b93c6d` |

| Image | OCI index digest | Linux AMD64 manifest digest |
|---|---|---|
| ghcr.io/yegamble/vidra-core | `sha256:f653962115c8f36857e237b9e0ec9c95d89fef5b1f23cdcea75c20d1582f42a0` | `sha256:c0d41c276129f88d13668731954416dbba8884dd11476c86cd3f99fabebbe0c5` |
| ghcr.io/yegamble/vidra-user | `sha256:443336d4945365337e9459c270d51c80d1f62f9923ba80efffd3130389f814a3` | `sha256:a0a5b34f4bcd77e926d9cfc6de0ce23aacb2df20a01f4c0d4901f808c946625e` |
| ghcr.io/yegamble/vidra-search | `sha256:afcdb8a4bba86adfc7c64c4ea8a5e6edd8411fbc97c3f1a5f31dfb999dafb2cc` | `sha256:c8f49a5b8e2af91e99baf1120af120119a53766cb40bb4fe3bd7f81377a01488` |

All three registry indexes contain one runnable `linux/amd64` image plus an attestation manifest. They do not publish ARM64 service images. These are **registry/provenance observations**, not inspected containers on a deployed host.

- Documented `deploy/release-preflight.py --tag v0.6.4 --platform linux/amd64`: **exit 0**, four checks PASS: release assets and bundle provenance, frontend paths, byte-identical generated types, deliberate resolver-skew rejection. Node 26.8.1 / npm 11.19.0 / buildx 0.32.1. Four private detached source snapshots; no component checkout advanced.
- Released meta source: **47 checks PASS** comprising shell syntax/shellcheck, Node driver parsing, installer units, Python units, Compose render and required-secret refusal. Python: **48 executed, 48 passed, 0 failed, 0 skipped**. Installer log and per-command records are linked in the evidence. These fixture/unit results are not installation or application acceptance.
- Production Compose at the exact release: core/frontend/edge profiles, zero published datastore ports, API/frontend bound to loopback, both migrators volume-free and using their respective service image. Missing JWT exits 1 for the intended reason. Only **INS-03**, whose criterion explicitly allows static rendering, is PASS.
- Audit tooling at meta `d136982`: 64 Python tests pass with zero skips; shell/Node/installer checks pass. Initial Compose attempts lacked nested component paths and failed; temporary links to frozen release snapshots supplied the missing files, after which render/refusal checks passed. Initial failures remain in local evidence; those links were removed from the working tree. This diagnostic run is separate from released-meta evidence.

## Required tests: execution, omissions and revision limits

All unconditional check names in each released `.github/required-checks.txt` exist and concluded success on their respective source SHA. Conditional absent lanes were **not executed** and are not presented as proof. Job steps and logs were fetched, not inferred from the aggregate green badge.

| Exact-source CI evidence | Executed result | Limit |
|---|---|---|
| Meta `34473817340` | validate, bundle and boot executed; 48 Python tests / 0 skips | boot builds source; transcoding disabled and search integration unset |
| Core `34473452198` | 5,348 PASS markers; 6 registered SKIPs; 0 FAIL markers | markers include Go subtests; skipped RTMP plus five hardware-capability tests |
| Core IPFS `34473452234`, private `34473452255` | 7 / 51 PASS markers; 0 skips | isolated test networks |
| User `34424282838` | 2,679 unit tests; 632 mocked browser tests; 0 skips | mocked suite proves no deployed workflow |
| User `34424282808` | local 107 pass / 11 skip; S3 107 pass / 11 skip; channel-sync 2 pass; IPFS 3 pass; 0 final failures/flakes | builds core **1c2ea3ce94b018754732e9a28c87c680cf2f2a7d**, not released **ed55a6d**; S3 is a fixture |
| Search `34195815805` | 316 PASS markers; 0 skips | integration fixtures, not deployed upload-to-index proof |
| Search training `34195815801` | JUnit: 4 tests, 0 failures/errors/skips | synthetic training smoke |

Core/search untagged `make ci` and OpenAPI jobs executed successfully; their nonverbose output does not enumerate individual test counts, so no invented count is supplied. Core integration includes importer tests, but does not establish the requested representative-source rehearsal.

Each main browser lane skips ATProto, owner claim, PeerTube preview, channel sync, two quarantine tests, two registration-approval tests, two search-discovery tests and Whisper. Channel sync has its own successful two-test lane; the other omissions need their own current execution evidence. Allowlisted skips are still unexecuted tests. The optional-workflow source explicitly leaves search, registration approval, Whisper, ATProto and PeerTube unwired; no optional run on this frontend SHA was returned.

Search `rollback-floor.yml` runs **34475622088, 34402189473 and 34195814588** report **failure with zero jobs**, and their log retrieval fails. The conditional previous-migrator check never ran on this SHA. This is a recorded workflow failure and a recovery-evidence gap; its root cause was not established here. Successful required jobs do not certify a v0.6.3 → v0.6.4 upgrade or rollback.

## Blocking inputs and unperformed work

- **B1** — No available clean disposable Ubuntu 24.04 linux/amd64 server. Local host and Docker Engine are ARM64; existing test-runner VM inspection fails with No route to host. Existing machines and shared lab containers are not a blank acceptance host.
- **B2** — A prior generated PeerTube fixture and retained archive were located, but representativeness for all required source families and target scale is not established. It has seven short videos and no actor images, custom categories, plugins or preexisting remote followers. No operator source inventory, scale, source layout, retention or domain plan was supplied; no current import was executed.
- **B3** — Selected external integration endpoints and locally configured test credentials were not supplied: object bucket/presigned delivery, CDN, offsite retrieval, SMTP and identity provider. Local fixtures and simulator results do not establish selected-provider behavior.
- **B4** — No separate disposable restoration destination or agreed RPO/RTO, catalogue size/upload concurrency, and source/domain recovery plan. No fault injection, restart, backup/restore, upgrade or rollback was performed.
- **B5** — SCP-01 through SCP-10 retain their documented decisions; no additional family was silently waived or approved. Any launch-required undecided facet is BLOCKED.
- **U1** — Required CI jobs exist and report success, but exact-image end-to-end completeness is UNVERIFIED. Main browser lanes each skip 11 tests and build against a different core SHA. Meta boot disables transcoding and search. Search rollback-floor runs failed before producing any jobs/logs.

The pending input request asked for the release/server and representative source. With no reply, the latest published component tag is the explicit candidate assumption. No absent provider was silently disabled to produce a pass. A selected-provider run must also cover SMTP/IdP requirements where selected, beyond the four provider facets called out in the checklist.

**Setup/login/upload/real transcoding and browser playback/search/permissions/user and admin controls:** BLOCKED on B1. No fake ready state, preseeded index, API-only mutation or prior screenshot was substituted. Desktop/390px, themes, keyboard/axe, denied actions, persistent readback and fresh UI refetch all remain unexecuted.

**Migration:** dry-run, read-only role, unsupported-schema refusal, collisions/bcrypt login, repeat idempotency, interruption/resume, all entity counts/IDs/hashes, privacy, captions/images, source-disconnected decoding and outbox-to-search remain BLOCKED on B1/B2. A prior generated PeerTube 8/schema-970 lab and its retained archive were located read-only; its seven short videos and absent actor images/remote followers do not establish this source's representativeness or scale. No archive was deleted or copied into public evidence.

**Persistence and recovery:** container/host restart, API plus two-worker lease recovery, DB/Redis outages, search fallback and catch-up, backup plus independently restored DB/config/keys/media, post-restore login/playback/reindex and measured RPO/RTO remain BLOCKED on B1/B4. No restoration into the original destination is accepted as a replacement-host drill.

## Old-server and shared-storage dependencies

These are source/runbook findings, not measured elimination of dependencies:

- Copy mode still needs the read-only source DB plus accessible source media during import/delta/backfill. The release adds bounded copying of local HLS dependencies, but independence requires a completed hash/count reconciliation followed by disconnecting the source and decoding every required sample. External/nested HLS references are unsupported and must be surfaced, not silently skipped.
- Reference mode deliberately keeps original/video/HLS/caption keys in the shared canonical store. That bucket/filesystem and its read access must remain available; shutting down the old application does not remove the storage dependency. Foreign-object GC and retention need their own proof.
- PeerTube actor images, posters and storyboards need its local media tree or HTTP `lazy-static` origin during acquisition/backfill; a video bucket alone is insufficient. Unavailable image families are reported as deferred. Keep the source accessible until these counts and hashes reconcile too.
- Source DB/config/media archives, reports/blocklists/history/preferences/provenance and unsupported families require an agreed retained disposition. Existing generated-fixture archives retain their previous operator ownership and no-automatic-deletion rule. No real-source cleanup is authorized.
- Actor keys, domain/old links, preexisting remote followers and cutover/rollback need an isolated same-origin or explicit domain-move plan. This rehearsal made no DNS, traffic or public federation changes.
- The release Dockerfile ships `/app/api`, not the standalone `peertube-import` binary; the release assets also omit that executable. The documented CLI rehearsal therefore retains a source/toolchain dependency. The packaged admin/API import path must be exercised if it is the chosen operator procedure; no locally built replacement was represented as a release image.

## Full workflow disposition

B1–B5/U1 are defined above. Exact verification procedures are preserved in the JSON, so no control or rejection case is dropped by this compact table.

| ID | Required behavior | This rehearsal | Evidence / blocker |
|---|---|---|---|
| REL-01 | Compatible release sources, contracts and images | BLOCKED | B1 |
| INS-01 | Install on blank supported Linux host without developer tools | BLOCKED | B1 |
| INS-02 | One setup engine writes valid configuration and explains next steps | BLOCKED | B1 |
| INS-03 | Production Compose closes datastore ports and binds app ports locally | PASS | Static Compose assertions |
| INS-04 | First deploy migrates both ledgers before starting serving processes | BLOCKED | B1 |
| INS-05 | TLS/proxy/runtime URLs work at the installed domain | BLOCKED | B1 |
| AUTH-01 | Owner claim is exclusive, one-time and grants admin | BLOCKED | B1 |
| AUTH-02 | Registration, approval, login, logout and session refresh persist | BLOCKED | B1 |
| AUTH-03 | Email verification and password recovery deliver real mail | BLOCKED | B1, B3 |
| AUTH-04 | TOTP enrollment, recovery and removal; OAuth/OIDC login/link/unlink | BLOCKED | B1, B3 |
| AUTH-05 | Profile/privacy, email/password changes, deactivation/deletion and account archive | BLOCKED | B1 |
| PUB-01 | Create channel and draft; upload a real file within quota | BLOCKED | B1 |
| PUB-02 | Resumable upload, cancel, draft recovery and batch publishing | BLOCKED | B1 |
| PUB-03 | Transcode durable jobs into playable CMAF/HLS ladder | BLOCKED | B1 |
| PUB-04 | Schedule/quarantine/privacy gates survive processing and replacement | BLOCKED | B1 |
| PLAY-01 | Watch, seek, quality, speed, resume, PiP/theater and mobile/native playback | BLOCKED | B1 |
| PLAY-02 | Canonical/legacy links, sharing, embeds, oEmbed/feed/sitemap | BLOCKED | B1 |
| PLAY-03 | Private, unlisted, password, embed and download revocation | BLOCKED | B1 |
| CRT-01 | Studio edit/delete/taxonomy/tags/thumbnails/chapters/storyboards | BLOCKED | B1 |
| CRT-02 | Creator/channel/video statistics are accurate and scoped | BLOCKED | B1 |
| SRC-01 | Real outbox→search indexing→visible search result | BLOCKED | B1 |
| SRC-02 | Search privacy, retries, deletion and degraded fallback | BLOCKED | B1 |
| SRC-03 | Discovery, suggestions, trending, recommendations and history controls | BLOCKED | B1 |
| SOC-01 | Follow/subscriptions, saves, playlists and watch history | BLOCKED | B1 |
| SOC-02 | Comments/replies/ratings, mentions, reports and notification preferences | BLOCKED | B1 |
| MSG-01 | Plaintext DM timeline, retry/read receipts/delete/report and attachments | BLOCKED | B1 |
| MSG-02 | Approved 100 MiB / 30-file and office-document attachment behavior | BLOCKED | B1 |
| MSG-03 | E2EE device/session lifecycle and honest unsupported attachments | BLOCKED | B1 |
| ADM-01 | Users/roles/quotas/suspensions/signup approval with lockout guards | BLOCKED | B1 |
| ADM-02 | Reports, video blocks/quarantine, mutes, watched words and appeals/context | BLOCKED | B1 |
| ADM-03 | Runtime config, branding/legal documents and feature capability truth | BLOCKED | B1 |
| ADM-04 | Health/jobs/audit/infra/storage-GC dashboards reflect real operations | BLOCKED | B1 |
| MIG-01 | Source/version/storage preflight and truthful dry-run | BLOCKED | B1, B2 |
| MIG-02 | Accounts, roles, bcrypt login, channels and actor keys migrate safely | BLOCKED | B1, B2 |
| MIG-03 | Videos/media/metadata transfer produces independent playable catalogue | BLOCKED | B1, B2 |
| MIG-04 | Comments/playlists/tags/follows/ratings/chapters/views/taxonomy reconcile | BLOCKED | B1, B2 |
| MIG-05 | Omitted safety/user data and instance identity have explicit disposition | BLOCKED | B1, B2 |
| MIG-06 | Repeatable cutover, old links and federation continuity | BLOCKED | B1, B2 |
| STO-01 | Local/S3 canonical storage persists and serves valid media | BLOCKED | B1, B3 |
| STO-02 | Reference-mode foreign media is protected from garbage collection | BLOCKED | B1, B3 |
| STO-03 | Storage migration/copy/verification/abort and GC interlocks | BLOCKED | B1, B3 |
| INT-01 | Live RTMP ingest→HLS watch→replay with moderation | BLOCKED | B1 |
| INT-02 | Direct URL import, yt-dlp platform import and channel auto-sync | BLOCKED | B1 |
| INT-03 | Manual captions and Whisper generation/review | BLOCKED | B1 |
| INT-04 | ClamAV scanning actually gates all ingestion | BLOCKED | B1 |
| INT-05 | ActivityPub remote discover/follow/accept/video/comment/delete/moderation | BLOCKED | B1 |
| INT-06 | ATProto/Bluesky login, linking and outbound cross-post | BLOCKED | B1 |
| INT-07 | Public IPFS mirror and viewer fallback preserve disclosure boundary | BLOCKED | B1 |
| INT-08 | Private IPFS is isolated replication, never public delivery | BLOCKED | B1 |
| INT-09 | Presigned S3 browser delivery obeys CORS/expiry/authorization | BLOCKED | B1, B3 |
| INT-10 | CDN redirects, purge and versioned media remain correct | BLOCKED | B1, B3 |
| INT-11 | Noncustodial donation addresses verify and display honestly | BLOCKED | B1 |
| OPS-01 | API/worker split updates settings and recovers leased jobs | BLOCKED | B1 |
| OPS-02 | Health, logs/trace correlation, metrics/QoE and retention are useful | BLOCKED | B1 |
| REC-01 | Backup includes DB, settings/sealing keys and required media | BLOCKED | B1, B4 |
| REC-02 | Restore on replacement host yields usable accounts/media/search | BLOCKED | B1, B4 |
| REC-03 | Upgrade/rollback and dirty-schema recovery preserve data | BLOCKED | B1, B4 |
| QLT-01 | Contract/codegen/sqlc/tests remain reproducible and maintainable | UNVERIFIED | U1 |
| QLT-02 | All required screens handle keyboard/mobile/themes/errors and real persistence | BLOCKED | B1 |

## A-items and retained scope

| Acceptance item(s) | This rehearsal | Evidence / blocker |
|---|---|---|
| A01 | PASS | Four-repo immutable manifest; assets/contracts/codegen/skew preflight |
| A02–A38 | BLOCKED | No matching fresh host; source, provider and recovery prerequisites apply per exact criterion in JSON |
| A39 | UNVERIFIED | Required jobs executed, but skipped/missing runtime tests and companion revision mismatch remain |
| A40 | BLOCKED | Every required control needs deployed browser/role/persistence validation |
| SCP-01–SCP-10 | BLOCKED on undecided required facets | Existing deferrals retained; no silent launch-scope decision |
| A24/A32/A33/A37 provider facets | BLOCKED | Selected bucket, presign, CDN edge and offsite transport unavailable |

## Reproduction and continuation

The manifest and assessment are durable sanitized evidence. Raw logs, downloaded assets, detached snapshots and the read-only collection scripts remain at `/tmp/vidra-release-verification-20260910/v0.6.4`; v0.6.3 baseline evidence is its parent directory. GitHub run/job/artifact URLs, expiry dates and raw-log SHA-256s are in the assessment. CI artifacts currently exist with 14-day retention; preserve them before expiry if full traces are needed. Individual raw logs may contain synthetic test credentials and must not be published unreviewed.

Re-run the preflight with installed Node 26 and a new output directory:

```bash
python3 deploy/release-preflight.py --tag v0.6.4 --platform linux/amd64 --out /tmp/vidra-v064-new-preflight
# Re-fetch any recorded CI proof by its repository and run ID:
gh run view 34424282808 --repo yegamble/vidra-user --log
```

On a newly provisioned, disposable **AMD64 Ubuntu 24.04** host, use the frozen meta install script with `--yes --ref v0.6.4`, checksum-verified bundle/CLI, documented setup and `deploy/deploy.sh` sequence. Preserve before-state proof of no Docker/install tree, installation output, immutable images actually loaded, both migration ledgers and edge/version probes. The existing Multipass harness defaults to host architecture and cannot certify AMD64 service execution on this ARM64 workstation; do not accept emulation or preexisting containers as target-environment evidence.

Continue through each recorded criterion with real services and browser readback. Supply a representative sanitized source, selected provider endpoints with local test credentials, independent restore destination, retention/domain decisions and recovery objectives. Rehearse v0.6.3 → v0.6.4 with persisted data and the supported recovery paths; the runbook requires restoration for the older v0.6.2 rollback boundary. Preserve pre-deploy dump → pull → gated migrations → `up -d --no-build` → probes, checkout/ledger guards and Compose version checks. **No production promotion is authorized by this report.**
