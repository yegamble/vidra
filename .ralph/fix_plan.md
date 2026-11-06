# Vidra Monorepo — Ralph Orchestrator Gate

> ⛔ STOP GUARD: **Never create application code at the monorepo root.** All code,
> tests, config, Docker, and docs go inside `vidra-core/` or `vidra-user/`. The root
> holds only `.git`, `.gitignore`, `README.md`, `.github/workflows/`, and `.ralph/`.
>
> This is the **coarse gate** for a single orchestrator loop run from the root. It
> exists to keep the loop alive and track overall progress. The **real, detailed task
> lists live in the subdirectory plans** — work from those:
> - `vidra-core/.ralph/fix_plan.md`
> - `vidra-user/.ralph/fix_plan.md`
>
> Tick a phase box here **only** when that whole phase is genuinely complete
> (`VERIFIED`/done) in the corresponding subdirectory plan. See `.ralph/PROMPT.md`.

## vidra-core (Go backend) — phase gate

- [ ] P0 — Ralph control plane and PeerTube parity tracking (`vidra-core`) (sub-plan 13 open, L52–L68: PeerTube reference pin + the endpoint/model/job/config/moderation/federation mapping tables + route/control inventory rules at vidra-core `4995d024`, 2026-11-06)
- [ ] P1 — Backend project foundation (module, config, Docker, CI) (sub-plan 8 open, L79–L149: `cmd/worker`, `internal/testutil`, `Dockerfile.worker`, run-subset docs, Docker build/cache/artifact CI steps at vidra-core `4995d024`, 2026-11-06)
- [ ] P2 — Database, migrations, and sqlc (sub-plan 2 open, L164/L166: transactional test helper, migration rollback test at vidra-core `4995d024`, 2026-11-06)
- [ ] P3 — HTTP API foundation and contracts (OpenAPI, system endpoints) (sub-plan 1 open, L244: TS client/types for vidra-user — the work exists in vidra-user (`contract-ci.yml` + `npm run codegen`); the core sub-plan item is stale at vidra-core `4995d024`, 2026-11-06)
- [x] P4 — Auth, accounts, and identity (sub-plan 24/24 ticked at vidra-core `4995d024`, reconciled 2026-11-06)
- [x] P5 — Channels, profiles, and instance metadata (sub-plan 12/12 ticked at vidra-core `4995d024`, reconciled 2026-11-06)
- [x] P6 — Video publishing and media pipeline (sub-plan 39/39 ticked at vidra-core `4995d024`, reconciled 2026-11-06)
- [x] P7 — Playback, discovery, and public video API (sub-plan 14/14 ticked at vidra-core `4995d024`, reconciled 2026-11-06)
- [x] P8 — Library, playlists, comments, and notifications (sub-plan 17/17 ticked at vidra-core `4995d024`, reconciled 2026-11-06)
- [x] P9 — Moderation, admin, and safety (sub-plan 24/24 ticked at vidra-core `4995d024`, reconciled 2026-11-06)
- [x] P10 — Federation (ActivityPub, ATProto extension) (sub-plan 21/21 ticked at vidra-core `4995d024`, reconciled 2026-11-06)
- [x] P11 — Messaging (normal + encrypted foundation) (sub-plan 21/21 ticked at vidra-core `4995d024`, reconciled 2026-11-06)
- [x] P12 — Live streaming (sub-plan 11/11 ticked at vidra-core `4995d024`, reconciled 2026-11-06)
- [x] P13 — Captions and Whisper (sub-plan 8/8 ticked at vidra-core `4995d024`, reconciled 2026-11-06)
- [x] P14 — Simple crypto donations (sub-plan 7/7 ticked at vidra-core `4995d024`, reconciled 2026-11-06)
- [x] P15 — Security hardening (sub-plan 14/14 ticked at vidra-core `4995d024`, reconciled 2026-11-06)
- [x] P16 — Testing strategy (sub-plan 13/13 ticked at vidra-core `4995d024`, reconciled 2026-11-06)
- [ ] P17 — Observability and operations (sub-plan 1 open, L940: request-scoped logger propagation through service/store layers at vidra-core `4995d024`, 2026-11-06)
- [x] P18 — PeerTube import and migration (import an existing PeerTube DB + instance) (sub-plan 17/17 ticked at vidra-core `4995d024`, reconciled 2026-11-06)
- [x] P19 — Backend release gates (sub-plan 19/19 ticked at vidra-core `4995d024`, reconciled 2026-11-06)

