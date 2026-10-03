# The IPFS mirror and the disk: pin less first, pin by reference maybe — design

Date: 2026-09-20 · Status: **draft for discussion — not approved, not planned, not
built** · Repos: vidra-core (C), vidra (M), vidra-user (U)

Every claim below is tagged by how it is known: **[read]** in the code at
vidra-core `400c1a8` / vidra `79a84cd` with file:line, **[measured]** in the lab
spike recorded beside this document
(`docs/evidence/ipfs-reference-pinning-spike-2026-09-20/`), **[sourced]** from a
URL fetched on 2026-09-20, or **[unverified]**. Nothing here is an owner ruling;
section 12 lists the decisions the owner has not made.

This is revision 3. Revisions 1 and 2 were each reviewed by four independent
readers (backend, security, infrastructure, evidence audit) and each review found
claims that were false and mechanisms that could not work. Section 14 lists them.
That history is itself a finding, and it shapes the recommendation.

## 1. What this is, and what it recommends

The owner asked, on 2026-09-20: *"is there a way to possibly mount S3 instead to
help pin IPFS videos instead of paying for a large volume?"*, under the constraint
*"without extra incurred cost or great effort on part of the admin"*, because *"at
the moment, pinning stops at a point on local disk"*.

1. **Mounting S3 under the IPFS node does not work** (section 3).
2. **The mirror pins roughly 2.7 times the bytes a player can ever ask it for, and
   reserves twice that again** (section 2). Pinning only what plays and reserving
   what is measured should let the same disk hold about **five times** the video —
   by construction, not yet by measurement — with no new mechanism, no new
   cost and nothing for the operator to do. That is **Tier A** (section 5): six
   small fixes, each worth shipping alone. **This document recommends Tier A now.**
3. **Removing the ceiling altogether is possible**: Kubo can keep references to
   bytes vidra already stores instead of a second copy. That is **Tier B**
   (section 6). The lab spike shows the mechanism works and the CIDs do not change.
   Two review rounds show it is not a flag: it needs a new unauthenticated route, a
   withdraw procedure that must hook every deleter of HLS objects, an RPC credential
   the host manager cannot carry today, and it turns a disk cost into bucket egress
   that has to be limited — on an upstream that loses its maintainers on 2026-09-30
   (section 4). **This document recommends deciding Tier B only after Tier A has
   been measured on beta** (section 12, D2).

## 2. Why pinning stops today

**Every pinned byte is stored twice.** Primary storage stays authoritative
(`internal/ipfsmirror/classes.go:1-9`) and Kubo holds a full second copy: the add
is a plain `POST /api/v0/add?pin=true&cid-version=1&raw-leaves=true`
(`internal/ipfs/client.go:139-153`) with the bytes streamed from the storage
backend into a multipart body (`internal/ipfsmirror/service.go:1590-1630`,
`internal/ipfs/client.go:158-180`) — never staged on scratch. In managed mode the
stream is paced and bounded by `limitedSource` (`limited_source.go:69-173`,
`admission.go:342-350`); the legacy drain reads the backend directly. **[read]**

**And the tree it pins is roughly 2.7 times what plays.** Per public video the
mirror wrap-adds the promoted HLS generation directory (`service.go:1420-1468`),
taking every key under it except `vp9.webm` (`service.go:1433-1448`). That directory
also holds, in every rendition, `video.mp4` and `video-only.mp4` — *"the two
required progressive MP4 assets for a rendition"*, remuxed from it without
re-encoding (`internal/media/cmaf.go:627-651`; names at `internal/media/hls.go:28-32`,
keys at `:1011-1022`) — and, when the source has audio, one `audio.m4a` beside the
master. Both packagers always emit the two MP4s, under the pinned prefix, with no
setting or lean mode that skips them (`internal/media/packager.go:497-501`, `:531`;
`cmaf.go:513-517`, `:530`). Each MP4 is about the size of the rendition it was
remuxed from; the audio asset is one shared track. Counting the all-intra
trick-play renditions (`hls.go:679-681`, `:831-846`) as playback, which they are,
the tree works out to **2.6–2.8 times the playback bytes for a single H.264
ladder**, falling toward ~2.2 when HEVC or AV1 representations are enabled, since
the downloads stay H.264-only (`cmaf.go:474-482`). **[read; computed, not
measured]** No playlist references those files and nothing resolves them through
the mirror: the gateway URL handed out is the master only
(`internal/ipfsmirror/playback.go:43`), delivery deliberately has no mirror class
for downloads (`internal/httpapi/delivery.go:38-42`), and the frontend uses only
the master URL. The code's own comment says the intent is *"a clean
playlists+segments tree"* (`service.go:1445-1446`). Thumbnail, storyboard, VTT
and captions are pinned as separate rows; the original and the WebM are deferred
while a ready HLS tree exists (`admission.go:196-207`).

Four independent mechanisms can then stop pinning: **[read]**

| # | Mechanism | Where | What the operator sees |
|---|---|---|---|
| 1 | Managed-mode admission refuses the pass when `repo_used > budget_bytes` or `filesystem_free < min_free_bytes` | `admission.go:166`; re-asserted per claim in `ipfs_admission.sql:36-37` | `admission_paused_reason` on Admin → IPFS (`internal/ipfscontrol/runtime.go:112-138`) |
| 2 | The reservation is `2 × bytes + 16 KiB × files + 1 MiB` | `admission.go:110` ("Include ample UnixFS/chunk/directory overhead and never assume deduplication") | A budget that stops admitting at about half its nominal figure |
| 3 | The host manager sets `Datastore.StorageMax = budget_bytes`, which Kubo treats as a soft GC trigger | `deploy/ipfs-manager.py:229-235`; `deploy/IPFS-MANAGER.md:75-78` | Nothing — it is not a ceiling |
| 4 | **Unmanaged mode has no admission at all**: the legacy drain is unbounded, the compose service sets no `--enable-gc` and no `StorageMax` | `service.go:1196-1243`; `vidra-core/docker-compose.yml:1286-1312` | The volume fills. `ipfs_data` is a named volume (`vidra-core/docker-compose.yml:1303-1304`), so unless the operator moved it, it shares the Docker data root with Postgres and the media scratch |

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
follows from the news: **keep the IPFS investment small, config-shaped and
reversible, on the Kubo version already pinned; do not write an IPFS server of our
own.** Filestore and urlstore have been in-tree and "experimental" since 2017, and
a frozen Kubo is unlikely to remove them, but equally unlikely to fix a bug in them.

## 5. Tier A — fixes that stand on their own

Each is a small PR. In this order, because the fixes that shrink and brake go in
before the one that admits more.

