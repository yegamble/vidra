# Representative PeerTube acceptance inputs

The browser driver accepts a fifth argument for hash-bound representative preview, COPY and repeat checks:

```sh
node tests/peertube-release-acceptance.mjs PRIVATE_STAGE preview preview BASELINE INPUTS_JSON
```

BASELINE must contain the frozen candidate.json. Omitting INPUTS_JSON retains the historical generated fixture and its fixed schema/count expectations; it supplies no representative acceptance.

INPUTS_JSON contains schema_version: 1, scope: "representative", candidate_sha256, and source / expectations references. Each reference has path and sha256; paths resolve relative to INPUTS_JSON.
The source JSON records peertube_schema_version, snapshot_sha256 and media_manifest_sha256.
The expectations JSON records every CATALOGUE_TABLES entry in catalogue_delta, plus preview / import / repeat maps of entity counters. Video counts use planned / imported / skipped respectively; preview also requires user.planned. video_no_media requires planned for preview and imported for COPY/repeat. Record unsupported counters explicitly when nonzero; failed entities cannot be accepted.

Capture expectations independently from the source, never from the imported destination. Hashes bind inputs; they do not establish their accuracy.
PRIVATE_STAGE/preparation.json must report PASS, scope "representative", candidate_sha256, source_snapshot_sha256 and source_media_manifest_sha256 matching those inputs.
The driver refuses a schema mismatch or schema acknowledgement. Representative mode refuses the legacy schema-refusal, search and playback paths before browser/host execution; those generated-fixture shortcuts cannot certify real data. Never rewrite a representative source marker or use force.

Run only on an isolated, authorized candidate with a restored SELECT-only source and read-only source media. This driver launches imports; it is not a fresh-owner installation harness.
Passing these provenance/count checks does not prove asset hashes, decoded source-disconnected playback, complete search convergence, ZIP import, recovery or production GO. Preserve separate evidence for those gates.
