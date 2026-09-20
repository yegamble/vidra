# Reference pinning (Kubo urlstore / `nocopy` + URL `Abspath`) — local lab spike

Measured 2026-09-20 against the exact Kubo version vidra pins. Every figure below
is copied from a real run; transcripts live in `out/` (`out/RUN.txt` is the whole
end-to-end run). Reproduce with `bash run.sh`; clean up with `bash run.sh teardown`.

What is committed in `out/`: the 48 text transcripts, with the local spike
directory, scratch paths, home directory and username replaced by `<spike>`,
`<scratch>`, `<home>` and `<user>` — nothing else was altered. Not committed: the
payload and read-back `.bin` files (429 MB) and `origin-requests.txt`, the origin's
full 487 KB request log; the per-test origin excerpts that matter are in the
transcripts.

One run of each test, one machine (arm64, Docker Desktop), an offline node, a
Python origin, random payloads. This establishes what Kubo does, not how fast.

## Environment

```
$ docker exec refpin-spike-kubo ipfs version --all
Kubo version: 0.43.0-e9914bb
Repo version: 18
System version: arm64/linux
Golang version: go1.26.5

$ curl --version | head -1
curl 8.7.1 (x86_64-apple-darwin25.0) libcurl/8.7.1 (SecureTransport) LibreSSL/3.3.6 zlib/1.2.12 nghttp2/1.68.1
```

- Image `ipfs/kubo:v0.43.0` (already local; nothing pulled).
- Node is **never** on the public network: `Routing.Type=none`, `ipfs bootstrap rm --all`
  (bootstrap list empty), `Addresses.Swarm=[]`, started with `daemon --offline`
  ("Swarm not listening, running in offline mode."). RPC/gateway published on
  `127.0.0.1:15001` / `127.0.0.1:18080` only.
- **Origin placement:** `origin.py` runs **on the macOS host**, bound `0.0.0.0:18090`,
  reached from the container as `http://host.docker.internal:18090/...` (the
  container sees it as `192.168.65.254:18090`). A container-on-a-user-network origin
  was not needed. Binding `0.0.0.0` is required because `host.docker.internal`
  traffic arrives from the Docker VM, not from loopback.
- curl 8.7.1 supports the `;headers="..."` form, so no Python multipart builder was
  needed. Parts look like:
  `-F 'file=@payload1.bin;filename=payload1.bin;headers="Abspath: http://host.docker.internal:18090/payload1.bin"'`
- Default chunker is 256 KiB (`Import.UnixFSChunker: null`), so a 64 MiB payload is 256 leaves.

## Summary

