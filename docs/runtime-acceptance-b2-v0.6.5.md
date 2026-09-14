# v0.6.5 Backblaze B2 runtime milestone — canonical object storage demonstrated

**PASS for this bounded milestone on the published, unmodified v0.6.5 images.
Full release readiness remains NO-GO.** This is the v0.6.5 run of the same B2
continuation recorded for v0.6.4 in
[runtime-acceptance-b2-v0.6.4.md](runtime-acceptance-b2-v0.6.4.md): a blank
native host, the released installer, CLI and bundle by checksum, the published
images by digest, and one browser-driven upload → real CMAF transcode →
advancing playback → real vidra-search indexing, with **a dedicated private
Backblaze B2 bucket as canonical storage** instead of the local disk the
[native v0.6.5 run](runtime-acceptance-v0.6.5.md) used. No other bucket in the
account was read, written or configured.

Unlike the v0.6.4 B2 attempt, the runner exited zero and performed the direct
signed S3 readback of the original itself: no separate completion step was
needed or run.
[result.json](evidence/release-v0.6.5-verification/b2-runtime/result.json)
carries `status` **PASS** with every check PASS, and
[export-provenance.json](evidence/release-v0.6.5-verification/b2-runtime/export-provenance.json)
records `completion_raw_sha256` **null** and `original_failure_preserved`
**false**. The v0.6.4 record's `contentSha1` correction still applies: B2
reports `none` for this original's native SHA-1 (`native_original_sha1_field`),
which is a provider representation, not a checksum attestation — the byte
identity below rests on the SHA-256 the runner computed over the object it
actually downloaded.

Extending the native v0.6.5 record's labelling: values below are
**file-asserted** — read out of the committed evidence — unless marked
**session-reported**, in which case they come from the operator's account of
the run and are not reconstructible from the committed artifacts.

## Candidate and execution boundary

The candidate is the same one the native run used: the **committed**
[frozen manifest](evidence/release-v0.6.5-verification/manifest.json).
`result.json`'s `candidate_sha256`
`f55299d6eec7ed725743a9dcc463badfc1af12e761215454bcbe2e5fb526b47f` is the
sha256 of that file on `main`, so the handoff was prepared against the record
in this repository and not a local copy. `deployment_adaptation` records the
only change made to the released deployment: *"Only six application image
references replaced with frozen digests and linux/amd64; scripts unchanged."*

| Boundary | Value |
|---|---|
| Images | core `ghcr.io/yegamble/vidra-core@sha256:a6e08b93…3bb1` (rev `d13d40e6`), user `…/vidra-user@sha256:08e920ba…3178` (rev `fdef1cec`), search `…/vidra-search@sha256:55196d27…a0f8` (rev `b7a7f55b`), all `linux/amd64` — the same digests as the manifest and the native run |
| Supporting images | `caddy:2.11.4-alpine`, `clamav/clamav:1.5`, `postgres:18-alpine`, `redis:8-alpine`, `alpine:3.24` |
| Installer / CLI | installer sha256 `d0e632d5…4eea`; CLI `vidra_v0.6.5_linux_amd64` sha256 `8af9ccf7…afce` from the v0.6.5 release |
| Ledgers | core **146\|f** (expected 146, source `d13d40e6`), search **18\|f** (expected 18, source `b7a7f55b`) — identical to the manifest and the native run |
| Served version | `/version` → `v0.6.5`, commit `d13d40e`, built `2026-09-13T05:57:31Z`, `go1.27.1` |
| Engine | Docker **29.8.0** (build 88096ef), Compose **5.5.1** |
| Handoff | `handoff.json` sha256 `6135feca…6add` (`result.json`); the handoff tarball sha256 `45e7739c…d26ac`, built `COPYFILE_DISABLE=1 tar --no-xattrs` and extracted `--no-same-owner`, is **session-reported** and not committed |
| Drill tools | `tests/` files at meta `ef1614f`, staged on the host as `/root/vidra-v065-drill-tools` and checksummed — **session-reported** |

