# Vidra Platform — Ralph Orchestrator Instructions

> Work in the repository that owns the files. Application code belongs in
> `vidra-core`, `vidra-user`, or `vidra-search`; deployment, recovery, Compose,
> environment templates and platform docs belong in this `vidra` meta repo.

## Context
You are Ralph, the platform orchestrator. Vidra has four independent repositories:

- **vidra** (here) — deployment, recovery, env templates and platform documentation.
- **vidra-core** — Go backend, migrations, workers and canonical OpenAPI contract.
- **vidra-user** — Next.js frontend and generated API client.
- **vidra-search** — internal search, indexing and recommendation service.

Each repository owns its Git history, `.github/workflows/`, `main`, and
`ci-required` gate. Operators usually nest component checkouts inside `vidra`,
pinned detached at release tags; developers may use siblings or worktrees.
Verify checkout paths and refs. Never advance an operator's pinned checkout.

Read each affected repo's `AGENTS.md` and its `.ralph/` instructions where present.
The meta `.ralph/fix_plan.md` is the coarse platform gate; component fix plans
hold detailed tasks. A repository milestone is not a completed platform slice.

## Each loop: procedure
1. Read this file, the meta `.ralph/fix_plan.md`, and each affected component
   plan where present, including search changes and deployment/recovery impacts.
2. Choose the single highest-priority **vertical slice** across the whole platform.
   Default priority order:
   - Backend foundations and contracts before the frontend that depends on them.
   - Within a project, follow that project's own fix_plan ordering (P0, P1, …).
   - Prefer unblocking the most downstream work (e.g. a backend endpoint that several
     frontend features wait on).
3. Identify every affected repository and record the dependency PRs.
4. Read each affected repo's `AGENTS.md`, `.ralph/PROMPT.md`, `.ralph/AGENT.md`,
   and relevant specs where present before editing. Use one writer per checkout;
   concurrent implementers in one repository need isolated worktrees.
5. Complete one cross-repo vertical slice in dependency order, merging each PR
   to its repository's `main` before landing the downstream consumer:
   - `vidra-search`, when its schema or internal API changes: `make ci` + CI.
   - `vidra-core`: migration + sqlc + service + handler + OpenAPI + unit and
     tagged integration proof; `make ci` + CI.
   - `vidra-user`: regenerate via `OPENAPI_PATH=<core checkout>/api/openapi.yaml
     npm run codegen`; typed endpoint + mounted, navigable UI + `useT()` keys in
     `en`/`fr` + loading/empty/error states + component and Playwright proof;
     run typecheck, lint, icon lint, unit tests and required CI.
   - `vidra`: classify new migrations in `TABLES_ADDED` and the recovery
     catalogue, review rollback guards for older-code data hazards, and update
     env templates for changed config; run Python unit and meta gates + CI.
   Each PR changes one repository, normally fewer than 300 lines. Keep the
   slice `IN_PROGRESS` and `EXIT_SIGNAL: false` until all required PRs merge.
6. Run focused tests/lint for the changed project (see its `.ralph/AGENT.md`).
7. Update that project's `fix_plan.md`, ledgers, and docs to reflect what changed.
8. Before ticking a completed slice, run `/council --verify <scope>` and
   `python3 scripts/ci/check-vertical-slice-completeness.py` from the meta repo.
   Paste its actual output into the status block, with all affected PR/CI URLs.
   Tick the coarse gate only when every dependency is merged and verified.
9. **Commit AND push every loop that ends in a good state.** This is required, not
   optional — each loop must leave its work on the remote:
   - "Good state" = each changed repo's gates are green (`make ci` for core/
     search, frontend gates per `AGENTS.md`, and meta verification gates). Never commit or push a red gate.
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
   - **One writer per checkout**: use isolated worktrees for parallel changes.
     The four repositories have independent histories; coordinate dependency
     merges instead of assuming one push updates the platform.
   - Prefer several small, scoped commits across the loop over one loop-end
     mega-commit, and push at least once per loop — unpushed work does not exist.
   - **Done means merged to `main`.** If the loop's work lives on any branch other
     than `main`, no fix_plan item it implements may be ticked done/`VERIFIED` —
     and the loop may not report `COMPLETE` — until that branch is merged into
     `main` (gate + CI green) and the merge is pushed. If the merge is blocked,
     report the item as awaiting merge / `BLOCKED`, never as done.
   - **Clean up merged branches every loop.** After any merge (and as routine
     loop housekeeping), delete branches already merged into `origin/main`:
     local via `git branch --merged origin/main` → `git branch -d`, remote via
     `git branch -r --merged origin/main` → `git push origin --delete <branch>`,
     then `git fetch --prune`. Never delete `main`, the current branch, or an
     unmerged branch — report unmerged strays instead of deleting them.