| Test | Verdict | One line |
|---|---|---|
| T0 urlstore off | **PASS** | HTTP 500, `either the filestore or the urlstore must be enabled to use nocopy` — no origin contact. |
| T1 nocopy add 64 MiB | **PASS** | CID **identical** to a copy add; repo grows **0.094%** of payload; **0 origin reads at add time** — the streamed bytes are what gets hashed. |
| T2 read back | **PASS** | RPC + gateway both byte-exact; **256 ranged GETs of exactly 262144 B**, zero non-Range requests, no caching between reads. |
| T3 HLS directory | **PASS** | Per-part `Abspath` works, root CID **identical** to a copy add, nested gateway path resolves; a 225-byte playlist becomes a **reference**, not an inline. |
| T3 probe | **SURPRISE** | A file that fits in **one chunk** costs exactly **one full-file origin read at add time** (≤262144 B); ≥2 chunks costs zero. Independent of `pin`. |
| T4a origin down | **PASS** | Gateway 500 `cannot detect content-type: failed to fetch all nodes` in ~0.03 s; **recovers with no re-add** when the origin returns. |
| T4b wrong bytes | **PASS** | Integrity holds: **0 bytes** served, generic `failed to fetch all nodes`; heals by itself once bytes are right again. |
| T4c 404 | **PASS** | Same generic error; `filestore/verify` gives the good message (`expected HTTP 200 or 206 got 404`). |
| T4d 307 redirect | **PASS** | Followed, bytes correct, **Range survives the redirect** — but costs **2 requests per block**. |
| T5 migration | **SURPRISE** | A nocopy re-add over an already-copied pin is a **silent no-op** — 0 references written, repo stays 68 MB. Cheapest fix: `pin/rm` → `repo/gc` → nocopy re-add; CID unchanged. |
| T6 GC safety | **PASS** | `repo/gc` keeps references while pinned and `cat` still works; `pin/rm`+`repo/gc` removes them and reads 404 offline. |
| T7 chunk size | **PASS** | `chunker=size-1048576` changes the CID (expected); one full read = 256 GETs @256 KiB vs **64 GETs** @1 MiB, same total bytes. |
| T8 throughput | **PASS (weak)** | 64 MiB gateway read: copy **0.401 s** median vs nocopy **2.635 s** median — ~6.6× against a *localhost* origin. Says nothing about S3. |
| T9 concurrency | **PASS** | 8 parallel 1 MiB range reads all byte-exact, all HTTP 206, no daemon errors. |
| T10 first-writer-wins | **SURPRISE** | Second URL writes **nothing**; when URL A rots the pin is dead even though B is healthy. `block/rm` refuses while **any** pin covers the block, `force=true` does **not** override. |
| T11a missing Abspath | **PASS / SURPRISE** | Rejected `missing file path or URL, can't create filestore reference` — but if the bad part is **last**, the response is **HTTP 200** with the error only in the `X-Stream-Error` trailer, and 8 orphan references are left with no pin. |
| T11b pre-copy trick | **PASS** | Works: copy-add the small file first (`pin=false`), then the nocopy tree — the playlist stays a **real block**, serves with the origin 404ing, and survives `repo/gc`. |
| T12 maintenance reads | **SURPRISE** | `pin/ls`, `pin/verify`, `repo/stat`, `repo/gc`, `files/stat`, `ls`, `block/stat`, `filestore/ls` → **0 origin bytes**. But `refs -r` and `dag/stat` **re-download the whole file**, and every gateway read has a **2-block (512 KiB) floor**. Reprovider **could not be tested** (offline). |

---

## T0 — `nocopy` with `Experimental.UrlstoreEnabled=false`

```
$ docker exec refpin-spike-kubo ipfs config Experimental
{ "FilestoreEnabled": false, ..., "UrlstoreEnabled": false }

$ curl -sS -X POST "$API/add?nocopy=true&cid-version=1&raw-leaves=true&pin=true&progress=false" \
    -F "file=@payload1.bin;filename=payload1.bin;headers=\"Abspath: http://host.docker.internal:18090/payload1.bin\""
HTTP/1.1 500 Internal Server Error
{"Message":"either the filestore or the urlstore must be enabled to use nocopy, see: https://github.com/ipfs/kubo/blob/master/docs/experimental-features.md#ipfs-filestore","Code":0,"Type":"error"}

--- origin requests during T0 ---   (empty)
```

**Verdict: PASS.** Fails closed with an actionable message, before touching the origin.
Note the wording: **either** flag satisfies it. Everything below was measured with
`UrlstoreEnabled=true` and `FilestoreEnabled` left **false** — URL-backed nocopy needs
only the urlstore flag.

## T1 — 64 MiB nocopy add, bytes streamed in the body

```
$ ipfs config --json Experimental.UrlstoreEnabled true   # + restart
$ curl ... "$API/add?only-hash=true&cid-version=1&raw-leaves=true" -F file=@payload1.bin
only-hash CID: bafybeibnsrbh65nrgdpsvlpwilk6ozx6phs6wunsmel7tu5mjsry4c5zsq

$ curl ... "$API/add?nocopy=true&cid-version=1&raw-leaves=true&pin=true&progress=false" \
    -F "file=@payload1.bin;filename=payload1.bin;headers=\"Abspath: http://host.docker.internal:18090/payload1.bin\""
http=200 time=0.300416s
{"Name":"payload1.bin","Hash":"bafybeibnsrbh65nrgdpsvlpwilk6ozx6phs6wunsmel7tu5mjsry4c5zsq","Size":"67121797"}

IDENTICAL: nocopy CID == copy-mode CID
RepoSize before 26247  after 89246  delta 62999 bytes (0.060 MiB) = 0.0939% of 64 MiB payload
entries: 256
origin request count during add: 0
```

`filestore/ls` sample:

