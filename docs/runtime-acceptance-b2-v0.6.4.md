# v0.6.4 Backblaze B2 runtime milestone — demonstrated

**PASS for the requested milestone on published, unmodified v0.6.4 images.
Full release readiness remains NO-GO.** Fresh native installation, owner
claim/login, browser upload, real CMAF transcoding, advancing playback/audio
and real vidra-search indexing were demonstrated using a dedicated private
Backblaze B2 bucket. Sizetube's live and backup buckets were untouched.

The original recorder's final checksum-metadata assertion exited **1** and is
preserved as **FAIL** in [result.json](evidence/release-v0.6.4-verification/b2-runtime/result.json).
The [browser sequence](evidence/release-v0.6.4-verification/b2-runtime/browser.json)
had already passed every step. A separate
[read-only completion](evidence/release-v0.6.4-verification/b2-runtime/completion.json)
then downloaded the original directly from B2, verified its bytes, and captured
the post-browser image/ledger snapshot. It passed without changing application
state or rebuilding an application image. This is a completed evidence chain,
not a claim that the original recorder exited zero.

## Actual results

The fresh application sequence ran **2026-09-11 04:14:02–04:18:28 UTC** on
DigitalOcean droplet **599531580**, `159.203.118.182`, after an authorized clean
OS rebuild. It used Ubuntu **24.04.4 LTS / x86_64**, 8 vCPUs, 16 GiB RAM and
320 GiB disk. Read-only completion ran **04:22:49–04:22:52 UTC**.
The firewall permits operator SSH only; Chromium used the internal origin
`https://secure.video.test` inside the guest. No production DNS/traffic changed.

| Check | Actual evidence |
|---|---|
| Fresh installation | Blank-host guard, released installer/CLI/bundle checksums, deliberate corruption refusal, configuration-preserving reinstall and native CLI PASS |
| Frozen deployment | Same four source revisions and immutable core/user/search digests in the [unchanged manifest](evidence/release-v0.6.4-verification/manifest.json); released deployment scripts unchanged; actual loaded image IDs/digests/revisions captured before and after browser |
| Ledgers | Core **146\|f**, search **18\|f**, verified after deployment and after provider completion |
| Owner | Browser claim/logout/login/refresh and admin readback PASS; owner `03bc7310-61c8-49b4-8259-273b47c5ecbc` |
| Upload | Browser channel/draft/file/metadata/Publish; video `24ed6a83-18fd-44bc-8bc7-4229b7ba042d`, title `Releaseacceptance08248cc266b3` |
| Canonical B2 original | Browser original download and independent signed S3 GET both **200**, `video/mp4`, **1311662 bytes**, SHA-256 **47e46fdf11a5f3851cd87ab7ea02cb12a5db4f679bef5ee846fad4d6fa74923a**, identical to generated source |
| Real transcoding | Job `df9723dd-9341-4358-8919-aae4f23ec669` observed running then **done**, retry count **0**; CMAF 360p; all **12** advertised playlists/init/fragments fetched successfully |
| Browser playback | Chromium **153.0.8010.12**: time **0 → 3.763359 s**, frames **8 → 122**, decoded audio bytes **6258 → 53549**, unmuted, readyState 4, no media error; seek **7 s** |
| Real search | Same UUID in delivered outbox, search inbox, eligible document and signed internal result; actual UI query raised vidra-search success counter **1 → 2** and opened the result; separate routed fetch recorded `source=search` |
| Actual storage | Same API container inspected before/after; `STORAGE_BACKEND=s3`, exact test bucket/endpoint/region, TLS true/path-style false; live credential privately compared with the provider-verified single-bucket key |
| Provider objects | Empty version inventory before deployment; final inventory **31 version entries: 25 upload versions and 6 hide markers**, including original, ownership marker, thumbnails/storyboards and real transcode files |

The UI search first received **429 / Retry-After 26**; the driver waited and
retried successfully. Request limits and fail-closed ClamAV remained enabled.
The release's default inline worker topology was retained; no separate worker
profile or split-worker resilience result is claimed.

