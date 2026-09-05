# Vidra completion campaign — release readiness

Audit date: **2026-09-05**. Target: a fresh-server installation, migration of the operator's PeerTube instance, and complete required user/admin workflows with maintainable code. **Release readiness is not established.** There are confirmed workflow gaps, an initial contract mismatch explained by checkout skew, and no fresh-server or representative migration rehearsal in this audit.

This is the authoritative campaign record for this audit, superseding earlier readiness labels **only for the revisions and evidence below**. Historical plans remain requirement sources. The original audit used one agent with no product edits, commits, pushes, merges, deployment, or branch cleanup. The implementation session below authorizes scoped commits/pushes and a draft PR, but prohibits merge, release publication and production deployment. No production database, media bucket, credentials, or running stack was used.

## Revision boundary and evidence rules

| Repository | Audited HEAD | Checkout state at start |
|---|---|---|
| yegamble/vidra | `f79581146ed292833118eb109a5165f1e0aec9f7` | `main`, clean; latest commit pins example environments to v0.6.3 |
| yegamble/vidra-core | `b2d12a2a716addcd00b0a7fe061cbca127628a03` | detached at v0.6.2, clean |
| yegamble/vidra-search | `e8a1f76d4b9db28591d63e0cf68ea0afc2776f80` | `main`, clean; local v0.6.0, v0.6.1 and v0.6.2 tags all point here |
| yegamble/vidra-user | `cbc11451e6fc804e76a2a73e693e2f9842178bba` | `main`, clean; 11 commits after locally described v0.6.2 |

**Concurrent checkout change:** during this audit, an external action advanced core to `63eafcbf371122e5b69666e9e59131de4b2c06cc` (2026-09-04, distribution/federation short-code change). This agent did not change the checkout. The other three SHAs stayed unchanged. Final source checks use git archives in `/tmp/vidra-readiness-snapshot-r7s7uc6c`, whose `manifest.json` records all four SHAs; core at `63eafcb` plus the other three initial SHAs is the **final frozen source set**. The 45-file core delta was inspected for contract/media/import effects: it adds the resolver, short-code and imported PeerTube UUID columns/mappings (migrations 0126/0127), distribution URLs and media error handling. F02/F03/F06/F07 still apply. The initial contract failure is resolved on this final set; no new resolver implementation is recommended.

Neither source set is a tested release-image manifest. No remote fetch or current GitHub run lookup was performed by this audit; remote HEAD, v0.6.3 source/image correspondence, image availability, release checksums, and current CI conclusions remain unverified. Background checkout mutation invalidates a gate's revision attribution: the mutable-tree core retry was interrupted and replaced with a frozen-snapshot run.

Statuses apply to the behavior in each row:

- **PASS**: the specified check actually ran and passed on this audit's files. A static PASS proves only the named static property.
- **FAIL**: an executed check failed, or inspected implementation contradicts the expected behavior. Static contradictions are labeled as such; they are not reproduced runtime incidents.
- **UNVERIFIED**: code/tests or historical claims exist, but sufficient current execution evidence was not obtained.
- **BLOCKED**: an identified input, dependency, or scope decision prevents the acceptance procedure. This does not mean the feature passed when disabled.

Workflow acceptance requires the actual service boundary, successful and rejected actions, a persisted API/DB read, and fresh UI refetch. A mock, route registration, schema match, skipped test, or historical `VERIFIED` label is insufficient. Record exact revisions/images, command, environment/profile, test names, exit code, pass/fail/skip counts and artifact locations when promoting a row. Required tests must fail on missing prerequisites. Use synthetic data or a sanitized source copy; never place secrets, source password hashes or actor private keys in evidence.

### Sources inspected

- All four root `AGENTS.md` files; no additional nested `AGENTS.md` found in component trees. Read meta Ralph prompt/plan and targeted component prompt/plan requirements. `vidra-search` has no `.ralph` directory; its README, Makefile, API, `docs/architecture.md`, `docs/privacy.md`, `docs/operations.md` and CI are its local evidence sources.
- All four READMEs; [deployment runbook](../deploy/README.md), installer, bootstrap/deploy/compose/library/provision/release/backup/restore/rollback scripts, Caddy routing, base/prod/external datastore Compose definitions, production example environment and CI entry points.
- Core [product decisions](../vidra-core/.ralph/specs/product-decisions.md), [migration design](../vidra-core/.ralph/specs/peertube-import.md), [migration guide](../vidra-core/docs/peertube-migration.md), importer implementation and fixture integration tests; both component PeerTube and extension ledgers and fix plans.
- Meta [parity acceptance](../.ralph/specs/parity-acceptance.md), [backport program](../.ralph/specs/backport/PROGRAM.md), feature-vision inventory, [config parity ledger](../.ralph/specs/config-parity/ledger.md), productionization phase 1–5 status/exit criteria and CMAF/P2P/content-steering decisions; `docs/short-codes-2026-09.md` records the later resolver programme and frozen federation identities. Archived OpenAPI references describe proposals, not the current served contract.
- Current core/search OpenAPI, frontend API client and generated types, server route registration and service wiring; selected workflow implementations and backed tests. This is a targeted workflow audit, not exhaustive line-by-line review of every handler or independent upstream PeerTube parity certification.

## Baseline checks performed

Host: macOS arm64; Go 1.26.2, Node 22.14.0, Compose 5.1.0, shellcheck and sqlc available. Frontend `package.json` requires **Node >=24**; therefore frontend checks on this host are diagnostic and cannot certify the supported release environment. No frontend E2E suite was executed, consistent with `vidra-user/AGENTS.md`.

| Check | Result and limits |
|---|---|
| Git status and revision inventory | PASS: all four trees initially clean; no checkout or branch operations performed |
| `bash -n` and `shellcheck -x`, separately on `bootstrap.sh`, `install.sh`, `tests/install_test.sh`, `deploy/*.sh` | PASS: 12 scripts each, zero errors |
| `bash tests/install_test.sh` | PASS, exit 0: Compose version cases, hostile/corrupt bundle handling, release pin checks, migration lock-wait bounds. Extracted-function/fixture tests, **not** a real Linux installer run |
| Production Compose JSON render with dummy secrets, explicit base+prod files, core/frontend/edge profiles | PASS, exit 0. postgres/redis/search publish no ports; API 8080 and frontend 3000 bind only 127.0.0.1. Both migration services have no volumes and use the same image tag as their corresponding service. Rendering does not pull images or start containers. Final snapshot `config -q` also passes default, external Postgres, external Redis and both-external+worker shapes with appropriate dummy DSNs. Missing JWT and missing external DSNs each correctly fail (exit 1) |
| Frontend path/method contract guard | Initial set **FAIL**: missing `/api/v1/videos/resolve`, 230 backend paths / 302 operations. Final frozen set **PASS**, exit 0: 231 paths / 303 operations, all 202 client paths / 257 call sites covered |
| OpenAPI generated-type comparison | Final frozen set **PASS**: installed `openapi-typescript` writes only `/tmp/vidra-readiness-generated-final.ts`; byte comparison with archived user `lib/api/generated.ts` matches. No generated product file edited |
| `node scripts/check-no-emoji.mjs` | PASS, SVG/icon guard |
| `tsc --noEmit --incremental false` | PASS, exit 0; does not prove compatibility with sibling core |
| Search `GOMAXPROCS=2 GOFLAGS=-p=2 GOCACHE=/tmp/vidra-readiness-go-cache make ci` | PASS, exit 0 at unchanged `e8a1f76`: fmt/vet/migration lint/OpenAPI/sqlc/race gate. This is not tagged integration evidence |
| Core `GOMAXPROCS=2 GOFLAGS=-p=2 GOCACHE=/tmp/vidra-readiness-go-cache make ci` | Final frozen `63eafcb` **PASS**, exit 0: fmt/vet/migration lint (127 up migrations)/OpenAPI/sqlc/race. Initial sandbox run failed (exit 2) because httptest could not bind localhost; approved retry used temporary listeners outside the sandbox. Mutable-tree retry was interrupted after drift and is not evidence |
| Tagged integration compile/vet | `go vet -tags=integration ./...` PASS, exit 0 for final frozen core and unchanged search. No live integration tests executed |
| `npm run lint` | PASS, exit 0, zero errors/two warnings (WatchView internal navigation and unused test variable) |
| `npm run test -- --maxWorkers=2` | **FAIL**, exit 1: 2200 passed / 82 failed, 220 passed files / 8 failed files. Failures include localStorage methods missing and an AdminVideosView 5-second timeout. Node 22 is below declared >=24; reproduce under supported Node before assigning product defects. No failure suppressed |
| Initial unconstrained Go/lint/Vitest invocations | Interrupted (exit 130) during slow execution; not passes. Bounded retries replace their results |
| Live database/media/browser/fresh-server/migration/recovery tests | NOT RUN; workflows below remain UNVERIFIED or BLOCKED. No skipped dependency was accepted as a pass |

Raw local scratch evidence: `/tmp/vidra-readiness-*.log` and the `vidra-readiness-m6o06lzt` directory under the host temporary directory. The durable result is this record; scratch paths are not a substitute for release-attached artifacts. Compose scratch input used v0.6.1 as a dummy tag to test interpolation, **not** as a selected campaign release.

## Findings that change the campaign

