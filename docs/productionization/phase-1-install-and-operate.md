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

> **Wave 4 (2026-08-20): items 10, 13, 16 and 19 implemented** — the running-it half of the
> operator CLI, the schema-compat policy turned from prose into a blocking gate, the health
> surface host tooling reads, and `vidra setup` made survivable for an operator who mistypes
> or has no terminal. **Branches:** `vidra-core prod/phase1-wave4` (tip a041e1e — waves 2+3
> landed first as core#45), `vidra-search prod/phase1-wave4` (tip 262d70e), `vidra-user
> prod/phase1-wave4` (tip 1f7ba04), meta `prod/phase1-wave4` (the compose healthcheck fix
> df1523f, the doc commits 156f299/adea171/6e364df/a62c3fa, and this note's own commit).
> **Adversarially verified same day:** six independent verifiers attacked every lane, each
> serious finding then re-attacked by a skeptic that had to reproduce it. Two majors were
> confirmed and FIXED the same day — a line-split `DROP\nCONSTRAINT` evaded migrate-lint
> (statement-level matching now; a 26-case attack matrix passes under both onetrueawk and
> mawk, fixed in core 7ff807b + search 262d70e, copies still byte-identical), and the CLI
> honored an exported `ENV_FILE` for child scripts while its own reads used the flag default
> (one resolution rule now, invariant-tested, bae8747) — plus six minor sweeps (openapi
> description, restart arity message, answers-file validation of argv-overridden lines,
> INSTANCE_NAME still-the-example warning, stray root binary gitignored, stale gate comment).
> **Gates run in the meta lane:** `shellcheck -x
> deploy/deploy.sh` clean; the prod chain rendered against a synthetic production env
> (`-f docker-compose.yml -f docker-compose.prod.yml --profile core --profile frontend
> config`, exit 0) with the rendered frontend healthcheck asserted to be the CMD-SHELL
> `/healthz`-then-`/` form; and meta-ci's own production-overlay render step re-run verbatim
> against `env/production.env.example`. **Component gates, per their lanes:** core `make ci`
> (which now carries migrate-lint) with the schema-compat job rehearsed locally *and*
> negative-controlled — HEAD's migrations applied to a fresh postgres 18, then v0.2.0's
> `go test -tags=integration -race ./internal/store/...` 38/38 PASS, versus exit 1 with
> `column "description" does not exist` from six tests once `videos.description` was dropped
> to stand in for a destructive 0105; search `make ci` (lint verified byte-identical to
> core's under both onetrueawk and mawk); user `npm run ci` with a unit test pinning that
> `app/healthz/route.ts` contains no import at all. **Merge order is waves 2–3's, plus one
> new edge:** vidra-core and vidra-search land and release before meta, and vidra-core must
> also merge before vidra-user — contract-ci regenerates `lib/api/generated.ts` against
> vidra-core@main, so the user branch (which carries the `/schemaz` + `/admin/system` regen)
> stays red until core's branch is on main. **This wave adds no new tag
> floor:** the compose healthcheck falls back to `/` when `/healthz` 404s, so the meta change
> needs no minimum `VIDRA_USER_TAG` and a rollback to v0.2.0 stays healthy — the one design
> decision that keeps the hard merge order from growing a fourth constraint.

> **Wave 5 (2026-08-20): items 15, 17 and 18 implemented — and, unlike every wave before it,
> already MERGED to main in both repos** (`vidra-core` main d9b1634 via PRs #46–#52, meta main
> 2da03b2 via meta#15/#16 plus three direct merges). This is the installing-it half: the
> command that moves an instance between releases, the command that creates one from a bare
> VPS, and the host prep and backup coverage that make the result survivable. **Shipped:**
> `vidra update` (release discovery over `net/http`, `/schemaz`'s numeric refusal of an image
> older than the database, one-release-step automatic tag-flip rollback, ten generations of env
> history at `backups/env-history/<basename>.<UTC stamp>` shared byte-for-byte with
> `deploy/lib.sh`); `install.sh` (`curl … | sh` with the `/dev/tty` reattach that lets the
> wizard run at all, checksum-verified CLI binaries from vidra-core's new `release-assets.yml`,
> a resumable tree, and secrets that are never re-minted); `deploy/provision.sh` +
> `deploy/cloud-init.yaml.example`; `vidra-config-<stamp>.tar.gz` beside every dump on the same
> off-site path under the same retention rule; and **the two hand-sync residuals wave 4
> recorded are now asserted in meta-ci** — `MIN_EMBEDDED_MIGRATE_TAG` must agree across
> deploy.sh/rollback.sh/restore.sh (eb5a694) and both Go repos must ship a byte-identical
> `scripts/migrate-lint.sh` (3c654ba). Neither was a defect yet; both were a comment saying "a
> CI assertion would be cheap", and cheap things that stay uncosted are how a policy stops being
> enforced in half the platform without anyone noticing.
>
> **The adversarial-verification catch, and why it needed five PRs.** `vidra update` originally
> armed its tag-flip rollback on the arithmetic alone — one release step, therefore safe — and
> never asked whether `deploy/rollback.sh` would *accept* the flip. It would not: rollback.sh
> refuses any core or search tag below `MIN_EMBEDDED_MIGRATE_TAG` (v0.2.0, the first image
> carrying the embedded migrator) before it reads anything else. So a v0.1.x instance updating
> to v0.2.0 was promised an automatic rollback that could not run, and then — on failure —
> handed the manual command, which is refused for the same reason. A promise kept only while
> nothing goes wrong is worse than no promise, because it is believed during the incident.
> **Fixed on vidra-core main (d9b1634, PRs #48–#52):** the CLI now parses the floor out of
> `rollback.sh` at runtime and **deliberately does not become a fourth hand-synced constant** —
> item 13's whole argument is that a transcribed gate drifts and its first symptom is a
> divergence during an outage. Below the floor the rollback is disarmed *with the reason stated
> up front*, and an unreadable rollback.sh disarms it too, since "cannot verify" and "verified
> safe" must not print the same sentence. The floor is also gated on the **migrators only**
> (core and search own migrations; the frontend tag has no such constraint), and the
> partial-downgrade hole found in the same pass — mixed tags with `--tag` equal to the oldest,
> which is arithmetically "not a downgrade" while silently walking two components backwards —
> now refuses and **names the components that would move back**, with `vidra rollback` as the
> honest verb. **Release consequence: v0.2.1 must be tagged at or after vidra-core d9b1634**, so
> that the first `vidra` binaries anyone downloads from a release asset carry this rather than
> the version that promised a rollback it could not perform.
>
> **Deviations recorded honestly, because a checked box that overstates itself is a trap:**
> **(a)** item 17's *"(no git clone)"* shipped as *"no MANUAL git"* — the installer drives git
> and bootstrap itself, and three hard dependencies (the unconditional `include:` of
> `./vidra-core/docker-compose.yml`, the bind-mounted
> `vidra-core/deploy/media/nginx.conf.template`, and deploy.sh's schema version from
> `ls vidra-core/migrations/*.up.sql` plus its `.git`-requiring checkout sync) make a git-free
> install impossible today. The artifact bundle that would fix it **stays open** — item 12 or a
> follow-up. *(Closed in wave 6, tranche 1 — see the wave-6 note below.)* **(b)** The installer's happy path begins at v0.2.1, the first release cut after
> `release-assets.yml` landed; v0.2.0 and earlier have no assets, and the installer says so and
> names `make build-vidra` rather than failing opaquely. **(c)** A fully-refusing
> external-Postgres host gets **no config archive either** — the refusal is placed before the
> dead-man's-switch trap on purpose and that ordering is preserved, so provider-side config
> backup is documented and not automated. **(d)** `vidra setup` requires `--template`; the
> runbook's bare `vidra setup` was simply wrong and was corrected this wave (8f01f1b). **(e)**
> rollback.sh used to `cp "$ENV_FILE" "${ENV_FILE}.bak"` **before** `require_caddyfile_local`,
> so a rollback the Caddyfile gate then refused had already destroyed the only previous
> generation — the gates are hoisted above the write now, and the write is a history rather than
> a single file.
>
> **What wave 5 leaves for wave 6:** item 9 (the rest of the web wizard — still blocked on the
> same prerequisite it has had since wave 2: the instancesettings validators are not exposed, so
> per-field validation of *proposed* answers has no callable surface), item 12 (plain-HTTP and
> external-proxy modes: `config.CookieSecure()`, unconditional HSTS, and giving caddy a compose
> profile — the item that also unblocks the loopback half of pre-TLS bring-up and the no-git
> artifact bundle above), and item 20 (the admin infra panels).
>
> **Wave 6, tranche 1 (2026-08-21) — item 12 + the no-git artifact bundle.** Item 12 shipped
> in full (see its entry) and item 17's deviation (a) is now closed: the artifact bundle
> exists. `deploy/make-bundle.sh` assembles a deterministic `vidra-bundle_<tag>.tar.gz` — the
> prod deployment tree plus, at their checkout-relative paths, `vidra-core/docker-compose.yml`
> and the five `vidra-core/deploy/**` files compose bind-mounts (the list is *derived* from
> the compose file, not hard-coded, so a sixth mount ships automatically) — and writes
> `vidra-bundle.manifest` (tag, `core_schema_version`, both source commits). That manifest is
> both the bundle marker and deploy.sh's schema second opinion: a tree with the manifest and
> no `vidra-core/.git` skips the checkout-sync loop and reads the expected migration version
> from the manifest; a git checkout behaves byte-for-byte as before. install.sh is now
> **bundle-first with a git fallback** (`--git`/`VIDRA_INSTALL_GIT` forces the checkout path;
> a 404 on pre-bundle tags falls back and says so) — proven in a debian:12 container with no
> git on the host. `release-assets.yml` builds the bundle from a meta checkout at the **same
> tag** (release.sh now tags the meta repo, refusing a HEAD not on origin/main) into the same
> bare-name `SHA256SUMS`. meta-ci gained a bundle job (byte-identical rebuild, manifest⇔`ls`
> agreement, six prod renders from a checkout-less extract) and the two-way caddy gate.
> **Deviations recorded honestly:** **(a)** the `release-assets.yml` bundle step has never
> actually executed — it needs a tagged release after both repos merge; the first release cut
> after this wave is its live test. **(b)** `vidra update` on a bundle tree remains
> degraded-graceful (it warns that the target schema version cannot be read from git and
> proceeds ungated) — a bundle-aware update flow is a real follow-up, and bundle-tree
> *upgrades* are today a documented manual unpack. **(c)** meta-ci's "every config key has a
> compose consumer" assert only sees `getEnv*` string keys — the 66 typed keys
> (`p.Bool`/`p.Int`/…) are invisible to it, including `VIDRA_ALLOW_PLAIN_HTTP`; both new vars
> were wired anyway, but the gate would not have caught the omission. **(d)** core's HSTS
> max-age (2y) and the frontend's (1y) differ on the same origin — pre-existing, recorded.
>
> **What wave 6 tranche 1 leaves open:** item 9 (the web wizard's remaining surface — same
> instancesettings-validator prerequisite as every wave since 2) and item 20 (the admin infra
> panels), plus the follow-ups in (b) and (c) above.
>
> **Wave 6, tranche 2 (2026-08-21) — item 20 + item 9's prerequisite.** Both shipped (see the
> item entries; core PR #54, user PR #53). One new follow-up recorded honestly: **the
> shared-boolean-spelling gap** — `setup.IsTrue`, `deploy.sh` and the wizard all accept
> `yes`/`on` for the keys the api and scripts share, but `config` reads booleans with
> `strconv.ParseBool`, so `MAIL_ENABLED=yes` in a hand-edited file passes `vidra setup` and
> then refuses to boot the api. Pre-existing (`MAIL_ENABLED`, `FEDERATION_ENABLED`);
> `VIDRA_EXTERNAL_POSTGRES` deliberately does NOT inherit it (display-only keys must never be
> boot-fatal — it reads the shell-true spellings). The right fix — moving the spelling rule
> into `config` and having `setup.IsTrue` delegate — changes `MAIL_ENABLED` parsing and needs
> its own change with its own tests. Also noted: the mail-test rate budget is spent before the
> 503/409 checks (an unconfigured deployment can burn its 3/hour on 503s — standard middleware
> ordering, cosmetic).
>
> **What wave 6 leaves open after tranche 2:** item 9's nine-step wizard itself, now
> architected as `vidra setup --web` on the host binary (the ruling and its evidence are in
> item 9's entry) — a tranche-3-sized build; the spelling-gap follow-up above; and tranche 1's
> recorded follow-ups (bundle-aware `vidra update`, the typed-keys blind spot in meta-ci's
> consumer assert).

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
  **Prerequisite CLOSED (wave 6 tranche 2, 2026-08-21):** `config.validate()` now collects
  every semantic error (parse errors keep their short-circuit — semantics over garbage values
  is second-order noise; duplicate findings dedupe; guarded branches stay guarded; multi-var
  rules stay unattributed — each property pinned by a test), `instancesettings.Validate` is
  exported, `Apply` reports every invalid key, and `POST /admin/instance-settings/validate` is
  the callable per-field surface — sharing the PATCH's coercion switch so dry-run and write
  messages are word-identical by construction. The admin config UI already consumes it,
  retiring the five hand-copied TypeScript validators (the exact drift `NormalizeOrigin`'s
  doc comment forbids).
  **Architecture ruling for the remaining nine-step wizard (tranche 3, from the wave-6
  research):** it will be served by the **host `vidra` binary** (`vidra setup --web`, loopback
  bind), not the frontend container. Three verified facts force this: the api container cannot
  install (no docker socket, no deploy tree, no env file on disk — config arrives as process
  env) and structurally cannot report its own boot failure, which the item explicitly asks to
  surface; a frontend-served wizard has a fatal pre-TLS origin problem (`singleOriginKeys`
  points browser JS at the not-yet-live public origin, and CORS pins the same single origin,
  so the documented SSH tunnel reaches a page whose API calls go to a dead address); and the
  item's own "binds to localhost pre-TLS with an SSH-tunnel instruction" line is only
  coherently satisfied by a host-side server. Every ingredient exists (`Generate`,
  `RenderCaddyfile`/`RenderNginxExternal` are deliberately pure; `Check`/`Warnings` are pure
  over a map; `doctor.Report` is a serialisable struct; `preflight` is host-free; the binary
  already execs deploy.sh) except an HTTP listener and embedded wizard assets. The Admin
  Account step stays where it shipped — `/setup/claim` in the frontend, post-TLS.
  **Wave-4 update (partial):** the *answer-shape* trio is now callable — `setup.NormalizeOrigin`,
  `setup.NormalizeTLSMode` and `setup.CheckAcmeEmail` are exported wrappers over the engine's
  own unexported validators (item 10 uses them to re-ask at the prompt), so domain, TLS mode
  and ACME address can be validated one field at a time by the same code that would later
  reject the file. Two caveats: they live in `internal/setup`, so a web wizard reaches them
  through an endpoint that has yet to be written; and the instancesettings half — the runtime
  settings the wizard's Optional Features step edits — is still unexposed.
- [x] **10. Terminal wizard + non-interactive install** *(implemented 2026-08-20, wave 4:
  `vidra-core prod/phase1-wave4` 992e2e3 + 395e84f + d173baa + c85f320 + 4b20b61 + 75a88fb +
  ff164fc)* — the engine and the TTY interview shipped with item 8; this is the six things
  standing between them and an install that survives a real operator.
  **(1) A non-TTY stdin is refused before the first question.** `curl … | sh` holds stdin, so
  the interview used to print question one, read EOF, and die with "no answer for …" —
  halfway through a run the operator had watched start, having written nothing. The mode is
  knowable up front, so it is answered up front, naming both ways forward (a real terminal,
  or `--non-interactive` with the answers as flags). The file-ness test is one-sided on
  purpose: only a stdin that *positively* reports it is not a character device is refused, so
  a test's `strings.Reader` or an in-process pipe behaves exactly as before — "not provably a
  terminal" must never become "refuse the install".
  **(2) `--answers <file>`** — one `flag-name = value` line per answer, because the
  alternative to a file is one enormous shell line retyped correctly on the next host. The
  vocabulary is the flag names themselves, so `-h` is its documentation and there is no
  second spelling to keep in step. Two rules make it safe: **argv always wins** (the file is
  applied through `fs.Set` only for names `fs.Visit` did not report, so a flag beside a file
  that disagrees is an override, not a conflict), and **it implies nothing else** — not
  `--non-interactive`, not `--yes` — so a partial file is a pre-seeded interview. Every line
  is validated even when argv overrides it (a typo is a typo), unknown names are reported
  with file and line number, and `-` (stdin) for the four secret flags is refused *from
  inside a file*: stdin belongs to the terminal and only one flag may ever claim it.
  **(3) `--instance-name` plus one interview question** kills the silently-shipped
  `INSTANCE_NAME=Example Video`. That value is not a `<…>` placeholder — it is plausible — so
  the placeholder pass had nothing to say about it and `Check` had no grounds to reject it,
  and **every unattended install to date served it**: at `GET /api/v1/instance`, in NodeInfo,
  and as the TOTP issuer label in every user's authenticator app. Empty still means
  unanswered, so a re-run about a release tag cannot reset the name the instance is known by.
  **(4) The interview's storage default flips to `local`** when the S3 key pair it would fall
  back to is still the template's `<your Spaces access key>` placeholders — a default that
  cannot pass `Check` is not a default, and the old one refused to write *anything* after
  every other question had been answered (the wave-3 note recorded this as a pre-existing
  template gap; this is the fix). The template's `s3` remains the recommendation the moment
  real keys are behind it, a re-run on an S3 instance is offered s3 back, and non-interactive
  behaviour is untouched — with nobody to offer an alternative to, the refusal naming the
  placeholder key is still the right answer.
  **(5) Prompt-time re-ask validation** for the three answers that have a shape.
  `https://*.example.org` used to be accepted at the prompt, carried through every remaining
  question, and then rejected by `Generate` — which writes nothing, so one typo cost the
  whole interview. Origin, TLS mode and ACME address are now checked where they are typed and
  re-asked until usable, through **exported wrappers around the engine's own validators**
  (`NormalizeOrigin`, `NormalizeTLSMode`, `CheckAcmeEmail`) rather than a second, friendlier
  opinion — a prompt that accepts what `Generate` rejects is the bug being removed, and two
  implementations is how it comes back. The domain then gets **one non-blocking ✓/⚠ DNS
  line** (5s bound, `preflight.CheckDomain` behind one indirection so the tests need no
  nameserver): DNS that does not point here yet is an ordinary state of a fresh install —
  it is what `VIDRA_TLS_MODE=internal` exists for — and a check that could not *complete* is
  ⚠, never ✗, per `internal/preflight`'s doctrine.
  **(6) The report ends with the owner-claim handoff** — where the one-time token is printed,
  where to redeem it, and that a restart mints a fresh one and invalidates the previous
  (which is what turns a copied-too-late token into a confusing failure). Generating the env
  file otherwise left an operator two commands away from an instance nobody can log into,
  with nothing naming the two. The quoted log command is `./deploy/compose.sh logs api` and
  never a bare `docker compose logs api`, which on a deployment host auto-loads the dev
  override and addresses a different project.
  **Test-shape change worth keeping:** the interactive tests no longer script stdin as a
  fixed count of newlines. They answer **by question** and assert *which* question was asked,
  so the next question added cannot break five unrelated tests — and the pre-seeded-interview
  case (what a partial `--answers` file leaves to ask) becomes assertable at all.

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
- [x] **12. External proxy / deliberate plain-HTTP modes** *(implemented 2026-08-21, wave 6:
  core `prod/phase1-wave6` 0accc63..303f35c, user 9ebd4ef..f383f7d, meta b21d315..4a3fcf8)* —
  `VIDRA_TLS_MODE` grew two modes, both gated, both explicit. **`external`** (operator
  terminates TLS): caddy sits behind a new `edge` compose profile that the *engine* decides —
  `deploy/lib.sh`'s `edge_profile()` and `setup.SkipsManagedCaddy()` are the two spellings of
  one rule, "append `edge` unless mode is external" — so every existing env file keeps its
  caddy with zero edits; setup emits `deploy/nginx-external.conf.example` instead of a
  Caddyfile (routing mirrors `deploy/Caddyfile`, upstream ports read from the resolved
  `HTTP_PORT`/`FRONTEND_PORT`, gitignored like `Caddyfile.local` so install.sh's
  clean-tree check never wedges); deploy.sh skips the Caddyfile gate, reload and DNS
  preflight loudly and downgrades the edge probe to a warning, because the edge is
  operator-owned. **`plain-http`** (deliberate no-TLS for lab/LAN): caddy *stays*, generated
  as an `http://<host>` site — the managed edge and all its deploy gates survive, including
  `require_real_domain`'s placeholder and site-address⇔origin checks (only the DNS preflight
  is skipped, and the probe speaks http). **One https predicate in core:**
  `PUBLIC_BASE_URL`'s scheme drives both `CookieSecure()` and HSTS
  (`PublicOriginIsHTTPS()`), and an `http://` origin in production is a hard boot **refusal**
  unless `VIDRA_ALLOW_PLAIN_HTTP=true` — the consent lives in `config.validate()` itself, so
  the wizard, doctor and boot cannot drift, and the old failure (production pins Secure,
  login silently dies over http) became a named error. **Breaking change, deliberate:** a
  production deployment already serving an `http://` PUBLIC_BASE_URL refuses to boot until
  the consent var is set. The frontend's HSTS moved from the build-baked header list to
  `proxy.ts` (Next 16's middleware), keyed on the same `PUBLIC_BASE_URL` at *runtime* — unset
  or unparseable emits (fail-secure; RFC 6797 makes over-emission over http a no-op), only an
  explicit `http://` origin suppresses. `TRUSTED_PROXY_CIDRS` (validated CIDR list →
  `echo.TrustIPRange`) covers public-IP terminators; setup warns when external mode leaves it
  empty, because the silent failure is every visitor behind the LB sharing one login budget.
  Setup also now warns on placeholder domains and ported origins (caddy publishes 80/443
  only) at generation time instead of letting deploy.sh refuse them later.
  **Verification:** fresh un-cached `make ci` + `npm run ci` green; all five modes exercised
  end-to-end through `vidra setup --template` + doctor; caddy itself validated the plain-http
  Caddyfile; the generated nginx example passes `nginx -t`; an adversarial audit caught (and
  wave 6 fixed) the one real drift — core's `checkProfiles()` compose-chain builder not
  knowing `edge`, which had silently dropped caddy from doctor's port-exposure audit.
  **Recorded gaps:** core emits 2y HSTS and the frontend 1y on the same origin (pre-existing,
  now adjacent); federation/OAuth keep their https-in-production requirement — a plain-http
  instance cannot enable them, by design.

### The `vidra` CLI

- [x] **13. `vidra` CLI core** *(implemented 2026-08-20, wave 4: `vidra-core prod/phase1-wave4`
  470b691 + 62d3906 + 86c5029, `cmd/vidra`)* — an operator now learns `vidra <verb>` instead
  of a directory of scripts, and every verb works from anywhere via `-C/--repo`.
  **The five deploy commands are wrappers, not re-implementations.** `deploy`, `rollback`,
  `backup`, `restore` and `release` resolve `deploy/<name>.sh` under `--repo`, **exec** it
  through bash with the operator's own terminal attached, and return its exit code unchanged.
  There is no Go copy of `MIN_EMBEDDED_MIGRATE_TAG`, no second `Caddyfile.local` check, no
  added prompt: a transcription of any gate is a second opinion that has to be hand-synced,
  and the first symptom of it drifting is a deploy `vidra` allows and `deploy.sh` would have
  refused. `restore.sh` and `release.sh` each keep their one confirmation, and
  `--yes` / `RESTORE_CONFIRM` reach them verbatim. **Exec, not run**, is also what preserves
  exit-code fidelity for `vidra deploy || vidra rollback …`, and TTY passthrough is what keeps
  the scripts' own prompts and progress usable.
  **`ENV_FILE` precedence is preserved rather than reinvented:** each script already reads
  `${ENV_FILE:-env/production.env}` from its environment, so `vidra` injects only a *default*
  — an `ENV_FILE` the operator exported (`ENV_FILE=env/staging.env vidra deploy`) is never
  overwritten, and an exported-but-empty value counts as unset because that is how `:-` reads
  it. Flag parsing is a hand-written loop that stops at the first token it does not know
  (`--` ends `vidra`'s half explicitly), precisely so a `FlagSet` cannot eat `restore.sh`'s
  `--yes` or reorder `release.sh`'s repo list.
  **`vidra logs`** is `deploy/compose.sh` with `make prod-logs`'s own `-f --tail=100`, so both
  show the same 100 lines of the same project. **`vidra restart <service>`** maps product
  names → compose services and adds the three refusals compose cannot give, because compose's
  own error sends the operator to the wrong place: a one-shot (`migrate`, `search-migrate`,
  `prep-volumes`) restarts happily and does nothing; postgres/redis on a `VIDRA_EXTERNAL_*`
  deployment answer "no such service", which reads as "your deployment is broken" rather than
  "that database is managed elsewhere"; and so does a service outside
  `VIDRA_COMPOSE_PROFILES`, when the answer is one key in the env file. Restarting caddy says
  first that `vidra deploy` reloads the config with no dropped connection and this does not.
  **`vidra status`** answers "is it up": compose `ps`, the api's `/readyz` (with its
  per-dependency line) and `/schemaz`, the search service's `/readyz` **exec'd from inside the
  network** (where in production it is reachable at all), and the frontend's `/healthz` with a
  `/` fallback — all on 127.0.0.1, in doctor's ✓/⚠/✗ glyphs and doctor's exit rule (1 iff any
  ✗). A stack that is simply down is ⚠ with the reason, an image too old for `/schemaz` or for
  the frontend `/healthz` is ⚠ and never a failure, and a raw Go error never reaches the
  operator.
  **Deliberately deferred:** the spec's "admin system endpoint" half of `status`. It stays
  **unauthenticated** — a CLI that stored an admin JWT to render a status screen would be a
  credential on disk in exchange for a nicer table; the richer per-dependency view
  (object store, SMTP, search, ffmpeg — item 19) is a page an admin opens, and `vidra doctor`
  already probes those from the host without a token.
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
- [x] **15. `vidra update`** *(implemented 2026-08-20, wave 5: `vidra-core` 3012ad0 + 0f523a8 +
  4083e8f, hardened by 8c13b24 + 4aaee44 + f373ffa; on main via core#46→#52, meta 77f9758)* —
  the one CLI verb that is **not** a wrapper, and `cmd/vidra/main.go` says why: there is no
  script under `deploy/` for *choose a version, decide whether it is safe, write it down, and
  clean up after a failure*. Everything that already exists is still run by the thing that owns
  it — the pre-deploy dump, `MIN_EMBEDDED_MIGRATE_TAG`, the Caddyfile and DNS preflights, the
  migration steps and every probe stay in `deploy/deploy.sh`, invoked through the same
  Passthrough as item 13's five wrappers so the operator watches their own terminal.
  **Release discovery is `net/http` against api.github.com, not `gh`** (3012ad0) — the CLI is
  a static binary an installer drops on a droplet, and a version check that first needs a
  second tool installed is a version check nobody runs. `githubAPIBase` is a package variable
  so the tests serve their own releases from `httptest` and nothing in the suite leaves the
  machine. **All three components must carry the same tag**: a release that exists in two of
  them is a broken release, and pinning it turns into a `docker compose pull` failure halfway
  through a deploy instead of a refusal before it.
  **The schema floor is the reason item 19 made `/schemaz` numeric.** `vidra deploy` will ship
  an image whose embedded migrations are older than the database's ledger and notice nothing:
  `migrate up` on a behind image is a no-op, the stack comes up green, and the fault surfaces
  later as code reading columns added after it was built. deploy.sh cannot catch this because
  it checks the ledger against the checkout it just moved to the *same* tag — it compares the
  image with itself. So this command reads the running api's `/schemaz` on loopback and
  **refuses** an image that carries fewer migrations than the database has applied. Every other
  outcome is a note, not a refusal: an api that is down, or an image predating `/schemaz`, or a
  malformed document leaves the update ungated and says so, because refusing on what could not
  be read makes a probe an outage.
  **The automatic tag-flip rollback is armed for exactly one release step.** deploy.sh's
  failure text correctly tells the operator to run `rollback.sh`; it is a bad moment to be
  reading an instruction, because the site is down and the previous tags are in the file that
  was just overwritten. They are held in memory here and flipped back without being asked —
  but only when the target is one release ahead of what is running, since a tag flip does not
  touch the database and the one-release schema-compat policy (item 16's lint, now enforced in
  both migration-owning repos) is precisely the guarantee that makes flipping back *one*
  release safe. It says nothing about flipping back three, so three is not offered.
  **Multi-generation env history replaces the single `.bak`** (0f523a8 in Go, 77f9758 in
  `deploy/lib.sh`'s `env_snapshot`, both wired into rollback.sh). One `.bak` records one
  generation and the next run overwrites it: `rollback.sh v0.2.1` then `rollback.sh v0.2.0`
  and the `.bak` holds v0.2.1 — the middle of the incident, the one state nobody wants back —
  while the tags served *before* it started, which is what the incident notes need, are gone.
  Snapshots now land at `backups/env-history/<env-basename>.<UTC %Y%m%dT%H%M%SZ>`, ten
  generations of that basename, `VIDRA_ENV_HISTORY_KEEP` to change it. **The path shape is a
  cross-language contract**: the Go half and the shell half write and prune the same directory,
  so a disagreement about the separator or the stamp means each prunes the other's history (or
  neither prunes and it grows without bound). They are byte-for-byte agreed on directory,
  separator and format, the keep variable is read by both, and the tests state keep-vs-left
  explicitly rather than counting survivors. Files are `cat >` under `umask 077` into a 0700
  directory, never `cp` then `chmod` — `cp` takes the *source's* mode, so a hand-created 0644
  env file would be copied world-readable and a later chmod leaves a window, however short, in
  which the whole host can read `MFA_KEY_KEK`.
- [x] **16. CI-enforce the one-release schema-compat policy** *(implemented 2026-08-20,
  wave 4: `vidra-core prod/phase1-wave4` 464c6dd + d68faa9 + f10957f + fc164a9 + d098e34,
  `vidra-search prod/phase1-wave4` dcded14 + cf12454 + c12d17a + 3da1d91)* — the policy
  ("release N−1's code must keep running against release N's schema", deploy/README.md) was
  documentation only, and it is the sole reason `rollback.sh` can be a 60-second tag flip
  that never touches the database. It now has a cheap static half and an expensive dynamic
  half.
  **The lint** — `scripts/migrate-lint.sh`, byte-identical in both Go repos and wired into
  each one's canonical `make ci` (which `backend-ci.yml`/`search-ci.yml` run and `ci-guard`
  forces them to keep running, so it blocks locally and on GitHub at the same time, in the
  first second rather than after `test-race`). It rejects DROP TABLE/COLUMN, RENAME,
  TRUNCATE, SET NOT NULL, `ALTER … TYPE`, DELETE FROM and dropping a
  type/view/function/trigger/sequence/schema in any `*.up.sql`; down files are exempt because
  they **are** the rollback path. Matching runs per *statement* on a normalised copy
  (comments and single-quoted literals stripped, uppercased, every non-identifier character
  turned into a space) so `CHECK (policy IN ('rename', …))` and a column named `rename_count`
  cannot false-positive. Three constructs are deliberately legal: **DROP CONSTRAINT judged at
  end-of-file, allowed only when the same file re-ADDs the same constraint name** (the
  widen-a-CHECK idiom, 10 sites in core's history), `DROP NOT NULL` (relaxing is
  additive-safe), and `DROP INDEX` (invisible to application code). `-- migrate-lint:allow`
  is the escape hatch, mirroring `# ci-guard:allow`. **All 104 core and 14 search up
  migrations pass with zero grandfathered exceptions** — nothing had to be waived to turn it
  on, which is what makes the rule enforceable.
  **The N−1 job** — vidra-core's new `.github/workflows/schema-compat.yml`, path-filtered to
  `migrations/**`: apply HEAD's migrations to a fresh database, check the highest `v*` release
  tag into a worktree, and run **that tree's** `make test-integration` against the
  already-migrated schema. sqlc emits explicit column lists, so a column this PR drops,
  renames, narrows or makes NOT NULL fails the previous release's store tests hard — the exact
  breakage an operator hits halfway through a rollback. clamav and ffmpeg are provided and
  `DATABASE_URL` is set so the old suite cannot silently self-skip (a suite that skips proves
  nothing), and a missing `v*` tag is a loud failure rather than a vacuous pass. Rehearsed
  locally before shipping, **with a negative control**: 38/38 PASS against v0.2.0's store
  suite, versus exit 1 and `column "description" does not exist` from six tests once
  `videos.description` was dropped to stand in for a destructive 0105.
  **Search CI stopped downloading the golang-migrate CLI** and migrates with
  `go run ./cmd/api migrate up` — the same embedded migrator the published image runs, so CI
  exercises the production code path and there is no CLI version left to keep pinned.
  **Core CI now runs postgres 18 / redis 8**, the versions the compose files and production
  ship: a gate on 16/7 can pass a migration that stalls or fails on the major operators
  actually boot, and a rollback proof on the wrong major proves the wrong thing.
  **The two stale sub-items were verified already done, not skipped:** vidra-search's
  Dockerfile has injected `VERSION`/`COMMIT`/`BUILD_DATE` ldflags since wave 2 (`/version` no
  longer reports 0.1.0 forever), and the golang-migrate pin skew (CI 4.17.1 vs compose 4.19.1)
  no longer exists anywhere — wave 2's embedded migrator removed every CLI download from both
  repos' workflows, and wave 4 removed the last two in search.
  **Residual, both known:** the two `migrate-lint.sh` copies are **hand-synced with nothing
  asserting it** (they carry no repo-specific strings precisely so they can stay identical; a
  cross-repo checksum assertion would be cheap and does not exist), and the second half of the
  policy — the two-release drop cycle — remains unenforceable by lint and invisible to the
  N−1 job, which proves N−1 still *reads and writes* fine but not that N−1 had already stopped
  writing what N removes. Staged drops still need a reviewer.

### Installer + host

- [x] **17. One-command installer** *(implemented 2026-08-20, wave 5: meta `install.sh` +
  CI at 8f01f1b/1d40827; `vidra-core` release-assets workflow e8ceb3b/ce9b5fe)* —
  `curl -fsSL <url> | sh` now detects the platform, checks or installs Docker and Compose,
  puts the checksum-verified `vidra` binary in `/usr/local/bin`, lands the deployment tree in
  `/opt/vidra`, and hands the terminal to `vidra setup`.
  **The `/dev/tty` reattach is the whole trick.** Under `curl … | sh`, stdin *is* the script,
  which is exactly the state item 10 taught the wizard to refuse before its first question —
  so an installer that shells out to `vidra setup` with stdin as it found it would print a
  correct refusal at the end of an otherwise successful install. Every question, including the
  installer's own, is read from `/dev/tty` instead. The terminal test is `( true < /dev/tty )`
  and not `[ -t 0 ]`, which is false for every piped install, nor `[ -r /dev/tty ]`, which is
  true on a host with no controlling terminal at all; when it genuinely cannot be opened the
  installer says so and names `--yes`, rather than failing one question at a time.
  **Binaries are verified or not installed.** `SHA256SUMS` is fetched from the release, the
  single line for this asset is extracted, and `sha256sum -c` gates the install — a missing
  `sha256sum`, a missing sums file, an unlisted asset and a mismatch are each a `die` with the
  binary discarded, because an unverified binary about to hold the instance's secrets is not
  worth having. A `/usr/local/bin/vidra` that is already byte-for-byte the download is left
  alone. `vidra-core`'s new `release-assets.yml` is what makes any of this exist: it
  cross-compiles `cmd/vidra` for linux and darwin on amd64 and arm64, writes bare-name
  `SHA256SUMS` so `sha256sum -c` works from any directory, and uploads both to the release.
  **The tree is resumable and secrets are never re-minted.** Whatever a failed run already
  created is left in place and re-running continues; a checkout with uncommitted changes or on
  a non-`main` branch is reported and not touched rather than fast-forwarded over; and the env
  file belongs to `vidra setup`, which refuses to rewrite an existing one without `--yes` —
  re-minting `MFA_KEY_KEK` orphans every MFA, federation and ATProto secret already sealed
  under the old one.
  **Deviation from the item as written — "(no git clone)" shipped as "no MANUAL git".** The
  installer drives git and `bootstrap.sh` itself, so the operator never types a git command,
  but the tree really is a checkout. Three hard dependencies make a git-free install impossible
  today: `docker-compose.yml` `include:`s `./vidra-core/docker-compose.yml` unconditionally, so
  the core repo must be on disk before compose parses anything at all;
  `vidra-core/deploy/media/nginx.conf.template` is bind-mounted by the media profile's
  nginx-rtmp service; and `deploy.sh` derives its expected schema version from
  `ls vidra-core/migrations/*.up.sql` and keeps the checkouts in step with `git -C … fetch
  --tags --force`, refusing a `vidra-core` that is not a git checkout. A true artifact bundle
  (the compose files, the Caddyfile and nginx templates, the migration inventory, shipped as
  release assets rather than repositories) is a real piece of work and **stays open** — fold it
  into item 12's compose surgery or carry it as a follow-up. *(Closed in wave 6, tranche 1:
  the bundle ships all three dependencies at their checkout-relative paths, the manifest
  replaces the `ls`, and install.sh is bundle-first — the wave-6 note in the Foundations
  section has the full record.)* Meta-ci covers what it can without
  a host: `sh install.sh --help` runs under `/bin/sh`, needs no network, no root and no clone,
  and is asserted to document every flag and environment variable it accepts.
  **Timing caveat, stated by the installer itself:** its happy path begins with the first
  release cut *after* `release-assets.yml` landed — v0.2.1. v0.2.0 and everything before it
  have no assets to download, and rather than failing opaquely the installer names the
  situation and points at `make build-vidra` in the checkout it has already made.
- [x] **18. Host provisioning + backup completeness** *(implemented 2026-08-20, wave 5: meta
  d1393f4 + 7669b80 + a5b7584 + 5f7a3f5 + 7e3c77f + 762262d)* — both halves.
  **`deploy/provision.sh`** is the runbook's host-prep section, executed: firewall, swap,
  `/opt/vidra` and the service user, the systemd backup timer installed *and verified*. The
  media profile's 1935 is opened only when it is on, because a permanently open RTMP port on a
  host that does not ingest RTMP is an attack surface bought with nothing.
  **`deploy/cloud-init.yaml.example`** is the same work at first boot for anyone whose provider
  has a user-data box. Meta-ci validates it as **ASCII** cloud-config with `#cloud-config` on
  line one — cloud-init treats a payload whose first line is anything else as not-a-config and
  silently ignores it, which is a provisioning failure that looks like a successful boot, and
  the ASCII rule is the DigitalOcean user-data trap this program has already been bitten by
  once.
  **The backup gap is closed by `vidra-config-<stamp>.tar.gz`** (5f7a3f5): the env file plus
  `deploy/Caddyfile.local`, written beside each dump, shipped to the **same** off-site
  destination in the same rclone/scp pass, and pruned by the **same** daily+weekly retention
  rule. That last point is why the archive is not a separate mechanism with its own schedule:
  eight weeks of dumps sitting next to three weeks of the configuration required to restore
  them is a recovery that fails at exactly the moment it is being relied on. The prune helper
  is one function parameterised by the stamp's offset in the basename (7 for `vidra-`, 14 for
  `vidra-config-`) precisely so the two families cannot drift apart. `deploy/README.md` now
  carries the restore order this unblocks, and names the volumes still backed up by nothing.
  **Wave-3 note, carried forward and now with a wave-5 consequence:** external-Postgres
  deployments **refuse** backup.sh and restore.sh outright — both work by `docker exec` inside
  the bundled container, which `docker-compose.external-postgres.yml` keeps out of the project
  — with provider snapshot/PITR guidance instead; backing up a managed database is deliberately
  not reimplemented. backup.sh's refusal is placed *before* the healthchecks.io trap on purpose,
  so the dead-man's switch goes silent and the inactivity alert fires, which is the honest
  signal for a host that genuinely takes no backups from here. **That ordering is preserved,
  and it costs the config archive too**: a fully-refusing external-Postgres host writes no
  archive either, because the refusal comes first by design and moving the archive above it
  would restore the dead-man's ping on a host that backs up nothing. Backing that instance's
  config up is documented (`deploy/README.md`) and not automated — the honest state, rather
  than a half-backup that pings green.
- [x] **19. Health surface hardening** *(implemented 2026-08-20, wave 4: `vidra-core
  prod/phase1-wave4` 986a794 + fabda52 + b2b6f18 + dce4ed4, `vidra-user prod/phase1-wave4`
  f3a25d4 + 280fcf5, meta df1523f)* — all three halves.
  **`GET /schemaz` on core** — `{"software":{name,version,commit,build_date,go},
  "schema":{"version","dirty","applied"}}`, root-mounted and unthrottled beside `/healthz`,
  `/readyz` and `/version`. `applied` exists because a fresh install and a database at
  version 0 are the same integer and must not be the same answer, and the comparison is
  numeric so `vidra update` can refuse an image whose embedded migrations are older than the
  database it is pointed at. It **always answers 200**, including when the database cannot be
  read (the error goes *inside* the document): a caller that gets a 5xx cannot tell "no api
  here" from "api here, database gone", which is the one distinction the probe exists to
  draw. The ledger read goes over the server's own pool with a context — `dbmigrate.Version`
  was the obvious call and the wrong one, because it opens a connection per probe and
  **creates** the ledger table when missing, i.e. a write on a read path; the table name comes
  from `dbmigrate.Table` so nothing re-spells the literal. **Deliberately not edge-routed:**
  `deploy/Caddyfile` proxies a root-path allow-list and this is not on it, so it is host-local
  tooling's surface (`vidra status`, `vidra doctor`, the future `vidra update`) dialing
  127.0.0.1 — an operations endpoint that names build and schema has no business being on the
  public internet. It is still declared in `api/openapi.yaml`, because
  `TestOpenAPIContract` enumerates every unconditionally registered route and `/version` set
  the precedent.
  **Four components on `GET /api/v1/admin/system`** — object store, SMTP relay, search
  service and the ffmpeg binary, i.e. the four dependencies operators actually get wrong,
  which were invisible until something failed downstream. Probed concurrently under their own
  3s deadlines so a relay that accepts a connection and then stops talking cannot decide how
  long the page takes; `not_configured` (local storage, mail off, no search service) never
  degrades the instance, because those are supported deployments and not faults; the search
  probe asks the service's own `/readyz` rather than the background prober's cached flag,
  since an admin looking at the page wants the answer now; and storage is `BucketExists`,
  never `EnsureBucket` — a diagnostic that creates the bucket it could not find turns a typo
  in `STORAGE_S3_BUCKET` into a new, empty, silently-wrong store. `/readyz` keeps its cheap
  two-dependency contract: it runs on every orchestrator tick, this runs when someone opens a
  page. `preflight.CheckSMTP` is doctor's dial lifted out whole rather than copied — two
  implementations would eventually disagree about one mail server.
  **The finding that made the frontend route load-bearing:** `GET /` was never a
  frontend-only test. vidra-user's root layout **and** its home page both await
  `getInstanceConfig()`, which fetches vidra-core over `INTERNAL_API_BASE_URL` — so a degraded
  api marked the *frontend* container unhealthy (a cascading false-fail that restarts a
  container that is fine), on top of the known false-fail of a full render missing a 5s
  timeout under transcode load. `app/healthz/route.ts` is the cheapest possible answer: a
  route handler skips the root layout, and this one **imports nothing at all** (the unit test
  asserts exactly that, alongside `force-dynamic` and the 200 body). At the public edge
  `deploy/Caddyfile` routes `/healthz` to the api, so the route is reachable only
  container-internally — a shadow that is known and accepted.
  **The CMD-SHELL fallback trick (meta):** `docker-compose.prod.yml`'s frontend healthcheck is
  now `CMD-SHELL` with `wget … /healthz || wget … /`. The fallback is what keeps this off the
  hard merge order — images older than the route 404 the first wget and pass on the second, so
  no `MIN_*_TAG`-style floor is needed and a rollback to v0.2.0 stays healthy. `CMD-SHELL`
  rather than `CMD` because the fallback is a shell `||`, not a wget flag. `deploy.sh`'s
  one-shot probe deliberately stays on `/`: a deploy gate runs once and wants the strongest
  signal (a full render, with the api proven ready one line above), while the recurring
  container check wants the cheapest one that cannot lie about whose fault it is.
- [x] **20. Admin infra visibility** *(implemented 2026-08-21, wave 6 tranche 2: core
  `prod/phase1-wave6b` 7938a13..6cccc16, user 1321658..5636ead)* — `GET /admin/infrastructure`
  renders read-only Server / Storage / Networking / Backups panels plus a 13-capability
  feature-discovery list, and `POST /admin/mail/test` sends one probe message.
  **Env-derived and guidance-oriented, literally:** every response field is hand-picked with a
  justifying comment, and the no-secret test plants sentinels in every secret-bearing config
  field *and* every internal endpoint (DSNs, S3 keys, SMTP credentials, KEKs, tokens, ClamAV /
  Whisper / RTMP / IPFS addresses) and asserts none reflects. **The Backups panel is
  guidance-only by proof, not laziness:** the api container has no bind of `backups/`, none of
  the backup env, no docker socket and no systemd — four walls verified — so it renders the
  documented cadence, the 26-hour staleness rule, the two artifact families and (via the new
  display-only `VIDRA_EXTERNAL_POSTGRES` passthrough, which accepts the shell-true spellings
  and is never boot-fatal) the managed-database advice, then points at `vidra doctor` for live
  state. **Feature discovery keys on the flags the api owns** — compose profiles are invisible
  to the container, and the flag is the honest signal anyway. Off features get "Optional: …";
  on-but-unconfigured gets a warning and a bare finding, because a broken relay is not
  "optional" (deliberate deviation, recorded). Deep-links exist only where a runtime settings
  page actually holds the switch; an e2e assertion pins that boot-env-only features get none.
  **The item's own examples were aspirational:** DASH and CDN do not exist in core (phase 3/4
  items), so the pattern shipped over the thirteen real capabilities and those two slot in
  when they exist. **Mail test cannot become a relay:** the recipient is the instance contact
  address, the request body is ignored (asserted), the limiter is 3/hour per admin, all three
  failure modes are typed errors with stable codes that survive the generic 5xx scrub, and the
  audit event carries an outcome — never an address.

## Safe-defaults checklist (Phase 1 exit criteria)

- HTTPS + managed Caddy; local Postgres/Redis/storage; HLS; H.264 compatibility profile.
- DRM disabled; DASH/IPFS/P2P/CDN optional and off.
- Owner-claim bootstrap (no first-registrant race); registration policy an explicit choice.
- No secret defaults survive an unedited install; all secrets generated.
- Bare `docker compose up` on a prod host must not silently load the dev override
  (rate limiting off) — doctor detects; docs + CLI make the right invocation the only obvious one.
- Media GC gets an explicit enable/dry-run story *before* Phase 2 (see phase-2 doc).
- Every `vidra` command works on the proven single-host recipe.
