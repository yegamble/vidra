# Vidra

A clean-room, PeerTube-inspired federated video platform. Vidra is split across
**two independent repositories**, tied together by this lightweight **meta-repo**:

| Repo | What | Stack |
|------|------|-------|
| [`vidra-core`](https://github.com/yegamble/vidra-core) | Backend / HTTP API | Go, Echo, PostgreSQL, sqlc, Redis, Docker |
| [`vidra-user`](https://github.com/yegamble/vidra-user) | Frontend | Next.js, TypeScript, Tailwind |

Each repo is self-contained — its own `go.mod` / `package.json`, its own Docker
setup, its own GitHub Actions CI, and its own Ralph control plane (`.ralphrc` +
`.ralph/`). The frontend consumes the backend's HTTP API **contract** at runtime
(`NEXT_PUBLIC_API_BASE_URL`); there is no build-time coupling.

> **Why a meta-repo and not git submodules?** The two components talk only over
> HTTP at runtime, and the autonomous Ralph loop commits many times per hour. A
> submodule pins a commit SHA and requires a strict commit-child → push-child →
> bump-pointer → push-parent transaction on every sync, which fights the loop and
> risks dangling pointers. The meta-repo gives the same "one place to clone and
> run" without any of that: each repo's loop just commits and pushes its own tree.

## Getting started

```bash
git clone https://github.com/yegamble/vidra.git
cd vidra
./bootstrap.sh            # clone/update vidra-core + vidra-user into ./vidra-core, ./vidra-user

# Full stack in Docker (backend + frontend production image — :3000 and :8080):
docker compose --profile core --profile web up --build

# Or backend-only, with the frontend in dev mode (hot reload) in another shell:
docker compose --profile core up --build
cd vidra-user && npm ci && NEXT_PUBLIC_API_BASE_URL=http://localhost:8080 npm run dev
```

`bootstrap.sh` is idempotent: it clones each component if missing, otherwise
`git pull --ff-only`. The `./vidra-core` and `./vidra-user` directories are
independent git checkouts and are **git-ignored by this repo**.

## The frontend ⇄ backend contract

`vidra-core/api/openapi.yaml` is the source of truth for the HTTP API. `vidra-user`
hand-maintains `lib/api/types.ts` against it (no codegen yet) and guards drift with
`scripts/check-contract.mjs`, which asserts every `/api/` path the frontend calls
exists in the spec. In CI, `vidra-user`'s `contract-ci` fetches the spec from the
public `vidra-core` repo; locally it resolves the sibling `../vidra-core` checkout.

**Making a breaking API change spans two repos** — there is no longer one atomic
commit. Stage it back-compat: land the additive backend change in `vidra-core`
first (its `openapi` CI publishes the updated spec), then update `vidra-user`, then
remove the old endpoint in a later `vidra-core` change.

## CI

Each repo runs its own GitHub Actions:
- **vidra-core** — `backend-ci` (`make ci`), `backend-integration`, `openapi`, `ci-guard`.
- **vidra-user** — `frontend-ci` (`npm run ci`), `contract-ci`, `frontend-e2e-backed`
  (checks out `vidra-core` and runs the UI against the live backend), `ci-guard`.

This meta-repo runs `meta-ci` (validates `bootstrap.sh` and the full-stack compose).

## Autonomous development (Ralph)

Run a **per-repo loop** inside each component checkout — this is Ralph's native
single-working-tree model:

```bash
cd vidra-core && ralph --live      # uses vidra-core/.ralphrc
cd vidra-user && ralph --live      # uses vidra-user/.ralphrc
```

Each loop's terminal step is a plain `git add -A && git commit && git push` against
that repo's own `main` — no cross-repo pointer to bump. For a change that spans both
(e.g. an API endpoint), run the two loops **sequentially, backend first** (see the
contract note above).

The former monorepo root orchestrator (`.ralphrc`, `.ralph/PROMPT.md`,
`.ralph/fix_plan.md`) is **legacy** and no longer drives a loop from here. The
cross-cutting product specs under [`.ralph/specs/`](.ralph/specs/) (architecture,
PeerTube parity ledger, security, testing) are **preserved here as product docs**,
since they describe the whole platform rather than either component.

## License
TBD.
