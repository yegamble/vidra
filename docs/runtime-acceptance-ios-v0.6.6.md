# v0.6.6 real-iPhone Safari pass — watch, native/MSE playback and sign-in

**PASS for this bounded single-device subset on the v0.6.6 stack. Full release
readiness stays NO-GO.** This is a focused real-iPhone Safari pass of the
highest-risk **iOS-specific** behaviours that desktop Chromium cannot cover —
the watch page loading on iOS Safari, the `<video>` element reaching a playable
state and *advancing*, and a real owner sign-in — run against the **same
v0.6.6 local-storage runtime stack** the [runtime milestone](runtime-acceptance-v0.6.6.md)
(meta#213) stood up (droplet 159.203, `COMPOSE_PROJECT_NAME=vidra-release-acceptance`,
internal origin `https://secure.video.test`, `TLS_MODE=internal` self-signed).
It is **one device and one iOS version**, not a browser matrix, and it moves **no
workflow row**: the [ios-runtime disposition](evidence/release-v0.6.6-verification/ios-runtime/disposition.json)
records it as a measured subset and keeps counts at **5 PASS / 45 UNVERIFIED /
9 BLOCKED**.

Every value in the evidence table is **file-asserted** from
[`ios-runtime/run-3/result.json`](evidence/release-v0.6.6-verification/ios-runtime/run-3/result.json)
unless marked **session-reported** (the real-hardware, real-device-cloud,
tunnel-MITM and host facts, recorded in
[`provenance.json`](evidence/release-v0.6.6-verification/ios-runtime/provenance.json)).

## Candidate, host and tool boundary

- **Candidate.** v0.6.6, exercised against the running stack from the
  native-runtime milestone — the three published images pinned by their v0.6.6
  index digests (core `b2b7717d…07e32fd`, user `4d86a264…be8882e`, search
  `804530bf…555e927c6`), schema `146|f` / search `18|f`. No image, application
  source or deploy script changed for this pass; nothing was rebuilt.
- **Device.** A **real iPhone 15 / iOS 17** on the **LambdaTest real-device
  cloud** (Appium/XCUITest, hub `mobile-hub.lambdatest.com/wd/hub`). The
  `result.json` records `device` "iPhone 15" and `ios` "17"; that this is real
  Apple hardware on the real-device cloud (not a simulator) is **session-reported**.
- **Reaching the private stack.** The stack's origin is the self-signed internal
  `https://secure.video.test`, not a public host, so the device reached it over
  **LambdaTest Tunnel in MITM mode** (`--mitm --allowHosts secure.video.test`,
  tunnel `vidra-v066-ios`, id 17014436) run on the stack host (159.203). MITM is
  what lets iOS Safari present a **trusted padlock** for a self-signed origin
  inside the tunnel. Tunnel name/mode/id and host are **session-reported**.
- **Session.** LambdaTest session `607dbe4f-a428-4a8a-8cbe-ccfd351ef735`, run
  **2026-09-14 21:07:55Z → 21:08:38Z**. The `session_id` is file-asserted in
  `result.json`.
- **Same video as the milestone.** The watch page is `/v/BfnHVc4m9E4`, video
  `8d06000b-627a-4781-952f-05ecb4e8607f`, title `Releaseacceptancec998f7b453b8` —
  the same video the native runtime milestone uploaded, transcoded and indexed,
  now decoded on real iOS hardware.
- **Scope.** The **iOS-specific** page-load / playback-advance / sign-in risks
  only. Everything else stays with the desktop drills. Not deployed: production
  and beta were untouched.

## Executed evidence

Every value below is read from
[`ios-runtime/run-3/result.json`](evidence/release-v0.6.6-verification/ios-runtime/run-3/result.json).

| Check | Result | Measured values |
|---|---|---|
| **watch-page-loads** | **PASS** | iOS Safari loaded `https://secure.video.test/v/BfnHVc4m9E4` over the tunnel (trusted padlock via MITM); document `readyState` complete; page title `Releaseacceptancec998f7b453b8`; URL on-origin |
| **video-element-ready** | **PASS** | `<video>` reached `readyState` **4**, `duration` **12.010666…s** (~12.01 s), `currentSrc` **`blob:https://secure.video.test/ceb2d0b2-…`** — a **Managed Media Source (MSE) path, NOT a native m3u8 src** |
| **playback-advances** | **PASS** | muted inline `play()`; `currentTime` advanced **0 → 2.2549…s** (`advanced_seconds` **2.255**); `paused` **false**, `readyState` **4**, media `error` **null** at both ends |
| **sign-in** | **PASS** | owner credentials submitted through the real login form; landed on `https://secure.video.test/` with the signed-in signal true (account menu / home feed) |

**status: PASS** — all four checks PASS. Screenshots confirm the checks:
[watch page](evidence/release-v0.6.6-verification/ios-runtime/run-3/01-watch.png),
[playing video](evidence/release-v0.6.6-verification/ios-runtime/run-3/02-playing.png)
(frame counter advancing, pause icon),
[login filled](evidence/release-v0.6.6-verification/ios-runtime/run-3/03-login-filled.png),
[signed-in feed](evidence/release-v0.6.6-verification/ios-runtime/run-3/04-signed-in.png).

### The blob: / Managed Media Source finding

