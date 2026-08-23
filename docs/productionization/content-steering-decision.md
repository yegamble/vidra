# Decision: standards-based content steering (multi-CDN)

**Status:** Decided 2026-08-23 · **Phase:** 5, item 2 (the research half)
**Evidence:** primary-source reads of `draft-pantos-content-steering-05` (18 May 2026) and
`draft-pantos-hls-rfc8216bis-22` (1 May 2026) fetched from the IETF archive; ETSI TS 103 998
V1.1.1; the shipped `hls.js@1.6.16` TypeScript in `vidra-user/node_modules` **and** upstream master
at `afe5b8bf` (≡ v1.7.1) — the controller's behaviour on `VERSION`, on 410, on 429, on a
pathway-id mismatch and on a missing `STABLE-RENDITION-ID` is documented nowhere but the source;
Apple's WWDC21/WWDC22 transcripts, developer-forum threads, HLS Authoring Specification and the
(stale) hosted steering PDF; and reads of `vidra-core`'s playlist rewrite, delivery resolver, CDN
provider, storage-key generation scheme and QoE classifier at HEAD. Every claim about Vidra's code
was read out of the tree and is cited by line. Every third-party claim carries a source. What could
not be verified — which for Apple's client is nearly everything that matters — is in
"Limits of this research".

## Decision

**BUILD — but not first, and not before four prerequisites, three of which are gaps in work phase 4
already shipped.** HLS Content Steering is the right standard and it fits Vidra's architecture
almost suspiciously well: the Multivariant Playlist is already rewritten per request at the origin
(`serveHLSPlaylist` → `rewritePlaylistReferences`, `internal/httpapi/hls.go:221-241, 319-353`),
which is a live injection point; hls.js 1.6.16 is already shipped in `vidra-user` and implements
the whole client half, so **the client-side cost of the feature is zero**; the QoE beacon already
reports the final fetch URL of every fragment, so **per-pathway measurement needs no client change
either**; and the feature is provably invisible to an install that has not configured two edges.
It also costs the viewer nothing — no new exposure, no third-party connection, one extra request to
the operator's own origin — which is what makes this a BUILD where phase-4 item 6 was a DEFER.
Against that: the value is proportional to the number of CDNs an operator runs, which for Vidra's
target install is zero or one; the standard is **not an RFC and has no RFC number**; Apple's
implementation of the one mechanism the design depends on is *unverified by anybody*, with the only
two public field reports being failures; no CDN vendor documents the feature as a product and no
named operator has published a production deployment; and steering pushes variant playlists onto
edges Vidra today can neither version nor purge — a correctness gap that already exists in the
shipped CDN path for *segments* and that must be closed before it is widened.

Concretely:

1. **Phase 5 item 2's research half is closed by this document.** The build half is scheduled behind
   item 1 (multi-CDN configuration and per-pathway measurement), which is where its real
   prerequisites live.
2. **Shape: pathway cloning** — one declared pathway in the playlist plus `PATHWAY-CLONES` carrying
   `PER-VARIANT-URIS`/`PER-RENDITION-URIS` — because Vidra's origin is route-addressed and its edges
   are key-addressed, and because it is the only shape that leaves a non-steering client's ladder
   untouched (§D1).
3. **Four prerequisites, all independently justified** (§Sequence): generation-addressed HLS keys,
   `Purge` call sites plus a prefix-purge form, multi-CDN configuration, and the QoE pathway
   dimension. Two of them are open phase-4 carry-forwards, not steering groundwork.
4. **An empirical test is a deliverable, not a follow-up.** No published source anywhere reports
   having tested `PER-VARIANT-URIS` against AVPlayer or Safari — not Apple, not a CDN vendor, not an
   independent engineer — and the two public reports of pathway cloning on iOS 16.2 are both
   failures (§F3). The iPhone branch of Vidra's player is native HLS, so this is not academic.
5. **DASH steering is not deferred for the reason the phase doc assumes.** It is not merely blocked
   on a DASH client (item 3c): DASH's steering standard *explicitly excludes* the per-variant URI
   replacement Vidra's addressing mismatch requires (ETSI TS 103 998 clause 7 step 13), and the MPD
   is served verbatim with no rewrite path. **DASH steering is structurally unavailable to Vidra's
   current topology even after Shaka lands** (§F5).
6. **The minimal first slice contains no steering at all** (§Sequence).

---

## Findings

### F1. The standard moved, and it is not an RFC

The steering-manifest format is **no longer defined in `draft-pantos-hls-rfc8216bis`**. It was
split out between bis-16 (Nov 2024, the last revision with the JSON inline) and bis-17 (Feb 2025)
into a separate, delivery-protocol-neutral draft. The current pair, both fetched 2026-08-23:

| Document | Rev | Date | Status |
|---|---|---|---|
| `draft-pantos-content-steering` — *Pathway-based Content Steering*, Pantos & Vershen (Apple) | **-05** | 18 May 2026 | ISE stream, Informational; at the RFC Editor, **no RFC number assigned** |
| `draft-pantos-hls-rfc8216bis` | **-22** | 1 May 2026 | ISE; "Sent to the RFC Editor"; describes protocol version 13 |

- steering-05 §§: 3 CDP Responsibilities, **4 Steering Manifest**, **5 Pathway Cloning**, 6 Steering
  Query Parameters, **7 Steering Client Responsibilities** (the normative error algorithm),
  11.1 IANA media type.
- bis-22 §§: **4.4.6.6** `EXT-X-CONTENT-STEERING`, **7** Content Steering (7.1 mapping, 7.2 manifest
  → defers to steering-05, **7.3 Pathway Cloning + the HLS-only extensions**, 7.4 query parameters,
  7.5 client responsibilities), examples at 9.12/9.13.
- The draft states its own standing: *"This informational specification is not an Internet standard…
  It was developed by Apple Inc."* Pantos' IETF-124 MOPS slides (Nov 2025) say only *"Plan to
  publish as an RFC."*
- **A false citation is circulating: content steering is *not* RFC 9512** (that number is the
  `application/yaml` media type). Cite the drafts by revision.

**Media type:** `application/vnd.apple.steering-list`, IANA-registered (steering-05 §11.1), file
extension `.json`. Serve it.

**No `EXT-X-VERSION` gate.** bis-22 §8 lists no protocol-version requirement for
`EXT-X-CONTENT-STEERING`, `PATHWAY-ID`, `STABLE-VARIANT-ID` or `STABLE-RENDITION-ID`. Vidra's CMAF
master stays `#EXT-X-VERSION:7` and its MPEG-TS master stays `:4` (`internal/media/cmaf.go:1142`,
`packager.go:858`). This was a live risk — the rewrite would have had to bump a stored value — and
it is closed.

### F2. The manifest format, and the failure semantics that constrain the endpoint

`#EXT-X-CONTENT-STEERING` (bis-22 §4.4.6.6): *"It MUST NOT appear more than once in a Multivariant
Playlist."* `SERVER-URI` is REQUIRED. `PATHWAY-ID` is OPTIONAL, and its definition is
load-bearing for §D3 below:

> "The value is a quoted-string that identifies the Pathway that MUST be applied by any client that
> supports Content Steering … until the initial Steering Manifest has been obtained. **Its value MUST
> be a legal Pathway ID … that is specified by the PATHWAY-ID attribute of one or more Variant
> Streams in the Multivariant Playlist.**"

A Variant Stream with no `PATHWAY-ID` belongs to the default Pathway `"."` (§4.4.6.2). Pathway-ID
charset is `[a-z][A-Z][0-9] . - _`. `STABLE-VARIANT-ID` charset is `[a-z][A-Z][0-9] + / = . - _`,
matched *"using a byte-for-byte comparison"*.

The manifest JSON (steering-05 §4): `VERSION` REQUIRED (*"A Client MUST refuse to use Steering
Manifest if the VERSION is missing or the VERSION number is unrecognized"*); `TTL` **REQUIRED**,
*"recommended value is 300 seconds"*, and the server *"MAY vary the TTL per Client to distribute
server load"*; `RELOAD-URI` OPTIONAL and may be relative; `PATHWAY-PRIORITY` REQUIRED, *"MUST
contain at least one Pathway"*, no duplicates, and *"Clients MUST ignore unrecognized Pathway IDs"*;
`PATHWAY-CLONES` OPTIONAL, each with `BASE-ID`, `ID` (*"MUST NOT match any other Pathway ID"*) and
`URI-REPLACEMENT`. The core draft's `URI-REPLACEMENT` has **only** `HOST` and `PARAMS`.

**The HLS-only extension — the mechanism this whole design turns on** (bis-22 §7.3, verbatim):

> "The Pathway Clone object is defined by the Pathway Cloning section of [Content-Steering], **with
> the addition that the URI-REPLACEMENT object can contain PER-VARIANT-URIS and PER-RENDITION-URIS.
> These keys are defined for Steering Manifest VERSION 1 and onward.**"

Keys are `STABLE-VARIANT-ID` / `STABLE-RENDITION-ID` strings; values are *replacement absolute
URIs*; and *"performing URI replacement in steps 5 and 6 will supersede changes made in step 4"*
(step 4 being HOST+PARAMS). So a per-variant URI is used verbatim — **which is exactly what a
route-addressed origin and a key-addressed edge require.**

**Query parameters** (bis-22 §7.4): the client *SHOULD* add `_HLS_pathway="<CURRENT-PATHWAY-ID>"`
and `_HLS_throughput=<bits per second>`. bis-22 newly reserves the `_HLS_` prefix and adds:
*"HTTP proxy caches SHOULD be configured to exclude highly variable query parameters such as
`_HLS_throughput` from their cache keys, or treat the Steering Manifest response as
non-cacheable."*

**The client error algorithm** (steering-05 §7 step 7) is what pins the endpoint's contract:

- **410 Gone** — *"it MUST NOT issue another request for that URI for the remainder of the session.
  It MAY continue to use the most-recently obtained list of Pathway priorities."*
- **429 + `Retry-After`** — *"it SHOULD wait until the time specified by the Retry-After header to
  reissue the request."*
- **everything else** (unreachable, 5xx, timeout, malformed) — *"the Client SHOULD continue to use
  the previous values and attempt to reload it after waiting for the previously-specified TTL. If no
  Steering Manifest has been successfully parsed, a TTL of 5 minutes SHOULD be used."*

**Playback is never blocked on steering.** Pathway penalization is triggered by *media* failure
only (step 3: *"If all the URIs from the current Pathway fail with a network error…"*), and
bis-22 §7.5 recommends *"For HLS, a two minute penalization period."*

One more constraint worth stating before the design, because it prices shape B honestly:
steering-05 notes that the first element of `PATHWAY-PRIORITY` *should* agree with the Content
Description's initial Pathway, precisely to avoid a startup redirect.

### F3. Apple / native HLS — the evidence is thin, and what exists is negative

This matters because Vidra's iPhone branch is MSE-less native HLS (`lib/player-engine.ts`, the
`native-hls` engine).

