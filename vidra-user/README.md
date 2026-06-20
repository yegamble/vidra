# Vidra User

The TypeScript **Next.js** frontend for **Vidra** — a clean-room, PeerTube-inspired
federated video platform. This project (`vidra-user`) consumes the HTTP API served by
the sibling **`vidra-core`** Go backend.

> Status: scaffolded (P1 foundation). Next 16 (app router) · React 19 · strict
> TypeScript · Tailwind v4 · ESLint 9 (`no-console`) · Vitest · Playwright. The
> canonical gate `npm run ci` (typecheck + lint + unit + build + e2e smoke) is green.
> Remaining work is tracked in `.ralph/fix_plan.md` and the parity ledgers under
> `.ralph/specs/`.

## Quick start
```bash
cp .env.example .env.local   # set NEXT_PUBLIC_API_BASE_URL to a vidra-core instance
npm install
npm run dev                  # http://localhost:3000
```

## Commands
```bash
npm run ci         # canonical gate: typecheck + lint + unit + build + e2e smoke
npm run typecheck  # tsc --noEmit (strict)
npm run lint       # eslint (no-console enforced; logger module is the only exception)
npm run test       # vitest unit/component tests
npm run build      # next build
npm run e2e        # playwright (needs: npx playwright install chromium)
```
The single structured logger is `lib/logger.ts` (raw `console.*` is banned elsewhere).

## API client
`lib/api/` is the typed client over the `vidra-core` contract: `apiRequest<T>` (a fetch
wrapper that sends `X-Correlation-ID`, maps the `{error:{code,message,…}}` envelope to a
typed `ApiError`, and parses JSON) plus `api.*` functions for the public read endpoints
(instance, feed, video detail, search, channel, channel videos) and
`videoOriginalUrl`/`videoThumbnailUrl` helpers. Types in `lib/api/types.ts` are
hand-maintained against the backend OpenAPI and marked provisional. Configure the target
with `NEXT_PUBLIC_API_BASE_URL` (`lib/config.ts`).

## UI
`components/Header.tsx` is the app-shell header; `components/VideoFeed.tsx` (a client
component) loads the public feed and renders loading / error / empty / grid states using
`components/VideoCard.tsx` and the `components/ui/*` primitives. The home route
(`app/page.tsx`) is the discovery grid. Because the feed loads client-side, Playwright
route-mocks the API in `e2e/` to test the grid without a running backend; proving real
data still requires the backend-backed profile (later slice). The watch page
(`app/videos/[id]` → `components/WatchView.tsx`) plays a video's original via a native
Range-capable `<video>` and shows its metadata, with loading / not-found / error states.

Auth is wired client-side: `components/auth/AuthProvider.tsx` (`useSession`) holds the
session, the access token lives in-memory (`lib/api/auth-store.ts`, auto-attached by the API
client, never persisted to `localStorage`), and the login page (`app/login`) signs in via
`lib/api/auth.ts`. The header `AccountMenu` shows Sign in / username + Sign out. Note: login
is mock-tested only — proving it persists requires the backend-backed e2e (later slice).

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
