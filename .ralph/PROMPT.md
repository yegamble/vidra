# STOP — Do not run Ralph from the monorepo root

This is the **Vidra monorepo root**. It contains two independent, separately
Ralph-driven projects. **No application code should ever be created here at the root.**

If you are an autonomous agent reading this as your prompt, you are in the WRONG
directory. Do not scaffold, build, or modify application code here. Exit and re-run
Ralph from one of the project subdirectories instead.

## The two projects

```
vidra/                 # <- you are here (monorepo root: git, CI, this guard)
├── vidra-core/        # Go backend  — has its own .ralphrc + .ralph/ control plane
└── vidra-user/        # Next.js UI  — has its own .ralphrc + .ralph/ control plane
```

## How to run Ralph

Ralph reads `.ralphrc` and `.ralph/` relative to the current working directory, so
run it from inside the project you want to work on:

```bash
# Backend:
cd vidra-core && ralph --live

# Frontend:
cd vidra-user && ralph --live
```

Each project has its own `PROMPT.md`, `AGENT.md`, `fix_plan.md`, and `specs/` under
its own `.ralph/`. They are scoped so backend work never touches the frontend and vice
versa. See `.ralph/fix_plan.md` in each subdirectory for the actual task lists.

## What lives at the root
- `.git/`, `.gitignore` — the single git repository for both projects.
- `.github/workflows/` — CI for both projects (GitHub only reads workflows from the
  repo root); workflows are path-filtered to `vidra-core/**` and `vidra-user/**`.
- `README.md` — monorepo overview.
- This `.ralph/` — a guard only. It drives no work.

## Status block
If you were nonetheless invoked here, do nothing and report:

```text
---RALPH_STATUS---
STATUS: BLOCKED
TASKS_COMPLETED_THIS_LOOP: 0
FILES_MODIFIED: 0
TESTS_STATUS: NOT_RUN
WORK_TYPE: DOCUMENTATION
EXIT_SIGNAL: false
RECOMMENDATION: Wrong directory. cd into vidra-core or vidra-user and run Ralph there.
---END_RALPH_STATUS---
```
