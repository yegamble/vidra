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
pushes, and non-main branches. `MAX_BLOCKS=6` caps the reminder counter only:
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
| `PUT /videos/{id}/passwords` | [PasswordManager:71](https://github.com/yegamble/vidra-user/blob/57cceb9e5cbf47254cefa178d2758c88f93e9a91/components/PasswordManager.tsx#L71) adds individual passwords and [:86](https://github.com/yegamble/vidra-user/blob/57cceb9e5cbf47254cefa178d2758c88f93e9a91/components/PasswordManager.tsx#L86) removes them. This manages the set but does not expose the API's atomic bulk replacement semantics. That capability remains a product decision. |
| `POST /videos/{id}/license/clearkey` | There is no player license caller. The [core contract:6368](https://github.com/yegamble/vidra-core/blob/449e450954e231087ab401ff5b57f00dad39161f/api/openapi.yaml#L6368) explicitly says the endpoint is not usable and returns 404 on every install; [DRM provider:61](https://github.com/yegamble/vidra-core/blob/449e450954e231087ab401ff5b57f00dad39161f/internal/drm/drm.go#L61) says packaging integration is still missing. DRM requires a complete packaging and playback slice before a UI caller can work. |

All paths in this table are beneath `/api/v1`. These findings do not establish
that the corresponding product features are absent, nor that production is
ready: the scanner requires direct operation evidence, and no alternative or
deferred-capability policy is implemented here.
