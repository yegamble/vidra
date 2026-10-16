# PeerTube schema-refusal rehearsal

Published core v0.7.8 (`04a7f0e127177b631eb323d04d330673fee044f9`)
accepts source schema markers **700–1040 inclusive**, as defined in
[`version.go`](https://github.com/yegamble/vidra-core/blob/04a7f0e127177b631eb323d04d330673fee044f9/internal/peertubeimport/version.go).
The retained schema-970 rehearsal therefore uses **1041** for its unsupported
marker. This is separate from the new synthetic schema-1040 fixture generator.

On the prepared disposable clone, `peertube_release_checks.py`'s
`schema-unsupported` action permits only **970 → 1041**. Then the browser driver's
`schema-refusal` mode must observe a failed dry run with `unverified_schema`,
source version 1041 and no operator acknowledgement. Its existing entity counts,
content fingerprints, persisted API/UI readback and disabled launch controls
remain required. Import-run metadata and destination capability probes are not
covered by the entity no-write assertions.

The `schema-restore` action permits only **1041 → 970**, verifies the readback,
and leaves an unexpected source marker untouched. Use a new attempt label for
each action; previous results are retained.

Dated evidence recording an older release's refusal of 1040 remains historical
evidence. Updating this fixture supplies no v0.7.8 runtime result or G10
qualification; the published-image rehearsal still has to run.
