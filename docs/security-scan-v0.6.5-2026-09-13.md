# v0.6.5 dependency and image vulnerability scan — 2026-09-13

**The security facet of v0.6.5 is PASS as published.** Every advisory with a
released fix that the [v0.6.4 record](security-scan-v0.6.4-2026-09-12.md) found
in shipped artifacts — next 16.3.0, Alpine openssl 3.5.7-r0, grpc 1.83.1 — is
absent from the v0.6.5 artifacts, and each of those three was verified **in the
artifact itself**, not only in a lockfile or a merged PR. What remains are three
named residuals with no upstream fix to apply, one scanner false positive, and
one finding in a tree that is not shipped.

This record covers **one facet only**. It says nothing about runtime acceptance
of v0.6.5, promotes no workflow row, and changes no release verdict. No merge,
tag move, deployment or host change was made by it. Nothing was executed that
could reach a Vidra instance: three read-only commands were run inside the
images with `--network none`, and no service was started.

Machine-readable record:
[dependency-scan/summary.json](evidence/release-v0.6.5-verification/dependency-scan/summary.json)
— 11 scanner runs and 15 supplementary captures, with exits, scanner and
database versions, and the SHA-256 of all 31 raw artifacts. Raw output is under
`dependency-scan/raw/` (gzipped JSON where large; one local scratch path
replaced with `<scratch>`; secret-grepped before commit).

## Candidate and boundary

The candidate was frozen by commit **and** by image digest before anything ran,
and every digest was re-verified here at 2026-09-13T06:45Z with
`docker buildx imagetools inspect` and again by recomputing the SHA-256 of each
raw manifest locally:

| Component | Commit | Index digest | linux/amd64 digest | Release published |
|---|---|---|---|---|
| vidra-core | `d13d40e6670d0bf95d28e1f69b5af20e5b99237b` | `sha256:a6e08b93…f3bb1` | `sha256:7cab2447…80ea6` | 2026-09-13T06:36:04Z |
| vidra-user | `fdef1cec82fc155aab49282c3342ff47d1abcace` | `sha256:08e920ba…b03178` | `sha256:b19c9717…52e4d` | 2026-09-13T06:38:04Z |
| vidra-search | `b7a7f55be6646c2730d5bbc481e423ac9cfa9e08` | `sha256:55196d27…5ea0f8` | `sha256:68e16ad4…6c50b` | 2026-09-13T06:41:55Z |
| meta | tag object `b7e9e8c2…ed1fa5` → commit `9c3a9ec55572098581394c0110cf5274244749c4` | — | — | tagged 2026-09-13T06:36:02Z |

Each index holds exactly two entries: one `linux/amd64` image manifest and one
`unknown/unknown` provenance **attestation** manifest, which is not an image.
**v0.6.5 is amd64-only**, as v0.6.3 and v0.6.4 were. Every image's
`org.opencontainers.image.revision` equals the commit above
(`raw/image-labels-v065.txt`), so the images are built from the tagged commits
and not from a later `main` — an assertion by the builder, which is the
strongest statement available without a reproducible-build check (see
"Coverage limits").

Sources were read with `git archive <commit>` out of the pinned nested
checkouts; nothing was checked out and no working tree was touched. Images were
pulled **by linux/amd64 platform digest**, never by tag. The workstation is
darwin/arm64. Unlike the v0.6.4 record, which treated the images purely as
files, three read-only commands were executed inside them under linux/amd64
emulation with `--network none` — an `apk` listing, a version print, and a
`node_modules` version read — because "does the image carry openssl 3.5.8-r0"
is a question best answered by the image.

Scanners, both installed through the Go module proxy at exact versions with the
checksum database enabled, and no Trivy binary or action used (the March 2026
Trivy release/action compromise):

- **govulncheck v1.8.0** — the CI pin since vidra-core `d976d65` /
  vidra-search `f326dd0` (2026-09-13); the v0.6.4 record used v1.3.0.
  `GOTOOLCHAIN=go1.27.1` (the release images' Go version; the local toolchain is
  go1.26.2 and would report stale stdlib advisories). DB `https://vuln.go.dev`,
  last modified **2026-09-10T14:48:42Z**.
- **osv-scanner 2.5.1 / osv-scalibr 0.5.2** — `api.osv.dev` queried online
  2026-09-13T06:47–06:53Z.
- **npm audit** — npm 10.9.2 on node v22.14.0, `registry.npmjs.org`; npm exposes
  no database timestamp.