1. **F01 — initial source skew, resolved for the final frozen source set.** The initial core at v0.6.2 lacks the resolver consumed by user `lib/api/endpoints.ts:298` and `lib/video.server.ts:37–55`. After the external core advance, `server.go:1527` registers it and both the path/method guard and generated-type comparison pass. `docs/short-codes-2026-09.md` independently records the later programme. Still prove the release images and actual canonical/legacy/password links together; do not implement a duplicate resolver.
2. **F02 — copy-mode migration does not deliver all playable media.** Core `internal/peertubeimport/importer.go:492–509` explicitly says no automatic re-transcoding occurs; HLS-only source content can yield `video_no_media`. The guide's “relies on the pipeline after import” understates the required per-video admin enqueue and cannot recover a missing original. A self-contained migration needs an HLS acquisition/remux/copy strategy or an explicit retained-source requirement, plus a durable, resumable backfill.
3. **F03 — approved messaging limits stop at the backend.** Core product decision §14a and `internal/messaging/service.go:85` permit thirty attachments and 100 MiB/file; user `components/messaging/Composer.tsx:15–16` still permits four and 25 MiB. The old frontend “blocked on core D6” note is stale. Fix against generated types, including the document MIME/kind UI, with recipient readback.
4. **F04 — release proof lacks the complete service chain.** Meta `meta-ci.yml` boot lane builds core in production mode with transcoding disabled and search integration unset, then checks both migrators. User backed workflow starts core's Compose, not meta's search-inclusive stack. `e2e-backed/search-discovery.spec.ts:11–16` self-skips without `E2E_SEARCH_SERVICE=true`; that variable is absent from its workflow. A green combination of these lanes cannot certify upload → real transcode → browser decode → search indexing.
5. **F05 — fresh-host and recovery evidence is absent.** Installer tests and Compose checks pass, but no audit proof covers Linux package installation, released bundle/CLI/images, setup, owner claim, restart, backup and replacement-host restore together. Do not run the installer against this workstation or reuse existing volumes as “fresh.”
6. **F06 — optional CDN work has concrete unfinished correctness dependencies.** Core `internal/httpapi/media_purge.go`'s STILL UNPURGED list includes thumbnail/storyboard replacement, same-source re-transcode, account deletion, and instance-wide download revocation. `internal/media/hls.go:HLSGenerationName` addresses source replacement generations, not every transcode. CDN acceptance needs generation-safe keys and bounded purge work, followed by actual edge tests; proxy playback remains a separate acceptance path.
7. **F07 — migration dry-run documentation is stronger than the implementation.** `Importer.Preflight` calls `checkDestinationWritable` before schema validation; that performs a destination object write/delete even for dry-run, and failed cleanup can leave the scratch object. Admin dry-run also persists an import-run record. The source remains read-only by design. “Writes nothing” needs to distinguish source/entity writes from destination probe/run metadata; use a disposable destination for preview.
8. **F08 — importer delivery is incomplete for CLI operators.** Core Dockerfile packages only `cmd/api`; release-assets builds the `vidra` CLI, not `cmd/peertube-import`. The migration CLI examples require a source build. The shipped admin API/worker is a viable alternate path, so **migration as a whole is not absent**. Provide a supported no-toolchain CLI path or make the admin path the complete, tested operator procedure.

### Re-investigated historical labels

| Earlier claim | Current evidence and disposition |
|---|---|
| Worker settings freeze at boot (`docs/beta-readiness-2026-09.md`, productionization audit) | Refuted at audited core: `cmd/api/main.go:1420–1468` starts settings polling for every role; only status exposure is HTTP-gated. Split-topology execution still UNVERIFIED |
| Search config reaches service only on startup | Refuted as a blanket claim: `internal/httpapi/admin_instance_settings.go:356` calls `emitSearchConfigChangedIfNeeded`; `search.go:737` enqueues config events. Verify delivery, restart/retry and split workers |
| S3 has no automated integration/browser lane | Refuted: core `backend-integration.yml:120–168` starts MinIO and sets `S3_TEST_ENDPOINT`; user backed workflow has local/S3 matrix. This audit did not execute those lanes or verify their remote run conclusions |
| IPFS playback exists only on mocks / no backed coverage | Stale: user workflow now has an IPFS job for `ipfs.spec.ts` and `ipfs-privacy-fence.spec.ts`. Public/private distribution correctness still needs current execution evidence |
| All moderation state is omitted from migration | Too broad: `peertubeimport/entities.go` carries suspended users and video blacklist into `video_blocks`; `report.go` exposes those counts. Account/server blocklists and abuse reports remain deferred |
| Whole media pipeline / auth / admin features `VERIFIED` | Retained as historical claims, downgraded to UNVERIFIED here unless the complete specified procedure was executed. Existence of a test is not its outcome |
| IPFS and channel sync “not built” in older ledgers | Superseded by implemented mirror services, channel-sync service/UI and dedicated CI jobs. Do not rebuild; verify and reconcile the records |
| Main README describes installer cloning and Node 20+ | Current installer defaults to verified bundle with git fallback; frontend requires Node >=24. Setup/runbook reconciliation is acceptance work |
| Config gap-matrix `missing` fields | Ledger explicitly calls this a frozen pre-implementation snapshot. Use the later W1–W15 record and current registry, not the JSON labels alone |

## Workflow readiness register

Owners: **M** meta-repo; **C** core; **S** search; **U** user. Relative source paths below are rooted in the named owner unless prefixed otherwise. There are **59 workflow rows: 1 static PASS, 3 FAIL, 40 UNVERIFIED and 15 BLOCKED**; the 10 scope families below are additionally BLOCKED on decisions. These are workflow statuses, not test counts. All required workflows are retained. “Conditional” means required if that capability is selected; disabling it does not prove it. Decision-dependent extensions remain visible in the scope register after this table.

Every procedure involving a mutation includes independent API/DB readback and UI reload, even where abbreviated below. For all media paths include owner, ordinary user and anonymous visibility, failed jobs, retries, and deletion/revocation. Dependency IDs are gates, not reasons to omit a row.

