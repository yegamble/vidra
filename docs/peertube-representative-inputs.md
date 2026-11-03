# Representative PeerTube acceptance inputs

The browser driver accepts a fifth argument for hash-bound representative preview, COPY and repeat checks:

```sh
node tests/peertube-release-acceptance.mjs PRIVATE_STAGE preview preview BASELINE INPUTS_JSON
```

BASELINE must contain the frozen candidate.json. Omitting INPUTS_JSON retains the historical generated fixture and its fixed schema/count expectations; it supplies no representative acceptance.

INPUTS_JSON contains schema_version: 2, scope: "representative", candidate_sha256, and source / expectations references. Each reference has path and sha256; paths resolve relative to INPUTS_JSON. Version 1 representative inputs are refused rather than silently using fixture transport.
Its target object requires origin (canonical HTTPS, no trailing slash/path/credentials), project (the actual Compose project), install_dir (absolute candidate directory), and timeout_ms (1,000–2,147,483,647). Set COMPOSE_PROJECT_NAME to that recorded project. Certificate checks stay enabled; the fixture DNS override is not applied.
The source JSON records peertube_schema_version, snapshot_sha256 and media_manifest_sha256.
The expectations JSON records every CATALOGUE_TABLES entry in catalogue_delta, plus preview / import / repeat maps of entity counters. Video counts use planned / imported / skipped respectively; preview also requires user.planned. video_no_media requires planned for preview and imported for COPY/repeat. Record unsupported counters explicitly when nonzero; failed entities cannot be accepted.

Capture expectations independently from the source, never from the imported destination. Hashes bind inputs; they do not establish their accuracy.
PRIVATE_STAGE/preparation.json must report PASS, scope "representative", candidate_sha256, source_snapshot_sha256, source_media_manifest_sha256 and target matching those inputs. Running containers must carry the recorded Compose project label. The HTTPS API's release/commit must match the frozen candidate before owner credentials are loaded or login starts.
The driver refuses a schema mismatch or schema acknowledgement. Representative mode refuses the legacy schema-refusal, search and playback paths before browser/host execution; those generated-fixture shortcuts cannot certify real data. Never rewrite a representative source marker or use force.

Run only on an isolated, authorized candidate with a restored SELECT-only source and read-only source media. This driver launches imports; it is not a fresh-owner installation harness.
Passing these provenance/count checks does not prove asset hashes, decoded source-disconnected playback, complete search convergence, ZIP import, recovery or production GO. Preserve separate evidence for those gates.
An import wait timeout does not cancel the worker. Retain its run ID and inspect the ongoing job; do not blindly start another COPY.
