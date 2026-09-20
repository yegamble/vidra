# v0.7.5 dependency and image vulnerability scan — 2026-09-20

**The security facet of v0.7.5 is PASS.** v0.7.5 is the first release since v0.6.6
(2026-09-14) to be scanned at all: **41 core commits** and five Go dependency bumps
landed in between, and every one of v0.7.0–v0.7.4 shipped unscanned. Scanned by
linux/amd64 image digest with the same scanners the v0.6.6 record used, that whole
range introduced **no new advisory** and regressed **no v0.6.6 fix**: the image-scan
advisory ID set is identical to v0.6.6's for all three components, the Go binary
finding is the same single advisory, the frontend lockfile audit is still clean, and
the OpenSSL floor still holds at 3.5.8-r0. **Zero new high or critical findings.**
What remains are the same three residuals with no fix to apply — one Go advisory
that is not reachable, the AV1 crate advisories with no Alpine fix, and one scanner
false positive.

Two claims the v0.6.6 record had to leave inherited or session-reported are
**measured directly here**, because the basis that let v0.6.6 inherit them is gone:

- **Reachability was re-measured, not carried.** v0.6.6's "0 reachable" rested on
  v0.6.5's source-mode scan plus *unchanged source*. 41 core commits break that, so
  source-mode govulncheck was re-run on the v0.7.5 and v0.7.3 source trees.
- **The OpenSSL floor and the shipped `next` version were read out of the images**
  rather than session-reported, using `--platform linux/amd64` emulation.

This record covers **one facet only**. It says nothing about runtime acceptance of
v0.7.5, promotes no workflow row, and changes no release verdict — the overall
v0.7.5 verdict stays **NO-GO**, and the other eight lanes named in
[release-readiness](release-readiness.md) as not run on these digests are still not
run. No merge, tag move, deployment or host change was made by it. The scanners read
published artifacts by digest; **no Vidra service was started**.

Machine-readable record:
[dependency-scan/summary.json](evidence/release-v0.7.5-verification/dependency-scan/summary.json).
The exact commands and tool versions are in
[dependency-scan/commands.txt](evidence/release-v0.7.5-verification/dependency-scan/commands.txt).
Raw scanner output is under
[dependency-scan/raw/](evidence/release-v0.7.5-verification/dependency-scan/raw/)
(gzipped JSON where large), and
[dependency-scan/committed-hashes.json](evidence/release-v0.7.5-verification/dependency-scan/committed-hashes.json)
carries the SHA-256 of every other file in that tree so the committed evidence can
be proven byte-identical to the capture; it was regenerated and re-verified against
the tree (26 files, 0 mismatches) before commit. The evidence was secret-grepped and
host-path-scrubbed before commit: scanner stderr had the working directory replaced
with `<scratch>`, and nothing else in any raw file was edited. The only
`password`/`secret`/`token` strings in the tree are advisory summaries and Go symbol
names inside the govulncheck vulnerability database, not credentials.

## Candidate and boundary