```
{"Status":0,"ErrorMsg":"","Key":{"/":"bafkreiaohsapmqdamm4pjprs6ckiks24bbj67k3r325gtp3ljfl2htdlp4"},"FilePath":"http://host.docker.internal:18090/payload1.bin","Offset":6815744,"Size":262144}
{"Status":0,"ErrorMsg":"","Key":{"/":"bafkreiap7gl5opb5p42zajlw6jc3lird4r7bkwwjqs4trlh6tt56wpgbvq"},"FilePath":"http://host.docker.internal:18090/payload1.bin","Offset":21495808,"Size":262144}
```

**Verdict: PASS, and the central design claim holds.** Kubo hashed the bytes we
streamed and stored only `{URL, offset, length}` triples. The 63 KB of growth is the
UnixFS root plus 256 reference records — **0.094%** of the payload. The CID is
byte-for-byte what today's copy add produces, so switching modes does not change any
already-published CID. **Kubo did not contact the origin at all during the add.**

## T2 — read back

```
$ curl -X POST "$API/cat?arg=$CID"            http=200 time=2.588647s size=67108864   RPC MATCH
$ curl "$GW/ipfs/$CID"                        http=200 time=2.488587s size=67108864   GATEWAY MATCH
origin requests: 256    with Range: 256    without Range: 0
range-size histogram:   256 x 262144
2026-09-20T13:20:16.453 ... "GET /payload1.bin" Range=bytes=0-262143 ... -> 206
2026-09-20T13:20:16.470 ... "GET /payload1.bin" Range=bytes=262144-524287 ... -> 206
```

**Verdict: PASS.** One ranged GET per block, exactly one block wide, never a whole-object
GET. The gateway read issued its own 256 requests — **nothing is cached between reads**,
so every playback of a cold file is a full set of origin GETs.

## T3 — HLS directory tree, one `Abspath` per part

```
$ curl ... "$API/add?nocopy=true&cid-version=1&raw-leaves=true&pin=true&recursive=true&wrap-with-directory=true" \
   -F 'file=@/dev/null;filename=hls;type=application/x-directory' \
   -F 'file=@hls__master.m3u8;filename=hls/master.m3u8;headers="Abspath: .../hls/master.m3u8"' \
   -F 'file=@/dev/null;filename=hls/720p;type=application/x-directory' \
   -F 'file=@hls__720p__init.mp4;filename=hls/720p/init.mp4;headers="Abspath: .../hls/720p/init.mp4"' \
   -F 'file=@hls__720p__seg-1.m4s;filename=hls/720p/seg-1.m4s;headers="Abspath: .../hls/720p/seg-1.m4s"'
{"Name":"hls/master.m3u8","Hash":"bafkreiede27t6tjhxurohbuw2p6e3xjgb6kcgshp2fdia734sr7zqtbfde","Size":"225"}
{"Name":"hls/720p/init.mp4","Hash":"bafkreih7gjtzws5254vo7yexz3mqyrt243zatux33crai7rc65d27uvr7e","Size":"700"}
{"Name":"hls/720p/seg-1.m4s","Hash":"bafybeib44snfojlej6s6rj7fodgvwu3yu2xstiax67b6imkecj3hmh7ooe","Size":"3146337"}
{"Name":"","Hash":"bafybeidosoqui4j57nlswzl3whsrjyc2xsytn7hmmybawofr3hv6fsggie","Size":"3147540"}

ROOT CIDs IDENTICAL          (vs. a copy-mode add of the same tree)
$ curl "$GW/ipfs/$ROOT/hls/720p/seg-1.m4s"   http=200 size=3145728   SEGMENT MATCH
$ curl "$GW/ipfs/$ROOT/hls/master.m3u8"      -> #EXTM3U ... (correct text)
```

Tiny files become **references, not inlines**:

```
{"Key":{"/":"bafkreiede27t6tjhxurohbuw2p6e3xjgb6kcgshp2fdia734sr7zqtbfde"},"FilePath":".../hls/master.m3u8","Offset":0,"Size":225}
{"Key":{"/":"bafkreih7gjtzws5254vo7yexz3mqyrt243zatux33crai7rc65d27uvr7e"},"FilePath":".../hls/720p/init.mp4","Offset":0,"Size":700}
```

**Verdict: PASS.** Directory parts (`type=application/x-directory`, empty body) plus
nested `filename=` values work, each file part carries its own URL, and the root CID
matches a copy add. Unescaped `/` in `filename=` is accepted. **The 225-byte playlist
and the 700-byte init segment are references** — every playlist fetch therefore hits
the origin (see T11 for how to avoid that).

