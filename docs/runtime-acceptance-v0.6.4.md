# v0.6.4 first runtime milestone — executable handoff

**Runtime BLOCKED; handoff prepared, not executed on the target.** This continues
[PR #185](https://github.com/yegamble/vidra/pull/185) and its
[frozen verification](release-verification-v0.6.4-2026-09-10.md).
One agent prepared this on September 10, 2026. No release image was executed,
owner claimed, video uploaded, or shared lab changed in this continuation.
[Preparation evidence](evidence/release-v0.6.4-verification/runtime-preparation.json)
separates local checks from the missing deployed observations.

The precise missing access is an **authorized new Ubuntu 24.04 AMD64 VM/host's
SSH destination, login user and working locally configured SSH identity with
passwordless sudo**. This workstation is Darwin ARM64 and its Docker Engine is
Linux aarch64. The configured SSH file supplies no acceptance host; the listed
Multipass machines are existing labs/rehearsals. No existing machine is accepted
as a blank installation, and no emulation is used to meet this target.

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
   Test Node/Playwright tooling is installed only after application installation.
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
5. The same video's durable transcode job completes with a real attempt. Its
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
   A SQL fallback, old event, seeded document or mocked response cannot pass.

This is a bounded milestone across INS/AUTH/PUB/PLAY/SRC, **not full closure of
those workflow rows or A02–A09**. Ordinary-user/approval/claim-race cases, playback
fallback/ABR/native/mobile controls, privacy/deletion/search outages, other user
and admin controls, recovery, scale and migration remain separate requirements.
No current count in the 59-workflow/40-item verification is promoted by preparing
a script. All historical passes keep their original revision/fixture boundaries.

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
against the provisioning record. These are the missing values; no placeholder
is a usable host. Test access without installing anything:

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
# Export the whole run privately, preserving diagnostics for failures too.
ssh vidra-acceptance 'sudo -n tar -C /root -czf - vidra-v064-runtime' \
  > /tmp/vidra-v064-runtime-private-results.tar.gz
```

`result.json` reports each completed phase, loaded images and both ledgers;
`browser-result.json` records exact commands, same-video IDs, job observations,
HLS asset requests, playback samples, search events and screenshot hashes.
`private/commands.jsonl` records host argv, cwd, start/end times, exit codes and
the corresponding log file, including all A02 installer invocations. Frozen
deploy output and container events establish sequencing. Raw logs can contain
owner-claim tokens, generated setup secrets, or browser diagnostics; the owner
password is only in `private/owner.json`. Keep the export private and review it
before committing sanitized observations. Review the four actual screenshots:
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
