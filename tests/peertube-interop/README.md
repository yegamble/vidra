# tests/peertube-interop — vidra ⇄ PeerTube federation lab

A throwaway, local-only lab that makes vidra federate with a **real PeerTube
v8.3.2** and records what happens. It is Step 1 of
`.gg/plans/peertube-federation.md`; the committed record of a run lives in
`docs/evidence/peertube-interop-<date>.md`.

It is **not** a CI lane. Nothing in `.github/workflows` or
`.github/required-checks.txt` refers to it.

## Run it

```
tests/peertube-interop/run.sh --control-only   # PeerTube ⇄ PeerTube only
tests/peertube-interop/run.sh                  # the control, then every scenario against vidra
tests/peertube-interop/run.sh --keep           # leave the stack up afterwards
tests/peertube-interop/run.sh down             # destroy everything
```

To test a vidra-core change, point the lab at a **separate git worktree** that
holds it. The nested `vidra-core/` checkout is left alone (`deploy.sh` reads it
for the migration ledger assertion, so it must stay clean and on its commit):

```
git -C vidra-core worktree add ../../vidra-core-worktrees/fix -b my-fix origin/main
LAB_VIDRA_CORE_DIR=../vidra-core-worktrees/fix tests/peertube-interop/run.sh
```

Only the api **image** is built from that tree; the compose service definition
still comes from the nested checkout, so `run.sh` refuses a tree whose
`docker-compose.yml` differs. The lab tags its image
`vidra-core-api:ptinterop-lab` and never touches `vidra-core-api:local`.

One check (G7) plays a video in a real browser. It uses Google Chrome or
Chromium if one is installed (`LAB_CHROME=<binary>` to name it) and installs
nothing; without a browser that check is reported `blocked` and every other
check still runs.

Needs Docker with Compose ≥ 2.24, Node ≥ 18, `openssl` and `curl`. The script
refuses to start with less than 3 GiB of Docker memory for the control or 5 GiB
for the full run. That is headroom for the image build and transcodes (the
running lab held about 1.1 GiB when sampled), chosen so an OOM kill cannot be
read as a federation failure.
The first full run also builds the vidra-core image from the nested checkout.

