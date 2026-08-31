# Vidra repo map — binding context for every council teammate

Read this once, at the start of your investigation, before you form any opinion.

## The four repositories

You are launched from the **meta repo** (`vidra`). The three component repos are
checked out NESTED inside it, are separate git repos, and are gitignored here.

| Path | Repo | Owns |
|---|---|---|
| `.` | `vidra` (meta) | docker-compose files, Caddy, `deploy/` (deploy, rollback, backup, restore, release), `env/` templates, `install.sh`/`bootstrap.sh`, `tests/`, platform audit docs in `docs/` |
| `./vidra-core` | `vidra-core` | Go/Echo v4 backend, **canonical `api/openapi.yaml` product contract**, sqlc, golang-migrate `migrations/`, in-process workers (transcode, imports, search outbox, media GC), federation, storage, notifications, instance settings |
| `./vidra-user` | `vidra-user` | Next.js 16 App Router frontend — the ENTIRE user-facing product: viewer, creator Studio, admin console, moderation, settings, messages, live |
| `./vidra-search` | `vidra-search` | internal-only search / autosuggest / trending / recommendations service |

## Non-negotiable architectural boundaries

```
Browser ──▶ vidra-user ──HTTP──▶ vidra-core ──HTTP (HMAC)──▶ vidra-search
                                  (source of truth)
```

1. **core owns the contract.** `vidra-core/api/openapi.yaml` is the product
   contract. `TestOpenAPIContract` fails in BOTH directions (route without doc,
   doc without route).
2. **user consumes, never invents.** `vidra-user/lib/api/generated.ts` is
   generated from that spec and is never hand-edited. The frontend may not
   invent an endpoint or field core does not ship.
3. **search returns ranked IDs and scores only.** Core hydrates the IDs and
   applies per-viewer visibility (mutes, blocks, sensitivity). Titles and viewer
   state never leave core. Search bakes in only the static eligibility gate
   (public + published + not suppressed) plus an `is_sensitive` flag.
4. **search is never a hard dependency.** Any search failure is core's cue to
   fall back silently to its own SQL. A design that lets search take the site
   down, or lets it bypass core's visibility rules, is unacceptable — say so as
   a BLOCKER.
5. **The frontend never calls search directly.** Search is internal-only, HMAC
   authed (`X-Vidra-Internal-Auth: v1:{ts}:{hex hmac}`, ±120s skew), and its
   port must never be published to the internet.

## Each component's AGENTS.md is binding

Before analyzing or proposing changes to a component repo, read its `AGENTS.md`
and treat it as binding law — verification gates, TDD requirement, append-only
migrations, one-small-PR, no dependency bumps, no `.github/workflows` edits, no
secrets.

- `vidra/AGENTS.md` — meta rules: deploy ordering is sacred, nested-checkout
  migration trap, Compose >= 2.24 `!reset`/`!override`, `env/*.env` untracked.
- `vidra-core/AGENTS.md` — thin handlers, HTTP-agnostic services under
  `internal/`, never hand-edit `internal/store/sqlcgen/**`, append-only
  migrations, OpenAPI lock-step, sensitive-key logging denylist,
  `requireRole`/`requireAuth` + ownership checks, `subtle.ConstantTimeCompare`.
- `vidra-user/AGENTS.md` — YouTube layout ergonomics + Apple visual skin,
  contract-is-core-first, SVG icons only, design tokens, `EmptyState` /
  `ErrorState` / `Spinner` idioms, and a list of **real historical failure
  classes** you should actively hunt for.
- `vidra-search` has **no AGENTS.md** — that is itself a finding. Use
  `vidra-search/README.md` and `vidra-search/docs/{architecture,evaluation,operations,privacy}.md`.

## Verification gates (quote these, do not invent them)

| Repo | Gate |
|---|---|
| meta | `bash -n` + `shellcheck` on touched scripts; `docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file <filled> config -q` |
| core | `make ci` (fmt-check, vet, openapi-verify, sqlc-verify, test-race); integration tests need live Postgres+Redis and the `integration` build tag |
| user | `npx tsc --noEmit`, `npm run lint`, `npm run lint:icons`, `npm run test` (vitest). Do NOT run `npm run e2e` / `e2e:backed` — they need a real backend and browser fleet |
| search | `make ci` (fmt-check, vet, migrate-lint, openapi-verify, sqlc-verify, test-race) |

## Traps that have burned this project before

- **Recursive grep from the meta root silently skips the nested checkouts**
  (they are gitignored, and the search tooling honours ignore files). If you
  search from `.` and find nothing in core/user/search, you have proven
  NOTHING. Always `cd vidra-core && grep -rn ...` from inside the component.
- **Nested checkouts are pinned DETACHED at release tags.** `git pull` in the
  meta repo does not advance them. A deploy can run new images against old
  migrations and still exit 0.
- **`make ci` proves nothing about media** — the ffmpeg-dependent tests are
  build-tagged out of the default lane.
- **There are TWO frontend e2e suites** (`e2e/` and `e2e-backed/`); they must
  move together or one rots.
- **MERGED is not DEPLOYED.** Work merged to `main` is not on the beta
  instance until a deploy runs. When you assess status, distinguish
  *implemented* / *merged* / *released* / *deployed* explicitly.
- **"Implemented in Go" is not the same thing as "Vidra has this feature."**
