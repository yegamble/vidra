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
| AUTH-05 Profile/privacy, email/password changes, deactivation/deletion and account archive | C U S | Backed profile-edit/deactivate/delete-account/account-export; core account and search deletion hooks; live evidence `a12-profile-archive` (profile/privacy + archive round trip), `a12-deletion` (deactivation/deletion with content, DM retention, media cleanup, search hook), `a12-password-change` (password change with re-verification, on session-bound access tokens) and `a12-email-change` (two-step email change with re-verification over real SMTP) | PASS (candidate; unmerged) | Mutate profile/unlisted/email/password with re-verification, export and import supported archive; delete/deactivate with content, sessions, follows and search history; verify recipient DM retention policy and media cleanup | AUTH-02, SRC-02 → A12 |
| PUB-01 Create channel and draft; upload a real file within quota | C U M | `internal/video`, upload routes; backed upload/studio/channel-management | UNVERIFIED | Browser-create channel/draft; upload generated audiovisual clip; inspect original metadata, owner quota accounting and durable state; deny nonowner/overquota/invalid input | AUTH-02 → A06 |
| PUB-02 Resumable upload, cancel, draft recovery and batch publishing | C U | W2 plans; backed upload-draft-recovery/upload-cancel/upload-batch | PASS (candidate; unmerged) | Interrupt network and restart service between chunks; resume without duplicate files/charges; recover draft on another session; cancel cleanup; partial batch failure retained | PUB-01 → A10 |
| PUB-03 Transcode durable jobs into playable CMAF/HLS ladder | C M U | `internal/media/hls.go`, CMAF packager, transcode jobs; backed hls-playback | UNVERIFIED | Real ffmpeg job: source→processing→ready; fetch advertised master, audio/video variants, init/segments; decode audio and video; retry crash without duplicate promotion | PUB-01 → A07 |
| PUB-04 Schedule/quarantine/privacy gates survive processing and replacement | C U S | Schedule/quarantine backed specs; replace handlers; instance gates | PASS (candidate; unmerged) | Publish-after-transcode and schedule, quarantine approve/reject, replacement preserving URL/metadata; no premature discovery; concurrent old/new playback; failed replacement retains prior usable generation | PUB-03, SRC-02 → A10 |
| PLAY-01 Watch, seek, quality, speed, resume, PiP/theater and mobile/native playback | C U | `components/player`, HLS hook, backed hls-playback/player-settings/history | UNVERIFIED | Browser actual currentTime advance and audible track, seek, quality change and saved preferences; Chromium plus native-HLS Safari on representative ladder; original fallback when appropriate | PUB-03 → A07 |
| PLAY-02 Canonical/legacy links, sharing, embeds, oEmbed/feed/sitemap | C U M | F01 resolved at final snapshot; resolver and imported UUID mapping now present; no actual browser route proof | UNVERIFIED | Run path guard first; follow canonical and old PeerTube/UUID/short links through edge with timestamps; verify privacy/password unlock and embed origin rules, metadata and downloadable file | REL-01, PLAY-01 → A01 then A08 |
| PLAY-03 Private, unlisted, password, embed and download revocation | C U S | Backed video-password/embed; HTTP media auth and purge helpers | UNVERIFIED | Copy all manifest/segment/original/caption/storyboard URLs to unauthorized session; enforce token expiry, unlisted discovery exclusion and changed download policy; test account-unlisted transition | PLAY-01, SRC-02 → A08 |
| CRT-01 Studio edit/delete/taxonomy/tags/thumbnails/chapters/storyboards | C U S | Studio/channel/taxonomy/tag/upload-thumbnail backed specs; core chapters and storyboard handlers | UNVERIFIED | Edit every supported field and reorder chapters; real frame extraction and hover sprite; fresh detail/UI fetch; delete and verify bytes/discovery vanish; source replacement retains identity | PUB-03, SRC-02 → A11 |
| CRT-02 Creator/channel/video statistics are accurate and scoped | C U | Core stats/view-day rollups; user HEAD fixes previous-channel totals | UNVERIFIED | Two creators/channels; known views/ratings/comments; dedupe; switch channels during requests; unauthorized stats refusal; imported totals distinct from absent daily history | PLAY-01 → A11 |
| SRC-01 Real outbox→search indexing→visible search result | M C S U | Core `searchevents`, search client/drainers; S `/internal/v1/events`; F04 | UNVERIFIED | Finish real upload/transcode, inspect outbox acknowledgement + indexed ID, issue UI query and click result; prove service used rather than SQL fallback; no seeded index substitution | PUB-03, REL-01 → A09 |
| SRC-02 Search privacy, retries, deletion and degraded fallback | C S U | Core search hydration predicate; S idempotent events/privacy/retention; health probe | UNVERIFIED | Duplicate/reorder/retry events; private/quarantine/unlisted/delete/block transitions; stop search and retain safe SQL fallback; restart/reconcile and verify history/personalization opt-out | SRC-01 → A09 |
| SRC-03 Discovery, suggestions, trending, recommendations and history controls | C S U | S APIs/worker jobs; the three user search-discovery controls are opt-OUT (all three default true); ranked IDs rehydrated in core; live evidence `a13-suggest-trending`, `a13-recommendations-history`, `a13-optout-attribution` | PASS (candidate; unmerged) | Seed synthetic multi-user engagement above privacy thresholds; check filters/paging/ranking, related/home cards and suggestion bans; history delete survives reload/reconcile; opting out stops attributed collection, not only personalized serving | SRC-02 → A13 |
| SOC-01 Follow/subscriptions, saves, playlists and watch history | C U S | Backed subscribe/subscriptions/save/playlists/history/continue-watching | UNVERIFIED | Two accounts; follow then publish notification/feed; unfollow; playlist CRUD/privacy/order/cover and playback continuation; history disable/clear and watch-later persistence | PUB-03, AUTH-02 → A12 |
| SOC-02 Comments/replies/ratings, mentions, reports and notification preferences | C U | Backed comments/comment-replies/rating/report/notifications/notification-prefs; live three-actor evidence `a12-social-notifications`, `a12-mute-block`, `a12-ratings-reports-prefs` (mentions are not a shipped capability — recorded, not accepted) | PASS (candidate; unmerged) | Three actors: reply attribution, intended recipient notification, deleted/tombstoned parent, blocked/muted content; refresh unread counts/preferences and resolve report | SOC-01 → A12 |
| MSG-01 Plaintext DM timeline, retry/read receipts/delete/report and attachments | C U | `internal/messaging`; backed messaging/message-compose; frontend P-MSG2 unfinished boxes | UNVERIFIED | Two browser contexts send/poll/read, prepend history without jumps/duplicates, retry once, receipts opt-out, delete/report; recipient downloads attachment, third party denied | AUTH-02 → A14 |
| MSG-02 Approved 100 MiB / 30-file and office-document attachment behavior | C U | F03; product decision §14a vs Composer limits | FAIL | Boundary values, 31st file and oversize refusal; document kind renders; multi-file recipient API/UI readback; configured scanner failure semantics | MSG-01, INT-04 → A14 |
| MSG-03 E2EE device/session lifecycle and honest unsupported attachments | C U | `internal/e2ee`, Olm client; backed e2ee; D7 defers encrypted blobs; live two-device evidence `a15-e2ee` (real Olm in two Chromium profiles, 290-column plaintext scan, unlink cascade, attachment refusal, enumerated IPFS block store) | PASS (candidate; unmerged) | Two devices establish encryption; inspect server stores ciphertext only; restart/recover/unlink as supported; plain attachment affordance absent and API rejection; no IPFS pin for DM bytes | AUTH-02 → A15; encrypted blobs remain SCP-03 |
| ADM-01 Users/roles/quotas/suspensions/signup approval with lockout guards | C U | Backed admin-users/registration-approval; `requireRole` and self guards; live evidence `a16-users-roles` (three-role matrix over 43 admin-only + 24 staff routes, role change biting a LIVE session, real over/under-quota uploads, bypass_quarantine proven against the quarantine gate, deactivate/reactivate/delete with the tombstone made irreversible, approval queue and audit rows) | PASS (candidate; unmerged) | Admin vs moderator vs user; quotas, verified/bypass flags, deactivate/reactivate, reject self-demotion; session revocation and audit evidence | AUTH-02 → A16; no last-admin or owner guard ships (recorded) |
| ADM-02 Reports, video blocks/quarantine, mutes, watched words and appeals/context | C U S | Backed moderation/admin-comments/blocked-videos/watched-word-matches/instance-mutes; live evidence `a16-quarantine-blocks` (236 assertions, per-surface table for quarantine/block/reject with vidra-search readbacks, oEmbed leak and empty DM report fixed), `a16-moderation-hardening` (stale watch-page cache, rejection note persisted, creator told of a block) and `a16-mutes-watched-words` (125 assertions: per-surface mute table with search-service rails, instance mutes proven against real remote rows, watched-word semantics, and a blocked account's repeatable follow notification fixed) | PASS (candidate; unmerged) | Report video/comment/message; staff review and note; owner notifications; ban/block/unblock and affected feeds/search; unauthorized and bulk behavior inventoried explicitly | SRC-02, SOC-02 → A16; remote/federated content is A29-owned; muted accounts still visible on their own channel page and in autosuggest (recorded) |
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

**A01 and A02 are merged; bounded A03 runtime verification PASS ([implementation PR #85](https://github.com/yegamble/vidra/pull/85)). A07 now has passing runtime evidence with the frontend fix (see final A07 evidence below); A09 now has passing runtime evidence (see below); A08 now has bounded passing runtime evidence (see final A08 media evidence and linked delivery PRs).** The original A01 recommendation was to add a compatible release-manifest/contract preflight in the meta-repo. The initial `node scripts/check-contract.mjs` failure already demonstrated why it is needed; the final frozen source set passes, so this item must not add a resolver. Its acceptance is a pinned four-repository **and image-digest** candidate that passes path/codegen validation without relying on moving `main`, and records release-asset/checksum availability. This is prerequisite to meaningful fresh-server testing; the next implementation is the small blank-server smoke harness A02, not a new product feature.

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


## A04 registration/session policies — 2026-09-05

**Bounded A04 verification PASS; next dependency-ready item A06.** The owner/basic
slice merged as `7e3273a` ([meta #86](https://github.com/yegamble/vidra/pull/86)).
This continuation pairs [frontend #145](https://github.com/yegamble/vidra-user/pull/145)
with [meta #87](https://github.com/yegamble/vidra/pull/87). Frontend #145 merged
first as `13072dc6cadb6487a3ad68e66971ff279d7aae3d` after all CI lanes passed.
It completes AUTH-02's password/session scenarios on the selected HTTPS Chromium
stack. AUTH-01's provider-specific preclaim paths remain unverified until A05;
the broader auth rows above are not blanket certifications of those paths.

The real browser exposed a product defect: two tabs can rotate the same shared
refresh cookie concurrently, causing a 401 and lost session. Frontend revision
`8d4a8d856ccdbf4c839b30cf10bb0b2c5b34d6da` serializes cookie refresh across tabs
with one same-origin Web Lock, retaining the existing per-tab in-flight promise
and backend replay policy. Environments without Web Locks retain the previous
fallback; this run certifies secure Chromium, not that fallback. Logout proof
checks the other tab after reload, not immediate broadcast-driven UI updates.

| Verification | Result and evidence |
|---|---|
| Reproduction | [Original-image paced run](evidence/a04-policies-before.json): approval and logout-all PASS, simultaneous refresh pair **200/401**, concurrent-tabs FAIL. Earlier unpaced attempts also hit real rate limits; the decisive run paces cases 62 seconds apart without disabling limits |
| Fixed browser | [Final complete run](evidence/a04-policies-after.json): **3 groups PASS**, no skipped groups. Two pending signups receive 202 and create no users; admin browser approves one/rejects one, SQL verifies both dispositions, approved login succeeds and rejected login is 401. Three pairs of hard reloads yield **six 200 refreshes** and signed-in menus in both tabs |
| Logout/revoke | Same final run: browser logout 204 clears shared refresh cookie; other-tab reload is signed out and missing-cookie refresh returns the existing **422 unprocessable_entity / refresh_token** validation error. Two independent token sessions both return 401 on refresh after logout-all 204 |
| Expiry | [Elapsed-time test](evidence/a04-expiry.json): **3 groups PASS**. Normal disposable-stack deploy temporarily sets access/refresh TTLs to 6s/18s; after 8.5s old access is 401, refresh rotates and new access is 200; after another 11.5s untouched refresh is 401. Finally normal deploy restores and verifies **15m/720h** |
| Fixture | [Exact provenance](evidence/a04-frontend-fixture.json): frozen released frontend source plus only the production client patch, built locally for ARM64. Core/search remain frozen A01 images. This avoids combining current frontend main with an older API. No new release was published; the original release image does not contain this fix |
| Product TDD/gates | New lock tests first failed **2**, then focused suite passed **25**. Required Node **24.20.0** typecheck, lint, icon lint and full unit gate pass: **228 files / 2,284 tests**, zero skips; [exit metadata](evidence/a04-frontend-gates.json). Two existing lint warnings remain. An initial Node 25 diagnostic full run was interrupted after environment-related localStorage failures and is not counted as passing |
| CI | Frontend canonical gate, contract, local/S3/IPFS backed suites, channel-sync and GitGuardian all PASS on fix revision. Meta harness commit `a0060d4` passes bundle/validate/boot and GitGuardian; final documentation head must also pass before merge |
| Harness/gates | Both new JS helpers parse; existing Node assertions **3 PASS**, Python suite **20 PASS**, production Compose config -q with dummy secrets and diff check pass. No shell scripts touched |

Commands are in [the deploy runbook](../deploy/README.md#a04-registration-and-session-policy-verification).
Private results remain under `/tmp/vidra-a04-policies-*` and
`/tmp/vidra-a04-expiry-r1`; generated credentials, dumps and private error/deploy
logs are excluded from Git. A test initially expected missing-cookie 401; it was
corrected to assert the actual 422 field error, then the entire run passed.
Registration and approval end disabled; synthetic approved accounts and rejected
requests remain in the disposable database. The original frontend Compose/image
was restored after verification; the disposable VM was then stopped. No production deployment occurred.

A06 now proceeds with the retained owner/ordinary actors: browser-create a
channel/draft, upload a real generated audiovisual fixture, and prove original
metadata, owner/quota accounting, persistence and refusal paths. A05 provider
fixtures and every later acceptance remain open.


## A06 channel/draft/original upload — 2026-09-05

**A06 PASS on the retained local-storage stack; A07 next.** A04 delivery is merged:
frontend `13072dc`, meta `2b8db36`. This A06 adds only a
[real browser harness](../tests/upload-smoke.mjs), procedure and evidence;
no product, migration, workflow, dependency or release-pin changes.

[Final result](evidence/a06-upload.json) records four passing groups, exact helper
and fixture hashes, Node **24.20.0**, Chromium **151.0.7922.34**, channel/video/upload
IDs and quota readback. [Fixture provenance](evidence/a06-fixture.json) records
actual inspected container image references and ffprobe output. All runtime
checks used the original A01 release images, including the original frontend;
A04's local patch image was not used. HTTPS browser traffic is real, with no
route interception; A03 separately verified the lab CA. Emulation establishes
functionality, not performance capacity.

| Acceptance | Executed proof |
|---|---|
| Channel/draft | Ordinary A04 actor creates a unique channel using Studio, explicitly selects it when multiple channels exist, and chooses a generated file. Channel SQL owner matches the actor; draft response is 201/private/draft; SQL draft channel matches the newly created channel |
| Real original | 5-second, 320×240 H.264 + AAC test-pattern/sine fixture, **225,521 bytes**. Resumable completion 202 is followed by the browser's actual **Uploaded** state. API duration/dimensions are 5/320/240, original row has exact filename/size, authenticated original GET is 200 video/mp4 and SHA-256 equals the local file |
| Ownership/input | Other actor's upload-session request and private-original request are 404. Zero size returns 422, unsupported .exe returns 415. No rejected request creates an extra upload session |
| Quota | Admin temporarily sets this synthetic user's override to 1 byte; session request returns **422 quota_exceeded**, then exact previous override is restored. Final API used_bytes **1,402,160** equals SQL sum of all owned video_files; pre-run usage **1,137,240**. Usage includes derived files and retained earlier synthetic fixtures, not just the original |
| Corrupt media | Browser selects deliberately invalid .mp4 bytes. UI shows processing failure, never Published!; SQL video state is failed. This is distinct from rejecting an unsupported extension |
| Durability | Recreate API container only with existing images/volumes, wait for readyz 200, reload browser session, reread metadata and original. Original SHA-256 remains identical and quota still matches SQL |
| Gates | Helper parses; existing Node assertions **3 passed**, Python suite **20 passed**, zero skips; production Compose config -q with dummy values and git diff --check pass. No shell scripts changed. Final PR CI must pass before merge |
| Visual review | Inspected post-recreation Studio screenshot: correct selected channel, private uploaded clip and failed corrupt clip. The private clip's thumbnail is visibly broken; thumbnail/playback behavior is **not** certified here and requires investigation in A07 |

The draft automatically reaches state published while privacy remains private
when original processing finishes; this test does not press Publish or claim
public visibility. A07 must deliberately set the visibility needed for its
playback checks and inspect transcode jobs/assets, not infer playback from this
state label. Retained successful video: `0a0991c0-8656-4fb2-9ff2-ea6b2f1d78a4`.

Exploratory evidence was not silently promoted: initial Node-side HTTP requests
could not resolve the test-only hostname (browser DNS mapping does not apply to
Playwright's Node request context); all requests now use actual browser fetch.
An initial database MIME assertion was over-specific: the optional stored field
is empty but the original response is correctly video/mp4, now asserted directly.
The first four-group result lacked a new-channel association assertion; visual
review and SQL caught uploads targeting the previously selected channel. The
harness now selects the channel through the actual switcher and proves the
association. The final complete rerun passes those stronger checks. Earlier
selector timeouts/strict-match failures are retained privately, not product bugs.

Private outputs `/tmp/vidra-a06-r1` through `r7` contain diagnostics; only sanitized
results are committed. Fixture generation/run commands are in the
[runbook](../deploy/README.md#a06-original-upload-verification). Existing private
A04 actor credentials are reused and never committed. Synthetic rows remain for
A07 and failed-run diagnosis. No release publication or production deployment.

**Next: A07 on this same video's real transcode pipeline and local storage:**
inspect advertised HLS master/audio/video/init/segments; prove browser decode,
time progression, audio and seek plus progressive fallback; investigate the
observed private thumbnail failure. A10 resumability, A24 S3 and A28 scanning
remain separate unverified requirements.

## A07 playback checkpoint — 2026-09-05

**Open — runtime acceptance and merge pending.** Meta [PR #89](https://github.com/yegamble/vidra/pull/89)
adds the retained-stack harness. A06 delivery is merged as `87ac38a` (#88).
The original A01 images complete the same video's transcode job
`c269149a-3a85-4001-acee-c8ac06e08c3d` (done, attempt 1) and serve all nine
advertised HLS/CMAF assets. Real Chromium HLS playback advances unmuted, decodes
video/audio and completes seek to 3.5 seconds. These successes do not certify
progressive fallback.

[Original-image failure](evidence/a07-playback-before.json) records a real
transition failure: temporarily marking this synthetic video's playlist pending
makes the detail and playback-session stop advertising HLS, but the player stays
on an empty blob source instead of playing the original. The harness restores
ready and verifies HLS advertisement in `finally`. The frontend regression
reproduces the underlying ordering: React commits the original src, then HLS
teardown removes it while detaching its owned child source. A focused source
reconciliation fix and real-browser rerun are pending; do not promote A07 from
unit tests or HLS-only results.

Earlier click-based starts were intermittent during the original-to-HLS startup
transition. The media harness now waits for the intended source and starts with
the DOM play API. A40 must separately verify Play-button behavior; this evidence
does not certify it or physical speaker output. The private thumbnail probe
returned anonymous 404 and authenticated-owner 200/23,236 bytes; the original
exists, but A08 must verify private image delivery through the actual UI. Raw
errors, screenshots, credentials and failed-run logs remain private under
`/tmp/vidra-a07-*`. No production deployment or release publication occurred.

### A07 final runtime evidence — 2026-09-05

**Bounded A07 acceptance PASS with the frontend fix.** The linked PRs track delivery and merge state.
Frontend [PR #146](https://github.com/yegamble/vidra-user/pull/146), revision
`fde5ccc`, restores the direct src after HLS teardown. Meta PR #89 contains the
harness and reviewed [complete result](evidence/a07-playback-after.json).
[Fixture provenance](evidence/a07-frontend-fixture.json) proves the only changed
production file in the frozen A01 frontend source is `lib/use-playback-engine.ts`.
Core/search remain A01 images. The original release frontend still has this
bug; no new release was published.

| Acceptance | Observed result |
|---|---|
| Same media/job | A06 video `0a0991c0-8656-4fb2-9ff2-ea6b2f1d78a4`; exact fixture SHA-256 matches A06; job `c269149a-3a85-4001-acee-c8ac06e08c3d` done, attempt 1. Earlier stalled-lease observations and failure logs remain private; this final run certifies completion, not a new controlled worker-kill test |
| Advertised tree | Nine nonempty 200 assets: master, video/audio media playlists, both init files and fragments, iframe playlist and MP4; CMAF, advertised 320×240 rendition. Every referenced URI is followed through the actual HTTPS edge |
| HLS decode | Unmuted 1.645s, 48 frames, 27,377 audio decoded bytes, 320×240; readyState 4, completed seek 3.5s. Menu selection of the advertised 240p followed by repeated unmuted decode succeeds; this single-rung fixture does not certify ABR switching |
| Original/audio | Original decoded by browser to 5s/48kHz/mono PCM, nonzero peak 0.157. Under real pending-playlist state, API and session omit HLS; player chooses `/original`, advances unmuted to 1.596s with 43 frames/16,557 decoded audio bytes and completes seek 3.5s |
| Recovery | `finally` restores ready, then API advertises HLS again. Only this synthetic playlist row is temporarily changed; no bytes deleted, migrations altered or production service touched |
| Reproduction/TDD | Original-image run FAIL with empty blob; rendered-video regression fails with null src before the fix. After fix, 37 playback-engine tests pass; full frontend gate is 228 files/2,285 tests, zero skips, on Node 24.4.1. Typecheck/icon lint pass, lint has zero errors/two existing warnings |
| Harness/visual | Complete six-check run exits 0 on Node 25.9.0/Chromium 151.0.7922.34. Reviewed screenshot shows the actual test pattern at 3.5s. Meta Python 20 and Node 3 assertions pass, Compose config validation and diff check pass. No shell script changed |

This certifies browser media decoding and no-ready-tree progressive selection,
not physical speaker output, fatal-network-error recovery, Play-button timing,
ABR, or private-thumbnail UI delivery. A40/A08 retain those relevant follow-ups.
A channel avatar is also visibly broken in the watch screenshot; its identity
and delivery need their own UI acceptance rather than a playback claim.
The successful private output is `/tmp/vidra-a07-r16`; failures remain under
r1–r15. Next dependency-ready item is A09 (same ID through real search), then
A08. Dependent playback runs requiring this fix must select the recorded local
patch fixture or a later verified release containing `fde5ccc`.

The original A01 frontend digest was restored after the successful run and its
HTTPS home page returned 200; the disposable VM was then stopped. The local
A07 patch image and exact build source remain available for dependent rehearsals.
A09 preflight found `e2e-backed/search-discovery.spec.ts` still gated by
`E2E_SEARCH_SERVICE=true`; its two cases alone do not prove this same ID's
outbox/index/UI path, privacy/deletion rehydration or fallback/reconcile. Those
remain required A09 work, not implied by green general frontend CI.

## A09 real search acceptance — 2026-09-05

**Bounded A09 acceptance PASS.** [PR #90](https://github.com/yegamble/vidra/pull/90)
tracks delivery and merge state. A07 delivery is merged: meta `cc5ab1a`, frontend
`f160f5c`. The new [required-search helper](../tests/search-smoke.mjs) executes
six groups against the original A01 core/search/frontend release images; exact
running image references, helper/fixture hashes, Node 25.9.0 and Chromium
151.0.7922.34 are in the reviewed [complete result](evidence/a09-search.json).
No product changes, image-pin changes or new releases were needed for A09.
The A07 local frontend patch was not selected; this search proof does not
recertify its progressive transition.

| Acceptance | Executed evidence |
|---|---|
| Mandatory real service | `E2E_SEARCH_SERVICE=true` is required before the helper starts the VM; a missing flag exits 1, and search must be healthy. No route interception, fake search server or skip path. The actual service is reached through signed probes inside the guest without exporting its secret |
| Same uploaded ID end to end | A06 video `0a0991c0-8656-4fb2-9ff2-ea6b2f1d78a4`, exact audiovisual fixture hash, unique title `A09search1788627554677`. Upsert event ID matches core's delivered outbox and search's inbox; index title/eligibility and internal search IDs match. Anonymous header search renders a title link whose href is that exact video's watch path; clicking shows its heading and actual media image |
| Required search route | Fresh `search.submitted` event `cc962c05-1050-4ef6-9a44-73d9dcefd618` records source `search`, after a per-request outbox marker. The proof cannot silently pass by using local SQL or an old telemetry row |
| Private stale index | Real API privacy change delivers an ineligible upsert. After intentionally re-enabling only this stale synthetic search document, internal search returns its ID but public API and search UI exclude it; anonymous direct detail returns 404. Restoring public delivers another upsert |
| Outage/cold fallback | Stop real search: same query still returns the video, with a fresh `local` event. Restart search healthy; delete only this synthetic index document: cold-index query still finds it locally. These are separate observations, not simulated error responses |
| Reconcile | Restart API with existing images. Startup reconcile restores eligible document with a new run stamp; begin/page/end event IDs all appear delivered in core and received in search. A fresh query then records source `search` again |
| Deletion | API-create and upload a separate exact-fixture copy (201, original size 225,521 bytes), wait for eligible index/search result, then DELETE 204. Suppression event reaches both ledgers. Intentionally re-enable its stale candidate: internal search still returns it, but public API/UI do not, and core row count is zero. Stale eligibility is cleared afterward. Deleted copy ID `5d3c3960-4b48-4b35-bd12-9748d86b38be`; the main A06 ID is preserved for A08 |
| Verification | Final command exits 0: six groups PASS, zero skipped. Helper syntax, Python 20 and Node 3 assertions, production Compose config validation and diff check pass. No shell script changed; final PR CI must be green before merge |

Reviewed watch screenshot confirms the anonymous UI reached the retitled A06
fixture. Final readback is public video / ready playlist / eligible index.
The unique A09 title remains; the main media bytes were never deleted. A failed
first run used a channel UUID where draft creation requires its handle (404);
that harness error was corrected. r2 passed, then r3 passed with stronger fresh
routing-event correlation. Private diagnostics remain `/tmp/vidra-a09-r1` through
r3; credentials, raw errors and screenshots are not committed.

The existing frontend discovery/history spec was not run or relabelled here;
its default opt-out remains visible. This dedicated required lane certifies
A09's index, routing, visibility and recovery boundary, not autocomplete quality,
search history, recommendations, scale or relevance tuning (A13/A39/A40 retain
those separate requirements). Next dependency-ready item: **A08**, using the
preserved A06 video and the recorded A07 patch fixture where playback needs it.


## A08 links checkpoint — 2026-09-05

**A08 remains OPEN.** Canonical/legacy routes, timestamp playback and the real
Share dialog/embed pass on the exact-source lab fixture; private owner playback
fails. This is partial runtime evidence, not PLAY-02/03 acceptance or a release
certification.

The original v0.6.2 core image predates stored short codes. A08 therefore uses
pristine archives of core `63eafcbf371122e5b69666e9e59131de4b2c06cc` and frontend
`f160f5c80a96623e0ff537db5bfba140c243d680`, built as native ARM64 lab images.
The exact [source/image identities and normal deployment result](evidence/a08-source-fixture.json)
are retained. No published release or committed production pin changed.
`make-bundle.sh` generated an unmodified manifest with synthetic lab tag
`v999.8.0`; the normal deploy completed pre-deploy dump, pull (local images use
`pull_policy: never`), separate migrators, independent ledger assertions, startup
and API/frontend/HTTPS probes. The core ledger advanced from 125 to **127 clean**.
The retained VM is now a schema-127 source fixture; the old release bundle must
not be treated as the active installation or used for a blind schema rollback.
The lab-only API CPU limit is two, matching the VM. Existing stateful/search
images and their architectures were preserved.

The [browser result before product fixes](evidence/a08-links-before.json) proves
actual audio/video decode through `/v/{stored-code}`, `/videos/{uuid}`, legacy
Bitcoin-base58 `/v/{sid}`, PeerTube Flickr-base58 `/w/{sid}`, and
`/videos/watch/{uuid}`, all with `?t=2`. Canonical metadata names the stored code
without the timestamp. The Share dialog produces that watch link and an iframe
that plays the same fixture with its timestamp. This tests local UUID aliases;
source-import UUID mapping still needs its own fixture.

A separate fresh-login trace reproduced an anonymous resolve 404 before the
successful refresh/me responses; the private page stayed on not-found.
[Frontend PR #147](https://github.com/yegamble/vidra-user/pull/147) waits for the
session to settle before resolving UUID/code links. Three reproducing tests
failed first; all seven focused tests and 2,288 full tests then passed, alongside
typecheck and lint gates. Private original, thumbnail and HLS fetches with the
owner bearer returned 200 while ordinary media-element requests returned 404;
that separate transport issue remains open.

Private runs r1/r2 corrected harness path-alphabet and exact-label mistakes.
r3 exposed private access; its automatic restore failed. r4 added request-status
diagnostics and exposed API rate limiting after repeated full-page navigations;
fresh-login recovery restored public with HTTP 200. The helper now paces those
navigations and retries rate-limited cleanup. Raw errors, screenshots and account
credentials remain private under `/tmp/vidra-a08-*`, never in git.

Remaining A08 work: verify the session fix through the real edge, fix owner media
transport with regression tests, then test password unlock and copied assets,
expiry, download revocation, embed allowlists/disablement, source UUID aliases,
oEmbed/feed/sitemap and unlisted/account-unlisted discovery boundaries. None is
implied by the passing link subset. The retained A06 audiovisual bytes and UUID
remain the acceptance subject.

The session fix's [exact lab deployment](evidence/a08-session-fixture.json) also
passed all normal gates. A [focused fresh-login browser trace](evidence/a08-session-check.json)
then showed refresh/me 200 followed by **authenticated stored-code resolution
200**, and the UI displayed the title plus “Private — Only you can see this”.
Native original/HLS still returned 404 and the player remained at 0:00. This
isolates the remaining media failure without rate-limit responses. Public
restoration returned 200. The full r5 run still hit 429 during its sweep; pacing
was increased to 30 seconds per route, and that revised full sweep has not yet
been rerun. Current active guest installation is the one named in the session
fixture result; schema remains 127 clean.


## A08 private playback checkpoint — 2026-09-05

**Private owner playback PASS; full A08 remains OPEN.** The prior page-session
fix is merged in frontend [PR #147](https://github.com/yegamble/vidra-user/pull/147)
(`df327d9`), and the first link checkpoint is merged in meta
[PR #91](https://github.com/yegamble/vidra/pull/91) (`ee078ea`).
Core [PR #158](https://github.com/yegamble/vidra-core/pull/158) supplies the missing
native media credential: cookie-mode login/refresh sets a short-lived HttpOnly
video-path access cookie, which only private/unpublished GET/HEAD reads consult.
Explicit bearers take precedence, mutations remain bearer-only, and public
playback ignores this cookie to preserve anonymous CDN/cache behavior.

The [exact-source fixture](evidence/a08-private-media-fixture.json) again passed
normal dump/pull/discrete migrations/independent ledger/startup/health gates.
Schema remains 127 clean, with core source `0f5b347` and the already-proven
frontend session fix. This is a lab fixture, not a newly published release.
The [complete browser result](evidence/a08-private-playback.json) records all
five canonical/legacy timestamp routes, Share/embed playback, owner and anonymous
asset responses, decoded frames/audio, exact identities and cleanup status.

For the retained A06 video, bearer and owner-native requests to original,
thumbnail and HLS master each returned **200**; a separate anonymous browser
returned **404** for each. The owner opened its stored-code private page and
played actual media with advancing time, decoded frames and audio. The final
privacy restore returned 200. The 30-second route pacing completed without
rate-limit interference. Private raw diagnostics remain `/tmp/vidra-a08-links-r6`.

Core regression tests failed first for the missing cookie, then passed for
owner/foreign/expired access, explicit-bearer precedence, cookie-only mutation
and account rejection, private no-store, public CDN eligibility, refresh and
logout. Full `make ci` and integration-tag vet passed; frontend contract guard
passed all 303 operations. Meta Python 20 / Node 3 tests, helper syntax,
production Compose config validation and diff checks passed. PR CI/merge state
is tracked at the linked PRs.

Still required for A08: password unlock and expiry, copied segment/caption/
storyboard assets, download revocation, embed origins/disablement, source UUID
mapping, oEmbed/feed/sitemap, and unlisted/account-unlisted discovery boundaries.
The passing reproduction helper deliberately does not claim those phases.


The follow-on [password watch/embed helper](../tests/password-links-smoke.mjs)
also passed against those exact running images; its
[complete result](evidence/a08-password-links.json) records both real browser
surfaces. Each rejected a wrong password, accepted the temporary correct one,
and decoded audio/video. Original, thumbnail and HLS master returned 200 with
the playback token and 401 without it. The fixture initially had no passwords;
cleanup restored public (200) and removed the temporary password (204). No
password or playback token is retained in the evidence. Private output is
`/tmp/vidra-a08-password-r2`; r1 was the successful preliminary probe.

This closes basic password unlock/playback on watch and embed. **A08 is still
open** for token expiry, copied segment/caption/storyboard paths, download
revocation, embed origin/disabled policy, source UUID mapping, metadata and
unlisted/account-unlisted discovery. A valid copied playback token is a bearer
credential; this run does not claim that it expires before its six-hour TTL.


The extended password run r3 also passed **server-side playback-token expiry**.
Inside the disposable guest, the helper creates a correctly signed valid/expired
control pair using the deployed signer's format and domain separation; the key
never leaves the guest and neither token is saved in evidence. Real edge reads
of original, thumbnail, HLS master, CMAF variant and a real `.m4s` chunk return
200 for the valid control and 401 for the expired control. This is an explicit
expired-credential fixture, not a claim that a browser was held open for six
hours. Watch/embed playback and cleanup passed again. The password evidence
now records this complete r3 run.

Remaining A08 boundaries are copied caption/storyboard and other asset paths,
download revocation, embed origins/disablement, source UUID aliases, metadata,
and unlisted/account-unlisted discovery. Core CI's first public-IPFS lane failed
because the external gateway returned 429 for the fresh CID; all other lanes
passed. That specific lane was retried without changing its test or workflow.


## A08 downloads and embed policies — 2026-09-05

**Download revocation and real iframe policy checks PASS; full A08 remains
OPEN.** Core private-media fix [PR #158](https://github.com/yegamble/vidra-core/pull/158)
is merged (`d1250c3`), as is the private/password/expiry evidence in meta
[PR #92](https://github.com/yegamble/vidra/pull/92) (`614535b`). The public-IPFS CI
retry passed without changing the gate.

The [download/embed helper](../tests/download-embed-smoke.mjs) uses the same A06
video and exact bytes, separate anonymous and owner browsers, and real local
HTTP/HTTPS parent servers. It does not intercept browser requests or spoof
referrer/ancestor-origin properties. Its
[complete result](evidence/a08-download-embed.json) and
[exact fixture deployment](evidence/a08-http-embed-fixture.json) record image,
source, helper and media identities, response statuses and decoded frames/audio.
Normal dump/pull/migration/ledger/startup/health gates passed; schema remains
127 clean. Production pins and releases were not changed.

The browser's Download dialog selected Original file and saved all 225,521 bytes
with the original SHA256. Every advertised download URL independently returned
200 and nonempty bytes. Disabling the per-video download flag made the listing
and every copied file URL return 403 `feature_disabled`, and removed the UI
button after reload. Actual streaming still played. The original flag was
restored with HTTP200.

With an allowlist containing `allowed.a08.test`, actual HTTPS and HTTP parents
on that hostname both played audio/video. Parents on `denied.a08.test` both
showed the blocked notice and no video element. Setting embed policy to disabled
also removed the player and showed its disabled notice. The original embed
policy was restored with HTTP200. These are the shipped browser embed-policy
semantics, not a server-side restriction against a determined custom embedder.

The HTTP-parent case initially failed before any API request: an HTTPS child
under an HTTP ancestor is not a secure context, so `crypto.randomUUID` is absent.
The [before trace](evidence/a08-http-embed-before.json) records that distinction
and the empty API request list. Frontend
[PR #148](https://github.com/yegamble/vidra-user/pull/148) adds a CSPRNG UUIDv4
fallback using `getRandomValues`, shared by API transports. Its new test failed
first; 56 focused and 2,289 full tests then passed, with typecheck and lint gates.
The new browser result proves HTTP-parent playback while `randomUUID` remains
undefined. The fixture uses runtime source `5217e36`; the later generated-code
update changes only the login contract comment to match core's media cookie.
That generated file was regenerated normally, never hand-edited.

Private runs r1/r2 exposed the HTTP-parent failure; r3 proved HTTPS policy
behavior, and r4 passed both schemes plus all advertised download URLs. Private
TLS keys and diagnostics remain under `/tmp/vidra-a08-download-embed-*`, never
in git. Meta Python20/Node3 tests, syntax, production Compose validation and diff
checks passed. The fixture is public and its original policies are restored.

Remaining A08 acceptance: copied captions/storyboards and remaining media paths,
instance-wide download policy, source-import UUID aliases, oEmbed/feed/sitemap
and other metadata, and unlisted/account-unlisted discovery transitions.


## A08 metadata, discovery and source UUID routing — 2026-09-05

**Six discovery/metadata/alias groups PASS; full A08 remains OPEN.** Frontend
HTTP-parent fix #148 is merged (`5f7efe3`) and download/embed evidence #93 is
merged (`b10ee3f`). The new [required helper](../tests/discovery-links-smoke.mjs)
and [complete result](evidence/a08-discovery-aliases.json) use the same exact
source fixture from the preceding checkpoint and retain image/fixture identities.

Canonical and OpenGraph URLs match the stored code; OpenGraph title matches the
video. oEmbed discovery points at that canonical link, and the actual provider
returns the correct title and working embed path. Instance/channel RSS link to
the code while retaining the UUID permalink as their GUID; the sitemap advertises
the canonical code. Every endpoint returned 200. Anonymous feed/search/RSS/
sitemap include the original public fixture.

Changing the video to unlisted excludes it from all four discovery surfaces,
while its direct watch page decodes audio/video. Changing its owning account to
unlisted also excludes the public video from those surfaces, while direct video
and channel APIs return 200. Restoring the account restores discovery. Private
visibility excludes the video from those surfaces and makes oEmbed return 401.
The helper restores public visibility and the account's original listed status.

For legacy source routing, a fresh synthetic source UUID is temporarily assigned
to this fixture's previously-empty `peertube_uuid`. Its real Flickr-base58 `/w/`
path and `/videos/watch/{source UUID}` both reach the existing stored-code page,
preserve `?t=2`, and decode the same media. The conditional SQL update and cleanup
both affect exactly this fixture; the mapping is cleared afterward. This proves
the source-UUID routing mechanism, **not** an actual PeerTube import or cutover;
those remain A18–A23 requirements.

The command exits 0 with six groups PASS, no skips, privacy/account restoration
200 and alias cleanup confirmed. Python20/Node3 tests, helper syntax, production
Compose config validation and diff checks passed. No product code, shell script,
workflow or production pin changed. Private output: `/tmp/vidra-a08-discovery-r1`.
Remaining A08 work is the copied caption/storyboard/remaining media-path boundary
and instance-wide download policy. Cached frontend metadata freshness is not
certified as immediate revocation by this origin/distribution test.

## A08 final media access evidence — 2026-09-05

**Bounded A08 runtime acceptance PASS.** Core/frontend fixes are merged; meta
[PR #95](https://github.com/yegamble/vidra/pull/95) tracks final evidence delivery.
A07 was already delivered (meta #89, frontend #146); A08 is the next open item
continued here. This closes the two remaining boundaries from the preceding
checkpoint, reusing the same A06 video and the earlier link/discovery evidence.

The prior real probe returned 404 for an unlisted caption. Core
[PR #159](https://github.com/yegamble/vidra-core/pull/159), revision `b01c53e`,
reuses `videoVisibleForMedia` for caption metadata and bytes. The new regression
failed first, then focused caption tests and `make ci` passed (format, vet,
migration lint, OpenAPI, sqlc and race tests); integration-tagged vet passed.
The linked [frontend PR #149](https://github.com/yegamble/vidra-user/pull/149) is generated normally from that OpenAPI
source; it changes comments only. Frontend typecheck, lint, icon lint and all
2,289 tests in 228 files passed. Merge order: core fix → generated client →
[meta evidence PR #95](https://github.com/yegamble/vidra/pull/95).

[Required media helper](../tests/media-access-smoke.mjs),
[full result](evidence/a08-media-access.json), and
[fixture identity](evidence/a08-caption-fixture.json) record exact source/image
identities and the helper hash. Command (Node 24.4.1):

```sh
node tests/media-access-smoke.mjs /tmp/vidra-a03-r3 /tmp/vidra-a04-r3 \
  /tmp/vidra-a06-fixture/clip.mp4 /tmp/vidra-a08-caption-fixture-r1 \
  /tmp/vidra-a08-assets-r2
```

Exit 0: four groups PASS, zero skips. Real Chromium through the HTTPS edge:

- Global download listing and every advertised file return 403
  `feature_disabled` after the instance switch is disabled; streaming still
  advances time and decodes audio/video. Original setting restored with 200.
- The helper walks the complete advertised HLS tree (alternate audio, variants,
  init files and segments), plus original, thumbnail, storyboard image/map and
  caption list/bytes: 15 endpoints. Public/unlisted reads return 200; private
  owner cookie reads return 200 and anonymous reads return 404.
- Real password form unlock plays audio/video. All 15 copied paths return 200
  with its playback token, 401 without it, and 401 with an expired signed token.
  The signing secret stays inside the disposable guest; no token is evidence.
- Cleanup restores public visibility (200), removes the temporary caption and
  password (204 each), and restores the download setting (200).

Docker Hub's Dockerfile frontend resolution stalled. The lab therefore uses a
local `CGO_ENABLED=0 GOOS=linux GOARCH=arm64 go build -trimpath` of the archived
core revision with version/commit ldflags, copied into the retained runtime
image `sha256:bbb048f88cf83c8340f61e7544fc9d09dd73ee42f5e861b5b91bf24830ab3297`.
This is an exact-source local fixture, **not a released-image certification**.
Normal pre-deploy dump, discrete migration/ledger checks and health gates passed;
core schema remains 127 clean. Frontend runtime remains `5217e36` as previously
recorded; the generated comment update has no runtime effect. No production
pins, releases, deployment, workflows, SQL or migrations changed.

Meta Python20/Node3 tests, helper syntax, production Compose config validation
and diff checks pass. Private diagnostics remain `/tmp/vidra-a08-assets-r2`.
Earlier A08 checkpoints retain canonical/legacy/source alias, metadata,
discovery, per-video download and real iframe-policy evidence. Native Safari,
selected CDN-edge revocation, actual PeerTube import/cutover and instantaneous
cached frontend metadata revocation are not certified here; retain their
existing A40/A33/A18–23 scope. Stop after A08 delivery; do not start another item.

### A08 delivery checkpoint (superseded below)

**Open — awaiting merge.** Core #159 passed all six checks, including real
integration and public/private IPFS lanes. Automatic approval review rejected
merging twice: the session has both an earlier no-merge instruction and a later
merge instruction, which it considers ambiguous. No merge occurred. Fresh user
confirmation is required. Smallest next action: authorize core #159 → frontend
#149 → meta #95 merges, then rerun frontend contract run `33985647123` after
core lands. Its current failure is precisely the four generated documentation
lines versus core's pre-merge `main`; do not revert the correct generated client
or weaken the gate. Wait for all remaining checks before each merge and delete
only merged branches. The local fixture is restored and the VM stopped.

### A08 approved delivery — 2026-09-05

The user explicitly resolved merge authorization with “continue with automatical
approval.” Core #159 is merged to main at `6a6ea24` after all six checks passed.
Frontend #149 is merged at `ad00b69` after all seven checks passed, including
real backend-backed local/S3 browser lanes, channel-sync, IPFS, and the contract
rerun against merged core (run `33985647123`, attempt 2). The original contract
failure was resolved by the documented dependency order without code changes or
gate weakening. Both component work branches were deleted locally and remotely.
Meta #95 carries this final delivery record; merge it on its final green checks,
then delete its work branch. The fixture remains restored and stopped. A08 is
the only acceptance item completed here; the earlier runtime limitations remain.


## A10 recovery checkpoint — 2026-09-05

**A10 OPEN — resume/cancel slice verified; remaining lifecycle acceptance unverified.**
Dependencies A07/A09 have prior runtime evidence. Observable PUB-02 outcomes:
interruption and service restart preserve uploaded chunks, a fresh session resumes
without duplicate files/quota, and failed cancellation remains recoverable until
cleanup succeeds. PUB-02 batch and PUB-04 publishing lifecycle remain separate
required work; this checkpoint does not mark either entire row PASS.

Frontend [PR #152](https://github.com/yegamble/vidra-user/pull/152), revision
`420bc56`, fixes two false-success paths: failed inventory checks were hidden,
and failed cancellation/deletion removed the recovery row. Inventory now has a
retry action. Discard waits for confirmed cancellation and draft deletion; failed
draft deletion remains retryable and disables unsafe resume. No API/SQL contract,
authorization, privacy, dependencies or workflow changes.

[Evidence](evidence/a10-recovery.json): real Chromium and the restored lab API
proved an 11,207,830-byte two-chunk MP4 survives interruption and API restart.
A fresh browser rejected the wrong file, sent only chunk 1, and downloaded a
published original with matching SHA-256. SQL showed one original and quota
matched stored files. Browser network fault injection proved inventory retry
and failed Discard retaining its row. The real cleanup retry removed the draft,
left quota unchanged and left zero session chunk files on disk. API final health
is healthy; the source VM and test runner were untouched.

TDD: three new tests failed before implementation and passed after. Required
frontend gates PASS: TypeScript, lint (0 errors, 2 existing warnings), icons,
229 unit files / 2,292 tests. Meta Compose config and diff/JSON checks PASS
(nested core `6a6ea24`). No scripts changed. Runtime used the development frontend and actual
lab backend; PR CI is pending, so no production-build CI result is claimed.

Failed attempts retained: the first draft fixture used a channel UUID where the
contract requires a handle (404); the corrected run persisted chunk 0, then its
service-outage UI assertion timed out while the VM temporarily lost SSH. Immediate
API recovery also failed. A later successful restart resumed that same session;
the inventory error UI was separately proven through request-level network abort.
No mocked success responses, raised limits or duplicate replacement drafts.

Next: PUB-02 partial batch failures, then PUB-04 schedule/quarantine/replacement
with processing, search and browser persistence evidence. Also verify recovery
across reload between successful cancellation and failed draft deletion. The
private reproduction paths/hashes are recorded in evidence. This focused slice
is reviewable; A10 and the wider A09–A40 goal remain open. Merge authorization
is still pending; no merge is claimed.


### A10 batch retry evidence — 2026-09-05

Frontend PR #152, revision `20fd27b`, now also fixes batch retries abandoning their original
draft/session and the capacity backoff timer leaving a queued row stalled.
Retries read the existing session and reuse server identity; successful rows
remain untouched. Cancellation cleanup errors remain Failed instead of being
reported as Cancelled. No contract or migration changed.

[Batch evidence](evidence/a10-batch.json) records the real pre-fix failure:
three chosen files, one interrupted chunk stream, then four database rows after
retry (one abandoned draft plus three published videos). After the fix the same
scenario retained the failed file/title, retried only that row, and produced
exactly three published private videos whose original SHA-256 hashes matched.
A second actual browser test filled the backend's five-session limit, observed
`429 too_many_active_uploads`, released only its four seeded reservations, and
proved automatic recovery to two completed videos with no extra draft. All
seeded reservations/drafts were cleaned up; existing lab sessions were preserved.

Regression tests reproduced duplicate draft creation and stalled backoff before
their fixes. Three focused batch tests now pass, including honest cleanup error
state. Final frontend gates: 230 files / 2,295 tests, TypeScript, lint (0 errors,
2 existing warnings), icons and diff check PASS. Live tests exercised the real
API and processing pipeline through a development frontend. Updated PR CI is
pending and must be checked independently; the prior revision's checks do not
prove this revision.

PUB-04 remains UNVERIFIED. Next experiment: schedule a small real upload through
the ordinary UI without holding its completion request, then check persistence,
processing/search visibility, due-time publication, quarantine and replacement.
The existing schedule spec deliberately holds completion until metadata PATCH;
that cannot by itself prove the ordinary user flow is free from that race.
Reload during partially completed cancellation cleanup also remains unverified.
A10 and the A09–A40 goal remain OPEN; no merge is claimed.


### A10 ordinary scheduling checkpoint — 2026-09-05

**A10 remains OPEN; scheduling slice verified, other PUB-04 paths unverified.**
Frontend [PR #153](https://github.com/yegamble/vidra-user/pull/153), candidate
`fd7ce8f`, fixes an observed ordinary-flow race: a small upload
finalized as privately published before the creator saved a schedule, making the
API correctly reject `publish_at` with 422. Bytes still upload immediately, but
finalization now waits for the Publish metadata PATCH to succeed. Failed saves
remain retryable, and waiting uploads remain cancellable. This preserves the
existing API/authorization contract; no SQL/API client regeneration was needed.

[Scheduling evidence](evidence/a10-scheduling.json): a real upload stayed in draft
with no video-file rows after transfer, accepted its schedule through the ordinary
UI, survived a page reload, and was excluded from public detail/search before due
time. The same video was public and indexed 16 seconds after due time; its
original hash matched the audiovisual fixture. Cancel after transfer sent zero
completion requests and removed the real draft and chunk files. The earlier
failed cancellation attempt's single orphan draft was separately deleted using
the owner API and the cleanup was verified.

Three new regressions failed before implementation; 34 focused tests pass.
Final full suite: 228 files / 2,292 tests PASS with two workers and unchanged
timeouts. The initial default-worker run failed two unrelated component timeouts
while the VM status probe also timed out; the original failures are retained.
TypeScript, lint (0 errors, 2 existing warnings), icons and diff checks PASS.
Existing backed schedule specs now exercise fully transferred files without an
artificial completion-route gate; exact revised specs await CI, whereas actual
lab browser/API/search tests above ran. No green CI claim for this new revision.

Other failed attempts remain explicit: a test-only wrong search URL, temporary
Multipass info timeout, and a real 429 during repeated pre-due reads. The final
follow-up used bounded reads after the limit reset; it does not prove continuous
visibility monitoring during that interval. No server limits were raised.

Next: publish-after-transcode state and discovery, then real quarantine approve/
reject and replacement preserving identity and playable generations. Recovery
across partial cleanup/reload remains recorded. Review this scheduling change
and the independent recovery/batch PR #152 before their shared evidence record.
No production deployment or merge occurred; the A09–A40 goal remains OPEN.


### A10 processing and quarantine checkpoint — 2026-09-05

**A10 OPEN — replacement and partial-cleanup verification remain.**
[Evidence](evidence/a10-processing-quarantine.json) adds actual processing and
moderation proof using frontend `fd7ce8f` and the isolated PostgreSQL-backed API:

- A real 11 MB audiovisual upload with publish-after-transcode enabled entered
  the persisted hold and was excluded from public detail/search. It later became
  published and discoverable with an advertised ready HLS master. Chromium
  playback advanced past two seconds and decoded 68 frames. No processing jobs
  or success responses were mocked; existing A07 evidence covers the full ladder
  and audio decoding separately.
- Real uploads under temporarily enabled quarantine entered the held state.
  Browser approval/rejection, reload persistence, intended viewer policy, owner
  notification and moderation response semantics passed on candidate core
  `39be454` in [PR #160](https://github.com/yegamble/vidra-core/pull/160).
  Security: needs owner attention; detailed prior reproduction remains private.
- The quarantine setting was restored with its original override status. The
  candidate API was built only in the disposable VM from the unchanged lab base
  plus the scoped binary; original image and complete environment were restored
  and health verified. Source VM/test runner were untouched. Temporary frontend
  and proxy processes were stopped, and generated unrelated instructions removed.

Core TDD regression failed before the fix; full HTTP API suite PASS. Required
`make ci` PASS (format, vet, migration lint, OpenAPI, generated SQL, race tests),
with bounded build concurrency. Integration-tagged vet PASS. Full tagged store/
federation suites were NOT RUN; targeted acceptance ran against actual lab
PostgreSQL through the API/browser. No SQL or API shape changed, so no migration
or client regeneration was needed. New core PR CI remains pending.

Review core #160 and independent frontend #152/#153 before this evidence record;
there is no contract dependency order among those implementation PRs. Next:
replacement must preserve stable identity/metadata and playable old/new
versions, including failure retaining the previous usable generation. Partial
cleanup/reload gaps remain recorded. No merge, release or production deployment;
the wider A09–A40 goal remains OPEN.

### A10 replacement and CI checkpoint — 2026-09-05

**A10 OPEN — replacement failure retention and scheduling CI pending.**
[Replacement evidence](evidence/a10-replacement.json) records real Chromium
playback during a 48 MB replacement and after its HLS generation was promoted.
The video ID, short link, channel, title, description, privacy, creation time and
publish-after-transcode setting stayed equal. Views did not decrease; the
returned original matched the replacement SHA-256. The existing player kept
advancing with no media error before, during and after promotion, including a
seek after promotion. The replacement feature override was restored exactly.

An invalid replacement did not settle within the test's 90-second terminal wait.
Read-only inspection found the existing five-attempt exponential retry policy,
with the safe error "the file is not a playable video" and a pending job after
attempt four. This is not terminal-failure proof. Next: observe the natural final
attempt, then verify the previous master/original and actual playback survive.
No retries, job states or clocks were modified to manufacture completion.

Scheduling frontend #153's first CI run exposed stale test sequencing: the
shared backed fixture and two mocked tests waited for finalization before
Publish. Revision `217b083` saves metadata first, then asserts the unchanged
processing outcome; the mocked publish test additionally requires zero
completion requests before Publish and exactly one afterward. Typecheck, lint
(two existing warnings), production build and both previously failing mocked
Chromium tests PASS (2/2). Full updated local/S3 CI is pending. Earlier unit and
icon gates remain recorded above; this follow-up changes only tests.

Recovery frontend #152 and core #160 now have green CI, including their actual
integration suites. This supplements, rather than reclassifies, the explicitly
unrun local tagged core suites. Partial-discard fault injection confirms honest
cleanup errors and a retained draft discoverable in its channel after reload;
[Partial-cleanup evidence](evidence/a10-partial-cleanup.json) now confirms UI
deletion, API 404, zero video-file rows and unchanged used quota after reload.
Test-selector corrections and transient inventory failure remain in private
checkpoints. Meta Compose config, evidence JSON and diff checks PASS.
No acceptance completion, merge, release or production deployment is claimed.

### A10 candidate acceptance — 2026-09-05

**A10 implementation and acceptance proof are reviewable; delivery remains OPEN
— awaiting merge.** This checkpoint supersedes the pending observations above.
PUB-02/PUB-04 candidate success means resumable transfers survive network/service
interruption and a fresh session without duplicate files/quota; cancellation
and partial batch failures remain recoverable; schedule, processing and
quarantine enforce visibility; replacement preserves identity and playable
media, including when the replacement fails.

The invalid replacement naturally exhausted the existing five-attempt retry
policy. Its job and session became failed without manipulating their state or
clock. The prior HLS master, original SHA-256 and video metadata remained intact;
an anonymous Chromium player then advanced 3.006 seconds and decoded 77 frames
with no media error. [Replacement evidence](evidence/a10-replacement.json) now
PASS. [Partial-cleanup evidence](evidence/a10-partial-cleanup.json) PASS includes
zero remaining chunks under the verified media root. Earlier failed harness
attempts and the initial 90-second wait remain recorded, not relabeled as passes.

Implementation revisions and green CI:

- Frontend recovery/batch `20fd27b`, [#152](https://github.com/yegamble/vidra-user/pull/152):
  frontend, local/S3 backed, channel-sync, contract and IPFS checks PASS.
- Frontend schedule `217b083`, [#153](https://github.com/yegamble/vidra-user/pull/153):
  frontend [run 33996505843](https://github.com/yegamble/vidra-user/actions/runs/33996505843)
  and local/S3 backed [run 33996505849](https://github.com/yegamble/vidra-user/actions/runs/33996505849)
  PASS; contract, channel-sync and IPFS checks PASS.
- Core intended viewer policy `39be454`, [#160](https://github.com/yegamble/vidra-core/pull/160):
  build/test, OpenAPI, integration and IPFS integration checks PASS. Security:
  needs owner attention; detailed original reproduction stays private.

Review all three independent implementation PRs before accepting the linked
meta evidence PR #101; none requires a contract migration or an ordering among
implementation PRs. No production deployment/release or merge occurred. Local
core full tagged suites were not run (CI integration passed); temporary browser
harnesses supplement committed tests and do not replace their gates. Temporary proxy/frontend processes were stopped and the generated instruction
suffix removed; component checkouts are clean. The wider
A09–A40 goal remains open. Next action: resolve pending merge authorization and
review these candidates; continue the next dependency-ready item separately.

## A11 Studio and statistics checkpoint — 2026-09-05

**A11 OPEN — stored-byte deletion awaits collector approval.** Dependency-ready
from A07/A09. Observable success requires persisted Studio field/media edits,
chapter order and real frame/sprite behavior, deletion removing media/discovery,
and correctly attributed owner-scoped video/channel/account analytics, including
channel-switch races and historical totals without fabricated daily history.

- [Chapter evidence](evidence/a11-chapters.json): failed initial GET was presented
  as an empty editable set; Save genuinely erased two synthetic stored chapters.
  The chapters were restored after reproduction. Frontend
  [#154](https://github.com/yegamble/vidra-user/pull/154) now disables whole-set
  replacement until the read succeeds, shows the design-system error/retry UI,
  and loads the authoritative rows before editing. Actual Chromium/API retry,
  changed chapter order and reload persistence PASS. Two TDD regressions failed
  first; all 8 focused chapter tests and 228 files / 2294 full tests PASS.
  TypeScript, lint (two existing warnings), icons and diff checks PASS.
- [Studio evidence](evidence/a11-studio.json): title, description, taxonomy,
  tags, privacy, sensitive flag/reason and comment/download toggles persisted
  through fresh read/reload. Valid custom PNG upload matched stored SHA and
  decoded in-browser; actual frame picker at two seconds returned JPEG;
  playback hover rendered the real storyboard sprite/VTT. Schedule and source
  replacement remain covered by the separate A10 evidence, not duplicated here.
- [Statistics evidence](evidence/a11-stats.json): repeated view/like calls
  deduped; real comment attribution and daily rollup matched expected deltas.
  Two creators' video/channel stats enforce 404 for the other owner (including
  staff), account sums exclude the other creator, and UI/account/per-video
  reload checks PASS. A delayed actual channel stats request clears previous
  totals, then shows the new channel's 500 historical views and zero recent
  views. The 500 total is an explicitly synthetic aggregate without daily rows;
  this proves analytics semantics, not PeerTube migration. A Playwright route
  cleanup race was corrected and rerun on the same fixtures.
- [Deletion evidence](evidence/a11-deletion.json): Studio confirmation returned
  204; reload stayed deleted, public detail/thumbnail/storyboard/HLS and owner
  original returned 404, file rows vanished, and real search excluded the ID.
  Physical object deletion remains UNVERIFIED. The existing collector dry run
  found about 105 earlier lab orphans before this deletion, within its unchanged
  25% circuit breaker. Automatic approval review rejected running that complete
  set because it extends beyond the focused A11 fixture. User approval is
  pending; no collector or manual blob deletion was performed.

Frontend revision `e085945` adds the backed chapter read-failure regression and
replaces the old eight-byte thumbnail header fixture with a decodable PNG plus
browser decode assertion. Its updated CI is pending. #154 is stacked on A10
frontend #153; review/merge #153 first, then #154. This evidence is stacked on
meta #101. No core contract/SQL change, client regeneration, dependency change,
workflow edit, production deployment or merge. An initial upload toast timeout
on the new fixture is recorded separately; persisted publication was verified,
but that toast assertion is not relabeled as a success.

Next: review the pending collector permission and observe #154's updated CI.
Keep A11 open until physical cleanup is proved. Independent A12 work can proceed
while that external approval remains pending; the A09–A40 goal stays active.


## A12 library checkpoint — 2026-09-05

**A12 OPEN — partial library proof; remaining acceptance slices unverified.**
Observable success remains all AUTH-05, SOC-01 and SOC-02 criteria: persistent
library actions, intended social recipients/privacy, and complete profile,
archive, deactivation and deletion behavior. No suite result substitutes for
those individual workflows.

The session-restoration defect is fixed in [frontend draft PR #155](https://github.com/yegamble/vidra-user/pull/155), revision `4a84aac`:
channel follow state and private playlist detail wait for the restored viewer;
changing identity clears pending resource/editor state. Four new regressions
failed before implementation; all six focused tests now pass. Required gates:
TypeScript and icons pass; ESLint has zero errors and two existing warnings;
229 test files / 2,295 tests pass. Backed follow/unfollow and private-playlist
reload regressions were added; full local/S3 PR CI is pending.

[Library evidence](evidence/a12-library.json) records real Chromium against the
disposable restored API/PostgreSQL/search/media worker: follow before actual
uploads, notification/feed after publication, saved reload, owner private
playlist reload and other-user refusal, add/order/reload, unlisted metadata and
write denial, and uploaded cover decoding/reload. Registration was temporarily
enabled only for the three synthetic actors and the exact closed setting was
restored. Harness rate-limit and expected-status corrections are recorded.

Private detail now loads correctly, but its owner's image element receives 404
because the cover request lacks bearer authentication. Anonymous refusal still
passes. Next: a failing authenticated-cover regression and scoped correction,
then real history/continuation/unfollow, social, profile/archive and deletion
proof. No production or source migration data was used. A11 frontend PR #154
and meta PR #102 now have all checks green; physical GC remains approval-blocked.


Further A12 browser evidence: actual long-video playback saved a 12-second
position; the in-progress history query and a hard reload retained it, and
Resume played from that position. Clear-history persisted in a fresh session
(HTTP 200 empty list); the immediate post-clear assertion timed out and is
recorded separately. Unfollow survived reload and removed the channel's videos
from the subscription feed. Disabling “Keep my watch history” survived reload;
12 seconds of actual playback created no history. The original enabled setting
was restored and verified after reload. These checks pass; playlist continuation,
private-cover rendering and the social/profile/archive/deletion slices remain
open. Evidence PR: [meta #103](https://github.com/yegamble/vidra/pull/103), stacked
on #102; all checks passed for its initial `bdbe88f` revision.


A12 private covers corrected in [frontend #156](https://github.com/yegamble/vidra-user/pull/156),
revision `de7bd33`, stacked after #155. Owner images now fetch authenticated bytes
in the editor, playlist grid and Library; all three decoded in real Chromium,
with anonymous denial intact. TDD manager regression failed before the fix;
six focused tests pass, including viewer changes, cancellation and stale-response
cleanup. Required gates pass: TypeScript/icons, zero lint errors (two existing
warnings), 232 files / 2,301 tests. Backed tests now cover public and private
owner reload with a decodable PNG. Full local/S3 CI for #156 is pending; all
checks for #155 are green. A12 remains OPEN for playlist continuation and the
remaining social/profile/archive/deletion criteria.


A12 continuation reproduction: a three-item saved playlist ordered “A12 short →
A11 other → A12 long” played the first item to its natural 5-second end, but the
end card offered “A12 long” from recommendations; the playback queue was empty.
The first two-item experiment was inconclusive because recommendation order
happened to match playlist order. One later attempt returned 429 before adding
the item; after waiting, add/order/read and real playback succeeded, isolating
the wrong next-item behavior. Next: TDD for playlist navigation carrying ordered
remaining items into playback, followed by this discriminating browser case.
The synthetic playlist retains the recorded three-item order for reproduction.
## A36 backup confidentiality and failure checkpoint — 2026-09-05

**A36 OPEN.** A09 is already merged as #90 (`56ef7a8`); source-dependent
A18–A23 await a sanitized source inventory. A36 is independently ready after
A03/A07 and is being completed before A37. Actual offsite storage selection
was requested; a local host rehearsal must not be labelled separate-region proof.

The retained A08 fixture ran the real backup script successfully. Inspection
exposed insufficient default permissions for database artifacts. The focused
fix applies `umask 077` before any backup file/directory creation, covering the
dump, partial/decompressed verification files, and marker as well as config.
Two regression tests failed first and then passed. No dump format, retention,
success-marker contract or deploy/migration ordering changed.

The [required real helper](../tests/backup-smoke.py) and
[complete sanitized evidence](evidence/a36-backup-local.json) record script/helper
hashes, fixture identity, archive filenames/modes, and independent verification.
Command: `python3 tests/backup-smoke.py /tmp/vidra-a08-caption-fixture-r1
/tmp/vidra-a36-smoke-r1` (arguments on one command line). Exit 0, two groups PASS,
zero skips. Real `pg_restore -l` finds core and search tables. Both configuration
members match the active files byte-for-byte, including presence of sealing and
session keys; values are never output. New directory mode is 0700 and new files
0600. A second real `pg_dump` against a nonexistent DB exits 1, leaves only a
private partial, finalizes no archive, and does not change `last_success`.

Local tests: Python22 PASS; `bash -n deploy/backup.sh`, `shellcheck -x
 deploy/backup.sh`, helper compile and diff checks PASS. Private diagnostics and
archives remain only in the disposable lab and `/tmp/vidra-a36-*`. This is a
focused A36 fix/checkpoint, not full recovery acceptance: encrypted retrieval,
matched media snapshot, independent restore and selected offsite target remain
required. Next: quiesce fixture writers, capture a matched media/DB/config set,
then encrypt/retrieve and validate it before A37 replacement-host recovery.
## A14 attachment contract checkpoint — 2026-09-05

**A14 OPEN.** [Frontend PR #150](https://github.com/yegamble/vidra-user/pull/150),
revision `0cc2278`, removes the reproduced Composer mismatch with the already
shipped API: 30 attachments, 100 MiB per file, and six Office MIME types in the
picker and validation. An overflowing selection is visibly refused as a whole
instead of silently truncating files. Server error and explicit upload retry
semantics are preserved. No OpenAPI/generated-client change was required.

[Sanitized evidence](evidence/a14-attachment-checkpoint.json) records:

- TDD: 11 failed / 3 passed before implementation; 14 focused tests passed after.
  Exact 100 MiB, one byte over, 30/31 files, existing pending counts, all six
  Office types, unsupported types and 413/415/422/503 retry behavior are covered.
- Required frontend gates passed: TypeScript, lint (0 errors, 2 existing
  warnings), icon check, 229 unit-test files / 2,303 tests, and diff checks.
- Actual Chromium against the changed frontend and real restored lab API:
  31-file refusal; 30 Word files uploaded and sent; recipient API readback has
  all 30 as `doc`; recipient UI download matches the source SHA-256.
- An actual 104,857,600-byte synthetic size fixture uploaded and sent through
  Composer. A separate approved synthetic account gets 404 for both attachment
  and conversation, preserving nonparticipant privacy.

The frontend ran in Next development mode at localhost behind a guarded proxy
to verified disposable VM `vidra-a02-20260905194815-89796`; no API interception,
response mocks, or changed rate limits were used. The first local proxy lacked
Next's HMR WebSocket and the development API default was wrong; correcting
that test setup enabled React hydration. A selector initially included Next's
route announcer and was narrowed to Composer's actual alert. One real send
returned 429 after all 30 uploads; the limiter remained unchanged and the next
run passed. The first size probe's five-second page wait timed out; a bounded
30-second readiness retry passed. These failed attempts are retained, not
counted as successful acceptance.

Production frontend build and the full backed messaging suite are **unverified**
for this slice. A14 remains open for timeline/history stability, send retry and
receipt/privacy controls, delete/report, and the configured scanner failure
lane. Next: use these persisted synthetic conversations for those probes;
do not redo the global audit. Private helpers/results remain under
`/tmp/vidra-a14-*`, with helper hashes in the evidence. Frontend PR #150 precedes
this readiness checkpoint; no merge is claimed and the A09–A40 goal stays open.

## A14 plaintext history and scroll checkpoint — 2026-09-05

**A14 OPEN.** [Frontend PR #151](https://github.com/yegamble/vidra-user/pull/151),
revision `3a69671`, is stacked on attachment PR #150. Plaintext threads previously
loaded only the newest 100 messages; only encrypted threads could page earlier.
The shared loader now uses the oldest plaintext ID with `before_id` (no offset),
merges overlapping pages once, retains loaded history on failure, and exposes
retry. The timeline anchors prepends without treating history as new mail or
jumping to the reader's last own message.

[Real history evidence](evidence/a14-history-checkpoint.json) includes the initial
browser failure: the message log had `scrollHeight=clientHeight=6428`, because
the page expanded with its history. The anchored message jumped 306px despite
passing component tests. A messaging-only viewport constraint now lets the root
flex row shrink and the existing panes scroll; header, banner and tab navigation
retain their intrinsic heights. No root layout rewrite or fixed chrome-height
assumption was introduced.

Actual Chromium checks passed at desktop, 390px and 768px: a real authenticated
keyset response added earlier history, the anchored message moved **0px**, all
105 seeded fixture rows appeared exactly once, and polling preserved the loaded
history. Phone/tablet body dimensions matched their viewports and the composer
remained visible. Phone screenshot was visually inspected. Old fixture rows were
seeded directly in the disposable database; the history reads and a newest
message send traversed the real API. This proves history behavior, not 105
individual API sends. Browser proof used the development frontend.

TDD: three new tests failed before implementation and passed after. Final gates:
TypeScript PASS; lint PASS (0 errors, 2 existing warnings); icons PASS; 230 unit
files / 2,306 tests PASS; diff check PASS. Attachment PR #150 now has all CI green,
including local/S3 backend, IPFS, channel-sync, frontend and contract checks.
Do not infer that predecessor result covers the new #151 revision; its CI must
complete separately. Required meta Compose validation also passes.

Next: explicit send retry, receipt opt-out, delete/report and configured scanner
failure acceptance using the existing synthetic actors/conversation. Those remain
unverified, so A14 and the A09–A40 goal are not complete. Temporary test servers
were stopped, generated unrelated AGENTS changes removed, and both worktrees
are clean. Private reproduction scripts/results are under `/tmp/vidra-a14-*`.
Delivery order: frontend #150 → #151; readiness #99 → this checkpoint. No merge
is claimed; the pending explicit merge-authorization request remains unresolved.

## A14 candidate acceptance PASS — 2026-09-05

**A14 runtime acceptance PASS; delivery OPEN awaiting merge authorization.**
Candidate frontend `3a69671` in PR #151 (after #150) now has evidence for MSG-01
and MSG-02. This is not a claim that the unchanged main branch is ready.
[Controls/scanner evidence](evidence/a14-controls-scanner.json) completes the
preceding attachment and history checkpoints:

- Actual browser offline mode prevented a send from reaching the server; the UI
  showed failure, SQL confirmed zero rows, and one explicit Retry created exactly
  one message. Recipient read advanced the sender's API watermark and UI Seen.
- The recipient's receipt opt-out persisted across reload and hid their watermark
  from the sender API/UI. Original preference was restored and verified.
- A live incoming message reached the other browser by polling, appeared once,
  preserved a reader's history position and left their read watermark unchanged.
  Jump to latest made it visible and advanced that watermark.
- Non-sender delete returned 404; repeated UI reports returned 204 and retained
  exactly one report/body snapshot. Sender UI delete returned 204 and the peer
  read a tombstone; the report snapshot survived deletion.
- An actual 104,857,601-byte file was refused in Composer before any upload.
  This complements the real accepted 104,857,600-byte and 30/31-file proofs.
- The repository-pinned `clamav/clamav:1.5` image ran in the disposable VM without
  host ports. It is amd64-only, so the existing QEMU support was used; no pin was
  changed. Recorded engine/image: ClamAV 1.5.4, SHA in evidence. With real scanning
  enabled fail-closed, a benign Word document uploaded and sent. Standard harmless
  EICAR returned 422, as did a benign upload with clamd stopped. Rejected uploads
  produced neither attachment rows nor orphan blobs, and the UI could not send
  them. Counts increased only for the benign accepted document (35 → 36).
  Original API flags were restored exactly and clamd was stopped afterward.

Failed attempts remain visible: an unhandled WebSocket reset killed the private
local test proxy; a real 429 interrupted delete and cleanup; and an isolated
retry initially navigated the sender incorrectly. These were corrected without
API response mocks, raised limits or fake success. Cleanup was separately
verified after the failed attempts. Only individually completed phases from the
partial runs contribute to this combined acceptance evidence.

Frontend PRs #150 and #151 both have all CI green, including the frontend gate,
contract, local/S3 backed suites, IPFS and channel sync. Local final history gates
remain 230 unit files / 2,306 tests, TypeScript, lint and icons PASS. Browser
acceptance used the real lab API and a development frontend; CI separately ran
the production frontend gate. Meta Compose validation and diff/JSON checks PASS.
No product code changed in this final evidence step. The DM scanner lane is
proven here; A28's other ingestion paths are still a separate acceptance item.

Review/merge order: vidra-user #150 → #151; vidra #99 → #100. The prior explicit
merge-authorization request remains unresolved; nothing was merged. Next ready
work should use the existing readiness dependency order and retain source/A37
external blockers. The wider A09–A40 goal is still open.

## A36 matched capture and encrypted B2 retrieval — 2026-09-05

**A36 runtime acceptance PASS; delivery remains open pending merge authorization.**
The user selected a new Backblaze B2 test bucket and explicitly authorized
uploading the client-encrypted synthetic DB/config (including test sealing and
session keys)/media archives. No DigitalOcean source data has been accessed.
The backup permission fix is green in [PR #96](https://github.com/yegamble/vidra/pull/96),
revision `fdfed44`; its merge was rejected by automatic approval review, and
explicit approval for it and subsequent acceptance merges was requested.

[Matched capture helper](../tests/backup-capture-smoke.py) stops only the
synthetic fixture's API/search/frontend writers, verifies the exact running
images and backup script hash, takes the DB/config backup, then snapshots the
actual canonical media volume with the same stamp. Services restart in `finally`.
[Offsite helper](../tests/backup-offsite-smoke.py) uploads through S3 with rclone
crypt, retrieves into a fresh private directory, and compares every archive
SHA-256 and size. [Complete final result](evidence/a36-offsite.json) includes
exact images/source revisions, both helper hashes, backup hash, capture times,
and all archive checksums. No keys, tokens or archive contents are committed.

Final commands (exit 0 each; capture PASS and three recovered archives PASS):

```sh
python3 tests/backup-capture-smoke.py /tmp/vidra-a08-caption-fixture-r1 /tmp/vidra-a36-set-r3
python3 tests/backup-offsite-smoke.py /tmp/vidra-a36-set-r3 \
  /tmp/vidra-a36-b2/private-rclone.conf /tmp/vidra-a36-b2/private-key.json \
  vidra-acceptance-20260905-a36 /tmp/vidra-a36-offsite-r3
```

The independently provisioned test bucket is `vidra-acceptance-20260905-a36`,
endpoint `https://s3.us-east-005.backblazeb2.com`. Bucket readback confirms
`allPrivate` and `SSE-B2` / AES256. Client encryption and encrypted names are
also verified by opaque object names and the actual rclone ciphertext header.
A bucket-scoped seven-day application key provides S3 read/write access;
the crypt recovery configuration stays outside the bucket, private on the
operator host. The first attempt failed because rclone tried to create an
already-existing bucket with that restricted key; `no_check_bucket=true` fixed
the configuration without granting broader privileges.

All three final archives recover byte-for-byte; the media tar contains 64 files
and the exact A06 audiovisual fixture. The preceding real `pg_restore -l` and
configuration comparison prove both schemas and exact config/key inclusion;
the failed-dump probe proves no finalized failed archive or advanced marker.
Search models are rebuildable and Redis is disposable per the existing runbook.
This certifies the synthetic local-storage set to an independent remote B2
provider, not an unselected production geographic redundancy or S3 version
retention policy. These are test archives, retained for A37; private recovery
material and downloaded archives remain under `/tmp/vidra-a36-*`.

Python22, Node3, helper compilation, production Compose validation and diff
checks PASS; no product behavior changed in this evidence slice. Next: A37
replacement-host restore from this retrieved set, with login, usable media,
reindex and measured recovery. Source migration A18–A23 still needs the SSH
host/user and read-only inventory; other selected integration decisions remain
explicitly open. The A09–A40 goal is not complete.

## A37 replacement-host recovery checkpoint — 2026-09-05

**A37 OPEN / UNVERIFIED.** Observable acceptance requires restored accounts,
sealed-secret decryption, old and new media playback, search rebuild and measured
recovery time. [Checkpoint evidence](evidence/a37-restore-checkpoint.json) records
real recovery of the approved A36 B2 set onto replacement VM
`vidra-a02-20260905194815-89796`; source VM and test runner remain intact.

The initial image import hung the replacement VM. Both Multipass stop modes
stalled; administrator intervention was requested. Once the VM was observed
stopped, restarting only that VM and importing the already-transferred verified
archive succeeded. Configuration and canonical media were extracted before
running the repository's normal `restore.sh` against its empty database.
Both migrators passed, core ledger is `127|f`, and blob verification found every
referenced object. Stack recovery took **970.73 seconds**, including the VM
interruption, from staging start to services ready. This is a measured lab
interval, not a production RTO guarantee. The data point and archive hashes are
those recorded in `a36-offsite.json`; application writes were quiesced for that
matched snapshot. Browser verification completed after the stack-ready interval.

Actual Chromium checks passed restored-account login, exact original-media
SHA-256, old-video audio/video decoding and seeking, new browser upload and
processing, and new-video decoding/seeking after its transcode job completed.
The first new-playback probe expected HLS before the job completed and observed
original-file playback instead; that failed probe remains in the evidence.
The bounded retry waited for actual `transcode_jobs.state=done` and passed.
Search evidence deletes only a synthetic video's restored index entry, restarts
only the replacement API, verifies a rebuilt reconciliation entry, and finds
and opens the video through the browser search UI. The recorded search event
confirms `source=search`, excluding a local fallback as proof of index recovery.

Remaining blocker: decryption of a restored sealed fixture is **unverified**.
A temporary synthetic MFA enrollment was captured locally and removed from the
source after capture. Automatic approval review rejected uploading that newer
archive because it includes a new temporary TOTP secret beyond the previously
approved payload. Explicit approval for that upload remains pending. No new
MFA archive has been uploaded. Next experiment: after approval, encrypt/upload
and retrieve that matched set, restore it on this replacement VM, then prove
MFA authentication using the recovered sealing key. Keep the original failure
and successful retry evidence; do not rerun blank-host provisioning.

Private scripts/logs and recovery material remain under `/tmp/vidra-a37-*`;
the checkpoint records helper hashes, not credentials or archive contents.
This evidence checkpoint depends on A36 PR #97 (which depends on #96), and does
not close A37 or the wider A09–A40 goal.

A14 delivery update: merge authorization is now explicit. Frontend #150 is
merged; #151 is retargeted to main with CI rerunning. This conflict resolution
preserves both the complete A14 and the independent A36/A37 evidence.

## Merge delivery checkpoint — 2026-09-05

The user explicitly instructed “make sure we're merging to main and push as we
go.” Merge authorization is resolved. A10 implementation PRs core #160 and
frontend #152/#153 are merged after green checks; the prior runtime PASS remains
supported by its individual evidence. A11 chapter recovery frontend #154 and A12
session restoration frontend #155 are also merged; their broader acceptance
items remain open as recorded. A36 offsite proof meta #97 and the A37 checkpoint
#98 are merged. A14 frontend #150 is merged; its dependent #151 is retargeted to
main and its new checks are running. Completed base branches are removed only
after dependents are retargeted. No production deployment or release occurred.

A14 final delivery: frontend #150 and #151 are now merged after all gates passed.
The combined runtime acceptance remains PASS; this evidence PR completes its
delivery record once its final validation passes and it is merged.

A12 playlist continuation is fixed in [frontend #157](https://github.com/yegamble/vidra-user/pull/157),
revision `9c2a0e3`. Watch links and end-card navigation retain a playlist id;
the current viewer reauthorizes a fresh saved-order read. Unavailable reads
show retry and suppress unrelated recommendations. The last item stops.
Real Chromium proved the discriminating three-item order after reload, two
natural five-second endings, manual/countdown navigation with retained context,
and final completion after seeking near the end of the long item. Focused tests
pass 24/24; full suite passes 233 files / 2,307 tests, TypeScript/icons pass,
lint has zero errors and two existing warnings. An initial unrelated StudioContext
timeout passed in isolation and then in the full one-worker rerun without test
changes. Temporary harness navigation/role/duplicate-label errors were corrected;
the instrumented final run passed with no 429. Production build and the two
corrected cover Chromium tests also pass. #157 CI is pending. Remaining A12
social/profile/archive/deactivation/deletion criteria stay open.

Final implementation gates: frontend #156 and #157 both pass all checks,
including production frontend, local/S3 backed suites, contract, channel sync
and IPFS. The final merge/branch cleanup is being completed under the user’s
explicit instruction. A12 remains open for the individually listed social and
account lifecycle criteria; green library checks do not certify those slices.


## A12 social deletion recovery — 2026-09-05

**A12 OPEN; SOC-02 comment deletion recovery PASS.** Observable success for this
focused slice: a failed Delete visibly explains the failure and retains the
comment, an explicit retry reaches the service, and a fresh API read and UI reload
agree with the confirmed deletion. [Frontend #158](https://github.com/yegamble/vidra-user/pull/158),
revision `a220c9e`, uses the existing Alert and error mapper; authorization and
server error semantics are unchanged. No contract, SQL or generated-file edits.

[Sanitized evidence](evidence/a12-comment-delete.json) records the actual Chromium
reproduction: offline Delete re-enabled the button but produced no alert. TDD
also failed first (1 failed / 17 passed). The correction passes 18 focused tests.
Browser checks pass against both development and **production-built** frontend,
using the existing disposable restored API/PostgreSQL. Browser offline mode
caused the real transport failure; fresh API readback confirmed the row remained.
Explicit retry returned 204; deletion persisted after reload. Three checks pass
in each final run, zero skips. The error screenshot was visually inspected.
The backed threaded-comment regression now covers the same failure/retry and
preserves its original reply-chain assertions.

Actual Node 24.20.0 gates pass: TypeScript, icons, lint (zero errors, two existing
warnings), 237 unit files / 2,336 tests, production build, and diff check. Meta
production Compose config-q passes with dummy configuration. All frontend CI
checks pass, including contract, frontend, local/S3 backed, IPFS and channel sync.
Failed attempts remain recorded: wrong notification route in the helper (404),
unchanged rate limiting (429), initial implementation state placed in the wrong
component (caught by tests), and an interrupted Node 25 diagnostic unit run.
The misleading Homebrew node@24 symlink resolves to Node 25; cached Node 24.20.0
was used for the final gates and production browser run. No tests were weakened.

The three existing synthetic actors also posted a parent and reply via browser;
a fresh API read proved parent_id and reply author identity. Recipient reads did
not complete, so notification delivery is **unverified**. Static inspection of
core handleCreateComment finds only video-owner notifications, with no separate
reply/mention path. This is a separate A12 finding, not fixed in this small PR.
Next: reproduce intended reply/mention recipients with those actors, then
ratings/preferences/unread, reports/mutes/blocks, and profile/archive/deactivation/
account deletion. Deleted-account tombstones remain unverified. Prior library
and playlist proofs are retained; no global audit was repeated.

Delivery order: frontend #158, then this evidence PR. Merge is authorized by the
user's final instruction; no release or production deployment is authorized.
Private helpers/results stay under /tmp/vidra-a12-{social,delete}-*. The complete
A12 acceptance remains open even after this focused fix is merged.


A12 social delivery: frontend #158 is merged as `c0160dc` after all CI passed.
Local and S3 backed lanes each report **100 passed / 11 skipped**; skipped
workflows remain unverified and do not close other A12 criteria. The independent
production browser run above has three passing checks and zero skips. Frontend
work branch cleanup follows the confirmed merge. Evidence PR #104 records this
bounded result; the complete A12 item remains OPEN.

## A12 social notification recipients — 2026-09-05

**A12 OPEN; the SOC-02 reply-recipient criterion PASSES.** Observable success for
this focused slice: when B replies to A's comment on C's video, A is told — told
that it was a reply, by whom, and where — while C's existing owner notification
is untouched and one reply never produces two. [Core #161](https://github.com/yegamble/vidra-core/pull/161),
revision `2dd2f88`, and [frontend #159](https://github.com/yegamble/vidra-user/pull/159),
revision `c9988a9`. Authorization, best-effort semantics and error shapes are
unchanged; no migration (`notifications.type` is unconstrained TEXT, latest
migration stays 0127) and no hand-edited generated files.

The previous record's static reading is confirmed, then reproduced live. Built
from `origin/main` `b7a2755` and run against the same database and the same three
synthetic actors, bob's reply to alice left **alice with 0 notifications** while
carol, the video's owner, held 2. That failing run is kept. The correction adds
one `comment_reply` type and one `CommentReplyRecipient` statement that keeps
every selection rule in SQL — local parent author only, no tombstones, no
self-notification, active account, mute and block excluded in **both** directions
— following the 0101/0103 set-based idiom rather than an N+1 of Go lookups.
`handleCreateComment` resolves the reply recipient first and skips the owner's
`comment` notification only when the owner IS that recipient.

[Sanitized evidence](evidence/a12-social-notifications.json) records the live
proof: alice now holds exactly one `comment_reply` naming a12bob with the video
and the reply's comment id; carol still receives a `comment` for the parent AND
the reply; bob replying to himself notifies nobody; carol, when she is both the
video's owner and the parent's author, receives **one** notification for one
reply, and it is the reply. Mute, alice-blocks-bob and bob-blocks-alice each
deliver nothing, and a control run with every relationship lifted delivers again
— so the exclusions, not a broken fixture, are doing the work. Unread counting
and read-marking use the untouched shared endpoints: 2 → 1 on mark-one → 0 on
read-all, with the row's read flag true. The UI half ran in real Chromium
151.0.7922.34 against the **production-built** frontend: after a hard reload
alice's Inbox reads "a12bob replied to your comment on “A12 reply thread”", never
"commented on", and the row navigates to that video's watch page. The screenshot
was visually inspected.

TDD failed first in every lane. Core: with the reply path stubbed to its
pre-change no-op, "bob has 0 notifications, want 1" and "newest notification =
“comment”, want “comment_reply”". SQL: deleting the mute/block clauses made
the real-PostgreSQL test fail on all three relationship cases, and it passes
again with them restored. Frontend: 2 failed / 3 passed, with the unknown type
falling through to "started following your channel" — the same failure class as
the historic `new_video` bug — plus a missing preference label.

Gates: core `make ci` passes uncached (fmt-check, vet, migrate-lint,
openapi-verify, sqlc-verify, test-race), and `go test -tags=integration
./internal/store/... ./internal/federation/...` passes against real PostgreSQL 16
at schema 127 with Redis. Frontend passes TypeScript, icons, lint (zero errors,
two existing warnings), **237 files / 2338 tests**, and the production build.
**Node 24.20.0 is not present on this machine** — nvm carries 24.4.1 and 25.x,
and the Homebrew `node@24` symlink still resolves to Node 25 — so gates ran on
24.4.1, which satisfies `.nvmrc` "24", `engines >=24` and CI's `node-version:
"24"`. Per vidra-user's AGENTS.md the local e2e suites were **not run**; CI runs
them and both backed lanes, IPFS and channel-sync all pass on #159.

**Docker was unavailable for the whole slice**: its engine had crashed with "no
space left on device" because the host disk is 100% full, and restarting Docker
Desktop did not recover it. The lab was rebuilt without Docker on native
PostgreSQL 16 + Redis with the API and the production frontend run directly.
Clearing the regenerable Go build cache was required before the race build would
link; before that, `make ci` reported spurious "[build failed]" for packages that
passed individually. Other failed attempts are recorded in the evidence: the
wrong login field (`login` instead of `identifier`, 422), comments 404ing until
the lab video left `draft`, a CORS refusal from `127.0.0.1` vs `localhost`, and
Playwright's `networkidle` never settling against this app's polling.

Two items are deliberately NOT done. **Mention notifications are not a shipped
capability** and were not built: vidra-user's "mention" is a client-derived
`@handle` prefix computed from `parent_id` (`lib/comments.ts` `replyMention`) —
plain non-linked text, no picker, no linkification, no delivery promise — and
core has no mention feature at all. And a reply notification links to the video,
not the comment: no per-comment anchor exists, and replies sit inside a collapsed
"View N replies" control, so a `#comment-<id>` fragment would target a node that
is not in the DOM.

Two unrelated findings. `NotifyComment` — the older owner notification — does
**not** consult mutes or blocks, so an account the owner muted or blocked still
reaches their inbox by commenting on their video; it was left exactly as it was
rather than changed under an unrelated slice. And an unknown notification type
falls through `describeNotification`'s final return and renders as "started
following your channel"; a neutral default arm would make that class of drift
plain rather than wrong.

Register rows are unchanged. The reply-recipient criterion belongs to **SOC-02**
(comments/replies/ratings, mentions, reports and notification preferences), not
SOC-01, and SOC-02's remaining criteria — ratings, reports, the mute/block
surfaces themselves, and mentions — are untouched, so the row stays UNVERIFIED.

Delivery order: core #161 (contract owner, all checks pass, ready for review),
then frontend #159, then this evidence PR. #159 stays **draft on purpose**: its
`contract` job regenerates from `vidra-core@main` and wants to remove the
`comment_reply` lines until #161 merges; every other check on it passes. Nothing
is merged here and no deployment is authorized. Next: deep-link a notification to
its comment (anchor + thread auto-expansion), then ratings/reports and the
mute/block surfaces, then profile/archive/deactivation/account deletion. The
complete A12 acceptance remains OPEN.

## A12 social mute/block privacy — 2026-09-05

**A12 OPEN; the SOC-02 "blocked/muted content" and "deleted/tombstoned parent"
criteria PASS.** Observable success for this focused slice: an account C has
muted or blocked — or that has blocked C — cannot reach C's inbox by commenting
on C's video, cannot appear in C's comment thread on a hard reload, and the two
surfaces round-trip and read differently; and a parent comment that is gone,
by either of the two conventions, leaves neither text nor a notification behind.
[Core #162](https://github.com/yegamble/vidra-core/pull/162), revision `a0a96a3`,
and [frontend #160](https://github.com/yegamble/vidra-user/pull/160), revision
`a90d697`. Authorization, best-effort semantics and error shapes are unchanged;
no migration (latest stays 0127), no route or response-shape change, and no
hand-edited generated files.

The finding the last slice deliberately left alone is now reproduced live rather
than read. Built from `origin/main` `cd8a12e` against the same database and three
fresh synthetic actors, bob's comment on carol's video notified carol **every
time** — with carol muting bob, with carol blocking bob, and with bob blocking
carol, deltas 1, 1, 1, indistinguishable from the no-relationship control's 1.
The muted account reached the inbox of the person who muted it, carrying the
comment id back to the comment the mute had hidden. That failing run is kept. The
correction adds one `CommentVideoOwnerRecipient` statement that keeps every
selection rule in SQL — mute, block in **both** directions, tombstoned comment,
federated comment, self-comment, inactive or deleted owner — following the
0101/0103 idiom `CommentReplyRecipient` and `NotifyFollowersOfNewVideo` already
follow. `NotifyComment` now resolves its own recipient, mirroring
`NotifyCommentReply`; it has to, because the caller cannot see the relationship.

A second, larger gap turned up in the browser and is fixed in the same slice.
**The watch page fetched its comment list anonymously.** `CommentsSection` fired
its effect on mount with deps `[videoId, reloadKey]`, but the access token is
restored asynchronously from the refresh cookie, so the request carried **no
`Authorization` header at all** — the mute/block filter is per-viewer and applied
by the server, which therefore had no viewer to filter for and handed the muted
author's comments back to the person who hid them. The effect never re-ran, so
the mute held only for as long as the client-side filter survived: mute, and the
comment vanishes; reload, and it is back. The effect now waits for the session to
settle, and that single change is what makes a mute or a block hold across a
reload at all.

The shipped promise was established before anything was called a defect, and it
is narrow: **a mute one-directionally hides the muted account's content from the
muter, and a block does everything a mute does plus cuts direct messaging in both
directions — neither stops the muted or blocked account from commenting on your
video, replying to you, or reading your comments.** That was confirmed live and
left alone: while blocked, bob still saw the whole thread and still posted a
comment (201) and a reply (201), while `POST /conversations` answered 403 in both
directions.

[Sanitized evidence](evidence/a12-mute-block.json) records the proof. On the
fixed build the same four cases give 0, 0, 0 and **1** — the control with every
relationship lifted still delivers, so the exclusions and not a broken fixture
are doing the work. In real Chromium against the **production-built** frontend:
carol muted bob from the comment's own overflow menu, and after a HARD reload the
thread read "Comments (2)" with bob's comment and his reply both gone and alice's
untouched; `/settings/mutes` listed him and `GET /me/blocks` was empty, so the
state was unambiguously the mute; unmuting from that page restored the comment.
Blocking repeated the whole round trip: the control reads "Blocked", and after a
hard reload the server has filtered the comment out — "Comments (2)" again, with
alice untouched — while `/settings/blocks` lists him and `GET /me/mutes/accounts`
is empty. That page reads "Accounts you have blocked. Neither of you can send the
other a direct message." against the mutes page's "Their comments are hidden from
you." — different routes, different headings, different promises. With bob blocked, his fresh
comment left carol's Inbox at four rows after a hard reload; after unblocking,
the same action produced a fifth, "bobu3 commented on …". Screenshots were
visually inspected.

The tombstoned parent has **two conventions behind one word** and both were
exercised. An author deleting their own comment is a hard delete, and
`comments.parent_id` is `ON DELETE CASCADE` (0026), so replies go with it —
alice's deletion removed her comment, bob's reply and the row itself, and her own
`comment_reply` notification went too (`notifications.comment_id` is also
`ON DELETE CASCADE`, 0018), so nothing survives pointing at deleted content. The
"[deleted]" placeholder with the thread preserved is the **account**-deletion
path (0057): dana hard-deleted her account, and her comment came back with
`deleted=true`, body `[deleted]` and an anonymised `deleted-<8 random>` handle —
never her username — while bob's reply kept its own body and attribution under
it. Carol's watch page renders exactly that. Tombstoning raised no notification
for anyone, and alice replying **to** the tombstone raised none either.

TDD failed first in every lane. Core HTTP: `owner has 1 notifications after
"ada muted bob", want 0`, and the same for both block directions, with the
control passing. SQL: replacing the two `NOT EXISTS` clauses with `AND TRUE` and
regenerating sqlc made the real-PostgreSQL test fail on exactly those three cases,
and it passes again with them restored. Frontend: three failures, including
`getVideoComments` being called while the session was still restoring. The third
covered a second change — blocking removing the author's comments at once, as
muting does — which was **reverted**: repo CI showed `e2e/blocks.spec.ts` ("The
comment stays (a block doesn't hide content)") and `e2e-backed/blocks.spec.ts`
both pin the current behaviour, and editing an existing e2e spec to make a change
fit is exactly what vidra-user's AGENTS.md forbids. Whether the row should also
go immediately is a product call for its owner; it is cosmetic either way, since
the server hides it on the next load regardless.

Gates: core `make ci` passes (exit 0; fmt-check, vet, migrate-lint,
openapi-verify, sqlc-verify, test-race; 79 packages, 0 failures), and
`go test -tags=integration ./internal/store/...` passes against native
PostgreSQL 16 at schema 127. Frontend passes TypeScript, lint (zero errors, two
pre-existing warnings), icons, **237 files / 2340 tests**, and the production
build, on nvm Node 24.4.1 (24.20.0 is still absent from this machine; 24.4.1
satisfies `.nvmrc` "24", `engines >=24` and CI's `node-version: "24"`). Per
vidra-user's AGENTS.md the local e2e suites were **not run**. On #162 the
`ipfs-integration` lane timed out once on `TestIntegrationPublicVideoRoundTrip`
(300s) and was re-run; this change touches nothing IPFS-related. Docker remains
unavailable, so the lab is again native PostgreSQL + Redis with the API and the
production frontend run directly.

Failures worth keeping. The first "baseline" run silently hit the **fixed**
binary: `pkill` matched an absolute path while the process had been started as
`./vidra-api`, so the old process kept port 8088, the baseline died with "bind:
address already in use", and `healthz` still answered 200 — caught only because
the baseline reported the fixed numbers. The first browser walkthrough tripped
the shipped 120 req/min rate limiter (35 × 429), which put the comment list into
its error state and produced a false negative; it was re-run with cool-downs
between phases and a hard failure on any 429, rather than by raising the limit.

Four unrelated findings. The "fetch on mount, before the session is restored"
shape may apply to other client-side reads whose answer is viewer-scoped; not
swept here. Mute and Block sit in the same overflow menu and behave differently
on the spot — Mute removes the comment, Block leaves it reading "Blocked" — and
two e2e specs pin the Block half, so it needs a ruling rather than a patch.
`/settings/blocks` under-promises — it mentions only direct messages,
while the contract says a block also hides the blocked account's videos and
comments from the blocker. And a notification **about** a comment outlives that
comment's account-level tombstoning: nothing leaks (no body is stored, the actor
is anonymised) but the inbox row remains, pointing at a "[deleted]" placeholder.

Register rows are unchanged. This slice closes SOC-02's "blocked/muted content"
and "deleted/tombstoned parent" criteria; its remaining criteria — ratings,
report resolution, and refreshing unread counts and notification preferences —
are untouched, so the row stays UNVERIFIED.

Delivery order: core #162 and frontend #160 have **no contract dependency** on
each other (core changes no route and no response shape, so vidra-user needs no
regenerated client), then this evidence PR. Nothing is merged here and no
deployment is authorized. Next: ratings and report resolution with the
notification-preference refresh, then per-comment deep links, then mentions. The
complete A12 acceptance remains OPEN.

## A12 social ratings, reports and preferences — 2026-09-06

**A12 OPEN; SOC-02 PASSES and its register row flips.** Observable success for
this slice: a viewer's own rating is theirs, survives a hard reload and can be
changed or removed; a notification type turned off in the UI actually stops
delivery and stays off; the bell never lies about how many unread notifications
exist; and a report travels from the reporter through the moderator's queue to a
resolution the reporter is told about and the reported party never hears of.
[Frontend #161](https://github.com/yegamble/vidra-user/pull/161), revision
`1972ac0`. **vidra-core is untouched** — three of the four criteria pass exactly
as shipped, so there is no core PR, no contract change, no migration (latest
stays 0127) and no hand-edited generated file.

One gap was found, and it was found by reading the ratings control against the
defect [#160](https://github.com/yegamble/vidra-user/pull/160) had just fixed
next door. **`RatingControls` read the rating summary anonymously.** Its effect
had deps `[videoId]` and fired on mount, but `my_rating` is per-viewer and
resolved by the server from the request's bearer token, which is restored
asynchronously from the refresh cookie — so the read carried no `Authorization`
header, the server answered `my_rating: null`, and the effect never re-ran. That
failing build was kept and run: on a production build with only that file
reverted, **6 of 15 SC1 browser assertions failed**, with A's own like showing
`aria-pressed=false` after a hard reload while `GET /videos/{id}/rating` as A
answered `"like"`. It is not merely cosmetic. The control toggles by comparing
the click to the `my_rating` it holds, so on a freshly loaded page the
clear-my-rating click became a *set*: the baseline's removal step left the
dislike in place and the run drifted to 1 like / 1 dislike. **A viewer could not
take their own rating off a page they had just loaded.** The correction is the
same one `CommentsSection` took: wait for the restore to settle, and re-read when
the session changes. The component had **no test file at all**, which is how this
survived; it has one now.

[Sanitized evidence](evidence/a12-ratings-reports-prefs.json) records the proof —
**69 API assertions and 56 browser assertions, none failed, and no 429 in either
run**. Ratings are video-level only, and that is confirmed rather than assumed:
`/api/v1/videos/{id}/rating` is the sole rating path in the whole OpenAPI
document, so there are no comment ratings to accept. A likes (1/0, mine=like),
flips (0/1 — the aggregate moves rather than double-counting), B likes
independently (1/1, and A's own read still says dislike), A removes (1/0, B's
survives, and a second DELETE is idempotent). In Chromium every one of those
states survives a hard reload, in A's context and in B's separately. **Two
shipped promises, as shipped and not as preferred: nobody can learn who rated —
`/videos/{id}/rating` is the only rating route, a probe of `GET
/videos/{id}/ratings` as the admin is 404, and every read of `video_ratings` in
the codebase is either a COUNT or the caller's own row, so no response shape
names a rater; and an owner MAY rate their own video — PUT as the owner is 200
with the count incremented, the owner's capsule is enabled like anyone else's,
and no self-rating guard exists.** A signed-out visitor sees the counts with both
buttons `disabled` and a "Sign in to rate" link, and the API answers **401** to
an anonymous PUT or DELETE.

Preferences and counts were driven from the UI, not the API. A turned **Replies**
off on `/settings/notifications`; it was still off after a hard reload, `GET
/me/notification-prefs` agreed and the `notification_prefs` row read
`enabled=false`; B's next reply created **no** notification, and re-enabling made
the one after that deliver. The same round trip ran for C's owner **Comments**
type. An unknown type still rejects the whole update with 422. The per-channel
follow bell (`PUT /channels/{handle}/follow/notifications`) is a different route,
store and surface — **out of scope**, and named as such. For counts, with a real
backlog of four the bell's accessible name and badge both equalled
`/me/notifications/unread-count`; marking one read took the shared endpoint to 3
and the bell agreed **after a hard reload**; read-all zeroed both, left no unread
row, and left every row in place. No endpoint was re-implemented.

**What "resolve" does is now precise: it closes the report and nothing else.** A
reported C's video from the watch page and B's comment through the same contract;
both reached M's queue with the right target and the right reporter, and M got a
`new_report` for each. M accepted one from the browser with an internal note:
status `accepted`, `resolved_at` set, note stored, out of the open queue and into
the resolved one, with API readback agreeing. A's inbox reads "A moderator
accepted your video report" — the outcome in words — and never names the
moderator (`actor_id` is deliberately null on that type) or leaks the note. C
holds **zero** report-typed notifications and no row carrying a report id; B, whose
comment was reported, the same. **Neither is told a report exists, let alone who
filed it.** And accepting changed nothing about the content: the video is still
200, still `published`/`public` with zero `video_blocks` rows, still on screen for
everyone, and the reported comment is still in the thread. Taking content down is
a separate control in the same pane (`POST /admin/videos/{id}/block`, or admin
comment deletion) that a moderator may use with or without resolving.
`DELETE /admin/reports/{id}` was cheap and is included: 403 for a non-admin, 204
for the admin, gone from the queue, and its `report_resolved` notification
cascades away. Screenshots were visually inspected.

Gates: frontend TypeScript, lint (0 errors, the same 2 pre-existing warnings),
icons, **238 files / 2346 tests** — up from 237/2340 by exactly this slice's six
new tests — and the production build, on nvm Node 24.4.1 (24.20.0 is still absent
from this machine). TDD failed first: the new
`components/RatingControls.test.tsx` ran **2 failed / 4 passed** against the
unchanged component, both failures the session-gating cases. Core `make ci` is
**not required and not claimed** — vidra-core is unchanged — but the named
#161/#162 tests were run and pass, including the tagged real-PostgreSQL
`TestCommentReplyRecipientOnRealPG` and `TestCommentVideoOwnerRecipientOnRealPG`
at schema 127. Per vidra-user's AGENTS.md the local e2e suites were **not run**.
Docker is present again but holds no images or volumes, so the lab stayed native
PostgreSQL 16 + Redis with the API and the production frontend run directly.

Failures worth keeping. **`next start` cannot serve this repo's
`output: "standalone"` build**: the JS chunks come back as `text/plain`, Chromium
refuses to execute them, and the watch page sat on "Loading video…" having issued
two API calls — a walkthrough against that server would have failed everything
for the wrong reason. The shipped auth limiter is **10 requests/minute per IP**
on login/register/claim-owner, separate from the 120/min general budget, and the
seeder spends most of it; the run now waits out a fresh window and signs each
actor in exactly **once**, rather than raising the limit. One watch-page load
costs ~14 API calls, so an early paced attempt still tripped the general limiter
mid-SC1; document loads are now budgeted with a window cool-down every fourth,
and any 429 voids the run. Registration on a fresh instance is `403
owner_claim_required` until the owner is claimed, so M is now created through the
real first-run bootstrap rather than a SQL role bump. Two harness bugs were
corrected rather than the app: the bell correctly reads plain "Notifications"
with no badge at zero, and "the reported party is never told" needed precise
assertions instead of a `/report/i` match that hit page chrome.

Four unrelated findings. The **"fetch on mount, before the session is restored"**
shape has now been found twice, both times on viewer-scoped reads behind
`optionalAuth`; a sweep of the rest would be cheap and is not done here.
`NotificationsView` and `NotificationsBell` keep independent unread counters, so
marking a row read on `/notifications` leaves the header bell stale until the next
route change — both agree with the server after any navigation, and both were
correct after every hard reload here, but they can disagree on-page.
`describeNotification` returns `href: "#"` for `report_resolved`, the only type
with nowhere to go: a reporter told their report was accepted cannot reach it,
because there is no reporter-facing report view at all. And the queue's "Block
video" button sits in the same action bar as Accept/Reject with no grouping, so
"resolve the report" and "take the content down" read as peers when they are
independent.

**The SOC-02 register row flips to PASS (candidate; unmerged)**, its criteria
closed across three slices: reply attribution and intended-recipient notification
(#161/#159), blocked/muted content and the deleted/tombstoned parent (#162/#160),
and ratings, preferences, unread counts and report resolution (this one).
*Mentions* appear in the row's title but are **not a shipped capability** — core
has no mention feature and vidra-user's "mention" is a client-derived `@handle`
prefix on a reply, plain text with no picker, no linkification and no delivery
promise — so there is no mention behaviour to accept; that is recorded, not
counted as a pass. Delivery order: frontend #161 alone (no contract dependency,
`contract-ci` regenerates cleanly from `vidra-core@main`), then this evidence PR.
Nothing is merged here and no deployment is authorized. **A12 remains OPEN**:
AUTH-05 — profile/privacy, email/password changes, deactivation/deletion and the
account archive — is untouched, and is the next slice.

## A12 profile, credentials and archive — 2026-09-06

**A12 stays OPEN and the AUTH-05 row does NOT flip.** This is the first half of
AUTH-05 — profile/privacy, password and email changes with re-verification, and
the account archive; deactivation and deletion are the next slice. Two of the
four capabilities pass on real evidence. **The other two cannot pass, because
they do not exist.** [Core #163](https://github.com/yegamble/vidra-core/pull/163)
(`e4bde3b`) and [frontend #162](https://github.com/yegamble/vidra-user/pull/162)
(`32f6b57`) each carry one small, TDD-first fix; no migration (latest stays
0127), no hand-edited generated file.
[Sanitized evidence](evidence/a12-profile-archive.json) records **224 API
assertions and 60 browser assertions, none failed, and no 429 in either
walkthrough**.

**There is no password-change endpoint and no email-change flow anywhere in the
product.** That is proven, not inferred: eleven plausible password routes and
twelve email routes were probed as the signed-in owner and every one answers
404/405; `PATCH /auth/me` cannot set a password (the stored hash is
byte-identical afterwards) and rejects an `email` field with 422; **`PATCH
/admin/users/{id}` as the instance owner also refuses an email (422)** — the
admin surface can only toggle `email_verified`. In Chromium, `/settings` and
`/settings/security` offer no such control either. So an account's address is
fixed at registration and cannot be moved by anyone, and the only password
rotation is the **forgotten**-password flow: `POST /auth/password-reset` (always
202, enumeration-safe) → a single-use expiring token delivered out of band →
`POST /auth/password-reset/confirm`. Re-verification is by **mailbox
possession**, never by the current password. Those two facts compound: a user who
loses the mailbox loses the ability to change their password, and cannot change
the address either. On an instance with no working SMTP, password rotation is
simply impossible.

What *is* shipped passes end to end, and the mail path was exercised **two
ways**, so this is not blocked on the AUTH-03/A05 SMTP-selection gate. The
shipped dev capture seam (`DEV_MAIL_CAPTURE_ENABLED`, `GET
/api/v1/dev/email-token` — registered only outside production, logged as a loud
boot warning, tokens in memory only, deliberately absent from the OpenAPI
document) served the tokens for the main runs; and a **real SMTP delivery** was
proven separately against a throwaway Mailpit sink with `MAIL_ENABLED=true` and
the capture seam **off** — 10 assertions, the dev seam 404, the message
delivered to the right address from the configured `SMTP_FROM`, and the token
lifted out of the real message body verifying the account. The reset itself: a
wrong token 400 and a too-short password 422 both leave the hash untouched, the
real token is 204 and changes it, a replay is 400, the old password is then 401
at login and the new one 200.

**What a password change does to your other sessions, exactly.** `ResetPassword`
revokes every session row, so all refresh tokens die at once — a second Chromium
context signed in *before* the reset showed "Your session has ended." after a
hard reload, with no settings form rendered, and so did the first. But
`requireAuth` verifies the access JWT alone and never re-checks a session row,
so an **already-issued access token keeps answering 200 for the rest of its
`JWT_ACCESS_TTL` (default 15 minutes)** — proven live, refresh 401 and access 200
in the same breath. "Signed out everywhere" is true of refresh tokens instantly
and of access tokens within fifteen minutes. The deletion slice must say which
token it means.

Profile and privacy pass. **"Unlisted" is a discovery opt-out, not an access
control**: with it on, A's video leaves the anonymous feed *and* B's, she leaves
`/search/accounts` and her channel leaves `/search/channels`, while the direct
video, channel and profile URLs all still answer **200 anonymously** — and
turning it off restores the feed. **`profile_public` is a different control and
is privacy-by-default**: `users.profile_public` is `NOT NULL DEFAULT FALSE`
(migration 0091) and registration does not opt in, so a brand-new account's
profile is 404 to everyone until its owner ticks "Make my profile public" —
proven on an account that never did. Display name, bio and a real decodable
96×96 PNG avatar all persist, are confirmed by independent API reads *and* the
database, and survive a hard reload in the browser; B sees the new public values
on A's profile page and **never her email**. Every mutation was attempted by the
wrong actor: `PATCH /auth/me` is self-scoped so B's attempt edited *bob*, B's
`PATCH /admin/users/{A}` is 403, an anonymous PATCH is 401, an over-long name is
422 and changes nothing, and B's avatar upload leaves A's bytes identical. The
**vidra-search** facet is honestly unverified — that service is not running — but
the core half is proven: with `SEARCH_SERVICE_URL` set, toggling unlisted
enqueues a `user.suppress` outbox event carrying `unlisted:true`, and un-listing
enqueues the restoring one.

The archive passes, and its contents are recorded by field name rather than
claimed. Ten top-level sections, all of them present, and **what is missing is
named**: media bytes (each video carries an `original_download_url` instead —
documented v1), ratings, mutes and blocks, messages, sessions and devices,
OAuth/ATProto links, player and messaging preferences, search history, donation
addresses, and any moderation or audit history. No credential material of any
kind. The lifecycle is complete: 404 before any request, 202 pending, **409 while
one is in flight**, done with an expiry stamped, an attachment download, a
re-request that produces a **new job id and replaces** the previous archive, a
forced expiry that gives **410** while the status still reads 200 with
`download_ready:false`, and a fresh request downloadable again. **IDOR is
structurally impossible rather than merely guarded** — `/me/export` and
`/me/export/download` take no id parameter, and there is no admin route to
another user's archive either (404); B's download is *bob's* archive with A's
address nowhere in it. Both halves are operator kill-switchable and independent
(`user_export_enabled` off → 403 `feature_disabled` while import still works, and
vice versa; a normal user gets 403 on the switches).

**Archive import IS a shipped capability** (`POST /api/v1/me/import`, with a card
on `/settings`) and it round-tripped: A's archive into a fresh actor applied the
profile, created the playlist with its one locally-matched item, re-created the
follow of a local channel and applied one notification preference, while
`skipped_sections` named the five it cannot restore — and the readback confirms
the **username and email were never imported**, no channel, comment or video was
created, and a re-import duplicates the playlist while the follow stays one row.
The whole thing was then driven from Chromium: the card polls honestly, offers
"Download archive" when the job finishes, states the expiry in words, and the
captured `vidra-account-export.json` is Alice's with no credential material; the
import through the real file input reported *"Profile: display name and bio
applied / Playlists: 1 created, 1 items added / Follows: 1 created /
Notification preferences: 1 applied / Not importable from an archive: Channels
(1), Comments (1), Saved videos (1), Videos (2), Watch history (1)"*.

Two defects, both found by reading the summary against the database. **The
import reported `follows_created` for follows it did not create**: `FollowChannel`
is `:execrows` with `ON CONFLICT DO NOTHING` — the query's own comment says the
count exists so callers can tell a new follow from an existing one — but
`ImportArchive` discarded it and incremented unconditionally, so a re-import
claimed a follow with exactly one row in `channel_follows`. The **in-memory fake
mirrored the bug** (it always answered 1), which is how it survived; it now
mirrors the SQL. Red first: `re-import reported follows_created = 1, want 0`.
And the frontend then **named the wrong cause** — `", N skipped (channel not on
this instance)"` told an importer whose follows were already in place that the
channels were missing. Both fixed, both with a failing test first.

Gates: core `make ci` **passed** (fmt-check, vet, migrate-lint, openapi-verify,
sqlc-verify, test-race) plus the tagged `internal/store` and `internal/account`
integration lanes against real PostgreSQL 16 at schema 127; frontend TypeScript,
lint (0 errors, the same 2 pre-existing warnings), icons, **238 files / 2348
tests** — up from 237/2346 by exactly this slice's two new tests — and the
production build, on nvm Node 24.4.1. Core CI is **all green**:
`ipfs-integration` failed once on `TestIntegrationPublicVideoRoundTrip` timing
out at 300s — a lane this diff (`internal/account` plus an OpenAPI description)
cannot reach — and passed on a re-run in 1m53s, so core#163 is marked ready. **`contract-ci` on the frontend PR is
expected red until core#163 merges** — it regenerates `lib/api/generated.ts` from
`vidra-core@main` and this branch carries the regen for an unmerged spec change;
that PR stays draft until then. Per vidra-user's AGENTS.md the local e2e suites
were **not run** — and CI earned its keep for it: the first push turned the
`frontend` lane red on `e2e/account-data.spec.ts`, which pins the import summary
line character for character and so moved with the copy fix. The spec now asserts
the corrected string, exactly as strictly as before; vitest was green throughout,
only the Playwright expectation was stale. With that corrected the whole lane is
green — `frontend` (the canonical gate, e2e included) plus all four backed lanes
— and `contract` is the only red check left, for the ordering reason above. SC5 no-regression: the named tests from all three merged A12
slices pass, including the tagged real-PostgreSQL
`TestCommentReplyRecipientOnRealPG` and `TestCommentVideoOwnerRecipientOnRealPG`.

Failures worth keeping. **The frontend could not reach the API at all on the
first browser attempt**: `CORS_ALLOWED_ORIGINS` defaults to
`http://localhost:3000`, so every call from the lab's `127.0.0.1:3100` origin
failed preflight and the sign-in form reported "Couldn't reach the server." — it
looks exactly like a broken login. The **auth limiter is 10/min per IP and a
per-process pacer resets between scripts**, so a run 429'd mid-SC3 and was
voided; the pacer is now file-backed and the limit was never raised. The first
browser walkthrough tripped the *general* 120/min limiter seven times (a settings
load costs ~10 calls); document loads are now budgeted and both final
walkthroughs recorded **zero** 429s. **Access tokens are 15-minute JWTs**, so a
long lab run silently 401s mid-script — actor tokens are re-minted between
phases. Six harness bugs were corrected rather than the app, including an
assertion that a brand-new profile is publicly readable (it is not), the feed's
envelope key (`videos`, not `items`), the notification-prefs body shape
(`{"prefs": …}`), the admin settings route (`/admin/instance-settings`), and an
import-summary read that grabbed the page's first `[role="status"]` — a spinner.

Findings worth a decision, none fixed here. After an import applies the profile,
**the profile form above it still shows the pre-import values until a reload** —
visible in the acceptance screenshot, where the summary says "display name and
bio applied" beside an input still reading the old name. `POST /me/import`
accepts a body carrying only the format marker and no `profile` (200, all-zero
summary) while `AccountArchive` lists `profile` as required — `ParseArchive`
checks the marker and version only, so the schema and the validator disagree
about what a valid archive is. `PATCH /auth/me`'s OpenAPI *description* still says
"display_name, bio" while the schema under it carries nine more fields including
every privacy toggle. And an archive **carries no identity**, so it cannot write
another account — but a leaked one lets a stranger clone a creator's display
name, bio, playlists and follows onto their own account, which deserves an
explicit product call rather than being an accident of the design.

**The AUTH-05 row is not flipped and A12 remains OPEN.** Profile/privacy and the
account archive are closed on evidence; "email/password changes … with
re-verification" describes a product Vidra does not ship, and that is recorded
rather than counted either way. The remaining half — deactivation, deletion, DM
retention, media cleanup and the search deletion hooks — is the next slice.
Delivery order: **core#163 first** (it changes `api/openapi.yaml`), then
**frontend#162** (its `contract-ci` goes green only after core merges), then this
evidence PR. Nothing is merged here and no deployment is authorized.

## A12 deactivation and deletion — 2026-09-06

**A12 stays OPEN and the AUTH-05 row does NOT flip.** This is the second half
of AUTH-05 — deactivation and deletion with content, the search deletion hook,
DM retention and media cleanup — and all five of those pass on real evidence.
The row still cannot flip, for the reason the first half recorded: its
"email/password changes … with re-verification" clause describes capabilities
the product does not have. [Core #164](https://github.com/yegamble/vidra-core/pull/164)
(`7475c5a`) carries two TDD-first fixes; no migration (latest stays 0127), no
OpenAPI change, no hand-edited generated file, and **no frontend change was
needed, so no vidra-user PR exists for this slice**. [Sanitized
evidence](evidence/a12-deletion.json) records **168 API assertions across eight
drivers and 24 browser assertions in one continuous Chromium walkthrough, with
ZERO 429 responses anywhere**.

This is the first A12 slice with **vidra-search actually running**, so the
deletion hook is proven rather than read: built from `main`, migrated to schema
16, wired to core over the HMAC internal API, and asserted both through core and
through a signed `/internal/v1/search` call and the index tables themselves.
Media is real too — `TRANSCODING_ENABLED=true` with ffmpeg 8.1, so the
originals, 240p renditions, thumbnails, storyboards and the CMAF/HLS ladder on
disk came out of the shipped pipeline, and SC5 proves **physical removal**, not
scheduling.

**Deactivation is a login switch, not a visibility switch — say so out loud.**
`POST /auth/me/deactivate` re-confirms the password, clears `is_active`,
deliberately does *not* stamp `deleted_at`, keeps the username, and revokes
every session row (7 of them here); login is then 403 "account is disabled".
What the account's audience sees changes far less than the UI implies: the
**profile goes to 404 for everyone — anonymous, the counterpart, and the
instance owner** — and the account leaves `/search/accounts` while its channel
leaves `/search/channels` (both are core-local queries filtered on
`u.is_active`). Everything else stays public. The channel page answers 200 with
its video grid, both videos answer 200 by direct URL **and stay in the anonymous
feed**, thumbnails and the HLS master serve, and the account's comments still
carry its username. **vidra-search never hears about it at all** — deactivation
enqueues no event, so the videos were still returned by the service afterwards
(2 hits before, 2 after), unlike "unlisted", which does enqueue `user.suppress`.
The shipped copy — *"This disables your account and signs you out everywhere.
You will not be able to sign in again."* — is accurate about sign-in and silent
about content. Reactivation is **admin-only**: there is no self-service path,
the owner flips it from `/admin/users` (driven in Chromium), and everything
returns — login 200, profile 200, the videos back in the feed, `/search/accounts`
back to 1.

**Name the token, because the two answers differ.** Refresh tokens die
instantly: every session row is revoked and `POST /auth/refresh` is 401 in the
same breath. The already-issued **15-minute access JWT does not** — `requireAuth`
verifies the JWT and never re-reads the account, so only the handful of handlers
that load the user row notice. Probed route by route right after a
deactivation: `GET /auth/me` 401, but `PATCH /auth/me` **200**,
`GET /me/notifications` 200, `GET /me/conversations` 200,
`POST /videos/{id}/save` 204, `GET /me/playlists` 200, `GET /me/export` 200 and
`POST /channels/{handle}/videos` **201** — and the database confirmed the
writes landed: the disabled account changed its own bio and created a video row.

**Deletion.** `DELETE /auth/me` re-confirms the password and answers 204 in
0.30s. The `users` row is anonymised rather than removed — `deleted-<8 hex>`,
`deleted-<8 hex>@deleted.invalid`, hash cleared, display name and bio emptied,
`is_active` false, `deleted_at` stamped — and **no row anywhere still holds the
old username or address**. Channels and videos are hard-deleted; both videos are
404 by direct URL and out of the feed; the channel page is 404. Comments written
before the deletion are tombstones with emptied bodies, rendered `[deleted]`
under the anonymised handle with an empty display name, **and both replies under
them stay live and readable**; the account's comment on its *own* video went
with the video, which is correct, not a missing tombstone. The strings that
still say "alice" in that thread are *other users' own comment bodies* — their
writing, not a leak — and that is asserted explicitly rather than waved away.
Follows vanish in both directions, playlists, ratings, saved videos, watch
history and notification preferences are purged, and **other people's rows that
pointed at the deleted content go too**: C's playlist item, C's and B's saved
rows and every watch-history row for those videos are gone, and C's Playlist,
Saved and History pages no longer name them. The three notifications whose actor
was the deleted account are kept but resolve through the anonymised row —
B's list reads `deleted-312a3b06` with no display name.

**`account_exports` do NOT outlive the account** — the previous slice flagged
this as untested and the answer is reassuring. The export row is deleted *and*
the archive blob is removed from storage inside the delete
(`DeleteAccountExportsByUser` returns the keys and each one is deleted);
`GET /me/export/download` with the deleted account's own token is 404, and the
object is gone from disk. A stranger holding the link could not pull a deleted
user's archive.

**The search hook, proven at both ends.** The delete enqueued
`user.suppress(unlisted=true)` and `user.history_deleted(all)`, erased core's own
outbox rows for the user and issued the direct `DELETE /internal/v1/users/{id}`.
In vidra-search: **0 hits for the account, 0 eligible documents** (both rows now
carry `suppressed_reason: "deleted"`), and `query_log`, `behavior_events`,
`user_search_history` and `user_watch_projection` are all 0 for it. In core:
`/videos/search` 0, `/search/accounts` 0, `/search/channels` 0. Repeated for a
second actor deleted through the **UI** against the patched binary, with the
same result. What survives is narrow and by design: delivered `video.upsert`
rows still carry the deleted owner's id and video titles until the
`search_event_retention_days` prune, because the erasure deliberately targets
only payloads that name the user at the top level.

**DM retention: the recipient keeps their copy, and only the sender's identity
goes.** The conversation, both message rows and the E2EE ciphertext all survive;
the counterpart's thread is still 200 with the same envelope count, and nothing
in it names the deleted account. In Chromium, B's `/messages` reads
*"deleted-251d3f2e — Encrypted conversation"*. **Media cleanup has no gate to
record on this path**: nothing is deferred to media GC or a purge ledger — the
delete collects every recorded blob key before the rows cascade, deletes each
object, deletes the whole HLS key prefix, then the profile/channel images and
the export archives, swallowing failures so cleanup can never abort the
deletion. Of 55 objects on disk, 37 belonged to the account; afterwards **zero**
objects carry either video id or the account id, `video_files` and
`streaming_playlists` are empty for them, every media URL is 404, and the
counterpart's media is untouched.

**Wrong actor and edges all hold.** There is no route by which one user deletes
another — `DELETE /auth/me` is self-scoped and B's `DELETE /admin/users/{A}` is
403; anonymous is 401. A wrong password is 403 with **nothing changed** (still
active, no `deleted_at`, same username, all three videos still owned) and a
missing one is 422. An account with an empty password hash — the OAuth-only
shape — **can neither self-delete nor self-deactivate**: 422 on an empty
password, 403 on any other, and the row is untouched, because bcrypt can never
verify an empty hash.

**Two defects, both fixed with a failing test first.** The §1 delete left the
**encrypted-messaging device directory standing**: the users row is anonymised
rather than removed, so the `ON DELETE CASCADE` on `e2ee_devices.user_id` never
fires, and the checklist covered MFA and recovery codes but not devices. After
the account was gone the counterpart's `GET /users/{id}/e2ee/devices` still
answered 200 with the **user-chosen `device_name`** and both public keys, and
key-claiming still worked — the tombstone took the username away and left a name
the user had chosen. Red first: *"e2ee devices left behind for the deleted
account"*, *"one-time keys left behind … 3"*, *"purge \"e2ee_devices\" did not
run"*. And **both comment write paths committed the mutation and then answered
500** when the author had been disabled: they resolved the author *after* the
insert/edit, so the row was already written when `UserByID` refused it — a
comment on the page from an account that no longer exists, and
`{"code":"internal_error"}` to the client. Red first: *"create with a disabled
account = 500, want 401"*, *"comments after the refused writes = 2, want 1"*.
Both fixed and both re-proven live against the rebuilt binary.

**The finding that is not fixed here is the important one.** Because
`requireAuth` never re-checks the account, a **hard-deleted** account's
unexpired access token kept writing: `PATCH /auth/me` 200,
`POST /videos/{id}/save` 204, `POST /playlists` **201**, `POST /channels`
**201**, `POST /me/export` **200** — it created a channel, a playlist and **a
fresh data archive of itself** after its own tombstone was written, and a
comment it posted in that window is live and untombstoned in the public thread
under the `deleted-<suffix>` handle. "Signs you out everywhere" is true of
refresh tokens instantly and of access tokens within fifteen minutes; for that
window the tombstone is not final. Closing it is a design decision — a
per-request account read, a revocation set, or session-bound access tokens — not
a surgical diff, so it is recorded rather than patched.

Gates: core `make ci` **passed** (fmt-check, vet, migrate-lint, openapi-verify,
sqlc-verify, test-race) plus the tagged `internal/store` and `internal/account`
integration lanes against real PostgreSQL 16 at schema 127. Core CI on #164 is
**all green** on the first run — GitGuardian, build-test, integration,
ipfs-integration, ipfs-private-integration and openapi — and the PR is marked
ready. SC7 no-regression: the named tests from every merged A12 slice pass,
including the tagged real-PostgreSQL `TestCommentReplyRecipientOnRealPG` and
`TestCommentVideoOwnerRecipientOnRealPG`. **vidra-user was not modified, so its
gates were not run and no frontend PR exists**; the meta compose render was not
needed (no compose or script files touched). Nothing here is unverified.

Failures worth keeping. The lab directory still held the **previous slice's
`state.json`**, so the first seed skipped the owner claim and every registration
came back `403 owner_claim_required` — and the `rm -f a b out-*.json` meant to
clear it **aborted whole under zsh's nomatch**, so the file survived a second
attempt; every phase now establishes its starting state explicitly. `psql -At`
with a field separator **drops trailing empty columns**, so an assertion about
the wiped display name crashed the delete driver on an `IndexError` *after* the
one-shot deletion had run; its remaining assertions were finished by a
continuation driver using the access token `state.json` still held, and every
possibly-empty column is now wrapped in `'['||col||']'`. Two assertions were
simply wrong about the product and are restated rather than argued with. The
Playwright admin row is only actionable at a wider viewport (it timed out at
1280×900 and works at 1440×1000), and the walkthrough is not idempotent — it
deactivates its own actor — which is recorded rather than worked around.

Findings worth a decision, none fixed here. **Deactivation's visibility
semantics** deserve an explicit product call: today it hides the profile and the
two account/channel search listings and leaves everything else — feed, channel,
playback, comments with the username on them — fully public, and the UI copy
describes neither behaviour. **An instance owner can flip `is_active` back to
true on a tombstoned row** from `/admin/users` (it lists as `deleted-<suffix>`
with Reactivate and Delete actions); doing so makes a public profile page for
`deleted-<suffix>` answer 200 again, though login still fails and the account
does not return to `/search/accounts` — a "Reactivate" control on a hard-deleted
account probably should not exist. And an **unrelated frontend packaging
finding**: on `vidra-user@3bd9bfe`, a hard load of `/settings` served from
`.next/standalone/server.js` — with `.next/static` and `public` copied in
exactly as the Dockerfile does — 404s a turbopack runtime chunk the build never
emits and falls back to "Something went wrong", reproduced on two clean builds;
the same build under `next start` renders it fine, which is what this
walkthrough used. It is worth checking against the released image before being
treated as shipped-broken, because the container runs the standalone server.

**The AUTH-05 row is not flipped and A12 remains OPEN.** Everything the row's
procedure names about deletion is now closed on evidence — *"delete/deactivate
with content, sessions, follows and search history; verify recipient DM
retention policy and media cleanup"* — and profile/privacy plus the archive were
closed by the previous slice. **The only thing left for the row to flip is its
"email/password changes … with re-verification" clause, and that describes a
product Vidra does not ship**: 23 route probes in the previous slice found no
password-change endpoint and no email-change flow, `PATCH /auth/me` rejects an
email, and even the instance owner cannot move an address. So the row flips only
when the owner either builds current-password-authenticated password change and
email change with re-verification, or rewrites the criterion to describe what is
shipped — a mailbox-possession reset, and an address fixed at registration.
That is a product decision, not an engineering gap. Delivery order: **core#164
first**, then this evidence PR. Nothing is merged here and no deployment is
authorized.

## A12 password change and token revocation — 2026-09-06

**A12 stays OPEN and the AUTH-05 row does NOT flip.** The previous two slices
closed everything the row's procedure names except one clause, and reported that
the clause described a product Vidra does not ship. The owner's answer was to
build it. This slice builds **half** of it — current-password-authenticated
password change — and, because the deletion slice proved that revoking sessions
kills only refresh tokens, it builds the revocation mechanism underneath it
once, properly. Email change with re-verification is the remaining half and the
next slice, so the row still cannot flip.
[Core #165](https://github.com/yegamble/vidra-core/pull/165) (`2863a54`, three
commits, **migration 0128**) and [frontend
#163](https://github.com/yegamble/vidra-user/pull/163) (`8ce8666`). [Sanitized
evidence](evidence/a12-password-change.json) records **127 API assertions across
six drivers on one clean database and 23 browser assertions across two Chromium
contexts, none failed**, with **zero 429s** other than the five the rate-limit
phase deliberately provokes as its own assertion.

**The mechanism, and why this one.** Access tokens now carry `sid` — the id of
the `sessions` row they were minted from — and the auth middleware resolves that
session on every authenticated request. It costs **one indexed read**: a
primary-key lookup on `sessions` joined to `users` by primary key. That single
query covers four revocation sources at once, because it re-reads the *account*
rather than trusting the token's copy of it — session revoked, session expired,
account deactivated, account tombstoned. There is deliberately **no in-process
cache**: vidra runs multiple replicas, so a cache on one process could not be
invalidated by a revocation served by another, and immediate invalidation is the
entire property being bought. A per-user `token_version` or `sessions_revoked_at`
column was rejected — both need a migration and a `users` change for no extra
coverage, and the timestamp form additionally has a one-second `iat` race. A
token that names **no** session fails closed; only the previous binary could
mint one, its holder's refresh token is untouched, and clients re-authenticate
transparently on the next 401. That is the one upgrade-visible behaviour here.
`optionalAuth` and the private-media access cookie get the same check, so a
revoked or tombstoned principal is not a principal anywhere.

**The deletion slice's reproduction, re-run and now refused.** That slice proved
a hard-deleted account creating a channel, a playlist and a fresh archive of
itself after its own tombstone was written. On this binary, all eight of the
probed routes — `GET /auth/me`, `PATCH /auth/me`, `GET /me/playlists`, `POST
/playlists`, `POST /channels`, `POST /me/export`, `GET /me/notifications`, `GET
/me/conversations` — answer **401**, and the database confirms the deleted
account created no channel, no playlist and no `account_exports` row. The same
eight are 401 for a **deactivated** account, where `PATCH /auth/me` was 200
before. An **admin** flipping `is_active` false through `PATCH
/admin/users/{id}` reaches the account's access token too; re-enabling does not
resurrect the old token, because that path also revokes the sessions, so the
user signs in again — recorded as the shipped behaviour rather than argued with.
The strongest form of the claim is pinned in the tagged real-PostgreSQL test:
`DeactivateUser` writes **no session row at all** and the surviving session
immediately stops resolving.

**The endpoint.** `POST /api/v1/auth/me/password` behind `requireAuth` **and**
the strict auth limiter — supplying a current password makes it a guessing
surface exactly like login, and the limiter runs first, so an unauthenticated
attacker cannot bypass it. That is proven on the route itself and not inferred:
an unpaced burst of 14 wrong-password attempts answers 403 nine times and then
**429**, on the shipped 10/min per-IP limit, which was never raised for this run.
A wrong current password is 403 with the stored hash **byte-identical**
afterwards and the caller not signed out; the 403 echoes neither password. The
new password is validated by the same policy as registration and the reset
(8–72), plus a refusal when it equals the current one — a no-op "change" would
still sign out every device and mail a security notice. **The password-less rule
is explicit**: an account with an empty stored hash (the OAuth/ATProto-only
shape) is refused **409** with *"this account has no password: use the password
reset flow to set one"*, deliberately not the unfalsifiable 403 it would
otherwise get, since bcrypt can never verify an empty hash and no supplied
password could ever satisfy it. On success every **other** session is revoked
(0.64s to the other browser's first 401, exactly one un-revoked session row
left) and the changer's own keeps reading and writing. Its refresh token is
**not** rotated, and that is a decision, not an omission: it is a 256-bit random
secret with no relation to the password, and the property that matters — killing
whatever an attacker holds — is the revocation of the other sessions.

**A defect the lab found, not the reading.** The SC2 driver asserted that the
changer's own session survives, and it did not: *"the changer's refresh still
works: got 401, want 200"*, *"un-revoked session rows: 0, want 1"*.
Refresh-token **reuse detection** assumed compromise and revoked every session
whenever a revoked refresh token was presented — correct for a replayed
*rotated* token, wrong for a device that was deliberately signed out and whose
client simply retried on its first 401, which is what every client does the
moment a password change signs it out. The escalation then took down the very
session the change was meant to keep. **Migration 0128** (append-only) adds
`sessions.revoked_reason`: rotation stamps `rotated`, every deliberate sign-out
stamps `signed_out`, and only a replayed `rotated` token still escalates. Rows
revoked before 0128 carry `''` and keep escalating exactly as before, which is
the safe direction. A second test pins what must **not** weaken — a replayed
rotated token still takes every session down, including a freshly rotated one
and an unrelated second browser — and the real-PostgreSQL test asserts both
reasons are actually written.

**The notice, over real SMTP.** The dev capture seam was deliberately **off** and
a throwaway Mailpit container was the sink, so `SendPasswordChanged` (the new
sibling of `SendPasswordReset`) is proven end to end: exactly one message, to the
account's own address, from the configured `SMTP_FROM`, subject *"Your password
on … was changed"*, a body that says every other device was signed out and tells
the reader what to do if it was not them, and — asserted, not assumed — **no
password, no token and no link of any kind**. With the sink stopped the change
still answered 204 and the new password logged in, so the notice can never fail
the change. There is **no in-app notification convention for security events** to
use: `internal/notification`'s vocabulary is follow / comment / comment_reply /
message / report_resolved / video_rejected / caption_ready / new_video /
new_report, none of them account-security shaped. Email-only is recorded as the
shipped answer, and adding a type is a product decision plus a prefs-registry
row.

**The UI.** `ChangePasswordSection` on `/settings/security`, mounted between the
two-factor card and "Signed-in devices" — adjacent on purpose, because a change
signs the other devices out. Current / new / confirm, every field label-bound and
`type="password"` with `current-password` / `new-password` / `new-password`
autocomplete tokens, submit disabled until all three are filled, Tab moving
Current → New. Errors go through the shared `Alert`: the confirmation mismatch
and the 8-character floor are caught client-side with **no** request, 403 renders
*"That is not your current password."*, and 409 renders a sentence with a real
link to `/reset-password`. Success is a `role="status"` Alert stating the
consequence — *"Your password was changed, and every other device was signed
out."* — and the typed passwords are cleared from the form. Driven in real
Chromium after hard reloads: the changer survives a hard reload signed in, the
**second browser context** is signed out on its next hard reload 2.5s after the
change with no settings form left, the old password does not sign it back in and
the new one does. `lib/api/generated.ts` was regenerated from the branch's spec
via the documented workflow.

Gates: core `make ci` **passed** (fmt-check, vet, migrate-lint, openapi-verify,
sqlc-verify, test-race) plus the tagged `internal/store` and `internal/account`
integration lanes against real PostgreSQL 16 at **schema 128**, including the new
`TestSessionRevocationQueriesPersist`. Frontend: TypeScript clean, lint 0 errors
with the same 2 pre-existing warnings, icons clean, and **239 files / 2355
tests** — up from 238/2348 by exactly this slice's seven new tests, and the same
counts CI reports on the green `frontend` lane — on nvm Node 24.4.1. Per
vidra-user's AGENTS.md the e2e suites were **not** run locally; repo CI owns
them. `vidra-search` was not modified and not run — nothing here reaches the
search boundary — and no compose or script files were touched, so the meta render
was not needed. SC5 no-regression: the reset flow passes end to end over real
SMTP (19 assertions: 202, an unknown address still 202, the token lifted from the
real message body, a wrong token 400 and a short password 422 both leaving the
hash untouched, the real token 204, a replay 400, old password 401 and new 200),
the two flows **compose** (the account then changed the password the reset had
just set), and a pre-reset access token is now 401 immediately instead of living
out its TTL. The two comment-write tests from core#164 still pass; they are now
partly redundant with the middleware and are deliberately **kept**, because they
pin the handler's own ordering guarantee — resolve the author *before* the insert
— independently of it.

Failures worth keeping. The **first full vitest run reported 18 failures across
12 files**, every one an unrelated component with a 5–21 second duration, run
while a Go build, a docker pull and the lab API competed for the machine; re-run
unloaded it is 1 failure (AdminMediaView's 501-item orphan list timing out at 5s)
which passes alone, 24/24. The status-contract guard broke **honestly**: its
probe minted a session-less token, which now 401s everywhere, so it saw *"only 1
of 304 operations were observed to 403"* — it now authenticates as a fixed
principal with a live session, floors unchanged. **tsc, not vitest, caught** the
test's `ApiError` stand-in taking a bare status number where the real class takes
an object; vitest was green on the wrong shape. The admin phase first probed
`POST /admin/users/{id}/deactivate`, which does not exist — eight assertions
"failed" against an account that had never been disabled, and its writes landed
and survived into the next attempt, so that phase now deletes its own residue
first. An assumption that the admin path writes no session row was simply
**wrong** (it revokes them) and is restated. The rate-limit phase first measured
`requireAuth` rather than the limiter, because it used a token SC2 had correctly
killed. Playwright's `getByLabel("New password")` matches *"Confirm new
password"* too, and an unscoped `getByRole("status")` grabbed a two-factor
spinner and made a failed change look successful — **the same harness trap the
previous slice recorded, hit again**; every browser query is now exact and scoped
to the Password card. And the walkthrough is not idempotent (it changes its
actor's password), so it now registers a fresh actor per run.

Findings worth a decision, none fixed here. The session lookup already reads the
account, so making a **role demotion** effective immediately rather than at token
expiry is now a one-field change; it was left out to keep the diff to the
revocation question. The auth limiter is **keyed per IP and shared** across
register / login / reset / and now change, so on an instance behind a proxy that
does not set a trusted client IP one user can exhaust everyone's budget — noted
because this slice adds a route to that bucket. On an instance with no working
SMTP a password change produces **no notice at all**, the same gap the reset flow
has. And the previous slice's `.next/standalone` chunk-404 finding was **not
re-tested** — this walkthrough used `next start` against the same production
build, as that one did — so it remains open.

**CI, and what it caught.** Core #165 is **green on all six functional lanes**
(build-test, integration, ipfs-integration, ipfs-private-integration, openapi,
prev-release-against-new-schema) and is marked ready. Two of them went red once
and passed on re-run: `integration` on `TestStateFlipClaimsAreExclusive` — a
queue-lease concurrency test this diff cannot reach — and `ipfs-integration` on
`TestIntegrationPublicVideoRoundTrip` timing out at 300s, the same lane and the
same test that flaked on core#163. **GitGuardian is red and needs owner
attention**: it reports *"1 secret uncovered"*, and nothing in the branch is a
live credential — every credential-shaped string it adds is a test fixture
password or the long-standing test JWT signing secret that already sits in about
twenty test files on `main`. Two follow-up commits removed the newly-introduced
copies anyway (the fixture passwords now have one definition each, and the test
wiring was deduplicated so the signing secret does too), and neither cleared the
check, because GitGuardian scans **every commit in the PR** and a finding in the
first survives its removal in a later one. Clearing it needs someone with
dashboard access.

Frontend #163 is green on `frontend` (the canonical gate, Playwright included)
and all four backed lanes; `contract` is red for the ordering reason and nothing
else — *"Frontend calls paths that do NOT exist in vidra-core's openapi.yaml:
/api/v1/auth/me/password"* — so **that PR stays a draft until core#165 merges**.
One backed lane failed in 11s on `unauthorized: authentication required` pulling
a compose image and passed on re-run.

And CI earned its keep. The first push turned the `frontend` lane red on two
cases in `e2e/security-settings.spec.ts` with *"strict mode violation:
getByLabel('Current password') resolved to 2 elements"* — when two-factor is on,
`/settings/security` now carries **two correctly-labelled "Current password"
inputs**, the disable form's and this card's. The spec's two locators are scoped
to the card that owns the "Turn off two-factor authentication" button, which is
what they always meant; no assertion changed, and both were reproduced failing
and then passing locally. The ambiguity is not only a test problem — two
identically-labelled password inputs are indistinguishable to a screen reader
too — so the Password card is now a **named region**, with a test.
`e2e/settings.spec.ts` and `e2e-backed/deactivate.spec.ts` use the same label but
on `/settings`, where this card is not mounted; that was checked, not assumed.

**The AUTH-05 row is not flipped and A12 remains OPEN.** What remains is
**email change with re-verification, and nothing else**: an account's address is
still fixed at registration, `PATCH /auth/me` rejects an `email` with 422, and
even the instance owner cannot move one. The next slice should know that the
re-verification shape is now settled and reusable, that revocation is no longer
an open question, that an email change needs *both* the current password and
possession of the new address (so it is a two-step pending-email flow, not a
PATCH), that the obvious fourth mailer sender is a notice to the **old** address
— the only signal that reaches a user whose address was stolen — that login
resolves email-or-username with **email taking precedence** so a new address must
not collide with a username-shaped login, and that a deliberate sign-out must
stamp `revoked_reason = 'signed_out'` or a signed-out client's retry will revoke
everything. Delivery order: **core#165 first** (it changes `api/openapi.yaml` and
carries migration 0128), then **frontend#163** (its `contract-ci` goes green only
after core merges), then this evidence PR. Nothing is merged here and no
deployment is authorized.

## A12 email change with re-verification — 2026-09-06

**A12's stopping criterion is met and the AUTH-05 row flips to PASS (candidate;
unmerged).** Five slices closed the row's procedure clause by clause, and the
last one — "email … changes … with re-verification" — described a capability
vidra did not ship at all: an account's address was fixed at registration,
`PATCH /auth/me` 422'd an `email`, and not even the instance owner could move
one, so a user who lost their mailbox lost password recovery permanently. The
owner's answer was to build it, and this slice builds it.
[Core #166](https://github.com/yegamble/vidra-core/pull/166) (`b760f57`, two
commits, **migration 0129**) and [frontend
#164](https://github.com/yegamble/vidra-user/pull/164) (`5744c10`). [Sanitized
evidence](evidence/a12-email-change.json) records **114 API assertions on one
clean database and 23 browser assertions in real Chromium, across two complete
walkthroughs, none failed**, with the shipped rate limits never raised and every
message delivered over **real SMTP** to a throwaway Mailpit sink with the dev
capture seam deliberately **off**.

**The model, and why a second table.** A pending change is a row in
`email_change_requests` (0129, append-only, with its `.down.sql`), not a pair of
`pending_*` columns on `users`: the token lifecycle it needs — issued, used,
expired, superseded — is exactly the lifecycle `password_reset_tokens` (0012)
and `email_verification_tokens` (0013) already have, the hot `users` row stays
untouched by a flow that may never complete, and `ON DELETE CASCADE` disposes of
pending requests with the account (proven). Only the SHA-256 of the token is
stored; the raw token exists only in the message.

**The switch is one SQL statement, and that is the point.** A CTE consumes the
token — `used_at IS NULL` is *inside* its predicate — and the outer `UPDATE
users` moves the address and sets `email_verified` from the CTE's row. So there
is no window in which the token is spent and the address is not, two concurrent
confirmations cannot both win without a transaction, and a token that is
unknown, already used, expired **or issued to another account** matches nothing
and returns no row: one indistinct 400 for all four, so a caller cannot probe
which. `users_email_lower_idx` is the final authority on collisions — an address
claimed by somebody else between the request and the confirmation fails as a
unique violation (409), not as a silent overwrite. All of that is pinned against
real PostgreSQL in `TestEmailChangeQueriesPersist`, not merely mirrored in a
fake.

**Confirm requires the session as well as the token.** The mail token proves
possession of the mailbox; the bearer token proves whose account it is. Both are
required, so a token that leaks out of the one place it necessarily sits in
plaintext moves nobody's address: bob presenting alice's token is 400, alice's
address does not move, bob's does not move, and — asserted separately — the
refused attempt does not consume the token, so alice's own confirmation still
works afterwards.

**The refusal rule has two halves and only one of them is a refusal.** An
address that resolves to **another** account's sign-in identifier is 409 —
either its email or its **username**, because sign-in accepts both with **email
taking precedence**, so an address equal to somebody's username would silently
shadow their sign-in, and usernames predating the `@` ban may literally be
addresses. An address equal to the **caller's own** username is *accepted*: it
shadows nobody, and a legacy account whose username *is* an address must be able
to set it. The lab is what forced that distinction into the open — its first run
made the collision actor its own victim, saw 202, and reported a failure that
turned out to be the harness misreading a rule the code had right. The
disclosure is deliberate and unchanged from what the instance already leaks:
registration answers 409 for a taken address today, so refusing here tells an
authenticated caller nothing an anonymous one cannot already learn. The other
refusals: wrong current password **403** with the stored hash byte-identical
afterwards, a password-less (OAuth/ATProto-only) account **409** pointed at the
reset flow — the same rule the password slice set, and for the same reason —
the address the account already has **422** (case-insensitively), a malformed
address **422**, a missing password **422**, and anonymous **401** on all five
routes. Every refusal was followed by an independent database read proving the
address had not moved, that nothing was left pending, and that **no mail was
sent at all**.

**Sessions are NOT revoked, and that is a decision.** An email address is not a
credential — knowing it grants nothing — and the change is already gated on the
password, so signing every device out would be a cost with no security bought.
Proven live: a second session opened before the change keeps reading and writing
afterwards, and the database shows **zero** revoked session rows. The safeguard
is the notice to the old address instead. Nothing here stamps
`revoked_reason`, because nothing here signs anything out.

**Both messages, over real SMTP.** The confirmation goes to the **new** address
and nowhere else (the old mailbox cannot supply possession of the new one), from
the configured `SMTP_FROM`, subject naming the instance, carrying no password
and saying in words that the account keeps its current address until the code is
used. It is deliberately **not** best-effort: a pending request whose message
never left is a dead end the user cannot see, so a failed send fails the
request and leaves the address alone. The notice to the **old** address is the
opposite — best-effort, because the address has already moved by then and
reporting a failure would read as "your address did not change" — and it
**names the new address**, since it is the last message that mailbox will ever
get and its reader needs to know what happened and be able to prove it to an
operator. Both were asserted at the sink: exactly one message each, to the right
address, with the token present in one and absent from the other.

**The limiter is in front of it, proven on the route.** The request, the resend
and the confirmation sit behind the same strict auth limiter as login and the
password change, which runs *before* `requireAuth`. An unpaced burst of 14
wrong-password requests answered **403 eight times and then 429 six times**, on
the shipped 10/min per-IP budget, which was never raised for this run. The
pending-state **read** and the **cancel** are deliberately *not* in that bucket:
a settings page load must not be able to exhaust a budget shared with sign-in.

**The UI.** `ChangeEmailSection` on `/settings/security`, above the Password
card — the address is the more consequential of the two, and both are gated on
the same current-password proof. It is a **named region** for the reason the
Password card is one: with two-factor on, the page now carries three correctly
labelled "Current password" inputs, and the section name is what tells them
apart to a screen reader. The card is two-step in the UI as well as the API:
asking shows the **pending** state — which address is waiting, with **Resend**
and **Cancel** — because "we mailed a link to an address you cannot read" is the
one state a user needs a way out of. The two 409s are different sentences on
purpose (an address in use is not an account with no password, and the latter
links to `/reset-password`). `/email-change/confirm` mirrors
`/verify-email/confirm` and `/reset-password/confirm`, with one difference that
matters: this endpoint needs the session too, so a signed-out reader is asked to
sign in and **the token stays in the URL** rather than being spent on a request
with no bearer token and lost for good; it also waits for the boot-time session
restore before submitting, which is one of its five tests.
`lib/api/generated.ts` was regenerated from the branch's spec via the documented
workflow.

Driven in real Chromium against the production frontend build, twice, after hard
reloads: the card shows the current address, the request produces the pending
state, **the pending state survives a hard reload** (it is server state, not
component state) with the account still showing the old address, the real
message arrives at the new address, a **wrong** token lands on an explicit
failure and claims nothing, the real token states the new address, a hard reload
of the settings page shows the new address and not the old one with the form
back, the old mailbox has the notice naming the new address, **replaying the
consumed link is refused**, the old address no longer signs in while the new one
does, and a signed-out reader is asked to sign in instead of having the token
spent. Zero uncaught page errors.

Gates: core `make ci` **passed** (fmt-check, vet, migrate-lint, openapi-verify,
sqlc-verify, test-race) plus the tagged `internal/store`, `internal/account` and
`internal/federation` integration lanes against real PostgreSQL 16 at **schema
129**, including the new `TestEmailChangeQueriesPersist`. Twenty new Go tests
(10 service, 9 handler, 1 real-PostgreSQL). Frontend: TypeScript clean, lint 0
errors with the same 2 pre-existing warnings, icons clean, and **241 files /
2365 tests** — up from 239/2355 by exactly this slice's two new files and ten
new tests — on nvm Node 24.4.1. Per vidra-user's AGENTS.md the e2e suites were
**not** run locally; repo CI owns them, and its `frontend` lane (Playwright
included) is green. `vidra-search` was not modified and not run — nothing here
reaches the search boundary — and no compose or script files were touched, so
the meta render was not needed. SC5 no-regression, all live: the password change
from the previous slice still answers 204 **on the account that just moved** and
its notice follows the address to the new mailbox; the reset flow round-trips
end to end over real SMTP on the moved address; the registration
verify-email flow still works on a fresh account; and the two flows **compose**
— a verified account then changed its address and the change confirmed.

Failures worth keeping. The lab's **first run reported three failures that were
one harness error**: the username-collision case made carol both the actor and
the account whose username was the lookalike, so it asserted a refusal for a
"collision" with herself. The code was right and the *rule* was under-stated;
both halves are now separate assertions. The **`getByRole("status")` trap
recorded by the previous two A12 slices hit again**, and harder: this page
carries three polite live regions (the search announcer, the session spinner,
and the confirmation page's own), so an unscoped query is a strict-mode
violation rather than a wrong answer — every browser query is now by exact text
or scoped to the Email card. The **second and third browser runs 429'd** on the
shipped **120/min general** limiter, not the auth one: a settings page load
costs about ten calls and three back-to-back walkthroughs exceed the budget. The
limit was not raised; the runs were paced apart, and two complete walkthroughs
passed clean. The Go **lint rule `react-hooks/set-state-in-effect`** rejected
both new components' first shape (a `setState` called synchronously inside an
effect); they were rewritten into the promise-chain form the two-factor card
already uses, which is better code and not a workaround. And a **real
regression signal from an existing test**: `SecuritySettingsView.test.tsx` mocks
`@/lib/api` method by method, so mounting a card that reads its pending state on
mount turned it red with *"authApi.getEmailChange is not a function"* — the mock
gained the stub and **no assertion was weakened**. The real-PostgreSQL test also
corrected an assumption of mine rather than the code: `DeleteUnusedEmailChange
Requests` sweeps **expired** rows too ("unused" is `used_at IS NULL` and says
nothing about expiry), which is why the pending read filters on `expires_at`
itself instead of trusting the table to hold only live rows.

**CI.** Core #166 is **green on all six functional lanes** (build-test,
integration, ipfs-integration, ipfs-private-integration, openapi,
prev-release-against-new-schema) **and on GitGuardian** — the fixture discipline
the previous slice paid for held: every credential-shaped string this branch
adds is an obviously fake fixture (`pw-fixture-alice`, `token-fixture-1`) from
its first commit, and the check that has been red since core#165 is green here.
The PR is marked ready. Frontend #164 is green on `frontend` (the canonical
gate, Playwright included) and all four backed lanes; `contract` is red for the
ordering reason and nothing else — *"Frontend calls paths that do NOT exist in
vidra-core's openapi.yaml: /api/v1/auth/me/email-change …"* — so **that PR stays
a draft until core#166 merges**.

**A12's stopping criterion is met.** Every clause of the AUTH-05 procedure now
has live evidence behind it: profile/privacy and the account archive
(`a12-profile-archive`), deactivation and deletion with content, DM retention,
media cleanup and the search hook (`a12-deletion`), password change with
re-verification on session-bound access tokens (`a12-password-change`), and
email change with re-verification (`a12-email-change`). The row flips to **PASS
(candidate; unmerged)** — candidate because nothing here is merged and nothing
is deployed. The open **product rulings** recorded across the A12 sections are
follow-ups, not blockers, and none of them is a gap in what the row asserts:
Block-vs-Mute optimistic removal; what "deactivated" should mean for visibility;
whether an admin may "Reactivate" a tombstoned row; the **10/min auth limiter
being keyed per IP and shared**, which behind a proxy that does not set a
trusted client IP lets one user exhaust everyone's budget (this slice adds three
more routes to that bucket, so it is now the most consequential of them);
per-comment deep links; and mention notifications, which are not a shipped
capability. Two smaller ones from this slice: on an instance with **no working
SMTP** an email change cannot be completed at all — the confirmation is the
flow, so it fails closed rather than silently, which is the safe direction but
means the AUTH-03/A05 SMTP-selection gate now governs one more capability; and
there is still **no in-app notification type for account-security events**, so
both the password-change and email-change notices are email-only. Delivery
order: **core#166 first** (it changes `api/openapi.yaml` and carries migration
0129), then **frontend#164** (its `contract-ci` goes green only after core
merges), then this evidence PR. Nothing is merged here and no deployment is
authorized.


## A13 suggestions, trending and discovery opt-out — 2026-09-06

**A13 stays OPEN and the SRC-03 row does NOT flip.** This is the first half of
A13 — autosuggest thresholds, suggestion bans, the trending gates and the user's
own discovery controls — and all of it passes on live evidence against a real
vidra-search. The second half (recommendations, related and home cards, search
filters/paging/ranking, history delete and reconcile) was not attempted, so the
row stays UNVERIFIED by construction. [Core
#167](https://github.com/yegamble/vidra-core/pull/167) (`a324ebd`) carries one
TDD-first fix; no migration (latest stays 0129), no OpenAPI change, no generated
file touched, and **no frontend change was needed, so no vidra-user PR exists
for this slice**. [Sanitized evidence](evidence/a13-suggest-trending.json)
records the full run. Shipped rate limits were left ON at their defaults and the
harness paced itself instead of widening them: **zero 429 responses in any
browser phase**.

**State the numbers, because the register row asks for "thresholds" and there
are four of them.** A normalized query becomes instance-wide suggestible only
when `distinct_users >= minimum_query_user_count` (the `service_config` overlay,
falling back to `MIN_QUERY_USER_COUNT`, **default 3**) **and** it is not banned.
That count is an exact recount over the retention window
(`search_event_retention_days`, default 90 days): distinct `user_id`s plus, for
rows carrying no user, distinct `COALESCE(subject_id, session_id)`. The
`aggregates_rollup` worker writes it on a **60 s** cadence, and ordering inside
the stream uses `decayed_freq` with a **168 h** half-life. Trending is gated
twice by `trending_sweeper`, also every **60 s**: the *same* distinct-user floor
of **3**, counted from a per-day HyperLogLog over a **2-day** window, and then a
Wilson lower bound of distinct/total at z=1.96 that must clear **0.10**. Scores
decay with a **6 h** half-life, and one `(subject,item)` may bump the *ranking*
score only once per **1 h** while its raw count and its distinct-user
contribution are always recorded. The three user controls are **opt-OUT, not
opt-in** — all three default `true`, observed on the registration response for
all five synthetic accounts — so SRC-03's phrase "user search-discovery opt-in"
mislabels the shipped default. A ban needs no worker at all.

**The threshold behaves exactly as documented, and the fixture says so four
ways.** `zynthara`, typed by exactly three distinct signed-in users, reached
`distinct_users=3, suggestible=true` and appeared in the anonymous
`SearchAutocomplete` listbox in Chromium. `qwoplex`, typed by two, stayed at
`false` and was absent from both the API and the listbox. `vurblok`, typed
**twelve times by one user**, recorded `total_count=12, distinct_users=1` and was
absent — volume alone never clears the floor. And the streams the floor does
*not* gate are worth naming: title, channel and tag prefixes come straight off
`search.documents`, plus a trigram typo fallback at similarity ≥ 0.35, none of
them threshold-gated, because they surface public catalogue text rather than what
people typed.

**What failed first is the anonymous half of that floor, and it was open on one
of the two ingest paths.** vidra-search counts distinct `session_id`s for rows
with no user, and `X-Vidra-Session` is client-supplied and validated for UUID
*shape* only — so core derives `subject_id`, a keyed, domain-separated,
day-scoped HMAC of the connecting address, precisely to stop one client minting
identities by rotating the header. It was attached on `POST /search/events`
only. `GET /videos/search` emits its **own** `search.submitted`, that event lands
in the **same** `query_log`, and it carried `session_id` alone. Three anonymous
searches from one address with three rotated headers therefore gave
`distinct_users=3, suggestible=true`, and the string only that client had ever
typed appeared in anonymous autosuggest. The identical attack through
`POST /search/events` gave `distinct_users=1`. Core #167 puts the subject on both
paths; three tests were written first and two were RED (`subject_id missing ("" /
"")`, `two different client addresses produced the same subject_id ""`). Replayed
against the patched binary with four rotated headers: four rows, four distinct
sessions, **one** subject, `distinct_users=1, suggestible=false`, absent from the
Chromium listbox. The authenticated shape is pinned unchanged — `user_id` is
already the trustworthy subject, so no address-derived value goes beside it.

**Bans are immediate, and the one place they are not is measurable.** The ban
upsert writes `banned=true` *and* `suggestible=false` in a single statement, so
it waits on no worker: **4 ms** from the API call to the suggestion being gone on
an uncached prefix, with vidra-search's own row reading `true/false` and the
entry visible both in core's admin list and in a separately signed call at the
service's `/internal/v1` surface. The single staleness window is the
non-personalized short-prefix cache — prefixes of at most **3 runes**, TTL
**60 s** — and it was forced on purpose: `pli` kept returning the banned string
for exactly 60 seconds while `plind` lost it instantly. A non-admin gets **403**
and anonymous **401**; both write a `moderation.search.suggestion_*` audit row
fingerprinting the key the *service* moved rather than the operator's input. Two
more distinct users then searched the banned string while it was banned
(`distinct_users` 3 → 5) and a full rollup pass that saw that traffic still left
it `banned=true, suggestible=false`. **An unban never promotes**: right after
`DELETE` the row read `banned=false, suggestible=FALSE`, and the query only
returned to autosuggest after real traffic plus one rollup. The whole lifecycle
was then driven again through `SuggestionBansView` at `/moderation/autosuggest`
as the owner, including a **hard reload** between the ban and the readback.

**Trending: the distinct-user gate bites, and the page called "Trending" is not
this.** The video played by three distinct users reached HLL 3 and score 3.0 and
was the *only* member of the gated list after a sweeper pass; the video played by
two reached HLL 2 and score 2.0 and never entered it, with
`vidra_search_trending_gate_rejections_total{domain="v",reason="distinct_users"}`
climbing once per pass. The gated list's only outlet is the home rail, where
`GET /recommendations/home` answered `source=search` with the hot fixture
carrying `reason=trending` and the cold one absent — identically for anonymous, a
signed-in user and the opted-out user. That is recorded **as the gate's readout
only**; home cards and their ordering belong to the next slice. Meanwhile
`/trending` in vidra-user is core's own public feed: watching its traffic in
Chromium, it calls `GET /api/v1/videos?sort=trending`. **No surface in the
product renders vidra-search's gated trending list under that name.** The Wilson
gate could not bite in this fixture — with the 1 h cap window, total tracked
distinct, and the lower bound of 3/3 at z=1.96 is 0.579 against a 0.10 floor — so
its live behaviour under a bot-shaped ratio is **unverified**, as is the decay
half-life and HLL window edge, which cannot be forced without leaving the shipped
configuration.

**The opt-out keeps every promise the product makes, and the register row asks
for one it does not make.** With all three controls off, the actor wrote **zero**
`user_search_history` rows and **zero** `user_watch_projection` rows; a query
they made while opted out came back to them as an empty listbox in Chromium;
`/recommendations/home` answered them `personalized=false` — the same flag and
the same items an anonymous visitor gets. The setting survived a `GET /auth/me`
readback, a brand-new login (it lives on the user row, not the session) and a
hard reload of `/settings/search`, and toggling it in the UI wrote through to
core's `users` row both ways. Re-enabling is **forward-only**: nothing already
searched appeared, and the very next search produced exactly one history row.
**But the same fully opted-out user still had 5 `query_log` rows and 8
`behavior_events` rows carrying their raw `user_id` and their raw query text,
still counted toward the instance-wide floor** — the discriminator query, typed
by them plus two others, reached `distinct_users=3` and became suggestible where
it would have stopped at 2 — **and their play still bumped trending under a Redis
guard key literally named with their account UUID**. The shipped copy only ever
says "new searches are not stored to your history", so this is not a broken
promise; it *is* short of SRC-03's "no personalized data when off" if that is read
as "no attributed collection". Recorded as a **product ruling for the owner**,
not changed here.

**What search stores per attributed event, read off the schema and the rows.**
`query_log` holds the normalized query, the **raw query text as typed**, the
**raw account UUID**, the client-supplied session id, the day-scoped subject
digest, a result count and a timestamp; `behavior_events` holds the same identity
columns plus the whole delivered payload verbatim in `props`. **No email address,
username, display name, IP address or user agent appears in any search table** —
the anonymous subject is a keyed HMAC and the address itself is never persisted.
The flag: for a *signed-in* user the attribution key is the durable account id
rather than a rotating pseudonym, written for every search whatever their
controls say, and nothing in the schema needs a durable id to enforce a
k-anonymity floor — a day-scoped digest would count identically.

**Gates.** Core `make ci` passed (`fmt-check, vet, migrate-lint, openapi-verify,
sqlc-verify, test-race`, exit 0). On core#167: GitGuardian, build-test,
integration, ipfs-private-integration and openapi all green;
**ipfs-integration** failed on `TestIntegrationPublicVideoRoundTrip` after
301.77 s — a public-IPFS-gateway round trip in a lane that normally finishes in
~90 s and passed on every recent `main` and PR run, and which a one-line change
in `emitSearchSubmitted` cannot reach — so it was re-run. vidra-search was **not
modified**, so its gate was not run; it was run as a dependency and its tables,
its Redis state and its signed internal API were asserted directly. vidra-user
was not modified, so no frontend gate and no frontend PR.

**Traps for the second slice.** One browser search writes **two** `query_log`
rows — core's own emit plus the frontend's client event — so `total_count` and
`decayed_freq` double for browser traffic against API traffic while
`distinct_users` does not; only the client row carries `allow_history`, so an
API-only client's searches are retained yet never appear on the user's own
search-history page; **Redis state outlives a fresh database**, and an earlier
lab's trend ZSETs and HLLs had to be flushed before the trending fixture meant
anything; the 15-minute access JWT expires mid-run; and any threshold fixture
must use strings that match no catalogue text, or the un-gated document streams
answer instead. Delivery order: **core#167 first** (the only code change), then
this evidence PR. Nothing is merged here and no deployment is authorized. Next:
A13's second slice — recommendations/related/home cards, filters, paging and
ranking, and history delete surviving reload and reconcile — which is what SRC-03
still needs before it can flip.

## A13 recommendations, ranking and history controls — 2026-09-06

**A13 is now fully attempted and SRC-03 still does NOT flip — but for one
named reason, not for want of evidence.** This is the second half of A13:
co-visitation into related cards, the home rail and its sources, search
filters/paging/ranking, and the search-history controls. Every claim below is a
live readback against a real vidra-core, a real vidra-search (its own database
and its own Redis logical database), and real Chromium on the production
frontend build — no route interception, no fake search server, no skipped lane.
Three defects were found and fixed TDD-first in [core
#168](https://github.com/yegamble/vidra-core/pull/168) and two in [user
#165](https://github.com/yegamble/vidra-user/pull/165); no migration (core stays
0129, search stays 0016), no OpenAPI change, and vidra-search itself was **not
modified** — it was stood up as a dependency and its tables, Redis keys and
signed internal API were asserted directly. [Sanitized
evidence](evidence/a13-recommendations-history.json) records the run. Rate
limits were left ON at their shipped defaults and the harness paced itself:
**zero 429 responses in any phase**.

**State the numbers again, because the register row asks for thresholds and this
half has a different set.** Co-visitation is rolled up by `covis_rollup` on
`SEARCH_COVIS_INTERVAL`, **default 15 minutes** — not the 60 s cadence the
aggregates and trending sweepers run at, so a related rail is up to a quarter of
an hour behind the watching that shaped it. It pairs each new
`video.play_started` / `video.meaningful_watch` only with EARLIER events in the
**same `session_id`** inside `SEARCH_COVIS_WINDOW_SECONDS`, **default 3600 s**,
then rebuilds `search.item_neighbors` from scratch as a shrunk cosine
(`raw = cooc/sqrt(totI·totJ)`, `shrunk = raw · cooc/(cooc+λ)`, **λ default 10**)
blended **0.7 co-watch + 0.3 co-search**, keeping the top **100** neighbours per
item. The fixture matches the formula to five decimals: three distinct users
each watching A1 then A2 gave `cooc=3, totI=totJ=3`, so `0.7 · 1.0 · 3/13 =
0.16154`, and that is exactly the stored score.

**The first thing to say about co-visitation is what it does NOT have: a
distinct-user floor.** The only filter in the neighbour rebuild is `score > 0`.
Dave alone, in one session, watching C1 → P → U produced **three public
neighbour edges** at 0.03182 each. Autosuggest gates a query behind
`minimum_query_user_count` (default 3) and trending gates a video behind the
same floor plus a Wilson bound; the index that decides "watch this next" gates
nothing, so on a quiet instance one person's session is enough to publish an
association between two videos to everybody. Recorded as a **product ruling for
the owner**, not changed here — the k-anonymity argument that justifies the
suggestion floor applies to this table verbatim.

**The second thing to say is that in the shipped default, co-visitation reaches
nobody.** `search_mode` defaults to `simple`, and vidra-search dispatches BOTH
recommendation rails on it: `relatedSimple` composes up to two recent
same-channel videos, then tag/category/language overlap, then a popular fill,
and **never reads `item_neighbors` at all**. With the A1↔A2 edge sitting in the
table at its full 0.16154, `GET /videos/{A1}/recommendations` in simple mode
returned ten `similar` cards and A2 was not among them. Flip the instance to
`advanced` and the same request answers `A2` first with `reason: "co_watch"`,
and the watch page renders it. So SC1 passes — the pipeline works end to end —
but only on a setting no shipped instance has on.

**What failed first is what the API said about that.** `personalized` is not
decoration: `HomeRecommendationsRail` picks its heading from it, "For you" when
true and "Trending now" when false. Core computed it as
`instancePersonalizedRecs() && authed && prefs.PersonalizedRecs` — **without the
mode gate that personalized search has carried all along**. In the shipped
simple default a signed-in user's home rail and related rail came back
**byte-identical to the anonymous ones** with `personalized: true`, so the
product shipped a "For you" rail that was nobody's. Core #168 adds the gate; the
flag is now false in simple mode for everyone and, in advanced, true only for a
signed-in user whose instance and preference both allow it — verified as a gate
and not a mute: in advanced, alice gets `personalized: true` and a genuinely
different list, while erin (opted out) and anonymous get `false` and the generic
one.

**The second failure was a paging lie, and it was live on the shipped page
size.** Core asks vidra-search for an over-fetch — `(offset+limit)·2+10` ids at
offset 0 — hydrates them under the canonical predicate, slices the caller's
window out, and then forwarded the service's `has_more` **verbatim**. The
service answers for ITS window, so any match set that fits inside the over-fetch
came back `has_more: false` on page one. `vidra-user`'s `resolveHasMore`
believes an explicit `has_more` over `loaded < total`, so it hides "Load more".
At `PAGE_SIZE = 20` the over-fetch is 50, which means **every query matching 21
to 50 visible videos lost its tail**. Reproduced in Chromium before the fix: 23
matching fixture videos, "23 results" under the heading, twenty cards, **no Load
more** — and it survived a hard reload. At `limit=5` the flag even flipped
mid-walk (`offset=0 → true`, `offset=5..20 → false`) while five pages remained.
After core #168 the same page shows a Load-more control, a hard reload keeps it,
and clicking it brings the count to the full 23. The fix is careful about the
one thing the old behaviour got right: a service too old to report the field
still leaves it **absent**, because absent means unknown, and
`TestSearchServicePagingFieldsAbsentMeansUnknown` still passes.

**Paging itself was already sound, and the walk proves it.** Walking `?q=plexoid`
at `limit=5` from offset 0 to exhaustion returned **23 rows, 23 distinct**, in
stable order, with no duplicates and no gaps against the 23 eligible documents
in `search.documents` — and `total: 23` all the way down, which is core's own
per-viewer count and correctly excluded the two fixtures that had been flipped to
private and unlisted.

**Filters narrow, and the API and the database agree on every one.** From a
25-document corpus: `tag=zephqar` → 3, `category=1` → 11, `language=fr` → 1,
`license=7` → 2 (these four route to vidra-search), and `tags_all_of=plexoid,
mirvane` → 2, `tags_one_of=quolbex,traskil` → 5, `duration_min=5` → 0 (every clip
is 2 s), `duration_max=5` → 13, `published_before=now-30d` → exactly the one
backdated fixture, `published_after=now-30d` → the other 12 (these run on core's
local SQL because `searchServiceCanRank` refuses anything but the relevance sort
with the four facets the service knows). The date windows sum to the whole set,
which is the check that a window filter is a partition and not a sieve.

**Ranking: the live ranker is the SQL one, and it behaves as documented.**
`search_mode` defaults to `simple`, so the live path is vidra-search's
`SearchSimple`: `0.5·ts_rank_cd + 0.2·trigram(title,q) + 0.1·(title exact 1.0 +
channel exact 0.5 + tag exact 0.5) + 0.1·ln(1+views)/20 + 0.1·exp(-ln2 · age/30)`,
tie-broken by `published_at DESC, video_id`. `?q=wondrix` put the video titled
exactly `wondrix` first, ahead of two partial matches titled `wondrix drift log`
— the exact-title flag plus the higher trigram similarity, as the formula says.
And on the two videos with **identical** titles and tags, one backdated 120 days
in core and re-indexed, the fresh one ranks above the stale one on both queries:
the 30-day half-life term is the only thing separating them. The
`internal/experiment` / LightGBM shadow ranker is **not live in simple mode** and
was not exercised — recorded as out of scope, not as passing.

**The per-viewer predicate holds on two independent layers, and the second one
is the load-bearing one.** The private and unlisted fixtures were co-visited
while public, so their neighbour edges outlive their eligibility — after the
flip, `search.item_neighbors` still carried C1→P and C1→U. In normal operation
vidra-search drops them itself (its documents go `eligible=false`), so nothing
leaked. To test the layer that matters, the index was then deliberately made
**stale** — `eligible` forced back to true on both — and the service duly
returned the private and unlisted ids at the TOP of the ranked list with
`reason: co_watch`. **Core's `HydrateByIDs` dropped both for every viewer**:
anonymous, another signed-in user, the admin, **and carol, who owns them**. No
id, no title, no thumbnail, in any response. That last part is worth stating
plainly because the acceptance criterion asks the opposite: the hydration
predicate requires `privacy = 'public'`, so **recommendation rails are
public-only for everybody, the owner included** — an owner never sees their own
private or unlisted video in a related rail. That is the safe behaviour and it is
what ships; it is not what "while their owner does" expects.

**Muted and blocked authors disappear from both rails.** Alice muting dave
removed exactly dave's two candidates (D2, F8) from her related rail and her home
rail and nothing else; blocking bob removed exactly bob's (B1, F11). Both are the
same `NOT EXISTS` branches of `ListPublicVideosByIDs`, and both were exercised
through the shipped `/me/mutes/accounts/{id}` and `/me/blocks/{id}` controls and
reversed afterwards. Anonymous callers get the non-personalised set on both rails
in both modes.

**The home rail, per viewer, in real Chromium on a hard load.** Anonymous:
heading **"Trending now"**, `personalized: false`, and the two videos at the top
carry `reason: trending` — they are exactly the two members of the gated Redis
list `trend:v:top`, the sweeper's post-gate output, which is where the first
slice's distinct-user gate was proven. Alice, who has history: heading **"For
you"**, `personalized: true`, and A1 and A2 are **gone from her rail** because
`homeAdvanced` excludes the last 200 videos she watched. Erin, opted out:
**"Trending now"**, `personalized: false`, and her rail is item-for-item the
anonymous one. Frank, a brand-new account that has never watched anything:
`personalized: true` and the **generic list** — cold start as shipped, because
every personalized generator keys off `user_watch_projection`. Every id rendered
on every one of those rails is visible to that viewer under the predicate.

**That hard-load result took a frontend fix to become true, and the same bug on
the watch page was worse.** Before user #165, loading `/` while signed in fired
the home rail's fetch **twice** — once carrying the `Authorization` header and
once without, because `AuthProvider` re-renders the tree while the refresh cookie
is being redeemed — and the anonymous answer landed last. So a signed-in viewer
got the generic list under "Trending now" on every hard load, and the
personalized rail only after a client-side navigation. `RelatedVideos` had the
identical shape — a mount effect keyed on the video with no session dependency —
and there the consequence is not a heading. **That rail is filtered per viewer by
core's hydration predicate, so an anonymous fetch walks straight past the
viewer's own mute and block lists.** Proven in Chromium: alice muted dave, hard-
loaded a watch page, and dave's "Traskil Echo Beta" rendered in her watch-next
rail off a single related request carrying `auth: false`; the mute only bit after
a client-side navigation. The API layer was never wrong about this — muting dave
removed exactly his two candidates from alice's rails, and blocking bob removed
exactly his — it was the browser asking as nobody. Both rails now wait for the
session to settle and take its status as a dependency, so the one request that
goes out carries the viewer it is filtered for.

**History: what is stored, what the page shows, and the gap between them.** The
first slice's finding stands and was re-observed: **the `search.submitted` that
`GET /videos/search` emits itself never sets `allow_history`**, so two API
searches produced two `query_log` rows and **zero** history entries, while three
client-emitted `search.submitted` events (what the browser sends) produced three.
An API-only client's searches are retained and never appear on the page that is
supposed to show them. Erin, with all three controls off, produced **zero**
history rows from both paths.

**The search-history page shows the right rows and its delete control is
exact.** In Chromium, `/settings/search` listed alice's four stored queries
alongside the three preference toggles; the per-row control is labelled *Remove
"<query>" from your search history*, clicking it removed `krondal` from the list
and left `brimseq` standing, and after a **hard reload** `krondal` was still gone
with the endpoint answering `[xylthorn, brimseq, flendric]`. Erin's page, with all
three controls off, listed nothing.

**Delete works, and survives everything that could undo it.** A single-entry
`DELETE /me/search-history/{query}` removed `flendric` and it did not come back
after `aggregates_rollup`, `engagement_rollup`, `sessionizer`, `covis_rollup`,
`trending_sweeper`, `suggestible_reeval` and `reconcile_guard` were each driven
to completion, nor after a hard reload of `/settings/search`. `DELETE
/me/search-history` (clear all) is exact in every durable store: history rows
2→0, `query_log` rows attributed to that user 5→0 (anonymized, not deleted, so
instance aggregates survive), `behavior_events` 9→0, and core's OWN
`search_outbox` rows naming the user 14→6 — the six that remain are the purge
events themselves, which `PurgeUserSearchOutbox` excludes structurally. It too
survives every worker pass. Re-searching a deleted query recreates the row
fresh, which is the documented behaviour.

**One promise is not kept, and it is the strongest one on the page.** The
clear-all confirm says "This permanently removes every search you have made on
this instance. This cannot be undone." It does not reach vidra-search's Redis
**session-recency list**. After the clear, `brimseq` and `krondal` were still
returned to alice by `GET /search/suggestions` as personal, `history`-typed
suggestions; sending the identical request **without** the `X-Vidra-Session`
header returned nothing, which isolates the source exactly. The key is
`sess:q:<session-id>` with a **TTL of about two hours**. Single-entry delete has
the same hole. It is not a small fix in one repo: the list is keyed by session,
which the search-side history service never sees, so closing it means core
passing the caller's session id on the purge call — a change to the internal
contract in both repos. Recorded precisely, not attempted.

**Authorization holds.** There is no public user-scoped history route at all
(`GET`/`DELETE /users/{id}/search-history` → 404); `?user_id=` on
`/me/search-history` is ignored and the caller still gets only their own rows;
and bob issuing `DELETE /me/search-history/xylthorn` — the exact normalized query
alice had — returned 204 and **left alice's entry intact**, because the delete is
scoped to the caller's principal. (204 for an entry that does not exist is an
idempotent no-op and does not disclose whether it existed.) vidra-search's
`/internal/v1` history surface answered **401** to an unsigned request and 401 to
a forged `X-Vidra-Internal-Auth`.

**One more response was lying, found on the way in.** `POST
/setup/claim-owner` reported all three of the owner's discovery controls as
**false** while the row it had just created carried the schema defaults (all
true, migration 0093) and `/auth/me` agreed — `ClaimOwner` hand-copied a subset
of columns into a fresh `sqlcgen.User` and the rest went out as Go zero values.
The operator's first view of `/settings/search` therefore showed three controls
they never turned off. Fixed in core #168; registration was already correct, and
all six synthetic accounts registered with all three true.

**Gates.** Core `make ci` passed (`fmt-check, vet, migrate-lint, openapi-verify,
sqlc-verify, test-race`) — **exit 0, 79 packages ok, 0 failures**. vidra-user
`npm run ci` passed — typecheck, lint, lint:icons, **241 test files / 2369
vitest tests**, production build, and **623 Playwright specs**, exit 0.
vidra-search was not modified, so its gate was not run on a diff; it was run as a
dependency and asserted directly against its tables, its Redis keys and its
signed internal API. Core's `-tags=integration` lane was **not** run: the lab was
native (Homebrew Postgres + Redis) rather than the compose stack, so `go vet
-tags=integration ./...` is the only compile-level assurance for it here.

**Unverified.** The LightGBM / `internal/experiment` shadow ranker — not live in
`simple` mode, out of scope by the brief. The Wilson trending gate and the HLL
window edge — still unverified from the first slice and not reachable in this
fixture either. Co-visitation's `co_search` half (blend weight 0.3) — no
`search.result_clicked` traffic was generated, so only the `co_watch` half of the
blend was exercised; the SQL and its Go mirror agree by unit test. The ε-greedy
exploration slot and the MMR diversity reranker were observed only as part of the
composed advanced feed, never isolated.

**The exact remaining gap for SRC-03.** Everything in the row's procedure now has
live evidence except one clause, and it is the same clause the first slice
flagged: **"no personalized data when off"**. As shipped, opting out stops the
*serving* completely — no `user_search_history` rows, no `user_watch_projection`
rows, no personal suggestions, an item-for-item anonymous home rail, and
`personalized: false` on the wire — but it does not stop the *collection*. An
opted-out user's searches still land in `query_log` and `behavior_events` under
their **raw account UUID with their raw query text**, still count toward the
instance-wide k-anonymity floor, and their plays still bump trending under a
Redis guard key literally named with their account UUID; this slice adds that
their queries are also written to the two-hour `sess:q:<session-id>` Redis list
(they are not served back to them, because the read side is gated). The shipped
UI copy only ever promises that new searches are not stored to *your history*, so
this is not a broken promise — it is short of the register row's phrasing if that
is read as "no attributed collection". **The owner's ruling on that sentence is
the only thing standing between this row and PASS**; if the ruling is that the
shipped copy is the promise, SRC-03 can flip on this evidence plus the first
slice's, and the row's "user search-discovery opt-in" wording should be corrected
to opt-OUT at the same time.

**Findings recorded, not fixed.** (1) Co-visitation has no k-anonymity floor —
one user's single session publishes a neighbour edge. (2) `total` can undercount
the page it ships: `?q="wondrix drift log"` returned `total: 2` with **three**
hydrated videos, because vidra-search's recall also admits trigram title
similarity and core's own count does not — the two backends disagree on recall,
which is a contract decision across two repos. (3) The clear-all Redis
session-recency gap above. (4) `reason: "subscribed"` is reported for channels
the viewer never subscribed to — the advanced recommender relabels any candidate
whose normalized channel affinity clears 0.8, and vidra-search holds no
subscription data at all. (5) `SearchSettingsView` gates the *Personalize my
search results* toggle on simple mode with an honest reason, but *Personalize my
recommendations* has no such gate and is equally inert in simple mode — it
accepts a click, says "Saved.", and changes nothing.

**Delivery order:** core #168 first (it changes what the rails report and what
`has_more` means), then user #165, then this evidence. Nothing is merged here and
no deployment is authorized.

## A15 E2EE device lifecycle and attachment refusal — 2026-09-06

**MSG-03 flips to PASS on the candidate frontend; delivery is open awaiting
merge.** This is A15 in full: two devices establishing encryption, ciphertext-only
storage, restart/unlink behaviour, the honest absence of attachments in encrypted
threads, and the negative IPFS proof. Encrypted blobs stay out of scope (SCP-03),
so the row's own note survives the flip. One defect was found and fixed TDD-first
in [user #166](https://github.com/yegamble/vidra-user/pull/166); **vidra-core was
not modified** — no migration (schema stays 129), no OpenAPI change, no core gate
claimed. [Sanitized evidence](evidence/a15-e2ee.json) records the run.

**The lab was built to be the production shape, because the first attempt proved
that shape is load-bearing.** Frontend and API on separate origins looked like it
worked — sign-in returned 201 — and then every page load answered *"Sign in to
manage your devices. Your session has ended."* The refresh token rides an httpOnly
`SameSite=Lax` cookie scoped `Path=/api/v1/auth`, so cross-origin it is simply
never presented and the boot-time restore 422s forever. A pipe-only lab proxy that
inspects, rewrites and mocks nothing put Next and vidra-core behind one origin —
the Caddy topology — and the session survived. Everything below ran on the
**production frontend build** (`next build` + `next start`), a real vidra-core
built from the working tree at schema 129, and **real Chromium with the real Olm
WASM the app serves itself**: the crypto stub seam (`__VIDRA_E2EE_CRYPTO__`) was
never touched, so every ciphertext quoted here is genuine Olm output. One
persistent Chromium profile is one DEVICE, because IndexedDB is where the keys
live. Rate limits were left at their shipped defaults and the harness paced
itself: **zero 429 responses in any of the five browser phases**.

**What the product actually promises, established from the code and then proven.**
A send fans out one envelope per recipient device that exists *at send time*, and
the list endpoint returns only envelopes addressed to the caller's devices — so a
device added later sees **nothing**, and there is **no recovery key, no key
backup, no device-to-device history share and no cross-signing anywhere in either
repo**. Keys are a pickled Olm account under a random 32-byte pickle key in the
`vidra-e2ee` IndexedDB database; clearing the origin loses them permanently. All
of that was then observed rather than asserted: alice's third browser, registered
after four messages existed, opened the thread to **zero bubbles and the shipped
"No messages yet" copy**, and after bob sent again it received **only** that new
message.

**What failed first is the thing a two-device run exists to find.** Alice with two
browsers saw **four bubbles for a two-message conversation** — each message once
readable and once as *"Message can't be decrypted on this device"*. The cause is a
mismatch nobody could see with one device: core's `ListE2EEMessagesForRecipient`
joins the recipient device on `user_id` and takes no device parameter, so the
endpoint answers for the **account**, while the fan-out writes one envelope per
**device**. `EncryptedThreadView` rendered every envelope it received, so each of
alice's other devices added a permanent placeholder to every message in the
thread, growing with each device she adds. `recipient_device_id` was already on
the wire, so user #166 filters on it. The placeholder is not removed — it is
*restored to meaning*: an envelope addressed to **this** device that will not open
is the only trace a real ratchet fault leaves. The three tests that prove it are
the first component tests these e2ee components have ever had; 2 failed and 1
passed before the fix, 3 pass after, and the re-run in Chromium shows each of the
three devices rendering exactly the real messages and no placeholder.

**The round trip, on the fixed build.** Alice device 1 sent; bob's device
decrypted it; **alice's other device decrypted it too**, because the fan-out
addresses the sender's own other devices. Bob replied and both of alice's devices
decrypted the reply. Two messages produced **four envelope rows of 246 opaque
bytes each, every copy distinct**, with 30 one-time prekeys uploaded per device
and claims visible in the unclaimed counts.

**Ciphertext only, and this time the scan is exhaustive.** Every `text`,
`varchar`, `json` and `jsonb` column in the schema — **290 of them** — was
searched for the three sent plaintexts. **Zero hits.** The plaintext `messages`
table holds nothing for the encrypted thread. `last_message_body` is the empty
string and the rendered inbox row reads **"Encrypted conversation"** where a
plaintext row shows the body. Notifications carry `type: message`, an actor and a
conversation id and **no body at all**, for encrypted and plaintext alike.
`search_outbox` stayed empty for the entire run — messaging emits no search event,
which is why vidra-search was not stood up. Redis was written to zero times. All
three captured core stdout files contain **no occurrence of any sent plaintext**.
Every stored key is 43-char base64 — a 32-byte *public* key; no private-key column
exists.

**What the server does see, stated plainly, because "ciphertext only" is not
"metadata free":** both participants' ids and usernames, a `dm_key` that literally
concatenates the two account UUIDs, per-envelope timestamps, ciphertext lengths,
Olm message types, device ids, **user-chosen device names**, device public keys,
last-seen times, unread counts — and the fan-out width, which is one row per
recipient device and therefore discloses **how many devices each party has**.

**Restart, sign-out and unlink.** A hard reload, a **full browser restart** (the
process gone, only the profile on disk) and a sign-out/sign-in on the same browser
all left the thread readable; the pickle grew 3060 → 4118 characters as the
sessions ratcheted, and the device, plaintext-cache and outbox rows all survived
sign-out. Deleting the `vidra-e2ee` database returned the setup form and left
nothing readable. Then alice unlinked *alice browser two* through the shipped
Settings → Devices arm-then-confirm control, and every layer agrees: **the device
row, its 30 one-time keys and every envelope to or from it are gone (0/0/0)**;
**bob's next send addressed only the two remaining devices**; the unlinked
browser's thread is empty; and a send from it is refused *422 sender_device_id
must be one of your registered devices*. Nobody else can unlink it — an outsider,
a conversation peer **and the instance admin all get 404**, anonymous gets 401,
and all three devices survived every refusal.

**Attachments are refused honestly, in the UI and at the API.** The encrypted
composer has **zero file inputs and zero attachment controls**; the plaintext
composer in the same browser and session has one, carrying the unchanged A14
accept list (image/video/audio/pdf plus the six Office types). Every API shape is
**422**: uploading into an encrypted conversation is refused *before the multipart
body is read* ("attachments are not supported on encrypted conversations"), a send
with `attachment_ids` and envelopes is 422 on `attachment_ids`, and a send with
`attachment_ids` but no envelopes is 422 on `envelopes`. **No attachment row and
no stored bytes** result from any refusal, and the plaintext path still uploads,
sends and echoes its attachment back.

**No IPFS pin for DM bytes — run, not read.** A real kubo 0.40.1 node was
configured by the repository's **own shipped hook**
(`deploy/ipfs-public/001-configure-network-mode.sh` with
`IPFS_PUBLIC_NETWORK=false`) and asserted local-only: no bootstrap peers,
`Routing.Type=none`, `Provide.Enabled=false`, deny-all address filters, zero swarm
peers. With `IPFS_ENABLED=true` the exchange was repeated: encrypted messages, a
plaintext DM attachment uploaded and sent, and an ordinary public avatar as the
control. The mirror drained and the ledger holds **exactly one row** —
`user_avatar / pinned / public` with a real CID — and **zero rows naming a DM
attachment, conversation, message or e2ee object**. The stronger statement is that
the node's **entire block store was enumerated: three blocks, every one accounted
for** (the avatar, kubo's own pin-index entry for it, and the 4-byte empty-directory
block that predated the run). The DM attachment's would-be CID is absent, while its
bytes really do sit under the authoritative local backend — so the negative is about
mirroring, not about a file that was never written.

**Authorization.** Carol, an outsider, gets **404** reading the thread, 404 posting
to it, an empty conversation list, 404 on alice's device directory and 404 claiming
her prekeys; anonymous gets 401. A conversation peer may read alice's device
directory — ids, names, public identity/signing keys, timestamps — and **nothing
more**: even bob gets 404 on her one-time-key *count*, which is owner-only. The
instance admin gets 404 on the directory too; sharing a conversation, not a role, is
the key.

**Gates.** vidra-user: TypeScript PASS, lint PASS (0 errors, 2 pre-existing
warnings), icons PASS, **242 unit files / 2,372 tests PASS** (2,369 before; three
added), contract check PASS, production build PASS, and the named A14 suites
(Composer, ConversationView, MessagingShell, ThreadHeader plus every `lib/e2ee`
suite) 8 files / 48 tests PASS. All seven repo CI checks are green on user #166 —
contract, frontend, ipfs-backed, channel-sync-backed and both e2e-backed lanes.
**vidra-core was not touched**, so no core gate is claimed; the meta compose render
was not re-run because no compose, script or env file changed; vidra-search was not
started, which the empty `search_outbox` justifies rather than excuses.

**Findings recorded, not fixed.** (1) `StartEncryptedButton.tsx` is exported and
imported nowhere — a dead control; encrypted threads stay reachable through the
New-message dialog's checkbox. (2) `POST /users/{id}/e2ee/claim` is all-or-nothing
per user *including the caller's own device*, so fanning out to your own other
devices burns one of the sending device's own prekeys every time. (3) Clearing a
browser's storage **orphans its server-side device row**: peers keep encrypting to
a device nobody can read, and neither side is told — only an explicit unlink
removes it. (4) No audit row is written for any e2ee device registration or
deletion. (5) A signed-out visitor's first page load fires one `POST /auth/refresh`
that 422s with no cookie to present.

**MSG-03 → PASS**, evidence `docs/evidence/a15-e2ee.json`, with the row's
"encrypted blobs remain SCP-03" note intact: this verifies the current refusal, not
feature completion. A15's stopping criterion is met. **Delivery order:** vidra-user
#166 first, then this evidence PR. Nothing is merged here and no deployment is
authorized. The lab was torn down; no lab artefact is committed.

## A13 ruling applied — opt-out without attribution — 2026-09-06

**SRC-03 flips to PASS (candidate; unmerged), and the row's wording is corrected
at the same time.** Both A13 slices left exactly one clause uncertified — *"no
personalized data when off"* — and both recorded it as a **product ruling for the
owner** rather than a defect, because the shipped copy only ever promised that
new searches are not stored to *your history*. The owner has ruled: **opt-out
means no attributed collection.** This slice implements that, proves it in a real
lab, and makes the settings page say what the server now does. Three PRs carry
it — [core #169](https://github.com/yegamble/vidra-core/pull/169),
[search #35](https://github.com/yegamble/vidra-search/pull/35),
[user #167](https://github.com/yegamble/vidra-user/pull/167) — with **no
migration** (core stays 129, search stays 0016), **no OpenAPI change**, and no
generated file touched. [Sanitized evidence](evidence/a13-optout-attribution.json)
records the run. Rate limits were left ON at their shipped defaults and the
harness paced itself: **zero 429 responses in any phase**.

**The rule, in one paragraph, because the register row will be read against it.**
An authenticated caller's behavioural search event carries their account id only
when it may feed at least one durable per-user store that is *actually running*:
`allow_history` (the instance runs search history **and** the user keeps theirs)
or `allow_personalization` (the instance is in **advanced** search mode **and** at
least one personalization feature is enabled instance-wide with the user's
matching control on). `attributed == allow_history || allow_personalization`,
because the account id exists in these payloads to key one of those two stores and
nothing else. When neither holds — an anonymous visitor, a user who has switched
their controls off, or an instance where none of those features runs — the event
is built exactly as an anonymous visitor's would be: no `user_id`, no
account-derived value under any key in `props`, and the day-scoped anonymous
subject core already derives for anonymous callers (`anonSearchSubject`, core#167)
beside the client's session id, so vidra-search counts them **once** in every k
floor however many session ids they rotate through and never keys trending or
co-visitation to the account. Each surviving control then feeds only its own
store: `allow_history` gates `user_search_history`, the new
`allow_personalization` gates `user_watch_projection`. The decision is taken per
event at emit time, so it is **forward-only**.

**Where the boundary of "consent" falls is the part that changed while proving
it, and it is not just the user's row.** The test is not "did the user leave a
switch on" but "may this event feed a store that is running" — the user's control
AND the operator's setting AND, for the projection, the search mode. Two reasons.
A control the site has switched off is one the settings page already tells the
user is unavailable, so collecting on the strength of it would be collecting on a
consent the product has just declared moot. And it is what makes the promise
**reachable**: on the shipped `simple` default both personalization toggles are
inert — nothing there reads a watch projection — so the page disables them with an
honest reason, and if they could still justify attribution a default-instance user
could never get to "nothing is collected about me" using controls that work. The
cost is taken deliberately and stated here rather than discovered later: **a
simple-mode instance now builds no `user_watch_projection` at all**, so one that
later flips to advanced personalizes from that moment rather than from months of
quietly accumulated history. A durable per-user store nothing can read is exactly
the collection the ruling forbids; serving gates and collection gates are now the
same gates.

**Core is the only place this could live, and it has three emit paths, not one.**
`searchEventIdentity` is the single decision point and every path goes through it:
`POST /search/events` (the client batch), the routed `GET /videos/search` emit,
and — the one that used to be structurally exempt — the authenticated `PUT
/videos/{id}/watch-progress` emit. That third one matters because vidra-search
stores `video.watch_progress` in `behavior_events` like any other event and then
*synthesises* `video.meaningful_watch` from it, which the co-visitation k floor
counts; leaving it attributed would have left a hole exactly the width of a watch.
`allow_personalization` joins `user_id`, `session_id`, `subject_id` and
`allow_history` on the strip-then-set list, so a client cannot grant itself either
store. Nine tests were written first and seven were RED.

**The proof, in a real lab, one origin, real Chromium, both databases read back
independently.** A opted out **through `SearchSettingsView`** — and on the shipped
`simple` default that is one click, because the two personalization boxes render
*disabled* with their reason and refuse a change dispatched past the disabled
attribute, while "Keep my search history" is live and is the only control that
could still justify attribution there. She then searched through the UI and played
a real HLS video to the end (`currentTime` 2.02 s on a 2 s clip). Every row her
actions wrote reads `user_id NULL`, `props.subject_id` = the day-scoped anonymous
digest, `allow_history=false`, `allow_personalization=false` — identical in shape
to the anonymous rows beside them. Her history page is empty; her home rail is
headed **"Trending now"** and is item-for-item the anonymous one with
`personalized: false`. The k floor counts her **once**: a string she typed only
after opting out, four times from one address with four different
`X-Vidra-Session` values, reads **4 rows, 0 distinct `user_id`, 1 distinct
`COALESCE(subject_id, session_id)`**. Her trending guard keys are the anonymous
digest in both domains; the single guard key naming her account is the pre-opt-out
one and it carries a 3481-second TTL. Two videos watched in one session recorded
`co_watch` and published **nothing** — `item_neighbors` stayed empty, because one
subject does not clear the floor search#34 put on that table. B, opted in
throughout, is attributed exactly as before and is the only holder of a
`user_search_history` row in the database. Re-enabling through the same page
attributed the very next search and left every earlier row exactly as it was.

**On rows written BEFORE the change, the honest answer is that search cannot find
them, so we say so instead of guessing.** vidra-search holds **no per-user
preference state at all** — there is no users table, and preferences reach it only
as the per-event `allow_*` booleans, while `search.config_updated` carries
instance settings and never per-user ones. A `0017_` migration could only guess
which accounts are currently opted out, so there is none: those rows age out under
`search_event_retention_days` (default 90), and the settings copy now says that in
plain words. What it also says is that there is a remedy today — and proving it
exposed a real bug. **"Clear all" was unreachable for exactly the users who need
it**: it rendered only when the history list was non-empty, and an opted-out
user's list is empty by construction. It is now offered whenever the list has
loaded, because the list is `user_search_history` alone while the clear also
anonymizes the raw ledgers and erases core's own outbox copy of the query text.
Measured on A's own pre-opt-out rows: `behavior_events` attributed to her **4 →
0**, `query_log` **2 → 0** (anonymized, not deleted — the seven rows survive so
instance aggregates do), `user_search_history` **1 → 0**, and core's own
`search_outbox` rows naming her **4 → 1**, the remainder being the purge event
itself.

**The honest-toggle defect from the second slice is closed.** *Personalize my
recommendations* was as inert as its search sibling in simple mode — core gates
both on `searchAdvanced()` since core#168 — but carried no gate: it accepted a
click, answered "Saved." in green, and changed nothing. Both are now mode-gated
with the same copy pattern and the same one-line reason, and the tests prove
neither reaches `PATCH /auth/me`. One existing assertion moved deliberately: the
old case asserted the recommendations toggle was *not* disabled, which pinned the
bug.

**Gates.** Core `make ci` passed (`fmt-check, vet, migrate-lint, openapi-verify,
sqlc-verify, test-race`, exit 0) plus `go vet -tags=integration ./...`; the tagged
lane itself was not run because the lab was native rather than the compose stack.
Search `make ci` passed, and so did its real-PostgreSQL `-tags=integration` lane
(`internal/store` 6.06 s), which is where the projection split is proven at the
table level. vidra-user `npm run ci` passed on the repo's pinned **Node 24** —
typecheck, lint, lint:icons, **242 test files / 2376 vitest tests**, production
build, **621 Playwright specs**. Two e2e specs failed on the loaded run
(`admin-users`, `oauth`) and **both pass unloaded, 20/20**: the documented
CPU-competition flakiness, with the lab's Postgres, Redis, core and search all
running at the time. Worth recording for anyone else running the suite locally:
**vitest is broken on Node 25** in this repo — 82 tests fail with
`window.localStorage.clear is not a function`, reproduced on clean `origin/main`,
and `.nvmrc` and every workflow pin Node 24.

**Two lab findings that are not defects in this slice.** The routed
`search.submitted` from a *browser* search is emitted by the frontend's
**server-side** fetch, which carries no bearer token and no session header — so
for a signed-in user it lands anonymous, keyed to the Next server's own address,
which collapses every SSR-issued search on an instance into one subject. That
under-counts, which is the safe direction for a k floor, and it is unchanged here;
it is recorded because the earlier note that "one browser search writes two
`query_log` rows" did not say that one of the two is anonymous. And `next start`
cannot serve this app at all — `next.config` sets `output: standalone`, so it
warns and then serves stale route output; the settings page rendered *without* its
instance gates under it, which looks exactly like a bug in the gate. Any future
lab must use `node .next/standalone/server.js`.

**A13's stopping criterion is met.** Every clause of the SRC-03 procedure now has
live evidence behind it: thresholds, bans and the trending gates
(`a13-suggest-trending`), co-visitation into related cards, the home rail,
filters/paging/ranking and history delete surviving reload and reconcile
(`a13-recommendations-history`), and "no personalized data when off" under the
owner's reading of it (`a13-optout-attribution`). The row flips to **PASS
(candidate; unmerged)** — candidate because nothing here is merged and nothing is
deployed. The follow-ups the two A13 sections recorded stay follow-ups, not
blockers: the cumulative `co_watch`/`co_search` counters that nothing prunes;
`total` undercounting because vidra-search's recall admits trigram title
similarity and core's own count does not; `reason: "subscribed"` reported for
channels the viewer never subscribed to; the clear-all gap against
vidra-search's two-hour `sess:q:<session-id>` Redis recency list, which needs the
caller's session id on the internal purge contract in both repos; the double
`query_log` row per browser search; and the routed emit never setting
`allow_history`, which is deliberately still not fixed here because setting it
would double-count `use_count` for every browser search. **Delivery order:** core
#169 and search #35 are independent of each other — search accepts an absent
`allow_personalization` and falls back to `allow_history`, so either may merge
first — then user #167, which touches no contract, then this evidence PR. Nothing
is merged here and no deployment is authorized. The lab was torn down; no lab
artefact is committed.

## Frontend hardening — session-restore sweep, Block parity, single search emit — 2026-09-06

**No register row changes. The defect the last four slices each fixed once is
closed as a CLASS, and two rulings the owner has made are applied.** Four
components in four slices — `CommentsSection` (#160), `RatingControls` (#161),
`HomeRecommendationsRail` and `RelatedVideos` (#165) — carried the same bug: a
viewer-scoped read fired from a mount effect, before `AuthProvider` had redeemed
the httpOnly `vidra_refresh` cookie, so the request left with no `Authorization`
header and core answered it as an anonymous visitor. This slice sweeps the whole
frontend for it, introduces the one seam that spells the fix, applies the Block
removal ruling, and closes the double `query_log` row the A13 opt-out slice
recorded. Three PRs: [core
#170](https://github.com/yegamble/vidra-core/pull/170), [user
#168](https://github.com/yegamble/vidra-user/pull/168), and this evidence. **No
migration** (core stays 129), **no OpenAPI change**, no generated file touched.
[Sanitized evidence](evidence/frontend-hardening.json) records the run. Rate
limits were left ON at their shipped defaults; the reported runs contain **zero
429 responses**.

**The inventory, because "we looked" is not a finding.** Every client-side read
in vidra-user was enumerated from the source — **107 `"use client"` modules that
call `api.get*/list*/search*/fetch*/resolve*`** — and classified against core's
route table: which sit behind `optionalAuth`, and which of those answer
differently per viewer. **Seven were vulnerable**, four were the already-fixed
ones, and **96 are safe with a reason recorded next to each** rather than by
silence. The reasons fall into four shapes: the surface already waits
(`ChannelView` renders a spinner while restoring and remounts on a key carrying
`status` and `user.id`); the endpoint is not viewer-scoped at all (`GET /live`
takes no viewer; `/remote-videos/{id}` carries no auth middleware); the read is
gated on `authed` so it cannot run before the settle (`SaveButton`,
`SidebarFollowing`, `NotificationsBell`); or the fetching component does not
MOUNT while restoring, because its parent returns a `SignInGate` or a `RoleGate`
first — which is what covers every settings page, every studio surface and every
admin view in one argument.

**State the transition precisely, because everything below keys off it.**
`AuthProvider` derives `status` as `user ? "authed" : restored ? "anon" :
"restoring"`. Every hard load starts at `"restoring"` while one silent `POST
/auth/refresh` redeems the cookie, and it settles **once** — to `"authed"`
(`setUser` and `setRestored` land in the same batch) or to `"anon"`. Later
transitions are sign-in and sign-out only. And the mistake is not self-healing:
`apiRequest` retries a 401 only when it *used* a stored token
(`usedStoredToken = opts.token === undefined && getAccessToken() !== null`), and
during the restore there is no stored token — while an `optionalAuth` endpoint
does not 401 at all. It answers, as nobody, and the effect never re-runs.

**One seam, `useSettledSession`, and it needs both of its halves.** `settled` is
the guard; `viewerKey` (`"anon"` | `"authed:<id>"`) is the dependency that makes
the delayed read happen and happen again across a sign-in, a sign-out, and the
account switch that never passes through `"anon"`. Neither alone is enough:
`settled` never re-runs the read, and `viewerKey` never fires for a visitor who
settles anonymous, because their key never changed. `viewerKey` reads `"anon"`
**while restoring** on purpose — a server-rendered first page was fetched with no
viewer, so it *is* the anonymous answer, and keying it that way is what lets an
anonymous visitor keep the seed and issue no browser request at all. A sibling
`useSettledOptionalSession` mirrors `useOptionalSession` for the components that
also render bare, where no viewer can ever arrive and delaying would hang the
surface instead of guarding it. `useAppendingList` grew exactly one option,
`viewer`, taking the hook's return whole; it pins `initialPage` to the
**anonymous** key rather than the mount-time key, so arriving already signed in —
a client-side navigation — still replaces the seed.

**The seven, and what each got wrong.** `VideoFeed` (`GET /videos`, which drops
muted and blocked authors, muted instances and the viewer's own
sensitive-content override). `SearchResults`' video tab (`GET /videos/search`)
and its channel/account tabs (`/search/channels`, `/search/accounts`, both of
which take the viewer and drop what they have muted or blocked).
`SearchAutocomplete` (`/search/suggestions`, which returns the caller's own past
searches as `history`-typed personal suggestions) — and it needed one thing more
than the wait, because its per-prefix cache belonged to **no viewer**, so an
anonymous answer taken during the restore would be replayed to the signed-in
viewer for the rest of the tab's life; entries are now keyed by viewer too, and
the existing LRU ages the superseded ones out. `WatchView`'s channel read, which
supplies `is_following` and does **not** inherit the video read's wait, because a
public watch page is server-rendered and that seed paints on the first render.
`DownloadButton`, where `videoForDownload` resolves the file set for the caller.
`UserProfileLoader`, where core resolves an **owner's** own profile from the
account row rather than the public projection. And `LiveWatchView`, where a
private stream 404s for everyone but its owner.

**What failed first, in the browser, on `origin/main`.** The baseline was built
from `ff59a72` and run against the same lab and the same data, with alice signed
in, muting dave and following bob's channel. Her home page **never requested
`GET /api/v1/videos` at all** — the anonymous server seed stood — and **dave was
visible on it**. Her search page sent `GET /videos/search` and `GET
/search/suggestions` with **no `Authorization` header**, and **dave was visible
in her results**. On the watch page `GET /channels/bobchan` went out 15 ms after
the refresh POST, unauthenticated, on 3 of 3 runs, and the follow control read
**"Follow"** for a channel she already follows, on 3 of 3 runs. The control that
makes those negatives mean something: an **anonymous** visitor sees dave on all
three pages, so "alice sees no dave" is the exclusion working and not an empty
fixture.

**What passes now, same lab, same data.** Signed in: `GET /api/v1/videos` — one
request, **with** the bearer, dave absent. `GET /videos/search` and
`/search/suggestions` — one each, with the bearer, dave absent. The watch page's
`/videos/{id}`, `/comments`, `/rating`, `/recommendations` and
`/channels/{handle}` — **one each, all authenticated** — and the follow control
reads **"Following"** on 3 of 3 runs. The channel page, notifications and
settings likewise: one request per viewer-scoped endpoint, every one carrying
`Authorization`. Anonymous: one request per endpoint, none carrying it — and
`GET /api/v1/videos` is **not requested at all**, because the server seed still
stands for the viewer it was rendered for. Dave appears on none of alice's six
pages.

**One thing this does not fix, stated rather than discovered later.** The
server-rendered HTML of the home page is still the ANONYMOUS feed, because
`vidra_refresh` is `Path=/api/v1/auth` and the Next server cannot read it — so a
signed-in viewer's hard load paints the anonymous first page for the moment
before hydration replaces it with their own. What changed is that it is now
replaced at all; before, it never was.

**Block removal parity: the owner's ruling, applied.** Blocking a commenter from
the comment's overflow menu now removes their comments at once, exactly as Mute
already did. This is not test weakening and the commit says so: core's
`blockUser` contract already filters a blocked author out of the blocker's
comment list per viewer, with the same predicate it applies to mutes —
`ListComments` carries `user_blocks` and `muted_accounts` side by side — so the
row disappeared on the next load either way. Leaving it until then only made two
controls with the same effect look like they had different ones. The two specs
that pinned the old behaviour are updated: `e2e/blocks.spec.ts` gains a second
author so it can tell "the blocked author's rows went" from "the list emptied",
and `e2e-backed/blocks.spec.ts` is reshaped around the fact that there is no
comment row left to open a menu from — it opens the DM **before** the block,
then proves the removal survives a hard reload, that a send into the existing
thread is refused, and that unblocking brings the comment back. In real Chromium:
alice's thread read "bob says hello / carol says hello" (dave's already gone to
her mute), Block answered 204 and carol's row vanished **with no reload**, a
**hard reload** kept it gone — that is the server's own filter answering, not the
client's optimistic removal — and after Unblock (204) the next load had it back.
The dead `blocked` state and its "Blocked" menu label went with it: nothing can
render them once the item is gone.

**And the settings copy now says what the server does.** `/settings/blocks`
promised only the messaging half; a block also hides the account's videos and
comments. The mutes page had the mirror-image gap — it mentioned only comments,
while `ListPublicVideosSorted` carries `muted_accounts` too. Both pages were
read back in the browser after the change.

**Single search emit, and a correction to the note that raised it.** One browser
search wrote **two** `query_log` rows: the client's `POST /search/events` batch —
the row that reaches the user's own history page, because `handleSearchEvents`
is the only ingest path that sets `allow_history` — and the routed
`search.submitted` core emits behind the same `GET /videos/search`. The A13
opt-out section attributed the second row to "the frontend's **server-side**
fetch of `GET /videos/search`". **There is no such fetch**: vidra-user
server-renders `/instance`, the home feed and the watch video, and nothing else.
The routed row landed anonymous because the **browser's own** search request went
out before the session had settled — the same defect this slice's sweep closes —
and because `api.searchVideos` sends no `X-Vidra-Session` either. Both halves are
fixed here.

**The mechanism is a declaration, not a heuristic.** A client that emits its own
`search.submitted` says so on the request — `X-Vidra-Search-Events: client` — and
core skips its routed emit for that request only. It has to be the client that
says so: nothing on the server distinguishes a browser, which will send the
event, from an API consumer, which will not — and an API consumer must keep the
routed emit, because it is the **only** record its searches ever leave. Accepting
the caller's word is safe in the one direction that matters: the declaration can
only make core collect *less* about that caller, and can never touch anyone
else's rows. An unrecognised value fails toward recording, which is what every
existing client already does. No OpenAPI change: the header follows
`X-Vidra-Session`, the sibling client-supplied search header this contract also
carries only in prose. Nine core tests, six RED first.

**Read back from vidra-search's own `query_log`.** On the baseline build, one
signed-in browser search wrote **2** rows — an unattributed routed row with no
session id beside the client's attributed one. On the fixed build: a signed-in
opted-in search writes **1**, `user_id` set; an **opted-out** user's search
writes **1**, `user_id` NULL with the day-scoped anonymous `subject_id` (the A13
consent rule, untouched); a `curl` with a bearer and no frontend writes **1**,
the routed emit, attributed and unchanged. A paging request (`offset=20`) sent
twice — once declared, once not — wrote exactly one row, from the undeclared one.
Walking the entry surfaces in the browser (results-page load → autocomplete
submit → filter change) wrote **3 rows for 3 searches**, every request carrying
both the declaration and the bearer.

**Gates.** vidra-user's `npm run ci` passes in repo CI on the final revision:
typecheck, lint (0 errors, 2 pre-existing warnings), icons, **245 test files /
2421 vitest tests**, the production build, and **623 Playwright specs, all
passed** — and `frontend-e2e-backed` passes too, which is the lane that actually
RUNS the reshaped `e2e-backed/blocks.spec.ts` against a real vidra-core +
PostgreSQL. Core `make ci` passes (fmt-check, vet, migrate-lint, openapi-verify,
sqlc-verify, test-race; exit 0) plus `go vet -tags=integration ./...`; the tagged
lane itself was **not** run, because the lab is native rather than the compose
stack. vidra-search was **not modified** — it was stood up as a dependency and
its `query_log` read back directly. Run locally, the same frontend gate was green
except five e2e specs that failed under CPU competition and passed **44/44
unloaded**: the documented flakiness, not a regression. **vitest is still broken
on Node 25** in this repo (82 failures on `window.localStorage.clear`); `.nvmrc`
and every workflow pin Node 24.

**One lab trap worth keeping.** `INTERNAL_API_BASE_URL` defaults to
`http://localhost:8080`, so with core on 8088 every SERVER-side read — the home
feed's first page, the watch page's video seed — silently returned null, and the
seeded code paths were never exercised at all. The first sweep therefore looked
clean for entirely the wrong reason, and the `VideoFeed` and `WatchView` defects
were invisible. Any future lab that wants to see the SSR seeds must set it. (The
`next start` trap the A13 slice recorded still holds: `node
.next/standalone/server.js` is the only way to serve this build, and a stale
server left listening on the port will happily answer with the previous slice's
bundle.)

**Findings recorded, not fixed.** (1) `GET /me/notifications/unread-count` is
requested **twice** per page load, by `NotificationsBell` and `BottomTabBar`
independently; both carry the bearer, so it is a duplicate fetch rather than a
correctness bug. (2) `GET /me/oauth-identities` is requested twice on
`/settings`, and `GET /channels/{handle}/donation-addresses` twice on the watch
page — the same shape. (3) `api.searchVideos` sends no `X-Vidra-Session`, so
before this slice the routed row it produced could not have been correlated with
the client's row for the same search even in principle. (4) The watch page's
captions read can still go out unauthenticated when a public server seed paints
first; harmless, because a public video's captions are public, but it is the one
read left that fires before the settle.

**SOC-02's recorded follow-up is closed with no row change:** the Block-vs-Mute
"open product ruling" the mute/block slice left for its owner has been ruled and
implemented here, and SOC-02 stays **PASS (candidate; unmerged)** on the evidence
it already had.

**Delivery order:** core #170 first (the frontend's declaration is inert until
core honours it, and shipping the frontend alone would leave the double row
exactly as it is), then user #168, then this evidence PR. Nothing is merged here
and no deployment is authorized. The lab was torn down; no lab artefact is
committed.

## A16 users, roles, quotas and signup approval — 2026-09-06

**ADM-01 flips to PASS (candidate; unmerged). A16 stays OPEN — ADM-02 remains.**
This is the first of three A16 slices: the account-administration half. Two
defects were found and fixed TDD-first — a **role change that did not reach the
session it demoted**, and a **hard-deleted account an admin could switch back
on** — and both were reproduced in the lab on the `origin/main` binary before
being fixed, so the "before" is evidence rather than a claim.
[Core #171](https://github.com/yegamble/vidra-core/pull/171) and
[user #169](https://github.com/yegamble/vidra-user/pull/169). **No migration**
(core stays at schema 129); one additive OpenAPI field; no generated file
hand-edited. [Sanitized evidence](evidence/a16-users-roles.json) records **338
assertions across eleven API drivers on one clean database, plus a real-Chromium
walkthrough**, with **three failing rows that are all deliberate**: one lab
formatting bug, restated and passing in its addendum, and the two baseline
reproductions where the defect answering 200 *is* the finding.

**The role matrix as shipped, established from the route table rather than
guessed.** There are exactly **three** roles — `user`, `moderator`, `admin` —
and `admin.ValidRole` accepts nothing else (`owner` and `superuser` are both
422). Parsing `routes()` gives **43 admin-only** routes and **24 staff** routes
(`requireRole(admin, moderator)`); five representatives of each tier were probed
against all four principals, and every one of the 40 answers was the shipped
one: admin 200 / moderator 403 / user 403 / anonymous 401 on the admin tier, and
admin 200 / moderator 200 / user 403 / anonymous 401 on the staff tier. **There
is no owner role.** The instance owner is simply the first account, claimed with
`OWNER_CLAIM_TOKEN`, holding `admin` like any other admin — and nothing
distinguishes it afterwards. `user → moderator → admin → moderator → user` was
walked in both directions with a Postgres readback *and* an admin-list readback
at every step; a moderator, an ordinary user and anonymous were each refused a
role change (403/403/401) with the target's role unmoved after all three.

**The self guards hold and the last-admin guard does not exist.** The owner
cannot demote itself (422 *"cannot demote or deactivate yourself"*), cannot
deactivate itself (422), and cannot hard-delete itself through
`DELETE /admin/users/{id}` (422, pointing at `DELETE /auth/me`) — after all four
refusals the row still reads `admin/true`. Setting one's **own quota** is
deliberately allowed, because it carries no lockout risk, and re-asserting one's
own `admin` role is a no-op rather than a refusal. But **admin A demoted the
instance owner M to `user` and got 200**. There is no last-admin guard and no
owner protection: the self-change guard is the *only* thing between an instance
and zero admins, and two admins can lock the instance out of its own console by
demoting each other. That is a product decision — vidra has no notion of an
owner after first-run — and it is recorded, not patched.

**Defect 1: a demoted moderator kept every staff route.** `requireAuth` has
re-read the account on every request since AUTH-05 slice (c) — one indexed
`sessions ⋈ users` lookup, which is what made revocation, deactivation and
deletion immediate. It then took the principal's **role** from the JWT's copy of
it, so the last piece of stale principal state survived: a snapshot taken at
sign-in. Paired probe, same lab, same data, same account, **only the binary
different**: on `origin/main` a moderator demoted mid-session answers **200 on
`/admin/reports`, `/admin/videos` and `/admin/comments`** with the token it was
already holding, for the rest of `JWT_ACCESS_TTL`; on the patched binary all
three are **403**, measured at **1 ms** after the demotion returned. The fix is
one column: `GetActiveSessionForAccessToken` also selects `u.role`,
`AuthenticateAccessToken` returns an `auth.Principal{UserID, Role}`, and
`requireAuth`, `optionalAuth` and the private-media access cookie all build the
principal from it. **No extra query** — the row was already being read. Seven
more staff and admin routes were probed on the demoted token, all 403. The other
half matters as much: **demotion is not a sign-out.** `/auth/me`,
`/me/notifications`, `/me/playlists`, `/me/conversations` and `/videos` all keep
answering 200 on that same token, the refresh token still works, and every
session row stays un-revoked. Promotion is the same mechanism in reverse: a
token minted while the account was a plain user reaches the admin list the
instant the role is granted.

**Defect 2: a tombstone could be switched back on.** The A12 deletion slice
recorded that `/admin/users` lists a hard-deleted account as `deleted-<suffix>`
with **Reactivate** and **Delete** actions. Reproduced here with a control — an
account whose profile was **public and answering 200** before the delete: on
`origin/main`, `PATCH {"is_active": true}` on the tombstone answers **200**,
flips `is_active` to true, and the deleted account's **public profile page
answers 200 again**, while restoring nothing (the username, address, display
name and bio are gone for good). `admin.UpdateUser` now refuses it —
`ErrDeletedAccount` → **422** *"this account was deleted; deletion is permanent
and cannot be reversed"*, audited as an `admin.user.update` **failure** beside
the self-change guard. The ruling is that **a tombstone is irreversible by
design**: it is the one admin action with no inverse, so the write is refused
rather than half-honoured. A combined body carrying `is_active: true` *and* a
quota is refused **whole** — the quota in it was not written either —
while `is_active: false` on a tombstone stays a harmless 200 no-op, and deleting
an already-deleted row stays 404. The row remains listed and readable, and the
admin projection now carries **`deleted_at`** so a console can tell a tombstone
from a deactivation.

**Deactivation, re-verified with the control the first attempt lacked.**
`profile_public` defaults to **false**, so "the profile 404s" proves nothing
until the account has opted in — the first run of this phase asserted it anyway
and is restated rather than quietly re-run. With A's profile public and
answering 200 first: deactivation revokes **every session row**, the **access
JWT** is 401 on `/auth/me`, `/me/playlists`, `/me/notifications`,
`/me/conversations` and on a write (`PATCH /auth/me`, which changed nothing),
the **refresh token** is 401, login is **403 "account is disabled"**, the
profile is 404 for anonymous *and* for the instance owner, and the account
leaves `/search/accounts`. What does **not** change: the channel page still
answers 200 and the videos stay in the public feed — deactivation is a login
switch, not a content switch, exactly as A12 recorded. Reactivation restores
login, the profile and the search listing, and the pre-deactivation sessions
**stay dead** — it is not a resurrection. A moderator, an ordinary user and
anonymous were each refused both the deactivate and the delete (403/403/401),
six refusals with the account untouched after all of them.

**Quotas, on real bytes.** A real 36,859-byte mp4 was uploaded through the
shipped path — create video, open session, PUT the chunks, complete — under
`TRANSCODING_ENABLED=true` with ffmpeg 8.1, so the **63,555 stored bytes** the
admin list reports are originals plus renditions the pipeline actually wrote,
and the admin list's `storage_used_bytes` matches the SQL aggregate exactly. An
admin quota set just above that is echoed by the PATCH, held in Postgres, and
reported by the account's **own** `/me/quota`. An upload session declaring four
times the cap is **422 `quota_exceeded`** — *"storing this file would exceed your
storage quota"* — with **no `upload_sessions` row created**, while one that fits
is still 201, so the gate is a cap and not a wall. The tri-state is exercised
end to end: `null` writes NULL (instance default), `0` reports an unlimited cap
on `/me/quota`, and a negative value is 422. Moderator, ordinary user and
anonymous are refused (403/403/401) with the target's quota still NULL.

**The two flags, and what the bypass actually lifts — proven, not read.**
`email_verified` flips on (response, Postgres and the target's own `/auth/me` all
agree) and off again, and is refused for a moderator, for the target themselves
and for anonymous. `bypass_quarantine` exempts an account from
`QUARANTINE_NEW_UPLOADS` (§11), and that was proven against the live gate rather
than described: with the instance gate **ON**, a plain user's finished upload
parks in **`quarantined`** and appears in the moderator's queue; the same upload
by an account the admin has flagged publishes **straight through** and never
enters the queue; **revoking the flag re-subjects the account** and its next
upload is quarantined again. A moderator approving one is **204** and publishes
it; an ordinary user is 403. Both instance-settings overrides were **cleared**
afterwards, not merely set back — they read `overridden: false` again, exactly
as found.

**Signup approval.** With `registration_require_approval` on, P's signup is
**202 `{"status":"pending"}`** with **no `users` row** and a pending
`registration_requests` row carrying the applicant's own note and **no password
hash anywhere in the projection**. A pending applicant's login is **401 "invalid
credentials"** — **the same status and the same message an address that never
existed gets**, so the queue leaks nothing beyond what registration already
discloses. The queue is **admin-only**: a moderator is 403 on reading it, 403 on
approve and 403 on reject, with the request still pending after both attempts.
Approval marks the request approved, records **who** reviewed it, creates a
`user/true` account, and the applicant signs in with the password from the
*application*; approving twice is 404 rather than a second account. Rejection
keeps the moderator note, creates no account, leaves the pending queue but stays
auditable under `?status=rejected`, and rejecting twice is 404. **Nothing
notifies the applicant either way** — no notification row, no mail on approve or
reject; they learn by trying to sign in, and that is a gap worth a product call
rather than a defect. Lockout: **14 unpaced login attempts by the rejected
applicant answer 401 ten times and then 429**, on the shipped 10/min per-IP
limit which was never raised — and an address that never existed produces a
**byte-identical** sequence, so the limiter cannot be used to tell one from the
other either.

**Audit coverage, before and after.** Every mutation this slice performs already
wrote an `audit_log` row and still does: `admin.user.update` (role, quota, both
flags, deactivate and reactivate — each naming the target and the field it
changed), `admin.user.delete` (naming the target), `auth.registration.approve`
(naming the created account), `auth.registration.reject`,
`auth.registration.request` and `admin.instance.update` (key names only). **The
gap was on the failure side and this slice closes half of it**: the self-change
refusal was already audited as a failure, and the new tombstone-reactivation
refusal now is too. Nothing secret leaks — the fixture password, the word
"password" and every email address are absent from the whole table. The admin
audit **view** serves them (139 entries, filterable by action, moderator 403 /
user 403 / anonymous 401) and shows the browser's own three mutations at the top
with `Actor: mona`. Out of scope and unchanged: **messaging and e2ee still write
no audit rows at all** (the A15 finding), confirmed here as 0 for both actions.

**The browser walkthrough.** Real Chromium against the production frontend build
served from `.next/standalone`, behind one origin, with hard reloads. `/admin/users`
renders the table with `ADMIN`/`MODERATOR`/`USER` pills and a `YOU` pill on the
owner; the three tombstoned rows read **Deleted** while live rows read **Active**.
Opening a tombstone shows Status **Deleted**, the role frozen to a static pill,
**no Reactivate and no Delete**, no flag switches, and the notice explaining that
the row is kept only as a record. Opening a live account shows the actions, the
three-way role control and the two **new** switches. Clicking Moderator and both
switches flips the header pill, the subtitle to *verified* and the facts column
to *Exempt* — and a **hard reload of `/admin/users?q=avery` still reads
MODERATOR**, so it was the server, not optimistic UI; Postgres reads
`moderator/true/true` and three audit rows name the fields. `/admin/registration-requests`
lists a pending applicant with their note and an internal-note box; **Approve**
through the UI creates the account, marks the request approved by mona, and the
applicant signs in. And the effect-timing proof in the browser: **dana signed in
as a moderator sees the Moderation nav and the full inventory; demoted from
another process, the same session's next hard load of `/moderation/videos` shows
"Moderators only" with the Moderation nav gone — while `/settings` still renders
her account normally**, on the same session, with no re-login.

**Gates.** Core `make ci` **passed** (fmt-check, vet, migrate-lint,
openapi-verify, sqlc-verify, test-race) on the final revision, and core CI on
#171 is **all six checks green** — GitGuardian, build-test, integration,
ipfs-integration, ipfs-private-integration and openapi. vidra-user: `npx tsc
--noEmit` PASS, `npm run lint` PASS (0 errors, 2 pre-existing warnings),
`npm run lint:icons` PASS, `npm run test` **245 files / 2,427 tests PASS** on
**Node 24** (vitest is still broken on Node 25 in this repo: 82 failures on
`window.localStorage.clear`). User CI on #169: **six of seven green**, including
`frontend` (which runs the 623 Playwright specs), both `e2e-backed` lanes,
`ipfs-backed` and `channel-sync-backed`; **`contract` is red and expected to be**
— its diff is exactly the two additions from core#171 and nothing else. SC7
no-regression: `TestDeleteAccountFlow`, `TestAdminUserManagement`,
`TestAdminSetsEmailVerified` and the A12 auth/session suites all pass alongside
the three new tests. The meta compose render was not re-run: no compose, script
or env file changed. **Unverified:** the tagged real-PostgreSQL `internal/store`
integration lane was not run locally (the lab is native rather than the compose
stack) — repo CI's `integration` job ran it and is green; and vidra-search was
not started, which nothing in this slice needs.

**What failed first, beyond the two defects.** `psql -At` renders a bare boolean
as `t`/`f` and only a text-concatenated one as `true` — three assertions were
wrong about the LAB rather than the product and are restated in addenda rather
than silently re-run. The **first attempt at the baseline probe never ran the
baseline binary at all**: `pkill -f 'a16sock/vidra-api$'` did not match a process
started as `./vidra-api` from that directory, the second binary died on
`address already in use`, and the patched server answered every "baseline"
assertion — those rows were discarded and the probe redone with the bind failure
checked explicitly. The upload-finalize worker **drains in batches**, so reading
a video's state immediately after `complete` returns 200 shows `draft`; the first
quarantine run convinced itself the gate had not fired when in fact every video
was processed *after* the gate was turned back off. The public profile route is
`/users/{username}/profile`, not `/users/{username}`. And an evidence-recorder
crash on a non-serializable `set` **truncated the results file mid-write**; it
was repaired by trimming to the last complete row, nothing was lost, and the
recorder now serializes defensively.

**Findings recorded, not fixed.** (1) **No last-admin guard and no owner
protection** — any admin may demote or delete any other, the instance owner
included; only the self-change guard stands between an instance and zero admins.
(2) **Approval and rejection notify the applicant of nothing** — no notification,
no mail; they discover the outcome by trying to sign in. (3) The **approval queue
is admin-only**, so a moderator cannot triage signups; whether that is the
intended split is a product call. (4) Every field of a **tombstone other than
`is_active`** is still writable (role, quota, flags); the writes are inert,
because the session lookup requires `deleted_at IS NULL` and the row can never
authenticate, but they are accepted. (5) `admin.user.update` records a
**free-text reason string** rather than the structured `changes` array the audit
envelope carries, so a consumer must parse prose to know what changed.

**ADM-01 → PASS (candidate; unmerged)**, evidence
`docs/evidence/a16-users-roles.json`. **A16 stays OPEN**: ADM-02 (reports,
video blocks and quarantine, then mutes and watched words) is untouched here.
Delivery order: **core#171 first** (it carries the `deleted_at` contract
addition), then **user#169** (its `contract` check goes green the moment core
merges), then this evidence PR. Nothing is merged here and no deployment is
authorized. The lab was torn down — Postgres and Redis stopped, their data
directories removed, both binaries and the `origin/main` worktree deleted, no
listener left on 8088/3100/3200 — and no lab artefact is committed.

## A16 quarantine, video blocks and report context — 2026-09-06

**ADM-02 does NOT flip. A16 stays OPEN.** This is the second of three A16
slices — the video-and-report half of the moderation row. Three defects were
found: **a blocked video was still embeddable through oEmbed**, **a reported
direct message reached the moderator with no message in it**, and **the
server-rendered watch page keeps serving a blocked video's title and its whole
video document to anonymous crawlers indefinitely**. The first two are fixed
TDD-first in [core #172](https://github.com/yegamble/vidra-core/pull/172); the
third is a vidra-user caching decision and is recorded, not patched. **No
migration** (core stays at schema 129), **no OpenAPI change** (both fixed fields
were already documented), no generated file hand-edited, and **no vidra-user PR**
— the frontend already renders everything the fixes restore. [Sanitized
evidence](evidence/a16-quarantine-blocks.json) records **236 assertions across
twenty-one phases on one clean database**, with vidra-search stood up natively so
every index claim is a `search.documents` readback, plus a real-Chromium
walkthrough. Twelve rows failed: **two are the defect answering wrong** and ten
are lab errors, every one restated in an addendum rather than quietly re-run.

**The per-surface promise, measured on one video per state rather than reasoned
about.** Six actors (anonymous, two viewers, the owner, a moderator, the admin)
against nine authenticated surfaces plus the three anonymous root ones, for each
of five actions. `in`/`absent` is feed membership; a number is the HTTP status.

| surface | quarantined | approved | blocked | unblocked | rejected |
|---|---|---|---|---|---|
| home feed / `/videos` listing | absent for **all six**, owner included | `in` for all | absent for all | `in` for all | absent for all |
| channel page (public) | absent | `in` | absent | `in` | absent |
| channel page (owner/editor view) | **listed, state `quarantined`** | listed | **listed, state `published`, no block marker** | listed | listed, `failed` |
| subscriptions feed | absent | `in` | absent | `in` | absent |
| `GET /videos/search` | absent | `in` | absent | `in` | absent |
| watch detail | 404 anon/A/B · **200 owner** · 200 staff | 200 all | **404 anon/A/B/owner** · 200 staff | 200 all | 404 anon/A/B · 200 owner · 200 staff |
| thumbnail + HLS bytes | 404 anon/A/B · 200 owner/staff | 200 all | 404 anon/A/B/owner · 200 staff | 200 all | 404 anon/A/B · 200 owner/staff |
| `GET /videos/{id}/embed-privacy` | 404 anon/A/B | 200 | 404 anon/A/B/owner | 200 | **200 for anonymous** |
| RSS `/feeds/videos.xml` | absent | `in` | absent | `in` | absent |
| `/sitemap.xml` | absent | `in` | absent | `in` | absent |
| oEmbed `/services/oembed` | 404 | 200 | **200 → 404 (fixed here)** | 200 | 404 |
| vidra-search index | never indexed | `eligible=true` | `eligible=false, suppressed_reason=blocked` | re-indexed `eligible=true` | `eligible=false, suppressed_reason=moderated` |

Everything in that table is a readback, not a claim: feed membership is the
video's id in the response, the index column is a row from `search.documents` in
the search service's own database, and the block column was taken with a
`video_blocks` row present and the video still reading `published`/`public` —
**a block changes neither state nor privacy**, which is exactly why the two
checks around the oEmbed leak both passed on it.

**Defect 1: a blocked video was still embeddable.** `handleOEmbed` asked
"published?" and "public or unlisted?" and nothing else, so a moderator block —
which touches neither — left it answering **200 with the title, the channel
name, a thumbnail URL and a ready-made `<iframe>`** to any CMS that resolved the
share link, in all three URL forms (`/videos/{uuid}`, `/embed/{uuid}`,
`/v/{code}`). It now consults `videoHiddenByBlock`, the same helper every other
read path uses; the route is unauthenticated so that helper's staff escape never
applies, and a blocked video is `404 "no video matches the url"`, byte-identical
to an unknown one. **The reason nothing caught it is worth more than the bug**:
`videoFakeRepo` modelled `video_blocks` only in `adminInventory`, while the
public-feed, channel, subscription, search, by-ids and related fakes all ignored
blocks — and every one of those SQL queries carries `NOT EXISTS (SELECT 1 FROM
video_blocks …)`. The fakes said a block changes nothing about what a viewer
sees, so **no handler test could have proved a block hides a video from any
feed**. `blockedFromFeed` now puts the predicate where the SQL has it, and the
new test asserts all three distribution surfaces at once.

**Defect 2: a reported DM arrived empty.** The whole message-report path worked
except the part that makes it useful. The body is snapshotted at report time
into `message_body_snapshot`, `ListReports` joins it, `moderation.Item` carries
it, `api/openapi.yaml` documents `message_id` and `message_body` on `Report`,
and `ModerationQueue.tsx` renders `report.message_body || "(message
unavailable)"` — but `reportView` never had the two fields, so **every reported
direct message in the queue read "(message unavailable)"**. A conversation is
private: that snapshot is the only thing a moderator will ever see of the
reported message, so the queue entry was unactionable. Two things hid it:
`TestDMReportMessage` asserted the 204 and stopped without ever reading the
queue back, and the fake report repo did not store the snapshot either.
`TestOpenAPIContract` fails on a route without a doc and a doc without a route —
**not on a response shape** — so a contract promising two fields the server never
sent was invisible. Paired probe, same lab, same report row, only the binary
different: on the pre-fix binary `message_body` is absent; on the patched one the
moderator reads the full text, in the API and in Chromium.

**The appeal path, stated because it was asked: there is none.** The string
"appeal" does not occur anywhere in vidra-core or vidra-user — no route, no
notification type, no UI. A creator whose upload is rejected receives one
`video_rejected` notification and has nowhere to answer it.

**What the moderator sees, and what the creator is told.** The quarantine queue
carries exactly eight fields — id, title, privacy, state, channel handle,
channel display name, **owner username** and created-at — and **no reason, no
prior-action history and no report linkage**; a moderator triaging a held upload
sees who uploaded it and what it is called, and nothing about whether this
creator has been actioned before. A report entry carries the reporter's username,
the reason, the status, the note and the target's context — and **never the
author of the reported thing**: a reported comment names its body but not its
commenter, and a reported DM names its text but not its sender, so the moderator
cannot act on the person without leaving the queue. A comment report also carries
no `video_id`, so there is no route from the report to the video the comment sits
on. On the creator's side: **approval notifies nobody**, **blocking notifies
nobody**, and rejection sends a `video_rejected` notification that names the
video and nothing else. The quarantine UI's own label says the rejection reason
is *"recorded in the audit trail — not shown to the owner"*; the first half is
not true. A sweep of **all 290 text/JSON columns in the database** for the note's
text found **zero** — the audit row records only `reason_provided: true|false`,
by the deliberate rule that moderator prose must not enter the security ledger.
So the prose a moderator types on rejection is **discarded entirely**, and the
UI promises otherwise.

**Blocking is invisible to the creator, which is the sharpest thing here.** A
blocked video 404s for its owner too (only staff are exempt), it leaves every
public surface, and no notification is sent — but the owner's own channel
management listing **still lists it, still reading `published`, with no field
that could say otherwise**. The admin inventory carries a `blocked: true` marker;
the owner's projection has no equivalent. A creator's video therefore becomes
unreachable to everyone including themselves while their own dashboard says it is
live, and nothing anywhere tells them why, when, or by whom.

**Defect 3, recorded not patched: the watch page keeps serving a blocked
video.** `lib/video.server.ts` reads the public video document with `next:
{ revalidate: 60 }` and a comment accepting that "watch metadata may lag a
title/thumbnail edit by up to a minute". Applied to a moderation hide it does not
lag by a minute — **it does not clear at all**. Measured: a watch URL rendered
once before the block was fetched **30 times over 175 seconds** after it, every
single response carrying `<title>Control Clip</title>`, `og:title`, the canonical
`og:url`, an `og:image` pointing at the thumbnail endpoint, **an `<h1>` in the
body and the whole serialized video document in the flight payload** — while
`GET /api/v1/videos/{id}` answered 404 to the same anonymous caller throughout.
A URL never rendered before the block is clean (200 with the generic title and a
"Loading video…" shell), which is what identifies the mechanism: Next's data
cache does not replace a cached successful body with a failed revalidation, so
the last good copy is served indefinitely. A JavaScript-enabled visitor still
lands on **"Video not found — this video does not exist, or it is private"**
because the client re-fetches; a crawler, a link-preview unfurler, a no-JS reader
or anything reading the HTML gets the video back. The fix is a policy call this
slice should not make alone — `freshness: "no-store"` on the two watch reads
buys correctness at one uncached core request per watch load, and a narrower fix
would need the cache to treat a 404 as invalidating — so it is recorded with the
file, the constant and the measurement rather than changed.

**Remote and instance blocks, and the line under them.** The instance blocklist
round-trips fully: a moderator blocks `blocked-instance.example` with a reason,
it reads back through the API with that reason, Postgres agrees, a second block
of the same domain is idempotent at one row, unblocking removes it, and both
actions are audited. All six wrong-actor attempts (ordinary user 403, anonymous
401, on block/list/unblock) leave the table at exactly one row. The remote-video
blocklist reads (empty), blocking an unknown remote id is 404, and the list is
403/401 for a user/anonymous. **The "affected feeds and search" facet for remote
content is UNVERIFIED**: this lab holds **zero** `remote_videos` and zero remote
actors, federation is not enabled, and A29 owns the two-instance proof — so no
remote video was hidden from anything here, and nothing in this section should be
read as evidence that it would be.

**Unauthorized and bulk, inventoried explicitly.** Every route this slice touches
was attempted by the wrong actor and answered the shipped way with nothing
changed: approve, reject and the quarantine queue are **staff** (moderator 204/
200, user 403, anonymous 401); block, unblock and both block lists are **staff**;
report resolution is **staff** and report deletion is **admin-only**; reporting
anything needs auth (anonymous 401) and reporting a DM you are not a participant
of is **404**, not 403, so the existence of the message is not leaked. After the
six quarantine refusals both held videos were still `quarantined`; after the four
block refusals `video_blocks` was still empty; after the two resolve refusals the
report was still `open`. Idempotency: blocking twice is 204 with one row,
unblocking an unblocked video is 204, reporting the same message twice creates
one row, approving an already-published video is **409** (not a second publish)
and rejecting an already-rejected one is 409. **There is no bulk endpoint and no
multi-select anywhere**: no admin or moderation route in the OpenAPI document
takes an array body, and `ModerationQueue`, `QuarantineQueueView` and
`BlockedVideosView` have no checkboxes and no selection state — a moderator
acts on exactly one item at a time. **Zero 429s** in the whole run, at shipped
limits (general 120/min paced at ~109, auth 10/min with one login per actor).

**The E2EE promise holds because encrypted messages cannot be reported at all.**
An encrypted conversation is a distinct, immutably-flagged row whose traffic
lives in `e2ee_messages`, while `POST /messages/{id}/report` resolves ids in
`messages`. Proven rather than described: B registered a device, opened an
encrypted conversation with A and sent an envelope; the send wrote **zero** rows
to `messages` and one to `e2ee_messages`, the ciphertext round-tripped
byte-identically, and A reporting the real envelope id is **404** with no report
row created. There are five report routes in the contract and none of them
accepts an envelope, and `EncryptedThreadView` renders no `ReportButton` — so the
UI offers nothing the API would refuse. Nothing of an encrypted message can reach
a moderator, and nothing pretends otherwise.

**The browser walkthrough.** Real Chromium against the production build served
from `.next/standalone` behind one origin, with hard reloads. Signed in as the
moderator: the Moderation nav appears, `/moderation` renders the queue with
Accept / Reject / **Block video**, and the message report's detail pane shows the
DM's text under a "Direct message" label with the internal note — the visible
proof of defect 2's fix, where the same pane read "(message unavailable)" before.
`/moderation/quarantine` lists the held upload with `QUARANTINED` / `PUBLIC`
pills, the owner and channel, and the rejection-reason box carrying the label
this section quotes. Blocking from the queue's own button turns the action bar
into "Video blocked · Manage", records the **report's reason** as the block
reason, and `/moderation/blocked` then lists the video with "blocked 24s ago · by
dana", the reason and an Unblock button; `/moderation/blocked/remote` renders
`BlockedRemoteVideosView` with its empty state. Signed out, with all three
videos blocked, the anonymous channel page reads **"0 videos — this channel has
not published anything"** and the watch URL renders **"Video not found"** — with
the stale `<title>` from defect 3 still on the browser tab.

**Gates.** Core `make ci` **passed** (fmt-check, vet, migrate-lint,
openapi-verify, sqlc-verify, test-race); `go test ./internal/httpapi/ -count=1`
passes at every revision. SC7 no-regression: the named A16 slice-1 and A12 report
tests — `TestReportVideoAndModerate`, `TestReportCommentAndUnknown`,
`TestReportAccountAndModerate`, `TestReportValidationAndAuth`,
`TestReportsStatusFilterIsValidated`, `TestAdminUserManagement`,
`TestAdminSetsEmailVerified`, `TestDeleteAccountFlow` — plus the oEmbed, RSS and
sitemap suites, **24 test functions, all pass** alongside the changed one.
vidra-user was not modified, so its gates are **not claimed and were not run**;
neither were the e2e suites, per its AGENTS.md. The meta compose render was not
re-run: no compose, script or env file changed. **Unverified:** the tagged
real-PostgreSQL `internal/store` integration lane was not run locally (the lab is
native rather than the compose stack) — repo CI's `integration` job covers it;
and everything about **remote/federated** content, as stated above.

**Findings recorded, not fixed.** (1) **Defect 3 above** — the stale
server-rendered watch page, the most serious open item in this slice.
(2) **A blocked video is invisible to its owner in every way except the one
listing that would tell them**, with no notification and no reason. (3) **The
rejection note is discarded**, while the UI says it is recorded in the audit
trail. (4) **A moderator cannot see who wrote the content they are judging** —
no author on a comment report, no sender on a message report — and a comment
report carries no link to its video. (5) `GET /videos/{id}/embed-privacy`
answers **200 for a rejected (`failed`) video to anonymous callers**: it goes
through `videoReadBase`, which gates blocks, quarantine, scheduled and
transcoding but not `failed` (measured) or `draft` (from the same code path). It returns only `{"status":"enabled"}`,
so it is an existence oracle for a uuid the caller already holds, not a content
leak. (6) `handleAddPlaylistItem` does not check `video_blocks`, so a blocked
video can still be added to a playlist; the read side filters it, so the row is
inert. (7) The AP outbox's `CountPublicVideosByChannel` deliberately counts
blocked videos, so a federated `totalItems` over-reports what the collection will
serve — unverified in this lab, from code. (8) The quarantine queue shows a
moderator **no prior-action history** for the account whose upload they are
holding.

**ADM-02 stays OPEN.** Closed here: reports (video, comment, message) with staff
review, notes and resolution; video blocks and unblocks with their affected feeds
and search; quarantine approve and reject; the remote-video and instance
blocklists as far as a single instance can prove them; and the unauthorized and
bulk inventory. **Remaining for the row: mutes (accounts and instances) and
watched words** — slice 3 — plus the remote-content facet that A29's two-instance
lab owns. Delivery order: **core#172 first**, then this evidence PR. Nothing is
merged here and no deployment is authorized. The lab was torn down.

## A16 moderation hardening — 2026-09-06

**No register row changes.** This is the repair slice for what A16 slice 2
recorded and could not take, plus one copy correction the search work left
behind. Five things were wrong and four of them are now fixed with a measurement
either side: **the server-rendered watch page kept serving a blocked video
indefinitely**, **the rejection note a moderator types was discarded while the UI
said it was recorded**, **a block was invisible to the creator it was aimed at**,
and **two block/state predicates disagreed with the per-surface promise**. One
migration ([0130](../vidra-core/migrations/0130_video_rejections.up.sql),
`video_rejections`, with its `.down.sql`), one additive OpenAPI change, one new
notification type. [Sanitized
evidence](evidence/a16-moderation-hardening.json) carries the timestamps,
the actor matrix and the numbers below.

**The cache leak, reproduced before it was fixed.** On a production build of
`origin/main`, a watch URL rendered once before the block was fetched **30 times
over 176 seconds** after it (block at 16:53:50, fetches 16:53:59 → 16:56:55), and
**every single response** carried `<title>Control Clip</title>`, `og:title`,
`og:description`, the canonical `og:url`, an `og:image` pointing at the thumbnail
endpoint, an `<h1>` in the body and the whole serialized video document in the
flight payload — while `GET /api/v1/videos/{id}` answered **404** to the same
anonymous caller throughout. The `/v/{code}` form of the *same* video, never
rendered before the block, was clean at the same instant: that is what identifies
the mechanism as Next's data cache rather than the route. **Privacy changes and
deletion share the path and leaked identically**: a video flipped to `private`
and another deleted at 16:57:23 were both still serving their titles at 16:58:44,
65–81 seconds later — past the 60-second window, because the window was never the
variable. Next does not replace a cached successful body with a *failed*
revalidation, so once the document 404s the last good copy is served forever.

**The mechanism chosen, and its cost, honestly.** `no-store` on the three public
watch-document reads in `lib/video.server.ts`. Shortening the window fixes
nothing, for the reason above; tag-based invalidation would need vidra-core to
call back into the frontend, and there is no such channel. **The cost is one
uncached `GET /api/v1/videos/{id}` per watch-page RENDER** — not two: React
`cache()` still deduplicates `generateMetadata` and the page body within a pass —
where concurrent views of one video could previously share a single backend read
for up to a minute. On a hot video that is the difference between roughly one
request a minute and one per view. The home page's featured-banner read is
uncached now too, but that page was already dynamic (`lib/feed.server.ts` is
`no-store`), so it gains one request and loses no caching tier. On the patched
build, the same three actions fired at 16:59:53 and **12 fetches over 89 seconds
starting the same second** returned **zero** hits on all four counters — blocked
by uuid, blocked by short code, made private, deleted — with the API 404
throughout. The blocked page now serves the instance's own `<title>`, **no `og:*`
tags at all**, no description, no thumbnail URL, and a "Loading video…" shell for
a no-JS reader; in Chromium it reads "Video not found" and the **browser tab
title is the instance name**, where slice 2 recorded the stale video title still
sitting on it. What did *not* change: the route still answers **200** with a
loading shell rather than 404 for a blocked or unknown video. That is
pre-existing, it leaks nothing, and it is recorded rather than widened.

**The rejection note, and the one place it deliberately does not go.** The reject
route has always accepted a `reason`; slice 2 swept all 290 text/JSON columns and
found it in none of them. It now lands in `video_rejections` (0130 — shaped
exactly like `video_blocks`: one row per video, the acting moderator, the
moment), reaches the creator on their `video_rejected` notification, and is read
back by staff on the moderation-inventory row, which is the only staff surface a
rejected video still appears on once it has left the quarantine queue. Measured
end to end: the creator's inbox reads *"A moderator rejected your upload “Held
Upload” — it was not published: Third-party music you do not hold the rights
to…"* after a hard navigation, `/moderation/videos` shows *"Rejected: …"* under
the state pills, and a SQL sweep of `audit_log` for the note's text returns
**zero rows**. That last part is a deliberate deviation from the brief, which
asked for the note in the audit row's structured payload. It is not
implementable and would have been a regression: `audit.normalizeEvent` validates
metadata against a **closed key allowlist with a 256-byte value cap** and states
that user prose never belongs there, so a 2000-character note makes the whole
event invalid and **deletes the audit row rather than enriching it** — and the
existing reject test already fails if the prose reaches the log stream. The
ledger keeps `reason_provided`; the words live in the moderation domain.

**The creator now learns their video was blocked, and is not told why.** The
owner/editor channel listing carries `blocked` (the SQL's `EXISTS`, mirrored in
the fake — the slice-2 fake-fidelity lesson bit again, and the marker test proved
nothing until `ListVideosByChannel`'s fake learned `video_blocks`). Measured with
a block in place, the row still reads `state=published` and `privacy=public`,
because a block changes neither — which is exactly why the marker had to be its
own field. The Studio row badges it **BLOCKED** beside **PUBLISHED** and says
*"Blocked by moderation — this video is not available to viewers, including you,
until a moderator lifts the block. Nothing else about it has changed."* The
notification is a **new `video_blocked` type**: `video_rejected` does not fit,
because it means an upload that never published, while a block takes down live
content and is reversible, and reusing it would have told the creator something
false. The whole payload was checked for the moderator's block reason: **absent**.
**Whether a creator may read a block reason is left OPEN as a product ruling** —
rejection notes are shown, block reasons are not, and that asymmetry is
deliberate but unratified. The block itself is unweakened: the owner's
`GET /videos/{id}` is still 404. **What is not fixed and is recorded**: the
single-video Studio deep link `/studio?video={id}` still shows its generic error
for the owner of a blocked video, because it reads `GET /videos/{id}`; opening
that read would flip a promise this slice measured, so the creator reaches the
video, badged, from `/studio/content` instead. **Unblocking still notifies
nobody.**

**The two predicate gaps.** `GET /videos/{id}/embed-privacy` answered **200** to
an anonymous caller for a rejected (`failed`) video: it reaches the row through
`videoReadBase`, which gated blocks, quarantine, scheduled and transcoding and
simply did not know about `failed`, while the detail route applied that rule
separately. The rule now lives in `videoReadBase` and the two agree — measured
404 anon, 404 viewer, 200 owner, 200 staff, against 404 anon on the detail route.
It is deliberately **not** extended to `draft`/`processing`: the detail route
answers 200 for those by the compatibility rule `videoVisibleForMedia` documents,
and the point of the fix is that the two routes agree. `handleAddPlaylistItem`
ignored `video_blocks`; adding a blocked video is now **404, byte-identical to an
unknown id**, so the route is not an existence oracle for taken-down content, and
`playlist_items` stayed empty.

**Clear-all copy.** vidra-search#37 made "Clear all" delete the search service's
raw records instead of anonymising them, so `/settings/search` saying it "unlinks
the rest from your account" **understated its own button** — as wrong as
overstating it, because that sentence is what a reader uses to decide whether
pressing it is enough. Replaced with the deletion wording, including what cannot
be deleted (the aggregate counters are recomputed within a day; the trending
counters cannot be edited and expire within eight days). The source comment
claiming the clear "anonymizes the raw `query_log` and `behavior_events` rows"
was corrected, the confirm modal is now true as written and was left alone, and a
component test pins the new sentence and asserts the old one is gone — verified
red against the pre-change component. **The one-day and eight-day figures come
from vidra-search#37 and were not re-measured here.**

**Unauthorized, once each.** Rejecting as the creator is 403 and anonymously 401;
blocking as a viewer is 403; the moderation inventory — where the note is
readable — is 403 for the creator and 401 anonymously; the `blocked` marker never
appears for a non-owner viewer or an anonymous caller. After all of them,
`video_rejections` still held exactly one row with the note unchanged.

**Gates.** vidra-core `make ci` **passed** (fmt-check, vet, migrate-lint,
openapi-verify, sqlc-verify, test-race), `go vet -tags=integration ./...` is
clean, and repo CI on core#173 is **7/7 green** including `integration` and
`prev-release-against-new-schema`. vidra-user: `npx tsc --noEmit` clean,
`npm run lint` 0 errors (2 warnings, both pre-existing on main), `npm run
lint:icons` pass, `npm run test` **2358 passed / 82 failed — and the same 82 fail
on clean `origin/main` in this environment**, seven files dying on
`localStorage.clear is not a function` under local Node 25 and this jsdom
(baseline measured by stashing the branch: 82 failed / 2345 passed on main).
Repo CI is the authority for those. **Unverified:** the frontend e2e and
e2e-backed suites (this repo's AGENTS.md forbids running them locally); the
`internal/store` integration lane locally, which repo CI ran green; anything
about **vidra-search**, which was switched off in this lab, so nothing here
re-proves a block's search suppression; and anything **remote/federated**, since
the lab holds no remote rows — the admin inventory's remote arm returning an
empty `moderation_note` is asserted from the SQL, not measured. The meta compose
render was not re-run: no compose, script or env file changed.

**Findings recorded, not fixed.** (1) The Studio single-video deep link, above.
(2) Unblocking notifies nobody. (3) The watch route's 200-with-a-shell for a
blocked, deleted or unknown video. (4) A creator can still `PATCH` a blocked
video's metadata — the update path has no block gate — while they cannot read it;
inert, inconsistent, out of scope here. (5) Reason-visibility for blocks, left
open above.

**For slice 3 and the admin follow-up.** A new notification type costs four edits
that must move together — the constant, `knownType()`, `KnownTypes()`, and the
frontend's `TYPE_LABELS` + `TYPE_ORDER` + `describeNotification` case; a missing
case falls through to "started following", this repo's most-repeated frontend
bug. `audit_log` cannot carry prose, so any slice wanting a moderator's words
persisted needs a moderation-domain table. Mirror a new predicate in
`videoFakeRepo` **before** trusting a green handler test. An inline `": "` inside
a plain-scalar OpenAPI description parses in Go and **breaks the frontend
codegen's YAML loader**. `PATCH /admin/instance-settings` takes a flat object;
the `{"settings":{…}}` shape is 422. And a synthetic mp4 fails the ffprobe media
probe, landing the upload in `failed` — generate a real clip with ffmpeg.

**Delivery order: core#173 → user#170 → this evidence PR.** user#170's
`contract-ci` is red until core#173 merges, by construction, because
`lib/api/generated.ts` is regenerated from core's branch. Nothing is merged here
and no deployment is authorized. The lab was torn down.

## A16 admin guards and signup notices — 2026-09-06

**No register row changes. ADM-01 stays PASS.** This is the ruling slice for the
two findings A16 slice 1 recorded and did not patch: **an ordinary admin demoted
the instance owner and got HTTP 200**, and **approving or rejecting a signup
notified the applicant of nothing**. Both were reproduced on the `origin/main`
binary before anything was written, so the "before" is a measurement rather than
a citation. One migration
([0131](../vidra-core/migrations/0131_users_is_owner.up.sql), `users.is_owner`,
with its `.down.sql`), one additive OpenAPI field, two new mailer methods, no new
notification type. [Core #174](https://github.com/yegamble/vidra-core/pull/174)
and [user #171](https://github.com/yegamble/vidra-user/pull/171). [Sanitized
evidence](evidence/a16-admin-guards.json) records **137 assertions on one
database, across a baseline binary and a patched one, plus a real-Chromium
walkthrough**, with **six failing rows that are all lab bugs, each restated and
passing in an addendum**.

**What origin/main actually did.** Admin `avery` demoted the instance owner
`mona` to `user` — **200**, and Postgres read `mona=user` afterwards. Deactivating
the owner was **200** too. Then the whole path to zero administrators, in three
calls: avery demoted mona, avery deactivated *itself* through
`POST /auth/me/deactivate` (**204**, because the admin routes' self-guard does
not cover the self-service ones), and
`SELECT count(*) … role='admin' AND is_active` answered **0**. The lab had to be
repaired with SQL, which is the point: there is no API route back, because every
route that could promote an admin requires an admin to call it. Signup, on the
same binary and a real SMTP sink: applying, approving and rejecting produced
**0 messages** and **0 notification rows**; the reviewer's note reached nobody.

**The owner marker, and exactly what its backfill can determine.** The marker is
`users.is_owner`, a column rather than an id in `instance_settings`, for three
reasons stated in the migration: the guards already read the target's `users` row
so it costs no extra query and cannot go stale between reads;
`users_single_owner_idx` (partial, `WHERE is_owner`) makes **at most one owner a
database invariant** — proven by a direct `UPDATE` on a second account being
refused by that index; and `instance_settings` is writable by every admin, which
is precisely the principal the guard restrains. It is written in exactly one
place: the owner-claim CTE.

The backfill uses **two independent, exact sources**, and marks a row only when
they resolve to one live account: the `auth.owner_claim` **success audit row**,
whose `actor_id` is the created account; and the equality
**`owner_claim_tokens.claimed_at = users.created_at`**, which is exact *by
construction* rather than a tolerance window — the claim is one statement whose
`UPDATE` sets `claimed_at = now()` while the `INSERT` takes `created_at` from its
`DEFAULT now()`, and inside one statement `now()` is the transaction timestamp.
That was confirmed on real Postgres, not reasoned about: the lab's two timestamps
are byte-identical to the microsecond. Each source alone was then shown to
identify the owner on its own, on a database seeded at schema 130 and migrated
up. What the backfill **cannot** determine, each proven to mark nobody: a
pre-0104 upgrade with no claim row and no audit row; an instance whose owner
account was hard-deleted (the tombstone is excluded on purpose — it can never
authenticate and would spend the single owner slot); the two sources naming
different accounts; and two accounts created at the exact claim instant. The
real backfill ran on the lab's own pre-0131 data and marked `mona` and nobody
else. The `.down.sql` drops the column and its index and the up re-applies
afterwards — applied directly with psql, because the api binary has **no
`migrate down` subcommand** (its usage is `up|version|force`).

**`vidra doctor` says so when it could not tell.** An instance with no marked
owner would otherwise be silent for ever: nothing badges anybody and no route
sets the marker afterwards. The new `instance owner` check reports ✓ with a
marked owner, and — measured against a seeded pre-0131 database — ⚠ *"no account
is marked as this instance's owner, so every administrator here is equal"*,
naming both sources the backfill needed and warning that there is **exactly one
owner slot and no transfer route** before it tells anyone to write it by hand.
Zero active administrators is a ✗ in the same check, because that is the state
the last-admin guard exists to prevent and the recovery is a database edit.

**The guards, and what they deliberately still allow.** Another admin demoting
the owner to `user` or to `moderator`, deactivating it, or deleting it is **422
`owner_protected`** on all four, with the row reading `admin/true/live`
afterwards. Editing the owner's **quota**, its **email_verified** flag, or
re-asserting the `admin` role it already holds is still **200** — none can lock
anybody out. The owner's **own** self-guards are untouched: self-demote is still
422 with *"cannot demote or deactivate yourself"*, not the new message, so the
sentence the owner has always read did not silently move. A moderator, an
ordinary user and anonymous are refused **before** any of this (403/403/401 on
both PATCH and DELETE, six refusals with the owner untouched after all of them).
The last-admin guard is **422 `last_admin`** and its reachable home is the
self-service pair: the sole admin's `POST /auth/me/deactivate` and
`DELETE /auth/me` — the exact call that took the baseline to zero — are both
refused, the account stays `admin/true`, and **the refusal is not a sign-out**
(`/auth/me` still answers 200 on the same token). Promote a second admin and the
same call is **204**. A plain user's own account still closes normally. Both
guards also cover `PATCH`/`DELETE /admin/users/{id}` as defence in depth, where
`requireRole` means the caller is always an active admin and the branch is not
reachable — said plainly in the code rather than dressed up as coverage. **This
is a check-then-act guard, not an atomic one**: two admins removing each other in
the same instant can still each pass their own count, and closing that needs
`SERIALIZABLE` or an advisory lock around the write. Recorded, not half-built.

**Tombstone writes (slice 1 finding 4).** All seven admin writes to a
hard-deleted row — reactivate, deactivate again, role, quota, both flags, and a
combined body — are now **422**, and a field-by-field readback shows **not one of
them landed**. Deleting an already-deleted row keeps its shipped **404**. The
refusal reuses the reactivation refusal's own 422 rather than minting a code for
it, and all seven are audited as failures carrying `reason_code=deleted_account`.
There is no legitimate surviving write: the session lookup requires
`deleted_at IS NULL`, so every one of those fields was inert, and "accepted and
ignored" is the shape that lets a console report a change that never happens.

**Signup notices, over real SMTP.** Approval mails the applicant *"Your account
on <instance> was approved"* carrying the account name, the sign-in page when a
public base URL is configured (`…/login`, built from the trimmed origin) and
**no credential** — checked, the fixture password does not appear in the body —
and the approved applicant then really signs in with the password from the
application. When the instance ALSO holds new accounts for email verification the
message says so instead of promising a sign-in that would be refused. Rejection
mails the applicant and **carries the reviewer's note verbatim**; a sweep of
`audit_log` for the note's text returns **zero rows**, which is deliberate — the
envelope's metadata allowlist caps values at 256 bytes and states that user prose
never belongs there, so prose travels by mail and the ledger keeps the shape.
Applying sends nothing (the decision is what the applicant is waiting on), a
repeat decision is 404 and sends nothing more, and the wrong-actor refusals — a
non-admin's 403 on both routes, anonymous 401 — send **nothing**, with the
request still pending afterwards. The queue stays admin-only. **Best-effort was
proven by killing the relay**, not asserted: with the SMTP sink down, approval is
still 204 and creates the account, rejection is still 204 and resolves the
request, and the two failures are logged without the applicant's address. The
reject SQL now `RETURNING`s the applicant so the notice needs no second read
racing the write.

**Audit shape (slice 1 finding 5) — implementable after all.** The envelope's
`allowedChangeFields` already carried `role`, `account_enabled`,
`email_verified` and `bypass_quarantine`; `storage_quota_bytes` was added beside
them (a byte count, not content). `admin.user.update` now writes the structured
`changes` array with **before and after on every field the request carried** —
measured: `role: admin→moderator`, `email_verified: false→true`,
`bypass_quarantine: false→true`, `storage_quota_bytes: default→2048`, and no
entry for the field the request did not mention — plus `resource_type=user` and
the target's id. The human `reason` line the admin audit view already renders is
**kept**, because removing it would break a shipped surface to fix a machine
consumer. The guard refusals carry `reason_code` (`owner_protected` ×4,
`last_admin` ×2, `deleted_account` ×7). Nothing secret leaks: the fixture
password and every address are absent from `reason` and from `changes`.

**The browser walkthrough.** Real Chromium against the production frontend build
served from `.next/standalone` behind one origin, signed in as **avery — the
other admin, the actor the guard defends against**. `/admin/users` renders the
OWNER badge on `mona` and on nobody else, beside avery's own YOU pill. Opening
mona shows **Deactivate and Delete account both disabled** (in the DOM, checked
by property, on the desktop detail *and* the mobile card), the role control
replaced by a static ADMIN pill where bob and pat still have their three-way
switches, and the line *"This is the instance owner's account — the account that
completed first-run setup. Another administrator can't change its role,
deactivate it or delete it."* The quota controls and both flag switches stay
live. **The handler refuses regardless of the DOM**, proven from inside the page:
re-enabling the button and clicking it does nothing (React resets `disabled`
first), so the write was issued directly from the page's own session — **422
`owner_protected`** on both the PATCH and the DELETE. Then the last-admin half on
its reachable surface: with avery demoted, mona's own `/settings` Danger Zone
answers her deactivate with the server's sentence verbatim — *"this is the last
active administrator on this instance; promote another admin first, or the
instance would have nobody who can reach its own console"* — and her account is
still `admin/true`.

**The console's last-admin gate is deliberately conservative, and one branch of
it is unreachable in the UI.** `GET /admin/users` filters by search text only, so
a searched or paged view cannot prove how many admins an instance has; the
frontend gate therefore fires only when the loaded rows are the whole unfiltered
instance, and otherwise leaves the control live for core to refuse. Separately,
the last-admin *reason* can never be the one an admin reads on `/admin/users`:
precedence is self → owner → last-admin, and reaching the last-admin branch for
a **non-self** target requires a caller who is not themselves a live admin, which
`requireRole` makes impossible. The vitest cases cover the branch; the console
surface that actually shows it is `/settings`.

**Gates.** vidra-core `make ci` **passed** (fmt-check, vet, migrate-lint,
openapi-verify, sqlc-verify, test-race) on the final revision and
`go vet -tags=integration ./...` is clean. Repo CI on core#174 is **7/7 green**
— GitGuardian, build-test, integration, ipfs-integration, ipfs-private-integration,
openapi and prev-release-against-new-schema. `ipfs-integration` failed once first,
on `TestIntegrationPublicVideoRoundTrip` **timing out at 301 s** — an IPFS
round-trip this slice does not touch, which had passed on the same branch's
previous revision — and passed on re-run in 5m22s; it is recorded as flaky here
rather than filed away as green. vidra-user: `npx tsc --noEmit` clean, `npm run lint` 0 errors
(2 pre-existing warnings), `npm run lint:icons` pass, `npm run test` **247 files
/ 2,448 tests pass on Node 24** (vitest is still broken on Node 25 here). User CI
on user#171: **six of seven green** including `frontend`, both `e2e-backed`
lanes, `ipfs-backed` and `channel-sync-backed`; **`contract` is red and expected
to be** — `lib/api/generated.ts` was regenerated (never hand-edited) from
core#174's spec, and its diff is exactly the one additive field. SC7
no-regression: `TestAdminUserManagement`, `TestClaimOwnerEndpointCreatesAdmin`,
`TestDeleteAccountFlow` and the A12 session-revocation suites all pass beside the
new tests. `TestDeleteAccountFlow` and `TestDeleteAccountErasesCoreOwnSearchRows`
needed one honest edit each: their single account is the harness's only admin, so
they now promote a successor before it stands down — which is the operator flow
the guard exists to force. The meta compose render was not re-run: no compose,
script or env file changed. **Unverified:** the tagged real-PostgreSQL
`internal/store` integration lane was not run locally (the lab is native rather
than the compose stack) — repo CI's `integration` job ran it and is green; and
vidra-search was not started, which nothing here needs.

**What failed first, beyond the two defects.** Six assertions failed on the lab
rather than the product and are restated in addenda rather than quietly re-run:
a multi-statement psql seed that omitted `audit_log.domain` **rolled the whole
seed back**, so a backfill case that should have found the owner found an empty
table; the api binary has **no `migrate down`**, so the down migration had to be
applied with psql; an account registered while approval mode was on never existed
to sign in with; a duplicate application is 409, not 202; `json.load(strict=True)`
rejects a mail body's own control characters; and one comparison passed
expected/actual in the wrong order. Two lab traps beyond those: the frontend's
`NEXT_PUBLIC_API_BASE_URL` is an **origin**, not an API path — building it as
`…/3100/api/v1` produced `POST /api/v1/api/v1/auth/login` and a login form that
said only *"Not Found"* — and it is **inlined at build time**, so fixing it needs
a rebuild, not a restart. `form_input` on the login form set values React never
saw; typing into the field worked.

**Findings recorded, not fixed.** (1) **There is no ownership transfer.**
`is_owner` is written only by the first-run claim, there is no route that moves
it, and an owner who deletes their own account leaves the instance permanently
unmarked. That is the natural next slice. (2) The last-admin guard is
**check-then-act**; simultaneous mutual removal is still theoretically possible
and needs `SERIALIZABLE` or an advisory lock. (3) An instance the backfill could
not resolve can only be marked with a hand-written `UPDATE`, which `vidra doctor`
now tells the operator — but an admin **system view** would be a better home for
it than a CLI. (4) The approval queue remains **admin-only**, so a moderator
still cannot triage signups; unchanged product call. (5) Unblocking still
notifies nobody (carried from the previous slice).

**For A16 slice 3 (account/instance mutes, watched words).** The audit envelope's
`changes` array is now a worked example: `allowedChangeFields` is a small
allowlist, adding to it is one line, and before/after needs the service to hand
back its pre-image — `admin.UpdateUserDetailed` is the shape. `audit_log` still
cannot carry prose (256-byte values, closed key vocabulary), so watched words
belong in a moderation-domain table and reach a person by mail or notification,
never through the ledger. Adding a `Mailer` method costs **four** implementations
that must move together — the interface, `noopMailer`, `mail.SMTP` and
`auth.CaptureMailer` — plus every test double in `internal/httpapi` and
`internal/auth` that satisfies the interface (`captureMailer`,
`captureResetMailer`); the compiler finds them, but budget for it. Adding a
column to `users` means appending it to **every** full-row column list in
`internal/store/queries/users.sql` or sqlc stops mapping those queries to
`sqlcgen.User` and generates per-query row structs instead. And any harness whose
single account is its only admin now needs a successor before that account can
deactivate or delete itself.

**Delivery order: core#174 → user#171 → this evidence PR.** user#171's `contract`
check goes green the moment core#174 merges. Nothing is merged here and no
deployment is authorized. The lab was torn down — Postgres, Redis and Mailpit
stopped and their data directories removed, both binaries and the `origin/main`
worktree deleted, no listener left on 8088/3100/3200 — and no lab artefact is
committed.

## A16 mutes, instance mutes and watched words — 2026-09-06

**ADM-02 flips to PASS (candidate; unmerged). A16's stopping criterion is met:
ADM-01 + ADM-02 are both PASS, so the item closes.** This is the third and last
A16 slice — the half of the row slice 2 left open. One defect was found and
fixed: **an account you have BLOCKED could put its username in your inbox by
following your channel, repeatedly.** Two surfaces still show a muted account to
the muter and are recorded rather than changed, because both are product calls
this slice should not make alone: the muted account's **own channel page**, and
**autosuggest**. [Core #175](https://github.com/yegamble/vidra-core/pull/175)
and [user #172](https://github.com/yegamble/vidra-user/pull/172). **No
migration** (core stays at schema 131), **no OpenAPI change**, no route or
response-shape change, no generated file hand-edited. [Sanitized
evidence](evidence/a16-mutes-watched-words.json) records **125 passing
assertions across eleven phases on one clean database**, with vidra-search stood
up natively — every recommendation and related rail below answers
`source: "search"`, so the rails were served by the real service and not core's
fallback — plus a real-Chromium walkthrough on the production build. **One row
failed, on the lab and not the product**, and is restated in an addendum rather
than quietly re-run.

**The shipped semantics, established from the code and then measured, not
assumed.** A mute is **one-way**: it hides the muted account's content FROM the
muter and never restricts the muted account. Proven by having the muted account
do everything a mute does not stop — bram commented on uma's video (**201**),
followed her channel (**204**), opened a conversation with her and sent a
message (**201**) — while uma had him muted. He is never told: his own mute and
block lists both read `total: 0` throughout. A **block** is the same predicate
plus one thing more, and the control isolates it: with a block in place
`POST /conversations` is **403** in both directions, with a mute it is **201**.
Core reads `muted_accounts` and `user_blocks` as one clause everywhere, so a
block inherits every row of the table below.

**The per-surface promise, measured on one account rather than reasoned about.**
Five actors and a synthetic federated instance, against every surface the mute
could reach. Each cell counts bram's two published videos (or his one comment,
one channel, one account) visible to that actor.

| surface | U before | U muted | U unmuted | C (control) | anonymous |
|---|---|---|---|---|---|
| home feed / `/videos` `?sort=recent` | 2 | **0** | 2 | 2 | 2 |
| feed `?sort=trending` | 2 | **0** | 2 | 2 | 2 |
| subscriptions feed | 2 | **0** | 2 | 0 (follows nobody) | 401 |
| comment thread | 1 of 3 | **0 of 2** | 1 of 3 | 1 of 3 | 1 of 3 |
| related rail (`source: search`) | 2 | **0** | 2 | 2 | 2 |
| home rail (`source: search`) | 2 | **0** | 2 | 2 | 2 |
| `GET /videos/search` | 2 | **0** | 2 | 2 | 2 |
| `GET /search/channels` | 1 | **0** | 1 | 1 | 1 |
| `GET /search/accounts` | 1 | **0** | 1 | 1 | 1 |
| `GET /search/suggestions` | 4 | **4 — byte-identical to anonymous** | 4 | 4 | 4 |
| B's own channel page | 2 | **2 — still visible** | 2 | 2 | 2 |
| watch detail by direct URL | 200 | 200 | 200 | 200 | 200 |
| notification: B comments on U's video | 1 row | **0 rows** | — | — | — |
| notification: B follows U's channel (`origin/main`) | 1 row | **1 row — the defect** | — | — | — |
| notification: B follows U's channel (patched) | 1 row | **0 rows** | 1 row (control) | — | — |
| DM: B opens a conversation with U | 201 | **201 — a mute does not cut DMs** | 201 | — | — |
| the same, with a **block** instead | 201 | **403 — a block does** | — | — | — |

The search hydration predicate is core-side and that is what the table proves:
vidra-search returned ranked ids for a muted author and core's
`ListPublicVideosByIDs` dropped them, so the rail went to zero while still
reporting `source: "search"`. Every "0" has a live control beside it — cleo and
the anonymous caller still saw all of it at the same instant — so the exclusion,
not an empty index, is doing the work.

**The defect: a blocked account could ping you at will.** Every other
notification path already carried the mute/block predicate in SQL — the video
owner's `comment` (closed in A12), the `comment_reply`, the `new_video` fan-out
— but `NotifyFollow` took its recipient from the caller and consulted neither
table. It is also the one an unwanted account can repeat: the handler raises the
notification whenever the follow row is **genuinely new**, so unfollow and
follow again produces another. Measured on the `origin/main` binary with uma
having **blocked** bram: he followed umachan and her inbox went from 2 rows to
3, the new one reading `('follow', 'bram')`. `NotifyFollow` now resolves its own
recipient through a new `FollowNotificationRecipient` statement shaped exactly
like `CommentVideoOwnerRecipient` — the channel's owner, excluded on a
self-follow, an inactive or deleted owner, a mute, or a block in either
direction — because the caller cannot see the relationship. Paired probe, same
lab, same actors, only the binary different: blocked re-follow **delta 0**,
muted re-follow **delta 0**, and the control with every relationship lifted
**delta 1**.

TDD failed first, both ways, which is the part that matters. With the fake's
mute/block mirror removed, the handler test fails on all three relationships
(*"owner has 1 notifications after \"ada muted bob\", want 0"*); with the
statement's two `NOT EXISTS` clauses replaced by `AND TRUE` and sqlc
regenerated, the real-PostgreSQL test fails on the same three. The
`notifFakeRepo` mirrors both clauses on purpose — slice 2's fake-fidelity lesson
is what made a green handler test worth anything here.

**Instance mutes are fully proven, including their effect, and that was not
guaranteed going in.** The schema makes remote content representable locally, so
rather than mark the facet unverified this slice inserted one honest
`remote_actors` + `remote_videos` row and one federated comment on
`remote.example` at the DB level and measured the predicate. Before: uma, cleo
and an anonymous caller each saw the remote video on `?scope=all` and the
federated comment in the thread. With uma's mute: **the remote video and the
remote comment are gone for uma, present for cleo, present for anonymous**, and
her `GET /videos/search?scope=all` for it returns 0 where cleo's returns 1.
Unmuting restores both. The round trip is complete in the UI too — muted from
the **remote comment's own overflow menu** ("Mute instance"), listed on
`/settings/mutes/instances` as *"remote.example · muted just now"*, unmuted from
that page with the row gone from Postgres. Idempotent and normalised: muting
`REMOTE.EXAMPLE` a second time leaves exactly one lowercased row; a scheme or a
space in the domain is 422 and writes nothing.

**Instance mute versus instance block, on the same domain, minutes apart.** The
mute is **per-viewer**: uma stops seeing `remote.example`, cleo and anonymous
are untouched, nothing is audited, and no other user can tell. The moderator's
block is **instance-wide**: the same rows vanish for uma, for cleo **and for
anonymous**, it carries a reason that reads back through the admin API, and both
the block and the unblock are audited (`moderation.instance.block` /
`moderation.instance.unblock`). A user cannot see the block on their own mute
list (`total: 0` while it stands), so the two never collide. An ordinary user
blocking an instance is 403 and anonymous is 401, with `blocked_instances` still
at zero rows after both.

**Watched words, as shipped.** Matching is **case-insensitive substring**
(`strpos(lower(text), lower(word)) > 0`) — not word-boundary, not regex: the
term `Casserole` matched *"casseroles are underrated"*. It runs on **comment
create and edit**, and on **video create and edit** over `title + "\n" +
description` — an edit that introduces a term produced a match on both. It is
**staff tier, not admin-only**: dana the moderator added, listed and deleted
words and read the match queue exactly as mona the admin did. A duplicate
differing only in case is **409** (the unique index is on `lower(word)`); a
blank word is 422. **Matching never hides anything** — the flagged comment was
accepted 201 and stayed publicly visible to an anonymous reader while its match
sat in the queue. A match carries the term, the type badge, **the author's
username**, a link to the video, the video's title and the comment's body.

**Three things about that queue a moderator should know, all measured.**
**(1) There is no resolve and no dismiss** — every mutating verb is 404 on the
collection and on a single match id, and the view renders no action control. A
row leaves only when its content or its word is deleted, so an instance with an
active term accumulates matches forever with no triage state, unlike the report
queue, which has a status and a note. **(2) The excerpt is a live join, not a
snapshot.** `ListWatchedWordMatches` reads `c.body`, so a flagged comment edited
to remove the term keeps its match and now quotes a body with no term in it: the
queue really renders a row badged `pineapple / Comment / by cleo` above
*"never mind, plain cheese"*. The DM report path solved exactly this with
`message_body_snapshot` (0064); this table has no equivalent, so a moderator
cannot see what was flagged and an author can edit the evidence away while the
flag stands. **(3) Both deletions cascade.** Deleting the flagged comment
removes its match (`comment_id` is `ON DELETE CASCADE`, 0030) — the queue went
5 → 4 — and deleting a **word** removes all of its existing matches — 4 → 2 —
so a moderator pruning the term list silently discards its review history. A
deleted word raises no new matches, which is the half that is clearly right.

**Appeals and context: there is still none, and a mute needs none.**
`git grep -in appeal` returns **0** lines in vidra-core and **0** in
vidra-user — no route, no notification type, no UI. For mutes that is coherent
rather than a gap: the muted account is never told and never restricted, so
there is nothing to appeal. For a watched-word match it is the same, because a
match neither hides nor notifies. On staff context the comparison is worth
stating exactly, because it inverts slice 2's finding: a watched-word match
**names its author and links to its video**, while a comment report on the same
lab carries `reporter`, `reason`, `status`, `moderator_note`, `comment_id`,
`comment_body` and **no author field of any kind**. The report has a reporter
and a reason the match has no equivalent of; neither carries prior-action
history.

**Unauthorized and bulk, inventoried explicitly.** Anonymous is 401 on all six
mute routes; a self-mute is 422 *"cannot mute yourself"*; an unknown or
malformed target is 404; muting on someone else's behalf is **unrepresentable**
— no route accepts a muter parameter, the caller always is one. The four
watched-word routes are **staff**: moderator and admin succeed, an ordinary user
is 403 and anonymous is 401, on the list, the add, the delete and the match
queue alike. After every refusal `muted_accounts`, `muted_instances` and
`blocked_instances` were still at zero rows and the word list was unchanged.
**There is no bulk endpoint**: every mutating verb on the match queue is 404, no
route this slice touches accepts an array body (`{"words":[…]}` is 422, a
collection POST on mutes is 404), and the UI has no checkboxes and no selection
state. **Zero 429s** across **819 logged requests** at shipped limits (general
120/min paced at ~109, auth 10/min with logins 6.5 s apart).

**The browser walkthrough.** Real Chromium against the production build served
from `.next/standalone` behind one origin. Signed in as uma: bram muted from his
comment's own overflow menu, and after a **hard reload** the thread reads
"Comments (7)" with his comment gone and cleo's and the federated one untouched
(8 → 7). Muting `remote.example` from the federated comment's menu takes it to
**6**, with the two mechanisms visibly independent. `/settings/mutes` lists
*"bram · @bram · muted 1m ago"* under *"Accounts you have muted. Their videos and
comments are hidden from you."*, `/settings/mutes/instances` lists the domain,
and unmuting from each page restores exactly what it hid — bram's comment came
back, the count returned to 7. The search page reads **"No results — Nothing
matched 'bram'"**. `/moderation/watched-words` renders as dana with the section
nav, "2 watched words", the add form, and each row's *"added 14m ago by dana"*;
`/moderation/watched-word-matches` renders "2 flagged items" with the
`Video` / `Comment` badges, the author, the video link and the stale excerpt
above. An ordinary user and an anonymous visitor both get the shared
**"Moderators only"** gate on both pages, and nothing fetches.

**The two surfaces that still show a muted account, and why they were not
patched.** **(a) The muted account's own channel page.**
`ListPublicVideosByChannel` and `CountPublicVideosByChannelVisible` carry the
`video_blocks` predicate but no per-viewer mute/block clause, unlike every other
list — so with bram muted, `/channels/bramchan` reads *"BRAMCHAN · 1 follower ·
2 videos"* with both cards. That is **contract-conformant**: `POST
/me/blocks/{id}` enumerates its promise as *"their videos leave the blocker's
feed, search, and subscriptions, and their comments are filtered from comment
lists"*, and a channel page is none of those. It is also what Mastodon and
Twitter do. But `/settings/mutes` promises *"Their videos and comments are
hidden from you"* without qualification, so the contract and the copy disagree
and one of them has to move. **(b) Autosuggest.**
`GET /search/suggestions` returns **byte-identical** payloads to the muter, the
control and an anonymous caller — the channel `BRAMCHAN` and both video titles.
The screenshot worth keeping is the dropdown offering *"Bram Beta Clip"* and
*"Bram Alpha Clip"* over a results page reading *"No results"*. Filtering it is
not surgical: vidra-search's index stores static eligibility and **never
per-viewer state** by design, which is exactly what makes the ranked-ids
contract visibility-safe, and the free-text query suggestions have no owner to
join against. **The two compose**: the channel suggestion links straight to the
channel page, so together they are a complete route back to everything the mute
hid. Recorded with the file, the query and the measurement rather than changed.

**Gates.** vidra-core `make ci` **passed**, exit 0 (fmt-check, vet,
migrate-lint, openapi-verify, sqlc-verify, test-race; **79 packages ok, 0
failures**); `go vet -tags=integration ./...` clean; `go test -tags=integration
./internal/store/... ./internal/federation/...` **passed** against native
PostgreSQL 16 at schema 131 on a scratch database. vidra-user: `npx tsc
--noEmit` clean, `npm run lint` 0 errors (2 warnings, both pre-existing on
main), `npm run lint:icons` pass, `npm run test` **248 files / 2,449 tests
passed** on Node 24.4.1. No-regression: **52 named A12/A16 test functions pass**
beside the new ones, including `TestFollowCreatesNotificationForOwner`,
`TestCommentNotificationRespectsMutesAndBlocks`, `TestReportVideoAndModerate`,
`TestReportCommentAndUnknown`, `TestReportAccountAndModerate`,
`TestReportValidationAndAuth`, `TestAdminUserManagement`,
`TestDeleteAccountFlow`, `TestClaimOwnerEndpointCreatesAdmin`,
`TestFollowFlowAndFollowerCount` and `TestFollowNotificationBellEndpoint`. No
new viewer-scoped client read was added, so `lib/use-settled-session.ts` needed
no new caller. **Unverified:** federation itself — the remote rows are honest
local rows on one instance and no delivery, signature or two-instance behaviour
was exercised, which **A29 owns**; what is proven here is the predicate, not the
plumbing. Also the frontend e2e and e2e-backed suites, which this repo's
AGENTS.md forbids running locally. The meta compose render was not re-run: no
compose, script or env file changed.

**What failed first, beyond the defect.** One assertion failed on the **lab**:
the instance block/unblock audit check queried `action IN ('instance.block',
'instance.unblock')` when the shipped names are `moderation.instance.*`. Kept,
and restated in the next run at the correct names — 2 rows. Two browser errors
worth the same treatment: two `Unmute` clicks on `/settings/mutes/instances`
issued **no `DELETE` at all** (clicked before the row had rendered, then on a
stale element ref), which looked exactly like a broken control until the core
log showed no request; re-run carefully the same button deleted the row (`DELETE
204`, table empty). And a probe that should have been guarded from the start:
the "unmuted" column first read as the **anonymous** answer because uma's
15-minute access token had expired — **every discovery route is `optionalAuth`,
so an expired bearer is silently treated as anonymous** rather than refused.
Every viewer-scoped probe now asserts `GET /auth/me = 200` first. The earlier
baseline and muted runs survive that scare on their own evidence:
`/me/subscriptions/videos` is `requireAuth` and answered 200 in both.

**Findings recorded, not fixed.** (1) The channel page, above. (2) Autosuggest,
above. (3) The match excerpt is a live join, not a snapshot — the sharpest of
the three, and the only one needing a migration. (4) Deleting the comment, or
the word, destroys the match history. (5) No resolve or dismiss on the match
queue. (6) A muted account's DM still leaves one `message` row in the muter's
inbox — coherent, since a mute does not cut DMs, but it is the one row a mute
leaves. (7) The muted channel stays in the viewer's own FOLLOWING sidebar rail;
the viewer chose to follow, so it is defensible, but it is the one place the
name still shows. (8) **The UI offers exactly one place to mute an account** — a
comment's overflow menu, `api.muteAccount`'s single call site — so an account
that never comments cannot be muted from the UI at all; instance muting likewise
needs remote content on screen.

**ADM-02 → PASS (candidate; unmerged)**, evidence
`docs/evidence/a16-mutes-watched-words.json` beside `a16-quarantine-blocks` and
`a16-moderation-hardening`. **A16's stopping criterion is met** — ADM-01 and
ADM-02 are both PASS — so **A16 closes**. The follow-ups recorded across its
four sections are follow-ups, not blockers: no ownership transfer route; the
last-admin guard is check-then-act rather than atomic; unblocking notifies
nobody; block-reason visibility to the creator is an open product ruling;
`/studio?video={id}` still errors for the owner of a blocked video; an owner can
still `PATCH` a blocked video's metadata; a report carries no comment author and
no DM sender; the quarantine queue shows no prior-action history; the two
mute surfaces above; the watched-word excerpt and its missing triage state; and
**everything about remote/federated content, which A29 owns**.

**Delivery order: core#175 and user#172 are independent** — neither changes a
route or a response shape, so vidra-user needs no regenerated client and there
is no `contract-ci` ordering failure to expect — then this evidence PR. Nothing
is merged here and no deployment is authorized. The lab was torn down.

## A16 rulings applied — block reasons, unblock notices, ownership transfer — 2026-09-06

**No register row changes.** A16 closed this morning with ADM-01 and ADM-02 both
PASS and three product rulings recorded and unimplemented. This slice implements
them: **a creator could not read the reason their video was taken down**,
**lifting a block notified nobody**, and **`users.is_owner` had exactly one
writer and no way to move**, so an owner who closed their account left the
instance permanently unowned with a hand-written `UPDATE` as the only repair.
**No migration** — core stays at schema 131; `video_blocks.reason` (0021) and
`users.is_owner` (0131) already existed, and what changes is who may read them.
Five additive OpenAPI changes and one new route. [Core
#176](https://github.com/yegamble/vidra-core/pull/176) and [user
#173](https://github.com/yegamble/vidra-user/pull/173). [Sanitized
evidence](evidence/a16-rulings.json) records **91 API/DB assertions in one clean
run on a freshly migrated database**, two real-PostgreSQL concurrency tests, two
messages over a real SMTP conversation, and a Chromium walkthrough that found
two defects the unit tests did not.

**The block reason, and exactly how far it travels.** The reason a moderator
already writes for the staff block-list is now creator-facing on two owner-only
surfaces: `block_reason` on the owner's channel-management listing, beside the
`blocked` marker it explains, and `moderation_note` on the `video_blocked`
notification. Both are correlated on the same row — the listing's is a subselect
on the same `video_blocks` row as `EXISTS`, the notification's a `LEFT JOIN`
inside the same `CASE` that already carried the rejection note — so a badge and
its reason can never come from different reads. Measured: with a block in place
the Studio row reads *"Blocked by moderation … Reason: Third-party music you do
not hold the rights to"* while still reading `published`/`public`, and the
creator's inbox says *"A moderator blocked “Control Clip” — it is no longer
available to viewers: Third-party music…"*. **The block is unweakened**: the
owner's own `GET /videos/{id}` is still 404, as it is for a signed-in stranger
and for an anonymous reader, and the prose appears in **neither** a stranger's
nor an anonymous read of the same channel listing, nor in a stranger's inbox.
Lifting the block deletes the row, so an older `video_blocked` notice silently
loses its reason and renders as the neutral notice it was before this slice —
measured, and correct: the reason no longer applies.

**And the leak that ruling opened, closed in the same change.** The moderation
queue's "Block video" sent **the REPORTER's own free text** as the block reason.
That was harmless while block reasons were staff-only and is not now: it would
deliver a reporter's prose about a person to that person, on their own video and
in their inbox. The moderator now writes their own, in a field whose copy says
*"The creator sees this on their video and in their notification, so write it
for them"*; empty is allowed and lands the creator on the neutral notice. A
component test asserts the reporter's words never reach the request.

**`video_unblocked`.** A new type — the constant, `knownType()`, `KnownTypes()`
and prefs on one side, `TYPE_LABELS` + `TYPE_ORDER` + `describeNotification` on
the other, the four edits that must move together. It is deliberately its own
type rather than a second `video_blocked`, which would read as a SECOND takedown
in an inbox that renders by type. Delivered on `DELETE
/admin/videos/{id}/block`, best-effort, linking to the restored video. Two
details are load-bearing and both are measured: the owner is read **after** the
unblock (the mirror of the block path's read-before, because a blocked video
404s on every ordinary read), and `UnblockVideo` now reports whether a block was
actually **lifted**, so a repeated `DELETE` is still 204 and delivers **no
second notice**. A creator who turns the type off gets nothing.

**Ownership transfer.** `POST /api/v1/admin/owner/transfer` sits under `/admin`
because that is where the console surface and the `requireRole(admin)` gate
already are; the OWNER-only rule cannot live in `requireRole` at all, because
Vidra deliberately has no owner ROLE, so it is a service check and a non-owner
admin is **403 `owner_only`**. The caller re-enters their password — the same
confirmation the account-closing routes ask for, and this is the one admin
action that permanently strips the caller of a capability. The target must be an
active, non-tombstoned administrator other than the caller: **422
`owner_target_invalid`**, checked in the service for the readable error and
re-asserted inside the write for the race. Measured refusals, each with a
readback proving the marker did not move: a non-owner admin 403, a moderator
403, an ordinary user 403, anonymous 401, the owner with a wrong password 403,
and 422 for an ordinary user, a moderator, the caller themselves and a
deactivated admin, with 404 for an unknown id. **The former owner keeps their
admin role** — this moves the marker, not the role.

**Why the swap is one statement, and what proves it.**
`users_single_owner_idx` is a partial UNIQUE index and is not deferrable, so
splitting the clear and the set opens either a window with no owner (a crash
between them leaves the instance in the state the route exists to escape) or one
with two, which the index refuses outright. The clear provably runs first
because the main `UPDATE` joins an aggregate over it and an aggregate must
consume its whole input — without that forced ordering PostgreSQL is free to run
an unreferenced data-modifying CTE **after** the main query, and every transfer
would raise a unique violation. Against real PostgreSQL: the marker moves,
exactly one row holds it, the former owner is still `admin`, and every
ineligible target changes nothing including the clear. The race is **forced,
not hoped for** — firing two transfers from goroutines proves nothing, because
they serialize and both legitimately succeed in order. Two transactions are
interleaved deliberately: the second blocks on the first's uncommitted marker,
and when the first commits the second is refused by the index with SQLSTATE
23505, which the route answers **409 `owner_transfer_conflict`** with nothing
changed. One winner, one marked account.

**Both parties are mailed, over a real SMTP conversation** (a minimal sink that
speaks the protocol; there is no mailpit on this machine). The new owner's
message names the former owner, carries the admin console URL and **no
credential**; the former owner's names the new one, says they remain an
administrator, states exactly what they gave up, and tells them to change their
password if it was not them — the notice that matters if the transfer was not
their idea. Best-effort is proven at the service level: with a failing mailer
the transfer still commits. **No new notification type**: none of the ten
existing types means "you now own this instance", and adding an eleventh for one
event that already sends mail is not worth the four coordinated edits — said
plainly rather than half-built. One `Mailer` method, four implementations plus
the doubles. Audited structurally: `is_owner` joins the envelope's change
allowlist beside `account_enabled` and `email_verified`, the resource is the
account that **gained** the marker, and `count` records how many held it before
— 0 on an instance the 0131 backfill could not resolve, which is a fact an
operator reading the ledger wants. The password reaches neither the log stream
nor the ledger.

**The owner cannot leave without handing it on.** `DELETE /auth/me` and
`POST /auth/me/deactivate` by the marker's holder are **422
`owner_must_transfer`**, checked **after** the last-admin guard so a sole
owner-admin reads the actionable sentence first ("promote another admin"), then
this one. Deactivation is gated for the same reason deletion is: a disabled
account cannot sign in, so it can never call the transfer route again.
Measured: both refused, the refusal is **not a sign-out** (`/auth/me` still
200), the row is still `admin`/active/owner afterwards, and after the transfer
the former owner deletes themselves normally while the instance still has an
owner. A plain user's own account was never gated by this. Five existing tests
covered accounts that were the owner; each now hands the instance over first, or
runs as an ordinary second account where ownership was never the subject.

**One defect the lab found on the way.** The **owner-claim response** said
`is_owner:false` about the account that had just claimed the instance — the
claim statement is the one place the marker is written TRUE, but the response's
user view left the flag at Go's zero value, while the next login said true. That
payload is exactly what the console draws its owner-only controls from. Fixed,
with the assertion added to `TestClaimOwnerEndpointCreatesAdmin`.

**The browser walkthrough, and the two things it caught.** Real Chromium against
the production `.next/standalone` build behind one origin. As the creator: the
Studio row carries the badge and the reason, and the bell holds all three
renderings side by side — a block **with** its reason, a restoration, and an
older block whose reason went with the lift. As the owner: `/admin/users` badges
mona OWNER, avery's detail offers the transfer with the consequences stated
before the password is asked for, bob's shows the same control **disabled** with
*"Ownership can only go to another administrator"* and no password field; after
the transfer avery carries OWNER, avery's Deactivate and Delete are disabled and
the role control is a static pill. Her own `/settings` Danger zone answers her
deactivate with the server's sentence verbatim. **Two defects surfaced only
here**: `video_unblocked` had no notification icon or chip entry, so the
restoration rendered with the **follow glyph in a neutral circle** — the
moderation event dressed as a new follower, this repo's most-repeated frontend
bug wearing different clothes; and after a transfer the LIST reloaded but the
**session** did not, so the former owner was still offered a control core
answers 403. Both fixed, both with a test.

**SC5, the last-admin race: recorded, not built.** The guard has four write
paths, and they serialize against each other only if they share one lock, which
means the count and the write must sit in the same transaction. Two are a single
`UPDATE` and could carry a `SELECT … FOR UPDATE` roster lock in-statement, where
READ COMMITTED's post-wait re-check is exactly the recheck this needs. The hard
delete cannot: it is a multi-table erasure that also deletes blobs and fans a
federation `Delete` out, and holding a roster lock across that is worse than the
race. A partial fold buys almost nothing, because a mixed race — one admin
`PATCH`ing while the other self-deletes — stays open unless every path takes the
lock. The real fix is a transaction seam threaded through `admin`, `auth` and
`account` together: structural, not surgical. That reasoning now lives on
`ensureAdminRemains` so the next slice does not re-derive it.

**Gates.** vidra-core `make ci` **passed** (fmt-check, vet, migrate-lint,
openapi-verify, sqlc-verify, test-race) and `go vet -tags=integration ./...` is
clean; the tagged `internal/store` integration lane was run **locally against
real PostgreSQL** for the two new concurrency tests. vidra-user: `npx tsc
--noEmit` clean, `npm run lint` 0 errors (2 warnings, both pre-existing on
main), `npm run lint:icons` pass, `npm run test` **2,378 passed / 82 failed —
and the same 82, in the same 7 files, fail on clean `origin/main` in this
environment** (measured by stashing: 2,367 passed / 82 failed), dying on
`window.localStorage.clear is not a function` under local Node 25 and this
jsdom. Net: **+11 passing, zero new failures**; repo CI is the authority.
**Unverified locally, and what repo CI then found.** vidra-user's AGENTS.md
forbids running the e2e suites locally, so they were left to CI — and CI earned
its keep: two shipped specs clicked "Block video" and waited for the POST, which
no longer fires on that click, because a LOCAL block now asks the moderator for
a reason first. `e2e/moderation.spec.ts` and `e2e-backed/blocked-videos.spec.ts`
both write one and confirm; neither is weakened (each still waits for the same
request and asserts the same outcome, with one step more in between), and the
mocked one now additionally asserts the request carries the MODERATOR's words
rather than the reporter's — which is the point of the change and was
previously untested end to end. That is a regression the component tests
structurally could not see, and it is recorded here rather than quietly fixed.
Also **unverified**: anything about **vidra-search**, which was not started, so
nothing here re-proves that a block suppresses a search document; and anything
**remote/federated** — the lab holds no remote rows. The meta
compose render was not re-run: no compose, script or env file changed.

**Findings recorded, not fixed.** (1) The last-admin race, above. (2)
`AdminVideosView` and the watch-page action menu still block a video with **no
reason at all**, so the creator gets the neutral notice from those two surfaces;
only the moderation queue asks for one. (3) `caption_ready` has no notification
chip entry either — pre-existing, and it falls through to the same neutral
circle. (4) Remote video blocks still record the reporter's reason, which is
correct only because `remote_video_blocks` reaches no local creator and sends no
notification; if that ever changes it becomes the same leak. (5) An instance the
0131 backfill could not resolve still has no owner and no route that can mint
one — `vidra doctor` reports it and a hand-written `UPDATE` is still the repair.

**Delivery order: core#176 → user#173 → this evidence PR.** user#173's
`contract` check is red until core#176 merges, by construction, because
`lib/api/generated.ts` is regenerated from core's branch spec and never
hand-edited. Nothing is merged here and no deployment is authorized. The lab was
torn down — postgres, redis, the SMTP sink, the api, the Next server and the
proxy all stopped, the data directory removed, no listener left on
3100/3200/8088/52525/55432/56379 — and no lab artefact is committed.

## A16 ruling applied — mute scope and mute/block controls — 2026-09-06

**No register row changes.** A16 closed this morning with ADM-01 and ADM-02 both
PASS. Its last slice recorded two surfaces that still showed a muted account to
the muter — the account's **own channel page** and **autosuggest**, which
together were a complete route back to everything the mute hid — and the fact
that the UI offered **exactly one place to mute**: a comment's overflow menu,
`api.muteAccount`'s single call site, so an account that never commented could
not be muted at all. The owner has ruled on all three and this applies the
rulings. Two PRs: [core #177](https://github.com/yegamble/vidra-core/pull/177)
and [user #174](https://github.com/yegamble/vidra-user/pull/174). **No
migration** (core stays at schema 131); **one additive OpenAPI change**, which
sets the delivery order. [Sanitized
evidence](evidence/a16-mute-scope.json). **Zero 429s** across 184 core requests
at shipped limits.

**The channel page, measured on two binaries over one database.** The gap was
reproduced live before it was closed: on the `origin/main` binary (8372a57),
with uma having muted bram, `GET /channels/bramchan/videos` still answered her
with **both** of his videos — delta 0 — while an anonymous caller saw the same
two, so the mute did nothing there at all. Swap the binary, same database, same
fixtures, and the same call answers **0 rows and `total: 0`**, restores to 2 on
unmute, goes to 0 again on a **block**, and restores again on unblock — with
cleo, the anonymous caller and **bram's own view of his own channel** all at 2
throughout, and uma's view of *cleo's* channel untouched, because the clause is
keyed on the owner rather than on channels in general. `ListPublicVideosByChannel`
and `CountPublicVideosByChannelVisible` now carry the same two `NOT EXISTS`
clauses `ListPublicVideosSorted` has, on a nullable `viewer_id`; the list and the
count were asserted together on every read, because a page returning no rows
while the total still promised one would promise a page the list cannot serve.

**What the page shows instead, and why the header stays.** The convention the
block case set is that a mute or a block hides an account's CONTENT and never
its existence — you can still open the page, and you have to be able to, because
that is where the control that lifts it lives. So the header is untouched
(avatar, display name, `@bramchan`, follower count) and only the grid changes.
It does not say *"No videos yet — this channel has not published anything"*,
which would be a lie told to the one viewer who can see it; it says **"Videos
hidden — You muted this account, so its videos are hidden from you. Unmute it
from the menu above to see them again."**, and the block gives the block's
wording. A channel that genuinely has no videos still gets the ordinary empty
state; uma's own channel, in the same session, read *"No videos yet"*.

**Per route, because "the channel page" is four reads and one of them is a
route that does not exist.** `GET /channels/{handle}` stays **200** and
unfiltered, deliberately, per the paragraph above. `GET /channels/{handle}/videos`
is what this slice fixed. `GET /channels/{handle}/stats` answers the muter
**404** and `GET /channels/{handle}/live` **403** — both are `requireAuth` plus
an owner/editor check, so neither is reachable by a non-owner and neither can
leak. `GET /channels/{handle}/donation-addresses` is **200 with no auth
middleware at all**, so the Support button stays on a muted account's header;
coherent with the header staying, and recorded rather than widened. A channel's
playlists are **not a route** — nothing lists them (only `POST /playlists`,
`/me/playlists` and `/playlists/{id}` exist), which `ChannelView`'s own comment
already said. One route beyond the ruling's scope is worth naming: **`GET /live`,
the public "Live now" rail, takes no viewer at all** (`ListLivePublic(ctx, limit,
offset)`), so a muted account's live stream would still be listed to the muter.
Read from the code, not measured — the lab had no live stream.

**Autosuggest: the server stayed viewer-agnostic and the client learned to
filter.** The ruling is exact about why. vidra-search's index stores static
eligibility and **never** per-viewer state, which is precisely what makes the
ranked-ids contract visibility-safe, so per-viewer filtering cannot live there.
Measured, with uma's mute in place: `GET /search/suggestions?q=bram` returns
**byte-identical** payloads to uma, to cleo and to an anonymous caller — the
channel `Bram Channel` and both video titles. Unchanged, as ruled.

The client could not act on that alone, and the reason is a data limit rather
than a decision: a suggestion carries `channel_handle` for a channel and
`video_id` for a video, while the mute and block lists carried only
`user_id`/`username`, with nothing joining them. A client could have resolved
the owner of each suggested handle only with **a request per keystroke**, which
would be worse than the gap. So both lists now carry the account's
**`channel_handles`** — one `ARRAY()` subquery, no new route, no new query,
`[]` and never `null` for an account with no channel, in the SQL, the service
and the JSON alike, because a client that has to null-check a set it intersects
against is one missed check away from showing what the mute hides. That is the
OpenAPI change, and it is what makes the frontend's filter exact instead of a
name-matching heuristic.

**In real Chromium, on the production build behind one origin.** Signed in as
uma with nothing muted, typing `bram` gives three suggestions: the two clips and,
under a **CHANNELS** heading, *"Bram Channel"*. Muting bram **from his channel
page's own kebab** — the new control — takes the grid to "Videos hidden" with no
reload, and the header's search box, a different component entirely, drops the
channel suggestion on the next keystroke with **no reload either**: two
suggestions, both queries, the CHANNELS group gone. A **hard reload** keeps both:
the page still reads "Videos hidden" because the SERVER hid the videos, and the
dropdown still shows two because the client filtered them, with the suggestion
request going out and answering 200 exactly as before. The control that makes
those negatives mean something ran at the same instant: an **anonymous** visitor,
with uma's mute still in place, saw both videos on the channel page and all three
suggestions including *"Bram Channel"*.

**One read per settled session, not one per keystroke.** On a full load of the
channel page as uma the network log shows exactly **one** `GET
/me/mutes/accounts?limit=100` and **one** `GET /me/blocks?limit=100`, both
**after** the `POST /auth/refresh` that settles the session — the
`useSettledOptionalSession` guard the frontend-hardening sweep introduced —
and five more typed characters added neither. The lists are cached at module
scope and shared, which is why the channel page's mute reached the header's
search box at all. A failed read leaves the set empty, which keeps every
suggestion: the degraded direction is showing more, never hiding a stranger's
channel.

**The control, on both pages that are ABOUT an account.**
`AccountModerationMenu` is one component rendered by `ChannelView` and
`UserProfileView`, in the comment menu's overflow-kebab idiom with its labels
verbatim (Mute / Unmute, Block / Unblock, Block styled danger). It reflects the
current state on load: with bram muted, the menu on **his profile page** opened
on **"Unmute"**, and unmuting from there restored his **channel** page to two
videos on the next load — the two surfaces share one store. It renders **nothing**
for an anonymous visitor (that header shows only "Sign in to follow") and nothing
on your own channel, where the whole visitor cluster is already hidden. A failed
call is silent and the label does not flip, which is the comment menu's
behaviour exactly — a gap the two now share rather than one this control
introduces.

**Copy.** The two page headers are **unchanged**, and that is the point: A16
slice 3 recorded that `/settings/mutes` promised *"Their videos and comments are
hidden from you"* while the contract did not cover the channel page, and that one
of them had to move. The contract moved, so the sentence is now true rather than
aspirational. What did change is the two **empty states**, each of which said
less than its own page header two lines above it — the mutes one named only
comments, the blocks one only messaging. Both now name the hiding, the channel
page included, and both were read back in the browser.

**Failed first, in four places.** The httpapi test fails on the mute row **and**
the block row without the SQL. With the two `NOT EXISTS` clauses replaced by
`AND TRUE` and sqlc regenerated, the real-PostgreSQL test fails on both
relationships — so the clause, not the fixture, is doing the work; it applies and
then **lifts** each relationship, and asserts that being blocked BY the owner
changes nothing, which pins the clause's shape rather than its mere presence. The
`channel_handles` test fails on all four rows before the field exists. And with
the frontend filter neutered to the identity and the channel page's predicate
forced false, **4 of the 12 new frontend tests fail** — both suggestion cases and
both channel-page cases — while the anonymous, degraded-read, once-per-session
and control-state cases keep passing, which is what makes the four mean
something. `videoFakeRepo` mirrors the new clause and its Count delegates the
viewer through; the mute and block fakes mirror the `ARRAY()` subquery. A green
handler test against a fake that disagrees with the SQL is how this gap survived
four slices of mute work.

**Gates.** vidra-core `make ci` **passed**, exit 0 (fmt-check, vet, migrate-lint,
openapi-verify, sqlc-verify, test-race); `go vet -tags=integration ./...` clean;
`go test -tags=integration ./internal/store/... ./internal/federation/...`
**passed** against native PostgreSQL 16 at schema 131. vidra-user: `npx tsc
--noEmit` clean, `npm run lint` 0 errors (2 warnings, both pre-existing on main),
`npm run lint:icons` pass, `npm run test` **250 files / 2,472 tests passed** on
Node 24.4.1, production `next build` pass. **The 2,460 tests that existed before
this branch pass unchanged — no existing spec was edited**, and all 12 new ones
live in one new file. **Unverified:** the frontend e2e and e2e-backed suites,
which this repo's AGENTS.md forbids running locally; `GET /live` with an actual
live stream; and anything federated, which A29 owns. The meta compose render was
not re-run — no compose, script or env file changed.

**One lab note worth keeping.** The four fixture videos are DB-published rows
with no media bytes: created through `POST /channels/{handle}/videos` (which
lands them at `draft`) and flipped to `published` with SQL. Every surface under
test here is a **list predicate** that reads `privacy`/`state` and the mute
tables and never the bytes, so the missing media cannot flatter the result — the
"No preview" placeholders in the walkthrough are that and nothing else. Stated
rather than left for a reader to infer from a screenshot.

**Findings recorded, not fixed.** (1) `GET /live` takes no viewer, above. (2)
`/channels/{handle}/donation-addresses` is unauthenticated, above. (3) A muted
account's **video-title** suggestions still appear — not a decision either: a
video suggestion carries only `video_id`, so no client-side filter can reach it,
and a mute never hid a direct watch URL (slice 3's table: watch detail 200 for
every actor). (4) Neither this menu nor the comment menu reports a **failed**
mute or block. (5) A muted account's profile page still lists its **channels**;
the cards now link to pages that are empty for the muter, so nothing hidden is
reachable through them, but the names are on screen — the same shape as the
FOLLOWING sidebar rail slice 3 recorded. (6) The optimistic handle update is
additive, so unmuting drops only the handles the calling page knows; a channel
this session never saw can stay in the hidden set until the next read, which is
the safe direction.

**Delivery order: core #177 first, then user #174, then this evidence PR.** The
frontend's filter reads `channel_handles`, so `contract-ci` on the user PR is
**expected RED until core merges** — `lib/api/generated.ts` is regenerated from
core's branch spec and never hand-edited. Nothing is merged here and no
deployment is authorized. The lab was torn down — postgres, redis, vidra-core,
vidra-search, the Next server and the proxy all stopped, the data directory
removed — and no lab artefact is committed.

## A16 ruling applied — watched-word queue snapshots and triage; live rail mutes — 2026-09-06

**No register row changes.** A16 closed this morning. Its last slice recorded
two defects in the watched-word review queue — **the excerpt was a live join,
not a snapshot**, and **there was no resolve and no dismiss** — and the
follow-up slice recorded one more, from a code read it could not measure:
**`GET /live`, the public "Live now" rail, takes no viewer at all**, so a muted
or blocked account's stream stays on the muter's rail while every other public
list has dropped it. The owner ruled all three fixed and this applies the
rulings. Two PRs: [core #178](https://github.com/yegamble/vidra-core/pull/178)
and [user #175](https://github.com/yegamble/vidra-user/pull/175). **One
migration** ([0132](../vidra-core/migrations/0132_watched_word_match_snapshots.up.sql),
schema 131 → 132, with its `.down.sql`); **one additive OpenAPI change**, which
sets the delivery order. [Sanitized evidence](evidence/a16-word-matches.json).

**The defect, reproduced before it was closed and then inverted.** cleo posted
*"I want pineapple on it"* on a lab with `pineapple` watched; the queue flagged
it. cleo then edited the comment to *"never mind, anchovy instead"*. On the old
shape that left the queue rendering a row badged `pineapple / Comment / by cleo`
above a body with no term in it — a moderator could not see what was flagged and
an author could edit the evidence away while the flag stood. On the new one the
match keeps `matched_text: "I want pineapple on it"` while `comment_body`, still
the live join, reads the edited text and **`target_status` flips to
`edited_away`**. The same edit raised a **second** match for `anchovy` with its
own snapshot and `target_status: present`, which is the other half of the rule:
a term already recorded hits the `ON CONFLICT` and keeps its ORIGINAL snapshot;
a term the edit introduces gets a new row. **The video arm is treated
identically** and was measured separately — a description carrying the term
snapshotted `"my mixtape\npure pineapple inside"`, the flagger's own
`title + "\n" + description` join, and editing the description away left the
snapshot untouched.

**What the snapshot carries, and one decision inside it.** `matched_text`, plus
`matched_term` (so the term survives its word being deleted), plus
`match_offset`/`match_length` — **in runes, not bytes**, because the review UI
highlights by slicing the string and a byte offset would cut a multi-byte
character in half. `-1` means *not located* and is the honest answer rather than
a guess: Postgres `lower()` and Go's `ToLower` need not agree on every
locale-sensitive rune, and every **backfilled** row carries it. That marker,
`snapshot_backfilled`, is the point of the backfill: it was proved by seeding two
pre-0132 rows and running the migration, and one of them had already had its term
edited away, so its backfilled quote **is** the clean body. A backfilled quote is
the text as it reads today, which is exactly the thing the defect says cannot be
trusted, and it must never be mistaken for a flag-time capture.

**The cascade ruling is a split decision, and the half not taken has a
mechanism.** Deleting a **word** used to delete its whole review history, so a
moderator pruning the term list silently discarded the record of everything it
had caught. That is closed: the FK is now `ON DELETE SET NULL`, the match
survives, the term reads back from the snapshot and the row reports
`term_active: false` — measured, both matches surviving the deletion of
`pineapple`. Deleting the **comment or video** still cascades, **deliberately**.
Making those ids nullable breaks one-release schema compat outright: release
N-1's `ListWatchedWordMatches` projects `COALESCE(m.video_id, c.video_id)::uuid`
and `COALESCE(cu.username, vu.username)::text` as NOT-NULL columns —
`ListWatchedWordMatchesRow.VideoID` is a `uuid.UUID` and `.AuthorUsername` a
`string` — so the first deleted target would make N-1's whole queue endpoint fail
to scan, which is precisely what the rollback policy behind `migrate-lint`
exists to prevent. So `target_status` has **two** values, `present` and
`edited_away`; `deleted` is not representable, because the row leaves with its
target. The lab confirms it (deleting the flagged comment took its 2 matches to
0) and the store test asserts it, so the cascade is a pinned behaviour rather
than an assumption.

**Triage, shaped like the report queue rather than invented.**
`POST /admin/watched-word-matches/{id}/resolve` with
`{"status":"resolved"|"dismissed","note":…}` — **one verb carrying the outcome**,
exactly `POST /admin/reports/{id}/resolve`'s shape, and **idempotent the same
way: a repeat is 204, not 409**, because the UPDATE overwrites and still reports
one row affected, so a retry is never an error. Measured once each: moderator
resolve **204**, immediate re-triage **204** (and the second note is what reads
back), unknown id **404**, bogus outcome **422**, ordinary user **403**,
anonymous **401**, and `?status=bogus` on the list **400** rather than a silent
collapse to "all". The queue lists **open by default**, server-side, with
`?status=open|resolved|dismissed|all`; the count carries the same filter as the
page, asserted together on every read, because a total counting rows the list
filters out promises a page it cannot serve. **The note lives on the domain
row**: `audit.normalizeEvent` validates metadata against a closed key allowlist
with a 256-byte cap and would delete the audit row rather than enrich it — the
`0130` lesson — so the ledger carries `outcome` and `reason_provided` only. Three
`moderation.watched_word_match.resolve` rows were written (two success, one
failure for the unknown id) and a sweep of `audit_log` for the moderator's actual
words returns **zero**.

**In real Chromium, on the production build behind one origin.** Signed in as
dana the moderator, `/moderation/watched-word-matches` reads **"2 flagged items"**
under Open / Resolved / Dismissed / All chips with **Open** selected. The video
row is badged `pineapple · Video · Term removed · by mona · my mixtape`, quotes
the snapshot with **pineapple** highlighted, and says *"The live video no longer
contains this term — it was edited after the flag. Open the video to see it as it
reads now."* Typing a note into the anchovy row and pressing **Resolve** took the
queue to "1 flagged item" and the row reappeared under **Resolved** reading
*"Note: hid the comment"* and *"Resolved by dana"* — core logged the POST as
**204**. The Dismissed tab is the screenshot worth keeping: `pineapple · Comment
· Dismissed · Term removed · by cleo`, quoting **"I want pineapple on it"** while
the live comment reads *"never mind, anchovy instead"*, and it survives a **hard
reload** unchanged, because the server hid nothing and the snapshot is a column.
An anonymous visitor gets the shared **"Moderators only"** gate and nothing
fetches.

**The live rail, closed at the layer that can hold it.**
`ListLivePublicStreams` and `CountLivePublicStreams` now take an optional
`viewer_id` and carry the same two `NOT EXISTS` clauses `ListPublicVideosSorted`
and `ListPublicVideosByChannel` do; the handler was already `optionalAuth`, so an
anonymous caller passes a NULL viewer and nothing changes for them. **A live
stream cannot be created without the RTMP publish path**, so the real-PostgreSQL
test inserts the row at the state ingest would leave it in (`state='live'`,
`privacy='public'`, `started_at` set) — stated rather than implied; every surface
under test is a list predicate over `live_streams` + `channels` + the mute tables
and never touches media. Each relationship is applied and then **lifted**, with an
anonymous control read at the same instant and the count asserted with the rows,
and being blocked **by** the streamer is asserted *not* to hide them, which pins
the clause's shape rather than its presence. The HTTP test drives the real ingest
hook and the real mute/block routes: ada's rail **1 → 0** with a mute, **0** with
a block, **1** again after each is lifted, while the anonymous rail and bob's own
rail stay at 1 throughout.

**Failed first, in five places.** With `matched_text` reverted to the live
`COALESCE(c.body, v.title || E'\n' || v.description)` join and sqlc regenerated,
both real-PostgreSQL snapshot tests fail on exactly the defect — *"the original
snapshot moved to \"never mind, anchovy…\"; it must stay \"I want pineapple…\""*.
With the `watched_word_id` FK put back to `ON DELETE CASCADE` on the live
database, the word-survival assertion fails. With the live rail's two `NOT
EXISTS` clauses removed, the real-PostgreSQL test fails on both relationships
**and** on the count. With the fake's mirror removed, the httpapi test fails on
both — and it did, on the first run, because `liveFakeRepo` had not yet been
wired to the shared mute and block fakes; the test caught it, which is the
fake-fidelity lesson four A16 slices paid for. And with the frontend's snapshot
rendering reverted to the live body, **6 of the 14 new component tests fail**
while the pure `splitSnapshot` cases and the backfilled / term-removed cases keep
passing. `watchwordFakeRepo` was rewritten to **store** the 0132 columns and
**project** at read time, because a fake that echoed the snapshot back as the
live body could not tell a snapshot from a live join.

**Gates.** vidra-core `make ci` **passed**, exit 0 (fmt-check, vet, migrate-lint
— 132 up migrations clean, openapi-verify, sqlc-verify, test-race; **79 packages
ok, 0 failures**); `go vet -tags=integration ./...` clean; `go test
-tags=integration ./internal/store/... ./internal/federation/...` **passed**
against native PostgreSQL 16 at schema 132 on a scratch database. **19 named
A12/A16 test functions pass** beside the new ones, including
`TestWatchedWordMatchesFlow`, `TestWatchedWordVideoMatchesFlow`,
`TestListLivePublicStreams`, `TestListLivePublicStreamsUngatedRead`,
`TestCommentNotificationRespectsMutesAndBlocks` and `TestReportVideoAndModerate`.
The `.down.sql` was applied **by hand** — the api binary ships only
`migrate up`/`version`/`force` — and left the table back at its 0030/0049 shape,
five columns with all three FKs at CASCADE. vidra-user: `npx tsc --noEmit` clean,
`npm run lint` 0 errors (2 warnings, both pre-existing on main), `npm run
lint:icons` pass, production `next build` pass, `npm run test` **2,406 passed /
82 failed — and the same 82 fail on clean `origin/main` in this environment**
(baseline measured by stashing: 82 failed / 2,390 passed), seven files dying
under local Node 25.9.0 rather than the repo's Node 24; repo CI is the authority
for those. The 17 new frontend tests live in one new file (15) and two added
cases in `lib/api/endpoints.test.ts`; the only existing spec touched is the
mocked e2e one above, whose fixture had to move with the contract and whose
assertions were added to, never weakened. No new viewer-scoped client read was added, so
`lib/use-settled-session.ts` needed no new caller. The meta compose render was
not re-run: no compose, script or env file changed. Repo CI: **core #178 is 7/7 green**, including `integration` and
`prev-release-against-new-schema` — which is the compat argument above, checked
by the job that exists to check it — and meta #124 is 4/4 green.
**Unverified locally:** the frontend
e2e and e2e-backed suites, which vidra-user's AGENTS.md forbids running locally
(repo CI is the authority, and it found the spec above);
`GET /live` in a browser, since the lab stood up no RTMP ingest; the backfilled
marker in Chromium, since the walkthrough database was created fresh at schema
132 and held no backfilled row (the backfill itself was measured in SQL, its
rendering by component test); an ordinary user's browser view of the queue, where
only the anonymous gate was exercised in Chromium and cleo's 403 measured at the
API; and anything remote or federated, which **A29** owns.

**What repo CI caught that this lab could not.** vidra-user's AGENTS.md forbids
running the e2e suites locally, so the first run of `frontend` on user #175 found
a real breakage: `e2e/watched-word-matches.spec.ts` **mocks** the matches
endpoint, which makes its fixture the contract, and that fixture predated the
snapshot and triage fields — so the spec asserted a body the view no longer reads
from. The fixture now carries the new fields, **every existing assertion is
kept**, and two cases were added rather than removed: the queue quotes the
flag-time snapshot and *not* a body edited since, and **Resolve** POSTs
`{status, note}` to the right path and the row leaves the open queue. The same
run also exposed a failure mode worth closing on its own terms: `matched_text` is
contract-required, but a frontend running ahead of a pre-0132 core would hand
`splitSnapshot` an `undefined` and `Array.from` would throw, taking the **whole
queue** down through the error boundary rather than blanking one row's quote. It
now returns empty spans for a non-string snapshot, with a test. `e2e-backed`'s
own failure is the ordering one and needs no change: it reads a real core, whose
`main` has no `matched_text` yet. One more bug was caught by reading the new case
back rather than by a runner: the spec's `MATCHES` route pattern is anchored at
`?` or end-of-string, so it never matched `…/{id}/resolve` — the POST would have
escaped to a backend that is not running under `npm run ci`, and the case would
have failed as *"the row is still there"* rather than *"the request never
happened"*. It has its own pattern now, and the list fixture keeps serving the
row so the assertion proves the **view** drops it on the 204. And the two new
cases then failed on their first assertion for a reason worth keeping: in a
mocked spec `page.goto` is a **full load**, which restarts session restore, and
that needs `POST /auth/refresh` against a backend `npm run ci` does not run — so
the session comes back **anonymous**, `RoleGate` renders "Moderators only" and
nothing fetches. The file's own anonymous-gate case depends on exactly that
behaviour, which is what identifies it; both new cases now click through
**Moderation → Word matches**, as the pre-existing case always did. One last
collision, of a kind only a runner shows: `getByRole` matches the accessible
name as a **substring**, and the new status filter puts a **"Resolved"** chip on
the same page as the row's **"Resolve"** button, so the click resolved to two
elements. Adding a filter to a page is what created it.

**One lab artefact worth keeping.** The browser's network panel reported **503**
for the resolve POST while core logged **204** and the client took the success
path — the row left the Open queue and its note read back on the next GET. That
is the throwaway one-origin proxy mishandling a body-less 204, not the product,
and it is recorded rather than quietly dropped.

**Findings recorded, not fixed.** (1) Deleting a flagged **comment or video**
still destroys its match history, for the compat reason above; the word half is
closed. (2) The flagger does not snapshot the target's **author**, so the author
is only resolvable while the target row exists — moot today, and the first thing
that would have to be added if the cascade is ever closed. (3) `match_offset` is
`-1` on every backfilled row, so those are highlighted by a case-insensitive
fallback search; where the term has since been edited away the fallback finds
nothing and the row renders unhighlighted, which is the safe direction. (4)
There is still **no bulk triage** — no endpoint takes an array, the UI has no
selection state. (5) A triaged match **cannot be reopened**: the verb moves
open → resolved/dismissed and between the two terminal states, and nothing sets
it back. (6) The queue still carries no prior-action history per author, the gap
slice 2 recorded for reports and slice 3 for this queue.

**For A17.** `moderation.watched_word_match.resolve` is a **new audit action**
with `resource_type: watched_word_match`, and its failure variant is emitted too
— any audit or health dashboard enumerating actions needs both. `audit_log` still
cannot carry prose, so no dashboard should try to surface a moderator's words out
of the ledger; they live on the domain row, as `0130` established. No new
setting, gate or registry row: the triage verbs are unconditional staff routes.
The deployed schema moves **131 → 132**; `0132` is additive plus one FK
relaxation, its backfill runs inside the migration, and deploy ordering is
unchanged.

**Delivery order: core #178 first, then user #175, then this evidence PR.** The
frontend's client is regenerated from core's spec, so `contract-ci` on the user
PR is **expected RED until core merges** — `lib/api/generated.ts` is never
hand-edited. Nothing is merged here and no deployment is authorized. The lab was
torn down — postgres, redis, vidra-core, the Next server and the proxy all
stopped, the data directory and the frontend build output removed — and no lab
artefact is committed.
