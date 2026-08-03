# Deploying Vidra (dev-remote / QA / staging / production)

Canonical environment matrix: [`.ralph/specs/environments.md`](../.ralph/specs/environments.md).
This directory holds the reference single-host deployment: the meta-repo compose
stack plus a production overlay, behind Caddy for TLS.

| File | What |
|---|---|
| [`../docker-compose.prod.yml`](../docker-compose.prod.yml) | Production overlay: loopback binds, GHCR images, restart policies, log caps, resource limits, named volumes, Caddy. |
| [`Caddyfile`](./Caddyfile) | Single-origin TLS reverse proxy (path routing to api/frontend). |
| [`deploy.sh`](./deploy.sh) | dump → pull → gated migrations → up → probe. |
| [`rollback.sh`](./rollback.sh) | Rewrite the image tags, pull, restart, re-probe. |
| [`backup.sh`](./backup.sh) | `pg_dump -Fc` → gzip → optional off-site → retention → success marker. |
| [`restore.sh`](./restore.sh) | **Destructive.** Drop, recreate, `pg_restore -j4`, migrate, re-probe. |
| [`vidra-backup.service`](./vidra-backup.service) / [`.timer`](./vidra-backup.timer) | systemd units for the nightly backup. |

---

## First boot — do these in order

The ordering here is not cosmetic. `vidra-core/internal/auth/service.go:244-246`
grants the **admin** role to the first account created while the `users` table is
empty (`if n, err := s.repo.CountUsers(ctx); err == nil && n == 0 { role = "admin" }`),
and it does so on **every** signup path. There is no CLI to create or promote an
admin — `vidra-core/cmd/` contains only `api` and `peertube-import` — so if a
signup bot beats you to the first registration, it owns your instance and the
only recovery is hand-written SQL against the `users` table.

1. **Ship with registration closed.** Set `REGISTRATION_ENABLED=false` in
   `env/production.env` *before* the first `up -d`. (Step 1 of the readiness plan
   is what made this variable reachable from the env file at all; the code
   default is `true`.)
