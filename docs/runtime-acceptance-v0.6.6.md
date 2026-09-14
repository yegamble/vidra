# v0.6.6 runtime milestone + white-label toggle — local storage demonstrated

**PASS for this bounded milestone on the published v0.6.6 images. Full release
readiness remains NO-GO.** This is the v0.6.6 run of the A02/A03 runtime
acceptance harness recorded for v0.6.5 in
[runtime-acceptance-v0.6.5.md](runtime-acceptance-v0.6.5.md), with the same
scope (a blank native host, the released installer, CLI and bundle by checksum,
the published images by digest, one browser-driven upload → transcode →
playback → search on **local canonical storage**), plus an API-level check of
the new admin white-label toggle. It does not certify B2, migration, recovery
or any row the v0.6.5 continuations covered; the storage and disaster-recovery
rows are **carried from v0.6.5 by an explicit delta** (see below), not re-run on
the v0.6.6 digests.

## Candidate and boundary

v0.6.6 is v0.6.5 plus a single admin-only white-label toggle
`branding_hide_software_name` (vidra-core#242 `3219290e` / vidra-user#221
`1aec0d23`). **No migration**: `schema_migrations` stays at **146** and
`vidra_search_migrations` at **18** (vidra-search rebuilt at the same revision
`b7a7f55b`).

The harness ran release-agnostic: `tests/release_acceptance.py prepare
--candidate docs/evidence/release-v0.6.6-verification/manifest.json` then `run`.
The candidate handed to `prepare` was the **committed**
[frozen manifest](evidence/release-v0.6.6-verification/manifest.json):
`result.json`'s `candidate_sha256`
`b023dacb4aa809643852551b8c5082005083c7a824509c621977f5c804911f68` is the
sha256 of that file on this branch (verified equal at commit time). The three
published images were pinned by their v0.6.6 index digests:

| Image | Digest (index) | Revision |
|---|---|---|
| `ghcr.io/yegamble/vidra-core` | `sha256:b2b7717d…07e32fd` | `3219290e` |
| `ghcr.io/yegamble/vidra-user` | `sha256:4d86a264…be8882e` | `1aec0d23` |
| `ghcr.io/yegamble/vidra-search` | `sha256:804530bf…555e927c6` | `b7a7f55b` |

Host: droplet **599531580** (159.203), rebuilt blank amd64 by the operator,
native Ubuntu **24.04.4 LTS / x86_64** (`before.existing` empty — no
`/opt/vidra`, no `/usr/local/bin/vidra`, no `/var/lib/docker`; `check-host`
passed: root, systemd, no container). The droplet id and rebuild are
operator-reported, not reconstructible from the committed artifacts; the browser
used `https://secure.video.test` inside the guest and the stack ran under
`COMPOSE_PROJECT_NAME=vidra-release-acceptance`. Production and the beta host
were untouched. No application source, image or released deployment script
changed; only the six application image references were replaced with the frozen
v0.6.6 digests on `linux/amd64` (`deployment_adaptation`).

The uninterrupted passing run lasted from **2026-09-14 18:01:30 UTC** to
**2026-09-14 18:06:45 UTC** (315.1 s).
[Runtime observations](evidence/release-v0.6.6-verification/native-runtime/result.json),
[browser measurements](evidence/release-v0.6.6-verification/native-runtime/browser-result.json),
[exact host commands](evidence/release-v0.6.6-verification/native-runtime/host-commands.json)
and [export provenance](evidence/release-v0.6.6-verification/native-runtime/export-provenance.json)
record the actual execution; the raw logs stay on the host.

## Executed evidence

