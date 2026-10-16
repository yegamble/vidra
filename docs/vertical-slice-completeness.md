# Mechanical vertical-slice verification

From the meta checkout, run:

```sh
python3 scripts/ci/check-vertical-slice-completeness.py
python3 scripts/ci/check-vertical-slice-completeness.py --strict-migrations
```

The command supports nested and sibling component checkouts; independent
worktrees can pass `--core-root` / `--user-root` or `VIDRA_CORE_ROOT` /
`VIDRA_USER_ROOT`. Run `npm ci` in vidra-user first. It checks the existing
path/verb contract and regenerates API types with the locally pinned
openapi-typescript into a temporary directory, then byte-compares them to
`generated.ts`. The verifier never rewrites generated source.

The static inventory requires a method-specific client wrapper and a consumer
in the import graph reachable from `app/`. It understands the current API
object and endpoint-factory conventions, named barrel re-exports and aliases,
static/dynamic imports, and literal/template request paths. Tests, comments,
string examples, type-only imports and isolated import cycles do not mount UI.
Unresolved dynamic transports are reported for review; static evidence cannot
prove browser navigation, response rendering, authorization or behavior.
The exact-operation `BACKEND_ONLY_PATHS` map documents external byte/protocol
consumers. Product endpoints must not be hidden there to make the gate green.

Migration checks compare real SQL CREATE TABLE statements to `TABLES_ADDED`
and recovery classifications. Missing audits warn by default and fail under
`--strict-migrations`. These checks cannot establish rollback safety or that a
sealed credential remains decryptable; recovery and rollback drills remain
required. The default full inventory can fail on historical debt and must not
be described as production certification.

Claude SessionStart records immutable core/user commit SHAs in a hashed
session file under ignored `.claude/hooks/.state/`. Resume and compaction
preserve the original baseline. Stop compares static wiring findings with
those SHAs, so merging an incomplete backend PR during the session cannot
turn its missing UI into forgiven historical debt. Missing or invalid
snapshots run the full inventory or fail closed. Contract/type checks always
run in full. Manual `--baseline-ref origin/main` is available for diagnosis;
it is not the Stop-hook baseline.

The Stop hook also refreshes each repo's `origin/main`, checks actual commit
containment, dirty tracked files (including detached checkouts), upstream
pushes, and non-main branches. `MAX_BLOCKS=6` caps the reminder counter only:
failed verification continues blocking after six attempts. A blocked merge is
reported as **open — awaiting merge**. This does not authorize committing
someone else's changes, and untracked local environment secrets are ignored.
