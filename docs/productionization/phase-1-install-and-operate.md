# Phase 1 — Production-ready basic installation & operation

**Outcome:** a person with a VPS and a domain installs Vidra without cloning git, editing env
files, or knowing compose exists:

```text
curl -fsSL <installer-url> | sh   →   setup wizard   →   Vidra works (HTTPS, local PG/Redis/storage, HLS)
```

…and operates it with `vidra status | logs | doctor | update | backup | restore`.

**Non-goals for this phase:** S3-as-default, DASH/CMAF, CDN, DRM, multi-node (Phases 2–5).
The existing single-host recipe is the tested default that everything generalizes *from*.

## Work items

Ordered by dependency. Keep this list current: `[x]` done, `[ ]` open. Reference commits/PRs
when closing items.

### Foundations (no-fork + trust prerequisites)

> **Wave 1 (2026-08-19): items 1–5 implemented on local branches, adversarially reviewed, full
> gates green** (vidra-core `make ci` equivalent incl. race + integration; vidra-user
> `npm run ci` incl. 558/558 mocked Playwright; meta-ci-equivalent renders). **Awaiting
> merge/push:** `vidra-user prod/phase1-runtime-origin` (d085794, 28d0aba, 69da5ac),
> `vidra-core prod/phase1-config-owner` (be150c7, f93327f, 1189da9, c7b8116, 8709029),
> meta `prod/phase1-deploy-fixes` (cb1b169, 95f202e, fbf7162, 8ba60dd, 471bd2f, 6e81342).
> Merge notes: the backed-e2e harness commit (69da5ac) is order-independent (404 fallback), so
> either repo can merge first; the frontend API contract regen runs on core merge per the
> established convention; after the meta branch lands, live hosts need one deploy (or manual
> `git fetch --tags --force`) to re-pin post-rewrite tags.

- [x] **1. Un-bake the frontend origin** *(implemented 2026-08-19, `vidra-user`
  `prod/phase1-runtime-origin` d085794 + 28d0aba)* — origin resolution is now runtime:
  same-origin relative default (prod is single-origin behind Caddy), `PUBLIC_API_BASE_URL`
  runtime env served per-request via `/runtime-config.js`, `INTERNAL_API_BASE_URL`/`API_BASE_URL`
  for SSR, dev/e2e `NEXT_PUBLIC_API_BASE_URL` override preserved, publish-workflow origin gate
  removed, malformed/loopback origins validated at the seam. Acceptance verified: one build
  served two different origins in two runs with only env changed (plus headless-browser proof
  that all `/api/v1/*` calls follow the runtime value).
- [x] **2. Parameterize the image owner** *(implemented, meta `prod/phase1-deploy-fixes`
  cb1b169 + 471bd2f)* — `VIDRA_IMAGE_OWNER` (default yegamble) in the prod compose chain;
  fork-knob cross-references (GITHUB_OWNER, VIDRA_GH_OWNER) documented.
- [x] **3. Strict env parsing in vidra-core** *(implemented, `vidra-core`
  `prod/phase1-config-owner` be150c7)* — malformed bool/duration/int values are fatal at config
  load; **all** malformed vars reported in one boot (errors.Join) for the generated-env use
  case; empty still means unset (documented at the getters).
- [x] **4. Close the first-admin race** *(implemented, same branch f93327f + 1189da9 + c7b8116 +
  8709029)* — one-time owner-claim token: sha256-only storage (migration 0104), atomic
  single-winner claim CTE (8-way-concurrency integration-tested), `POST /api/v1/setup/claim-owner`,
  all four signup paths (register, pending-verification, OAuth, ATProto) refuse with
  `owner_claim_required` while empty+unclaimed, existing instances implicitly claimed, token
  rotates on every boot while unclaimed (leaked logs don't become permanent credentials; loud
  warning when users exist but owner unclaimed), `owner_claim_pending` signal on
  `GET /api/v1/instance` for the wizard, `OWNER_CLAIM_TOKEN` dev/test override (fatal in
  production) for harnesses/local dev, backed-e2e harness migrated to claim-first bootstrap
  (vidra-user 69da5ac, order-independent). Wizard/UI consumption arrives with item 9.