## vidra-user (Next.js frontend) — phase gate

- [x] P0 — Ralph control plane and PeerTube parity tracking (`vidra-user`) (sub-plan 22/22 ticked at vidra-user `595ac805`, reconciled 2026-11-06)
- [ ] P1 — Frontend project foundation (Next.js, TS, Tailwind, API client, Docker, CI) (sub-plan 11 open, L200–L259: Prettier, compose override, Makefile, Docker build check, reusable workflow, Playwright cache, secrets-in-logs check, and the four OTel items — `instrumentation.ts` + `@vercel/otel` exist in the code, so the sub-plan (last edited 2026-07-08) is stale here at vidra-user `595ac805`, 2026-11-06)
- [x] P2 — App shell and navigation (sub-plan 12/12 ticked at vidra-user `595ac805`, reconciled 2026-11-06)
- [ ] P3 — Auth and account UI (sub-plan 1 open, L285: terms-of-use signup step at vidra-user `595ac805`, 2026-11-06)
- [x] P4 — Public video browsing and watch page (sub-plan 34/34 ticked at vidra-user `595ac805`, reconciled 2026-11-06)
- [x] P5 — Library, playlists, subscriptions, and notifications (sub-plan 18/18 ticked at vidra-user `595ac805`, reconciled 2026-11-06)
- [ ] P6 — Publishing and upload UX (sub-plan 1 open, L397: save-draft/publish controls at vidra-user `595ac805`, 2026-11-06)
- [ ] P7 — Studio and creator tools (sub-plan 2 open, L468/L469: remote channel sync page, quota/storage display at vidra-user `595ac805`, 2026-11-06)
- [x] P8 — Messaging UX (sub-plan 16/16 ticked at vidra-user `595ac805`, reconciled 2026-11-06)
- [ ] P9 — Moderation and reporting UI (sub-plan 1 open, L533: bulk moderation actions at vidra-user `595ac805`, 2026-11-06)
- [ ] P10 — Admin UI (sub-plan 1 open, L549: federation settings page at vidra-user `595ac805`, 2026-11-06)
- [ ] P11 — Federation, search, and external identity UI (sub-plan 1 open, L569: fake-remote federation harness follow-up at vidra-user `595ac805`, 2026-11-06)
- [x] P12 — Captions, accessibility, and i18n readiness (sub-plan 11/11 ticked at vidra-user `595ac805`, reconciled 2026-11-06)
- [x] P13 — Simple crypto donation UI (sub-plan 8/8 ticked at vidra-user `595ac805`, reconciled 2026-11-06)
- [ ] P14 — Frontend testing strategy (incl. backend-backed DB-effect e2e) (sub-plan 2 open, L621/L632: MSW (not adopted), focused-vs-full suite docs at vidra-user `595ac805`, 2026-11-06)
- [x] P15 — Frontend release gates (sub-plan 21/21 ticked at vidra-user `595ac805`, reconciled 2026-11-06)

## Backport programme (`.ralph/specs/backport/PROGRAM.md`) — phase gate

