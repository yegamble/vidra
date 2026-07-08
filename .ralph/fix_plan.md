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

- [ ] P0 — Ralph control plane and PeerTube parity tracking (`vidra-core`)
- [ ] P1 — Backend project foundation (module, config, Docker, CI)
- [ ] P2 — Database, migrations, and sqlc
- [ ] P3 — HTTP API foundation and contracts (OpenAPI, system endpoints)
- [ ] P4 — Auth, accounts, and identity
- [ ] P5 — Channels, profiles, and instance metadata
- [ ] P6 — Video publishing and media pipeline
- [ ] P7 — Playback, discovery, and public video API
- [ ] P8 — Library, playlists, comments, and notifications
- [ ] P9 — Moderation, admin, and safety
- [ ] P10 — Federation (ActivityPub, ATProto extension)
- [ ] P11 — Messaging (normal + encrypted foundation)
- [ ] P12 — Live streaming
- [ ] P13 — Captions and Whisper
- [ ] P14 — Simple crypto donations
- [ ] P15 — Security hardening
- [ ] P16 — Testing strategy
- [ ] P17 — Observability and operations
- [ ] P18 — PeerTube import and migration (import an existing PeerTube DB + instance)
- [ ] P19 — Backend release gates

## vidra-user (Next.js frontend) — phase gate

- [ ] P0 — Ralph control plane and PeerTube parity tracking (`vidra-user`)
- [ ] P1 — Frontend project foundation (Next.js, TS, Tailwind, API client, Docker, CI)
- [ ] P2 — App shell and navigation
- [ ] P3 — Auth and account UI
- [ ] P4 — Public video browsing and watch page
- [ ] P5 — Library, playlists, subscriptions, and notifications
- [ ] P6 — Publishing and upload UX
- [ ] P7 — Studio and creator tools
- [ ] P8 — Messaging UX
- [ ] P9 — Moderation and reporting UI
- [ ] P10 — Admin UI
- [ ] P11 — Federation, search, and external identity UI
- [ ] P12 — Captions, accessibility, and i18n readiness
- [ ] P13 — Simple crypto donation UI
- [ ] P14 — Frontend testing strategy (incl. backend-backed DB-effect e2e)
- [ ] P15 — Frontend release gates

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

- [ ] W2 — Upload & import (both projects; specs
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
      `vidra-user` → `vidra-core` boundary.
- [ ] Backend ↔ frontend API contract is proven compatible (generated types / contract tests).
- [ ] PeerTube import path exists: an existing PeerTube instance (PostgreSQL DB +
      media storage) can be imported into Vidra per
      `vidra-core/.ralph/specs/peertube-import.md` (read-only source, idempotent,
      dry-runnable, audited), with the `vidra-user` admin import UI consuming it.
- [ ] Every in-scope data-mutating `vidra-user` flow is verified against the real
      database (row changed AND visible in the UI after refetch).

## Optional / Deferred / Non-Blocking

These do not block exit.

- [ ] Premium subscriptions, payouts, custodial payments (out of scope).
- [ ] Native mobile apps.
- [ ] Full plugin/theme API parity.

## Completed

- [x] Split Vidra into `vidra-core/` and `vidra-user/` monorepo subdirectories.
- [x] Gave each subdirectory its own `.ralphrc` + `.ralph/` (PROMPT, AGENT, fix_plan, specs).
- [x] Configured the root `.ralph/` as the orchestrator (this file + `.ralph/PROMPT.md`).
