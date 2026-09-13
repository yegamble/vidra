# v0.6.4 dependency and image vulnerability scan — 2026-09-12

**v0.6.4 remains NO-GO. Its security scan facet is FAIL as published.** This
record adds the scans that had never been run against the exact candidate, the
triage of what they found, and CI gates that keep the question asked. It does
not change any workflow-row status: counts stay those of the current
disposition (2 PASS, 45 UNVERIFIED, 12 BLOCKED on PR #187's branch). No
merge, release, tag move, deployment or host change was made.

Machine-readable record: [dependency-scan/summary.json](evidence/release-v0.6.4-verification/dependency-scan/summary.json)
(13 scanner runs, exits, scanner/database versions, raw-output hashes).
Raw scanner output is under `dependency-scan/raw/` (gzipped JSON; local paths
replaced with `<scratch>`/`~`; secret-grepped before commit).

## Candidate and boundary

The [immutable manifest](evidence/release-v0.6.4-verification/manifest.json) is
unchanged: core `ed55a6d`, user `e584069`, search `1f8b854`. Images were pulled
anonymously **by linux/amd64 platform-manifest digest** with crane v0.22.1; each
manifest's SHA-256 was recomputed and matched the digest. Images were scanned as
files on a darwin/arm64 workstation and never executed, so this is artifact
evidence, not runtime evidence. The core and search `/app/api` binaries report
`go1.27.1`; core's hash `0ec31451…ba90a` matches the binary PR #187 extracted on
the retained host. Current component mains (core `0261b59`, user `dc4f164`,
search `5f7a3a3`) were scanned separately and are not the candidate.

Scanners, all fetched through the Go module proxy at exact versions (checksum
database pinned; no Trivy binaries or actions were used — see the March 2026
Trivy release/action compromise): govulncheck v1.3.0 (database modified
2026-09-10T14:48:42Z), osv-scanner 2.5.1 / osv-scalibr 0.5.2 (api.osv.dev queried
online 2026-09-13T02:37–02:38Z), npm audit (registry bulk endpoint; npm exposes
no database timestamp). A scanner or network failure is recorded as a failure,
never as clean.

## What ran

| Target | Scanner | Exit | Result |
|---|---|---|---|
| core source v0.6.4 and main | govulncheck source, go1.27.1, linux/amd64 | 0 / 0 | 0 reachable; 1 module-level (GO-2026-5932, x/crypto/openpgp) |
| search source v0.6.4 and main | govulncheck source, go1.27.1 | 0 / 0 | 0 reachable; 4 module-level (GO-2026-5932, -6303, -6354, -6355) |
| core, search released binaries | govulncheck `-mode=binary` | 0 / 0 | same IDs as symbol rows; binary mode cannot prove reachability, and `go list -deps ./cmd/api` shows neither `x/crypto/ssh` nor `x/crypto/openpgp` linked (655 / 374 deps) |
| user lockfile v0.6.4 and main | npm audit (runtime `--omit=dev`; full) | 1 / 1 | runtime: 1 critical, 1 moderate; full: 1 critical, 4 high, 1 moderate — identical on main |
| core image | osv-scanner image | 1 | 138 apk, 71 Go, 97 crates, 1 PyPI packages; findings below |
| user image | osv-scanner image | 1 | **18 apk packages only — zero npm packages, no node binary detected** |
| search image | osv-scanner image | 1 | 21 apk, 32 Go packages; findings below |

## Triage (what affects Vidra, under which conditions, smallest safe mitigation, how to verify)

| # | Finding | Affects Vidra? | Mitigation | Verify |
|---|---|---|---|---|
| T1 | **next 16.3.0** (user image + lockfile): GHSA-2xp9-vwfh-vxw4 critical (Image Optimization API decoding AVIF via sharp/libheif), GHSA-p293-qw3h-jr36 critical (Windows-hosted servers) | GHSA-p293: no (Linux image). GHSA-2xp9: **exposure not demonstrated**. `/_next/image` is enabled (no `images` config) and Caddy routes it to the frontend, but remote URLs are refused by default and local URLs are fetched in-process through Next's own routes, none of which returns attacker-controlled image bytes (review of e584069). The shipped image already contains sharp 0.35.4 / sharp-libvips 1.3.3 — the floor Next 16.3.4 requires — verified by extracting `/app/node_modules/*/package.json` from the digest. | Upgrade to next 16.3.5 (vidra-user#218). Optional hardening: `images.unoptimized: true` or a Caddy `404` for `/_next/image*`, since the app never uses the optimizer. | `npm run audit:deps` exit 0; image rebuild then `app/node_modules/next/package.json` = 16.3.5 |
| T2 | user tooling tree: js-yaml, brace-expansion, browserslist, @redocly/openapi-core (high); baseline-browser-mapping (moderate, runtime tree) | Build/lint/test time; DoS-class; not demonstrated at runtime | In-range lockfile updates, no `--force` (vidra-user#218) | same |
| T3 | **Alpine openssl 3.5.7-r0** (libssl3/libcrypto3) in **all three images**: ten CVEs incl. ALPINE-CVE-2026-63073 (CMP, 9.8) and -75803 (ChaCha20-Poly1305/AES-OCB empty-ciphertext tag check, 9.1); fixed 3.5.8-r0 | core: yes for outbound TLS by ffmpeg, python3/yt-dlp and wget. user: node does not link it (`DT_NEEDED` = libstdc++, libgcc_s, musl; node embeds its own OpenSSL). search: Go binary does not use it. The v3.24 main repository has 3.5.8-r0 but the `alpine:3.24` base image (checked 2026-09-13) still ships 3.5.7-r0, so **a plain rebuild re-ships it**. | Upgrade base packages in each runtime stage, then build a new candidate | Rebuilt image: `apk info -v libssl3` ≥ 3.5.8-r0; osv-scanner image rows gone |
| T4 | **grpc 1.83.1** in core `/app/api` (indirect): GHSA-2v4p-qf9q-27wj high, xDS-server DoS; fixed 1.83.2 | Not reachable: core registers no `xds.NewGRPCServer` and imports no grpc directly. Invisible to govulncheck — absent from the Go vulnerability database at the recorded timestamp; only osv-scanner reported it. | Bump to 1.83.2 so the advisory is gone rather than argued | `go mod tidy -diff` clean; osv-scanner binary row gone |
| T5 | x/crypto GO-2026-5932 (openpgp, no fix), search x/crypto 0.54.0 ssh advisories (-6303 fixed 0.55.0; -6354/-6355 fixed 0.56.0) | Not linked into either released binary (package graph above) | Search: bump x/crypto to ≥0.56.0 to remove the rows; openpgp: none (not imported) | govulncheck module rows |
| T6 | core image rav1e 0.8.1 / libdovi 3.3.2 (ffmpeg dependencies): RUSTSEC-2026-0190 (anyhow unsoundness), -0204 (crossbeam-epoch), -0097 / GHSA-cq8v (rand unsound with custom logger), -0105 / 2024-0436 (unmaintained core2, paste) | Unsoundness/unmaintained classes in media libraries that parse untrusted uploads; no exploit path demonstrated. **No Alpine v3.24 fix exists** (repository version = image version). | Owner risk decision: accept pending Alpine, or build without these codecs | APKINDEX version change |
| T7 | core glib 2.88.1-r1 flagged ALPINE-CVE-2021-27219 (fixed 2.66.6) | **Scanner false positive** — the installed version is newer than the fix | None; recorded, not suppressed | — |
| T8 | **Scanner coverage gap**: osv-scanner found no npm packages in the user image, so it missed T1 | An image scan alone is not a frontend dependency scan; govulncheck alone misses GHSA-only Go advisories (T4) | Release qualification needs lockfile audit + govulncheck + image scan together | This table |

## CI gates added (open draft PRs, not merged)

| PR | Gate | Real-CI proof on the PR head |
|---|---|---|
| [vidra-user#218](https://github.com/yegamble/vidra-user/pull/218) `b71fcaa` | `dependency-audit` required: any runtime advisory, high/critical anywhere, or an unreachable endpoint fails; PRs, main, daily. Includes the next 16.3.5 fix. | [run 34733894868](https://github.com/yegamble/vidra-user/actions/runs/34733894868/job/103661688061): node 26.8.2 / npm 11.19.1, both audits `found 0 vulnerabilities` |
| [vidra-core#233](https://github.com/yegamble/vidra-core/pull/233) `db2b3c7` | `govulncheck` required (`make vuln`), PRs, main, daily | [run 34733893225](https://github.com/yegamble/vidra-core/actions/runs/34733893225/job/103661684605): go1.27.1 linux/amd64, DB 2026-09-10 14:48:42, 70 modules, 0 affected |
| [vidra-search#43](https://github.com/yegamble/vidra-search/pull/43) `e21fd9d` | same twin | [govulncheck](https://github.com/yegamble/vidra-search/actions/runs/34733894551/job/103661687536) success; [ci-required](https://github.com/yegamble/vidra-search/actions/runs/34733894582/job/103661687580) success with the new lane required |

Failure propagation was proven locally, not only the green path: the npm gate
exits 1 on the v0.6.4 and main lockfiles, 1 with the registry unreachable, and 1
with a hostile `.npmrc`. A fresh-context review found that `offline=true` in an
`.npmrc` made the **original** script print "found 0 vulnerabilities" and exit 0
against the critical lockfile; that defect was reproduced and fixed
(`--offline=false`, `--include=dev`) before this record. govulncheck exits 2 via
make (3 from the scanner) on a stale go1.26.2 toolchain with reachable stdlib
advisories, and 1 when the database is unreachable. Gate outputs are in `raw/`.

## Other defects found while doing this

- **Required CI broken upstream.** Docker Hub's `minio/minio` repository no longer
  resolves (404, "pull access denied"), so vidra-core `integration` and vidra-user
  `e2e-backed (s3)` fail on every commit, including main's next run; operators
  on the bundled `storage` profile cannot pull it either. Fix:
  [vidra-core#234](https://github.com/yegamble/vidra-core/pull/234) — same release
  tag from quay.io pinned by digest; its `integration` lane
  [passed](https://github.com/yegamble/vidra-core/actions/runs/34733953941/job/103661850424).
  vidra-user#218's s3 lane stays red until #234 merges (core-first).
- **`ci-required` has fail-open paths** (reproduced with a stubbed `gh`): any
  failed API call silently disables the zero-job guard; a `?` jobs count passes;
  `startup_failure` is not matched; partial pagination is accepted; with two
  same-named check-runs on one SHA the first row wins (duplicates really occur,
  e.g. search `1f8b854`); a non-Actions app's same-named check counts; the
  workflow lacks `actions: read`. The meta copy also lacks the zero-job guard.
  No repository tested the script. Fix with a byte-identical twin regression
  test (15 of 35 assertions RED on the component copy, 17 on meta; 0 after):
  [vidra#188](https://github.com/yegamble/vidra/pull/188),
  [vidra-core#235](https://github.com/yegamble/vidra-core/pull/235),
  [vidra-search#44](https://github.com/yegamble/vidra-search/pull/44),
  [vidra-user#219](https://github.com/yegamble/vidra-user/pull/219).
- **No release-mapping preflight.** Nothing machine-readable maps a platform
  release to component versions and digests; a user tag from another release or
  a never-released core/search pairing deploys; bundle tag and env tags are never
  compared; images are pulled by tag only; no test proved a refusal. Fix:
  [vidra#189](https://github.com/yegamble/vidra/pull/189) adds `releases/v0.6.4.json`
  (cross-checked against the evidence manifest) and `deploy/release-mapping.py`,
  called before the checkout sync, dump, pull, migrate and `up` in `deploy.sh`
  and before the env rewrite in `rollback.sh`. RED: core v0.6.4 + user v0.6.3 +
  search v0.6.4 dumped, pulled, migrated, started and exited 0; GREEN: refused
  with no stubbed dump/pull/migrate/up call. Pulling by digest and the owner
  decisions in that PR remain open.
- **Image findings T3/T4 and unverified yt-dlp** — fixes on main only:
  [vidra-core#236](https://github.com/yegamble/vidra-core/pull/236) (runtime
  `apk upgrade`, grpc 1.83.2, yt-dlp checked against the signed SHA2-256SUMS
  value `495be29f…49f3fd`),
  [vidra-search#45](https://github.com/yegamble/vidra-search/pull/45),
  [vidra-user#220](https://github.com/yegamble/vidra-user/pull/220). Local
  **arm64** builds showed libssl3 3.5.8-r0 and a wrong hash failing the build;
  no CI lane builds the production Dockerfiles, so the amd64 release build is
  unverified until a candidate is built.
- **Operator-facing drift.** `env/production.env.example` and
  `env/staging.env.example` pin v0.6.3 (also inside the v0.6.4 meta tag) while
  the installer resolves core's latest release; the installer's git path clones
  meta at `main`; `docs/releases/` has no v0.6.4 notes; vidra-site renders
  `VERSION` v0.6.0 from `lib/envelope.json` and has no LICENSE or
  `dependabot.yml`. Its v0.5.0 strings are mostly deliberate screenshot
  provenance. Bumping templates to v0.6.4 would advertise a NO-GO release — an
  owner decision.
- **Dependabot alerts and security updates are disabled in all four service
  repositories** (repository settings; owner action). The new gates do not
  replace them.
- **yt-dlp** is downloaded into the core image by version with no checksum; base
  images are pinned by tag, not digest; build provenance attestations are
  produced but never verified by deploy tooling.

## Dispositions

| Criterion | Before | After this record | Why |
|---|---|---|---|
| REL-01 / A39 security facet | not measured | **FAIL for v0.6.4 as published** | T1, T3, T4 are known advisories in shipped artifacts; fixes are on unmerged branches, and an unreleased fix is not a released fix |
| QLT-01 | UNVERIFIED (U1) | UNVERIFIED (U1) | Vulnerability lanes now exist and pass on PR heads but are unmerged; `ci-required` fail-open paths remain; companion-revision and skipped-lane gaps unchanged |
| REL-01 mapping preflight | not measured | **FAIL (absent)** | Deliberate mismatches are not refused before mutation |
| All other rows | unchanged | unchanged | No runtime acceptance ran in this session (see blockers) |

Full release remains **NO-GO**.

## Blockers for runtime acceptance in this session

- **Acceptance hosts unreachable from this workstation.** `159.203.118.182` and
  `159.65.249.255` accept TCP/22 but SSH times out at the banner; this
  workstation's egress address is `146.70.72.166`, while the acceptance firewall
  rule added on 2026-09-11 allows `185.244.215.14/32`. Smallest operator action:
  approve adding the current address to that firewall for TCP/22 (or supply the
  approved route). No firewall change was made.
- Local Docker daemon not running (ARM64 regardless; not release acceptance).
- Unchanged: representative sanitized PeerTube source and inventory (B2);
  approval to place the generated fixture passwords on the test host (MIG-02);
  independent restore destination and approved RPO/RTO (B4); selected-provider
  credentials (B3); the retained B2 media key expires 2026-09-18.

## Continuation

Merge order when authorized: core#234 first (unblocks every core and user PR);
then core#233, search#43, user#218 in any order. A new candidate must include
the image and dependency fixes, then be re-scanned **by digest** with all three
scanners before any acceptance run is promoted to it.

```bash
# exact-candidate rescan (replace digests from the new manifest)
export GOTOOLCHAIN=go1.27.1 GOBIN=$PWD/bin   # one module@version per go install
go install golang.org/x/vuln/cmd/govulncheck@v1.3.0
go install github.com/google/osv-scanner/v2/cmd/osv-scanner@v2.5.1
go install github.com/google/go-containerregistry/cmd/crane@v0.22.1
bin/crane pull --format tarball ghcr.io/yegamble/vidra-core@<platform-digest> core.tar
bin/osv-scanner scan image --archive core.tar --format json --output-file core.osv.json
bin/govulncheck -json ./...            # in each frozen Go source
npm run audit:deps                     # in the frozen vidra-user source (after #218)
```
