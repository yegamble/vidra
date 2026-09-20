# IPFS reference pinning — mirror public HLS without a second copy — design

Date: 2026-09-20 · Status: **draft for discussion — not approved, not planned, not
built** · Repos: vidra-core (C), vidra (M), vidra-user (U)

Every claim below is tagged by how it is known: **[read]** in the code at
vidra-core `400c1a8` / vidra `79a84cd` with file:line, **[measured]** in the lab
spike recorded beside this document
(`docs/evidence/ipfs-reference-pinning-spike-2026-09-20/`), **[sourced]** from a
URL fetched on 2026-09-20, or **[unverified]**. Nothing here is an owner ruling;
section 12 lists the decisions the owner has not made yet.

Revision 2 (same day) folds in four independent reviews of revision 1 — backend,
security, infrastructure, and an evidence audit. What they changed is listed in
section 14, because several of revision 1's claims were wrong.

## 1. What this is

An opt-in storage mode for the public IPFS mirror in which the Kubo node stores
**references** — URL, offset, length — to the HLS bytes vidra already holds in
primary storage, instead of a second full copy of them. The node's disk need falls
from "about the size of the public HLS library" to "about the size of its index".

No new service and nothing new for the operator to run. It is **not free of
cost**: the disk bill becomes bucket GET and egress traffic, because every byte the
mirror serves is then read from primary storage. Limits on the new route bound that
(5.3); their values are not set until gate 3 has run (section 10).

It answers the owner's question of 2026-09-20, in their words: *"is there a way to
possibly mount S3 instead to help pin IPFS videos instead of paying for a large
volume?"*, under their constraint *"without extra incurred cost or great effort on
part of the admin"*, for the problem *"at the moment, pinning stops at a point on
local disk"*.

The short answers: mounting S3 under Kubo does not work (section 3); what works is
not storing the second copy at all (section 5); and five fixes are worth shipping
whether or not reference pinning is ever built (section 6).

## 2. Why pinning stops today

**Every pinned byte is stored twice.** Primary storage stays authoritative
(`internal/ipfsmirror/classes.go:1-9`) and Kubo holds a full second copy: the add
is a plain `POST /api/v0/add?pin=true&cid-version=1&raw-leaves=true`
(`internal/ipfs/client.go:139-153`) with the bytes streamed from the storage
backend into a multipart body (`internal/ipfsmirror/service.go:1590-1630`,
`internal/ipfs/client.go:158-180`) — never staged on scratch. In managed mode the
stream is paced and bounded by `limitedSource` (`limited_source.go:69-173`,
`admission.go:342-350`); the legacy drain reads the backend directly. **[read]**

What is pinned per public video: the promoted HLS generation directory as one
wrap-add (every playlist and segment, `service.go:1420-1468`), plus thumbnail,
storyboard, VTT and captions; the original and the WebM are deferred while a ready
HLS tree exists (`admission.go:196-207`). So the node's disk tracks the size of
the public HLS ladder. **[read]**

Four independent mechanisms can then stop pinning: **[read]**

| # | Mechanism | Where | What the operator sees |
|---|---|---|---|
| 1 | Managed-mode admission refuses the pass when `repo_used > budget_bytes` or `filesystem_free < min_free_bytes` | `admission.go:166`; re-asserted per claim in `ipfs_admission.sql:36-37` | `admission_paused_reason` on Admin → IPFS (`internal/ipfscontrol/runtime.go:112-138`) |
| 2 | The reservation is `2 × bytes + 16 KiB × files + 1 MiB` | `admission.go:110` ("Include ample UnixFS/chunk/directory overhead and never assume deduplication") | A budget that stops admitting at about half its nominal figure |
| 3 | The host manager sets `Datastore.StorageMax = budget_bytes`, which Kubo treats as a soft GC trigger | `deploy/ipfs-manager.py:229-235`; `deploy/IPFS-MANAGER.md:75-78` | Nothing — it is not a ceiling |
| 4 | **Unmanaged mode has no admission at all**: the legacy drain is unbounded, the compose service sets no `--enable-gc` and no `StorageMax` | `service.go:1196-1243`; `vidra-core/docker-compose.yml:1286-1312` | The volume fills, and it is shared with Postgres and the media scratch (`docker-compose.prod.yml:620-628`) |

A refused row stays `pending` with `capacity_reason` set and retries every 60 s
(`ipfs_admission.sql:90-93`), so pinning resumes by itself when space frees. The
exception is a row evicted for capacity: `capacity_reason = 'evicted_capacity'`
is excluded from both candidate queries (`:15`, `:79`) and returns only on a fresh
`demand` tag (`:135-143`). And `/admin/system`'s `ipfs` component reports `ok` on
a full budget as long as node and gateway answer
(`internal/httpapi/system_ipfs_managed.go:29-68`). **[read]**