Host: `before` records `Linux` / `x86_64`, hostname
`vidra-beta-v064-b2-acceptance` (retained across rebuilds), Ubuntu **24.04.4
LTS (Noble Numbat)**, `root` true, `systemd` true, `container` false and
`existing` **empty** — no `/opt/vidra`, no CLI, no Docker state. That it is
DigitalOcean droplet **599531580** (`159.203.118.182`), rebuilt blank by the
operator at **04:39:23 UTC** with 8 vCPU / 15 GiB / 309 GB, is
**session-reported**. The browser reached the guest-internal origin
`https://secure.video.test` (`browser_args`: `--host-resolver-rules=MAP
secure.video.test 127.0.0.1`, `--no-proxy-server`,
`--autoplay-policy=no-user-gesture-required` — the user-gesture requirement was
deliberately disabled so the driver could start playback and assert that it
advances). No production DNS, traffic or resource was touched.

The run began **2026-09-14 06:35:13 UTC** and finished **06:39:45 UTC**
(**271.4 s**), as transient unit `vidra-v065-acceptance`. That the unit
reported `ActiveState=inactive ExecMainStatus=0 Result=success` with journal
tail *"PASS: /root/vidra-v065-runtime/result.json; private logs retained; no
cleanup performed"*, 2 min 37 s CPU and 2.4 G peak memory, is
**session-reported**;
[host-commands.json](evidence/release-v0.6.5-verification/b2-runtime/host-commands.json)
is the file-asserted record of the execution — **96** commands in one
contiguous sequence, every one with its exit code, every log marked *"retained
privately on host; output not exported"*. The two deliberate corruption probes
(`install-corrupt-bundle`, `install-corrupt-cli`) are the only non-zero exits,
and they are non-zero **because** the installer refused the tampered artifact.

## Actual results

