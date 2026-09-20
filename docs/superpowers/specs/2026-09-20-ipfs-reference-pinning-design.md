# IPFS reference pinning — mirror public media without a second copy — design

Date: 2026-09-20 · Status: **draft for discussion — not approved, not planned, not
built** · Repos: vidra-core (C), vidra (M), vidra-user (U)

Every claim below is tagged by how it is known: **[read]** in the code at
vidra-core `400c1a8` / vidra `79a84cd` with file:line, **[measured]** in the lab
spike recorded beside this document
(`docs/evidence/ipfs-reference-pinning-spike-2026-09-20/`), **[sourced]** from a
URL fetched on 2026-09-20, or **[unverified]**. Nothing here is an owner ruling;
section 12 lists the decisions the owner has not made yet.

## 1. What this is

An opt-in storage mode for the public IPFS mirror in which the Kubo node stores
**references** — URL, offset, length — to bytes vidra already holds in primary
storage, instead of a second full copy of them. The node's disk need falls from
"about the size of the public HLS library" to "about the size of its index". No
new service, no new bill, and nothing for the operator to run.

It answers the owner's question of 2026-09-20, in their words: *"is there a way to
possibly mount S3 instead to help pin IPFS videos instead of paying for a large
volume?"*, under their constraint *"without extra incurred cost or great effort on
part of the admin"*, for the problem *"at the moment, pinning stops at a point on
local disk"*.

The short answers: mounting S3 under Kubo does not work (section 3); what works is
not storing the second copy at all (section 5); and four small fixes are worth
shipping whether or not reference pinning is ever built (section 6).

## 2. Why pinning stops today