Kubo facts that bound any fix: `Datastore.StorageMax` is *"A soft upper limit …
used to calculate whether to trigger a gc run (only if `--enable-gc` flag is set)
… It is not a hard limit on total disk usage"*, default `10GB`
([config.md](https://github.com/ipfs/kubo/blob/master/docs/config.md)).
**[sourced]** GC removes only what is unpinned (T6) **[measured]**, so for a node
whose whole job is pinning it frees nothing.

## 3. Options considered and rejected

| Option | Verdict | Why |
|---|---|---|
| FUSE-mount a bucket under the Kubo repo (s3fs, goofys, rclone mount, mountpoint-s3) | **No** | The tools say so themselves. mountpoint-s3: *"It does not emulate operations like `rename` on S3 general purpose buckets"*, *"All writes must be sequential"*, *"POSIX file locks (`lockf`) are not supported"* ([SEMANTICS.md](https://github.com/awslabs/mountpoint-s3/blob/main/doc/SEMANTICS.md)); rclone: *"Without the use of `--vfs-cache-mode` this can only write files sequentially"* ([docs](https://rclone.org/commands/rclone_mount/)) — and the cache that fixes it is local disk. **[sourced]** Kubo's repo lock is an fcntl lock ([kubo#6363](https://github.com/ipfs/kubo/issues/6363) shows `Lock FcntlFlock`) **[sourced]**; that flatfs needs atomic rename and leveldb/pebble need random writes is general knowledge of those stores, **[unverified]** against a Kubo document here |
| JuiceFS under the repo | No | Genuinely POSIX, but needs its own metadata database — a new stateful service to run and back up. Fails "no great effort". **[sourced]** |
| `go-ds-s3` datastore plugin | **No** | README banner *"🚧 Looking for Maintainers 🚧"*; newest prebuilt plugin is `go-ds-s3-plugin/v0.32.1` (2024-11-21) against our 0.43; `go.mod` on `aws-sdk-go v1.55.6`, whose SDK reached end-of-support 2025-07-31; *"Garbage collection appears to be broken with this plugin"* open since 2021 ([go-ds-s3#198](https://github.com/ipfs/go-ds-s3/issues/198)); a Go plugin must match the exact Kubo build, so we would ship our own Kubo for every release. It also still stores a **second copy**, only in a bucket. **[sourced]** |
| Remote pinning service | No | Recurring cost. No free tier above 5 GB; cheapest plan found is Filebase Pro, $7.50/month for 500 GB ([pricing](https://filebase.com/pricing)). `vidra-core/.ralph/specs/ipfs-media-private.md:244-248` keeps the seam open for it: *"If a hosted adapter is ever justified … it slots in as another implementation behind that interface plus a config choice"*. **[sourced] [read]** |
| IPFS Cluster followers / collaborative cluster | No | Followers add replicas; the origin still pins everything, so its disk ceiling is untouched. **[sourced]** |
| A vidra-native S3-backed trustless gateway on `boxo` | No | The only other zero-copy design, but weeks of work and a permanent maintenance obligation on a library that is losing its maintainers (section 4). **[sourced]** |
| A PeerTube-style size-capped pin budget (`redundancy.videos` strategies with `size` + `min_lifetime`) | Already built | Managed mode has budget, reservations and cold-pin eviction (`EvictColdIPFSPin`, `ipfs_admission.sql:154-170`). It caps the ceiling; it cannot raise it. **[read]** |

## 4. Upstream context, and what it means for how much to build

IP Shipyard's IPFS work ends on **2026-09-30**. Kubo, Boxo, Helia, Rainbow,
Someguy and the Service Worker Gateway lose their dedicated maintainers; Shipyard
stops operating `ipfs.io`, `dweb.link`, `delegated-ipfs.dev` and the bootstrap
nodes, and *"Protocol Labs, as the owner of the associated domains and
infrastructure, will determine their future"*
([announcement, 2026-08-24](https://ipshipyard.com/blog/2026-the-end-of-ipfs-at-shipyard/)).
Kubo v0.43 is *"the last Kubo release with new features from the Shipyard team"*
([changelog](https://github.com/ipfs/kubo/blob/master/docs/changelogs/v0.43.md)).
As of a post dated 2026-08-25, visitors to `ipfs.io` and `dweb.link` *"are now
redirected to the service worker gateway at inbrowser.link"*
([blog.ipfs.tech](https://blog.ipfs.tech/2026-08-beyond-sponsored-gateways/)).
**[sourced — both pages re-fetched by the author of this document]**

Vidra's mirror does not depend on those gateways — viewers are sent to the
operator's own `IPFS_GATEWAY_URL` — so the feature keeps working. But the posture
this design takes follows from the news: **keep the IPFS investment small,
config-shaped and reversible, on the Kubo version already pinned; do not write an
IPFS server of our own.** Filestore and urlstore have been in-tree and
"experimental" since 2017, and a frozen Kubo is unlikely to remove them, but
equally unlikely to fix a bug in them. Section 12 asks the owner how much of this
to build in that light.

## 5. Design: reference pinning

```
   worker (as today)                         Kubo node                    viewer / peer
   storage.Open(key) ──stream──▶ POST /api/v0/add?nocopy=true
                                 part header  Abspath: <source URL>
                                 hashes the bytes, keeps the DAG nodes,
                                 stores leaves as {URL, offset, length}
                                                 │                 GET /ipfs/<cid>/…
                                                 │◀────────────────────────┘
   api: GET /ipfs-source/v1/<key>  ◀──Range GET──┘  re-hashes each block, serves it
        reference-mode HLS row, live generation,
        video still anonymously served?  ── no ──▶ 404
        serveStoredObject (Range → ranged S3 GET), under the route's limits
```

**Scope: HLS trees only.** Reference mode applies to the `hls` media class and to
nothing else. Thumbnails, storyboards, VTTs, captions, avatars, banners, playlist
covers, originals and WebM stay copies. That is where the bytes are, and the two
reviews that tried to break the design both broke it on the other classes:

- HLS generation directories are immutable — generation N is written to a fresh
  directory and promoted by swapping `streaming_playlists.master_key`
  (`internal/media/hls.go:912-947`) — whereas a poster or storyboard is replaced
  **at a stable key** with the mirror never told (`internal/video/service.go:1724`,
  `:1670`; `fireMediaReplaced` at `:520` exists "for exactly one consumer: CDN
  invalidation"), caption delete has no mirror call at all
  (`internal/video/captions.go:125`), and avatar replacement deletes the blob
  before it unpins (`internal/profileimage/service.go:449-451`). **[read]** A
  reference to a key whose bytes changed serves nothing, forever (T4b).
- A public `pinned` row does not mean "this instance serves these bytes
  anonymously today". Turning `downloads_enabled` off revokes original-file URLs
  through a catalogue walk (`internal/cdnpurge/cdnpurge.go:21-24,71,333`) that
  never touches `media_ipfs_pins`; the mirror's gate reads no download policy
  (`internal/ipfsmirror/eligibility.go:96-115`). **[read]** An unauthenticated
  source route over originals would serve them after they were revoked. For HLS of
  a public, published, unblocked, non-DRM video the two agree (5.3).

### 5.1 The Kubo mechanism, as measured

All **[measured]** on `ipfs/kubo:v0.43.0`, arm64, Docker Desktop, an **offline**
node, a local Python Range-serving origin, random payloads, one run per test. Test
ids refer to `EVIDENCE.md`; the transcripts are in `out/` beside it. The spike
establishes what Kubo does, not how fast.

| Fact | Test |
|---|---|
| With `Experimental.UrlstoreEnabled=true` (the filestore flag is not needed), `add?nocopy=true` with a multipart part header `Abspath: <http URL>` stores `{URL, offset, length}` per leaf. The bytes are still streamed in the body, and those are what Kubo hashes | T1 |
| **The CID is identical to today's copy add** — for a single file and for a wrapped HLS tree with one `Abspath` per part | T1, T3 |
| Repo growth for one 64 MiB file: 62,999 bytes — **0.094 % of the payload**. A real HLS tree, with a DAG node per file, was not sized | T1 |
| Kubo does not contact the URL at add time — **except** for a file that fits in one chunk (≤ 262,144 bytes), which costs exactly one origin read during the add | T1, T3 probe |
| A read is one ranged GET per block, exactly one block wide, never a whole-object GET; nothing is cached between reads | T2 |
| Wrong bytes at the URL: **zero bytes served** (every block is re-hashed). Origin refusing connections or answering 404: the read fails in ~0.03 s and **recovers with no re-add** when the origin returns. An origin that stalls instead of refusing was **not** tested | T4 |
| A 307 is followed and `Range` survives it, at two requests per block | T4d |
| With the flag off the add fails closed: HTTP 500, `either the filestore or the urlstore must be enabled to use nocopy` | T0 |
| `repo/gc` keeps references while pinned; unpin + gc removes them | T6 |
| `pin/ls`, `pin/verify`, `repo/stat`, `repo/gc`, `files/stat`, `ls` on a directory root, `block/stat`, whole-store `filestore/ls`, and non-recursive `refs` on a single-file root read **zero** origin bytes | T12 |
| **`refs?recursive=true`, `dag/stat` and `filestore/verify` re-download every byte** | T12 |
| Every gateway read has a two-block floor: a HEAD, which returns no body, costs 512 KiB of origin traffic (one block of readahead) | T12 |
| **One reference per block, first writer wins.** A second add of identical bytes under another URL returns HTTP 200 and the right CID and records nothing; the same is true of a nocopy re-add over blocks the node already holds as copies | T5, T10 |
| `block/rm` removes references (32 in one call) but refuses while **any** pin covers the block; `force=true` does not override | T10 |
| Heal, end to end: unpin every covering pin → `block/rm` the leaves → nocopy re-add from the good URL. CID unchanged, no gc, no restart | T10-iv |
| A failure on a late part of an add returns **HTTP 200** with the error only in the `X-Stream-Error` trailer, no root entry and no pin. On success the wrapping directory is the last entry, with `Name: ""` | T11a, T3 |
| A small file added first in copy mode stays a real block through a later nocopy add of the tree, serves while the origin answers 404, and survives gc | T11b |

Not measured, and gated in section 10: the DHT reprovider, bitswap retrieval by a
remote peer, any real S3 endpoint, a stalling origin, Kubo's resource use under
many ranged reads, and the multi-level walk of 5.4.

### 5.2 The add call (C)

`ipfs.DirEntry` (`internal/ipfs/client.go:24`) gains a `SourceURL` field. When it is
set, `add` writes that part with `CreatePart` and an `Abspath` header instead of
`CreateFormFile` (`client.go:163`), and the query gains `nocopy=true`. The `Client`
interface keeps its shape — the seam `ipfs-media-private.md:244-248` asks not to
widen. Because the CID does not depend on the mode (T1, T3), **the mode is
invisible outside the node**: ledger rows, gateway links, federation payloads and
anything a viewer bookmarked are unaffected by a switch in either direction.

**Tiny files are always real copies.** Files at or under a threshold (placeholder
**32 KiB**: playlists, init segments) are added first in copy mode with
`pin=false`; the tree add then carries `Abspath` on every part, finds those blocks
present, leaves them alone (T11b), and its recursive pin covers them. This is not
an optimisation. **CMAF init segments are the files most likely to be
byte-identical across different videos** — same codec, same resolution, same
encoder settings — and with one reference per block (5.4) every video's init
segment would otherwise hang off the *first* video ever pinned at that rendition,
and break with it. Whether init segments really are identical across videos is
**[unverified]** and is a gate-4 measurement; the rule makes the answer not matter.

Two constraints on how it is built, both **[read]**:

- **One open per key.** `limitedSource` refuses a second `Open` of a key
  (`limited_source.go:73-79`), `lazyBlob` is single-use (`service.go:1590-1625`),
  and the admitted byte budget is `Σ sizes` (`admission.go:339-350`, `:389`). So the
  worker reads each tiny file **once** into memory — that is why the threshold is
  small — and sends the buffer in both requests. Kubo will not mix a copy part into
  a nocopy request (T11a), so it has to be two requests.
- The unmanaged path lists keys without sizes (`service.go:1433`), so it decides
  "tiny" by reading up to threshold + 1 bytes.

Files between the threshold and one chunk — which for a low-bitrate rendition is
**every segment** — stay references and cost one add-time origin read each (T3
probe), so the source route must already answer for the row being added. If a gc
lands between the two requests the tiny files become references too: correct,
merely less resilient. Whether the pre-copy also removes those files' add-time read
is **[unverified]** — T11b did not count origin reads during its tree add.

**The client must stop trusting the status code** — fix F2 in section 6, required
here because a half-finished nocopy add leaves orphan references (T11a).

### 5.3 The source route (C, M)

`GET /ipfs-source/v1/<object key>`, mounted at the root beside `/metrics`
(`internal/httpapi/server.go:1455`): outside `/api/v1`, outside the OpenAPI
contract, outside the rate-limited group (`server.go:1440-1512`).

- **Always mounted.** `routes()` runs once at construction (`server.go:1441`) but
  the managed mode is changed live from Admin → IPFS; a route registered only "when
  reference mode is on" would let the worker pin rows whose every segment then
  404s until a restart. The gate below already answers 404 for an instance with no
  reference rows.
- **No authentication, because Kubo cannot send any**: boxo's urlstore calls
  `http.DefaultClient.Do(req)` with only a `Range` header added
  ([fsrefstore.go](https://github.com/ipfs/boxo/blob/main/filestore/fsrefstore.go)).
  **[sourced]** A presigned URL would expire and permanently break its blocks.
  `GET` only — the urlstore sends nothing else, so `HEAD` would be surface for
  nothing.
- **The gate is "bytes this instance serves anonymously right now"**, which is
  narrower than "already public". All of: the key lies under the **committed
  generation** of a reference-mode `hls` row on the public network
  (`source_generation`, `ipfs_admission.sql:43`, `:108-129`) — not under the row's
  intent key `streaming-playlists/<id>/`, which would also authorize superseded
  generations and the separately-ledgered `…/rN/vp9.webm` (`internal/media/vp9.go:70`);
  the row is `pending` or `pinned`; and the video passes, **at request time**, the
  same visibility facts the eligibility gate encodes (public, published, not
  blocked or quarantined, no DRM key — `eligibility.go:96-130`,
  `ipfs_admission.sql:111`). The live check matters because the ledger lags:
  `syncVideoMirror` is best-effort and swallows errors (`internal/httpapi/videos.go:1975-1983`)
  and converges only at `IPFS_RECONCILE_INTERVAL`, five minutes by default
  (`internal/config/config.go:1328`). **[read]** The decision may be cached
  in-process for a few seconds, no longer.
- **One canonical key.** The key is taken from the *decoded* path, canonicalized
  once, matched as "row prefix ending in `/`" + remainder, and that identical
  string is what reaches `storage.Open`. Both backends already reject empty,
  absolute, NUL and `..` keys (`internal/storage/s3.go:170-180`, `local.go:71-81`).
- **Never redirects, never cached.** Delivery elsewhere may 307 to a CDN, a
  presigned URL or the IPFS gateway itself; here that is a loop or an expiring
  reference. Responses carry `Cache-Control: no-store`, and the runbook says never
  to put this path behind a cache: a cached 200 outlives a takedown. It serves
  through the existing stored-object path (`serveStoredObjectNamed`,
  `internal/httpapi/videos.go:1578`), which already turns `Range` into ranged S3
  GETs (`internal/storage/s3.go:443-486`), with bounded read timeouts.
- **Limits, because this is where the cost constraint is won or lost.** Any IPFS
  peer can ask for any block; nothing is cached (T2); every read is a ledger
  decision plus a bucket round trip; and a ~200-byte HEAD to the gateway costs
  512 KiB of bucket egress (T12) — about **2,500× amplification**. The route cannot
  see which peer asked — its only client is the node — so limits are global and
  per-object, never per-peer: a byte-rate bucket, a request-rate limit, a
  concurrency semaphore, and a per-object share so one hot or hostile object cannot
  take the whole allowance. Above them sits a **daily egress budget that pauses the
  mirror visibly** (component state, log line, gauge) rather than starving reads at
  random; viewers then fall back as for any gateway failure. All of them ship with
  safe defaults; gate 3 tunes them.
- **Reachability.** Through the shipped Caddy config an unmatched path already
  falls to the frontend, which proxies nothing to the api, so an explicit `handle
  /ipfs-source/* { respond 404 }` is belt-and-braces — the same shape as the
  `/metrics` block (`deploy/Caddyfile:76-78`). Two things make it load-bearing
  anyway: the base compose file publishes the api on `0.0.0.0:8080`
  (`vidra-core/docker-compose.yml:1060`) and only the prod overlay pins it to
  loopback (`docker-compose.prod.yml:328-329`, which needs Compose ≥ 2.24); and
  production mounts a generated `deploy/Caddyfile.local` that `deploy.sh` checks but
  never re-renders (`deploy/deploy.sh:160-187`, `:228-283`). **[read]** So the
  renderer (`vidra-core/internal/setup/caddyfile.go`) gains the handle, **and**
  `deploy.sh` refuses to enable reference mode while `Caddyfile.local` lacks it.
- **Base URL:** `IPFS_SOURCE_BASE_URL`, default `http://api:8080`. The in-container
  port is the literal `HTTP_PORT: "8080"` (`vidra-core/docker-compose.yml:77`) that
  no operator env moves; nothing declares a network, so every service is on the
  project default, and the manager attaches its node to that network as external
  (`deploy/ipfs-manager.py:243`, `:248`). **[read]** **The base URL is written into
  every reference.** It can break without changing: the manager freezes project and
  network names (`ipfs-manager.py:251-274`), so a restore into a differently named
  directory leaves the node on a stale network where `api` no longer resolves. An
  equality check would pass. The mirror therefore runs a **startup reachability
  probe** — the api fetches one live key from its own route, and fetches one block
  of one reference row through the gateway, which proves the node → api path — and
  on failure refuses reference-mode adds (not the whole mirror) and says why.

### 5.4 One reference per block: the invariant (C)

This is the part of the design that can silently break videos, and the reason it
is a design and not a flag.

Because the first writer wins (T10), identical bytes reached through two object
keys share **one** reference — the first key's. A live pin is then left depending
on an object that is gone whenever:

1. **The media gc collects a superseded generation while the ledger still points
   at it.** `mediagc` decides what is referenced from `video_files` and
   `streaming_playlists` only and never reads `media_ipfs_pins`
   (`internal/mediagc/service.go:532`, `isReferenced` at `:599`). **[read]** In copy
   mode that is harmless — the node has its own bytes. In reference mode it removes
   them.
2. **Identical files live under two keys.** Init segments across videos (5.2's rule
   takes those out). Whole trees, if the same source is uploaded twice or deleted
   and re-uploaded — but only if two transcodes of one source are byte-identical,
   which is **[unverified]** and is a gate-4 measurement, not an assumption. If
   they are not, this case does not occur for HLS.

What the code already gets right, and the design relies on: video delete removes
the row, fires `onDelete` → `UnpinVideo`, and leaves the blobs to the media gc much
later (`internal/video/service.go:2215-2220`); `EvictColdIPFSPin` and
`SweepIneligible` touch only the ledger; and a storage migration *"copies each
object to the SAME key"* (`internal/storagemigration/service.go:23-30`). **[read]**

**Invariant: no reference may outlive the object it points at, and a row is
re-added only after its own old references are gone.** Two mechanisms keep it:

- **The media gc defers.** `isReferenced` treats any key under the committed
  generation of a live reference-mode row as referenced. The old generation becomes
  collectable only after the row has been withdrawn from it.
- **The withdraw procedure**, run by the worker whenever a reference-mode row is
  withdrawn or replaced (delete, block, privacy change, eviction, new generation):
  1. enumerate the row's leaves by walking its DAG with **non-recursive** `refs`,
     descending only into dag-pb CIDs and never opening a raw (`bafkrei…`) one.
     Every node opened is a real local block, so the walk should read zero origin
     bytes — T12 measured that for non-recursive `refs` on a file root and `ls` on a
     directory root; the multi-level walk is composed from those and is asserted by
     section 10's counters, not yet measured. (The obvious `refs?recursive=true`
     re-downloads the video.)
  2. `pin/rm` the root;
  3. `block/rm` the leaves in batches (T10). What is removed can no longer poison a
     later add. What is **refused** is still covered by another pin;
  4. for each refused leaf, ask where its reference points. T12 measured whole-store
     `filestore/ls` at zero origin bytes; the per-key `arg=` form is assumed local
     and must be confirmed. If it points under the generation being withdrawn, the
     covering pin has borrowed it, and that pin's ledger row is marked for **heal**;
  5. heal each such row with the sequence T10-iv measured end to end: unpin,
     `block/rm` the borrowed leaves, re-add from its own objects.

Two costs to state plainly. A heal takes an **unrelated, published** video off
IPFS for the length of its re-add because of someone else's takedown. And the
procedure is only as good as the list of callers: the implementation plan must
enumerate every flow that removes HLS objects, by file:line, the way the review of
this document did.

`filestore/verify` is **not** a periodic job: it re-downloads the store (T12) and
cannot take a root CID (T10). Section 5.7 is how a broken video is found instead.

### 5.5 Node configuration and the RPC boundary (C, M)

- **Unmanaged:** `vidra-core/deploy/ipfs-public/001-configure-network-mode.sh` sets
  `Experimental.UrlstoreEnabled` from the environment. It is bind-mounted into
  `/container-init.d/` (`docker-compose.yml:1306`) and re-runs on persisted repos by
  design (its own header, `:5-8`), so a restart applies it. **[read]**
- **Managed:** `ipfscontrol.HostConfig` gains one boolean and the manager's
  `public_config()` (`deploy/ipfs-manager.py:229-235`) writes it. This respects the
  boundary stated at `internal/ipfscontrol/config.go:25` — *"URLs, images, mount
  paths and commands deliberately cannot cross this boundary"*: only a boolean
  crosses; the URL travels core → Kubo inside the add request. `public_config()`
  only `setdefault`s its own keys, so an older manager does not clear the flag.
- **The flag is never turned off while reference rows exist.** Core does not ask
  for it to be cleared while any row is in reference mode, and the init script only
  ever sets it.
- **Fail closed.** If the node rejects `nocopy` (T0), the row fails with a closed
  error code and the admin page says the node is not configured for references.
  Core **never falls back to a copy add**: that would quietly fill the disk.
- **RPC authorization is a precondition of the flag.** With the urlstore on,
  whoever can reach the Kubo RPC can make the node fetch arbitrary URLs *and read
  the result back as blocks* — a read-SSRF from the node's network position,
  link-local metadata endpoints included. Today the RPC is published on host
  loopback (`vidra-core/docker-compose.yml:1301`; `ipfs-manager.py:242`), which
  means every local account; the managed node sits on the **application's** network
  with the frontend, caddy, worker and search; and no RPC authorization is
  configured anywhere. **[read]** Reference mode does not switch on until the RPC
  requires a credential (Kubo's `API.Authorizations`, to be confirmed on v0.43.0
  **[unverified]**) or the node is on a network only core shares.
- The pinned image stays `ipfs/kubo:v0.43.0`. v0.43.1 exists; bumping it is a
  separate decision (AGENTS.md hard rule 7).

### 5.6 Mode, conversion, rollback, restore (C, M)

- **Mode** is `copy` (default) or `reference`, per instance, for the public
  network's `hls` rows. Managed instances set it in the policy document on Admin →
  IPFS; unmanaged instances set `IPFS_PIN_STORAGE`. Each ledger row records the
  mode it was added in (new column; migration number assigned when the PR opens —
  0151 is the newest today), because the withdraw procedure and the admission
  arithmetic differ by row, and a node legitimately holds both kinds at once.
- **Conversion is not a re-add.** A nocopy re-add over copied blocks reports
  success and reclaims nothing (T5). What T5 measured is `pin/rm` → `repo/gc` →
  nocopy re-add, CID unchanged — and `repo/gc` is global. The per-row route this
  design wants (enumerate with recursive `refs`, which is free while the blocks are
  local copies; `pin/rm`; `block/rm`; nocopy re-add) is T10's heal transposed to
  copy blocks and is **not yet measured**. Blocks another pin still covers are
  refused and stay copies, which is harmless: a copy cannot rot.
- **The row is held for the whole conversion.** `VerifyPins`
  (`internal/ipfsmirror/verify.go:119`) → `RearmLostIPFSPin`
  (`media_ipfs_pins.sql:508-526`) re-arms a `pinned` row whose CID the node does not
  hold — exactly the state between the unpin and the re-add — and the drain would
  then race a competing add. Conversion takes the row's claim/lease
  (`AdmitIPFSPin`, `ipfs_admission.sql:40-47`) first, or moves it out of `pinned`.
- It runs as a tracked, stoppable backfill paced by `copy_bytes_per_second`. **The
  row is off IPFS between its unpin and its re-add**; normal delivery is unaffected.
- **What it costs in bucket traffic.** Every converted byte is read from primary
  storage once (one object GET per file). Afterwards every byte the mirror serves
  is bucket egress, which today it is not: that is the trade this mode makes, a
  one-time disk cost for a per-read egress cost, and what 5.3's limits bound. Beta's
  bucket is Backblaze B2 behind a Cloudflare endpoint (`deploy/IPFS-MANAGER.md:78-79`);
  B2's published allowance is free egress up to three times average stored data
  **[sourced by the research for this document; not re-fetched]**.
- **Rows evicted for capacity return.** Conversion re-arms
  `capacity_reason = 'evicted_capacity'` rows once: the budget that evicted them no
  longer binds.
- **There is a rollback floor, and today nothing enforces one.** An api image from
  before the source route makes *every* reference block unreadable while
  `/admin/system` still says `ok`, and its deletes skip the withdraw procedure, so
  rolling forward again inherits dangling references. `rollback.sh` knows one floor,
  `MIN_EMBEDDED_MIGRATE_TAG` (`deploy/rollback.sh:62`, `:133-142`). **[read]**
  `rollback.sh`, `deploy.sh` and `restore.sh` gain `MIN_IPFS_REFERENCE_TAG` and
  refuse to go below it while any row is in reference mode. Switching the *mode*
  back to `copy` is always safe: new adds copy, existing reference rows keep
  working, and converting them back is the same procedure in the other direction.
- **Restore.** Onto a new host with an empty node: the ledger says `pinned`, the
  node holds nothing, the reconcile tick re-arms and the drain re-adds by reference
  — it recovers by itself, re-streaming the public HLS library from the bucket
  once. With a node volume *newer* than the ledger, or after the fresh-repo
  fallback, per-row heal does not scale: an admin **"re-index all reference rows"**
  action runs the withdraw-and-re-add over the whole ledger as a tracked run.

### 5.7 Admission, and how a broken video is found (C)

Budget, free-space floor, reservations, pacing, demand pins and eviction all stay.
The reservation for a reference row changes from `2 × bytes + …`
(`admission.go:110`) to the index cost plus the tiny files that are copied —
**placeholder `bytes / 256 + tiny_file_bytes + 16 KiB × files + 1 MiB`**, to be
replaced by a measurement on a real HLS tree. Note the per-file term dominates it
for a tree of 1–2 MiB segments. Reservations are transient; what fills the budget
is actual repo growth — 0.094 % for one large file (T1), higher and **unmeasured**
for a tree. If that ratio is even several times worse, the disk budget stops being
the limit by about two orders of magnitude.

**The ceiling moves; it does not vanish.** Reference mode still streams every byte
through the add (T1), so the other limiter is untouched: `admission.go:221` refuses
a row whose bytes cannot be read within ~24 h at `copy_bytes_per_second / workers`,
and at beta's 2 MiB/s (`deploy/IPFS-MANAGER.md:72-73`) indexing 5 TiB is about a
month of continuous paced reading. And the disk budget was also the only brake on
an **anonymous** trigger: `POST /api/v1/videos/:id/playback-session` is
`optionalAuth` (`server.go:1844`) and calls `DemandPublicVideo`
(`playback_session.go:142-148`), tagging any public video for a demand pin that
reads the whole tree from the bucket. **[read]** Reference mode therefore adds a
bytes-admitted-per-day brake that does not depend on disk.

**Finding a broken video.** Kubo's read error is generic (`failed to fetch all
nodes`, T4) and there is no periodic verify. So:

- **A 404 on the source route is the canary.** It means a live reference points at
  a key the gate no longer covers — the signature of 5.4 failing.
  `vidra_ipfs_source_requests_total{result}` and `vidra_ipfs_source_bytes_total`
  are required metrics, and a non-zero 404 rate is reported by the `ipfs` component
  and by `vidra doctor`.
- Each reconcile tick fetches **one block of one reference row** through the
  gateway, rotating through the ledger — a sampled end-to-end check that costs one
  block of egress per tick.
- An admin "re-index this video" action is the manual repair.

### 5.8 Out of scope

- **Every media class except `hls`** (top of section 5).
- **The private swarm stays in copy mode.** Its source route would serve
  non-public bytes without authentication; its replicas copy regardless.
- **The chunk size stays 256 KiB.** 1 MiB chunks cut origin requests four-fold
  (T7) but change every CID, and "the mode never changes a CID" is what makes
  conversion and rollback safe. Section 12, D3.
- No change to delivery, to the gateway probe, or to which media classes are
  pinned.

## 6. Fixes that stand on their own

Each is a small PR that is worth shipping if reference pinning is never built. The
order matters: the brake and the gauge go in before the fix that admits more.

| # | Fix | Why |
|---|---|---|
| F2 | Read `X-Stream-Error`, and require the wrap entry, in `ipfs.Client.add` | Kubo reports a late add failure as HTTP 200 plus a trailer (T11a) and the client returns the last hash it saw (`client.go:186-211`) — for a wrap add, a segment's CID recorded as the tree's root. `c.post` (`client.go:345-364`) returns only `resp.Body`, so it must hand back the response; Go fills `resp.Trailer` only after the body is read to EOF, and the scanner's 1 MiB line cap (`client.go:188`) can abort before EOF — an unread trailer is a failure, not a pass. T3 shows the wrap entry as `Name: ""`; the code comment at `client.go:154-156` says otherwise, so the PR pins it with a real-Kubo test. Whether a copy-mode add that runs out of disk mid-tree takes this path is **[unverified]** — but a full disk is exactly when it would |
| F4 | Make a capacity pause visible outside Admin → IPFS | `/admin/system` reports `ok` on a full budget (`system_ipfs_managed.go:29-68`), there is no capacity WARN in the logs, and no metric carries `repo_used_bytes` or the budget. Add gauges and one log line per pause transition. How `/admin/system` shows it needs vidra-user's input: a component that turns `degraded` demotes the whole page, which has broken that repo's backed test harness before |
| F3 | Give unmanaged mode a ceiling | The legacy drain has none (`service.go:1196-1243`). A `repo/stat`-based budget (`IPFS_REPO_BUDGET_BYTES`) that pauses the drain with the same `capacity_reason` vocabulary. Core cannot `statvfs` an unmanaged node, so this is a repo-size budget, not a free-space floor, and `ipfs_data` shares a filesystem with Postgres, media and transcode scratch (`docker-compose.prod.yml:620-628`): the runbook must say the budget sits below disk − database growth − scratch |
| F1 | Replace the `2 ×` reservation with a measured factor | T5 measured a copy add of 67,108,864 bytes growing the repo by 68,031,550 — **1.014 ×**. One sample of incompressible data; measure a real HLS tree, then set the factor with stated headroom. At ~1.1 × the same disk admits nearly twice the media — which is why it ships after F4 and F3 |
| F5 | Tell the mirror when a pinned object is deleted or replaced | Found while reviewing this design, and a takedown gap in copy mode today **[read, untested]**: caption delete removes the blob and the row and never unpins (`internal/video/captions.go:125`), so a deleted caption stays pinned and retrievable; avatar replacement deletes before it unpins and skips both on a same-key replacement (`internal/profileimage/service.go:449-451`); a replaced poster or storyboard leaves the old bytes pinned under the old CID (`internal/video/service.go:1724`, `:1670`) |

## 7. Failure handling

The fallback in every case is today's behaviour for a video that is not on IPFS:
normal delivery.

| Situation | Behaviour |
|---|---|
| Node has the urlstore flag off | Add fails closed (T0); row fails with a closed code; **no copy fallback** |
| Primary storage, Postgres or the api unreachable | The source route cannot answer; Kubo's read fails fast when refused (T4a) and recovers by itself; tiny files keep serving from the node. A bucket that *stalls* is untested — gate 3 |
| Object changed under a live reference | Zero wrong bytes served (T4b). Cannot happen to an immutable HLS generation; the classes where it can are out of scope |
| Video deleted, blocked or made private | The live visibility check 404s the route at once; the ledger follows; then the withdraw procedure (5.4). Tiny files remain real blocks until unpin + gc, and blocks other peers already fetched are beyond reach — as today |
| Identical bytes under two keys | 5.4: the lender's withdrawal heals the borrower |
| Media gc wants a generation a reference row still uses | It defers (5.4) |
| Add stream fails midway | F2 fails the row; orphan references are unpinned and the next gc removes them (T11a) |
| Node cannot reach the source URL | Startup probe fails; reference-mode adds are refused with the reason; existing rows fall back to normal delivery |
| A limit or the daily egress budget is hit | The mirror reports itself paused; the requesting peer retries; viewers on the operator's gateway fall back |
| App rollback below the floor | `rollback.sh` refuses while reference rows exist (5.6) |
| Kubo is never updated again | The image is already pinned, and nothing here needs a newer one |

## 8. Security

- **What the route serves:** bytes this instance serves anonymously *right now* —
  HLS of public, published, unblocked, non-DRM videos, checked live at request time
  and scoped to the committed generation. That is strictly narrower than "already
  public", and originals are excluded precisely because the two differ for them.
- **The RPC boundary becomes load-bearing.** 5.5: with the urlstore on, RPC access
  is read-SSRF from the node's network position, and today that boundary includes
  every local account and every container on the application network. RPC
  authorization or a core-only network is a precondition, and section 10 adds the
  negative test that a **filesystem** `Abspath` is refused while
  `FilestoreEnabled=false`. A 307 from the source is followed (T4d); the source is
  our own api and never redirects, so that is not an open redirector.
- **Amplification** is ~2,500× (a gateway HEAD → 512 KiB of egress) and the limits
  in 5.3 are the control. A single global bucket would itself be a denial of
  service against real viewers, hence the per-object share and the visible pause.
- **Withdrawal, with its qualifiers.** Media segments stop resolving when the live
  visibility check fails, which is faster than today's wait for a gc. But tiny
  files stay real blocks until unpin + gc; blocks other peers already hold are
  untouched; and a takedown can briefly take an unrelated borrowing video off IPFS
  while it heals.
- **What the node's datastore now holds:** internal URLs containing object keys —
  video and user UUIDs, no filenames, no credentials, no presigned query strings.
  `filestore/ls` is RPC-only and `Gateway.NoFetch=true` in both network modes
  (`001-configure-network-mode.sh:53`, `:73`). A copy of the datastore is
  nonetheless an inventory of public object keys.

## 9. Surfaces

- **Admin → IPFS (U):** the mode select (managed instances), a line reading "N
  videos stored as copies · M as references · index X of budget Y", the conversion
  run with Stop, "re-index this video" and "re-index all", and the mirror's paused
  state with its reason. No new page.
- **Environment (C):** `IPFS_PIN_STORAGE`, `IPFS_SOURCE_BASE_URL`, the route's limit
  knobs, `IPFS_REPO_BUDGET_BYTES` (F3). The consumers land in
  `vidra-core/docker-compose.yml` beside `HTTP_PORT`, as plain `${VAR:-}`
  pass-throughs — a compose fallback value would shadow the Go default. The meta
  repo cannot declare `api`/`worker` env, and `docker-compose.override.yml` is not
  loaded by `deploy.sh` (`deploy/lib.sh:113-115`), so a consumer added there would
  work locally and not exist on the host. `env/production.env.example` (M)
  documents them.
- **Deploy (M):** the Caddy handle in the renderer and the `Caddyfile.local`
  refusal (5.3); `MIN_IPFS_REFERENCE_TAG` (5.6); the manager's boolean (5.5).
- **Runbook (M, C):** `deploy/IPFS-MANAGER.md` and `vidra-core/docs/operations.md`
  gain the mode, the base-URL and renamed-project warnings, the RPC precondition,
  "never cache this path", the rollback floor, and the statement that a
  reference-mode mirror depends on primary storage, Postgres **and** the api.

## 10. Testing and the gates before beta

A mocked-green suite is not accepted as evidence that this works; the behaviour
that matters lives in Kubo.

- **Real Kubo, in core's existing IPFS integration lane:** nocopy add of an HLS
  tree; CID equality with copy mode; the tiny-file rule under `limitedSource`'s
  one-open constraint; the trailer check (a part with no `Abspath` placed last);
  fail-closed with the flag off; a filesystem `Abspath` refused; and 5.4's cases —
  media gc against a row still on the old generation, and identical bytes under two
  keys with the lender withdrawn — each ending with every segment fetched through
  the gateway.
- **Origin-read accounting:** the source route counts requests and bytes, and the
  tests assert **zero** origin bytes for the withdraw walk on a multi-level tree,
  for `filestore/ls?arg=`, for the reconcile tick (`pin/ls`) and for gc — the
  guard against anyone reaching for `refs -r`, and the measurement 5.4 still owes.
- **Source route:** 404 for a key outside the committed generation, for
  `vp9.webm`, for a private-network row, for a row in `unpinning/unpinned/failed`,
  and for a video that has just been blocked while its row still says `pinned`;
  encoded-slash, `..` and double-encoding cases; never a redirect; `no-store`; each
  limit. Reviewers mutation-test each guard: revert the clause, a test must fail.
- **Conversion:** copy → reference → copy on one row with the CID unchanged, the
  repo size moving as expected at each step, and a `VerifyPins` tick fired inside
  the window.
- **Deploy:** `rollback.sh` refuses below the floor with a reference row present;
  restore into a renamed project directory trips the reachability probe.

**Gates, recorded in `docs/` before the mode is enabled on beta:**

1. **Reprovider.** On a networked private test swarm, origin bytes read over one
   full provide cycle under the manager's `Provide.Strategy = pinned+unique`. The
   spike could not run this. If it is not zero, the design does not ship as is.
2. **Remote retrieval.** A second peer fetches a reference-pinned tree over
   bitswap, byte-exact.
3. **Real object storage.** Against MinIO and one real provider: time to first
   frame and steady-state segment latency through the gateway, copy vs reference;
   origin requests per viewer-minute; add-time cost of a low-bitrate rendition
   whose every segment fits one chunk; the cost of a hostile HEAD loop under the
   limits; and a bucket that stalls rather than refuses. T8's localhost numbers say
   nothing about any of this.
4. **The measurements the placeholders wait on:** index size of a real HLS tree;
   the reservation factors; the tiny-file threshold; whether init segments are
   byte-identical across videos; whether two transcodes of one source are.
5. **Resource envelope.** Kubo RSS, CPU and file descriptors under the production
   limits — `cpus 1.0` / `mem_limit 1g`, which the manager hardcodes with no env
   seam (`deploy/ipfs-manager.py:240`) — at the concurrency the limits permit. The
   spike ran unlimited. Raising the managed envelope would be a manager change.

## 11. PR sequence

Small PRs, each merged before the next. Section 6 goes first because it helps
today and does not depend on any decision in section 12.

1. C — F2, the trailer and wrap-entry check in `ipfs.Client.add`.
2. C + M — F4, capacity gauges, the pause log line, the `/admin/system` decision.
3. C + M — F3, the unmanaged repo budget and its runbook line.
4. C — F1, the measured reservation factor, with the measurement recorded.
5. C — F5, mirror hooks for caption delete, avatar replace, poster and storyboard
   replace.
6. C + M — the RPC precondition: authorization or a core-only network for the node.
7. C — `SourceURL` on `DirEntry`, the tiny-file pre-copy, the mode column; no
   caller sets it yet.
8. C + M — the source route: its gate, its limits and metrics, the Caddy handle in
   the renderer, the `Caddyfile.local` refusal.
9. C — the media-gc deferral, the withdraw procedure and heal, with 5.4's cases on
   real Kubo.
10. C + M — node configuration (init script, `HostConfig`, manager, fail closed)
    and the startup reachability probe.
11. M — `MIN_IPFS_REFERENCE_TAG` in `rollback.sh`, `deploy.sh`, `restore.sh`, and
    the runbook. **Before** the mode can be switched on.
12. C + U — mode setting, reference-mode admission and the per-day brake,
    conversion and re-index runs, admin surface.
13. M — the five gates, recorded; then the beta decision.

The mode defaults to `copy`, so a release containing any prefix of this list is
safe to deploy.

## 12. Decisions the owner has not made

- **D1 — Is a mirror that depends on the rest of the stack acceptable?** In
  reference mode the mirror depends on primary storage **and on Postgres and on the
  api container**: the gate is a database decision and the bytes are served
  in-process. A Postgres restart, a migration window or `up -d` recreating the api
  takes every reference-pinned video off IPFS — events the mirror survives today.
  The existing doctrine points this way — `vidra-core/docs/operations.md:1404-1406`:
  *"**The pinset is a distribution surface, never a backup.** Do **not** back up
  the Kubo datastore for durability — it holds only re-derivable copies of
  already-public bytes"* — but that sentence was written about backups, not about
  this, and it is the owner's call.
- **D2 — How much to build, given section 4?** Section 6 alone (PRs 1–5) roughly
  doubles what today's disk pins, makes the stop visible, and closes a takedown
  gap. PRs 6–13 remove the ceiling and carry the complexity of 5.3–5.6 on an
  upstream that is winding down, in exchange for bucket egress that must be
  limited.
- **D3 — Chunk size.** Stay at 256 KiB (recommended here: CIDs never change), or
  use 1 MiB for rows that have never been pinned (four times fewer origin requests,
  at the price of a per-row chunker record and CIDs that differ by vintage).
- **D4 — Which mode does beta run?** `IPFS_MANAGED_NODE` and the live
  `admission_paused_reason` are in the untracked env file and the database, not in
  either repo. The answer decides whether F1 or F3 is the fix beta feels first.

## 13. Risks and open items

- **5.4 is the risk.** It is correct only if every flow that removes or replaces an
  HLS object is covered by the media-gc deferral or the withdraw procedure. The
  review of revision 1 found four uncovered flows in an afternoon — all in classes
  now out of scope, which is the argument for the narrow scope, not proof that HLS
  has none.
- **Composed, not measured:** the multi-level non-recursive walk, per-key
  `filestore/ls`, and per-row conversion by `block/rm` (5.4, 5.6). Each is asserted
  by a counter in section 10 before anything depends on it.
- **Parsing `block/rm` refusals.** Step 3 of 5.4 learns which pin covers a block
  from Kubo's error text; `pin/ls?arg=<leaf>&type=all` is the structured
  alternative and must be compared on large pinsets.
- **What the player does mid-stream is unknown.** How the watch page chooses and
  abandons the gateway origin was not read for this document **[unverified]**. If
  it decides once, on the master playlist, then a tree whose playlist resolves and
  whose segments fail is the worst case for it — and tiny files staying local makes
  exactly that case more likely. A fatal segment error on the gateway origin must
  fall back to normal delivery. A vidra-user question for the plan.
- **Serving speed against a real bucket is unmeasured** (gate 3). Each block is a
  ranged GET through the api; at 256 KiB a 2 MiB segment is eight of them plus one
  of readahead.
- **Experimental upstream features, unmaintained upstream.** The filestore has
  been in-tree since 2017 with sharness coverage for directory adds;
  [kubo#7161](https://github.com/ipfs/kubo/issues/7161) tracks it as an unstable
  experiment, and the `--nocopy` + `--fscache` hang it lists (kubo#5815) is closed.
  This design never passes `fscache`. **[sourced]**
- **Mechanisms are behavioural.** The single-chunk add-time read and the one-block
  readahead were observed, not explained from Kubo's source.

## 14. What review changed (revision 1 → 2)

- **False in revision 1:** that a full Kubo repo cannot gc. kubo#5041 was closed on
  2026-02-10 after `ipfs repo gc` was shown to work on a full flatfs disk; the fix
  predates the pinned v0.43.0. Removed from sections 2 and 6.
- **False in revision 1:** "no new bill". The disk cost becomes bucket egress.
- **Wrong scope:** revision 1 referenced every media class. Narrowed to `hls`
  (in-place replacement, missing mirror hooks, and originals outliving
  `downloads_enabled`). Those findings became F5.
- **Wrong hazards:** revision 1's three 5.4 scenarios were guesses. The real one is
  the media gc never reading the pin ledger; byte-identical transcodes are
  unverified and now a measurement.
- **Unbuildable as written:** the tiny-file pre-copy against `limitedSource`'s
  one-open rule; a route registered only when the mode is on; an F2 that could not
  reach `resp.Trailer`.
- **Too weak:** the gate (ledger state only → live visibility + committed
  generation), the limits (one byte bucket → rate, concurrency, per-object, visible
  pause), the base-URL check (equality → reachability probe), the SSRF note
  (description → precondition), D1 (storage → storage, Postgres and the api).
- **Missing:** the rollback floor, the Caddy renderer and `Caddyfile.local`, env
  consumers in the right repo, the resource-envelope gate, diagnosability, the
  per-day admission brake against anonymous demand pins, F-ordering.
- **Overclaimed:** three "zero origin bytes" statements and the conversion route
  were composed from separate measurements; the 5 TiB figure ignored its own
  per-file term; several quotes were trimmed. All corrected and tagged.