The candidate is the frozen, recorded v0.7.5: `releases/v0.7.5.json` (meta#230).
Images were pulled and scanned **by linux/amd64 platform digest**, never by tag.
v0.7.5 is a **core-only** release: user and search were not rebuilt for it and stay
at `v0.7.3`, the same pairing v0.7.4 used.

| Component | Tag | Commit | linux/amd64 image digest |
|---|---|---|---|
| vidra-core | `v0.7.5` | `ce3eb0a4be680b46fd18c3d317f1703e66e2bd09` | `sha256:49974ded92048d377ec64471be08ed762a01b724af3c76a84feddc620cf8b6de` |
| vidra-user | `v0.7.3` | `c7dbea44b1f271dfdd37fbbbf3a6f58856ce5070` | `sha256:814df2644e7dfdec2b527e1e3eb79db5d733ff127066309c8e9778c58c5c3995` |
| vidra-search | `v0.7.3` | `4daed1850a4289e297bd7cd40a4310f20ccd1c44` | `sha256:a2195eaf9738ff049984db5913372d59dcc4c8736e3a2e4c7bf8a0c77d6046b1` |

**How the digests were confirmed.** Each image was pulled with
`docker pull --platform linux/amd64 …@sha256:…`, then `docker image inspect`
re-read its `RepoDigests` and platform; all three came back **equal to the digest in
`releases/v0.7.5.json`** and reported `linux/amd64`
([raw/digest-verification.txt](evidence/release-v0.7.5-verification/dependency-scan/raw/digest-verification.txt)).
The two source trees were cloned at their release tags and their `HEAD`s likewise
matched the record's commits before anything was scanned. So every number below is
pinned to the artifacts the release record names, not to a tag that could move.

**Host:** a darwin/arm64 workstation, Docker 29.8.0. Archive scanning is
architecture-neutral, so the amd64 images were read without emulation; the two steps
that execute inside an image (the apk floor, the `next` version) used
`--platform linux/amd64` emulation, which **worked** — see "What could not be run"
for what it cost.

## What ran

Scanners, all fetched at exact versions through the Go module proxy into a private
bin directory. **No Trivy binary or action**, following v0.6.4/v0.6.5/v0.6.6 (the
March 2026 Trivy release/action compromise):

- **osv-scanner 2.5.1** (osv-scalibr 0.5.2) — `scan image --archive`, by linux/amd64
  digest, on all three images; plus an `--all-packages` inventory pass.
- **govulncheck v1.8.0** (`GOTOOLCHAIN=go1.27.1`, the release images' own Go version;
  database `https://vuln.go.dev` updated **2026-09-16T18:00:43Z**) — `-mode=binary`
  on the shipped `/app/api` from the core and search images, **and** `-mode=source`
  on both source trees at their release tags.
- **npm audit** — vidra-user's committed lockfile at `c7dbea44`,
  `--package-lock-only --include=dev`, against the npm registry.

**Negative control — run this round, and it fired.** The v0.6.6 record ran none and
said so; its continuation block says to *"run the npm audit against a known-bad
lockfile in the same shell before believing a clean answer."* Done: the same command,
in the same shell, against the **v0.6.4** lockfile exited **1** with **6
vulnerabilities (1 moderate, 4 high, 1 critical)**
([raw/negative-control-v064-npm-audit.txt](evidence/release-v0.7.5-verification/dependency-scan/raw/negative-control-v064-npm-audit.txt)).
The clean candidate answer is therefore a real registry answer, not a silent no-op.

## Results

| Target | Scanner | Exit | Result |
|---|---|---|---|
| core image, by amd64 digest | osv-scanner 2.5.1, image | 1 | **9 vulnerable rows / 8 distinct IDs**: `ALPINE-CVE-2021-27219` (glib), `GO-2026-5932` (x/crypto), `RUSTSEC-2026-0190` (anyhow, reported twice — once via libdovi, once via librav1e), `RUSTSEC-2026-0105` (core2), `RUSTSEC-2026-0204` (crossbeam-epoch), `RUSTSEC-2024-0436` (paste), `GHSA-cq8v-f236-94qc` + `RUSTSEC-2026-0097` (rand, one aliased pair) |
| user image, by amd64 digest | osv-scanner 2.5.1, image | 0 | **0 vulnerable rows** (`results: []`) |
| search image, by amd64 digest | osv-scanner 2.5.1, image | 1 | **1 vulnerable row**: `GO-2026-5932` (x/crypto 0.56.0, `/app/api`) |
| core image inventory | osv-scanner, `--all-packages` | 1 | **307 packages**: Alpine 138, Go 71, crates.io 97, PyPI 1 |
| user image inventory | osv-scanner, `--all-packages` | 0 | **18 packages, Alpine only — zero npm packages** (see blind spots) |
| search image inventory | osv-scanner, `--all-packages` | 1 | **53 packages**: Alpine 21, Go 32 |
| core `/app/api` binary | govulncheck v1.8.0, `-mode=binary` | 0 (json) | Only advisory affecting the binary: **`GO-2026-5932`**, 15 finding records |
| search `/app/api` binary | govulncheck v1.8.0, `-mode=binary` | 0 (json) | Only advisory affecting the binary: **`GO-2026-5932`**, 15 finding records |
| core source @ `v0.7.5` | govulncheck v1.8.0, `-mode=source`, linux/amd64 | 0 (json) | **0 reachable**; 1 module-level (`GO-2026-5932`) |
| search source @ `v0.7.3` | govulncheck v1.8.0, `-mode=source`, linux/amd64 | 0 (json) | **0 reachable**; 1 module-level (`GO-2026-5932`) |
| user lockfile (`c7dbea44`) | npm audit, `--include=dev` | 0 | **0 vulnerabilities** across info/low/moderate/high/critical; `dependencies.total` = **678** (prod 132, dev 501, optional 119, peer 54) |
| user lockfile @ `v0.6.4` (negative control) | npm audit, `--include=dev` | 1 | **6 vulnerabilities** (1 moderate, 4 high, 1 critical) — the control fired |

Exit codes follow the scanners' documented contracts: osv-scanner exits 1 when it
reports a vulnerable row and 0 otherwise; govulncheck in `-json` mode returns 0
regardless of findings, so the finding set — `GO-2026-5932` and nothing else — is the
signal, not the exit; npm audit exits 0 with zero findings and non-zero with
findings, as the negative control demonstrates. All exits are recorded as an
explicit field in `summary.json`.

### Reachability, measured rather than asserted

**Binary mode still cannot prove reachability**, and the two modes disagree in a way
worth stating precisely, because it is easy to misread the binary output as calls:

- **Binary mode** emits 15 finding records per binary — 1 module-level, 7
  package-level, and 7 whose `function` field is a **package wildcard**
  (`org/x/crypto/openpgp/*`), not a named called symbol.
- **Source mode**, run on the actual v0.7.5 / v0.7.3 trees, emits **1** finding each,
  **module-level, with no package frame and no function frame** — the shape that
  means *present in the module graph, no symbol called*.

So `GO-2026-5932` is **0-reachable on this candidate's own source**, not on an
inherited claim. The per-finding trace shapes behind that read are printed in
[raw/findings-detail.txt](evidence/release-v0.7.5-verification/dependency-scan/raw/findings-detail.txt)
and recoverable from the gzipped govulncheck JSON.

## OpenSSL floor and shipped frontend versions — read from inside the images

Both are values the v0.6.6 record marked session-reported. Emulation worked, so both
are direct reads here
([raw/openssl-floor.txt](evidence/release-v0.7.5-verification/dependency-scan/raw/openssl-floor.txt),
[raw/user-image-next-version.txt](evidence/release-v0.7.5-verification/dependency-scan/raw/user-image-next-version.txt)):

| Fact | Value | How |
|---|---|---|
| OpenSSL floor | **libcrypto3 3.5.8-r0 / libssl3 3.5.8-r0** in all three images | `apk list -I` inside each image; independently corroborated by `openssl@3.5.8-r0` in each image's apk database via the inventory scan |
| Base image | **Alpine 3.24.2** in all three | `cat /etc/alpine-release` |
| Frontend runtime | **node v26.9.0** | `node --version` inside the user image |
| `next` | **16.3.5** | `/app/node_modules/next/package.json` |
| `react` / `react-dom` | **19.2.8** | same |
| `sharp` | **0.35.4** | same |

The floor equals v0.6.6's and sits at or above the publish-time gate
(`OPENSSL_MIN_APK_VERSION=3.5.8-r0`, core#236 / user#220 / search#45). `next` 16.3.5
is the version that closed v0.6.4's two criticals (T1), and it is what the **image**
carries, matching the lockfile.

## Delta versus v0.6.6

Every finding, classified. **New: 0. Unchanged: 9. Fixed: 0.**

| Advisory | Component | v0.6.6 | v0.7.5 | Class |
|---|---|---|---|---|
| `GO-2026-5932` (x/crypto/openpgp) | core image + binary | present, module-level | **present, module-level, 0 reachable (source-mode)** | **UNCHANGED** — v0.6.6 disposition: residual with no upstream fix |
| `GO-2026-5932` | search image + binary | present, module-level | **present, module-level, 0 reachable (source-mode)** | **UNCHANGED** — same disposition |
| `ALPINE-CVE-2021-27219` (glib 2.88.1-r1) | core image | present, ruled a **false positive** | **present, same version, same ruling** | **UNCHANGED** |
| `RUSTSEC-2026-0190` (anyhow 1.0.98) | core image | present | **present, same version** | **UNCHANGED** — accepted by prior ruling |
| `RUSTSEC-2026-0105` (core2 0.4.0) | core image | present | **present, same version** | **UNCHANGED** — accepted by prior ruling |
| `RUSTSEC-2026-0204` (crossbeam-epoch 0.9.18) | core image | present | **present, same version** | **UNCHANGED** — accepted by prior ruling |
| `RUSTSEC-2024-0436` (paste 1.0.15) | core image | present | **present, same version** | **UNCHANGED** — accepted by prior ruling |
| `RUSTSEC-2026-0097` / `GHSA-cq8v-f236-94qc` (rand 0.9.1) | core image | present (aliased pair) | **present, same version** | **UNCHANGED** — accepted by prior ruling |
| user image | — | 0 vulnerable rows | **0 vulnerable rows** | **UNCHANGED** |
| npm audit (user lockfile) | — | 0/0, 676 deps | **0/0, 678 deps** | **UNCHANGED** (dependency count moved, findings did not) |

And the fixes v0.6.4 failed on, re-checked so the delta covers regression as well as
addition
([raw/key-package-versions.txt](evidence/release-v0.7.5-verification/dependency-scan/raw/key-package-versions.txt)):

| v0.6.4 failing item | Fixed at | v0.7.5 | Holds? |
|---|---|---|---|
| `next` 16.3.0 (2 criticals) | 16.3.5 | **16.3.5 in the image and the lockfile** | yes |
| Alpine openssl 3.5.7-r0 (10 CVEs) | 3.5.8-r0 | **3.5.8-r0 in all three images** | yes |
| grpc 1.83.1 (GHSA-2v4p-qf9q-27wj, high) | 1.83.2 | **`google.golang.org/grpc@1.83.2`** in core | yes |
| x/crypto ssh advisories `-6303`/`-6354`/`-6355` | 0.56.0 | **core 0.57.0, search 0.56.0** | yes |

**The only movements in the whole delta** are core's `golang.org/x/crypto`
**0.56.0 → 0.57.0** (one of the five Go bumps in the range; the same advisory
applies, because `GO-2026-5932` is an "unmaintained package" advisory with no fixed
version at any release) and the npm dependency total 676 → 678. Neither changes a
finding. The v0.6.6 record does not state an x/crypto version; the 0.56.0 baseline
above is quoted from the [v0.6.5 record](security-scan-v0.6.5-2026-09-13.md) line
that reads *"module lists confirm **grpc v1.83.2** (core, 71 modules) and **x/crypto
v0.56.0** (both)"*.

## Residuals with no upstream fix

- **`GO-2026-5932`** (golang.org/x/crypto/openpgp) — **no fixed version published**;
  the advisory is that the package is unmaintained and unsafe by design. Present as a
  module in the core and search binaries, **0 reachable** by source-mode govulncheck
  on this candidate's own source. Nothing to apply.
- **AV1 codec crate advisories in the core image** — `RUSTSEC-2026-0190` (anyhow
  1.0.98), `RUSTSEC-2026-0105` (core2 0.4.0), `RUSTSEC-2026-0204` (crossbeam-epoch
  0.9.18), `RUSTSEC-2024-0436` (paste 1.0.15), `GHSA-cq8v-f236-94qc` /
  `RUSTSEC-2026-0097` (rand 0.9.1). The inventory scan attributes every one of them
  to `/usr/lib/librav1e.so.0.8.1` and `/usr/lib/libdovi.so.3.3.2` — i.e. Alpine's
  `rav1e@0.8.1-r0` and `libdovi@3.3.2-r0`, which is what Alpine v3.24 ships.

  **Accepted by prior owner ruling, re-checked and still applicable.** The standing
  ruling is recorded in [release-readiness.md](release-readiness.md) as *"the rav1e
  0.8.1 / libdovi 3.3.2 AV1 crate advisories (no Alpine v3.24 fix — owner risk
  decision)"*, and the v0.6.6 record states the choice as *"accept pending an Alpine
  update, or build without these codecs."* The facts that ruling was made on are
  **unchanged on the v0.7.5 images**: same two Alpine packages, same upstream
  versions (rav1e 0.8.1, libdovi 3.3.2), same five advisories, same absence of an
  Alpine fix, and the base image is still Alpine v3.24 (3.24.2). The acceptance is
  therefore **carried forward by citation, not re-decided here** — and it is not
  silently dropped either. If Alpine v3.24 later ships a fixed rav1e/libdovi, this
  stops being an accepted risk and becomes an available fix.
- **`ALPINE-CVE-2021-27219`** on glib 2.88.1-r1 — a scanner **false positive**: the
  installed version is far newer than the advisory's own fixed version (2.66.6-r0).
  Recorded, **not suppressed**, as v0.6.6 did. This is the one row carrying a
  high-band CVSS score (7.5); see the verdict for why it does not fail the candidate.

## Verdict, against the criteria v0.6.6 states

The v0.6.6 record's disposition row states the criterion verbatim as:

> **"The rebuild introduced no new advisory and regressed no v0.6.5 fix.** The
> image-scan ID set is identical to v0.6.5's, the Go binary finding is the same
> single advisory, the frontend lockfile audit is clean, and the OpenSSL floor is
> unchanged. The three residuals have no fix to apply"

and its opening states the same test as a set relation:

> "every advisory ID the image scans report is a subset of v0.6.5's recorded set"

Applied to v0.7.5 with v0.6.6 as the baseline, clause by clause, **not softened**:

| Clause of the v0.6.6 criterion | v0.7.5 | Met? |
|---|---|---|
| "introduced no new advisory" | 0 new IDs; the core set is the identical 8, search the identical 1, user still empty | **yes** |
| "regressed no … fix" | next 16.3.5, openssl 3.5.8-r0, grpc 1.83.2, x/crypto ≥ 0.56.0 all hold | **yes** |
| "image-scan ID set is identical" | identical for all three components | **yes** |
| "the Go binary finding is the same single advisory" | `GO-2026-5932` only, both binaries | **yes** |
| "the frontend lockfile audit is clean" | 0/0, and the negative control proves the command reports findings when they exist | **yes** |
| "the OpenSSL floor is unchanged" | 3.5.8-r0, verified inside all three images | **yes** |
| "the … residuals have no fix to apply" | true of all three; the AV1 group is accepted by the cited prior ruling on unchanged facts | **yes** |

**Verdict: PASS.** Every clause is met on evidence captured this session.

**On the one high-scored row.** The task this scan was run under treats a **new**
high/critical as failing. There is none: `new_high_or_critical_since_v066` is **0**.
The only finding carrying a high-band score is `ALPINE-CVE-2021-27219` at CVSS 7.5,
which is (a) not new — it is in v0.6.5's and v0.6.6's recorded sets — and (b) ruled a
false positive on the arithmetic, the installed glib being newer than the advisory's
fixed version. It is stated here rather than suppressed precisely because a naive
"any high anywhere fails" gate — the shape of the `dependency-audit` CI criterion
quoted in the [v0.6.4 record](security-scan-v0.6.4-2026-09-12.md) as *"any runtime
advisory, high/critical anywhere, or an unreachable endpoint fails"* — **would** fire
on it, and a reader is entitled to see that and disagree with the false-positive call.
No other finding in this scan carries a published high or critical severity; osv-scanner
reports **no severity at all** for the RUSTSEC rows and `GO-2026-5932`, and `LOW` for
`GHSA-cq8v-f236-94qc`.

## Disposition (this facet only)

| Criterion | v0.6.6 | v0.7.5 | Why |
|---|---|---|---|
| Exact-candidate dependency and image scan | PASS | **PASS** | The v0.6.6 → v0.7.5 range (41 core commits, five Go bumps) introduced no new advisory and regressed no v0.6.6 fix. Image-scan ID sets identical, Go binary finding the same single advisory, lockfile audit clean with a firing negative control, OpenSSL floor verified inside the images at 3.5.8-r0. Reachability re-measured on this candidate's source rather than inherited |
| Everything else | unchanged | unchanged | No runtime acceptance, no workflow row, no release verdict is touched by this record. v0.7.5 stays **NO-GO** |

**No workflow-register row moves**, following the v0.6.6 scan precedent, whose own
boundary paragraph says it *"promotes no workflow row, and changes no release
verdict."* One of nine named lanes closing does not move a register row.

## Blind spots — what these scanners cannot see

Carried forward from the earlier records, plus what this round re-confirmed:

- **The user image scan is blind to the frontend's JavaScript dependencies.** The
  `--all-packages` pass finds **18 Alpine packages and nothing else** in the user
  image — no npm ecosystem entries, no node binary detected — reproducing the v0.6.4
  observation exactly. Yet the image demonstrably contains `/app/node_modules` with
  next 16.3.5, react 19.2.8 and sharp 0.35.4, which this session read out of it. So
  the **only** coverage of the frontend's runtime dependencies is `npm audit` against
  the **committed lockfile**, which is a different object from the image: it proves
  what the lockfile resolves to, not what was baked in. The two agree on `next` here
  because that was checked by hand; nothing automated enforces the agreement.
- **Binary-mode govulncheck cannot prove call-reachability** — its `function` frames
  are package wildcards. Source mode is what supports the 0-reachable claim.
- **govulncheck only knows the Go vulnerability database.** grpc's
  GHSA-2v4p-qf9q-27wj was invisible to it in the v0.6.4 round and was reported only
  by osv-scanner. A Go advisory absent from `vuln.go.dev` at scan time is simply not
  asked about.
- **osv-scanner publishes no severity for most RUSTSEC advisories** (and none for
  `GO-2026-5932`), so any severity-threshold gate is silent on them in both
  directions — it would neither fail them nor vouch for them.
- **A scanner database is a point-in-time snapshot.** The Go DB here was updated
  2026-09-16T18:00:43Z and the OSV/npm queries were live on 2026-09-20; an advisory
  published after those instants is not in this record.
- **Artifact evidence only.** Nothing here is runtime acceptance of v0.7.5, and a
  clean dependency scan says nothing about whether the release deploys, migrates,
  plays back or recovers.

## What was NOT run, and why

- **The other eight lanes on the v0.7.5 digests** — native runtime milestone,
  backend-backed e2e, iOS/Safari and the broader browser matrix, B2/canonical S3
  storage, migration rehearsal, recovery drill (REC-01/REC-02), off-site backup
  retrieval, and REC-03 upgrade/rollback — remain not run. This record closes exactly
  one of the nine, the one that needs no host.
- **No Dependabot or `go list -deps` package-graph capture** this round; the v0.6.4
  and v0.6.5 records hold core's and search's graphs. Source-mode govulncheck
  supersedes the graph grep as reachability evidence, so nothing rests on their
  absence.
- **vidra-search's `training/uv.lock`** — the PyPI tree the v0.6.5 record flagged a
  pytest advisory in — was not audited. It is **not shipped in any image** (the
  search image inventory is 21 Alpine + 32 Go packages, zero PyPI), so it is out of
  this record's artifact boundary, but it is also therefore still unmeasured at
  v0.7.3.
- **No source-mode govulncheck for a non-`./cmd/api` entrypoint.** Both source scans
  targeted `./cmd/api`, the binary the images ship. Other packages in either module
  were not scanned.
- **Nothing was executed as a service.** The only in-image executions were
  `apk list -I`, `cat /etc/alpine-release`, `node --version` and reading
  `package.json` files, all with `--network none`.

## Continuation

```bash
# exact-candidate rescan (digests from releases/v0.7.5.json)
export GOTOOLCHAIN=go1.27.1 GOBIN=$PWD/bin
go install golang.org/x/vuln/cmd/govulncheck@v1.8.0
go install github.com/google/osv-scanner/v2/cmd/osv-scanner@v2.5.1

CORE=ghcr.io/yegamble/vidra-core@sha256:49974ded92048d377ec64471be08ed762a01b724af3c76a84feddc620cf8b6de
docker pull --platform linux/amd64 "$CORE"
docker image inspect "$CORE" --format '{{.Os}}/{{.Architecture}} {{.RepoDigests}}'  # must equal the record
docker save "$CORE" -o core.tar
bin/osv-scanner scan image --archive core.tar --format json --output core.json
bin/osv-scanner scan image --archive core.tar --all-packages --format json --output core-all.json

# Go binary, from the image (docker create does not execute it: no emulation needed)
cid=$(docker create --platform linux/amd64 "$CORE"); docker cp "$cid:/app/api" ./core-api; docker rm -f "$cid"
bin/govulncheck -mode=binary -json ./core-api

# reachability — re-measure, never carry it across a source change
git clone --depth 1 --branch v0.7.5 https://github.com/yegamble/vidra-core.git src-core
( cd src-core && GOOS=linux GOARCH=amd64 ../bin/govulncheck -mode=source -json ./cmd/api )

# openssl floor and shipped frontend versions, direct from the images
docker run --rm --platform linux/amd64 --network none --entrypoint sh "$CORE" \
  -c 'apk list -I | grep -E "^(libssl3|libcrypto3)-"'

# frontend lockfile, at the user tag this release pairs with
git clone --depth 1 --branch v0.7.3 https://github.com/yegamble/vidra-user.git src-user
( cd src-user && npm audit --package-lock-only --registry=https://registry.npmjs.org/ --include=dev )
```

Run the npm audit against a known-bad lockfile in the same shell before believing a
clean answer — `git show v0.6.4:package-lock.json` is the control this round used, and
it must exit non-zero.
