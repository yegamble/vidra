# PeerTube interop lab — first run, 2026-11-16

Step 2 of `.gg/plans/peertube-federation.md`: S1–S8 against a real PeerTube
v8.3.2, in the local lab at [`tests/peertube-interop/`](../../tests/peertube-interop/README.md).
Nothing here was fixed. Every failure below is reported as measured.

**Result: federation works in both directions for follows and for receiving
videos. It does not work for taking a video back.** A vidra video that is
deleted, made private or blocked stays on PeerTube, and four out of five
PeerTube videos made private stayed listed on vidra.

## What was run

| | |
|---|---|
| vidra-core | `main` @ `4e93718992288b566622fe52557b7bb36f0001d7`, source build, no tracked file modified |
| PeerTube | `chocobozzz/peertube:v8.3.2-trixie` (`sha256:3fc4a73e…16006ef`), two instances: `pt` and the control `ctl` |
| Edge | `caddy:2.11.9-alpine`, internal CA minted per run; vidra behind the shipped `deploy/Caddyfile` with only its site address changed |
| Host | Docker Desktop on macOS arm64, 7.9 GiB; the running lab held about 1.1 GiB resident when sampled mid-run (image build not included) |
| Runs | Four full runs. The table is the fourth (18:51–19:01 UTC), whose logs every excerpt below is cut from. Runs two and three are cited once each, where they differ |
| Not touched | sizetube.com, beta.sizetube.com, any workflow, any vidra-core source |

**One deviation from the plan.** The plan asks for `VIDRA_ENV=staging`.
vidra-core refuses to boot with it:

```
{"level":"ERROR","msg":"fatal","error":"config: invalid VIDRA_ENV \"staging\" (want development|test|production)"}
```

The lab runs `VIDRA_ENV=test`. In `internal/config` that differs from
production only by skipping the production-only refusals, so none of those
checks is exercised here.

