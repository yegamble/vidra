# PeerTube interop lab — the open gaps, measured, 2026-11-17

Third note in the series, after
[`peertube-interop-2026-11-16.md`](peertube-interop-2026-11-16.md) and
[`peertube-interop-2026-11-17.md`](peertube-interop-2026-11-17.md). The second
one ended with S1–S8 green and six rows of the plan's gap table still open:
two the lab had only *observed* (G5, G11) and four it could not *produce* at
all (G4, G6, G7, G12). This note is what happened when the lab was made to
check all six, against vidra-core `main` as it stands.

**Result: seven new checks are red and one is green. Every check S1–S8 had
before still passes, and so does the control.**

| Gap | The check | Verdict on `main` |
|---|---|---|
| G4a | a vidra video with no poster is stored by PeerTube | **FAIL** — refused, `icons` |
| G4b | a vidra video whose poster size cannot be read is stored by PeerTube | **FAIL** — refused, `icons` |
| G5 | a vidra video with a 2-character title appears on PeerTube | **FAIL** — refused, `name` |
| G6 | a vidra video of unknown duration is stored by PeerTube | **FAIL** — refused, `duration format` |
| G7 | PeerTube's own watch page plays a vidra video in a real browser | **PASS** — and P2P is cleanly off |
| G11 | a video PeerTube published before a **channel** follow arrives on vidra | **FAIL** — vidra never read the outbox |
| G11 | a video PeerTube published before an **instance** follow arrives on vidra | **FAIL** — vidra never read the outbox |
| G12 | a third server's activity, forwarded by PeerTube, is answered 2xx | **FAIL** — vidra answers `400`; PeerTube marks its inbox bad |

G5 and G11 were expected red. G4a, G4b, G6 and G12 are now **measured**
failures, where before they were readings of source. G7 is **measured and
refuted**: the plan suspected PeerTube's player might not play a playlist
that has no files; it plays.