| # | Fix | Why |
|---|---|---|
| F2 | Read `X-Stream-Error`, and require the wrap entry, in `ipfs.Client.add` | Kubo reports a late add failure as HTTP 200 plus a trailer (T11a) and the client returns the last hash it saw (`internal/ipfs/client.go:186-211`) — for a wrap add, a segment's CID recorded as the tree's root. `c.post` (`client.go:345-364`) returns only `resp.Body`, so it must hand back the response; Go fills `resp.Trailer` only after the body is read to EOF, and the scanner's line cap (`client.go:186`) can abort before EOF — an unread trailer is a failure, not a pass. T3 shows the wrap entry as `Name: ""`; the code comment at `client.go:154-156` says otherwise, so the PR pins it with a real-Kubo test. Whether a copy-mode add that runs out of disk mid-tree takes this path is **[unverified]** — but a full disk is exactly when it would |
| F6 | **Pin only what plays** | Section 2: the wrap-add takes every key under the generation but `vp9.webm`, so each rendition's `video.mp4` and `video-only.mp4` and the `audio.m4a` ride along — well over half the tree. The wrap-add should admit only what the HLS handlers serve, defined in one place so the mirror and the handlers cannot drift. Three things the definition must get right **[read]**: it matches the **relative path** (rendition directory + file), not the basename; it covers native trees through `hlsFileName` / `hlsCMAFFileName` plus the master (`internal/httpapi/hls.go:75-76`); and it keeps a branch for imported PeerTube trees, which are mirrored on purpose (`internal/ipfsmirror/lookups.go:107-116`), are served by the looser `hlsPeerTubeFileName` (`hls.go:77`) and whose master *"need not be master.m3u8"* (`internal/ipfsmirror/playback.go:20`) — without it every file of such a tree is excluded and the pin fails as `hls tree is empty` (`service.go:1462-1468`). The same filter must go into `admissionInventory` (`admission.go:69-78`), which carries its own copy of the `vp9.webm` exclusion and both sizes the reservation and bounds the copy source (`limited_source.go:69-77`) — filter only `pinDirectory` and managed mode still reserves for files it never adds. There is a second reason to do this: those are files the instance otherwise serves only under its download policy (`internal/httpapi/downloads.go:56-82`), which the mirror does not read. **Nothing consumes them through the mirror** (section 2), so F6 breaks no consumer. Existing rows need a **new** re-pin backfill: `Reconcile` re-arms only `failed` rows (`service.go:1703-1714`), `rearmLatestHLS` fires only when the master key changed (`admission.go:413-425`), and `RepinIPFSObject` (`media_ipfs_pins.sql:112-126`) is the right lever with one caller today. Until its turn comes a row keeps serving from its old root; the re-add is cheap because retained files re-chunk to identical CIDs; the freed blocks return only on a gc (`IPFS_GC_AFTER_UNPIN` defaults to false, `internal/config/config.go:1330`) |
| F4 | Make a capacity pause visible outside Admin → IPFS | `/admin/system` reports `ok` on a full budget (`system_ipfs_managed.go:29-68`), there is no capacity WARN in the logs, and no metric carries `repo_used_bytes` or the budget. Add gauges and one log line per pause transition. How `/admin/system` shows it needs vidra-user's input: a component that turns `degraded` demotes the whole page, which has broken that repo's backed test harness before |
| F3 | Give unmanaged mode a ceiling | The legacy drain has none (`service.go:1196-1243`). A `repo/stat`-based budget (`IPFS_REPO_BUDGET_BYTES`) that pauses the drain with the same `capacity_reason` vocabulary. Core cannot `statvfs` an unmanaged node, so this is a repo-size budget, not a free-space floor: the runbook must say it sits below disk − database growth − scratch |
| F1 | Replace the `2 ×` reservation with a measured factor | T5 measured a copy add of 67,108,864 bytes growing the repo by 68,031,550 — **1.014 ×**. One sample of incompressible data, and `repo/stat`'s RepoSize excludes flatfs slack and inodes: measure a real HLS tree, keep the `16 KiB × files` and `1 MiB` terms, then set the factor with stated headroom. `admission.go:110` is the only place it is computed, and it is not the copy bound (`admission.go:338-341`), so under-reserving weakens the budget gate between host polls, not the transfer. It ships after F4 and F3 because it admits more |
| F5 | Tell the mirror when a pinned object is deleted or replaced | Found while reviewing this design **[read, untested]**: caption delete removes the blob and the row and never unpins (`internal/video/captions.go:114-128`), so a deleted caption stays pinned and retrievable; a replaced poster or storyboard keeps its key, and `fireMediaReplaced` exists *"for exactly one consumer: CDN invalidation"* (`internal/video/service.go:493-520`, `:1670`, `:1724`), so the old bytes stay pinned under the old CID; avatar replacement does unpin the old key, but skips both delete and unpin when the key is unchanged (`internal/profileimage/service.go:448-451`) |

**What Tier A should buy.** Today a budget `B` admits about `B / 2` of a tree that
is about 2.7 times the playback bytes — roughly `B / 5.4` of playable video. After
F6 and F1 it admits about `B / 1.1` of a tree that is only playback bytes. **About
five-fold (4.5–5.5) for a single H.264 ladder, nearer three-fold with HEVC or AV1
representations on — by construction; the first thing to do after F6 and F1 is
measure it on beta** and record the number in `docs/`.

## 6. Tier B — reference pinning (a gated option)

```
   worker (as today)                         Kubo node                    viewer / peer
   storage.Open(key) ──stream──▶ POST /api/v0/add?nocopy=true
                                 part header  Abspath: <source URL>
                                 hashes the bytes, keeps the DAG nodes,
                                 stores leaves as {URL, offset, length}
                                                 │                 GET /ipfs/<cid>/…
                                                 │◀────────────────────────┘
   api: GET /ipfs-source/v1/<secret>/<key> ◀─────┘  re-hashes each block, serves it
        playback filename, live generation of a reference row,
        video still served anonymously?   ── no ──▶ 404
        serveStoredObject (Range → ranged S3 GET), under the route's limits
```

