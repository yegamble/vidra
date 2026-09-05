# Deploying Vidra (dev-remote / QA / staging / production)

Canonical environment matrix: [`.ralph/specs/environments.md`](../.ralph/specs/environments.md).
This directory holds the reference single-host deployment: the meta-repo compose
stack plus a production overlay, behind Caddy for TLS.

| File | What |
|---|---|
| [`../docker-compose.prod.yml`](../docker-compose.prod.yml) | Production overlay: loopback binds, GHCR images, restart policies, log caps, resource limits, named volumes, Caddy. |
| [`Caddyfile`](./Caddyfile) | **Template.** Single-origin TLS reverse proxy (path routing to api/frontend). `vidra setup` renders it to `deploy/Caddyfile.local` — the real domain and ACME settings go there, at the `# vidra:global-options` / `# vidra:tls` markers. |
| `Caddyfile.local` | **Generated, gitignored, and the only file mounted into the caddy container.** Must exist before `up -d`: a missing bind-mount source is created by Docker as a directory and Caddy crash-loops on it. `deploy.sh`, `rollback.sh` and `restore.sh` all refuse to start without it — except under `VIDRA_TLS_MODE=external`, where there is no caddy service to mount it into. |
| [`lib.sh`](./lib.sh) | **Sourced, not run.** The one copy of `env_get`, `is_true` and the compose-chain assembly. Every script below builds the SAME `-f` chain and `--profile` set from the env file through it. |
| [`compose.sh`](./compose.sh) | `docker compose` against that chain: `./deploy/compose.sh ps \| logs -f \| config -q \| down`. Gates nothing — use it to read and to stop, `deploy.sh` to change. |
| [`deploy.sh`](./deploy.sh) | pin checkouts → dump → pull → gated migrations → up → Caddy reload → probe (api, frontend **and the edge**). Mode-aware: `VIDRA_TLS_MODE` decides which of those still apply, and every skip is printed. |
| [`make-bundle.sh`](./make-bundle.sh) | **Release-time, not host-time.** Assembles `vidra-bundle_<tag>.tar.gz`: this deployment tree plus the six files a deploy needs out of vidra-core, at the same relative paths a checkout has them. Deterministic; `install.sh` unpacks it instead of cloning. |
| [`rollback.sh`](./rollback.sh) | Rewrite the image tags, pull, restart, re-probe. |
| [`backup.sh`](./backup.sh) | `pg_dump -Fc` → gzip → **config archive** → optional off-site → retention → success marker. |
| [`restore.sh`](./restore.sh) | **Destructive.** Drop, recreate, `pg_restore -j4`, migrate, re-probe. |
| [`provision.sh`](./provision.sh) | Host prep, idempotent, as root: swap, service user, `/opt/vidra`, log cap, unattended-upgrades, backup timer (installed **and verified**). Warns about sshd and the firewall; edits neither. |
| [`cloud-init.yaml.example`](./cloud-init.yaml.example) | The same, as provider user-data, for a host that does not exist yet. Pure ASCII on purpose. |
| [`vidra-backup.service`](./vidra-backup.service) / [`.timer`](./vidra-backup.timer) | systemd units for the nightly backup. `provision.sh` installs them. |

**The `vidra` CLI wraps these 1:1.** `vidra deploy | rollback | backup | restore |
release` exec the script of the same name with `ENV_FILE` injected and your terminal
attached, and return its exit code unchanged — same gates, same refusals, no second
copy of any of them; `vidra logs` / `restart <service>` / `status` go through
`compose.sh`. [`../install.sh`](../install.sh) installs it from vidra-core's release
assets (checksum verified); `make build-vidra` in `vidra-core` still builds one for a
release cut before those assets existed. **The scripts below remain the source of
truth** — every rule documented here is enforced in them, not in the CLI.

---

## First boot — do these in order

**The first admin is claimed, not registered.** This used to be a race: the api
granted the admin role to whichever account was created while the `users` table
was empty, on every signup path, so a signup bot that beat you to the first
registration owned your instance. It does not work that way any more
(`vidra-core/internal/auth/ownerclaim.go`). While the instance is unclaimed —
empty `users` table plus an unredeemed token — **every** signup path answers
`403 owner_claim_required`, and the only way in is a one-time token the api
mints at boot and prints to its own log.

1. **Bring the stack up** and confirm `/readyz` is 200 — see
   [First bring-up](#first-bring-up) below. `vidra setup` prints these same two
   steps at the end of its run, for the same reason they are here: generating an
   env file otherwise leaves you two commands away from an instance nobody can
   log into.
2. **Read the token out of the api log:**
   ```bash
   ./deploy/compose.sh logs api | grep 'FIRST-RUN SETUP REQUIRED'
   ```
   Use `compose.sh`, never a bare `docker compose logs api` — on a deployment
   host the bare form auto-loads `docker-compose.override.yml` and addresses a
   different project than the deploy scripts do. **Take the newest line.** Every
   api restart mints a fresh token and *invalidates* the previous one, which is
   what turns a token copied ten minutes and one deploy ago into a confusing
   `owner_claim_invalid`.
3. **Redeem it**, at `https://<your domain>/setup/claim` in the UI, or directly:
   ```bash
   curl -X POST https://example.com/api/v1/setup/claim-owner \
     -H 'Content-Type: application/json' \
     -d '{"token":"<the token>","username":"...","email":"...","password":"..."}'
   ```
   Only the token's **hash** is stored, so a lost token is re-minted (restart the
   api), never recovered.
4. **Verify you actually got admin** before you trust it:
   `GET /api/v1/admin/system` with your access token must return 200 (a
   non-admin gets 403), and `/admin` in the UI must render.
5. **Decide your registration policy.** `REGISTRATION_ENABLED=false` is still the
   right default for a private launch, but it is now a *policy* choice, not the
   thing standing between a bot and your admin account — set it to `true`
   (optionally with `REGISTRATION_REQUIRE_APPROVAL=true`, which files signups
   into the admin approval queue instead of creating accounts) and `up -d` again
   when you want the doors open.
6. **Announce the domain.**

> An instance that already has users and no outstanding token is *implicitly
> claimed* and never mints one — upgrading an existing install does not suddenly
> print a bootstrap credential. The inverse also holds and is deliberate: if
> users exist but the owner was never claimed, the api re-mints on **every**
> boot, so an unclaimed token sitting in an old log can never stay a live admin
> credential.
>
> `OWNER_CLAIM_TOKEN` pins the mint to a fixed value for test harnesses.
> `config.validate()` **refuses it in production**; it is not an operator knob.

---

## Four things a real deploy hit (2026-08-23)

All four are silent-failure-shaped, which is why they are here rather than in a
commit message.

### `env/production.env` is docker-compose format, NOT shell — never `source` it

`vidra setup` generates `VIDRA_COMPOSE_PROFILES=core frontend`: unquoted, with a
space. Compose's `--env-file` parser reads that as the literal string
`core frontend`, which is correct. A shell that `source`s the same file sets
`VIDRA_COMPOSE_PROFILES=core` and then tries to **execute `frontend`**.

Writing deploy automation that sources this file is the natural thing to do and
it is wrong. Parse it as `KEY=VALUE` with the value taken literally, or hand it
to `docker compose --env-file` / `docker run --env-file`, which already do. The
same applies to any value with a space — a multi-word `INSTANCE_NAME` behaves the
same way.

Worse, the failure is quiet: a `set -e` script that pipes its output to `tail`
reports the pipeline's exit status, so a run that died on line 1 exits 0 and looks
like a run that found nothing to do. Capture to a file and check the status
separately.

### `git` in `/opt/vidra` must run as the `vidra` user, not as root

`install.sh` clones as root; `provision.sh` then creates the service user and
chowns the tree to it. After that, `git` as root refuses with *"detected dubious
ownership in repository at '/opt/vidra'"* and does nothing.

That refusal is safe on its own. What is not safe is mixing it with file-level
edits, because those still succeed:

```bash
# WRONG — the sed lands, the checkout does not, and nothing says so
sed -i 's/^VIDRA_CORE_TAG=.*/VIDRA_CORE_TAG=v0.3.0/' env/production.env
git checkout v0.3.0            # fatal: dubious ownership

# RIGHT
sudo -u vidra git -C /opt/vidra fetch --tags origin
sudo -u vidra git -C /opt/vidra checkout v0.3.0
```

The first form leaves the env file naming a release the tree is not on. `vidra
deploy` will happily pull those images and run them against the previous
revision's compose files.

### Nothing publishes a Postgres port, so host tooling cannot use `postgres:5432`

The prod overlay's loopback discipline means Postgres, Redis and search publish
**nothing at all** — that is the point (see *Firewall* below). The service name
`postgres` only resolves inside the compose network, so a tool run on the host
with a `DATABASE_URL` copied from the env file cannot connect, and the error is a
DNS failure rather than anything about ports.

Either run the tool inside the network:

```bash
docker run --rm --network vidra_default --env-file env/production.env <image> …
```

or resolve the container address and repoint the DSN at it:

```bash
docker inspect vidra-postgres-1 \
  --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}'
```

Prefer the first: it uses the same env parsing as the stack, and the address is
not stable across recreates.

### `peertube-import` is not shipped anywhere

`Dockerfile` builds only `./cmd/api`, and the release assets carry only the
`vidra` CLI. An operator migrating from PeerTube therefore has no supported way
to run the importer — it has to be built from the source tree with a Go
toolchain and copied to the host:

```bash
cd vidra-core
GOOS=linux GOARCH=amd64 CGO_ENABLED=0 go build -o peertube-import ./cmd/peertube-import
scp peertube-import root@<host>:/opt/vidra/
```

