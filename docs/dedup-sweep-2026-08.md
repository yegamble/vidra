# Copy-paste dedup sweep — 2026-08-28

Three research passes (one per repo, plus a core↔search cross-repo diff) fed eight merged PRs
that consolidated the worst copy-paste clusters into shared helpers/components. Everything
below is on `main` in its repo.

## Merged

### vidra-search
- **#25 — fix: sync the three diverged vidra-core twins.** `/readyz` gained core's drain flag,
  503-only-when-postgres-down, and a 2s probe cache (the old copy 503'd every replica on a
  Redis blip and dropped in-flight requests on rolling restarts). Malformed `bool`/`duration`
  env values are now fatal at boot instead of silently falling back to defaults
  (`SEARCH_WORKERS_ENABLED=flase` used to boot with workers on). `codeForStatus` learned
  `409 → conflict` and `501 → not_implemented`.
- **#26 — refactor: one home per duplicated helper + auth golden vectors.** `internal/paging`
  replaced four divergent limit-clamps (`?limit=-5` used to mean three different things across
  one API); byte-identical helpers (`ageDays`, `subjectOf`, `parseUUIDs`, `optStr`, `derefStr`)
  consolidated; `pathUUID`/`queryUUID` collapsed five copies of param boilerplate.

### vidra-core
- **#107 — refactor: httpapi helpers.** `mustPrincipal` (175 sites), `pathUUID` (114 sites,
  preserving the deliberate 404-for-malformed-id rule and six intentional exceptions),
  `isStaff` + `admin.Role*` constants replacing ~63 bare role literals, `internal/pgconv`
  (unique-violation/sqlstate/uuid/time/deref/trim helpers from ~15 packages), and one shared
  image-extension allowlist replacing three copies of a security list.
- **#108 — refactor: retry/security helpers + four correctness fixes.** `internal/retry.Backoff`
  (9 loops, equivalence pinned by table tests), `internal/safeerr`, config-driven rate-limit
  middleware (fail-open + `Retry-After` clamp preserved), generic state-cookie seal/open for
  OAuth/ATProto. Fixes: two byte-truncations that could split UTF-8 runes; thumbnail ffmpeg
  calls now capture stderr like every sibling exec site.
- **#109 — refactor: `internal/jobloop`.** 22 of 24 hand-rolled worker ticker loops in
  `cmd/api/main.go` (~975 lines) ported onto one tested loop runner; all worker log strings
  byte-identical. `ipfsMirror` and `mediaGC` stay hand-rolled deliberately — comments in-tree
  explain the select/gating semantics that the shared shape would change.

### vidra-user
- **#82 — refactor: ui primitives.** `ui/Alert` (26 inline alert copies), `FederatedOriginBadge`
  (5 hand-inlined globe SVGs), `lib/api/pagination` (`FULL_LIST_LIMIT`, `PageParams`,
  `pageQuery`), merged role-gated nav links, `ui/PillTabs`.
- **#83 — refactor: list loading.** `lib/use-api-resource` (the Status/AbortController/reloadKey
  loader that was written out dozens of times), `ManagedList` + `UndoActionRow` for the
  clone list views, `SignInGate` (~20 drifted sign-in gates; one real fix: SecuritySettingsView
  no longer fires its 2FA fetch mid-session-restore), `lib/use-visible-poll`.
- **#84 — refactor: presentation dedup.** `lib/use-video-card-presentation` +
  `RestrictedModePlaceholder` (the sensitive-content/restricted-mode card policy, 6 copies),
  `lib/use-async-action` (finally-centralized busy reset; adopted only where behavior-equivalent),
  `lib/server-json` (7 SSR fetch helpers, knobs preserved bit-for-bit), `PageHeader` across
  32 routes (admin h1s normalized onto the `text-title` token), `lib/rail.ts` for the 4
  horizontal snap rails.

## The systemic finding

Fixes land in vidra-core and the hand-copies in vidra-search fossilize (`/readyz`, the env-parse
rule, `codeForStatus` all diverged this way). Two mitigations are now in-tree:

1. `// TWIN:` comments on both sides of every deliberate core↔search copy
   (version, logger, correlation, metrics, errors, health).
2. **Golden HMAC vectors** for the v1 internal-auth protocol:
   `vidra-search/internal/api/testdata/internal_auth_vectors.json` and
   `vidra-core/internal/searchclient/testdata/internal_auth_vectors.json` are byte-identical
   (SHA256 `9495846f…f487`) and asserted by tests in both repos, including decoded-path
   (space/CJK) cases. Any protocol change must update both files identically.

A shared `vidra-shared` Go module was considered and rejected for now — the genuinely shared
surface is ~150 lines and nothing in it had diverged; revisit if the internal-auth protocol grows.

## Deferred backlog (ranked)

1. **vidra-core test-fake consolidation** (`internal/store/storefake`): ~1,094 duplicated fake
   methods / 12.4k LOC across packages. Biggest remaining item; test-only; a half-done
   migration would just mint a third copy, so it needs one dedicated pass.
2. **SSR fetch timeouts (vidra-user)**: `feed.server`, `instance-config.server`,
   `instance-homepage.server`, `video.server` have no timeout and can hang a render
   indefinitely if core accepts and stalls; `feed.server` runs on every home render.
   Deliberately not changed during the refactor (behavior change).
3. **`runFFmpegToFile` (vidra-core)**: the temp-file/exec/stderr-tail preamble is 3 real copies,
   but storyboard's exec path has zero test coverage — add coverage first.
4. **`AdminUsersView.test.tsx` (vidra-user)** is flaky on clean `main` (6/13 failures unloaded,
   not purely load-related) and deserves a real diagnosis.
5. **vidra-search test gaps**: the error-envelope and telemetry packages had no tests at all
   before this sweep; coverage there is still thin.
