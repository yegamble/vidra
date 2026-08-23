# Phase 4 — Delivery infrastructure

**Outcome:** playback is brokered by a session API; delivery sources (api-proxy, presigned,
CDN, IPFS gateway, P2P) are selected per-viewer behind a provider-neutral abstraction; the
player runs on a unified engine adapter; playback quality is measured. A basic install still
works with zero external services: local storage → Caddy → viewer.

## Delivery tiers

```text
Basic:       local storage → Caddy → viewer
Production:  S3 → CDN → viewer
Enterprise:  origin → {CDN A, CDN B, CDN C}  (Phase 5 steering)
P2P (opt):   peers first → CDN/IPFS/S3/local fallback — peers are never the only durable source
```

## Work items

- [ ] **1. Playback session API** (interfaces.md §5) — `POST /api/v1/videos/:id/playback-session`
  determines authorization, available renditions, HLS/DASH preference, delivery endpoints,
  tokens/signed URLs, (later) DRM requirements and P2P config. First version simply returns
  today's hls_url + optional `?pt=` token so the player consumes a session object from day one;
  token gains scope/session claims + renewal (today's 6h password token has neither). The
  response lets the player operate without consulting the core API per segment.
  **Inherited from phase 3:** the session response is the natural home for `dash_url` / packaging-
  format discovery. Phase 3 ships DASH manifests but no way to ask for one — clients probe
  `/hls/cmaf/stream.mpd` and infer. Until this lands, a TS-packaged back-catalog video and a CMAF
  one are indistinguishable to a client without a round trip that can 404.
- [ ] **2. Delivery-source resolver + CDN provider abstraction** (interfaces.md §4) — ordered
  source list, api-proxy as permanent fallback, purge hooks in the interface from day one.
  Single-CDN support: origin pull from api-proxy or S3, cache-key discipline via the existing
  `?v=` generation-versioned immutable URLs (the ready groundwork), header promotion
  private→shared *only* through this machinery. No CDN vendor in core media logic.
- [ ] **3. Player engine adapter** (interfaces.md §8) — collapse the three hls.js lifecycles;
  re-key quality identity off hls.js level indexes; multi-audio + in-manifest subtitle
  consumption; evaluate Shaka Player as the second engine (DASH/EME-capable) with hls.js
  retained for the default HLS path. The bespoke player shell stays.
- [ ] **4. QoE telemetry** (interfaces.md §9) — TTFF, buffering events, rebuffer duration,
  bitrate switches, selected rendition, delivery source, playback/DRM failures, segment
  latency, P2P/IPFS contribution. Event stream via the outbox pattern + batched beacon
  transport; sha256 viewer-key privacy precedent; admin playback-health page via the
  jobstatus/bounded-metrics patterns. Basic installs need no external analytics service;
  collection is configurable and privacy-conscious.
- [ ] **5. IPFS delivery integration** — promote the mirror from metadata-only to a real
  delivery source in the resolver: health/priority model, failover, attempt/outcome
  measurement feeding QoE.
- [ ] **6. P2P (peer-assisted delivery, optional)** — research task first: current
  PeerTube/p2p-media-loader architecture, WebRTC privacy implications (opt-in only), segment
  granularity (HLS/CMAF segments, never whole-video blobs). Then: tracker/signaling decision,
  integration under the engine adapter, fallback discipline (peers → CDN/origin), contribution
  metrics into QoE. Never a durable source.
- [ ] **7. Live-plane delivery review** — live HLS currently bypasses much of this (shared
  volume + os.Open, raw RTMP 0.0.0.0:1935, no playback tokens); bring live segments under the
  session/delivery model or explicitly document the gap.

## Exit criteria

- Player fetches a session, then plays without further core-API round-trips per segment.
- Enabling a CDN is an admin configuration act (with purge wired), not a code change; disabling
  it falls back cleanly.
- An admin can see TTFF/rebuffer percentiles per source for the last 24h.