A scanner or network failure is recorded as a failure, never as clean. Because
the frontend answer this time is "zero vulnerabilities", and because the
v0.6.4 record documented a gate that printed exactly that when it was silently
offline, the same npm command was re-run against **vidra-user's v0.6.4
lockfile** on the same host, npm, flags and `HOME`: it exited 1 with 2 findings
(`raw/npm-audit-negative-control-v064-lockfile.txt`). The clean answer is a real
registry answer.

## What ran

| Target | Scanner | Exit | Result |
|---|---|---|---|
| core source v0.6.5 | govulncheck source, go1.27.1, linux/amd64 | 0 | 0 reachable; 1 module-level (GO-2026-5932, x/crypto/openpgp) |
| search source v0.6.5 | govulncheck source, go1.27.1, linux/amd64 | 0 | 0 reachable; **1** module-level (GO-2026-5932) — was 4 on v0.6.4 |
| core, search released binaries | govulncheck `-mode=binary` | 0 / 0 | GO-2026-5932 only; module lists confirm **grpc v1.83.2** (core, 71 modules) and **x/crypto v0.56.0** (both) |
| user lockfile v0.6.5 | npm audit, runtime (`--omit=dev`) and full (`--include=dev`) | 0 / 0 | **0 vulnerabilities in both**; `metadata.dependencies.total` = **676** (prod 132, dev 499, optional 119, peer 21); `next` = **16.3.5** |
| core image | osv-scanner image, by digest | 1 | 138 apk, 71 Go, 97 crates, 1 PyPI = 307 packages; 8 vulnerable rows |
| user image | osv-scanner image, by digest | 0 | **18 apk packages only, zero vulnerable rows** — and still **zero npm packages, no node binary detected** |
| search image | osv-scanner image, by digest | 1 | 21 apk + 32 Go = 53 packages; 1 vulnerable row |
| search `training/uv.lock` | osv-scanner source (new this record) | 1 | 31 PyPI packages; 1 vulnerable (pytest, medium) — **not shipped** |
| all three images | in-image `apk` listing, `--network none` | 0 | **libssl3 3.5.8-r0 and libcrypto3 3.5.8-r0 in all three** |

The `apk info -v libssl3 libcrypto3 openssl` form named in the v0.6.4
continuation prints package *descriptions*, not versions, under the images'
apk-tools 3.0.8-r0; the version was therefore read with `apk list -I` and
independently cross-checked against `/lib/apk/db/installed`. Both forms are in
`raw/images-apk-openssl-v065.txt`.

## openssl per image (the point of core#236 / user#220 / search#45)

| Image | libssl3 | libcrypto3 | Alpine | Installed packages |
|---|---|---|---|---|
| vidra-core v0.6.5 | **3.5.8-r0** | **3.5.8-r0** | 3.24.1 | 138 |
| vidra-user v0.6.5 | **3.5.8-r0** | **3.5.8-r0** | 3.24.1 | 18 |
| vidra-search v0.6.5 | **3.5.8-r0** | **3.5.8-r0** | 3.24.1 | 21 |

