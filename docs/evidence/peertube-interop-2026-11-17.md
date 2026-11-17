# PeerTube interop lab — follow-up, 2026-11-17: S1–S8 all pass

Follow-up to [`peertube-interop-2026-11-16.md`](peertube-interop-2026-11-16.md).
That note measured vidra-core `main` against a real PeerTube v8.3.2 and found
seven failing checks in S5 and S7. This one measures the same lab, with the
same driver, against four vidra-core fixes.

**Result: the control and S1–S8 all pass on a branch that combines the four
fixes.** A vidra video that is deleted, made private or blocked now disappears
from PeerTube; a PeerTube video shows under its channel; an edit on PeerTube
reaches a vidra that follows only the channel; and a PeerTube video made
private no longer comes back.

The driver was not changed: `tests/peertube-interop/driver.mjs` is
byte-identical to the one merged in meta#403. One weakness in an S2 check was
found today and is **not** fixed here; see
[the last section but one](#a-weakness-in-an-s2-check-found-today-and-left-alone).

## What was run

| | |
|---|---|
| vidra-core | `23cd351b`, a local merge of the heads of four pull requests on top of `main` @ `4e937189`; built from a separate git worktree, no tracked file modified. The nested `vidra-core/` checkout was not touched |
| On `main` since | All four were merged after the run. vidra-core `main` @ `9e95f1cc` has the same tree as `23cd351b` (`fb9884bd641f…`), so the table below is a statement about `main` |
| The four fixes | [vidra-core#566](https://github.com/yegamble/vidra-core/pull/566) `8c1aa451` (G8) · [#567](https://github.com/yegamble/vidra-core/pull/567) `57b2c2ba` (G9) · [#568](https://github.com/yegamble/vidra-core/pull/568) `881ee9ea` (G10) · [#569](https://github.com/yegamble/vidra-core/pull/569) `4d81533d` (the finding that was not in the plan) |
| PeerTube | `chocobozzz/peertube:v8.3.2-trixie` (`sha256:3fc4a73e…16006ef`), unchanged: `pt` and the control `ctl` |
| Lab | as on 2026-11-16, plus `LAB_VIDRA_CORE_DIR`, which builds vidra's api from another vidra-core tree, and the lab's own image tag (`vidra-core-api:ptinterop-lab`) |
| Host | Docker Desktop on macOS arm64, 7.9 GiB |
| Runs | Five full runs today, control included each time: one per fix as it was written, then the combined branch. The tables are the combined run (06:25–06:32 UTC); every log excerpt is cut from it unless it says otherwise |
| Not touched | sizetube.com, beta.sizetube.com, any workflow, federation settings anywhere outside the lab |

## Control

| | Check | Verdict |
|---|---|---|
| C1 | `ctl` follows the `pt` instance; `accepted` on both sides | PASS |
| C2 | a video uploaded to `pt` arrives on `ctl` as a remote video | PASS |
| C3 | a video made private on `pt` disappears from `ctl`, and returns when made public | PASS |

## Scenarios

| | Scenario | 2026-11-16 | Now |
|---|---|---|---|
| S1 | PeerTube admin follows the vidra instance | PASS | **PASS** |
| S2 | vidra publishes; PeerTube lists it as remote; thumbnail, playlist and first segment fetch | PASS | **PASS** |
| S3 | a PeerTube user follows a vidra channel; backfill and a new video arrive | PASS | **PASS** |
| S4 | a vidra user follows a PeerTube channel | PASS | **PASS** |
| S5 | PeerTube uploads; the video appears on vidra under the channel name | FAIL | **PASS** |
| S6 | vidra admin follows the PeerTube instance; a new upload arrives by `Announce` | PASS | **PASS** |
| S7 | edit, privacy flip, delete, moderator block, both directions | FAIL, 6 of 10 checks | **PASS**, 10 of 10 |
| S8 | negatives | PASS | **PASS** |

45 checks passed, none failed, none blocked. `run.sh` exited 0.

| S7 check | 2026-11-16 | Now | Fixed by |
|---|---|---|---|
| vidra → PeerTube: edit | PASS | PASS | |
| vidra → PeerTube: flip to private | FAIL | **PASS** | #566 |
| vidra → PeerTube: delete | FAIL | **PASS** | #566 |
| vidra → PeerTube: moderator block | FAIL | **PASS** | #566 |
| PeerTube → vidra, channel follow only: edit | FAIL | **PASS** | #568 |
| PeerTube → vidra, channel follow only: delete | PASS | PASS | |
| PeerTube → vidra, instance follow: edit | PASS | PASS | |
| PeerTube → vidra, instance follow: flip to private, once | PASS or FAIL by run | **PASS** | #569 |
| PeerTube → vidra, instance follow: flip to private, five times | FAIL, 4 of 5 left on vidra | **PASS**, 0 of 5 | #569 |
| PeerTube → vidra, instance follow: moderator block with unfederate | PASS | PASS | |

## Each fix alone, then together

Every fix was measured by a full run of its own branch before the combined run,
so each scenario can be seen changing for the reason given.

| vidra-core under test | S2 | S5 | S7a | S7b | S7c |
|---|---|---|---|---|---|
| `main` (2026-11-16) | PASS | FAIL | FAIL | FAIL | FAIL |
| #566 alone, `8c1aa451` | PASS | FAIL | **PASS** | FAIL | FAIL, 3 of 5 left |
| #567 alone, `57b2c2ba` | FAIL (timing) | **PASS** | FAIL | FAIL | FAIL, 3 of 5 left |
| #567 + #568, `881ee9ea` | FAIL (timing) | PASS | FAIL | **PASS** | FAIL, 3 of 5 left |
| #567 + #568 + #569, `4d81533d` | PASS | PASS | FAIL | PASS | **PASS**, 0 of 5 left |
| all four, `23cd351b` | PASS | PASS | PASS | PASS | PASS, 0 of 5 left |

S1, S3, S4, S6 and S8 passed in every run. #568 and #569 are stacked on #567
because all three edit the same function. The two S2 failures are the driver
weakness described below, not a regression.

## What was refused or dropped, and is now applied

### vidra → PeerTube: a retraction removes the video (#566, G8)

Before, PeerTube answered the POST 204 and then refused the Delete, three times
out of three:

```
[pt] warn: Cannot process activity Delete.
     "message": "Account https://vidra.interop.test/video-channels/chan87e713d1 does not own video channel https://vidra.interop.test/video-channels/chan87e713d1"
```

vidra now sends each retraction twice: first from the account that owns the
channel, then from the channel as before. PeerTube acts on the first and
ignores the second. The privacy flip:

```
[pt] 06:31:34.668 info: Receiving inbox requests for 1 activities by https://vidra.interop.test/accounts/labfe4e731f.
[pt] 06:31:34.673 info: … "POST /inbox HTTP/1.1" 204 - "-" "Go-http-client/2.0"
[pt] 06:31:34.679 debug: Removing remote video "49759351-d426-4994-9bea-dbef37924287".
[pt] 06:31:34.691 info: Receiving inbox requests for 1 activities by https://vidra.interop.test/video-channels/chanfe4e731f.
[pt] 06:31:34.692 info: … "POST /inbox HTTP/1.1" 204 - "-" "Go-http-client/2.0"
[pt] 06:31:34.706 info: Remote video with uuid 49759351-d426-4994-9bea-dbef37924287 removed.
```

The delete and the moderator block, same shape:

```
[pt] 06:31:54.690 debug: Removing remote video "034977ed-26b2-41e5-8b57-3c5175c39ede".
[pt] 06:31:54.715 info: Remote video with uuid 034977ed-26b2-41e5-8b57-3c5175c39ede removed.
[pt] 06:32:14.688 debug: Removing remote video "8efdb4cb-f2d3-40f8-ae73-ccb138ddb8fb".
[pt] 06:32:14.739 info: Remote video with uuid 8efdb4cb-f2d3-40f8-ae73-ccb138ddb8fb removed.
```

In the whole run PeerTube logged `Remote video with uuid … removed.` three
times, `Cannot process activity` zero times and `does not own video channel`
zero times. The driver then got HTTP 404 for all three videos from PeerTube.

### PeerTube → vidra: the video is shown under its channel (#567, G9)

Nothing was ever refused here; vidra read the wrong actor out of a valid
object.

```
before  channel_handle "root@pt.interop.test"
        remote_videos.remote_actor_url = https://pt.interop.test/accounts/root
now     channel_handle "root_channel@pt.interop.test"
        remote_videos.remote_actor_url = https://pt.interop.test/video-channels/root_channel
```

It also holds for a channel vidra had never heard of. The S6 upload went to a
second PeerTube channel and reached vidra only through the instance actor's
Announce; vidra fetched that channel's actor and filed the video under it:

```
S6  {"title":"PeerTube via instance follow fe4e731f","remote_actor_url":"https://pt.interop.test/video-channels/second_fe4e731f"}
```

### PeerTube → vidra: an edit reaches a vidra that follows only the channel (#568, G10)

PeerTube's side is unchanged: it sends the Update as the uploader's account to
the one vidra inbox that follows the channel. Before, vidra answered 202 and
dropped it. Now it applies it:

```
[pt]    06:29:09.519 info: … "PUT /api/v1/videos/7a36d050-b1a5-4df4-bb1a-ecb1b56df43b HTTP/1.1" 204
[pt]    06:29:09.530 info: Creating job to update video https://pt.interop.test/videos/watch/7a36d050-b1a5-4df4-bb1a-ecb1b56df43b.
[pt]    06:29:09.533 debug: Creating broadcast job. { "broadcastUris": [ "https://ctl.interop.test/inbox", "https://vidra.interop.test/accounts/labfe4e731f/inbox" ] }
[vidra] 06:29:09.568 POST /accounts/:handle/inbox 202
[vidra] 06:29:09.593 POST /accounts/:handle/inbox 202
driver  first poll: title "PeerTube edited fe4e731f"   (before: still the old title after 60 s)
```

### PeerTube → vidra: a video made private stays gone (#569, not in the plan)

PeerTube's side is unchanged here too. When a video stops being public it
sends a Delete, and in some rounds a stale Update straight after. Before, that
Update put the video back on vidra. Now vidra never stores a video on an
Update's word: it goes back to PeerTube for it, and PeerTube refuses.

The five flips of the combined run (`vidra GET` is vidra re-reading the video
from PeerTube; each activity reaches two vidra inboxes, hence two fetches):

| round | PeerTube sent | vidra's re-read | left on vidra | on stock PeerTube |
|---|---|---|---|---|
| 1 | Delete | none needed | no | 404 |
| 2 | Delete | none needed | no | 404 |
| 3 | Delete, then Update | `401`, `401` | no | 404 |
| 4 | Delete, then Update | `401`, `401` | no | 404 |
| 5 | Delete | none needed | no | 404 |

```
[pt]    06:30:00.264 info: Creating job to broadcast delete of video https://pt.interop.test/videos/watch/29827b90-….
[pt]    06:30:00.278 info: Creating job to update video https://pt.interop.test/videos/watch/29827b90-….
[pt]    06:30:00.284 info: … "PUT /api/v1/videos/29827b90-… HTTP/1.1" 204
[vidra] 06:30:00.293 POST /accounts/:handle/inbox 202   (x2)
[pt]    06:30:00.333 info: 172.18.0.8 … "GET /videos/watch/29827b90-… HTTP/1.1" 401 96 "-" "Go-http-client/2.0"
[pt]    06:30:00.334 info: 172.18.0.8 … "GET /videos/watch/29827b90-… HTTP/1.1" 401 96 "-" "Go-http-client/2.0"
[vidra] 06:30:00.334 POST /accounts/:handle/inbox 202   (x2)
```

Two rounds with a stale Update is a small sample, so the run before it counts
as well: on `4d81533d` PeerTube sent the stale Update in 4 of 5 rounds, vidra
was refused with `401` each time, and 0 of 5 videos were left. The three runs
today without #569 each left 3 of 5.

## Still open, and not failures of any scenario

Nothing in S1–S8 fails, so there is no PeerTube rejection line left to quote
for a failing check. These were observed again and are unchanged, because no
fix for them was in scope:

- **G5, titles under 3 characters.** A vidra video titled `ab` again never
  appeared on PeerTube (404 after 45 s, no row). PeerTube's line is still
  `debug: Video field is not valid to PeerTube: name`.
- **G11, no backfill.** 30 s after PeerTube accepted the channel follow, 0 of
  the 1 public video already on that channel was on vidra.
- **G4, G6, G7, G12** are as unverified as they were on 2026-11-16: the lab
  still never produces a video without a poster or a duration, has no browser,
  and makes PeerTube forward nothing. All 72 inbox POSTs from the two
  PeerTubes during S1–S7 were answered 202.
- **G15** is still visible: PeerTube delivers each broadcast to every vidra
  inbox that follows, so most activities arrive twice.
- PeerTube logged `warn: Cannot determine image extension from input
  https://vidra.interop.test/api/v1/videos/<id>/thumbnail` 13 times and served
  every thumbnail anyway.
- PeerTube logged one error of its own, unrelated to federation:
  `Cannot execute job … in queue video-transcoding … Instance could not be
  reloaded because it does not exist anymore`. The driver had deleted that
  video (S7, "delete me") while PeerTube was still transcoding it.

## A weakness in an S2 check, found today and left alone

S2's last check, "the HLS playlist PeerTube stored is fetchable", failed in 2
of today's 5 runs and passed in the other 3, the combined run among them. It
is a timing fault in the check, not in either product, and the check has
**not** been changed.

vidra announces a video when it is published and sends an Update when its HLS
ladder is ready (`cmd/api/main.go`, `fedUpdate`: "so the object remote
followers hold gains the playable url the publish-time Create could not
carry"). In between, PeerTube holds a copy with no playlist. The check reads
PeerTube's copy once, the moment vidra reports the ladder ready, and in the two
failing runs that was before the Update had been delivered:

```
run on 57b2c2ba
[vidra]  05:47:58.321 upload finalize drain completed        (published; Announce queued)
[pt]     05:48:02.866 debug: Adding remote video …4a048802-… { … "url": [] … }
[pt]     05:48:03.120 info: Remote video with uuid 4a048802-… inserted.
[vidra]  05:48:08.232 transcode drain completed              (ladder ready; Update queued)
[driver] 05:48:11.2   reads PeerTube's copy: streamingPlaylists [] -> FAIL
[pt]     05:48:12.831 debug: Updating remote video "4a048802-…" { … application/x-mpegURL … }
[pt]     05:48:12.850 info: Remote video with uuid 4a048802-… updated
later    PeerTube's copy carries …/hls/master.m3u8
```

The driver was 1.6 s early there and 6 s early on `881ee9ea`. What decides it
is whether PeerTube first fetches the video before or after vidra's ladder is
ready, and that depends on where vidra's delivery tick falls relative to its
transcode:

| run | PeerTube's first fetch, relative to the ladder being ready | first copy had a playlist | S2 |
|---|---|---|---|
| `8c1aa451` | 3.4 s after | yes | PASS |
| `57b2c2ba` | 5.4 s before | no | FAIL |
| `881ee9ea` | 2.3 s before | no | FAIL |
| `4d81533d` | 0.2 s after | yes | PASS |
| `23cd351b` | 3.1 s after | yes | PASS |

So a green S2 here is partly luck: the margin was 0.2 s in one passing run.

Two things follow, and neither was acted on:

- The check should wait for PeerTube's copy to carry a playlist before
  asserting what it asserts now. That is a change to a driver assertion, so it
  waits for a decision.
- For up to about ten seconds after a vidra video is published, a PeerTube that
  follows it lists a video with nothing to play. That is how vidra-core is
  written today, not something this lab was asked to judge.

## What this does not prove

Everything in the 2026-11-16 note's list still applies: nothing about SSRF,
Cloudflare, public DNS or browser playback; `VIDRA_ENV=test`; rate limiting and
scanning off; small numbers. In addition:

- **`main` itself was not run.** The run was on a local merge of the four
  branches. `main` holds the same tree (see the table at the top), so the code
  is the same, but the commit `9e95f1cc` was never booted in the lab.
- **The stale Update is PeerTube's to send or not.** It appeared in 2 of 5
  rounds here and 4 of 5 in the run before. A run in which PeerTube sends none
  would pass the five-flip check without exercising #569 at all; the excerpts
  above are what shows it was exercised.
- **Logs are not kept.** They live in an untracked output directory; this note
  holds the excerpts.

## Reproduce

```
git -C vidra-core worktree add ../../vidra-core-worktrees/fix <commit>
LAB_VIDRA_CORE_DIR=../vidra-core-worktrees/fix tests/peertube-interop/run.sh
```
