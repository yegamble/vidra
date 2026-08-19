# Phase 5 — Enterprise media

**Outcome:** the capabilities that make "Netflix-class" honest — multi-CDN with content
steering, DRM with real key management, distributed/multi-region topology — as optional
modules/providers on the same core. No fork: same interfaces, different providers, different
scale. An ordinary Vidra installation never sees any of this.

## Prerequisite chain (why this is last)

- Multi-CDN steering needs the Phase 4 session API + delivery resolver (today at most two
  sources exist and selection is a bespoke user toggle).
- DRM needs CMAF packaging (Phase 3), the engine adapter with a FairPlay path for the MSE-less
  iOS native-HLS branch, and playback sessions for license issuance (Phase 4).
- Multi-region needs the worker lease retrofit (Phase 3) and is blocked today by: live HLS on a
  shared filesystem volume, single-process worker claims, and a hardcoded pool MaxConns=10
  (blocks managed-Postgres sizing).

## Work items

### Multi-CDN & steering

- [ ] **1. Multiple delivery paths per asset** in the resolver with health/latency/region/
  cost/capacity signals.
- [ ] **2. Standards-based content steering** — research task first: HLS Content Steering +
  DASH steering support in target players; steering-manifest service behind the session API.
  Invisible to ordinary installations.
- [ ] **3. Origin shielding / regional failover** patterns documented and supported in the
  resolver + CDN providers.

### DRM

- [ ] **4. `DRMProvider` interface** (interfaces.md §10) — NoDRM default, ClearKeyTest for CI,
  ExternalMultiDRM, then Widevine/FairPlay/PlayReady integrations. No proprietary Vidra DRM.
- [ ] **5. Common Encryption (CENC)** at the packager — encrypted CMAF segments shared across
  DRM ecosystems where device support allows; per-video protection metadata kept separate from
  Vidra metadata.
- [ ] **6. Key management** — content encryption keys never in the normal Vidra DB; KMS/HSM/
  external-provider integration following the existing KEK discipline (env-only, validated,
  destructive-rotation warnings); license issuance wired through the session API.
- [ ] **7. DRM + P2P compatibility** — peers may exchange already-encrypted segments; peers
  never exchange keys; license requests always hit the license service. Test actual
  browser/platform behavior before claiming support.

### Distributed topology

- [ ] **8. Multi-node API** — externalize the live-HLS filesystem coupling; configurable pool
  sizing; trusted-proxy/LB story; session/state audit for statelessness.
- [ ] **9. Worker fleets** — hundreds of workers across machines (Phase 3 conventions at
  scale); distributed encoding of a single title (segment-parallel) as a later optimization.
- [ ] **10. Multi-region** — regional storage/delivery, replication jobs (Phase 2 machinery),
  failover runbooks; RTMP ingest brought inside the managed edge.

## Exit criteria

- A deployment can run: managed PG + S3 + 2 CDNs with steering + DRM-protected premium content +
  worker fleet — configured entirely through providers/config on stock Vidra images.
- The Simple tier install remains byte-identical in experience.