On iOS 17 the player's `currentSrc` was a **`blob:` URL**, i.e. the app selected
the **Managed Media Source (MSE)** engine rather than a native `.m3u8` `src`.
This is **expected modern iOS 17 behaviour, not a defect**: `lib/player-engine.ts`
selects hls.js when `MediaSource` or `ManagedMediaSource` is present, and hls.js
1.7.1 prefers `ManagedMediaSource`, which iOS Safari exposes. The desktop
campaign predicted exactly this ("no shipped Apple browser reaches the native-HLS
engine … iOS Safari takes MSE too" — [`play-01-safari.json`](evidence/play-01-safari.json),
and the A32/A33 delivery slice's "WebKit does not take a native-HLS path here")
but had **never verified it on real Apple hardware**. This pass is the first
real-iPhone confirmation of that MSE path — and it confirms playback *advances*
on it. It does **not** exercise the native-HLS branch, which remains covered
only by the safaridriver PLAY-01 slice and stays UNVERIFIED on the v0.6.6 digests.

## Retained attempts — harness/credential artifacts, not product defects

Two earlier attempts are retained for provenance; **neither is a v0.6.6 defect**:

- **run-1** — session refused **"Authorization Required"** at creation. The
  real-device hub, like the tunnel service, requires the account **email** as the
  user (the REST API accepts the username). A credential/harness artifact.
  [`retained/run-1-hub-auth-refused-result.json`](evidence/release-v0.6.6-verification/ios-runtime/retained/run-1-hub-auth-refused-result.json).
- **run-2** — **watch-page-loads and video-element-ready PASSED** (`readyState`
  4, `blob:` src, duration 12.01 s), then the playback-advance check crashed on a
  bug in the operator's own script (a walrus-in-conditional evaluation order:
  `UnboundLocalError: local variable 's'`), fixed for run-3. The retained device
  screenshot shows playback was already in progress (pause icon, moved frame
  counter).
  [`retained/run-2-script-bug-result.json`](evidence/release-v0.6.6-verification/ios-runtime/retained/run-2-script-bug-result.json),
  [`retained/run-2-01-watch.png`](evidence/release-v0.6.6-verification/ios-runtime/retained/run-2-01-watch.png),
  [`retained/run-2-99-fail-playback-advances.png`](evidence/release-v0.6.6-verification/ios-runtime/retained/run-2-99-fail-playback-advances.png).

## Disposition — no row moved

The [ios-runtime disposition](evidence/release-v0.6.6-verification/ios-runtime/disposition.json)
is a delta on the current v0.6.6 disposition
([native-runtime](evidence/release-v0.6.6-verification/native-runtime/disposition.json),
cited as `prior_disposition_sha256`
`34a58bc0b82376a709e501152bc1d53654142f79683598e3d0b9a48b53d2289e`; 5 PASS /
45 UNVERIFIED / 9 BLOCKED). Two rows were **considered and deliberately not
moved**:

- **PLAY-01** ("Watch, seek, quality, speed, resume, PiP/theater and mobile/native
  playback … Chromium plus native-HLS Safari on representative ladder") is a full
  playback-control matrix. This pass is a single-device smoke of page-load +
  currentTime advance + sign-in on one rendition, over the **MSE** path — it
  exercises no seek/quality/speed/resume/PiP, no representative ladder, and not
  the native-HLS branch PLAY-01's Safari slice established. **Kept UNVERIFIED.**
- **QLT-02** ("All required screens handle keyboard/mobile/themes/errors and real
  persistence") is a full control + accessibility inventory. This pass drives no
  control inventory, no axe/keyboard, no theme or error-state checks; it does use
  a real touch device (a residual QLT-02 flagged as missing), but that is one
  fragment of a large row. **Kept UNVERIFIED.**

Being conservative — a single device + version sample does not close a full
browser matrix — no `UNVERIFIED → PASS` move is made. The pass is recorded as a
new `measured_subsets` entry (as the branding toggle was), and counts stay
**5 PASS / 45 UNVERIFIED / 9 BLOCKED**.

## Evidence integrity

The evidence tree is copied verbatim into
`docs/evidence/release-v0.6.6-verification/ios-runtime/`. The exporter's
attestation [`artifact-hashes.json`](evidence/release-v0.6.6-verification/ios-runtime/artifact-hashes.json)
was verified byte-equal against the copied files at commit time, and
[`committed-hashes.json`](evidence/release-v0.6.6-verification/ios-runtime/committed-hashes.json)
is the independent sha256 index recomputed over every committed file in the tree
except itself (13 files, including `disposition.json` and `artifact-hashes.json`).

## What this proves and does not

**Proves:** on the v0.6.6 stack, real **iPhone 15 / iOS 17 Safari** — reaching
the self-signed internal origin over Tunnel MITM with a trusted padlock — loads
the watch page, decodes the published video to `readyState` 4 and **advances
playback 0 → 2.255 s** on the **Managed Media Source (MSE)** path with no media
error, and completes a real owner **sign-in** through the login form. This is the
first real-Apple-hardware confirmation of the MSE playback path the desktop
campaign could only predict.

**Does not prove:** anything beyond this single device + iOS version. It is
**not** the full browser/Safari matrix — no other iOS versions or devices, **no
iPad, no macOS Safari, no accessibility** (screen reader / physical speaker
output). It is **not** upload-from-iOS and **not** player-gesture controls
(seek/quality/speed/resume/PiP). It exercises **local canonical storage** only
(no presign/S3/CDN delivery), and it does **not** exercise the native-HLS branch
(PLAY-01's native-HLS Safari slice stays UNVERIFIED on the v0.6.6 digests). No
workflow row changed status. Not a deployment — production and beta were
untouched.
