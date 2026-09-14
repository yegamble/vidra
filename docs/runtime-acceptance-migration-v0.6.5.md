# v0.6.5 packaged migration rehearsal — generated fixture, source-disconnected

**PASS for this bounded rehearsal on the published, unmodified v0.6.5 images.
Full release readiness remains NO-GO, and no workflow row moves.** This is the
v0.6.5 run of the migration continuation recorded for v0.6.4 in
[runtime-acceptance-migration-v0.6.4.md](runtime-acceptance-migration-v0.6.4.md):
the released `vidra setup` and `deploy.sh`, the admin
`/admin/import-peertube` UI and the real import worker, driven against a
**generated** PeerTube 8.0.0 / schema 970 fixture, with the canonical media
landing in the same dedicated private Backblaze B2 acceptance bucket the
[B2 runtime milestone](runtime-acceptance-b2-v0.6.5.md) used. No application
binary was rebuilt or replaced; no standalone importer was used.

The derived
[disposition](evidence/release-v0.6.5-verification/migration-runtime/disposition.json)
reads **3 PASS / 45 UNVERIFIED / 11 BLOCKED** — identical to its baseline, the
[B2-runtime disposition](evidence/release-v0.6.5-verification/b2-runtime/disposition.json)
(sha256 `faadc85e74b5240b6dc77783a67c3d69baef60abc1d6bd5e4479e36c3759c64a`).
**MIG-01…06 stay BLOCKED on B2**, the approved sanitized representative source,
because a generated seven-video fixture is not representative-source
acceptance. What changes is the MIG rows' `basis`, plus the measured subsets
this rehearsal is entitled to record.

Extending the native v0.6.5 record's labelling, as the B2 record did: values
below are **file-asserted** — read out of the committed evidence — unless
marked **session-reported**, in which case they come from the operator's
account of the run and are not reconstructible from the committed artifacts.

