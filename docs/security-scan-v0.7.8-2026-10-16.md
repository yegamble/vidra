# v0.7.8 published-image security scans — 2026-10-16

The three recorded first-party linux/amd64 images were scanned successfully.
**No new advisory ID appeared versus v0.7.5.** Existing findings remain visible;
this is neither a risk acceptance nor a release GO/waiver.

The immutable [record](https://github.com/yegamble/vidra/blob/79cb14b38e20dcc80749d6c44e1ab60f34378ab4/releases/v0.7.8.json)
and [real PASS preflight](https://github.com/yegamble/vidra/blob/79cb14b38e20dcc80749d6c44e1ab60f34378ab4/docs/evidence/release-v0.7.8-verification/manifest.json)
bind the published assets and images to meta `35d2d3c5`, core `04a7f0e1`, user
`e861ff57` and search `63eed039`. Embedded schema maxima were measured as **182/18**.
Each scan pulled the record's platform digest, then checked RepoDigest, platform
and OCI revision label before saving the archive. Full references and hashes are
in [summary.json](evidence/release-v0.7.8-verification/dependency-scan/summary.json).

| Actual scan | Exit | Result |
| --- | ---: | --- |
| core OSV image / inventory | 1 / 1 | 9 package/advisory pairs, 8 IDs; 308 inventory rows |
| user OSV image / inventory | 0 / 0 | 0 findings; 19 Alpine rows, **zero npm packages** |
| search OSV image / inventory | 1 / 1 | GO-2026-5932 only; 53 inventory rows |
| core/search shipped `/app/api`, Go binary JSON | 0 / 0 | Each: go1.27.2, GO-2026-5932 only, 15 finding records |
| all three runtime package readers | 0 each | Alpine 3.24.2; libcrypto3/libssl3 **3.5.9-r0** |
| user runtime reader | 0 | Node 26.12.0; embedded OpenSSL 3.5.9; next 16.4.0; react/react-dom 19.3.0; sharp 0.35.5 |

Scans ran at 16:11–16:12 UTC with osv-scanner **2.5.1** / osv-scalibr **0.5.2**,
govulncheck **v1.8.0** (DB modified `2026-10-08T22:31:09Z`), Docker 28.4.0,
native Linux/amd64. No Trivy tool was used. OSV exit 1 means findings; Go JSON exit
0 is not a clean-finding verdict. No Vidra service/default entrypoint was started;
only network-disabled, read-only version readers ran. No production data was used.

## Residuals, including the reported HIGH

| ID | Artifact package | Severity and disposition |
| --- | --- | --- |
| ALPINE-CVE-2021-27219 | core glib 2.88.1-r1 | **CVSS 3.1 7.5 HIGH**, retained scanner false positive. Advisory describes pre-2.66.6 / development pre-2.67.3; converted range is inverted (`introduced 2.67.0`, `fixed 2.66.6-r0`). The shipped image's `apk version -t` confirms installed > fixed. |
| GO-2026-5932 | core/search x/crypto 0.57.0 | Unscored; unsafe/unmaintained OpenPGP, no fixed version. Binary records do not prove call reachability. |
| RUSTSEC-2026-0190 | anyhow 1.0.98 in libdovi and librav1e | Unscored; fixed upstream in 1.0.103. Two artifact locations give two pairs. |
| RUSTSEC-2026-0105 | core2 0.4.0 in librav1e | Unscored; unmaintained/yanked, no fixed version listed. |
| RUSTSEC-2026-0204 | crossbeam-epoch 0.9.18 in librav1e | Unscored; fixed upstream in 0.9.20. |
| RUSTSEC-2024-0436 | paste 1.0.15 in librav1e | Unscored; unmaintained, no fixed version listed. |
| RUSTSEC-2026-0097 / GHSA-cq8v-f236-94qc | rand 0.9.1 in librav1e | One aliased advisory; GitHub severity LOW, no numeric CVSS. Fixed upstream in 0.8.6 / 0.9.3 / 0.10.1. |

No new HIGH/CRITICAL advisory is reported versus v0.7.5. The existing reported
HIGH is retained above; unscored advisories are **unknown severity**, not LOW.
The AV1 owner risk decision remains unresolved; this report supplies no acceptance.

Actual official HTTPS Alpine v3.24 x86_64 main/community indexes were read through
the normal proxy at 16:12:20 UTC, both HTTP 200. They still offer only
`rav1e`/`rav1e-libs 0.8.1-r0` and `libdovi 3.3.2-r0`; main offers OpenSSL
3.5.9-r0 and glib 2.88.1-r1. Thus upstream crate fixes exist, but no newer packaged
codec is available there. No package was installed. Index hashes and selected
versions are committed; HTTP metadata remains in the hashed session capture.

## Separate source and lockfile evidence

[source-lock.json](evidence/release-v0.7.8-verification/dependency-scan/source-lock.json)
records actual canonical Go source scans at the exact core/search commits:
**0 reachable advisories, 0 affected imported packages**, one module-only residual
each. Configuration: Go 1.27.2, Linux/amd64, CGO disabled, default tags, `./...`,
tests excluded. Canonical text exits were 0 independently of JSON exits. The
binary scans' 15 records each are 1 module + 7 packages + 7 wildcards, not 15
distinct vulnerabilities or proof that vulnerable functions are called.

The final user commit's package.json/lockfile SHA256s equal the frozen `abbd6960`
inputs actually audited with Node 26.12.0/npm 11.19.0: exit 0, **0 vulnerabilities
across 663 dependencies including dev**. The same invocation's known-bad v0.6.4
control exited 1 with 14 npm-reported vulnerabilities: 1 moderate, 12 high,
1 critical. This covers the source lockfile; OSV still cannot inventory the
frontend's npm bundle from the image. The image runtime version reads above
independently agree on next/react/sharp versions.

## Review, reproduction and limits

The compact [capture-hashes.json](evidence/release-v0.7.8-verification/dependency-scan/capture-hashes.json)
binds the original command logs, raw scanner outputs, source policy/graphs,
lockfile/control reports, official indexes and independent read-only review.
Large raw SBOMs, binary/image archives and caches are not committed. Original
captures remain in the session's `security/` artifacts; hashes alone do not make
those uncommitted bytes available to a later reader. The committed summaries
are review records, not substitutes for rerunning a scan against today's database.

Actual command forms, using the immutable references in summary.json:

```sh
docker pull --platform linux/amd64 "$REF"
docker image inspect "$REF"
docker image save --output image.tar "$REF"
osv-scanner scan image --archive image.tar --format json --output-file image.json
osv-scanner scan image --archive image.tar --all-packages --format json --output-file inventory.json
# Copy /app/api from a stopped container created from the same digest, then:
govulncheck -db https://vuln.go.dev -mode=binary -json ./api
# In each exact source checkout, Go 1.27.2, linux/amd64, CGO_ENABLED=0:
govulncheck -mode=source -scan=symbol -show verbose ./...
npm audit --package-lock-only --offline=false --registry=https://registry.npmjs.org/ --include=dev --audit-level=info --json
```

Only the three released first-party images are covered. Other stack images,
Whisper, the training PyPI tree, other architectures/build tags, browser flows,
REC-03 and sealed recovery are outside this evidence. Independent review found
no malformed/vacuous/error scan promoted as successful evidence; 97 final image
capture hashes matched. Full untranslated-copy extraction/guard work, human
acceptance and G10/G2 debt remain unresolved. No release-readiness row is waived.