**Scope: locally transcoded HLS trees, and nothing else.** A row qualifies only if
its class is `hls` **and** its tree prefix is one vidra's own transcoder minted
(`HLSPrefixForGeneration`). Out: every other media class; and imported trees — a
PeerTube reference-mode import keeps the source instance's layout
(`internal/ipfsmirror/lookups.go:111-115`) in the **source instance's bucket**
(`internal/mediagc/service.go:601-610`), which is neither immutable nor ours.
**[read]** Generation-0 rows, whose tree prefix is the whole per-video directory,
are out until the plan shows nothing else is ever written under it. The reasons the
other classes are out are the ones review found: a poster or storyboard is replaced
at a stable key with the mirror never told, caption delete has no mirror call (F5),
and an original stays `pinned` after `downloads_enabled` is switched off, because
that catalogue walk (`internal/cdnpurge/cdnpurge.go:21-25`, `:71`) never touches
`media_ipfs_pins`. A reference to a key whose bytes changed serves nothing, forever
(T4b). Locally transcoded generations, by contrast, are written to a fresh directory
and promoted by swapping `streaming_playlists.master_key`
(`internal/media/hls.go:912-947`). **[read]**

Tier B assumes F2 and F6 are in: F6's filename grammar is also the route's gate.

### 6.1 The Kubo mechanism, as measured

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
| Every gateway read has a two-block floor: a HEAD returns no body and still costs 512 KiB of origin traffic (one block of readahead) | T12 |
| **One reference per block, first writer wins.** A second add of identical bytes under another URL returns HTTP 200 and the right CID and records nothing; the same is true of a nocopy re-add over blocks the node already holds as copies | T5, T10 |
| `block/rm` removes references (32 in one call) but refuses while **any** pin covers the block; `force=true` does not override | T10 |
| Heal, end to end: unpin every covering pin → `block/rm` the leaves → nocopy re-add from the good URL. CID unchanged, no gc, no restart | T10-iv |
| A failure on a late part of an add returns **HTTP 200** with the error only in the `X-Stream-Error` trailer, no root entry and no pin. On success the wrapping directory is the last entry, with `Name: ""` | T11a, T3 |
| A small file added first in copy mode stays a real block through a later nocopy add of the tree, serves while the origin answers 404, and survives gc | T11b |

Not measured, and gated in section 10: the DHT reprovider, bitswap retrieval by a
remote peer, any real S3 endpoint, a stalling origin, Kubo's resource use under
many ranged reads, and the multi-level walk of 6.4.

### 6.2 The add call (C)

`ipfs.DirEntry` (`internal/ipfs/client.go:24`) gains a `SourceURL` field. When it is
set, `add` writes that part with `CreatePart` and an `Abspath` header instead of
`CreateFormFile` (`client.go:162`), and the query gains `nocopy=true`. The `Client`
interface keeps its shape — the seam `ipfs-media-private.md:244-248` asks not to
widen. Because the CID does not depend on the mode (T1, T3), **the mode is
invisible outside the node**: ledger rows, gateway links and federation payloads
are unaffected by a switch in either direction.

**Tiny files are always real copies.** Files at or under a threshold (placeholder
**32 KiB**: playlists, init segments) are added first in copy mode with
`pin=false`; the tree add then carries `Abspath` on every part, finds those blocks
present, leaves them alone (T11b), and its recursive pin covers them. Small files —
playlists and init segments — are the likeliest to be byte-identical across videos:
vidra authors the master playlist itself from the ladder profile with relative URIs
(`internal/media/cmaf.go:1127`), and an init segment depends on codec, resolution
and encoder settings, not on content. That is **[unverified]** and a gate-4
measurement; with one reference per block (6.4) the rule is insurance against every
video's playlist hanging off the first video ever pinned, not only an optimisation.

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
probe). **So the source route must answer for the row being added, before it is
pinned** — which drives 6.3's gate. Whether the pre-copy also removes the tiny
files' own add-time read is **[unverified]**: T11b did not count origin reads
during its tree add.

### 6.3 The source route (C, M)

`GET /ipfs-source/v1/<instance secret>/<object key>`, mounted at the root beside
`/metrics` (`internal/httpapi/server.go:1455`): outside `/api/v1`, outside the
OpenAPI contract, outside the rate-limited group (`server.go:1440-1512`).

- **Always mounted, inert until used.** `routes()` runs once at construction
  (`server.go:1441`) but the managed mode is changed live from Admin → IPFS; a route
  registered only "when the mode is on" would let the worker pin rows whose every
  segment 404s until a restart. With no reference row, every request is a 404.