**Every pinned byte is stored twice.** Primary storage stays authoritative
(`internal/ipfsmirror/classes.go:1-9`) and Kubo holds a full second copy: the add
is a plain `POST /api/v0/add?pin=true&cid-version=1&raw-leaves=true`
(`internal/ipfs/client.go:139-153`) with the bytes streamed from the storage
backend through a rate-limited reader into a multipart body
(`internal/ipfsmirror/service.go:1590-1630`, `limited_source.go:69-173`,
`internal/ipfs/client.go:158-180`) — never staged on scratch. **[read]**

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
| 4 | **Unmanaged mode has no admission at all**: the legacy drain is unbounded, the compose service sets no `--enable-gc` and no `StorageMax` | `service.go:1196-1243`; `vidra-core/docker-compose.yml:1286-1312` | The volume fills; at ENOSPC even `ipfs repo gc` fails because it first writes to the repo ([kubo#5041](https://github.com/ipfs/kubo/issues/5041)) **[sourced]** |

A refused row stays `pending` with `capacity_reason` set and retries every 60 s
(`ipfs_admission.sql:90-93`), so pinning resumes by itself when space frees. The
exception is a row evicted for capacity: `capacity_reason = 'evicted_capacity'`
is excluded from both candidate queries (`:15`, `:79`) and returns only on a fresh
`demand` tag (`:135-143`). And `/admin/system`'s `ipfs` component reports `ok` on
a full budget as long as node and gateway answer
(`internal/httpapi/system_ipfs_managed.go:29-68`). **[read]**

Kubo facts that bound any fix: `Datastore.StorageMax` is *"A soft upper limit …
used to calculate whether to trigger a gc run (only if `--enable-gc` flag is set)
… It is not a hard limit on total disk usage"*; default `10GB`; `ipfs add` does
not fail when it is exceeded; and GC only ever removes **unpinned** blocks — for a
node whose whole job is pinning, GC frees nothing
([config.md](https://github.com/ipfs/kubo/blob/master/docs/config.md)). **[sourced]**

## 3. Options considered and rejected

| Option | Verdict | Why |
|---|---|---|
| FUSE-mount a bucket under the Kubo repo (s3fs, goofys, rclone mount, mountpoint-s3) | **No** | flatfs needs atomic rename + fsync; leveldb/pebble need random writes and the repo lock is an fcntl lock ([kubo#6363](https://github.com/ipfs/kubo/issues/6363)). mountpoint-s3: *"It does not emulate operations like `rename`"*, *"All writes must be sequential"*, *"POSIX file locks (`lockf`) are not supported"* ([SEMANTICS.md](https://github.com/awslabs/mountpoint-s3/blob/main/doc/SEMANTICS.md)). rclone: *"Without the use of `--vfs-cache-mode` this can only write files sequentially"* ([docs](https://rclone.org/commands/rclone_mount/)) — and the cache that fixes it is local disk. **[sourced]** |
| JuiceFS under the repo | No | Genuinely POSIX, but needs its own metadata database — a new stateful service to run and back up. Fails "no great effort". **[sourced]** |
| `go-ds-s3` datastore plugin | **No** | README banner *"Looking for Maintainers"*; newest prebuilt plugin targets Kubo 0.32.1 (2024-11-21) against our 0.43; `go.mod` on `aws-sdk-go` v1, end-of-support 2025-07-31; *"Garbage collection appears broken"* open since 2021 ([go-ds-s3#198](https://github.com/ipfs/go-ds-s3/issues/198)); a Go plugin must match the exact Kubo build, so we would ship our own Kubo for every release. It also still stores a **second copy**, only in a bucket. **[sourced]** |
| Remote pinning service | No | Recurring cost. No free tier above 5 GB; cheapest honest plan found is Filebase Pro, $7.50/month for 500 GB ([pricing](https://filebase.com/pricing)). `vidra-core/.ralph/specs/ipfs-media-private.md:244-248` keeps the seam open for it: *"If a hosted adapter is ever justified … it slots in as another implementation behind that interface plus a config choice"*. **[sourced] [read]** |
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
Since 2026-08-25 `ipfs.io` and `dweb.link` redirect to the in-browser gateway
`inbrowser.link` instead of serving content
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
        ledger says public + live?  ── no ──▶ 404
        serveStoredObject (Range → ranged S3 GET)
```

### 5.1 The Kubo mechanism, as measured

All **[measured]** on `ipfs/kubo:v0.43.0`, offline node, local Range-serving origin;
test ids refer to `EVIDENCE.md`.

| Fact | Test |
|---|---|
| With `Experimental.UrlstoreEnabled=true` (the filestore flag is not needed), `add?nocopy=true` with a multipart part header `Abspath: <http URL>` stores `{URL, offset, length}` per leaf. The bytes are still streamed in the body, and those are what Kubo hashes | T1 |
| **The CID is identical to today's copy add** — for a single file and for a wrapped HLS tree with one `Abspath` per part | T1, T3 |
| Repo growth for a 64 MiB file: 62,999 bytes — **0.094 % of the payload** | T1 |
| Kubo does not contact the URL at add time — **except** for a file that fits in one chunk (≤ 262,144 bytes), which costs exactly one origin read during the add | T1, T3 probe |
| A read is one ranged GET per block, exactly one block wide, never a whole-object GET; nothing is cached between reads | T2 |
| Wrong bytes at the URL: **zero bytes served** (every block is re-hashed). Origin down or 404: the read fails in ~0.03 s and **recovers with no re-add** when the origin returns | T4 |
| A 307 is followed and `Range` survives it, at two requests per block | T4d |
| With the flag off the add fails closed: HTTP 500, `either the filestore or the urlstore must be enabled to use nocopy` | T0 |
| `repo/gc` keeps references while pinned; unpin + gc removes them | T6 |
| `pin/ls`, `pin/verify`, `repo/stat`, `repo/gc`, `files/stat`, `ls`, `block/stat`, `filestore/ls` and non-recursive `refs` read **zero** origin bytes | T12 |
| **`refs?recursive=true`, `dag/stat` and `filestore/verify` re-download every byte** | T12 |
| Every gateway read has a two-block floor: a HEAD costs 512 KiB of origin traffic (one block of readahead) | T12 |
| **One reference per block, first writer wins.** A second add of identical bytes under another URL returns HTTP 200 and the right CID and records nothing; the same is true of a nocopy re-add over blocks the node already holds as copies | T5, T10 |
| `block/rm` removes a reference, but refuses while **any** pin covers the block; `force=true` does not override | T10 |
| A failure on a late part of an add returns **HTTP 200** with the error only in the `X-Stream-Error` trailer, no root entry and no pin | T11a |
| A small file added first in copy mode stays a real block through a later nocopy add of the tree, serves with the origin down, and survives gc | T11b |

Not measured, and gated in section 10: the DHT reprovider, bitswap retrieval by a
remote peer, any real S3 endpoint, and a blackholed (not refused) origin.

### 5.2 The add call (C)

`ipfs.DirEntry` (`internal/ipfs/client.go:24`) gains a `SourceURL` field. When it is
set, `add` writes that part with `CreatePart` and an `Abspath` header instead of
`CreateFormFile` (`client.go:163`), and the query gains `nocopy=true`. The `Client`
interface keeps its shape — the seam `ipfs-media-private.md:244-248` asks not to
widen. Because the CID does not depend on the mode (T1, T3), **the mode is
invisible outside the node**: ledger rows, gateway links, federation payloads and
anything a viewer bookmarked are unaffected by a switch in either direction.

**Files that fit in one chunk are always real copies.** Before the nocopy add, the
worker adds every part of at most 262,144 bytes in copy mode with `pin=false`
(one request, no wrap); the tree add then carries `Abspath` on every part, finds
those blocks present and leaves them alone (T11b), and its recursive pin covers
them. This one rule removes the add-time origin read (T3 probe), keeps playlists,
init segments and VTTs served from the node when primary storage blinks, and takes
the files most likely to be byte-identical across videos out of the hazard in 5.4.
The disk cost is the size of those small files. If a gc lands between the two
requests the small files become references instead — correct, merely less
resilient — so the source route (5.3) must already answer for a `pending` row.

**The client must stop trusting the status code.** Today `add` returns the last
NDJSON line that carries a hash (`client.go:186-211`) and never reads the
trailer **[read]**. With T11a's behaviour that turns a half-finished tree add into
a success whose "root" is the last file Kubo happened to emit. The fix — read
`X-Stream-Error`, and for a wrap add require the final entry to be the wrapping
directory (`Name == ""`) — is needed for reference mode and is listed in section 6
because it is not specific to it.

### 5.3 The source route (C, M)

`GET|HEAD /ipfs-source/v1/<object key>`, mounted at the root beside `/metrics`
(`internal/httpapi/server.go:1455`): outside `/api/v1`, outside the OpenAPI
contract, outside the rate-limited group, registered only when reference mode is on.

- **No authentication, because Kubo cannot send any**: boxo's urlstore fetches with
  `http.DefaultClient` and adds only a `Range` header
  ([fsrefstore.go](https://github.com/ipfs/boxo/blob/main/filestore/fsrefstore.go)).
  **[sourced]** A presigned URL would expire and permanently break its blocks.
- **The ledger is the authorization.** The key, or the directory prefix that
  contains it, must be the `object_key` (primary key,
  `migrations/0071_media_ipfs_pins.up.sql:22`) of a **public-network** row in state
  `pending` or `pinned`. Anything else is 404. Withdrawal therefore cuts the bytes
  off at the source the moment the row leaves those states — before unpin or gc
  run. Today an unpinned CID stays retrievable from the gateway until a gc; in
  reference mode its media segments stop resolving at once (the small files of
  5.2, being real blocks, still wait for the gc).
- **Never redirects.** Delivery elsewhere may 307 to a CDN, a presigned URL or the
  IPFS gateway itself; here that is a loop or an expiring reference. It serves
  through the existing stored-object path (`serveStoredObjectNamed`,
  `internal/httpapi/videos.go:1578`), which already turns `Range` into ranged S3
  GETs (`internal/storage/s3.go:443-486`), with bounded read timeouts so a stalled
  bucket fails Kubo's read instead of hanging it.
- **A byte-rate cap.** Any IPFS peer can ask for any block, nothing is cached
  between reads (T2), and every such read is now bucket egress. A global token
  bucket on this route (placeholder default to be set from a measurement) answers
  503 when exceeded; Kubo's read fails and the requester retries. This is what
  keeps "no extra incurred cost" true when a crawler walks the library.
- **Not reachable from the internet.** Caddy gets `handle /ipfs-source/* { respond
  404 }`, the pattern `deploy/Caddyfile:69-77` uses for `/metrics`; the prod overlay
  already publishes the api on 127.0.0.1 only. The bytes are public either way —
  the block exists so that the rate cap and the view counters cannot be bypassed.
- **Base URL:** `IPFS_SOURCE_BASE_URL`, default `http://api:8080`. It must resolve
  from the Kubo container: the unmanaged `ipfs` service shares the compose project,
  and the manager attaches its node to the application's network
  (`deploy/ipfs-manager.py:248`). **The base URL is written into every reference.**
  Changing it breaks every reference until the rows are re-indexed (5.6), so it is
  a fixed internal name — never the public hostname, never a CDN.

### 5.4 One reference per block: the invariant and the withdraw procedure (C)

This is the part of the design that can silently break videos, and the reason it
is a design and not a flag.

Because the first writer wins (T10), identical bytes reached through two object
keys share **one** reference — the first key's. Three ordinary events then leave a
live pin depending on an object that no longer exists:

1. **Delete, then re-upload the same file.** Unpinning does not remove references
   (only gc or `block/rm` does), so the re-upload's add finds the blocks present,
   writes nothing, and is born pointing at the deleted video's keys.
2. **The same file uploaded twice; the first is deleted.**
3. **A re-transcode that reproduces some renditions byte for byte** under a new
   generation directory, after which the old generation is removed.

In each case the ledger says `pinned`, the master playlist resolves (it is a real
block, 5.2) and the segments fail.

**Invariant: no reference may outlive the object it points at, and a row is
re-added only after its own old references are gone.** Whenever a reference-mode
row is withdrawn or replaced (delete, block, privacy change, eviction, new
generation), the worker:

1. enumerates the row's leaves by walking its DAG with **non-recursive** `refs`,
   descending only into dag-pb CIDs and never opening a raw (`bafkrei…`) one — every
   node it opens is a real local block, so the walk reads zero origin bytes (T12;
   the obvious `refs?recursive=true` would re-download the video);
2. `pin/rm`s the root;
3. `block/rm`s the leaves in batches. What is removed can no longer poison a later
   add. What is **refused** is still covered by another pin (T10);
4. for each refused leaf, asks `filestore/ls?arg=<leaf>` (zero origin bytes, T12)
   where it points. If it points under the key being withdrawn, the covering pin
   has borrowed it: that pin's ledger row is marked for **heal**;
5. heals each such row with the sequence T10 measured end to end: unpin it,
   `block/rm` the borrowed leaves, re-add it from its own objects. The CID does not
   change and no gc or daemon restart is needed.

Primary-storage deletion of the withdrawn objects should follow step 3 where the
calling flow allows it; where it cannot, the borrowing row is broken on IPFS until
its heal completes, and the instance serves it through normal delivery meanwhile.

`filestore/verify` is **not** a periodic job in this design: it re-downloads the
store (T12) and cannot take a root CID (T10). The invariant is kept by
construction at withdraw time, and proved by the three scenarios above as
real-Kubo acceptance tests (section 10). An admin "re-index this video" action
(the heal sequence on demand) is the manual escape hatch.

### 5.5 Node configuration (C, M)

- **Unmanaged:** `vidra-core/deploy/ipfs-public/001-configure-network-mode.sh` sets
  `Experimental.UrlstoreEnabled` from the environment; it runs on every container
  start, so a restart applies it.
- **Managed:** `ipfscontrol.HostConfig` gains one boolean and the manager's
  `public_config()` (`deploy/ipfs-manager.py:229-235`) writes it. This respects the
  boundary stated at `internal/ipfscontrol/config.go:26` — *"URLs, images, mount
  paths and commands deliberately cannot cross this boundary"*: only a boolean
  crosses; the URL travels core → Kubo inside the add request.
- **The flag is never turned off while reference rows exist** — reads of those
  blocks would fail. Core does not ask for it to be cleared while any row is in
  reference mode, and the init script only ever sets it.
- **Fail closed.** If the node rejects `nocopy` (T0), the row fails with a closed
  error code and the admin page says the node is not configured for references.
  Core **never falls back to a copy add**: that would quietly fill the disk, the
  failure this work exists to prevent.
- The pinned image stays `ipfs/kubo:v0.43.0`. v0.43.1 exists; bumping it is a
  separate decision (AGENTS.md hard rule 7).

### 5.6 Mode, conversion, rollback (C)

- **Mode** is `copy` (default) or `reference`, per instance, for the public
  network. Managed instances set it in the policy document on Admin → IPFS;
  unmanaged instances set `IPFS_PIN_STORAGE`. Each ledger row records the mode it
  was added in (new column; migration number assigned when the PR opens — 0151 is
  the newest today), because the withdraw procedure and the admission arithmetic
  differ by row, and a node legitimately holds both kinds at once.
- **Conversion is not a re-add.** A nocopy re-add over copied blocks reports
  success and reclaims nothing (T5). Per row: enumerate the blocks with recursive
  `refs` (free here — the blocks are local copies), `pin/rm`, `block/rm`, nocopy
  re-add. Blocks another copy-mode pin still covers are refused and simply stay
  copies, which is harmless: a copy cannot rot. The CID is unchanged (T5). It runs
  as a tracked, stoppable backfill paced by the existing `copy_bytes_per_second`,
  because every converted byte is read once from primary storage. **The row is off
  IPFS between its unpin and its re-add**; normal delivery is unaffected.
- The documented fallback for a small node is a fresh repo: the pinset is
  re-derivable by the project's own doctrine (section 12, D1) and the reconcile
  tick re-arms rows the node does not hold (`internal/ipfsmirror/verify.go:119`).
  It costs the node its peer identity, so conversion in place is preferred.
- **Rows evicted for capacity return.** Conversion re-arms
  `capacity_reason = 'evicted_capacity'` rows once: the budget that evicted them no
  longer binds.
- **Rollback:** set the mode back to `copy`. New adds copy; existing reference rows
  keep working; converting them back is the same procedure in the other direction.

### 5.7 Admission in reference mode (C)

Budget, free-space floor, reservations, pacing, demand pins and eviction all stay.
Only the reservation changes for a reference row: from `2 × bytes + …`
(`admission.go:110`) to the measured index cost plus the small files that are
copied. **Placeholder: `bytes / 256 + small_file_bytes + 16 KiB × files + 1 MiB`**
— four times the 0.094 % T1 measured — to be replaced by a measurement on a real
HLS tree before it ships. At that ratio a 20 GiB budget indexes on the order of
5 TiB of media, so in practice the budget stops being what ends pinning.

### 5.8 Out of scope

- **The private swarm stays in copy mode.** Its source route would serve
  non-public bytes without authentication and needs its own security review; its
  replicas copy regardless.
- **The chunk size stays 256 KiB.** 1 MiB chunks cut origin requests four-fold
  (T7) but change every CID, and "the mode never changes a CID" is what makes
  conversion and rollback safe. Section 12, D3.
- No change to delivery, to the gateway probe, or to which media classes are
  pinned.

## 6. Fixes that stand on their own

Each is a small PR that is worth shipping if reference pinning is never built.

| # | Fix | Why |
|---|---|---|
| F1 | Replace the `2 ×` reservation with a measured factor | T5 measured a copy add of 67,108,864 bytes growing the repo by 68,031,550 — **1.014 ×**. One sample of incompressible data; measure a real HLS tree, then set the factor with stated headroom. At ~1.1 × the same disk admits nearly twice the media. `admission.go:110` |
| F2 | Read `X-Stream-Error` and require the wrap entry in `ipfs.Client.add` | 5.2. Kubo reports a late add failure as HTTP 200 plus a trailer (T11a) and the client records the last hash it saw (`client.go:186-211`). Whether a copy-mode add that hits ENOSPC mid-tree takes this path is **[unverified]** — but a full disk is exactly when it would |
| F3 | Give unmanaged mode a ceiling | The legacy drain has none (`service.go:1196-1243`) and a full Kubo repo cannot even gc. Minimum: a `repo/stat`-based budget (`IPFS_REPO_BUDGET_BYTES`) that pauses the drain with the same `capacity_reason` vocabulary. Core cannot `statvfs` an unmanaged node, so this is a repo-size budget, not a free-space floor — the runbook says so |
| F4 | Make a capacity pause visible outside Admin → IPFS | `/admin/system` reports `ok` on a full budget (`system_ipfs_managed.go:29-68`), there is no capacity WARN in the logs, and no metric carries `repo_used_bytes` or the budget. Add gauges and one log line per pause transition. How `/admin/system` shows it needs vidra-user's input: a component that turns `degraded` demotes the whole page, which has broken that repo's backed test harness before |

## 7. Failure handling

The fallback in every case is today's behaviour for a video that is not on IPFS:
normal delivery.

| Situation | Behaviour |
|---|---|
| Node has the urlstore flag off | Add fails closed (T0); row fails with a closed code; **no copy fallback** |
| Primary storage unreachable or slow | Source route fails within its timeout; Kubo's read fails fast (T4a); recovers by itself when storage returns; small files keep serving from the node |
| Object changed under a live reference | Zero wrong bytes served (T4b); the row is healed by re-index |
| Video deleted, blocked or made private | Row leaves `pending/pinned` → source route 404s at once → withdraw procedure (5.4) |
| Identical bytes under two keys | 5.4: the lender's withdrawal heals the borrower |
| Add stream fails midway | Trailer check (F2) fails the row; orphan references are unpinned and the next gc removes them (T11a) |
| `IPFS_SOURCE_BASE_URL` changed | Every reference breaks. The boot check compares it with the value recorded at first use and refuses to start the mirror until the operator confirms a re-index |
| Rate cap exceeded | 503 to Kubo; the requesting peer retries; viewers on the operator's gateway fall back as they do for any gateway failure |
| Kubo is never updated again | The image is already pinned, and nothing here needs a newer one |

## 8. Security

- The route serves only bytes that are already public **and** in the public pin
  ledger, and is blocked at Caddy. Object keys are validated exactly as the storage
  layer validates them; no path reaches the backend that a ledger row does not
  cover.
- With the urlstore on, anyone who can reach the Kubo **RPC** can make the node
  fetch arbitrary URLs. The RPC is already loopback- and compose-internal only
  (`vidra-core/docker-compose.yml:1286-1312`); this design makes that binding
  load-bearing for SSRF, and the runbook must say so.
- References sit in the node's datastore in clear text. They contain internal
  object keys of public media and nothing else: no credentials, no presigned
  query strings.
- Withdrawal is *faster* than today: the bytes stop at the source when the ledger
  row changes, not at the next gc.

## 9. Surfaces

- **Admin → IPFS (U):** the mode select (managed instances), a line reading "N
  videos stored as copies · M as references · index X of budget Y", the conversion
  run with Stop, and "re-index this video". No new page.
- **Environment (M):** `IPFS_PIN_STORAGE`, `IPFS_SOURCE_BASE_URL`,
  `IPFS_SOURCE_MAX_BYTES_PER_SECOND`, `IPFS_REPO_BUDGET_BYTES` (F3). Each gets a
  compose consumer as a plain `${VAR:-}` pass-through — a compose fallback value
  would shadow the Go default — and an entry in `env/production.env.example`.
- **Runbook (M, C):** `deploy/IPFS-MANAGER.md` and `vidra-core/docs/operations.md`
  gain the mode, the base-URL warning, the RPC/SSRF note and the statement that a
  reference-mode mirror depends on primary storage.

## 10. Testing and the gates before beta

A mocked-green suite is not accepted as evidence that this works; the behaviour
that matters lives in Kubo.

- **Real Kubo, in core's existing IPFS integration lane:** nocopy add of a file and
  of an HLS tree; CID equality with copy mode; the small-file rule; the trailer
  check (a part with no `Abspath` placed last); fail-closed with the flag off; and
  the three scenarios of 5.4 — delete → re-upload, duplicate upload → delete the
  first, identical-rendition re-transcode — each ending with every segment fetched
  through the gateway.
- **Origin-read accounting:** the source route counts requests and bytes, and the
  tests assert **zero** origin bytes for the withdraw walk, the reconcile tick
  (`pin/ls`) and gc — the guard against anyone reaching for `refs -r`.
- **Source route:** 404 for a key no ledger row covers, for a private-network row,
  and for a row in `unpinning/unpinned/failed`; never a redirect; Range correctness;
  the rate cap. Reviewers mutation-test each guard: revert the clause, a test must
  fail.
- **Conversion:** copy → reference → copy on one row with the CID unchanged and
  the repo size moving as expected at each step.

**Gates, recorded in `docs/` before the mode is enabled on beta:**

1. **Reprovider.** On a networked private test swarm, origin bytes read over one
   full provide cycle under the manager's `Provide.Strategy = pinned+unique`. The
   spike could not run this. If it is not zero, the design does not ship as is.
2. **Remote retrieval.** A second peer fetches a reference-pinned tree over
   bitswap, byte-exact.
3. **Real object storage.** Against MinIO and one real provider: time to first
   frame and steady-state segment latency through the gateway, copy vs reference;
   origin requests per viewer-minute; behaviour when the bucket stalls rather than
   refuses. T8's localhost numbers say nothing about this.
4. **The placeholders** — reservation factor, rate cap — set from those runs.

## 11. PR sequence

Small PRs, each merged before the next. Section 6 goes first because it helps
today and does not depend on any decision in section 12.

1. C — F2, the trailer and wrap-entry check in `ipfs.Client.add`.
2. C — F1, the measured reservation factor, with the measurement recorded.
3. C + M — F4, capacity gauges, the pause log line, the `/admin/system` decision.
4. C + M — F3, the unmanaged repo budget.
5. C — `SourceURL` on `DirEntry`, the small-file pre-copy, the mode column; no
   caller sets it yet.
6. C + M — the source route, its ledger gate, the rate cap, the Caddy block.
7. C — the withdraw procedure and heal, with the three scenarios on real Kubo.
8. C + M — node configuration: the init script, `HostConfig`, the manager, fail
   closed.
9. C + U — mode setting, reference-mode admission, conversion run, admin surface.
10. M — the four gates, recorded; then the beta decision.

The mode defaults to `copy`, so a release containing any prefix of this list is
safe to deploy.

## 12. Decisions the owner has not made

- **D1 — Is a mirror that depends on primary storage acceptable?** In reference
  mode the IPFS copy is no longer independent: if the bucket is down, so is the
  mirror, and the gateway stops being a fallback for a primary-storage outage. The
  existing doctrine points this way — `vidra-core/docs/operations.md:1404-1406`:
  *"**The pinset is a distribution surface, never a backup.** Do **not** back up
  the Kubo datastore for durability — it holds only re-derivable copies of
  already-public bytes"* — but that sentence was written about backups, not about
  this, and it is the owner's call.
- **D2 — How much to build, given section 4?** Section 6 alone (PRs 1–4) roughly
  doubles what today's disk pins and makes the stop visible. PRs 5–10 remove the
  ceiling and carry the complexity of 5.4 on an upstream that is winding down.
- **D3 — Chunk size.** Stay at 256 KiB (recommended here: CIDs never change), or
  use 1 MiB for rows that have never been pinned (four times fewer origin requests,
  at the price of a per-row chunker record and CIDs that differ by vintage).
- **D4 — Which mode does beta run?** `IPFS_MANAGED_NODE` and the live
  `admission_paused_reason` are in the untracked env file and the database, not in
  either repo. The answer decides whether F1 or F3 is the fix beta feels first.

## 13. Risks and open items

- **5.4 is the risk.** It is correct only if every flow that removes or replaces a
  pinned object goes through the withdraw procedure. A path that deletes objects
  directly produces a video that is `pinned`, resolves its playlist and fails its
  segments. The origin-read counters and the three scenarios are the defence; the
  implementation plan must list every such flow by file:line.
- **Parsing `block/rm` refusals.** Step 3 of 5.4 learns which pin covers a block
  from Kubo's error text; `pin/ls?arg=<leaf>&type=all` is the structured
  alternative and must be compared on large pinsets.
- **What the player does mid-stream is unknown.** How the watch page chooses and
  abandons the gateway origin was not read for this document **[unverified]**. If
  it decides once, on the master playlist, then a tree whose playlist resolves and
  whose segments fail is the worst case for it, and a fatal segment error on the
  gateway origin must fall back to normal delivery. A vidra-user question for the
  plan.
- **Serving speed against a real bucket is unmeasured** (gate 3). Each block is a
  ranged GET through the api; at 256 KiB a 2 MiB segment is eight of them plus one
  of readahead.
- **Experimental upstream features, unmaintained upstream.** The filestore has
  been in-tree since 2017 and has sharness coverage for directory adds, but an open
  bug concerns recursive `--nocopy` adds combined with `--fscache`
  ([kubo#7161](https://github.com/ipfs/kubo/issues/7161)); this design never passes
  `fscache`. **[sourced]**
- **Mechanisms are behavioural.** The single-chunk add-time read and the one-block
  readahead were observed, not explained from Kubo's source.
- **The spike is one machine, one run of each test, arm64, a Python origin.** It
  establishes what Kubo does, not how fast.