## T3 probe — the single-chunk add-time read (SURPRISE)

```
single-small-file nocopy add (300 B)   -> 1 origin read
single-multichunk nocopy add (3 MiB)   -> 0 origin reads
directory nocopy add (3 files)         -> 2 origin reads   (the m3u8 and the init.mp4, not the segment)

sc_pin_true.bin  (400 B)     pin=true   -> 1 origin read   GET Range=bytes=0-399
sc_pin_false.bin (400 B)     pin=false  -> 1 origin read
sc_exact.bin     (262144 B)  pin=false  -> 1 origin read   GET Range=bytes=0-262143
mc_justover.bin  (262145 B)  pin=false  -> 0 origin reads
mc_pin_true.bin  (1000000 B) pin=true   -> 0 origin reads
```

**SURPRISE.** The boundary is **exactly the chunk size**. A file of ≤262144 bytes — whose
DAG root *is* the single raw filestore leaf — causes Kubo to read that block straight back
from the origin during the add. Anything needing ≥2 chunks (so the root is a dag-pb node
held as a real block) causes none. `pin=true/false` makes no difference, so it is not the
pinner. The practical cost: an HLS tree pays one origin round-trip per small file
(playlist, init segment, VTT) at publish time. Mechanism not confirmed in source; the
behaviour is reproducible and the boundary is exact.

## T4 — failure modes

### (a) origin stopped

```
RPC cat:  http=200 size=0  real 0.03   Trailer X-Stream-Error: failed to fetch all nodes
gateway:  http=500 size=54 real 0.03   cannot detect content-type: failed to fetch all nodes

filestore/verify (whole store), origin down, real 0.31
{"Status":10,"ErrorMsg":"Get \"http://host.docker.internal:18090/payload1.bin\": dial tcp 192.168.65.254:18090: connect: connection refused", ...}
status histogram: 256 x payload1.bin, 16 x t4.bin, 12 x hls/720p/seg-1.m4s, ...  (all Status 10)

--- after restarting the origin, no re-add ---
http=200 size=4194304   RECOVERED without re-add: MATCH
```

**Verdict: PASS.** Fails fast and **recovers by itself** — the reference is durable, only
the fetch failed. Timing caveat: this step took **0.31 s** in the clean run but **30.34 s**
in an earlier run of the same code; a host that actively refuses fails fast, and I did
**not** test a blackholed origin (dropped packets), which is the case that would hang.

### (b) origin serves different bytes at the same URL

```
RPC cat:  http=200 size=0  real 3.20   X-Stream-Error: failed to fetch all nodes
gateway:  http=500 size=54 real 3.19
filestore/verify?arg=<root>: {"Status":30,"ErrorMsg":"ipld: could not find bafkrei...","FilePath":"","Offset":0,"Size":0}
```

**Verdict: PASS on integrity, weak on diagnosis.** **Zero** bytes of wrong content are
served — Kubo re-hashes every fetched block. But the client-facing error is the same
generic `failed to fetch all nodes` as for a missing origin, so corruption and outage are
indistinguishable from the read path alone.

### (c) origin returns 404

```
RPC cat:  http=200 size=0  real 0.03   X-Stream-Error: failed to fetch all nodes
gateway:  http=500 size=54 real 0.03
filestore/verify (leaf):  {"Status":10,"ErrorMsg":"expected HTTP 200 or 206 got 404", ...}
```

**Verdict: PASS.** `filestore/verify` is the only call that names the real cause.

### (d) origin returns 307 to a path serving the right bytes

```
RPC cat:  http=200 size=4194304   (X-Stream-Error empty)
gateway:  http=200 size=4194304 time=0.033042s   REDIRECT GATEWAY MATCH
origin hits: 32  (307s: 16, 206s: 16)

"GET /t4.bin"       Range=bytes=0-262143      mode=redirect -> 307
"GET /redir/t4.bin" Range=bytes=0-262143      mode=redirect -> 206
"GET /t4.bin"       Range=bytes=262144-524287 mode=redirect -> 307
"GET /redir/t4.bin" Range=bytes=262144-524287 mode=redirect -> 206
```

**Verdict: PASS.** Redirects are followed and **the `Range` header survives the redirect
unchanged**. Cost: **2 HTTP requests per block** (16 blocks → 32 requests). Relevant if the
stored URL would be a redirector to presigned storage URLs.

