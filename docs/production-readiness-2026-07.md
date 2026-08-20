<!-- Generated 2026-07-28 by a 17-agent audit (8 dimensions, adversarially verified). Top blockers re-verified by hand. -->

# VIDRA — PRODUCTION READINESS PLAN (DigitalOcean)

## VERDICT

The application is production-grade; the deployment is not. Every hard problem — auth, SSRF, path traversal, durable job queues, fail-closed malware scanning, non-root images, structured logging, RED metrics, quota enforcement, HLS/Range serving, CDN policy — is already solved and tested well above the norm for self-hosted software. What is missing is the last mile between "the code is correct" and "a droplet runs it safely": the shipped `env/production.env.example` **cannot boot** (JWT_SECRET has no path into the container; ClamAV is enabled pointing at a hostname that does not exist in a profile nobody starts), the documented deploy command **publishes Postgres with password `vidra` and an unauthenticated Redis to the public internet**, and there is **no backup script, no deploy script, no rollback, no restart policy, no TLS service, and no image tags** — the entire deploy story is one `up -d --build` line. On top of that, the blanket 120-req/min per-IP limiter has no media exemption and no client-IP forwarding from the Next.js server, so a single frontend container consumes one shared bucket and the site starts 429-ing at roughly two server-rendered page loads per second.

The true blockers are four: **(1) config plumbing** — the api compose `environment:` allow-list is missing ~60 keys including JWT_SECRET; **(2) network exposure** — no production compose overlay, everything on 0.0.0.0; **(3) rate-limit/timeout shape** — the limiter and the 30s request deadline make normal browsing and normal uploads fail; **(4) operational floor** — no backups, no deploy/rollback, no restart policies. All four are days of work, not weeks. Nothing here requires re-architecting anything.

---

## STATE AS OF 2026-08-02

Branch `chore/prod-readiness-2026-07` (meta-repo) plus the matching work already on
`vidra-core` / `vidra-user` closes the launch gate **except for step 4.3**. Statuses
below were checked against the tree, not against this document.

| Step | Status | Evidence / what remains |
|---|---|---|
| 0 — stop the secrets leak | ✅ done | `.gitignore` ignores `env/*.env` **and** `env/*.env.bak` — `deploy/rollback.sh` writes the latter, and the original glob did not match it. meta-ci asserts both, and that `*.env.example` stays tracked. |
| 1 — config reaches the container | ✅ done | All **129** `getEnv*("KEY"` sites in `vidra-core/internal/config/config.go` resolve to an entry in the rendered api `environment:` map; meta-ci now fails on any that does not. DSN indirection landed. |
| 2 — bootable env templates | ✅ done | Both templates rewritten. meta-ci's new `boot` job writes a production env file with dummy secrets, boots the api with `VIDRA_ENV=production` and asserts `/readyz` 200 — the plan's "Verify" for this step. |
| 3 — `docker-compose.prod.yml` | ✅ done | Overlay ships. **Correction to the recipe above:** the port closes are `ports: !reset []` / `ports: !override [...]`, not `ports: []` — Compose *merges* sequence fields across a `-f` chain, so a bare `[]` appends nothing and the base publish survives. That raises the floor to Compose ≥ 2.24, and `deploy/{deploy,rollback,restore}.sh` now refuse to run on anything older (an old Compose ignores the tags silently and leaves Postgres/Redis on `0.0.0.0`). |
| 4.1 / 4.2 / 4.4 / 4.5 | ✅ done | `vidra-core/Dockerfile` stamps `VERSION`/`COMMIT`/`BUILD_DATE`; the frontend release build fails loudly on an unset `NEXT_PUBLIC_API_BASE_URL`; `.ralph/specs/environments.md §2` corrected; `bootstrap.sh` takes `VIDRA_REF=<tag\|sha>` and detaches all three components onto it (default behaviour unchanged). |
| **4.3 — tag ×3, cut GHCR releases** | ⚠️ **first cut done, superseded** | `0.1.0` (**unprefixed** tag, marked pre-release) was cut in `vidra-core` / `vidra-user` / `vidra-search` on 2026-08-02 and all three images published. They were built from **pre-merge `main`**, so none of them carries this branch: in particular `vidra-user:0.1.0` was built by the old workflow's `\|\| 'http://localhost:8080'` build-arg fallback (the repository variable is unset), which is exactly the silent breakage step 4.2 exists to prevent. **`v0.1.1`, cut from `main` after this branch merges, is the first deployable set** and is what every `image:` line here should pin; treat `0.1.0` as archival. |
| 5 — request shape, fail-secure, requeue | ✅ done | `IPExtractor` set in `NewServer`; media/stream deadline exemptions; the two production refusals at `config.go:950,953`; `internal/jobrecovery` does the boot-time requeue. |
| 6 — deploy / rollback / backup / restore | ⚠️ done **except the drill** | All four scripts, the systemd `.service`/`.timer`, the Make wrappers, the dirty-migration runbook and the `make nuke` guard ship (and `make restore` now supplies `restore.sh --yes` behind its own `CONFIRM=1`/prompt, so it can actually succeed). **`deploy/restore.sh` has still never been run against a real dump.** |
| 7 — host prerequisites + firewall + Caddyfile | ✅ done | `deploy/README.md` "Host prerequisites"; Caddyfile proxies the compose service names, 404s `/metrics`, keeps `encode` off the api routes. `deploy.sh` now refuses to run while a **non-comment** line of `deploy/Caddyfile` still says `example.com`. |
| 8 — first-boot ordering | ✅ done | `deploy/README.md` "First boot — do these in order". |
| 9 — single origin | ✅ done | Single-origin Caddyfile, split-subdomain variant kept as a documented (and discouraged) alternative; `vidra-user/app/robots.ts` exists. |

**CI.** `.github/workflows/meta-ci.yml` now carries every "Verify:" line this plan
asked for: the gitignore assertions (step 0), `shellcheck` over `bootstrap.sh` **and**
`deploy/*.sh`, a render of the production `-f` chain with dummy values for every
`${VAR:?}` (step 3), an assertion on the *rendered* result that postgres/redis/search
publish nothing and api/frontend publish only on `127.0.0.1` — because a Compose
older than 2.24 ignores `!reset` silently and the render alone would still pass —
the `getEnv*`-vs-rendered-compose drift check (step 1), and the boot-to-`/readyz`
job (step 2, which passes an explicit `-f docker-compose.yml` so the dev override
cannot leak into what it calls a production boot).

### Still open, in order

1. **Step 4.3 — the `v0.1.1` releases.** The `0.1.0` pre-releases above do not carry
   this branch. Cut `v0.1.1` in `vidra-core`, `vidra-user` and `vidra-search` from
   post-merge `main` and confirm three images land in GHCR. `vidra-user`'s release
   build will refuse to run until the repository variable
   `NEXT_PUBLIC_API_BASE_URL` is set to the real public api origin — by design; do
   not restore the loopback fallback to get past it.
2. **The restore drill.** Run `./deploy/restore.sh` once against a real dump on a
   scratch stack. It is the only part of step 6 no script can prove, and neither it
   nor the 101 down-migrations have ever been exercised end to end.