| Required step | Actual result |
|---|---|
| Fresh installation | Blank native host (`existing: []`); released installer, CLI and bundle by checksum; a tampered bundle and a tampered CLI both **refused**; configuration-preserving reinstall; native CLI executes — `blank_native_host`, `corrupt-bundle`, `corrupt-cli`, `install`, `native_cli_executes`, `configuration_preserved` all **PASS** |
| Deployment | `pinned_image_pulls` and `installed_migrated_serving` **PASS**; the three published images inspected before and after the browser phase with unchanged container ids (api `581a8baf…`); api on `127.0.0.1:8080` and frontend on `127.0.0.1:3000` only, **postgres, redis and search publish nothing**; api, frontend, search, postgres, redis, caddy **and clamav** healthy; edge `/healthz`, `/readyz`, `/version`, `/` and `/runtime-config.js` all captured |
| Storage identity | `STORAGE_BACKEND=s3`, endpoint `s3.us-east-005.backblazeb2.com`, region `us-east-005`, bucket `vidra-acceptance-v065-20260914-media`, TLS **true**, path-style **false** — read from the **loaded api container twice** (06:37:36 and 06:39:42 UTC), each time with `credential_matches_verified_single_bucket_key` **true**. `TRANSCODING_ENABLED=true`, `TRANSCODING_PACKAGER=cmaf`, `MALWARE_SCAN_MODE=fail-closed`, `RATE_LIMIT_ENABLED=true` (120 req, media 3000) were all in force |
| Owner | Browser claim of the boot token, logout, login, refresh and persisted admin identity **PASS**; owner `a654ce9b-84d3-435e-8d8e-0f0131771e8f` |
| Real upload | Browser-created channel `0001d397-5bd9-4a3d-9159-9aac3c6512b0`, draft, file selection, metadata and Publish; upload `49e52f50-cb57-4c29-89fe-b97033d6fd6b`, video `cded6735-89ee-497b-b5ec-4f31c457f1e7`, title `Releaseacceptance686123c584ad`; browser original download **200**, `video/mp4`, **1311662 bytes**, SHA-256 `47e46fdf11a5f3851cd87ab7ea02cb12a5db4f679bef5ee846fad4d6fa74923a` — equal to `fixture_sha256` |
| **Canonical B2 original** | Independent signed S3 GET of `https://vidra-acceptance-v065-20260914-media.s3.us-east-005.backblazeb2.com/web-videos/cded6735-89ee-497b-b5ec-4f31c457f1e7.mp4` → **200**, `video/mp4`, **1311662 bytes**, SHA-256 **`47e46fdf11a5f3851cd87ab7ea02cb12a5db4f679bef5ee846fad4d6fa74923a`** — byte-identical to the generated source fixture and to what the browser downloaded through the API. `storage.preflight` **PASS**, `storage.provider_objects` **PASS** |
| Real transcode | Durable job `1f185ddb-1dc4-4b52-8c8b-e4380e4d4a21` observed `running` → **`done`**, retry counter **0**; one **360p** (640×360) CMAF rendition; all **12** advertised playlist/init/fragment assets fetched (master 476 B, `media_0` 258 B, `media_1` 309 B, `iframe-0.m3u8` 1096 B, init 828/765 B, five `m4s` fragments, `iframe-0.mp4` 146059 B); **26** media requests recorded — 24×200, one 206 (the original) and one 204 (the view beacon) |
| Browser playback | Chromium **153.0.8010.12** on Node **v26.8.1**: playback time **0 → 3.756112 s**, decoded frames **17 → 130**, decoded audio bytes **10224 → 57515**, 640×360, `readyState` **4**, unmuted, **no media error**; a seek to **7 s** then reported frames **144** and audio bytes **63122** |
| Real search | Search-upsert events **4** and **5** `delivered` with **0** attempts and `received` true; an **eligible** search document for the same UUID and title; the signed internal query returned that one id with `score` **0.8999994392637409**, `model_version` `simple-v1`, `total` **1**; the UI query met the published request limit once — **429 with `Retry-After: 34`**, honoured — and returned the video on the second attempt, raising the vidra-search successful-query counter **1 → 2**; the result linked `/v/MgBftwN1Ljf`; a separate routed fetch returned **200** on its first request and the routing ledger recorded `source=search` (event `00463ad4…`) |
| Source fixture | The generated fixture is H.264 High 640×360 @ 30 fps + AAC-LC 48 kHz mono, 12.000000 s, **1311662 bytes** (`fixture_probe`) — the same 12-second synthetic clip the v0.6.4 and native v0.6.5 runs used |

The release's **default inline worker topology** was retained. No separate
worker profile was selected and **no split-worker or OPS result is claimed by
this run**.

## Test-bucket isolation

Only **`vidra-acceptance-v065-20260914-media`**, bucket id
**`9555421b394994e8a7070215`**, region **`us-east-005`**, endpoint
**`s3.us-east-005.backblazeb2.com`**, was used. `result.json` records the
authorization response the harness checked on the host before installation:

```json
"authorized_scope": {
  "buckets": [{ "id": "9555421b394994e8a7070215",
                "name": "vidra-acceptance-v065-20260914-media" }],
  "capabilities": ["writeFiles", "deleteFiles", "readBuckets",
                   "listFiles", "readFiles", "listBuckets"],
  "namePrefix": null
}
```

One bucket, six capabilities, **no name prefix** — the key cannot see, list or
touch anything else in the account. The bucket was created today, `allPrivate`,
with no lifecycle rules; the key `vidra-v065-media-acceptance`
(keyId `005552b994877250000000012`) expires after seven days on **2026-09-21**;
the account credential never left the operator workstation. Those four facts
are **session-reported** — the evidence asserts the scope, not the bucket's
creation options or the key's expiry. The bucket's default server-side
encryption setting is **not in evidence** and is not claimed here.