2. **Bring the stack up** and confirm `/readyz` is 200 — see
   [First bring-up](#first-bring-up) below.
3. **Register the owner account.** Registration is closed, so do it while the
   flag is still `false` by flipping it for exactly this one step:
   temporarily set `REGISTRATION_ENABLED=true`, run
   `docker compose … up -d api`, register, then set it back to `false` and
   restart the api again. Do this **before DNS propagates**, or over the
   loopback port (`http://127.0.0.1:8080`) through an SSH tunnel, so the window
   is not publicly reachable.
4. **Verify you actually got admin** before you trust it:
   `GET /api/v1/admin/system` with your access token must return 200 (a
   non-admin gets 403), and `/admin` in the UI must render.
5. **Only now** decide your registration policy — leave it closed for a private
   launch, or set `REGISTRATION_ENABLED=true` (optionally with
   `REGISTRATION_REQUIRE_APPROVAL=true`, which files signups into the admin
   approval queue instead of creating accounts) and `up -d` again.
6. **Announce the domain.**

---

## Host prerequisites

`ufw`, `unattended-upgrades` and SSH hardening are not mentioned anywhere else in
this repo, and one of the items below (the DOCKER-USER warning) is the reason a
host firewall will *not* save you.

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
constructed compose default for both core and search, and
`SEARCH_MIGRATE_DATABASE_URL` overrides the search migrator's, which must keep
its `&x-migrations-table=vidra_search_migrations` suffix.

---

## First bring-up

```bash
git clone https://github.com/yegamble/vidra.git /opt/vidra && cd /opt/vidra
./bootstrap.sh                          # clones the three component repos
cp env/production.env.example env/production.env
$EDITOR env/production.env              # JWT_SECRET, POSTGRES_PASSWORD, REDIS_PASSWORD,
                                        # MFA_KEY_KEK, SEARCH_INTERNAL_SECRET, SMTP_*,
                                        # STORAGE_S3_*, INSTANCE_NAME, PUBLIC_BASE_URL,
                                        # VIDRA_*_TAG=v0.1.0, REGISTRATION_ENABLED=false
git check-ignore -v env/production.env  # MUST match, or stop and fix .gitignore
$EDITOR deploy/Caddyfile                # replace example.com with your domain —
                                        # deploy.sh refuses while a non-comment
                                        # line still says example.com

export COMPOSE="docker compose -f docker-compose.yml -f docker-compose.prod.yml \
  --env-file env/production.env --profile core --profile frontend"

$COMPOSE config -q                      # render check — catches missing required vars
$COMPOSE pull
$COMPOSE run --rm migrate && $COMPOSE run --rm search-migrate
$COMPOSE up -d --no-build

curl -fsS http://127.0.0.1:8080/readyz  # {"status":"ok"} incl. postgres + redis
curl -fsS https://example.com/          # Caddy + certificate + frontend
nmap -Pn -p 5432,6379,8080,3000 <droplet-ip>   # must all be closed
```

`make prod-config` is the same render check; `./deploy/deploy.sh` does the whole
sequence with a pre-deploy dump and health gates and is what you should use for
every subsequent deploy.

Then, before you need them:

```bash
sudo cp deploy/vidra-backup.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now vidra-backup.timer
./deploy/backup.sh                                   # prove it works
RESTORE_CONFIRM=vidra ./deploy/restore.sh backups/<latest>.dump.gz   # on a SCRATCH stack
sudo reboot                                          # confirm every container returns
```

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
$COMPOSE config | grep -E 'DATABASE_URL|REDIS_URL'   # every DSN must name postgres/redis
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

## Everyday operations

```bash
# UPGRADE — tag a release in the component repo, wait for GHCR, then:
cd /opt/vidra && git pull --ff-only            # compose + Caddyfile only
$EDITOR env/production.env                     # VIDRA_CORE_TAG=v0.2.0
./deploy/deploy.sh                             # dump -> pull -> gated migrate -> up -> probe

# ROLLBACK — app only, no schema change (see the one-release rule below):
./deploy/rollback.sh v0.1.0

# ROLLBACK across an incompatible schema change:
$COMPOSE stop api frontend
./deploy/restore.sh backups/pre-deploy-<ts>.dump.gz
./deploy/rollback.sh v0.1.0
```

Equivalent Make targets: `make prod-config`, `make deploy`,
`make rollback TAG=v0.1.0`, `make backup`,
`make restore DUMP=… CONFIRM=1`, `make prod-logs`, `make prod-down`. All of them
honour `PROD_ENV_FILE=env/staging.env`.

`make restore` is the one that asks first: like `make nuke` it wants `CONFIRM=1`
or the word `restore` typed at an interactive prompt, and refuses outright with
no terminal (CI, a cron job, an editor task runner). It then invokes
`deploy/restore.sh --yes`, which is what satisfies that script's own refusal —
so the confirmation happens exactly once, at the layer the operator is typing at.

### Migration failed mid-deploy

golang-migrate marks its version ledger `dirty = true` when a migration fails
part-way and then **refuses every subsequent `up`** with an opaque error. Because
the api gates on `migrate: condition: service_completed_successfully`, the site
stays down and each retry fails identically. `deploy.sh` runs the two migrators as
separate gated steps precisely so you see *which* one failed before anything is
restarted.

There are **two independent ledgers**:

| Service | Table | Migrator |
|---|---|---|
| vidra-core | `public.schema_migrations` | `docker compose … run --rm migrate` |
| vidra-search | `public.vidra_search_migrations` | `docker compose … run --rm search-migrate` |

Either can go dirty without the other. Recovery, for whichever failed:

```bash
# 1. Find out where it stopped.
$COMPOSE exec postgres psql -U vidra -d vidra -c 'SELECT * FROM schema_migrations;'
#    search ledger:                              SELECT * FROM vidra_search_migrations;
#    -> version | dirty
#          42   | t

# 2. Work out what migration 42 actually did before it failed, and undo the
#    partial effect BY HAND. golang-migrate does not roll back for you — a failed
#    migration leaves whatever it managed to commit. The .up.sql is in
#    vidra-core/migrations/ (or vidra-search/migrations/).
$COMPOSE exec postgres psql -U vidra -d vidra

# 3. Point the ledger at the last CLEAN version, i.e. N-1.
#    CAUTION: `docker compose run <service> <args>` REPLACES the service's whole
#    command, so -path and -database must be repeated in full — the compose
#    definition's flags are NOT inherited.
DSN='postgres://vidra:<POSTGRES_PASSWORD>@postgres:5432/vidra?sslmode=disable'
$COMPOSE run --rm migrate -path=/migrations -database="$DSN" force 41
#    search ledger: use the search-migrate service and append
#    &x-migrations-table=vidra_search_migrations to the DSN.
#    Equivalent, and simpler if the DSN is awkward to quote:
#      UPDATE schema_migrations SET version = 41, dirty = false;

# 4. Re-run the normal migrator (its own -path/-database from compose).
$COMPOSE run --rm migrate
```

Never `force` to `N` — that claims the broken migration succeeded and the next
deploy will build on a schema that does not exist.

Note that **none** of the 101 up-migrations use `CREATE INDEX CONCURRENTLY` and
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

The frontend image bakes `NEXT_PUBLIC_API_BASE_URL` at **build** time (Next.js
inlines `NEXT_PUBLIC_*` into the client bundle), so a restart cannot repoint it.
CI publishes **one** `vidra-user` image per release, built with the production
API URL from the `NEXT_PUBLIC_API_BASE_URL` repository variable — it does *not*
build a separate image per environment. A staging host with a different origin
therefore needs its own build. With the single-origin Caddyfile this is usually
a non-issue, because `NEXT_PUBLIC_API_BASE_URL` equals the site origin.

---

## Backups & restore

`./deploy/backup.sh` (and the systemd timer) writes
`backups/vidra-<UTC>.dump.gz` — a custom-format `pg_dump`, verified with
`pg_restore -l` before it is kept, retained **14 daily + 8 weekly**, with a
`backups/last_success` marker.

- **One dump covers both services.** vidra-search shares the core database in the
  `search` schema, so a database-wide dump already includes it.
- **Off-site is opt-in and you must opt in.** Set `BACKUP_RCLONE_REMOTE` (with
  `rclone` installed) or `BACKUP_S3_URI` + `BACKUP_S3_ENDPOINT` (with the `aws`
  CLI). Use a bucket in a **different region from the media Space**.
- **Alert on a *missing* backup**, not just a failing one. Set
  `HEALTHCHECKS_URL=https://hc-ping.com/<uuid>`; the script pings `/start`,
  `/fail` on any error, and success at the end, so a droplet that stops running
  the timer at all still pages you.
- **Media** is not in the dump. With `STORAGE_BACKEND=s3` use the object store's
  versioning/replication; with `local`, snapshot the `media_data` volume on the
  same cadence so rows and files stay consistent.
- **Redis** is a cache + rate-limit/dedup store: no backup needed, and it may be
  flushed at any time.
- **Restore drill (quarterly).** Restore the latest dump into a scratch stack,
  boot, and click through login / watch / upload.

`./deploy/restore.sh` refuses to run without `--yes` or
`RESTORE_CONFIRM=<database name>`. It stops api + search + frontend (search
shares the database, so leaving it up means it reconnects mid-restore), drops and
recreates the database, restores with `-j4`, runs both migrators to bring the
schema to HEAD, restarts, and polls `/readyz`.

---

## Health & monitoring

- Probes: `GET /healthz` (liveness), `GET /readyz` (readiness incl.
  postgres/redis). Point an external uptime check at `https://<domain>/healthz`
  **and** at the site root — an internal check cannot tell you the certificate
  expired.
- Operator snapshot: `GET /api/v1/admin/system` (admin JWT) — status, versions,
  uptime, dependency health, effective non-secret config.
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
