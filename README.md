# Vidra

A clean-room, PeerTube-inspired federated video platform. Vidra is a **monorepo** (one
git repository) containing two independently developed projects:

```
vidra/
├── vidra-core/   # Go backend / HTTP API  (Echo, PostgreSQL, sqlc, Redis, Docker)
└── vidra-user/   # Next.js + TypeScript frontend (Tailwind, custom components)
```

Each project is self-contained — its own `go.mod` / `package.json`, its own Docker
setup, and its own Ralph control plane (`.ralphrc` + `.ralph/`) with a separate
`fix_plan.md`. The frontend consumes the backend's HTTP API contract.

## Getting started
See each project's README:
- Backend: [`vidra-core/README.md`](vidra-core/README.md)
- Frontend: [`vidra-user/README.md`](vidra-user/README.md)

## Autonomous development (Ralph)
Ralph runs as a single **orchestrator from the monorepo root** and advances both
projects, one vertical slice per loop:

```bash
ralph --live            # run from the repo root — drives vidra-core AND vidra-user
```

Each loop the orchestrator picks the highest-priority slice, works inside the target
project (`vidra-core/` or `vidra-user/`), and follows that project's own `.ralph/`
(PROMPT, fix_plan, specs). It reads the **root** `.ralphrc` for loop settings and the
root `.ralph/PROMPT.md` + `.ralph/fix_plan.md` as the coarse orchestration gate; the
root `.ralph/` is *not* idle — it coordinates the whole run. (It never writes code at
the root — see the stop guard in `.ralph/PROMPT.md`.)

You *may* instead run a focused single-project loop from inside a subdirectory
(`cd vidra-core && ralph --live`), which uses that subdir's `.ralphrc`. Do **not** run
a subdir loop and the root orchestrator at the same time — both projects share one git
history and one `main`.

## CI
GitHub Actions workflows live at the repo root in [`.github/workflows/`](.github/workflows/)
(GitHub only reads workflows from the root). They are path-filtered so backend changes
run backend CI and frontend changes run frontend CI.

## License
TBD.
