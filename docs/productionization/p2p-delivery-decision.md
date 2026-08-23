# Decision: P2P (peer-assisted delivery) — build, defer, or close

**Status:** Decided 2026-08-22 · **Phase:** 4, item 6 (the research half) · **Evidence:** primary-source
reads of `p2p-media-loader` v4.0.0 source cloned at HEAD (not docs — the project's own FAQ is stale
against v4), PeerTube 8.2.4's `develop` tree (client integration, tracker controller, `config/default.yaml`,
5,195-line CHANGELOG, privacy guide, viewer-facing strings, and eight years of issue threads), the npm
registry / GitHub APIs / DNS and HTTP probes for version, maintenance and vendor-liveness facts,
RFC 8826/8827/8828 and the mDNS ICE draft for the WebRTC privacy floor, the DSN 2024 peer-assisted-CDN
measurement study, current vendor pricing pages, and Vidra's own `internal/media/cmaf.go`,
`internal/mediahash`, `internal/delivery` and `internal/ipfsmirror`. Every library, version,
maintenance, pricing and vendor-status claim below was fetched or probed, not recalled; what remains
uncertain is listed in "Limits of this research".

## Decision

**DEFER. Do not build P2P in phase 4.** Not because the library is bad — it is healthier than expected —
but because the feature's benefit is proportional to *simultaneous viewers on one title*, which the
target install does not have, while its cost is a **permanent** widening of the viewer's exposure from
"the operator sees my IP" to "anyone on the internet who can read the public manifest can enumerate
everyone watching this video, in real time." For a platform that explicitly serves sensitive, political
and adult content to viewers in hostile jurisdictions, that trade is not close.

Concretely:

1. **Phase 4 ships no P2P.** Item 6's research half is closed by this document; the build half is not
   scheduled.
2. **Build the one prerequisite that is independently justified: per-segment SHA-256 manifests**
   (§"Segment digests"). It is *required* by phase-4 item 5 (IPFS delivery) regardless of P2P, it is
   the gap `internal/mediahash` explicitly declares out of scope, and it happens to be the exact thing
   P2P would need first. This is a real phase-4 work item, not P2P groundwork wearing a disguise.
3. **Reserve the name only.** `delivery.SourceKind` gains no `peer` member and the resolver gains no
   peer source. The engine adapter (item 3) must keep hls.js construction behind one seam — it already
   must, for QoE — and that seam is where a loader mixin would attach if this ever flips. Nothing else.
4. **Write the position down publicly.** "Vidra does not do browser P2P, and here is why" is a feature
   for the operator segment Vidra targets, not an apology. PeerTube ships P2P **on by default** in both
   webapp and embed; a self-hoster choosing between them deserves to know Vidra made the opposite call
   deliberately.

**The trigger that would flip this** is named in §"What would have to be true", and it is a
concurrency-and-cost trigger, not a technology trigger. If it never fires, the correct final state is
DON'T BUILD, and §"What would close it permanently" says what would make that final.

Two things found late in the research make the trigger harder to hit than it looked at the outset, and
are the reason this is DEFER rather than "phase 5": the entire commercial market for public-internet
browser P2P has been shut down (§5), and the bandwidth the feature optimizes is **$0** on the hosting
the target operator actually uses (§5). Meanwhile the harvesting attack that motivates the privacy
objection has been demonstrated empirically on the same architecture — 7,740 viewer IPs from one peer in
one week (§3) — and, in the EU, is expressly lawful.

---

## 1. Current state of the art — better than its reputation

### The library is alive — and was rewritten twice in the last three months

`Novage/p2p-media-loader`, Apache-2.0, is the only serious *self-hostable* browser P2P engine for
HLS/DASH, and it is under active development — not the abandonware the "WebTorrent is dead" narrative
implies:

| Version | Published (npm) | What changed |
|---|---|---|
| 2.2.2 | 2025-11-16 | dependency/lint maintenance |
| 2.3.0 | 2026-05-08 | multi-quality HLS, Shaka Player v5, **breaking infohash change** |
| 2.3.1 / 2.3.2 | 2026-05-10 / 2026-06-01 | truncated-HTTP-segment poisoning fix; byte accounting |
| 3.0.0 | 2026-06-07 | **custom in-tree WebTorrent client replaces the external dependency**, WebRTC tuning, peer churn |
| 3.0.1 | 2026-06-07 | follow-up fixes |
| 4.0.0 | **2026-08-19** | stream identity moves into the core; predictable, server-reproducible swarm infohashes |

(npm registry `p2p-media-loader-core`, and GitHub releases API, both fetched 2026-08-22. Repo:
1,712 stars, 99 commits in the trailing 52 weeks, `pushed_at` 2026-08-19, not archived, 0 open issues.)

Two things matter more than the cadence. First, **v3.0.0 removed the `webtorrent` npm dependency** and
reimplemented just the signaling client in-tree — so "PeerTube uses WebTorrent" is now only true of the
*wire protocol*, not of the supply chain. The runtime deps of `p2p-media-loader-core@4.0.0` are exactly
`debug` and `@types/debug`. Second, **the top contributor is one person** (`mrlika`, 525 commits vs. 146
for the next), at a small Ukrainian company. Bus factor is a genuine risk; PeerTube's author
(`Chocobozzz`) has 8 commits upstream, which is a mitigation of sorts but not a second maintainer.

### What PeerTube actually does today, and what it learned

**PeerTube ships two majors behind the library it is usually credited with driving.** The released
`v8.2.4` tag pins `p2p-media-loader-core|-hlsjs` at `^2.2.2` (client `devDependencies`, with
`hls.js ~1.6.16`); `develop` has been bumped to `^4.0.0` (`hls.js ~1.6.17`) but is unreleased.
Everything analysed in §2 about v4's cross-engine identity design is therefore what PeerTube is *about
to* ship, not what is running in the field today — field behavior is still v2.x's index-based identity.
PeerTube also maintains its own fork of the library (`Chocobozzz/p2p-media-loader`, last pushed
2026-08-04). There is **no `webtorrent` or `bittorrent-tracker` dependency in the client at all**; the
server keeps `@peertube/bittorrent-tracker-server ^11.1.2` (a PeerTube fork, server-only, last published
2024-07-31) because PeerTube runs the tracker itself.

The changelog is the most useful artifact in this whole investigation, because it is a 8-year record of
a project discovering the costs of this feature one at a time:

- **v1.0.0-beta.10.pre.1** — "Add tracker rate limiter", "Improve explanations of P2P & Privacy section
  in about page". The privacy explanation problem is as old as the feature.
- **v1.0.0-beta.11** — "Tracker only accept known infohash (avoid people to use your tracker for files
  unrelated to PeerTube)". *An open WebTorrent tracker becomes someone else's distribution
  infrastructure.* This is the single most under-budgeted operator risk.
- **v1.3.0** — "Add ability for admins to disable the tracker (and so the P2P aspect of PeerTube, **in
  order to improve users privacy** for example)". PeerTube's own framing.
- **v3.0.1** — "Fix bad tracker client IP when using a reverse proxy." Every reverse-proxy deployment
  gets this wrong once.
- **v4.1.0** — P2P disableable in embeds via a `p2p` URL parameter (i.e. embeds are P2P-on by default).
- **v4.2.0** — live latency setting: "small latency without P2P or high latency to increase P2P ratio."
  **P2P is explicitly traded against latency**, by the upstream project, in its own UI.
- **v4.3.0** — `log.log_tracker_unknown_infohash` to silence the noise from item two above.
- **v5.1.0** — tracker-blocked IPs moved from Redis to Node memory "reducing PeerTube load".
- **v6.0.0** — **"Remove WebTorrent support in player"**: whole-file torrent P2P is gone; "We still use
  P2P with the HLS player." "WebTorrent videos" renamed "Web Video" — "The video format is the same, we
  just stop to use P2P for these videos."
- **v6.2.1** — "Fix broken HLS P2P by correctly updating HLS infohash on privacy update." Swarm
  identity is *derived state* that must be resynchronized whenever a video's privacy changes, and
  PeerTube shipped it desynchronized. (The stored infohash goes stale against the new playlist URL, so
  the symptom PeerTube fixed was P2P breaking; the same desynchronization class in the other direction
  is a stale swarm outliving the privacy change. I verified the model stores pre-computed infohashes
  with no privacy coupling in the model itself — I did **not** verify that a leak occurred, and am not
  claiming one.)
- **v6.3.0** — nginx `access_log: off` removed for static video, "now the player doesn't use WebTorrent
  anymore (which was doing a large amount of small HTTP requests)".
- **v7.1.0** — "Remove WebTorrent redundancy support... It hasn't been used in the player for several
  major versions"; upgrade p2p-media-loader to v2.
