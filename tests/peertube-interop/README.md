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
tests/peertube-interop/run.sh                  # the control, then S1-S8 against vidra
tests/peertube-interop/run.sh --keep           # leave the stack up afterwards
tests/peertube-interop/run.sh down             # destroy everything
```

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

S3 runs against `ctl`, not `pt`: `ctl` has no instance follow with vidra, so a
channel subscription is its only link and whatever arrives arrived because of
it. Execution order is S1 S2 S3 S4 S5 S7b S6 S7c S7a S8 — S7b must see the
channel-only state before S6 adds the instance follow.

Besides pass/fail checks the driver records **observations** (`observed` in the
results file): measurements the plan asks for that are not part of a scenario's
own claim, such as whether PeerTube's older videos arrive after a follow.

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
- **No browser and no decoder.** Playback claims are playlist text plus segment
  bytes.
- **No frontend, no vidra-search, no worker split.** None is on the ActivityPub
  path; anything the shipped Caddyfile routes to `frontend:3000` answers 502.
- **Rate limiting and malware scanning are off** on vidra, as in the
  `stack-e2e` lane and for the same reasons.
- **A source build of whatever the nested `vidra-core` checkout holds**, not a
  published image. `run.sh` prints the commit; the evidence note must name it.
