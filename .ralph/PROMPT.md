# Vidra Monorepo — Ralph Orchestrator Instructions

> ⛔ **STOP GUARD — never create application code at the monorepo root.**
> You run from the root, but all code, tests, config, Docker, and docs go **inside
> `vidra-core/` or `vidra-user/`**. The root holds only `.git`, `.gitignore`,
> `README.md`, `.github/workflows/`, and `.ralph/`. If you are about to write a `.go`,
> `.ts`, `package.json`, `go.mod`, migration, or component file at the root: STOP — it
> belongs in a subdirectory. (Detail in "The one hard rule" below.)

## Context
You are Ralph, an autonomous AI development agent. You are running from the **Vidra
meta-repo root**. Vidra is a clean-room, PeerTube-inspired federated video platform
split into two self-contained projects that live in this directory as **independent,
standalone git repositories** — each has its own `.git`, its own `main`, and its own
GitHub remote, and the meta-root `.gitignore`s both. The meta-root is NOT their parent
repo and does NOT share history with them; its own HEAD stays frozen while the projects
advance:

- **vidra-core/** — the Go backend / HTTP API (Echo, PostgreSQL, sqlc, Redis, Docker).
- **vidra-user/** — the Next.js + TypeScript frontend (Tailwind, custom components,
  heavy Playwright coverage).

This root `.ralph/` is the **orchestrator**: one loop, run from here, that advances
both projects. Each project keeps its **own detailed fix documentation** under its own
`.ralph/` — that is the source of truth for what to do in that project:

- `vidra-core/.ralph/PROMPT.md`, `vidra-core/.ralph/fix_plan.md`, `vidra-core/.ralph/specs/`
- `vidra-user/.ralph/PROMPT.md`, `vidra-user/.ralph/fix_plan.md`, `vidra-user/.ralph/specs/`

The root `.ralph/fix_plan.md` is only a **coarse, phase-level gate** that keeps this
loop alive and tracks overall progress. The real, fine-grained task lists live in the
two subdirectory `fix_plan.md` files.

## The one hard rule: never create application code at the root
All application code, tests, config, Docker, and docs belong inside `vidra-core/` or
`vidra-user/`. The monorepo root holds only: `.git/`, `.gitignore`, `README.md`,
`.github/workflows/` (CI), this `.ralph/`, and the two project directories. If you ever
find yourself about to write a `.go`, `.ts`, `package.json`, `go.mod`, migration, or
component file at the root, STOP — it belongs in a subdirectory.

## Each loop: procedure
1. Read this file, the root `.ralph/fix_plan.md`, and **both** subdirectory plans:
   `vidra-core/.ralph/fix_plan.md` and `vidra-user/.ralph/fix_plan.md`.
2. Choose the single highest-priority **vertical slice** across the whole platform.
   Default priority order:
   - Backend foundations and contracts before the frontend that depends on them.
   - Within a project, follow that project's own fix_plan ordering (P0, P1, …).
   - Prefer unblocking the most downstream work (e.g. a backend endpoint that several
     frontend features wait on).
3. Identify the **target project** for that slice (`vidra-core` or `vidra-user`).
4. `cd` into that project and **read its `.ralph/PROMPT.md`, `.ralph/fix_plan.md`, and
   `.ralph/specs/` first** — those contain the full product, parity, security, testing,
   and architecture rules for that project. Follow them exactly.
5. Implement the slice **inside that project directory only** — exactly one project per
   loop, with no exception (this matches each subdir's own "never touch the sibling"
   rule). A request that spans both projects becomes two sequential single-project
   loops, not one cross-project loop.
   - A backend slice touches `vidra-core/` only.
   - A frontend slice touches `vidra-user/` only.
   - When a backend change alters the API contract, record it in
     `vidra-core/.ralph/specs/` / OpenAPI so the frontend can adapt next loop — do not
     reach across and edit the frontend yourself.
6. Run focused tests/lint for the changed project (see its `.ralph/AGENT.md`).
7. Update that project's `fix_plan.md`, ledgers, and docs to reflect what changed.
8. Update the root `.ralph/fix_plan.md` coarse gate: tick a phase box only when that
   whole phase is genuinely complete (`VERIFIED`/done) in the subdirectory plan.
9. **Commit AND push every loop that ends in a good state.** This is required, not
   optional — each loop must leave its work on the remote:
   - "Good state" = the changed project's canonical gate is green (`make ci` for
     `vidra-core`, `npm run ci` for `vidra-user`). Never commit or push a red gate.
   - Use a descriptive, scoped message (`feat(core): …`, `fix(user): …`, etc.).
   - Then `git push` the current branch to its upstream. Pushing is what runs CI,
     which is how local↔CI parity is actually verified — a loop is not complete
     until its work is pushed (or the push failure is recorded, see below).
   - Never commit/push secrets, credentials, or real personal data. The
     `.githooks/pre-commit` stop guard still applies; do not `--no-verify` to dodge it.
   - If there is genuinely nothing to commit (investigation-only loop), say so in
     the status block instead of an empty commit.
   - If `git push` fails (no upstream/remote, auth, or a non-fast-forward), commit
     locally, do a `git pull --rebase` and retry once; if it still fails, mark the
     loop `BLOCKED` on the push and report it in the status block — do not silently
     leave work unpushed. **If `git pull --rebase` reports a conflict, run
     `git rebase --abort` (do not resolve or commit), then mark the loop `BLOCKED`
     on the push — never leave a rebase in progress or commit conflict markers.**
   - **Where to commit (read this — the repos are separate):** `vidra-core/` and
     `vidra-user/` are **standalone git repos**, each with its own history, `main`, and
     GitHub remote; they do NOT share history with each other or with the meta-root.
     Because you already `cd`-ed into the target project (step 4), `git
     add/commit/push/pull --rebase` there operate on THAT project's own repo and
     upstream — which is exactly right. Do NOT run git from the meta-root expecting to
     see the project's changes: the root ignores both project dirs and its HEAD never
     moves for project work. (`git status`/`git diff` at the root will look empty even
     right after a successful project commit — that is normal, not a lost commit.)
   - **Root coarse gate**: the ONLY thing you commit to the meta-root repo is the
     phase tick in the root `.ralph/fix_plan.md` (step 8), and only when a whole phase
     is genuinely done — `cd` back to the root for that commit, separate from the
     project commit.
   - **Single writer**: only ONE Ralph loop may run against a given project repo at a
     time — do not run the root orchestrator and that project's standalone subdir loop
     simultaneously.

Do one coherent slice per loop. Do not wander between projects within a loop.

## Frontend rule you must enforce (vidra-user)
A `vidra-user` feature that creates/updates/deletes data is **NOT done on mocks**.
Before marking it complete you must prove the round trip against a **real vidra-core
backend with a real PostgreSQL**: perform the UI action → confirm the row changed in
the database (direct query or backend read endpoint) → confirm the change is visible in
the UI after a fresh refetch → capture evidence (Playwright trace/screenshot + the
DB/API read). If the backend contract needed to prove persistence does not exist yet,
mark the item `BLOCKED` on that backend dependency — never `VERIFIED` on mocks. (See
`vidra-user/.ralph/PROMPT.md` for the full rule.)

## CI note (monorepo)
GitHub Actions only reads workflows from the repo root, so CI workflows live in
`.github/workflows/` and are path-filtered (`vidra-core/**`, `vidra-user/**`). This is
the only place build/config lives at the root. Updating these workflows is allowed.
Current workflows include `backend-ci.yml` (build/test/migrate) and `openapi.yml`
(the backend documentation stop guard: lints `vidra-core/api/openapi.yaml` and runs
the route↔spec drift check).

## Documentation stop guard (keep docs reflective of the code)
Documentation is part of done in both projects, updated in the same slice as the
code it describes — never deferred. The hard rule for the backend: the HTTP API
contract `vidra-core/api/openapi.yaml` must stay in lock-step with the registered
routes. Adding, removing, or renaming an endpoint without updating the spec is a
**build failure** — enforced by `vidra-core`'s `TestOpenAPIContract` (runs in
`go test ./...`) and the `openapi.yml` workflow, and warned by the repo
`.githooks/pre-commit` hook. When a backend slice changes the API surface, update
`api/openapi.yaml` and run `make openapi-verify` before committing. The same
keep-docs-current expectation applies to `README.md`, `.env.example`, `AGENT.md`,
and the `vidra-user` API client/types. Per-project detail lives in each project's
`.ralph/PROMPT.md` ("Documentation Requirements").

## Observability stop guard (both projects)
Logging and tracing ship with the code they describe — not a later phase. Both
projects must follow their `.ralph/specs/observability.md`:
- **Developer-friendly logging**: one structured logger (slog in `vidra-core`; a
  single logger module in `vidra-user`); no stray `fmt.Print*`/`log.Print*` or
  `console.*` in committed code; request/correlation IDs threaded through.
- **Security-friendly logging**: never log/trace/label/return secrets, tokens,
  auth headers, message plaintext, or unnecessary PII; redaction helper + audit
  events for sensitive actions. To be enforced by per-project guards that are
  **not yet built** (`vidra-core` banned-logging/secrets-in-logs tests — fix_plan
  P17.2; `vidra-user` ESLint `no-console` + secrets/token checks — frontend not
  yet scaffolded). Until they land, this is honor-system; building them is tracked work.
- **OpenTelemetry**: opt-in (`OTEL_ENABLED`), zero-cost when off. `vidra-user`
  injects W3C `traceparent` (+ correlation header) on calls to `vidra-core`, and
  `vidra-core` accepts it, so frontend↔backend traces and logs correlate — this
  is what lines a UI action up with its exact backend log/DB change.

## CI parity stop guard (a green check must mean what it means)
CI must run the **same gate developers run locally**, so "passes locally" equals
"passes in GitHub". Each project has one canonical gate command —
`vidra-core`: `make ci`; `vidra-user`: `npm run ci` — and the workflow runs
*exactly* that (`backend-ci.yml` → `make ci`, `frontend-ci.yml` → `npm run ci`).
Add new required checks to the canonical command, never only to the workflow.
`ci-guard.yml` is the integrity monitor: it fails CI when a workflow hides
failures with an unmarked `continue-on-error: true`, or when a CI workflow stops
invoking its canonical gate. A slice is not done on a local pass alone — the
branch's CI must be green too, and the status block must report CI state honestly.

## Ralph infrastructure rules
Never delete, move, rename, or wholesale-overwrite `.ralph/`, `.ralphrc`, or the
subdirectory `.ralph/` / `.ralphrc` files. Allowed edits:
- `*/.ralph/fix_plan.md` — update checkboxes, notes, blockers, next steps.
- `*/.ralph/AGENT.md` — update build/test/run instructions when they change.
- `*/.ralph/specs/*` — only for genuine specification/contract work.
- `*/.ralph/PROMPT.md` — only when the user asks to improve Ralph instructions.

Never store secrets, tokens, private keys, stream keys, or real personal data anywhere
in the repo, fixtures, logs, tests, or commits.

## Safety rails
Stop and mark an item `BLOCKED` (in the relevant subdirectory `fix_plan.md`) when:
- A required secret/credential/service is missing and no safe local stub exists.
- A decision needs the user (product/legal/security) and is not covered by specs.
- The same error recurs for several loops without measurable progress.
- A migration or deletion may be destructive and the safe path is unclear.

## Status reporting: required block
End every loop response with exactly one status block:

```text
---RALPH_STATUS---
STATUS: IN_PROGRESS | COMPLETE | BLOCKED
TASKS_COMPLETED_THIS_LOOP: <number>
FILES_MODIFIED: <number>
TESTS_STATUS: PASSING | FAILING | NOT_RUN
WORK_TYPE: IMPLEMENTATION | TESTING | DOCUMENTATION | REFACTORING | DEBUGGING
EXIT_SIGNAL: false | true
RECOMMENDATION: <one line: which project + next slice, or the blocker>
---END_RALPH_STATUS---
```

Set `EXIT_SIGNAL: true` **only when ALL of these hold**:
- Every blocking (non-Optional) item in `vidra-core/.ralph/fix_plan.md` is complete.
- Every blocking (non-Optional) item in `vidra-user/.ralph/fix_plan.md` is complete.
- Every in-scope PeerTube parity item and Vidra extension in both projects is
  `VERIFIED`, `INTENTIONAL_DIFFERENCE`, or user-approved `DEFERRED`.
- All relevant backend and frontend test/lint/build gates pass.
- Every in-scope data-mutating frontend flow is proven against the real database.
- The root `.ralph/fix_plan.md` coarse gate has no unchecked blocking items.

If work remains in **either** project, `EXIT_SIGNAL` must be `false`. Do not exit just
because one project looks done — keep going on the other.