After all four abuses, with the origin healthy again: `HEALED: MATCH (no re-add, no restart)`.

## T5 — migrating an already-copied pin to references (SURPRISE)

```
0. before anything                         RepoSize=186579     NumObjects=347
1. after COPY add of payload2 (64 MiB)     RepoSize=68218129   NumObjects=607   refs: 0
2. after nocopy RE-ADD (same bytes + URL)  RepoSize=68218660   NumObjects=607   refs: 0
   {"Name":"payload2.bin","Hash":"bafybeifnh6du3fblj6jrvq4fj5epyuuwgk3p2iphczfkdc66idffnept7i",...}
   filestore/dups: 0 lines        origin hits during the re-add: 0
3. after pin/rm                            RepoSize=68218940   NumObjects=607   refs: 0
4. after repo/gc (274 entries removed)     RepoSize=1119793    NumObjects=333   refs: 0
5. after nocopy re-add                     RepoSize=1166408    NumObjects=593   refs: 256
   CID UNCHANGED across the migration
   pin/ls -> {"Keys":{"bafybeifnh6du3...":{"Type":"recursive"}}}
   readback http=200 size=67108864   READBACK MATCH
```

**SURPRISE, and the most important operational result.** Step 2 **looks like a success** —
HTTP 200, the right CID returned — but writes **nothing**: RepoSize stays at 68 MB,
`filestore/ls` gains 0 entries, `filestore/dups` is empty. Kubo already `Has` those blocks,
so the reference is never recorded. **A fleet-wide "re-add everything with nocopy" migration
would report total success and reclaim zero bytes.**

Cheapest sequence that actually converts: **`pin/rm` → `repo/gc` → nocopy re-add**. The CID
is unchanged, the pin is restored, and the read path works. Two caveats for the spec:
`repo/gc` is **global**, not per-CID (T10 shows a per-CID alternative), and between the gc
and the re-add the content is **unavailable** on that node.

## T6 — GC safety

```
(a) with the nocopy pin in place
refs before gc: 256    gc removed 1 entries    refs after gc: 256
read after gc: http=200 size=67108864    SURVIVES GC: MATCH
pin/ls -> recursive

(b) pin/rm then repo/gc
gc removed 259 entries       refs after unpin+gc: 0
gc output names the dropped refs: {"Key":{"/":"bafkrei..."}} ...
gateway: http=404 size=273 time=0.001056s
  failed to resolve /ipfs/bafybei...: block was not found locally (offline): ipld: could not find bafkrei...
RPC cat: http=500
RepoSize=1176265
```

**Verdict: PASS.** `repo/gc` respects a nocopy pin — references survive and reads still work.
Unpin + gc drops the references and the content becomes unreachable (the node is offline,
so there is no network fallback to mask it). GC reclaims the *reference records*, never
origin bytes.

## T7 — chunk size

```
256 KiB chunker CID: bafybeibnsrbh65nrgdpsvlpwilk6ozx6phs6wunsmel7tu5mjsry4c5zsq
1 MiB   chunker CID: bafybeifa42em4wnwbafxgmfohpwhmrersyauet26xfihiynnp4ht4ljtnu
CIDs DIFFER (expected: chunking is part of the CID)
filestore entries with Size 1048576: 64

full read @256 KiB: 256 request(s), 67108864 bytes
full read @1 MiB:    64 request(s), 67108864 bytes
both readbacks byte-exact
```

**Verdict: PASS.** A 4× larger chunk is a 4× cut in origin request count for the same
bytes — a direct lever on per-request S3 cost. It changes the CID, so it must be decided
before publishing, not after.

## T8 — rough throughput (weak evidence, stated as such)

```
64 MiB gateway read, 3 runs each
copy mode : median 0.401s  (runs: 0.314, 0.401, 0.412)
nocopy    : median 2.635s  (runs: 2.565, 2.635, 2.815)
```

**Verdict: PASS, but do not cite this as a latency model.** ~6.6× slower with the origin on
**localhost**, i.e. with essentially zero network latency and a single-threaded Python
server. Against S3/Spaces the per-request latency (tens of ms × 256 sequential-ish
requests) dominates and this ratio is meaningless. **A localhost origin says nothing about
S3 latency.**

## T9 — concurrency

