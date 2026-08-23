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

## Status 2026-08-23

**Item 1 is DONE and merged** (core#74). **Item 6's research half is CLOSED — verdict DEFER, phase 4
ships no P2P** ([decision doc](p2p-delivery-decision.md)). Item 3a (re-key quality identity) is
built and awaiting merge as user#59; item 3b (collapse the lifecycles) branches off it. Items 2, 4,
5 and 7 are scoped against the code below but not started.

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

- [x] **1. Playback session API** — **DONE 2026-08-23** (core#74 `802b5ae`). Backend + OpenAPI;
  frontend consumption is a deliberate follow-up, gated on item 3's engine adapter because the
  frontend has no DASH code to point a `dash_url` at yet.

  Shipped: `POST /api/v1/videos/:id/playback-session` under `optionalAuth`, returning `session_id`,
  `video_id`, `packaging_format`, `hls_url`, `dash_url` (CMAF only), `renditions`, and a
  **conditional** `playback_token` + `expires_in`; `packaging_format`/`dash_url` also added to the
  video detail. Authorization calls `videoVisibleForMedia` rather than restating it, so the 401
  unlock-prompt flow is untouched. Token payload is now versioned; v1 keeps *verifying* for its
  remaining TTL but there is no v1 mint path left in production code.

  Four things worth carrying forward:
  - **The token is minted only for password videos**, and a regression test asserts on the raw
    response body that a public session carries no `playback_token` key. This is the constraint
    that protects CDN/presign delivery — any `?pt=` or `Authorization` header marks a request
    credentialed, which forces `no-store` and blocks redirect.
  - **`dash_url` is emitted unversioned**, deliberately. Adding `?v=` would make the manifest
    return `immutable` over segments that arrive `must-revalidate`, because a DASH player expands
    `SegmentTemplate` itself. Unversioned is the only spelling that makes no false claim.
  - **A live bug fixed for free:** the *owner* of their own password-protected video could never
    watch it in Safari — native HLS cannot set an `Authorization` header and the password gate has
    no cookie path, so `master.m3u8` 401'd on the owner. Minting for owner/moderator closes it.
  - **For item 4:** there is no session table. For a non-password video the `session_id` is
    server-*minted* but not server-*recorded*, so a beacon carrying it is client-asserted; for a
    password video the id is inside the HMAC-signed token and is verifiable. If item 4 wants to
    reject events for sessions that never existed, that table is item 4's to add.

  *Original scope, for reference:* `POST /api/v1/videos/:id/playback-session`
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
- [ ] **3. Player engine adapter** (interfaces.md §8) — collapse the three hls.js lifecycles
  (`use-hls-playback`, `use-live-playback`, `use-remote-playback`); re-key quality identity off
  hls.js level indexes; evaluate Shaka Player as the second engine (DASH/EME-capable) with hls.js
  retained for the default HLS path. The bespoke player shell stays.

  *Scoped 2026-08-23 against the code:*
  - **Re-key BEFORE collapsing** — this doc originally implied the reverse. Re-keying while there
    is still exactly one interface implementation (the only one with a test file) means Live and
    Remote change once instead of twice.
  - **The shell/engine boundary is already clean.** `components/player/VideoPlayer.tsx` imports no
    hls.js type or value; its entire coupling is the 7-field `HlsPlayback` interface. §8's
    precondition is already satisfied, which is what makes this item cheap.
  - **Descoped: in-manifest subtitles.** Blocked at the packager (WebVTT hard-fails the dash
    muxer), not the player — see risks.md #10. Belongs with the phase-5 Shaka Packager work.
  - **Descoped: the player half of multi-audio.** The pipeline emits one hardcoded audio
    representation with no language tag, so a selector would be a UI for a set of size one. The
    backend half (probe N audio streams, emit `LANGUAGE=`/`NAME=`) is the real prerequisite.
  - **Fold in:** Remote playback currently gets *no* ABR tuning at all (no `capLevelToPlayerSize`,
    no `backBufferLength`), so a federated watch retains the whole played stream in MSE. Collapsing
    fixes this for free. Live never wires `LEVEL_SWITCHED`, so its quality menu has no active-height
    readout and PR #58's codec-family fix never reached it. Embeds pass no caption tracks at all.
  - **Riskiest part: modelling native HLS as a third engine.** The browser owns variant selection
    there via the manifest `SCORE` attribute; the adapter can neither read nor set the active
    variant, so quality identity has no faithful implementation. Today's behavior (empty quality
    list, menu renders nothing) is correct and must be preserved rather than faked. Engine
    selection must also become `probe → ask each engine → pick`: today an MSE-partial browser is
    routed to the full progressive file even when it plays HLS natively.
- [ ] **4. QoE telemetry** (interfaces.md §9) — TTFF, buffering events, rebuffer duration,
  bitrate switches, selected rendition, delivery source, playback/DRM failures, segment
  latency, P2P/IPFS contribution. Event stream via the outbox pattern + batched beacon
  transport; admin playback-health page via the jobstatus/bounded-metrics patterns. Basic
  installs need no external analytics service; collection is configurable and privacy-conscious.

  *Corrected 2026-08-23 against the code — four premises were wrong:*
  - **The outbox pattern does not fit unmodified.** `search_outbox` is an *egress queue to an
    external service* and **prunes nothing** — there is no DELETE anywhere against it. That is
    survivable at search volume and is not at playback volume. QoE needs
    outbox → **local rollup table** → prune worker. **Design the rollup first** (source × class ×
    hour bucket, percentiles precomputed); otherwise the exit criterion "TTFF/rebuffer percentiles
    per source for the last 24h" becomes a full scan of an unbounded table and the
    bounded-cardinality rule gets violated in the storage layer instead of the label layer.
    Copy the *retention* pattern from `jobstatus.Prune` (30/90-day windows, 10k batches, leader-
    elected), not from searchevents.
  - **The "sha256 viewer-key privacy precedent" is not one.** `viewerKey` is a bare unsalted
    `sha256("ip:"+RealIP)` — trivially reversible against a known IP — and it survives only because
    it is *never persisted*, existing solely as a Redis key fragment with a 1h TTL. Copying it into
    a persisted event row would be a privacy regression dressed as reuse. Use a **keyed** digest
    with domain separation (the `playback/token.go` HMAC construction) and state the rotation
    policy.
  - **The capture point does not exist yet.** interfaces.md §9 says "hls.js handlers in the unified
    engine adapter" — there is no adapter, there are three hooks, and the live and remote hooks
    wire no `LEVEL_SWITCHED` or `FRAG_BUFFERED` at all. Item 4 is sequenced behind item 3 unless v1
    instruments only the VOD hook.
  - **"Delivery source" is not currently knowable by the client.** `serveMediaAsset` redirects on
    the first non-api-proxy source and emits no marker, so the client can only infer source by
    sniffing a redirect host. Emitting an explicit source marker is part of item 4's cost, not a
    freebie. Note also that **"selected rendition" is permanently null on native HLS** (item 3).
- [ ] **5. IPFS delivery integration** — bring the two IPFS delivery paths that *already exist*
  under the resolver and give them a health model: health/priority, failover, attempt/outcome
  measurement feeding QoE, and a runtime kill switch.

  *Rewritten 2026-08-23 — "promote from metadata-only" mis-stated the starting point twice.*
  Server-side, thumbnails, playlist covers and avatars/banners **already 307 to the gateway**
  through the resolver. Client-side, a viewer can **already play an entire HLS ladder off a
  gateway** — the video detail carries `ipfs.hls_cid`, the watch view probes the gateway and offers
  a manual source toggle, and the chosen URL is handed to hls.js as a master override. That path is
  opt-in, unmeasured, and sits **entirely outside `internal/delivery`**. What is missing is not
  delivery, it is *brokered, policy-driven, measured* delivery. Four concrete gaps: HLS is pinned
  as **one directory CID, not per-segment**, so there is no per-segment gateway URL (cheapest fix:
  have the lookup return `{gateway}/ipfs/{car_root}/<rendition>/<file>` — CI already proves nested
  path resolution works); the resolver has **no health, priority or failover concept** and its
  single consumer takes the first non-api-proxy source and returns, so post-307 failover is
  impossible server-side and must live in the player (another item-3 dependency); nothing anywhere
  measures gateway fetch outcomes; and unlike presign there is **no runtime kill switch** — turning
  IPFS delivery off during an incident currently means a restart.

  **Do not assume public IPFS gateways still exist** (surfaced 2026-08-22 by the P2P research, which
  probed them). The public gateway landscape collapsed while this item sat in the backlog:
  **Infura's IPFS gateway shut down 2026-08-15 — one week ago**; Cloudflare's closed 2024-08;
  Interplanetary Shipyard is redirecting `ipfs.io`/`dweb.link` with rate limits rolling out and has
  **explicitly asked hot-linked video to migrate off**. Range requests cap at 5 GiB, and
  verifiability and range-seeking are mutually exclusive (`entity-bytes` is CAR-only). Protocol
  Labs' own NSDI '24 paper says IPFS *"struggles with real-time applications such as live video
  streaming."* This does not close the item — a self-hosted or operator-chosen gateway is still
  viable, and `IPFS_GATEWAY_URL` already never defaults to a public one — but any design premised on
  free public gateway capacity is now wrong. **Also needs per-segment SHA-256 manifests**, which
  `internal/mediahash` explicitly scopes HLS out of today.

  **Sequence item 4 before item 5.** Nobody has ever measured gateway TTFB for a segment; the only
  latency evidence in the repo is a CI test that polls a public gateway for up to *5 minutes* for
  one object — a reachability proof, not a latency proof, and ~150× a 2-second segment budget.
  Item 5's whole premise is unfalsifiable until measurement exists, so its **first deliverable
  should be measuring the existing client-side path**, not new plumbing.
- [x] **6. P2P (peer-assisted delivery, optional)** — **research half CLOSED 2026-08-22.
  Verdict: DEFER — phase 4 ships no P2P.** Full decision at
  [p2p-delivery-decision.md](p2p-delivery-decision.md).

  The benefit is proportional to *simultaneous viewers on one title*, which the target install does
  not have; the cost is a permanent widening of viewer exposure from "the operator sees my IP" to
  "anyone who can read the public manifest can enumerate everyone watching this video, in real
  time." The swarm id is derived from the video UUID in the page URL, so the swarm is a public
  enumeration oracle — and the attack is not theoretical: a DSN 2024 measurement study harvested
  **7,740 unique viewer IPs from one controlled peer** on this architecture in a week, and in the EU
  (CJEU *Mircom*) harvesting them is expressly lawful. The usual mDNS rebuttal does not apply — that
  draft never became an RFC and explicitly excludes public addresses. "Download-only" is not a
  privacy setting either: the WebRTC connection completes before the upload flag is consulted.
  Two findings make the trigger harder to hit than expected: the commercial market for
  public-internet browser P2P is dead (Peer5/Streamroot/Viblast all DNS-dead), and the bandwidth
  being optimized is **$0** on the hosting the target operator actually uses.

  Not built, deliberately: no `peer` member on `delivery.SourceKind`, no peer source in the
  resolver. Item 3's engine adapter keeps hls.js construction behind one seam — which it must
  anyway for QoE — and that seam is where a loader would attach if this ever flips.

  **One prerequisite IS worth building, independently of P2P: per-segment SHA-256 manifests.**
  Item 5 needs them regardless, and `internal/mediahash` explicitly scopes HLS out today. Tracked as
  part of item 5 rather than as P2P groundwork.
- [ ] **7. Live-plane delivery review** — all three audit claims verified still true (shared
  volume + `os.Open` at `live_hls.go:134`, raw RTMP `0.0.0.0:1935` as a documented prod firewall
  exception, no playback tokens). **Decision taken 2026-08-23: split the item — bring live under
  the SESSION model, and explicitly document the DELIVERY gap.** The original phrasing bundled two
  things with wildly different cost and value.

  **In scope (cheap, high value):** a live playback-session endpoint returning the same session
  object as VOD, carrying a scoped token; `liveStreamForHLS` accepting that token alongside session
  auth; the QoE beacon carrying a live session id with `origin-live` as a first-class
  `delivery_source`; and the hand-rolled `Cache-Control` at `live_hls.go:149-154` moving onto the
  `delivery.CacheControl` constants. The session half is the **only** mechanism that gives live a
  private-but-shareable tier and a revocable, expiring credential — today it has neither. Live has
  no `password` privacy tier at all, so anyone who obtains the stream UUID (handed out on the
  channel's public live detail) can pull segments for the whole broadcast. VOD's equivalent
  capability is enforced with a signed, video-scoped, 6-hour token.

  **Out of scope, and written down as a supported-topology statement rather than a defect:** live
  segments never enter `storage.Backend` during the broadcast — they are ephemeral, live in a
  12-second window, and their names are *reused across restarts* — so they have no `ObjectKey`, no
  presign, no mirror CID and no `?v=` discipline. Forcing them into `delivery.Request` would mean
  inventing a non-storage source kind. Live is also **single-host by construction** (a local Docker
  volume shared by rtmp/api/worker); an api replica on another node sees an empty volume and 404s
  every live request indistinguishably from "not live". **That is a volume problem, not a
  delivery-abstraction problem** — no resolver work fixes it; fixing it properly means replacing
  nginx-rtmp's HLS muxer with a Go-side repackager writing through `storage.Backend`, which is a
  live-plane rewrite and is not phase 4. Record this in `vidra-core/docs/operations.md` beside the
  phase-3 supported-topology section.

  **Riskiest unknown — verify before committing to the design:** VOD makes `?pt=` work by
  *rewriting the m3u8*. Live cannot — the playlist is written by nginx-rtmp and mutates every 2
  seconds. So a token on `master.m3u8` will **not** propagate to the relative segment URIs inside
  it. Either the segment route accepts the token per-request from the query string (plausible; the
  handler already validates names and never rewrites), or Go starts rewriting a file that changes
  every fragment. **Test path (a) against Safari native HLS first** — Safari is precisely the client
  that cannot set headers and is the entire reason `?pt=` exists.

## Build order (decided 2026-08-23 from the recon above)

The items are not independent, and two of the dependencies run opposite to the order the list is
written in.

```text
item 3a  re-key quality identity ──┐        (schedulable NOW; depends on nothing)
                                   ├─► item 3b  collapse the three lifecycles
item 1   playback session API ─────┤              │
         (+ dash_url discovery)    │              ├─► item 3c  engine selection / Shaka
                                   │              │
                                   │              └─► item 4  QoE (needs ONE capture point)
                                   │                        │
item 2   CDN provider + real Purge─┘                        ├─► item 5  IPFS (needs measurement
         (mostly built by phase 2)                          │           before plumbing)
                                                            └─► item 7  live session half
item 6   P2P — research first, decision doc, then a build decision
```

- **Re-key before collapse** (item 3a → 3b) — the item text implies the reverse.
- **Item 4 before item 5** — item 5's premise (health/priority/failover is worth building) is
  unfalsifiable until gateway latency is measured, and item 4 is what measures it.
- **Item 1 gates engine selection**, but *not* the re-key or the collapse, which is what makes
  item 3 startable immediately.
- **Item 2 is mostly done**; what remains (a CDN provider, a real `Purge`, config keys, header
  promotion) is gated on `Purge` existing, because nothing may become shared-cacheable until
  something can invalidate it.

## Exit criteria

- Player fetches a session, then plays without further core-API round-trips per segment.
- Enabling a CDN is an admin configuration act (with purge wired), not a code change; disabling
  it falls back cleanly.
- An admin can see TTFF/rebuffer percentiles per source for the last 24h.