**One harness bug, found and fixed before this table.** On run two S2 failed
with `no thumbnailPath`. That was the driver reading a field PeerTube 8.3.2 no
longer fills (it is `null` for PeerTube's own videos too); the thumbnail was
there under `thumbnails[].fileUrl` and PeerTube served it. The driver was
corrected and S2 passes. It is recorded because it is exactly the mistake the
control exists to prevent, and the control did not catch it: the control checks
the lab's plumbing, not every field the driver reads.

## Control (must pass before anything about vidra is believed)

| | Check | Verdict |
|---|---|---|
| C1 | `ctl` follows the `pt` instance; `accepted` on both sides | PASS |
| C2 | a video uploaded to `pt` arrives on `ctl` as a remote video | PASS |
| C3 | a video made private on `pt` disappears from `ctl`, and returns when made public | PASS |

## Scenarios

| | Scenario | Verdict | Plan gap |
|---|---|---|---|
| S1 | PeerTube admin follows the vidra instance | **PASS** | |
| S2 | vidra publishes; PeerTube lists it as remote; thumbnail, playlist and first segment fetch | **PASS** | G5 seen on the side |
| S3 | a PeerTube user follows a vidra channel; backfill and a new video arrive | **PASS** | |
| S4 | a vidra user follows a PeerTube channel | **PASS** | G11 seen on the side |
| S5 | PeerTube uploads; the video appears on vidra under the channel name | **FAIL** — it arrives, under the uploader's account instead | G9 |
| S6 | vidra admin follows the PeerTube instance; a new upload arrives by `Announce` | **PASS** | |
| S7 | edit, privacy flip, delete, moderator block, both directions | **FAIL** — 6 of 10 checks | G8, G10, and one new |
| S8 | negatives | **PASS** — 6 of 6 refusals, after a positive baseline | |

S7 ran as three blocks, in this order around S6: S7b (PeerTube → vidra while
vidra had only a channel follow), S7c (the same after the instance follow),
S7a (vidra → PeerTube).

| S7 check | Verdict |
|---|---|
| vidra → PeerTube: edit | PASS |
| vidra → PeerTube: flip to private | **FAIL** |
| vidra → PeerTube: delete | **FAIL** |
| vidra → PeerTube: moderator block | **FAIL** |
| PeerTube → vidra, channel follow only: edit | **FAIL** |
| PeerTube → vidra, channel follow only: delete | PASS |
| PeerTube → vidra, instance follow: edit | PASS |
| PeerTube → vidra, instance follow: flip to private, once | PASS on runs 3 and 4, **FAIL** on run 2 |
| PeerTube → vidra, instance follow: flip to private, five times | **FAIL** — 4 of 5 copies stayed on vidra, 0 of 5 on the stock PeerTube |
| PeerTube → vidra, instance follow: moderator block with unfederate | PASS |

On the fourth run the driver recorded the five-flip measurement as an
observation, so its console table printed S7c as PASS. The committed driver
asserts it, so a re-run prints FAIL.

## Per scenario

### S1 — PASS

PeerTube resolved vidra's instance actor from NodeInfo, sent the Follow, and
got the Accept in under four seconds.

```
driver   PeerTube lists vidra as following: {"state":"accepted","following":"peertube"}
vidra    GET /admin/federation/instance-followers -> {"actor_url":"https://pt.interop.test/accounts/peertube","host":"pt.interop.test","handle":"peertube@pt.interop.test","state":"accepted"}
vidra    instance_followers.state = accepted
```

### S2 — PASS

```
PeerTube GET /api/v1/videos/50f4f5d3-… -> name "Vidra to PeerTube 87e713d1", isLocal false, duration 4,
         channel chan87e713d1@vidra.interop.test, account lab87e713d1@vidra.interop.test
PeerTube thumbnails[0] 640x480, /lazy-static/thumbnails/40e7d785-….jpg -> 200, 21953 bytes
vidra    master.m3u8 -> 200 #EXTM3U, 1 variant; first segment 200, 435821 bytes
PeerTube streamingPlaylists[0]: files 0, segmentsSha256Url null; web video files 0
```

PeerTube logs one warning per vidra video and carries on:

```
warn: Cannot determine image extension from input https://vidra.interop.test/api/v1/videos/<id>/thumbnail
```

### S3 — PASS

Run against `ctl`, which has no instance follow with vidra, so the channel
subscription is its only link. The video published before the follow arrived
(vidra's backfill), and so did one published after.

### S4 — PASS

`root_channel@pt.interop.test` resolved, `pending` then `accepted` within ten
seconds, and PeerTube holds an accepted `actorFollow` from a vidra actor.

### S5 — FAIL (G9)

The video arrives and plays from PeerTube's playlist. It is filed under the
account that uploaded it, not the channel it belongs to.

```
expected  channel_handle "root_channel@pt.interop.test"
vidra     channel_handle "root@pt.interop.test"
          actor_url "https://pt.interop.test/accounts/root"
          remote_videos.remote_actor_url = https://pt.interop.test/accounts/root
```

No rejection on either side: PeerTube sent a valid object, vidra stored it and
answered 202.

### S6 — PASS

The upload went to a second PeerTube channel that vidra does not follow, so it
can only have arrived through the instance follow.

### S7 — FAIL

**vidra → PeerTube: private, delete and block are all refused (G8).** PeerTube
answers the POST with 204 and then drops the activity. The exact reason, three
times, once per check:

```
[pt] 18:57:34.023 info: Receiving inbox requests for 1 activities by https://vidra.interop.test/video-channels/chan87e713d1.
[pt] 18:57:34.025 info: … "POST /inbox HTTP/1.1" 204 - "-" "Go-http-client/2.0"
[pt] 18:57:34.033 warn: Cannot process activity Delete. {
  "err": {
    "stack": "Error: Account https://vidra.interop.test/video-channels/chan87e713d1 does not own video channel https://vidra.interop.test/video-channels/chan87e713d1\n    at file:///app/dist/core/lib/activitypub/process/process-delete.js:62:19 …
[pt] 18:58:44.041 warn: Cannot process activity Delete.
[pt] 18:59:54.041 warn: Cannot process activity Delete.
```

The activity vidra sent:

```
"actor": "https://vidra.interop.test/video-channels/chan87e713d1",
"id":    "https://vidra.interop.test/video-channels/chan87e713d1/activities/delete/…",
"object":"https://vidra.interop.test/videos/…", "type": "Delete"
```

vidra has no idea it failed. Every one of its 39 rows in
`federation_deliveries` is `delivered`, because PeerTube's 204 comes before it
processes anything. vidra's log has no line for these deliveries at all. Sixty
seconds after each action PeerTube still served the video with HTTP 200.

**PeerTube → vidra, channel follow only: the edit is ignored (G10).** PeerTube
sent the Update to the one vidra inbox that follows the channel; vidra answered
202 and changed nothing.

```
[pt]    18:54:10.440 info: … "PUT /api/v1/videos/8ff77673-… HTTP/1.1" 204
[pt]    18:54:10.453 info: Creating job to update video https://pt.interop.test/videos/watch/8ff77673-….
[pt]    18:54:10.455 debug: Creating broadcast job. { "broadcastUris": [ "https://ctl.interop.test/inbox", "https://vidra.interop.test/accounts/lab87e713d1/inbox" ] }
[vidra] 18:54:10.478 INFO request POST /accounts/:handle/inbox status 202
[vidra] 18:54:10.496 INFO request POST /accounts/:handle/inbox status 202
driver  after 60 s: title still "PeerTube to vidra 87e713d1", wanted "PeerTube edited 87e713d1"
```

Those two request lines are everything vidra logged, at `LOG_LEVEL=debug`. The
delete in the same state did go through, and after the instance follow (S6) an
edit went through in under a second.

**PeerTube → vidra: a video made private usually stays listed on vidra. New,
not in the plan.** When a video stops being public, PeerTube 8.3.2 sends a
Delete and, most of the time, an Update for the same video straight after. If
the Update lands second, vidra stores the video again from the object inside
it.

```
[pt]    18:55:57.847 info: Creating job to broadcast delete of video https://pt.interop.test/videos/watch/80f2c857-….
[pt]    18:55:57.863 info: Creating job to update video https://pt.interop.test/videos/watch/80f2c857-….
[pt]    18:55:57.866 info: … "PUT /api/v1/videos/80f2c857-… HTTP/1.1" 204
[vidra] 18:55:57.874 POST /accounts/:handle/inbox 202   (x2)
[vidra] 18:55:57.904 POST /accounts/:handle/inbox 202   (x2)
vidra   remote_videos: "PeerTube privacy-2 87e713d1", fetched_at 18:55:57.898
```

vidra made no request back to PeerTube after the Delete, so the copy was
rebuilt from the Update alone. Fetching the object anonymously at that point
would have told it otherwise: on run two the same URL answered `401`.

Five flips in a row, each as soon as the video had arrived:

| round | PeerTube sent | left on vidra | on stock PeerTube (`ctl`) |
|---|---|---|---|
| 1 | Delete only | no | 404 |
| 2 | Delete, then Update | **yes** | 404 |
| 3–5 | (same outcome as 2) | **yes** | 404 |

The stock PeerTube received the same activities and kept none. The four
titles were still in vidra's `remote_videos` when the lab was torn down. The
single flip in the same scenario passed on this run and on run three and
failed on run two, which is how the race was noticed. The pt log lines were
checked for rounds 1 and 2; rounds 3–5 are the driver's before/after reading
only.

### S8 — PASS

A correctly signed request from PeerTube's own instance key (read out of the
lab PeerTube's database) is accepted first, so each refusal differs from an
accepted request in one property.

| request | answer |
|---|---|
| baseline, correctly signed | 202 |
| body changed after signing | 401 |
| `Date` one hour old | 401 |
| no `Signature` | 401 |
| 1.5 MiB body, correctly signed | 401 |
| key id on a host that 302s to PeerTube's real actor | 401 |
| real Follow from `ctl` after vidra blocked `ctl.interop.test` | 202 on the wire by design; no `instance_followers` row; `ctl` shows the follow `rejected` |

```
[vidra] WARN request POST /inbox status 401 error "code=401, message=signature verification failed"   (x5)
```

`env/production.env.example` still ships `HTTP_IMPORT_ALLOW_PRIVATE_URLS=false`.

## The plan's gaps G4–G12

| # | Gap | Status | What was measured |
|---|---|---|---|
| G4 | video dropped without a valid icon | **still unverified** | Every lab video had a poster, and vidra emitted `icon` with `width 640, height 480, image/jpeg`, which PeerTube accepted. The branch the gap is about (no poster, or no readable size) was never produced |
| G5 | titles under 3 characters dropped | **measured-confirmed** | A vidra video titled `ab` never appeared on PeerTube (404 after 45 s, no row). `debug: Video field is not valid to PeerTube: name` then `Remote video JSON is not valid.` then `Cannot fetch remote video …: maybe not a video object?` |
| G6 | duration omitted when unknown | **still unverified** | Every lab video had a duration (`PT4S`, accepted). The unknown-duration branch was never produced |
| G7 | HLS link with an empty `tag` | **still unverified** for playback | Measured only this far: PeerTube stored the playlist with **0 files** and no `segmentsSha256Url`, and 0 web video files; the playlist and first segment fetch anonymously. Whether PeerTube's player can play a playlist with no files needs a browser, which the lab does not have |
| G8 | Delete signed by the channel is refused | **measured-confirmed** | Private flip, delete and block all refused with `Account … does not own video channel …` (`process-delete.js:62`). Worse than the plan says: vidra records each as `delivered` |
| G9 | PeerTube videos filed under the account | **measured-confirmed** | S5: `channel_handle` is `root@pt.interop.test`, not `root_channel@…` |
| G10 | edits ignored with only a channel follow | **measured-confirmed** | S7: Update answered 202 and dropped; Delete honoured; Update honoured once an instance follow exists |
| G11 | no backfill of what a followed PeerTube already has | **measured-confirmed** for a channel follow | 30 s after the Accept, 0 of the 1 public video already on that channel was on vidra. Not measured separately for an instance follow |
| G12 | forwarded third-party activities answered 400 | **still unverified** | No scenario makes PeerTube forward a third party's activity. For what it is worth, all 72 inbox POSTs from the two real PeerTubes during S1–S7 were answered 202 |

Also seen, outside G4–G12: PeerTube delivered every broadcast to vidra **twice**
once vidra had two followers on it (`…/accounts/lab87e713d1/inbox` and
`…/accounts/peertube/inbox`), which is G15 as the plan describes it.

## What this does not prove

- **Nothing about SSRF.** PeerTube ran with `federation.prevent_ssrf=false` and
  vidra with `HTTP_IMPORT_ALLOW_PRIVATE_URLS=true`. The lab's only SSRF claim
  is that the production template still ships the switch off.
- **Nothing about Cloudflare or the real edge.** No WAF, bot challenge or
  caching in front of the inbox, no ACME. Only the shipped Caddyfile's routing
  is real here. G2 is as open as it was.
- **Nothing about public DNS or a public peer.** Every name is `.test` and
  resolves only inside one Docker network; both PeerTubes are fresh, empty
  installs.
- **No browser, no decoder.** Playback is playlist text and segment bytes.
- **Not production mode.** `VIDRA_ENV=test`, rate limiting off, malware
  scanning off, no frontend, no vidra-search, a source build rather than a
  published image.
- **Small numbers.** One fixture, one channel each way, a handful of videos.
  The privacy race was seen in 4 of 5 rounds on one run and in 1 of 2 single
  flips on the others; that is enough to say it happens, not how often.
- **Logs are not kept.** The full PeerTube and vidra logs live in the
  untracked `tests/peertube-interop/out/` and are destroyed by the next run;
  this note holds the excerpts. Run two's logs were overwritten, so its two
  citations here rest on what was read at the time.

## Reproduce

```
tests/peertube-interop/run.sh --control-only   # about 1 minute
tests/peertube-interop/run.sh                  # about 12 minutes after the first image build
```