Inventory, file-asserted from `result.json`:

| Moment | Inventory |
|---|---|
| Before deployment | `storage.before` is **empty** — **0 versions** |
| After the run | `storage.after` holds **29 version entries: 24 uploads and 5 hide markers** |

The 24 uploads, by prefix: `.vidra` **2** (the ownership marker and a write
probe), `uploads` **1** (the staged original, 1311662 B), `web-videos` **2**
(the canonical original 1311662 B `video/mp4`, and a 360p web copy 1405208 B),
`streaming-playlists` **16** (the real CMAF tree — `master.m3u8`, `media_0`,
`media_1`, `iframe-0.m3u8`, two init segments, five `m4s` fragments,
`iframe-0.mp4`, `stream.mpd`, `audio.m4a`, `video.mp4`, `video-only.mp4`),
`thumbnails` **1** (19423 B JPEG) and `storyboards` **2** (a 39042 B JPEG sheet
and a 777 B VTT). The 5 hide markers cover the write probe, the staged upload
and its part, and the two `r1` rendition directories. The independent
post-run inventory the operator took from the workstation with the same scoped
key returned the same 29/24/5 split (**session-reported**; it agrees with the
committed file).

Hidden staging and probe versions therefore remain visible in the actual
inventory and no lifecycle rule was added, so the **retention/billing risk
recorded for v0.6.4 stays open** — see
[Backblaze file-version behavior](https://www.backblaze.com/docs/cloud-storage-file-versions)
and [application-key restrictions](https://www.backblaze.com/docs/cloud-storage-application-keys).
Isolation here rests on a dedicated bucket and a restricted key, not on a
prefix inside a shared bucket.

## Screenshots, hashes and export provenance

Actual screenshots:
[claimed owner](evidence/release-v0.6.5-verification/b2-runtime/owner-claimed.png),
[published upload](evidence/release-v0.6.5-verification/b2-runtime/upload-published.png),
[advancing playback](evidence/release-v0.6.5-verification/b2-runtime/playback-advancing.png),
[search result](evidence/release-v0.6.5-verification/b2-runtime/search-result.png).
`browser-result.json` carries their sha256 values and every one matches the
committed bytes.

Hashes: [export-hashes.json](evidence/release-v0.6.5-verification/b2-runtime/export-hashes.json)
is the exporter's own manifest of the eight files it wrote beside it on the
host; **all eight entries match the bytes committed here**.
[artifact-hashes.json](evidence/release-v0.6.5-verification/b2-runtime/artifact-hashes.json)
is recomputed over every committed file in the directory except itself — ten
entries, so it covers `export-hashes.json` and the disposition as well — the
same shape [native-runtime/artifact-hashes.json](evidence/release-v0.6.5-verification/native-runtime/artifact-hashes.json)
uses.

Export: `release_acceptance_export.py /root/vidra-v065-runtime` run from
`/root/vidra-v065-drill-tools` on the host, producing nine files in
`/root/vidra-v065-reviewed-evidence/`. The exporter's `secret_scan: PASS` and
the archive sha256 `ffa67a9036a14476d11fbedfd52a20784cc4360b6afc03b93444a1435af7ee38`
are **session-reported**; the archive is not committed.
[export-provenance.json](evidence/release-v0.6.5-verification/b2-runtime/export-provenance.json)
asserts the raw hashes on the host — `raw_result_sha256` `9791507a…5df2d`,
`raw_browser_sha256` `a4437d0c…d19b`, `raw_commands_sha256` `e34a9fb3…7ac8b`,
raw location `/root/vidra-v065-runtime` — and its declared scope: *"Sanitized
result/browser measurements, command arguments and raw-log hashes, four
requested browser screenshots. No raw logs, generated environment,
credentials, database or application storage exported."* Of the three exported
JSON measurement files, `browser-result.json` is byte-identical to its raw
(`raw_browser_sha256` equals the committed hash); `result.json` and
`host-commands.json` were transformed — health-log and command outputs
replaced by their hashes — so their committed hashes differ from the raw ones
by design. The raw logs stay on the host.

The stack was left running on the host with the B2 media in place (it becomes
the migration drill's host next) — **session-reported**.

## Disposition

[This run's disposition](evidence/release-v0.6.5-verification/b2-runtime/disposition.json)
is derived from the
[v0.6.5 native-runtime disposition](evidence/release-v0.6.5-verification/native-runtime/disposition.json),
sha256 `d3df8e7fee541586983055914758687aa8b06e3f79f331c3826bde4b76e9a3e6`. All
59 workflow procedures, 40 acceptance criteria and ten scope families remain
authoritative.

The delta is exactly the one the v0.6.4 B2 milestone applied, for exactly the
same reason and no further: **STO-01, STO-02, STO-03 and INT-09** move
**BLOCKED (B3) → UNVERIFIED**, because dedicated provider bucket, endpoint and
scoped credentials are now established for v0.6.5, so their unexecuted cases
are no longer blocked on a missing input. Provider access **unblocks** those
rows; it does not verify them, and **no row is promoted to PASS by this run** —
SRC-01 was already PASS from the native v0.6.5 run and its chain passed again
here. AUTH-03/04 and INT-10 stay BLOCKED on B3 (other selected provider and CDN
inputs), MIG-01…06 on B2, REC-01/02 on B4.

Counts: **3 PASS / 45 UNVERIFIED / 11 BLOCKED** (up from 3 / 41 / 15). The
three PASS rows are unchanged: INS-03 (static, on the v0.6.5 preflight),
SRC-01 (the native v0.6.5 run) and REC-03 ([meta#199](runtime-acceptance-rec03-v0.6.5.md)).

## What this does and does not prove

**It proves**, on the published v0.6.5 images and this evidence alone:

- A fresh native install from the released installer, CLI and bundle by
  checksum, refusing tampered artifacts, on a host with no prior state.
- That the deployed api actually loaded the S3 backend pointed at the dedicated
  private B2 bucket, with a credential matching the verified single-bucket key,
  both before and after the browser phase.
- That a browser-driven upload landed in that bucket as the canonical original,
  and that an **independent signed S3 GET straight from B2** returned bytes
  whose SHA-256 equals the source fixture's.
- That a **real** CMAF transcode ran to `done` with zero retries and wrote its
  real outputs into that bucket, and that Chromium decoded the resulting HLS
  tree from the API — video frames and audio bytes both advancing — and seeked.
- That the same upload reached vidra-search and came back through the UI and a
  routed fetch, with the published rate limit enforced and honoured on the way.

**It does not prove** — and nothing here should be read as:

- **Full release readiness.** The verdict stays **NO-GO**.
- **Storage acceptance.** STO-01/02/03 are UNVERIFIED, not PASS: retention,
  lifecycle, destructive GC, quota and provider-policy clauses were not run.
- **Delivery beyond API proxying.** No presigned URL, no CDN, no cross-origin
  browser check — INT-09 is unblocked, not verified; INT-10 and A33 remain
  BLOCKED.
- **Any split-worker or OPS result.** The default inline worker topology was
  used; OPS-01's recorded subset is still the meta#199 one.
- **Any browser but desktop Chromium 153.** No WebKit, no Firefox, no mobile
  viewport — QLT-01/02 are untouched.
- **Any migration or recovery claim.** No representative-source or PeerTube
  migration, no crash/outage/backup/replacement-host drill; MIG-01…06 and
  REC-01/02 stay BLOCKED on their own inputs.
- **Provider durability, encryption or billing.** One bucket, one key, one
  short run; the bucket's encryption default is not in this evidence.

It is a **bounded milestone**: `result.json`'s `candidate_certification` says
`BOUNDED_MILESTONE_ONLY` and `scope` says *"first runtime milestone only"*.

## Reproduce

Use a **new** blank Ubuntu 24.04 AMD64 host — this one is now populated, and
its evidence and the bucket's contents must not be erased or reused
automatically. Create a new private bucket and a new key restricted to it; put
only `bucket`, `bucket_id`, `region` and `endpoint` in a nonsecret
`storage-spec.json`, and keep `access_key`/`secret_key` in a separate mode-0600
JSON file. Use an actual date and a lowercase nonce:

```bash
umask 077
mkdir /tmp/vidra-v065-b2-next
b2 bucket create vidra-acceptance-v065-YYYYMMDD-media-NONCE allPrivate \
  > /tmp/vidra-v065-b2-next/bucket-id
b2 key create --bucket vidra-acceptance-v065-YYYYMMDD-media-NONCE \
  --duration 604800 vidra-v065-media-acceptance \
  listBuckets,readBuckets,listFiles,readFiles,writeFiles,deleteFiles \
  > /tmp/vidra-v065-b2-next/key.txt
python3 tests/release_acceptance.py prepare \
  --frozen /tmp/vidra-v065-preflight \
  --node-archive /tmp/vidra-v065-toolchain/node-v26.8.1-linux-x64.tar.xz \
  --node-sums /tmp/vidra-v065-toolchain/SHASUMS256.txt \
  --b2-spec /tmp/vidra-v065-b2-next/storage-spec.json \
  --candidate docs/evidence/release-v0.6.5-verification/manifest.json \
  --out /tmp/vidra-v065-b2-next/handoff
```

The v0.6.4 recipe's `--default-server-side-encryption SSE-B2` is deliberately
absent: this run's bucket was created without it, and the recipe has to
describe what ran. It would also have been an unverifiable flag to carry over —
neither the harness nor the exported evidence reads a bucket's default-encryption
setting back, so v0.6.4's "SSE-B2 / AES256" line was never evidenced either.
This bucket's setting is therefore **not in evidence** (as stated above), and a
future run that wants to assert encryption at rest must capture `b2 bucket get`
output into the evidence rather than infer it from the create command.

`--candidate` is **not optional here**: `prepare` falls back to the committed
v0.6.4 manifest, and without the flag the handoff is prepared against the
v0.6.4 record, after which the correctly named v0.6.5 acceptance bucket is
refused as *"requires a new dedicated v0.6.4 acceptance bucket"*. A committed
unit test (`tests/docs_prepare_candidate_test.py`) fails the `validate` lane if
any recipe outside a v0.6.4 record omits it.

Convert the two key values privately into JSON; never print, commit or include
credentials in the nonsecret handoff archive. Build the archive with
`COPYFILE_DISABLE=1 tar --no-xattrs` if the workstation is macOS — plain macOS
`tar` adds AppleDouble `._*` files and the operator's uid to the stage — and
extract it `--no-same-owner`, then chown to root. Extract into
`/root/vidra-v065-runtime` mode 0700 and store the key at
`/root/vidra-v065-b2-key.json` mode 0600. Then, on the host:

```bash
python3 /root/vidra-v065-runtime/release_acceptance.py check-host
systemd-run --unit=vidra-v065-acceptance \
  /usr/bin/env -i PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
  LANG=C.UTF-8 /usr/bin/python3 /root/vidra-v065-runtime/release_acceptance.py run \
  /root/vidra-v065-runtime --acknowledge fresh-disposable-host \
  --b2-credentials /root/vidra-v065-b2-key.json
journalctl -u vidra-v065-acceptance --no-pager -n 30
systemctl show vidra-v065-acceptance -p ActiveState -p ExecMainStatus
```

The runner performs the direct signed S3 download itself; no completion helper
is needed for a run that exits zero. Export with the
[export helper](../tests/release_acceptance_export.py) and **no** completion
argument:

```bash
python3 /root/vidra-v065-drill-tools/release_acceptance_export.py /root/vidra-v065-runtime
```