| ID / required behavior | Owners | Evidence at audited revisions | Status | Verification procedure | Dependencies → next action |
|---|---|---|---|---|---|
| REL-01 Compatible release sources, contracts and images | M C S U | F01 initial mismatch; A01 now pins and validates v0.6.2 sources/images/assets (see implementation evidence below); runtime version probes remain unverified | UNVERIFIED | Resolve all four SHAs and OCI digests for one release in a disposable tree; run both route guards, frontend path/codegen drift checks and version probes | None → A01 |
| INS-01 Install on blank supported Linux host without developer tools | M C | `install.sh`, `tests/install_test.sh`, `cmd/vidra`, release-assets; F05 | UNVERIFIED | Empty Debian/Ubuntu VM: verified bundle+CLI download, install/setup, re-run preserving secrets/config; also test git fallback, corrupt download and interrupted install | REL-01 → A02 |
| INS-02 One setup engine writes valid configuration and explains next steps | M C U | Core `internal/setup`, `cmd/vidra`; prod template; first-boot runbook | UNVERIFIED | CLI/noninteractive/web setup: domain, local/S3, registration and existing-key preservation; compare generated config, validate runtime frontend API origin; no browser credential disclosure | INS-01 → A03 |
| INS-03 Production Compose closes datastore ports and binds app ports locally | M C S | Fresh dummy JSON render; both migrators use service images with no volumes | PASS | Re-render explicit base+prod, core/frontend/edge; inspect ports, image equality, missing-required-secret failure; PASS here covers default static render only | REL-01 → carry render assertion into A02 |
| INS-04 First deploy migrates both ledgers before starting serving processes | M C S | `deploy.sh` dump→pull→two gated migrators→independent ledgers→up→probes; embedded SQL | UNVERIFIED | Empty volumes; assert expected core/search version and clean flag; inject failing/dirty migrator and failed pre-upgrade dump; prove no subsequent restart; test lock timeout | INS-01 → A03; preserve pin/ledger guards |
| INS-05 TLS/proxy/runtime URLs work at the installed domain | M C U | Caddy routes; user runtime-config and server API origin; five TLS modes in deploy library | UNVERIFIED | Real HTTPS edge: API, frontend, media Range, setup, static, well-known/federation and legacy watch routes; restart with new lab origin; test selected external/internal TLS mode separately | INS-04 → A03 |
| AUTH-01 Owner claim is exclusive, one-time and grants admin | C U M | `auth/ownerclaim.go`, `e2e-backed/owner-claim.spec.ts`, setup routes | UNVERIFIED | Before claim all signup methods refuse; valid boot token claims once; restart invalidates old token; race two claims; admin/system succeeds only for claimant | INS-05 → A04 |
| AUTH-02 Registration, approval, login, logout and session refresh persist | C U | Auth service/routes; backed auth-persistence/session/registration-approval tests; approval opt-in | UNVERIFIED | Open/closed/approval registration with two users; accept/reject; expiration/refresh/revoke; reload and multi-tab/logout; rejected credentials never create sessions | AUTH-01 → A04 |
| AUTH-03 Email verification and password recovery deliver real mail | M C U | `internal/mail/smtp.go`; backed reset/verify use dev capture | BLOCKED | Disposable SMTP sink + browser token redemption, expiry/reuse and enumeration behavior; then operator-selected SMTP delivery and disabled-mail UX | AUTH-02 + SMTP selection → A05 |
| AUTH-04 TOTP enrollment, recovery and removal; OAuth/OIDC login/link/unlink | C U M | Core auth/MFA/OAuth routes; backed mfa/oauth-identities; real provider not supplied | BLOCKED | TOTP second login/recovery/revoke; local OIDC provider callback/state/PKCE, account collision and unlink-last-method policy; never substitute a precreated identity for login | AUTH-02 + OIDC selection → A05 |
| AUTH-05 Profile/privacy, email/password changes, deactivation/deletion and account archive | C U S | Backed profile-edit/deactivate/delete-account/account-export; core account and search deletion hooks | UNVERIFIED | Mutate profile/unlisted/email/password with re-verification, export and import supported archive; delete/deactivate with content, sessions, follows and search history; verify recipient DM retention policy and media cleanup | AUTH-02, SRC-02 → A12 |
| PUB-01 Create channel and draft; upload a real file within quota | C U M | `internal/video`, upload routes; backed upload/studio/channel-management | UNVERIFIED | Browser-create channel/draft; upload generated audiovisual clip; inspect original metadata, owner quota accounting and durable state; deny nonowner/overquota/invalid input | AUTH-02 → A06 |
| PUB-02 Resumable upload, cancel, draft recovery and batch publishing | C U | W2 plans; backed upload-draft-recovery/upload-cancel/upload-batch | UNVERIFIED | Interrupt network and restart service between chunks; resume without duplicate files/charges; recover draft on another session; cancel cleanup; partial batch failure retained | PUB-01 → A10 |
| PUB-03 Transcode durable jobs into playable CMAF/HLS ladder | C M U | `internal/media/hls.go`, CMAF packager, transcode jobs; backed hls-playback | UNVERIFIED | Real ffmpeg job: source→processing→ready; fetch advertised master, audio/video variants, init/segments; decode audio and video; retry crash without duplicate promotion | PUB-01 → A07 |
| PUB-04 Schedule/quarantine/privacy gates survive processing and replacement | C U S | Schedule/quarantine backed specs; replace handlers; instance gates | UNVERIFIED | Publish-after-transcode and schedule, quarantine approve/reject, replacement preserving URL/metadata; no premature discovery; concurrent old/new playback; failed replacement retains prior usable generation | PUB-03, SRC-02 → A10 |
| PLAY-01 Watch, seek, quality, speed, resume, PiP/theater and mobile/native playback | C U | `components/player`, HLS hook, backed hls-playback/player-settings/history | UNVERIFIED | Browser actual currentTime advance and audible track, seek, quality change and saved preferences; Chromium plus native-HLS Safari on representative ladder; original fallback when appropriate | PUB-03 → A07 |
| PLAY-02 Canonical/legacy links, sharing, embeds, oEmbed/feed/sitemap | C U M | F01 resolved at final snapshot; resolver and imported UUID mapping now present; no actual browser route proof | UNVERIFIED | Run path guard first; follow canonical and old PeerTube/UUID/short links through edge with timestamps; verify privacy/password unlock and embed origin rules, metadata and downloadable file | REL-01, PLAY-01 → A01 then A08 |
| PLAY-03 Private, unlisted, password, embed and download revocation | C U S | Backed video-password/embed; HTTP media auth and purge helpers | UNVERIFIED | Copy all manifest/segment/original/caption/storyboard URLs to unauthorized session; enforce token expiry, unlisted discovery exclusion and changed download policy; test account-unlisted transition | PLAY-01, SRC-02 → A08 |
| CRT-01 Studio edit/delete/taxonomy/tags/thumbnails/chapters/storyboards | C U S | Studio/channel/taxonomy/tag/upload-thumbnail backed specs; core chapters and storyboard handlers | UNVERIFIED | Edit every supported field and reorder chapters; real frame extraction and hover sprite; fresh detail/UI fetch; delete and verify bytes/discovery vanish; source replacement retains identity | PUB-03, SRC-02 → A11 |
| CRT-02 Creator/channel/video statistics are accurate and scoped | C U | Core stats/view-day rollups; user HEAD fixes previous-channel totals | UNVERIFIED | Two creators/channels; known views/ratings/comments; dedupe; switch channels during requests; unauthorized stats refusal; imported totals distinct from absent daily history | PLAY-01 → A11 |
| SRC-01 Real outbox→search indexing→visible search result | M C S U | Core `searchevents`, search client/drainers; S `/internal/v1/events`; F04 | UNVERIFIED | Finish real upload/transcode, inspect outbox acknowledgement + indexed ID, issue UI query and click result; prove service used rather than SQL fallback; no seeded index substitution | PUB-03, REL-01 → A09 |
| SRC-02 Search privacy, retries, deletion and degraded fallback | C S U | Core search hydration predicate; S idempotent events/privacy/retention; health probe | UNVERIFIED | Duplicate/reorder/retry events; private/quarantine/unlisted/delete/block transitions; stop search and retain safe SQL fallback; restart/reconcile and verify history/personalization opt-out | SRC-01 → A09 |
| SRC-03 Discovery, suggestions, trending, recommendations and history controls | C S U | S APIs/worker jobs; user search-discovery opt-in; ranked IDs rehydrated in core | UNVERIFIED | Seed synthetic multi-user engagement above privacy thresholds; check filters/paging/ranking, related/home cards and suggestion bans; history delete survives reload/reconcile; no personalized data when off | SRC-02 → A13 |
| SOC-01 Follow/subscriptions, saves, playlists and watch history | C U S | Backed subscribe/subscriptions/save/playlists/history/continue-watching | UNVERIFIED | Two accounts; follow then publish notification/feed; unfollow; playlist CRUD/privacy/order/cover and playback continuation; history disable/clear and watch-later persistence | PUB-03, AUTH-02 → A12 |
| SOC-02 Comments/replies/ratings, mentions, reports and notification preferences | C U | Backed comments/comment-replies/rating/report/notifications/notification-prefs | UNVERIFIED | Three actors: reply attribution, intended recipient notification, deleted/tombstoned parent, blocked/muted content; refresh unread counts/preferences and resolve report | SOC-01 → A12 |
| MSG-01 Plaintext DM timeline, retry/read receipts/delete/report and attachments | C U | `internal/messaging`; backed messaging/message-compose; frontend P-MSG2 unfinished boxes | UNVERIFIED | Two browser contexts send/poll/read, prepend history without jumps/duplicates, retry once, receipts opt-out, delete/report; recipient downloads attachment, third party denied | AUTH-02 → A14 |
| MSG-02 Approved 100 MiB / 30-file and office-document attachment behavior | C U | F03; product decision §14a vs Composer limits | FAIL | Boundary values, 31st file and oversize refusal; document kind renders; multi-file recipient API/UI readback; configured scanner failure semantics | MSG-01, INT-04 → A14 |
| MSG-03 E2EE device/session lifecycle and honest unsupported attachments | C U | `internal/e2ee`, Olm client; backed e2ee; D7 defers encrypted blobs | UNVERIFIED | Two devices establish encryption; inspect server stores ciphertext only; restart/recover/unlink as supported; plain attachment affordance absent and API rejection; no IPFS pin for DM bytes | AUTH-02 → A15; encrypted blobs remain SCP-03 |
| ADM-01 Users/roles/quotas/suspensions/signup approval with lockout guards | C U | Backed admin-users/registration-approval; requireRole and self guards | UNVERIFIED | Admin vs moderator vs user; quotas, verified/bypass flags, deactivate/reactivate, reject self-demotion; session revocation and audit evidence | AUTH-02 → A16 |
| ADM-02 Reports, video blocks/quarantine, mutes, watched words and appeals/context | C U S | Backed moderation/admin-comments/blocked-videos/watched-word-matches/instance-mutes | UNVERIFIED | Report video/comment/message; staff review and note; owner notifications; ban/block/unblock and affected feeds/search; unauthorized and bulk behavior inventoried explicitly | SRC-02, SOC-02 → A16 |
| ADM-03 Runtime config, branding/legal documents and feature capability truth | M C U S | Instance registry/config parity W1–W15; core settings poller and search config events | UNVERIFIED | Change typed settings/documents/images in admin; observe public/UI/worker/search after refresh and restart; dependencies missing must be explained; test dangerous custom CSS/JS confirmation path | INS-05, SRC-01 → A17 |
| ADM-04 Health/jobs/audit/infra/storage-GC dashboards reflect real operations | M C U S | Core admin system/jobs/audit/media-GC; backed admin-system/admin-audit; `vidra doctor` | UNVERIFIED | Create failed job and degraded dependency, inspect status/log correlation/retry; doctor identifies drift and backup age; regular users denied; no secrets in responses/logs | PUB-03 → A17 |
| MIG-01 Source/version/storage preflight and truthful dry-run | M C U | Importer Preflight/report/version, admin import UI; F07 | BLOCKED | Obtain sanitized source/schema; read-only DB role and source filesystem/bucket; preview includes conflicts/unsupported/counts and destination probe side effects; unsupported version refused without automated override | INS-04 + source inventory → A18 |
| MIG-02 Accounts, roles, bcrypt login, channels and actor keys migrate safely | C U | `entities.go`, actor-image passes, sealed keys, integration fixture | BLOCKED | Import sample admin/mod/user/suspended accounts and collisions; login with source password; verify role/claim coexistence; rerun preserves Vidra-owned changes; compare public actor identity without exposing keys | MIG-01, AUTH-02 → A19 |
| MIG-03 Videos/media/metadata transfer produces independent playable catalogue | C U M | F02; copy/reference/none modes, report `video_no_media`; actor/poster/storyboard copying | FAIL | Sample progressive+HLS-only, split audio, captions, private/password/unlisted/blocked content; compare counts/hashes; source disconnected after copy; decode all selected media and require zero unexplained no-media rows | MIG-01, PUB-03 → A20; source sample still needed |
| MIG-04 Comments/playlists/tags/follows/ratings/chapters/views/taxonomy reconcile | C U S | `entities_pervideo.go`, taxonomy ledger, original dates/view-delta passes | BLOCKED | Rehearse parent-first import, restart and repeat: no doubles; compare source/local expected counts, thread/order/privacy, lifetime deltas vs no invented daily history; imported items searchable | MIG-02, MIG-03, SRC-02 → A21 |
| MIG-05 Omitted safety/user data and instance identity have explicit disposition | M C U | Deferred families; blacklist/suspensions implemented; other moderation/history/preferences absent | BLOCKED | Inventory actual source reports/blocklists/history/preferences/provenance/settings; port each required family or retain approved archive/manual conversion; reconcile name/terms/categories and role/quota policy | MIG-01 + retention decisions → A22 |
| MIG-06 Repeatable cutover, old links and federation continuity | M C S U | Source-authoritative mode; legacy frontend routes; source readonly design | BLOCKED | Rehearsal timed full+delta; stop source writes for final snapshot, reconcile media/data, old links and two-instance actors/follows; documented rollback while source retained; no dual-writer or public federation rehearsal | MIG-02–05, PLAY-02, REC-02 + domain plan → A23 |
| STO-01 Local/S3 canonical storage persists and serves valid media | M C U | Storage interface, local/S3 adapters; current MinIO CI lanes | UNVERIFIED | Run PUB/PLAY on both backends; bucket creation/write/Range/content-type/space exhaustion; recreate containers and verify bytes; deployment filesystem ownership | PUB-01 → A07 local, A24 S3 |
| STO-02 Reference-mode foreign media is protected from garbage collection | C M | `internal/mediagc` ownership marker, foreign-layout adoption refusal and keep rules | UNVERIFIED | Disposable shared bucket with foreign and Vidra keys; dry-run/adoption refusal/orphan breaker; delete imported record then sweep; foreign objects remain byte-identical | MIG-01, STO-01 → A24 |
| STO-03 Storage migration/copy/verification/abort and GC interlocks | C U M | `internal/storagemigration`; phase-2 plan and integration tests | UNVERIFIED | Local→MinIO copy with checksums, failures/resume and final authority switch; prove reads during movement and old-store retention; GC cannot race migration | STO-01, REC-01 → A25 |
| INT-01 Live RTMP ingest→HLS watch→replay with moderation | M C U | `media` profile, live service/hooks/replay; backed tests simulate hook transitions | BLOCKED | Actual RTMP publisher with audio; live watch advances, authorization and stream-key rotation; terminate/max-duration/disconnect→replay; verify selected ladder/latency; hooks alone insufficient | PUB-03 + live selection/ingest plane → A26 |
| INT-02 Direct URL import, yt-dlp platform import and channel auto-sync | M C U | Videoimport/channelsync; W2; released image yt-dlp build arg; dedicated channel-sync CI | UNVERIFIED | Local fixture origin/file and extractor fixture; scheduled channel discovers new item once; restart/retry/SSRF/disabled gates; verify released image actually contains executable | PUB-03 → A27 |
| INT-03 Manual captions and Whisper generation/review | M C U | Caption routes/CaptionsManager; backed captions/whisper-captions opt-in | BLOCKED | Manual VTT CRUD, watch track and language; configured Whisper audio→job→editable caption; outage/timeout and unsupported language; owner-only access | PUB-03 + Whisper selection/endpoint → A28 |
| INT-04 ClamAV scanning actually gates all ingestion | M C U | Scanner service; scan profile; uploads/imports/DM hooks and config policy | BLOCKED | Disposable scanner: benign file, standard EICAR fixture, unavailable scanner, approved fail policy; never publish/link rejected bytes; test URL and DM paths as well as upload | PUB-01 + scanner selection → A28 |
| INT-05 ActivityPub remote discover/follow/accept/video/comment/delete/moderation | M C U | Federation service/integration tests; user federation queues; no two-instance backed lane | BLOCKED | Two isolated instances: signed inbox/outbox, approved/rejected follow, new/update/delete videos, reply, block server/account, remote URL; source identity after migration | INS-05, ADM-02 + AP selection → A29 |
| INT-06 ATProto/Bluesky login, linking and outbound cross-post | M C U | Auth/ATProto service, connection UI; backed atproto opt-in; old extension “no login” claim stale | BLOCKED | Test PDS/account: login callback/state, link/unlink, private exclusion, public post contains working watch URL; restart sealed credential and outage/retry; no public rehearsal posts | AUTH-02, PLAY-02 + provider/test account → A30 |
| INT-07 Public IPFS mirror and viewer fallback preserve disclosure boundary | M C U | Mirror eligibility; dedicated backed IPFS job and privacy fence | BLOCKED | Private test network: publish eligible object→real CID→master+segments playback; gateway failure→canonical fallback; unlist/delete unpin, no private/quarantine/DM ledger row; record irreversibility of real public publication | PLAY-01 + IPFS selection → A31 |
| INT-08 Private IPFS is isolated replication, never public delivery | M C U | Product decision §5.P; private-swarm CI; no private gateway knob; DM excluded | BLOCKED | Two keyed nodes and outsider: replication works only inside, outsider cannot fetch; private CID absent from APIs; quorum/outage recovery; no DM attachment pins | STO-01 + private topology selection → A31 |
| INT-09 Presigned S3 browser delivery obeys CORS/expiry/authorization | M C U | Delivery resolver/presign; historical browser CORS incident; core README notes | BLOCKED | Real cross-origin bucket in browser: Range/preflight/307, expiry and private refusal; Chromium and Safari; bucket outage does not masquerade as success | STO-01, PLAY-03 + selected bucket/CORS → A32 |
| INT-10 CDN redirects, purge and versioned media remain correct | M C U | F06; CDN provider/resolver and purge ledger | FAIL | Edge simulator first, then selected edge: retranscode/replacement, privacy/delete/global download revoke and failed purge/retry; stale segments must never play; failure after redirect tested | PLAY-03 + CDN selection → A33 |
| INT-11 Noncustodial donation addresses verify and display honestly | C U | Donation service; backed donations; product decision excludes custodial flows | UNVERIFIED | Address validation/challenge/ownership verification, update/remove and profile/watch support dialog; no fabricated payment confirmation or funds handling | AUTH-02 → A30 |
| OPS-01 API/worker split updates settings and recovers leased jobs | M C S | All-role settings poller now fixed; job leases/sweeps; worker Compose profile | UNVERIFIED | API-only + two workers; edit config, observe both; kill one mid-transcode/import, recover once; Redis/DB outage and leader failover; no local-volume split across hosts | PUB-03, ADM-03, STO-01 → A34 |
| OPS-02 Health, logs/trace correlation, metrics/QoE and retention are useful | M C S U | Observability/OTel/QoE packages; search metrics and privacy retention | UNVERIFIED | Follow one browser upload/play/search via correlation; inspect safe structured logs, failed worker status and bounded metrics; run retention; distinguish native-HLS/proxy/CDN source truth | SRC-01 → A35 |
| REC-01 Backup includes DB, settings/sealing keys and required media | M C S | `backup.sh`, config archive, deploy runbook local/S3 snapshots; search schema in same DB | UNVERIFIED | Disposable data: backup/check restore-list; failed dump never finalizes; encrypted offsite config/media retrieval with same timestamp; search models/rebuild plan and S3 version retention documented | INS-04, STO-01 → A36 |
| REC-02 Restore on replacement host yields usable accounts/media/search | M C S U | `restore.sh`, disaster-recovery order; no audit rehearsal | UNVERIFIED | Destroy only disposable host; restore config before DB/media, apply known migrations, login and decrypt saved integrations, play old+new uploads, reindex search; measure RPO/RTO | REC-01, SRC-01 → A37 |
| REC-03 Upgrade/rollback and dirty-schema recovery preserve data | M C S U | Deploy/rollback floor, separate ledger guards, schema-compat workflow | UNVERIFIED | Upgrade previous compatible release with data; injected migration failure abort; supported app-only rollback; incompatible schema uses tested backup restoration; no blind force/automatic down migrations | REL-01, REC-02 → A38 |
| QLT-01 Contract/codegen/sqlc/tests remain reproducible and maintainable | M C S U | Final contract/codegen PASS; frontend baseline FAIL on unsupported Node; independent gates insufficient for release | UNVERIFIED | Same release manifest under supported Node/Go; contract/codegen/sqlc diff, unit/race/tagged integration and selected backed suites; required missing services fail; preserve small additive contract changes | REL-01 → A01 then A39 |
| QLT-02 All required screens handle keyboard/mobile/themes/errors and real persistence | U C | Design system; mocked axe suite vs backed persistence; unfinished P-MSG2 and admin notes | UNVERIFIED | Inventory every required control by role; 390px and desktop, light/dark, keyboard/axe, loading/empty/error/retry; mutation readback after full reload; no dead controls | All selected workflows → A40 |

