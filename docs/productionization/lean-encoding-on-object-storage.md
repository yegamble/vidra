# Keeping instances lean when encoding with S3 enabled

**Status:** researched and IMPLEMENTED 2026-08-20. All six items in §5 shipped and merged to
`vidra-core` main (`e16edb7`). Feeds Phase 2 (storage) and Phase 3 (media pipeline).

See §6 for what landed, what it measured out at, and what is deliberately still open.

**Question asked:** PeerTube stores videos locally and *then* moves them to S3, so a server needs
enough disk for the encode queue, and a server that dies mid-flight can lose or corrupt an upload.
Can Vidra keep the bytes in object storage instead — for durability, and so several `vidra-core`
instances can serve one deployment?

**Short answer:** the durability half is already solved — better than PeerTube's — and the premise
that Vidra loses uploads on instance death is not true today. The *leanness* half is not solved:
with `STORAGE_BACKEND=s3`, one upload can pull its own original out of the bucket up to eight
times and stage roughly **5× the source size** on local disk before a single byte is uploaded. And
there is a 10-line bug in the S3 backend that allocates a **528 MiB buffer on every single `Put`**,
including 4 KB thumbnails.

---

## 1. What is already lean (don't rebuild)

Vidra's ingest path is *already* object-storage-native, and this is the part PeerTube gets wrong:

- **Uploads never touch local disk.** `internal/upload/service.go` PUTs each 8 MiB chunk straight
  into the backend at `uploads/<session>/<n>` (`service.go:287`). On completion, `chunkAssembler`
  (`service.go:509`) streams the chunks back out in order as one `io.Reader` — the assembled file
  is never materialised anywhere.
- **So an instance dying mid-upload loses nothing.** The chunk ledger is in Postgres
  (`upload_chunks`), the bytes are in the bucket. A client resumes against
  `GET /uploads/:id`, or `ActiveSessionsForUser` reconstructs the whole in-flight list after a
  browser refresh or a device change. There is no local staging directory to lose.
- **The S3 backend streams both ways.** `Put` uses multipart so a large original is never buffered
  whole in memory (`internal/storage/s3.go:155`); `Open` returns a `*minio.Object`, which is an
  `io.ReadSeeker` whose seeks become ranged GETs — so `http.ServeContent` gets Range/206 without a
  local file (`s3.go:171`, `httpapi/videos.go:1292`).
- **ClamAV already streams.** `internal/media/clamav.go:49` reads the object through `Open` — no
  temp file.
- **The transcode queue is durable.** `transcode_jobs` with retry/backoff/dead-letter, plus
  `internal/jobrecovery` returning stranded rows at boot. A crash mid-encode costs CPU, not data.

The gap is entirely in the **encode** stage, which is still written as if the blob store were a
local filesystem.

---

## 2. The four leaks, measured

### Leak 1 — every `Put` allocates 528 MiB (the one to fix first)

`storage.Backend.Put` takes an `io.Reader` with no size, so `S3.Put` passes `-1`:

```go
// internal/storage/s3.go:161
info, err := s.client.PutObject(ctx, s.bucket, key, r, -1, minio.PutObjectOptions{})
```

With an unknown size, minio-go routes to `putObjectMultipartStreamNoLength`, which does:

```go
// minio-go/v7@v7.2.1/api-put-object.go:410,433
totalPartsCount, partSize, _, err := OptimalPartInfo(-1, opts.PartSize)  // partSize = 553,648,128
buf := make([]byte, partSize)                                            // 528 MiB, every call
```

The SDK's own unit test pins the number: `OptimalPartInfo(-1, 0)` → `partSize == 553648128`
(`api_unit_test.go:158`). The doc comment explains why — with no size it assumes the 5 TiB maximum
and divides by the 10,000-part limit — and explicitly says *"callers should set configuredPartSize
explicitly to control memory usage."* Vidra never does.

Consequences, in descending order of how much they hurt:

