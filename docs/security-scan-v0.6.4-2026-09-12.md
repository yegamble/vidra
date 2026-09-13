# v0.6.4 dependency and image vulnerability scan — 2026-09-12

**v0.6.4 remains NO-GO. Its security scan facet is FAIL as published.** This
record adds the scans that had never been run against the exact candidate, the
triage of what they found, and CI gates that keep the question asked. It does
not change any workflow-row status: counts stay those of the current
disposition (2 PASS, 45 UNVERIFIED, 12 BLOCKED on PR #187's branch, `ed4c82d`
on 2026-09-12). No merge, release, tag move, deployment or host change was made
by this record. **Audit fixes 2026-09-13:** every point-in-time fact about
another PR below (head, test count, merge state, pinned version) now carries the
commit or the time it was true; the section "CI gates added" and the defects
list reflect the merges of core#234, search#43 and user#218 on 2026-09-13.

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
the retained host. Component mains at scan time (2026-09-13T02:50Z: core
`0261b59`, user `dc4f164`, search `5f7a3a3`) were scanned separately and are not
the candidate; all three mains have moved since (core#234, search#43 and
user#218 merged on 2026-09-13, see "CI gates added").

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
| core, search released binaries | govulncheck `-mode=binary` | 0 / 0 | same IDs as symbol rows; binary mode cannot prove reachability, and `go list -deps ./cmd/api` for linux/amd64 lists neither `x/crypto/ssh` nor `x/crypto/openpgp`: core's graph (655 lines, at `ed55a6d`) is committed on #187's branch as `migration-runtime/security/api-package-graph.txt`; search's (374 lines, at `1f8b854`, `GOTOOLCHAIN=go1.27.1 GOOS=linux GOARCH=amd64`, produced 2026-09-13T05:25Z) is `raw/vidra-search-v064-api-package-graph.txt`; `grep -cE 'x/crypto/(ssh\|openpgp)'` = 0 on both |
| user lockfile v0.6.4 and main | npm audit (runtime `--omit=dev`; full) | 1 / 1 | runtime: 1 critical, 1 moderate; full: 1 critical, 4 high, 1 moderate — identical on main |
| core image | osv-scanner image | 1 | 138 apk, 71 Go, 97 crates, 1 PyPI packages; findings below |
| user image | osv-scanner image | 1 | **18 apk packages only — zero npm packages, no node binary detected** |
| search image | osv-scanner image | 1 | 21 apk, 32 Go packages; findings below |

## Triage (what affects Vidra, under which conditions, smallest safe mitigation, how to verify)

| # | Finding | Affects Vidra? | Mitigation | Verify |
|---|---|---|---|---|
| T1 | **next 16.3.0** (user image + lockfile): GHSA-2xp9-vwfh-vxw4 critical (Image Optimization API decoding AVIF via sharp/libheif), GHSA-p293-qw3h-jr36 critical (Windows-hosted servers) | GHSA-p293: no (Linux image). GHSA-2xp9: **exposure not demonstrated**. `/_next/image` is enabled (no `images` config) and Caddy routes it to the frontend, but remote URLs are refused by default and local URLs are fetched in-process through Next's own routes, none of which returns attacker-controlled image bytes (review of e584069). The shipped image already contains sharp 0.35.4 / sharp-libvips 1.3.3 — the floor Next 16.3.4 requires — verified by extracting `/app/node_modules/*/package.json` from the digest. | Upgrade to next 16.3.5 (vidra-user#218). Optional hardening: `images.unoptimized: true` or a Caddy `404` for `/_next/image*`, since the app never uses the optimizer. | `npm run audit:deps` exit 0; image rebuild then `app/node_modules/next/package.json` = 16.3.5 |
| T2 | user tooling tree: js-yaml, brace-expansion, browserslist, @redocly/openapi-core (high); baseline-browser-mapping (moderate, runtime tree) | Build/lint/test time; DoS-class; not demonstrated at runtime | In-range lockfile updates, no `--force` (vidra-user#218) | same |
| T3 | **Alpine openssl 3.5.7-r0** (libssl3/libcrypto3) in **all three images**: ten CVEs incl. ALPINE-CVE-2026-63073 (CMP, 9.8) and -75803 (ChaCha20-Poly1305/AES-OCB empty-ciphertext tag check, 9.1); fixed 3.5.8-r0 | core: yes for outbound TLS by ffmpeg, python3/yt-dlp and wget. user: node does not link it (`DT_NEEDED` = libstdc++, libgcc_s, musl; node embeds its own OpenSSL). search: Go binary does not use it. The v3.24 main repository has 3.5.8-r0 but the `alpine:3.24` base image still ships 3.5.7-r0, so **a plain rebuild re-ships it** — `raw/alpine-3.24-apk-policy.txt` (`apk policy` inside `alpine:3.24` = 3.24.1, index digest `28bd5fe8…43f8b`, linux/amd64, captured 2026-09-13T05:23Z: installed 3.5.7-r0, v3.24/main offers 3.5.8-r0). | Upgrade base packages in each runtime stage, then build a new candidate | Rebuilt image: `apk info -v libssl3` ≥ 3.5.8-r0; osv-scanner image rows gone |
| T4 | **grpc 1.83.1** in core `/app/api` (indirect): GHSA-2v4p-qf9q-27wj high, xDS-server DoS; fixed 1.83.2 | Not reachable: core registers no `xds.NewGRPCServer` and imports no grpc directly. Invisible to govulncheck — absent from the Go vulnerability database at the recorded timestamp; only osv-scanner reported it. | Bump to 1.83.2 so the advisory is gone rather than argued | `go mod tidy -diff` clean; osv-scanner binary row gone |
| T5 | x/crypto GO-2026-5932 (openpgp, no fix), search x/crypto 0.54.0 ssh advisories (-6303 fixed 0.55.0; -6354/-6355 fixed 0.56.0) | Not linked into either released binary (package graph above) | Search: bump x/crypto to ≥0.56.0 to remove the rows; openpgp: none (not imported) | govulncheck module rows |
| T6 | core image rav1e 0.8.1 / libdovi 3.3.2 (ffmpeg dependencies): RUSTSEC-2026-0190 (anyhow unsoundness), -0204 (crossbeam-epoch), -0097 / GHSA-cq8v (rand unsound with custom logger), -0105 / 2024-0436 (unmaintained core2, paste) | Unsoundness/unmaintained classes in media libraries that parse untrusted uploads; no exploit path demonstrated. **No Alpine v3.24 fix exists**: v3.24/community carries rav1e / rav1e-libs 0.8.1-r0 and libdovi 3.3.2-r0, the image's versions (`raw/alpine-3.24-apk-policy.txt`, 2026-09-13T05:23Z). | Owner risk decision: accept pending Alpine, or build without these codecs | APKINDEX version change |
| T7 | core glib 2.88.1-r1 flagged ALPINE-CVE-2021-27219 (fixed 2.66.6) | **Scanner false positive** — the installed version is newer than the fix | None; recorded, not suppressed | — |
| T8 | **Scanner coverage gap**: osv-scanner found no npm packages in the user image, so it missed T1 | An image scan alone is not a frontend dependency scan; govulncheck alone misses GHSA-only Go advisories (T4); no Python/uv dependency tree was scanned in any repo (vidra-search `training/uv.lock` — Dependabot opened a medium pytest alert on it on 2026-09-13, see below) | Release qualification needs lockfile audit + govulncheck + image scan together, plus a uv/pip audit for the training tree | This table |

## CI gates added (state as of 2026-09-13T05:25Z)

| PR | Gate | Real-CI proof at the commit named |
|---|---|---|
| [vidra-user#218](https://github.com/yegamble/vidra-user/pull/218) `b71fcaa`; **merged 2026-09-13T05:17:11Z** as `6854c0f` | `dependency-audit` required: any runtime advisory, high/critical anywhere, or an unreachable endpoint fails; PRs, main, daily. Includes the next 16.3.5 fix. | At `b71fcaa`, [run 34733894868](https://github.com/yegamble/vidra-user/actions/runs/34733894868/job/103661688061): node 26.8.2 / npm 11.19.1, both audits `found 0 vulnerabilities`. On merged main at `6854c0f`, [run 34739921397](https://github.com/yegamble/vidra-user/actions/runs/34739921397/job/103677778860) success (05:17Z). |
| [vidra-core#233](https://github.com/yegamble/vidra-core/pull/233) `db2b3c7`; **open**, head `1d1e15e` — `d976d65` (05:03Z) raised `GOVULNCHECK_VERSION` v1.3.0 → v1.8.0 | `govulncheck` required (`make vuln`), PRs, main, daily | At `db2b3c7`, [run 34733893225](https://github.com/yegamble/vidra-core/actions/runs/34733893225/job/103661684605): govulncheck v1.3.0, go1.27.1 linux/amd64, DB 2026-09-10 14:48:42, 70 modules, 0 affected. At `1d1e15e`, [govulncheck v1.8.0](https://github.com/yegamble/vidra-core/actions/runs/34739569332/job/103676849862) "No vulnerabilities found" (05:09Z) and [ci-required](https://github.com/yegamble/vidra-core/actions/runs/34739569335) success (05:24:51Z, after core#234 merged). |
| [vidra-search#43](https://github.com/yegamble/vidra-search/pull/43) `e21fd9d`; **merged 2026-09-13T05:16:02Z** as `92bdd79` — `f326dd0` raised the pin to v1.8.0 | same twin | At `e21fd9d`, [govulncheck](https://github.com/yegamble/vidra-search/actions/runs/34733894551/job/103661687536) success and [ci-required](https://github.com/yegamble/vidra-search/actions/runs/34733894582/job/103661687580) success with the new lane required. On merged main at `92bdd79`, [govulncheck v1.8.0](https://github.com/yegamble/vidra-search/actions/runs/34739875773/job/103677657319) "No vulnerabilities found" (05:16Z). |

The scans in this record used govulncheck v1.3.0 (the pin at the time); the
lanes now run v1.8.0 and reported no reachable advisory on the current
sources at the commits above, which does not re-scan the v0.6.4 candidate.

Failure propagation was proven locally, not only the green path: the npm gate
exits 1 on the v0.6.4 and main lockfiles, 1 with the registry unreachable, and 1
with a hostile `.npmrc`. A fresh-context review found that `offline=true` in an
`.npmrc` made the **original** script (vidra-user `b6cdaea`) print "found 0
vulnerabilities" and exit 0 against the critical lockfile; the defect was fixed
(`--offline=false`, `--include=dev`, `b71fcaa`) before this record. That review
run kept no log, so it was reproduced for the record on 2026-09-13T05:26Z with
the `b6cdaea` script, the v0.6.4 lockfile (`e584069`) and an `.npmrc` of
`offline=true` (node v22.14.0 / npm 10.9.2): both audits printed `found 0
vulnerabilities`, exit 0 — `raw/dependency-audit-gate-original-offline-npmrc.txt`;
the same inputs without the `.npmrc` exit 1 with 2 / 6 findings. govulncheck
exits 2 via make (3 from the scanner) on a stale go1.26.2 toolchain with
reachable stdlib advisories, and 1 on an invalid vulndb URL (`https://vuln.invalid`:
the log says `unrecognized vulndb format`, a format error rather than a DNS
failure; the `make` exit was not captured in that log). Gate outputs are in
`raw/`.

## Other defects found while doing this

- **Required CI broken upstream.** Docker Hub's `minio/minio` repository no longer
  resolves (404, "pull access denied"), so vidra-core `integration` and vidra-user
  `e2e-backed (s3)` fail on every commit, including main's next run; operators
  on the bundled `storage` profile cannot pull it either. Fix:
  [vidra-core#234](https://github.com/yegamble/vidra-core/pull/234) — same release
  tag from quay.io pinned by digest; its `integration` lane
  [passed](https://github.com/yegamble/vidra-core/actions/runs/34733953941/job/103661850424).
  core#234 **merged 2026-09-13T04:54:19Z** as `f87bf6f`; vidra-user#218's
  `ci-required` then passed on `87537c1` and #218 merged at 05:17:11Z.
- **`ci-required` has fail-open paths** (reproduced with a stubbed `gh`): any
  failed API call silently disables the zero-job guard; a `?` jobs count passes;
  `startup_failure` is not matched; partial pagination is accepted; with two
  same-named check-runs on one SHA the first row wins (duplicates really occur,
  e.g. search `1f8b854`); a non-Actions app's same-named check counts; the
  workflow lacks `actions: read`. The meta copy also lacks the zero-job guard.
  No repository tested the script. Fix with a byte-identical twin regression
  test, re-run 2026-09-13T05:25Z against the copies on `main`: at the suite's
  current revision (vidra#188 head `c51d083`, test file last changed in
  `4b5355a`) 45 cases / 52 assertions, **25 RED against vidra-core main's copy
  (`f87bf6f`, blob `524b9e3`), 27 against meta main's (`67840ab`, blob
  `ffe1298`), 0 against the fixed script**; the suite's earlier revisions read
  33/35 with 15/17 RED (`f841c98`, the figures first recorded here) and 38/41
  with 19/21 RED (`c3c32ac`). PRs (heads at 05:25Z):
  [vidra#188](https://github.com/yegamble/vidra/pull/188) `c51d083`,
  [vidra-core#235](https://github.com/yegamble/vidra-core/pull/235) `65c4a2b`,
  [vidra-search#44](https://github.com/yegamble/vidra-search/pull/44) `f5c3f3f`,
  [vidra-user#219](https://github.com/yegamble/vidra-user/pull/219) `6b237ca`;
  all four open.
- **No release-mapping preflight.** Nothing machine-readable maps a platform
  release to component versions and digests; a user tag from another release or
  a never-released core/search pairing deploys; bundle tag and env tags are never
  compared; images are pulled by tag only; no test proved a refusal. Fix:
  [vidra#189](https://github.com/yegamble/vidra/pull/189) (open, head `02ad018`
  at 2026-09-13T05:25Z) adds `releases/v0.6.4.json`
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
  **arm64** builds showed libssl3 3.5.8-r0 and a wrong hash failing the build
  (run locally; build log not retained). Since this record, a path-filtered
  `docker-build` PR lane on those PRs built all three production Dockerfiles
  on GitHub for linux/amd64 without pushing, and each log shows `Upgrading
  libssl3 (3.5.7-r0 -> 3.5.8-r0)`: core#236 `8734545`
  [run 34739925166](https://github.com/yegamble/vidra-core/actions/runs/34739925166/job/103677788533)
  (05:17Z), user#220 `507c9d7`
  [run 34739626736](https://github.com/yegamble/vidra-user/actions/runs/34739626736/job/103677000782)
  (05:10Z), search#45 `76499c6`
  [run 34739638218](https://github.com/yegamble/vidra-search/actions/runs/34739638218/job/103677032947)
  (05:10Z); all three PRs open at 2026-09-13T05:25Z. The amd64 **release**
  image is still unbuilt until a candidate is cut.
- **Operator-facing drift.** `env/production.env.example` and
  `env/staging.env.example` pin v0.6.3 (also inside the v0.6.4 meta tag) while
  the installer resolves core's latest release; the installer's git path clones
  meta at `main`; `docs/releases/` has no v0.6.4 notes; vidra-site renders
  `VERSION` v0.6.0 from `lib/envelope.json` and has no LICENSE or
  `dependabot.yml`. Its v0.5.0 strings are mostly deliberate screenshot
  provenance. Bumping templates to v0.6.4 would advertise a NO-GO release — an
  owner decision.
- **Dependabot security updates (auto-PRs) are disabled in all four service
  repositories** (`automated-security-fixes`: enabled=false, queried
  2026-09-13T05:21Z). **Alerts were enabled on all four on 2026-09-13 (~05:06Z)**
  and none has been triaged. Open alerts at 05:22:48Z (`GET
  /repos/yegamble/<repo>/dependabot/alerts?state=open`): vidra 0; vidra-core 1
  — high, **GHSA-2v4p-qf9q-27wj grpc on `go.mod`, the advisory govulncheck
  cannot see (T4)**; vidra-user 0 — its 15 alerts (incl. both next criticals
  GHSA-2xp9-vwfh-vxw4 / GHSA-p293-qw3h-jr36, 05:06:44–46Z) flipped to `fixed`
  at 05:17:15–17Z when #218 merged; vidra-search 1 — medium, GHSA-6w46-j5rx-g56g
  pytest on `training/uv.lock`, a tree no scanner in this record covered. The
  new gates do not replace alerts.
- **yt-dlp** is downloaded into the core image by version with no checksum; base
  images are pinned by tag, not digest; build provenance attestations are
  produced but never verified by deploy tooling.

## Dispositions

| Criterion | Before | After this record | Why |
|---|---|---|---|
| REL-01 / A39 security facet | not measured | **FAIL for v0.6.4 as published** | T1, T3, T4 are known advisories in shipped artifacts; the next fix is merged to main (user#218, 2026-09-13T05:17Z) and the openssl/grpc fixes are open (core#236, search#45, user#220); an unreleased fix is not a released fix |
| QLT-01 | UNVERIFIED (U1) | UNVERIFIED (U1) | Vulnerability lanes exist and pass: user's and search's are merged (2026-09-13 05:17Z / 05:16Z), core's is open (#233); `ci-required` fail-open paths remain (vidra#188 and its twins open); companion-revision and skipped-lane gaps unchanged |
| REL-01 mapping preflight | not measured | **FAIL (absent)** | Deliberate mismatches are not refused before mutation |
| All other rows | unchanged | unchanged | No runtime acceptance ran in this session (see blockers) |

Full release remains **NO-GO**.

## Blockers for runtime acceptance in this session

- **Acceptance hosts unreachable from this workstation.** `159.203.118.182` and
  `159.65.249.255` accept TCP/22 but SSH times out at the banner; this
  workstation's egress address differs from the operator /32 that the acceptance
  firewall rule added on 2026-09-11 allows (both values recorded privately, not
  in this repository). Smallest operator action:
  approve adding the current address to that firewall for TCP/22 (or supply the
  approved route). No firewall change was made.
- Local Docker daemon not running (ARM64 regardless; not release acceptance).
- Unchanged: representative sanitized PeerTube source and inventory (B2);
  approval to place the generated fixture passwords on the test host (MIG-02);
  independent restore destination and approved RPO/RTO (B4); selected-provider
  credentials (B3); the retained B2 media key expires 2026-09-18.

## Continuation

Merged 2026-09-13: core#234 (04:54Z, `f87bf6f`), search#43 (05:16Z, `92bdd79`),
user#218 (05:17Z, `6854c0f`). Still open at 05:25Z: core#233 (`1d1e15e`, every
lane green at 05:24Z). A new candidate must include
the image and dependency fixes, then be re-scanned **by digest** with all three
scanners before any acceptance run is promoted to it.

```bash
# exact-candidate rescan (replace digests from the new manifest)
export GOTOOLCHAIN=go1.27.1 GOBIN=$PWD/bin   # one module@version per go install
go install golang.org/x/vuln/cmd/govulncheck@v1.3.0   # this record's pin; CI pins v1.8.0 since core d976d65 / search f326dd0 (2026-09-13)
go install github.com/google/osv-scanner/v2/cmd/osv-scanner@v2.5.1
go install github.com/google/go-containerregistry/cmd/crane@v0.22.1
bin/crane pull --format tarball ghcr.io/yegamble/vidra-core@<platform-digest> core.tar
bin/osv-scanner scan image --archive core.tar --format json --output-file core.osv.json
bin/govulncheck -json ./...            # in each frozen Go source
npm run audit:deps                     # in the frozen vidra-user source (after #218)
```