## Deferred and decision-dependent scope — not silently removed

These items are **BLOCKED on scope/acceptance**, not PASS. Existing explicit decisions stand until changed; this campaign does not authorize implementing a contrary feature. Their implementation gaps remain tracked even if the operator keeps them outside launch. No “everything complete” claim is valid while required members remain undecided.

| ID / retained requirement family | Owners / sources | Present position, verification and next action |
|---|---|---|
| SCP-01 Payments, subscriptions/Inner Circle, premium, invoices/tips/Lightning/BTCPay, payouts and custodial wallet | C U M; backport W5/PAY-01…11, parity acceptance | Explicitly deferred; verified wallet display is INT-11 only. Decide inclusion before building; if required, split invoice/provider persistence, webhook idempotency, entitlement, UI and reconciliation acceptances. Dependency: AUTH/ADM and payment provider; no payment action in audit |
| SCP-02 Browser P2P/WebTorrent/torrent import | C U M; product decisions §4, W2→W6 note, P2P decision | Conflicting old “intentional difference” vs later import defer; browser P2P explicitly DEFER in phase 4. Retain separately from IPFS. Confirm import need; any future build requires consent/privacy/integrity and fallback proofs, not a hidden UI tab |
| SCP-03 E2EE attachments/private encrypted-blob replication | C U; Messaging v2 D7, IPFS §5.P | Current encrypted threads refuse attachments; plaintext DM bytes never mirror. Decide if required, then define opaque encrypted-blob/device recovery contract before UI/pinning. MSG-03 verifies current refusal, not feature completion |
| SCP-04 Advanced creator retention/watch-time/stream analytics and warehouse | C S U; W3 ANALY-01…05, older minimal-stats decision | Minimal totals/daily views do not fulfill retention curves. Enumerate required charts; prove event aggregation/privacy/deletion before UI. Dependency OPS-02, CRT-02 |
| SCP-05 Full live chat, slow mode/chat moderation/tips, DVR/live ladder/low latency and permanent scheduling | C U M; W4 LIVE-01…08 and config ledger §12 | RTMP/live CRUD is not full W4 acceptance. Check each requested feature against current routes and media plane; split chat transport/moderation from ingest/replay. Dependencies INT-01 and SCP-01 for money |
| SCP-06 Remote runners and cross-instance redundancy | C M U; W6 ADMIN-07/STOR/P2P, config ledger | Worker role/leases are not PeerTube remote-runner protocol or redundancy parity. Decide required topology; define task authentication, result promotion and failure ownership before remote execution |
| SCP-07 Plugins/themes/marketplace, OAuth2 provider applications and full i18n | C U M; W7 PLUG-01…03/USER-15/UX-03 | OAuth login is not an OAuth provider. Branding/custom CSS is not a plugin API. English UI/accessibility is not multilingual delivery. Inventory exact extension hooks/locales and compatibility expectations; retain each as separate future acceptance |
| SCP-08 Multi-CDN/content steering, shielding, CENC/DRM/KMS, multi-region | C U M; productionization phase 5, content-steering/CMAF decisions | Interfaces/floors exist; module completion not established. Steering is BUILD after generation/purge/measurement prerequisites. ClearKey test is not protected production video. Keep phase-5 remaining items gated, with real packager/license/failover proofs |
| SCP-09 Config-parity omissions and unfinished control-level plan items | C U S; config ledger §§1–16; both fix plans | Retain comment preapproval, auto-tag policies, Bluesky channel feed, real-time notification transport, auto-follow index/global index, live tuning, custom email HTML, original retention/podcast/audio settings, OAuth auto-redirect, unified moderation mobile queues, conversation search/unread rollup, messaging polish. Some are now implemented: inspect each before coding. Map requested behavior to ADM/CRT/SRC/MSG/INT rows; no bulk “N/A” closeout |
| SCP-10 Other explicit optional plan items | C U S M; both Optional buckets | Native apps, advanced recommendation engine, enterprise SSO, multi-region automation, AI moderation, full visual regression and extra locales remain listed. Search already has advanced ranking and OIDC already exists: avoid duplicate systems. Confirm concrete acceptance instead of treating “advanced” as a specification |