Reviewed screenshots: [owner](evidence/release-v0.6.4-verification/b2-runtime/owner-claimed.png),
[published upload](evidence/release-v0.6.4-verification/b2-runtime/upload-published.png),
[advancing playback](evidence/release-v0.6.4-verification/b2-runtime/playback-advancing.png),
[search result](evidence/release-v0.6.4-verification/b2-runtime/search-result.png).
The watch screenshot also shows a broken default channel-avatar placeholder;
that visual issue was not investigated and did not prevent this milestone.
[Commands](evidence/release-v0.6.4-verification/b2-runtime/commands.json),
[provenance](evidence/release-v0.6.4-verification/b2-runtime/provenance.json) and
[artifact hashes](evidence/release-v0.6.4-verification/b2-runtime/artifact-hashes.json)
retain exact observations, source/tool hashes, commands, exits and raw-log hashes.

## Test-bucket isolation

Only `vidra-acceptance-v064-20260911-media`, bucket ID
`e565124b996984e8a7070215`, endpoint `s3.us-east-005.backblazeb2.com`, region
`us-east-005`, was used. It was newly created **allPrivate**, with default
**SSE-B2 / AES256**. The seven-day application key grants only
`listBuckets,readBuckets,listFiles,readFiles,writeFiles,deleteFiles` for this
exact bucket. Backblaze's authorization response was checked on the host
before installation. The account credential stayed on the operator workstation.

Every existing bucket is excluded, including all Sizetube live/backup buckets
and retained `vidra-acceptance-20260905-a36` recovery evidence. No existing
bucket's contents, versions, lifecycle, retention, CORS or policy changed.
Isolation uses a dedicated bucket and restricted key, not a production prefix.
The initial transfer-review rejection remains in
[historical preparation](evidence/release-v0.6.4-verification/b2-runtime/preparation.json);
the user then explicitly approved the restricted key's transfer to this host.