- **v8.0.0** — "Add more STUN Servers to `webrtc.stun_servers` to improve P2P robustness."
- **v8.2.3** — **"Fix P2P segment validator to correctly reject invalid chunks."** In 2026. In the
  security-critical component.

The arc is unambiguous: PeerTube moved from *whole-file* P2P (the thing everyone remembers) to
*segment-level* P2P on HLS only, deleted the whole-file path entirely, and has spent the years since
paying a steady maintenance tax in tracker abuse controls, proxy/IP correctness, privacy-state
propagation, and validator bugs. **Nothing in that record suggests P2P got cheaper.**

### The reference integration, in full

PeerTube's `hls-options-builder.ts` configures the engine with: `announceTrackers` = the instance's own
tracker (entries filtered to those starting with `ws`); `rtcConfig` from the instance's configured STUN
servers; `isP2PDisabled: !p2pEnabled`; `isP2PUploadDisabled` set on cellular connections or when a
`peertube-videojs-p2p-consume-only` localStorage flag is set; `highDemandTimeWindow` 4 for live / 15
for VOD; and — decisively — **both `validateP2PSegment` and `validateHTTPSegment` bound to a SHA-256
validator**.

Two details matter more than the rest.

**PeerTube refuses to run P2P at all without the digest manifest.** `hls-options-builder.ts:45-48`:

```ts
const segmentsSha256Url = this.options.hls.segmentsSha256Url
if (!segmentsSha256Url) {
  logger.info('No segmentsSha256Url found. Disabling P2P & redundancy.')
```

The per-segment hash file is not a hardening option in the reference implementation — it is a hard
precondition. Vidra does not have one (§2).

**The swarm string is not the playlist URL.** `swarmId: this.options.hls.playlistUrl` is set at line
203, but line 146 overrides the whole derivation with a `streamSwarmIdBuilder` calling
`generateSwarmId()` from `@peertube/peertube-core-utils`, which returns
`pt-${peerProtocolVersion}-${videoUUID}-${streamType}-${codecName}-${resolution}` (audio variants
substitute `language` for `resolution`). The server precomputes exactly these strings' infohashes to
populate its "private" tracker allowlist. This is also the hook Vidra would use to put the packaging
protocol into the swarm ID (§2) — and, as §3 shows, it is what makes every swarm on a PeerTube instance
derivable from a video UUID alone.

`config/default.yaml`, verbatim:

```yaml
tracker:
  # If you disable the tracker, you disable the P2P on your PeerTube instance
  enabled: true
  # Only handle requests on your videos
  # If you set this to false it means you have a public tracker
  # Then, it is possible that clients overload your instance with external torrents
  private: true
  # Reject peers that do a lot of announces (could improve privacy of TCP/UDP peers)
  reject_too_many_announces: false
```

```yaml
  p2p:
    # Enable P2P by default in PeerTube client
    # Can be enabled/disabled by anonymous users and logged in users
    webapp:
      enabled: true
    # Enable P2P by default in PeerTube embed
    # Can be enabled/disabled by URL option
    embed:
      enabled: true
```

**PeerTube is opt-out, in both the app and third-party embeds.** Vidra's phase doc mandates opt-in and
default-off, which is already a departure from the reference implementation — and, as §3 argues, it is
not a sufficient one.

---

## 2. Segment granularity — and what phase 3's shared segments actually do

**Yes, it works at CMAF/fMP4 segment granularity.** The hls.js integration replaces hls.js's *fragment*
loader and keys every segment on `getSegmentRuntimeId(url, byteRange)` — `url` or `url|start-end`. It
neither parses nor cares about the container. Vidra's CMAF output
(`chunk-$RepresentationID$-$Number%05d$.m4s`, `-seg_duration 6`, `internal/media/cmaf.go`) is discrete
files with no byte ranges, which is the simplest possible case. There is no "whole-video blob" mode in
this library at all — the whole-file path is the thing PeerTube deleted in v6.0.0.

Three sharp details, read out of the source:

**Init segments never go over P2P.** `SegmentManager.updatePlaylist` registers only `details.fragments`;
an `EXT-X-MAP` init segment is not among them, so `FragmentLoaderBase.load` finds
`!core.hasSegment(segmentId)` and delegates to the default hls.js loader. Correct behavior, and it means
every CMAF viewer makes an origin request for each rung's init segment the first time it plays that
rung. (Read from source; not empirically run.)

**hls.js's ABR estimator is displaced.** The loader initializes `stats.total = stats.loaded = 1`
explicitly "to prevent hls.js on progress loading monitoring in AbrController", then synthesizes
`stats.loading` from the P2P engine's own bandwidth figure. Vidra's player feeds
`abrEwmaDefaultEstimate` from a *stored measurement of the authoritative server*
(`use-hls-playback.ts`) — that machinery and this one are two ABR seeds fighting over the same
controller. Any integration must reconcile them, and QoE bitrate-switch metrics (item 4) would be
measuring a distorted signal.

**Fallback discipline is the library's default, not something Vidra must add.** In `hybrid-loader.ts`,
within the `highDemandTimeWindow` (default 15s of playback ahead) HTTP is preferred; an *in-flight P2P
download* is cancelled and re-issued over HTTP as soon as HTTP capacity frees
(`shouldSwitchFromP2PToHttp`). Only outside that window is P2P used alone. Peers are structurally a
prefetch accelerator, never on the critical path. This is exactly the phase-doc requirement, already
satisfied upstream.

### Does phase 3's HLS+DASH shared-segment design help? No — and it hides a trap

This was the genuinely open question, and the answer is worse than "neutral".

v4 derives a stream's identity from **stream properties, not manifest position**
(`computeStreamIdentityHash({bitrate, codecs, width, height, language, channels, name, frameRate,
videoRange})` → SHA-1 → base64), and the two integrations *deliberately* normalize toward each other.
From the Shaka integration's own comments: audio codecs are stripped from muxed video codec arrays
"to strictly match HLS.js's cleanly separated videoCodec parsing, ensuring peers on identical video
tracks share P2P segments regardless of differently selected audio track descriptors"; and from the
hls.js side, `maxBitrate` (the `BANDWIDTH` tag) is preferred over `bitrate` (`AVERAGE-BANDWIDTH`)
"to universally match Shaka's variant.bandwidth parsing". **Cross-engine swarm unification is an
explicit v4 design goal.** So an HLS viewer and a DASH viewer of the same Vidra rung would compute the
same `identityHash`.

But `Segment.externalId` — the only identifier peers exchange on the wire — is derived
**per protocol, not per engine**:

- HLS (both hls.js and Shaka-playing-HLS): the media sequence number / fragment index.
- DASH (`processDashSegmentReferences`): `Math.trunc(reference.getStartTime() / 0.5)`.

For Vidra's 6-second segments, the DASH viewer numbers the same byte-identical file `0, 12, 24, 36…`
while the HLS viewer numbers it `0, 1, 2, 3…`. They collide at 0, 12, 24 — **overlapping but wrong**.

Today this is harmless only by accident: the default `swarmId` is
`config.swarmId ?? this.manifestResponseUrl` (`core.ts:409`), and Vidra's `master.m3u8` and
`stream.mpd` are different URLs, so the two protocols land in different swarms. The trap is that the
*obvious* optimization — "our HLS and DASH are literally the same bytes, so set `swarmId` to the video
ID and let them share" — produces one swarm in which peers request each other's segments under
mismatched numbering, and the library performs **no integrity check by default**
(`validateP2PSegment` defaults to `undefined`; the only call sites are `p2p/peer.ts` and `p2p/loader.ts`
passing the user-supplied callback through). The result is silently wrong bytes in the media buffer.

So: phase 3's shared-segment design is **not an advantage for P2P**. Its only real contribution is that
one per-segment digest manifest would serve both protocols, because the bytes are identical. The correct
integration rule, if this is ever built, is: **the packaging protocol must be part of the swarm ID** —
never unify HLS and DASH swarms, even though the segments are byte-identical.

### Segment digests — the prerequisite worth building anyway

`internal/mediahash/service.go` says it plainly: *"Deliberately out of scope: HLS segments and
playlists. They have no `video_files` rows — a ladder rung is one `video_renditions` row covering a whole
directory of segments — so there is no per-object place to record a digest and nothing that would read
one back."* Vidra therefore has **no per-segment digests**, and P2P without them means accepting
arbitrary bytes from arbitrary internet peers into the media buffer.

PeerTube's answer is `segments-sha256.json` per playlist, fetched by the client, consulted by
`segment-validator.ts` for *both* P2P and HTTP segments, with byte-range support
(`segmentValue[start + '-' + end]`) and a 10×500ms retry when a hash is not yet known. PeerTube was
still fixing that validator in v8.2.3 (2026).

