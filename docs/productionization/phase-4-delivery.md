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

## Ground truth 2026-08-23 (recon against the code, before any phase-4 build)

This phase was scoped before phases 2 and 3 landed. Verified corrections — read these before
trusting an item's premise:

**Item 2 is mostly already built.** Phase 2 (core#61) shipped `internal/delivery`: the `Resolver`
interface (`Resolve` returning an ordered `[]Source`, plus `Purge`), the `api-proxy | presigned |
ipfs-gateway | cdn` kinds with `SourceCDN` declared-but-unimplemented on purpose, api-proxy as a
fallback that cannot error, the `delivery_presign_enabled` runtime kill switch, and the full
private cache-header policy. What actually remains in item 2 is narrow: a CDN provider
implementation, a real `Purge` behind it, CDN config keys (none exist — there is no `DELIVERY_*`
env key at all), and the private→shared header promotion that `Purge` gates.

**interfaces.md §4 is stale on one point.** It says the resolver is consulted at *URL-mint time*
(`hlsDetail`, `videos.go`, `downloads.go`). It is not — it is consulted at *byte-serve time*, in
`serveMediaAsset` (11 call sites). `hlsDetail` still mints a plain origin-relative path.

**Three constraints that must shape item 1's design, none of which are in the item text:**

1. **A token handed to every viewer would silently disable CDN/presigned delivery for everyone.**
   `credentialedMediaRequest` treats *any* `?pt=` or `Authorization` header as credentialed, and
   credentialed requests are forced to `no-store` and never redirected. Today this is benign
   because tokens exist only for password videos. A session API that mints one per viewer would
   turn every request origin-only. **The session must not hand out a media credential by default.**
2. **The resolver is per-object-key, not per-video.** A session response cannot ask it for "the
   delivery base for this video"; presigned URLs are single-object bearer credentials with a 1h
   TTL. A session advertising `sources:` should advertise origin-relative bases and leave presign
   as a per-request redirect decision inside `serveMediaAsset`.
3. **`Eligible` is `public AND published` only.** A CDN plugged into this resolver can therefore
   serve *only* public, published, uncredentialed media. Private/password/unlisted-cover/scheduled/
   quarantined bytes are structurally origin-only. CDN-fronted private playback needs
   signed-URL-at-the-edge — a different mechanism. Plan it explicitly; the resolver does not
   generalize to it.

**The playback token is worse than the item says.** Its payload is
`base64(videoUUID:expUnix).base64(HMAC)` with no scope, no session id, no audience, and **no
version discriminator** — so adding claims is a payload-grammar change, not a field addition. TTL
is a compile-time 6h const; the only mint path requires a correct password.

**`?v=` immutability does not cover DASH.** The MPD is served verbatim because `SegmentTemplate`
patterns are not literal URIs, so DASH segments arrive **unversioned** and get `must-revalidate`
rather than `immutable`. Any CDN cache-key plan that assumes `?v=` covers CMAF is wrong.

**There is no subscriber-only privacy tier.** Privacy is `public | unlisted | private | password`.
Do not design against one that does not exist.

## Work items

- [ ] **1. Playback session API** (interfaces.md §5) — `POST /api/v1/videos/:id/playback-session`
  determines authorization, available renditions, HLS/DASH preference, delivery endpoints,
  tokens/signed URLs, (later) DRM requirements and P2P config. First version simply returns
  today's hls_url + optional `?pt=` token so the player consumes a session object from day one;
  token gains scope/session claims + renewal (today's 6h password token has neither). The
  response lets the player operate without consulting the core API per segment.
  **Inherited from phase 3:** the session response is the natural home for `dash_url` / packaging-
  format discovery. *Corrected 2026-08-23 against the code:* nothing probes `/hls/cmaf/stream.mpd`
  — vidra-user contains **zero** DASH code (no Shaka, no dash.js, no MPD fetch; `hls.js` is the only
  playback dependency). The true state is that **DASH is served and entirely unconsumed**, reachable
  only by hand-written `curl`. TS and CMAF videos are indeed indistinguishable to a client, and it
  currently does not matter: the CMAF packager writes HLS `.m3u8` playlists over the same fMP4
  segments and `hls_url` still points at `master.m3u8`, so both play identically. Format discovery
  is therefore a **prerequisite for item 3's engine adapter**, not a live defect — priority drops,
  but it must land before any second engine can choose a manifest.
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