All three shipped it. One caveat worth keeping: `alpine:3.24` **still installs
3.5.7-r0** while `v3.24/main` offers 3.5.8-r0 (re-verified today against the
linux/amd64 variant, index digest `sha256:28bd5fe8…43f8b`,
`raw/alpine-3.24-apk-policy.txt`). The 3.5.8-r0 in these images comes from the
runtime stages' own upgrade step, not from a base-image change. The floor is
asserted at PUBLISH time only: `publish-container.yml` (core#236 / user#220 /
search#45, merged before this tag) runs `apk` inside the just-pushed digest and
fails the job below `OPENSSL_MIN_APK_VERSION=3.5.8-r0` — the step ran green for
all three v0.6.5 publishes (runs 34743148440 core 06:36Z, 34743227349 user 06:38Z, 34743386552 search 06:41Z; step "Assert the pushed image carries the OpenSSL floor"). The PR-time
`docker-build` lane builds the image but does not assert the floor, so a dropped
upgrade step is caught after the release exists, not before.

## v0.6.4 triage rows, re-measured against v0.6.5

| # | v0.6.4 finding | v0.6.5 status | Backed by |
|---|---|---|---|
| T1 | **next 16.3.0** — GHSA-2xp9-vwfh-vxw4 (critical), GHSA-p293-qw3h-jr36 (critical) | **CLOSED.** Lockfile and the **shipped image** both carry next **16.3.5**; runtime and full npm audit are 0/0; vidra-user's 15 Dependabot alerts, including both criticals, are `fixed` | `raw/vidra-user-v065.npm-audit*.json.gz`, `raw/vidra-user-v065-shipped-versions.txt`, `raw/npm-audit-negative-control-v064-lockfile.txt`, `raw/dependabot-alerts-2026-09-13.txt` |
| T2 | user tooling tree: js-yaml, brace-expansion, browserslist, @redocly/openapi-core, baseline-browser-mapping | **CLOSED.** `--include=dev` reports 0 across all 676 dependencies | `raw/vidra-user-v065.npm-audit.json.gz` |
| T3 | **Alpine openssl 3.5.7-r0 in all three images**, ten CVEs, fixed 3.5.8-r0 | **CLOSED in all three**, verified inside each image rather than inferred from a PR; the osv-scanner openssl rows are gone from every image, and the user image now has **zero** vulnerable rows | `raw/images-apk-openssl-v065.txt`, the three `*-image.osv.json.gz`, `raw/alpine-3.24-apk-policy.txt` |
| T4 | **grpc 1.83.1** in core `/app/api`, GHSA-2v4p-qf9q-27wj (high), invisible to govulncheck | **CLOSED**, and confirmed three independent ways: `go.mod` says v1.83.2, the binary's own module list says v1.83.2, the osv-scanner row is gone, and vidra-core's Dependabot alert is `fixed` (fixed_at 2026-09-13T05:29:58Z, before the 06:36Z tag) | `raw/vidra-core-v065-binary.govulncheck.json.gz`, `raw/vidra-core-v065-image.osv.json.gz`, `raw/dependabot-alerts-2026-09-13.txt` |
| T5 | x/crypto: GO-2026-5932 (openpgp, no fix) plus search's 0.54.0 ssh advisories -6303 / -6354 / -6355 | **Half closed, half a permanent residual.** The three ssh advisories are **gone** — x/crypto is 0.56.0 in both modules. **GO-2026-5932 remains** with no fixed version; it is not linked into either binary: `grep -cE 'x/crypto/(ssh\|openpgp)'` = 0 on both linux/amd64 package graphs | `raw/vidra-{core,search}-v065-api-package-graph.txt`, `raw/vidra-search-v065.govulncheck.json.gz` |
| T6 | core image rav1e 0.8.1 / libdovi 3.3.2 crate advisories (RUSTSEC-2026-0190, -0204, -0097 / GHSA-cq8v, -0105, 2024-0436) | **STILL OPEN, unchanged, and still unfixable from Alpine**: v3.24/community carries exactly rav1e-libs 0.8.1-r0 and libdovi 3.3.2-r0, which is what the image installs. Unsoundness and unmaintained classes in libraries that parse untrusted uploads; no exploit path demonstrated. Owner risk decision: accept pending Alpine, or build without these codecs | `raw/vidra-core-v065-rust-codec-apk.txt`, `raw/alpine-3.24-apk-policy.txt`, `raw/vidra-core-v065-image.osv.json.gz` |
| T7 | core glib 2.88.1-r1 flagged ALPINE-CVE-2021-27219 (fixed 2.66.6) | **Unchanged scanner false positive** — installed version is far newer than the fix, and 2.88.1-r1 is the only version v3.24/main has. Recorded, not suppressed | `raw/vidra-core-v065-image.osv.json.gz`, `raw/alpine-3.24-apk-policy.txt` |
| T8 | **Scanner coverage gap**: the image scan saw no npm packages; no Python tree was scanned anywhere | **Half closed.** The Python half is closed: `training/uv.lock` was scanned for the first time and is reported below. The npm half is **unchanged** — osv-scanner still finds 0 npm packages and no node binary in the user image, so an image scan alone is still not a frontend dependency scan | this table; `raw/vidra-user-v065-image.osv-all-packages.json.gz`; `raw/vidra-search-v065-training-uvlock.osv.json.gz` |

### New this record

| # | Finding | Affects Vidra? | Smallest action | Verify |
|---|---|---|---|---|
| T9 | **pytest 8.4.2** in vidra-search `training/uv.lock` — GHSA-6w46-j5rx-g56g / PYSEC-2026-1845, medium. First scan of that tree; it is also vidra-search's one open Dependabot alert (created 2026-09-13T05:07:45Z) | **Not shipped.** The search image contains no Python interpreter and no PyPI package record — only `/app/api` plus 21 Alpine packages. It is a ranker-training developer dependency | In-range `uv lock --upgrade-package pytest` in vidra-search; add a uv/pip lane so the tree is scanned by CI rather than only by Dependabot | `osv-scanner scan source --lockfile training/uv.lock` exit 0; the alert closes |

No other new advisory appeared in any v0.6.5 artifact. yt-dlp in the core image
is **2026.07.04**, sha256 `495be29f…0349f3fd` — byte-identical to the value
vidra-core#236 pinned from the signed `SHA2-256SUMS`, so the build-time checksum
verification held through to the published image (`raw/vidra-core-v065-image-tool-versions.txt`).

## Hardening still missing (not vulnerabilities; no fix shipped in v0.6.5)

- **Dependabot security updates (auto-PRs) remain disabled in all four
  repositories** — `automated-security-fixes` `{enabled: false, paused: false}`,
  queried 2026-09-13T06:52:32Z. Alerts are enabled on all four (HTTP 204 on
  `/vulnerability-alerts`) and, unlike on 2026-09-12, they have been triaged: 0
  open in vidra, vidra-core and vidra-user, 1 open in vidra-search (T9). Alerts
  without auto-PRs mean the next advisory waits for a human to look.
- **The openssl floor is asserted only at publish time.** `publish-container.yml`
  checks the pushed digest (`OPENSSL_MIN_APK_VERSION`); the PR-time `docker-build`
  lane builds without asserting it, so a dropped upgrade step fails the release
  publish rather than the PR. A one-line `apk list -I` assertion in that lane
  (with `load: true`) would move the failure to the PR.
- **Provenance attestations are produced and never verified.** Each index
  carries an attestation manifest; no deploy tooling checks it, and base images
  are still pinned by tag rather than digest.
- **No reproducible-build check.** This record proves the images *claim* the
  scanned commits, not that they were built from them.
- **No uv/pip lane** anywhere, so T9's tree is covered only by Dependabot.

## Coverage limits

- Artifact evidence only. **Nothing here is runtime acceptance of v0.6.5.**
- Binary-mode govulncheck cannot prove reachability; it emits GO-2026-5932 rows
  down to package/symbol-wildcard granularity for `x/crypto/openpgp/*`, which is
  the advisory's affected-package list, not proof that openpgp code is linked
  in. The package graphs are what answer that question.
- govulncheck alone would still miss GHSA-only Go advisories — T4 was invisible
  to it on v0.6.4. Release qualification needs lockfile audit **and**
  govulncheck **and** an image scan, plus Dependabot as an independent opinion.
- The user image scan remains blind to npm (T8).
- No lock-scan of a Python tree inside the core image: it carries exactly one
  PyPI package record and commits no uv/pip lockfile for the runtime image.

## Disposition (this facet only)

| Criterion | v0.6.4 | v0.6.5 | Why |
|---|---|---|---|
| Exact-candidate dependency and image scan | **FAIL** (T1, T3, T4 shipped with released fixes available) | **PASS** | Every advisory with a released fix is gone from the shipped artifacts, verified in the artifacts themselves. The three residuals — GO-2026-5932 (no fix, not linked), the rav1e/libdovi crates (no Alpine fix), glib (false positive) — have no fix to apply, and T9 is not shipped |
| Everything else | unchanged | unchanged | No runtime acceptance, no workflow row, no release verdict is touched by this record |

## Continuation

```bash
# exact-candidate rescan (replace digests from the new manifest)
export GOTOOLCHAIN=go1.27.1 GOBIN=$PWD/bin   # one module@version per go install
go install golang.org/x/vuln/cmd/govulncheck@v1.8.0      # the CI pin
go install github.com/google/osv-scanner/v2/cmd/osv-scanner@v2.5.1
docker pull ghcr.io/yegamble/vidra-core@<linux/amd64 digest>   # never by tag
docker save ghcr.io/yegamble/vidra-core@<digest> -o core.tar
bin/osv-scanner scan image --archive core.tar --format json --output-file core.osv.json
bin/osv-scanner scan image --archive core.tar --all-packages --format json --output-file core.all.json
docker run --rm --platform linux/amd64 --network none --entrypoint sh \
  ghcr.io/yegamble/vidra-core@<digest> -c 'apk list -I | grep -E "^(libssl3|libcrypto3)-"'
bin/govulncheck -json ./...                    # in each frozen Go source
bin/govulncheck -mode=binary -json ./api       # on the binary from the image
npm audit --package-lock-only --offline=false --registry=https://registry.npmjs.org/ --omit=dev
npm audit --package-lock-only --offline=false --registry=https://registry.npmjs.org/ --include=dev
bin/osv-scanner scan source --lockfile training/uv.lock   # vidra-search
```

Run the npm audit against a known-bad lockfile in the same shell before
believing a clean answer.
