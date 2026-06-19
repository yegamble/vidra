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
Ralph drives each project independently. Always run it from inside the project
directory (Ralph reads `.ralphrc` / `.ralph/` relative to the current directory):

```bash
cd vidra-core && ralph --live   # work the backend
cd vidra-user && ralph --live   # work the frontend
```

Do **not** run Ralph from the monorepo root — the root `.ralph/` is a guard that does
no work and exists only to prevent code being scaffolded at the root.

## CI
GitHub Actions workflows live at the repo root in [`.github/workflows/`](.github/workflows/)
(GitHub only reads workflows from the root). They are path-filtered so backend changes
run backend CI and frontend changes run frontend CI.

## License
TBD.