**Update, the same day: all seven are closed.** Six vidra-core pull requests,
one per gap, turn every red check green. They are merged, and on vidra-core
`main` @ `1ab2ab46` the control and all fourteen scenarios pass, 50 checks out
of 50, with the lab unchanged. The before and after table, and what each fix
changed on the wire, are in [After the fixes](#after-the-fixes).

**Update, 2026-11-18: run again on vidra-core `main` @ `bb081e9d`.** The 17
vidra-core commits merged after `1ab2ab46` (among them the poster-read,
duration, sharedInbox, SSRF-guard and inbound-fetch-budget changes) had not
been in the lab. One full run on `bb081e9d`, control included, with the
rebuilt G4b fixture: `run.sh` exited 0, the control's 5 checks and the 50
vidra checks pass, none failed or blocked. Two things it adds: the G4b poster
whose frame header sits past 2 MiB is still unsized by vidra and still stored
by PeerTube, and PeerTube now lists the video of unknown duration with
`duration: 4` where it listed 0, although vidra still served `PT0S` for it (an
observation, not a check, and not evidence for the duration change: see G6).
It is one run, one desktop Chrome, source-built, not the released images. The
lab runs with `VIDRA_ENV=test`, private fetch addresses allowed and rate
limiting off, so it shows only that those 17 commits did not break federation:
it exercises neither the production https-only rule, nor the private-address
block, nor any inbound fetch limit or its 429.

## What was run

| | |
|---|---|
| vidra-core | `main` @ `67f0897d` (`9e95f1cc`, which the last note measured as a tree but never booted, plus four dependency bumps). Built from a separate git worktree, no tracked file modified; the nested `vidra-core/` checkout was not touched |
| PeerTube | `chocobozzz/peertube:v8.3.2-trixie` (`sha256:3fc4a73e…16006ef`), unchanged: `pt` and the control `ctl` |
| Lab | this repository at `2f8df29` for the run the tables are from, and at `30714c8` for the last run: the driver, `run.sh` and README changes described below |
| Browser | Google Chrome 157.0.8103.79, headless, on the host. Every `*.interop.test` name mapped to the lab edge on `127.0.0.1`; every other name made unresolvable |
| Host | Docker Desktop on macOS arm64, 7.9 GiB |
| Runs | Three full runs, control included each time: 16:27–16:42, 16:47–17:00 and 17:27–17:40 UTC. Every table and excerpt here is from the second. The first and the third gave the same verdict on every check. The third used the final driver, which proves the G4a and G6 cases from vidra's own state instead of from the object it serves (see below) |
| Not touched | any live host (production or beta), any workflow, `required-checks.txt`, federation settings anywhere outside the lab |

43 checks passed, 7 failed, none was blocked, 3 observations were recorded.
`run.sh` exited 1, which is its code for "the control passed and at least one
vidra check is red".

## What changed in the lab

- **S2's playlist check waits.** It re-reads PeerTube's copy for up to 60 s
  until the copy carries a streaming playlist, then asserts exactly what it
  asserted before (master, variant, first segment). The wait was **6 ms** in
  the first run and **8,105 ms** in the second. The second is the timing that
  failed 2 of 5 runs on 2026-11-17.
- **G5 and G11 are checks**, not observations. G11 no longer counts rows 30 s
  after the Accept: it uploads a named public video to PeerTube *before* each
  follow and waits 90 s for that video on vidra. For the instance follow the
  video goes to a channel vidra does not follow, and the check first confirms
  nothing delivered it in the 10 s before the follow.
- **G4, G6 and G12 produce their cases**, through vidra's and PeerTube's own
  APIs. Nothing is edited in a database or in storage:
  - *no poster*: an audio-only upload. vidra grabs no frame from one and
    publishes it with no poster;
  - *poster of unreadable size*: a private video is given a custom poster
    through `POST /api/v1/videos/{id}/thumbnail` and then made public. The
    poster is a valid JPEG whose frame header sat 320 KiB in, behind comment
    segments, when vidra read the first 256 KiB. vidra-core `main` now reads up
    to `maxPosterHeaderBytes` (2 MiB), so that 320 KiB fixture would be sized
    and the check would report BLOCKED; the driver now places the header past
    2 MiB. That fixture ran once, on `bb081e9d` (2026-11-18), and passed;
  - *unknown duration*: a WebM written to a pipe, which states no duration, as
    a browser recording does. `run.sh` asserts with `ffprobe` that it states
    none;
  - *forwarded activity*: a user of the control PeerTube comments on a `pt`
    video that vidra follows the channel of.
- Each of those checks first **proves the case was produced** and is
  `blocked`, not passed, if it was not. In the first two runs the proof was the
  object vidra serves: no icon, no icon size, no duration. That ties the proof
  to how vidra renders such a video, so for the third run it was moved to
  vidra's own state where vidra has one: the audio-only upload has no poster on
  file (its thumbnail route answers 404) and the WebM has no duration probed
  (the video detail states none). vidra keeps no record of failing to size a
  poster, so that one is still read from the object. What is asserted did not
  change, and neither did any verdict.
- **G7 plays a video.** Chrome is driven over its DevTools pipe; nothing is
  installed.
- A red check now carries **PeerTube's own log line** in its detail.

## Control

| | Check | Verdict |
|---|---|---|
| C1 | `ctl` follows the `pt` instance; `accepted` on both sides | PASS |
| C2 | a video uploaded to `pt` arrives on `ctl` as a remote video | PASS |
| C3 | a video made private on `pt` disappears from `ctl`, and returns when made public | PASS |

## Scenarios

| | Scenario | Checks it had before | New checks | Verdict |
|---|---|---|---|---|
| S1 | PeerTube admin follows the vidra instance | 3 of 3 pass | | PASS |
| S2 | vidra publishes; PeerTube lists it; thumbnail, playlist, first segment | 4 of 4 pass | G5 fails | FAIL |
| S3 | a PeerTube user follows a vidra channel; backfill and a new video arrive | 5 of 5 pass | | PASS |
| S4 | a vidra user follows a PeerTube channel | 3 of 3 pass | G11 fails | FAIL |
| S5 | PeerTube uploads; the video appears on vidra under the channel name | 3 of 3 pass | | PASS |
| S6 | vidra admin follows the PeerTube instance; a new upload arrives by `Announce` | 4 of 4 pass | G11 fails | FAIL |
| S7 | edit, privacy flip, delete, moderator block, both directions | 10 of 10 pass | | PASS |
| S8 | negatives | 8 of 8 pass | | PASS |
| G4 | vidra videos with no poster, and with a poster of unreadable size | | both fail | FAIL |
| G6 | a vidra video of unknown duration | | fails | FAIL |
| G7 | PeerTube's watch page plays the vidra video in a real browser | | passes | PASS |
| G12 | PeerTube forwards a third party's activity to vidra | | 2 pass, 1 fails | FAIL |

S2, S4 and S6 are red only on the check added to each. This is also the first
time the commit on `main` itself was booted in the lab: the four fixes of
2026-11-17 hold (S5 and all ten S7 checks pass, five privacy flips left
nothing on vidra).

## Each red check, with what PeerTube said

### G5 — a title under 3 characters: the whole video is refused

A vidra video titled `ab`. PeerTube fetched it and refused it; ten seconds
later vidra's transcode-complete `Update` for it was dropped at the inbox for
the same reason. PeerTube answered 404 for the video 45 s after publish and
held no row.

```
[pt] 16:48:34.030 info: Fetching remote video https://vidra.interop.test/videos/d448ce51-e7c9-4ebf-889f-bac14096e413.
[pt] 16:48:34.038 debug: Video field is not valid to PeerTube: name
[pt] 16:48:34.038 debug: Remote video JSON is not valid.
[pt] 16:48:34.038 debug: Cannot fetch remote video https://vidra.interop.test/videos/d448ce51-…: maybe not a video object?
[pt] 16:48:44.031 debug: Video field is not valid to PeerTube: name
[pt] 16:48:44.031 debug: We keep 0 activities.
```

How PeerTube counts the 3, run against the validator package inside the
PeerTube image: it counts **code points, and does not count the variation
selectors U+FE0E and U+FE0F**. Two emoji have length 2; `ab` followed by
U+FE0F has length 2. A fix that counts bytes or plain code points would still
let some titles through to a refusal.

### G4a — no poster: the whole video is refused

An audio-only upload. vidra served the object with no `icon`.

```
vidra served   {"icon": null, "duration": "PT4S"}
[pt] 16:56:44.214 debug: Video field is not valid to PeerTube: icons
[pt] 16:56:44.214 debug: Remote video JSON is not valid.
[pt] 16:56:44.214 debug: Cannot fetch remote video https://vidra.interop.test/videos/fc2c97b4-e013-4902-b975-67bad045f730: maybe not a video object?
```

404 from PeerTube 60 s later, no row.

### G4b — a poster whose size vidra cannot read: the whole video is refused

vidra served the icon with a `url` and a `mediaType` and no `width` or
`height`. Because the video went from private to public, vidra sent an
`Update`, and PeerTube dropped it at the inbox before fetching anything:

```
vidra served   {"type": "Image", "mediaType": "image/jpeg", "url": "https://vidra.interop.test/api/v1/videos/c8579025-…/thumbnail"}
[pt] 16:57:54.217 debug: Filtering 1 activities...
[pt] 16:57:54.217 debug: Video field is not valid to PeerTube: icons
[pt] 16:57:54.217 debug: We keep 0 activities.
[pt] 16:57:54.217 info: Receiving inbox requests for 0 activities by https://vidra.interop.test/video-channels/chandfe5778b.
```

PeerTube answered the POST 204 all the same, so vidra's delivery reads as
delivered. 404 from PeerTube 60 s later, no row.

### G6 — unknown duration: the whole video is refused

vidra's probe read no duration from the WebM and served the object without
one. The poster was fine (640×480).

```
vidra served   {"duration": null, "icon": [{"width": 640, "height": 480, …}]}
[pt] 16:59:04.242 debug: Video field is not valid to PeerTube: duration format
[pt] 16:59:04.242 debug: Remote video JSON is not valid.
[pt] 16:59:04.243 debug: Cannot fetch remote video https://vidra.interop.test/videos/b4088632-c7e0-46c2-9721-44dab345a5e4: maybe not a video object?
```

404 from PeerTube 60 s later, no row.

### G11 — nothing published before a follow ever arrives

There is no PeerTube line to quote, because PeerTube was never asked. It logs
every read of an outbox, and in the whole run it logged one: the control
PeerTube reading `pt`'s after its own follow, which is what PeerTube does and
vidra does not.

```
[pt] 16:47:27.817 info: Receiving outbox request for https://pt.interop.test/accounts/peertube/outbox.   (ctl, during the control)
```

| | Read of the followed outbox by vidra, after its follow | Pre-follow video on vidra after 90 s |
|---|---|---|
| channel follow (S4) | 0 reads of `/video-channels/root_channel/outbox` | no; vidra held 0 of `pt`'s 2 public videos |
| instance follow (S6) | 0 reads of `/accounts/peertube/outbox` | no; vidra held 2 of `pt`'s 5 public videos, both uploaded after a follow |

The other direction works and shows what is missing: when `ctl` followed the
vidra channel in S3, it read vidra's channel outbox twice within a second and
the earlier video arrived.

### G12 — a forwarded activity is answered 400, and PeerTube counts it

A `ctl` user posted five comments on a `pt` video. `pt` stored them and
forwarded each to the one vidra inbox in that video's audience. The POST is
signed by `pt`'s instance actor; the activity inside is `ctl`'s, with `ctl`'s
id. vidra refuses an activity whose id is not on the signer's host.

```
[pt]    16:51:33.140 info: Forwarding activity https://ctl.interop.test/videos/watch/71bb3564-…/comments/1/activity.
[pt]    16:51:33.145 debug: Creating forwarding job.
[vidra] 16:51:33.153 WARN request POST /accounts/:handle/inbox 400
[pt]    16:51:33.157 debug: HTTP broadcast to https://vidra.interop.test/accounts/labdfe5778b/inbox failed.
           "message": "Request failed with status code 400 (Bad Request): POST https://vidra.interop.test/accounts/labdfe5778b/inbox"
           "responseBody": "{\"error\":{\"code\":\"bad_request\",\"message\":\"invalid activity\",…}}"
[pt]    16:51:33.158 info: Updating 0 good actor follows and 1 bad actor follows.
```

| | |
|---|---|
| comments posted on `ctl` / received by `pt` | 5 / 5 |
| forwarding jobs `pt` created naming a vidra inbox | 5 |
| vidra's answers | `400` × 5 |
| status PeerTube recorded | `400` × 5 |
| times PeerTube marked the vidra inbox bad | 5 |
| PeerTube's follow row for vidra, before and after | `accepted`, `score=5000` both times |

The score did not move, and it could not have within a run. What PeerTube
does with a bad inbox, read from the code in the image
(`lib/schedulers/actor-follow-scheduler.js`, `initializers/constants.js`):

- every **20 hours** it takes the inboxes that had a failed delivery and the
  inboxes that had a successful one since the last pass;
- an inbox that had failures **and no success** costs every follow behind it
  **1,000 points**, from a base of 5,000; an inbox with both is left alone;
- a follow at 0 is **deleted**.

So this is not an immediate loss, and a vidra that also receives ordinary
deliveries from the same PeerTube in the same 20 hours is spared. But a vidra
user who follows a PeerTube channel that uploads rarely and is commented on,
shared or viewed from other servers (PeerTube forwards all of those) gets only
refusals in most windows, and after five such windows PeerTube silently drops
the follow. The lab measured the cause (the `400` and PeerTube recording it);
the 20-hour arithmetic is read, not measured.

## The green one: G7

PeerTube's watch page for the S2 video, in headless Chrome:

| | |
|---|---|
| `readyState` | reached 4 (`HAVE_ENOUGH_DATA`) |
| `currentTime` | 0 → 2.22 s across 12 samples, without a click (the page autoplayed) |
| decoded frames | 71, none dropped, 320×240 |
| `MediaError` | none |
| fetched from vidra | the master playlist, 2 media playlists, 2 init segments, 2 media segments — all `200` |
| failed requests, console errors, page exceptions | none |

**P2P is cleanly off.** PeerTube's player showed its HTTP-fallback label
(`HLS`) and not its peer counters. It opened no WebSocket and asked for no host
outside the lab. One `RTCPeerConnection` was created and closed at once
without making an offer.

One thing seen on the way and not a failure of this check: PeerTube's API
lists tracker URLs for the vidra video that it derived from vidra's hostname,
`wss://vidra.interop.test/tracker/socket` and
`https://vidra.interop.test/tracker/announce`. vidra has no tracker. The web
player did not contact either.

## Groundwork for the G5 fix: which padding PeerTube takes

The fix for G5 has to turn `ab` into something PeerTube's validator counts as
3. Candidates were run through that validator inside the image, and two were
then federated between the two PeerTubes (`ctl` → `pt`) and looked at on
`pt`'s watch page.

| Padding added to `ab` | PeerTube's validator | PeerTube → PeerTube, end to end |
|---|---|---|
| a trailing space | accepts | **cannot be produced by a PeerTube**: its upload form trims the name first and answers 400 |
| a no-break space, U+00A0 | accepts | same, 400 |
| a zero-width space, U+200B | accepts | stored as sent on both; the page shows `ab` and the invisible character stays in the name and in the page title |
| a braille blank, U+2800 | accepts | stored as sent; the page shows `ab` followed by a blank that takes up width |
| the variation selector U+FE0F | **rejects** (not counted) | |

PeerTube's inbox path does not trim (`name: videoObject.name`), so a trailing
space from vidra should be stored as sent. That has not been measured yet,
because no PeerTube can send one. It is the first thing the run on the fix
has to show.

## After the fixes

One pull request per gap, each with its failing test first. G7 passed on
`main`, so nothing was changed for it.

| Gap | Pull request | What changed in vidra-core |
|---|---|---|
| G5 | [vidra-core#570](https://github.com/yegamble/vidra-core/pull/570) | the name on the wire has a 3-character floor: a shorter title is padded with trailing spaces. The stored title is untouched |
| G4a, G4b | [#572](https://github.com/yegamble/vidra-core/pull/572) | a video with no poster, or with one vidra cannot size, also names a fallback poster: a real 640×360 PNG served by the instance |
| G6 | [#573](https://github.com/yegamble/vidra-core/pull/573) | an unknown duration is stated as `PT0S` instead of being left out |
| G11 | [#574](https://github.com/yegamble/vidra-core/pull/574), [#575](https://github.com/yegamble/vidra-core/pull/575) | a bounded reader for a followed actor's outbox, and an accepted Follow that queues one read of it |
| G12 | [#571](https://github.com/yegamble/vidra-core/pull/571) | a forwarded activity is answered 202 and ignored, not refused |

### What was run

| | |
|---|---|
| vidra-core | `bd0fcb20`, a local merge of the heads of the six pull requests on top of `main` @ `67f0897d` (tree `9a0186a0…`), built from a separate git worktree with no tracked file modified |
| On `main` since | All six were merged after that run. vidra-core `main` @ `1ab2ab46` has the same tree (`9a0186a0…`), and was then booted in the lab itself |
| Lab | this repository at `187afe8`: the driver, `run.sh`, compose files and README byte-identical to the last run on the old `main` above |
| Everything else | as above: PeerTube `v8.3.2-trixie`, Chrome 157, the same host |
| Runs | two full runs, control included each time: the local merge `bd0fcb20`, 18:04–18:12 UTC, and `main` @ `1ab2ab46`, 18:42–18:50 UTC. `run.sh` exited 0 both times, with the same verdict on every check. The excerpts below are from the first |

### Before and after

| | Check | `main` @ `67f0897d` | With the six fixes |
|---|---|---|---|
| C1–C3 | the control | PASS | PASS |
| S1–S8 | the 40 checks they had before today | 40 of 40 pass | 40 of 40 pass |
| G4a | a vidra video with no poster is stored by PeerTube | FAIL | **PASS** |
| G4b | a vidra video whose poster size cannot be read is stored by PeerTube | FAIL | **PASS** |
| G5 | a vidra video with a 2-character title appears on PeerTube | FAIL | **PASS** |
| G6 | a vidra video of unknown duration is stored by PeerTube | FAIL | **PASS** |
| G7 | PeerTube's watch page plays a vidra video in a real browser | PASS | PASS |
| G11 | a video published before a channel follow arrives on vidra | FAIL | **PASS** |
| G11 | a video published before an instance follow arrives on vidra | FAIL | **PASS** |
| G12 | a forwarded third-party activity is answered 2xx | FAIL | **PASS** |
| | checks passed / failed / blocked | 43 / 7 / 0 | **50 / 0 / 0** |
| | scenarios passed, of 14 | 8 | **14** |

In each of the two runs PeerTube logged `Video field is not valid to PeerTube`
zero times (7 in each run on the old `main`) and marked no inbox bad (5 in
each). vidra answered 79 and 81 inbox POSTs with 202 and 5 with 401; the 401s
are S8's negatives, which are meant to be refused.

Two things differed between the two runs, neither in a check. S2's wait for
PeerTube's copy to carry a playlist was 10.1 s in the first and 7 ms in the
second. And in the second, PeerTube's player logged one non-fatal warning
while playing the video of unknown duration (`HLS.js error: mediaError -
fatal: false - bufferStalledError`) and dropped one frame of 71; in the first
it logged nothing and dropped none. Playback advanced in both.

### G5 — which padding PeerTube takes, and how it shows it

The fix pads with trailing spaces. This is the measurement the groundwork
above was waiting for.

```
vidra title               "ab"
vidra serves              "name": "ab "
[pt] 18:06:16.386 info:   Fetching remote video https://vidra.interop.test/videos/70ced5bf-7d2a-478f-a957-233eaf3c001a.
[pt] 18:06:16.415 info:   Remote video with uuid 70ced5bf-7d2a-478f-a957-233eaf3c001a inserted.
PeerTube's API            "name": "ab "      U+0061 U+0062 U+0020
PeerTube's watch page     heading text "ab ", drawn as "ab"; page title "ab - PeerTube"
```

So PeerTube **accepts** the trailing space, **stores** the name as sent, and
**shows** the title alone: the layout drops the space, and the page title has
no gap before the separator. Set beside the candidates trialled earlier:

| Padding | Accepted | In the stored name | On PeerTube's page |
|---|---|---|---|
| **trailing space** (chosen) | yes | a space, which any trim removes | `ab` |
| zero-width space, U+200B | yes | an invisible character no trim removes | `ab`, with the character still in the heading and the page title |
| braille blank, U+2800 | yes | a visible-width blank | `ab` and a gap |
| U+FE0F | no: PeerTube does not count it | | |

### G4 — a video with no poster it can size

vidra now adds a fallback icon, and PeerTube takes it. The audio-only upload:

```
vidra serves   "icon": [{"type": "Image", "mediaType": "image/png", "width": 640, "height": 360,
                         "url": "https://vidra.interop.test/api/v1/federation/poster.png"}]
[pt] 18:10:36.404 info: Fetching remote video https://vidra.interop.test/videos/2fe78bd5-29be-4bfc-8783-143ae7a09d56.
[pt] 18:10:36.431 info: Remote video with uuid 2fe78bd5-29be-4bfc-8783-143ae7a09d56 inserted.
PeerTube holds one thumbnail for it, 640x360
```

The video whose poster vidra cannot size keeps that poster first, without a
size, and gains the fallback second. PeerTube drops the first and keeps the
second. This is also the first time the lab saw a vidra video go from private
to public: vidra sends an `Update`, and PeerTube creates the video from it.

```
vidra serves   "icon": [{"type": "Image", "mediaType": "image/jpeg", "url": "…/api/v1/videos/dede0f26-…/thumbnail"},
                        {"type": "Image", "mediaType": "image/png", "width": 640, "height": 360, "url": "…/api/v1/federation/poster.png"}]
[pt] 18:10:56.427 debug: We keep 1 activities.
[pt] 18:10:56.430 info: Fetching remote video https://vidra.interop.test/videos/dede0f26-c68c-4e23-8c0a-e3e3803111ec.
[pt] 18:10:56.467 info: Remote video with uuid dede0f26-c68c-4e23-8c0a-e3e3803111ec inserted.
PeerTube holds one thumbnail for it, 640x360
```

### G6 — a video of unknown duration

```
vidra serves   "duration": "PT0S"
[pt] 18:11:06.401 info: Fetching remote video https://vidra.interop.test/videos/4e8091b8-0c2b-4ea8-9264-bd726f477b08.
[pt] 18:11:06.423 info: Remote video with uuid 4e8091b8-0c2b-4ea8-9264-bd726f477b08 inserted.
PeerTube's API  "duration": 0
```

Stored is not played, so the lab also loaded PeerTube's watch page for it. In
the first run (the excerpt above): `readyState` 4, `currentTime` 0 → 2.07 s, 66
frames decoded, none dropped, no `MediaError`, no page error. In the second run
PeerTube's player logged one non-fatal `bufferStalledError` and dropped one
frame of 71 (see "Two things differed" above); playback advanced in both runs.
The input fixture is 4 s long (`tests/peertube-interop/run.sh` generates it with
`duration=4`); the length of the media vidra served was not measured. The driver
stops watching as soon as playback has advanced 2 s, so what was observed is
playback moving to about 2 s on a video PeerTube lists with a duration of 0. The
lab did not watch it to the end, so this does not show that PeerTube plays all
of it, and the stall was not followed further.

2026-11-18: vidra-core
[#576](https://github.com/yegamble/vidra-core/pull/576) (merged, unreleased)
now fills in the duration its transcode measures, once the video has been
transcoded. Whether this lab's G6 upload (`needHls: false` in
`tests/peertube-interop/driver.mjs`) takes that path was not checked, and none of
this has been re-measured against PeerTube: everything above is from before it.

Run on `bb081e9d` (2026-11-18): for the same G6 upload the object the driver
read from vidra still said `"duration": "PT0S"`, so #576 is **not shown by the
lab**. PeerTube nonetheless stored and listed the video with `duration: 4`,
where it listed 0 before, with playback again advancing to about 2 s and no
page error. Where PeerTube's 4 came from was not traced (a later Update from
vidra, or PeerTube's own reading of the file). The value is an OBSERVED line,
not a check, and it is one run. Showing #576 would
need a scenario that fetches the object after the transcode has measured the
duration and asserts it is not `PT0S`; that is not changed here.

### G11 — what PeerTube published before the follow

PeerTube now logs vidra reading the outbox it follows, 3.4 s after each
Accept reached vidra (18:06:46.5 and 18:07:26.4), and vidra's worker logs what
the read stored:

```
[pt]    18:06:49.895 info: Receiving outbox request for https://pt.interop.test/video-channels/root_channel/outbox.
[pt]    18:06:49.908 info: Receiving outbox request for https://pt.interop.test/video-channels/root_channel/outbox.
[vidra] 18:06:49.941 INFO federation: read a followed actor's outbox  actor=…/video-channels/root_channel stored=2 state=done
[pt]    18:07:29.880 info: Receiving outbox request for https://pt.interop.test/accounts/peertube/outbox.
[pt]    18:07:29.895 info: Receiving outbox request for https://pt.interop.test/accounts/peertube/outbox.
[vidra] 18:07:29.921 INFO federation: read a followed actor's outbox  actor=…/accounts/peertube stored=1 state=done
```

| | Reads of the followed outbox by vidra | Stored | The staged video on vidra |
|---|---|---|---|
| channel follow (S4) | 2 (the outbox, then its page) | 2: the staged video and the control's | yes, filed under `root_channel` |
| instance follow (S6) | 2 | 1: the staged video; the others were already held and not fetched again | yes, filed under its own channel `early_…`, which vidra does not follow |

### G12 — a forwarded activity

Same five comments, same five forwards. vidra now answers each 202 and applies
none, and PeerTube records a good delivery where it recorded a bad one:

```
[pt]    18:06:57.950 info: Forwarding activity https://ctl.interop.test/videos/watch/6e766ef4-…/comments/1/activity.
[vidra] 18:06:57.966 DEBUG federation: forwarded activity accepted and ignored  activity_type=Create activity_host=ctl.interop.test forwarded_by=pt.interop.test
[vidra] 18:06:57.966 INFO request POST /accounts/:handle/inbox 202
[pt]    18:06:57.967 info: Updating 1 good actor follows and 0 bad actor follows.
```

| | `main` | With the fix |
|---|---|---|
| forwarding jobs `pt` created naming a vidra inbox | 5 | 5 |
| vidra's answers | `400` × 5 | `202` × 5 |
| failed broadcasts PeerTube logged | 5 | 0 |
| times PeerTube marked the vidra inbox bad | 5 | 0 |

## Still open after the fixes

Nothing in the lab fails. These are known and were not in scope, or are what a
fix leaves behind:

- **A forwarded comment is ignored, not shown.** vidra cannot attribute it
  without verifying its LD signature, so a third server's comment on a followed
  PeerTube video still does not appear on vidra.
- **vidra still does not know the duration** of a video whose container states
  none; it now says so in a form PeerTube accepts. PeerTube lists such a video
  with a duration of 0. (As measured here; vidra-core #576 since changes this
  for transcoded videos; the lab does not show it: see the 2026-11-18 note
  under G6.)
- **The fallback poster is one flat colour.** As measured here,
  vidra read only the first 256 KiB of a poster for its size; vidra-core `main`
  now reads up to `maxPosterHeaderBytes` (2 MiB); a poster whose header sits
  past that ran once on `bb081e9d` and is still unsized and still stored.
- **The backfill is bounded**: the outbox and ten pages, about the newest
  hundred videos. A follow accepted before the fix is not read.
- **PeerTube lists tracker URLs on vidra's hostname** for every vidra video.
  vidra has no tracker. The web player does not use them.
- **For up to about ten seconds after a vidra video is published**, a PeerTube
  that follows it lists a video with nothing to play (the wait in S2 was
  10.1 s in this run). Unchanged.
- From the plan's gap table, untouched by the fixes measured here: G2 (the
  real edge, Cloudflare), G16–G18. G13, G14 and G15 have since been **partly**
  addressed in vidra-core `main`: **merged, not released, not deployed, and not
  run in this lab**.
  - G13 (no rate limit on the inbox): inbound-path actor fetches are now bounded
    and budgeted per host, with refusals counted by reason. The edge per-IP
    limit is still open.
  - G14 (one switch relaxes SSRF for the importer and for federation): the
    cloud-metadata range is always blocked, and actor fetches require https in
    production. The shared relaxing switch is not claimed closed beyond that.
  - G15 (PeerTube delivers once per vidra inbox that follows): every actor now
    advertises the instance `/inbox` as its `sharedInbox`. Whether PeerTube then
    delivers once per instance was not measured.

## What this does not prove

Everything in the two earlier notes' lists still applies: nothing about SSRF,
Cloudflare or public DNS; `VIDRA_ENV=test`; rate limiting and scanning off;
small numbers. In addition:

- **The cases are produced, not found.** G4a, G4b and G6 show what PeerTube
  does with such a video. They say nothing about how often a real vidra has
  one. The unsized poster in particular is built to defeat vidra's poster read
  (256 KiB when measured, 2 MiB on main now); a poster vidra cannot size for another reason (a storage error, an
  unreadable file) gives the same object but was not produced.
- **G7 is one browser and one 4-second clip**: desktop Chrome, H.264 and AAC,
  one rendition. Not Firefox, Safari, a phone, or PeerTube's embed player.
- **G12's consequence is read, not measured.** The lab saw the refusal and
  PeerTube recording it. The score change 20 hours later and the deletion of
  the follow are PeerTube's code as read from the image.
- **G12 covers a forwarded comment.** PeerTube forwards views, shares, comment
  deletions and redundancy records through the same function
  (`forwardVideoRelatedActivity`); none of those was produced.
- **Logs are not kept.** They live in an untracked output directory; this note
  holds the excerpts.
- **The fixes were run twice, together.** Once as a local merge and once as
  `main`. No run isolates one fix from the other five; each check is specific
  to one fix, and the excerpts show each fix doing its work.

## Reproduce

```
git -C vidra-core worktree add ../../vidra-core-worktrees/main --detach 67f0897d
LAB_VIDRA_CORE_DIR=../vidra-core-worktrees/main tests/peertube-interop/run.sh
```

For the run on the fixes, the same with the worktree at `1ab2ab46`.
