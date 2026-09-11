# v0.6.4 first runtime milestone — local storage demonstrated

**PASS for this bounded milestone on the published v0.6.4 images. Full release
readiness remains NO-GO.** This completed run used **local canonical storage**.
The operator subsequently required Backblaze B2 test storage with all Sizetube
live and backup buckets excluded. The separate [B2 continuation](runtime-acceptance-b2-v0.6.4.md)
retains that requirement; this local pass does not certify B2. One agent continued
[PR #185](https://github.com/yegamble/vidra/pull/185) with its unchanged
[frozen manifest](evidence/release-v0.6.4-verification/manifest.json).
The operator authorized deleting beta `104.236.27.225` and starting fresh.
That droplet was deleted; replacement **159.65.249.255**, DigitalOcean ID
**599514574**, ran native Ubuntu **24.04.4 LTS / x86_64**, 8 vCPUs, 16 GiB RAM
and 320 GiB disk. Its firewall permits only operator SSH; the browser used
`https://secure.video.test` inside the guest. Production and shared labs were
untouched. No application source, image or released deployment script changed.

The uninterrupted passing run lasted from **2026-09-11 03:27:56 UTC** to
**2026-09-11 03:32:39 UTC** (September 10 in the operator's timezone).
[Runtime observations](evidence/release-v0.6.4-verification/native-runtime/result.json),
[browser measurements](evidence/release-v0.6.4-verification/native-runtime/browser.json),
[exact commands and raw-log hashes](evidence/release-v0.6.4-verification/native-runtime/commands.json)
and [host/attempt provenance](evidence/release-v0.6.4-verification/native-runtime/provenance.json)
record the actual execution. The original
[blocked preparation](evidence/release-v0.6.4-verification/runtime-preparation.json)
is retained as historical evidence; B1 host access is now resolved.

| Required step | Actual result |
|---|---|
| Fresh installation | Blank native host, released installer/CLI/bundle checksums, corruption refusal and configuration-preserving reinstall PASS; Docker 29.8.0, Compose 5.5.1 |
| Deployment | Published immutable core/user/search images inspected before and after the browser; released deploy script unchanged; core **146\|f**, search **18\|f**; edge health/readiness/version/runtime origin PASS |
| Owner | Browser claim, logout, login, refresh and persisted admin identity PASS; owner `9f464732-bc11-4ee4-8ddd-e5a67c044d3c` |
| Real upload | Browser-created channel/draft, file selection, metadata/public privacy and Publish; video `b2f9216a-559d-479b-aa5d-21913c8c0dbc`; downloaded original **1311662 bytes**, SHA-256 matches source |
| Real transcode | Durable job `9c7edcbd-7098-4594-b87a-595d00e14a92` **done**, retry counter **0**; CMAF renditions and **12** advertised playlists/init/fragments fetched successfully |
| Browser playback | Chromium **153.0.8010.12** HLS blob source; time **0.00 → 3.69 s**, decoded frames **23 → 135**, decoded audio bytes **13907 → 60419**; unmuted, no media error; seek **7.00 s** |
| Real search | Same UUID in delivered outbox + search inbox + eligible document + signed internal result; unchanged UI query returned it and opened it; vidra-search successful query counter **1 → 2**; additional routed browser fetch recorded **source=search**, event `6fb621b6-581b-4d11-81bc-8d189a128b9f` |

Actual screenshots: [claimed owner](evidence/release-v0.6.4-verification/native-runtime/owner-claimed.png),
[published upload](evidence/release-v0.6.4-verification/native-runtime/upload-published.png),
[advancing playback](evidence/release-v0.6.4-verification/native-runtime/playback-advancing.png),
[search result](evidence/release-v0.6.4-verification/native-runtime/search-result.png).
Hashes are in the browser record and
[artifact inventory](evidence/release-v0.6.4-verification/native-runtime/artifact-hashes.json).

Earlier fresh attempts stopped on harness assumptions: Docker frontend
health was still starting after HTTP readiness, Node needed Ubuntu's `libatomic1`,
identity readback reused the access token revoked by session refresh, and
rapid test bursts met the published request limit at UI search or its subsequent
supplemental routing fetch. The runner records any 429 and obeys its Retry-After
before a bounded browser reload or supplemental request retry;
no limiter is disabled or reset. The passing run's UI request attempts were
`[{"status": 429, "retry_after": "32"}, {"status": 200, "retry_after": null}]`. Supplemental request attempts are
recorded separately in the browser evidence.
Retained-host diagnostics additionally established that transcode `attempts`
counts retries (zero is valid first-run success) and UI-owned search telemetry
deliberately suppresses the server's duplicate routing event. The corrected
driver measures the actual UI's successful vidra-search request counter, then
uses A09's separate routed fetch for `source=search`. All failed/interrupted
observations remain in private archives. A fresh OS rebuild followed the
diagnostics; none of those partial runs is substituted for this passing run.
No application defect or modified-build result was required.

[Current disposition](evidence/release-v0.6.4-verification/native-runtime/disposition.json)
closes SRC-01 and the A02 installer procedure. It removes B1 from remaining
workflow blockers: unexecuted cases become UNVERIFIED, while B2–B5/U1 stay
attached to dependent requirements. All other criteria, historical passes and
scope decisions are preserved. This change remains **open — awaiting review and
merge** in [draft PR #186](https://github.com/yegamble/vidra/pull/186); this
session prohibits merging, release publication and production deployment.

## Scope and acceptance

The runner uses the four revisions, three immutable application-image references
and asset checksums in the existing
[manifest](evidence/release-v0.6.4-verification/manifest.json). It refuses source,
asset, prepared-file and running-image drift. It does not replace the released
`deploy.sh` with the current meta script. Only the disposable bundle's six
application service/migrator/worker image lines become the frozen digest plus
`platform: linux/amd64`; semver settings and every shipped deployment guard stay
intact. Third-party images keep the release's references; their actual loaded
digests and image IDs are captured too.

[Host runner](../tests/release_acceptance.py) reuses the A02 install assertions
(including corruption refusal and configuration-preserving reinstall) and A03
port/ledger assertions. [Browser driver](../tests/release-acceptance.mjs) adapts
the existing owner, upload, playback and search drivers to a fresh host. The
released UI holds upload completion until Publish saves metadata; the old A06
driver's wait-before-Publish sequence is unsuitable for this candidate.

Success requires all of these in **one new run**:

1. Native Ubuntu 24.04/x86_64, root/systemd, no container runtime/data/install
   tree; real released installer and checksum-verified native CLI/bundle.
   Test Node/Playwright tooling and Ubuntu `libatomic1` are installed only after
   application installation.
2. Released setup engine, local storage, internal test TLS, closed registration,
   enabled CMAF transcoding and real search. Default ClamAV/fail-closed scanning
   stays enabled. Frozen deploy executes its pre-dump/pull/gated-migration/start/
   probe sequence. No migration SQL or deployment order is rewritten.
3. Actual core ledger **146|f** and search ledger **18|f**, compared with frozen
   source migration filenames/hashes; released bundle provenance and deployment
   scripts checked independently. Actual service image IDs, RepoDigests,
   architectures, revisions, health, runtime ports, deployment container events
   (including removed migrators), edge/version and runtime-origin probes saved.
4. Browser owner claim, admin identity readback, sign-out, login and session
   refresh; create/select a channel in Studio. Choose a generated 12-second
   640×360 H.264/AAC moving-pattern/sine file, set a unique title/public privacy,
   press Publish, observe real completion and fresh UI readback. Downloaded
   original SHA-256 must equal the uploaded file. No API-only publication.
5. The same video's durable transcode job completes; the retry counter is recorded
   (zero means success without a retry). Its
   advertised CMAF/HLS tree and referenced playlists/init/fragments return
   nonempty 200 responses. The actual Chromium HLS player advances at least
   two seconds while decoded video frames and decoded audio bytes increase;
   it remains unmuted/error-free, then seeks to seven seconds. Screenshots and
   numeric before/after samples are saved. Browser autoplay is enabled for
   media-API measurement; this does not certify Play-button UX or speaker output.
6. That same uploaded UUID appears in a delivered `video.upsert` and matching
   search inbox event, an eligible search document, and the signed internal
   vidra-search response. Anonymous browser search renders the title/link and
   opens it; a **new** `search.submitted` event must report **source=search**.
   The unchanged UI's successful vidra-search request counter must also increase.
   A separate browser fetch obtains the routed event because the shipped UI owns
   its query telemetry and suppresses that duplicate event. A SQL fallback, old
   event, seeded document or mocked response cannot pass.

This closes SRC-01 and A02's installer procedure. It supplies measured parts of
the broader INS/AUTH/PUB/PLAY workflows and A03–A09. Ordinary-user/approval/claim-race cases, playback
fallback/ABR/native/mobile controls, privacy/deletion/search outages, other user
and admin controls, recovery, scale and migration remain separate requirements.
The remaining cases are tracked in the current disposition. All historical
passes keep their original revision/fixture boundaries.

## Provision the host

Allocate a new **Ubuntu 24.04 LTS AMD64** cloud image or native AMD64 hypervisor
VM, **4 vCPUs, 16 GiB RAM, 80 GiB disk** (at least 30 GiB free at start). Use an
ordinary Ubuntu image with SSH, Python 3 and systemd; do not preinstall Docker,
containerd, Vidra, or application data. Save the provider instance/image ID,
creation time and architecture beside the evidence. Do not use a production
address, mounted production disk, shared database, bucket or retained lab.

Allow inbound SSH only from the operator. Keep inbound 80/443 closed at the
provider firewall: Caddy is reached by the browser running **inside this host**
using a test hostname. Outbound DNS and HTTPS/HTTP must reach Ubuntu/Docker
package mirrors, GitHub/raw GitHub/releases, GHCR and Docker Hub image layers,
the ClamAV signature CDN, npm and Playwright's browser CDN. The published Vidra
artifacts are public; no provider bucket, SMTP, IdP, CDN or source credentials
are required for this local-storage milestone. Failure to fetch scanner
signatures must be diagnosed, not worked around by disabling scanning.

Configure an SSH alias `vidra-acceptance` with the newly allocated address,
login user (normally `ubuntu`), and its test key. Verify its host-key fingerprint
against the provisioning record. For the retained run the destination is `root@159.65.249.255` with the
operator's existing configured SSH identity. That host is now populated; a new
blank-run attempt requires another authorized clean host or OS rebuild. Test access without installing anything:

```bash
ssh -o BatchMode=yes -o ConnectTimeout=10 vidra-acceptance \
  'uname -sm; cat /etc/os-release; sudo -n true'
```

## Prepare, transfer and run

On the operator workstation use Python >=3.9, Git, curl and tar; regenerating
the release preflight additionally needs Node >=24, npm and Docker buildx.
From this meta checkout, reuse the retained exact preflight output. If it no
longer exists, run `deploy/release-preflight.py --tag v0.6.4 --platform linux/amd64`
with a **new** `--out` directory first, and substitute that directory below.
Preparation still compares every source SHA and asset hash against #185's
manifest; a newly resolved tag cannot silently become the candidate.

```bash
# All workstation preparation writes go into new private temporary directories.
umask 077
mkdir /tmp/vidra-v064-test-tools
curl -fsSL https://nodejs.org/dist/v26.8.1/SHASUMS256.txt \
  -o /tmp/vidra-v064-test-tools/SHASUMS256.txt
curl -fsSL https://nodejs.org/dist/v26.8.1/node-v26.8.1-linux-x64.tar.xz \
  -o /tmp/vidra-v064-test-tools/node-v26.8.1-linux-x64.tar.xz
python3 tests/release_acceptance.py prepare \
  --frozen /tmp/vidra-release-verification-20260910/v0.6.4/preflight \
  --node-archive /tmp/vidra-v064-test-tools/node-v26.8.1-linux-x64.tar.xz \
  --node-sums /tmp/vidra-v064-test-tools/SHASUMS256.txt \
  --out /tmp/vidra-v064-runtime-handoff
tar -C /tmp/vidra-v064-runtime-handoff -czf /tmp/vidra-v064-runtime-handoff.tar.gz .
shasum -a 256 /tmp/vidra-v064-runtime-handoff.tar.gz
scp /tmp/vidra-v064-runtime-handoff.tar.gz vidra-acceptance:/tmp/
ssh vidra-acceptance 'sha256sum /tmp/vidra-v064-runtime-handoff.tar.gz'
```

Compare the local and remote archive hashes before continuing. `handoff.json`
also hashes every input, including the installer, helper scripts, source-ledger
inventory, minimal Playwright lockfile and checksum-verified Node archive.
Its printed hash is a second transfer check. Playwright **1.63.0** and its two
dependencies come directly from the frozen frontend lockfile, retaining npm
integrities; application source is never built by this harness.

```bash
ssh vidra-acceptance 'sudo -n mkdir -m 700 /root/vidra-v064-runtime &&
  sudo -n tar -xzf /tmp/vidra-v064-runtime-handoff.tar.gz -C /root/vidra-v064-runtime &&
  sudo -n python3 /root/vidra-v064-runtime/release_acceptance.py check-host'

# A transient guest service survives SSH disconnects. Expect image/signature/
# browser downloads plus real transcoding; systemd-run returns before completion.
ssh vidra-acceptance 'sudo -n systemd-run --unit=vidra-v064-acceptance \
  /usr/bin/env -i PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
  LANG=C.UTF-8 /usr/bin/python3 /root/vidra-v064-runtime/release_acceptance.py run \
  /root/vidra-v064-runtime --acknowledge fresh-disposable-host'
ssh vidra-acceptance 'sudo -n journalctl -u vidra-v064-acceptance --no-pager -n 30'
ssh vidra-acceptance 'sudo -n systemctl show vidra-v064-acceptance -p ActiveState -p ExecMainStatus'
```

The acknowledgement authorizes installation only on the new host just checked.
The runner rejects reused output and existing runtime/install data before
installer mutation. A failure is preserved, not reset or turned into PASS.
It never stops, deletes or clears data automatically. Use another fresh host
for a complete rerun; retain a failed host for diagnosis until explicit cleanup.

## Read and retain the actual evidence

```bash
ssh vidra-acceptance 'sudo -n cat /root/vidra-v064-runtime/result.json'
ssh vidra-acceptance 'sudo -n cat /root/vidra-v064-runtime/browser-result.json'
# After PASS, export only the reviewed evidence allowlist. Raw logs and generated
# credentials/configuration stay on the host. The helper refuses existing output.
scp tests/release_acceptance_export.py vidra-acceptance:/tmp/vidra-export.py
ssh vidra-acceptance 'sudo -n python3 /tmp/vidra-export.py'
scp vidra-acceptance:/root/vidra-v064-reviewed-evidence.tar.gz /tmp/
shasum -a 256 /tmp/vidra-v064-reviewed-evidence.tar.gz
```

`result.json` reports each completed phase, loaded images and both ledgers;
`browser-result.json` records exact commands, same-video IDs, job observations,
HLS asset requests, playback samples, search events and screenshot hashes.
`private/commands.jsonl` records host argv, cwd, start/end times, exit codes and
the corresponding log file, including all A02 installer invocations. Frozen
deploy output and container events establish sequencing. Raw logs can contain
owner-claim tokens, generated setup secrets, or browser diagnostics; the owner
password is only in `private/owner.json`. The
[export helper](../tests/release_acceptance_export.py) hashes raw logs, removes
health-command output, includes only named evidence files and checks text
against generated secrets on the host before export. Compare the printed archive
hash with the downloaded file. Automatic approval review rejected the broad raw
archive in this session because it could contain generated secrets; the limited
export passed. Raw evidence remains at `root@159.65.249.255:/root/vidra-v064-runtime`.
Review the four actual screenshots:
`owner-claimed.png`, `upload-published.png`, `playback-advancing.png`, and
`search-result.png`. Do not substitute images from an earlier rehearsal.

If failure indicates an application defect, preserve the original digest, phase,
request/job/event IDs and logs, reproduce it, then prepare a focused component
fix with relevant tests. A subsequent modified build needs its own source/image
manifest and separately labelled results. Never edit this frozen manifest or
replace the release images to make this published-v0.6.4 certification pass.

B2 representative-source, B3 selected-provider, B4 recovery-destination/objective
and B5 scope-decision requirements remain as recorded. They block their own
dependent checks, not this milestone. U1's CI/skipped-test/revision limitations
remain. No merge, release publication, production deployment or shared-lab
mutation is authorized by this handoff.