The reason to build the equivalent regardless of P2P: **phase-4 item 5 promotes IPFS from a metadata
mirror to a real delivery source.** A public IPFS gateway is third-party infrastructure returning bytes
that Vidra's player will feed to MSE. The same `validateHTTPSegment`-shaped hook, backed by the same
digest manifest, is what makes gateway-delivered and CDN-delivered segments verifiable — and it closes
the mediahash gap for the largest class of objects Vidra stores. Cost is low: the digest is computable
in the packaging pass as segments stream to storage, and the write path already produces a SHA-256 for
`video_files` (migration 0106). Size is the real design constraint — a 1-hour video at 6s segments
across 5 rungs is ~3,000 digests, ~230 KB as naive JSON,
which must not become a blocking pre-roll fetch; per-rung files or a compact binary form, fetched lazily
alongside the media playlist, is the shape to aim for.

---

## 3. WebRTC privacy — the part that decides it

### The floor is set by the protocol, not the library

RFC 8826 (*Security Considerations for WebRTC*, January 2021), §4.2.4 "IP Location Privacy":

> "Note that as soon as the callee sends their ICE candidates, the caller learns the callee's IP
> addresses. The callee's server-reflexive address reveals a lot of information about the callee's
> location."

and, on VPN users specifically:

> "because sites can cause the browser to provide IP addresses, this provides a mechanism for sites to
> learn about the user's network environment even if the user is behind a VPN that masks their IP
> address."

RFC 8827 (*WebRTC Security Architecture*, January 2021) §6.4 is blunter still:

> "A side effect of the default ICE behavior is that the peer learns one's IP address, which leaks
> large amounts of location information."

RFC 8828 (*WebRTC IP Address Handling Requirements*, January 2021) defines the four modes; Mode 2/3
restrict **private/host** candidate disclosure. Mode 3 keeps "the only IP addresses gathered are those
discovered via mechanisms like STUN and TURN" — i.e. **the public address is what remains, by design,
because that is what the peer must reach.** The only mode that hides it is Mode 4 / forced TURN relay,
and forcing TURN means the operator pays for every relayed byte — **the sole mitigation that works
destroys the entire economic rationale for the feature.**

**The mDNS mitigation does not apply here, and this is the most common technical error in the debate.**
Browser mDNS obfuscation of ICE candidates comes from `draft-ietf-mmusic-mdns-ice-candidates`, which
**never became an RFC** (rev 03, `intended_std_level: inf`, expired 2022-06-09) — it is browser
practice, not a standard — and §3.1.2.2 of that draft excludes public addresses explicitly:

> "Naturally, an address that is already exposed to the Internet does not need to be protected by mDNS,
> as it can be trivially observed by the web server or remote endpoint."
> "Regardless of whether the address turns out to be public or private, a server-reflexive candidate
> will be generated…"

Chrome's 2019 announcement is scoped the same way: *private* IP addresses in host candidates are
replaced by an mDNS hostname. mDNS solved local-network fingerprinting. **It did nothing about the
public address, which is the one that identifies a viewer.** PeerTube's own issue tracker contains the
opposite claim from a maintainer (§3, "what the maintainers say"), and it is wrong.

Note what this does to a specific Vidra user: a viewer in a hostile jurisdiction using a VPN to reach an
instance is *more* exposed by WebRTC than by plain HTTPS, not less, per RFC 8826's own text.

### The swarm is a public enumeration oracle — verified end to end

This is the finding that decides the question, and both halves of it were read out of source rather than
inferred:

1. **The infohash is a pure function of public data.** `computeStreamSwarmId` =
   `"v2-" + swarmId + "-" + streamType + "-" + identityHash`, where `swarmId` defaults to the manifest
   URL and `identityHash` is SHA-1 of properties (`bitrate`, `codecs`, `width`, `height`, …) that are
   *printed in the public master playlist*. `computeInfoHash` = `btoa(sha1(streamSwarmId).slice(0,15))`.
   The library's own doc comment advertises this reproducibility: *"use it on a server (Node.js 16+) to
   compute the infohashes to allowlist on a private tracker."* PeerTube does exactly that —
   `packages/node-utils/src/p2p.ts` reimplements it as
   `return btoa(sha1(input, 'binary').slice(0, 15))`. **Anyone who can load a public video page can
   compute its swarm's infohash.** A ~50-line Go reimplementation would do it.
2. **Joining a swarm hands you the members.** The tracker protocol
   (documented in the library's own `webtorrent-client/spec.md`) is JSON over WebSocket: you `announce`
   with the infohash and a set of SDP `offers`; the tracker routes offers to other members and routes
   their `answer`s back to you, each carrying the remote `peer_id`. Completing ICE with each yields
   their address. An observer needs no special tooling — **the library itself is the tool.** Point it at
   a public video's infohash, answer every offer, log the addresses.

On a PeerTube instance the derivation is even shorter than the generic case: the swarm string is
`pt-${peerProtocolVersion}-${videoUUID}-${streamType}-${codecName}-${resolution}`, so **the video UUID
from the page URL plus a resolution from the public playlist is the entire input.** Nothing has to be
guessed. And the unauthenticated video API hands out the infohashes and tracker URLs directly anyway,
in the magnet links it publishes.

**PeerTube's own maintainer documented the technique.** Chocobozzz, in `webtorrent/bittorrent-tracker`
issue #271 (2019-01-21), answering a research group that had failed to observe peer IPs:

> "I think you are able to find the IP address in the `SDP offer` (between `tracker` and `peer 2`).
> Tracking users using webtorrent protocol is harder than the classic bittorrent protocol, because the
> tracker does not send directly IP address to those who request them. **But it's still possible if you
> seed a particular file: you just have to wait the `SDP offer` from the tracker.**"

That is the attack, stated by the person who wrote the platform. Note the asymmetry it turns on: a plain
*HTTP* announce returns only TCP/UDP peers — which is why PeerTube's docs can truthfully say "web peers
are not publicly accessible" — but a **WebSocket** client joins the signalling mesh and receives SDP
from real viewers. The public-facing reassurance and the maintainer's technical answer describe
different transports.

**And it has been done, at scale, on comparable systems.** Tang et al., *"Stealthy Peers: Understanding
Security and Privacy Risks of Peer-Assisted Video Streaming"*, DSN 2024 (DOI 10.1109/DSN58291.2024.00041;
preprint arXiv:2212.02740) studied WebRTC peer-assisted delivery networks — the same architecture, not
classic BitTorrent:

> "all PDN services expose viewers' real IPs extensively with few protections. This enables an attacker
> to harvest viewers' IPs and link them to the content of the videos being watched."
> "Altogether, our PDN analyzer gathered 7,740 unique peer IP addresses, including 7,055 from Huya TV
> and 685 from RT News."

That was **one controlled peer, roughly two hours a day, for one week** — with the RT News viewers
spanning 259 cities in 56 countries. The "in practice this is difficult" defence does not survive it.

The consequence: for any public video on a P2P-enabled instance, an arbitrary third party can obtain a
**live, timestamped list of the IP addresses currently watching that specific title**, without
authenticating, without appearing in the operator's logs, and without the operator being able to detect
it. Two PeerTube defences are weaker than they read:

- **`tracker.private: true` blocks nothing here.** The infohash is *supposed* to be on the allowlist —
  the server precomputes exactly these. That control exists to stop strangers distributing unrelated
  torrents through your tracker (v1.0.0-beta.11), not to stop swarm enumeration.
- **The announce rate limit is off by default.** `reject_too_many_announces: false` is the shipped
  default, so the `ANNOUNCES_PER_IP_PER_INFOHASH: 15` / `ANNOUNCES_PER_IP: 30` limits in
  `initializers/constants.ts` are inert; the other checker only calls `logger.warn`. Meanwhile
  `bittorrent-tracker`'s `MAX_ANNOUNCE_PEERS = 82` caps yield *per announce*, and announces are
  unmetered. PeerTube's privacy guide argues that "there must be at least 50 requests sent to know every
  peer in the swarm" — on a default install, making 50 requests costs nothing.

Compare the honest baseline. Without P2P, watching a video reveals your IP to: the instance operator,
their CDN, and their transit. With P2P it additionally reveals it to *any interested party*, correlated
to a specific title, in real time. For a general-interest video platform that is an unpleasant
externality. For an instance hosting political organizing, or adult content in a jurisdiction that
criminalizes consuming it, it is the difference between "trust your operator" and "assume you are
enumerable." Vidra is not speculating about that audience: it already ships granular sensitive-content
machinery (`internal/video`, `internal/instancesettings`, `vidra-user/lib/use-sensitive-policy.ts`, a
device-level restricted mode) precisely because instances host content whose viewers have a reason to
care who knows they watched it.