**Which OS version.** Apple's own sources contradict each other three ways: a DTS engineer
(forum thread 696538, Dec 2021) says *"introduced at WWDC 2021, so it's available with iOS/tvOS 15
and above"*; a Media Engineer (thread 721338, Dec 2022) says *"**I believe** the first iOS version
that supported pathway cloning was iOS 15.4 — I am not sure about Safari support"*; Pantos' IETF-124
deck (Nov 2025) says *"Offered in iOS 16 (2022) and onwards."* iOS 15.4 predates bis-11 (11 May
2022), the first published text for pathway cloning. **No macOS/Safari version floor has ever been
stated by Apple**, and the question was asked directly in thread 721338 and never answered.

**Safari's steering is AVFoundation's.** The WebKit tree contains zero references to
`CONTENT-STEERING`, `contentSteering` or `_HLS_pathway` (controls: `"EXT-X-"` → 64 hits, `"m3u8"` →
82). There is no open-source path to inspect Safari's behaviour.

**Does AVPlayer implement `PER-VARIANT-URIS`?** The strongest positive evidence is WWDC22 session
10144, *Deliver reliable streams with HLS Content Steering*, presented by Apple's **AVFoundation
team**, which introduces the fields with a worked example. Three counter-signals:

1. Apple never states "AVPlayer supports X" — no availability annotation, no documentation page, no
   release note.
2. **Pantos' own Nov 2025 deck omits them**, describing cloning as only *"Replace hostname… Replace
   query parameters."*
3. **Apple's canonical hosted steering document is pre-cloning.** `HLSContentSteeringSpecification.pdf`
   is still served (Last-Modified 30 Jan 2026) as *"v1.2b1 Preliminary, © 2020-2021"* and contains
   **zero occurrences** of `PATHWAY-CLONES`, `URI-REPLACEMENT`, `BASE-ID` or `PER-VARIANT-URIS`.
   Anyone who reads Apple's own steering spec today gets a pre-WWDC22 document.

**And the only two public field reports of cloning against Apple's client are failures**, both from
the same developer on iPhone iOS 16.2 in Dec 2022. Thread 722145: a minimal `HOST`-only clone
produced `CoreMediaErrorDomain -15881 "Content Steering: error in handling Steering Manifest,
ignoring and continue playback"` and the player never requested the cloned host; Apple's engineer
diagnosed an unrecognized pathway id in `PATHWAY-PRIORITY`, which the spec says clients MUST ignore,
and removing it did not fix it. Thread 721338, separately: *"I can switch between pathways defined
in the manifest file, but when I try to clone a pathway and introduce a new pathway id my stream
stops."* No resolution, no radar, no follow-up in the three-and-a-half years since.

Note carefully what that second report says: **the thing that worked on Apple's client was
switching between pathways declared in the Multivariant Playlist; the thing that broke was
cloning.** That is the single strongest argument for shape A in §D1, and it is one data point from
one person on one OS build.

**Every industry paper claiming AVPlayer support cites Apple's marketing page, not a test.**
Reznik et al., *Implementing HLS/DASH Content Steering at Scale* (IBC 2023, Brightcove), asserts
*"Content Steering is already supported by the AVplayer framework"* with a citation to
`developer.apple.com/av-foundation/`; its own 4-scenario experiment instrumented *"HLS.js and
DASH.js"* — **AVPlayer and Safari were never in the test matrix.**

**Where the evidence *is* solid, and it is the part that matters most.** Base steering — pathway
grouping, priority switching, and falling back to the Multivariant Playlist's declared order when
the steering server is unreachable — is spec-mandated, Apple-confirmed since iOS/tvOS 15, and
independently reported working in the same forum thread that reports cloning broken. Even the
410-on-the-first-request case is specified to keep working: the client *"SHOULD create a priority
list from the Pathways in the Content Description, with the initial Pathway, if any, as the highest
priority"* (content-steering-05 §7). **The evidence collapses precisely at pathway cloning**, which
is the mechanism Vidra's addressing mismatch forces it to use — see the failure-mode asymmetry in
§D1 for why that is survivable.

On Safari specifically, the closest thing to an answer Apple has given is a hedge from a Systems
Engineer in thread 696538 (Jun 2022): *"Content steering **should be** available in Safari when
playing HLS via the native video element. If you're using an MSE-based HLS player you'll need to
implement Content Steering yourself."* No version, and the direct macOS question in thread 721338
was never answered.

Three Apple facts that *are* clear and useful:

- **HLS Authoring Specification for Apple Devices, rule 9.18** — its only steering mention:
  *"An `EXT-X-CONTENT-STEERING` tag SHOULD always have a `PATHWAY-ID` attribute."*
- **Offline/download steering** ("What's new in HTTP Live Streaming 2023") requires
  *"consistent stable IDs for all variants and renditions"* and that *"renditions with matching
  stable IDs … have bit-for-bit identical media segments."* Vidra satisfies the second condition by
  construction: every pathway serves **the same stored objects** through a different host. The same
  document warns that during a download *"a failure to fetch a specific file terminates the
  download, rather than causing a switch to an alternate pathway"* — steering does not make offline
  downloads resilient, it only re-prioritizes them.
- **Apple's own warning about the startup redirect**, which prices §O-d5 directly:
  *"it is important for the Master Playlist and the preferred Pathway of the initial Steering
  Manifest to agree. Immediately redirecting a player to a different Pathway on startup will delay
  playback and increase network utilization."*

### F4. hls.js — what the shipped client actually does

Read from `vidra-user/node_modules/hls.js@1.6.16/src/controller/content-steering-controller.ts` and
cross-checked against upstream master `afe5b8bf` (≡ v1.7.1). Steering landed in **v1.4.0**
(2023-04-11, PR #5191) and is **present in both the full and the `light` bundle** (verified by
grepping `dist/hls.mjs` and `dist/hls.light.mjs` for `_HLS_pathway` and `PATHWAY-CLONES` — one hit
each). `vidra-user` imports the default entry, so steering is live today.

- **`URI-REPLACEMENT` is only ever applied to `PATHWAY-CLONES`.** `performUriReplacement`
  (lines 589-621) is called from `clonePathways` (line 365) and `cloneRenditionGroups` (line 574),
  both reachable only from the `PATHWAY-CLONES` branch (line 487). All four forms are implemented;
  matching is an exact key lookup on `STABLE-VARIANT-ID` / `STABLE-RENDITION-ID` with **no
  positional fallback** (lines 601-606).
- **`_HLS_pathway` and `_HLS_throughput` are sent on every non-`data:` steering request**
  (lines 432-437), with `throughput = (hls.bandwidthEstimate || config.abrEwmaDefaultEstimate) | 0`.
  hls.js sends the pathway id **unquoted**, where the spec's ABNF shows it quoted.
- **The `SERVER-URI` is resolved against the playlist URL at parse time**
  (`m3u8-parser.ts:203-207`, `M3U8Parser.resolve(…, baseurl)`), so a relative `SERVER-URI` is safe.
- **Failure handling** (lines 501-538): 410 → `enabled = false` permanently (spec-conformant);
  every other error or timeout → reschedule at TTL, playback continues on the current pathway.
  Load policy is `maxTimeToFirstByteMs: 10000`, `maxLoadTimeMs: 20000`, one error retry, two timeout
  retries (`config.ts:527-543`). **The steering server is not a single point of failure for
  playback** — only for steering.
- **Two deviations that constrain the endpoint's contract, both present since v1.4.0 and still
  present in v1.7.1:**
  - **429 is fatal to steering.** The 429 branch reads `Retry-After` into a local `ttl` and then
    `return`s without calling `scheduleRefresh` (lines 517-527) — the value is dead code, and
    `stopLoad()` has already nulled the loader the header is read from. One 429 ends steering for
    the session. The spec says the client *SHOULD* retry after `Retry-After`.
  - **A wrong `VERSION` silently ends the refresh loop.** Lines 463-466 log and `return` **before**
    `scheduleRefresh`.