This proves canonical B2 storage with API-proxied playback. It does not certify
presigned/CDN delivery, destructive GC, recovery, provider version-retention
policy or billing. Hidden staging/probe versions remain visible in the actual
inventory, and no lifecycle rule was added; the recorded retention/billing
risk remains open. See [Backblaze file-version behavior](https://www.backblaze.com/docs/cloud-storage-file-versions)
and [application-key restrictions](https://www.backblaze.com/docs/cloud-storage-application-keys).

## Recorder corrections and evidence boundaries

1. [Attempt 1](evidence/release-v0.6.4-verification/b2-runtime/attempt-1.json)
   stopped before application deployment because the harness assumed the optional
   separate `worker` service was selected. Frozen setup and B2 configuration
   were correct. The correction and regression test are in `c82c806`; only the
   disposable host was rebuilt. Reviewed failure facts, redacted commands and
   raw-log hashes were retained; raw pre-deploy logs/config retired with that
   authorized rebuild. There were no deployed containers/volumes or uploaded media.
2. Attempt 2, harness `c82c8061cf3832bde42f356b8cadde2cc0151637`, completed all
   fresh application/browser steps, then compared B2's original `contentSha1`
   value **`none`** with a SHA-1. B2 documents that multipart/large files can
   lack a native SHA-1; other observed entries carry `unverified:` values.
   Neither should be treated as a checksum attestation.
   [Provider API semantics](https://www.backblaze.com/apidocs/b2-get-file-info).
3. [Read-only completion helper](../tests/release_acceptance_complete_b2.py),
   with corrected [B2 verification](../tests/release_acceptance_b2.py), requires
   the exact known recorder failure, an already passing fresh install/browser
   sequence, unchanged original handoff and matching fixture hash. It performs
   a direct signed S3 GET, compares SHA-256, and inspects actual images/ledgers.
   The original FAIL is never overwritten. Commands and completion evidence
   explicitly identify this supplementary step. No application defect or
   modified-build result was required.

All **52 local checks** pass, including **92 Python tests / zero skips**.
The sanitizer exports only named evidence files and checks them against real
host secrets before transfer. Its first attempt encountered an unset Docker
Env entry; handling that representation was corrected before the successful
export. No incomplete archive was transferred. The reviewed archive SHA-256 is
`c7ab04ae5561a6cae276eaa4e6e7c0a4861e7bd27277e7fa980505a27b8f0294`.
Raw attempt-2 outputs/config/credentials stay on the test host under
`/root/vidra-v064-runtime`; supplementary raw evidence is in
`/root/vidra-v064-b2-completion`.

## Reproduce

Use the [native-host preparation](runtime-acceptance-v0.6.4.md#provision-the-host),
the same frozen manifest and a new blank Ubuntu 24.04 AMD64 host. Both current
hosts are now populated. Do not erase/reuse their evidence or any existing
bucket automatically. The current test-media key expires after seven days.

Create a new private `vidra-acceptance-v064-YYYYMMDD-media-NONCE` bucket and a
new key restricted to it. Put only `bucket`, `bucket_id`, `region`, `endpoint`
in a nonsecret `storage-spec.json`; keep `access_key` and `secret_key` in a
separate mode-0600 JSON file. Use an actual date and lowercase nonce. Example:

```bash
umask 077
mkdir /tmp/vidra-v064-b2-next
b2 bucket create vidra-acceptance-v064-YYYYMMDD-media-NONCE allPrivate \
  --default-server-side-encryption SSE-B2 > /tmp/vidra-v064-b2-next/bucket-id
b2 key create --bucket vidra-acceptance-v064-YYYYMMDD-media-NONCE \
  --duration 604800 vidra-v064-media-acceptance \
  listBuckets,readBuckets,listFiles,readFiles,writeFiles,deleteFiles \
  > /tmp/vidra-v064-b2-next/key.txt
python3 tests/release_acceptance.py prepare \
  --frozen /tmp/vidra-release-verification-20260910/v0.6.4/preflight \
  --node-archive /tmp/vidra-v064-acceptance-toolchain/node-v26.8.1-linux-x64.tar.xz \
  --node-sums /tmp/vidra-v064-acceptance-toolchain/SHASUMS256.txt \
  --b2-spec /tmp/vidra-v064-b2-next/storage-spec.json \
  --out /tmp/vidra-v064-b2-next/handoff
```

Convert the two key values privately into JSON; never print, commit, or include
credentials in the nonsecret handoff archive. Transfer the verified archive
and separately the scoped key to the selected disposable host. Extract into
`/root/vidra-v064-runtime` mode 0700 and store the key at
`/root/vidra-v064-b2-key.json` mode 0600. Then execute on the host:

```bash
python3 /root/vidra-v064-runtime/release_acceptance.py check-host
systemd-run --unit=vidra-v064-acceptance \
  /usr/bin/env -i PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
  LANG=C.UTF-8 /usr/bin/python3 /root/vidra-v064-runtime/release_acceptance.py run \
  /root/vidra-v064-runtime --acknowledge fresh-disposable-host \
  --b2-credentials /root/vidra-v064-b2-key.json
journalctl -u vidra-v064-acceptance --no-pager -n 30
systemctl show vidra-v064-acceptance -p ActiveState -p ExecMainStatus
```

The updated fresh runner performs the direct S3 download itself. The one-time
completion command used for the preserved historical attempt was:

```bash
python3 /root/vidra-v064-b2-completion-tools/release_acceptance_complete_b2.py \
  /root/vidra-v064-runtime /root/vidra-v064-b2-completion \
  --b2-credentials /root/vidra-v064-b2-key.json
python3 /tmp/vidra-export.py /root/vidra-v064-b2-completion
```

For a future uninterrupted runner PASS, invoke the
[export helper](../tests/release_acceptance_export.py) without a completion
argument. Original and supplementary tool revisions/hashes are recorded in
provenance; neither changes the frozen application candidate.

[Current disposition](evidence/release-v0.6.4-verification/b2-runtime/disposition.json)
retains all 59 workflow procedures, 40 acceptance criteria and ten scope
families. Provider access is now available for STO-01/02/03 and INT-09, so
unexecuted remaining cases are UNVERIFIED rather than blocked on missing bucket
credentials. Counts: **2 PASS, 45 UNVERIFIED, 12 BLOCKED**. No blanket storage,
provider or recovery acceptance is claimed. Missing other providers,
representative-source/recovery inputs and scope decisions block only dependent
checks. Historical local/fixture results remain historical.

[Draft PR #186](https://github.com/yegamble/vidra/pull/186) remains **open —
awaiting review and merge**; merging, releases and production deployment are
prohibited in this session. The local-pass host `159.65.249.255` and B2-pass
host `159.203.118.182` retain private evidence, at approximately **$0.28572/hour
combined** while retained.