See [vidra-core's migration notes](../vidra-core/docs/operations.md) for what the
importer does and does not carry across.

## Host prerequisites

`ufw`, `unattended-upgrades` and SSH hardening are not mentioned anywhere else in
this repo, and one of the items below (the DOCKER-USER warning) is the reason a
host firewall will *not* save you.

### The short version: `deploy/provision.sh`

Everything in this section except Docker itself is applied by one idempotent
script:

```bash
sudo ./deploy/provision.sh          # asks once, then applies
sudo ./deploy/provision.sh --yes    # no prompt (cloud-init, CI, re-runs)
```

It does the swapfile **and** its `/etc/fstab` line, the `vidra` service user in
the `docker` group, `/opt/vidra` with the right owner, the daemon log cap,
`unattended-upgrades`, and the backup timer — which it then *verifies* with
`systemctl is-enabled`/`is-active` and prints the next elapse for. Re-run it
after enabling a compose profile and it re-prints the firewall requirements for
the profiles you actually have on.

It **never** edits sshd and it opens **no** ports; both are checked and
reported. It **never** overwrites an `/etc/docker/daemon.json` that says
something else — it prints the keys to merge. Those refusals are the point: the
first two are how a host gets locked out or silently left open, and the third is
a much bigger outage than uncapped logs.

For a host you have not created yet, [`cloud-init.yaml.example`](./cloud-init.yaml.example)
is the same thing as provider user-data: paste it into the "user data" box, edit
the SSH key, and the server comes up already provisioned. It is deliberately
pure ASCII (DigitalOcean rejects non-ASCII user-data, silently) and meta-ci
asserts that it stays that way.

**The manual steps below remain the source of truth** and are worth reading
before you run the script — they say *why*, and the script only says *what*.
Follow them by hand on a non-apt host, which `provision.sh` refuses rather than
half-provisions.

### Docker

- **Docker Engine ≥ 24** and **Compose ≥ 2.24**.
  - The ≥ 2.20 floor comes from `docker-compose.yml:23`, which uses the
    top-level **`include:`** key to pull in `vidra-core/docker-compose.yml`. An
    older Compose fails with a cryptic "unsupported field" parse error and no
    hint that the version is the problem.
  - The floor is **2.24**, not 2.20, because `docker-compose.prod.yml` uses the
    **`!reset` / `!override` merge tags**. Compose *merges* sequence fields
    across a `-f` chain, so a plain `ports: []` in the overlay appends nothing
    and the base file's `0.0.0.0:5432` publish survives. `!reset` is what
    actually closes the port. On an older Compose the tags are ignored and
    **Postgres, Redis and the search service stay exposed to the internet** —
    verify with the `nmap` check below rather than trusting the version string.
  - `deploy/deploy.sh`, `deploy/rollback.sh` and `deploy/restore.sh` each parse
    `docker compose version --short` and **refuse to run** below 2.24, because
    that failure mode is silent: nothing errors, the deploy reports success, and
    the database is on the public internet.
- `sudo systemctl enable --now docker` — `restart: unless-stopped` does nothing
  if the daemon itself does not start at boot.
- Cap the daemon's logs. The default `json-file` driver is **unbounded**, and the
  api emits a structured JSON line per request onto the same disk as Postgres
  and the media volume:
  ```bash
  cat >/etc/docker/daemon.json <<'EOF'
  {"log-driver":"json-file","log-opts":{"max-size":"10m","max-file":"5"}}
  EOF
  systemctl restart docker
  ```
  (`docker-compose.prod.yml` also sets a per-service cap; the daemon default is
  the backstop for anything started outside the compose stack.)

### Firewall

- **Use a DigitalOcean Cloud Firewall.** It sits outside the droplet, in DO's
  network, and is the only control Docker cannot bypass. Allow inbound TCP
  **22** (from your admin IP only), **80** and **443** (`0.0.0.0/0, ::/0` — port
  80 is required for the ACME HTTP-01 challenge). Deny everything else; leave
  outbound open.
- **Two more ports, but only with the profiles that need them.** The prod
  overlay resets every other publish to nothing, and deliberately does *not*
  reset these two, because remote peers dial them directly and a reverse proxy
  cannot stand in front of either:

  | Port | Open it when | Why it cannot be loopback |
  |---|---|---|
  | **1935/tcp** | `VIDRA_COMPOSE_PROFILES` contains `media` | RTMP ingest. OBS on a creator's laptop connects to it from the internet. |
  | **4001/tcp+udp** | …contains `ipfs` | libp2p swarm. Peers dial in; a node nobody can reach only ever pushes. |

  Both stay **closed** on an instance that has not enabled those profiles, which
  is the default. `deploy/provision.sh` reads the profiles out of your env file
  and prints exactly the list your firewall needs, so re-run it after changing
  them rather than working it out again. meta-ci renders the overlay with
  *every* optional profile enabled and fails if anything other than caddy 80/443,
  rtmp 1935 and ipfs 4001 faces the network — that allow-list is the contract,
  and a new service wanting a host port has to argue for it there first.
- **A host `ufw` does NOT filter Docker-published ports.** Docker installs its
  own `DOCKER-USER` iptables chain and it is traversed *before* ufw's rules, so
  `ufw deny 5432` has no effect on a container publishing 5432. Running ufw as
  defence-in-depth for non-Docker services is fine, but do not believe it is
  protecting the stack.
- **The real control is the loopback binds in `docker-compose.prod.yml`.**
  Postgres, Redis and search publish nothing at all; api and frontend publish on
  `127.0.0.1` only. Verify from **another host** after bring-up:
  ```bash
  nmap -Pn -p 22,80,443,3000,5432,6379,8080,8081 <droplet-ip>
  ```
  Only 22/80/443 may be open. If 5432 or 6379 answer, the prod overlay is not
  being applied (wrong `-f` chain, or a Compose older than 2.24).

### OS

- `unattended-upgrades` for security patches:
  `apt-get install -y unattended-upgrades && dpkg-reconfigure -plow unattended-upgrades`.
- SSH key-only: in `/etc/ssh/sshd_config` set `PasswordAuthentication no` and
  `PermitRootLogin no`, then `systemctl restart ssh`. Confirm you can still log
  in **from a second terminal** before closing the first.
- A **4 GB swapfile**. It is the difference between a slow transcode and an
  OOM-killed Postgres:
  ```bash
  fallocate -l 4G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
  ```
- Create an unprivileged deploy user in the `docker` group (`adduser
  --disabled-password vidra && usermod -aG docker vidra`) and clone to
  `/opt/vidra`. Note that membership in `docker` is equivalent to root on the
  host — that is inherent to Docker, not to this setup.

### Sizing

ffmpeg runs **inside the api container** (`vidra-core/Dockerfile:39` installs it
there), so the droplet is sized for transcoding, not for web serving. One
`TargetAll` job on a 1080p source is **12 full-source encode passes**: four HLS
ladder rungs, four trick-play I-frame encodes and four progressive web videos.
Expect roughly 1.5–2.5× source duration of wall clock on 4 vCPU at
`-preset veryfast`.

| Launch profile | Droplet | Why |
|---|---|---|
| Small / private (<50 users, occasional uploads) | **Premium AMD 4 vCPU / 8 GB / 160 GB — ~$63/mo** | The floor. Set `API_CPUS=3.0`, `API_MEM_LIMIT=4g`, `POSTGRES_SHARED_BUFFERS=512MB`, `POSTGRES_EFFECTIVE_CACHE_SIZE=3GB` — the overlay's defaults target the 16 GB box, and **Docker refuses to start a container whose `cpus` exceeds the host core count**. |
| Public launch | **Premium Intel 8 vCPU / 16 GB / 160 GB — ~$168/mo** | The overlay's defaults (`API_CPUS=7.0`, `API_MEM_LIMIT=6g`): transcoding takes seven cores and still leaves one for the API and Postgres. Roughly halves upload-to-playable time. |
| + ClamAV (`MALWARE_SCAN_ENABLED=true`) | **add 2 GB RAM** | `clamd` loads the full signature database into memory: ~1.5–2 GiB resident, and it OOM-kills on a small host. |

**Do not use a 2 GB droplet.** Even though production *pulls* images (so
`next build` never runs on the box), Postgres + api + frontend + search + Caddy +
one transcode needs ~4 GB before ClamAV.

Runtime levers that need no restart (admin UI → instance settings): set
`transcoding_threads` to vCPU−1 and keep `transcoding_concurrency` at 1. Raising
concurrency multiplies both CPU **and** scratch disk.

**Splitting the transcoders off the API.** `API_CPUS` sizes one container that
both serves HTTP and runs ffmpeg, which is why it is so large. Setting
`EXTRA_COMPOSE_PROFILES=worker` and `API_ROLE=api` in the env file moves every
background worker — ffmpeg included — into separate `worker` containers running
the same image, so `API_CPUS`/`API_MEM_LIMIT` can shrink to a web-serving
envelope and `WORKER_CPUS`/`WORKER_MEM_LIMIT` take the transcoding budget
(`--scale worker=N` for more). The two still have to fit the host together, and
**`API_ROLE=api` with no worker container running means nothing transcodes,
imports or sweeps at all** — there is no interlock. Optional; the single-container
topology remains the default and the supported one. See
[vidra-core operations](../vidra-core/docs/operations.md#splitting-the-api-and-the-workers).

### Storage

- **Media → DO Spaces.** `STORAGE_S3_ENDPOINT=nyc3.digitaloceanspaces.com` —
  host only, **no scheme**; a `://` is rejected at `internal/storage/s3.go:74-76`.
  Also set `STORAGE_S3_REGION=nyc3`. `USE_SSL=true` / `FORCE_PATH_STYLE=false`
  are already the right compose defaults. Pre-create the bucket.
- **Transcode scratch → a Block Storage volume**, mounted at the host path
  backing the `transcode_tmp` named volume. The overlay sets `TMPDIR=/scratch`,
  which redirects all nine `MkdirTemp`/`CreateTemp` sites at once — including a
  full uncompressed PCM wav for Whisper and a full second encode for VP9. Budget
  **~4 × `UPLOAD_MAX_SIZE` × `transcoding_concurrency`**; with the default
  `UPLOAD_MAX_SIZE=2G` that is ~8 GB per concurrent job. Without a separate
  volume this lands under `/var/lib/docker` on the same root disk as Postgres.
- **Backups → a second Spaces bucket in a different region** (`fra1` if media is
  in `nyc3`). A dump that only exists on the droplet dies with the droplet.
- **`STORAGE_BACKEND=local` needs the `media_data` volume** from the prod
  overlay. Without it the default root resolves to `/app/data/media` on the
  container writable layer, and `up -d` destroys the media while the Postgres
  rows survive pointing at nothing.

### Managed Postgres — not at launch

`internal/store/store.go:53` hardcodes `MaxConns=10` *after* `ParseConfig`,
silently discarding `pool_max_conns` from the DSN. Core 10 + search 10 + a 4-conn
import pool = 24 connections, above the smallest DO Managed plan's cap. Run the
bundled Postgres 18 with the nightly dump to Spaces; migrate to Managed once a
`DATABASE_MAX_CONNS` knob exists. The DSN indirection is already in place —
setting `DATABASE_URL` (with `sslmode=require`) in the env file overrides the
constructed compose default for core, search **and both migration one-shots**.
It is a single variable: the search migrator carries its `vidra_search_migrations`
ledger name (and the `public` schema it lives in) in the binary, so it no longer
needs the separate `SEARCH_MIGRATE_DATABASE_URL` that existed only to append
`&x-migrations-table=…`.

**That tolerance is the *search* migrator's alone.** `vidra-search`'s
`internal/dbmigrate` normalizes a DSN that still carries
`x-migrations-table=vidra_search_migrations` (it strips it) and *refuses* one
naming a different table or moving the schema (`search_path`, `options`).
`vidra-core`'s migrator does neither: it hands the DSN to golang-migrate
verbatim, and that driver reads `x-migrations-table` itself — so a
`DATABASE_URL` carrying the search ledger name would make **core** write its
version counter into `vidra_search_migrations`. Keep the shared `DATABASE_URL`
free of migrator parameters.

---

## First bring-up

### One-command install

```bash
curl -fsSL https://raw.githubusercontent.com/yegamble/vidra/main/install.sh | sh
```

[`../install.sh`](../install.sh) does everything down to `vidra setup`: detects the
platform (Linux amd64/arm64; on macOS it prints the dev quick start and stops),
installs `curl`, Docker Engine and the Compose v2 plugin from **Docker's own apt
repository** when they are missing, resolves vidra-core's latest release,
downloads that release's `vidra-bundle_<tag>.tar.gz`, verifies it against the
release's `SHA256SUMS` and unpacks it into `/opt/vidra`, then downloads
`vidra_<tag>_linux_<arch>` the same way — **refusing to install either on a
checksum mismatch** — and hands the terminal to `vidra setup`.

**No git.** The bundle is a complete deployment tree: the compose files, the
`deploy/` scripts, the env templates, and `vidra-core/docker-compose.yml` plus
the files it bind-mounts, at exactly the paths a checkout would have them. Its
root carries `vidra-bundle.manifest`, which is how `deploy.sh` and `rollback.sh`
recognise the tree (they skip the component-checkout sync, which has nothing to
sync, and read the expected schema version from the manifest instead of from a
`migrations/` directory the bundle deliberately does not ship).

**The clone path is still there**, and is reached two ways: `--git`, and a
release that carries no bundle asset — every release cut before the bundle
existed, which must keep installing. Both say so. That path is the old one
exactly: clone this repo, run `./bootstrap.sh` with `VIDRA_REF` set so all three
component checkouts are pinned to the release. Take it deliberately if you want
history, local patches, or to follow `main`; `git` is installed only if that path
is actually taken.

Everything it would change is behind **one** confirmation, read from `/dev/tty`
because under `curl … | sh` stdin is the script. `--yes` skips it and is *required*
where there is no terminal at all (cron, a Docker build, `</dev/null`) — an
installer that silently installs Docker onto an unattended host is the wrong
default. Other flags: `--ref vX.Y.Z` to pin a release, `--dir` (default
`/opt/vidra`), `--owner` for a fork, `--git` for a checkout; `VIDRA_YES` /
`VIDRA_REF` / `VIDRA_HOME` / `VIDRA_GH_OWNER` / `VIDRA_INSTALL_GIT` are the
environment equivalents, and `sh install.sh --help` prints the lot.

It is **safe to re-run**, and that is the design: it reports what it found and
skipped, leaves an already-unpacked bundle tree exactly as it is (it is never
re-extracted over — your `env/production.env`, your `Caddyfile.local` and your
edits are not in the tarball to be restored), fast-forwards a checkout only while
it is clean (a dirty tree is left alone and warned about, never reset), leaves
`/usr/local/bin/vidra` alone when it is already the same bytes, and **never**
writes or overwrites `env/production.env` —
`vidra setup` owns that file, refuses to rewrite an existing one without `--yes`, and
the installer never passes `--yes` to it. Re-running an installer must not re-mint
the KEKs that seal data already in the database. If it stops early — a release with
no CLI assets (v0.2.0 and older predate them; it names `make build-vidra` as the
fallback), a checksum mismatch, no terminal for the interview — whatever it created
stays where it is and the next run continues from there.

What it deliberately leaves to you: it starts **no containers** (`vidra deploy`
does that, with the pre-deploy dump and the health gates), opens **no ports**, and
does not run [`provision.sh`](./provision.sh) — swap, the service user and the
backup timer are a separate, root-only decision.

### By hand

Advanced users can do exactly the same thing manually, and this is what the
installer automates:

```bash
git clone https://github.com/yegamble/vidra.git /opt/vidra && cd /opt/vidra
./bootstrap.sh                          # clones the three component repos
cp env/production.env.example env/production.env
$EDITOR env/production.env              # JWT_SECRET, POSTGRES_PASSWORD, REDIS_PASSWORD,
                                        # MFA_KEY_KEK, SEARCH_INTERNAL_SECRET, SMTP_*,
                                        # STORAGE_S3_*, INSTANCE_NAME, PUBLIC_BASE_URL,
                                        # VIDRA_*_TAG=v0.2.0, REGISTRATION_ENABLED=false
git check-ignore -v env/production.env  # MUST match, or stop and fix .gitignore
vidra setup --template env/production.env.example --yes
                                        # renders deploy/Caddyfile.local from the
                                        # template + PUBLIC_BASE_URL/VIDRA_TLS_MODE.
                                        # --template is required (it is the input
                                        # format); --yes only because the cp above
                                        # already created the output file, and every
                                        # value that file sets is still preserved.
                                        # Skip the cp/$EDITOR and let the interview
                                        # write it instead, and neither is needed.
                                        # By hand instead:
                                        #   cp deploy/Caddyfile deploy/Caddyfile.local
                                        #   $EDITOR deploy/Caddyfile.local   # your domain
                                        # deploy.sh refuses while Caddyfile.local is
                                        # missing, still says example.com, or serves a
                                        # different host than PUBLIC_BASE_URL. It also
                                        # refuses an ACME deploy whose domain does not
                                        # yet resolve to this host (Let's Encrypt rate
                                        # limits); VIDRA_SKIP_DNS_PREFLIGHT=1 overrides.

./deploy/compose.sh config -q           # render check — catches missing required vars
./deploy/compose.sh pull
./deploy/compose.sh run --rm migrate && ./deploy/compose.sh run --rm search-migrate
./deploy/compose.sh up -d --no-build

curl -fsS http://127.0.0.1:8080/readyz  # {"status":"ok"} incl. postgres + redis
curl -fsS https://example.com/          # Caddy + certificate + frontend
nmap -Pn -p 5432,6379,8080,3000 <droplet-ip>   # must all be closed
```

**Never hand-spell the `docker compose -f … --profile …` chain.** `deploy/compose.sh`
is a thin wrapper that reads the SHAPE of the stack — which overlays, which
profiles — out of `env/production.env`, exactly as `deploy.sh`, `rollback.sh`,
`restore.sh` and `backup.sh` do (they all share `deploy/lib.sh`). A typed-out
chain is a copy that drifts: an operator on managed Postgres who types the plain
two-file chain gets a render containing the **bundled** postgres, so `config -q`
goes green for a stack that is not the one running and `up -d` starts a second,
empty database next to the managed one. Use `ENV_FILE=env/staging.env
./deploy/compose.sh …` for another environment.

`make prod-config` is the same render check through the same wrapper;
`./deploy/deploy.sh` does the whole sequence with a pre-deploy dump, a
Compose-version floor, the migrator-tag gate, the DNS preflight, a Caddy reload
and health gates — it is what you should use for every subsequent deploy.
`compose.sh` gates **nothing**; it is for reading and for stopping.

**`POSTGRES_PASSWORD` on a host with an existing database volume:** Postgres
reads the env value only at initdb — it initializes a *fresh* volume and is
ignored afterwards. If the volume already exists, set the database's **current**
password in the env file, not a freshly generated one; rotate by running
`ALTER USER` inside the container first (see the rotation table below).

Then, before you need them:

```bash
sudo ./deploy/provision.sh --yes                     # installs AND verifies the timer
./deploy/backup.sh                                   # prove it works
RESTORE_CONFIRM=vidra ./deploy/restore.sh backups/<latest>.dump.gz   # on a SCRATCH stack
sudo reboot                                          # confirm every container returns
```

By hand instead of `provision.sh` (it does exactly this, plus the verification
step people skip):

```bash
sudo cp deploy/vidra-backup.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now vidra-backup.timer
systemctl is-enabled vidra-backup.timer && systemctl is-active vidra-backup.timer
systemctl list-timers vidra-backup.timer             # when does it next run
```

`enable --now` on a timer whose `.service` fails to parse can still exit 0, and
that failure surfaces as "no backups have ever run" — six weeks later, during a
restore. `vidra doctor` checks both the timer and the age of
`backups/last_success` for the same reason.

**Run `restore.sh` once against a real dump before launch.** The 101 down
migrations have never been executed and the restore path has never been exercised
end to end.

### Important: `vidra-core/.env` must not exist on the droplet

Compose resolves an **included** model's `${VAR}` substitutions against the `.env`
file in the *included file's own directory*. `docker-compose.yml` therefore pins
`env_file: /dev/null` on its `include:` of `vidra-core/docker-compose.yml`,
specifically so a stray `vidra-core/.env` cannot override
`--env-file env/production.env`.

That file ships as `vidra-core/.env.example` and vidra-core's own README tells
developers to `cp .env.example .env`. If it is ever loaded, it sets
`DATABASE_URL=…@localhost:5432…`, `REDIS_URL=…@localhost…`,
`POSTGRES_PASSWORD=vidra` and `JWT_SECRET=<the dev constant>` — so the api and the
migrator are handed a DSN pointing at nothing, and the real Postgres password is
ignored. Keep the droplet clean (`rm -f vidra-core/.env`) and verify after any
compose change:

```bash
./deploy/compose.sh config | grep -E 'DATABASE_URL|REDIS_URL'   # every DSN must name postgres/redis
```

### Important: the explicit `-f` chain disables `docker-compose.override.yml`

Every plain `docker compose …` in this repo implicitly merges
`docker-compose.override.yml`. An explicit `-f` chain does **not**. That is the
behaviour production wants (the override file sets `RATE_LIMIT_ENABLED=false`),
but the same file is also the **only** place the api's `SEARCH_SERVICE_URL` and
`SEARCH_INTERNAL_SECRET` are wired. In production you must set both in
`env/production.env`:

```
SEARCH_SERVICE_URL=http://search:8080
SEARCH_INTERNAL_SECRET=<openssl rand -hex 32>     # must equal the search service's INTERNAL_SECRET
```

Leave `SEARCH_SERVICE_URL` empty and the whole search integration is disabled —
the site degrades gracefully to local SQL search with **no error anywhere**, which
is exactly the kind of silence that survives to production. Setting the URL
without the secret is loud instead: `validate()` requires ≥32 characters and the
api refuses to boot.

---

## TLS topologies: who terminates, and what the deploy stops checking

`VIDRA_TLS_MODE` in `env/production.env` is not only a certificate setting — it
decides whether this host runs an edge at all, and therefore which of
`deploy.sh`'s pre-flight checks still mean anything. Three of the five modes
(`acme`, `acme-staging`, `internal`) are the managed-Caddy path documented above
and unchanged. The other two are below.

Every skip is **printed** by the deploy, with its reason. If you did not read a
skip line, the check ran.

### `external` — your proxy, LB or CDN terminates TLS

The site is on TLS; it is just not this container's TLS. `PUBLIC_BASE_URL` stays
`https://`, cookies stay `Secure`, HSTS is still emitted.

`deploy/lib.sh` withholds the `edge` compose profile in this mode, so **the
caddy service is not in the project at all** — nothing here competes for `:80`
and `:443`. Consequently `deploy.sh` skips the `deploy/Caddyfile.local` check,
the caddy reload, and the DNS preflight (the domain is *supposed* to resolve to
your proxy, not to this box), and the edge probe becomes a single attempt whose
failure is a **warning**: the deploy succeeded, and whether an operator-owned
edge two networks away answers on this host's loopback is not something a deploy
can conclude anything from.

What you own:

1. **Routing.** Forward `/api/*`, `/healthz`, `/readyz`, `/version`,
   `/sitemap.xml`, `/feeds/*`, `/nodeinfo/*` and `/.well-known/*` to the api on
   `127.0.0.1:${HTTP_PORT}` (default 8080), everything else to the frontend on
   `127.0.0.1:${FRONTEND_PORT}` (default 3000). `vidra setup` writes
   `deploy/nginx-external.conf.example` — a server block mirroring
   `deploy/Caddyfile`'s split exactly. Start from it; a hand-written proxy that
   sends `/feeds/*` to the frontend 404s every feed link and nothing errors.
2. **Headers.** `X-Forwarded-Proto: https` and `X-Forwarded-For`. Without the
   first, the api believes it is serving plain HTTP and mints `http://` links.
3. **Upload limits and timeouts.** Whatever your proxy's body-size limit is, it
   is now the upload limit. nginx's default is 1 MB.
4. **`TRUSTED_PROXY_CIDRS`** — only when the terminator has a **public** IP. The
   api already trusts loopback, private and link-local sources, so a proxy on
   this host or on the same private network needs nothing. A cloud LB or CDN
   edge does: without its CIDR listed, its `X-Forwarded-For` is ignored and every
   visitor is rate-limited as one address. List only ranges you control —
   trusting a range you do not own lets anyone in it forge the header.

`vidra doctor` is the check that still applies end-to-end; run it after the
first deploy.

### `plain-http` — deliberate no-TLS (lab, LAN, air-gap)

Caddy still runs, as a plain-HTTP site: one managed front door, all of the
Caddyfile and reload machinery, no certificate. `PUBLIC_BASE_URL` must be
`http://`, and because the api applies production validation rules whatever
`VIDRA_ENV` says, that origin is a hard refusal until you also set
**`VIDRA_ALLOW_PLAIN_HTTP=true`**. That switch is the consent, and it is what
turns off `Secure` cookies and HSTS — neither of which can work over plain HTTP.

`deploy.sh` skips `require_real_domain` and the DNS preflight (a lab origin is
legitimately an IP or an internal name, with no public A record), and probes the
edge over `http://` instead of `https://`. Everything else — the Caddyfile gate,
the reload, the migrator floor, the health probes — is unchanged.

**Every credential, cookie and upload on this deployment crosses the network in
the clear.** Use it behind a VPN, on an isolated network, or through an SSH
tunnel; not on anything the internet can reach. Federation and OAuth remain
https-only by design and will not work here.

---

## Everyday operations

```bash
# UPGRADE — tag a release in the component repo, wait for GHCR, then:
cd /opt/vidra && git pull --ff-only            # compose + Caddyfile only; CHECKOUT TREES ONLY
$EDITOR env/production.env                     # VIDRA_CORE_TAG=v0.2.0
./deploy/deploy.sh                             # dump -> pull -> gated migrate -> up -> probe

# ROLLBACK — app only, no schema change (see the one-release rule below):
./deploy/rollback.sh v0.2.0

# ROLLBACK across an incompatible schema change:
./deploy/compose.sh stop api frontend
./deploy/restore.sh backups/pre-deploy-<ts>.dump.gz
./deploy/rollback.sh v0.2.0
```

**On a bundle tree there is no `git pull`.** An upgrade is the tag bump plus
`vidra deploy` — a release changes the images, and that is what the tags name.
To take a release's new compose files and deploy scripts as well, unpack its
bundle over the tree (it contains no `env/` secrets and no `Caddyfile.local`, so
neither is touched), then deploy:

```bash
cd /opt/vidra
curl -fsSLO https://github.com/yegamble/vidra-core/releases/download/v0.2.0/vidra-bundle_v0.2.0.tar.gz
tar -xzf vidra-bundle_v0.2.0.tar.gz            # overwrites tracked files, keeps yours
$EDITOR env/production.env                     # VIDRA_CORE_TAG=v0.2.0 …
./deploy/deploy.sh
```

Verify its checksum against the release's `SHA256SUMS` first if you did not get
it through `install.sh`. A bundle-aware `vidra update` is a recorded follow-up;
today it warns rather than refuses on a tree with no git.

`vidra deploy`, `vidra rollback v0.2.0`, `vidra backup`, `vidra restore <dump>` and
`vidra release v0.2.0` are the same four lines: each execs the script above with
`ENV_FILE` set and returns its exit code, so `--yes` / `RESTORE_CONFIRM` and every
refusal reach you unchanged. `vidra logs [service]`, `vidra restart <service>` and
`vidra status` cover the read side.

### Upgrade notes: the embedded-migrator tag floor

**Both migration one-shots are the service image itself**, running its compiled-in
`migrate up`. That has a hard consequence for which tags this compose revision can
run at all:

- `deploy/deploy.sh` and `deploy/rollback.sh` carry a
  **`MIN_EMBEDDED_MIGRATE_TAG`** constant (`v0.2.0` — the first release cut with
  the embedded subcommand; raise it, never lower it) and refuse a
  `VIDRA_CORE_TAG` / `VIDRA_SEARCH_TAG` below it. An older image's `main()`
  **ignores the `migrate up` argv and starts an API server**, so the one-shot never
  exits: `deploy.sh` would hang on step 3/5, and `rollback.sh` on the
  `service_completed_successfully` edges inside `up -d`. A hang with no error is
  worse than a refusal, hence the gate.
- To run a component release *older* than the floor you must also check out the
  meta-repo revision that shipped with it — the pre-embedded compose files drove a
  `migrate/migrate` CLI container and bind-mounted `migrations/`.
- `VIDRA_USER_TAG` is not gated: the frontend has no migrator.

**Merge order — component releases land BEFORE this compose revision.** The chain
is `bootstrap.sh` → component checkouts → `docker-compose.yml` `include:`s
vidra-core's compose file. Until **vidra-core and vidra-search have both released
a tag whose image carries `migrate up`** (and `bootstrap.sh`'s default branch
sync therefore has it), a host on this revision runs `migrate up` against a binary
that does not know the word — locally that hangs `make dev` / `make dev-hot` on
the `migrate` one-shot, and in production `deploy.sh` refuses at pre-flight. Ship
in this order:

1. `vidra-core` — release the embedded migrator (`migrate up|version|force`).
2. `vidra-search` — same.
3. this meta-repo revision, with `MIN_EMBEDDED_MIGRATE_TAG` set to the tags from
   1 and 2, then `VIDRA_CORE_TAG` / `VIDRA_SEARCH_TAG` bumped in the env file.

Equivalent Make targets: `make release VERSION=…`, `make prod-config`,
`make deploy`, `make rollback TAG=v0.2.0`, `make backup`,
`make restore DUMP=… CONFIRM=1`, `make prod-logs`, `make prod-down`. All the
compose-based ones honour `PROD_ENV_FILE=env/staging.env`.

`make restore` is the one that asks first: like `make nuke` it wants `CONFIRM=1`
or the word `restore` typed at an interactive prompt, and refuses outright with
no terminal (CI, a cron job, an editor task runner). It then invokes
`deploy/restore.sh --yes`, which is what satisfies that script's own refusal —
so the confirmation happens exactly once, at the layer the operator is typing at.

### The restart window

Step 4/5 of a deploy recreates the api and frontend containers, so both are
briefly gone. Caddy buffers that window rather than exposing it: `Caddyfile`
sets `lb_try_duration` on both reverse-proxy blocks (30s for the api; 45s for
the frontend, which cannot start until the api is *healthy*), so a request
arriving mid-deploy is held and re-dialled every 250ms until the container
answers. Callers get a slow response instead of a 502.

What that is, precisely, and what it is not:

- **It retries connection failures.** A dial that failed is retried for *any*
  method, because the upstream never received the request — replaying it cannot
  duplicate an upload or a delete. A request that reached the container and then
  failed mid-round-trip is retried only if it matches `lb_retry_match`, which
  defaults to GET. That split is the whole safety argument; do not widen it.
- **It is not blue-green.** There is one instance of each service and nothing
  serves while the replacement boots. The wait is real — it is merely spent
  inside Caddy instead of in an error page.
- **Requests already in flight are not covered.** They are mid-response on the
  old container when it gets SIGTERM, so their fate is the graceful drain
  (`HTTP_SHUTDOWN_TIMEOUT`, 20s by default, inside the 30s
  `stop_grace_period`), and anything still running when that expires is cut off.
  Caddy will not replay those: the connection had already succeeded.
- **Past the duration it is a 502 again.** The buffer covers a normal recreate,
  not a deploy that is failing — a boot-looping api still surfaces, ~30s later.

### Cutting a release

The "tag a release in the component repo" line above is one command:

```bash
make release VERSION=v0.2.0                    # all three repos; prompts first
make release VERSION=v0.2.0 CONFIRM=1          # same, unattended
make release VERSION=v0.2.0 REPOS="vidra-core" # one repo only
./deploy/release.sh --yes v0.2.0               # the script directly
vidra release --yes v0.2.0                     # the CLI, which execs that script
```

Each component repo's `publish-container.yml` runs on `release: published` and
pushes `ghcr.io/<owner>/<repo>:<tag>` — the owner `deploy/release.sh` targets
via `GITHUB_OWNER`, which must agree with the `VIDRA_IMAGE_OWNER` the deploy
overlay pulls from — so cutting the release *is* building the image. `deploy/release.sh` creates the release in each repo
(`--generate-notes --latest`), watches the resulting workflow run to its
conclusion, and then verifies the image is really in GHCR
(`docker manifest inspect`, falling back to the GitHub packages API and saying
which check it used). It exits non-zero with a per-image summary if any repo
fails, and it does **not** deploy anything — bump `VIDRA_*_TAG` and run
`./deploy/deploy.sh` when you want the release live.

**Release the three repos at the same version.** Nothing enforces it, but
`./deploy/rollback.sh v0.2.0` sets all three `VIDRA_*_TAG` values from one
argument, staging→production promotion copies three identical lines, and "which
build is running?" during an incident has one answer instead of three. Skipping
a component that did not change means its tag no longer exists — release it
anyway.

**This repository is tagged too — first, and without a release.** vidra-core's
`release-assets.yml` builds `vidra-bundle_<tag>.tar.gz` by checking *this* repo
out at the same tag and running [`make-bundle.sh`](./make-bundle.sh) from it, so
the bundle has a provenance (one meta commit, one core commit, both recorded in
`vidra-bundle.manifest`) instead of being whatever `main` happened to be that
afternoon. The workflow fails loudly if the tag is missing, which is why
`deploy/release.sh` creates and pushes it above the per-repo loop. It is *not* in
`ALL_REPOS`: that loop creates a GitHub release, watches `publish-container.yml`
and verifies an image in GHCR, and there is no image here. Run `release.sh` from
a clean `main` — it refuses to tag a HEAD that is not already on `origin/main`,
because pushing a tag would otherwise publish unreviewed commits under it.

Guards, all of which fire *before* the first release is created (a release
notifies watchers and is not meant to be deleted):

- the tag must match `^v[0-9]+\.[0-9]+\.[0-9]+$` — the leading `v` is what
  `VIDRA_*_TAG` and every image reference here assume;
- `gh` must be authenticated;
- the tag must not already exist in **any** target repo;
- this repo's `origin` must be the `GITHUB_OWNER` repository the bundle step
  checks out, HEAD must be an ancestor of `origin/main`, and any existing meta
  tag of that name must point at that very commit (so re-running for a subset of
  repos works, and a tag pointing somewhere else is a refusal, not a surprise);
- **`vidra-user` needs the `NEXT_PUBLIC_API_BASE_URL` repository variable set**,
  because its workflow refuses to build without one — it is the build-time
  fallback origin, not the one production uses (see *Staging → production
  promotion* below). Set it once with
  `gh variable set NEXT_PUBLIC_API_BASE_URL -R yegamble/vidra-user -b https://your.origin`.
  Until it is set, `vidra-user` has **no published image** for any tag.

**Re-publishing a tag that already exists** — a build that failed on a transient
registry error, or a tag released before its workflow existed — does not need a
new release. Each `publish-container.yml` also takes a `workflow_dispatch` with
a required `tag` input, checks out that tag, and refuses if the tag does not
exist (so a typo can never publish the default branch):

```bash
gh workflow run publish-container.yml -R yegamble/vidra-search -f tag=v0.1.1
gh run watch "$(gh run list -R yegamble/vidra-search --workflow=publish-container.yml \
  --limit 1 --json databaseId --jq '.[0].databaseId')" -R yegamble/vidra-search
```

### Migration failed mid-deploy

Both migrators drive golang-migrate as a **library inside the service binary**
(`api migrate up` / the search image's `migrate up`), with the SQL compiled into
the image — there is no CLI container and nothing is bind-mounted from a
checkout, so applying a schema never depends on the repo layout on disk.

That library marks its version ledger `dirty = true` when a migration fails
part-way and then **refuses every subsequent `up`** with an opaque error. Because
the api gates on `migrate: condition: service_completed_successfully`, the site
stays down and each retry fails identically. `deploy.sh` runs the two migrators as
separate gated steps precisely so you see *which* one failed before anything is
restarted.

`deploy.sh` also pins nested checkouts to `VIDRA_*_TAG` so the migrators run the matching schema versions, and asserts the final ledger state against `vidra-core/migrations` to ensure it is correctly updated and `dirty=false`.

There are **two independent ledgers**:

| Service | Table | Migrator |
|---|---|---|
| vidra-core | `public.schema_migrations` | `docker compose … run --rm migrate` |
| vidra-search | `public.vidra_search_migrations` | `docker compose … run --rm search-migrate` |

Either can go dirty without the other. Recovery, for whichever failed:

```bash
# 1. Find out where it stopped. Either migrator reports its own ledger and runs
#    no migration SQL. It is not quite read-only: on a database that has NEVER
#    been migrated, opening the migrator CREATEs the empty ledger table first
#    (golang-migrate's ensureVersionTable, plus a brief advisory lock). Harmless
#    here — you are in this runbook because a ledger already exists — but do not
#    reach for it to probe a database you did not mean to touch.
#    Note the REPEATED word: `docker compose run <service> <args>` REPLACES the
#    service's command, so the subcommand must be restated.
./deploy/compose.sh run --rm migrate        migrate version   # core   -> version=42 dirty=true
./deploy/compose.sh run --rm search-migrate migrate version   # search -> version=… dirty=…
#    Straight from the ledger, if you are already in psql:
./deploy/compose.sh exec postgres psql -U vidra -d vidra -c 'SELECT * FROM schema_migrations;'
#    search ledger:                              SELECT * FROM vidra_search_migrations;
#    -> version | dirty
#          42   | t

# 2. Work out what migration 42 actually did before it failed, and undo the
#    partial effect BY HAND. golang-migrate does not roll back for you — a failed
#    migration leaves whatever it managed to commit. The .up.sql is in
#    vidra-core/migrations/ (or vidra-search/migrations/).
./deploy/compose.sh exec postgres psql -U vidra -d vidra

# 3. Point the ledger at the last CLEAN version, i.e. N-1, with the migrator's
#    own `force` — it stamps the version and clears `dirty` WITHOUT running any
#    migration SQL, so it is an assertion about the schema you just repaired.
#    --yes-i-know is mandatory and is checked before the database is touched: a
#    refusal means nothing happened. Whichever ledger is dirty, the command is
#    the same shape — each service forces its OWN table:
./deploy/compose.sh run --rm migrate        migrate force 41 --yes-i-know   # core
./deploy/compose.sh run --rm search-migrate migrate force 41 --yes-i-know   # search
#    Each prints the ledger state before and after (core: `before:`/`after:`,
#    search: `migrate force: before/after … table=…`) — keep it for the incident
#    notes. `force -1` is the right target when it was the FIRST migration that
#    died (that is golang-migrate's "empty ledger"), and both migrators refuse
#    anything below -1.

# 4. Re-run the normal migrator (the compose `command:` is `migrate up`).
./deploy/compose.sh run --rm migrate
```

Never point the ledger at `N` — that claims the broken migration succeeded and the
next deploy will build on a schema that does not exist.

Note that **none** of the 104 up-migrations use `CREATE INDEX CONCURRENTLY` and
none sets `lock_timeout`, so a data-dependent migration against a populated table
*stalls* rather than fails, and api boot is gated behind it. If a migration hangs,
look for a blocking lock (`pg_stat_activity`, `pg_locks`) before assuming it
crashed.

**Release policy: schema changes stay backward-compatible for one release.**
Release *N−1*'s code must run against release *N*'s schema. That is what makes
`rollback.sh` a 60-second tag flip that never touches the database, and it is why
a true schema rollback is "restore the pre-deploy dump" rather than "migrate
down". Additive columns, additive tables, and a two-release drop cycle
(stop writing → deploy → drop) are the way to keep it true.

**This is now mechanically enforced, not just documented.** `make ci` in *both* Go
repos runs `scripts/migrate-lint.sh`, which rejects destructive forward DDL (DROP
TABLE/COLUMN, RENAME, TRUNCATE, SET NOT NULL, ALTER … TYPE, DELETE FROM, DROP of a
schema object) in any `*.up.sql`; down migrations are exempt, since they *are* the
rollback path, and a line carrying `-- migrate-lint:allow` is the escape hatch for a
compat break the team has accepted. On top of that, vidra-core's `schema-compat`
workflow runs on every migrations change: it applies HEAD's migrations to a fresh
database, then runs the **previous release tag's** integration suite against that
schema — the exact breakage an operator would hit halfway through a rollback. Its
blind spot is the second half of the drop cycle: it proves N−1 still reads and writes
fine, not that N−1 had already stopped writing what N removes. Staged drops still need
a reviewer to confirm the write path went away in the prior release.

### Secret rotation

`ATProtoKEK()` and `MFAKEK()` in `vidra-core/internal/config/config.go:1257-1274`
both fall back to `FederationKeyKEK` when their own value is unset — verified in
the source, not assumed. So rotating `FEDERATION_KEY_KEK` on an instance that
never set `ATPROTO_KEY_KEK` / `MFA_KEY_KEK` silently destroys those too.

**There is no re-wrap job.** Nothing in the codebase re-encrypts persisted rows
under a new KEK. Rotating an envelope key means the old ciphertext can never be
opened again.

| Secret | Rotation cost | Notes |
|---|---|---|
| `JWT_SECRET` | **Free — logs everyone out.** | Invalidates every access + refresh token. Also re-derives the playback-token signer, so outstanding `?pt=` links for password-protected videos stop working. Rotate freely; just do it off-peak. |
| `SMTP_PASSWORD` | Free | Change at the relay and in the env file, `up -d api`. |
| `STORAGE_S3_ACCESS_KEY` / `STORAGE_S3_SECRET_KEY` | Free | Create the new Spaces key, deploy, then delete the old one — not the other way round. |
| `LIVE_INGEST_SECRET` | Free | Breaks any in-flight RTMP session; new stream keys work immediately. |
| `POSTGRES_PASSWORD` / `REDIS_PASSWORD` | Free, but **two places** | Change the value **and** any explicit `DATABASE_URL` / `REDIS_URL` / `SEARCH_REDIS_URL` that embeds it, then recreate the containers. Redis needs no data migration; Postgres needs `ALTER ROLE … PASSWORD` if the volume already exists (the `POSTGRES_PASSWORD` env only seeds a *fresh* cluster). |
| `SEARCH_INTERNAL_SECRET` | **Must change on BOTH services in ONE deploy** | It is a shared HMAC. The single `${SEARCH_INTERNAL_SECRET}` substitution feeds the api's `SEARCH_INTERNAL_SECRET` and the search service's `INTERNAL_SECRET`, so one env-file edit + one `up -d` is atomic enough. A split rollout means every core→search call 401s until it converges. |
| `FEDERATION_KEY_KEK` | 🔴 **DESTRUCTIVE** | Envelope key over persisted federation actor private keys. Rotating it makes them unreadable — and, via the fallback above, also breaks stored ATProto app passwords and TOTP secrets unless those have their own KEKs set. |
| `MFA_KEY_KEK` | 🔴 **DESTRUCTIVE** | Every stored TOTP secret becomes undecryptable; every user with 2FA is locked out and must be reset by an admin. (Also: leaving this **unset** stores TOTP secrets in **plaintext**, warned about only at `cmd/api/main.go:376`.) |
| `ATPROTO_KEY_KEK` | 🔴 **DESTRUCTIVE** | Every linked Bluesky app password becomes undecryptable; affected users must re-link. |

If you must rotate an envelope KEK, the only safe procedure today is: set the new
KEK, accept that the old ciphertext is dead, and force the affected users through
re-enrolment (disable + re-enroll TOTP, re-link ATProto, regenerate federation
actor keys). Plan it as a user-visible event, not as an ops task.

### Email

- **DigitalOcean blocks outbound port 25** on new accounts, and does not
  un-block it on request for most customers. Direct-to-MX delivery will not work.
  Use a relay (Postmark, SES, Mailgun, Resend, Fastmail…) on **port 587 with
  STARTTLS + AUTH** — which is what `SMTP_PORT=587` already defaults to and what
  the mailer implements.
- `SMTP_FROM` must be a domain you control, with **SPF** and **DKIM** published
  for the relay you chose (plus a **DMARC** record once those pass). Without
  them, password-reset and email-verification mail lands in spam and users
  conclude the site is broken.
- `MAIL_ENABLED=true` requires `SMTP_HOST` and `SMTP_FROM`; the api refuses to
  boot in production otherwise.
- **Never set `DEV_MAIL_CAPTURE_ENABLED=true` in production.** It exposes
  `GET /api/v1/dev/email-token`, which returns a live password-reset token for
  any address. It is gated in code (config validation plus the route
  registration) and 404'd at the edge by `deploy/Caddyfile`; do not go looking
  for a fourth way around it.

---

## Staging → production promotion

Staging runs production config with throwaway data. Promote by deploying the
**exact image tags** staging validated: `./deploy/rollback.sh` and
`./deploy/deploy.sh` both work from the `VIDRA_CORE_TAG` / `VIDRA_USER_TAG` /
`VIDRA_SEARCH_TAG` values in the env file, so promotion is copying three lines.

**The same image serves every environment.** This used to be the opposite: the
frontend inlined `NEXT_PUBLIC_API_BASE_URL` into the client bundle at build time,
so a staging host with a different origin needed its own build. It no longer
does. The container reads `PUBLIC_API_BASE_URL` (which `docker-compose.yml` fills
from the env file's `NEXT_PUBLIC_API_BASE_URL`) and serves it to the browser as
`/runtime-config.js`, so the origin is a **restart**, not a rebuild. The
build-time inline survives only as the dev/e2e fallback.

CI still publishes one `vidra-user` image per release and its workflow still
requires the `NEXT_PUBLIC_API_BASE_URL` repository variable to be set — that gate
has not changed — but the value it bakes is now only what a container that was
given no runtime origin would fall back to. Under the single-origin topology it
is the site origin anyway.

---

## Backups & restore

`./deploy/backup.sh` (and the systemd timer) writes **two** files per run, both
stamped with the same UTC timestamp:

| File | Contents | Kept |
|---|---|---|
| `backups/vidra-<UTC>.dump.gz` | Custom-format `pg_dump`, verified with `pg_restore -l` before it is kept | 14 daily + 8 weekly |
| `backups/vidra-config-<UTC>.tar.gz` | `env/production.env` + `deploy/Caddyfile.local`, stored repo-relative, mode 0600 | 14 daily + 8 weekly |

plus a `backups/last_success` marker — `<RFC3339Z> <dump filename>`, which is
what `vidra doctor` reads to judge backup age against a 26-hour window. Its
format is a contract; do not "improve" it.

- **One dump covers both services.** vidra-search shares the core database in the
  `search` schema, so a database-wide dump already includes it.
- **The config archive is why a dump is restorable at all.** `env/production.env`
  holds every secret and `MFA_KEY_KEK`, which is generated once, is the
  key-encryption key for stored TOTP secrets, and is not derivable again — restore
  a database without it and every user's second factor is undecryptable.
  `deploy/Caddyfile.local` is generated by `vidra setup` and gitignored, so it
  existed *only* on the host that died. Until wave 5 the off-site bucket held a
  full history of dumps and nothing that could read them.
- **Off-site is opt-in and you must opt in.** Set `BACKUP_RCLONE_REMOTE` (with
  `rclone` installed) or `BACKUP_S3_URI` + `BACKUP_S3_ENDPOINT` (with the `aws`
  CLI). Use a bucket in a **different region from the media Space**. Both files
  go to the same target; there is deliberately no separate knob, because sending
  the dump away and leaving its config on the dead host is the exact failure the
  archive closes.
- **Alert on a *missing* backup**, not just a failing one. Set
  `HEALTHCHECKS_URL=https://hc-ping.com/<uuid>`; the script pings `/start`,
  `/fail` on any error, and success at the end, so a droplet that stops running
  the timer at all still pages you.
- **Media is not in either file.** With `STORAGE_BACKEND=s3` that is deliberate
  and the durability settings are the provider's — see
  [S3-canonical deployments](#s3-canonical-deployments) below, which is also
  where the versioning-without-a-lifecycle-rule billing trap is written down.
  With `local`, see
  [Local media volume snapshots](#local-media-volume-snapshots).
- **Redis** is a cache + rate-limit/dedup store: no backup needed, and it may be
  flushed at any time.
- **External Postgres takes no backup here at all.** With
  `VIDRA_EXTERNAL_POSTGRES=true` both `backup.sh` and `restore.sh` refuse
  outright — they work by `docker exec` inside a container that overlay keeps out
  of the project — and you use your provider's automated backups and PITR
  instead. The refusal is placed *before* the healthchecks.io ping on purpose, so
  the dead-man's switch stays silent and the inactivity alert fires. That is the
  honest signal for a host that genuinely backs nothing up from here. It also
  means such a host gets **no config archive** either: back up
  `env/production.env` and `deploy/Caddyfile.local` yourself.
- **Restore drill (quarterly).** Restore the latest dump into a scratch stack,
  boot, and click through login / watch / upload.

### Disaster recovery: rebuild the host, in this order

The order matters and it is not the obvious one. `restore.sh` **refuses to run
while `deploy/Caddyfile.local` is missing** — `docker-compose.prod.yml` mounts
that file, and a missing bind-mount source is created by Docker as an empty
*directory*, which crash-loops Caddy with every app container perfectly healthy.
So the configuration has to land before the database, not after:

```bash
# 1. A host and a checkout.
sudo ./deploy/provision.sh --yes                     # or boot it from cloud-init
git clone https://github.com/yegamble/vidra.git /opt/vidra && cd /opt/vidra
./bootstrap.sh

# 2. Fetch both files for the SAME stamp from off-site.
rclone copy "$BACKUP_RCLONE_REMOTE/vidra-config-20260820T031500Z.tar.gz" backups/
rclone copy "$BACKUP_RCLONE_REMOTE/vidra-20260820T031500Z.dump.gz"        backups/

# 3. Configuration FIRST. Restores env/production.env (0600) and
#    deploy/Caddyfile.local to exactly where the compose chain looks for them.
tar -xzf backups/vidra-config-20260820T031500Z.tar.gz -C /opt/vidra
git check-ignore -v env/production.env               # MUST match

# 4. Bring up just enough to restore into, then restore.
./deploy/compose.sh up -d postgres
./deploy/restore.sh backups/vidra-20260820T031500Z.dump.gz

# 5. Media, if STORAGE_BACKEND=local — see the next section.
# 6. Point DNS at the new host, then ./deploy/deploy.sh.
```

Two things to check before you trust the result. The env file pins
`VIDRA_*_TAG`, so the rebuilt host comes back on **the release the dump was
taken under** — which is what you want, and is worth reading rather than
assuming. And the archive is only as fresh as the last successful run: if
`vidra setup` regenerated the Caddyfile or rotated a secret *after* the newest
archive, that change is not in it.

`./deploy/restore.sh` refuses to run without `--yes` or
`RESTORE_CONFIRM=<database name>`. It stops api + search + frontend (search
shares the database, so leaving it up means it reconnects mid-restore), drops and
recreates the database, restores with `-j4`, runs both migrators to bring the
schema to HEAD, **checks that the media the restored database references is
actually in the object store** (see the next section — it warns and continues,
never blocks), restarts, and polls `/readyz`.

### S3-canonical deployments

`STORAGE_BACKEND=s3` is the production default, and it moves one job off this
host and onto your provider: **media durability is a bucket setting, not a
script.** There is no media in either backup file and there never will be —
nothing a shell script here could do would beat what the provider already offers.
So configure it deliberately, because the defaults of the cheapest target are
also the most expensive ones.

**Pick one of two durability stories, and know which you picked.**

| | What it protects against | What it costs |
|---|---|---|
| **Versioning** | A delete or an overwrite — yours, or a compromised key's. The previous bytes are still there. | Every superseded version keeps billing **until a lifecycle rule removes it**. |
| **Cross-region replication** | Losing the region, the bucket, or the account's access to it. | A second copy's storage + egress, continuously. |

Versioning is the one most operators reach for and the one with the trap.

**If you turn versioning on, pair it with a lifecycle rule that expires
non-current versions.** Without one, a versioned bucket never reclaims anything:
a delete writes a *delete marker* (Backblaze calls it a *hide marker*) and the
previous version keeps existing and keeps billing, forever. Vidra's media GC
deletes orphaned objects — a deleted video's HLS tree, a superseded original —
and on such a bucket a *successful* sweep frees exactly zero bytes while
reporting that it deleted thousands of objects. Both numbers are true; only one
is on the invoice.

This matters most on **Backblaze B2, whose buckets are versioned by default**,
so the expensive case is the default case for the cheapest storage target.

`vidra doctor` reports it under **object retention**, and that ⚠ is the same
fact from the other end: it reads the bucket's versioning and lifecycle
configuration and warns when versioning is on with no `NoncurrentVersionExpiration`
rule. A green **object retention** line means either "not versioned" or
"versioned *and* expiring non-current versions" — those are the two supported
shapes. Thirty days of non-current retention is a sane default: long enough to
undo an accidental delete, short enough that the bill stops growing.

**The ordering hazard, stated plainly.** The nightly dump is a snapshot of the
database at time T. The bucket is whatever it is at T+n, because its durability
runs on the provider's schedule and not on this one. Restore them and the two
are no longer a matched pair, in both directions:

- **object with no row** — media uploaded after the dump. Harmless to viewers,
  and it is what the media-GC safety rails exist for: the ownership marker
  refuses to delete from a store this install has not been shown to own, the
  orphan-ratio breaker refuses a sweep that finds an implausible share of the
  store to be garbage (a freshly restored older database looks *exactly* like
  "almost everything is an orphan"), and the first sweep after any restart is
  always a dry run. Without those rails a restore would be followed, within 24
  hours, by a GC pass that deleted every object the older dump does not mention.
- **row with no object** — media deleted after the dump, or a bucket restored
  from a different point in time. Nothing detects this on its own: the api just
  404s that one video, forever, and you hear about it from a viewer.

`restore.sh` closes the second half automatically. After both migrators and
before the stack comes back up it runs the fast pass:

```bash
docker compose … run --rm api verify-blobs --timeout=10m
```

It **never blocks the restore.** Exit `3` (verified, and it is wrong) prints a
warning block naming the missing keys and continues; exit `1` (could not verify
— bucket or database unreachable) prints a different warning and continues.
Aborting there would leave the site down over a media problem that not booting
does not fix.

**When to run it by hand, with `--hash`.** The fast pass reads no bytes — it
asks the store whether each object exists. `--hash` re-downloads every object
that has a recorded digest and compares, which is the only mode that detects
media that is *present but corrupt*. It reads the whole library, so give it a
real timeout and run it:

- after a **bucket-level restore** or a provider incident, where the objects came
  back but you have no independent evidence they came back intact;
- after **moving the media store** (the storage-migration campaign verifies each
  copy in flight, but this is the whole-library statement at the end);
- on whatever **periodic schedule** you are willing to pay the reads for — this
  is a full read of every original, so it is a deliberate cost, not a cron
  default.

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml \
  --env-file env/production.env run --rm api verify-blobs --hash --deep --timeout=4h
```

`--deep` additionally walks each HLS tree through the storage backend instead of
trusting that a present master manifest implies a present ladder — worth adding
after anything that touched the store wholesale, because a partial restore that
brought back one small text file per video and none of the segments passes the
fast pass with a clean bill of health and plays nothing.

Two things it deliberately does not do: it never writes (no repair mode — every
plausible repair destroys information, and only you know which of the two stores
is the stale one), and it must not be run **during a storage migration**, when
the two stores are deliberately out of step. It says so in its own output, and
`vidra doctor`'s **storage migration** check reports the same fact before you
start. Full reference: "Verifying media consistency" in
`vidra-core/docs/operations.md`.

### Local media volume snapshots

**The nightly backup does not touch a single byte of media.** With
`STORAGE_BACKEND=s3` that is correct and deliberate — use the object store's own
versioning and cross-region replication, which is better than anything a shell
script here could do. With `STORAGE_BACKEND=local` it means the uploads live in
a Docker named volume that nothing backs up, while the rows pointing at them are
dumped every night. Restore that dump onto a new host and you get a complete
catalogue of videos that will not play.

The volumes, as Docker names them (the compose project is `vidra`, so each is
prefixed):

| Volume | Holds | Back it up? |
|---|---|---|
| `vidra_media_data` | `/app/data` — originals, HLS renditions, thumbnails, storyboards | **Yes**, when `STORAGE_BACKEND=local`. This is the one. |
| `vidra_caddy_data` | ACME account key + issued certificates | Worth it. Losing it re-orders every certificate, and Let's Encrypt's duplicate-certificate limit is 5/week. |
| `vidra_caddy_config` | Caddy's autosaved JSON config | No — regenerated from `Caddyfile.local`, which the config archive already carries. |
| `vidra_ipfs_data` | Pinned content, with the `ipfs` profile on | Yes, if you are the only pinner. |
| `vidra_postgres_data` | The database | No — `backup.sh` dumps it, which is portable across majors; a raw volume copy is not. |
| `vidra_transcode_tmp` | ffmpeg scratch (`TMPDIR=/scratch`) | No. Genuinely disposable. |
| `vidra_live_hls` | In-flight live segments | No. Replays land in `media_data`. |
| `vidra_search_models` | Trained ranking models | No — regenerated by training. |
| `vidra_whisper_models`, `vidra_clamav_data` | Downloaded model/signature data | No — re-downloaded on demand. |

Snapshot without stopping anything. `tar` reads a consistent-enough view for
media, which is append-mostly; do it **after** the nightly dump so files are
never older than the rows:

```bash
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
docker run --rm \
  -v vidra_media_data:/src:ro \
  -v "$PWD/backups":/dst \
  alpine tar czf "/dst/media_data-${STAMP}.tar.gz" -C /src .

# Off-site, same bucket as the dumps, different region from the media Space:
rclone copyto "backups/media_data-${STAMP}.tar.gz" \
  "${BACKUP_RCLONE_REMOTE%/}/media_data-${STAMP}.tar.gz"
```

Restore is the mirror image, into a volume the stack is **not** running against:

```bash
docker volume create vidra_media_data
docker run --rm -v vidra_media_data:/dst -v "$PWD/backups":/src:ro \
  alpine sh -c 'tar xzf /src/media_data-<stamp>.tar.gz -C /dst'
```

Two honest caveats. This is **not** wired into `backup.sh` or the timer: a media
volume is orders of magnitude larger than a dump, the right cadence and target
differ per instance, and a nightly job that silently fills the disk it is
protecting is worse than a documented manual step. And `tar` over a live volume
is crash-consistent, not point-in-time — a file being written during the
snapshot may be truncated in it, which for an upload in progress is acceptable
and for anything you care about means using a filesystem or block-storage
snapshot instead. If media matters more than that, the answer is
`STORAGE_BACKEND=s3`.

---

## Health & monitoring

- Probes: `GET /healthz` (liveness), `GET /readyz` (readiness incl.
  postgres/redis). Point an external uptime check at `https://<domain>/healthz`
  **and** at the site root — an internal check cannot tell you the certificate
  expired.
- `GET /schemaz` (core, unauthenticated) reports the running build **and** the
  migration ledger — `{"software":{…},"schema":{"version","dirty","applied"}}` — so
  `vidra status`/`doctor` can ask "what is this instance at" without psql. Always
  200, including when the database is unreachable (the error goes inside the
  document: a 5xx cannot distinguish "no api" from "api up, database gone").
  Deliberately **not** edge-routed — `deploy/Caddyfile` proxies a root-path
  allow-list and this is not on it — so it is host-local only:
  `curl -s http://127.0.0.1:${HTTP_PORT}/schemaz`.
- The **frontend** container has its own `/healthz` (`app/healthz/route.ts`),
  reachable only inside the container — the edge routes `/healthz` to the api. It is
  what `docker-compose.prod.yml`'s healthcheck probes, because a `/` render awaits
  the api and so cannot report on the frontend alone.
- Operator snapshot: `GET /api/v1/admin/system` (admin JWT) — status, versions,
  uptime, dependency health, effective non-secret config. Dependency health now
  covers the object store, the SMTP relay, the search service and the ffmpeg binary
  alongside postgres/redis (probed concurrently, 3s each, only when the page is
  opened); `not_configured` — local storage, mail off, no search service — is a
  supported deployment and never degrades the instance. `/readyz` keeps its cheap
  two-dependency contract, because that one runs on every orchestrator tick.
- `METRICS_ENABLED=true` exposes Prometheus RED metrics at `/metrics`. That route
  is root-mounted with **no auth** (`internal/httpapi/server.go:806`), which is
  why `deploy/Caddyfile` answers 404 for it unconditionally. Scrape it from
  inside the compose network, never through Caddy.
- Optional OTel: set `OTEL_ENABLED=true` plus the `OTEL_*` variables. The api,
  the frontend and the search service all read them; the api and the frontend
  keep distinct service names (`OTEL_SERVICE_NAME` vs
  `FRONTEND_OTEL_SERVICE_NAME`) so their spans stay distinguishable. Enabling
  OTel without `OTEL_EXPORTER_OTLP_ENDPOINT` is a **hard boot failure**.

---

## Media delivery and CDN policy

The API is the visibility gate for originals, HLS, and thumbnails. Do not apply
a blanket public/immutable rule to `/api/v1/videos/*`: a video can become private
or be deleted, and password playback tokens can appear in the query string.

Vidra emits cache policy by asset shape:

| Asset | API policy | Reason |
|---|---|---|
| Versioned VOD HLS (`?v=<generation>`) | `private, max-age=31536000, immutable` | A completed generation never changes; master/variant rewrites propagate the version to every child request. |
| Unversioned VOD HLS compatibility URL | `private, max-age=0, must-revalidate` | The route can point at a newer transcode generation. |
| Authenticated or `?pt=` media | `private, no-store` | Prevents credentials or protected media from entering a shared/browser cache. |
| Live playlist | `no-cache, no-store` | The manifest changes continuously. |
| Live segment | `private, max-age=12` | Short reuse window; nginx-rtmp can reuse sequence names after a restart. |
| Replaceable thumbnail | `private, max-age=300, must-revalidate` | The stable thumbnail URL can receive new bytes. |

The original-file route already supports `Accept-Ranges: bytes` and `206 Partial
Content` on local and S3 storage, so a CDN or reverse proxy must preserve Range
requests and responses. This is why `deploy/Caddyfile` applies `encode` **only**
to the frontend site block and never to the api routes — edge compression on
already-compressed media buys nothing and is the classic way to break seeking.

For a shared CDN, use an origin shield and bypass caching whenever
`Authorization`, cookies, or `pt` are present. Promoting versioned public-video
HLS from `private` to shared `public` caching is safe only after the deployment
can purge every old URL on privacy changes and deletion; otherwise an old CDN
entry can outlive the API authorization decision. Keep live playlists uncached
and use a short TTL for live segments. Configure vendor-specific shield and
purge hooks outside the application—the reference stack deliberately does not
pretend a particular CDN exists.

The frontend's Next.js `assetPrefix` is a separate static-JS/CSS lever. Set it
only when those assets are actually published at a CDN origin; it does not alter
video-media headers or replace the media delivery policy above.

---

## `vidra-search` is internal

Only `vidra-core` talks to it, over the compose network, HMAC-authenticated. Do
**not** add a Caddyfile site for it or publish its port past the host; the prod
overlay removes the publish entirely. Its host port (`SEARCH_HTTP_PORT`, default
`:8081`) exists for local inspection in development only.

---

## QA environment

QA mirrors `vidra-user/.github/workflows/frontend-e2e-backed.yml` exactly — that
workflow is the QA contract (flags in `env/qa.env.example`). A QA host exists to run
the same backed suite against long-lived data and for manual exploratory testing.
Note that `env/qa.env.example` deliberately sets `DEV_MAIL_CAPTURE_ENABLED=true`
and `HTTP_IMPORT_ALLOW_PRIVATE_URLS=true`; both are account-takeover / SSRF
primitives and must never be copied into a production env file.

## Release-readiness preflight (A01)

Before a fresh-host rehearsal, freeze an **existing** common release tag in a
new disposable directory. Requires Python >=3.9, Node >=24 with npm, git,
authenticated `gh`, and Docker buildx registry access. This reads GitHub/GHCR;
it does not publish, run containers, or change the operator's nested checkouts.

```bash
python3 deploy/release-preflight.py --tag v0.6.2 --platform linux/amd64 \
  --out /tmp/vidra-candidate-unique > /tmp/vidra-candidate-unique.log 2>&1
python3 -m unittest discover -s tests -p release_preflight_test.py
```

The output directory must not exist. Retain its `manifest.json`, command log,
and `bundle-provenance.txt` with the acceptance evidence. A nonzero exit or
anything other than `status: PASS` blocks the next acceptance. Failures preserve
partial evidence; retries use a new directory. A PASS covers:

- Four detached source commits resolved from the requested release tag.
- Three immutable registry digest references, selected Linux platform, and OCI
  revision/source labels matching those commits (label correspondence, not
  an independent reproducible-image build).
- Downloaded bundle and selected Linux CLI checked against release SHA256SUMS;
  bundle meta/core provenance must match the source commits. Assets are never
  executed or extracted. Checksums establish release consistency, not signatures.
- The frozen frontend's existing path guard, lockfile-installed code generator,
  byte-identical generated types, and rejection of a resolver call against a
  spec without that endpoint. The guard's coverage is version-dependent: v0.6.2
  checks paths, while newer source also checks methods.

Use the recorded commits and `images.*.reference` digests for subsequent tests;
do not resolve moving `main` or image tags again and call that the same candidate.
`source/` holds disposable checkouts and installed codegen dependencies; the
manifest is the portable identity record. A01 does not certify runtime workflows,
image startup, blank-host installation, search, or browser/media behavior. The
v0.6.2 example is a rehearsal candidate, not a change to production pins.

## Blank-server installer smoke (A02)

Run the released installer on a **new Ubuntu 24.04 Multipass VM**, using an A01
PASS manifest. Requires Multipass with a working daemon, Python >=3.9, curl and
network access to Ubuntu/Docker repositories, GitHub release assets and GHCR.
The launcher allocates 2 CPUs, 4 GiB RAM and a 20 GiB disk, without mounting host
directories or the host Docker socket. It never selects an existing VM.

```bash
python3 -m unittest discover -s tests -p '*_test.py'
bash tests/blank-server-smoke.sh \
  docs/evidence/a01-v0.6.2-linux-amd64.json /tmp/vidra-a02-unique
```

Use a new output directory each time. A missing dependency, failed transfer,
failed assertion or missing result returns nonzero. `status.txt` and `result.json`
must both say PASS. `candidate.json`, `vm.json` (including the base image hash),
`install.sh`, staged guest verifier and sanitized result identify the run.

The real released installer installs Docker/Compose, rejects a corrupted bundle
and CLI download, and then installs the original verified assets. Corruption is
injected only in negative runs by appending a byte after curl's actual transfer;
HTTP status and exit codes are preserved. Positive runs use the ordinary curl.
The released setup CLI generates local test configuration; reinstall must leave
the env file, rendered Caddyfile and CLI byte-identical. The harness validates
production Compose ports with explicit profiles and pulls all three exact A01
image digests, checking their platform and revision labels after the pull.

Multipass uses the workstation's native architecture. The native CLI is verified
against the SHA256SUMS **whose own hash A01 pinned**. An ARM64 VM can pull the
candidate's amd64 images, but this proves availability only: no containers start
in A02. Runtime ports, architecture-compatible image execution, migration,
readiness and frontend checks remain A03. The plain-HTTP `video.test` setup is an
isolated test configuration and requests no public TLS certificate.

The VM is retained **stopped** on success or failure, named in `vm-name.txt`.
Only sanitized evidence leaves it; raw command logs, generated configuration and
test secrets stay under `/root/vidra-a02-private` and `/opt/vidra` in the VM.
For a failed run, start that exact VM and inspect the named private log; rerun the
acceptance on a new VM after a fix. Do not label an existing volume as fresh.
To remove the disposable VM after retaining evidence, use `multipass delete
--purge <name-from-vm-name.txt>`; never use a global purge or an unrelated VM name.
# Released-stack runtime rehearsal (A03)

After A02, run the retained disposable VM through setup, both real migrators,
edge and frontend probes, and injected dirty-ledger failures:

```sh
bash tests/runtime-smoke.sh /tmp/vidra-a02-smoke-r1 \
  docs/evidence/a01-v0.6.2-linux-amd64.json /tmp/vidra-a03-new
```

The VM must still have **no containers or volumes**. The harness refuses a used
runtime; use a new A02 VM for another full rehearsal. It copies the installation
inside that VM, pins the copy's application images/platforms to A01, and uses a
unique Compose project. It runs this checkout's deploy script against that bundle
and records both script hashes, retaining the semver gates,
bundle provenance and independent core ledger assertion. The test independently
checks the search ledger against migration filenames at the frozen source SHA.
No workstation install or production host is accepted.

The candidate architecture must execute on the VM. On an ARM64 Ubuntu VM with
an amd64 candidate, install Ubuntu's `qemu-user-static` package in the disposable
guest first. The harness records binfmt registration and executes every image;
a pull alone cannot pass. Emulation results are functional evidence, not native
performance or capacity evidence. The lab sets API limits to 2 CPUs / 1536 MiB.

The default ACME edge profile is rendered only. Actual runtime checks use plain
HTTP then internal-CA HTTPS, including certificate verification using Caddy's
test root, frontend HTML and runtime API-origin changes. No public certificate
is ordered. Dirty core and search ledger bits are injected separately after a
successful deployment; each must produce a nonzero migration failure without
reaching startup or changing serving container IDs, start times or restart
counts. Only the injected bit is cleared, followed by a normal recovery deploy.

`result.json`, progress and status are exported; raw command logs and generated
test secrets stay in the guest's root-only `private` directory. The VM is stopped
and retained on success or failure. A failure is evidence to investigate, never
a skipped acceptance. These checks do not certify owner claim, browser workflows,
media processing, public ACME, external TLS, lock contention or recovery objectives.
# Owner and session rehearsal (A04)

With Node >=24 and the sibling frontend's installed Playwright/Chromium, run:

```sh
node tests/owner-auth-smoke.mjs /tmp/vidra-a03-r3 /tmp/vidra-a04-new
node --test tests/owner_auth_smoke_test.mjs
```

The target must be the retained A03 disposable VM with **zero users**. The
harness refuses an already-claimed instance; do not point it at an operator
stack or delete accounts to make that guard pass. It opens registration through
the released setup/deploy procedure before claim so signup refusal proves the
owner gate. It verifies boot-token rotation, claims through the actual browser,
checks API/SQL roles, signs up a normal user, reloads twice, signs out/in and
checks rejected authentication and closed registration. Registration ends closed.
The two synthetic users remain available for later acceptance work.

The browser uses an explicit lab-host DNS mapping and ignores the lab certificate
only in its isolated Playwright contexts. A03 separately verifies that certificate
chain with the lab CA. No route interception or mocked backend is used.

The output directory is private: `private-accounts.json`, error diagnostics and
screenshots can contain synthetic credentials or account details and must not be
committed. Only the sanitized `result.json` is suitable for acceptance evidence.
No screenshot/trace of a filled setup-token form is exported.

For the simultaneous-claim case, transfer `tests/owner_claim_race.py` into the
same VM and run it as root with the A03 Compose project and a new root-only output
directory. It creates a new database, runs the pinned core image's real migrations,
starts a separate API with workers disabled, then releases two claim requests at
a barrier. Exactly one must create an admin. The test container is stopped and
its database/logs retained; the primary A04 users are unaffected.


### A04 registration and session policy verification

After the owner harness succeeds, reuse its private actor directory and A03 VM
metadata. Each output directory must be new. Run these sequentially against the
disposable VM only; the expiry helper temporarily changes token lifetimes using
the normal deploy path and restores the original values in `finally`.

```bash
node tests/auth-policies-smoke.mjs /tmp/vidra-a03-r3 /tmp/vidra-a04-r3 /tmp/vidra-a04-policies-new
node tests/auth-expiry-smoke.mjs /tmp/vidra-a03-r3 /tmp/vidra-a04-r3 /tmp/vidra-a04-expiry-new
```

The policy harness uses real browser approval/rejection, concurrent reloads,
shared-cookie logout and independent-session logout-all. It spaces groups by
62 seconds to respect production rate limits. `A04_CASES` accepts a comma-separated
subset of `approval-rejection,concurrent-tabs,logout-all-revocation` for diagnosis;
only a result selecting all three proves the full policy set. Neither harness
uses browser route mocks. Private credentials/logs must remain outside Git.

The frozen release reproduces the multi-tab refresh race. For the passing A04
run, a local image used the frozen frontend source plus the production client
patch from frontend PR #145; see
[fixture provenance](../docs/evidence/a04-frontend-fixture.json). Restore the
original frontend image after this disposable test. Do not infer that an older
published image contains a merged source fix. The current proof uses HTTPS
Chromium with Web Locks; other browser/fallback behavior remains unverified.


### A06 original upload verification

Use the retained disposable A03 VM and A04 private actors. Generate a real audio
and video fixture with ffmpeg (the recorded run used 8.1), then run on Node >=24:

```bash
mkdir -p /tmp/vidra-a06-fixture
ffmpeg -hide_banner -loglevel error \
  -f lavfi -i testsrc2=size=320x240:rate=24 \
  -f lavfi -i sine=frequency=440:sample_rate=48000 \
  -t 5 -c:v libx264 -pix_fmt yuv420p -c:a aac -movflags +faststart \
  /tmp/vidra-a06-fixture/clip.mp4
node tests/upload-smoke.mjs /tmp/vidra-a03-r3 /tmp/vidra-a04-r3 \
  /tmp/vidra-a06-fixture/clip.mp4 /tmp/vidra-a06-new
```

The harness creates and selects a channel through the browser, uploads through
the real resumable protocol, checks persisted ownership/metadata/hash and
refusal paths, briefly sets/restores the synthetic user's quota override, then
recreates only the disposable API container and verifies durability. It also
uploads corrupt media and requires an honest failed outcome. Output must be a
new directory. Credentials, screenshots and raw errors remain private; retain
successful video IDs for A07. Existing fixtures are not reset. Do not run on an
operator or production installation. A06 does not certify playback or thumbnails.

### A07 HLS and progressive playback verification

After A06, retain its exact fixture and disposable VM. The helper validates the
A03/A06 target evidence and uses the A04 ordinary actor:

```bash
node tests/playback-smoke.mjs /tmp/vidra-a03-r3 /tmp/vidra-a04-r3 \
  /tmp/vidra-a06-fixture/clip.mp4 /tmp/vidra-a07-new
```

It makes the synthetic A06 video public, waits up to 40 minutes for its real
transcode job to finish, walks every advertised HLS playlist/init/segment, and
measures unmuted browser frames, decoded audio, time progression and completed
seek through the production player. Playback is started with the media API;
this does not certify Play-button behavior or physical speaker output. The
browser also decodes the original into nonzero PCM, selects the advertised
quality via the actual menu, and repeats playback.

To exercise the same original after HLS is ready, the helper temporarily marks
only this synthetic video's streaming playlist pending. It verifies that the
real API stops advertising HLS and the production player chooses `/original`,
then restores ready in `finally` and verifies HLS is advertised again. This
models pre-transcode availability; it does not inject a fatal HLS network error.
A hard process kill can bypass `finally`; inspect the retained video's
`streaming_playlists.state` before resuming. Never run against production.
The video stays public, and all bytes/job rows remain for dependent A09/A08.
Keep raw errors/screenshots and account credentials private; commit only reviewed,
sanitized evidence. Missing media or unavailable runtime prerequisites fail the
run rather than skip. Use a new output directory for each attempt.