### What PeerTube itself says — and what its viewers actually see

PeerTube's own privacy guide concedes the substance. Its GDPR claim is **conditional**:

> "PeerTube core (without installed plugins) is GDPR compatible: It doesn't send personal data to any
> third party **if P2P and remote redundancy are disabled**"

Its data-processing register entry for "Player P2P" reads, verbatim:

> **Persons concerned** — Any visitor that is watching a video
> **Purpose** — Reduce server load: legitimate interest — Improve playback quality: legitimate interest
> **Processed data** — IP address
> **Data retention** — As long as the user is watching the video
> **Recipients** — System administrators — **Other peers that are watching the video, and so
> potentially with remote peers outside the European Union**

The mitigations it offers are the ones §3 has just dismantled ("there must be at least 50 requests sent
to know every peer in the swarm"; "the IP address is a vague information"; "web peers are not publicly
accessible"), ending at: *"if you want to keep your IP private, you must use a VPN or Tor Browser."*
Per RFC 8826, the VPN advice is itself unreliable against WebRTC.

**The viewer-facing text is a notice, not a consent gate.** Watch page
(`privacy-concerns.component.html`):

> "**Friendly Reminder:** the sharing system used for this video implies that some technical
> information about your system (such as a public IP address) can be sent to other peers."

Its only control is a button labelled **"OK"**; it never gates playback, it writes a localStorage key
and never appears again, and it renders only when P2P is *already* enabled — i.e. **after** the swarm
join. The embed string is `"Watching this video may reveal your IP address to others."`, and it is
suppressible: the share dialog exposes a checkbox documented as *"Display privacy warning (only for
Embed): unclick if you don't want to display…"*, wired to `warningTitle=0` — **an embed parameter
independent of `p2p`**, so anyone embedding a PeerTube video can run P2P with the warning switched off.
The user setting is labelled *"Help share videos being played"* and marked `[recommended]="true"`.

**There is no per-video control.** `isP2PEnabled()` consults only instance tracker state and the
viewer's own toggle; the video model carries no P2P field. On PeerTube, **a creator cannot disable P2P
for a sensitive video.** That is the single most important thing Vidra would have to do differently,
and it is §"What opt-in has to mean" item 2.

### What the maintainers say, and where it is wrong

The position is long-standing and consistent. Issue #316 (2018) opens *"By design, viewers don't have
privacy."* Chocobozzz added a blocking confirm modal in March 2018 and removed it three weeks later
(#355), with the reasoning:

> "People that don't want to expose their public IP address to the world should use a VPN or Tor.
> Disabling P2P in PeerTube would just add a false feeling of privacy."

Issue #2934 — *"Privacy concerns around P2P, WebRTC and the opt-out pattern"* (2020, closed, labelled
"Type: Discussion") — raised exactly this document's objection: *"Re-sharing is enabled by default (aka
it's opt-out)… no process to require **informed** consent."* The maintainer rebuttal is the load-bearing
error:

> "Leaking your public IP did indeed used to be an issue with WebRTC, but this was fixed a long time ago
> (back in 2011) in Firefox and Chrome."

What was fixed is *private/local* IP leakage. The public address is unaffected — see the mDNS draft's own
§3.1.2.2 above. The thread was closed with "admins have now the choice to opt-in or opt-out P2P", which
answers a different question than the one asked. Relatedly, issue #4806: admins who disabled WebTorrent
transcoding believing it disabled P2P were wrong — *"HLS also uses P2P :)"*.

None of this is a criticism of PeerTube's engineering; it is evidence that after eight years the
strongest available defence of the feature is "use Tor if you care", and that the community pressure
runs toward *hiding* the warning rather than tightening it (a 2024-25 forum thread resolved an admin's
"hide the IP exposure warning while keeping P2P" request with CSS `display: none`).

### The legal position: harvesting swarm IPs is lawful in the EU

This matters because it removes the fallback assumption that the law would deter the attack.

- **Viewer IPs are personal data for the platform.** CJEU *Breyer* (C-582/14, 19 Oct 2016) — a dynamic
  IP address is personal data where the controller has legal means to identify the subject with ISP
  data. *IAB Europe* (C-604/22, 2024) treats the IP address as the paradigm identifier.
- **Harvesting them from a P2P swarm is expressly permitted.** CJEU *Mircom* (C-597/19, 17 June 2021)
  holds that Art 6(1)(f) GDPR "precludes in principle, neither the systematic recording, by the holder
  of intellectual property rights as well as by a third party on his or her behalf, of IP addresses of
  users of peer-to-peer networks…". **The enumeration attack in §3 is not merely feasible; for a class
  of well-funded actors it is a settled lawful practice with existing tooling economics.**
- **The same judgment sets the consent bar for the viewer**, conditioning a user's own exposure on their
  having consented "after having been duly informed of its characteristics" — which a dismissible "OK"
  banner shown after the swarm join does not achieve.
- **The legitimate-interest basis PeerTube relies on is untested and its necessity prong is the weak
  one.** The closest analogue with actual authority is the Google Fonts line of German decisions, where
  transmitting a visitor IP to a third party failed Art 6(1)(f) precisely because it *was not
  necessary* — the content was deliverable without it. Video is deliverable without P2P, and PeerTube's
  own config proves it with a boolean. (Applying ePrivacy Art 5(3) and EDPB Guidelines 2/2023 — which do
  contemplate ad-hoc peer relaying at ¶25 — to peer-assisted CDN is **analysis, not cited authority**:
  no DPA has ruled on it. Note also that the widely cited LfDI Baden-Württemberg guidance recommending
  PeerTube as a privacy-friendly YouTube alternative **contains no mention of P2P at all** and must not
  be cited as regulatory approval of it.)

### "Download-only mode" is a bandwidth setting, not a privacy setting

The most common proposed compromise — "let viewers consume from peers without uploading" — **does not
reduce IP exposure at all.** In `p2p/loader.ts`, `isP2PUploadDisabled` is checked at line 321, *after*
`#onPeerConnected` has already fired; it suppresses the segment announcement, and at line 406 it answers
incoming requests with `sendSegmentAbsentCommand`. The WebRTC connection is established either way. The
same is true of `shouldGenerateOffers: false`, which sends `numwant: 0` "while still answering incoming
offers". **Only `isP2PDisabled: true` keeps a viewer out of the swarm.** PeerTube's cellular-detection
and `consume-only` flag are data-plan protections; presenting anything like them as a privacy option
would be misleading.

### What opt-in has to mean, concretely

If this is ever built, all five of the following are required — not a menu:

1. **Per-instance:** off by default, an explicit operator enable. Necessary, and *insufficient on its
   own* — an operator enabling it is consenting on the viewer's behalf, which is precisely the failure
   mode.
2. **Per-video:** a default-deny eligibility fence. Vidra already owns exactly the right precedent —
   `internal/ipfsmirror`'s public-only gate (`classes.go`: *"the eligibility gate (eligibility.go) is
   the privacy fence and is default-deny"*), which excludes private and unlisted objects and re-checks
   the owner's flags. A P2P fence must reuse it and be **strictly narrower** (at minimum also excluding
   sensitive-flagged content). PeerTube's v6.2.1 infohash-on-privacy-update fix is the warning: swarm
   membership is derived state, so the fence must be tested against privacy *transitions*
   (public → unlisted → private, and the sensitive flag being set after upload), not just initial
   state.
3. **Per-viewer, per-device, explicit, never pre-checked.** `lib/device-preferences.ts` is the existing
   pattern (localStorage, `useSyncExternalStore`); an account-level default that silently applies on a
   new device is not consent.
4. **Never in embeds. No override.** PeerTube's embeds are P2P-on by default with a URL opt-out; a
   viewer on a third-party site never chose your instance at all. Vidra already has embed-privacy
   machinery (`lib/embed-privacy.ts`) whose whole purpose is deciding what an embedded player may do.
5. **A plain sentence, not a euphemism.** The UI must say approximately *"Other people watching this
   video — and anyone who chooses to look — will be able to see your IP address."* Not "help share the
   load", not a peer-count widget (PeerTube's in-player P2P control is informational only: download
   speed, upload speed, "peers", "From servers:"/"From peers:" — no toggle). **If that sentence cannot
   be shipped in the product's voice, the feature cannot be shipped.**

6. **A live concurrency gate.** P2P must not engage below a configured number of simultaneous peers on
   the same rendition, because below it the feature is provably all cost and no benefit: the ceiling is
   (N−1)/N, and DSN 2024 measured peers uploading *up to 200% of their download* at three peers. This
   is what PeerTube issue #5493 has been asking for since 2022 and still does not have.

