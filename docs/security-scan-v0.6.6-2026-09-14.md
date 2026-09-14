# v0.6.6 dependency and image vulnerability scan — 2026-09-14

**The security facet of v0.6.6 is PASS.** v0.6.6 is v0.6.5 plus one admin-only
white-label toggle (`branding_hide_software_name`, core#242 / user#221) with no
new migration (schema stays 146 / 18), and all three images were rebuilt. Scanned
by linux/amd64 image digest with the same scanners as the
[v0.6.5 record](security-scan-v0.6.5-2026-09-13.md), the rebuild introduced **no
new vulnerability** and regressed **no v0.6.5 fix**: every advisory ID the image
scans report is a subset of v0.6.5's recorded set (in fact the identical set),
the Go binary finding is the same single advisory, the frontend lockfile audit is
still clean, and the OpenSSL floor is unchanged. What remains are the same
residuals with no upstream fix — one Go advisory that is not linked, the AV1
crate advisories with no Alpine fix, and one scanner false positive.

This record covers **one facet only**. It says nothing about runtime acceptance
of v0.6.6, promotes no workflow row, and changes no release verdict. No merge,
tag move, deployment or host change was made by it. The scanners read published
artifacts by digest; no Vidra service was started.

Machine-readable record:
[dependency-scan/summary.json](evidence/release-v0.6.6-verification/dependency-scan/summary.json).
Raw scanner output is under
[dependency-scan/raw/](evidence/release-v0.6.6-verification/dependency-scan/raw/)
(gzipped JSON where large), and
[dependency-scan/committed-hashes.json](evidence/release-v0.6.6-verification/dependency-scan/committed-hashes.json)
carries the SHA-256 of every other file in that tree so the committed evidence
can be proven byte-identical to the capture. The evidence was secret-grepped
before commit; the only `password`/`secret`/`token` strings in it are advisory
summaries and Go symbol names inside the govulncheck vulnerability database
(for example `AuthenticationCleartextPassword.Encode`), not credentials.

## Candidate and boundary

The candidate is the frozen, recorded v0.6.6: `releases/v0.6.6.json` (meta#209),
cross-checked by [manifest.json](evidence/release-v0.6.6-verification/manifest.json).
Images were scanned **by linux/amd64 platform digest**, never by tag. v0.6.6 is
amd64-only, as v0.6.3–v0.6.5 were.

| Component | Commit | linux/amd64 image digest | Index digest |
|---|---|---|---|
| vidra-core | `3219290e0b7dfe6827f2d22e9f1dd3d5eb067b4c` | `sha256:332bdc2005db5a967d62f285b95b33b87f0246fccf28c7d54710e52d4c8ee64a` | `sha256:b2b7717da82aa5676a2bc3b8c9c09bd52a6b414081140f8723fa0619807e32fd` |
| vidra-user | `1aec0d23a496565947f4fdd356537c6ab3412af6` | `sha256:de2f8b17366f8e934b34e68896c01210a370ee27167c237b4400d750b63b2bde` | `sha256:4d86a264b66778a211d87b3ee95caa7e3c36ef4add096dc6094b52355be8882e` |
| vidra-search | `b7a7f55be6646c2730d5bbc481e423ac9cfa9e08` | `sha256:f021b0b1db340b7277cb625f946b23f31daec5a66ff7b68ba62cd7be6dc9fbd6` | `sha256:804530bfb5595944d9c2492cf16aec803696c74831df7e1fdc15192555e927c6` |
| meta | commit `22b27d5b56b45bb6be22fdea6855841d8fc4bf7c` | — | — |

**vidra-search was retagged at an UNCHANGED commit** — `b7a7f55b`, the exact
revision v0.6.5 shipped — but its **image was rebuilt**, so its digest differs
from v0.6.5's search digest (`sha256:68e16ad4…6c50b`). This scan is pinned to
v0.6.6's search digest so it measures the rebuilt image, not v0.6.5's.

**Host (session-reported):** the scan was run on 2026-09-14 on an amd64 host
(159.203), reproducing the v0.6.5 methodology so the two records are comparable.

## What ran

Scanners (from `summary.json`), the same three the v0.6.5 record used, no Trivy
binary or action (the March 2026 Trivy release/action compromise):

- **osv-scanner 2.5.1** — image scan, by linux/amd64 digest, on all three images.
- **govulncheck 1.8.0** (`GOTOOLCHAIN=go1.27.1`, the release images' Go version)
  — `-mode=binary` on the shipped `/app/api` from the core and search images.
- **npm audit** — vidra-user's committed lockfile (commit `1aec0d23`),
  `--include=dev`, against the npm registry.

**Negative control:** this round did **not** run a known-bad-lockfile negative
control, so none is claimed here. The v0.6.5 record established that the npm
audit command reports a real registry answer (it ran the same command against a
v0.6.4 lockfile and got exit 1 with findings); the v0.6.6 npm result rests on
that plus an unchanged command and an unchanged, clean lockfile answer. See
Coverage limits.

## Results

| Target | Scanner | Exit | Result |
|---|---|---|---|
| core image, by amd64 digest | osv-scanner 2.5.1, image | 1 | **8 vulnerable rows / 8 distinct IDs**: `ALPINE-CVE-2021-27219` (glib), `GO-2026-5932` (x/crypto), `RUSTSEC-2026-0190` (anyhow), `RUSTSEC-2026-0105` (core2), `RUSTSEC-2026-0204` (crossbeam-epoch), `RUSTSEC-2024-0436` (paste), `GHSA-cq8v-f236-94qc` + `RUSTSEC-2026-0097` (rand, one aliased group) |
| user image, by amd64 digest | osv-scanner 2.5.1, image | 0 | **0 vulnerable rows** (`results: []`) |
| search image, by amd64 digest | osv-scanner 2.5.1, image | 1 | **1 vulnerable row**: `GO-2026-5932` (x/crypto, `/app/api`) |
| core `/app/api` binary | govulncheck 1.8.0, `-mode=binary`, go1.27.1 | 0 (json) | Only advisory affecting the binary: **`GO-2026-5932`** (x/crypto/openpgp), 15 granular symbol/package findings; grpc and x/crypto modules present |
| search `/app/api` binary | govulncheck 1.8.0, `-mode=binary`, go1.27.1 | 0 (json) | Only advisory affecting the binary: **`GO-2026-5932`** (x/crypto/openpgp), 15 granular symbol/package findings; x/crypto module present |
| user lockfile (`1aec0d23`) | npm audit, `--include=dev` | 0 | **0 vulnerabilities** across info/low/moderate/high/critical; `metadata.dependencies.total` = **676** (prod 132, dev 499, optional 119, peer 21) |

Exit codes follow the scanners' documented contracts and are consistent with the
captured JSON: osv-scanner exits 1 when it reports a vulnerable row and 0
otherwise; govulncheck in `-json` mode returns 0 regardless of findings, so the
finding — `GO-2026-5932` and nothing else — is the signal, not the exit; npm
audit exits 0 with zero findings. (This bundle captured the scanners' JSON
results rather than a separate per-run exit log; v0.6.5's `summary.json`
recorded exits as an explicit field.)

**Binary-mode govulncheck does not prove reachability.** `-mode=binary` reports
the advisory's affected package/symbol list for what is linked in; it cannot say
whether that code is *called*. The claim that GO-2026-5932 is 0-reachable is not
made from these binary runs — it rests on the v0.6.5 **source-mode** govulncheck
scan (0 reachable, 1 module-level) plus **unchanged source**: vidra-search is the
identical revision `b7a7f55b`, and vidra-core's only change over v0.6.5 is the
`branding_hide_software_name` toggle (no migration; session-reported not to touch
crypto). No source-mode govulncheck was re-run for v0.6.6 (see Coverage limits).

## OpenSSL floor

`summary.json` records the OpenSSL floor as **libcrypto3 / libssl3 3.5.8-r0 in
all three images**, equal to v0.6.5's floor. This value is **session-reported**:
unlike the v0.6.5 record, this bundle does not include an in-image `apk`
listing, and osv-scanner's default (vulnerable-only) output does not enumerate a
non-vulnerable package, so 3.5.8-r0 is not independently re-derivable from the
raw files here. The publish-time gate (`publish-container.yml`,
`OPENSSL_MIN_APK_VERSION=3.5.8-r0`, core#236 / user#220 / search#45) fails a
publish below the floor, so a v0.6.6 image that shipped below 3.5.8-r0 could not
have been published; the direct confirmation from inside the image is the piece
this bundle leaves to the v0.6.5 record.

## Delta versus v0.6.5

| Facet | v0.6.5 | v0.6.6 | Verdict |
|---|---|---|---|
| core image osv IDs | 8 rows: ALPINE-CVE-2021-27219, GO-2026-5932, RUSTSEC-2026-0190 / -0105 / -0204 / 2024-0436 / -0097, GHSA-cq8v-f236-94qc | **identical 8** | subset — no new ID |
| user image osv | 0 vulnerable rows (18 Alpine pkgs) | **0 vulnerable rows** | unchanged |
| search image osv | 1 row: GO-2026-5932 | **1 row: GO-2026-5932** | unchanged |
| Go binary (core, search) | GO-2026-5932 only | **GO-2026-5932 only** | unchanged |
| npm audit (user, `--include=dev`) | 0 / 0, 676 deps | **0 / 0, 676 deps** | unchanged |
| OpenSSL floor | 3.5.8-r0 (verified in image) | **3.5.8-r0** (session-reported) | held |

Every image-scan advisory ID on v0.6.6 is a subset of — and equal to — v0.6.5's
recorded set: **no new vulnerability was introduced by the rebuild**, and no
advisory that v0.6.5 had fixed reappeared (next stays 16.3.5 — session-reported;
grpc and x/crypto stay at their fixed versions per the unchanged binary finding).

## Residuals with no upstream fix (same as v0.6.5)

- **`GO-2026-5932`** (golang.org/x/crypto/openpgp) — no fixed version; present as
  a module in the core and search binaries but **not linked/reachable** (v0.6.5
  source scan: 0 reachable). Nothing to apply.
- **AV1 codec crate advisories** in the core image — `RUSTSEC-2026-0190`
  (anyhow, via libdovi and librav1e), `RUSTSEC-2026-0105` (core2),
  `RUSTSEC-2026-0204` (crossbeam-epoch), `RUSTSEC-2024-0436` (paste),
  `GHSA-cq8v-f236-94qc` / `RUSTSEC-2026-0097` (rand). These come from
  rav1e 0.8.1 / libdovi 3.3.2, which is what Alpine v3.24 ships; no Alpine fix
  exists. **Owner risk decision:** accept pending an Alpine update, or build
  without these codecs.
- **`ALPINE-CVE-2021-27219`** on glib 2.88.1-r1 — a scanner **false positive**
  (installed version is far newer than the advisory's fixed version). Recorded,
  not suppressed.

## Coverage limits

- Artifact evidence only. **Nothing here is runtime acceptance of v0.6.6.**
- This bundle is narrower than v0.6.5's. It does **not** include: an
  `--all-packages` osv capture (so total package inventories are not re-stated
  for v0.6.6 — only vulnerable rows are), an in-image `apk` openssl listing (the
  floor is session-reported), a source-mode govulncheck run (the 0-reachable
  claim leans on v0.6.5's source scan + unchanged source), a shipped-version
  read of `next` (16.3.5 is session-reported), a negative-control npm audit, or
  Dependabot / package-graph captures. The delta method is what makes the
  narrower bundle sufficient: identical image-scan IDs, identical binary
  finding, identical clean lockfile answer, against v0.6.5's fuller baseline.
- Binary-mode govulncheck cannot prove reachability (see Results).

## Disposition (this facet only)

| Criterion | v0.6.5 | v0.6.6 | Why |
|---|---|---|---|
| Exact-candidate dependency and image scan | PASS | **PASS** | The rebuild introduced no new advisory and regressed no v0.6.5 fix. The image-scan ID set is identical to v0.6.5's, the Go binary finding is the same single advisory, the frontend lockfile audit is clean, and the OpenSSL floor is unchanged. The three residuals have no fix to apply |
| Everything else | unchanged | unchanged | No runtime acceptance, no workflow row, no release verdict is touched by this record |

## Continuation

```bash
# exact-candidate rescan (digests from releases/v0.6.6.json)
export GOTOOLCHAIN=go1.27.1 GOBIN=$PWD/bin
go install golang.org/x/vuln/cmd/govulncheck@v1.8.0
go install github.com/google/osv-scanner/v2/cmd/osv-scanner@v2.5.1
docker pull ghcr.io/yegamble/vidra-core@sha256:332bdc2005db5a967d62f285b95b33b87f0246fccf28c7d54710e52d4c8ee64a
docker save ghcr.io/yegamble/vidra-core@sha256:332bdc2005db5a967d62f285b95b33b87f0246fccf28c7d54710e52d4c8ee64a -o core.tar
bin/osv-scanner scan image --archive core.tar --format json --output-file core.osv.json
# openssl floor, direct from the image (the piece this bundle left to the v0.6.5 record):
docker run --rm --platform linux/amd64 --network none --entrypoint sh \
  ghcr.io/yegamble/vidra-core@sha256:332bdc2005db5a967d62f285b95b33b87f0246fccf28c7d54710e52d4c8ee64a \
  -c 'apk list -I | grep -E "^(libssl3|libcrypto3)-"'
bin/govulncheck -mode=binary -json ./api    # on the binary from the image
npm audit --package-lock-only --registry=https://registry.npmjs.org/ --include=dev
```

Run the npm audit against a known-bad lockfile in the same shell before believing
a clean answer.