```
8 parallel gateway range reads (1 MiB each, different offsets)
range 0..7: all http=206, all MATCH (1048576 bytes each)
all curls exited 0: yes
origin traffic: 39 request(s), 10223616 bytes      (40 requests in an earlier run)
kubo daemon log grep -iE 'error|panic|fatal|warn': (no error/warn lines)
```

**Verdict: PASS.** All eight byte-exact, no daemon errors. 39 requests (40 in an earlier
run) for 8 MiB of requested data = the 32 blocks actually needed plus per-read readahead
(see T12); the count varies by one because overlapping readahead is sometimes already
in flight.

## T10 — first writer wins, and how to heal it (SURPRISE)

```
1. nocopy add, Abspath .../a/dup.bin, pinned
   CID X = bafybeieb3idxciyqy237nwqdfavye77rx7qy4s6dgxf6tunjtnxaf55xjq   (8 MiB => 32 chunks)
        32 refs -> http://host.docker.internal:18090/a/dup.bin
2. nocopy add of the SAME bytes, Abspath .../b/dup.bin
   {"Name":"dup.bin","Hash":"bafybeieb3id...","Size":"8390218"}      <-- looks successful
        32 refs -> http://host.docker.internal:18090/a/dup.bin       <-- /b was NOT recorded
3. /a/dup.bin -> 404, /b/dup.bin -> 200
   gateway: http=500 size=54 time=0.026570s   cannot detect content-type: failed to fetch all nodes
```

**SURPRISE.** Kubo stores exactly **one** reference per block and the **first** writer wins.
A second URL for identical bytes is recorded nowhere, so when URL A rots the pin is dead
even though a healthy copy sits at B. There is no built-in failover between sources.

`filestore/verify` behaviour:

```
whole store:  real 0.04   lines: 32   bad: 32
  {"Status":10,"ErrorMsg":"expected HTTP 200 or 206 got 404","Key":{"/":"bafkreiagpz..."},"FilePath":".../a/dup.bin","Offset":4194304,"Size":262144}
verify?arg=<ROOT cid>: real 0.00
  {"Status":30,"ErrorMsg":"ipld: could not find bafkreieb3idxciyqy237nwqdfavye77rx7qy4s6dgxf6tunjtnxaf55xjq","FilePath":"","Offset":0,"Size":0}
verify?arg=<one leaf key>:
  {"Status":10,"ErrorMsg":"expected HTTP 200 or 206 got 404","Key":{"/":"bafkreibgcm..."},"FilePath":".../a/dup.bin","Offset":0,"Size":262144}
```

**`filestore/verify` does not accept a root CID in any useful sense.** Note the reported
key: the `bafybei…` (dag-pb) root comes back as `bafkrei…` — the **same multihash re-coded
as raw** — and is then "not found", because only leaves are filestore keys. So verify works
per-**leaf key** or over the **whole store**; there is no "verify this one video" call.
Timing scales with store size, not with the CID you asked about — measured on this node:
**32 entries → 0.04 s**, **334 entries → 4.14 s** (`real 4.14`, 334 lines, origin healthy),
and with the origin down it is one failed HTTP request per entry.
To health-check one video you must enumerate its leaves yourself — and see T12, `refs -r`
is an expensive way to do that.

Heal attempts, in increasing cost:

```
(i)  plain nocopy re-add from /b, nothing else
     {"Name":"dup.bin","Hash":"bafybeieb3id...","Size":"8390218"}
     32 refs -> .../a/dup.bin        gateway: http=500      -> NO-OP, same as T5
(ii) block/rm while X is still pinned
     {"Hash":"bafkreibgcm...","Error":"pinned via bafybeieb3idxciyqy237nwqdfavye77rx7qy4s6dgxf6tunjtnxaf55xjq"}
     with force=true: identical refusal        leaf still in filestore/ls? 1
(iii) a SECOND pin (wrapping directory) covering the same leaf, X unpinned
     {"Hash":"bafkreibgcm...","Error":"pinned via bafybeifckcfh6kzetpggf6vlcan6sjkwrsmcma4o7pczyewtiy5v4ffeji"}
     leaf still present? 1
(iv) unpin EVERY pin covering the blocks, block/rm all 32 leaves (+ root), re-add from /b
     block/rm results: 32 lines, errors: 0
     reference sources after block/rm: (no dup.bin references)
     CID after heal: bafybeieb3id...      CID UNCHANGED
     32 refs -> http://host.docker.internal:18090/b/dup.bin
     gateway: http=200 size=8388608       HEALED: MATCH (no daemon restart needed)
```