3. **The entire "DO IN THE FIRST WEEK" list below is untouched**, with two
   exceptions that landed as documentation on this branch: the **secret-rotation
   table** and the **Email** section are now in `deploy/README.md`, and
   `FEATURE_LIVE_ENABLED=false` is in the production template. Everything else is
   open — verified absent: no `RUNBOOK.md`, no `/readyz` storage probe, no
   `TRANSCODE_JOB_TIMEOUT`, no `POST /api/v1/admin/email/test`, no alerting or
   `monitoring` profile, no Dependabot security alerts, CI/prod image skew and the
   Node major skew unresolved, contract drift unscheduled, HLS renditions still
   uncounted in quota. Budget the 3–4 days the last section allocates; do not fold
   them into the launch gate.
4. **"SOON AFTER (medium / low)" is untouched** by design.

---

## MUST DO BEFORE LAUNCH

Ordered by dependency. Do not reorder — step 1 gates step 2, and step 4 depends on 2 and 3.

### 0. Stop the secrets leak first (5 minutes, do this before you write a single real secret)

`/Users/yosefgamble/github/vidra/.gitignore` has no `env` entry — `env/production.env` is untracked-but-committable, and `deploy/README.md:12` tells the operator to create exactly that file.

```
# append to /Users/yosefgamble/github/vidra/.gitignore
env/*.env
!env/*.env.example
```
Verify: `git check-ignore -v env/production.env` must match; `git ls-files env/` must list only `*.example`. Add a `meta-ci.yml` step asserting `git check-ignore -q env/production.env` so it cannot regress.

---

### 1. Make the config actually reach the container (`vidra-core/docker-compose.yml`)

This is the single reason the documented first deploy fails. The api service's `environment:` map at `vidra-core/docker-compose.yml:217-402` is an explicit allow-list and there is **no `env_file:` anywhere in the stack** — so `--env-file` only feeds compose substitution. `JWT_SECRET` has no substitution target at all; `config.go:637` falls back to the dev default and `:897-903` hard-exits in production.

Add to the api `environment:` map (use `${VAR:?message}` for the two that must never be defaulted):

```yaml
JWT_SECRET: ${JWT_SECRET:?JWT_SECRET is required (openssl rand -base64 48)}
JWT_ACCESS_TTL: ${JWT_ACCESS_TTL:-15m}
JWT_REFRESH_TTL: ${JWT_REFRESH_TTL:-720h}
MFA_KEY_KEK: ${MFA_KEY_KEK:-}
LOG_LEVEL: ${LOG_LEVEL:-info}
LOG_FORMAT: ${LOG_FORMAT:-json}
METRICS_ENABLED: ${METRICS_ENABLED:-false}
OTEL_ENABLED: ${OTEL_ENABLED:-false}
OTEL_SERVICE_NAME: ${OTEL_SERVICE_NAME:-vidra-core}
OTEL_EXPORTER_OTLP_ENDPOINT: ${OTEL_EXPORTER_OTLP_ENDPOINT:-}
OTEL_EXPORTER_OTLP_PROTOCOL: ${OTEL_EXPORTER_OTLP_PROTOCOL:-http/protobuf}
RATE_LIMIT_REQUESTS: ${RATE_LIMIT_REQUESTS:-120}
AUTH_RATE_LIMIT_REQUESTS: ${AUTH_RATE_LIMIT_REQUESTS:-10}
HTTP_BODY_LIMIT: ${HTTP_BODY_LIMIT:-}
HTTP_REQUEST_TIMEOUT: ${HTTP_REQUEST_TIMEOUT:-30s}
HTTP_READ_TIMEOUT / HTTP_WRITE_TIMEOUT / HTTP_SHUTDOWN_TIMEOUT
UPLOAD_MAX_SIZE: ${UPLOAD_MAX_SIZE:-2G}
STORAGE_LOCAL_ROOT: ${STORAGE_LOCAL_ROOT:-/app/data/media}
REGISTRATION_ENABLED: ${REGISTRATION_ENABLED:-true}
QUARANTINE_NEW_UPLOADS, FEATURE_LIVE_ENABLED, FEATURE_UPLOADS/IMPORTS/COMMENTS_ENABLED
INSTANCE_DESCRIPTION / INSTANCE_TERMS_URL / INSTANCE_PRIVACY_URL / INSTANCE_CONTACT_EMAIL
ATPROTO_ENABLED / ATPROTO_KEY_KEK / ATPROTO_LOGIN_ENABLED
TRANSCODE_HOLD_TIMEOUT, SEARCH_*_TIMEOUT_MS, CHANNEL_SYNC_COOLDOWN
```

Same pass, meta `docker-compose.yml` frontend service (currently only `NODE_ENV` + `INTERNAL_API_BASE_URL`): add `LOG_LEVEL`, `OTEL_ENABLED`, `OTEL_SERVICE_NAME: ${FRONTEND_OTEL_SERVICE_NAME:-vidra-user}`, `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_EXPORTER_OTLP_PROTOCOL`. Same pass, search service: add `LOG_LEVEL`, `LOG_FORMAT`, `METRICS_ENABLED`, `EVENT_RETENTION_DAYS`, `MODEL_DIR`, plus a `search_models:/var/lib/vidra-search/models` volume.

Also make the DSNs overridable — four literal sites block DO Managed Postgres entirely:
- `vidra-core/docker-compose.yml:220` → `DATABASE_URL: ${DATABASE_URL:-postgres://...}`
- `vidra-core/docker-compose.yml:221` → `REDIS_URL: ${REDIS_URL:-redis://redis:6379/0}`
- `docker-compose.yml:88-89` (search; keep redis DB index **1**)
- the two migrate services' `-database=` args (`vidra-core:181`, `docker-compose.yml:66` — preserve `&x-migrations-table=vidra_search_migrations`)

> **Superseded 2026-08-19:** both migrators are now embedded in the service images (`migrate up` on the api / search binary), so there are no `-database=` args and no `x-migrations-table` URL parameter — the ledger table names are compiled in. Both one-shots read the same `${DATABASE_URL}` as their service, which satisfies the overridable-DSN goal above. See `deploy/README.md`. The rest of this section stands as the 2026-07 audit recorded it.

**Verify:** `docker compose --env-file env/production.env --profile core --profile frontend config | grep -c JWT_SECRET` must return ≥1. Add a meta-ci step that diffs `getEnv*("KEY"` in `vidra-core/internal/config/config.go` against the rendered compose environment and fails on any key with no consumer — this class of rot is invisible to every existing gate.

---

### 2. Rewrite `env/production.env.example` and `env/staging.env.example` so they boot

The shipped templates are the documented starting point and they produce three consecutive fatal config errors.