1. **Every object becomes a 3-call multipart upload.** A 4 KB thumbnail, a 200 KB `.ts` segment, a
   `master.m3u8` — each costs `CreateMultipartUpload` + `UploadPart` + `CompleteMultipartUpload`
   instead of one `PutObject`. An HLS ladder is hundreds to thousands of segments, so this triples
   the request count and the round-trip latency of `storeTree` — which is already serial.
2. **A 528 MiB live heap object per in-flight `Put`.** Ten concurrent chunk uploads = 5.3 GB of
   buffer alive at once. Go faults pages lazily, so RSS tracks bytes actually read rather than the
   full allocation — but the GC heap *goal* is computed from the allocation, so the heap target
   inflates regardless, and a reused span gets zeroed in full before use. This wants measuring, not
   assuming; the request-count problem above stands on its own.
3. **Every 8 MiB upload chunk goes through this path too**, in the API container, on the request
   goroutine.

**Fix:** thread the known size through. `PutChunk` knows `expected`; `storeTree` can `Stat` the
file; `AttachOriginal` knows the session's `total_size`. Either widen `Backend.Put` or add a
`SizedPutter` optional capability alongside `PrefixDeleter`/`ObjectLister`. Where the size is
genuinely unknown, at minimum set `PutObjectOptions{PartSize: 16 << 20}` — minio's own `minPartSize`
— which drops the buffer from 528 MiB to 16 MiB. This is a small, self-contained change with no
behavioural risk, and it is the highest payoff-per-line item in this document.

### Leak 2 — the original is downloaded up to 8 times per video

`internal/media/ffprobe.go:65`, `objectPath()`, is the shared "give me a local path" helper. On the
local backend it returns the real path for free. On S3 it **copies the entire object to a temp
file**. Every call site pays that in full:

| # | Call site | Trigger |
|---|-----------|---------|
| 1 | `clamav.go:49` (streams, no temp file) | `MALWARE_SCAN_MODE` set |
| 2 | `ffprobe.go:42` ← `video.Process` probe | always |
| 3 | `thumbnail.go:42` | thumbnailer wired |
| 4 | `storyboard.go:173` | `storyboards_enabled` |
| 5 | `ffprobe.go:42` ← `TranscodeHLS`'s **own** `Probe` (`hls.go:676`) | every job |
| 6 | `hls.go:694` — the HLS source | every job |
| 7 | `ffprobe.go:42` ← `TranscodeWebVideos`'s **own** `Probe` (`web_video.go:57`) | `target=all` |
| 8 | `web_video.go:73` — the web-video source | `target=all` |
| 9 | `whisper.go:112` + a full uncompressed 16 kHz PCM WAV | auto-captions |

Rows 5 and 7 are pure waste even ignoring S3: `video.Process` already probed the file and wrote the
result to `video_metadata`, and then each transcode target re-probes independently. Three full
downloads to answer a question already answered and persisted.

**For a 2 GB source that is ~16 GB of GET traffic per video before anyone watches it.**

### Leak 3 — peak scratch is ~5× the source, held to the very end

`TranscodeHLS` (`hls.go:700`) does `os.MkdirTemp` and only calls `storeTree` (`hls.go:808`) after
*everything* has been encoded. Nothing is uploaded incrementally, and nothing is deleted early.
What accumulates in that one directory:

- MPEG-TS segments for every rung;
- **plus `remuxHLSDownloads` (`hls.go:906`), which writes a full progressive `video.mp4` *and* a
  full `video-only.mp4` per rung** — so each rung costs roughly 3× its own encoded size;
- plus a dense all-IDR `iframe.ts` trick-play file per rung;
- plus `audio.m4a`.

Worked example — 30-minute 1080p source, ~2 GB, default ladder (1080/720/480/360 at
5000/2800/1400/800 kbps video + 160/128/128/96 audio):

| Item | Size |
|---|---|
| TS segments, 4 rungs (10,512 kbps × 1800 s) | ~2.4 GB |
| `video.mp4` + `video-only.mp4`, 4 rungs (20,512 kbps × 1800 s) | ~4.6 GB |
| trick-play `iframe.ts` × 4 | non-trivial, unmeasured |
| `audio.m4a` | ~36 MB |
| **HLS temp dir subtotal** | **~7.3 GB** |
| local copy of the source (`objectPath`) | 2 GB |
| VP9/WebM top rung — encoded at `hls.go:835`, *after* `storeTree` but **before** the `defer RemoveAll` fires | ~1 GB |
| **Peak** | **~10.3 GB** |

