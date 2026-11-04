# SizeTube private read trial — 2026-11-04

**Production NO-GO.** This records a restricted partial-media trial, not release
or migration qualification. Production DB, media, configuration and DNS were
unchanged. All private records, credentials, logs and object maps remain outside Git.

## Frozen published artifacts

| Component | Source and artifact |
|---|---|
| CORE API and embedded migrator | `5a49cb3b262803a12d3b4eb858a832d935d3d037`, tag `beta-sizetube-20261104-5a49cb3b` |
| CORE linux/amd64 manifest | `sha256:ad334c06e1178f5488a846bc1c19ff42745786e06f51bc983474f6559c0b6907` |
| CORE OCI index | `sha256:3e9ed6a790b4649c5de4c502daabc53ac787479b85f96ee24ab546e160d2eb4a` |
| USER released frontend | v0.7.8, source `e861ff57ef45f655d71502e959cd4c59bb03c75f` |
| USER linux/amd64 manifest | `sha256:349cf5a440e9350f866b9b638b595fd1c467903453762f6ce577cb2938f7f3c6` |

The [official publisher](https://github.com/yegamble/vidra-core/actions/runs/41770164846)
passed build/push, OpenSSL floor and provenance steps. The
[attestation](https://github.com/yegamble/vidra-core/attestations/63418890)
verified against the exact repository, commit, tag and workflow identity. No
GitHub Release, stable/latest tag, normal release pin or workflow was changed.
Actual `/version` reports the beta tag, publisher-derived short commit `5a49cb3`
and Go 1.27.3. An initial assertion expecting eight commit characters refused
acceptance; its failure is retained separately from the corrected observation.

## Observed trial results

- The sole old COPY child was identified by executable SHA-256, parent, arguments
  and frozen snapshot binding, then terminated through a Linux pidfd. Its
  non-restarting wrapper exited and reasserted all eleven MFA holds. No target
  connections remained before the pre-migration checkpoint and DDL.
- Encrypted B2 point `20261104T043744Z-866a4441` preceded migration. The same
  published image ran a discrete `migrate up`, with no migration volume. Frozen
  source and embedded maxima independently equal 188; the actual ledger is
  `188:false`, all 24 dirty triggers exist and source catalog state is absent.
- Hashes of all 5,521 imported users, 5,520 account keys, 5,572 channel keys,
  27,481 ledger rows and 410 block rows matched across migration and owner claim.
  A pending-hash-only host repair enabled the native one-time claim for a new
  beta operator. No imported password, role, key or MFA hold changed.
- API, frontend and Redis have no published ports. The API runs `VIDRA_ROLE=api`
  with no source DSN/credentials, worker, mail transport, federation, search,
  IPFS or ingestion. `/readyz` body reports `ok` for PostgreSQL, Redis, storage
  and MFA KEK. API-only boot still writes its own probes/heartbeat/auth state;
  it is not a read-only process or frozen backup point.
- The operator receives HTTPS homepage/version 200. Browser navigation renders.
  Non-operator and spoofed forwarding-header requests return 403; host access
  is confined to health. Other mutations and actual HTTP/1.1 upgrades return
  403; only reads and exact POST login/refresh/logout are routed. Noindex and
  no-store were observed. An HTTP/2 request with ignored upgrade headers returned
  ordinary 200; it is not counted as a WebSocket-denial proof.
- One ready public HLS entry served a master through the exact API and decoded
  60 output frames / 1,966,667 microseconds. Decoder network protocols were
  HTTP/TCP/crypto; media was not saved. This is a host decoder observation,
  not browser playback, all renditions, separate audio, captions, seeking,
  whole-corpus closure or source-disconnection acceptance.
- B2 point `20261104T045318Z-ad90e914` contains schema-188 target DB and encrypted
  beta operator/app/edge/key configuration. Both points passed full exact-version
  ciphertext SHA-256 readback and anonymous 401. Their DB/config archives also
  decrypted to the original stream hashes under the separately held Mac identity,
  without persisted plaintext or transferring that identity to beta.
- The first 250 primary-version pool mappings / 100,853,238 bytes passed exact
  independent byte proof: 240 pairs required 480 complete immutable-ID GETs;
  ten earlier pairs reused a frozen full-read proof only after fresh exact
  identity/provenance checks. The private plan has 5,567 eligible objects /
  169,552,119,638 bytes, plus one deferred 16,527,038,005-byte object. This is
  prefill of observed primary versions, not a matched or complete media backup.
- The actual old importer passed schema-188 dry run before one bounded-memory,
  non-restarting continuation was launched. Its binary remains source-built
  `b59b14c3`, SHA-256
  `2358990e9de6208780c9764359c47fde35b6bf195b02a7340e6aa2be342175d1`.
  The beta image includes no standalone importer. Continuing preparation does
  not qualify published operator artifacts or implicitly reverify ready HLS.

## Open production gates

Complete available-media COPY, exact reconciliation and per-failure dispositions.
At the paused observation there were 462 ready HLS entries and 31 failed ledger
entries. The approved purge exception covers only its exact cohort; nine missing
variants across six masters, 12,706 storyboards, one cover and snapshot-drift
references remain separate. Failed-HLS source HEAD/parser diagnostics do not
explain the original discarded copy I/O errors.

Publish and qualify the coordinated operator artifacts; finish the paired search
runtime and outage/recovery proofs; run source-disconnected browser/media/access
and new scanned upload/transcode acceptance. Materialize the complete encrypted
media map onto an empty replacement host, require strict dependency-version-1
verification, test the actual imported sealed keys with correct/wrong KEKs and
measure RPO/RTO. Current-account B2 recovery does not prove cross-region recovery.

Complete the real installation/hardware-floor trials, English usability and
security dispositions. Settle production ownership, controlled MFA re-enrollment,
same-domain actor/URL continuity, final source freeze/delta and preservation of
new Vidra writes during rollback. French certification is excluded by scope.