| Line | Now | Change to |
|---|---|---|
| `production:16-17` | `MALWARE_SCAN_ENABLED=true` + `# CLAMAV_ADDR=clamd:3310` | `MALWARE_SCAN_ENABLED=false` with a commented opt-in block: `# MALWARE_SCAN_ENABLED=true`, `# CLAMAV_ADDR=clamav:3310` (**`clamav`, not `clamd`** — compose service name), `# and add --profile scan; clamd needs ~2 GiB RAM` |
| `production:19` | S3 keys commented, no region | Uncommented DO Spaces block: `STORAGE_S3_ENDPOINT=nyc3.digitaloceanspaces.com` (host only, **no scheme** — rejected at `s3.go:74-76`), `STORAGE_S3_REGION=nyc3`, `STORAGE_S3_BUCKET=`, `STORAGE_S3_ACCESS_KEY=`, `STORAGE_S3_SECRET_KEY=` |
| `production:22` | `# JWT_SECRET=` | uncommented, `openssl rand -base64 48` in the comment |
| `production:29-30` | `SEARCH_HTTP_PORT=8081`, `# SEARCH_INTERNAL_SECRET=` | **delete** `SEARCH_HTTP_PORT` (it forces the internet-facing publish the runbook forbids), uncomment `SEARCH_INTERNAL_SECRET=` with `openssl rand -hex 32` |
| new | — | `POSTGRES_USER=vidra`, `POSTGRES_PASSWORD=<openssl rand -base64 32>`, `POSTGRES_DB=vidra`, `REDIS_PASSWORD=<...>` |
| new | — | `MFA_KEY_KEK=<openssl rand -base64 32>` — **unset means every TOTP secret is stored in plaintext**, warned about only at `cmd/api/main.go:376` |
| new | — | `INSTANCE_NAME=` — default is `Vidra (dev)` and it is served publicly at `GET /api/v1/instance` and in NodeInfo |
| new | — | `METRICS_ENABLED=true`, `LOG_LEVEL=info`, `LOG_FORMAT=json` |
| new | — | `INSTANCE_DEFAULT_QUOTA_BYTES=5368709120` (5 GiB) — default is 0 = unlimited, with open registration |
| new | — | `RATE_LIMIT_REQUESTS`, `UPLOAD_MAX_SIZE`, `HTTP_REQUEST_TIMEOUT`, `VIDRA_CORE_TAG` / `VIDRA_USER_TAG` / `VIDRA_SEARCH_TAG` |
| new | — | commented `DATABASE_URL=postgresql://doadmin:...@db-...ondigitalocean.com:25060/defaultdb?sslmode=require` and `REDIS_URL=rediss://...` for the managed-DB path |
| `production:24` | `REGISTRATION_REQUIRE_APPROVAL=false` | `REGISTRATION_ENABLED=false` (open it deliberately after the owner account exists — see step 8) |

Also append the 15 keys missing from `vidra-core/.env.example` entirely: `YTDLP_IMPORT_ENABLED/PATH/TIMEOUT/MAX_HEIGHT/PROXY` (copy the egress-proxy warning from the compose comment), `CHANNEL_SYNC_*`, `HTTP_READ/WRITE/SHUTDOWN_TIMEOUT`, `TRANSCODE_HOLD_TIMEOUT`, `PEERTUBE_IMPORT_MEDIA_MODE`.

**Verify:** add a meta-ci job that renders each template with dummy secrets, boots the api, and asserts `/readyz` 200.

---

### 3. Create `docker-compose.prod.yml` — one file closes six findings

There is no production overlay today; the dev compose *is* the prod compose. Create `/Users/yosefgamble/github/vidra/docker-compose.prod.yml`:

```yaml
x-logging: &logging
  driver: json-file
  options: { max-size: "10m", max-file: "5" }

services:
  postgres:
    ports: []                       # nothing off the compose network needs it
    restart: unless-stopped
    logging: *logging
    command: ["postgres","-c","shared_buffers=2GB","-c","effective_cache_size=6GB","-c","max_connections=100"]
  redis:
    ports: []
    restart: unless-stopped
    logging: *logging
    command: ["redis-server","--save","","--appendonly","no",
              "--requirepass","${REDIS_PASSWORD:?}",
              "--maxmemory","256mb","--maxmemory-policy","allkeys-lru"]
  api:
    image: ghcr.io/yegamble/vidra-core:${VIDRA_CORE_TAG:?}
    ports: ["127.0.0.1:${HTTP_PORT:-8080}:8080"]
    restart: unless-stopped
    logging: *logging
    security_opt: ["no-new-privileges:true"]
    cpus: '7.0'                     # N-1 cores; ffmpeg runs IN this container
    mem_limit: 6g
    environment:
      TMPDIR: /scratch              # redirects all 9 MkdirTemp/CreateTemp sites at once
    volumes:
      - media_data:/app/data        # only load-bearing if STORAGE_BACKEND=local
      - transcode_tmp:/scratch
      - live_hls:/live-hls
  frontend:
    image: ghcr.io/yegamble/vidra-user:${VIDRA_USER_TAG:?}
    ports: ["127.0.0.1:${FRONTEND_PORT:-3000}:3000"]
    logging: *logging
    healthcheck:
      test: ["CMD","wget","-qO-","http://127.0.0.1:3000/"]
      interval: 15s
      timeout: 5s
      retries: 5
      start_period: 20s
  search:
    image: ghcr.io/yegamble/vidra-search:${VIDRA_SEARCH_TAG:?}
    ports: []
    logging: *logging
    volumes: [search_models:/var/lib/vidra-search/models]
  caddy:
    image: caddy:2-alpine
    ports: ["80:80","443:443"]
    restart: unless-stopped
    logging: *logging
    volumes:
      - ./deploy/Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy_data:/data            # ACME account + certs MUST survive up -d
      - caddy_config:/config

volumes: { media_data: , transcode_tmp: , search_models: , caddy_data: , caddy_config: }
```

Then change `docker-compose.yml:33-38` frontend `depends_on: api` from `condition: service_started` → `service_healthy`, and add a compose-level `healthcheck:` to api mirroring `vidra-core/Dockerfile:41-42` but hitting `/readyz`.

Change `deploy/README.md:13` and `README.md:101` from `up -d --build` to the explicit `-f` chain (note: an explicit chain disables auto-loading of `docker-compose.override.yml`, which is what you want in prod):

```
docker compose -f docker-compose.yml -f docker-compose.prod.yml \
  --env-file env/production.env --profile core --profile frontend pull
docker compose ... up -d --no-build
```

**Why the loopback binds are the only real fix:** Docker writes DOCKER-USER iptables rules *ahead of* ufw's chain, so a host firewall does not filter published ports. The technique is already used correctly in the same file for IPFS RPC (`vidra-core/docker-compose.yml:501-502, 560, 622`) — it simply was not applied to the core services. Caddy proxies `localhost:8080`/`localhost:3000`, so loopback binding breaks nothing.

---

### 4. Tag a release so images exist to pull and roll back to

Nothing consumes GHCR today — all three `publish-container.yml` workflows are gated on `on: release: published` and **have never fired** (`git tag | wc -l` = 0 in all four repos). Step 3's `image:` lines are inert until this lands.

1. `vidra-core/Dockerfile:13` — add `ARG VERSION/COMMIT/BUILD_DATE` and change `-ldflags="-s -w"` to include `-X .../internal/version.Version=$VERSION -X ...Commit=$COMMIT -X ...Date=$BUILD_DATE`. The machinery already exists (`internal/version/version.go:14-21`, `Makefile:10-14`) — the container throws it away, so `GET /api/v1/admin/system` will report "0.1.0 / unknown" on the droplet forever otherwise. Pass the args from `publish-container.yml`.
2. `vidra-user/.github/workflows/publish-container.yml:65` — **delete the `|| 'http://localhost:8080'` fallback** so the release build fails loudly when `vars.NEXT_PUBLIC_API_BASE_URL` is unset. Set that repo variable to your production URL first. Without this, the pulled frontend image ships a browser bundle that calls `localhost:8080` for every client-side action.
3. Tag `v0.1.0` and cut a GitHub Release in vidra-core, vidra-user, vidra-search. Confirm three images land in GHCR with `:v0.1.0` and `:sha-<long>`.
4. Correct the two false doc claims: `.ralph/specs/environments.md:68` and `deploy/README.md:31-32` both assert CI publishes `vidra-user:<env>-<sha>` per environment. It does not — one image, built with the production API URL. Either matrix the job or fix the docs (fix the docs).
5. `bootstrap.sh:15` does `git pull --ff-only` with no ref pinning — add a ref argument so the host can check out a tag.

