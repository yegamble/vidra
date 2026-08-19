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
- [ ] **6. Remove runtime git dependence** — compose bind-mounts `vidra-core/migrations`,
  `vidra-search/migrations`, `deploy/Caddyfile`, and the nginx-rtmp template from live
  checkouts, making no-git install structurally impossible. Bake migrations into the
  migrate/api/search images; ship Caddyfile + nginx template as generated artifacts.
- [ ] **7. Extract a callable validation library** — validation logic exists twice
  (config.validate() and instancesettings validators), neither invocable against candidate
  answers. The setup engine, wizard, and doctor all need per-field validation of *proposed*
  values.

### Setup engine + wizard

- [ ] **8. Setup engine** (new command under `vidra-core/cmd`, invoked by the CLI/installer) —
  **generates** `env/production.env` in the existing fail-loud template format; auto-generates
  all secrets (incl. POSTGRES_PASSWORD); **never silently re-mints KEKs on re-run**
  (MFA/FEDERATION/ATPROTO KEK rotation is destructive); keeps `SEARCH_INTERNAL_SECRET`
  consistent across services; maps local-vs-external component answers to compose profiles
  (postgres/redis/storage/scan/media/captions/otel/ipfs) + env; finishes with the
  `docker compose … config` render check. See interfaces.md §1 for the service shape.
  - Component profiles: external Postgres/Redis/S3 answers must *not* launch the local
    equivalents; S3-as-canonical must not require permanent local media storage.
- [ ] **9. Web setup wizard** — first-run flow: Welcome → System Check → Basic/Advanced →
  Domain/Networking → Storage → Admin Account (consumes the owner-claim token) → Optional
  Features → Review → Install → Success. "Recommended setup" makes production-safe decisions
  automatically; Advanced exposes external DB/storage/proxy/IPFS. Backbone already exists: the
  instancesettings Snapshot metadata (kind/default/validator/options/page/section) and the
  metadata-driven AdminInstanceConfigView machinery prove the rendering approach. Wizard binds
  to localhost pre-TLS with an SSH-tunnel instruction (`ssh -L 8080:localhost:8080 user@server`);
  never expose an unauthenticated installer publicly. Surface the 15s DB/Redis fail-fast and
  settings-overlay load failures as wizard feedback, not crash loops.
- [ ] **10. Terminal wizard + non-interactive install** — same engine, `vidra setup` in a TTY;
  flags/answers-file for automation. Works without a browser.

### Managed edge

- [ ] **11. Vidra-managed Caddy** — template deploy/Caddyfile from `PUBLIC_BASE_URL`; add a
  `caddy reload` step to deploys (bind-mount edits don't recreate the container); DNS preflight
  (domain resolves to this host's public IP) **before** any ACME order (Let's Encrypt
  rate-limit protection); set ACME email; staging-CA rehearsal mode; loopback/internal-CA
  pre-TLS bring-up mode; pin the caddy image. Keep deploy.sh's require_real_domain semantics
  coherent with generated files; handle a locally-edited Caddyfile on first templated deploy.
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
- [ ] **14. `vidra doctor`** — unify the scattered runbook checks: compose version;
  rendered-port exposure; stray `vidra-core/.env` detection; Caddyfile placeholder + domain-DNS
  match; env diff vs template (catches new required keys post-upgrade); secret shape validation
  (item 7's validators); `backups/last_success` age + systemd timer health; migration ledger
  version/dirty; disk space (incl. transcode scratch); S3/SMTP/search reachability (none
  covered by /readyz); docker log caps; ffmpeg presence. Output = human-readable ✓/⚠/✗ with a
  suggested fix per failure, never raw Go errors.
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
