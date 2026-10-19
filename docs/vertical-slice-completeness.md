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
indexed scope dispatch, React-cached server fetches, called local transport
helpers, mounted inline requests, and literal/template request paths. Tests, comments,
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
pushes, and non-main branches. Every required repository must be present, and
every audited HEAD must equal its freshly fetched `origin/main`. An older
detached release pin can have valid ancestry but cannot certify latest-main
completeness. Keep deployment pins intact; configure separate current development
audit worktrees through `CLAUDE_PROJECT_DIR` / `VIDRA_*_ROOT` before SessionStart.
The immutable baseline binds those paths, so changing roots mid-session does
not fix an audit. Update only dedicated development sources when they fall
behind; the hook never switches or advances a checkout.
`MAX_BLOCKS=6` caps the reminder counter only:
failed verification continues blocking after six attempts. A blocked merge is
reported as **open — awaiting merge**. This does not authorize committing
someone else's changes, and untracked local environment secrets are ignored.

## Endpoint inventory that remains open

The following six operations have no direct UI caller. They stay findings;
the alternative flows below are evidence for a product/API decision, not
permission to exempt an endpoint. This inventory was reviewed against frontend
`57cceb9` and core `449e450` on 2026-10-16; newer contracts can add findings.

| Operation | Existing behavior and remaining decision |
| --- | --- |
| `POST /admin/storage/migrations/{id}/cancel` | [StorageMigrationControls:322](https://github.com/yegamble/vidra-user/blob/57cceb9e5cbf47254cefa178d2758c88f93e9a91/components/StorageMigrationControls.tsx#L322) calls `abortStorageMigration` through [/abort](https://github.com/yegamble/vidra-user/blob/57cceb9e5cbf47254cefa178d2758c88f93e9a91/lib/api/endpoints.ts#L2876). The [core contract](https://github.com/yegamble/vidra-core/blob/449e450954e231087ab401ff5b57f00dad39161f/api/openapi.yaml#L18813) states that abort without destination cleanup is exactly cancel. The legacy cancel route remains exposed. |
| `POST /videos/{id}/file` | [UploadSection:651](https://github.com/yegamble/vidra-user/blob/57cceb9e5cbf47254cefa178d2758c88f93e9a91/components/studio/UploadSection.tsx#L651) uses `resumableUpload`; the [transport](https://github.com/yegamble/vidra-user/blob/57cceb9e5cbf47254cefa178d2758c88f93e9a91/lib/api/resumable-upload.ts#L472) opens an upload session, sends chunks, and completes it. Direct multipart upload has no UI caller. |
| `POST /videos/{id}/replace` | [ReplaceVideoManager:617](https://github.com/yegamble/vidra-user/blob/57cceb9e5cbf47254cefa178d2758c88f93e9a91/components/studio/VideoRow.tsx#L617) uses `resumableUpload` with `mode: "replace"`, selecting `/replace-session`. Direct multipart replacement has no UI caller. |
| `PUT /playlists/{id}/videos` | [PlaylistDetailView:233](https://github.com/yegamble/vidra-user/blob/57cceb9e5cbf47254cefa178d2758c88f93e9a91/components/PlaylistDetailView.tsx#L233) calls `movePlaylistItem`. The [wrapper:2430](https://github.com/yegamble/vidra-user/blob/57cceb9e5cbf47254cefa178d2758c88f93e9a91/lib/api/endpoints.ts#L2430) documents why this paginated move replaced the full-list PUT. The full-list route remains exposed. |
| `PUT /videos/{id}/passwords` | [PasswordManager:71](https://github.com/yegamble/vidra-user/blob/57cceb9e5cbf47254cefa178d2758c88f93e9a91/components/PasswordManager.tsx#L71) adds individual passwords and [:86](https://github.com/yegamble/vidra-user/blob/57cceb9e5cbf47254cefa178d2758c88f93e9a91/components/PasswordManager.tsx#L86) removes them. This manages the set but does not expose the API's whole-set replacement operation. That capability remains a product decision. |
| `POST /videos/{id}/license/clearkey` | There is no player license caller. The [core contract:6368](https://github.com/yegamble/vidra-core/blob/449e450954e231087ab401ff5b57f00dad39161f/api/openapi.yaml#L6368) explicitly says the endpoint is not usable and returns 404 on every install; [DRM provider:61](https://github.com/yegamble/vidra-core/blob/449e450954e231087ab401ff5b57f00dad39161f/internal/drm/drm.go#L61) says packaging integration is still missing. DRM requires a complete packaging and playback slice before a UI caller can work. |

All paths in this table are beneath `/api/v1`. These findings do not establish
that the corresponding product features are absent, nor that production is
ready: the scanner requires direct operation evidence, and no alternative or
deferred-capability policy is implemented here.

## War-room follow-up — 2026-10-18

Scope: recover the studio password editor after a failed list request, and stop
a search reconciliation sweep when its outbox writes fail. This is a source
development record; the platform slice remains **IN_PROGRESS** with
**EXIT_SIGNAL: false**.

| Concern | Result and acceptance boundary |
| --- | --- |
| Password-list recovery | A failed GET leaves the count unknown (`null`), renders `ErrorState` with Retry, and disables mutations until a successful load. `Spinner` covers loading; a successful empty response alone renders the existing compact empty warning. Video changes reset pending mutation state and drafts. Loading/error copy exists in English and French. |
| Reconciliation enqueue errors | `RunReconcile` returns failed `reconcile.begin`, `reconcile.page`, and `reconcile.end` enqueue errors; a failed begin/page aborts the remaining sweep. This prevents a failed enqueue from reporting a successful complete sweep. |
| Search outage recovery | **Open.** Enqueue error propagation does not fix outbox delivery ordering. [core issue #267](https://github.com/yegamble/vidra-core/issues/267) tracks retry ordering that can let `reconcile.end` suppress newly indexed documents. Public search already falls back to SQL for an empty first page, so this does not mean all public search disappears; a partially populated index or later page can still omit results. |
| Bulk password replacement | **Open.** No bulk-replacement UI was added. Core [ReplacePasswords](https://github.com/yegamble/vidra-core/blob/519c40e936db9c572076254f1dbd3584b43bc019/internal/video/passwords.go#L118) calls `DeleteVideoPasswords` followed by `InsertVideoPasswords` without a transaction, so an insert failure can erase the previous set. Repair atomicity before exposing that operation. |

Core implementation: [PR #429](https://github.com/yegamble/vidra-core/pull/429),
source commit `8be066562a697ad84e89a97a4b79dc3313b8e3dd`, **merged** as
`519c40e936db9c572076254f1dbd3584b43bc019`. User implementation:
[PR #403](https://github.com/yegamble/vidra-user/pull/403), final source head
`2b25519ce75c6794edfdf1200ab3a8ec04d3e107`, **merged** as
`255b921f1ba1084432a347d904faa0727fe39aeb`.
Neither source fix is released or deployed.

The QA, product-completeness, and devil's-advocate reviews checked the actual
diffs and kept the two fixes separate from the unresolved capabilities above.
The compact empty warning is deliberate inside the editor; it distinguishes an
actual zero-password result without replacing the surrounding form with a
large `EmptyState`.

Verification evidence retained for this session:

| Check | Actual result |
| --- | --- |
| Password-manager regression | Initial focused run: 3 failed and 4 passed (7 total). Final focused component/parity run: 14 passed (8 component, 6 parity). Independent QA also ran 23 tests on an earlier patch; that result is supporting evidence, not final-patch proof. |
| User local gates | Restored lockfile dependencies (`Next 16.4.0`, `Vitest 5.0.3`) before final checks. Full unit suite: **388 files, 3,909 tests passed** (`/tmp/vidra-user-final-unit.log`). TypeScript, lint (four existing warnings), icon hygiene, contract check, and production build passed (`/tmp/vidra-user-final-static.log`, `/tmp/vidra-user-final-build.log`). The earlier run interrupted under stale dependencies is not a passing result. The final browser-test locator correction changed no production code and passed TypeScript/targeted ESLint. |
| User hosted CI | Final source head `2b25519`: [canonical frontend](https://github.com/yegamble/vidra-user/actions/runs/39198914657/job/117887585311) passed **388 unit files / 3,909 tests** and **654 browser tests, zero flaky/failed/skipped**. All seven manifest lanes and [ci-required](https://github.com/yegamble/vidra-user/actions/runs/39198914614/job/117887584779) passed, including backed [local](https://github.com/yegamble/vidra-user/actions/runs/39198914615/job/117887585275) and [S3](https://github.com/yegamble/vidra-user/actions/runs/39198914615/job/117887585197) lanes. Normal password round trips exercised the real backend and fresh refetch; failed-list Retry coverage is a mocked browser case. No local browser fleet was run. |
| Core checks | Enqueue-error regression and targeted race/tagged vet passed. `make ci` passed (`fmt-check`, `vet`, `migrate-lint`, `openapi-verify`, `sqlc-verify`, `test-race`); actual output retained at `/tmp/vidra-core-reconcile-make-ci.log`. All six manifest lanes and [ci-required](https://github.com/yegamble/vidra-core/actions/runs/39197680168/job/117884462155) passed; the [tagged integration retry](https://github.com/yegamble/vidra-core/actions/runs/39197680018/job/117884346880) also passed. |
| Meta Python suites | **897 passed, zero skips**; output retained at `/tmp/vidra-war-room-meta-python.log`. |
| Production Compose model | PASS: `docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file /tmp/vidra-war-room-check.env config -q` with temporary dummy required values; output retained at `/tmp/vidra-war-room-compose.log`. No scripts changed. |
| Mechanical completeness | **FAIL: six unchanged endpoint findings, zero migration findings** from `python3 scripts/ci/check-vertical-slice-completeness.py` after both source merges; actual output retained at `/tmp/vidra-war-room-final-mechanical.log`. The open operations remain cancel, direct file upload, direct replacement, playlist full-list PUT, passwords PUT, and ClearKey. No endpoint exemption was added. |

**VERDICT: INCOMPLETE — SEND BACK TO WAR ROOM LOOP.** These focused changes
do not establish production release/deployment, a real password-list dependency
outage drill, fleet recovery, migration/rollback safety, or security certification.
Remaining work: repair search delivery ordering and password replacement
atomicity in core; resolve the six endpoint product/API decisions; then supply
the runtime and release evidence required by the council protocol.