### Requirement-family crosswalk and maintenance gates

Readiness IDs are local to this record; identically named IDs in archived `FEATURE_VISION.md` have their own meanings. Its entire inventory remains a requirement source, not evidence that the archived implementations were ported. Family mapping: CORE → PUB/PLAY/CRT/SRC/SOC; USER → AUTH/ADM/SOC and SCP-07; UPLOAD → PUB/CRT/INT-02/04 and SCP-02; archived PLAY → PLAY/CRT/INT-03/QLT-02; LIVE → INT-01/SCP-05; FED → INT-05/06/PLAY-02/SCP-09; P2P → INT-07/08/SCP-02; STOR → STO/REC/SCP-06; MOD → ADM/SOC/SCP-09; ADMIN → ADM/MIG/OPS/SCP-06/07; PLUG → SCP-07; ANALY → CRT-02/SCP-04; PAY → SCP-01 (simple verified addresses separately INT-11); UX → QLT-02/SOC/MSG/ADM/SCP-07/09; DEVOPS → INS/REL/OPS/REC/QLT. This groups related acceptances without declaring every source endpoint or proposed UI shape required by default.

Preserve the architecture already present: one setup engine, one Compose-chain library, embedded append-only migrations, independent migration-ledger assertions, typed core-first API and generated clients, durable job/outbox boundaries, canonical-storage separation from delivery, and core-side visibility rehydration of search IDs. Maintenance risks are evidence/configuration drift across repositories, stale generated-contract assumptions in hand-written wrappers, duplicate operational assumptions, and broad “VERIFIED” labels hiding opt-in test omissions. A39/A40 must attach per-workflow evidence and retire contradictory notes, not add a new parallel implementation. Respect core/search `TWIN` contracts when shared helpers change; this audit did not certify every twin byte-for-byte. Avoid a broad refactor campaign before installation/media/migration acceptance.

## Dependency-ordered acceptance backlog

Each item below is a small **acceptance slice**, with implementation only if inspection/reproduction proves a gap. Split a slice further if it exceeds one repository's small-PR limit. Cross-repository behavior must use compatible additive contracts, with separately reviewable changes; never hand-edit generated clients/sqlc or overwrite migration history. Future CI edits and publishing require their own authorized implementation session.

| Order / ID | Owning repo(s) | Acceptance artifact and stopping criterion | Depends on |
|---|---|---|---|
| 1 A01 | M — verified, merged externally as #83 | Freeze one four-repo/release-image manifest in a disposable audit tree; path and generated-type drift checks pass for that set. Keep the resolved `/videos/resolve` release-skew case as a preflight regression; do not add a duplicate endpoint | None |
| 2 A02 | M — bounded verification PASS, draft review pending | Add a blank-server smoke harness for released bundle/CLI/images on supported Linux; install/re-run preserves config; port exposure and checksum failure assertions execute | A01 |
| 3 A03 | M C | Extend smoke only through setup→both clean ledgers→edge/ready/frontend; failing migration prevents up; assert default and selected TLS profile | A02 |
| 4 A04 | C U | Owner claim then ordinary user creation/login/session reload against this stack, with role/readback proof | A03 |
| 5 A06 | U C | Real browser channel/draft/upload persists original with correct owner/quota; synthetic audio+video fixture | A04 |
| 6 A07 | C U | Same video's transcode produces advertised HLS tree; actual browser decode/time/audio/seek and progressive fallback. Keep failure logs/job IDs | A06 |
| 7 A09 | M S C U | Start real search, force required-search test rather than skip; prove same uploaded ID travels outbox→index→UI result; revoke privacy/delete and test fallback/reconcile | A07 |
| 8 A08 | U C M | Same fixture works via canonical/legacy/share/embed links and password/private/download guards | A01, A07 |
| 9 A18 | C M | Source inventory and sanitized source+media fixture, read-only role, schema guard, dry-run/conflict/no-media report; document destination probe writes | A03; source input |
| 10 A19 | C U | Representative users/channels/roles/password login and image identity import; repeat proves idempotence and conflict policy | A18, A04 |
| 11 A20 | C, then U/M | First reproduce HLS-only copy-mode no-media; deliver one source-independent HLS-only video including audio. Separately add bounded resumable backfill for eligible imports; no blanket re-transcode assumed | A18, A07 |
| 12 A21 | C S U | Representative catalogue/follows/comments/playlists/metadata/counts round-trip and index; crash/resume/repeat adds no duplicates | A19, A20, A09 |
| 13 A22 | C M U | Explicit source data retention disposition; implement each required omitted family separately; blacklist/suspension regression stays green | A18; decisions |
| 14 A36 | M | Backup of rehearsal DB/config/sealing keys/media can be verified and recovered offsite; failed dump never accepted | A03, A07 |
| 15 A37 | M C S U | Replacement-host restore of that backup permits login, playback and reindex; record measured recovery time/data point | A36, A09 |
| 16 A23 | M C S U | Timed full+delta migration and final cutover/rollback checklist using the rehearsal; old domain/actor/link strategy verified | A21, A22, A37, A08 |
| 17 A05 | C U M | SMTP/TOTP/OIDC real-provider fixtures and recovery errors; split each auth capability into its own change if needed | A04; provider selection |
| 18 A10 | C U S | Resume/cancel/batch first; separate schedule/quarantine/replacement slices with job+UI persistence | A07, A09 |
| 19 A11 | U C | Studio metadata/media tools, then stats attribution; each control has backing read evidence | A07, A09 |
| 20 A12 | U C S | Sequential library/social/profile/archive/deletion acceptances using two/three actors; no suite-wide proxy for individual workflows | A04, A09 |
| 21 A13 | S C U | Multi-user suggestions/trending/recommendations/history fixture proves thresholds and opt-out | A09 |
| 22 A14 | U | Reproduce Composer limits; adopt already-shipped 100 MiB/30/document contract; multi-recipient proof, then remaining timeline/receipt controls | A04, MSG-01; scanner lane if selected |
| 23 A15 | C U | E2EE device/recovery/text round trip and attachment refusal, keeping future blob work separate | A04 |
| 24 A16 | C U S | Separate users/roles, approval, report/quarantine and mute/watched-word acceptance slices | A09, A12 |
| 25 A17 | U C M S | Admin settings/config changes observed in API/worker/search, then job/infra/GC failure displays | A09, A16 |
| 26 A24 | C M U | Repeat real media path on MinIO then selected provider; foreign-key GC refusal and keep proofs | A07, A18 |
| 27 A25 | C U | Storage movement with interrupt/resume/abort/checksums and GC interlock | A24, A36 |
| 28 A26 | M C U | Actual RTMP audiovisual ingest and viewer playback, then disconnect/replay. Separate chat/advanced live work if selected | A07; live decision |
| 29 A27 | C U M | Released-image URL/yt-dlp import, then one scheduled channel-sync item with dedupe and outage evidence | A07 |
| 30 A28 | C U M | Manual captions independently; Whisper and ClamAV each get a service-backed failure/success lane, never merely a flag-on test | A07; integration decisions |
| 31 A29 | C U M | Isolated two-instance ActivityPub follow/publish/comment/delete with blocked-server tests | A08, A16; AP decision |
| 32 A30 | C U | Separate ATProto login/link/cross-post test-provider and donation-verification slices | A05, A08; ATProto decision |
| 33 A31 | C U M | Public gateway/fallback and private swarm isolation separately, plus DM no-pin invariant | A07, A24; IPFS decision |
| 34 A32 | M C U | Selected bucket cross-origin browser presign/Range/expiry proof; keep proxy proof distinct | A24; bucket selection |
| 35 A33 | C then U/M | Same-source transcode generation correctness first; each remaining purge family as a bounded job/slice; real edge test last | A07, A16; CDN decision |
| 36 A34 | M C S | API+two-worker recovery/settings test; no host-local media assumption in multi-host topology | A17, A24 |
| 37 A35 | C S U M | Correlated request/job evidence and truthful playback-source QoE; retention and redaction checks | A09 |
| 38 A38 | M C S U | Previous-compatible release upgrade/app rollback and failed-migration recovery in disposable restored stack | A37 |
| 39 A39 | M C S U | Supported-toolchain, exact-manifest CI gates with explicit required test selection and zero silent skips; attach artifacts | A01 and all implemented slices |
| 40 A40 | U | Required-control inventory closes mobile/theme/keyboard/error/persistence gaps; link each UI acceptance to workflow row and backend evidence | Selected workflows |