---

### 5. Fix the two request-shape defects that break normal use (vidra-core code)

These are the least obvious blockers and the most user-visible.

**5a. Rate limiter.** `internal/httpapi/server.go:853` applies `s.rateLimit(s.limiter)` to the entire `/api/v1` group with no Skipper, budget 120/60s keyed purely on `c.RealIP()`. Two compounding failures:
- One home page = 1 feed call + 20 thumbnails from `${apiBaseUrl}/api/v1/videos/{id}/thumbnail`; HLS playback adds ~10 segments/min plus prefetch bursts. A single normal user exceeds 120/min in their first minute.
- **Worse:** all Next.js SSR fetches go to `INTERNAL_API_BASE_URL=http://api:8080` with **no client IP forwarded** (`grep x-forwarded-for vidra-user/lib vidra-user/app` → nothing). Every visitor shares the frontend container's single bucket — the instance 429s server-rendered pages at ~2 renders/sec regardless of who is browsing.

Fix: (i) give media GETs a Skipper or a sibling group with a ~3000/min limiter — `/videos/:id/thumbnail`, `/videos/:id/hls/*`, `/videos/:id/storyboard.*`, `/videos/:id/download/hls/:height`, `/live/:id/hls/*`, `/playlists/:id/thumbnail`, `/remote-videos/:id/thumbnail`; (ii) trust-list the compose-network source in `internal/httpapi/ratelimit.go:21` **or** forward `X-Forwarded-For` from `vidra-user/lib/*.server.ts`; (iii) **in the same commit**, set `e.IPExtractor = echo.ExtractIPFromXFFHeader(echo.TrustLoopback(true), echo.TrustPrivateNet(true))` in `NewServer` before `s.routes()`. Echo v4.15.4's default `RealIP()` reads the *first* XFF entry from any caller, so today the 10/min auth limiter, the 1/hour contact limiter and the video-password limiter are all defeated by one header — and there is no per-account lockout to fall back on. Landing (ii) without (iii) makes spoofing free.