- [x] W0 — Design/template parity with the Apple-HIG templates (`vidra-user`; tasks
      W0.1–W0.13 in `vidra-user/.ralph/fix_plan.md`, spec
      `vidra-user/.ralph/specs/backport-w0-design-parity.md`). **DONE 2026-07-07**:
      all 13 tasks VERIFIED in the subplan (final commit `ec12836`, exit sweep
      re-read 120 PNGs against the templates; full `npm run ci` green per slice).
      W0.10 was upgraded mid-wave by user request from "restyle messages" to the
      full Messaging v2 frontend build (spec `vidra-user/.ralph/specs/messaging-v2.md`).
      Fresh-eyes audit: no blockers; one recorded template gap — the home "Live now"
      rail — is a tracked BACKEND dependency (no public live-listing contract; see
      W1 note below), plus two documented minors (deliberate extra filter row;
      dev-overlay artifact in evidence PNGs — hygiene fix queued in W1 frontend).
- [x] W1 — Watch & player backports. **DONE 2026-07-08, both halves audited PASS.**
      Backend (vidra-core `1c89c35..7440821`): playback-contract verification,
      chapters, video passwords + embed privacy (token unlock incl. `?pt=`),
      per-user player settings, public live-listing. Frontend (vidra-user):
      bespoke custom player (chrome-less <video>, HLS quality selector, speed
      0.25–4×, theater/PiP, shortcuts, storyboard previews, end card) + the
      backend-unblocked completion trio (chapters UI `e38805f`, player-settings
      `fb3d78c`, password UX `71004c1`). W0 follow-ups closed: Live-now rail +
      IPFS card badge shipped in the design-refresh wave.
- [x] Design-refresh wave (user-directed, 2026-07-08): the claude.ai/design
      "Vidra streaming platform design" implemented across all surfaces in
      vidra-user (18 slices, final audit PASS; closeout `3be27ba`). Includes the
      SVG-icon migration (emoji ban enforced by a lint guard), comment-reply
      @username attribution, IPFS watch-page source bar, crypto Support dialog,
      admin consoles + `/admin/stats` binding. Recorded honest deferrals:
      channel public-playlists contract, search-scope param, unified mobile
      admin queues tab, reply notifications (awaiting user approval).
- [x] IPFS media mirroring (user-directed, outside wave order): public tier
      P19.1–P19.6 + private swarm tier P19.P1–P19.P4 in vidra-core, three
      adversarial privacy-audit rounds, `ipfs-private-integration` CI green with
      all four swarm-isolation proofs executing (guarded against silent skips).

- [x] W2 — Upload & import. **DONE 2026-07-08, dual audits PASS (backend security
      + frontend design/truthfulness), zero blockers/majors.** Backend
      (vidra-core `91405ae..3f3c6e6`): yt-dlp import resolver (sandboxed, admin
      opt-in, EICAR-through-import proof in CI), server-side drafts, batch,
      channel auto-sync, frame-pick. Frontend (vidra-user `27a2f77..15ebc69`):
      resumable+draft-recovery UX, frame-pick, schedule/batch, import-from-URL,
      sync UI. Six audit minors recorded in fix_plans. (original wiring note:)
      (both projects; specs
      `vidra-*/.ralph/specs/backport-w2-upload-import.md`, seeded 2026-07-08).
      Net-new: yt-dlp URL import (marquee; admin opt-in, sandboxed, ClamAV-first),
      server-side draft recovery, batch upload, channel auto-sync, thumbnail
      frame-pick + UI slices on the design-refresh studio vocabulary. Already
      shipped & close-out-only: ClamAV scanning, scheduled publication,
      resumable-upload backend, direct-URL import + SSRF guard. Torrent import
      DEFERRED to W6 (security recommendation, user standing approval).

> W3–W7 are defined in `.ralph/specs/backport/PROGRAM.md` §3 but are **not yet
> wired** — do not start them. Wire one wave at a time per PROGRAM.md §5, only after
> the previous wave's box ticks.

## Cross-cutting

- [x] Root CI workflows exist and are path-scoped (`backend-ci` for `vidra-core/**`,
      `frontend-ci` for `vidra-user/**`). Both committed and green on `main`
      (frontend-ci ran the canonical `npm run ci` in GitHub for the first time).