**A01 and A02 are merged; bounded A03 runtime verification PASS ([implementation PR #85](https://github.com/yegamble/vidra/pull/85)). Next dependency-ready item: A04.** The original A01 recommendation was to add a compatible release-manifest/contract preflight in the meta-repo. The initial `node scripts/check-contract.mjs` failure already demonstrated why it is needed; the final frozen source set passes, so this item must not add a resolver. Its acceptance is a pinned four-repository **and image-digest** candidate that passes path/codegen validation without relying on moving `main`, and records release-asset/checksum availability. This is prerequisite to meaningful fresh-server testing; the next implementation is the small blank-server smoke harness A02, not a new product feature.

## Inputs still needed before dependent acceptance

1. Source PeerTube application/schema version, local/S3/HLS-only layout, same-domain vs new-domain plan, and whether the destination must be independent of source storage. A sanitized representative snapshot is needed for execution later, not credentials in this record.
2. Launch-required integrations and disposition of SCP-01…10. Pending an answer, local canonical storage/API proxy is only the minimal **test lane**, not a decision to remove S3/IPFS/live/federation or other requirements.
3. Recovery objectives (acceptable data loss and downtime), expected catalogue size/upload concurrency, and source-data retention requirements. Measure rehearsal results before setting a capacity/readiness PASS.

No launch, migration or recovery approval is requested in this audit. Stop at this record and the first item above; readiness remains open until the chosen workflows have current evidence.


## A01 implementation evidence — 2026-09-05

**Status: verification PASS for the bounded A01 acceptance; [PR #83](https://github.com/yegamble/vidra/pull/83) was merged externally on 2026-09-05 as `491a0cb790e1330b5f1a92a7547f7ef49a1daa59`. This agent did not merge it.**
Single agent. Implementation revision `183f729c1c5e579e9ed78361338173b269f4a284`
adds the read-only [preflight](../deploy/release-preflight.py), eight regression
tests and [operator procedure](../deploy/README.md#release-readiness-preflight-a01).
The subsequent documentation commit records this evidence. No component source,
workflow, production pin, migration, API, or generated client was changed.

Observable success: freeze four release commits and three immutable image digests
in a disposable tree; match image platform/revision/source labels; download the
bundle and Linux CLI and verify SHA256SUMS plus bundle source provenance; pass
path and byte-for-byte generated-type checks; explicitly reject resolver skew.
A01 is a source/asset compatibility check, not certification of the full REL-01
runtime/version-probe acceptance or the latest main-branch feature set.

The durable [v0.6.2 linux/amd64 candidate manifest](evidence/a01-v0.6.2-linux-amd64.json)
records exact four SHAs, three OCI digests, three asset URLs/hashes, tool versions,
and the verifier's SHA256. All image labels match their selected source commits.
The bundle's `meta_commit` and `core_commit` match the same candidate. Selected
platform: **linux/amd64 only**. Registry labels are provenance correspondence,
not independent reproducible-build proof. The release was read, never published.

| Verification | Result / exact boundary |
|---|---|
| TDD red baseline | `python3 -m unittest discover -s tests -p release_preflight_test.py`: exit 1 before implementation (missing module); then four focused tests passed, expanded to eight |
| Final focused tests | Same command: exit 0, **8 passed / 0 failed / 0 skipped**. Covers digest/platform/revision refusal, checksum missing/duplicate/corrupt refusal, resolver removal boundaries, explicit asset names, failed dependency status, preservation of existing evidence, command failure and unsupported Node rejection |
| Real preflight | `PATH=/opt/homebrew/opt/node@24/bin:$PATH python3 deploy/release-preflight.py --tag v0.6.2 --out /tmp/vidra-a01-v062-verified > /tmp/vidra-a01-v062-verified.log 2>&1`: **exit 0**, manifest PASS; four check groups PASS / zero skips. The host's `node@24` path resolves to **Node v25.9.0**, satisfying >=24; npm 11.12.1, Python 3.9, buildx 0.32.1. GitHub, GHCR and npm were accessed with approved network permissions |
| Frozen frontend path guard | **230 backend paths / 202 referenced paths**, exit 0. The released guard checks paths only; do not infer method coverage from it |
| Generated types | Frozen `npm ci --ignore-scripts --no-audit --no-fund`, then `node scripts/codegen.mjs` with explicit frozen `OPENAPI_PATH`: exits 0; output byte-identical to committed generated.ts |
| Resolver regression | Same released guard in separate scratch tree: explicit resolver probe with compatible spec exits 0; spec without `/api/v1/videos/resolve` exits **1**, specifically reporting that missing path. This retains the known skew failure mode even when the selected old frontend does not yet call the resolver |
| Supplemental method guard | Checker frozen from frontend audit revision `cbc11451e6fc804e76a2a73e693e2f9842178bba:scripts/check-contract.mjs`, copied beside the candidate's unmodified `lib/api` in `/tmp/vidra-a01-method-check`; `OPENAPI_PATH=/tmp/vidra-a01-v062/source/vidra-core/api/openapi.yaml node scripts/check-contract.mjs`: **exit 0**, 230 paths / 302 operations / 202 client paths / 258 call sites |
| Meta required local gates | `bash -n` and `shellcheck -x` on all 12 existing shell scripts: exit 0; Python entrypoint is not Bash. `docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file /tmp/vidra-a01-check.env config -q`: exit 0, production template with dummy required secrets |
| Existing installer regression | `bash tests/install_test.sh`: exit 0, all assertions passed, zero skips; this is fixture coverage, not blank-server proof |
| Integration boundary | Actual remote tags, registry manifests/configs, downloaded release bytes, lockfile installation and code generation executed. Browser/search/transcoding/database suites are not needed for this read-only A01 behavior; their workflow rows remain UNVERIFIED. Remote meta CI on `1c5b9b6` passed; details below |

Remote required gates: [meta CI run 33962973913](https://github.com/yegamble/vidra/actions/runs/33962973913) on `1c5b9b6` **PASS** — validate 48s, bundle 15s, production-mode boot 2m1s (including readiness and both migration one-shots); GitGuardian also passed. The final documentation-only checkpoint adds these links; it does not change the verified implementation. This existing CI lane does not certify real transcoding/search/browser acceptance (F04 still applies).

Local raw evidence: `/tmp/vidra-a01-v062-verified.log`, the matching output tree
(including `bundle-provenance.txt`), `/tmp/vidra-a01-unit.log`,
`/tmp/vidra-a01-method-check.log`, `/tmp/vidra-a01-install-tests.log`.
Do not commit scratch downloads or node_modules. Earlier exploratory preflight
runs used other scratch directories; only the verifier hash in the linked final
manifest identifies the accepted run.

**Unrelated finding retained:** the template recommends v0.6.3, but
`gh release view v0.6.3 -R yegamble/vidra-core --json assets,tagName` returned
`release not found` (exit 1); `gh release list` returned v0.6.2 as latest.
No release or pin was changed to resolve this. v0.6.2 is a compatible rehearsal
candidate; it predates the resolver/short-code programme. Re-freeze a later
published candidate before claiming those newer feature acceptances. The
implementation cannot make an unpublished v0.6.3 releasable in this session.

**Next action:** review the A01 draft PR, then implement A02's disposable Linux
blank-server harness using this manifest's exact sources/digests/assets. Carry
v0.6.3 availability and later resolver feature coverage as explicit blockers to
promoting a newer release candidate. No merged-branch leftovers were present;
no nested checkout or unrelated branch was changed. No merge or deployment is
authorized in this session.


## A02 implementation evidence — 2026-09-05

**Status: bounded A02 verification PASS; [draft PR #84](https://github.com/yegamble/vidra/pull/84) open — awaiting review/merge.**
One agent. Harness revision `910fa7d0f89524399197f2482a6a018bddf18d06`, based on
merged A01 `491a0cb`; subsequent documentation commit records the evidence.
The [launcher](../tests/blank-server-smoke.sh), [guest assertions](../tests/blank_server_smoke.py)
and [procedure](../deploy/README.md#blank-server-installer-smoke-a02) create a
new Multipass VM, never select an existing host, and fail closed on missing
prerequisites or evidence. No production scripts, workflows, pins, API, SQL,
migrations or component code changed.

Observable success criteria: real released installer on blank supported Linux;
corrupted bundle and CLI rejected before promotion; verified installation and
native CLI execution; generated configuration preserved on reinstall; explicit
production Compose port assertions; all three A01 digest-pinned images pulled
and inspected. Runtime startup is deliberately the dependent A03 boundary.

The [durable sanitized result](evidence/a02-ubuntu24.04-arm64.json) records the
candidate hash, installer and guest/launcher hashes, exact harness revision,
Ubuntu base-image hash, native CLI identity, Docker/Compose versions and port
bindings. It links by hash to the unchanged [A01 candidate](evidence/a01-v0.6.2-linux-amd64.json).

| Verification | Result and limits |
|---|---|
| TDD red baseline | `python3 -m unittest discover -s tests -p blank_server_smoke_test.py`: exit 1 before helper implementation (missing module) |
| Focused assertions | `python3 -m unittest discover -s tests -p '*_test.py'`: exit 0, **14 passed / 0 failed / 0 skipped** (6 A02, 8 A01). Covers incomplete candidate, mutable digest, exact/no datastore ports, empty profile render, native checksum selection and refusal to overwrite evidence before VM operations |
| Real blank-host smoke | `bash tests/blank-server-smoke.sh docs/evidence/a01-v0.6.2-linux-amd64.json /tmp/vidra-a02-smoke-r1`: **exit 0, 7 acceptance groups PASS / 0 failed / 0 skipped**; both exported status files PASS |
| Environment | New Ubuntu **24.04.4 LTS aarch64** VM `vidra-a02-20260905120542-66513`, 2 CPUs / 4 GiB / 20 GiB, no host mounts, no Docker, Vidra CLI or install tree at start. Multipass 1.16.1 on macOS ARM64. Installer actually installed Docker **29.8.0** and Compose **5.5.1**; daemon active and enabled assertions passed |
| Real checksum rejection and recovery | Installer exits **1** for bundle corruption, then **1** for CLI corruption, specifically CHECKSUM MISMATCH; fault wrapper appends one byte after each actual curl transfer and preserves HTTP/exit behavior. No corrupt bundle marker, no unverified CLI, no env generated. Unmodified transport install and reinstall each exit **0** |
| Released bundle and native CLI | Installer fetched at frozen meta `2a584f0`; bundle meta/core/tag match A01. Installed ARM64 CLI SHA256 `1fb66a1e54ef8954a0f596c9278f3ff41dd353e762850dfd81db7f3d4799e11e` matches native entry in the SHA256SUMS file **whose complete hash A01 pinned**. `vidra help` exits 0; the CLI has no version subcommand, so no version output is fabricated |
| Real persisted configuration | Released `vidra setup --non-interactive --domain http://video.test --instance-name "A02 disposable test" --registration closed --tls-mode plain-http --storage local --release-tag v0.6.2 --template env/production.env.example` exits 0. After reinstall, env, rendered Caddyfile and CLI bytes are identical; `vidra setup --check env/production.env` exits 0. Local test secrets never exported |
| Port and release assertions | Installed bundle's base+prod Compose rendered with explicit core/frontend profiles and generated env: postgres/redis/search have no published ports; API 127.0.0.1:8080, frontend 127.0.0.1:3000. All five api/migrate/frontend/search/search-migrate image tags equal the selected release. This is actual Linux Compose execution, **not runtime socket/edge proof** |
| Real image availability | Core, frontend and search each pulled with `docker pull --platform linux/amd64 <A01 digest reference>`; inspected RepoDigests, OS/architecture and OCI source revision match A01. `docker ps -aq` is empty. ARM64-host success here proves pulls, **not amd64 execution** |
| Meta required local gates | `bash -n` and `shellcheck -x` on all 13 shell scripts, existing `bash tests/install_test.sh`, and `docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file /tmp/vidra-a02-check.env config -q` with dummy required secrets: exits 0. `git diff --check`: exit 0 |
| Runtime suites | Browser/search-service/media-processing/database suites not run: A02 changes only the installer rehearsal harness and starts no application. A03 and dependent workflow rows remain UNVERIFIED; no missing runtime prerequisite was skipped and called PASS |

Local evidence: `/tmp/vidra-a02-smoke-r1/{result.json,status.txt,vm.json,guest-progress.log}`,
`/tmp/vidra-a02-unit.log`, `/tmp/vidra-a02-installer-unit.log`.
Raw command output and generated test secrets remain root-only at
`/root/vidra-a02-private` and in `/opt/vidra` inside the stopped VM. The launcher
keeps the VM for diagnosis/follow-on work and never deletes an unrelated instance.
The pre-existing `test-runner` VM was not used or changed.

**Blockers/next action:** review this small A02 draft, then implement A03 through
setup, clean migration ledgers, ready/edge/frontend, and migration-failure
abort. A03 requires an amd64 Linux host for the pinned candidate, or explicitly
verified emulation / a separately preflighted native candidate. Do not count an
ARM64 pull as execution. No new release, image publication or production deploy
is authorized. The earlier v0.6.3 availability finding and full INS-01 git
fallback/interrupted-transfer/installation workflow remain tracked, not silently
closed. The old local `codex/a01-release-preflight` branch remains for triage:
its PR was squash-merged, so `git branch --merged origin/main` does not include
it; no force deletion was performed.

A02 required remote gates: [meta CI run 33965465521](https://github.com/yegamble/vidra/actions/runs/33965465521) on `5dedb2e` **PASS** — validate 55s, bundle 14s, boot 1m55s; GitGuardian also passed. This existing CI source-build lane is separate from the frozen release/VM evidence and does not promote A03. The final documentation-only checkpoint adds the PR and CI links.


## A03 implementation checkpoint — 2026-09-05

**Status: open — awaiting runtime verification and merge of [PR #85](https://github.com/yegamble/vidra/pull/85).** The current user instruction authorizes the A03–A40 loop and merging green scoped PRs, superseding the earlier attachment's draft-only restriction. A02 PR #84 was merged as `d7c2dbd`; its remote/local branch was removed. Component checkouts remain unchanged and clean. The old A01 local branch was subsequently removed after GitHub confirmed PR #83 merged exactly its head `d5d35c1` and `git diff --quiet` proved its tree identical to merge `491a0cb`; this preserved all work despite squash ancestry.

Observable A03 success: setup → exact clean core/search ledgers → actual loopback app ports and closed datastore ports → ready/edge/frontend and runtime API origin; default edge render and selected internal-CA TLS execution; real dirty core/search migrations each abort before startup with serving IDs/start times/restarts unchanged; recovery deploy succeeds.

The [runtime harness](../tests/runtime_smoke.py) and [launcher](../tests/runtime-smoke.sh) use the frozen A01 images and a disposable A02 VM. Only the disposable bundle copy receives immutable image references/platforms and the deploy script under test; both original and tested script hashes are recorded. No application image, production pin, migration, workflow or component code changes.

**Reproduced defect:** run `/tmp/vidra-a03-r2` began with zero containers/volumes and executed all three amd64 images on ARM64 Ubuntu with Ubuntu QEMU binfmt (`POF`). Released deploy hash `ad97c6df35a3ac3174c581aaef8f07cbf907b5790a781093cc3e433c4addab5a` passed the complete plain-HTTP group. Setup then atomically replaced `Caddyfile.local` for `https://secure.video.test`, but the running Caddy file mount still contained `http://video.test`. Reload returned success while HTTPS failed; deploy exited 1 at its edge deadline. [Sanitized negative result](evidence/a03-stale-caddy-mount-failure.json). Transient SSH delays were observation failures; the original run was allowed to reach its own terminal failure without restarting it.

Fix revision `95c2599` compares mounted/generated content inside the existing reload retry loop and recreates only Caddy with `--no-build --no-deps --force-recreate` when stale. Unchanged mounts retain graceful reload; recreation failure is fatal. Dump/pull/migration/up ordering, Compose version check, bundle/checkout pinning and ledger guards are unchanged.

Verification checkpoint: two Caddy regression assertions failed before the fix; `python3 -m unittest discover -s tests -p '*_test.py'` now exits 0 (**20 passed / 0 failed / 0 skipped**). `bash -n` and shellcheck pass on touched scripts; production Compose `config -q` with `/tmp/vidra-a02-check.env` dummy values passes; existing installer regression exits 0. Full fixed-runtime run is pending on a newly launched blank VM (`/tmp/vidra-a03-fresh-a02-r3`), preserving the negative run. Do not promote A03 based on these unit/CI checks.

Next action: finish the fresh A02 preparation, install guest QEMU, run the fixed A03 harness through both TLS modes and both injected failures, attach sanitized evidence, then merge green PR #85. A04 needs a fresh owner-claim browser path: the existing backed setup claims the owner before its wizard spec, which normally skips that happy path; that suite alone cannot certify A04.


### A03 final runtime evidence — 2026-09-05

**Bounded A03 acceptance PASS.** [PR #85](https://github.com/yegamble/vidra/pull/85) tracks delivery and its current merge state. Tested checkout
`8668723852968b668ff664b417772531a9ca70ce`; deployment fix `95c2599`.
The [passing runtime result](evidence/a03-runtime-pass.json) records the exact
helper, candidate and original/fixed deploy hashes. They match the files in
this checkout. [Fresh-host result](evidence/a03-fresh-host.json) records the
successful A02 prerequisite rerun on Ubuntu 24.04.4 ARM64 VM
`vidra-a02-20260905123822-89250` (2 CPUs, 4 GiB, 20 GiB, no host mounts).

| Check | Executed evidence |
|---|---|
| Fresh runtime | Zero containers and zero volumes before startup; all three frozen amd64 image shells execute via Ubuntu QEMU binfmt POF, followed by real API/search/frontend execution |
| Default render | ACME edge profile present; exact loopback/no-datastore-port assertions; both migrators have no mounts and use their service image |
| Plain HTTP | Real setup/check/deploy, clean core 125 and search 16 ledgers, actual Docker port bindings, edge health/ready/frontend HTML and runtime API origin all PASS |
| Internal TLS transition | Setup changes origin to `https://secure.video.test`; deploy logs stale mount detection, recreates only Caddy and successfully reloads. Edge health/ready/frontend/runtime config PASS with curl trusting the exported lab CA root (no insecure flag in acceptance probes). Frontend runtime origin follows the new domain |
| Core dirty ledger | Real SQL injection followed by real deployed migrator: deploy exits nonzero at CORE MIGRATION FAILED, never reaches 4/6 startup; all six serving/datastore container IDs, start timestamps and restart counts unchanged. Injected dirty bit remains true until test cleanup |
| Search dirty ledger | Same independent procedure for vidra_search_migrations: SEARCH MIGRATION FAILED, no startup or container changes, dirty bit retained until cleanup |
| Recovery | Only synthetic injected dirty bits cleared; ordinary deploy succeeds and independent SQL reads show exactly core `125|f`, search `16|f` |
| Local required gates | 20 Python tests PASS, zero skips; bash syntax and shellcheck on deploy/deploy.sh and tests/runtime-smoke.sh PASS; installer regression PASS; production Compose config -q with dummy required secrets PASS; diff whitespace check PASS |
| CI on tested code | [Run 33966768372](https://github.com/yegamble/vidra/actions/runs/33966768372): validate 49s, bundle 12s, boot 2m2s PASS; GitGuardian PASS |

Commands: `bash tests/blank-server-smoke.sh docs/evidence/a01-v0.6.2-linux-amd64.json /tmp/vidra-a03-fresh-a02-r3`, then guest Ubuntu `apt-get install -y qemu-user-static`, then `bash tests/runtime-smoke.sh /tmp/vidra-a03-fresh-a02-r3 docs/evidence/a01-v0.6.2-linux-amd64.json /tmp/vidra-a03-r3`. Launcher exit 0 and exported status PASS; VM stopped successfully. Seven runtime acceptance groups PASS / zero failed / zero skipped. Private logs and generated secrets remain in `/home/ubuntu/vidra-a03-20260905124354-92490/private` inside the retained VM. No production deployment or release publication occurred.

This proves the bounded A03 row, not every INS-02/04/05 scenario: public ACME,
external TLS, web setup, lock contention, failed-dump injection and browser/media
workflows remain individually unverified. Emulation is functional evidence,
not a capacity claim. A changed Caddyfile now causes a brief Caddy-only restart;
unchanged configurations keep graceful reload. A04 is next, with a dedicated
unclaimed browser fixture rather than the existing normally-skipped wizard test.


## A04 owner/basic-session slice — 2026-09-05

**Slice verification PASS; A04 remains open for the remaining AUTH-02 cases.** [PR #86](https://github.com/yegamble/vidra/pull/86) tracks this slice and its delivery state.
The previous turn merged A03 as `386a179` ([PR #85](https://github.com/yegamble/vidra/pull/85)).
This slice adds the [browser harness](../tests/owner-auth-smoke.mjs), its three
assertion tests and an [isolated concurrent-claim harness](../tests/owner_claim_race.py).
No application code, contract, migration, workflow, dependency or release pin changed.

Observable result: a real unclaimed production-mode A03 stack refuses signup
while registration is open; restart rotates its random boot token; wrong/old
claims create no users; the browser claims the owner and reaches the signed-in
confirmation. Persisted API/SQL reads prove admin role, ordinary signup yields
user role and admin refusal, two hard reloads rotate the protected refresh
cookie, logout stays logged out, and fresh browser login succeeds. A separate
new database/API proves exactly one winner when two valid owner claims race.

[Browser result](evidence/a04-owner-browser.json) records the exact helper hash,
A03 evidence hash, VM/project, Node **v25.9.0**, and Chromium **151.0.7922.34**.
It ran from implementation `cc56f65` using the sibling's installed Playwright
against the frozen A03 release images, not a development frontend or mocked API.
The [race result](evidence/a04-owner-race.json) records the pinned core image and
helper hash; race helper/procedure committed as `453f30e`.

| Verification | Result and boundary |
|---|---|
| Host/safety | Retained disposable Ubuntu ARM64 VM `vidra-a02-20260905123822-89250`, A03 project `vidra-a03-20260905124354-92490`; guard requires zero users before browser bootstrap and preserves existing output directories. Own synthetic failed-run DB was backed up privately before restoring the known preclaim backup; no operator data touched |
| Browser execution | `node tests/owner-auth-smoke.mjs /tmp/vidra-a03-r3 /tmp/vidra-a04-r3`: exit **0**, five groups PASS / zero failures/skips. Dedicated Chromium contexts map secure.video.test to the VM; no route interception. Contexts ignore the lab certificate; A03 separately proved CA verification |
| Preclaim/rotation | With registration explicitly open via released CLI setup and normal deploy, signup returns 403 owner_claim_required. API restart produces a distinct boot token; old and invalid tokens return 403 owner_claim_invalid. SQL still has zero users |
| Owner | Actual setup form submission returns 201; UI shows Your server is ready and signs in. Auth response and GET auth/me prove owner username/admin role; admin/system is 200, owner_claim_pending false, SQL exactly one admin; spent-token claim returns 403 |
| Ordinary actor | Browser signup returns 201/user role; SQL exactly one ordinary user; its bearer token receives 403 from admin/system |
| Sessions | Two hard reloads each perform a real 200 refresh with correct user role and visible signed-in menu. Cookie is Secure/httpOnly and no refresh token appears in cookie-mode response bodies. Browser logout clears the cookie and remains signed out after reload; new form login with original credentials returns 200 and the persisted user |
| Rejections | Wrong-password login returns 401 with no session tokens. Admin closes registration through the actual settings API; signup returns 403; SQL still contains exactly the two created accounts |
| Race | New DB `a04race1788613956`, same digest-pinned core migrator/API with workers disabled. Two request threads leave a barrier together: one 201, one 403 owner_claim_invalid; SQL exactly one user/admin, spent token refused. Exit **0**, one group PASS; test API stopped, separate DB retained |
| Local gates | TDD first failed on missing harness/contract validator. Final Node assertion tests: **3 passed / 0 failed / 0 skipped**. Existing Python suite: **20 passed**, zero skips. New Python helper compiles; production Compose config -q with dummy secrets and git diff --check pass. No shell scripts touched |
| Visual check | Signed-in ordinary-user home screenshot inspected; real header/account menu and library/studio navigation rendered. Screenshot remains private; it does not replace the API/SQL assertions |

Exploratory failures were harness failures, not suppressed product defects:
closed registration correctly returned generic forbidden before the owner gate;
the fixture was changed to open registration before testing that gate. The
browser claim then succeeded but harness readback used access_token instead of
the generated contract's token field; fixed and covered by a contract assertion.
Docker's emulation warning preceded the race container ID; parser corrected,
created test containers stopped, and the complete race rerun passed.

Raw private evidence: `/tmp/vidra-a04-r{1,2,3}` on the workstation,
`/root/vidra-a04-race-r{1,2,3}` inside the VM. The failed-claim fixture is retained
as `/home/ubuntu/vidra-a03-20260905124354-92490/private/a04-failed-run-preserved.dump`.
Credentials remain in private-accounts.json (mode 0600 under mode 0700 output),
never in committed results. Primary fixture ends with owner + ordinary user,
registration closed; race DBs are separate. No production deployment occurred.

**Next action: finish A04's remaining AUTH-02 approval/accept/reject, explicit
expiry/revocation and multi-tab cases using these retained actors and fresh
pending actors, then assess the full row before advancing to A06.** Provider
signup paths still need their A05 provider fixtures. Neither this slice nor a
green CI lane closes those unexecuted requirements.