Note how far that list is from industry practice. DSN 2024 audited 134 websites, 38 Android apps and 10
private deployments and found: *"**none of them provide any pop-up windows to ask for viewers' consent**
or communicate with their viewers the P2P network they are about to join through 'Terms of Use' or other
web content… **none of the PDN providers we studied allow viewers to turn off the PDN function.**"* When
challenged, vendors *"argued that they suggest their customers inform users"* — a duty passed downstream
and discharged by nobody. Building this properly means being the first deployment to do so.

And the asymmetry that no amount of consent design fixes: consenting viewers only expose themselves to
*each other*, which is arguably symmetric and fair. But the harvesting observer consents to nothing,
contributes nothing, and is indistinguishable from a peer — and per *Mircom*, in the EU, is acting
lawfully. **A viewer's consent protects nobody from the party that matters.**

---

## 4. Tracker / signaling — and the parts nobody budgets for

The library ships three public trackers as defaults (`wss://tracker.novage.com.ua`,
`wss://tracker.webtorrent.dev`, `wss://tracker.openwebtorrent.com`) and its own FAQ says not to use
them: *"they support a limited number of peers and can reject connections or even go down on a heavy
loads. That is why they can't be used in production environments."* They also put your viewers'
signaling — and the swarm membership of your videos — on infrastructure you do not control. Not an
option for Vidra.

That leaves four:

| Option | What the self-hoster stands up | Verdict |
|---|---|---|
| Public trackers | nothing | Ruled out by upstream and by privacy |
| Hosted/commercial tracker | an account and a bill | Violates "basic install needs zero external services" |
| Sidecar container (`aquatic`, Rust; `wt-tracker`, Node; `bittorrent-tracker`, Node) | another service, profile, TLS route, and `vidra doctor` check | Workable; all three are maintained (`pushed_at` 2026-07-13 / 2026-06-07 / 2026-08-12) but it is another moving part |
| **Tracker embedded in vidra-core (Go)** | nothing new to install | The only option consistent with the program's philosophy |

The embedded option is more tractable than it sounds, and I can say so precisely because the library
documents its own wire protocol: six JSON-over-WebSocket message shapes (`announce` with `offers`;
announce response with `interval`/`complete`/`incomplete`; `failure reason`; `warning message`; offer
relay; answer relay with `to_peer_id`), plus per-infohash swarm membership held in memory. That is a
few hundred lines of Go on `gorilla/websocket`-class plumbing, mounted at `/tracker/socket` behind the
existing managed Caddy TLS — PeerTube's exact topology (`server/core/controllers/tracker.ts` registers
`GET /tracker/announce`, `GET /tracker/scrape` and the `/tracker/socket` upgrade, with all of `http`,
`udp`, `ws` disabled in the library and a custom `filter` doing the work). **No mature Go WebTorrent
tracker exists** to adopt — searches surfaced only generic WebSocket libraries and the Node/Rust
implementations above — so this is new code Vidra would own.

The costs that get left out of that estimate:

- **Abuse controls are not optional, they are the feature.** PeerTube's tracker carries an infohash
  allowlist backed by a cached DB lookup (`VideoInfohashModel.doesInfohashExistCached`), per-IP and
  per-IP-per-infohash announce counters, an LRU of blocked IPs with a TTL, 403s on WebSocket upgrade
  for blocked IPs, and a background suspicious-activity checker. Every one of those exists because
  something went wrong. Ship the tracker without them and you have published an open relay.
- **Proxy-correct client IPs.** The tracker must resolve the real peer IP through the reverse proxy
  (PeerTube uses `proxyAddr`; it shipped a fix for getting this wrong in v3.0.1). Vidra has
  `TRUSTED_PROXY_CIDRS` from phase-1 item 12, so the input exists — but a tracker that trusts the wrong
  header rate-limits and blocks the proxy instead of the abuser.
- **STUN is the hidden third-party dependency.** The library's default `rtcConfig` points at
  `stun:stun.l.google.com:19302` and `stun:global.stun.twilio.com:3478`. An instance whose selling
  point is not phoning home would be sending every viewer to Google to learn their public IP.
  PeerTube ships its own list (`stun:stunserver2025.stunprotocol.org`, `stun:stun.framasoft.org`,
  `stun:stun.ekiga.net`, `stun:stun.freeswitch.org`) and added more in v8.0.0 "to improve P2P
  robustness" — i.e. these go stale and break. Its client then does
  `shuffle(stunServers.map(...)).slice(0, 2)`, so **every viewer session sends a STUN binding request —
  whose entire purpose is to reveal the client's public IP — to two randomly chosen third-party
  operators**, three of whose four defaults are outside the instance's control and none of which appear
  as recipients in PeerTube's own data-processing register. Running your own STUN is another container.
- **The default trackers are not reliable either.** Probing the library's three hardcoded defaults on
  2026-08-22: `tracker.webtorrent.dev` upgraded (HTTP 101); `tracker.openwebtorrent.com` returned 404
  with no WS upgrade; `tracker.novage.com.ua` resolved but did not answer on 80/443. Single vantage
  point, so not a confirmed global outage — but shipping the library's defaults is not a plan.
- **A tracker is stateful, and phase 5 wants stateless API nodes.** Swarm membership lives in the
  process. Two API replicas behind a load balancer means two disjoint swarms per video, halving an
  already-marginal peer pool — directly against phase-5 item 8's multi-node API goal, and awkward
  against the leader-election/multi-instance work phase 3 just landed.

Net: standing up signaling is *possible* within "one VPS in minutes", but the honest bill is a new
public WebSocket endpoint, an abuse-control subsystem, a STUN answer, and a documented conflict with
the multi-node roadmap.

---

## 5. Alternatives — is P2P still the right answer?

The comparison is not "P2P vs. nothing". Vidra already has, or is about to have, three delivery sources
in `internal/delivery`: `api-proxy` (permanent authoritative fallback), `presigned`, `ipfs-gateway`,
with `cdn` arriving as phase-4 item 2. The question is whether a fourth, `peer`, earns its place.

**The economics have not merely moved against it — for the target install the bill being optimized is
often literally zero.** P2P's premise is that egress dominates the operator's cost. Published rates,
fetched 2026-08-22:

| Path | Cost of the first TB/month of video egress |
|---|---|
| Hetzner dedicated, 1 Gbit uplink | **$0** — "unlimited traffic" |
| Hetzner Cloud, EU | **$0** — "at least 20 TB of included traffic"; ~€1/TB beyond |
| Cloudflare R2 | **$0** — egress "does not incur data transfer (egress) charges and is free" |
| Backblaze B2 → partner CDN (incl. bunny.net) | **$0** origin egress — "unlimited free egress when downloading to or through partner content delivery networks" |
| Bunny Volume / Bunny standard EU-NA | $5 / $10 per TB ($0.005 / $0.01 per GB, $1 monthly minimum) |
| AWS CloudFront pay-as-you-go | $85/TB after the free tier |

A 720p rung at ~2.5 Mbps is ~1.1 GB per viewing-hour, so a self-hoster doing 1 TB/month — roughly 900
viewing-hours — is at **5% of a single Hetzner EU box's included allowance**. You cannot save a
meaningful fraction of zero. Even on a metered CDN, a *busy* instance at 5,000 viewing-hours/month pays
$28–55, and an optimistic 50% offload saves $14–27 against ~6.5–8 weeks of build and permanent
maintenance in the most consequence-heavy part of the stack.

The sharpest single number comes from the DSN 2024 study, which recorded what the leading vendor
actually charged: *"Peer5 will charge a customer $500 for offloading 50TB video traffic from the
original video server."* That is **$0.01/GB — exactly Bunny's standard EU/NA delivery rate and twice its
Volume rate.** At the commercial peak of this category, paying someone to make a terabyte disappear cost
the same as simply buying the terabyte.

**The concurrency requirement is the real killer, and it is arithmetic, not opinion.** A peer can only
serve a segment it has already fetched, and only into another viewer's prefetch window — everything
inside the 15-second high-demand window goes to HTTP by design (§2). For VOD with viewers arriving at
random times, two viewers of the same video overlap usefully only if their playheads are close. The
library's own FAQ concedes the ceiling, verbatim: *"For example for 10 peers in the best case the
maximum possible P2P ratio is 90% if a stream was downloaded from the source only once."* Ten
*simultaneous* peers on one title is already an unusual day for a self-hosted instance; the median Vidra
video will have one viewer at a time, for whom the FAQ's other answer applies: *"P2P Media Loader
downloads all the segments from HTTP(S) source in this case. It should not perform worse than a player
configured without P2P at all."* The ceiling is **(N−1)/N** in *simultaneous, time-aligned* peers:
0% at one viewer, 50% at two, 67% at three.

