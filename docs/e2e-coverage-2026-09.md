# End-to-end test coverage — audit and gap list (2026-09-03)

What the two Playwright suites actually cover, what the backed harness actually starts, and
which functionality has no end-to-end proof anywhere. Produced alongside the phase 1-5
productionization re-audit; the program-level findings live in
[productionization/README.md](productionization/README.md).

## The two suites

| | `vidra-user/e2e/` (mocked) | `vidra-user/e2e-backed/` (real backend) |
|---|---|---|
| spec files | **97** | **73** (+ `admin.setup.ts`, `fixtures.ts`) |
| `test()` call sites | ~603 | ~123 |
| gate | part of `npm run ci` | never in `npm run ci`; own workflow |
| mechanism | `page.route` interception, no backend | no mocks; real vidra-core + Postgres + Redis |

They are deliberately paired — most mocked specs name their backed counterpart in a header
comment. Mocked covers presentation, states, gating, a11y, responsive and keyboard; backed
covers persistence round-trips.

**~18 of the 123 backed tests are inert in the default CI job** because they self-skip on an
unset opt-in variable: `atproto` (needs real Bluesky creds), `peertube-import`,
`whisper-captions`, `registration-approval`, `search-discovery`, `channel-sync` (runs in its
own job), and two of four `quarantine` tests. So roughly **105 backed tests actually execute**.
A self-skipping test is green and asserts nothing; that is worth remembering when reading the
job as evidence.

## What the backed harness starts — and does not

`.github/workflows/frontend-e2e-backed.yml` runs `docker compose --profile core` from
vidra-core. That profile starts `postgres`, `redis`, `prep-volumes`, `migrate` and `api`. The
api runs as `VIDRA_ROLE=all`, so it serves HTTP *and* runs every background worker in-process —
which is why transcoding genuinely happens in backed runs.

It does **not** start, because each sits behind a profile the job never selects:

| Not started | Profile | Consequence |
|---|---|---|
| `minio` | `storage` | runs `STORAGE_BACKEND=local`; **S3 is never exercised** |
| `ipfs` (Kubo) | `ipfs` | `IPFS_ENABLED=false`; no pin ever happens |
| `kubo-private` (+ `-2`, cluster) | `ipfs-private` / `ipfs-private-cluster` | private mirror tier unexercised |
| `worker` | `worker` | the documented split topology is never run |
| `rtmp` | `media` | no real live ingest |
| `clamav` | `scan` | malware scanning unexercised |
| vidra-search | — | **search is never started at all** |

## Gaps, ranked

1. **S3 storage backend had no end-to-end proof anywhere.** Not in the browser harness, and —
   the sharper half — not in vidra-core's CI either: six `//go:build integration` files gate on
   `S3_TEST_ENDPOINT` (`internal/storage/s3_integration_test.go`,
   `internal/httpapi/delivery_integration_test.go`, `internal/mediagc/service_integration_test.go`,
   `internal/storagemigration/migration_integration_test.go`,
   `cmd/api/verify_blobs_integration_test.go`, `cmd/api/bucket_ownership_integration_test.go`)
   and `backend-integration.yml` declares no S3 service and never sets the variable. All six
   self-skipped on every run, while production runs S3.
2. **Presigned / direct (307) media delivery through a browser.** Proven at the Go level only
   (`delivery_integration_test.go:127`) — and that test is one of the six that self-skip. No
   test has ever driven hls.js through a cross-origin redirect to a bucket, which is exactly the
   failure class already observed on beta (bucket CORS scoped to a single origin).
3. **IPFS had no backed coverage.** `e2e/watch-ipfs.spec.ts` fabricates `ipfs_pinned`,
   `ipfs.hls_cid`, `ipfs.gateway_url` *and* the gateway response. Nothing proved the pin worker
   produces a real CID, that the detail response carries it, or that a gateway serves a playable
   master.
4. **Search is entirely unproven against the real service.** All ~29 search tests are mocked;
   `e2e-backed/search-discovery.spec.ts` is gated on `E2E_SEARCH_SERVICE` and the harness never
   starts vidra-search.
5. **Live streaming media plane.** Backed covers stream CRUD and the ingest-hook status flip
   only — no RTMP publish → HLS segment → watch-page playback.
6. **Federation.** Remote videos, remote follows and the follower-approval queue are mocked
   only; the backed stack has no second instance.
