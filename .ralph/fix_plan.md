# Monorepo root — no tasks here

This is the Vidra monorepo root. **There is no work to do at this level.** All tasks
live in the two project subdirectories, each with its own Ralph control plane:

- Backend tasks → `vidra-core/.ralph/fix_plan.md`
- Frontend tasks → `vidra-user/.ralph/fix_plan.md`

Run Ralph from inside the project you want to work on:

```bash
cd vidra-core && ralph --live   # backend
cd vidra-user && ralph --live   # frontend
```

Do not create application code at the monorepo root. See `.ralph/PROMPT.md`.

## Completed
- [x] Split Vidra into `vidra-core/` and `vidra-user/` monorepo subdirectories.
- [x] Gave each subdirectory its own `.ralphrc` + `.ralph/` (PROMPT, AGENT, fix_plan, specs).
