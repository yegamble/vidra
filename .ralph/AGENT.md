# Agent Build Instructions — Vidra Platform **Orchestrator** (meta repo)

Work in the owning repository: application code in `vidra-core`, `vidra-user`
or `vidra-search`; deployment, recovery, Compose, env and platform docs in
`vidra`. Each has its own Git history, `.github/workflows/`, `main`, and
`ci-required` gate. Nested component checkouts on operator hosts are detached
release pins; use separate development checkouts or worktrees for changes.

Read each affected repo's `AGENTS.md` and `.ralph/` instructions where present.
For one coherent vertical slice, land dependent PRs in search → core → user →
meta order. Keep one writer per checkout, one repository per PR (normally fewer
than 300 lines), and link downstream work instead of marking a backend-only
milestone complete. Update recovery classifications and review rollback guards
for each new core migration; update env templates for config changes.

Run each affected repo's gates and required CI. Frontend data mutations also
need real backend/DB evidence (not mocks). Before ticking a completed fix-plan
item or reporting completion, run the meta completeness command below, paste
its real output and the affected PR/CI links into the status block, and verify
that every required dependency PR is merged. Missing evidence stays open.

## Canonical commands (for reference; authoritative copies live per-project)
```bash
# backend (run inside vidra-core/)
make ci            # the full local gate the backend CI runs
make up / make down# full Docker stack (postgres, redis, migrate, api)
make sqlc          # regenerate typed query code after migration/query changes
make openapi-verify# lint api/openapi.yaml + route↔spec drift guard

# search (run inside vidra-search/)
make ci            # this independent repo owns its required CI

# meta (run inside vidra/)
python3 -m unittest discover -s tests -p '*_test.py'
python3 scripts/ci/check-vertical-slice-completeness.py

# frontend (run inside vidra-user/)
npm run ci         # the full local gate the frontend CI runs
npm run e2e:backed # Playwright against a live vidra-core + Postgres (proves persistence)
```

## Git workflow (follow each owning repo's `AGENTS.md`)
- **Commit AND push green checkpoints on short-lived PR branches off `main`.**
  Pushing runs CI; a loop is not done until its work is pushed
  (or the push failure is recorded `BLOCKED`). Use scoped conventional messages
  (`feat(core): …`, `fix(user): …`). See `.ralph/PROMPT.md` for the push/rebase
  failure handling.
- **One writer per checkout:** concurrent work in one repo needs separate
  worktrees; each repository has its own `main` and merge gate.
- **Done means merged to `main`:** prefer small, frequent commits over one
  loop-end mega-commit, and any work done on a side branch is not complete —
  and may not be ticked done in any fix_plan — until that branch is merged
  into `main` and the merge is pushed. Blocked merge = awaiting merge /
  `BLOCKED`, never done.
- **Delete merged branches every loop:** after any merge, remove the work
  branch locally and remotely, and sweep `git branch --merged origin/main` /
  `git branch -r --merged origin/main` → delete, then `git fetch --prune`.
  Never delete `main`, the current branch, or an unmerged branch — report
  unmerged strays instead.
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
