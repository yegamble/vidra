# Published v0.7.8 synthetic migration to Backblaze B2

Date: 2026-10-17. **Verdict: PASS within the synthetic subset below.**
This rehearsal uses the published component digests in
[the v0.7.8 release record](../releases/v0.7.8.json), with core/search schemas
**182/18**, and the ten-case [synthetic importer fixture](peertube-synthetic-fixture.md).
It uses no production source, existing media bucket, DNS record or delivery endpoint.

The source is a generated importer-query subset at schema marker **1040**, not
a PeerTube server or representative export. Source media is a read-only local
mount; the destination is a new private B2 bucket in `us-east-005`. An expiring
application key is restricted by Backblaze to that bucket and the six required
read/write/delete capabilities. Account credentials are used only to create and
remove the disposable bucket/key, and are never placed in application containers.

## Executed checks

The clean preparation used tool commit `bc2d266`. The retained evidence binds
each later driver to its exact SHA-256. Configuration, SQL, passwords, actor keys,
raw responses and logs stay private outside Git. The running API's actual storage
configuration and credentials were independently compared with the verified
single-bucket key after source disconnection.

| Check | Observed result |
| --- | --- |
| Published bytes | Running core, frontend and search image identities match the release's AMD64 digests; API version and clean migration ledgers match v0.7.8 and 182/18. |
| Read-only source | Reader has a read-only transaction default and a real write is denied by table permissions. Full source-table fingerprints match after import and repeat. |
| Schema refusal / preview | Default marker 1041 is refused with `unverified_schema`; marker 1040 previews successfully. Classified target catalogue and import ledger fingerprints remain unchanged in both cases. Import-run metadata and storage capability probes are outside that no-write assertion. |
| COPY and repeat | Ten source video identities map to ten stable destination identities with the expected privacy, draft and blacklist policies. A second import preserves IDs, asset mappings and catalogue counts. |
| Accounts / relationships | Two imported accounts, two channels, two comments, one playlist with two items, one accepted follow, one rating, one tag and two chapters. The additional third account is the isolated owner. Imported bcrypt hashes and public actor keys match; private actor keys have encrypted envelopes. Signing and private-key decryption were not tested. |
| Provider readback | **31 signed S3 GETs, all HTTP 200; 3,573,100 bytes.** Seven originals, thirteen HLS binaries, seven playlists, one caption, one poster, one storyboard image and one generated storyboard VTT. Binary SHA-256 values match independently retained source/expected bytes; playlist semantics and local dependencies match. |
| Source disconnection | Source PostgreSQL is stopped. API is recreated with the source mount and source credentials removed, and import disabled. Catalogue, assets and pinned image identities remain intact. |
| Disconnected browser | Published frontend decodes public, HLS-only and split-audio playback, plus a progressive original. Every sample advances at least 1.70 seconds with increasing frames/audio bytes and no media error. Captions, chapters, decoded storyboard, seeking, reload, real search, imported login/suspension and anonymous/owning/non-owning access checks pass. |
| Persisted operator report | API state is `done`, schema 1040 and copy mode. All 30 rendered entity rows match persisted counts, with zero failed entities and exactly one missing-media case. The real UI reports its gap honestly. |
| Private object | Unsigned HEAD of an independently verified original returns HTTP 401. |

B2's native inventory also retains completed storage write probes as upload/hide
pairs. They are validated against the frozen probe key grammar, payload metadata
and marker order, and counted separately from media. They are not claimed as
independently downloaded media. No other hidden, duplicate or unexplained object
version is accepted by the verifier.

The [sanitized evidence](evidence/release-v0.7.8-verification/b2-migration.json)
retains exact driver hashes, original result hashes, provider object hashes,
browser counters and all earlier attempts. The initial preparation stopped
before source import after fixture proxy/table-name errors. Three browser
attempts stopped at the report: an incorrect clean-badge expectation, a real
history-request 429, and a real session-refresh 429. The final browser driver
honored an observed 34-second limit and reloaded the real page, then passed all
six checks. Limits and application responses were not overridden.

**897 metadata tests passed with zero skips**, with production Compose and
browser syntax validation. Cleanup removed both isolated Docker projects and
their volumes/networks, all **51 native B2 versions** across the two disposable
buckets, both temporary keys and both buckets. The provider measurement's 44
versions includes six completed probes; later normal probes account for the
accepted bucket's final 48-version cleanup. Existing buckets were not accessed.

The fixture deliberately has **one video without media rows**. Its metadata is
retained and the report must say **Finished with gaps**, with the explicit
missing-media warning. Split-audio playback is checked independently of the
unsupported audio-only rendition descriptor. A completed import is not a claim
that unavailable source bytes were recovered.

## Reproduction

Provide a new private bucket spec and a 0600 JSON file with only `access_key`
and `secret_key`, holding a bucket-restricted key. The harness refuses a nonempty
bucket, including old versions. Do not pass an account-wide key. Use a new private
stage outside repositories for every preparation attempt:

```sh
python3 tests/b2_migration_rehearsal.py prepare \
  --stage /absolute/private-parent/new-run \
  --spec /absolute/private-parent/bucket.json \
  --credentials /absolute/private-parent/credentials.json
python3 tests/b2_migration_rehearsal.py disconnect \
  --stage /absolute/private-parent/new-run
python3 tests/b2_migration_provider.py \
  --pairs /absolute/private-parent/new-run/private/asset-pairs.json \
  --source-root /absolute/private-parent/new-run/media \
  --stage /absolute/private-parent/new-provider-check \
  --spec /absolute/private-parent/bucket.json \
  --credentials /absolute/private-parent/credentials.json --tag v0.7.8
node tests/b2-migration-browser.mjs \
  /absolute/private-parent/new-run/private/browser.json \
  /absolute/private-parent/new-browser-check
python3 tests/b2_migration_rehearsal.py cleanup \
  --stage /absolute/private-parent/new-run
```

Python 3.11+, FFmpeg/FFprobe, OpenSSL/bcrypt, Docker Compose, curl and a compatible
Playwright installation/browser are required. The browser driver defaults to the
adjacent `vidra-user` installation; `B2_BROWSER_PACKAGE` and `CHROMIUM_PATH` select
an existing installation and browser. Docker retains its configured outbound
proxy and a mounted CA bundle; B2 HTTPS certificate verification stays enabled.
Local candidate ports bind loopback only. Remove every native object version,
then the temporary key and bucket after verification; Docker cleanup does not
remove provider storage.

## Qualification boundary

This is a custom disposable Compose fixture, with malware scanning disabled and
local plain HTTP. It does not certify installer/deploy scripts, scanning, public
TLS, production scale/timing, S3-source server-side copy, CDN/presigned delivery,
federation continuity, per-user ZIP import, off-site recovery or a representative
PeerTube migration. It does not close G10 or the three-human installation gate.
Overall [production readiness remains NO-GO](release-readiness.md).