| Required step | Actual result |
|---|---|
| Fresh installation | Blank native host; released installer (sha256 `d0e632d5…4eea`, the `install.sh`), CLI `vidra_v0.6.6_linux_amd64` (`74fbf05a…2b75`) and bundle by checksum (frozen `vidra-bundle_v0.6.6.tar.gz` `587f1658…ce2b`); corruption refusal for a tampered bundle and CLI; configuration-preserving reinstall — all PASS; Docker 29.8.0, Compose 5.5.1 |
| Deployment | The three published images by index digest (core `b2b7717d…07e32fd`, user `4d86a264…be8882e`, search `804530bf…555e927c6`) inspected before and after the browser phase with unchanged container ids and `restart_count` 0; released deploy script unchanged; core **146\|f** from `3219290e`, search **18\|f** from `b7a7f55b`; api on `127.0.0.1:8080` and frontend on `127.0.0.1:3000` only, postgres/redis/search unpublished; api, frontend, search, postgres, redis, caddy **and clamav** healthy (`MALWARE_SCAN_MODE=fail-closed`); edge `/healthz`, `/readyz`, `/version` PASS (`/version` body `{name: vidra, version: v0.6.6, commit: 3219290, go1.27.1}`) |
| Owner | Browser claim of the boot token, logout, login, refresh and persisted admin identity PASS; owner `cb2ba68a-9d7b-46e5-a0f2-ade962e72e30` |
| Real upload | Browser-created channel `8062be35-81bf-413a-b410-45f335fa49f2`, draft, file selection, metadata/public privacy and Publish; video `8d06000b-627a-4781-952f-05ecb4e8607f` (upload `69c00bdf-f8c9-4039-806f-7bd53b1d304f`); downloaded original **1311662 bytes**, `video/mp4`, SHA-256 `47e46fdf…923a` equal to the source fixture (`fixture_sha256`) |
| Real transcode | Durable job `04b54607-012a-42a8-9199-439acb57caf8` observed `pending` → `running` → **`done`**, attempts **0**; a 360p (640×360) CMAF rendition and **12** advertised playlist/init/fragment assets fetched successfully; **28** media requests recorded (26×200, original 206, one view beacon 204) |
| Browser playback | Chromium **153.0.8010.12** on Node **26.8.1**; HLS playback time **0.00 → 3.903 s**, decoded frames **18 → 136**, decoded audio bytes **12876 → 61674**; unmuted, `readyState` 4, no media error (a seek to 7 s advanced to 150 frames) |
| Real search | The same UUID in the outbox/inbox (two delivered upsert events), an eligible search document, the signed internal query (`score` 0.90, `simple-v1`, total 1); the UI query `Releaseacceptancec998f7b453b8` met the published request limit once (`429`, Retry-After 31 s, honoured) and returned it on the second attempt; vidra-search successful query counter **1 → 2**; the routed fetch returned the same id (`200`) on its first request; short link `/v/BfnHVc4m9E4` |

