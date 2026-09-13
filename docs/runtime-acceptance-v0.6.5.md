# v0.6.5 first runtime milestone — local storage demonstrated

**PASS for this bounded milestone on the published v0.6.5 images. Full release
readiness remains NO-GO.** This is the v0.6.5 run of the A02/A03 runtime
acceptance harness recorded for v0.6.4 in
[runtime-acceptance-v0.6.4.md](runtime-acceptance-v0.6.4.md), with the same
scope (a blank native host, the released installer, CLI and bundle by checksum,
the published images by digest, one browser-driven upload → transcode →
playback → search on **local canonical storage**). It does not certify B2,
migration, recovery or any row the v0.6.4 continuations covered; those stay
UNVERIFIED for v0.6.5 until run on its digests.

The harness was made release-agnostic for this run (meta#200: `prepare
--candidate docs/evidence/release-v0.6.5-verification/manifest.json`; the
handoff records the candidate tag and `run` refuses a handoff prepared for
another release). The handoff was built from a fresh
`deploy/release-preflight.py --tag v0.6.5 --platform linux/amd64` run (status
PASS; its manifest carries the same repositories, image digests and asset
hashes as the committed
[frozen manifest](evidence/release-v0.6.5-verification/manifest.json) and
differs only in `created_at`):
`handoff.json` sha256 `579ae19259819197702851bd37f44f115b75943c7a4aba203240004d6d02314d`,
transferred as a tarball whose sha256 `5a51ef3f…8db195` matched on the host.

Host: droplet **599531580** (159.203.118.182), rebuilt blank by the operator at
**15:29:26 UTC** (no Docker, empty `/opt`), native Ubuntu **24.04.4 LTS /
x86_64**, 8 vCPUs; `check-host` passed (root, systemd, no container, no
existing data). The browser used `https://secure.video.test` inside the guest.
Production and the other acceptance host were untouched. No application
source, image or released deployment script changed; only the six application
image references were replaced with the frozen digests.

The uninterrupted passing run lasted from **2026-09-13 15:38:05 UTC** to
**2026-09-13 15:42:54 UTC** (289.3 s) as transient unit
`vidra-v065-acceptance`.
[Runtime observations](evidence/release-v0.6.5-verification/native-runtime/result.json),
[browser measurements](evidence/release-v0.6.5-verification/native-runtime/browser-result.json),
[exact host commands](evidence/release-v0.6.5-verification/native-runtime/host-commands.json)
and [export provenance](evidence/release-v0.6.5-verification/native-runtime/export-provenance.json)
record the actual execution; the raw logs stay on the host.

| Required step | Actual result |
|---|---|
| Fresh installation | Blank native host; released installer (sha256 `d0e632d5…4eea`, the v0.6.5 `install.sh`), CLI `vidra_v0.6.5_linux_amd64` (`8af9ccf7…afce`) and bundle by checksum; corruption refusal for a tampered bundle and CLI; configuration-preserving reinstall — all PASS; Docker 29.8.0, Compose 5.5.1 |
| Deployment | The three published images by index digest (core `a6e08b93…3bb1`, user `08e920ba…3178`, search `55196d27…a0f8`) inspected before and after the browser phase with unchanged container ids; released deploy script unchanged; core **146\|f** from `d13d40e6`, search **18\|f** from `b7a7f55b`; api/frontend published on 127.0.0.1 only, postgres/redis/search unpublished; api, frontend, search, postgres, redis, caddy **and clamav** healthy (scanning at its default `fail-closed`); edge `/healthz`, `/readyz`, `/version` PASS |
| Owner | Browser claim of the boot token, logout, login, refresh and persisted admin identity PASS; owner `a3929797-c792-4a31-8f5c-95268132792b` |
| Real upload | Browser-created channel `5d3df7db-63d2-44d7-881f-469061a5a9f0`, draft, file selection, metadata/public privacy and Publish; video `60d4ec9e-6c3a-46df-98f1-43ff5ab2cf64`; downloaded original **1311662 bytes**, `video/mp4`, SHA-256 `47e46fdf…923a` equal to the source fixture |
| Real transcode | Durable job `fa6dbfdd-8426-45ca-a454-e9c61cd8fe7d` observed `running` → **`done`**, retry counter **0**; a 360p CMAF rendition and **12** advertised playlist/init/fragment assets fetched successfully; 28 media requests recorded (thumbnail 200, original 206, segments 200) |
| Browser playback | Chromium **153.0.8010.12** on Node **26.8.1**; HLS playback time **0.00 → 3.76 s**, decoded frames **13 → 128**, decoded audio bytes **9955 → 57246**; unmuted, `readyState` 4, no media error |
| Real search | The same UUID in the outbox/inbox, an eligible search document, the signed internal query (`score` 0.90, `simple-v1`); the UI query `Releaseacceptance92cc65bc8369` met the published request limit once (`429`, Retry-After 34 s, honoured) and returned it on the second attempt; vidra-search successful query counter **1 → 2**; the routed fetch returned the same id on its first request |

Actual screenshots: [claimed owner](evidence/release-v0.6.5-verification/native-runtime/owner-claimed.png),
[published upload](evidence/release-v0.6.5-verification/native-runtime/upload-published.png),
[advancing playback](evidence/release-v0.6.5-verification/native-runtime/playback-advancing.png),
[search result](evidence/release-v0.6.5-verification/native-runtime/search-result.png).
Hashes: [export-hashes.json](evidence/release-v0.6.5-verification/native-runtime/export-hashes.json)
(written by the exporter on the host) and
[artifact-hashes.json](evidence/release-v0.6.5-verification/native-runtime/artifact-hashes.json)
(recomputed over the committed copies, plus the disposition).

Export: `tests/release_acceptance_export.py /root/vidra-v065-runtime` at the
PR's first revision (the stage as its argument; this local-storage run never
takes the B2-completion branch that the review round later corrected).
Exporter secret scan PASS; archive sha256
`efa55c0c942c54ee90a13f03e0c3a766037d842aa4e1edd5b21d42079a30825e`, identical
on the host and here. Raw `result.json`, `browser-result.json` and
`commands.jsonl` hashes are in `export-provenance.json`.

Two things went wrong on the way and are recorded rather than hidden: the
first handoff tarball was built with macOS `tar`, which added AppleDouble
`._*` metadata files and my uid to the stage — it was rebuilt with
`COPYFILE_DISABLE=1 --no-xattrs`, re-transferred (new sha256) and unpacked as
root before the run; and an export was attempted before the run had started
(and with the pre-#200 helper), which created an empty
`/root/vidra-v064-reviewed-evidence` directory, removed before the real export.
Neither touched the run's inputs: `check-host` was re-run on the rebuilt stage
and the harness's own reuse guards were satisfied.

[Local-run disposition](evidence/release-v0.6.5-verification/native-runtime/disposition.json)
is derived from the v0.6.4 native-runtime disposition: **SRC-01 PASS** (this
run), **INS-03 PASS** retained on the v0.6.5 preflight, **REC-03 PASS**
([meta#199](runtime-acceptance-rec03-v0.6.5.md)); every row a v0.6.4
continuation had moved is UNVERIFIED again for v0.6.5; B2–B5/U1 blockers
carry over. Counts: **3 PASS / 41 UNVERIFIED / 15 BLOCKED**.

## Not covered by this run

B2 or any S3 provider; the PeerTube migration and restart continuation; the
recovery drill (crash, outages, backup, replacement-host restore); WebKit or a
mobile viewport; TLS via ACME; a second host. Each has its v0.6.4 record and
harness; running them on the v0.6.5 digests is the remaining executable work.