- **Pathway penalty is 5 minutes, hard-coded** (`PATHWAY_PENALTY_DURATION_MS = 300000`, line 50),
  against the 2 minutes bis-22 §7.5 recommends for HLS. Not configurable.
- **A single-entry `PATHWAY-PRIORITY` disables error-driven failover** — the ERROR handler requires
  `pathwayPriority.length > 1` (line 216). Relevant to the kill-switch design (§O-d4).
- **No `Hls.Events.ERROR` is raised for steering failures** — logger output only. An application
  cannot observe steering breakage through the event API, which means Vidra cannot beacon it.
- **Redundant streams get pathways for free.** Even with no steering server, duplicate
  `EXT-X-STREAM-INF` entries with no `PATHWAY-ID` are assigned `"."`, `".."`, `"..."` and handed to
  the same penalty-box machinery (`level-controller.ts:167-176`). Plain HLS failover between two
  CDNs needs **no steering server at all** — see §Go/no-go.
- **Version hazard for Vidra:** `package.json` pins `"hls.js": "^1.6.16"`, which will never resolve
  to 1.7.x. **v1.7.0 fixed three URI-REPLACEMENT bugs** that 1.6.16 still has: `url.host = host`
  clobbers a non-default port (#7655); `PARAMS` was applied *on top of* a matched per-variant URI in
  violation of the supersede rule (#7710); and `URLSearchParams` re-serialization percent-encoded
  `~ = /`, **breaking signed CDN tokens** (#7969 — *"Signed CDN tokens carry those characters
  verbatim and are validated byte-for-byte"*). None of these bite the MVP, which uses neither
  `PARAMS` nor ports nor signed edge URLs, but **the version bump belongs in the same slice as the
  feature.**

### F5. DASH steering — blocked by more than a missing client

**ETSI TS 103 998 V1.1.1 (2024-01)**, *"DASH-IF: Content Steering for DASH"*, is the published
standard (the DASH-IF community-review draft CTS 00XX v0.9.0 of 2022-07-10 is superseded). Its
clause 6.1 NOTE says the design is *"intentionally similar to that defined by [1] section 7.1 for
HLS for the purposes of interoperability"*, and the field names are identical: `VERSION`, `TTL`,
`RELOAD-URI`, `PATHWAY-PRIORITY`, `PATHWAY-CLONES`. (An earlier draft used
`SERVICE-LOCATION-PRIORITY`; the rename to `PATHWAY-PRIORITY` landed by draft 0.9.7, and only legacy
players such as video.js still read both.) So **one JSON body can serve both HLS and DASH clients**,
distinguished by `_HLS_*` versus `_DASH_*` query parameters — which is a genuinely nice property, and
irrelevant to Vidra for the reason below.

**The blocker is not the client. It is the mechanism.** ETSI clause 7 step 13 has DASH clients
*"ignore … any URI-REPLACEMENT.PER-VARIANT-URIS and PER-RENDITION-URIS objects"* — those are HLS-only
extensions. DASH cloning is `HOST` + `PARAMS` only, and Shaka's README narrows it further:
*"Content Steering features not supported: PATHWAY-CLONES other replacements than HOST"* (no
`PARAMS`). **A hostname swap cannot bridge Vidra's route-addressed origin to its key-addressed
edge** (§D1). So even with Shaka shipped (item 3c), DASH steering would be unavailable to Vidra's
topology.

**And DASH's failure mode is harsher than HLS's.** Where an HLS client keeps playing whatever it has,
ETSI clause 7 specifies that if the MPD's `serviceLocation` values no longer intersect
`PATHWAY-PRIORITY`, the client reloads once more after the TTL and then *"the DASH client shall
terminate playback."* A steering server that drifts out of sync with its own manifests stops DASH
playback outright. Worth knowing before anyone treats HLS and DASH steering as the same feature.

Two further blockers, for completeness: `<ContentSteering>` is an **MPD element** (child of `MPD` or
`ServiceDescription`, with `@defaultServiceLocation`, `@queryBeforeStart`, `@clientRequirement`;
`@proxyServerURL` was a draft-only attribute and is **not** in the published standard), and Vidra's
MPD is served **verbatim** — `serveCMAFManifest` deliberately does not rewrite it, because
`SegmentTemplate` patterns are not URIs. There is no injection point, and baking a per-instance
steering URL into the stored MPD would poison an object that the IPFS mirror treats as content.

**Player support, for the record:** Shaka 4.6.0 (2023-11-16) implements steering for *both* DASH and
HLS; dash.js 4.5.0 (2022-09-28) against the old draft, modern syntax from 4.7.0; ExoPlayer/media3
1.11.0 (2026-08-05) for HLS including cloning, DASH slated for 1.12.0. **DASH steering is deferred
without loss, and for a better-stated reason than the phase doc gives.**

### F6. Vendor and industry conventions — thinner than the marketing suggests

**The CDN vendors have published nothing.** Searches of `techdocs.akamai.com`, `akamai.com/blog`,
`docs.fastly.com`, `developer.fastly.com` and `fastly.com/blog` found **no Akamai or Fastly product
documentation or blog post on HLS/DASH Content Steering** (2026-08-23). For AWS the negative is
stronger than a search result: the MediaPackage v2, MediaPackage v1 and MediaTailor user guides were
downloaded as PDFs and text-grepped — **zero occurrences of "steering" in all three**. MediaPackage
v2's HLS tag list (PROGRAM-DATE-TIME, START, SESSION-KEY, DATERANGE, PART, PRELOAD-HINT,
SERVER-CONTROL) does not include `EXT-X-CONTENT-STEERING`, and the DASH page has no
`ContentSteering` element. **No packager Vidra might be compared against emits the tag either.**
The AWS multi-CDN blog everyone cites (Souk, 2020-02-06) predates the standard and describes a
Lambda@Edge + DynamoDB URL dispenser.

The vendors' actual role in the record is as **substrates**: Akamai EdgeWorkers, AWS Lambda@Edge and
Fastly Compute@Edge are where other people's steering servers run. Akamai's participation is via
Will Law as co-author of the standard's canonical papers, not as a product.

**The one productization** is broadpeak.io's Content Steering beta (2024-08-20), whose framing is
the most useful sentence in the vendor corpus: the standard *"is an open-ended protocol as it does
not explain how traffic should be steered … Those considerations are usually part of the business
logic layer, which sits on top."* Priority computation is explicitly the operator's problem.
**Bitmovin does not support steering at all** (*"something which we're looking into but we don't
currently have a timeline"*, Bitmovin forum, 2025-04-08).

**TTL — and the finding that changes one of Vidra's numbers.** 300 s is both specs' recommendation
(Apple v1.2b1 and ETSI §6.3 use nearly identical wording, and both permit varying TTL per client
*"to distribute server load"*) and hls.js's pre-manifest default. But every serious implementation
drives it *down*, because **TTL is a function of what the priority depends on.** Reznik et al.
(IBC 2023), verbatim: *"While 300 seconds (5 minutes) may be adequate for essential load balancing
and CDN commit management tasks, it is inadequate for … QOS/QOE optimizations or rapid enough
failover … When clients start buffering, directing them to another CDN 5 minutes later is too
late!"* Their rule of thumb is a TTL *"shorter than the size of the player's buffer (e.g., 10-30
seconds)"*; their production-shaped Fastly deployment used **10 s**; einbliq.io documents 30 s
dropping to 10 s during re-balancing. The same paper gives the counter-pressure: *"with 300 seconds
TTL … 6M concurrent viewers … at least 20K requests per second."*

**Per-asset versus global.** The spec is agnostic and explicitly sanctions the per-asset form —
Apple: `SERVER-URI` *"MAY contain an asset identifier if the steering server requires it"*, with the
example `/steering?video=00012`. The dominant *published* architecture is the opposite: a global
two-tier system (a central master recomputing regional allocation every ~10 minutes, stateless edge
functions answering every TTL poll with all session state carried in the `RELOAD-URI` query string).
Note for an open-source project: that two-tier design is claimed in **US Patent 12,477,189**
(Brightcove). Vidra's stable-per-video path with server-side priority is the *other*,
spec-sanctioned shape and does not resemble it.

**Pathway naming — no convention exists.** Apple's examples use `CDN-A`/`CDN-B`; ETSI, dash.js
reference content and Fraunhofer use `alpha`/`beta`; the Brightcove/SVTA demo used
`cdn-a`/`cdn-b`/`cdn-c`; Apple's WWDC21 examples are geographic (`CN`, `JP`, `SG`).

**Caching.** bis-22 §7.4 is the only explicit CDN-configuration rule in the corpus: strip highly
variable parameters such as `_HLS_throughput` from cache keys *"or treat the Steering Manifest
response as non-cacheable."* Relatedly, the sharpest published criticism of steering is a caching
one — Pillsbury (Mux), Demuxed 2025: steering polling plus parameterized URLs *"inherently and
literally remove browser cache from the equation"*, a *"hidden performance tax of 2x network
requests."* That critique targets `URI-REPLACEMENT.PARAMS`, which mints per-session URLs. **Vidra's
design uses `PER-VARIANT-URIS` only — stable per pathway, not per session — so the cache tax does
not apply**, and that is worth keeping as an explicit constraint rather than an accident.

**Published failure modes with evidence** (Kara & Simon, MHV'25 doi 10.1145/3715675.3715790 and
MHV'26 doi 10.1145/3789239.3793279):

- **The recovery problem:** *"how to get informed about the recovery of a faulty CDN if no users are
  downloading from it?"* Naive strategies are measurably brutal — a "Unlucky Sacrifice" approach
  (which the paper says *"many service providers are unfortunately implementing"*) subjected one
  client to up to **32 consecutive rebufferings**; buffer-aware rotation detects recovery in <10 s,
  stateless random probing in <20 s. See open problem (e).
- **Thundering herd via TTL collapse:** setting TTL near the player's buffer means the sickest
  clients poll hardest exactly during an incident.
- **Cross-pathway consistency is an operational precondition:** switching requires *"consistent
  cache key construction and compatible tokenization or URL-signing across"* pathways, post-switch
  ABR throughput estimates go stale, and DRM licenses *"may require re-validation … when the
  delivery endpoint changes"* — the last being a live constraint on phase-5 items 4-7. The advice is
  to *"limit the rate of pathway changes per session and always advertise viable fallback pathways."*
- **A cloning-specific client bug:** hls.js #6759 (2024-10-07, fixed by #6760) — pathway-clone
  bookkeeping desync silently migrated traffic to the *low*-priority pathway with no errors raised.
  Cloning is the less-travelled path in hls.js too.

**Measurements exist; field deployments do not.** The headline numbers all come from one lab
testbed: Reznik et al. IBC 2023 (2-CDN throttled A/B: DASH buffering 80.1 s → 21.1 s, bitrate
784 → 4,327 kbps) and MHV'25/SMPTE MIJ 134(1) 2025 (3 anonymized tier-1 CDNs on Fastly
Compute@Edge, TTL 10 s, >5,000 synthetic sessions: global buffering ratio 0.03% steered vs 0.42%
for the best single CDN; India 0.14% vs 1.81%). **No named operator — Disney+, Peacock, Paramount+,
DAZN, Sky, Netflix, Prime Video — has published an attributable account of running standard content
steering in production.** The trade press concedes it: *"These are still early days for content
steering, and some operators are still seeking clear evidence that it delivers on its promise"*
(The Broadcast Bridge, 2025-05-02). The public demo estate is dead: `akamai.content-steering.com`'s
certificate expired 2025-07-23 and the origin bucket returns `NoSuchBucket`, and
`svta.content-steering.com` no longer resolves (both checked 2026-08-23).

**CMCD is not a prerequisite and is not part of the standard.** CTA-5004-A (CMCD v2, Feb 2026) and
CTA-5006 (CMSD, Nov 2022) were both fetched in full: **zero occurrences of "steering" in either.**
The CMCD-drives-steering linkage exists only in conference material and vendor practice. Vidra emits
no CMCD and does not need to.

**Reference implementation, if one is wanted:** the SVTA's "Content Steering at Edge" (manifest
updater + stateless steering server, Apache-2.0). The canonical SVTA repo is members-only; a public
copy is `github.com/merongithub/content_steering_at_edge`.

---

## Design — what Vidra would actually build

### D1. Three shapes are possible; only one keeps a non-steering client unharmed

The framing "PER-VARIANT-URIS **versus** pathway cloning with URI-REPLACEMENT" describes a choice
that does not exist. Per bis-22 §7.3, `PER-VARIANT-URIS` is a field *of* a Pathway Clone's
`URI-REPLACEMENT` object, and hls.js reaches it only through `clonePathways` (§F4). **`PER-VARIANT-URIS`
*is* pathway cloning.** The real choice is:

| | Shape | Multivariant Playlist | Steering manifest |
|---|---|---|---|
| **A** | Sibling pathways | every variant listed **once per pathway**, each with its own absolute URI and `PATHWAY-ID` | `PATHWAY-PRIORITY` only |
| **B** | Cloning | today's ladder + one `EXT-X-CONTENT-STEERING` line + `PATHWAY-ID` + `STABLE-VARIANT-ID`/`STABLE-RENDITION-ID` | `PATHWAY-CLONES` carrying `PER-VARIANT-URIS` / `PER-RENDITION-URIS` |
| **C** | Route-addressed edges | today's ladder + the tag | `PATHWAY-CLONES` with cheap `HOST`-only replacement |

**Why the addressing mismatch rules out the cheap form.** The edge URL is
`base + "/" + objectKey` (`internal/cdn/cdn.go`, `EdgeURL`) — e.g.
`https://cdn.example/streaming-playlists/<uuid>/cmaf/media_0.m3u8` — while the origin addresses the
same bytes by route: `/api/v1/videos/{id}/hls/cmaf/media_0.m3u8`. hls.js's `HOST` replacement is
`url.host = host` (line 609): host only, path preserved. A `HOST` swap of a route-addressed URI
produces a route-addressed URI at a key-addressed edge, which 404s — and, as `internal/cdn`'s own
package comment observes, *"a 404 from a third-party edge is indistinguishable from a cold cache"*,
so the failure presents as a CDN that is merely slow to warm. **Full explicit per-variant URIs are
required.** (Imported PeerTube trees have the same mismatch in a different spelling: the route is
`/hls/peertube/<file>` and the key is `streaming-playlists/hls/<source-uuid>/<file>`.)

**Shape A is rejected — it damages every client that does not implement steering.** hls.js
de-duplicates variants on a key that leads with the pathway id (`level-controller.ts:157-158`), so
two variants with distinct `PATHWAY-ID`s are two different levels; the only thing that hides the
inactive pathway is `filterParsedLevels` (`level-controller.ts:331-332`), which runs **only when a
steering controller exists**. A client without steering sees the ladder N times: N× variants for
ABR to choose between, N× master size, and — on Safari, where variant choice is driven by the
`SCORE` attribute Vidra deliberately emits (`cmaf.go`, `cmafVariantScore`) — N variants at
identical `SCORE`.
The cost is worse for Vidra than for a typical deployment because the CMAF ladder is
multi-codec: a 5-rung, three-codec ladder is already 15 `EXT-X-STREAM-INF` entries, and shape A
with two CDNs makes it 45.

**Shape A's one real argument, stated honestly:** the only public report of *anything* steering-shaped
working on Apple's client is playlist-declared pathway switching (§F3), and the only reports of
cloning are failures. If empirical testing shows AVPlayer still cannot clone and an operator needs
the iPhone branch steered, A is the fallback. It should be a documented escape hatch, not the default.

**Shape C — the one clean escape — exists only under a different topology.** Point the CDN at the
*Vidra API* origin rather than the object store and everything gets easier: `HOST` replacement
works, `?v=` survives end to end because the origin renders the playlist and the edge caches the
rewritten bytes, and purge is by URL. It is also **phase-5 item 3 (origin shielding), not item 2**:
it puts every segment byte back on the Go byte path behind a shield, it needs a second CDN
configuration shape, and `internal/cdn` states flatly that pointing `BaseURL` at the API origin
*"does not work and cannot be made to work here."* Record it as a supported alternative deployment
for operators who run a shield — under which steering becomes nearly free, and under which DASH
steering also becomes possible (§F5).

**Decision: shape B.** The stored objects do not change at all, and the *served* Multivariant
Playlist gains, for a steering-enabled install only:

- one `#EXT-X-CONTENT-STEERING:SERVER-URI="steering.json",PATHWAY-ID="VIDRA-ORIGIN"` line;
- `PATHWAY-ID="VIDRA-ORIGIN"` and `STABLE-VARIANT-ID="…"` on each `EXT-X-STREAM-INF`
  (and each `EXT-X-I-FRAME-STREAM-INF`);
- `STABLE-RENDITION-ID="…"` on the audio `EXT-X-MEDIA`.

A client that ignores all four gets byte-equivalent behaviour to today: the same ladder, at the same
origin URIs, with the same `?v=` chain. That is the property that makes this reversible.

**The failure-mode asymmetry is what settles B over A despite the Apple uncertainty.** Base steering
is the well-evidenced part and cloning is the thin part (§F3), so it is fair to ask why the design
depends on the thin part. Compare what each shape does when a client cannot do what it is asked:

| | If the client cannot clone | If the client ignores steering entirely |
|---|---|---|
| **B** | plays `VIDRA-ORIGIN` — today's behaviour, with segments still 307'd to the CDN. **No regression.** | identical to today |
| **A** | n/a (no cloning involved) | sees an N× duplicated ladder — a regression for every such client |

Shape B's worst case is *the feature does nothing for that client*; shape A's worst case is *the
client is worse off than before steering existed*. On an install where most traffic is hls.js —
which does clone, verifiably, in the shipped version — B buys the majority and costs the minority
nothing. A would buy the iPhone minority at the majority's expense, and only if Apple's playlist-
declared pathway switching works as the single field report suggests. **B, with A documented as the
escape hatch**, and with the empirical Apple test in §Sequence S1 as the thing that decides whether
the escape hatch is ever needed.

### D2. The attributes are synthesized at the rewrite, not written by the packager

The obvious implementation adds them in `renderCMAFMasterPlaylist` (`internal/media/cmaf.go:1127`)
and `renderMasterPlaylist` (`internal/media/packager.go:857`). That would be wrong twice: it changes
stored bytes, and **the entire back catalogue would be unsteerable until re-packaged** — including
the ~2k imported PeerTube trees phase 3 deliberately kept playing without re-packaging.

`rewritePlaylistReferences` already visits every line of every playlist on every request
(`hls.go:319-353`), splitting tag lines from URI lines. Synthesizing the attributes there is the
same work it already does. `STABLE-VARIANT-ID` need only be *stable for the asset and unique within
the playlist* (bis-22 §4.4.6.2), so a pure function of the variant's own relative URI —
`base64(sha256(relativeURI))[:16]`, whose alphabet is inside the attribute's legal charset — is
computable identically by the rewriter and by the steering endpoint, with no shared state.
**Zero packager change, zero re-transcode, zero back-catalogue migration.**

**Two implementation traps, both silent:**

1. **`hlsPlaylistURIAttrRE` is `URI="([^"]+)"`, unanchored** (`hls.go:75`). The string
   `SERVER-URI="steering.json"` *contains* `URI="…"`, so injecting the steering tag **before**
   `rewritePlaylistReferences` runs makes the rewriter append `?v=<generation>` — and on a
   credentialed request `?pt=<token>` — to the steering server URI, producing exactly the
   generation-scoped, potentially credentialed steering URI the design forbids. Inject **after** the
   rewrite, or anchor the regex to `(?:^|[,:])URI="`. Injecting after is cheaper and touches nothing
   already tested.
2. **There are two master-serving paths.** Native trees go through `serveHLSPlaylist`
   (`hls.go:221-241`); imported PeerTube trees go through `servePeerTubeHLSMaster` →
   `rewritePeerTubeMasterPlaylist` (`hls.go:277-317`). Injecting into only the first gives imported
   videos no steering, silently, and no test written against a natively transcoded fixture would
   catch it.

### D3. The pathway model

- **`VIDRA-ORIGIN`** — the pathway declared by the Multivariant Playlist. Route-addressed, always
  present, always last in `PATHWAY-PRIORITY`. It is the fail-open floor, the role `api-proxy` plays
  in `delivery.Resolver`.
- **One pathway per configured CDN**, id operator-chosen, matching `^[A-Z0-9][A-Z0-9_-]{0,15}$` (a
  subset of the spec's legal charset), **capped at 8** (§O-c). Ids must not be dots: hls.js
  auto-assigns `"."`, `".."`, `"..."` to redundant streams (`level-controller.ts:167-172`), and a
  Vidra pathway colliding with an inferred one would be indistinguishable in `_HLS_pathway` and in
  QoE rows.

**The mismatch that fails silently, and is also a spec violation.** bis-22 §4.4.6.6 requires the
tag's `PATHWAY-ID` to be *"specified by the PATHWAY-ID attribute of one or more Variant Streams"*.
hls.js does not error on a violation — it self-heals: `filterParsedLevels` (lines 238-256) filters
to the tag's pathway, finds zero levels, and adopts `levels[0].pathwayId` (which is `"."` when the
variants carry no attribute, `types/level.ts:180`). Every subsequent `PATHWAY-CLONE` whose `BASE-ID`
is `"VIDRA-ORIGIN"` then clones nothing, because `getLevelsForPathway(baseId)` is empty (line 349).
The symptom is not an error; it is steering doing nothing, with one debug line
(`No levels found in Pathway …`). **Emit `PATHWAY-ID` on the tag and on every variant, and assert
their equality in a test.** Apple's authoring rule 9.18 independently asks for the tag attribute.

**A pathway need not be a CDN — and this is the most valuable thing steering offers Vidra outside
multi-CDN.** Kara & Simon (MHV'26) note that *"the standard treats pathway identifiers as opaque
labels and does not require them to map to different providers."* Vidra has a second key-addressed
delivery source already in the resolver: the IPFS gateway. Phase-4 item 5 records that *"the
resolver has no health, priority or failover concept and its single consumer takes the first
non-api-proxy source and returns, so **post-307 failover is impossible server-side and must live in
the player**"* — and content steering **is** that player-side failover mechanism, standards-based,
already implemented in the shipped client. Item 5's own cheapest fix for per-segment gateway
addressing (*"have the lookup return `{gateway}/ipfs/{car_root}/<rendition>/<file>`"*) produces
exactly the per-variant absolute URIs a `VIDRA-IPFS` pathway clone needs.

This is not a phase-5 item-2 deliverable and should not be smuggled into one. It is a note for
whoever schedules item 5: **if steering lands, the "manual source toggle" in the watch view can be
replaced by a real, measured, automatically-failed-over pathway** — and item 5's requirement to
measure gateway TTFB before trusting it is satisfied by the same per-pathway QoE dimension in §O-c.

**The half-steer that fails quieter still.** `performUriReplacement` uses `PER-*-URIS` only when the
stable id is truthy and matches (lines 601-606, no positional fallback). With `STABLE-RENDITION-ID`
missing, a cloned audio track keeps its **origin** URL while the video variants move to the edge.
Playback works; measurements lie. The CMAF ladder encodes audio **once** for the whole ladder
(`cmaf.go`, `layout.audioRep`), so this is not an edge case — it is every CMAF video.

### D4. The steering endpoint

`GET /api/v1/videos/{id}/hls/steering.json` — stable per video, **no session component, no `?pt=`,
no `Authorization`**. Under `optionalAuth`; 404 unless the video is `Eligible`
(`publicVideoForIPFS(v.Privacy, v.State)` — public AND published, `ipfs_assets.go:24`), the same
fence `internal/delivery` already applies. `Content-Type: application/vnd.apple.steering-list`.
`Cache-Control: private, no-store`.

The stability requirement is not aesthetic. A public video's master is served
`private, max-age=31536000, immutable` when `?v=` matches (`delivery.CacheVersionedImmutable`), so
whatever `SERVER-URI` that master contains is pinned in caches — including the viewer's own — for a
year. Per-request policy lives *behind* the URI, in the priority the endpoint computes; nothing
session-scoped may live *in* it. hls.js resolves a relative `SERVER-URI` against the playlist URL
(`m3u8-parser.ts:203-207`), so `"steering.json"` is safe there; Apple's resolution behaviour is
unverified, which is one more reason the empirical test in §Sequence is a deliverable.

```json
{
  "VERSION": 1,
  "TTL": 300,
  "PATHWAY-PRIORITY": ["EDGE-EU", "EDGE-NA", "VIDRA-ORIGIN"],
  "PATHWAY-CLONES": [
    { "ID": "EDGE-EU", "BASE-ID": "VIDRA-ORIGIN",
      "URI-REPLACEMENT": {
        "PER-VARIANT-URIS":   { "<stable-variant-id>": "https://eu.cdn.example/streaming-playlists/<uuid>/cmaf/media_0.m3u8" },
        "PER-RENDITION-URIS": { "<stable-rendition-id>": "https://eu.cdn.example/streaming-playlists/<uuid>/cmaf/media_15.m3u8" }
      } }
  ]
}
```

Contract rules, each traceable to §F2 or §F4:

- **`VERSION` must be exactly `1`.** The spec makes a client refuse an unrecognized version; hls.js
  additionally returns before `scheduleRefresh`, ending the refresh loop for the session.
- **`TTL: 300` for the MVP — but TTL is a function of what the priority depends on, and this number
  must move when the policy does.** 300 s is both specs' recommendation and hls.js's pre-manifest
  default, and it is *correct for a static operator-ordered priority*, because nothing behind it
  changes faster than an operator changes it. It is **wrong** for the QoE-driven priority of S2:
  Reznik et al. (IBC 2023) put it plainly — *"When clients start buffering, directing them to another
  CDN 5 minutes later is too late!"* — and recommend a TTL *"shorter than the size of the player's
  buffer (e.g., 10-30 seconds)"*; their production-shaped deployment ran **10 s** (§F6). See the
  request-volume arithmetic below: that is a 10-30× change in origin load, and it must be priced
  when S2 is scheduled, not discovered then. The spec permits varying TTL per client to spread load
  (and Apple's WWDC21 session recommends jitter for exactly that) — a lever to keep in reserve.
- **`RELOAD-URI` omitted.** hls.js falls back to the request URL (`this.uri || context.url`), and a
  malformed `RELOAD-URI` permanently disables steering (lines 474-483). It buys nothing here.
- **Never answer `410`.** Per spec the client MUST NOT request that URI again for the session; hls.js
  implements it as `enabled = false`. Correct for "this asset is gone", catastrophic as a way to
  express "the operator turned the CDN off".
- **Never answer `429`.** The spec says retry after `Retry-After`; hls.js 1.4.0–1.7.1 returns without
  rescheduling, so one 429 ends steering for the session. This is a constraint on Vidra's
  rate-limiting policy for this route, not a preference.
- **Every other failure is soft** and playback continues on the current pathway. **The steering
  server is not a single point of failure for playback.**
- **`PATHWAY-PRIORITY` must contain at least one id**, must not repeat one, and — because hls.js
  requires `length > 1` before it will fail a pathway over — a single-entry priority list also turns
  off error-driven failover. That is the correct behaviour when draining to origin (§O-d4) and a
  footgun anywhere else.

**Request volume and cost.** hls.js appends `_HLS_pathway` and `_HLS_throughput` on every load, and
the throughput value is a live bandwidth estimate, so the URI is effectively unique per request and
uncacheable by anything shared — which is what we want, and which means the load is honestly origin
load: `1 + floor(watch_seconds / TTL)` requests per playback. For a 30-minute watch that is
**7 requests at TTL 300, 61 at TTL 30, and 181 at TTL 10.** A single-box self-hoster should see the
last number before S2 is scheduled. Bodies are small — a 5-rung × 3-codec CMAF ladder is 15 variants
+ 1 audio rendition, so one clone is ~16 URL entries ≈ 1.8 KB and two clones ≈ 4 KB, consistent with
the *"small JSON objects (typically ≤ 1 kB)"* the literature reports for HOST-form steering.

### D5. Priority is computed server-side, per request

MVP inputs: the operator's declared order plus each pathway's enable flag. That is enough to make
the feature real — an operator can shift traffic between two CDNs without a deploy and drain one
during an incident within one TTL — and it needs no data Vidra does not have.

Deliberately **not** in the MVP, each because its input does not exist:

- **measured QoE per pathway** — blocked on §O-c; there is no per-pathway measurement today;
- **geo** — Vidra holds no geo database and no client hint carrying one; adding one is a new
  third-party dependency of exactly the kind this program avoids;
- **health probes** — phase-5 item 1's job;
- **`_HLS_throughput`-driven selection** — the client sends it and it is tempting, but a bandwidth
  estimate does not say which of two edges is nearer, and acting on it produces a policy that is
  unstable across one viewer's own refreshes.

---

## Open problems

### (a) A steered variant playlist loses `?v=` — and the gap is already shipped

**The versioning fence is origin-only, and it already does not reach the edge.** `?v=` is enforced
by `validateHLSVersion` returning 404 when the requested generation is not current (`hls.go:407-414`)
and propagated into a playlist's URIs by the rewrite. But `cdn.EdgeURL` builds
`base + "/" + escapedKey` with **no query at all** — so every segment Vidra already 307s to a CDN
today is fetched from the edge under an unversioned, in-place-mutable key. **Steering does not
create this problem.** It extends it from segments to *variant playlists*, which is worse in kind: a
stale segment under a reused name delivers wrong bytes for six seconds; a stale variant playlist
misstates the whole segment map.

**In-place mutation is reachable.** `HLSPrefixForSource` (`internal/media/hls.go:983-989`) allocates
a fresh generation directory `streaming-playlists/<id>/rN/` only for a *source replacement*; a
re-transcode of the same source — the admin path at `internal/httpapi/admin_videos.go:65`,
`EnqueueTarget` — writes back over the legacy prefix. `?v=` changes (it is derived from
`sp.UpdatedAt`, `hls.go:399-405`) and the origin is safe. The edge is not.

**Can variant playlists stay origin-pinned with only segments steered?** No, and it is worth writing
down because it is the first thing anyone will propose. A pathway replaces *variant URIs*; segment
URIs are relative to the variant playlist that contains them, so whichever host serves the playlist
serves the segments. The only ways to break the coupling are (i) writing absolute segment URIs into
the stored playlist, which hard-codes one edge into a stored object and defeats steering entirely,
or (ii) `URI-REPLACEMENT.PARAMS`, which decorates the variant URI and never reaches a segment.
**Standard steering cannot express "playlist here, segments there."**

Three candidate disciplines:

1. **Query-string versioning** — teach `EdgeURL` to carry `?v=`. Cheap, and wrong as a *discipline*:
   correctness would depend on the CDN including the query string in its cache key, which is the
   default on some products and not others; a cache-key policy Vidra cannot verify is not a
   guarantee. It also needs the version *string* threaded into `delivery.Request`, which carries
   only `Versioned bool`.
2. **Generation-addressed keys — recommended.** Extend the existing scheme so *every* packaging run
   allocates a fresh `rN` directory, not only source replacements. The object key then **is** the
   version: edge URLs are immutable by construction, no cache-key policy is involved, and **content
   replacement needs no purge at all.** The machinery already exists — `HLSGenerationName`,
   `IsHLSGenerationName`, mediagc's collection of superseded generations, and the atomic DB swap in
   `transcode.storeResult`. It is also the only discipline under which an edge-served *playlist* is
   safe, because the playlist and its segments then live in the same immutable directory. It has a
   second, unrelated payoff: Apple's offline-steering requirement that renditions with matching
   stable ids have *bit-for-bit identical* segments across pathways becomes trivially true.
3. **Purge on every re-transcode** — the fallback if (2) is judged too invasive, and worse; see (b).

**Recommendation: (2) is a prerequisite, not a follow-up.** Under shape B a steered client fetches
variant playlists from the edge from the first pathway switch onward.

### (b) Purge fan-out across N pathways

`delivery.Resolver.Purge` is `Purge(ctx, objectKey) error` against one provider, and already has
three outcomes rather than two: `nil` with no CDN, `ErrPurgeNotConfigured` with an unpurgeable CDN,
the provider's answer otherwise (`internal/cdn/cdn.go`). Steering multiplies this three ways.

1. **N providers.** Purge must fan out and **fail if any pathway fails or is unpurgeable** — a
   partial purge does not satisfy "no stale public copy survives", which is the postcondition the
   header-promotion gate rests on (risks.md §6). Per-pathway outcomes belong in the log, named by
   pathway id; the URL and token must stay out of it, exactly as `stripURL` already ensures.
2. **Object count.** A takedown of a 1-hour CMAF video is ~15 variants × ~600 six-second segments ≈
   9,000 objects, × N pathways. `cdn.Purge` is single-URL. Purging 27,000 URLs one at a time during
   a legal takedown is not an implementation detail.
3. **Therefore: prefix purge.** `internal/cdn` bought vendor neutrality by reducing every purge API
   to "one method, one URL template, at most one header". A prefix form is the same trick applied
   once more — add `{prefix}` / `{prefix_encoded}` placeholders and a
   `DELIVERY_CDN_PURGE_PREFIX_URL` — and it must keep the same honesty about the third outcome: a
   CDN with no prefix-purge endpoint produces an **error**, not a `nil`.

**Which purges survive generation-addressed keys?** Only *authorization* changes: privacy flip,
unpublish, quarantine, delete. Content replacement stops needing purge entirely, which is the second
reason (a)(2) is the right answer. The residual exposure — which steering does not create but does
multiply by N — is that an edge holding a public segment keeps serving it under a key computable
from the public video UUID (risks.md §6) until it is purged or expires.

### (c) The QoE pathway dimension

**The cheapest finding in this document: no client change is required.** The client already reports
`source_url` — the *final* URL of its own fragment fetch (`lib/use-playback-engine.ts:357-359`,
`finalFetchUrl(data?.networkDetails)`) — and the server classifies it (`internal/qoe/classify.go`).
Extending `NewClassifier` from one `cdnBase` to N `(pathwayID, base)` pairs yields the pathway for
free, server-side, under the same longest-prefix and host-boundary discipline that already stops
`https://cdn.example.com.attacker.test/x` from matching (`matchesBase`). A client still cannot mint
a dimension value: an unrecognized origin stays `other`.

*(hls.js does expose `hls.pathways` and `hls.pathwayPriority`, and fires `STEERING_MANIFEST_LOADED`
and `LEVELS_UPDATED` on a pathway change — but deriving the dimension from the URL keeps the
existing "the client never names the delivery source" invariant, which `lib/playback-qoe.ts` states
in its own header comment. Do not trade that away for a getter.)*

**Storage is the real cost, and it is a genuine departure from the bounded-cardinality doctrine.**
`qoe_events.delivery_source` and its three siblings are closed **at schema time** — the CHECK
enumerates every legal value (`migrations/0109_qoe_telemetry.up.sql:57-63`) — and `qoe_rollups`'
primary key is `(hour_bucket, delivery_source, engine, packaging_format)`. Pathway ids are closed
**at configuration time**, which is a weaker guarantee and must not be smuggled in as if it were the
same one. The reconciliation:

- **Shape, in the schema:** `pathway TEXT NOT NULL DEFAULT '-'` with
  `CHECK (pathway = '-' OR pathway ~ '^[A-Z0-9][A-Z0-9_-]{0,15}$')`. A backstop, not the guarantee.
- **Count, in config validation:** a hard cap of **8** CDN pathways, rejected at boot like every
  other `DELIVERY_*` misconfiguration. The cap is what turns "operator-configured" into "bounded".
- **Derivation, in the server:** a pathway value is only ever produced by matching a configured base;
  unmatched origins stay `('other', '-')`.
- **`'-'` for every source with no pathway concept**, so the dimension is sparse rather than
  multiplicative — pathway is meaningful only when `delivery_source = 'cdn'`.
- **Row ceiling, computed rather than asserted:** source×pathway combinations go from 6 to
  `5 + cap` = 13, so the worst case is 24 buckets × 13 × 4 engines × 3 formats = **3,744 rows/day**
  (~337k over the 90-day window) against ~1,728/day (~155k) today. A 2.2× ceiling on a table whose
  retention worker already exists.
- **Migration:** `qoe_rollups`' primary key must be dropped and recreated; existing rows backfill to
  `'-'`, which reads honestly as "the pathway was not recorded" rather than "the origin pathway".

**Rejected:** encoding the pathway into `delivery_source` (`cdn:EDGE-EU`). It breaks the closed CHECK
and breaks the equality `qoe_test.go` asserts between `qoe.DeliverySource` and `delivery.SourceKind`
(`internal/qoe/qoe.go:100-108`).

**One measurement caveat to write into the admin page, not discover later:** steering only reaches
clients that implement it, which today means hls.js. Native-HLS (iPhone) rows will concentrate on
`VIDRA-ORIGIN` regardless of priority, so a per-pathway comparison that does not split by engine is
comparing populations, not pathways.

### (d) Coexistence with the existing 307

Steering and the resolver are **layered, not competing**: steering decides which host appears in a
manifest URI; the resolver decides what happens when a client asks *the origin* for a byte anyway.

1. **Steering governs public HLS reached through a Multivariant Playlist. The 307 resolver governs
   everything else** — progressive originals, downloads, images, storyboard VTT, DASH segments,
   live, and every request from a client that ignored the tag.
2. **Steering never applies to DASH** (§F5) and **never applies to an ineligible video** — same
   public-AND-published fence as the resolver. Password, private, unlisted and scheduled playback
   stays origin-only, and CDN-fronted private playback remains a different mechanism
   (signed-URL-at-the-edge) that neither steering nor the resolver generalizes to.
3. **A steered pathway bypasses the resolver entirely**, so `delivery_cdn_enabled` — read per request
   inside `Resolve` — does **not** stop a steered client. Steering needs its own runtime kill switch,
   and turning it off must reach clients holding a year-cached master. **The switch drains through
   priority, never through `410`:** the endpoint keeps answering and returns
   `PATHWAY-PRIORITY: ["VIDRA-ORIGIN"]`, which every conforming client applies within one TTL
   (≤300s). A `410` would disable steering permanently for that session — right for a deleted asset,
   wrong for an operator action. (Note the single-entry list also disables hls.js's error-driven
   failover, which is correct here: there is nowhere left to fail over to.)
4. **The fallback loop — the sharpest interaction, and a real defect if left alone.** A steered
   client that abandons `EDGE-EU` (hls.js penalizes a failing pathway for 5 minutes) falls back to
   `VIDRA-ORIGIN` — whereupon `serveMediaAsset` 307s its segment requests **straight back to a CDN**,
   possibly the one that just failed. The origin pathway is then not an origin, and single-CDN
   failover does not work.
   **Recommendation:** author the `VIDRA-ORIGIN` pathway as a clone whose `PER-VARIANT-URIS` carry an
   explicit `&src=origin` marker that `serveMediaAsset` reads as "resolve api-proxy only". Because
   that marker exists only in the steering response, non-steering clients never see it and keep their
   307 CDN benefit unchanged. Two costs to accept openly: it adds a query parameter to the immutable
   media URL space (stable per pathway, so it does not fragment the cache), and it lets any anonymous
   caller opt out of the CDN — a lever on origin bandwidth, bounded by the fact that origin serving
   is the pre-CDN default, but it should be stated rather than discovered.
   *Alternative considered and rejected as incomplete:* rely on there being ≥2 CDN pathways so the
   penalty box moves the client to a second edge before it reaches the origin. True with two CDNs,
   useless in the one-CDN case, which is the common one.
5. **The declared pathway is fetched from before the clones exist.** hls.js starts the steering fetch
   at `MANIFEST_LOADED` (lines 169-182), concurrently with the first variant-playlist load, and
   `clonePathways` cannot run until the manifest lands. Apple's WWDC21 description is the same:
   *"it will only use variant streams from the initial pathway… but in parallel… the client will
   start making periodic Steering Manifest requests in background."* So under shape B **every
   playback begins on `VIDRA-ORIGIN` and switches once**, costing one origin variant-playlist fetch
   and possibly the first segment. Apple names the cost directly: *"it is important for the Master
   Playlist and the preferred Pathway of the initial Steering Manifest to agree. Immediately
   redirecting a player to a different Pathway on startup will **delay playback and increase network
   utilization**."* Vidra is deliberately taking that startup redirect in exchange for leaving
   non-steering clients untouched — which means **TTFF is the metric most likely to move the wrong
   way when steering is switched on**, and the QoE page will show it. §Sequence S3 is what buys it
   back; until then, expect and explain it rather than treat it as a regression.
6. **The redirect's own cache policy stays private.** `CacheCDNRedirect` is `CacheShortLived`
   deliberately (`internal/delivery/delivery.go`), and steering changes none of that reasoning:
   promotion to `public` is still gated on a purge that has been *exercised*.

### (e) How does a demoted pathway ever come back?

Not in the original problem list, and it is the one open problem with published measurements behind
it. Once priority is computed from measurements (S2), a pathway that fails gets demoted — and then
**no client uses it, so no measurement of it exists, so it can never be promoted again.** Kara &
Simon (MHV'25) state it as *"how to get informed about the recovery of a faulty CDN if no users are
downloading from it?"* and measure the naive answers: the "Unlucky Sacrifice" strategy — keep one
victim on the broken pathway — which the paper says *"many service providers are unfortunately
implementing"*, subjected a single client to up to **32 consecutive rebufferings**; a fair-rotation
variant caused ~25× baseline rebuffering across the population. What works is buffer-aware rotation
(recovery detected in <10 s) or, for a stateless server, random probing (<20 s).

Vidra's MVP does not have this problem, because priority is static: an operator demotes a pathway
and an operator promotes it back. **It acquires the problem the moment S2 lands**, and the honest
mitigation for a self-hoster is the cheap one — probe server-side rather than sacrificing viewers.
Vidra can afford that where a CDN vendor cannot: phase-5 item 1 already scopes health signals, and
an origin-side HEAD against one known object per pathway costs nothing and taxes no viewer. **Write
this down as a constraint on item 1's health model: pathway health must be measurable without
routing a viewer to a pathway believed broken.**

Two adjacent constraints from the same authors, both of which bite Vidra later rather than now:
pathway switching requires *"consistent cache key construction and compatible tokenization or
URL-signing across"* pathways — which is open problem (a) restated from the client's side — and DRM
licenses *"may require re-validation … when the delivery endpoint changes"*, which is a live
constraint on phase-5 items 4-7 and should be recorded there.

---

## Sequence

Four prerequisites, **all independently justified by work already shipped** — none is steering
groundwork wearing a disguise, which is the test this program applies (cf. the segment-digest
prerequisite in the P2P decision).

| | Prerequisite | Why it stands on its own |
|---|---|---|
| **P0** | **Generation-addressed HLS keys** — every packaging run allocates `rN`, not only source replacements | Item 2's *shipped* CDN path already serves segments from unversioned edge keys that an admin re-transcode overwrites in place (`EdgeURL` carries no query; `HLSPrefixForSource` reuses the legacy prefix for a version-0 source). A live correctness gap today, with or without steering. |
| **P1** | **`Purge` call sites + a prefix-purge form** | Already the standing gate on private→shared header promotion (phase-4 carry-forwards; risks.md §6). `Purge` has zero call sites today. |
| **P2** | **Multi-CDN configuration** — `DELIVERY_CDN_*` becomes an id'd list, capped at 8, boot-validated; the resolver picks deterministically; N=1 stays byte-identical to today | This *is* phase-5 item 1's configuration half. Steering cannot have two pathways before the config can express two edges. |
| **P3** | **The QoE pathway dimension** (§O-c) | Phase 4's third exit criterion is still "built but never demonstrated on real traffic". Shipping steering before per-pathway measurement repeats exactly that: a routing decision nobody can evaluate. Measure the second CDN *before* steering to it. |

Then:

- **S1 — the steering MVP.** Endpoint (§D4) with static operator-ordered priority; tag +
  `PATHWAY-ID` + `STABLE-VARIANT-ID` + `STABLE-RENDITION-ID` synthesized at the existing rewrite
  (§D2) and injected **after** it, in **both** master paths; one clone per enabled CDN pathway plus
  the `VIDRA-ORIGIN` clone carrying `&src=origin`; a `delivery_steering_enabled` runtime switch that
  drains through `PATHWAY-PRIORITY` and never through `410`; and **the hls.js bump to ≥1.7.1**
  (`^1.6.16` will not resolve to it), which fixes three URI-REPLACEMENT defects (§F4).
  Tests that must exist before it ships: master byte-identical with <2 pathways configured; the
  tag's `PATHWAY-ID` equals every variant's; `SERVER-URI` survives the rewrite untouched; `VERSION`
  is literally `1`; the route never emits `410` or `429`; every clone's `PER-RENDITION-URIS` covers
  the audio rendition; the imported-PeerTube master gets the tag too.
  **Plus one deliverable that is not a unit test: an empirical run against Safari/iOS.** Nobody has
  published a test of `PER-VARIANT-URIS` on AVPlayer, and the only two public reports of cloning are
  failures (§F3). Capture the traffic; find out whether Apple sends `_HLS_pathway` at all; record the
  answer in this document. If cloning is still broken on current iOS, the decision to make is
  "leave iPhone on `VIDRA-ORIGIN`" (cheap, no regression) versus shape A (§D1).
- **S2 — dynamic priority** from per-pathway QoE (P3) and phase-5 item 1's health signals.
- **S3 — optional, behind its own switch: promote the base pathway to the primary edge.** The
  master's variant URIs point at the primary CDN and `VIDRA-ORIGIN` becomes a clone. This removes
  the startup redirect (§O-d5), gives non-steering clients the edge with one hop fewer than a 307,
  and satisfies steering-05's `PATHWAY-PRIORITY[0]` guidance. It requires P0, because it puts
  edge-served playlists in front of *every* client rather than only steered ones.
- **Not now: DASH steering** (§F5) — and not merely "until Shaka".

### The minimal first slice

If only one thing is built: **P2 + P3 — multi-CDN configuration and the per-pathway QoE dimension,
with no steering at all.** It is small, it is phase-5 item 1's real content, it makes "is the second
CDN actually better?" answerable for the first time, and every later steering decision is a guess
without it. Steering itself is worth close to nothing until an operator can see which pathway is
winning.

### Go / no-go

**GO on the research half — this document closes it. The build half is CONDITIONAL on P0–P3 and
sequenced behind phase-5 item 1.**

Why this is a GO where phase-4 item 6 was a DEFER, given that both are optional delivery features
aimed at large installs:

1. **It costs the viewer nothing.** No new exposure, no upload tax, no CPU, no third-party
   connection. The one new network request goes to the operator's own origin.
2. **It is invisible when unconfigured**, provably: fewer than two pathways means no tag, no
   attributes, no route.
3. **The client work is zero.** hls.js 1.6.16 is already shipped and already implements the feature,
   in both the full and light bundles; `lib/use-playback-engine.ts` needs no change for steering
   itself (only the version bump).
4. **It fails soft by construction.** Every failure mode short of a deliberate `410` degrades to
   "play the declared pathway", which is today's behaviour.
5. **It is reversible by deleting one line** from a per-request rewrite. Nothing is written to
   storage; nothing is written to the database except the QoE column.

Why it is conditional rather than unconditional:

1. **P0 is a live gap, not a hypothesis.** Steering pushes variant playlists onto edges Vidra cannot
   version and does not purge. Building it before P0 ships a correctness regression.
2. **The value is narrow, and belongs in the docs rather than implied.** The benefit is proportional
   to the number of CDNs an operator runs, which for the target install is zero or one. At N=1 the
   honest description of steering is "a slower way to do what the 307 already does, plus a failover
   path" — and even that failover is only real once §O-d4 is fixed. Vidra's own deployments run
   **zero** CDNs today.
3. **Its measurement prerequisite is the thing phase 4 has still not demonstrated.** Steering makes
   routing decisions from measurements; building it on a pipeline nobody has validated against real
   traffic is building on an assumption.
4. **The standard is a pre-RFC Apple submission and the reference client's behaviour deviates from
   it in two places** (§F4). Neither deviation is fatal; both are constraints Vidra must design
   around, and both could change under it.
5. **The track record is lab-measured, not field-attributed.** The headline gains (buffering ratio
   0.03% vs 0.42%) come from one synthetic testbed; **no named operator has published an
   attributable production deployment**, no CDN vendor documents the feature as a product, the
   public demo estate is dead, and Bitmovin still does not implement it (§F6). That does not argue
   against building — Vidra's cost is a rewrite hook and a JSON endpoint, not a platform bet — but it
   does argue against promising an operator a number.

**What would flip this to DON'T BUILD.** If phase-5 item 3 (origin shielding) lands first and the
route-addressed shield topology (shape C) satisfies the operators who ask for multi-CDN, steering's
remaining value is client-side failover between edges — and **plain HLS Redundant Streams already
provide that with no steering server at all.** hls.js assigns synthetic pathway ids to duplicate
`EXT-X-STREAM-INF` entries and hands them to the same penalty-box machinery
(`level-controller.ts:167-176`); it is the oldest failover idiom in HLS and it needs one extra line
per variant in the rewrite. If "one of my CDNs went down" is the only requirement an operator
actually has, that is the cheaper answer and it should win.

---

## Limits of this research

**hls.js.** Every assertion was read from source — `vidra-user/node_modules/hls.js@1.6.16` and
upstream master `afe5b8bf` (≡ v1.7.1) — with file and line references, and **none of it was
executed**. Two claims deserve a runtime check before anything depends on them: the 429 branch that
returns without rescheduling, and the `VERSION !== 1` branch that returns before `scheduleRefresh`.
Both read as defects; neither has an upstream issue or maintainer acknowledgement. S1's test plan
should settle them against a stub steering server.

**Apple.** Nearly everything that matters is unverified, and the gaps are the design's largest risk:

1. No wire evidence (pcap, HAR, or steering-server access log) that Safari or AVPlayer ever sends
   `_HLS_pathway` / `_HLS_throughput`. The spec says SHOULD; Apple's own hosted document says MAY.
2. **No claim in either direction, from any source including Apple, that AVPlayer honours
   `PER-VARIANT-URIS` / `PER-RENDITION-URIS`** — only the WWDC22 presentation introducing them.
3. Apple's minimum OS version for steering is stated three different ways by three Apple sources
   (iOS 15, iOS 15.4, iOS 16); no macOS/Safari floor has ever been given.
4. Whether the two Dec-2022 cloning failures on iOS 16.2 were ever fixed. No radar number, no
   follow-up, and no report since of cloning working *or* failing.
5. Apple's observed behaviour on steering-server 4xx/5xx/timeout, its actual retry cadence, and its
   actual penalization duration.
6. Whether `mediastreamvalidator` validates steering tags. An Apple engineer directed a developer to
   it for a steering defect; Apple's own tools page does not mention steering, and the tool ships
   behind an Apple ID so its documentation is not crawlable.

**Vidra.** Everything asserted was read from the tree at HEAD and is verifiable by line. No steering
code was written and no playback was run against a steering server, so "hls.js switches pathways
against a Vidra-authored steering manifest" is a **design** claim, not a demonstrated one.

**Vendor conventions.** Genuinely thin (§F6), and the negatives are as load-bearing as the
positives. The claim "Akamai and Fastly have published nothing on content steering" rests on
site-scoped searching and is only as strong as that coverage; the AWS negative is stronger, being a
text-grep of the downloaded MediaPackage v1/v2 and MediaTailor guides. No named production
deployment was found — an absence, not a proof. Paywalled camera-ready PDFs (MMSys 2024
`10.1145/3638036.3640293`, MHV 2025 `10.1145/3715675.3715791`, IBC 2024) were not read; their
numbers come from author-hosted versions and abstracts, and the MHV'25 sources contradict each other
on which Indian CDN took the residual share. A single blog cites a "CTA-5004-B" (April 2026) CMCD
revision; the CTA repository says CTA-5004-A, so treat -B as unestablished.

**DASH.** The normative `<ContentSteering>` semantics live in ISO/IEC 23009-1 Amd.2 Annex K.3, which
is paywalled; syntax and defaults above come from the public MPEG XSD (`6th-Ed` branch) and from
ETSI TS 103 998 V1.1.1, which itself cites the CD of that amendment. ETSI's own document carries an
unresolved contradiction on whether `PATHWAY-PRIORITY` is REQUIRED or optional-with-default.

## Sources

`draft-pantos-content-steering-05` (18 May 2026) ·
`draft-pantos-hls-rfc8216bis-22` (1 May 2026) ·
Apple pre-release `HLS-draft-pantos.pdf` (1 Jun 2026) ·
Apple `HLSContentSteeringSpecification.pdf` v1.2b1 (stale: © 2020-2021, no cloning) ·
HLS Authoring Specification for Apple Devices rule 9.18 ·
WWDC21 session 10141, WWDC22 session 10144 ("What's new in HLS" 2023-2026 contain no further
steering work) · Apple developer-forum threads 696538, 721338, 722145 ·
Pantos, IETF-124 MOPS slides (Nov 2025) ·
ETSI TS 103 998 V1.1.1 (2024-01) · DASH-IF CTS 00XX v0.9.0 (2022-07-10) · MPEG `DASH-MPD.xsd`
(`6th-Ed`) · Will Law, DASH-IF Content-Steering issue #5 ·
hls.js v1.4.0 release notes / PR #5191, PRs #6295, #6759/#6760, #6997, #7655, #7710, #7969,
master `afe5b8bf` · Shaka Player v4.6.0 · dash.js v4.5.0 PR #4031 / PR #4173 · androidx/media #1689 ·
video.js VHS `docs/content-steering.md` · Bitmovin community forum (2025-04-08) ·
IANA application media-type registry (`application/vnd.apple.steering-list`) ·
CTA-5004-A (CMCD v2, Feb 2026) and CTA-5006 (CMSD, Nov 2022) — both grepped, zero steering hits ·
AWS MediaPackage v1/v2 and MediaTailor user guides (PDF, grepped: zero steering hits) ·
broadpeak.io Content Steering beta (2024-08-20) · einbliq.io steering-server material ·
Fastly, *Multi-CDN: A Critical Decision for a Resilient Architecture* (2026-02-19) ·
Akamai, *Solve Multi-CDN Entitlement Drift with Edge Functions* (2026-07-28) ·
SVTA3015 (2020-04-07), SVTA5069 (draft), `merongithub/content_steering_at_edge` ·
Reznik et al., *Implementing HLS/DASH Content Steering at Scale*, IBC 2023; MHV'25 /
SMPTE MIJ 134(1) 2025 · Kara & Simon, MHV'25 doi 10.1145/3715675.3715790 and MHV'26 doi
10.1145/3789239.3793279 · Pillsbury (Mux), Demuxed 2025 · US Patent 12,477,189 (Brightcove) ·
The Broadcast Bridge, *Content Steering Goes Mainstream After Standardization* (2025-05-02) ·
Langendijk, *Are we ready for Multi-CDN with Content Steering?* (Dec 2025).
All fetched or checked 2026-08-23.

Vidra code cited: `internal/httpapi/hls.go` (75, 221-241, 277-317, 319-353, 399-414),
`internal/httpapi/delivery.go` (116-147), `internal/httpapi/ipfs_assets.go:24`,
`internal/httpapi/admin_videos.go:65`, `internal/httpapi/playback_session.go`,
`internal/delivery/delivery.go` (100-263), `internal/delivery/resolver.go`,
`internal/cdn/cdn.go`, `internal/media/hls.go` (906-989), `internal/media/cmaf.go` (75-107, 1127-1195),
`internal/media/packager.go` (849-871), `internal/qoe/qoe.go` (100-175), `internal/qoe/classify.go`,
`migrations/0109_qoe_telemetry.up.sql` (50-80, 160-190),
`vidra-user/lib/use-playback-engine.ts` (270-385), `vidra-user/lib/playback-qoe.ts`,
`vidra-user/package.json:27`.
