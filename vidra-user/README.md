# Vidra User

The TypeScript **Next.js** frontend for **Vidra** — a clean-room, PeerTube-inspired
federated video platform. This project (`vidra-user`) consumes the HTTP API served by
the sibling **`vidra-core`** Go backend.

> Status: not yet scaffolded. The first milestone is to bootstrap the Next.js +
> TypeScript + Tailwind app. Work is tracked in `.ralph/fix_plan.md` and the parity
> ledgers under `.ralph/specs/`.

## Monorepo layout
This is one project inside the Vidra monorepo (a single git repository):

```
vidra/
├── vidra-core/   # Go backend / HTTP API
└── vidra-user/   # this project — Next.js frontend
```

## Tech direction
Next.js · TypeScript (strict) · Tailwind CSS · custom components (no UI framework) ·
minified inline SVG icons · heavy Playwright coverage.

## Backend
Set `NEXT_PUBLIC_API_BASE_URL` to a running `vidra-core` instance. For features that
change data, verification must run against a real backend + PostgreSQL (see
`.ralph/AGENT.md`), not mocks.

## Running Ralph for this project
```bash
cd vidra-user
ralph --live   # uses vidra-user/.ralphrc and vidra-user/.ralph/
```

## License
TBD.
