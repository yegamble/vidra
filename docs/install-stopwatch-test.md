# Install stopwatch test — protocol

**Question this answers:** can a person who has never seen Vidra get from a blank
server to a signed-in owner account by following the published quickstart, and
how long does it take?

**Decision it drives** (council ruling, loop 1, EXPERIMENT): if the **median
time across three people is over 20 minutes**, the terminal-first install is not
WordPress-easy enough and the web installer is revisited. Under 20 minutes, the
next step is to fix whatever the testers got stuck on, not to add an installer.

Nothing here is automated, on purpose: CI already proves the install *works*
(`tests/install_test.sh`, the `boot` lane). This measures whether a human can
*follow* it.

## Before you run it

- **Release under test.** Run it against a release that contains `vidra claim`,
  `install.sh --no-setup` and the `sudo -u vidra` guidance — the first release
  after v0.7.5. On v0.7.5 or earlier you are timing the old flow, which the
  quickstart no longer describes. Write the tag in the results file.
- **Three testers**, deliberately mixed:
  1. someone who has administered a Linux server before but never Docker;
  2. a developer comfortable with Docker;
  3. someone who has run WordPress (or similar) from a host's control panel but
     rarely SSHes anywhere.
- **One blank server each**: Ubuntu 24.04 LTS (or Debian 12), **4 vCPU / 8 GB /
  160 GB** — the documented floor (`docs/start/requirements.md` in vidra-docs).
  Not a 2 GB droplet. Snapshot nothing, preinstall nothing.
- **A domain each, DNS already pointing** at the server (an A record created at
  least an hour earlier, so propagation is not what you measure). If a tester
  has no domain, use the setup interview's plain-HTTP mode and note it — that
  run is not comparable on the TLS step.
- **SSH access** handed over as a single line (`ssh root@<ip>` or a sudo user).
  Account setup is not part of the measured time.

## Rules for the session

- The tester gets **only** the quickstart URL:
  `https://vidra.yosef.app/docs/start/quickstart`. Nothing else is explained.
- The observer **does not help**. If the tester asks a question, the observer
  answers "what would you do if I weren't here?" and writes the question down.
  Unblock only after **10 minutes** stuck on one step, and mark that step as a
  failure.
- Screen-share or screen-record **the terminal only**. Never record or write
  down secrets: the setup interview prints generated secrets, and the claim
  link is a credential.
- No time limit; stop at 60 minutes and record "did not finish".

## What to time

Start the stopwatch when the tester's first SSH session opens. Record a lap at
each boundary — each one is a visible event, so two observers agree on it:

| Lap | Ends when |
|---|---|
| 1. Installer | `install.sh` prints its closing "Prepare the host" block |
| 2. Setup interview | `vidra setup` (terminal or `--web`) reports the env file written |
| 3. Provision | `provision.sh` prints `host provisioned. Next: …` |
| 4. Deploy | `vidra deploy` finishes and `/readyz` answers 200 |
| 5. Claim | the tester is **signed in as the owner** in a browser at their domain |

**Stop the clock at the end of lap 5.** Uploading a video is not part of the
test: transcode time measures the hardware, not the install.

For every lap, also record:

- **Stalls**: each time the tester stops for more than 60 seconds, with the
  quickstart heading they were on and what they said.
- **Wrong turns**: any command they ran that the quickstart does not say
  (`sudo` where it says `sudo -u vidra`, editing files by hand, re-running a
  step).
- **Errors**: copy the exact error line (redact secrets).

## Results file

Write one file per round: `docs/install-stopwatch-results-<YYYY-MM-DD>.md`.

```markdown
# Install stopwatch — <date>

Release tested: vX.Y.Z   Server: <provider, region, size>   Observer: <name>

| Tester | Profile | L1 | L2 | L3 | L4 | L5 | Total | Finished? |
|---|---|---|---|---|---|---|---|---|
| A | Linux admin, no Docker | | | | | | | |
| B | Docker developer | | | | | | | |
| C | Control-panel WordPress | | | | | | | |

**Median total:** __ min → [over 20: revisit the web installer | under 20: fix the stalls below]

## Stalls and wrong turns
| Tester | Lap | Quickstart heading | What happened | Exact error (redacted) |
|---|---|---|---|---|

## Fixes filed
- <link to each issue or PR opened from a stall>
```

## Reading the result

- **Median over 20 minutes** → revisit the web installer (the declined
  internet-reachable installer stays declined; a local-only one bound to
  127.0.0.1 over an SSH tunnel is the candidate).
- **Any lap where two of three testers stalled** → that lap is the defect. File
  it against the quickstart or the tool before running another round.
- **Any tester who did not finish** is a defect regardless of the median.
- Re-run after fixes with **new** testers; someone who has done it once is not
  measuring the docs any more.