That is **~5× the source, per concurrent job**. `transcoding_concurrency` clamps at 16
(`workerpool.MaxConcurrency`), so a fully-tuned box can want 160 GB of scratch for four 2 GB
uploads' worth of parallelism. `TranscodeWebVideos` then runs as a separate pass with its own source
copy and its own full set of progressive MP4s (~4.4 GB peak).

`docker-compose.prod.yml` already mitigates this operationally — `TMPDIR=/scratch` on a
`transcode_tmp` volume, with `deploy/README.md` telling operators to back it with Block Storage —
and `vidra doctor`'s `checkDiskSpace` (`internal/doctor/checks_state.go:263`) measures it. That is
good operational hygiene around an architectural cost, not a fix for it. There is **no admission
control**: `DrainJobs` claims work without ever asking whether the disk can hold it.

### Leak 4 — multi-instance is explicitly not supported yet

The user's stated goal — several `vidra-core` instances for one deployment — is blocked by two
things the codebase already documents against itself:

- `ClaimDueTranscodeJobs` (`internal/store/queries/transcoding.sql:11`) is
  `UPDATE ... WHERE id IN (SELECT ... LIMIT $1)` with **no `FOR UPDATE SKIP LOCKED`**, and its own
  comment says *"A single in-process worker drains sequentially."* There is no lease and no
  heartbeat, so a claimed row is owned until that process chooses to release it.
- `internal/jobrecovery` requeues **every** `running` row at boot. Its package comment is blunt:
  *"They are NOT true of a multi-node deployment: a second api node booting would requeue jobs the
  first node is actively running, and the two would then duplicate the work."*

Phase 3 items 8–11 already cover this (worker role flag, lease retrofit, replacing the blanket
requeue, scale validation). Nothing here supersedes that plan — but note the ordering constraint:
**a second instance is actively harmful until the lease retrofit lands.**

---

## 3. What ffmpeg can actually do with S3

Researched to separate what's real from what people wish were real.

### Input: yes — read straight from a presigned URL, no local copy