**PeerTube's own best result required 1,000 concurrent browsers.** Its 2023 stress test reports
*"P2P saves 98% of bandwidth"* for VOD and *"P2P saves 75%"* for normal-latency live — achieved by
simulating *"1,000 real Chrome web browsers watching the same video"*, and caveated as *"optimal
conditions, since our simulated web browsers had fast internet connection"*. That is the number quoted
in every pro-P2P argument, and it is a measurement of a scenario a self-hosted instance essentially
never has.

**At the swarm sizes a self-hoster does have, the feature taxes viewers to save the operator nothing.**
DSN 2024, measuring real deployments: *"the upload traffic of peers increases dramatically (up to 200%
of the download traffic with 3 peers) as the number of peers grows, while their download traffic does
not go up accordingly"*, plus *"15% more CPU and 10% more memory"*. A three-peer swarm can ask each
viewer to upload twice what they downloaded, to relieve an origin bill that is already $0.

**PeerTube's community has asked for the obvious fix twice, and it is still not built.** Issue #684
(2018): *"P2P is not even needed when you are alone watching a video: in this case the user IP should
remain privately shared only with the Peertube server."* Issue #5493, *"Do not activate p2p if there is
less than X viewers"* (opened 2022-12-30, **still open**): *"you could only activate p2p if you have
more than 10 peers. Furthermore a web server could easily handle this amount of viewers without the
needs of p2p."* That second sentence is the whole argument, written by a PeerTube user four years ago.
(I could not retrieve maintainer replies on either thread — treat the absence of an official threshold
as unverified rather than as a refusal.)

So the feature would be **inert** for the overwhelming majority of Vidra playbacks, while every opted-in
playback pays a 31 KB bundle, a tracker connection, an IP disclosure, and — in small swarms —
a real upload and CPU tax on the viewer.

Where P2P genuinely pays is **live streaming with many concurrent viewers on one clustered playhead** —
which is exactly why PeerTube exposes a live latency-vs-P2P-ratio knob (v4.2.0). That is also the path
Vidra is *least* ready for: live HLS comes out of the nginx-rtmp container as MPEG-TS, bypasses
`internal/media`'s packager entirely, and phase-4 item 7 already flags it as outside the session and
delivery model.

**IPFS is the better-shaped bet on the axis that decides this — but item 5 must not assume public
gateways.** On privacy the difference is categorical: an IPFS gateway is **a server disclosing its own
address**, not a viewer disclosing theirs, so the §3 objection evaporates entirely. And Vidra has
already paid most of the integration cost: an authority-vs-distribution split, a default-deny
eligibility fence, a pin ledger on the lease/SKIP-LOCKED convention, and a fail-open-to-authoritative
redirect the delivery resolver is modeled on.

**But the public-gateway path is being deliberately closed, and video is named as the reason.**
Interplanetary Shipyard, 2026-05-11: *"we have now begun redirecting users who navigate directly to
ipfs.io and dweb.link to inbrowser.link… **If you use public gateways for hot-linking images/videos or
within non-browser applications, please begin migrating to self-hosted or verified alternatives. We
will be rolling out additional rate-limits on the legacy gateways over the course of the year.**"* The
2025 plan behind it is explicit that *"Most IPFS gateway usage today stems from backend services
treating ipfs.io as a free CDN"*, with a phase for *"begin rate-limiting on ipfs.io and dweb.link"* and
429s. The official docs are blunter: *"No. Websites should not rely on the ipfs.io gateway for hosting
of any kind."* The surrounding ecosystem contracted in the same window — Cloudflare's IPFS gateway shut
down 2024-08-14, and **Infura's IPFS API and dedicated gateways shut down on 2026-08-15, one week
before this document.**

Two further constraints item 5 must design around: **HTTP Range is capped at 5 GiB** on the public
gateways (a larger file returns 200 instead of 206 — the player cannot seek), which is an argument *for*
delivering the HLS/CMAF segment tree rather than progressive files; and **verifiability and range
seeking are mutually exclusive** — `entity-bytes` partial retrieval is a CAR feature (IPIP-402), while
`Accept-Ranges` byte ranges are unverifiable, because a partial block cannot be hashed against its CID.
Protocol Labs' own co-authored NSDI '24 paper concludes IPFS *"is well suited to serving delay-tolerant
objects like file hosting, yet struggles with real-time applications such as live video streaming"*,
measuring retrieval ~3× slower than HTTPS. Paid pinning egress runs $15–100/TB against a $0–5/TB CDN
baseline.

None of that changes the P2P verdict — it makes item 5's scope more specific. The realistic shape is
**a self-hosted or paid gateway, segment-granular, behind the resolver's existing fail-open, measured
before it is trusted** — and the §2 digest manifest is what lets the player verify what any third-party
gateway returned.

**The commercial category for public-internet browser P2P is gone, and what survived went to the one
context where the privacy objection does not apply.** The DSN 2024 survey named the entire market —
*"we confirmed three popular PDN providers: Peer5, Streamroot, and Viblast"* — and all three have
since ceased to exist as purchasable products, verified by DNS/HTTP probe on 2026-08-22:
`peer5.com` resolves NOERROR with **no A record** (zone parked on Azure DNS under Microsoft), its final
page having read *"Peer5 is now Microsoft eCDN"*; `streamroot.io` likewise has **no A record**; and
`viblast.com` times out. Lumen — which bought Streamroot in 2019 — announced in October 2023 that it
*"plans to wind down its content delivery services"*, and all four of its mesh-delivery product URLs
now return **404**. StriveCast is listed as deadpooled. There is no EOL notice for Streamroot; the
pages were simply deleted.

What survived is **enterprise eCDN** — Microsoft (ex-Peer5, now bundled into Teams Enterprise, *"up to
98%"* reduction), Hive, Kollective, Ramp. Those are corporate all-hands streams where peers are
colleagues on one LAN, IP addresses are already known to the employer, and the constrained resource is
an office uplink. It is a genuinely good fit, and the opposite of Vidra's situation in every dimension.
Note how much it depends on fleet control: Vimeo's own eCDN documentation states *"it is critical
organizations deploy a browser policy to user devices to disable the IP anonymization features of modern
browsers. Without this browser policy, peering efficiency is limited"* — **a policy a public video site
cannot deploy to anonymous visitors.**

The remaining public-internet vendors are CDNBye/SwarmCloud (hosted signaling, domain registration
required, no license, public release notes 404) and Teleport Media. **No major consumer platform shows
evidence of browser P2P**: nothing found for YouTube, Twitch, Cloudflare Stream or Mux; Netflix's only
public trace is a 2014 job posting that never shipped; Vimeo offers it on Enterprise solely by reselling
Hive and Kollective.

**Two adoption signals are worth more than any argument.** npm downloads for the month to 2026-08-21:
`hls.js` **33,307,359** vs `p2p-media-loader-hlsjs` **9,575** — roughly **one in 3,478 hls.js consumers
(0.03%)** also pulls the P2P engine. And the industry has stopped discussing it: **Demuxed 2025 had zero
of 29 talks on P2P or peer-assisted delivery**, Mile-High Video 2025 had none, and Streaming Media's
P2P coverage stops at a January 2020 piece that is exclusively about enterprise.

One forward-looking constraint, correctly scoped: Chrome has a proposed *"Local Network Access
Restrictions for WebRTC"* feature (Chrome Platform Status id 5065884686876672, status **"Proposed"**, no
milestone assigned) that would gate WebRTC access to local/private addresses behind a permission prompt.
This does **not** block public-internet peering — but it does gate the same-LAN case, which is where
peering is most efficient, and the documented mitigation is an enterprise browser policy. Microsoft's
eCDN docs cite Chrome 146 for WebRTC enforcement; that milestone is vendor-stated, not Chrome-confirmed.

---

## Cost, if it were built anyway

An honest bottom-up estimate, assuming the engine adapter (item 3) and QoE pipeline (item 4) already
exist:

