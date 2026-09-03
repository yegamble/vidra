# AGENTS.md — vidra (meta repo)

Deployment/orchestration repo for the vidra platform: docker-compose files,
Caddy config, deploy/backup/restore/rollback scripts, env templates, and
audit docs. The application code lives in the component repos (vidra-core,
vidra-user, vidra-search), which are checked out NESTED inside this repo on
operator machines — those nested checkouts are gitignored here and pinned
DETACHED at release tags.

## Verification gates (run before opening any PR)

```
bash -n <every touched script>
shellcheck <every touched script>     # if available
cp env/production.env.example /tmp/check.env   # fill the ${VAR:?} keys with dummies
docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file /tmp/check.env config -q
```

`config -q` above is a complete check: Compose validates the whole model, and
the `${VAR:?}` asserts fire, whether or not profiles are selected (verified
2026-09-03 by breaking a service key and by removing `JWT_SECRET` — both forms
exit 1). But every service sits behind a profile, so if you drop `-q` to READ
the render, add `--profile core --profile frontend` or the output is a bare
`services: {}` and you will think the file is empty. Use the full form when you
need to assert what the prod overlay actually produces — e.g. that postgres,
redis and search publish no ports and api/frontend publish on 127.0.0.1 only:

```
docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file /tmp/check.env \
  --profile core --profile frontend config
```

## Hard rules

1. **One small PR per session.** Deploy tooling failures cost real downtime —
   keep diffs surgical and explain the failure mode each change closes.
2. **Ordering in `deploy/deploy.sh` is sacred**: pre-deploy dump (abort on
   failure) → pull → migrate as discrete exit-code-gated steps → `up -d
   --no-build` → health probes. Never fold migrations into `up -d`.
3. **Nested checkouts are a real trap** (incident 2026-08-10). *Mechanism
   corrected 2026-09-03 — the original bind-mount is gone, the rule is not.*
   The trap WAS that the migrate service bind-mounted
   `./vidra-core/migrations` from the nested checkout, which `git pull` on this
   repo does not advance, so a deploy could run new images against old
   migrations and exit 0. That is now architecturally impossible: migrations
   are compiled into the release binaries, and the rendered prod `migrate`
   service has **no volumes at all** — it runs `migrate up` on the same
   `VIDRA_CORE_TAG` image as the api, so image and migrations agree by
   construction. What survives is narrower and still load-bearing: the nested
   checkout is what `deploy.sh` reads to compute the EXPECTED migration
   version for its independent ledger assertion (a deliberate second opinion —
   reading it out of the migrator would only prove the migrator agrees with
   itself). So a drifted checkout no longer runs the wrong migrations, but it
   does invalidate the check that would catch the wrong ones. Any change
   touching migrations flow must keep the checkout-pinning + ledger-assertion
   guards intact, and must not reintroduce a migrations bind mount.
4. **Compose >= 2.24 assumptions**: `docker-compose.prod.yml` uses
   `!reset`/`!override` merge tags; older Compose silently ignores them and
   publishes Postgres/Redis on 0.0.0.0. Never remove the version check.
5. Keep the house script style: `set -euo pipefail`, `log()`/`die()`/`step()`
   helpers, comments that explain WHY (failure modes), POSIX-ish bash.
6. **Never commit secrets**: `env/*.env` stays untracked; only
   `*.env.example` files are committed. Never commit `.env.bak` files either.
7. Do not touch `.github/workflows` or bump pinned image digests/versions
   unless that is the task.

## Git hygiene — finished means merged (all agents / AI tools)

These rules bind every AI tool working in this repo (Claude, Jules, Codex, …):

1. **Commit early, push often.** Work on a short-lived branch off `main`.
   Prefer several small, scoped commits over one session-end mega-commit, and
   push the branch at every green checkpoint — unpushed work does not exist.
2. **A task is finished only when its work is merged to `main` and pushed.**
   Once the verification gates and the PR's CI are green, merge the PR before
   declaring the task done. If you cannot merge (no permission, review
   requested, red CI), report the task as **open — awaiting merge**, never as
   finished/complete/done.
3. **Delete merged branches.** Immediately after a merge: delete the work
   branch on the remote (`git push origin --delete <branch>`), delete it
   locally (`git branch -d <branch>`), then `git fetch --prune`. Also sweep
   for leftovers each session: delete any local (`git branch --merged
   origin/main`) or remote (`git branch -r --merged origin/main`) branch
   already merged into `origin/main`. Never delete `main`, the branch you are
   on, or an unmerged branch — an unmerged stray is reported for triage, not
   deleted.

**Enforcement:** `.claude/hooks/finished-means-merged.sh` runs as a Claude Code
`Stop` hook and refuses to let a session end while any repo here has
uncommitted tracked changes or unpushed commits. It ignores untracked files (so
`env/*.env` never trips it), skips detached checkouts (the pinned nested repos),
and gives up after 3 attempts. It is Claude-only — Jules, Codex and every other
tool are bound by the rules above regardless, with nothing mechanical to catch
them.

## Layout

- `deploy/` — deploy.sh, rollback.sh, backup.sh, restore.sh, release.sh
  (release.sh cuts GitHub releases in the component repos and verifies GHCR
  images), Caddyfile, systemd units.
- `env/` — production env template; `VIDRA_*_TAG` pins the deployed images.
- `docs/` — platform audits, parity reports, runbooks; treat them as the
  source of truth for known gaps and keep them honest.