ffmpeg takes an HTTPS URL as `-i` and does ranged GETs, so a presigned S3 URL works directly and
the source **never lands on disk**. The relevant [HTTP protocol options](https://ffmpeg.org/ffmpeg-protocols.html#http)
matter here:

- `seekable` — *"if set to 1 the resource is supposed to be seekable... Default value is -1"*
  (autodetect). S3 and B2 both send `Accept-Ranges: bytes`, so autodetect works; forcing `1` avoids
  relying on it.
- `multiple_requests 1` — persistent connections, so the many range requests of a seeky demux reuse
  one TLS session instead of renegotiating.
- `reconnect 1`, `reconnect_on_network_error 1`, `reconnect_delay_max` — *"Reconnect automatically
  when disconnected before EOF"* / *"in case of TCP/TLS errors during connect."* Non-optional for a
  30-minute read against a remote bucket.

Caveats worth planning around: a non-faststart MP4 (moov atom at the end) makes ffmpeg range-request
the tail and seek back, and a pathological file can seek enough to fetch more bytes than a straight
download would. The mitigation is to keep `objectPath`'s download as a fallback and pick per-source
— which is easy, because we already probe the file. Presigned URLs are also credentials in an
`argv`, so they must not be logged; `internal/observability`'s redaction rules apply.

minio-go already has `PresignedGetObject` (`api-presigned.go:69`) — this needs no new dependency,
just the `Presigner` capability that **Phase 2 item 3 already plans**. That item currently exists to
serve *viewers*; this is an argument to land it for the *encoder* first, where it is strictly
internal and carries none of the cache-header or filename-privacy analysis that gates item 6.

### Output: partly — `-method PUT` is real, but not straight to S3

The HLS muxer genuinely supports pushing segments over HTTP: `-method PUT` (*"Use the given HTTP
method to create output files. Generally set to `PUT` or `POST`"*) with `-http_persistent 1`
(*"Use persistent HTTP connections. Applicable only for HTTP output"*).

But **you cannot point `hls_segment_filename` at an S3 URL** — every request needs its own SigV4
signature and ffmpeg won't sign. This is a recurring disappointment in the wild
([ffmpeg-go#124](https://github.com/u2takey/ffmpeg-go/issues/124)); the standard workaround is
exactly what Vidra does today, write locally then upload.

Two ways to get bounded scratch anyway:

1. **Loopback signing sidecar.** Run a tiny `http.Server` on `127.0.0.1` inside the same process,
   point `-hls_segment_filename` at it, and have each `PUT` handler stream its body directly into
   `blobs.Put`. ffmpeg gets a plain HTTP origin, S3 gets properly signed uploads, and **no segment
   ever touches disk.** Requires `-hls_flags -temp_file` (the temp-file dance is meaningless over
   HTTP) and a per-job bearer token so the socket isn't an open relay. This is the cleanest end
   state and it composes with CMAF later — Phase 3's packager abstraction (item 1) is the natural
   place for it.
2. **Watch-and-drain.** Keep writing locally, but run a goroutine that uploads and `rm`s each
   segment as soon as the next one appears (the HLS muxer writes `seg_NNNNN.ts` strictly in order,
   so segment *N* is complete once *N+1* exists). Simpler and lower-risk than the sidecar; caps
   scratch at a few segments per rung instead of the whole ladder. `directorySize()` has to become
   a running total instead of a final `WalkDir`, and `remuxHLSDownloads` — which needs the complete
   playlist to remux — has to be re-thought or fed from the uploaded copies.

Note that PeerTube itself does **not** do either. Per the
[PeerTube remote-storage docs](https://docs.joinpeertube.org/maintain/remote-storage), it transcodes
to local disk and queues a separate *move-to-object-storage* job afterwards — which is the design
the question is trying to get away from, and which Vidra's ingest path has already beaten.

### The cheapest structural win: decode once

Independent of storage, `TranscodeHLS` loops per rung and re-decodes the whole source each time —
four decodes for the default ladder — and `TranscodeWebVideos` then re-encodes the *same four
resolutions* again from scratch, differing only in container. A single `filter_complex` graph with
`split`/`asplit` feeding N scaled encoder outputs decodes once. Phase 3 item 6 already lists
"decode-once architecture (N-decodes-per-job + full web_video re-encode duplication wastes ~2–3×
CPU)"; the finding here is that on S3 it also multiplies **bucket reads**, not just CPU.

---

## 4. Backblaze B2 specifics

B2 is the cheapest realistic target and the one with the sharpest edges. Vidra's `S3Config` already
documents B2 (`storage/s3.go:20`) and the endpoint/path-style handling is correct.

### What works

- **Presigned URLs are supported** by the B2 S3-compatible API — confirmed by
  [Backblaze's own KB article](https://help.backblaze.com/hc/en-us/articles/360047815993-Does-the-B2-S3-Compatible-API-support-Pre-Signed-URLs).
  So the "ffmpeg reads from a presigned URL" plan works on B2, not just AWS.
- **Multipart works**, with parts between **5 MB and 5 GB**. Relevant to Leak 1: if you set an
  explicit `PartSize`, keep it ≥ 5 MiB. minio's `minPartSize` of 16 MiB is comfortably above it.
- Standard API calls became free in May 2026, which softens (but does not remove) the
  triple-request cost of Leak 1 — the round trips still cost latency.

### The trap: B2 buckets are versioned by default

This is the one that will quietly cost money, and it interacts directly with how Vidra deletes.

Per [Backblaze's bucket-versions docs](https://www.backblaze.com/docs/cloud-storage-s3-compatible-api-bucket-versions),
B2 buckets are versioned by default: deleting by name **hides** the current version and older
versions keep existing and keep billing. `S3.Delete` calls `RemoveObject` with no `VersionId`, so
**every delete Vidra performs is a hide marker, not a reclaim.** Concretely:

- **Upload chunks are the worst case.** `MarkCompleted` deletes `uploads/<session>/*` after the
  original is assembled (`upload/service.go:392`). On B2 those bytes are hidden, not freed — so a
  2 GB upload is **billed as 4 GB forever**: once as chunks, once as the original. Every upload,
  permanently, unless a lifecycle rule exists.
- Re-transcoding the same source hits the same stable prefix, so `DeletePrefix` before `storeTree`
  (`hls.go:793`) leaves a full hidden generation of the old ladder behind.
- `internal/mediagc` reclaims orphans on the local backend and reclaims *nothing* on B2.

**Mitigations:** (a) document a required B2 lifecycle rule — Backblaze's guidance is to set
`daysFromHidingToDeleting` rather than accumulate versions, and they warn that many versions of one
object degrades listing and delete performance and can trigger account blocks; (b) have
`vidra doctor` check the configured bucket's versioning/lifecycle configuration and warn when
versioning is on with no expiry rule; (c) longer term, make `Delete` version-aware where the
backend reports versioning.

### Egress: the 3× free tier vs. our 8× re-download

B2 gives free egress up to **3× stored data per month**, then $0.01/GB, with unlimited free egress
only to Bandwidth Alliance CDN partners (Cloudflare, Fastly, bunny.net). Two ways Vidra spends that
allowance before a viewer sees anything:

1. **Leak 2 spends it at ingest.** A 2 GB upload stores ~12.7 GB of derivatives, earning ~38 GB of
   monthly free egress — and immediately consumes ~16 GB of it re-reading its own source eight
   times.
2. **API-proxied delivery spends the rest.** Every viewer byte goes B2 → droplet → viewer
   (`serveStoredObjectNamed`), so it is *not* CDN egress and does *not* qualify for Bandwidth
   Alliance. It counts against the 3×, and it is paid for twice — B2 egress plus droplet bandwidth.

This is the strongest available argument for revisiting the parked *signed URLs vs proxy* decision
(`.ralph/specs/product-decisions.md` §6), which says presigning is *"a later optimisation gated on a
CDN story; revisit when a deployment actually saturates the API egress."* On B2 the economics bite
well before saturation does — and Phase 2 item 6 already scopes the work correctly, including the
cache-header and filename-privacy analysis that has to land with it.

---

## 5. Recommended sequence

Ordered by payoff ÷ risk. Items 1–3 are small and independent; 4–6 are Phase 2/3 work already on
the roadmap that this note re-prioritises.

| # | Change | Effect | Risk |
|---|---|---|---|
| 1 | Pass the known size to `S3.Put` (or set `PartSize: 16<<20`) | 528 MiB → 16 MiB per Put; small objects stop being 3-call multiparts | Very low |
| 2 | Reuse the probe: pass `Metadata` into `TranscodeHLS`/`TranscodeWebVideos` instead of re-probing | −3 full downloads per video | Low |
| 3 | Free the HLS tree before the VP9 encode; upload + `rm` each rung directory as it finishes | Cuts peak scratch by roughly half with no pipeline redesign | Low |
| 4 | `Presigner` capability + ffmpeg reads the source by URL (Phase 2 item 3, used internally first) | −1 source copy per encode step; source never on disk | Medium |
| 5 | Decode-once `filter_complex` ladder; fold web-video outputs into the same graph (Phase 3 item 6) | ~2–3× CPU, and removes the last duplicate source read | Medium |
| 6 | Loopback signing sidecar for segment output (with Phase 3 item 1's packager seam) | Scratch becomes O(one segment); true streaming encode | Higher |

Two things worth adding to the existing phase docs regardless:

- **Disk admission control** — have `DrainJobs` consult free space against an estimate
  (`source_size × ladder_multiplier`) before claiming, and defer rather than fill the disk. Vidra
  already has `statfs` in `internal/doctor/host.go`; the estimate is easy because the source size is
  known and the ladder is planned up front.
- **B2 lifecycle documentation + a `doctor` check** — cheap, and the alternative is operators paying
  for hidden versions indefinitely without a signal.

### Ordering constraint

**Do not run a second `vidra-core` instance until Phase 3 items 9–10 land.** `ClaimDueTranscodeJobs`
has no `SKIP LOCKED` and no lease, and `jobrecovery` requeues every `running` row at boot — two
instances will duplicate work and fight over jobs. Everything in §5 items 1–6 makes each instance
leaner and is worth doing first; none of it makes multi-instance safe on its own.

---

---

## 6. What shipped (2026-08-20)

All six items merged to `vidra-core` main as `e16edb7`. `make ci` green; the `-tags=integration`
media and blobsink suites green against real ffmpeg 8.1.

| # | Commit | What changed |
|---|---|---|
| 1 | `ea475c0` | `S3.Put` sniffs the reader's exact length when it is free to know (`*os.File` from `storeTree`, `*bytes.Reader` from thumbnails/captions/storyboards), so small objects are a single PUT with no buffer. Where the length genuinely cannot be known, part size is pinned to minio's 16 MiB `minPartSize` instead of the 528 MiB default. Adds the `SizedPutter` capability + `storage.PutSized` helper. |
| 2 | `7649622` | `TargetTranscoder` gained `Probe`; the worker probes once per job and hands the result to every target, instead of `TranscodeHLS` and `TranscodeWebVideos` each probing independently. |
| 3 | `1485eac` | `storage.Presigner` (S3 only) + a media source resolver preferring local path → presigned URL → download. ffmpeg reads the source over HTTPS with `seekable`/`multiple_requests`/`reconnect*`/`rw_timeout`. Presigned URLs are redacted out of errors. |
| 4 | `d6b2fcc` | Decode-once ladders: one `filter_complex` pass per output class instead of one ffmpeg invocation per rung. |
| 5 | `3176498` | Each rung is remuxed, measured, uploaded and freed in turn; the scratch tree is released explicitly before the VP9 encode rather than by the deferred cleanup. |
| 6 | `f7d0891` | `internal/blobsink`: loopback signing sidecar so ffmpeg PUTs the HLS ladder straight into object storage. Opt-in via `TRANSCODING_STREAM_OUTPUT`, default off. |

### Effect on the worked example (2 GB, 30-min 1080p, default ladder)

| | Before | After |
|---|---|---|
| Full source reads from the bucket per video | up to 8 | 1 (streamed, never staged) |
| Full source decodes per `target=all` job | 13 | 3 (+1 for VP9) |
| Peak transcode scratch | ~10.3 GB | ~3.6 GB, or ~1.2 GB with `TRANSCODING_STREAM_OUTPUT=true` |
| Heap buffer per in-flight `Put` | 528 MiB | 16 MiB, or none for a known small object |
| Requests to store one HLS segment | 3 (multipart) | 1 |

The decode and read counts are exact. The scratch figures are computed from the ladder bitrate
table, not measured on a real 30-minute upload — the shape is right, the constant is an estimate.

### Behaviour changes an operator would notice

- **`transcoding_threads` is now divided across the ladder**, not handed to each rung in full. It
  is documented as a per-job budget and the rungs used to run sequentially; they now run
  concurrently in one process, so giving each the full number would silently multiply the setting
  by the ladder height.
- **Rungs report progress together** rather than one reaching 100% before the next starts. The
  per-resolution projection is unchanged in shape.
- **The prior-generation `DeletePrefix` runs earlier**, widening the window in which a manual
  re-run of the *same* source has no serving tree by the remux time. Replacement uploads are
  unaffected — they write to a fresh `rN` prefix.
- **A presigned source URL is visible in the process list** to a local user on the host. It is
  read-only, single-object and time-limited; that is the trade for not staging every original.

### Follow-ups — closed 2026-08-21

Three of the four items left open above were closed the next day.

- **Backblaze B2 versioning — CLOSED** (`9302746`). `storage.BucketRetention` reads the bucket's
  versioning and lifecycle configuration; `vidra doctor` reports it as **object retention** and
  warns when versioning is on with no non-current-version expiry rule. A store that will not answer
  either query reports UNKNOWN rather than OK, and a lifecycle rule that exists but is *disabled*
  does not count. The operator fix (including a copy-paste rule) is in
  `vidra-core/docs/operations.md`, in the media-backup section — which previously recommended
  leaning on the store's own versioning without mentioning that doing so stops every delete from
  reclaiming.
- **Disk admission control — CLOSED** (`a2b53d7`). `DrainJobs` now checks a free-space floor
  (`TRANSCODING_MIN_FREE_SCRATCH_MB`, default 10 GiB) *before* claiming, and estimates per-job need
  from `video_files.size_bytes` keyed by the job's `source_key`. A job that does not fit is
  **deferred** through a new query that does not increment `attempts` — using the existing
  reschedule would have dead-lettered a good video after five full-disk ticks. Both guards fail
  open: an unmeasurable filesystem or an unknown source size admits the job. `internal/diskspace`
  is shared with `vidra doctor` so both measure the same disk the same way.
- **Multi-instance claim safety — CLOSED** (`5ead076`, `b57a1d1`, `2763495`). Three commits:
  1. The three **bare-SELECT** queues (federation delivery, ATProto cross-post, search outbox) now
     lease. They had no claim at all, so two instances would both act on the same row — a duplicate
     activity delivered to every remote server, or a second Bluesky post on a user's public feed.
  2. The six **state-flip** claims gained `FOR UPDATE SKIP LOCKED`. Not theoretical: with it
     removed, the new integration test reproduces a double-claim 5 runs out of 5.
  3. `internal/jobrecovery`'s boot-time blanket requeue was replaced by **lease-expiry sweeps** —
     claim takes a 30-minute lease, the worker renews it every 5 minutes while working, and the
     sweep (now on a 2-minute ticker, not just at boot) returns only rows nobody is renewing.

  All of it is verified against real PostgreSQL, because the guarantee comes from
  `FOR UPDATE SKIP LOCKED` inside one statement and no in-memory fake can model that.

### Still open

- **Leader election for the singleton crons.** The ~9 periodic workers that *sweep* rather than
  *claim* (media GC, scheduled publish, transcode-hold sweep, upload sweep, search reconcile, IPFS
  reconcile, operational-job retention, E2EE sweep, live watchdog) would each run on every instance.
  They are individually idempotent today, but that is an observation about the current code rather
  than a guarantee. Phase 3 item 10's advisory-lock leader election is what would make it one, and
  it is now the last thing between this codebase and an honest multi-instance story.
- **Web-video peak.** Decode-once necessarily produces every progressive MP4 before any can be
  uploaded, so that pass's peak is the full set. Deleting each as it stores shortens how long the
  peak is held but does not lower it.
- **Streaming output is off by default** and needs a real deployment behind it before it can be
  recommended. It is verified against ffmpeg but has not run against a live S3/B2 bucket.
- **No soak test.** `docker compose up --scale` with two API replicas has not been run. The claim
  semantics are proven at the query level; the topology is not.

---

## Sources

- [FFmpeg Protocols Documentation — HTTP options](https://ffmpeg.org/ffmpeg-protocols.html#http)
- [FFmpeg Formats Documentation — HLS muxer](https://ffmpeg.org/ffmpeg-formats.html)
- [Support for Direct S3 Upload of HLS Segments — ffmpeg-go#124](https://github.com/u2takey/ffmpeg-go/issues/124)
- [PeerTube — Remote storage (S3)](https://docs.joinpeertube.org/maintain/remote-storage)
- [Does the B2 S3 Compatible API support Pre-Signed URLs? — Backblaze](https://help.backblaze.com/hc/en-us/articles/360047815993-Does-the-B2-S3-Compatible-API-support-Pre-Signed-URLs)
- [How to Use S3-Compatible API Bucket Versions in Backblaze B2](https://www.backblaze.com/docs/cloud-storage-s3-compatible-api-bucket-versions)
- [A Deeper Look at S3 Compatible Lifecycle Rules in Backblaze B2](https://www.backblaze.com/blog/a-deeper-look-at-s3-compatible-lifecycle-rules-in-backblaze-b2/)
- [Backblaze B2 — browser multipart upload sample (5 MB–5 GB part limits)](https://github.com/backblaze-b2-samples/browser-multipart-upload-compress-data)