- [x] Backend documentation stop guard exists: `openapi.yml` workflow lints
      `vidra-core/api/openapi.yaml` and runs the route↔spec drift check
      (`TestOpenAPIContract`); `.githooks/pre-commit` warns on doc drift.
- [x] `vidra-core/api/openapi.yaml` is current — lints clean (Redocly @1, 0 errors)
      and the route↔spec drift guard passes (no undocumented or orphaned endpoints).
      Fixed two OpenAPI 3.1 violations that had reddened the `openapi` workflow.
- [ ] README files in both projects reflect the current setup, endpoints, and commands.
- [x] CI parity guard exists: each project has one canonical gate (`make ci` /
      `npm run ci`), its workflow runs exactly that, and `ci-guard.yml` enforces
      it (no unmarked `continue-on-error`; workflows must invoke the canonical gate).
- [x] Branch CI is green in both projects running the same canonical gate as local
      (a local pass alone is not "done"). `main` green: backend-ci (`make ci`) +
      frontend-ci (`npm run ci`) + openapi + ci-guard all ✅ as of 0137e9d.
- [ ] Observability is enforced in both projects per `.ralph/specs/observability.md`:
      structured developer-friendly logging, no secrets/PII/plaintext in
      logs/traces, and OpenTelemetry with `traceparent` correlation across the
      `vidra-user` → `vidra-core` boundary. (Open in the sub-plans at 2026-11-06: core P17 L940
      logger propagation; user P1 L255–L259 — though `instrumentation.ts` exists, see P1 above.)
- [x] Backend ↔ frontend API contract is proven compatible (generated types / contract tests).
      Evidence 2026-11-06: vidra-user `contract-ci.yml` (required check `contract`) runs
      `scripts/check-contract.mjs` and fails when `lib/api/generated.ts` is stale vs core's
      `openapi.yaml`; locally at core `4995d024` / user `595ac805` it reports 307 paths / 412
      operations with every frontend path and method present. This repo's
      `scripts/ci/check-vertical-slice-completeness.py` (contract + type freshness, always run)
      exits 0 with `0 failure(s), 0 migration finding(s)` at the same SHAs.
- [x] PeerTube import path exists: an existing PeerTube instance (PostgreSQL DB +
      media storage) can be imported into Vidra per
      `vidra-core/.ralph/specs/peertube-import.md` (read-only source, idempotent,
      dry-runnable, audited), with the `vidra-user` admin import UI consuming it.
      Evidence 2026-11-06: core sub-plan P18 17/17 ticked at `4995d024` (`cmd/peertube-import`,
      `internal/peertubeimport`, `/api/v1/admin/peertube-import`); vidra-user
      `app/admin/import-peertube` → `AdminPeerTubeImportView` consumes it; meta runbook
      `docs/peertube-migration.md` and acceptance records `docs/runtime-acceptance-migration-v0.6.{4,5}.md`,
      `docs/runtime-acceptance-b2-migration-v0.7.8.md` (Verdict: PASS within the synthetic subset).
- [ ] Every in-scope data-mutating `vidra-user` flow is verified against the real
      database (row changed AND visible in the UI after refetch). (User sub-plan P14 has 2
      open items at `595ac805`; the backed suite exists — 55 `e2e-backed/` specs — but "every
      flow" has no inventory to certify against from this repo.)

## Optional / Deferred / Non-Blocking

These do not block exit.

- [ ] Premium subscriptions, payouts, custodial payments (out of scope).
- [ ] Native mobile apps.
- [ ] Full plugin/theme API parity.

## Completed

- [x] Split Vidra into `vidra-core/` and `vidra-user/` monorepo subdirectories.
- [x] Gave each subdirectory its own `.ralphrc` + `.ralph/` (PROMPT, AGENT, fix_plan, specs).
- [x] Configured the root `.ralph/` as the orchestrator (this file + `.ralph/PROMPT.md`).