Two facts the B2 record could only label session-reported are file-asserted
here, because `prepare-original.json` carries the checksums and this repository
carries the originals: the **18 shipped deployment files** all match the
`v0.6.5` tag byte-for-byte, and the **drill tools** are the `tests/` files at
meta **`ef1614f`** — the 13 tool checksums in `tools_sha256` that name a
`tests/` file all match `ef1614f:tests/<name>` exactly, including the exporter
(`peertube_release_export.py` `73ece427…7afd`, which is also
`provenance.json`'s `export_tool_sha256`) and the two harnesses that produced
every result below.

## Candidate and execution boundary

The candidate is the one the native and B2 runs used. `prepare-original.json`'s
`candidate_sha256`
`f55299d6eec7ed725743a9dcc463badfc1af12e761215454bcbe2e5fb526b47f` is the
sha256 of the committed
[frozen manifest](evidence/release-v0.6.5-verification/manifest.json) on
`main`, so the stage was prepared against the record in this repository.
`configuration_change` records the only change made to the released
deployment: *"Released setup `PEERTUBE_*` flags and one read-only source-media
mount on api/optional worker; images and scripts unchanged."*

| Boundary | Value |
|---|---|
| Images | core `ghcr.io/yegamble/vidra-core@sha256:a6e08b93…3bb1` (rev `d13d40e6`), user `…/vidra-user@sha256:08e920ba…3178` (rev `fdef1cec`), search `…/vidra-search@sha256:55196d27…a0f8` (rev `b7a7f55b`), all `linux/amd64` — the manifest digests, unchanged in all **30** image snapshots across the run |
| Supporting images | `caddy:2.11.4-alpine`, `clamav/clamav:1.5`, `postgres:18-alpine`, `redis:8-alpine`, `alpine:3.24` |
| CLI | `vidra_v0.6.5_linux_amd64` sha256 `8af9ccf7…afce` — the same value the B2 run recorded |
| Shipped deployment files | 18 files under `deploy/`, each matching `v0.6.5:<path>` in this repository |
| Ledgers | core **146\|f**, search **18\|f** before and after the reboot |
| Containers | frontend `883c642a…` and search `6a8ca321…` are the **same container** in all 30 snapshots. The api container is recreated exactly twice, both times by the released `setup`+`deploy.sh` pair: `581a8baf…` → `9bb676c4…` when the source integration is enabled, and `9bb676c4…` → `a9ada50f…` when it is disabled again. `581a8baf…` is the api container id the [B2 milestone](runtime-acceptance-b2-v0.6.5.md) recorded, so this rehearsal demonstrably continued that stack rather than a fresh one |
| Published ports | api `127.0.0.1:8080`, frontend `127.0.0.1:3000`, caddy `80`/`443`; **postgres, redis and search publish nothing**, before and after |
| One-shot jobs | `migrate` and `search-migrate` are exited with `ExitCode` **0**. `search-migrate`'s cached `Health` reads `unhealthy`; it is an exited one-shot migrator whose healthcheck never had a serving process to probe, not a failing service |
| Toolchain | Node **v26.8.1**, Chromium **153.0.8010.12** (`peertube-release-acceptance.mjs` `805cb543…`) |
| Stage | `/root/vidra-v065-migration-20260914`, a new stage; baseline `/root/vidra-v065-runtime` |

Host, bucket and key: droplet **599531580** (`159.203.118.182`), whose stack,
bucket `vidra-acceptance-v065-20260914-media` and scoped key
`/root/vidra-v065-b2-key.json` are the B2 milestone's, retained and not wiped —
**session-reported**, except that `reconcile.json`'s `provider_scope` is the
file-asserted proof of the bucket: `bucket_id` `9555421b394994e8a7070215`,
region `us-east-005`, endpoint `s3.us-east-005.backblazeb2.com`, and an
`authorized_scope` naming exactly **one** bucket with `namePrefix` **null** and
capabilities `readBuckets, deleteFiles, writeFiles, readFiles, listFiles,
listBuckets`. No other bucket in the account is reachable with that key. That
the browser reached the guest-internal origin `https://secure.video.test`, and
that no production DNS, traffic or resource was touched, is
**session-reported**.

Source inputs are copies of the retained generated fixture:
`source-final.dump` sha256 `ec26be51…d273` (**323,141** bytes) and
`source-media-config.tgz` sha256 `9756abd4…4b43` (**75,002,357** bytes), both
matching `retained_archive_manifest` in
[the fixture record](evidence/a18-a23-peertube-fixture.json). The originals
were read, not modified. The restored source ran in its own private container
`vidra-v065-migration-source-20260914`; the importer received a SELECT-only
role and a read-only media mount, and `prepare-original.json` inventories the
**81** source media files by hash.

The content is **seven generated eight-second 640×360 videos** and six
users/channels covering progressive, HLS-only, private, password, unlisted,
blocked and split-audio cases. The split-audio tree is a generated
compatibility fixture. There are no source actor images, no custom categories
and no preexisting remote followers. It establishes nothing about
representative source fidelity, scale or production cutover.

Command records: `commands.json` holds **359** host commands with their exit
codes, every log *"private; only hash exported"*. Exactly **one** is non-zero,
and it is non-zero by design — label `source-write-refused`, exit **1**: an
explicit `BEGIN READ WRITE; UPDATE video …` against the source as
`migration_reader`, refused. The eight browser phases carry a further **626**
commands between them, **all** exit zero.

## Executed evidence

| Procedure | Newly executed result on the v0.6.5 digests |
|---|---|
| Shipped operator path | Released `vidra setup` → released `deploy.sh` → admin `/admin/import-peertube`. `prepare-original.json` `status` **PASS**, checks `source_read_only` **PASS** and `published_setup_deploy` **PASS**; 10:56:32 → 10:57:13 UTC (41.5 s). No standalone importer, no development build |
| Source access | The read-only role's explicit read-write transaction is refused (the single non-zero exit above); source media mounted `:ro`. Non-PeerTube configuration preserved |
| Preview | Admin clicks Preview; the real worker completes dry run `e08b6add-…` **10:57:48.782805 → 10:57:49.134130 UTC (0.351 s)**, `state` `done`, `source_version` **970**, `media_mode` `copy`, `error_code` null, `conflict_count` 0. Plans 6 users, 6 channels, 7 videos, 5 video files, 6 HLS playlists, 6 renditions, 7 thumbnails, 7 storyboards, 12 tag links, 4 comments, 2 chapters, 1 caption, 1 playlist, 2 playlist items, 1 follow, 1 rating, 1 suspension, 1 block, 1 view count, 6 original dates — **imported 0, skipped 0, failed 0, unsupported 0**, and all thirteen catalogue counts and fingerprints are byte-identical before and after. Anonymous `GET`/`POST` on the endpoint are **401**. [preview-browser.json](evidence/release-v0.6.5-verification/migration-runtime/preview-browser.json) |
| Import | Admin clicks Start import; worker run `e9cef07f-…` completes **10:58:33.780106 → 10:58:39.429246 UTC (5.649 s)**, `state` `done`, mode `run`, `error_code` null, `conflict_count` 0. Imported: 6 users, 6 channels, 7 videos, 5 video files, 6 HLS playlists, 6 renditions, 7 thumbnails, 7 storyboards, 12 tag links, 4 comments, 2 chapters, 1 caption, 1 playlist, 2 playlist items, 1 follow, 1 rating, 1 user suspension, 1 video block, 1 view count, 6 unlimited quotas, 6 original dates. **Every entity class reports `failed` 0 and `unsupported` 0**, and `video_no_media` and `video_sensitive` are 0 across the board. The catalogue moves from 1/1/1/0/0/0/0/0/0/0/1/5/0 to **7 users, 7 channels, 8 videos, 4 comments, 1 playlist, 2 playlist items, 1 follow, 1 rating, 12 tag links, 2 chapters, 7 streaming playlists, 31 video files, 1 caption** — the pre-existing row in each is the B2 milestone's own upload. [import-browser.json](evidence/release-v0.6.5-verification/migration-runtime/import-browser.json) |
| Repeat | A second identical run `e436e528-…`, **10:59:18.779947 → 10:59:19.752652 UTC (0.973 s)**, `state` `done`, `conflict_count` 0. **Imported 0, updated 0, failed 0, unsupported 0**; 6 users, 6 channels, 7 videos, 6 renditions, 7 thumbnails, 7 storyboards, 4 comments, 2 chapters, 1 playlist, 1 rating, 1 follow, 6 original dates and 1 view count reported `skipped`. All thirteen catalogue counts **and** full-row fingerprints are identical before and after, and every displayed report cell survives a reload (`persisted-ui-report` **PASS**). [repeat-browser.json](evidence/release-v0.6.5-verification/migration-runtime/repeat-browser.json) |
| Schema guard | Only the **clone's** version marker is changed, 970 → 1040 (`schema-unsupported.json`, `isolated_source_marker` **PASS**). The actual UI preview then fails: run `06cdb8e6-…` `state` **`failed`**, `source_version` **1040**, `error_code` **`unverified_schema`**, `acknowledged_schema_version` **null** — and all thirteen fingerprints are unchanged across the refusal. The marker is restored to 970 (`schema-restore.json`, **PASS**). This tests the **marker guard**, not a genuinely newer schema layout. [schema-refusal-browser.json](evidence/release-v0.6.5-verification/migration-runtime/schema-refusal-browser.json) |
| Reconciliation | **7** source UUID → vidra id mappings, each `status` `done`, with titles and privacies carried across: progressive/split_audio/hls_only/blocked → `public`, unlisted → `unlisted`, private and password → `private`. **26** per-video asset rows — 5 `original`, 7 `thumbnail`, 7 `storyboard`, 7 `storyboard_vtt` — distributed 4 rows each to the five videos that have an original and 3 each to the HLS-only and split-audio videos; plus `source_asset_assignments` of 5 originals, 6 HLS trees and 1 caption. **30 signed B2 downloads, every one HTTP 200 and every one sha256-equal to the source file it came from** (verified here against `prepare-original.json`'s own 81-file source inventory): 24 under `streaming-playlists/`, 5 under `web-videos/`, 1 under `captions/`, 9,105,775 bytes in total, over 31 recorded provider calls. Thumbnails and storyboards are counted but **not** byte-qualified. [reconcile.json](evidence/release-v0.6.5-verification/migration-runtime/reconcile.json) |
| Search delivery | The import's own outbox events — `reconcile.begin` `c46ae050-…`, `reconcile.page` `0bb95acf-…`, `reconcile.end` `adb41428-…`, all under worker run `82b4ddb9-…`, created 10:58:39.439–10:58:39.452 UTC — are each `state` **`delivered`** and `received` **true** at real vidra-search. The page event names **4** video ids, the three eligible public imports plus the B2 milestone's pre-existing upload: the sweep covers the catalogue, not only the new rows. Exactly **3** eligible imported documents result (`939b488d`, `0a250212`, `cf15f385` — progressive, hls_only, split_audio), and `internal_search_ids` returns those three. No preseeded index rows |
| Browser search | The query is typed into the actual search control: one attempt, HTTP **200**, service success counter **4 → 5**, exactly the same three ids returned. [search-browser.json](evidence/release-v0.6.5-verification/migration-runtime/search-browser.json) |
| COPY independence | Released setup disables the integration and the same released `deploy.sh` succeeds without it; `disconnect.json` `source_disconnected` **PASS**, 11:02:08 → 11:02:36 UTC. The playback evidence carries the proof independently: `source_running` **`"false"`** and `source_media_unmounted` **true** |
| Disconnected decode | With the source down and unmounted, the admin browser plays all three formats from B2, each advancing with **no media error and unmuted**: hls_only 0 → **2.92721 s**, 16 → 84 frames, 8,884 → 35,936 audio bytes; progressive 0 → **2.948676 s**, 12 → 83 frames, 6,939 → 33,146 B; split_audio 0 → **2.942565 s**, 8 → 79 frames, 5,243 → 32,295 B. Private, password, unlisted and blocked playback and the caption UI remain **not run**. [playback-browser.json](evidence/release-v0.6.5-verification/migration-runtime/playback-browser.json) |
| Host restart | A real reboot changes the kernel boot id **`197275e8-514f-473a-993a-7dd7493f83c2` → `a9cd289a-956d-40c5-88eb-c64f18bac944`**. All thirteen `count\|fingerprint` pairs are identical across it — `users 7\|d8ec3cf2…`, `channels 7\|f5289a12…`, `videos 8\|1258bf0e…`, `comments 4\|5a97ca55…`, `playlists 1\|8613a71d…`, `playlist_items 2\|7c612d1c…`, `channel_follows 1\|2b7fe2de…`, `video_ratings 1\|00fcf4bc…`, `video_tags 12\|e30b0a6c…`, `video_chapters 2\|e14bf00a…`, `streaming_playlists 7\|6b5949b2…`, `video_files 31\|1a45f0e6…`, `captions 1\|07bab2c6…` — as are both clean ledgers **146\|f / 18\|f**. `restart-after.json` `host_restart_state_preserved` **PASS**. This is restart persistence, **not** replacement-host restoration |
| Post-restart supplement | Browser search again returns exactly the same three ids, counter **0 → 1** (the service's counter resets with the restart, which is itself consistent with a real reboot). All three formats decode again from B2 with the source still down and unmounted: hls_only 0 → **2.925479 s** (8 → 76 frames), progressive 0 → **2.997996 s** (9 → 81), split_audio 0 → **2.962373 s** (8 → 79), none muted, none erroring. [post-restart-search-browser.json](evidence/release-v0.6.5-verification/migration-runtime/post-restart-search-browser.json), [post-restart-playback-browser.json](evidence/release-v0.6.5-verification/migration-runtime/post-restart-playback-browser.json) |

Screenshots (`preview.png`, `import.png`, `repeat.png`, `schema-refusal.png`,
`search.png`, `playback-*.png`, `post-restart-*.png`) and the exact commands,
exits and timestamps are in the evidence directory. Health outputs are
represented by hashes; raw logs, DSNs, credentials, account-password hashes and
private actor keys are excluded — `provenance.json` records `secret_scan`
**PASS** and lists the 34 private raw files by hash.

The recovered data point is the pre-reboot thirteen-table snapshot captured at
**11:03:19.037 UTC**; the successful comparison completed at **11:04:56.633
UTC**, an observed interval of **97.596 seconds**. Computed exactly as the
v0.6.4 record computed its 208.873 s, this is an **upper bound** from
pre-reboot capture to successful state comparison, including operator
scheduling; it is **not a precise minimum RTO**, and no approved candidate
RPO/RTO was supplied, so no recovery-objective acceptance is claimed. That SSH
returned with a new boot id after 26 s and six healthy compose services after
60 s is **session-reported** — the operator-side waiter's timings are not in
the committed evidence.

Independent post-run bucket inventory from the workstation with the same scoped
key — **198 versions = 134 uploads + 64 hide markers**, prefixes `.vidra` 61,
`captions` 1, `storyboards` 16, `streaming-playlists` 40, `thumbnails` 8,
`uploads` 1, `web-videos` 7 — is **session-reported**; the committed evidence
proves the 30 objects it downloaded, not the bucket's total. The export archive
`/root/vidra-v065-migration-20260914-reviewed.tar.gz` sha256
`0df545d830a3e1dd15e1c48811ccf79b2cb4ec222bda939f4fe864fc541cf02f` is
**session-reported** and deliberately **not** committed.

## Evidence integrity

Thirty-one files came out of the exporter and are committed **verbatim**,
including its own `artifact-hashes.json`, whose 30 entries were re-verified
against the committed bytes here: **30/30 match**. Because that file describes
only what the exporter wrote, this record adds
[committed-hashes.json](evidence/release-v0.6.5-verification/migration-runtime/committed-hashes.json),
recomputed over **every** committed file in the directory except itself — all
32, so it covers the exporter's `artifact-hashes.json` and the derived
`disposition.json` as well. The exporter's file is not edited to cover them;
the two attestations are deliberately separate, the narrower one untouched.

`historical-tools.tar.gz` is committed as exported and is an **empty** archive
(66 bytes, zero members), consistent with `provenance.json`'s `tool_files: {}`.
The v0.6.4 run's equivalent carried 27 superseded tool revisions because that
run had failures and mid-run harness corrections. This run had neither: the
harnesses ran at one revision throughout, and the empty archive is the honest
record of that, not a missing artifact.

## Failures retained

**None this run.** Nothing failed, was overwritten or was relabelled: every
committed result carries `status` **PASS**, and the single non-zero exit in 359
host commands is the deliberate `source-write-refused` probe, which is non-zero
*because* the read-only role refused the write. The v0.6.4 run's four retained
failures and the corrections they forced — the read-only assertion, the
prep-volume anchoring, the original/thumbnail counting, the reconcile-sweep
event shape — are all already fixed in the `ef1614f` tools this run used, and
the results above are what those corrected assertions produce on a clean pass.

**An operator note, for completeness:** an earlier attempt to launch the
schema-guard chain aborted inside an operator-side summary script **before any
harness step ran**, and was re-issued. No host state changed, so nothing
distinguishes it in the evidence beyond the ordinary gap between the repeat
phase finishing (10:59:36.819 UTC) and `schema-unsupported` starting
(11:00:10.817 UTC). It is recorded here rather than inferred from a timestamp.

## What this does and does not prove

**It proves**, on the published v0.6.5 digests and nothing wider:

- That the **shipped operator path** — released CLI, released deployment
  scripts, admin UI, real import worker — carries a PeerTube 8.0.0 / schema 970
  COPY source into a running v0.6.5 instance with zero failed and zero
  unsupported entities, and that a second identical run changes nothing.
- That the **schema marker guard** refuses an unrecognised source version with
  `unverified_schema` and no catalogue change.
- That imported media genuinely **lands in canonical B2 object storage**, with
  30 downloads byte-equal to the source files.
- That the import's own reconcile events reach **real vidra-search** and that
  exactly the eligible public imports come back through the browser.
- That the instance keeps serving **with the source database stopped and its
  media unmounted**, decoding three HLS/progressive shapes in a real browser,
  and that a **real host reboot** preserves every table fingerprint and both
  ledgers.

**It does not prove** — and nothing here should be read as:

- **Full release readiness.** The verdict stays **NO-GO**.
- **Migration acceptance.** **MIG-01…06 and A18–A23 are not closed** and stay
  **BLOCKED on B2**. The source is a generated seven-video fixture, not the
  approved sanitized representative source; scale, cutover, collision handling,
  interruption/resume, imported-credential login, metadata ordering, old-link
  behaviour and federation continuity were **not run**.
- **Recovery acceptance.** The reboot is restart persistence only. No
  replacement host, no restore, no backup, no offsite drill, no approved
  RPO/RTO — **REC-01/02 stay BLOCKED on B4**, and A36–A38 keep their
  outstanding clauses.
- **Playback coverage.** Only public progressive, HLS-only and split-audio were
  decoded. Private, password, unlisted and blocked playback, the caption UI and
  every unauthorised-access case remain unexecuted.
- **Any browser but desktop Chromium 153.** No WebKit, no Firefox, no mobile
  viewport; QLT-01/02 are untouched.
- **Any split-worker or OPS result.** The release default **inline worker**
  topology was used; OPS-01's recorded subset is still the meta#199 one.
- **Storage or delivery completion.** Retention, lifecycle, destructive GC,
  quota, presigned URLs and CDN were not exercised; STO-01/02/03 and INT-09
  stay UNVERIFIED, INT-10 BLOCKED.
- **A clean-host result.** This stack already carried the B2 milestone's
  upload, which is why the catalogue starts at one video and the reconcile
  sweep names four ids.

## Remaining execution backlog and operator inputs

| Type | Criteria | Next concrete work or missing input |
|---|---|---|
| Missing source input | MIG-01–06 / A18–23 | Approved representative sanitized source/snapshot location, inventory and domain/cutover requirements. This generated-fixture proof remains separate and does not substitute for it |
| Specific credential-transfer approval pending | MIG-02 / A19 | Approve the generated fixture passwords into the named private test-host file; no production credentials or old tokens. Without it, imported-password login/roles/suspension checks stay unexecuted |
| Missing execution evidence | MIG-02–06 / A19–23 | Collisions and Vidra-owned edits, public actor identity/images, interruption and resume, all private/password/unlisted/blocked media and unauthorised cases, metadata ordering and dispositions, old links, and isolated federation continuity |
| Missing recovery input | REC-01/02, A36–38, INS-04/05 | Approved independent restore destination/profile, required offsite transport/object and approved RPO/RTO. The retained acceptance hosts cannot be wiped or used as replacement-host proof by restoring over them |
| Missing execution evidence | OPS-01, A17/A34; A36–38 | Job leases and two-worker interruption, DB/Redis/search outages, a failed backup, an independent decrypting restore, and the supported upgrade/app-rollback and incompatible-schema recovery paths beyond the REC-03 pair already recorded |
| Missing execution evidence and dependent provider inputs | Other required workflow rows, A03–17 / A24–35 / A39–40 | Continue the control inventory, negative cases, mobile/themes/keyboard/accessibility, WebKit and actual Safari/iOS separately; provider-specific cases wait only on their own approved inputs (B3) |
| Missing execution evidence | STO-01/02/03, INT-09/10 | Retention, lifecycle, destructive GC and quota clauses; presigned and CDN delivery with cross-origin browser checks |

## Reproduce

Use a **new** stage directory — this one is populated, and neither it, the
bucket's contents, the stopped source container nor the retained evidence may
be erased or reused automatically. The migration harness's own `prepare` takes
the candidate baseline positionally and has **no** `--candidate` flag — that
flag belongs to the runtime harness `release_acceptance.py`, whose own
`prepare` step must always carry it, because a committed unit test
(`tests/docs_prepare_candidate_test.py`) fails the `validate` lane if a recipe
outside a v0.6.4 record omits it. That guard matches on the command text
alone, so it fires on prose that merely names the runtime harness's step as
well as on a real recipe; this paragraph is worded to avoid the adjacency
rather than to quote a recipe it does not run. Run, as root, with the
baseline's Node on `PATH`:

```bash
export COMPOSE_PROJECT_NAME=vidra-release-acceptance
export VIDRA_BASELINE=/root/vidra-v065-runtime
STAGE=/root/vidra-v065-migration-YYYYMMDD

python3 /root/vidra-v065-drill-tools/peertube_release_acceptance.py "$STAGE" \
  --baseline /root/vidra-v065-runtime
node /root/vidra-v065-drill-tools/peertube-release-acceptance.mjs "$STAGE" preview
node /root/vidra-v065-drill-tools/peertube-release-acceptance.mjs "$STAGE" import
node /root/vidra-v065-drill-tools/peertube-release-acceptance.mjs "$STAGE" repeat

python3 /root/vidra-v065-drill-tools/peertube_release_checks.py "$STAGE" schema-unsupported \
  --baseline /root/vidra-v065-runtime --root "$STAGE" \
  --b2-key /root/vidra-v065-b2-key.json
node /root/vidra-v065-drill-tools/peertube-release-acceptance.mjs "$STAGE" schema-refusal
# ... schema-restore, reconcile, search, disconnect, playback, restart-before
# reboot the host, wait for SSH and a healthy stack, then:
# ... restart-after, post-restart-search, post-restart-playback

python3 /root/vidra-v065-drill-tools/peertube_release_export.py \
  --root "$STAGE" --baseline /root/vidra-v065-runtime \
  --b2-key /root/vidra-v065-b2-key.json
```

Do **not** rerun preparation over a populated stage. A future rehearsal uses a
new attempt label and preserves the source-disconnected state unless
reconnection is the declared procedure. The harness's Python/Playwright/Node
tools are acceptance prerequisites only; ordinary installation and import use
the released CLI, deployment scripts and web application.

Host state left as found: the source container
`vidra-v065-migration-source-20260914` **stopped, not removed**; the source
disconnected through released setup; the stack running; the stage, the B2
objects and the private raw evidence retained. Nothing was cleaned. Merge,
stable release publication, tag movement, production deployment or migration,
public DNS or federation, new infrastructure spending, host rebuilds and
evidence deletion remain unauthorized.