Actual screenshots: [claimed owner](evidence/release-v0.6.6-verification/native-runtime/owner-claimed.png),
[published upload](evidence/release-v0.6.6-verification/native-runtime/upload-published.png),
[advancing playback](evidence/release-v0.6.6-verification/native-runtime/playback-advancing.png),
[search result](evidence/release-v0.6.6-verification/native-runtime/search-result.png).
Hashes: [export-hashes.json](evidence/release-v0.6.6-verification/native-runtime/export-hashes.json)
(the exporter's on-host attestation over the eight files it wrote) and
[committed-hashes.json](evidence/release-v0.6.6-verification/native-runtime/committed-hashes.json)
(recomputed over every committed file in the tree except itself, including
`disposition.json` and `branding-evidence.json`).

Export: `raw_evidence_location` `/root/vidra-v066-runtime`; of the two exported
JSON files only `result.json` was transformed (health-log outputs replaced by
their hashes) — `browser-result.json` is byte-identical to its raw
(`raw_browser_sha256` `4fe49328…a66b39`). The exporter secret scan PASS and the
`handoff_sha256` `746145f7…3e8e3b` are session-reported; neither the archive nor
the handoff is committed. The v0.6.6 **security-facet (secret_scan) PASS is
recorded separately in meta#212**; this record does not duplicate that scan
evidence.

## New feature: white-label toggle (API-level)

The admin-only `branding_hide_software_name` was exercised on the live v0.6.6
stack at the **API level**, recorded in
[branding-evidence.json](evidence/release-v0.6.6-verification/native-runtime/branding-evidence.json):

- default `GET /api/v1/instance` → `branding.hide_software_name=false`,
  `software.name="vidra"`;
- `PATCH /api/v1/admin/instance-settings {"branding_hide_software_name": true}`
  (owner token) → **200**;
- read-back → `hide_software_name=true`;
- reverted to `false` → **200**.

**PASS** — the admin toggle flips the public branding block's
`hide_software_name` on the v0.6.6 images, machine-readable identifiers
unchanged per spec. **Scope: this is an API-level admin toggle plus a public
read-back, NOT a browser render check of the chrome** — the rendered white-label
UI belongs to the UI/iOS matrix and is not claimed here.

## Operator note — apt-lock first attempt (session-reported)

The first run attempt died at the installer's apt step because the
freshly-rebuilt host's first-boot apt held the lock; after cloud-init finished,
the re-run passed. The failed attempt is retained on the host as
`vidra-v066-runtime-fail-1-aptlock`; its evidence is not part of this record.
This is a harness/host timing issue, **not a v0.6.6 defect**, and is reported
here for completeness only.

## Delta-carry reasoning for the storage / DR rows

The [local-run disposition](evidence/release-v0.6.6-verification/native-runtime/disposition.json)
is a **delta** on the latest v0.6.5 disposition
([offsite-runtime](evidence/release-v0.6.5-verification/offsite-runtime/disposition.json),
sha256 `cc21305e…3f544`, cited as `prior_disposition`; 5 PASS / 45 UNVERIFIED /
9 BLOCKED). Because v0.6.6 = v0.6.5 + one admin-only branding flag with **no
schema change** and the **same deploy, storage, media, backup and recovery
code**, the delta is applied as follows:

- **Re-anchored on v0.6.6 evidence (this run):** the first runtime milestone
  (install/deploy/browser facets), **SRC-01** (same-upload through vidra-search),
  and **INS-03** (release-integrity boundary, via the candidate-manifest/digest
  verification; the secret_scan facet in meta#212). These stay PASS and are now
  proven on the v0.6.6 digests.
- **Carried PASS from v0.6.5 by delta (not re-run):** **REC-01** (off-site
  backup, meta#210), **REC-02** (replacement-host restore, meta#208) and
  **REC-03** (upgrade / app-only rollback / forward restore, meta#199). The
  mechanics they exercise are unchanged by an admin branding flag, and the v0.6.6
  runtime milestone + security scan confirm the images carrying that code are the
  ones under test. Each row is annotated as carried in its `basis`.
- **NOT promoted:** **STO-01/02/03** and **INT-09** were **UNVERIFIED — not
  PASS — in the v0.6.5 lineage** (only a B2 canonical-media subset passed; the
  full procedure never ran). Carrying them as PASS would invent a status the
  v0.6.5 record never established, so they are carried at **UNVERIFIED**. The
  unchanged storage code means the v0.6.5 subset still holds; the full original
  procedure remains required.
- **Kept BLOCKED:** MIG-01..06 on B2 (representative sanitized source), and
  AUTH-03/04, INT-10 on B3 (selected IdP/mail and CDN providers). None is
  affected by the branding flag.

No workflow row changed status versus the v0.6.5 offsite disposition. Counts:
**5 PASS / 45 UNVERIFIED / 9 BLOCKED**.

## What this run proves and does not

**Proves:** on **local canonical storage**, the published v0.6.6 images install
on a blank native host, deploy with the production port posture and healthy
services, and carry one browser-driven upload → real transcode → advancing HLS
playback → vidra-search retrieval to completion on the v0.6.6 index digests;
and the admin white-label toggle flips the public branding block at the API
level.

**Does not prove:** B2 or any S3 provider on the v0.6.6 digests (STO-01/02/03,
INT-09 stay UNVERIFIED); migration, recovery and off-site drills on the v0.6.6
digests (REC-01/02/03 are **carried from v0.6.5 by delta, not re-run**); the
white-label **browser render** (checked only at the API level here); any
**WebKit, Safari or iOS** coverage; TLS via ACME; or a second host. This is a
bounded acceptance milestone — **not a deployment**: production and beta were
untouched.
