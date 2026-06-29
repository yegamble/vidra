# Agent Build Instructions — Vidra Monorepo **Orchestrator** (root)

> ⛔ **You are the orchestrator, running from the monorepo root. NEVER create
> application code at the root.** All code, tests, config, Docker, and docs live
> inside `vidra-core/` or `vidra-user/`. The root holds only `.git`, `.gitignore`,
> `README.md`, `.github/workflows/`, and `.ralph/`. Full procedure: `.ralph/PROMPT.md`.

This checkout is the **Vidra monorepo root** — NOT a single project. Vidra is a
clean-room, PeerTube-inspired federated video platform split into two self-contained
projects that are **subdirectories of this one git repo** (not separate repos):

- **vidra-core/** — Go backend / HTTP API (Echo, PostgreSQL, sqlc, Redis, Docker).
- **vidra-user/** — Next.js + TypeScript frontend (Tailwind, Playwright).

One Ralph loop, run from here, advances **both**. The detailed, authoritative build
and test instructions for each project live in that project's own files — read them
when you work in that project, and follow them exactly:

- `vidra-core/.ralph/AGENT.md`, `vidra-core/.ralph/PROMPT.md`, `vidra-core/.ralph/fix_plan.md`
- `vidra-user/.ralph/AGENT.md`, `vidra-user/.ralph/PROMPT.md`, `vidra-user/.ralph/fix_plan.md`

## Per-loop orientation (see `.ralph/PROMPT.md` for the full procedure)
1. Read this file, the root `.ralph/fix_plan.md` (coarse phase gate), and **both**
   subdirectory `fix_plan.md` files.
2. Pick the single highest-priority vertical slice across the platform
   (backend foundations/contracts before the frontend that depends on them).
3. `cd` into the **one** target project and read its `.ralph/PROMPT.md`,
   `.ralph/AGENT.md`, and `.ralph/specs/` before writing anything. Exactly one
   project per loop — never touch the sibling in the same loop.
4. Run that project's **canonical gate** and never commit/push a red gate:
   - `vidra-core`: `make ci`  (fmt-check + vet + openapi-verify + test-race)
   - `vidra-user`: `npm run ci`  (lint + typecheck + build + e2e; data-mutating
     flows must be proven against a **real** vidra-core + Postgres via the
     backend-backed Playwright profile — never `VERIFIED` on mocks).

## Canonical commands (for reference; authoritative copies live per-project)
```bash
# backend (run inside vidra-core/)
make ci            # the full local gate the backend CI runs
make up / make down# full Docker stack (postgres, redis, migrate, api)
make sqlc          # regenerate typed query code after migration/query changes
make openapi-verify# lint api/openapi.yaml + route↔spec drift guard

# frontend (run inside vidra-user/)
npm run ci         # the full local gate the frontend CI runs
npm run e2e:backed # Playwright against a live vidra-core + Postgres (proves persistence)
```

## Git workflow (this is the ORCHESTRATOR's workflow — it overrides any
## "feature branch / pull request" language in the per-project AGENT files)
- **Commit AND push every loop that ends green, directly to the working branch
  (`main`).** Pushing is what runs CI; a loop is not done until its work is pushed
  (or the push failure is recorded `BLOCKED`). Use scoped conventional messages
  (`feat(core): …`, `fix(user): …`). See `.ralph/PROMPT.md` for the push/rebase
  failure handling.
- **Single writer:** only ONE Ralph loop may run against this repo at a time —
  `vidra-core` and `vidra-user` share one git history and one `main`, and the
  pull-rebase-retry is not concurrency-safe. Do not run a standalone subdir loop
  while the root orchestrator is running.
- Never commit secrets, tokens, keys, or real personal data anywhere (the
  `.githooks/pre-commit` stop guard applies; never `--no-verify` to dodge it).

## Quality bar (applies in whichever project the slice touches)
- Tests + docs ship in the **same slice** as the code (OpenAPI in lock-step with
  routes; README/AGENT/`.env.example`/frontend types kept current).
- Observability ships with the code (structured logging, no secrets/PII in
  logs/traces) per each project's `.ralph/specs/observability.md`.
- Update that project's `fix_plan.md`/ledgers, then tick a root coarse-gate phase
  box only when that whole phase is genuinely complete in the subdir plan.

## Ralph infrastructure rules
Never delete, move, rename, or wholesale-overwrite any `.ralph/`, `.ralphrc`, or
subdirectory equivalent. Allowed edits: `*/.ralph/fix_plan.md` (checkboxes/notes),
`*/.ralph/AGENT.md` (build/test instructions), `*/.ralph/specs/*` (genuine spec work),
and `*/.ralph/PROMPT.md` (only when the user asks to improve Ralph instructions).