7. **The worker-split topology** (`API_ROLE=api` + `--profile worker`), which `operations.md`
   actively recommends, is never exercised by any e2e run. This is how the frozen-settings
   defect (core#150) survived: no test runs the shape it breaks.
8. **E2EE attachments.** Backed E2EE covers text only.
9. **Admin overview / jobs / media-GC / infrastructure / config** pages have no backed read
   against real data.

## "Private pinning for messaging" — the feature does not exist

Worth recording explicitly, because it is a reasonable thing to assume exists and then to go
looking for a test of:

- `vidra-core/internal/ipfsmirror/classes.go:52-55` declares `ClassDMAttachment` in the
  **never-mirror** block.
- `vidra-core/internal/ipfsmirror/eligibility.go` `Route()` is the single routing policy and is
  **default-deny**: DM attachments fall to the default branch and return `NetworkNone` — refused
  on *both* swarms. The comment names them as "plaintext AND the future e2ee-blobs, **which do
  not exist yet**".
- The private tier (`IPFS_MIRROR_PRIVATE` + a second swarm.key'd node) is real, but its subjects
  are private/unlisted **videos** and their derivatives, unlisted or deactivated accounts'
  identity images, and non-public playlist covers. Never messaging.
- It is also **replication, not distribution**: `vidra-core/docker-compose.yml:590` records
  "deliberately NO `IPFS_PRIVATE_GATEWAY_URL` knob", and no gateway port is published. There is
  therefore no viewer-facing surface for a private CID at all.

The correct test is a **negative** one — on an IPFS-enabled stack, send a DM attachment and
assert no pin ledger row appears for it — which locks the privacy fence from outside the Go
unit tests. Making messaging content mirror-eligible would be a product decision against a
written privacy invariant, not a test gap.

## The bug mocked-only coverage hid

Found while wiring the IPFS backed spec, and the clearest justification in this repo for
backed tests existing at all.

`WatchView.tsx` offered the IPFS source bar only when
`video?.ipfs_pinned && ipfsMasterUrl && video?.hls_url`. **`GET /videos/{id}` never sends
`ipfs_pinned`.** It is a card/feed badge, set only by the list and search handlers
(`attachIPFSPinned` — `vidra-core/internal/httpapi/videos.go:645,666,838,932` plus three sites in
`search.go`) and declared `json:"ipfs_pinned,omitempty"`, so it is absent from a detail response
entirely. The detail handler calls `attachVideoIPFS` (`videos.go:518`) instead.

So on every real backend the condition was `undefined && … ` — false — and **the entire
client-side IPFS playback path was unreachable**, while `docs/productionization/phase-4-delivery.md`
described it as a working opt-in feature.

It survived because `e2e/watch-ipfs.spec.ts` is mocked and fabricated *four* things at once:
`ipfs_pinned`, `ipfs.hls_cid`, `ipfs.gateway_url` and the gateway's own response. Every one of its
assertions passed against a backend that could not produce any of them. No amount of additional
mocked coverage would have found this; only a request to a real core would.

The correct gate is the `ipfs` object itself, which is emitted only for a public, published video
with a `state='pinned'` row on the public swarm (`videos.go:416-434`) — strictly stronger than the
list-only badge it replaced.

## Manual verification run, 2026-09-03

An isolated stack (`-p vidramanual`, ports 8090/5442/6389/9010) was brought up on
`--profile core --profile storage` with `STORAGE_BACKEND=s3` against MinIO, and the video and
messaging paths were driven by hand. **26 of 27 checks passed**; the one failure was
`owner_claim_invalid` on a re-run against an already-claimed instance, which is correct
behaviour.

Confirmed working end to end **on S3**, which had never been exercised before:

- upload → CMAF transcode → publish, `state=published`, `hls_url` populated;
- the full ladder serves: `master.m3u8` (with `CODECS="avc1.4d4014,mp4a.40.2"`, a separate audio
  rendition and an I-frame trick-play playlist) → `cmaf/media_0.m3u8` → `init-0.mp4` +
  `chunk-0-00001.m4s`; init+segment concatenated decodes as h264 320x240 under ffprobe;
- the audio track is real, not silent — `mean_volume: -24.1 dB`, 5.99s decoded from a 6s source
  (a regression guard worth keeping: split-audio imports once came down silent);
- 40 objects in the bucket under the documented key grammar, including the `.vidra/owner`
  marker that arms the media-GC safety rail, `streaming-playlists/<id>/cmaf/*`, `stream.mpd`,
  progressive `video.mp4`/`video-only.mp4`, `audio.m4a`, and `storyboards/<id>.{jpg,vtt}`;
- messaging: conversation start, send, recipient read, and a **non-participant receiving 404
  rather than 403** so a conversation's existence is not leaked;
- DM attachments: upload, attach to a message, recipient downloads (200), third party refused
  (404). Attachments land under their own `dm-attachments/<conversation>/<id>` prefix — the
  prefix the IPFS privacy fence must never mirror;
- E2EE: device registration and cross-user device-directory lookup.

One minor observation, not filed as a defect: `GET /api/v1/ipfs/status` answers **503**
`ipfs_disabled` when the mirror is off. 503 signals "temporarily unavailable, retry"; a
deliberately disabled feature is closer to 404/403. Cosmetic, and the error code is explicit.