**Cheapest working heal: unpin every pin that covers the blocks → `block/rm` the leaves →
nocopy re-add from the good URL.** No `repo/gc` and **no daemon restart** required, which
makes it per-CID rather than global (unlike T5's recipe). Two hard constraints:
`block/rm` refuses while **any** pin covers the block — including a wrapping directory pin
that has nothing to do with the CID you are repairing — and **`force=true` does not
override a pin** (it only suppresses not-found errors).

## T11 — mixing copy and reference in one tree

### (a) one part with no `Abspath`

```
$ ... nocopy directory add, playlist part deliberately without Abspath (playlist FIRST)
{"Message":"missing file path or URL, can't create filestore reference","Code":0,"Type":"error"}
http=500
resulting filestore refs mentioning mix/: (none)
```

But with the bad part **last** (`t11c.sh`):

```
$ ... good part (with Abspath) first, bad part (no Abspath) last
{"Name":"mix2/720p/seg-1.m4s","Hash":"bafybeifa2twkul2cs3zpllknehodlpcrhwl6rbezrgfbnvbekfiktlolwi","Size":"2097561"}
http=200                                     <-- 200, not 500
HTTP/1.1 200 OK
Trailer: X-Stream-Error
X-Stream-Error: missing file path or URL, can't create filestore reference
   seg-1 refs now: 8
   total filestore entries: 8
   pins: 0
```

**PASS on fail-closed semantics, SURPRISE on reporting.** Kubo never mixes a copied block
into a nocopy add implicitly — it refuses. But the HTTP status is decided before the stream
ends, so a failure on a later part returns **HTTP 200** with the error only in the
`X-Stream-Error` **trailer**, leaving **orphan references, no root CID and no pin**.
Any client must check the trailer *and* that a root entry arrived; status code alone is not
a success signal. The 8 orphans are unpinned, so a later `repo/gc` reclaims them — verified directly:
`orphan refs after the failed add: 8` → `orphan refs after repo/gc: 0`.

### (b) the pre-copy trick

```
1. add the playlist ALONE in copy mode, pin=false
   playlist CID: bafkreia3r6mevd3p4e5o4tusda4y46flb76sps25tmzlh5sr7ygdqy2zgm
   in filestore/ls? 0   (== a real block)
2. full nocopy tree add, Abspath on EVERY part including the playlist
   http=200, root emitted
   playlist CID in the tree == standalone CID? yes
   playlist in filestore/ls? 0     (still a real block)
   seg-1 refs: 8      init.mp4 refs: 1

with the origin returning 404:
   playlist: http=200 size=225    PLAYLIST SERVED FROM LOCAL BLOCK: bytes match
   segment:  http=500 size=54
   init.mp4: http=500 size=204

after repo/gc while the tree is pinned:
   gc removed 1 entries
   block/stat playlist -> {"Key":"bafkreia3r6...","Size":225}
   playlist after gc (origin 404): http=200 size=225    SURVIVES GC: bytes match
```

**Verdict: PASS — the trick works and is cheap.** Pre-copying a small file makes it a real
block; the later nocopy add sees `Has`=true and leaves it alone (the same first-writer-wins
rule as T5/T10, used deliberately). The playlist then serves with the origin down and
survives `repo/gc` because the tree pin covers it, while the 2 MiB segment and the
un-pre-copied 700-byte `init.mp4` remain origin-dependent. This is the lever for keeping
playlists/init segments/VTTs locally resident while large media stays by reference — and it
also removes those files' add-time origin read from the T3 probe.

## T12 — which maintenance operations read origin bytes

Fixtures: one 64 MiB nocopy pin + one nocopy HLS directory, 270 filestore refs.

```
  pin-ls-all                         0 request(s), 0 bytes
  pin-ls-one                         0 request(s), 0 bytes
  pin-verify                         0 request(s), 0 bytes
  repo-stat                          0 request(s), 0 bytes
  repo-stat-sizeonly                 0 request(s), 0 bytes
  repo-gc                            0 request(s), 0 bytes
  refs-recursive                   256 request(s), 67108864 bytes (64.00 MiB)
  refs-dir-recursive                14 request(s),  3146653 bytes ( 3.00 MiB)
  dag-stat                         256 request(s), 67108864 bytes (64.00 MiB)
  files-stat                         0 request(s), 0 bytes
  ls-dir                             0 request(s), 0 bytes
  block-stat-root                    0 request(s), 0 bytes
  gateway-HEAD                       2 request(s),   524288 bytes (0.50 MiB)
  gateway-range-1k                   2 request(s),   524288 bytes (0.50 MiB)
  filestore-verify                 270 request(s), 70255517 bytes (67.00 MiB)
  filestore-ls                       0 request(s), 0 bytes
```

Confirmed in isolation (`t12b.sh`):

```
  refs-nonrecursive          0 request(s), 0 bytes
  refs-recursive-2         256 request(s), 67108864 bytes
  refs-unique              256 request(s), 67108864 bytes
  gw-head-2                  2 request(s), 524288 bytes
  gw-1byte                   2 request(s), 524288 bytes
  gw-1kib                    2 request(s), 524288 bytes
  gw-mid                     2 request(s), 524288 bytes

exact ranges for a 1 KiB read at offset 33554432:
  "GET /payload1.bin" Range=bytes=33554432-33816575 -> 206 bytes=262144
  "GET /payload1.bin" Range=bytes=33816576-34078719 -> 206 bytes=262144
```

**The good news:** the operations an operator actually runs on a schedule —
`pin/ls`, `pin/verify`, `repo/stat`, `repo/gc`, `files/stat`, `ls`, `block/stat`,
`filestore/ls` — cost **zero origin bytes**. Pin bookkeeping never re-downloads payload.

**SURPRISE 1: `refs -r` re-downloads everything.** `refs?recursive=true` on a 64 MiB file
pulled all 64 MiB (256 requests); non-recursive pulled nothing; `unique=true` did not help.
On the HLS tree it pulled all 3 MiB. This matters because `refs -r` is the obvious way to
enumerate a video's leaves — which is exactly what T10 showed you need for a per-CID health
check. **A naive "verify my pins" cron built on `refs -r` would re-download the entire
library from S3 every run.** `dag/stat` has the same cost.

**SURPRISE 2: every gateway read has a 2-block floor.** A HEAD, a 1-byte range and a 1 KiB
range each cost **2 origin requests / 512 KiB**. The mid-file case proves it is one-block
**readahead**, not content sniffing: the two ranges fetched are the target block and the one
immediately after it, not block 0. So the floor for any byte served is
**256 KiB × 2 = 512 KiB** of origin traffic, and a HEAD request — which returns no body —
still costs half a megabyte.

**Could not test: the DHT reprovider.** The node must be offline, and every provide-related
RPC refuses:

```
  provide/stat     -> {"Message":"this command must be run in online mode. Try running 'ipfs daemon' first",...}
  stats/provide    -> {"Message":"this command must be run in online mode. ...",...}
  bitswap/stat     -> {"Message":"unable to run offline: this command must be run in online mode. ...",...}
  routing/provide  -> argument "key" is required
  stats/repo       -> {"RepoSize":1406532,...}          (works, 0 origin reads)
  ipfs config Reprovider -> {}
```

So whether the periodic reprovide walk reads payload bytes is **unmeasured**. The evidence
above is only a proxy: reprovide needs CIDs, and every CID-enumerating call that stayed
local (`pin/ls`, `filestore/ls`) cost nothing, while the DAG-walking ones (`refs -r`,
`dag/stat`) cost everything. This must be measured on a networked node before the spec
claims anything about it.

---

## Things this spike does not establish

- **No S3, Spaces or MinIO.** The origin is a 40-line local Python server. Latency,
  per-request cost, throttling, TLS handshakes, presigned-URL expiry and redirect chains
  are all untested.
- **No networked node.** Offline throughout, so bitswap, the DHT, reproviding and remote
  retrieval of reference-pinned content are untested. Whether other peers can actually
  fetch a URL-backed block over bitswap was never exercised.
- **No blackholed origin** (packets dropped rather than refused), which is the failure
  mode most likely to hang reads rather than fail them.
- **No long-running or concurrent-writer test**, no restart-under-load, no repo corruption.
- Mechanism claims are behavioural only — nothing was read from Kubo's source to explain
  the single-chunk add-time read or the one-block readahead.