Exit codes: `0` everything that ran passed · `1` at least one vidra scenario
failed (read the table — some are expected to while the plan's gaps are open) ·
`2` **the control failed or the lab could not be built: nothing about vidra was
measured.**

## What is in the lab

| Name | What | Where it comes from |
|---|---|---|
| `pt.interop.test` | PeerTube v8.3.2, the instance vidra is tested against | `docker-compose.yml` |
| `ctl.interop.test` | a second, stock PeerTube v8.3.2 — the **control** | `docker-compose.yml` |
| `vidra.interop.test` | vidra's api, built from the nested `vidra-core` checkout | the repo's root `docker-compose.yml` + `docker-compose.vidra.yml` |
| `vidra-caddy` | the shipped `deploy/Caddyfile`, with only its site address changed | rendered by `run.sh` |
| `edge` | Caddy, TLS on an internal CA for all the names above | `Caddyfile.edge` |
| `redir.interop.test` | a host that 302s an actor URL to `pt` (S8 only) | `Caddyfile.edge` |

- **One published port: the edge, on `127.0.0.1:8443`.** The overlay closes the
  base compose files' `0.0.0.0` publishes with `!reset`, and `run.sh` asserts
  the result with `docker ps` instead of trusting it. The names are `.test`
  (RFC 6761) and resolve only on the lab's Docker network.
- **The CA is minted per run** by `run.sh` and trusted by PeerTube
  (`NODE_EXTRA_CA_CERTS`) and by vidra (`SSL_CERT_FILE`). `run.sh` proves the
  trust from inside the containers before any scenario runs.
- **PeerTube logs at `debug`.** PeerTube drops an ActivityPub object it does
  not like with a debug line and nothing else; at `info` a rejected vidra video
  is indistinguishable from one never sent.
- **vidra runs as `VIDRA_ENV=test`** with a throwaway `FEDERATION_KEY_KEK`,
  because production boot refuses `HTTP_IMPORT_ALLOW_PRIVATE_URLS`, which the
  lab cannot do without (every address is a Docker one). The plan said
  `staging`; vidra-core accepts only `development|test|production` and exits
  on anything else. Every production-only check in `internal/config` is
  therefore **not** exercised here.
- **Every run starts from nothing** (`down -v` first). Follows, actors and
  cached keys are durable on both sides; a second run on old volumes would
  "pass" a follow that sent nothing.

## The control comes first, always

Everything vidra-specific rides on a private CA, DNS aliases, a TLS edge and
PeerTube's SSRF guard being off. Break one and all eight scenarios fail looking
like vidra bugs. So `run.sh` first makes the two stock PeerTubes follow each
other and federate a video (C1, C2) through the same edge with the same driver
helpers. **If the control fails the run stops with exit 2 and no vidra scenario
is attempted.** A harness bug must never be read as a vidra bug.

## Scenarios

| | Scenario |
|---|---|
| C1 | control: `ctl` follows the `pt` instance; accepted on both sides |
| C2 | control: a video uploaded to `pt` appears on `ctl` as a remote video |
| C3 | control: a video made private on `pt` disappears from `ctl` (the reference for S7) |
| S1 | PeerTube admin follows the vidra instance |
| S2 | vidra publishes; PeerTube lists it as remote; playlist and first segment fetch |
| S3 | PeerTube user follows a vidra channel; backfill |
| S4 | vidra user follows a PeerTube channel |
| S5 | PeerTube uploads; appears on vidra under the channel's name |
| S6 | vidra admin follows the PeerTube instance; a new upload arrives by `Announce` |
| S7a | vidra → PeerTube: edit, privacy flip, delete, moderator block |
| S7b | PeerTube → vidra with **only a channel follow** (runs before S6): edit, delete |
| S7c | PeerTube → vidra with an instance follow (runs after S6): edit, privacy flip (once, then 5× to expose a race), moderator block |
| S8 | negatives: tampered body, stale `Date`, unsigned, oversized, blocked domain, cross-host redirect |

The gap checks, named after the rows of the plan's gap table:

| | Check | Where |
|---|---|---|
| G4a | an audio-only upload, which vidra publishes with no poster: does PeerTube store it | scenario G4 |
| G4b | a video whose poster size vidra cannot read: does PeerTube store it | scenario G4 |
| G5 | a vidra video with a 2-character title appears on PeerTube | in S2 |
| G6 | an upload whose container states no duration: does PeerTube store it | scenario G6 |
| G7 | PeerTube's own watch page plays the vidra video in headless Chrome | scenario G7 |
| G11 | a video PeerTube published **before** vidra's follow arrives on vidra | in S4 (channel follow) and S6 (instance follow) |
| G12 | a third server's comment on a `pt` video, forwarded by `pt` to vidra, is answered 2xx | scenario G12 |

G4, G6 and G12 each **produce** their case and then prove it was produced
before reading PeerTube's answer. The proof is taken from vidra's own state
where vidra has one to read, so it does not depend on what vidra puts in the
video object: the audio-only upload must have no poster on file (its thumbnail
route answers 404) and the WebM must have no duration probed (the video detail
states none). vidra keeps no record of failing to size a poster, so for that
one the proof is the object: the poster's icon carries no width or height. And
`pt` must log the forwarding jobs. A case that could not be produced is
`blocked`, never a pass.
Nothing is edited in vidra's database or storage: the no-poster video is an
audio-only upload, the unsized poster is a valid JPEG uploaded through vidra's
own API whose frame header lies past the 2 MiB vidra reads (`maxPosterHeaderBytes`; it was 256 KiB when the lab last ran), and the
no-duration video is a WebM written to a pipe, as a browser recording is.

S3 runs against `ctl`, not `pt`: `ctl` has no instance follow with vidra, so a
channel subscription is its only link and whatever arrives arrived because of
it. Execution order is S1 S2 S3 S4 S5 S7b G12 S6 S7c S7a G4 G6 G7 S8. S7b and
G12 must see the channel-only state before S6 adds the instance follow, and
G4 and G6 run after S1–S7 so the objects they leave in vidra's outbox cannot
change what the scenarios before them measured.

A red check carries PeerTube's own log line for the refusal in its detail.
Besides pass/fail checks the driver records **observations** (`observed` in the
results file): measurements that are not part of a scenario's own claim, such
as what PeerTube's player does about P2P, or PeerTube's follow score for vidra.

A failing scenario does not stop the run; the driver records each check and the
UTC window it ran in to `out/results-vidra.json`, and `run.sh` saves the full
PeerTube, vidra and Caddy logs to `out/logs/` on every exit. `blocked` is not
`fail`: it means a step the scenario depends on never happened, so it measured
nothing.

## What the lab does NOT prove

- **Nothing about SSRF.** PeerTube runs with `federation.prevent_ssrf=false`
  and vidra with `HTTP_IMPORT_ALLOW_PRIVATE_URLS=true`. SSRF stays covered by
  vidra-core's `urlsafety` and redirect-policy tests.
- **Nothing about the real edge.** No Cloudflare (no WAF, bot challenge or
  caching of ActivityPub responses), no public DNS, no ACME. The shipped
  Caddyfile's *routing* is real here; its TLS and everything in front of it in
  production are not.
- **One browser, one clip.** G7 plays a single 4 s video in headless Chrome on
  the machine running the lab, with every name outside the lab unresolvable.
  It is not Firefox, Safari, a phone, or PeerTube's embed player. Every other
  playback claim is playlist text plus segment bytes.
- **PeerTube's follow score cannot move in a run.** PeerTube applies failed
  deliveries to a follow's score every 20 hours. G12 measures what feeds that
  (PeerTube marking the vidra inbox bad), not the score.
- **No frontend, no vidra-search, no worker split.** None is on the ActivityPub
  path; anything the shipped Caddyfile routes to `frontend:3000` answers 502.
- **Rate limiting and malware scanning are off** on vidra, as in the
  `stack-e2e` lane and for the same reasons.
- **A source build of whatever the nested `vidra-core` checkout (or
  `LAB_VIDRA_CORE_DIR`) holds**, not a published image. `run.sh` prints the
  commit and the tree; the evidence note must name it.