**5b. Request deadline.** `internal/httpapi/server.go:684` applies a hard 30s `context.WithTimeout` to every request except `/admin/jobs/events`. Resumable chunks are 8 MiB — that requires a sustained ~2.2 Mbit/s upstream to complete, so typical residential uploaders retry-loop forever and mobile uploaders can never finish. Serving is cut off mid-stream too (`videos.go:1284` honours the same context). Extend the exemption list in `requestDeadline` (`server.go:776-791`) to the chunk PUT route, the direct upload/replace POSTs, and the media GET routes. While there: `HTTPReadTimeout`/`HTTPWriteTimeout` are parsed at `config.go:630-631` and **never applied** (`s.echo.Start` uses echo's default server) — either wire them into `s.echo.Server` or delete them so they stop lying.

**5c.** Same code pass, two 6-line fail-secure additions inside the existing `if c.Environment == "production"` block at `config.go:897`:
```go
if c.DevMailCaptureEnabled { return fmt.Errorf("config: DEV_MAIL_CAPTURE_ENABLED must not be set in production") }
if c.ImportAllowPrivateURLs { return fmt.Errorf("config: HTTP_IMPORT_ALLOW_PRIVATE_URLS must not be set in production") }
```
`deploy/README.md:26` already *claims* production refuses these. It does not — `server.go:963` registers `GET /api/v1/dev/email-token` with **no auth middleware**, which returns a live password-reset token for any address. `env/qa.env.example:11-12` sets both true, and `Makefile:94-95` sets them for e2e, so a copy-paste is one keystroke from admin takeover.

**5d.** Boot-time requeue in `cmd/api/main.go` before the workers start:
```sql
UPDATE transcode_jobs SET state='pending', attempts=attempts+1 WHERE state='running';
-- same for import_jobs, caption_jobs, account_exports, peertube_import_runs
UPDATE channel_syncs SET state='idle' WHERE state='syncing';
```
Every deploy, reboot and OOM kill currently strands the in-flight transcode permanently: `HasLiveTranscodeJob` keeps seeing the `running` row, so `POST /admin/videos/:id/transcoding` returns 409 forever and the partial-unique-index makes re-enqueue a no-op. Since you will deploy repeatedly during launch week, this bites immediately. (Worse than it looks: `DrainJobs` passes the *cancelled* ctx into `recordFailure`, so on shutdown even the reschedule write fails silently. Use `context.WithoutCancel(ctx)` for the bookkeeping writes at `internal/transcode/service.go:284-291, 424`.) The lease-column refactor mirroring `media_ipfs_pins.sql:161-173` is the durable version — do it in week one.

---

### 6. Ship the deploy / rollback / backup scripts

Today `ls deploy/` returns exactly `Caddyfile` and `README.md`. There is no script, no timer, no `make backup`, no `pg_restore` automation anywhere in four repos, and grep for "rollback" across all docs returns **zero hits**.

**`deploy/backup.sh`** — `set -euo pipefail`; resolve the container with `docker compose ... ps -q postgres` (removes the `<postgres>` placeholder from `README.md:42`); `pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB"` → gzip → `rclone/aws s3 cp` to a Spaces bucket **in a different region from the media Space**; prune to the 14-daily/8-weekly retention already written at `README.md:43`; touch a `last_success` marker and ping healthchecks.io so a *missing* backup alerts. Plus `deploy/vidra-backup.timer` + `.service` (OnCalendar=daily) and a `backup:` target in the meta Makefile.

**`deploy/restore.sh`** — stop `api`; `dropdb --force` + `createdb` (do **not** `--clean` into a live DB); `pg_restore -j4`; run the `migrate` service to confirm schema version; start api; assert `/readyz` 200.

**`deploy/deploy.sh`** — the ordering matters:
1. `pg_dump` to `backups/pre-deploy-$(date +%FT%H%M%S).dump` — `set -e` so a failed dump aborts the deploy
2. `docker compose ... pull`
3. `docker compose ... run --rm migrate` and `run --rm search-migrate` as **discrete gated steps** with `$?` checks (do not let `up -d` fan out)
4. `up -d --no-build`
5. poll `http://127.0.0.1:${HTTP_PORT}/readyz` and `:${FRONTEND_PORT}/` for up to 120s, exit non-zero on failure

**`deploy/rollback.sh <tag>`** — rewrite the three tag vars, `pull && up -d --no-build`.

Add a **"Migration failed mid-deploy"** subsection to `deploy/README.md`. golang-migrate sets `schema_migrations.dirty=true` on a partial failure and refuses every subsequent `up` — and because `api` gates on `migrate: condition: service_completed_successfully`, the site stays down and each retry fails identically with an opaque error. Document `migrate ... version` → `migrate ... force <N-1>` → re-run up, and note the search ledger (`vidra_search_migrations`) can go dirty independently. State the policy: schema changes stay backward-compatible for one release, so an app rollback never needs a schema rollback; a true rollback is restore-the-pre-deploy-dump.

Also add `CONFIRM=1` (or a prompt) to `Makefile:79-80` — `make nuke` is `down -v`, one character from `make down`, and it deletes `postgres_data`.

**Run `deploy/restore.sh` once against a real dump before launch.** 101 down migrations have never been executed and the restore path has never been exercised end to end.

---

### 7. Host prerequisites + firewall (docs, but load-bearing)

Add a **"Host prerequisites"** section at the top of `deploy/README.md`, before the current `:7` heading. `grep -i 'ufw|firewall|unattended|ssh'` across the README, deploy README and environment spec returns **zero**:

- Docker Engine ≥ 24, **Compose ≥ 2.20** — state why: `docker-compose.yml:23` uses the `include:` key, and an older compose gives a cryptic parse error with no version floor to check against
- `sudo systemctl enable --now docker` (restart policies are useless without it)
- `/etc/docker/daemon.json` = `{"log-driver":"json-file","log-opts":{"max-size":"10m","max-file":"5"}}` + `systemctl restart docker` — the default json-file driver is uncapped, and every request emits a JSON line on the same disk as Postgres and media
- **DigitalOcean Cloud Firewall** (sits outside the droplet, not bypassable by Docker) allowing only 22/80/443
- An explicit warning that **host ufw does not filter Docker-published ports** — DOCKER-USER precedes ufw — and that the 127.0.0.1 binds from `docker-compose.prod.yml` are the actual control
- `unattended-upgrades`; SSH key-only with `PermitRootLogin no`
- A 4 GB swapfile
- A **Sizing** table (numbers in the recipe below)

Rewrite `deploy/Caddyfile` to proxy the compose service names `api:8080` / `frontend:3000` instead of `localhost:*`; add `@metrics path /metrics` + `respond @metrics 404` so enabling `METRICS_ENABLED` later cannot publish the scrape (it is root-mounted with no auth at `server.go:806`); drop `encode gzip` from the api site or scope it off media paths so Range/206 passes through untouched per `README.md:77-79`.

---

### 8. First-boot ordering (5 minutes, but irreversible if you get it wrong)

`internal/auth/service.go:244-246` grants **admin to the first account created on an empty users table**, across all four signup paths. `REGISTRATION_ENABLED` defaults true and there is no CLI to create or promote an admin (`ls vidra-core/cmd` → `api`, `peertube-import` only). Recovery from a signup bot claiming ownership is raw SQL.

Add a numbered **"First boot"** section at the very top of `deploy/README.md`: ship `REGISTRATION_ENABLED=false`, bring the stack up, register the owner account over the loopback port or before DNS propagates, verify the admin surface, *then* flip registration on. Step 1 makes `REGISTRATION_ENABLED` settable from the env file for the first time.

---

### 9. Decide the origin topology — **use a single domain** (public launch only)

`internal/httpapi/distribution.go:61` builds watch/embed/channel URLs from `cfg.PublicBaseURL`, but the *same* field is appended with API paths for OAuth callbacks (`oauth.go:136`), NodeInfo (`federation.go:48`) and ActivityPub/atproto actor URIs (`main.go:1103/1118/1168`). `config.go:1009` forbids a path component, so with the shipped `PUBLIC_BASE_URL=https://api.example.com` + frontend on `example.com`, every RSS item link, every `<loc>` in `/sitemap.xml` and every oEmbed iframe src 404s. Flipping it to the frontend origin breaks OAuth and federation instead.

**The cheapest correct fix is topological, not code:** serve everything from `example.com` and let Caddy route by path.

```
example.com {
    encode gzip
    @api path /api/* /healthz /readyz /version /sitemap.xml /feeds/* /nodeinfo/* /.well-known/*
    reverse_proxy @api api:8080
    @metrics path /metrics
    respond @metrics 404
    reverse_proxy frontend:3000
}
```
Then `PUBLIC_BASE_URL=https://example.com` and `NEXT_PUBLIC_API_BASE_URL=https://example.com` are both correct, CORS becomes same-origin, and the split-origin bug disappears with no Go change. Frontend `/videos/{id}` and api `/api/v1/videos/{id}` do not collide.

If you insist on two subdomains, add `PublicWebBaseURL` (`PUBLIC_WEB_BASE_URL`, defaulting to `PublicBaseURL`) and have `distribution.go:61 webOrigin()` return it — but keep `thumbnailURL` at `:69` on `PublicBaseURL`, since that path *is* an API route.

Also add `vidra-user/app/robots.ts` disallowing `/studio /settings /admin /messages /library /history` and pointing at `/sitemap.xml`. **Sequence this after the origin decision** — a discoverable sitemap full of 404s is worse than no sitemap.

*Skippable for a small private launch:* the whole of step 9.

---

## DO IN THE FIRST WEEK (high)

- **Alerting.** Nothing scrapes the metrics that already exist. Point a free external uptime check (DO Uptime / Better Stack / healthchecks.io) at `https://example.com/healthz` and the site root with SMS on failure. Then add a `monitoring` compose profile: `prom/prometheus` scraping `api:8080/metrics` + `search:8080/metrics`, node-exporter, and alert rules on `vidra_job_oldest_queued_age_seconds > 900`, `vidra_job_stale_running > 0`, `rate(vidra_http_requests_total{status_class="5xx"}[5m])`, `up == 0`. Bind published ports to 127.0.0.1.
- **DO Monitoring alerts** on CPU >80% (5 min), disk >85%, memory >90%, bandwidth.
- **`/readyz` storage probe.** `health.go:39-58` checks only postgres and redis. With `STORAGE_BACKEND=s3`, a Spaces credential rotation or regional incident leaves the probe green through a total media outage. Add a bounded 2s `Exists(ctx, "<sentinel>")` component (report degraded-but-200, don't pull the only node out of rotation) plus a `syscall.Statfs` free-space component — the helper already exists at `internal/peertubeimport/sourcestorage.go:108-114`, just promote it out of that package.
- **Transcode job timeout.** Every ffmpeg exec inherits an undeadlined context. `runTranscodeWorker` calls `DrainJobs` in an unbounded inner loop, so one hung job wedges the worker goroutine's ticker entirely — with `transcoding_concurrency=1` that is *all* transcoding, permanently, with no error logged. Add `TRANSCODE_JOB_TIMEOUT` (default 4h) wrapping each job, keeping the original ctx for the bookkeeping writes.
- **Enable Dependabot security alerts** — off on all four repos (`gh api -X PUT repos/yegamble/<repo>/vulnerability-alerts` + `.../automated-security-fixes`). Secret scanning + push protection are already on. Add `govulncheck ./...` to `make ci` in vidra-core and vidra-search, `npm audit --audit-level=high` to frontend-ci.
- **Fix the CI/prod version skew.** vidra-core CI tests on `postgres:16-alpine` / `redis:7-alpine` / migrate `v4.17.1` while production runs `postgres:18-alpine` / `redis:8-alpine` / `v4.19.1` — six line-pairs in `backend-ci.yml:28,41,63`, `backend-integration.yml:31,44,99`, `bench-fuzz.yml:37,50,71`. vidra-search already got this right. Then add a `ci-guard.yml` assertion comparing `services.*.image` against `docker-compose.yml`.
- **Close the contract drift and schedule it.** `vidra-user/lib/api/generated.ts` is missing `setFollowNotifications` / `notification_setting` shipped in vidra-core main. Run `OPENAPI_PATH=<core>/api/openapi.yaml npm run codegen`, commit, then add `schedule: cron: "0 6 * * *"` to `contract-ci.yml` — that alone would have caught it. Repository_dispatch from vidra-core on `paths: [api/openapi.yaml]` is the durable version.
- **Node major skew.** `vidra-user/Dockerfile:12,19,29` build and run on `node:26-alpine` while every CI job uses Node 24. Pick one, add `.nvmrc` and `"engines"` to package.json. Add a CI job that `docker build`s the frontend image and boots `node server.js` from the standalone output — that entrypoint has literally never been executed by any automation (Playwright uses `next start`).
- **`RUNBOOK.md`** — one section per alert: API down / 5xx spike, transcode backlog (with the `vidra_job_oldest_queued_age_seconds` threshold and the `POST /api/v1/admin/videos/{id}/transcoding` lever), Postgres unreachable, Spaces erroring, disk >85%, dirty migration, rollback recipe.
- **Secret rotation table** in `deploy/README.md`: free to rotate (JWT_SECRET — logs everyone out; SMTP_PASSWORD; STORAGE_S3_SECRET_KEY; LIVE_INGEST_SECRET), must change on both services in the same deploy (SEARCH_INTERNAL_SECRET), and **destructive** (FEDERATION_KEY_KEK, MFA_KEY_KEK, ATPROTO_KEY_KEK — envelope KEKs over persisted rows; note `ATProtoKEK()` falls back to `FederationKeyKEK`, so rotating the federation KEK silently breaks atproto keys too). State plainly that no re-wrap job exists.
- **MFA KEK hard-require in production** — replace the shape-only check at `config.go:995-999` with the `FEDERATION_KEY_KEK` pattern from `:1017-1019`. `openTOTPSecret` already tolerates raw values, so it migrates live.
- **`FEATURE_LIVE_ENABLED=false`** in the production template. It defaults true, the RTMP ingest is in the `media` profile nobody starts, and `LiveStreamsSection.tsx:391` *hides* the server-URL row when empty — so every creator gets a one-time stream key pointing nowhere with no error.
- **Email**: add an "Email" section (DO blocks outbound port 25 on new accounts → use a relay on 587 with STARTTLS+AUTH; SMTP_FROM needs SPF/DKIM) and `POST /api/v1/admin/email/test`. Today the only way to test SMTP is to trigger a real password reset.
- **HLS renditions in quota.** `video_files.sql:22-38` sums only `video_files`; the HLS ladder lives in `video_renditions` and is uncounted. Your Spaces bill and every quota check under-report.

---

## SOON AFTER (medium / low)

- Frame protection: `X-Frame-Options: DENY` + `frame-ancestors 'none'` in `vidra-user/lib/security-headers.ts`, with a `/embed/:path*` exception in `next.config.ts`. The API already sets it; the pages Caddy serves do not, so `/admin` is framable. Promoting the report-only CSP to enforcing needs nonces on three inline bootstrap scripts first.
- `DATABASE_MAX_CONNS` knob — `store.go:53` hardcodes `MaxConns=10` *after* `ParseConfig`, silently discarding `pool_max_conns` from the DSN. Core 10 + search 10 + import 4 = 24, above the smallest DO Managed plan's cap.
- Fail on malformed booleans/durations — `getEnvBool`/`getEnvDuration` swallow parse errors (`config.go:1306-1329`), so `MALWARE_SCAN_ENABLED=yes` silently means *false* and passes validation cleanly. `getEnvInt` right above it does it correctly.
- Trivy image scanning in the three publish workflows; pin runtime base images by digest.
- Migration CI: `goto <prev release>` → seed → migrate to HEAD with a wall-clock bound → `down 1`/`up 1`. Note **zero** of the 101 up-migrations use `CREATE INDEX CONCURRENTLY` and none sets `lock_timeout`, so a data-dependent migration on a populated table *stalls* rather than fails — and api boot is gated on it.
- Presigned-URL / CDN offload for public HLS bytes (`storage.go` capability interface + a `redirectPresigned` helper modelled on the existing `ipfs_assets.go:15` 307 pattern). This is a cost ceiling, not a defect — every viewed byte is billed twice today (Spaces→droplet + droplet→viewer). **Designated scaling path (decision 2026-08-03):** the edge stays Caddy-only — an nginx edge (sendfile is moot while VOD flows through the api; TLS is the per-byte cost either way; dual configs would drift in the security rules) and Kamal were both evaluated and rejected. When sustained MB/s grows, this offload is the intended answer, not a proxy swap; nginx-rtmp keeps its separate live-ingest role. Revisit trigger: Caddy CPU visible as a meaningful share of peak-hour droplet CPU once the monitoring profile above lands.
- Admin job retry endpoint (`POST /admin/jobs/runs/:id/retry`) — Phase 1 is read-only by design, so a dead-lettered federation delivery or search-outbox event needs raw SQL.
- Terms-consent checkbox + `accepted_terms_at` on signup, and a `category` column on `reports` (spam/harassment/copyright/illegal/other) — copyright is the one carrying legal deadlines. *(Public launch only.)*
- Off-site operator notifications on new reports and pending registrations — currently pull-only. *(Public launch only.)*
- Log shipping (vector/promtail reading the docker json files) — only after rotation and alerting land.
- `read_only`/`cap_drop` on the prod services. Images already run non-root, which is the bigger half.

---

## DIGITALOCEAN RECIPE

### Droplet

**One droplet.** Do not split until you have measured something.

| Launch profile | Droplet | Why |
|---|---|---|
| Small / private (<50 users, occasional uploads) | **Premium AMD 4 vCPU / 8 GB / 160 GB — ~$63/mo** | Floor. ffmpeg runs *inside* the api container (`Dockerfile:18`), and one `TargetAll` job on a 1080p source is **12 full-source encode passes** — 4 ladder rungs (`hls.go:717`), 4 trick-play I-frame encodes (`hls.go:864`, ungated), 4 progressive web videos (`web_video.go:87`). Expect roughly 1.5–2.5× source duration wall-clock on 4 vCPU at `-preset veryfast`. |
| Public launch | **Premium Intel 8 vCPU / 16 GB / 160 GB — ~$168/mo** | Transcoding can take 7 cores (`cpus: '7.0'`) and still leave a core for the API + Postgres. Halves upload-to-playable time. |
| + ClamAV (`MALWARE_SCAN_ENABLED=true`) | **add 2 GB RAM** | `vidra-core/docker-compose.yml:100-104` documents clamd loading the full signature DB into RAM: ~1.5–2 GiB resident, OOM-kills on small hosts. |

**Do not use a 2 GB droplet.** With step 4 landed you pull images so `next build` no longer runs on the box, but Postgres + api + frontend + search + Caddy + one transcode still needs ~4 GB before ClamAV.

Add a **4 GB swapfile** (`fallocate -l 4G /swapfile`) — it is the difference between a slow transcode and an OOM-killed Postgres.

Runtime tuning levers (admin UI, no restart — `internal/instancesettings/service.go:716-721`): set `transcoding_threads` = vCPU−1, keep `transcoding_concurrency` = 1. Raising concurrency multiplies both CPU *and* scratch disk.

### Storage

- **Media → DO Spaces** (`$5/mo`, 250 GB + 1 TB transfer). Endpoint `nyc3.digitaloceanspaces.com` — **host only, no `https://`**, rejected at `s3.go:74-76`. Set `STORAGE_S3_REGION=nyc3` too; `USE_SSL=true` / `FORCE_PATH_STYLE=false` are already correct compose defaults. Pre-create the bucket so `EnsureBucket` never calls `MakeBucket`.
- **Transcode scratch → a 100 GB Block Storage volume** mounted at the host path backing the `transcode_tmp` named volume. Budget **~4× the largest permitted upload × transcoding_concurrency**; with `UPLOAD_MAX_SIZE=2G` that is ~8 GB per concurrent job. Without this, scratch lands on the container writable layer under `/var/lib/docker` on the same root disk as Postgres data — nine `MkdirTemp`/`CreateTemp` sites including a full uncompressed PCM wav for Whisper and a full second encode for VP9. Setting `TMPDIR=/scratch` redirects all of them at once, no Go change.
- **Backups → a second Spaces bucket in a different region** (`fra1` if media is in `nyc3`). A dump on the droplet dies with the droplet.
- Do **not** use `STORAGE_BACKEND=local` unless you have added the `media_data` volume from step 3 — the default `./data/media` resolves to `/app/data/media` on the container writable layer, and `up -d` destroys it while the Postgres rows survive pointing at nothing.

### Managed Postgres — **no, not at launch**

Three things block it as shipped: `DATABASE_URL` is *constructed*, not interpolated (step 1 fixes this); `sslmode=disable` is baked in and DO Managed rejects it; and the hardcoded `MaxConns=10` × core + search + a 4-conn import pool = 24 connections, above the smallest plan's ~22 cap. The postgres container is also in the `core` profile with no way to exclude it.

**Run bundled Postgres 18 on the droplet with the nightly dump to Spaces.** It is a genuinely fine answer for a single-node launch. Migrate to Managed (2 vCPU / 4 GB, ~$60/mo) once step 1's DSN indirection and a `DATABASE_MAX_CONNS` knob have landed and been tested — then you get PITR and failover for free. Note `vidra-core/docker-compose.yml:51-56` already documents the pg18 mount-path footgun.

### Firewall

**DO Cloud Firewall** (outside the droplet — the only control Docker cannot bypass):
- Inbound TCP **22** from your admin IP only
- Inbound TCP **80** and **443** from `0.0.0.0/0, ::/0` (80 is required for the ACME HTTP challenge)
- Everything else denied. Outbound: all.

ufw as defense-in-depth is fine, but write in the README that it does **not** filter Docker-published ports. Verify from another host after bring-up:
```
nmap -Pn -p 22,80,443,3000,5432,6379,8080,8081 <droplet-ip>
```
Only 22/80/443 may be open. If 5432 or 6379 answer, the prod overlay is not being applied.

### DNS / TLS

A + AAAA for `example.com` → droplet IP. With the single-origin Caddyfile from step 9 that is the only record you need. Caddy provisions Let's Encrypt automatically on first request; `caddy_data:/data` must be a named volume or you re-issue on every `up -d` and hit LE rate limits.

### First bring-up

```bash
# --- host prep (as root) ---
adduser --disabled-password vidra && usermod -aG docker vidra
apt-get update && apt-get install -y docker.io docker-compose-v2 git unattended-upgrades
systemctl enable --now docker
cat >/etc/docker/daemon.json <<'EOF'
{"log-driver":"json-file","log-opts":{"max-size":"10m","max-file":"5"}}
EOF
systemctl restart docker
fallocate -l 4G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
# attach + mount the Block Storage volume at /mnt/vidra_scratch

# --- stack (as vidra) ---
git clone https://github.com/yegamble/vidra.git /opt/vidra && cd /opt/vidra
./bootstrap.sh                          # clones the three component repos
cp env/production.env.example env/production.env
$EDITOR env/production.env              # JWT_SECRET, POSTGRES_PASSWORD, REDIS_PASSWORD,
                                        # MFA_KEY_KEK, SEARCH_INTERNAL_SECRET, SMTP_*,
                                        # STORAGE_S3_*, INSTANCE_NAME, PUBLIC_BASE_URL,
                                        # VIDRA_*_TAG=v0.1.0, REGISTRATION_ENABLED=false
git check-ignore -v env/production.env  # MUST match, or stop
$EDITOR deploy/Caddyfile                # your real domain

export COMPOSE="docker compose -f docker-compose.yml -f docker-compose.prod.yml \
  --env-file env/production.env --profile core --profile frontend"

$COMPOSE config -q                      # render check — catches missing required vars
$COMPOSE pull
$COMPOSE run --rm migrate && $COMPOSE run --rm search-migrate
$COMPOSE up -d --no-build

curl -fsS http://127.0.0.1:8080/readyz  # {"status":"ok", postgres+redis+storage}
curl -fsS https://example.com/          # Caddy + cert + frontend
nmap -Pn -p 5432,6379,8080,3000 <droplet-ip>   # must be closed

# --- claim ownership BEFORE announcing the domain ---
# register the owner account -> auto-granted admin (auth/service.go:244)
# then set REGISTRATION_ENABLED=true and re-run $COMPOSE up -d

# --- prove the safety net before you need it ---
sudo systemctl enable --now vidra-backup.timer
./deploy/backup.sh && ./deploy/restore.sh backups/<latest>.dump   # on a scratch stack
sudo reboot                             # confirm every container returns unattended
```

Smoke test after reboot: upload a 1080p clip, watch it transcode (`GET /api/v1/admin/jobs`), play it back, seek (confirm 206), and if ClamAV is on, upload an EICAR file and confirm it is withheld.

### Upgrade / rollback loop

```bash
# UPGRADE — tag a release in the component repo, wait for GHCR, then:
cd /opt/vidra && git pull --ff-only            # compose + Caddyfile only
$EDITOR env/production.env                     # VIDRA_CORE_TAG=v0.2.0
./deploy/deploy.sh                             # dump -> pull -> gated migrate -> up -> probe

# ROLLBACK — app only, no schema change (the one-release rule):
./deploy/rollback.sh v0.1.0                    # rewrite tags, pull, up -d --no-build

# ROLLBACK across an incompatible schema change:
$COMPOSE stop api frontend
./deploy/restore.sh backups/pre-deploy-<ts>.dump
./deploy/rollback.sh v0.1.0
```

Rule to write into the README: **schema changes stay backward-compatible for one release.** Then a bad deploy is a 60-second tag flip, and the pre-deploy dump is the only escape hatch you ever need for the rare case where it isn't.

---

## ALREADY HANDLED — DON'T REDO THIS WORK

Verified present. Skip all of it.

**Security.** bcrypt cost 12 (not the default 10). JWT pinned to HS256 with issuer+audience enforcement — alg-confusion is dead. Refresh tokens stored hashed with rotation + reuse detection; access token in memory only, never localStorage. **Every** `/admin/*` route carries `requireAuth` + `requireRole`. SSRF protection is dial-time in the dialer `Control` hook (blocks 169.254.169.254, RFC1918, CGNAT, ULA, embedded creds) so DNS rebinding is caught too. ffmpeg/ffprobe/yt-dlp are always `exec.CommandContext` with an argv slice — no shell, no injection. Path traversal is centrally rejected in both storage backends. API sets nosniff / X-Frame-Options / Referrer-Policy / COOP / production HSTS. CORS never combines `*` with credentials. 5xx bodies are scrubbed. All three images run non-root, multi-stage, no baked secrets, with `.dockerignore` excluding `.env`. Actions are SHA-pinned and CI *enforces* it.

**Config.** `internal/config/config.go` is the single source of truth and the rule holds — no other package reads `os.Getenv`. `validate()` already hard-fails in production on: the dev JWT_SECRET and any <32-byte secret, wildcard CORS, missing FEDERATION_KEY_KEK / ATProto KEK, non-https PUBLIC_BASE_URL when federation or OAuth is on, incomplete S3, incomplete SMTP, MALWARE_SCAN_ENABLED without CLAMAV_ADDR, malformed KEKs, unreachable OAuth providers. **vidra-search already refuses the dev HMAC secret in production** (`config.go:20, 261-266`) — do not re-implement that guard, just uncomment the template line. Cookies are `Secure` whenever env is production regardless of PUBLIC_BASE_URL. Dangerous-but-unset states already WARN loudly at boot. IPFS RPC ports are already loopback-bound. `vidra-core/.env.example` is a genuinely good 24 KB annotated reference covering 123 of 128 keys.

**Durability.** Every job queue is Postgres-backed with partial-unique idempotent enqueue, exponential backoff and dead-lettering — Redis holds nothing durable and needs no backup. Orphaned media *is* garbage-collected daily. Abandoned upload chunks *are* swept every minute. ffmpeg temp dirs *are* `defer os.RemoveAll`'d on every non-kill path. Stuck-transcode videos *are* published from the original by a hold sweeper with a CAS transition, so a lost transcode never hides a video forever. vidra-search shares the DB in a `search` schema with its own migrations table — one `pg_dump` covers both. Quota machinery (per-user override, instance default, rolling-24h ledger, admin editing) is complete apart from rendition accounting. Graceful SIGTERM shutdown is implemented and regression-tested.

**Observability.** Structured JSON logging is the *default*. `request_id` + `correlation_id` + `trace_id` on every line, with a guard test proving query strings never reach logs. Real Prometheus RED metrics with deliberately bounded cardinality (route templates, not paths), plus `vidra_queue_depth`, `vidra_job_oldest_queued_age_seconds`, `vidra_job_stale_running`, `vidra_search_service_healthy` — **the stuck-worker signal is already computed**, it just has no scraper. `/healthz` and `/readyz` are properly separated. `GET /api/v1/admin/system` and a live SSE job-events stream exist with a frontend page. OTel is end-to-end (pgx + Redis + outbound spans, frontend joins the same trace) and genuinely zero-cost when off.

**Media.** Resumable 8 MiB chunked upload with out-of-order idempotent PUTs, streaming assembly, resume across restarts, 24h expiry + sweeper, per-user session cap. Range/206 works on both backends. Cache-Control is per-asset-shape and correct (versioned HLS immutable, `?pt=` no-store, live segments max-age=12). HLS writes to a per-generation prefix so re-transcode never disturbs a live stream; promotion is a DB row swap. Progressive MP4 and audio M4A are `-c copy` stream copies, near-zero CPU. Transcode concurrency and threads are runtime-tunable with no restart. Feed queries are single joined statements — no N+1. Next.js is `output: "standalone"` with no image-optimizer load. DO Spaces is explicitly documented in the S3 backend with the exact endpoint recipe.

**Product.** Transactional email is fully implemented (587 + STARTTLS + header sanitizing), with reset/verify frontends; tokens are typed codes, immune to origin confusion. First-admin bootstrap exists in all four signup paths. vidra-search is genuinely optional with a circuit breaker *and* an active health prober, degrading to local SQL. It needs no external indexing cron. GDPR export/import/erasure is end-to-end. Ban/suspend, reports, quarantine, watched-words, approval queue all exist. Federation is correctly off and correctly gated in the UI. **Zero user-facing placeholder strings** in the frontend. 101 up + 101 down migrations, fully paired. `deploy/README.md`'s CDN policy section is genuinely good — keep it.

**CI.** Both Go services build, vet and test clean right now. Frontend typecheck is clean. The path-level frontend↔backend contract check *passes* (212 backend paths, 184 referenced, all present) — only generated-type freshness is drifted. `ci-guard.yml` in all three subrepos enforces SHA pins, bans silent `continue-on-error`, and asserts CI invokes the canonical local gate. Local/CI parity is exact (`make ci` / `npm run ci`). Backend OpenAPI drift is guarded by a passing route-vs-spec test. Permission/visibility, upload/transcode and auth all have substantial HTTP-layer test coverage. Integration tests run against real ffmpeg; e2e runs against a live backend with a real publish→transcode→HLS-playback assertion. Go toolchain versions are consistent end to end. The 50 vitest failures you may see locally are a Node 25/26 `localStorage` artifact, not code debt.

---

## TIME TO LAUNCH-READY

One competent engineer, focused. Steps 1–8 are the launch gate; step 9 is public-launch only.

| Workstream | Est. | Notes |
|---|---|---|
| **Compose plumbing** — prod overlay, loopback binds, restart, logging, volumes, resource limits, Caddy service, DSN indirection, healthchecks | **1.5–2 days** | Steps 3 + the DSN half of 1. Mechanical but touches two repos. |
| **Config & secrets** — ~60-key api passthrough, frontend/search passthrough, both env templates, gitignore, prod-refusal code, MFA KEK | **1.5–2 days** | Steps 0, 1, 2. The passthrough diff is the tedious part; the CI drift check pays it back. |
| **Backend code fixes** — rate-limit skipper + IPExtractor + internal trust, request-deadline exemptions, boot-time job requeue, `WithoutCancel` bookkeeping | **2–3 days** | Step 5. Needs tests: spoofed-XFF must not reset the auth budget; a 10-min upload must complete. |
| **Release & deploy tooling** — ldflags stamping, tag v0.1.0 ×3, GHCR wiring, deploy.sh / rollback.sh / backup.sh / restore.sh / timer, first restore drill | **1.5–2 days** | Steps 4 + 6. The restore drill is non-negotiable and eats half a day. |
| **Docs** — host prerequisites, firewall + DOCKER-USER warning, sizing table, first-boot ordering, dirty-migration runbook, rotation table, email section | **1 day** | Step 7 + 8. Fastest ROI in the whole list. |
| **Origin topology + SEO** *(public launch only)* | **0.5 day** | Step 9, single-domain Caddy routing. 2–3 days if you insist on split subdomains and need the `PUBLIC_WEB_BASE_URL` code change. |
| **Monitoring floor** — uptime check, DO alerts, METRICS_ENABLED, `/readyz` storage probe | **0.5–1 day** | Uptime check is 15 minutes; the storage probe is the rest. |
| **Rehearsal on a throwaway droplet** — full bring-up, reboot test, upload/playback/EICAR smoke, backup+restore, deploy+rollback | **1 day** | Do not skip. This is where the remaining unknown-unknowns surface. |

**Total: 9–12 working days → ~2 to 2.5 calendar weeks** for a public launch. A **small private launch is 6–8 days** — drop step 9, the SEO work, and the CAPTCHA/legal items, and keep `REGISTRATION_ENABLED=false` with manual account creation.

Add **3–4 days** in week one for the high-priority list (alerting, security alerts, CI version skew, contract scheduling, job timeout, RUNBOOK). Budget them; do not fold them into the launch gate or the launch slips.
