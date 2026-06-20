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