- [x] **5. Force tag re-fetch + POSTGRES_PASSWORD assert** *(implemented, meta branch 95f202e +
  fbf7162 + 8ba60dd)* — `git fetch --tags --force` in deploy.sh/rollback.sh/bootstrap.sh;
  `POSTGRES_PASSWORD` asserted `:?` in the prod chain, blanked in the env templates
  (fail-loud pattern), added to the meta-ci prod-render contract, with existing-volume
  recovery advice (the value only takes effect at initdb).
> **Wave 2 (2026-08-19): items 6–8 implemented on stacked branches, adversarially reviewed
> twice (initial + fix-verification), full gates green** (core `make ci` + full/race/integration
> suites; search `make ci` + integration; meta renders/port/one-shot assertions — the one
> skipped check, meta-ci's boot job, was blocked by host disk exhaustion, not a defect).
> **Branches:** `vidra-core prod/phase1-wave2` (10 commits stacked on `prod/phase1-config-owner`,
> tip d547ca1), `vidra-search prod/phase1-wave2` (9 commits over main, tip bcfd302), meta
> `prod/phase1-wave2` (8 commits stacked on `prod/phase1-deploy-fixes`, tip fd75406).
> **Hard merge order:** vidra-core and vidra-search must land + release BEFORE the meta wave-2
> branch (its compose invokes the embedded `migrate` subcommand; old binaries ignore argv and
> hang). `MIN_EMBEDDED_MIGRATE_TAG` (currently "v0.2.0") is duplicated in
> deploy.sh/rollback.sh/restore.sh — **adjust to the actual first embedded-migrate release at
> release time** (a three-file edit; a CI assertion that they agree would be cheap).

> **Wave 3 (2026-08-19→20): item 8 finished (component profiles), items 11 and 14 implemented,
> item 9 started — stacked branches, two independent adversarial verifications (2026-08-20),
> every finding fixed the same day.** **Branches:** `vidra-core prod/phase1-wave3` (8 commits
> stacked on `prod/phase1-wave2`, tip 70dfc94), meta `prod/phase1-wave3` (7 commits stacked on
> `prod/phase1-wave2`, tip f8ed6de), `vidra-user prod/phase1-wave3` (3 commits stacked on
> `prod/phase1-runtime-origin`, tip f275d91). **Gates green:** core `make ci`; user
> `npm run ci` (1508 unit, 566 mocked Playwright); meta — every validate-job step that needs no
> registry pull, `shellcheck -x` clean. **Deferred docker-bound checks, all run green 2026-08-20
> after a Docker Desktop restart cleared the corrupted containerd content store:** meta-ci's
> `caddy validate` in its exact CI form (pinned `caddy:2.11.4-alpine` in docker, `--network
> none`) on the template AND on four engine-rendered `Caddyfile.local` variants (acme,
> acme-no-email, acme-staging, internal) — all "Valid configuration", pin-drift step green; the
> full boot job locally against the wave branches (production boot `/readyz` 200, both
> migration one-shots run from their service images, `migrate version` clean — core v104,
> search v14 — ledgers confirmed via psql); the backed e2e suite at CI parity (API :8080, UI
> :3000) — **94 passed / 0 failed** (11 env-gated skips) including all 5 owner-claim specs and
> the owner-claim `admin.setup.ts` bootstrap, plus the registration-approval two-step (3
> passed). **Merge order is wave 2's, unchanged** —
> vidra-core lands and releases before meta, which now also depends on `vidra setup` to generate
> `deploy/Caddyfile.local`. **Operational migration (legacy hosts):** that file is mandatory now
> (`docker-compose.prod.yml` mounts it, never the committed template), so an existing droplet
> must run `vidra setup` — or `cp deploy/Caddyfile deploy/Caddyfile.local` to keep hand edits
> verbatim — **before** its next deploy; deploy.sh, rollback.sh and restore.sh refuse up front
> and print exactly those two options.

- [x] **6. Remove runtime git dependence (migrations half)** *(implemented 2026-08-19, wave 2)* —
  migrations are embedded in both Go binaries (`//go:embed` + golang-migrate as a library) with
  `migrate up | version | force <v> --yes-i-know` subcommands; ledgers unchanged
  (`schema_migrations`, `vidra_search_migrations` — continuity proven live by starting with the
  old CLI and finishing embedded on the same DB); compose one-shots run from the service images
  (prod overlay pins published images with `build: !reset null`, `pull_policy: always`,
  `no-new-privileges`); dev-hot overlay go-runs the migrator from bind-mounted source;
  deploy/rollback/restore refuse pre-embedded tags via `MIN_EMBEDDED_MIGRATE_TAG`.
  **Scope decision:** shipping the Caddyfile + nginx-rtmp template as no-git artifacts moved to
  item 17 (the installer's artifact bundle) — they are meta-repo deployment artifacts, not
  image content. Bonus fixes en route: search dev compose Postgres volume was broken since the
  16→18 bump (fresh volumes fixed + pg_upgrade remediation documented); search images now get
  real VERSION ldflags.
- [x] **7. Callable validation (config half)** *(implemented, wave 2)* — `config.LoadFrom(lookup)`
  + `config.CheckEnv(map)` validate candidate env values with the *same* code that boots (zero
  drift), and `VarError{Var, Msg}` types 88 single-variable errors for field mapping.
  **Open follow-ups:** semantic `validate()` still reports first-error-only (the wizard may want
  error collection); the instancesettings validators (the runtime-settings half) remain to be
  exposed for wizard use.

### Setup engine + wizard

- [x] **8. Setup engine** *(implemented, wave 2: `internal/setup` + `cmd/vidra setup`)* —
  parses the real template as INPUT (no embedded copy; comments/order preserved byte-identical),
  mints every blank secret per a shape-checked manifest (hex vs base64 per config validation),
  **merge mode preserves every existing non-empty value** (the output file is always a
  preservation source; `--from` adds sources but can never disarm it), KEK rotation requires
  `--rotate <VAR> --yes-i-know` with destructive-consequence text, KEKs mint only on genuine
  first install (truncated-file regression covered), self-validates via `CheckEnv` +
  leftover-placeholder pass, `setup --check <file>` (flags missing `VIDRA_ENV=production` and
  still surfaces production findings; warns on compose quote-stripping hazards), secrets
  accepted via @file/stdin/env with no-echo prompts, atomic 0600 writes with dir fsync.
  Proven end-to-end against the real template: generate → check → real prod-chain render →
  re-run byte-identical.
  **Component profiles** *(wave 3: core e30341d + d882bec, meta 7b08dce + 68edf3a)* — the
  answers now land in the file the deploy scripts read. Three keys are the cross-repo contract:
  `VIDRA_COMPOSE_PROFILES` (always `core frontend`, then scan/captions/media/otel/ipfs in that
  order, from the one `featureProfiles` table both `Profiles` and `FeaturesFromProfiles` go
  through, so a re-run round-trips its own list) and `VIDRA_EXTERNAL_POSTGRES`/`_REDIS` (the
  engine writes literal `true`/`false`; the shell's `is_true` word list is the read side of the
  contract and the exported `setup.IsTrue` is the engine's mirror of it, so engine, doctor and
  deploy cannot spell a boolean three ways). The original spec bullets, restated as satisfied:
  **external answers never launch the local equivalents** — externality is a conditional overlay
  file (`docker-compose.external-{postgres,redis}.yml`) inserted immediately after
  `docker-compose.prod.yml`, postgres first, deleting the bundled service and asserting the
  replacement DSN with `${…:?}`; **S3-as-canonical needs no permanent local object store** —
  neither storage answer enables the `storage` profile, whose minio is a dev convenience
  (`STORAGE_BACKEND=s3` names somebody else's endpoint, so a local one would be a container
  nothing talks to); **`SEARCH_INTERNAL_SECRET` stays consistent** — one minted variable the
  compose chain feeds to both the api and the search service; **the render check** is
  `RenderCheckArgs`, now the single builder for the chain the engine prints, doctor renders and
  the deploy runs. `SEARCH_REDIS_URL` joined the managed keys, *derived* to the next Redis DB
  index rather than copied (core holds `/0`; one eviction policy over two key populations is
  each service quietly evicting the other's data), left absent rather than guessed when the DSN
  is unparseable, and re-derived on `--redis-url` rotation **only** while it still holds what
  this engine derived from the old DSN. The shell half is single-sourced too: `deploy/lib.sh`
  (`env_get`, `is_true`, `vidra_compose_chain`) sourced by all four deploy scripts, plus
  `deploy/compose.sh` as the gate-free wrapper the Makefile's prod targets delegate to — the
  fifth, drifted copy in `PROD_COMPOSE` hardcoded `--profile core --profile frontend` and applied
  neither overlay, so `make prod-config` reported OK for a stack the operator was not running (a
  false green, found by verification); meta-ci now lints with `shellcheck -x` so it follows into
  lib.sh. Old env files keep working — absent keys fall back to today's behaviour and the legacy
  `core frontend`.
  **Recorded gotcha:** in an overlay, `profiles:` is a *sequence* and MERGES across the `-f`
  chain, so `!override` is required to replace it — `!reset` deletes the key entirely and leaves
  a service with no profiles, i.e. one that starts on every invocation, the exact opposite of the
  intent. `depends_on:` is a map, so `!reset` on the single key is right there (and required:
  a dangling edge makes the whole project invalid).
  **Pre-existing template gaps (loud, not wave-3 regressions):** the template ships
  `STORAGE_BACKEND=s3` with `<your Spaces access key>` placeholders, so a plain
  `vidra setup --domain X` refuses until the operator passes `--storage local` or real keys —
  which contradicts the local-storage safe default below; and `media_data` still mounts at
  `/app/data` under s3 (it is the `STORAGE_BACKEND=local` media root, simply unused there).
  **Not yet in scope (later items):** INSTANCE_NAME and richer answers, the web wizard UX
  (item 9).
- [ ] **9. Web setup wizard** *(PARTIAL — the owner-claim slice shipped 2026-08-20, wave 3:
  `vidra-user prod/phase1-wave3` c3aadce + dd8d00a + f275d91; the nine-step installer wizard
  remains open)* — first-run flow: Welcome → System Check → Basic/Advanced →
  Domain/Networking → Storage → Admin Account (consumes the owner-claim token) → Optional
  Features → Review → Install → Success. "Recommended setup" makes production-safe decisions
  automatically; Advanced exposes external DB/storage/proxy/IPFS. Backbone already exists: the
  instancesettings Snapshot metadata (kind/default/validator/options/page/section) and the
  metadata-driven AdminInstanceConfigView machinery prove the rendering approach. Wizard binds
  to localhost pre-TLS with an SSH-tunnel instruction (`ssh -L 8080:localhost:8080 user@server`);
  never expose an unauthenticated installer publicly. Surface the 15s DB/Redis fail-fast and
  settings-overlay load failures as wizard feedback, not crash loops.
  **Shipped (the Admin Account step, standing alone):** API contract regen, then `/setup/claim` —
  a standalone wizard driven by `owner_claim_pending` on `GET /api/v1/instance`, landing its 201
  `AuthResponse` through AuthProvider's `apply` (the seam login already uses), so the wizard ends
  signed in; `OwnerClaimCard` first-run signposts on home/sign-in/sign-up painting from the SSR
  snapshot and revalidating in the browser (a null snapshot is not evidence of a claim); signup
  and the OIDC/ATProto callback intercepting `owner_claim_required` into the wizard instead of a
  raw error over a form that cannot succeed; and error copy built around the token rotating on
  every boot — 403 `owner_claim_invalid` names *both* causes (rotated token, or a server that
  already has an owner) and quotes the prod compose chain's log command, not a bare
  `docker compose logs api`, which on a prod host implicitly merges the dev override that
  `vidra doctor` flags. `e2e-backed/owner-claim.spec.ts` is written but **not run** (see the
  wave-3 note); its happy path is skipped by design, because the backed-setup project claims the
  stack before any spec runs and first run cannot be re-entered without dropping the database.
  **Prerequisite for the rest is still unmet:** item 7's open follow-ups — semantic `validate()`
  reports first-error-only and the instancesettings validators remain unexposed — so per-field
  validation of *proposed* answers still has no callable surface.
- [ ] **10. Terminal wizard + non-interactive install** — same engine, `vidra setup` in a TTY;
  flags/answers-file for automation. Works without a browser.

### Managed edge

- [x] **11. Vidra-managed Caddy** *(implemented 2026-08-20, wave 3: core 5d514d4 + f7213cc +
  992e0b8 + 70dfc94, meta b066d80 + a2df5e0 + 9672976 + f8ed6de)* — `deploy/Caddyfile` stays a
  checked-in, `caddy validate`-clean template (a proxy config nobody can read without running a
  generator is a config nobody reviews) and gains two markers, `# vidra:global-options` and
  `# vidra:tls`; `vidra setup` renders `deploy/Caddyfile.local` from it, substituting the
  `PUBLIC_BASE_URL` host on every **non-comment** line and injecting the ACME issuer and the
  site-level TLS directive at the markers. **A missing marker is a hard refusal, not a silent
  skip** — injecting nothing where the issuer belongs yields a file that looks right and deploys,
  and a rehearsal meant for the staging CA then spends the instance's real rate limit on
  failures. `VIDRA_TLS_MODE` = `acme` | `acme-staging` | `internal` (blank reads acme) and
  `VIDRA_ACME_EMAIL` are the cross-repo contract; the contact address is **optional with a
  warning**, because a hard requirement refused every non-interactive install — the shipped
  template sets `acme` and leaves the address blank (verification finding, 992e0b8), and render,
  `--check` and doctor now agree that blank is fine. Image pinned to `caddy:2.11.4-alpine` in the
  prod overlay *and* in meta-ci's validate step, with a CI assertion that the two never drift;
  `docker-compose.prod.yml` mounts `Caddyfile.local` (gitignored, atomic-writer temp file
  included) and never the template. Three gates run before anything starts, in all three scripts
  that `up -d`: `require_caddyfile_local` (a missing bind-mount source is created by Docker as an
  empty DIRECTORY and crash-loops Caddy — whole site dark, every app container healthy — and the
  message offers the two legacy migrations), `require_real_domain` now reading the file actually
  mounted *and* comparing its site address with `PUBLIC_BASE_URL`'s host, and
  `require_dns_points_here` before any ACME order (`VIDRA_PUBLIC_IP`, else the same two IP-echo
  endpoints in the same order as `internal/preflight`, whitespace-stripped;
  `VIDRA_SKIP_DNS_PREFLIGHT` read through the env file, not just the process env). The
  placeholder-domain predicate is one anchored regex shared across repos
  (`setup.PlaceholderDomainPattern`, matched verbatim by deploy.sh): the unanchored
  `strings.Contains` it replaced refused `myexample.com` and waved `tube.example.org` through.
  After `up -d`, `caddy reload` — editing a bind-mounted file recreates nothing, so `up -d` alone
  leaves the OLD config serving — and exhausting its bounded retries is now a `die`, not a
  warning. Plus a third probe that finally tests the *edge*:
  `curl -fsSk -m 5 --resolve "$host:443:127.0.0.1" https://$host/healthz`, 180s `EDGE_TIMEOUT`
  (above `READY_TIMEOUT` because none of Caddy's ACME work starts until after everything that
  covers). Both pre-existing probes hit loopback, i.e. behind Caddy, so a deploy could exit 0
  with the public site dark.
  **Deliberate gap:** only the internal-CA half of the pre-TLS bring-up mode shipped — caddy
  still publishes `80:80`/`443:443` on 0.0.0.0 under `VIDRA_TLS_MODE=internal`. The loopback half
  needs the caddy compose profile and the cookie/HSTS work in **item 12, unchanged and open**.
  Template trap worth knowing: the commented split-origin block keeps `example.com` because the
  substitution skips comments, so uncommenting it *in the template* makes the next render emit
  `api.<domain>` — the block's own note explains why that layout needs a Go change first.
- [ ] **12. External proxy / deliberate plain-HTTP modes** — these need *code*, not just
  compose: caddy service needs a compose profile (it currently always starts);
  `config.CookieSecure()` hardcodes production⇒Secure (login silently breaks over plain HTTP);
  HSTS emitted unconditionally by both apps; public-IP TLS terminators need `TrustIPRange`
  wiring exposed as config. Also: generated-nginx-config option. All gated, explicit choices.

### The `vidra` CLI

- [ ] **13. `vidra` CLI core** — thin, gate-preserving orchestrator over the existing scripts
  (never a rewrite): `vidra deploy/rollback/backup/restore/release` wrap deploy/*.sh semantics
  verbatim (Compose≥2.24 refusal, dump-abort, gated migrators + ledger assertion,
  probe-or-fail, read-never-source env access, CONFIRM conventions). `vidra logs` = per-service
  selection; `vidra restart <service>` maps product names → compose services;
  `vidra status` aggregates /readyz + admin system endpoint + search /readyz + compose ps.
- [x] **14. `vidra doctor`** *(implemented 2026-08-20, wave 3: core f337b0c + daa976a,
  `internal/doctor` + `cmd/vidra doctor`)* — the runbook, executed. **18 checks** in four
  sections: docker & compose (compose version, published ports, log caps, dev override, stray
  `vidra-core/.env`), configuration (reverse proxy, domain DNS, env file vs template,
  configuration values), data & state (schema ledger, search ledger, backups, backup timer, disk
  space), reachability (object storage, SMTP, search service, ffmpeg). Each prints ✓/⚠/✗ with one
  line of finding and, for anything not ✓, one line of what to do about it; **exit 1 iff any ✗**,
  so it works as a pre-deploy gate. Every finding is DERIVED, never restated from a document —
  the exposure audit renders the deploy's own chain (`setup.RenderCheckArgs`, with `config -q`
  swapped for `config --format json`) and reads the ports out of the result, because whether the
  prod overlay's `!reset` beat the base file's publish, for THIS host with THESE profiles, is a
  question only the render answers. Three distinctions carry the design: a check that cannot RUN
  (no systemd, no daemon, stack down) is ⚠ + reason and exit 0, **not** a failure; a check whose
  subject is switched OFF is ✓, not a permanent ⚠ that teaches operators to ignore warnings; and
  a raw Go error never reaches the operator (asserted over a maximally broken run). Every outside
  dependency — exec, filesystem, DNS, HTTP, SMTP, object store, database — is injected behind two
  small interfaces, so the suite is hermetic and each check's *fix text* is asserted, which is the
  half of the package nothing else reads; every network/exec call is bounded by a per-check
  deadline, and each check runs under a `recover`, so one panic costs one ⚠ rather than all 18
  findings. It shares `internal/preflight` with the future setup wizard (the DependencyManager
  seam in interfaces.md §1) and reuses `setup.IsTrue` / `setup.PlaceholderDomainPattern` rather
  than inventing third answers; `storage.S3.BucketExists` was opened as one `HeadBucket`,
  deliberately not `EnsureBucket` — a diagnostic that creates the bucket it could not find turns a
  typo in `STORAGE_S3_BUCKET` into a new, empty, silently-wrong store. Verification found it
  answering about the wrong deployment: a bare `--filter label=com.docker.compose.project` fed
  every compose container on the host to the dev-override, search and ledger checks, so the filter
  now carries the project name from the rendered model and the label is verified on the way back.
  It covers both exit-criteria duties in the safe-defaults list below — dev-override detection,
  and the port audit. **The port audit's first catch was a live security gap** (fixed in meta
  7f70ee0): the prod overlay reset the publishes for postgres/redis/search and stopped there, so
  an operator who answered yes to virus scanning, captions or tracing got clamd on 0.0.0.0:3310,
  whisper on :8090, OTLP on :4317/:4318 and the unauthenticated Jaeger UI — a read of every traced
  request — on :16686, where a host firewall does not save you because Docker's DOCKER-USER rules
  sit ahead of ufw. All four are `ports: !reset []` now (rtmp 1935 and ipfs 4001 stay published:
  remote peers dial those, and they are gated in the cloud firewall); the same five services also
  gained the missing log caps and `restart: unless-stopped` (9672976); and meta-ci's port step now
  renders with **every** optional profile and walks every service against the same three-entry
  allow-list doctor keeps, instead of the core+frontend render that could never have seen this.
- [ ] **15. `vidra update`** — release discovery (GitHub releases/GHCR tags), VIDRA_*_TAG bump,
  then the deploy.sh pipeline **plus what it lacks**: automatic tag-flip rollback on failed
  health probes (safe *only* under the schema-compat policy — see item 16), and
  multi-generation rollback history (single `.bak` loses state after two rollbacks).
- [ ] **16. CI-enforce the one-release schema-compat policy** — currently documentation-only;
  one destructive migration turns every rollback into old-code-on-new-schema corruption.
  Migration lint rejecting destructive DDL in new files + an N−1-binary-vs-N-schema integration
  job (extend the existing populated-DB migration fixture test). **Highest-leverage
  prerequisite for auto-rollback, not optional hardening.** Also: inject VERSION ldflags into
  vidra-search's Dockerfile (its /version reports 0.1.0 forever); align the golang-migrate pin
  (CI 4.17.1 vs compose 4.19.1).

### Installer + host

- [ ] **17. One-command installer** — `curl -fsSL <url> | sh`: detect OS/platform; check/install
  Docker + Compose (≥2.24); fetch the `vidra` CLI + deployment artifacts (no git clone);
  start setup; print the setup URL/SSH-tunnel instruction. Advanced users can still install
  manually.
- [ ] **18. Host provisioning + backup completeness** — provisioning script/cloud-init template
  for the manual runbook steps (firewall incl. 1935 when the media profile is on, swap,
  /opt/vidra + service user, systemd backup timer install with verification). Extend backup to
  cover `env/production.env` + generated Caddyfile (today the off-site dumps survive host loss
  but the config to use them doesn't) and document/automate local-media volume snapshots.
  **Wave-3 update:** `deploy/Caddyfile.local` is now a real generated file that needs that
  coverage, not a hypothetical one. And external-Postgres deployments now **refuse** backup.sh
  and restore.sh outright — both work by `docker exec` inside the bundled container, which
  `docker-compose.external-postgres.yml` keeps out of the project — with provider
  snapshot/PITR guidance instead; backing up a managed database is deliberately not
  reimplemented. backup.sh's refusal is placed *before* the healthchecks.io trap on purpose, so
  the dead-man's switch goes silent and the inactivity alert fires, which is the honest signal
  for a host that genuinely takes no backups from here.
- [ ] **19. Health surface hardening** — cheap health route for vidra-user (prod healthcheck
  GETs `/` — a full Next render that false-fails under transcode CPU load); machine-readable
  version + schema-version surface on core so update/doctor can ask "what is this instance at"
  without psql; add S3/SMTP/search/ffmpeg readiness detail to the admin system endpoint.
- [ ] **20. Admin infra visibility** — read-only Server/Storage/Networking/Backups panels in the
  admin UI (env-derived, guidance-oriented, consistent with the env-vs-DB doctrine) + the
  feature-discovery pattern ("Optional: Enable DASH / Connect CDN / …") for capabilities that
  exist but aren't configured. Mail test action.

## Safe-defaults checklist (Phase 1 exit criteria)

- HTTPS + managed Caddy; local Postgres/Redis/storage; HLS; H.264 compatibility profile.
- DRM disabled; DASH/IPFS/P2P/CDN optional and off.
- Owner-claim bootstrap (no first-registrant race); registration policy an explicit choice.
- No secret defaults survive an unedited install; all secrets generated.
- Bare `docker compose up` on a prod host must not silently load the dev override
  (rate limiting off) — doctor detects; docs + CLI make the right invocation the only obvious one.
- Media GC gets an explicit enable/dry-run story *before* Phase 2 (see phase-2 doc).
- Every `vidra` command works on the proven single-host recipe.