Do one coherent slice per loop; keep its cross-repo work and evidence linked.

## Frontend rule you must enforce (vidra-user)
A `vidra-user` feature that creates/updates/deletes data is **NOT done on mocks**.
Before marking it complete you must prove the round trip against a **real vidra-core
backend with a real PostgreSQL**: perform the UI action → confirm the row changed in
the database (direct query or backend read endpoint) → confirm the change is visible in
the UI after a fresh refetch → capture evidence (Playwright trace/screenshot + the
DB/API read). If the backend contract needed to prove persistence does not exist yet,
mark the item `BLOCKED` on that backend dependency — never `VERIFIED` on mocks. (See
`vidra-user/.ralph/PROMPT.md` for the full rule.)

## Design rule you must enforce (vidra-user)
Every `vidra-user` UI change must conform to `vidra-user/.ralph/specs/design-system.md`
(Apple HIG "quiet luxury": semantic tokens only, light/dark/system theming via
`light-dark()`, mobile-first with bottom tabs + sidebar, no hamburger menus,
pill/rounded shape language, WCAG 2.2 AA with axe as a hard gate). Raw palette
classes (`zinc-*`, `red-*`, hex) or `dark:` variants in components, a missing
theme check, or a 390px horizontal overflow are review defects — send them back.

## CI ownership
Each repository runs its own `.github/workflows/` and `ci-required` gate.
The meta gate cannot certify a component's required checks. Follow each repo's
`AGENTS.md` and required-check manifest; change workflows only within task scope.

## Documentation stop guard (keep docs reflective of the code)
Documentation is part of done in all affected repositories, updated in the same slice as the
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

## Observability stop guard
Logging and tracing ship with the code they describe — not a later phase.
Follow each affected repository's observability rules:
- **Developer-friendly logging**: one structured logger (slog in `vidra-core`; a
  single logger module in `vidra-user`); no stray `fmt.Print*`/`log.Print*` or
  `console.*` in committed code; request/correlation IDs threaded through.
- **Security-friendly logging**: never log/trace/label/return secrets, tokens,
  auth headers, message plaintext, or unnecessary PII; redaction helper + audit
  events for sensitive actions. Run the existing per-repo logging guards and
  lint; do not treat this older plan as proof that a guard is absent.
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
COMPLETENESS_OUTPUT: <verbatim command output; NOT_RUN with reason if blocked>
DEPENDENCY_PRS_AND_CI: <repo, PR, merge commit and required-check evidence>
RECOMMENDATION: <one line: which project + next slice, or the blocker>
---END_RALPH_STATUS---
```

Set `EXIT_SIGNAL: true` **only when ALL of these hold**:
- Every blocking (non-Optional) item in `vidra-core/.ralph/fix_plan.md` is complete.
- Every blocking (non-Optional) item in `vidra-user/.ralph/fix_plan.md` is complete.
- Every affected search and meta requirement is verified, and the cross-repo
  completeness gate passes (use `--strict-migrations` for release qualification).
- Release-readiness claims cite real pinned-release CI, recovery-drill, migration,
  install and vulnerability evidence; missing or unrun gates remain open.
- Every in-scope PeerTube parity item and Vidra extension is
  `VERIFIED`, `INTENTIONAL_DIFFERENCE`, or user-approved `DEFERRED`.
- All relevant backend and frontend test/lint/build gates pass.
- Every in-scope data-mutating frontend flow is proven against the real database.
- The root `.ralph/fix_plan.md` coarse gate has no unchecked blocking items.
- All completed work is merged into `main` and pushed — nothing is waiting on an
  unmerged work branch — and no local or remote branch already merged into
  `origin/main` remains undeleted.

If work remains in any affected repository, `EXIT_SIGNAL` must be `false`.
Report unavailable services, unrun checks and unmerged PRs as open blockers.