- **No authentication header, because Kubo cannot send one**: boxo's urlstore calls
  `http.DefaultClient.Do(req)` with only a `Range` header added
  ([fsrefstore.go](https://github.com/ipfs/boxo/blob/main/filestore/fsrefstore.go)).
  **[sourced]** But the urlstore sends the stored URL **verbatim**, so the URL can
  carry a static, per-instance, randomly generated path segment. Unlike a presigned
  URL it never expires; rotating it means a re-index (6.6). This is the route's own
  defence, and it matters: HLS today carries the per-IP media budget
  (`internal/httpapi/routeclass.go:51-52`), this route cannot, and the base compose
  file publishes the api on `0.0.0.0:8080` (`vidra-core/docker-compose.yml:1060`) —
  only the prod overlay pins it to loopback (`docker-compose.prod.yml:328-329`, which
  needs Compose ≥ 2.24). `GET` only; the urlstore sends nothing else.
- **The gate, all of:**
  1. the file is one the HLS handlers serve (F6's shared definition) — never a
     directory prefix alone, because the generation directory also holds download
     assets and `vp9.webm`, which has its own ledger row (`internal/media/vp9.go:62`);
  2. the key lies under the live generation of a reference-mode row on the public
     network. **Which column depends on the row's state:** a claimed `pending` row
     has `source_generation`, written by `AdmitIPFSPin` (`ipfs_admission.sql:43`);
     `committed_generation` is set only by `CompleteIPFSAdmission` (`:109`), *after*
     the add, so it is the right column only for a `pinned` row. The unmanaged drain
     sets neither before the add — `RecordLegacyIPFSGeneration` is post-hoc and
     best-effort (`service.go:1490`) — so it must persist the resolved tree prefix
     **before** `AddDirectory`, or its add-time reads 404 and the first reference add
     fails;
  3. the video is served anonymously **right now**. The ledger lags: `syncVideoMirror`
     is best-effort and swallows errors (`internal/httpapi/videos.go:1977-1986`) and
     converges only at `IPFS_RECONCILE_INTERVAL`, five minutes by default
     (`internal/config/config.go:1328`). The function to reuse is
     `Service.gatewayRowEligible` (`internal/ipfsmirror/gateway.go:65-100`), which
     also covers the owner flags `Route` reads (`eligibility.go:95-123`) — plus the
     DRM clause, which lives only in SQL (`ipfs_admission.sql:111-114`). It is five
     round trips, and a 2 MiB segment is eight block reads, so an in-process cache is
     **mandatory**: a stated TTL of a few seconds, bounded by wall clock, and
     invalidated by the takedown paths.
- **One canonical key.** Taken from the *decoded* path, canonicalized once, and that
  identical string reaches `storage.Open`. Both backends already reject empty,
  absolute, NUL and `..` keys (`internal/storage/s3.go:170-180`, `local.go:71-81`).
- **Never redirects, never cached.** Elsewhere delivery may 307 to a CDN, a
  presigned URL or the IPFS gateway itself; here that is a loop or an expiring
  reference. `Cache-Control: no-store`, and the runbook says never to put this path
  behind a cache: a cached 200 outlives a takedown. It serves through
  `serveStoredObjectNamed` (`internal/httpapi/videos.go:1578`), which already turns
  `Range` into ranged S3 GETs (`internal/storage/s3.go:443-486`), with bounded read
  timeouts.
- **Limits, because this is where the cost constraint is won or lost.** Any IPFS
  peer can ask for any block; nothing is cached (T2); every read is a gate decision
  plus a bucket round trip; and a HEAD to the gateway returns no body and still
  costs 512 KiB of bucket egress (T12). On the route: a byte-rate bucket, a
  request-rate limit, a concurrency semaphore, a per-object share so one object
  cannot take the whole allowance, and above them a **daily egress budget that
  pauses the mirror visibly** (component state, log line, gauge, cumulative bytes
  served) rather than starving reads at random. The route cannot tell peers apart —
  its only client is the node — but **the node can**: Kubo's
  `Internal.Bitswap.MaxOutstandingBytesPerPeer`, `Gateway.MaxConcurrentRequests`,
  `Gateway.RetrievalTimeout` and `Gateway.MaxRequestDuration`, set by the manager's
  `public_config()` and the init script (named by the security review from Kubo's
  config.md; to be confirmed on v0.43.0 **[unverified]**). All ship with safe
  defaults; gate 3 tunes them.
- **Core proves the route is not public; a file grep cannot.** Production mounts a
  generated `deploy/Caddyfile.local` that `deploy.sh` checks but never re-renders
  (`deploy/deploy.sh:160-187`, `:228-283`), `VIDRA_TLS_MODE=external` has no caddy
  service at all (`deploy/deploy.sh:447-459`), and managed mode is switched live,
  long after `deploy.sh` last ran. So on mode-enable and on every reconcile tick the
  api requests its own route **through `PUBLIC_BASE_URL`** and refuses (or pauses)
  reference mode unless the edge answers non-2xx. The Caddy `handle /ipfs-source/*
  { respond 404 }` still goes into the renderer (`vidra-core/internal/setup/caddyfile.go`)
  and the examples, like the `/metrics` block (`deploy/Caddyfile:75-77`);
  `deploy.sh` and `vidra doctor` WARN, with the fix command, when `Caddyfile.local`
  lacks it.
- **Base URL:** `IPFS_SOURCE_BASE_URL`, default `http://api:8080`. The in-container
  port is the literal `HTTP_PORT: "8080"` (`vidra-core/docker-compose.yml:77`);
  nothing declares a network, so every service is on the project default, and the
  manager attaches its node to that network as external
  (`deploy/ipfs-manager.py:243`, `:248`). **[read]** **The base URL is written into
  every reference**, and it can break without changing: the manager freezes project
  and network names (`ipfs-manager.py:251-274`), so a restore into a differently
  named directory leaves the node on a stale network where `api` no longer resolves.
  So reachability is a **recurring reconcile-tick probe** — the api fetches one block
  of one reference row through the gateway, which proves the node → api path —
  latching both ways and reported through the `ipfs` component. Never a boot
  one-shot and never on the readiness path: the managed node is a separate compose
  project with no `depends_on` edge, and `up -d` recreates the api on every deploy.

### 6.4 One reference per block: the invariant (C)

This is the part that can silently break videos.

Because the first writer wins (T10), identical bytes reached through two object
keys share **one** reference — the first key's. A live pin then depends on an
object that is gone whenever an HLS object is removed while something still
references it. The flows that remove locally transcoded HLS objects, as found so
far **[read]**:

| Flow | Where | Order today |
|---|---|---|
| Superseded generation collected | `internal/mediagc/service.go` — `isReferenced` at `:599`, references built at `:696`, `:719` from `video_files` and `streaming_playlists` only; no `ipfs` anywhere in the package | Independent of the pin ledger |
| Account deletion | `internal/account/delete.go:84` — `blobDeletePrefix(HLSKeyPrefix(vid))` | **Synchronous** whole-tree delete; never consults mediagc |
| Transcode retry | `internal/media/hls.go:1403` clears a generation prefix | Synchronous |
| Video delete via `video.Service.Delete` | `internal/video/service.go:2215-2220` | Safe: row deleted, `onDelete` → `UnpinVideo`, blobs left to mediagc much later |
| Eviction, `SweepIneligible` | ledger only | Safe |
| Storage migration | `internal/storagemigration/service.go:25-29` — *"copies each object to the SAME key"* | Safe |

In copy mode none of this matters — the node has its own bytes. In reference mode
each unsafe flow removes them. And identical files under two keys add a second way
to break: tiny files across videos (6.2's rule takes those out), and whole trees if
one source is uploaded twice or deleted and re-uploaded — but only if two
transcodes of one source are byte-identical, which is **[unverified]** and a gate-4
measurement.

**Invariant: no reference may outlive the object it points at, and a row is
re-added only after its own old references are gone.**

- **The media gc defers**: `isReferenced` treats any key under the live generation
  of a reference-mode row as referenced.
- **The synchronous deleters call the withdraw procedure first** — account deletion
  and transcode retry each get a hook, not only a gc deferral.
- **The withdraw procedure**, for any reference-mode row being withdrawn or
  replaced:
  1. enumerate the row's leaves by walking its DAG with **non-recursive** `refs`,
     descending only into dag-pb CIDs and never opening a raw (`bafkrei…`) one.
     Every node opened is a real local block, so the walk should read zero origin
     bytes — T12 measured that for non-recursive `refs` on a file root and `ls` on a
     directory root; the multi-level walk is composed from those and is asserted by
     section 10's counters, not yet measured. (`refs?recursive=true` re-downloads
     the video.)
  2. `pin/rm` the root;
  3. `block/rm` the leaves in batches (T10). What is removed can no longer poison a
     later add. What is **refused** is still covered by another pin;
  4. for each refused leaf, ask where its reference points. T12 measured whole-store
     `filestore/ls` at zero origin bytes; the per-key `arg=` form is assumed local
     and must be confirmed. If it points under the generation being withdrawn, the
     covering pin has borrowed it, and that pin's row is marked for **heal**;
  5. heal each such row with the sequence T10-iv measured end to end.

Two costs, stated plainly. A heal takes an **unrelated, published** video off IPFS
for the length of its re-add because of someone else's takedown. And the table
above is only as good as the search that produced it: two review rounds each found
deleters the previous one missed.

`filestore/verify` is **not** a periodic job: it re-downloads the store (T12) and
cannot take a root CID (T10). Section 6.7 is how a broken video is found instead.

### 6.5 Node configuration and the RPC boundary (C, M)

- **Unmanaged:** `vidra-core/deploy/ipfs-public/001-configure-network-mode.sh` sets
  `Experimental.UrlstoreEnabled` from the environment. It is bind-mounted into
  `/container-init.d/` (`docker-compose.yml:1305`) and re-runs on persisted repos by
  design (its own header, `:5-8`), so a restart applies it. **[read]**
- **Managed:** `ipfscontrol.HostConfig` gains one boolean and the manager's
  `public_config()` (`deploy/ipfs-manager.py:229-235`) writes it. This respects the
  boundary stated at `internal/ipfscontrol/config.go:25` — *"URLs, images, mount
  paths and commands deliberately cannot cross this boundary"*: only a boolean
  crosses; the URL travels core → Kubo inside the add request. `public_config()`
  only `setdefault`s its own keys, so an older manager does not clear the flag.
- **The flag is never turned off while reference rows exist.**
- **Fail closed.** If the node rejects `nocopy` (T0), the row fails with a closed
  error code. Core **never falls back to a copy add**: that would quietly fill the
  disk.
- **RPC authorization is a precondition of the flag — and it is a manager change,
  not a config line.** With the urlstore on, whoever can reach the Kubo RPC can make
  the node fetch arbitrary URLs *and read the result back as blocks*: a read-SSRF
  from the node's network position. Today the RPC is published on host loopback
  (`vidra-core/docker-compose.yml:1301`; `ipfs-manager.py:242`) — every local
  account — the managed node sits on the application's network with the frontend,
  caddy, worker and search, and nothing authenticates it. **[read]** Kubo's
  `API.Authorizations` is documented and not experimental (config.md) **[sourced by
  the evidence audit]**, but nothing here can use it yet: `NewKuboClient`
  (`internal/ipfs/client.go:107`) sends no credential; both healthchecks call
  `ipfs … id` unauthenticated (`ipfs-manager.py:245-246`,
  `vidra-core/docker-compose.yml:1308`) and would restart-loop; the manager's own
  `repo/stat` calls need it; and there is nowhere to keep it — `install_settings`
  never saves the application env (`:252`) and `HostConfig` carries only scalars.
  "A network only core shares" is not available either: `install_settings` requires
  the loopback publish (`:269`, `:274`) and validates exactly one network named
  `default` (`:256`). So the PR is: the manager generates and stores the credential
  in its root-owned target and returns it over the socket; core's client gains an
  auth option; both healthchecks pass `--api-auth`.
- The pinned image stays `ipfs/kubo:v0.43.0` (AGENTS.md hard rule 7).

### 6.6 Mode, conversion, rollback, restore (C, M)

- **Mode** is `copy` (default) or `reference`, per instance. Managed instances set
  it in the policy document on Admin → IPFS; unmanaged instances set
  `IPFS_PIN_STORAGE`. Each ledger row records the mode it was added in (new column;
  migration number assigned when the PR opens — 0151 is the newest today): the
  withdraw procedure and the admission arithmetic differ by row, and a node
  legitimately holds both kinds at once.
- **Conversion is not a re-add.** A nocopy re-add over copied blocks reports
  success and reclaims nothing (T5). What T5 measured is `pin/rm` → `repo/gc` →
  nocopy re-add, CID unchanged — and `repo/gc` is global. The per-row route this
  design wants (enumerate with recursive `refs`, free while the blocks are local
  copies; `pin/rm`; `block/rm`; nocopy re-add) is T10's heal transposed to copy
  blocks and is **not yet measured**.
- **The row leaves `pinned` for the whole conversion.** `VerifyPins`
  (`internal/ipfsmirror/verify.go:119`) → `RearmLostIPFSPin`
  (`media_ipfs_pins.sql:508-526`) re-arms a `pinned` row whose CID the node does not
  hold — exactly the state between the unpin and the re-add. Taking the admission
  claim does not help: `AdmitIPFSPin` claims only `state='pending' AND claim_token IS
  NULL` under an active managed policy (`ipfs_admission.sql:8-46`) and cannot claim
  a `pinned` row, and unmanaged mode has no admission at all. So conversion first
  moves the row to `pending` with a conversion marker; the normal drain then
  performs the reference add.
- It runs as a tracked, stoppable backfill paced by `copy_bytes_per_second`. **The
  row is off IPFS between its unpin and its re-add**; normal delivery is unaffected.
- **What it costs in bucket traffic.** Every converted byte is read from primary
  storage once. Afterwards every byte the mirror serves is bucket egress, which
  today it is not: a one-time disk cost traded for a per-read egress cost, bounded
  by 6.3's limits. Beta's bucket is Backblaze B2 behind a Cloudflare endpoint
  (`deploy/IPFS-MANAGER.md:78-79`). B2 publishes free egress up to three times
  average monthly storage and $0.01/GB above it, and unlimited free egress through
  partner CDNs including Cloudflare **[sourced by the evidence audit]**; whether
  core's own reads go through that endpoint decides which applies **[unverified]**.
- **Rows evicted for capacity return** once: the budget that evicted them no longer
  binds.
- **The rollback floor is a host-side latch, not a database read.** An api image
  from before the source route makes *every* reference block unreadable while
  `/admin/system` still says `ok`, and its deleters skip the withdraw procedure.
  `rollback.sh` reads no database at all and knows one floor,
  `MIN_EMBEDDED_MIGRATE_TAG` (`deploy/rollback.sh:62`, `:133-142`); `deploy.sh`'s
  ledger read is a `docker exec` that is skipped on external Postgres
  (`deploy/deploy.sh:667-673`); `restore.sh` reads the dump
  (`deploy/restore.sh:300-305`). **[read]** A rollback happens when the api or the
  database is sick, so the gate must not need them. Core writes a marker file the
  first time a reference row is created, cleared only by a completed convert-back;
  all three scripts read that file. `rollback.sh` **warns and requires an explicit
  override** — incident scripts warn rather than refuse (`deploy/deploy.sh:235-238`)
  — while `deploy.sh` and `restore.sh` refuse below `MIN_IPFS_REFERENCE_TAG`, and
  `restore.sh` also checks the *dump* for reference rows, before the drop. How an
  unmanaged instance writes the marker (no manager socket) is open. Switching the
  *mode* back to `copy` is always safe.
- **Restore.** Onto a new host with an empty node: the ledger says `pinned`, the
  node holds nothing, the reconcile tick re-arms and the drain re-adds by reference
  — it recovers by itself, re-streaming the public HLS library from the bucket
  once. With a node volume *newer* than the ledger, or after a fresh repo, per-row
  heal does not scale: an admin **"re-index all reference rows"** run — admin-only,
  audited, single-flight, refused while the daily egress budget is paused.

### 6.7 Admission, and how a broken video is found (C)

Budget, free-space floor, reservations, pacing, demand pins and eviction all stay.
The reservation for a reference row becomes the index cost plus the tiny files —
**placeholder `bytes / 256 + tiny_file_bytes + 16 KiB × files + 1 MiB`**, to be
replaced by a measurement; the per-file term dominates it for a tree of 1–2 MiB
segments. Reservations are transient; what fills the budget is actual repo growth —
0.094 % for one large file (T1), higher and **unmeasured** for a tree. If that ratio
is even several times worse, the disk budget stops being the limit by about two
orders of magnitude.

**The ceiling moves; it does not vanish.** Reference mode still streams every byte
through the add (T1): `admission.go:221` refuses a row whose bytes cannot be read
within ~24 h at `copy_bytes_per_second / workers`, and at beta's 2 MiB/s
(`deploy/IPFS-MANAGER.md:72-73`) a 5 TiB library (illustrative) is about a month of
continuous paced reading. And the disk budget was also the only brake on an
**anonymous** trigger: `POST /api/v1/videos/:id/playback-session` is `optionalAuth`
(`server.go:1844`) and calls `DemandPublicVideo` (`playback_session.go:142-148`),
tagging any public video for a demand pin that reads its whole tree from the bucket.
**[read]** Reference mode therefore adds a bytes-admitted-per-day brake that does
not depend on disk.

**Finding a broken video.** Kubo's read error is generic (`failed to fetch all
nodes`, T4) and there is no periodic verify. So: a **404 on the source route is the
canary** — a live reference pointing at a key the gate no longer covers, the
signature of 6.4 failing — with `vidra_ipfs_source_requests_total{result}` and
`vidra_ipfs_source_bytes_total` as required metrics, reported by the `ipfs`
component and `vidra doctor`; the recurring gateway fetch of 6.3 rotates through
the ledger as a sampled end-to-end check; and "re-index this video" is the manual
repair.

### 6.8 Out of scope

- Every media class except locally transcoded `hls` (top of section 6).
- **The private swarm stays in copy mode.** Its source route would serve
  non-public bytes without authentication; its replicas copy regardless.
- **The chunk size stays 256 KiB.** 1 MiB chunks cut origin requests four-fold
  (T7) but change every CID, and "the mode never changes a CID" is what makes
  conversion and rollback safe. Section 12, D3.
- No change to delivery or to the gateway probe.

## 7. Failure handling (Tier B)

The fallback in every case is today's behaviour for a video that is not on IPFS:
normal delivery.

| Situation | Behaviour |
|---|---|
| Node has the urlstore flag off | Add fails closed (T0); row fails with a closed code; **no copy fallback** |
| Primary storage, Postgres or the api unreachable | The source route cannot answer; Kubo's read fails fast when refused (T4a) and recovers by itself; tiny files keep serving from the node. A bucket that *stalls* is untested — gate 3 |
| Object changed under a live reference | Zero wrong bytes served (T4b). Cannot happen to a locally transcoded generation; everything it can happen to is out of scope |
| Video deleted, blocked or made private | The live check 404s the route within the cache TTL; the ledger follows; then the withdraw procedure. Tiny files remain real blocks until unpin + gc, and blocks other peers already fetched are beyond reach — as today |
| Identical bytes under two keys | 6.4: the lender's withdrawal heals the borrower |
| A deleter wants HLS objects a reference row still uses | The gc defers; the synchronous deleters withdraw first (6.4) |
| Add stream fails midway | F2 fails the row; orphan references are unpinned and the next gc removes them (T11a) |
| Node cannot reach the source URL | The recurring probe latches "unreachable"; reference adds are refused with the reason; it clears by itself |
| The route is reachable through the public URL | Core refuses or pauses reference mode and says why |
| A limit or the daily egress budget is hit | The mirror reports itself paused; the requesting peer retries; viewers on the operator's gateway fall back |
| App rollback with reference rows present | `rollback.sh` warns and requires an override; `deploy.sh` and `restore.sh` refuse below the floor |
| Kubo is never updated again | The image is already pinned, and nothing here needs a newer one |

## 8. Security

- **Tier A closes two gaps that exist today:** F6 stops mirroring files the
  instance otherwise serves only under its download policy, and F5 stops deleted or
  replaced objects staying pinned.
- **What the Tier B route serves:** HLS playback files, of the live generation, of
  videos served anonymously right now — checked at request time, behind an
  unguessable path segment, with `no-store`. Originals and download assets are
  excluded precisely because "public and pinned" is not "served anonymously" for
  them.
- **The RPC boundary becomes load-bearing** (6.5): with the urlstore on, RPC access
  is read-SSRF, and today that boundary includes every local account and every
  container on the application network. Authorization is a precondition, and
  section 10 adds the negative test that a **filesystem** `Abspath` is refused
  while `FilestoreEnabled=false`. A 307 from the source is followed (T4d); the
  source is our own api and never redirects.
- **Cost as an attack surface.** A request that returns no body still costs 512 KiB
  of egress (T12). The controls are the node's per-peer and gateway limits plus the
  route's limits and its visible daily pause (6.3); a single global bucket would
  itself be a denial of service against real viewers.
- **Withdrawal, with its qualifiers.** Media segments stop resolving once the live
  check fails — faster than today's wait for a gc, bounded by the cache TTL. But
  tiny files stay real blocks until unpin + gc; blocks other peers already hold are
  untouched; and a takedown can briefly take an unrelated borrowing video off IPFS
  while it heals.
- **What the node's datastore now holds:** internal URLs containing the instance
  secret and object keys (video and user UUIDs, no filenames, no credentials, no
  presigned query strings). `filestore/ls` is RPC-only and `Gateway.NoFetch=true` in
  both network modes (`001-configure-network-mode.sh:53`, `:73`). A copy of the
  datastore is an inventory of public object keys plus that secret — one more reason
  the pinset is never backed up.

## 9. Surfaces

- **Admin → IPFS (U):** the mode select (managed instances), "N videos stored as
  copies · M as references · index X of budget Y", the conversion run with Stop,
  "re-index this video" and "re-index all", cumulative egress served against the
  daily budget, and the mirror's paused state with its reason. No new page.
- **Environment (C):** `IPFS_PIN_STORAGE`, `IPFS_SOURCE_BASE_URL`, the route's limit
  knobs, `IPFS_REPO_BUDGET_BYTES` (F3). The consumers land in
  `vidra-core/docker-compose.yml` beside `HTTP_PORT`, as plain `${VAR:-}`
  pass-throughs — a compose fallback value would shadow the Go default. The meta
  repo cannot declare `api`/`worker` env, and `docker-compose.override.yml` is not
  loaded by `deploy.sh` (`deploy/lib.sh:113-115`), so a consumer added there would
  work locally and not exist on the host. `env/production.env.example` (M)
  documents them.
- **Deploy (M):** the Caddy handle in the renderer and examples, with a WARN and a
  doctor line (6.3); the marker file and `MIN_IPFS_REFERENCE_TAG` (6.6); the
  manager's boolean, credential, healthcheck and Kubo limits (6.5, 6.3).
- **Runbook (M, C):** `deploy/IPFS-MANAGER.md` and `vidra-core/docs/operations.md`
  gain F6's re-pin and gc step, the mode, the renamed-project warning, the RPC
  credential, "never cache this path", the rollback floor, and the statement that a
  reference-mode mirror depends on primary storage, Postgres **and** the api.

## 10. Testing and the gates

A mocked-green suite is not accepted as evidence; the behaviour that matters lives
in Kubo.

**Tier A:** F2 against real Kubo with a failing late part; F6 asserting the pinned
tree's file list equals what the HLS handler serves, that no download asset is
reachable through the gateway after the re-pin and gc, and the tree's size before
and after on a real ladder; F1's factor recorded from a measurement; F3/F4 pause
and resume.

**Tier B, in core's existing IPFS integration lane:** nocopy add of an HLS tree;
CID equality with copy mode; the tiny-file rule under `limitedSource`'s one-open
constraint; add-time reads served for a claimed `pending` row in managed **and**
unmanaged mode; fail-closed with the flag off; a filesystem `Abspath` refused;
every deleter in 6.4's table against a live reference row, each ending with every
segment fetched through the gateway; conversion copy → reference → copy with a
`VerifyPins` tick fired inside the window.

- **Origin-read accounting:** the route counts requests and bytes, and the tests
  assert **zero** origin bytes for the withdraw walk on a multi-level tree, for
  `filestore/ls?arg=`, for the reconcile tick and for gc — the guard against anyone
  reaching for `refs -r`, and the measurements 6.4 still owes.
- **Source route:** 404 without the secret segment, for a download asset and
  `vp9.webm` under a live row, for a key outside the live generation, for an
  imported tree, for a private-network row, for `unpinning/unpinned/failed`, and for
  a video blocked a moment ago while its row still says `pinned`; encoded-slash,
  `..` and double-encoding cases; never a redirect; `no-store`; each limit; cache
  invalidation on takedown. Reviewers mutation-test each guard: revert the clause, a
  test must fail.
- **Deploy:** the marker makes `rollback.sh` warn and `restore.sh` refuse; a restore
  into a renamed project directory trips the reachability probe; a route reachable
  through `PUBLIC_BASE_URL` makes core refuse the mode.

**Gates, recorded in `docs/` before reference mode is enabled on beta:**

1. **Reprovider.** On a networked private test swarm, origin bytes read over one
   full provide cycle under the manager's `Provide.Strategy = pinned+unique`. The
   spike could not run this. If it is not zero, Tier B does not ship as designed.
2. **Remote retrieval.** A second peer fetches a reference-pinned tree over
   bitswap, byte-exact.
3. **Real object storage.** Against MinIO and one real provider: time to first
   frame and steady-state segment latency through the gateway, copy vs reference;
   origin requests per viewer-minute; add-time cost of a low-bitrate rendition
   whose every segment fits one chunk; the cost of a hostile HEAD loop under the
   limits; and a bucket that stalls rather than refuses. T8's localhost numbers say
   nothing about any of this.
4. **The measurements the placeholders wait on:** index size of a real HLS tree;
   the reservation factors; the tiny-file threshold; whether playlists and init
   segments are byte-identical across videos; whether two transcodes of one source
   are.
5. **Resource envelope.** Kubo RSS, CPU and file descriptors under the production
   limits — `cpus 1.0` / `mem_limit 1g`, which the manager hardcodes with no env
   seam (`deploy/ipfs-manager.py:240`) — at the concurrency the limits permit. The
   spike ran unlimited.

## 11. PR sequence

Small PRs, each merged before the next.

**Tier A — recommended now:**
1. C — F2, the trailer and wrap-entry check.
2. C + M — F6, the playback-only wrap-add, the re-pin run, the gc runbook step.
3. C + M — F4, capacity gauges, the pause log line, the `/admin/system` decision.
4. C + M — F3, the unmanaged repo budget and its runbook line.
5. C — F1, the measured reservation factor.
6. C — F5, mirror hooks for caption delete, poster and storyboard replace, and
   same-key avatar replace.
7. M — **measure what beta's disk now holds**, recorded in `docs/`. Then D2.

**Tier B — only if D2 says so:**
8. M + C — the RPC credential: manager, healthchecks, core client (6.5).
9. C — `SourceURL` on `DirEntry`, the tiny-file pre-copy, the mode column, and the
   unmanaged drain persisting its tree prefix before the add; no caller sets the
   mode yet.
10. C + M — the source route (secret segment, gate, limits, metrics), the public
    exposure probe, the Caddy handle in the renderer with its WARN.
11. C — the media-gc deferral, the hooks in account deletion and transcode retry,
    the withdraw procedure and heal, against real Kubo.
12. C + M — node configuration (init script, `HostConfig`, manager, Kubo limits,
    fail closed) and the recurring reachability probe.
13. C + M — the marker file and the three scripts.
14. C + U — mode setting, reference-mode admission and the per-day brake,
    conversion and re-index runs, admin surface.
15. M — the five gates, recorded; then the beta decision.

The mode defaults to `copy` and the route is inert without reference rows, so a
release containing any prefix of this list is safe to deploy.

## 12. Decisions the owner has not made

- **D2 — How much to build. Recommendation: Tier A now, and decide Tier B from
  beta's measured number.** Tier A is six small fixes, closes two gaps that exist
  today, and should multiply what the disk holds about five-fold. Tier B removes the
  ceiling, but two review rounds each found blockers in it, its deleter list is
  only as complete as the last search, it needs a manager change before it can be
  switched on safely, it converts disk into bucket egress that must be policed, and
  it rests on experimental features of software whose maintainers stop on
  2026-09-30. If five-fold is enough for the instances vidra has, Tier B is not
  worth its risk.
- **D5 — Are the download assets meant to be on IPFS?** F6 assumes not: the pin
  code's comment asks for *"a clean playlists+segments tree"*, delivery has no
  mirror class for downloads, and nothing reads them through the mirror today. If
  mirroring downloads is wanted, it should be its own media class with the download
  policy applied, not a side effect.
- **D1 — (Tier B) Is a mirror that depends on the rest of the stack acceptable?** In
  reference mode the mirror depends on primary storage **and on Postgres and on the
  api container**. A Postgres restart, a migration window or `up -d` recreating the
  api takes every reference-pinned video off IPFS — events the mirror survives
  today. The existing doctrine points this way —
  `vidra-core/docs/operations.md:1404-1406`: *"**The pinset is a distribution
  surface, never a backup.** Do **not** back up the Kubo datastore for durability —
  it holds only re-derivable copies of already-public bytes"* — but that sentence
  was written about backups, not about this.
- **D3 — (Tier B) Chunk size.** Stay at 256 KiB (recommended: CIDs never change), or
  1 MiB for rows never pinned before (four times fewer origin requests, at the price
  of a per-row chunker record and CIDs that differ by vintage).
- **D4 — Which mode does beta run?** `IPFS_MANAGED_NODE` and the live
  `admission_paused_reason` are in the untracked env file and the database, not in
  either repo. The answer decides whether F1 or F3 is the fix beta feels first.

## 13. Risks and open items

- **Tier A's five-fold is arithmetic, not a measurement.** The MP4s are "about the
  size of the rendition" because they are remuxed from it without re-encoding, and
  the trick-play share of playback is an estimate; nobody has sized a real tree. PR 7
  exists for that.
- **F6 changes every HLS root CID** as rows are re-pinned. The API hands out the
  current CID, so nothing should hold an old one — to be confirmed (federation
  payloads, cached pages).
- **6.4 is Tier B's risk.** It is correct only if every flow that removes an HLS
  object is covered. Review of revision 1 found four uncovered flows; review of
  revision 2 found two more.
- **Composed, not measured:** the multi-level non-recursive walk, per-key
  `filestore/ls`, and per-row conversion by `block/rm`. Each is asserted by a
  counter in section 10 before anything depends on it.
- **Parsing `block/rm` refusals.** 6.4 learns which pin covers a block from Kubo's
  error text; `pin/ls?arg=<leaf>&type=all` is the structured alternative.
- **What the player does mid-stream is unknown** **[unverified]**. If it decides
  once, on the master playlist, then a tree whose playlist resolves and whose
  segments fail is its worst case — and tiny files staying local makes exactly that
  case more likely. A vidra-user question for the plan.
- **How an unmanaged instance writes the rollback marker** is open (6.6).
- **Serving speed against a real bucket is unmeasured** (gate 3). At 256 KiB a
  2 MiB segment is eight ranged GETs through the api plus one of readahead.
- **Experimental upstream features, unmaintained upstream.** The filestore has
  been in-tree since 2017 with sharness coverage for directory adds;
  [kubo#7161](https://github.com/ipfs/kubo/issues/7161) tracks it as an unstable
  experiment, and the `--nocopy` + `--fscache` hang it lists (kubo#5815) is closed.
  This design never passes `fscache`. **[sourced]**
- **Mechanisms are behavioural.** The single-chunk add-time read and the one-block
  readahead were observed, not explained from Kubo's source.

## 14. What review changed

**Revision 1 → 2** (four reviews):
- *False:* that a full Kubo repo cannot gc (kubo#5041 was closed on 2026-02-10; the
  fix predates the pinned v0.43.0); and "no new bill" (the disk cost becomes bucket
  egress).
- *Wrong scope:* every media class was referenced. Narrowed to `hls`; the findings
  became F5.
- *Wrong hazards:* the three 6.4 scenarios were guesses; the real one is a deleter
  that never reads the pin ledger.
- *Unbuildable:* the pre-copy against `limitedSource`'s one-open rule; a route
  registered only when the mode is on; an F2 that could not reach `resp.Trailer`.
- *Too weak:* the gate, the limits, the base-URL check, the SSRF note, D1.
- *Missing:* a rollback floor, the Caddy renderer, env consumers in the right repo,
  a resource-envelope gate, diagnosability, a brake on anonymous demand pins.
- *Overclaimed:* two "zero origin bytes" statements and the conversion route were
  composed from separate measurements; several quotes were trimmed.

**Revision 2 → 3** (four fresh reviews):
- *The finding that reordered the document:* the pinned HLS tree carries each
  rendition's two progressive MP4s and the audio asset. That is F6, and with F1 it
  is most of the answer to the owner's question. Tier A moved first and became the
  recommendation.
- *Blockers in revision 2's route:* it gated on `committed_generation`, which is
  empty until after the add, so add-time reads would have 404'd; and "for HLS the
  two agree" was false, because the generation directory holds download assets —
  the gate is now a filename grammar, not a prefix.
- *Still wrong scope:* imported HLS trees live in another instance's bucket;
  generation-0 rows cover the whole per-video directory. Both excluded.
- *Two more deleters* bypass the media gc: account deletion and transcode retry.
- *Mechanisms that could not work:* a `deploy.sh` refusal for a mode switched live
  (now a probe core runs itself); a rollback floor that reads the database (now a
  marker file, and a warning in `rollback.sh`); RPC authorization as a config line
  (now a manager change); a boot-time reachability probe (now recurring);
  conversion "holding the claim" on a row the claim cannot take.
- *Added:* the instance secret in the route's path; Kubo's own per-peer and gateway
  limits; cumulative egress in the admin surface; conditions on "re-index all".
- *Corrected:* F5's avatar case; the amplification figure (a ratio against an
  unmeasured denominator); the B2 sentence; ten citations.

**After revision 3** (one targeted verification of Tier A, since the recommendation
now rests on it):
- *Overstated:* "about three times" and "six-fold". Worked through for both
  packagings with trick-play counted as playback, the tree is 2.6–2.8 times the
  playback bytes and Tier A is about five-fold — nearer three with HEVC or AV1 on.
- *F6 as first written would have broken imported trees:* the definition must match
  the relative path, keep a PeerTube branch, and be applied in `admissionInventory`
  as well as `pinDirectory`; and the re-pin needs a new backfill — no existing
  re-arm path fires for it.
- *Confirmed:* both packagers always emit the two MP4s under the pinned prefix, and
  nothing consumes a download asset through the mirror, so F6 breaks no consumer.