| Work | Estimate |
|---|---|
| Per-segment SHA-256 manifest: generation in the packaging pass, storage layout, serving, compact format, back-catalog backfill for ~2k imported videos | 1–1.5 weeks *(justified independently — see §2)* |
| Go WebTorrent tracker: protocol, in-memory swarms, infohash allowlist from the DB, per-IP + per-IP-per-infohash rate limits, blocked-IP LRU, proxy-correct client IP, metrics, `vidra doctor` check | 1.5–2 weeks |
| STUN answer: ship a curated list *and* an optional self-hosted STUN profile, plus the doc explaining the trade | 2–3 days |
| Player integration: mixin under the unified engine adapter, ABR-seed reconciliation, `httpRequestSetup` replacing the existing `xhrSetup` playback-token path, swarm ID including packaging protocol, validator wiring | 1 week |
| Consent surface: per-instance setting, per-video eligibility fence reusing ipfsmirror's, per-device viewer opt-in, embed hard-off, the plain-language copy, and privacy-transition tests | 1 week |
| Concurrency gate (§3 requirement 6): live per-rendition concurrent-viewer count exposed to the session API, threshold config, and the engage/disengage transition mid-playback. Vidra has no real-time concurrency signal today; PeerTube has never built this (issue #5493, open since 2022) | 1–1.5 weeks |
| QoE: `onChunkDownloaded`/`onChunkUploaded` aggregation, source attribution, admin surfacing | 3–4 days |
| Docs, `vidra doctor`, admin UI, e2e | 3–4 days |
| **Total** | **≈ 6.5–8 weeks**, plus permanent maintenance in the highest-consequence part of the codebase |

Runtime cost is genuinely modest and should not be the argument: `p2p-media-loader-core@4.0.0` +
`-hlsjs@4.0.0` ES builds measure 110,569 + 9,192 bytes minified, **31.1 KB gzipped combined** (measured
from jsDelivr, 2026-08-22); default segment storage is in-memory only
(`segment-storage/segment-memory-storage.ts`, with `customSegmentStorageFactory` opt-in for IndexedDB),
so viewers do not persist other people's content by default. One version-coupling note: v4.0.0's release
notes cite hls.js `^1.7.0` and its devDependency is `^1.7.0`, while Vidra pins `^1.6.16` (resolving to
1.6.19) — PeerTube ships `^4.0.0` against `~1.6.17` in production, so this is a coupling to watch, not a
blocker. hls.js 1.7.1 is current (2026-08-19).

## Fallback discipline (the rule, if it is ever built)

Already satisfied by the library's defaults, and must never be relaxed:

- Peers are **never** a durable source. `internal/delivery` keeps `api-proxy` terminal; a `peer` source
  would sit *above* the resolver as a player-side accelerator, not as an entry in the ordered source
  list, because the resolver's job is minting authoritative URLs and every P2P segment already has an
  HTTP URL it falls back to.
- HTTP wins inside the high-demand window; an in-flight P2P transfer is cancelled for HTTP when capacity
  frees. Do not raise `highDemandTimeWindow` to chase a better ratio — that is trading rebuffers for
  bandwidth, and QoE is the phase's exit criterion, not offload.
- Every peer-supplied byte is validated against the segment digest before it reaches the buffer, and a
  validation failure re-fetches over HTTP and is recorded.
- A stream that fails to register (`onStreamRegistrationError`) loads without P2P; the library already
  guarantees `addStreamIfNoneExists` never throws.
- Tracker unreachable, STUN unreachable, or zero peers must all degrade to exactly today's playback.

## Contribution metrics into QoE (the shape, if it is ever built)

The library exposes precisely what item 4 needs: `onChunkDownloaded(bytesLength, downloadSource,
peerId)` and `onChunkUploaded`, plus `onPeerConnect`/`onPeerClose`/`onPeerError` and
`onSegmentLoaded`/`onSegmentError`/`onSegmentStart`.

Per interfaces.md §9 (event/rollup stream, never Prometheus labels), the playback-session-keyed event
should carry **bytes by source** (`http` vs `p2p`), peer-connect success/failure counts, and
validation-failure counts — and must **never carry `peerId` or any peer address**. Recording peer
identifiers server-side would rebuild, inside Vidra's own database, exactly the viewer-correlation
capability §3 objects to. The admin view is a single ratio per source alongside TTFF and rebuffer
percentiles, which is the same shape item 5's IPFS attempt/outcome measurement needs — build one,
serve both.

## What would have to be true to flip this to BUILD

All three, together:

1. **Sustained concurrency exists.** Telemetry from item 4 shows real instances with a meaningful
   fraction of playback occurring at ≥10 simultaneous viewers on the same rendition of the same title
   — measured, from the QoE pipeline, not assumed. Without this the feature is inert.
2. **Egress is the binding constraint for those instances**, i.e. operators are actually choosing
   between "raise money" and "cap the audience". If the answer is "add a $5 CDN", P2P is the wrong tool.
3. **The privacy story is honest and the audience is right.** The instance is not in the
   sensitive-content threat model, the operator opts in knowingly, the viewer opts in per device with
   the plain sentence in front of them, embeds are hard-off, and the eligibility fence is narrower than
   ipfsmirror's.

Two further conditions would each independently *unblock* rather than trigger:

- The digest manifest exists (it should, via item 5).
- Live delivery is inside the session/delivery model (item 7), since live is where P2P actually pays.

**Not flip conditions:** library health (it is fine), bundle size (31 KB), maintenance risk (real but
manageable), PeerTube parity (parity with a default-on design is not a goal), or "decentralization" as
an aesthetic — Vidra's IPFS path already serves that value without pointing it at viewers.

## What would close it permanently

Record DON'T BUILD, and stop revisiting, if any of these becomes true:

- Item 5 lands and IPFS-plus-CDN delivery meets the QoE bar at acceptable cost. The remaining P2P upside
  is then a rounding error against a standing privacy liability.
- A demonstrated harvesting incident against PeerTube-style swarms (the attack in §3 requires no
  research, only intent), or regulatory guidance treating swarm participation as processing that
  requires explicit consent Vidra cannot meaningfully obtain.
- `p2p-media-loader` loses its maintainer with no successor. There is **no viable second
  implementation**: `augok/p2p-hls` is dormant (22 stars, last pushed 2024-09-27) and
  `cdnbye/hlsjs-p2p-engine` (1,073 stars, pushed 2026-01-19) declares no license and requires
  registering your domain at `dash.swarmcloud.net` for its hosted signaling — a permanent external
  dependency the basic install is not allowed to have. Vidra should not become the second
  implementation itself.

---

## Limits of this research (stated so the next reader does not over-trust it)

- **No proof-of-concept was run against a live PeerTube instance, and no PeerTube-specific harvesting
  incident was found.** The enumeration attack in §3 is assembled from shipping source, the maintainer's
  own description of the technique, and a peer-reviewed demonstration on the same architecture (DSN
  2024) — but nobody has published "here is a PeerTube swarm crawler" or "here is a case where PeerTube
  viewers were harvested". Absence of a reported incident is plausibly explained by audience size and by
  the WS/WebRTC transport not being what existing copyright-troll tooling targets. Neither reason is
  durable, but neither is it evidence of safety. **Treat the attack as a well-founded, partly
  demonstrated capability — not a documented PeerTube event.**
- **No DPA or court has ruled on peer-assisted CDN.** The *Breyer* / *Mircom* / Google-Fonts line is
  applied here by analogy. The ePrivacy Art 5(3) argument in particular is analysis, not authority.
  Also: the LfDI Baden-Württemberg guidance frequently cited as endorsing PeerTube on privacy grounds
  **does not mention P2P at all** and must not be read as approving it.
- **No offload ratio was measured by us.** The (N−1)/N ceiling is arithmetic; the 98% figure is
  PeerTube's own 1,000-browser lab test; vendor claims are vendor claims. Vidra has no telemetry on its
  instances' real concurrency distribution — which is exactly why flip condition 1 is "measure it from
  item 4 first."
- **Beware the secondary literature on this topic.** Specific-sounding offload percentages for
  long-tail VOD circulate verbatim across unrelated sites with no primary source or methodology, and the
  same cluster asserts p2p-media-loader "uses a tracker-less DHT-inspired approach" — which the source
  code flatly contradicts. The directional conclusion here is well supported; those particular numbers
  are not, and none are cited in this document.
- **Chrome's Local Network Access milestone (146) is Microsoft-stated, not Chrome-confirmed**; the
  Chrome feature entry is "Proposed" with no milestone. Lumen's Streamroot wind-down is inferred from
  404s and dead DNS, not from an EOL notice. The `tracker.novage.com.ua` non-response was observed from
  one vantage point.
- The p2p-media-loader behavioral claims (init-segment passthrough, upload-disabled still connecting,
  high-demand HTTP preference, absent default validation, DASH/HLS `externalId` divergence) come from
  reading v4.0.0 at HEAD. They were not exercised in a browser — and note that **v4 is not yet in a
  PeerTube release**, so nobody has field-proven them either.

---

## Sources (fetched/verified 2026-08-22)

**p2p-media-loader** — repo cloned at HEAD (v4.0.0): `packages/p2p-media-loader-core/src/`
(`stream-identity.ts`, `core.ts` defaults :47–93 and swarm resolution :409, `types.ts` `Segment`/
`StreamConfig`/`CoreEventMap`, `hybrid-loader.ts` :330–390 high-demand HTTP preference,
`p2p/loader.ts` :321/:373/:406 upload-disabled behavior, `segment-storage/`,
`webtorrent/webtorrent-client/spec.md` tracker wire protocol);
`packages/p2p-media-loader-hlsjs/src/` (`fragment-loader.ts`, `segment-manager.ts`,
`stream-properties.ts`, `utils.ts`); `packages/p2p-media-loader-shaka/src/segment-manager.ts`
(`SEGMENT_ID_RESOLUTION_IN_SECONDS = 0.5`) and `stream-properties.ts`; `FAQ.md`; `MIGRATION.md`.
<https://github.com/Novage/p2p-media-loader> · releases API · npm registry
`p2p-media-loader-core|-hlsjs|-shaka` · bundle sizes measured from
`https://cdn.jsdelivr.net/npm/p2p-media-loader-{core,hlsjs}@4.0.0/dist/*.es.min.js`.
*Note: `FAQ.md` is stale against v4 — its "same number of variants in the same order" rule describes
v3's index-based identity, which `stream-identity.ts` replaced. Source beat docs here.*

**PeerTube 8.2.4** (`develop`) — `client/package.json`, `package.json`, `config/default.yaml`,
`CHANGELOG.md` (5,195 lines; versions cited inline),
`client/src/standalone/player/src/shared/player-options-builder/hls-options-builder.ts`,
`.../p2p-media-loader/segment-validator.ts`, `.../control-bar/p2p-info-button.ts`,
`server/core/controllers/tracker.ts`, `packages/node-utils/src/p2p.ts`.
<https://github.com/Chocobozzz/PeerTube>

**PeerTube (docs, issues, measurements)** — privacy guide
<https://docs.joinpeertube.org/admin/privacy-guide> (GDPR-if-P2P-disabled claim; "Player P2P" processing
register); <https://docs.joinpeertube.org/use/watch-video> and
<https://docs.joinpeertube.org/api/embed-player> ("Display privacy warning" / `warningTitle=0`);
client strings from `privacy-concerns.component.html`, `player-options-builder.ts:481`,
`user-video-settings.component.html`; `isP2PEnabled()` in `client/src/root-helpers/video.ts`;
`initializers/constants.ts` announce limits; GitHub issues
[#316](https://github.com/Chocobozzz/PeerTube/issues/316),
[#355](https://github.com/Chocobozzz/PeerTube/issues/355),
[#684](https://github.com/Chocobozzz/PeerTube/issues/684),
[#2934](https://github.com/Chocobozzz/PeerTube/issues/2934),
[#4806](https://github.com/Chocobozzz/PeerTube/issues/4806),
[#5493](https://github.com/Chocobozzz/PeerTube/issues/5493) (open);
`webtorrent/bittorrent-tracker` [#271](https://github.com/webtorrent/bittorrent-tracker/issues/271)
(2019-01-21, the maintainer's SDP-offer technique); 1,000-browser stress test
<https://joinpeertube.org/news/stress-test-2023> (2023-12-21); release-vs-develop pin verified from the
`v8.2.4` tag and `develop` `client/package.json`; fork `Chocobozzz/p2p-media-loader` (pushed
2026-08-04).

**Specs** — RFC 8827 *WebRTC Security Architecture* §6.4 (January 2021),
<https://www.rfc-editor.org/rfc/rfc8827.html>; RFC 8826 *Security Considerations for WebRTC* §4.2.4
(January 2021), <https://www.rfc-editor.org/rfc/rfc8826.html>; RFC 8828 *WebRTC IP Address Handling
Requirements* (January 2021), <https://www.rfc-editor.org/rfc/rfc8828.html>;
`draft-ietf-mmusic-mdns-ice-candidates` rev 03 §3.1.2.2 (**never an RFC**; expired 2022-06-09),
<https://datatracker.ietf.org/doc/draft-ietf-mmusic-mdns-ice-candidates/>. IPFS Path Gateway and
Trustless Gateway specs + IPIP-0402 at <https://specs.ipfs.tech/>.

**Research** — Tang, Alowaisheq, Mi, Chen, Wang, Dou, *"Stealthy Peers: Understanding Security and
Privacy Risks of Peer-Assisted Video Streaming"*, IEEE/IFIP DSN 2024, DOI 10.1109/DSN58291.2024.00041,
preprint <https://arxiv.org/abs/2212.02740> (7,740 harvested IPs; 200%-upload-at-3-peers; +15% CPU;
134-site consent audit; Peer5's $500/50TB price). Trautwein et al. (incl. Protocol Labs),
*"Design and Evaluation of IPFS: A Storage Layer for the Decentralized Web"*, NSDI '24,
<https://www.usenix.org/system/files/nsdi24-wei.pdf>.

**Law** — CJEU *Breyer* C-582/14 (2016-10-19); *Mircom* C-597/19 (2021-06-17); *IAB Europe* C-604/22
(2024-03-07); EDPB Guidelines 2/2023 on Art 5(3) ePrivacy (v2.0, adopted 2024-10-07). Applied by
analogy — see "Limits of this research".

**Tracker implementations** — GitHub API metadata for `Novage/wt-tracker` (pushed 2026-06-07),
`greatest-ape/aquatic` (2026-07-13), `webtorrent/bittorrent-tracker` (2026-08-12); npm
`@peertube/bittorrent-tracker-server` 11.1.2 (published 2024-07-31). No mature Go implementation found.

**Alternatives / market** — GitHub API for `augok/p2p-hls` (22 stars, pushed 2024-09-27, Apache-2.0)
and `cdnbye/hlsjs-p2p-engine` (1,073 stars, pushed 2026-01-19, no declared license; registration at
`dash.swarmcloud.net` required). Vendor status verified 2026-08-22 by DNS/HTTP probe: `peer5.com` and
`streamroot.io` NOERROR with no A record, `viblast.com` timing out, four Lumen mesh-delivery URLs 404.
Peer5→Microsoft <https://venturebeat.com/business/microsoft-acquires-peer5-to-beef-up-teams-livestreaming>
(2021-08-10) and Microsoft eCDN
<https://learn.microsoft.com/en-us/microsoftteams/streaming-ecdn-enterprise-content-delivery-network>;
Lumen CDN wind-down PR (2023-10-10); Vimeo Enterprise eCDN browser-policy requirement
<https://help.vimeo.com/hc/en-us/articles/12426939952273-Vimeo-Enterprise-eCDN-overview>; Chrome
Platform Status feature 5065884686876672 ("Proposed") and
<https://learn.microsoft.com/en-us/ecdn/how-to/configure-local-network-access-policy>. Adoption: npm
downloads to 2026-08-21 (`hls.js` 33,307,359 vs `p2p-media-loader-hlsjs` 9,575);
<https://2025.demuxed.com/> (29 talks, none on P2P); Mile-High Video 2025 programme.

**Egress pricing (all fetched 2026-08-22)** — <https://bunny.net/pricing/cdn/>;
<https://developers.cloudflare.com/r2/pricing/>; <https://www.backblaze.com/cloud-storage/pricing>;
<https://docs.hetzner.com/robot/general/traffic/> and <https://www.hetzner.com/cloud/regular-performance/>;
<https://aws.amazon.com/cloudfront/pricing/pay-as-you-go/>. IPFS pinning:
<https://www.pinata.cloud/pricing>, <https://filebase.com/pricing/>,
<https://docs.4everland.org/get-started/billing-and-pricing/pricing-model>.

**IPFS gateway landscape** — <https://ipshipyard.com/blog/2026-ipfs-gateways-redirect-inbrowser-link/>
(2026-05-11, hot-linked video asked to migrate; rate limits coming);
<https://ipshipyard.com/blog/2025-a-post-gateway-world/> (2025-07-23);
<https://docs.ipfs.tech/concepts/public-utilities/> (5 GiB Range cap; "should not rely on the ipfs.io
gateway for hosting of any kind"); Cloudflare gateway shutdown 2024-08-14
<https://blog.cloudflare.com/cloudflares-public-ipfs-gateways-and-supporting-interplanetary-shipyard/>;
Infura IPFS shutdown 2026-08-15 <https://discuss.ipfs.tech/t/20300>.

**Vidra** — `vidra-core/internal/media/cmaf.go` (segment naming, `-seg_duration 6`),
`internal/media/hls.go` (`hlsSegmentSeconds = 6`), `internal/mediahash/service.go` (HLS segments
explicitly out of scope), `internal/delivery/{delivery,resolver}.go` (`SourceKind`, api-proxy terminal),
`internal/ipfsmirror/classes.go` (default-deny privacy fence), `internal/playersettings/service.go`,
`vidra-user/lib/use-hls-playback.ts` (hls.js construction, `abrEwmaDefaultEstimate`),
`lib/device-preferences.ts`, `lib/embed-privacy.ts`, `vidra-user/package.json` (`hls.js ^1.6.16`);
npm `hls.js` latest 1.7.1 (2026-08-19).
