# Automatic category and language (TypeSafe Jev), slice 1: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task by task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fill the empty `category` and `language` of public, published videos with TypeSafe Jev judgments. The feature is operator-enabled, off by default, never overwrites a human value, and marks each fill in Studio.

**Architecture:** vidra-core gets a small Jev HTTP client (`internal/judgment`) that also owns the TypeSafe account state (the sealed key and the account-wide pause). It also gets a leader-gated state-scan worker (`internal/metadatafill`) on `jobloop`. The worker claims eligible videos by inserting into `video_metadata_judgments` and asks Jev one request with two `choice` questions. A single SQL statement then records the raw answer and writes confident picks into still-empty fields. After that, a narrow `video.Service` hook tells search, and only search. vidra-user adds a toggle, an infrastructure row, a status card and a Studio marker. The meta repo documents the env keys and the runbook, and records the beta measurement that sets the confidence bars.

**Tech Stack:** Go, Echo v4, sqlc v1.31.1 (`emit_pointers_for_null_types: true`), Postgres, golang-migrate (vidra-core). Next.js 16, Vitest, Playwright (vidra-user). Bash/Compose/Markdown (meta).

**Spec:** [`docs/superpowers/specs/2026-09-20-jev-metadata-autofill-design.md`](../specs/2026-09-20-jev-metadata-autofill-design.md) (meta PR #231).

**Revision 3.1:** The final check found three more problems, now fixed:
- `SetCategoryProvider(nil)` panicked under the atomic provider; nil now restores the built-ins.
- The shared scratch database now uses `TestMain`, not `sync.Once`.
- Videos with nothing to ask no longer count as "not confident".

**Revision 3 (2026-09-26):** Both reviewers re-verified revision 2. Every earlier finding was fixed, and they raised 3 new MAJOR and 11 MINOR items, folded in here:
- One failing video can no longer stall the worker.
- A video with nothing to ask is recorded once.
- Category validation uses the same list the question used.
- The provider global is race-free.
- Dangling category ids are listed as a proposal.

The Self-review lists every item.

**Revision 2 (2026-09-26):** Two fresh reviews against the code (vidra-core engineer and cross-repo architect) found 3 blockers and 17 major problems in revision 1. All of them are fixed below. The design changes are:
- The worker is leader-gated.
- Recording a judgment and applying it happen in one statement.
- A search-only hook replaces the full `onUpdate` fan-out.
- Outages pause the worker instead of spending attempts.
- PeerTube re-sync keeps a value its source is silent about.
- The key and pause live in an account-level `typesafe_state` table.
- The status card sits on the VOD config page.
- Every core contract change is followed by a vidra-user codegen PR.

---

## 0. Read this first

### 0.1 What the code check changed

The spec was written against core v0.7.5. The code was re-read at core `400c1a8`, user `8efd7c7`, search `fb39a7b` and meta `79a84cd`, together with the live TypeSafe docs and a live API call on 2026-09-26: HTTP 200 in 0.32 s, answered by `jev-1.13.0`, and 401 for a bad key.

| Spec text | Code / vendor fact | Plan does |
|---|---|---|
| §4.1: breaker "with `searchclient`'s numbers" | The breaker is private (`internal/searchclient/breaker.go`) | Task 1 moves it to `internal/breaker`, so there is one implementation. |
| §4.1: codes `auth`, `rate_limited`, `unavailable`, `bad_response` | The API also returns 422 (invalid request) and 529 (overloaded). A wrong endpoint path returns 404. | 422/400 map to `invalid_request`; 529, 5xx, 404/405, transport errors and an open breaker map to `unavailable`. `not_configured` means no key. |
| §4.1: errors "laundered through `safeerr`" | `judgment.Error` carries only a closed code | No `safeerr`; the HTTP layer maps codes to typed errors. |
| §2.6 / §9: "reusing the write-only secret mechanism the admin mail-settings work is building" | That work merged (core #266) as a **mail-only** store, `internal/mailconfig`, on `internal/secretbox` and the MFA KEK. Three more Jev slices will share one TypeSafe key. | The sealed key and the account pause live in a new `typesafe_state` table owned by `internal/judgment`. It reuses `secretbox`, the same cipher instance, and mail's "sealed or refused" rule. Proposal §0.2.8. |
| §10: compose consumers in meta (spec §12 PR 5, "M") | The api env block is the `x-api-env` anchor in `vidra-core/docker-compose.yml`, which meta `include:`s | The compose lines ship in core (Task 3). Meta gets the env example and the runbook. |
| §5: "custom categories are sent as label only" beside the built-ins | A non-empty `instance_custom_categories` **replaces** the built-ins and may reuse their ids (`internal/instancesettings/service.go:1626-1646`) | Descriptions attach only when id *and* label match a built-in. |
| §5 / §9: the live category list | `video.SetCategoryProvider` is called only in `httpapi.WithSettingsService` (`server.go:943`). A `VIDRA_ROLE=worker` process returns before `httpapi.New` (`cmd/api/main.go:2925-2931`), so its `video.CategoryOptions()` is the 18 built-ins. | Task 9 registers the provider right after `settingssvc.Load` in every role. Otherwise a worker process would write built-in ids on an instance with a custom list. |
| §4 diagram / §4.5: "existing onUpdate hooks: federation Update, search upsert, …" / "the seam federation uses to send an Update to remote followers" | The federated video object carries neither category nor language. The federation hook fans out one delivery per follower inbox (`internal/federation/outbox.go:56-78,134`). | `ApplyInferredMetadata` is replaced by a single statement plus a **narrow** `WithInferredMetadataHook`, registered only for the search upsert. A 50,000-video backfill would otherwise enqueue 50,000 × followers deliveries that carry nothing new. Proposal §0.2.9. |
| §4.2: eligibility "mirrors the search index" | The predicate is `search_outbox.sql:116-118`: public, published, `NOT au.unlisted`, no `video_blocks` row. `EnqueueVideoUpsert` carries no block flag (`searchevents/enqueuer.go:96-106`). | The claim **and** the final write both carry the full predicate. |
| §4.2: "two replicas can never judge the same video" by insert-as-claim, run on every replica | Several global decisions (`enabled_since`, "run done") would be made from one replica's view. Settings reach replicas within one 10 s poll. | The loop is **leader-gated** (`jobloop.Loop{Leader: …}`). The insert-claim and lease remain for crash recovery. "Run done" is decided by a query, never by an empty claim. Proposal §0.2.5. |
| §4.4: `updated_at >= enabled_since` | PeerTube re-sync writes the source's category and language unconditionally and bumps `updated_at` (`peertubeimport/resync.go:546-575`, `peertube_import.sql:717-729`) | Task 6 applies re-sync's existing "a source that says nothing is not saying clear it" rule to category and language. Otherwise every re-run erases fills that can then never be re-judged. Proposal §0.2.7. |
| §4.3: "0150 is the newest" | Newest is `0151_mail_config` | The plan writes `0152`; take the next free number when the PR is opened. |
| §4.3: `lease_expires_at` | Queue leases here use `next_attempt_at`; `lease_expires_at` exists only on `job_runs` | The spec's column is kept (clearer here). `internal/jobrecovery` is not extended: the worker's own claim reclaims expired leases. |
| §12: nine PRs | Both component repos cap a PR at < 300 changed lines. vidra-user's required `contract-ci` regenerates types from core `main` and fails on any drift (`.github/workflows/contract-ci.yml:52-75`). | 22 PRs (§0.3). Every core PR that changes `api/openapi.yaml` is followed at once by a codegen-only vidra-user PR (Task 12). |

### 0.2 Proposals the owner should confirm

These are the smallest reasonable choices, not owner rulings. The only owner decisions are spec §2. Each proposal can be reversed within one task.

1. **An automatic fill does not bump `videos.updated_at`.** Search is told through the hook. A backfill must not re-sort `updated_at`-ordered listings or look like creator activity. Task 5 records a grep of `ORDER BY .*updated_at` in its PR.
2. **Saving the Studio edit form confirms the shown values.** The form resends category and language on every save (`components/studio/shared.tsx:148-158`), so a save clears the note even when only the title changed. Changing that would mean sending only dirty fields, a vidra-user behaviour change outside this slice.
3. **The marker requires `applied = current value`,** so it also disappears when anything outside `video.Service` changes the field.
4. **The status card lives on Config → VOD, in the `autofill` section,** through `AdminInstanceConfigView`'s existing `sectionPanel` seam (`:606-640`), beside the toggle. The Infrastructure row deep-links there.
5. **The worker is leader-gated.** Throughput stays bounded by the vendor (1,200 requests a minute) and the 25-per-tick batch, so one leader loses nothing that matters.
6. **Pauses.** `auth` pauses the account for 15 minutes. `rate_limited` and `unavailable` pause it for 2 minutes. Claims are released without spending an attempt. Only `bad_response` and `invalid_request` spend attempts, up to 5, and then mark the video `failed`. A successful **Test connection** clears the pause.
7. **PeerTube re-sync keeps the current category or language when the source has none.** This is the rule re-sync already applies to duration and `originally_published_at`. A source that clears its own category will no longer clear ours.
8. **The TypeSafe key and pause live in `typesafe_state`,** not in the mail store (see §0.1).
9. **Auto-fills do not send federation Updates** (see §0.1).
10. **A dangling category id counts as set.** A PeerTube import can keep a category id that the instance's custom list no longer has (`internal/peertubeimport/importer_integration_test.go:221-226`), so Studio and browse show it as empty. This plan does **not** treat such a video as empty, because overwriting a value that came from a human at the source edges into spec §2 decision 2. Instead:
    - the evaluator (Task 13) reports how many sampled videos carry a dangling id;
    - the runbook lists the case under Known limits.

    The alternative is to pass the live ids as a `text[]` and treat `NOT (v.category = ANY(@live))` as empty in the claim, the guard and the count, which is about 10 lines in Task 4. It is the owner's call.

### 0.3 PR map

Each PR is merged before the next one starts. Each happens in its own worktree (`superpowers-extended-cc:using-git-worktrees`), and `git branch --show-current` runs before every commit and push. If a PR goes over 300 changed lines, split it along the task's own steps and never across tasks.

| PR | Repo | Task | Depends on |
|---|---|---|---|
| C1 | core | 1: extract `internal/breaker` | none |
| C2 | core | 2: `internal/judgment` client | C1 |
| C3 | core | 3: env config, compose consumers, `.env.example`, denylist | C2 |
| C4 | core | 4: migration 0152 and queries | C3 |
| C5 | core | 5: `video.Service` seams (narrow hook, best-effort clear, `AutoFilled`) | C4 |
| C6 | core | 6: PeerTube re-sync keeps a value the source is silent about | none (independent; land before beta is enabled) |
| C7 | core | 7: request builder and decision (pure) | C5 |
| C8 | core | 8: `judgment.Account` pause and `metadatafill.Service.Tick` | C7 |
| C9 | core | 9: toggle, infra row, category provider, wiring, metrics | C8 |
| C10 | core | 10: admin endpoints, runs, audit, **all** OpenAPI prose | C9 |
| S1 | user | 12: contract sync (codegen only) | C10, merged immediately |
| C11 | core | 11: `auto_filled` on the video view | S1 |
| S2 | user | 12: contract sync | C11, merged immediately |
| C12 | core | 13: `evaluate-metadata` subcommand | C9 |
| C13 | core | 14: `jev-stub` compose profile | C9 |
| U1 | user | 16: toggle, warning, infra labels, API wrappers | S2 |
| U2 | user | 17: `MetadataFillCard` on Config → VOD | U1 |
| U3 | user | 18: Studio marker and mocked e2e | U1 |
| U4 | user | 19: backed e2e and optional-workflow job (**touches `.github/workflows`: that is this PR's task**) | U3, C13 |
| C14 | core | 15: sealed key setting | C10 |
| S3 | user | 12: contract sync | C14, merged immediately |
| U5 | user | 20: key field on the card | U2, S3 |
| M1 | meta | 21: env example and runbook | the first core and user **releases** that contain C9–C13 and U1–U2 |
| M2 | meta | 22: beta evaluation, bars, scope-ledger note | that release deployed to beta |

**Contract rule:** C10, C11 and C14 are the only core PRs that change `api/openapi.yaml`. Task 9 deliberately leaves OpenAPI alone and Task 10 carries its prose. After each of those three merges, S1, S2 or S3 respectively lands before any other vidra-user PR. Otherwise vidra-user's required `contract-ci` fails on every PR and every push.

**What runs even with the toggle off**, because "off by default" is not "no effect":
- C5: a human edit that sets category or language runs one best-effort `UPDATE` on `video_metadata_judgments`.
- C6: the PeerTube re-sync rule change (§0.2.7) applies on every re-run.
- C11: a signed-in viewer who neither owns the video nor is staff costs one channel-membership query per video-detail read (`canManageChannelContent`), for the `auto_filled` check.
- C9: the category provider is registered at boot in every role. The elected leader reads `metadata_fill_state` every 30 s and runs an `UPDATE` that matches no rows.

Everything else is gated by the toggle and a key. Nothing is released by this plan: cutting a release is the owner's step (`! ./deploy/release.sh --yes vX.Y.Z`).

### 0.4 Verification gates (from each repo's AGENTS.md; paste the tail into every PR)

- **core:** `make ci` (fmt-check, vet, migrate-lint, openapi-verify, sqlc-verify, test-race) and `go vet -tags=integration ./...`. Tasks 4, 6, 8 and 9 also run integration tests against live Postgres:
  ```
  docker compose --profile core up -d postgres redis
  make migrate-up
  DATABASE_URL=postgres://vidra:vidra@localhost:5432/vidra?sslmode=disable \
  REDIS_URL=redis://localhost:6379/0 go test -tags=integration ./internal/store/... ./internal/metadatafill/... ./internal/peertubeimport/...
  ```
  New integration tests that claim or write videos **must use a scratch database**, one per package test binary: create and migrate it once in a **`TestMain`**, which calls `m.Run()` and then drops the database explicitly. It must pass straight through, with `os.Exit(m.Run())`, when `DATABASE_URL` is unset. Do **not** wrap `newScratchDB` in a `sync.Once`, because it drops the database in its first caller's `t.Cleanup` and every later test would fail. Neither `internal/store` nor `internal/metadatafill` has a `TestMain` today. Each fixture deletes its own rows in `t.Cleanup`, and these tests do not call `t.Parallel`. Migrating per test would cost 150+ migrations each in the required lane (the pattern at `internal/peertubeimport/importer_integration_test.go:2205` `newScratchDB`). CI runs integration packages in parallel on one database (`Makefile:58`), so a claim over the shared database would take other packages' fixtures. If docker is unavailable, say so in the PR.
- **user:** `npx tsc --noEmit && npm run lint && npm run lint:icons && npm run test`. Do not run the e2e suites locally; CI runs them. Name anything you did not run.
- **meta:** `bash -n`/`shellcheck` on touched scripts, the compose `config -q` gate, and `python3 -m unittest discover -s tests -p '*_test.py'`.

PR titles follow `[claude] <area>: <summary>`. The body opens with a one-line WHY.

### 0.5 Generated sqlc types (determined by `sqlc.yaml`; do not guess)

- A nullable `text` column or `sqlc.narg` gives `*string`.
- A nullable `real` gives `*float32`.
- A non-null `timestamptz` (e.g. `next_attempt_at`) gives `time.Time`.
- A nullable `timestamptz` gives `pgtype.Timestamptz`.
- `uuid` gives `uuid.UUID`, and a nullable one gives `pgtype.UUID`.
- `::bool`/`::bigint`/`::int` casts in `SELECT` give `bool`/`int64`/`int32`.

The code below uses these types. After `make sqlc`, read the generated structs once and fix any field *name* that differs.

---

## File structure

**vidra-core**

| File | Responsibility |
|---|---|
| `internal/breaker/breaker.go` (new) | Consecutive-failure breaker, moved unchanged |
| `internal/searchclient/{client.go,*_test.go}` | Use `*breaker.Breaker` |
| `internal/judgment/judgment.go` (new) | `Client.Ask` over `POST /v1/systemone`, closed codes |
| `internal/judgment/account.go` (new) | TypeSafe account state: pause (Task 8), sealed key (Task 15) |
| `internal/config/config.go`, `docker-compose.yml`, `.env.example` | Four env keys |
| `internal/observability/audit.go` | Denylist entries, audit actions |
| `migrations/0152_metadata_autofill.{up,down}.sql` (new) | Four tables, a partial index, the run projection |
| `internal/store/queries/metadata_fill.sql` (new) | Every query below |
| `internal/video/inferred.go` (new) | `WithInferredMetadataHook`, `NotifyInferredMetadata`, `AutoFilled` |
| `internal/video/service.go` | Repository additions; best-effort clear in `UpdateForActor` |
| `internal/peertubeimport/resync.go` | Keep category/language when the source is silent |
| `internal/metadatafill/{request.go,service.go,evaluate.go}` (new) | Request/decision, the tick, admin operations, evaluation |
| `internal/instancesettings/service.go` | `KeyMetadataAutofillEnabled` |
| `internal/httpapi/{admin_infra.go,admin_metadata_fill.go,errors.go,ratelimit.go,server.go,videos.go}` | Infra row, endpoints, typed error, limiter, `auto_filled` |
| `cmd/api/{main.go,evaluate_metadata.go}` | Wiring, the subcommand |
| `api/openapi.yaml` | Routes, schemas, `auto_filled`, key lists |
| `scripts/dev/jevstub.py` (new) | Deterministic stand-in for backed e2e |

**vidra-user**

| File | Responsibility |
|---|---|
| `lib/api/generated.ts` | Regenerated only (Task 12) |
| `lib/api/types.ts`, `lib/api/endpoints.ts` | Aliases, wrappers |
| `lib/admin-config-ia.ts` | VOD `autofill` section and META entry with `warn` |
| `components/AdminInstanceConfigView.tsx` | `sectionPanel("vod","autofill")` hosts the card |
| `components/AdminInfrastructureView.tsx` | Label and deep link |
| `components/admin/MetadataFillCard.tsx` (new) | Status, counts, test, run, key field |
| `components/studio/{shared.tsx,VideoRow.tsx}` | The marker |
| `e2e/…`, `e2e-backed/metadata-autofill.spec.ts` | Mocked and backed coverage |

**meta**

| File | Responsibility |
|---|---|
| `env/production.env.example` | Four keys and the privacy statement |
| `docs/metadata-autofill.md` (new) | Operator runbook |
| `docs/metadata-autofill-evaluation-<date>.md` (new) | The measured bars |
| `docs/release-readiness.md` | Scope-ledger note |

**Deferred, deliberately not in this plan:** a served-by-vidra-search assertion for auto-filled values in meta's non-required `stack-e2e` lane. The U4 backed lane has no vidra-search, so its category-filter assertion exercises core's SQL fallback. Adding it means enabling `jev-stub` in `.github/workflows/stack-e2e.yml`, a workflow change that needs its own PR and owner approval. It is recorded here so the gap stays visible.

---
## Task 1: Extract the circuit breaker into `internal/breaker` (PR C1, core)

**Goal:** One exported breaker that both `searchclient` and the new `judgment` client use, with searchclient's behaviour unchanged.

**Files:**
- Create: `internal/breaker/breaker.go`, `internal/breaker/breaker_test.go`
- Delete: `internal/searchclient/breaker.go`
- Modify: `internal/searchclient/client.go` (field `breakers map[group]*breaker`, L89; construction L175-183; `doPaths` L213-266)
- Modify: `internal/searchclient/searchclient_test.go:185`, `internal/searchclient/prober_test.go:147` (renamed methods)

**Acceptance Criteria:**
- [ ] `breaker.New(now)` opens after `breaker.Threshold` (5) consecutive failures, refuses calls until `breaker.Cooldown` (30s) has passed, then admits exactly one probe.
- [ ] A failed probe restarts the cooldown; a successful one closes the breaker.
- [ ] `TestBreakerOpensAndRecovers` and `TestHealthyCombinesProberAndBreaker` pass unchanged apart from the renamed identifiers.
- [ ] No `breaker` type is left in `internal/searchclient`.

**Verify:** `go test ./internal/breaker/ ./internal/searchclient/ -race` shows `ok` for both.

**Steps:**

- [ ] **Step 1: Write the failing test** `internal/breaker/breaker_test.go`:

```go
package breaker

import (
	"testing"
	"time"
)

func TestBreakerOpensAfterThresholdAndAdmitsOneProbe(t *testing.T) {
	now := time.Unix(0, 0)
	b := New(func() time.Time { return now })
	for i := 0; i < Threshold; i++ {
		if !b.Allow() {
			t.Fatalf("call %d refused while closed", i)
		}
		b.Failure()
	}
	if b.Allow() {
		t.Fatal("breaker admitted a call while open")
	}
	if !b.IsOpen() {
		t.Fatal("IsOpen = false after threshold failures")
	}
	now = now.Add(Cooldown)
	if !b.Allow() {
		t.Fatal("no half-open probe after the cooldown")
	}
	if b.Allow() {
		t.Fatal("a second call was admitted while the probe is in flight")
	}
	b.Success()
	if !b.Allow() || b.IsOpen() {
		t.Fatal("a successful probe did not close the breaker")
	}
}

func TestBreakerFailedProbeRestartsCooldown(t *testing.T) {
	now := time.Unix(0, 0)
	b := New(func() time.Time { return now })
	for i := 0; i < Threshold; i++ {
		b.Failure()
	}
	now = now.Add(Cooldown)
	if !b.Allow() {
		t.Fatal("no probe after cooldown")
	}
	b.Failure()
	if b.Allow() {
		t.Fatal("a failed probe must re-open the breaker for a fresh cooldown")
	}
	now = now.Add(Cooldown - time.Second)
	if b.Allow() {
		t.Fatal("admitted before the restarted cooldown elapsed")
	}
	now = now.Add(time.Second)
	if !b.Allow() {
		t.Fatal("no probe after the restarted cooldown")
	}
}

func TestBreakerSuccessResetsTheCount(t *testing.T) {
	b := New(time.Now)
	for i := 0; i < Threshold-1; i++ {
		b.Failure()
	}
	b.Success()
	b.Failure()
	if !b.Allow() {
		t.Fatal("a success must reset consecutive failures")
	}
}
```

- [ ] **Step 2: Run it and watch it fail**

Run: `go test ./internal/breaker/`
Expected: FAIL. The build fails with `undefined: New`.

- [ ] **Step 3: Create `internal/breaker/breaker.go`** by moving `internal/searchclient/breaker.go` and exporting the names. The logic is byte-identical:

```go
// Package breaker is the consecutive-failure circuit breaker shared by vidra's
// outbound HTTP clients (vidra-search, TypeSafe). It moved here from
// internal/searchclient unchanged so a second client could reuse it instead of
// growing a copy.
package breaker

import (
	"sync"
	"time"
)

const (
	// Threshold is the consecutive-failure count that opens the breaker.
	Threshold = 5
	// Cooldown is how long an open breaker waits before a half-open probe.
	Cooldown = 30 * time.Second
)

// Breaker opens after Threshold consecutive transport/5xx failures and, once
// open, refuses calls until Cooldown has elapsed, then admits a single
// half-open probe. A success (any 2xx or a service-level 4xx: the service is
// up, it just rejected the request) closes it and resets the failure count.
type Breaker struct {
	mu        sync.Mutex
	failures  int
	openedAt  time.Time
	halfOpen  bool
	now       func() time.Time
	threshold int
	cooldown  time.Duration
}

// New returns a closed breaker driven by now (inject a fake clock in tests).
func New(now func() time.Time) *Breaker {
	return &Breaker{now: now, threshold: Threshold, cooldown: Cooldown}
}

// Allow reports whether a call may proceed. When the breaker is open and the
// cooldown has elapsed it admits exactly one half-open probe (blocking further
// calls until that probe reports back via Success/Failure).
func (b *Breaker) Allow() bool {
	b.mu.Lock()
	defer b.mu.Unlock()
	if b.failures < b.threshold {
		return true
	}
	if b.halfOpen {
		return false
	}
	if b.now().Sub(b.openedAt) >= b.cooldown {
		b.halfOpen = true
		return true
	}
	return false
}

// Success closes the breaker.
func (b *Breaker) Success() {
	b.mu.Lock()
	b.failures = 0
	b.halfOpen = false
	b.mu.Unlock()
}

// Failure records a transport/5xx failure, opening the breaker at the
// threshold. A failed half-open probe re-opens the cooldown window.
func (b *Breaker) Failure() {
	b.mu.Lock()
	if b.halfOpen {
		b.halfOpen = false
		b.openedAt = b.now()
		b.mu.Unlock()
		return
	}
	b.failures++
	if b.failures == b.threshold {
		b.openedAt = b.now()
	}
	b.mu.Unlock()
}

// IsOpen reports whether the breaker is currently refusing calls (for metrics
// and tests). It does not admit a probe.
func (b *Breaker) IsOpen() bool {
	b.mu.Lock()
	defer b.mu.Unlock()
	if b.failures < b.threshold {
		return false
	}
	if b.halfOpen {
		return true
	}
	return b.now().Sub(b.openedAt) < b.cooldown
}
```

- [ ] **Step 4: Point searchclient at it.** Run `git rm internal/searchclient/breaker.go`. In `client.go`, import `github.com/vidra/vidra-core/internal/breaker`, change the field to `breakers map[group]*breaker.Breaker`, construct with `breaker.New(c.now)`, whatever the current `newBreaker` argument is, and rename the call sites `b.allow()`→`b.Allow()`, `b.failure()`→`b.Failure()`, `b.success()`→`b.Success()`, `isOpen()`→`IsOpen()`. In the two test files, rename `.failure()`→`.Failure()` and `breakerCooldown`→`breaker.Cooldown`. Known sites beyond `client.go`: `moderation_test.go:114` (`.isOpen()`), and `breakerThreshold` in `prober_test.go:157` and `searchclient_test.go:202`. Find every site with `grep -rn 'breakerCooldown\|breakerThreshold\|\.allow()\|\.failure()\|\.success()\|isOpen()\|newBreaker' internal/searchclient`.

- [ ] **Step 5: Run everything that touched it**

Run: `go test ./internal/breaker/ ./internal/searchclient/ -race && go vet ./...`
Expected: `ok` for both packages, and vet is clean.

- [ ] **Step 6: Commit**

```bash
git add internal/breaker internal/searchclient
git commit -m "refactor(breaker): move searchclient's circuit breaker into internal/breaker

A second outbound client (TypeSafe) needs the same breaker; sharing one
implementation instead of copying it. Behaviour is byte-identical.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 2: `internal/judgment`, the Jev client (PR C2, core)

**Goal:** A video-agnostic client that sends a JSON state and `choice` questions to `POST /v1/systemone` and returns validated picks and probabilities, or a closed error code.

**Files:**
- Create: `internal/judgment/judgment.go`, `internal/judgment/judgment_test.go`

**Wire format (docs.typesafe.ai/api, re-read 2026-09-26; verified live the same day with HTTP 200 in 0.32 s):**
- Request: `{"model":"jev-1.13.0","state":{...},"questions":{"<id>":{"type":"choice","instructions":"...","criteria":{"<option>":"<description>"|null}}}}`
- Response: `{"model":"jev-1.13.0","answers":{"<id>":{"type":"choice","choice":"<option>","probabilities":{"<option>":0.88,...},"confidence":0.85}},"usage":{"input_tokens":579,"output_tokens":112}}`
- Errors: 401, 422, 429 and 529 are documented. A `choice` allows at most 255 options.

**Acceptance Criteria:**
- [ ] 200 with valid answers returns a `Result` whose picks are in each question's option set.
- [ ] 401 or 403 gives `auth`. 429 gives `rate_limited`. 400 or 422 gives `invalid_request`. 5xx, 529, 404 or 405 (a wrong `TYPESAFE_ENDPOINT` path), a transport error or a timeout gives `unavailable`. A malformed body, a body over the cap, a missing answer, or a pick outside the options gives `bad_response`. An empty key gives `not_configured`, and no request is made.
- [ ] Five consecutive transport/5xx failures open the breaker; the next call fails `unavailable` without reaching the server.
- [ ] The key is sent only as `Authorization: Bearer <key>`. No error string contains the key or the upstream body.
- [ ] More than 255 options is rejected locally as `invalid_request`.

**Verify:** `go test ./internal/judgment/ -race -v` → every test `PASS`.

**Steps:**

- [ ] **Step 1: Write the failing tests** `internal/judgment/judgment_test.go`:

```go
package judgment

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/vidra/vidra-core/internal/breaker"
)

func q() map[string]Question {
	return map[string]Question{
		"language": {
			Instructions: "In which language is `video.title` written?",
			Options:      []Option{{Key: "en", Description: "English"}, {Key: "fr", Description: "French"}, {Key: "unclear"}},
		},
	}
}

func staticKey(k string) KeyFunc { return func(context.Context) string { return k } }

func newTestClient(t *testing.T, h http.HandlerFunc, key string) (*Client, *httptest.Server) {
	t.Helper()
	srv := httptest.NewServer(h)
	t.Cleanup(srv.Close)
	return New(srv.URL, "jev-1.13.0", staticKey(key), WithHTTPClient(srv.Client())), srv
}

func TestAskReturnsValidatedAnswers(t *testing.T) {
	var got map[string]any
	c, _ := newTestClient(t, func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/v1/systemone" || r.Method != http.MethodPost {
			t.Errorf("request = %s %s", r.Method, r.URL.Path)
		}
		if r.Header.Get("Authorization") != "Bearer k-123" {
			t.Errorf("auth header = %q", r.Header.Get("Authorization"))
		}
		_ = json.NewDecoder(r.Body).Decode(&got)
		_, _ = io.WriteString(w, `{"model":"jev-1.13.0","answers":{"language":{"type":"choice","choice":"en","probabilities":{"en":0.97,"fr":0.02,"unclear":0.01},"confidence":0.95}},"usage":{"input_tokens":120,"output_tokens":9}}`)
	}, "k-123")

	res, err := c.Ask(context.Background(), map[string]any{"video": map[string]any{"title": "Hello"}}, q())
	if err != nil {
		t.Fatalf("Ask: %v", err)
	}
	a := res.Answers["language"]
	if a.Pick != "en" || a.Probabilities["en"] != 0.97 || res.Model != "jev-1.13.0" || res.InputTokens != 120 {
		t.Fatalf("result = %+v", res)
	}
	if got["model"] != "jev-1.13.0" {
		t.Errorf("model sent = %v, want the pinned jev-1.13.0", got["model"])
	}
	crit := got["questions"].(map[string]any)["language"].(map[string]any)["criteria"].(map[string]any)
	if crit["en"] != "English" || crit["unclear"] != nil {
		t.Errorf("criteria = %v (an empty description must be sent as null)", crit)
	}
}

func TestAskClassifiesFailures(t *testing.T) {
	cases := []struct {
		name string
		h    http.HandlerFunc
		want Code
	}{
		{"401", status(401, `{"detail":"bad key k-123"}`), CodeAuth},
		{"403", status(403, `{}`), CodeAuth},
		{"429", status(429, `{}`), CodeRateLimited},
		{"422", status(422, `{"detail":"questions.language.criteria"}`), CodeInvalidRequest},
		{"500", status(500, `boom`), CodeUnavailable},
		{"404 wrong endpoint path", status(404, `{}`), CodeUnavailable},
		{"529", status(529, `{}`), CodeUnavailable},
		{"malformed", status(200, `{"answers":`), CodeBadResponse},
		{"missing answer", status(200, `{"model":"jev-1.13.0","answers":{}}`), CodeBadResponse},
		{"pick outside options", status(200, `{"model":"jev-1.13.0","answers":{"language":{"type":"choice","choice":"de","probabilities":{"de":1}}}}`), CodeBadResponse},
		{"oversized", func(w http.ResponseWriter, _ *http.Request) {
			_, _ = io.WriteString(w, `{"model":"`+strings.Repeat("x", maxResponseBytes)+`"}`)
		}, CodeBadResponse},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			c, _ := newTestClient(t, tc.h, "k-123")
			_, err := c.Ask(context.Background(), map[string]any{}, q())
			if CodeOf(err) != tc.want {
				t.Fatalf("code = %q, want %q (err=%v)", CodeOf(err), tc.want, err)
			}
			if strings.Contains(err.Error(), "k-123") || strings.Contains(err.Error(), "detail") {
				t.Fatalf("error leaks key or upstream text: %q", err.Error())
			}
		})
	}
}

func TestAskWithoutKeyMakesNoRequest(t *testing.T) {
	hit := false
	c, _ := newTestClient(t, func(http.ResponseWriter, *http.Request) { hit = true }, "")
	if _, err := c.Ask(context.Background(), map[string]any{}, q()); CodeOf(err) != CodeNotConfigured {
		t.Fatalf("code = %q, want not_configured", CodeOf(err))
	}
	if hit || c.Configured(context.Background()) {
		t.Fatal("an unconfigured client reached the server or reported configured")
	}
}

func TestAskTimesOut(t *testing.T) {
	c, _ := newTestClient(t, func(w http.ResponseWriter, r *http.Request) {
		<-r.Context().Done()
	}, "k")
	c.timeout = 50 * time.Millisecond
	if _, err := c.Ask(context.Background(), map[string]any{}, q()); CodeOf(err) != CodeUnavailable {
		t.Fatalf("code = %q, want unavailable", CodeOf(err))
	}
}

func TestBreakerOpensAfterConsecutiveFailures(t *testing.T) {
	hits := 0
	c, _ := newTestClient(t, func(w http.ResponseWriter, _ *http.Request) {
		hits++
		w.WriteHeader(http.StatusBadGateway)
	}, "k")
	for i := 0; i < breaker.Threshold; i++ {
		_, _ = c.Ask(context.Background(), map[string]any{}, q())
	}
	if _, err := c.Ask(context.Background(), map[string]any{}, q()); CodeOf(err) != CodeUnavailable {
		t.Fatalf("code = %q, want unavailable while open", CodeOf(err))
	}
	if hits != breaker.Threshold {
		t.Fatalf("server hits = %d, want %d (an open breaker must not call out)", hits, breaker.Threshold)
	}
}

func TestTooManyOptionsIsRejectedLocally(t *testing.T) {
	hit := false
	c, _ := newTestClient(t, func(http.ResponseWriter, *http.Request) { hit = true }, "k")
	opts := make([]Option, MaxOptions+1)
	for i := range opts {
		opts[i] = Option{Key: strings.Repeat("o", i+1)}
	}
	_, err := c.Ask(context.Background(), map[string]any{}, map[string]Question{"x": {Instructions: "?", Options: opts}})
	if CodeOf(err) != CodeInvalidRequest || hit {
		t.Fatalf("code = %q hit=%v, want invalid_request with no request", CodeOf(err), hit)
	}
}

func TestServerAnsweredOnlyFor5xx(t *testing.T) {
	c, _ := newTestClient(t, status(503, `{}`), "k")
	_, err := c.Ask(context.Background(), map[string]any{}, q())
	if !ServerAnswered(err) {
		t.Fatal("a 503 must be marked ServerAnswered")
	}
	c404, _ := newTestClient(t, status(404, `{}`), "k")
	_, err = c404.Ask(context.Background(), map[string]any{}, q())
	if ServerAnswered(err) || CodeOf(err) != CodeUnavailable {
		t.Fatalf("a wrong endpoint path is unavailable but not ServerAnswered: %v", err)
	}
}

func TestCodeOfForeignError(t *testing.T) {
	if CodeOf(errors.New("x")) != "" || CodeOf(nil) != "" {
		t.Fatal("CodeOf must be empty for nil and foreign errors")
	}
}

func status(code int, body string) http.HandlerFunc {
	return func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(code)
		_, _ = io.WriteString(w, body)
	}
}
```

- [ ] **Step 2: Run them and watch them fail**

Run: `go test ./internal/judgment/`
Expected: FAIL. The build fails with `undefined: Question`, `New`, and so on.

- [ ] **Step 3: Write `internal/judgment/judgment.go`**

```go
// Package judgment is vidra's client for TypeSafe's System One API (the Jev
// model). It knows nothing about videos: callers pass a JSON state and a set of
// closed-vocabulary questions and get back, per question, the pick and the
// per-option probabilities.
//
// Only the `choice` primitive exists today. `noul` and `score` arrive with the
// slices that need them.
//
// The endpoint is operator configuration (TYPESAFE_ENDPOINT), so it uses a
// plain http.Client like the Whisper client, not the SSRF-guarded one.
package judgment

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"strings"
	"time"

	"github.com/vidra/vidra-core/internal/breaker"
)

const (
	// DefaultEndpoint is TypeSafe's hosted API.
	DefaultEndpoint = "https://api.typesafe.ai"
	// DefaultModel is pinned, never the moving jev-latest alias: the confidence
	// bars are tuned against a version, and an alias can change the answers
	// behind them without anything on our side changing.
	DefaultModel = "jev-1.13.0"
	// MaxOptions is the vendor's per-choice cap.
	MaxOptions = 255

	defaultTimeout   = 5 * time.Second
	maxResponseBytes = 1 << 20
)

// Code is the closed error vocabulary. It is safe to store, audit and return
// to an admin: it never carries upstream text.
type Code string

const (
	CodeNotConfigured  Code = "not_configured"
	CodeAuth           Code = "auth"
	CodeRateLimited    Code = "rate_limited"
	CodeInvalidRequest Code = "invalid_request"
	CodeUnavailable    Code = "unavailable"
	CodeBadResponse    Code = "bad_response"
)

// Error is the only error type Ask returns.
// Error is the only error type Ask returns. ServerAnswered is true when the
// vendor itself answered 5xx/529 — as opposed to a transport failure, an open
// breaker or a wrong endpoint path — so a caller can tell "this input makes
// the server fail" from "the service is unreachable".
type Error struct {
	Code           Code
	ServerAnswered bool
}

func (e *Error) Error() string { return "judgment: " + string(e.Code) }

// CodeOf returns err's code, or "" for nil and foreign errors.
func CodeOf(err error) Code {
	var je *Error
	if errors.As(err, &je) {
		return je.Code
	}
	return ""
}

func fail(c Code) error { return &Error{Code: c} }

// ServerAnswered reports whether err is a 5xx/529 the vendor actually sent.
func ServerAnswered(err error) bool {
	var je *Error
	return errors.As(err, &je) && je.ServerAnswered
}

// Option is one answer a choice question may return. Key is what the model
// sees and returns; an empty Description is sent as null.
type Option struct {
	Key         string
	Description string
}

// Question is a `choice` question.
type Question struct {
	Instructions string
	Options      []Option
}

// Answer is one validated choice answer.
type Answer struct {
	Pick          string
	Probabilities map[string]float64
	Confidence    float64
}

// Result is a whole response.
type Result struct {
	Model       string
	Answers     map[string]Answer
	InputTokens int
}

// KeyFunc resolves the API key per call, so a key saved in the admin panel
// takes effect on the next call with no restart. "" means not configured.
type KeyFunc func(ctx context.Context) string

// Client talks to POST {endpoint}/v1/systemone.
type Client struct {
	endpoint string
	model    string
	key      KeyFunc
	http     *http.Client
	br       *breaker.Breaker
	now      func() time.Time
	timeout  time.Duration
}

// ClientOption customises a Client (tests).
type ClientOption func(*Client)

// WithHTTPClient swaps the transport.
func WithHTTPClient(h *http.Client) ClientOption { return func(c *Client) { c.http = h } }

// WithClock drives the breaker's cooldown.
func WithClock(now func() time.Time) ClientOption { return func(c *Client) { c.now = now } }

// New builds a client. Empty endpoint/model fall back to the defaults.
func New(endpoint, model string, key KeyFunc, opts ...ClientOption) *Client {
	c := &Client{
		endpoint: strings.TrimRight(strings.TrimSpace(endpoint), "/"),
		model:    strings.TrimSpace(model),
		key:      key,
		http:     &http.Client{},
		now:      time.Now,
		timeout:  defaultTimeout,
	}
	if c.endpoint == "" {
		c.endpoint = DefaultEndpoint
	}
	if c.model == "" {
		c.model = DefaultModel
	}
	for _, o := range opts {
		o(c)
	}
	c.br = breaker.New(c.now)
	return c
}

// Model is the model id sent on every request.
func (c *Client) Model() string { return c.model }

// Configured reports whether a key currently resolves.
func (c *Client) Configured(ctx context.Context) bool { return strings.TrimSpace(c.key(ctx)) != "" }

type wireQuestion struct {
	Type         string             `json:"type"`
	Instructions string             `json:"instructions"`
	Criteria     map[string]*string `json:"criteria"`
}

type wireRequest struct {
	Model     string                  `json:"model"`
	State     any                     `json:"state"`
	Questions map[string]wireQuestion `json:"questions"`
}

type wireResponse struct {
	Model   string `json:"model"`
	Answers map[string]struct {
		Type          string             `json:"type"`
		Choice        string             `json:"choice"`
		Probabilities map[string]float64 `json:"probabilities"`
		Confidence    float64            `json:"confidence"`
	} `json:"answers"`
	Usage struct {
		InputTokens int `json:"input_tokens"`
	} `json:"usage"`
}

// Ask sends one request carrying every question. Questions run in parallel on
// the vendor side and cannot see each other's answers.
func (c *Client) Ask(ctx context.Context, state any, questions map[string]Question) (Result, error) {
	key := strings.TrimSpace(c.key(ctx))
	if key == "" {
		return Result{}, fail(CodeNotConfigured)
	}
	body, err := encode(c.model, state, questions)
	if err != nil {
		return Result{}, err
	}
	if !c.br.Allow() {
		return Result{}, fail(CodeUnavailable)
	}
	rctx, cancel := context.WithTimeout(ctx, c.timeout)
	defer cancel()
	req, err := http.NewRequestWithContext(rctx, http.MethodPost, c.endpoint+"/v1/systemone", bytes.NewReader(body))
	if err != nil {
		return Result{}, fail(CodeInvalidRequest)
	}
	req.Header.Set("Authorization", "Bearer "+key)
	req.Header.Set("Content-Type", "application/json")
	resp, err := c.http.Do(req)
	if err != nil {
		c.br.Failure()
		return Result{}, fail(CodeUnavailable)
	}
	defer func() { _ = resp.Body.Close() }()
	switch {
	// 404/405 means TYPESAFE_ENDPOINT points somewhere that is not the API:
	// an account-level outage, never a per-video failure.
	case resp.StatusCode >= 500:
		c.br.Failure()
		return Result{}, &Error{Code: CodeUnavailable, ServerAnswered: true}
	case resp.StatusCode == http.StatusNotFound || resp.StatusCode == http.StatusMethodNotAllowed:
		c.br.Failure()
		return Result{}, fail(CodeUnavailable)
	case resp.StatusCode == http.StatusUnauthorized || resp.StatusCode == http.StatusForbidden:
		c.br.Success()
		return Result{}, fail(CodeAuth)
	case resp.StatusCode == http.StatusTooManyRequests:
		c.br.Success()
		return Result{}, fail(CodeRateLimited)
	case resp.StatusCode >= 400:
		c.br.Success()
		return Result{}, fail(CodeInvalidRequest)
	}
	c.br.Success()
	raw, err := io.ReadAll(io.LimitReader(resp.Body, maxResponseBytes+1))
	if err != nil || len(raw) > maxResponseBytes {
		return Result{}, fail(CodeBadResponse)
	}
	var wr wireResponse
	if err := json.Unmarshal(raw, &wr); err != nil {
		return Result{}, fail(CodeBadResponse)
	}
	return validate(wr, questions)
}

func encode(model string, state any, questions map[string]Question) ([]byte, error) {
	wq := make(map[string]wireQuestion, len(questions))
	for id, q := range questions {
		if len(q.Options) == 0 || len(q.Options) > MaxOptions {
			return nil, fail(CodeInvalidRequest)
		}
		crit := make(map[string]*string, len(q.Options))
		for _, o := range q.Options {
			if _, dup := crit[o.Key]; dup || o.Key == "" {
				return nil, fail(CodeInvalidRequest)
			}
			if o.Description == "" {
				crit[o.Key] = nil
			} else {
				d := o.Description
				crit[o.Key] = &d
			}
		}
		wq[id] = wireQuestion{Type: "choice", Instructions: q.Instructions, Criteria: crit}
	}
	b, err := json.Marshal(wireRequest{Model: model, State: state, Questions: wq})
	if err != nil {
		return nil, fail(CodeInvalidRequest)
	}
	return b, nil
}

func validate(wr wireResponse, questions map[string]Question) (Result, error) {
	res := Result{Model: wr.Model, Answers: make(map[string]Answer, len(questions)), InputTokens: wr.Usage.InputTokens}
	for id, q := range questions {
		a, ok := wr.Answers[id]
		if !ok || a.Type != "choice" {
			return Result{}, fail(CodeBadResponse)
		}
		allowed := false
		for _, o := range q.Options {
			if o.Key == a.Choice {
				allowed = true
				break
			}
		}
		if !allowed {
			return Result{}, fail(CodeBadResponse)
		}
		res.Answers[id] = Answer{Pick: a.Choice, Probabilities: a.Probabilities, Confidence: a.Confidence}
	}
	return res, nil
}

```

- [ ] **Step 4: Run the tests**

Run: `go test ./internal/judgment/ -race -v`
Expected: every test PASSes. `TestAskClassifiesFailures` has 11 subtests.

- [ ] **Step 5: Commit** (one small PR: this package only)

```bash
git add internal/judgment
git commit -m "feat(judgment): TypeSafe Jev client with closed error codes and a breaker

Video-agnostic choice-question client for POST /v1/systemone, pinned to
jev-1.13.0. Errors are a closed code set that never carries upstream text
or the key.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 3: Env config, compose consumers, `.env.example`, denylist (PR C3, core)

**Goal:** The four env keys are parsed, validated, passed through compose, documented, and the key can never reach a log or audit record.

**Files:**
- Modify: `internal/config/config.go` (struct beside the Whisper fields, L461-480; literal beside L1236-1238; `validate()` near L1860)
- Modify: `internal/config/config_test.go` (next to `TestWhisperDefaultsAndOverride`, L953)
- Modify: `docker-compose.yml` (`x-api-env`, after the Whisper block at L385-391)
- Modify: `.env.example` (after the Whisper block at L205-216)
- Modify: `internal/observability/audit.go` (`sensitiveKeys`, L291-375), `internal/observability/audit_test.go:151`

**Acceptance Criteria:**
- [ ] Unset gives `TypeSafeEndpoint=https://api.typesafe.ai`, `TypeSafeModel=jev-1.13.0`, `MetadataAutofillEnabled=false`, `TypeSafeAPIKey=""`.
- [ ] A non-http(s) `TYPESAFE_ENDPOINT` is a boot error naming the variable.
- [ ] `docker compose config` renders each key, and the empty compose defaults fall through to the Go defaults.
- [ ] `IsSensitiveKey("typesafe_api_key")` and `IsSensitiveKey("typesafe.api_key")` are true.

**Verify:** `go test ./internal/config/ ./internal/observability/ -race` → `ok`. `TYPESAFE_ENDPOINT= docker compose --profile core config | grep -E 'TYPESAFE|METADATA_AUTOFILL'` shows 4 lines.

**Steps:**

- [ ] **Step 1: Failing tests.** Append to `internal/config/config_test.go`:

```go
func TestTypeSafeDefaultsAndOverride(t *testing.T) {
	cfg := mustLoadFrom(t, map[string]string{})
	if cfg.TypeSafeEndpoint != "https://api.typesafe.ai" || cfg.TypeSafeModel != "jev-1.13.0" ||
		cfg.TypeSafeAPIKey != "" || cfg.MetadataAutofillEnabled {
		t.Fatalf("defaults = %q %q %q %v", cfg.TypeSafeEndpoint, cfg.TypeSafeModel, cfg.TypeSafeAPIKey, cfg.MetadataAutofillEnabled)
	}
	cfg = mustLoadFrom(t, map[string]string{
		"TYPESAFE_ENDPOINT": "http://jev-stub:8080/", "TYPESAFE_MODEL": "jev-1.14.0",
		"TYPESAFE_API_KEY": "k", "METADATA_AUTOFILL_ENABLED": "true",
	})
	if cfg.TypeSafeEndpoint != "http://jev-stub:8080" || cfg.TypeSafeModel != "jev-1.14.0" ||
		cfg.TypeSafeAPIKey != "k" || !cfg.MetadataAutofillEnabled {
		t.Fatalf("override = %+v", cfg)
	}
}

func TestTypeSafeEndpointMustBeHTTP(t *testing.T) {
	_, err := loadFromMap(map[string]string{"TYPESAFE_ENDPOINT": "ftp://x"})
	if err == nil || !strings.Contains(err.Error(), "TYPESAFE_ENDPOINT") {
		t.Fatalf("err = %v, want a TYPESAFE_ENDPOINT error", err)
	}
}
```

`mustLoadFrom` and `loadFromMap` are placeholders for the file's existing map-backed `LoadFrom` helpers. Before writing, open `internal/config/loadfrom_test.go`, find the helper that builds a `lookup` from a map (it also fills the required keys such as `JWT_SECRET`), and use it under its real name. If there is none, add this one to the test file:

```go
func loadFromMap(env map[string]string) (*Config, error) {
	base := map[string]string{} // copy the minimal required env from TestWhisperDefaultsAndOverride's setup
	for k, v := range env {
		base[k] = v
	}
	return LoadFrom(func(k string) (string, bool) { v, ok := base[k]; return v, ok })
}

func mustLoadFrom(t *testing.T, env map[string]string) *Config {
	t.Helper()
	cfg, err := loadFromMap(env)
	if err != nil {
		t.Fatalf("LoadFrom: %v", err)
	}
	return cfg
}
```

Append to the `TestIsSensitiveKey` "must be flagged" table in `internal/observability/audit_test.go`: `"typesafe_api_key", "typesafe.api_key", "TYPESAFE_API_KEY"`.

- [ ] **Step 2: Run them and watch them fail**

Run: `go test ./internal/config/ ./internal/observability/`
Expected: FAIL with `cfg.TypeSafeEndpoint undefined`, and the denylist rows fail.

- [ ] **Step 3: Implement.** In the `Config` struct after the Whisper fields:

```go
	// TypeSafe (Jev) automatic category/language. The key may also be set in
	// the admin panel (sealed), which wins over this env value.
	TypeSafeAPIKey          string
	TypeSafeEndpoint        string
	TypeSafeModel           string
	MetadataAutofillEnabled bool
```

In the `cfg := &Config{...}` literal after the Whisper lines:

```go
		TypeSafeAPIKey:          strings.TrimSpace(getEnv("TYPESAFE_API_KEY", "")),
		TypeSafeEndpoint:        strings.TrimRight(getEnv("TYPESAFE_ENDPOINT", "https://api.typesafe.ai"), "/"),
		TypeSafeModel:           strings.TrimSpace(getEnv("TYPESAFE_MODEL", "jev-1.13.0")),
		MetadataAutofillEnabled: p.Bool("METADATA_AUTOFILL_ENABLED", false),
```

In `validate()`, next to the Whisper check (reuse whatever URL helper that check uses, e.g. `isHTTPURL`):

```go
	if !isHTTPURL(c.TypeSafeEndpoint) {
		add(varErrorf("TYPESAFE_ENDPOINT", "config: TYPESAFE_ENDPOINT must be a valid http(s) URL"))
	}
```

In `sensitiveKeys`: `"typesafe_api_key": true, "typesafe.api_key": true,`.

In `docker-compose.yml` `x-api-env`, after `WHISPER_DEFAULT_LANGUAGE`:

```yaml
  # Automatic category & language (TypeSafe Jev). OFF by default. When on, the
  # title, description, channel name and tags of PUBLIC published videos are
  # sent to TypeSafe (US-hosted third party). The key may instead be set in the
  # admin panel, which wins. Endpoint/model MUST keep EMPTY compose defaults: an
  # empty value falls through to the Go defaults (https://api.typesafe.ai,
  # jev-1.13.0), and a literal here would shadow them. TYPESAFE_API_KEY is a
  # secret: never commit a real value.
  METADATA_AUTOFILL_ENABLED: ${METADATA_AUTOFILL_ENABLED:-false}
  TYPESAFE_API_KEY: ${TYPESAFE_API_KEY:-}
  TYPESAFE_ENDPOINT: ${TYPESAFE_ENDPOINT:-}
  TYPESAFE_MODEL: ${TYPESAFE_MODEL:-}
```

In `.env.example`, the same four keys with the same comment and empty values.

- [ ] **Step 4: Run them**

Run: `go test ./internal/config/ ./internal/observability/ -race && docker compose --profile core config | grep -E 'TYPESAFE|METADATA_AUTOFILL'`
Expected: `ok`, then 4 rendered keys. The key renders as `TYPESAFE_API_KEY: ""`.

- [ ] **Step 5: Commit**

```bash
git add internal/config internal/observability docker-compose.yml .env.example
git commit -m "feat(config): TypeSafe env keys with compose consumers and denylist entries

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 4: Migration 0152 and the queries (PR C4, core)

**Goal:** Create the four tables, the claim index and the run projection into `job_runs`, plus every query the later tasks call, proven against a scratch Postgres database.

**Files:**
- Create: `migrations/0152_metadata_autofill.up.sql`, `migrations/0152_metadata_autofill.down.sql`
- Create: `internal/store/queries/metadata_fill.sql`
- Generated: `internal/store/sqlcgen/metadata_fill.sql.go`, `models.go` (run `make sqlc`; never hand-edit)
- Create: `internal/store/metadata_fill_integration_test.go`

**Acceptance Criteria:**
- [ ] `make migrate-up`, then `go run ./cmd/api migrate down 1`, then `make migrate-up` round-trips; `make migrate-lint` passes.
- [ ] `ClaimNewMetadataJudgments` claims only public, published, unblocked videos of non-unlisted owners with an empty category or language and no judgment row. With `since` set, it claims only videos updated at or after `since`.
- [ ] Two concurrent claimers over a scratch database get disjoint sets.
- [ ] `RecordAndApplyMetadataJudgment` writes only empty fields, and only on a video that is still fully eligible and still `running`. It records the picks and `*_applied` in the same statement, reports what it wrote, and leaves `updated_at` untouched.
- [ ] Only one `metadata_fill_runs` row can be `running`. A second `StartMetadataFillRun` fails with a unique violation and requeues nothing.
- [ ] A run projects to one `job_runs` row (`queue='metadata_fill_runs'`, `actor_id = started_by`) whose state follows the run.

**Verify:** The §0.4 integration command with `-run 'MetadataFill|RecordAndApply'`. All PASS.

**Steps:**

- [ ] **Step 1: `migrations/0152_metadata_autofill.up.sql`**

```sql
-- Automatic category & language via TypeSafe Jev (meta spec
-- 2026-09-20-jev-metadata-autofill-design.md, plan revision 2).

-- One row per video ever sent. A row's EXISTENCE means "already judged",
-- including when Jev was not confident, so an uncertain video costs one
-- request, ever. Raw picks are kept apart from what was applied, so a bar can
-- change later without asking Jev again.
CREATE TABLE video_metadata_judgments (
    video_id         UUID PRIMARY KEY REFERENCES videos(id) ON DELETE CASCADE,
    state            TEXT NOT NULL DEFAULT 'pending'
                     CHECK (state IN ('pending','running','done','failed')),
    attempts         INT  NOT NULL DEFAULT 0,
    next_attempt_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    lease_expires_at TIMESTAMPTZ,
    model            TEXT,
    judged_at        TIMESTAMPTZ,
    category_pick    TEXT,   -- category id; NULL = none_of_these or not asked
    category_prob    REAL,
    language_pick    TEXT,   -- language code; NULL = unclear or not asked
    language_prob    REAL,
    category_applied TEXT,   -- what the worker wrote; cleared when a human sets it
    language_applied TEXT,
    last_error_code  TEXT CHECK (last_error_code IS NULL OR last_error_code ~ '^[a-z_]{1,32}$'),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX video_metadata_judgments_due_idx
    ON video_metadata_judgments (next_attempt_at) WHERE state = 'pending';
CREATE INDEX video_metadata_judgments_lease_idx
    ON video_metadata_judgments (lease_expires_at) WHERE state = 'running';

-- The claim scans public, published videos with an empty field, newest first,
-- every 30 s; without this it is a sequential scan and sort of `videos`.
-- The predicate matches the claim query's text exactly so the planner can use it.
CREATE INDEX videos_metadata_fill_candidates_idx
    ON videos (updated_at DESC, id)
    WHERE privacy = 'public' AND state = 'published'
      AND (NULLIF(category, '') IS NULL OR NULLIF(language, '') IS NULL);

-- Single row. enabled_since is when the toggle was last seen ON by the
-- leader: videos updated at or after it are filled automatically; everything
-- older waits for an operator-started run.
CREATE TABLE metadata_fill_state (
    singleton     BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
    enabled_since TIMESTAMPTZ,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO metadata_fill_state (singleton) VALUES (TRUE) ON CONFLICT DO NOTHING;

-- TypeSafe ACCOUNT state, shared by every Jev slice (this one and the report-
-- triage / watched-word slices after it): the account-wide pause after a key
-- rejection, rate limit or outage, and the admin-panel key, SEALED with
-- internal/secretbox (MFA KEK) or absent. Never plaintext.
CREATE TABLE typesafe_state (
    singleton      BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
    paused_until   TIMESTAMPTZ,
    paused_code    TEXT CHECK (paused_code IS NULL OR paused_code ~ '^[a-z_]{1,32}$'),
    api_key_sealed TEXT CHECK (api_key_sealed IS NULL OR api_key_sealed LIKE 'enc:%'),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO typesafe_state (singleton) VALUES (TRUE) ON CONFLICT DO NOTHING;

-- An operator-started "fill existing videos" run. While one is running the
-- enabled_since cutoff is lifted.
CREATE TABLE metadata_fill_runs (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    state       TEXT NOT NULL DEFAULT 'running' CHECK (state IN ('running','stopped','done')),
    started_by  UUID REFERENCES users(id) ON DELETE SET NULL,
    judged      INT  NOT NULL DEFAULT 0,
    filled      INT  NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ
);
-- At most one running run (precedent: 0067's ((TRUE)) index). A racing
-- second start fails here → 409.
CREATE UNIQUE INDEX metadata_fill_runs_one_running_idx
    ON metadata_fill_runs ((TRUE)) WHERE state = 'running';

-- Operational projection (0083): one job_runs row per RUN, never per video.
-- Its own function per the 0107/0120 convention (sync_legacy_job_run() raises
-- on an unknown table).
CREATE FUNCTION sync_metadata_fill_run_job_run() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    canonical_state  TEXT;
    canonical_job_id UUID;
    event_kind       TEXT;
BEGIN
    canonical_state := CASE NEW.state
        WHEN 'running' THEN 'running'
        WHEN 'stopped' THEN 'cancelled'
        WHEN 'done'    THEN 'succeeded'
    END;

    INSERT INTO job_runs (
        type, queue, source_id, state, stage, progress_percent, priority, attempt, actor_id,
        resource_type, resource_id, input_metadata, output_metadata,
        error_class, error_code, error_detail, error_retryable,
        created_at, started_at, updated_at, finished_at
    ) VALUES (
        'metadata_fill', 'metadata_fill_runs', NEW.id::text, canonical_state,
        '', NULL, 0, 1, NEW.started_by, 'instance', '',
        '{}'::jsonb, jsonb_build_object('judged', NEW.judged, 'filled', NEW.filled),
        '', '', '', NULL,
        NEW.created_at, NEW.created_at, NEW.updated_at, NEW.finished_at
    )
    ON CONFLICT (queue, source_id) WHERE source_id <> '' DO UPDATE SET
        state = EXCLUDED.state,
        output_metadata = EXCLUDED.output_metadata,
        updated_at = EXCLUDED.updated_at,
        finished_at = EXCLUDED.finished_at
    RETURNING id INTO canonical_job_id;

    IF TG_OP = 'INSERT' THEN
        event_kind := 'started';
    ELSIF OLD.state IS DISTINCT FROM NEW.state THEN
        event_kind := CASE canonical_state WHEN 'succeeded' THEN 'succeeded' ELSE 'cancelled' END;
    ELSE
        RETURN NEW; -- count bumps are not operator events
    END IF;

    INSERT INTO job_events (
        job_id, kind, state, stage, progress_percent, attempt, message, metadata, occurred_at
    ) VALUES (
        canonical_job_id, event_kind, canonical_state, '', NULL, 1, '', '{}'::jsonb, NEW.updated_at
    );
    RETURN NEW;
END;
$$;

CREATE TRIGGER metadata_fill_runs_operational_projection
AFTER INSERT OR UPDATE ON metadata_fill_runs
FOR EACH ROW EXECUTE FUNCTION sync_metadata_fill_run_job_run();
```

The reviewer checked these against `0083`/`0133`: `job_events.kind` has no enum, `progress_percent` and `error_retryable` accept NULL, `actor_id` is a column (0083:61), and `inherit_job_run_identity` acts only on child rows.

- [ ] **Step 2: `migrations/0152_metadata_autofill.down.sql`**

```sql
DROP TRIGGER IF EXISTS metadata_fill_runs_operational_projection ON metadata_fill_runs;
DROP FUNCTION IF EXISTS sync_metadata_fill_run_job_run();
DELETE FROM job_runs WHERE queue = 'metadata_fill_runs';
DROP TABLE IF EXISTS metadata_fill_runs;
DROP TABLE IF EXISTS typesafe_state;
DROP TABLE IF EXISTS metadata_fill_state;
DROP INDEX IF EXISTS videos_metadata_fill_candidates_idx;
DROP TABLE IF EXISTS video_metadata_judgments;
```

- [ ] **Step 3: `internal/store/queries/metadata_fill.sql`**

```sql
-- Eligibility mirrors ListVideoSearchDocsPage (search_outbox.sql:116-118).

-- name: ClaimNewMetadataJudgments :many
-- The INSERT is the claim (primary key). `since` NULL lifts the cutoff (an
-- operator run is active). The id tie-break keeps two overlapping claimers
-- in one order, so they cannot deadlock on a bulk import's equal timestamps.
INSERT INTO video_metadata_judgments (video_id, state, attempts, lease_expires_at)
SELECT v.id, 'running', 1, now() + interval '5 minutes'
FROM videos v
JOIN channels c ON c.id = v.channel_id
JOIN users au ON au.id = c.owner_id
WHERE v.privacy = 'public' AND v.state = 'published'
  AND (NULLIF(v.category, '') IS NULL OR NULLIF(v.language, '') IS NULL)
  AND NOT au.unlisted
  AND NOT EXISTS (SELECT 1 FROM video_blocks b WHERE b.video_id = v.id)
  AND (sqlc.narg('since')::timestamptz IS NULL OR v.updated_at >= sqlc.narg('since')::timestamptz)
  AND NOT EXISTS (SELECT 1 FROM video_metadata_judgments j WHERE j.video_id = v.id)
ORDER BY v.updated_at DESC, v.id
LIMIT sqlc.arg('lim')::int
ON CONFLICT (video_id) DO NOTHING
RETURNING video_id;

-- name: ClaimDueMetadataJudgments :many
-- Retries whose backoff elapsed, plus claims a crashed leader left running.
UPDATE video_metadata_judgments
SET state = 'running', attempts = attempts + 1, lease_expires_at = now() + interval '5 minutes'
WHERE video_id IN (
    SELECT video_id FROM video_metadata_judgments
    WHERE (state = 'pending' AND next_attempt_at <= now())
       OR (state = 'running' AND lease_expires_at <= now())
    ORDER BY next_attempt_at, video_id
    LIMIT sqlc.arg('lim')::int
    FOR UPDATE SKIP LOCKED
)
RETURNING video_id, attempts;

-- name: GetMetadataFillSubject :one
-- The public fields sent to Jev, plus whether the video is STILL eligible.
SELECT v.id, v.title, v.description, c.display_name AS channel_name,
       (v.privacy = 'public' AND v.state = 'published' AND NOT au.unlisted
        AND NOT EXISTS (SELECT 1 FROM video_blocks b WHERE b.video_id = v.id)
        AND (NULLIF(v.category, '') IS NULL OR NULLIF(v.language, '') IS NULL))::bool AS eligible,
       (NULLIF(v.category, '') IS NULL)::bool AS category_empty,
       (NULLIF(v.language, '') IS NULL)::bool AS language_empty
FROM videos v
JOIN channels c ON c.id = v.channel_id
JOIN users au ON au.id = c.owner_id
WHERE v.id = $1;

-- name: RecordAndApplyMetadataJudgment :one
-- ONE statement records the judgment and fills the still-empty fields, so no
-- crash or error can leave "judged but never applied", "applied but no
-- marker", or a marker on a value a human set in between. `cur` locks the
-- video (a concurrent human UpdateVideo waits, then its ClearInferredApplied
-- runs after this commits) and the judgment row, and carries the FULL
-- eligibility predicate: a video blocked or made private while Jev was
-- answering is recorded, never written. It deliberately does not bump
-- videos.updated_at.
WITH cur AS (
    SELECT v.id,
           (NULLIF(v.category, '') IS NULL AND sqlc.narg('category')::text IS NOT NULL) AS write_category,
           (NULLIF(v.language, '') IS NULL AND sqlc.narg('language')::text IS NOT NULL) AS write_language
    FROM videos v
    JOIN channels c ON c.id = v.channel_id
    JOIN users au ON au.id = c.owner_id
    JOIN video_metadata_judgments j ON j.video_id = v.id AND j.state = 'running'
    WHERE v.id = sqlc.arg('video_id')
      AND v.privacy = 'public' AND v.state = 'published'
      AND NOT au.unlisted
      AND NOT EXISTS (SELECT 1 FROM video_blocks b WHERE b.video_id = v.id)
    FOR UPDATE OF v, j
),
upd AS (
    UPDATE videos v
    SET category = CASE WHEN cur.write_category THEN sqlc.narg('category')::text ELSE v.category END,
        language = CASE WHEN cur.write_language THEN sqlc.narg('language')::text ELSE v.language END
    FROM cur
    WHERE v.id = cur.id AND (cur.write_category OR cur.write_language)
    RETURNING cur.write_category AS wc, cur.write_language AS wl
),
rec AS (
    UPDATE video_metadata_judgments j
    SET state = 'done', model = sqlc.narg('model'), judged_at = now(),
        category_pick = sqlc.narg('category_pick'), category_prob = sqlc.narg('category_prob'),
        language_pick = sqlc.narg('language_pick'), language_prob = sqlc.narg('language_prob'),
        category_applied = CASE WHEN COALESCE((SELECT wc FROM upd), false) THEN sqlc.narg('category')::text END,
        language_applied = CASE WHEN COALESCE((SELECT wl FROM upd), false) THEN sqlc.narg('language')::text END,
        lease_expires_at = NULL, last_error_code = NULL
    WHERE j.video_id = sqlc.arg('video_id') AND j.state = 'running'
    RETURNING j.video_id
)
SELECT COALESCE((SELECT wc FROM upd), false)::bool AS category_written,
       COALESCE((SELECT wl FROM upd), false)::bool AS language_written,
       EXISTS (SELECT 1 FROM rec)::bool AS recorded;

-- name: RecordMetadataJudgmentFailure :exec
UPDATE video_metadata_judgments
SET state = CASE WHEN attempts >= sqlc.arg('max_attempts')::int THEN 'failed' ELSE 'pending' END,
    next_attempt_at = sqlc.arg('next_attempt_at'), lease_expires_at = NULL,
    last_error_code = sqlc.narg('code')
WHERE video_id = sqlc.arg('video_id') AND state = 'running';

-- name: ReleaseMetadataJudgment :exec
-- Hand a claim back without spending an attempt (account paused, or the tick
-- aborted on a database error).
UPDATE video_metadata_judgments
SET state = 'pending', attempts = GREATEST(attempts - 1, 0),
    next_attempt_at = sqlc.arg('next_attempt_at'), lease_expires_at = NULL
WHERE video_id = sqlc.arg('video_id') AND state = 'running';

-- name: DeleteMetadataJudgment :exec
-- The video stopped being eligible before it was judged; forget the claim so
-- it becomes eligible again if it is republished.
DELETE FROM video_metadata_judgments WHERE video_id = $1 AND state = 'running';

-- name: ClearInferredApplied :exec
-- A human set the field: the Studio marker must never claim their value.
UPDATE video_metadata_judgments
SET category_applied = CASE WHEN sqlc.arg('category')::bool THEN NULL ELSE category_applied END,
    language_applied = CASE WHEN sqlc.arg('language')::bool THEN NULL ELSE language_applied END
WHERE video_id = sqlc.arg('video_id')
  AND (category_applied IS NOT NULL OR language_applied IS NOT NULL);

-- name: GetVideoAutoFilled :one
SELECT (j.category_applied IS NOT NULL AND j.category_applied = v.category)::bool AS category,
       (j.language_applied IS NOT NULL AND j.language_applied = v.language)::bool AS language
FROM video_metadata_judgments j
JOIN videos v ON v.id = j.video_id
WHERE j.video_id = $1;

-- name: GetMetadataFillState :one
SELECT enabled_since FROM metadata_fill_state WHERE singleton;

-- name: MarkMetadataFillActive :exec
UPDATE metadata_fill_state SET enabled_since = now(), updated_at = now()
WHERE singleton AND enabled_since IS NULL;

-- name: MarkMetadataFillInactive :exec
UPDATE metadata_fill_state SET enabled_since = NULL, updated_at = now()
WHERE singleton AND enabled_since IS NOT NULL;

-- name: GetTypeSafePause :one
SELECT paused_until, paused_code FROM typesafe_state WHERE singleton;

-- name: SetTypeSafePause :exec
UPDATE typesafe_state
SET paused_until = sqlc.narg('paused_until'), paused_code = sqlc.narg('paused_code'), updated_at = now()
WHERE singleton;

-- name: GetRunningMetadataFillRun :one
SELECT * FROM metadata_fill_runs WHERE state = 'running';

-- name: StartMetadataFillRun :one
-- Insert and requeue in ONE statement: a unique violation (a run already
-- running) rolls back the requeue too, and a requeue failure leaves no run.
WITH run AS (
    INSERT INTO metadata_fill_runs (started_by) VALUES (sqlc.narg('started_by')) RETURNING *
),
rq AS (
    UPDATE video_metadata_judgments
    SET state = 'pending', attempts = 0, next_attempt_at = now(), last_error_code = NULL
    WHERE state = 'failed'
    RETURNING 1
)
SELECT run.id, run.state, run.judged, run.filled, run.created_at,
       (SELECT count(*) FROM rq)::bigint AS requeued
FROM run;

-- name: FinishMetadataFillRun :execrows
UPDATE metadata_fill_runs
SET state = sqlc.arg('state'), finished_at = now(), updated_at = now()
WHERE id = sqlc.arg('id') AND state = 'running';

-- name: AddMetadataFillRunCounts :exec
UPDATE metadata_fill_runs
SET judged = judged + sqlc.arg('judged')::int, filled = filled + sqlc.arg('filled')::int, updated_at = now()
WHERE id = sqlc.arg('id') AND state = 'running';

-- name: CountUnjudgedEligibleVideos :one
SELECT count(*)::bigint
FROM videos v
JOIN channels c ON c.id = v.channel_id
JOIN users au ON au.id = c.owner_id
WHERE v.privacy = 'public' AND v.state = 'published'
  AND (NULLIF(v.category, '') IS NULL OR NULLIF(v.language, '') IS NULL)
  AND NOT au.unlisted
  AND NOT EXISTS (SELECT 1 FROM video_blocks b WHERE b.video_id = v.id)
  AND NOT EXISTS (SELECT 1 FROM video_metadata_judgments j WHERE j.video_id = v.id);

-- name: CountOpenMetadataJudgments :one
SELECT count(*)::bigint FROM video_metadata_judgments WHERE state IN ('pending', 'running');

-- name: CountMetadataJudgments :one
-- filled = the worker's value is STILL the current value; not_confident is
-- decided from the stored probabilities against the bars the caller passes,
-- so a later human edit cannot move a filled video into "not confident".
SELECT
  count(*) FILTER (WHERE j.state IN ('pending','running'))::bigint AS waiting,
  count(*) FILTER (WHERE (j.category_applied IS NOT NULL AND j.category_applied = v.category)
                      OR (j.language_applied IS NOT NULL AND j.language_applied = v.language))::bigint AS filled,
  count(*) FILTER (WHERE j.state = 'done' AND j.model IS NOT NULL  -- asked (not a nothing-to-ask terminal row)
                     AND (j.category_pick IS NULL OR j.category_prob < sqlc.arg('category_bar')::real)
                     AND (j.language_pick IS NULL OR j.language_prob < sqlc.arg('language_bar')::real))::bigint AS not_confident,
  count(*) FILTER (WHERE j.state = 'failed')::bigint AS failed
FROM video_metadata_judgments j
JOIN videos v ON v.id = j.video_id;

-- name: MetadataJudgmentDepth :many
-- vidra_queue_depth{queue="video_metadata_judgments",state=...}.
SELECT state, count(*)::bigint AS depth FROM video_metadata_judgments GROUP BY state;

-- name: SampleLabelledVideosForEvaluation :many
-- Human-labelled public videos for the evaluator. Excludes anything this
-- feature filled, so the evaluator never grades Jev against itself.
SELECT v.id, v.title, v.description, c.display_name AS channel_name,
       v.category::text AS category, v.language::text AS language
FROM videos v
JOIN channels c ON c.id = v.channel_id
JOIN users au ON au.id = c.owner_id
WHERE v.privacy = 'public' AND v.state = 'published'
  AND NOT au.unlisted
  AND NOT EXISTS (SELECT 1 FROM video_blocks b WHERE b.video_id = v.id)
  AND NULLIF(v.category, '') IS NOT NULL AND NULLIF(v.language, '') IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM video_metadata_judgments j WHERE j.video_id = v.id
                  AND (j.category_applied IS NOT NULL OR j.language_applied IS NOT NULL))
ORDER BY md5(v.id::text || sqlc.arg('seed')::text)
LIMIT sqlc.arg('lim')::int;
```

- [ ] **Step 4: Generate** with `make sqlc && make sqlc-verify`. Expected: no diff after generation. Read `internal/store/sqlcgen/metadata_fill.sql.go` once and confirm the field names the later tasks use: `ClaimNewMetadataJudgmentsParams{Since pgtype.Timestamptz; Lim int32}`, `RecordAndApplyMetadataJudgmentParams{VideoID uuid.UUID; Category, Language, Model, CategoryPick, LanguagePick *string; CategoryProb, LanguageProb *float32}` with row `{CategoryWritten, LanguageWritten, Recorded bool}`, `RecordMetadataJudgmentFailureParams{VideoID; MaxAttempts int32; NextAttemptAt time.Time; Code *string}`, `ReleaseMetadataJudgmentParams{VideoID; NextAttemptAt time.Time}`, `SetTypeSafePauseParams{PausedUntil pgtype.Timestamptz; PausedCode *string}`, `StartMetadataFillRunRow{…; Requeued int64}`, `CountMetadataJudgmentsParams{CategoryBar, LanguageBar float32}`. Fix the later tasks' code to the generated names if any differ.

- [ ] **Step 5: Failing integration test** `internal/store/metadata_fill_integration_test.go`. Each test builds a **scratch database**: copy `newScratchDB` from `internal/peertubeimport/importer_integration_test.go:2205` into this file, because it is unexported there. Migrate it with `internal/dbmigrate` the way `cmd/api/verify_blobs_integration_test.go:48` does, then open `store.New` on it. The fixture inserts rows with plain SQL through the scratch pool: a user (`unlisted` false/true), a channel, videos with a given privacy, state, category, language and `updated_at`, and a `video_blocks` row.

```go
//go:build integration

package store

import (
	"context"
	"sync"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgtype"

	"github.com/vidra/vidra-core/internal/store/sqlcgen"
)

func TestMetadataFillClaimEligibilityAndCutoff(t *testing.T) {
	ctx := context.Background()
	f := newMetadataFillFixture(t, ctx) // scratch DB + helpers (see Step 5 prose)
	q := f.q
	old := f.video(t, videoSpec{privacy: "public", state: "published", updatedAt: time.Now().Add(-48 * time.Hour)})
	fresh := f.video(t, videoSpec{privacy: "public", state: "published"})
	_ = f.video(t, videoSpec{privacy: "private", state: "published"})
	_ = f.video(t, videoSpec{privacy: "public", state: "draft"})
	_ = f.video(t, videoSpec{privacy: "public", state: "published", category: "10", language: "en"})
	_ = f.video(t, videoSpec{privacy: "public", state: "published", ownerUnlisted: true})
	blocked := f.video(t, videoSpec{privacy: "public", state: "published"})
	f.block(t, blocked)

	since := pgtype.Timestamptz{Time: time.Now().Add(-time.Hour), Valid: true}
	got, err := q.ClaimNewMetadataJudgments(ctx, sqlcgen.ClaimNewMetadataJudgmentsParams{Since: since, Lim: 100})
	if err != nil {
		t.Fatal(err)
	}
	if len(got) != 1 || got[0] != fresh {
		t.Fatalf("with since: claimed %v, want only %s (the cutoff must exclude %s)", got, fresh, old)
	}
	got, _ = q.ClaimNewMetadataJudgments(ctx, sqlcgen.ClaimNewMetadataJudgmentsParams{Lim: 100})
	if len(got) != 1 || got[0] != old {
		t.Fatalf("without since: claimed %v, want only %s", got, old)
	}
}

func TestMetadataFillConcurrentClaimsAreDisjoint(t *testing.T) {
	ctx := context.Background()
	f := newMetadataFillFixture(t, ctx)
	for i := 0; i < 40; i++ {
		f.video(t, videoSpec{privacy: "public", state: "published"})
	}
	var mu sync.Mutex
	seen := map[uuid.UUID]int{}
	var wg sync.WaitGroup
	for w := 0; w < 4; w++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			ids, err := f.q.ClaimNewMetadataJudgments(ctx, sqlcgen.ClaimNewMetadataJudgmentsParams{Lim: 25})
			if err != nil {
				t.Error(err)
				return
			}
			mu.Lock()
			for _, id := range ids {
				seen[id]++
			}
			mu.Unlock()
		}()
	}
	wg.Wait()
	for id, n := range seen {
		if n > 1 {
			t.Fatalf("video %s claimed %d times", id, n)
		}
	}
}

func TestRecordAndApplyGuards(t *testing.T) {
	ctx := context.Background()
	f := newMetadataFillFixture(t, ctx)
	q := f.q
	s := func(v string) *string { return &v }
	p := func(v float32) *float32 { return &v }

	human := f.video(t, videoSpec{privacy: "public", state: "published", category: "10"})
	f.claim(t, human)
	before := f.updatedAt(t, human)
	row, err := q.RecordAndApplyMetadataJudgment(ctx, sqlcgen.RecordAndApplyMetadataJudgmentParams{
		VideoID: human, Category: s("2"), Language: s("en"), Model: s("jev-1.13.0"),
		CategoryPick: s("2"), CategoryProb: p(0.9), LanguagePick: s("en"), LanguageProb: p(0.99),
	})
	if err != nil {
		t.Fatal(err)
	}
	if row.CategoryWritten || !row.LanguageWritten || !row.Recorded {
		t.Fatalf("row = %+v, want language only, recorded", row)
	}
	if c, l := f.taxonomy(t, human); c != "10" || l != "en" {
		t.Fatalf("taxonomy = %q/%q, want the human category kept", c, l)
	}
	if ca, la := f.applied(t, human); ca != nil || la == nil || *la != "en" {
		t.Fatalf("applied = %v/%v, want language only", ca, la)
	}
	if !f.updatedAt(t, human).Equal(before) {
		t.Fatal("an automatic fill must not bump updated_at")
	}

	blocked := f.video(t, videoSpec{privacy: "public", state: "published"})
	f.claim(t, blocked)
	f.block(t, blocked) // blocked while Jev was answering
	row, err = q.RecordAndApplyMetadataJudgment(ctx, sqlcgen.RecordAndApplyMetadataJudgmentParams{
		VideoID: blocked, Language: s("en"), Model: s("jev-1.13.0"), LanguagePick: s("en"), LanguageProb: p(0.99),
	})
	if err != nil || row.LanguageWritten || !row.Recorded {
		t.Fatalf("blocked: row=%+v err=%v, want recorded and nothing written", row, err)
	}
}

func TestMetadataFillRunsOneRunningAndProjection(t *testing.T) {
	ctx := context.Background()
	f := newMetadataFillFixture(t, ctx)
	q := f.q
	actor := pgtype.UUID{Bytes: f.admin, Valid: true}
	failed := f.video(t, videoSpec{privacy: "public", state: "published"})
	f.judgmentRow(t, failed, "failed")

	run, err := q.StartMetadataFillRun(ctx, actor)
	if err != nil || run.Requeued != 1 {
		t.Fatalf("start: run=%+v err=%v, want 1 requeued", run, err)
	}
	f.judgmentRow(t, f.video(t, videoSpec{privacy: "public", state: "published"}), "failed")
	if _, err := q.StartMetadataFillRun(ctx, actor); err == nil {
		t.Fatal("a second running run was allowed")
	}
	if n := f.countState(t, "failed"); n != 1 {
		t.Fatalf("a refused start requeued rows: failed = %d, want 1", n)
	}
	if state, actorID := f.jobRun(t, run.ID); state != "running" || actorID != f.admin {
		t.Fatalf("projection = %q by %s", state, actorID)
	}
	if n, _ := q.FinishMetadataFillRun(ctx, sqlcgen.FinishMetadataFillRunParams{ID: run.ID, State: "stopped"}); n != 1 {
		t.Fatal("stop did not update the run")
	}
	if state, _ := f.jobRun(t, run.ID); state != "cancelled" {
		t.Fatalf("projected state = %q, want cancelled", state)
	}
}
```

The fixture (`newMetadataFillFixture`, `videoSpec`, `video`, `block`, `claim`, `judgmentRow`, `updatedAt`, `taxonomy`, `applied`, `countState`, `jobRun`, and the `admin` user id and `q *sqlcgen.Queries` fields) goes in the same file, about 150 lines of plain SQL over the scratch pool. `claim` inserts a `running` judgment row directly, and `t.Cleanup` drops the scratch database.

- [ ] **Step 6: Run** the §0.4 integration command with `-run 'MetadataFill|RecordAndApply'`. Expected: 4 PASS. Then `go vet -tags=integration ./...` and `make ci`.

- [ ] **Step 7: Commit**

```bash
git add migrations/0152_* internal/store/queries/metadata_fill.sql internal/store/sqlcgen internal/store/metadata_fill_integration_test.go
git commit -m "feat(store): metadata auto-fill tables, claim index, run projection and queries (0152)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 5: `video.Service` seams: narrow hook, best-effort clear, `AutoFilled` (PR C5, core)

**Goal:** An automatic fill can notify search, and only search. A human edit clears the marker without ever failing the edit. Callers can ask which fields are auto-filled.

**Files:**
- Create: `internal/video/inferred.go`, `internal/video/inferred_test.go`
- Modify: `internal/video/service.go` (`Service` fields L307-343; `Repository` interface ~L134-174; `UpdateForActor` after the `repo.UpdateVideo` call, L2089-2107)
- Modify: **both** fakes that implement `video.Repository`: `internal/video/service_test.go` (`newFakeRepo(owner uuid.UUID)`, L107) and `internal/httpapi/videos_test.go:56` (`videoFakeRepo`)

**Acceptance Criteria:**
- [ ] `WithInferredMetadataHook(fn)` registers a `func(ctx, videoID)`, and `NotifyInferredMetadata(ctx, id)` calls every such hook and nothing else. The `onUpdate` hooks do not fire.
- [ ] `UpdateForActor` with `Category` and/or `Language` set calls `ClearInferredApplied` for exactly those fields, including when the value equals the current one. **A failing clear is logged and the edit still succeeds**, with tags replaced and hooks fired.
- [ ] `AutoFilled` returns subsets of `[]string{"category","language"}`, and `nil` for no row.
- [ ] `go test ./internal/httpapi/` still compiles and passes (the second fake).

**Verify:** `go test ./internal/video/ ./internal/httpapi/ -race` → PASS.

**Steps:**

- [ ] **Step 1: Repository additions** in `internal/video/service.go`:

```go
	ClearInferredApplied(ctx context.Context, arg sqlcgen.ClearInferredAppliedParams) error
	GetVideoAutoFilled(ctx context.Context, videoID uuid.UUID) (sqlcgen.GetVideoAutoFilledRow, error)
```

Add them to both fakes. In `videoFakeRepo`, `ClearInferredApplied` returns nil and `GetVideoAutoFilled` returns `sqlcgen.GetVideoAutoFilledRow{}, pgx.ErrNoRows` unless a test seeds it through a new `autoFilled map[uuid.UUID][2]bool` field. The video package's `fakeRepo` gets `clearCalls []sqlcgen.ClearInferredAppliedParams`, `clearErr error`, and the same `autoFilled` map.

- [ ] **Step 2: Failing tests** `internal/video/inferred_test.go`. Create the owner and the video the way the package's existing `Update` tests do (`grep -n 'func TestUpdate' internal/video/service_test.go`, and reuse their seeding helper).

```go
package video

import (
	"context"
	"errors"
	"testing"

	"github.com/google/uuid"
)

func TestNotifyInferredMetadataFiresOnlyTheNarrowHook(t *testing.T) {
	owner := uuid.New()
	repo := newFakeRepo(owner)
	var narrow, update int
	svc := NewService(repo, nil,
		WithInferredMetadataHook(func(context.Context, uuid.UUID) { narrow++ }),
		WithUpdateHook(func(context.Context, uuid.UUID, bool) { update++ }))
	svc.NotifyInferredMetadata(context.Background(), uuid.New())
	if narrow != 1 || update != 0 {
		t.Fatalf("narrow=%d update=%d; an auto-fill must not fan out to federation", narrow, update)
	}
}

func TestUpdateClearsInferredAppliedEvenOnSameValue(t *testing.T) {
	owner := uuid.New()
	repo := newFakeRepo(owner)
	svc := NewService(repo, nil)
	id := seedPublicVideo(t, repo, owner) // the existing seeding helper, renamed here for clarity
	ten := "10"
	if _, err := svc.Update(context.Background(), owner, id, UpdateInput{Category: &ten}); err != nil {
		t.Fatal(err)
	}
	if len(repo.clearCalls) != 1 || repo.clearCalls[0].VideoID != id || !repo.clearCalls[0].Category || repo.clearCalls[0].Language {
		t.Fatalf("clear calls = %+v, want category only", repo.clearCalls)
	}
}

func TestUpdateSurvivesAFailingClear(t *testing.T) {
	owner := uuid.New()
	repo := newFakeRepo(owner)
	repo.clearErr = errors.New("db blip")
	hooks := 0
	svc := NewService(repo, nil, WithUpdateHook(func(context.Context, uuid.UUID, bool) { hooks++ }))
	id := seedPublicVideo(t, repo, owner)
	en := "en"
	if _, err := svc.Update(context.Background(), owner, id, UpdateInput{Language: &en}); err != nil {
		t.Fatalf("a failed marker clear failed a saved edit: %v", err)
	}
	if hooks != 1 {
		t.Fatalf("hooks = %d; search/federation must still hear about the edit", hooks)
	}
}

func TestUpdateWithoutTaxonomyDoesNotClear(t *testing.T) {
	owner := uuid.New()
	repo := newFakeRepo(owner)
	svc := NewService(repo, nil)
	id := seedPublicVideo(t, repo, owner)
	title := "t"
	if _, err := svc.Update(context.Background(), owner, id, UpdateInput{Title: &title}); err != nil {
		t.Fatal(err)
	}
	if len(repo.clearCalls) != 0 {
		t.Fatal("a title-only edit cleared the auto-fill marker")
	}
}

func TestAutoFilled(t *testing.T) {
	owner := uuid.New()
	repo := newFakeRepo(owner)
	svc := NewService(repo, nil)
	id := uuid.New()
	if got, err := svc.AutoFilled(context.Background(), id); got != nil || err != nil {
		t.Fatalf("no row: got %v err %v, want nil nil", got, err)
	}
	repo.autoFilled[id] = [2]bool{false, true}
	if got, _ := svc.AutoFilled(context.Background(), id); len(got) != 1 || got[0] != "language" {
		t.Fatalf("got %v, want [language]", got)
	}
}
```

If the package's seeding helper has another name, use it and drop `seedPublicVideo`.

- [ ] **Step 3: Run them and watch them fail.** `go test ./internal/video/ -run 'Inferred|AutoFilled|Clear'`. Expected: FAIL with `undefined: WithInferredMetadataHook`.

- [ ] **Step 4: Implement.** Add `onInferred []func(context.Context, uuid.UUID)` to the `Service` struct. Then `internal/video/inferred.go`:

```go
package video

import (
	"context"
	"errors"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
)

// WithInferredMetadataHook registers a consumer of machine-filled category/
// language (the Jev auto-fill). Deliberately NOT the onUpdate seam: those
// hooks include the federation Update, which fans out one delivery per follower
// inbox, and the federated object carries neither field. A backfill must reach
// only what indexes these fields — search.
func WithInferredMetadataHook(fn func(context.Context, uuid.UUID)) Option {
	return func(s *Service) { s.onInferred = append(s.onInferred, fn) }
}

// NotifyInferredMetadata tells the inferred-metadata consumers that videoID's
// category/language were filled automatically. The write itself is done by
// internal/metadatafill in one statement with its judgment record.
func (s *Service) NotifyInferredMetadata(ctx context.Context, videoID uuid.UUID) {
	for _, fn := range s.onInferred {
		fn(ctx, videoID)
	}
}

// AutoFilled lists which of "category"/"language" currently hold the value
// the worker wrote. nil when the video was never judged.
func (s *Service) AutoFilled(ctx context.Context, id uuid.UUID) ([]string, error) {
	row, err := s.repo.GetVideoAutoFilled(ctx, id)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	var out []string
	if row.Category {
		out = append(out, "category")
	}
	if row.Language {
		out = append(out, "language")
	}
	return out, nil
}
```

If `internal/video` compares no-rows through its own sentinel (`grep -n 'ErrNoRows' internal/video/*.go`), use that. In `UpdateForActor`, directly after the `if err != nil { return sqlcgen.Video{}, err }` that follows `s.repo.UpdateVideo(...)`:

```go
	// A human set the field: the Studio "set automatically" marker must never
	// claim their value, including when they re-selected the machine's pick.
	// Best-effort, like every other side effect here: the edit has already
	// committed, and failing it now would skip the tag replace and every hook.
	if in.Category != nil || in.Language != nil {
		if err := s.repo.ClearInferredApplied(ctx, sqlcgen.ClearInferredAppliedParams{
			VideoID: id, Category: in.Category != nil, Language: in.Language != nil,
		}); err != nil {
			s.logger.Warn("clear inferred-metadata marker failed", "video_id", id, "error", err)
		}
	}
```

Use the service's existing logger field (`grep -n 'logger' internal/video/service.go`). If it has none, use `slog.Default()`, which is what the other best-effort paths in the file log to.

- [ ] **Step 5: Run.** `go test ./internal/video/ ./internal/httpapi/ -race` → PASS. Then `make ci`.

- [ ] **Step 6: Record proposal §0.2.1.** Paste the output of `grep -rn 'ORDER BY[^;]*updated_at' internal/store/queries/` and one sentence into the PR body.

- [ ] **Step 7: Commit**

```bash
git add internal/video internal/httpapi/videos_test.go
git commit -m "feat(video): narrow inferred-metadata hook; human edits clear the marker best-effort

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 6: PeerTube re-sync keeps a category or language the source is silent about (PR C6, core)

**Goal:** A re-run sync no longer erases a category or language when the PeerTube source has none. Without this fix, every re-run on beta (a PeerTube import) wipes the auto-fills, and their judgment rows then block any re-judge.

**Files:**
- Modify: `internal/peertubeimport/resync.go` (`resyncVideo` struct L238-253; the load at L325-336; the compare and write at L528-575)
- Test: `internal/peertubeimport/resync_test.go` (unit), `internal/peertubeimport/importer_integration_test.go` (beside the existing re-sync `originally_published_at` keep test; find it with `grep -n 'origPub\|OriginallyPublishedAt' internal/peertubeimport/importer_integration_test.go`)

**Acceptance Criteria:**
- [ ] A source video with no category (`v.Category == nil`) or no language (`nil` or `""`) leaves the Vidra value in place. It also does not count as a change: the digest compares against the kept value.
- [ ] A source that *does* carry a category or language still overwrites, which is today's behaviour.
- [ ] An existing re-sync integration test still passes; a new one proves the keep.

**Verify:** `go test ./internal/peertubeimport/ -race -run 'Keep|Resync|Digest'`, then the §0.4 integration command with `-run Resync`.

**Steps:**

- [ ] **Step 1: Failing unit test** in `resync_test.go`:

```go
func TestKeepWhenSourceSilent(t *testing.T) {
	s := func(v string) *string { return &v }
	cases := []struct {
		name     string
		src      *string
		cur      string
		want     *string
	}{
		{"silent source keeps ours", nil, "10", s("10")},
		{"empty source keeps ours", s(""), "en", s("en")},
		{"source value wins", s("3"), "10", s("3")},
		{"both empty stays empty", nil, "", nil},
	}
	for _, tc := range cases {
		got := keepWhenSourceSilent(tc.src, tc.cur)
		if (got == nil) != (tc.want == nil) || (got != nil && *got != *tc.want) {
			t.Errorf("%s: got %v, want %v", tc.name, got, tc.want)
		}
	}
}
```

- [ ] **Step 2: Run it and watch it fail.** Expected: `undefined: keepWhenSourceSilent`.

- [ ] **Step 3: Implement.**
  - Add `category, language string` to `resyncVideo`, with this comment appended to the struct's existing doc: "category and language join them: a source with none is not saying 'clear it', and Vidra may have filled them itself (metadata auto-fill)". In the load loop (L329-333), set `category: v.Category, language: v.Language`. The query already `COALESCE`s both to `''`.
  - Then add to `resync.go`:

```go
// keepWhenSourceSilent returns the source's value, or — when the source has
// none — the value already standing here. The same rule as duration and
// originally_published_at: silence is not an instruction to clear.
func keepWhenSourceSilent(src *string, cur string) *string {
	if src != nil && *src != "" {
		return src
	}
	if cur == "" {
		return nil
	}
	return &cur
}
```

  - Before `desired := videoDigest(...)` (L549):

```go
	category := keepWhenSourceSilent(intPtrToText(v.Category), cur.category)
	language := keepWhenSourceSilent(v.Language, cur.language)
```

  - In the `videoDigest(...)` call, replace `pgconv.Deref(intPtrToText(v.Category)), pgconv.Deref(v.Language)` with `pgconv.Deref(category), pgconv.Deref(language)`. In `ImportUpdateVideoParams`, set `Category: category, Language: language`.

- [ ] **Step 4: Integration test.** Beside the existing re-sync keep test for the original-publication date, add `TestResyncKeepsCategoryAndLanguageWhenSourceHasNone`. It seeds a source video with a NULL category and language and imports it. It then sets the Vidra video's category to `"10"` and its language to `"en"` directly (standing in for an auto-fill), re-runs the sync, and asserts both values survive and the video counts as skipped, with no `updated_at` bump. Copy the existing test's setup exactly and change only these assertions.

- [ ] **Step 5: Run.** The Verify commands pass. Then `make ci`.

- [ ] **Step 6: Commit.** The PR body states the behaviour change in one line (§0.2.7).

```bash
git add internal/peertubeimport
git commit -m "fix(peertubeimport): re-sync keeps a category/language the source is silent about

Same rule as duration and originally_published_at. Without it every re-run
erased values Vidra set itself (and would erase metadata auto-fills).

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 7: `metadatafill` request builder and decision (PR C7, core)

**Goal:** Pure functions that turn a video's public fields and the live vocabulary into one Jev request, and turn the answer into raw picks plus the values that clear the bars.

**Files:**
- Create: `internal/metadatafill/request.go`, `internal/metadatafill/request_test.go`

**Acceptance Criteria:**
- [ ] The state is `{"video":{"title","description"(≤2,000 runes),"channel","tags"}}` and nothing else.
- [ ] The category options are the live list by **label**, plus `none_of_these`. Each built-in label carries its description only when the id and label both match a built-in. Labels that collide are disambiguated as `Label (id)`.
- [ ] The language options are the 30 codes with their labels as descriptions, plus `unclear`.
- [ ] With more than 254 categories, the category question is omitted.
- [ ] With the category already set, the category question is omitted. The same holds for language.
- [ ] `Decide` maps answers back to ids and codes, records the winning probability, and fills only at or above `CategoryBar` (0.70) and `LanguageBar` (0.90).

**Verify:** `go test ./internal/metadatafill/ -race -run 'Build|Decide'` → PASS.

**Steps:**

- [ ] **Step 1: Failing tests** `internal/metadatafill/request_test.go`

```go
package metadatafill

import (
	"strings"
	"testing"

	"github.com/vidra/vidra-core/internal/judgment"
	"github.com/vidra/vidra-core/internal/video"
)

func subject() Subject {
	return Subject{Title: "Fixing a squeaky bike chain", Description: strings.Repeat("é", 2500),
		Channel: "Weekend Wrenching", Tags: []string{"diy"}, CategoryEmpty: true, LanguageEmpty: true}
}

func TestBuildRequestShape(t *testing.T) {
	req := BuildRequest(subject(), video.Categories, video.Languages)
	v := req.State["video"].(map[string]any)
	if d := v["description"].(string); len([]rune(d)) != 2000 {
		t.Fatalf("description runes = %d, want 2000", len([]rune(d)))
	}
	if len(v) != 4 {
		t.Fatalf("state fields = %v, want exactly title/description/channel/tags", v)
	}
	cat := req.Questions[QCategory]
	if len(cat.Options) != len(video.Categories)+1 || cat.Options[len(cat.Options)-1].Key != NoneOfThese {
		t.Fatalf("category options = %d", len(cat.Options))
	}
	if cat.Options[0].Description == "" {
		t.Fatal("a built-in category must carry its description")
	}
	lang := req.Questions[QLanguage]
	if len(lang.Options) != len(video.Languages)+1 || lang.Options[len(lang.Options)-1].Key != Unclear {
		t.Fatalf("language options = %d", len(lang.Options))
	}
}

func TestBuildRequestCustomTaxonomy(t *testing.T) {
	custom := []video.ConfigOption{{ID: "1", Label: "Gardening"}, {ID: "2", Label: "Music"}, {ID: "3", Label: "Music"}}
	req := BuildRequest(subject(), custom, video.Languages)
	opts := req.Questions[QCategory].Options
	if opts[0].Description != "" {
		t.Fatal("id 1 relabelled Gardening is not the built-in Music: no description")
	}
	if opts[1].Key != "Music" || opts[2].Key != "Music (3)" {
		t.Fatalf("collision keys = %q %q", opts[1].Key, opts[2].Key)
	}
}

func TestBuildRequestSkipsFullAndOversizedFields(t *testing.T) {
	s := subject()
	s.CategoryEmpty = false
	if _, ok := BuildRequest(s, video.Categories, video.Languages).Questions[QCategory]; ok {
		t.Fatal("asked for a category the video already has")
	}
	many := make([]video.ConfigOption, 255)
	for i := range many {
		many[i] = video.ConfigOption{ID: string(rune('a' + i%26)) + strings.Repeat("x", i), Label: "L" + strings.Repeat("x", i)}
	}
	if _, ok := BuildRequest(subject(), many, video.Languages).Questions[QCategory]; ok {
		t.Fatal("255 categories + none_of_these exceeds the 255-option cap; the question must be skipped")
	}
}

func TestDecideBars(t *testing.T) {
	req := BuildRequest(subject(), video.Categories, video.Languages)
	music := video.Categories[0]
	res := judgment.Result{Model: "jev-1.13.0", Answers: map[string]judgment.Answer{
		QCategory: {Pick: music.Label, Probabilities: map[string]float64{music.Label: 0.70}},
		QLanguage: {Pick: "en", Probabilities: map[string]float64{"en": 0.89}},
	}}
	d := Decide(res, req)
	if d.CategoryPick == nil || *d.CategoryPick != music.ID || d.Category == nil {
		t.Fatalf("category at exactly the bar must fill: %+v", d)
	}
	if d.LanguagePick == nil || *d.LanguagePick != "en" || d.Language != nil || d.LanguageProb != 0.89 {
		t.Fatalf("language below the bar must be stored, not applied: %+v", d)
	}
}

func TestDecideNoneOfTheseAndUnclear(t *testing.T) {
	req := BuildRequest(subject(), video.Categories, video.Languages)
	res := judgment.Result{Answers: map[string]judgment.Answer{
		QCategory: {Pick: NoneOfThese, Probabilities: map[string]float64{NoneOfThese: 0.99}},
		QLanguage: {Pick: Unclear, Probabilities: map[string]float64{Unclear: 0.99}},
	}}
	d := Decide(res, req)
	if d.CategoryPick != nil || d.Category != nil || d.LanguagePick != nil || d.Language != nil {
		t.Fatalf("no-match answers must store NULL picks: %+v", d)
	}
	if d.CategoryProb != 0.99 {
		t.Fatal("the winning probability is still recorded")
	}
}
```

- [ ] **Step 2: Run them and watch them fail**

Run: `go test ./internal/metadatafill/`
Expected: FAIL (no package).

- [ ] **Step 3: Write `internal/metadatafill/request.go`**

```go
// Package metadatafill fills the empty category and language of public
// videos from TypeSafe Jev judgments. It knows nothing about HTTP; the
// judgment client knows nothing about videos.
package metadatafill

import (
	"fmt"

	"github.com/vidra/vidra-core/internal/judgment"
	"github.com/vidra/vidra-core/internal/video"
)

// Question ids (code only; never sent to the model as meaning).
const (
	QCategory   = "category"
	QLanguage   = "language"
	NoneOfThese = "none_of_these"
	Unclear     = "unclear"
)

// Confidence bars. PLACEHOLDERS from the vendor's general guidance, not
// measurements of vidra content: the beta evaluation (meta docs) sets them.
const (
	CategoryBar = 0.70
	LanguageBar = 0.90

	maxDescriptionRunes = 2000
)

// builtinCategoryHelp describes the 18 built-in categories (video.Categories)
// by id. Used only when an option's id AND label both match a built-in: a
// custom taxonomy REPLACES the built-ins and may reuse their ids.
var builtinCategoryHelp = map[string]string{
	"1":  "songs, music videos, live performances, instruments",
	"2":  "feature films, shorts, trailers, film analysis",
	"3":  "cars, motorcycles, bicycles and other vehicles as the subject",
	"4":  "visual and performing arts, crafts, design",
	"5":  "competitive or recreational sport, athletes, matches",
	"6":  "travel, destinations, trips and events visited",
	"7":  "video games, gameplay, game reviews",
	"8":  "everyday life, vlogs, people and blogs",
	"9":  "comedy, sketches, humour",
	"10": "entertainment, shows, celebrities, general amusement",
	"11": "news, current affairs, politics",
	"12": "tutorials, how-to guides, repairs, fashion and style",
	"13": "lessons, lectures, explainers, learning",
	"14": "charity, activism, social causes, non-profits",
	"15": "science, technology, engineering, computing",
	"16": "animals, pets, wildlife",
	"17": "content made for children",
	"18": "cooking, recipes, food and drink",
}

// Subject is the public data sent for one video.
type Subject struct {
	Title, Description, Channel string
	Tags                        []string
	CategoryEmpty               bool
	LanguageEmpty               bool
}

// Request is one Jev request plus the maps needed to read its answer.
type Request struct {
	State        map[string]any
	Questions    map[string]judgment.Question
	categoryByKey map[string]string // option key -> category id
}

// BuildRequest builds the state and the (at most two) questions. A question is
// omitted when its field is already set or its options would exceed the
// vendor cap. Zero questions means there is nothing to ask.
func BuildRequest(s Subject, categories, languages []video.ConfigOption) Request {
	desc := []rune(s.Description)
	if len(desc) > maxDescriptionRunes {
		desc = desc[:maxDescriptionRunes]
	}
	tags := s.Tags
	if tags == nil {
		tags = []string{}
	}
	req := Request{
		State: map[string]any{"video": map[string]any{
			"title": s.Title, "description": string(desc), "channel": s.Channel, "tags": tags,
		}},
		Questions:     map[string]judgment.Question{},
		categoryByKey: map[string]string{},
	}
	if s.CategoryEmpty && len(categories) > 0 && len(categories)+1 <= judgment.MaxOptions {
		opts := make([]judgment.Option, 0, len(categories)+1)
		seen := map[string]bool{}
		for _, c := range categories {
			key := c.Label
			if seen[key] {
				key = fmt.Sprintf("%s (%s)", c.Label, c.ID)
			}
			seen[key] = true
			req.categoryByKey[key] = c.ID
			opts = append(opts, judgment.Option{Key: key, Description: builtinHelp(c)})
		}
		opts = append(opts, judgment.Option{Key: NoneOfThese, Description: "no category fits, or there is too little information to tell"})
		req.Questions[QCategory] = judgment.Question{
			Instructions: "Which category best describes the subject of the video in `video`?",
			Options:      opts,
		}
	}
	if s.LanguageEmpty {
		opts := make([]judgment.Option, 0, len(languages)+1)
		for _, l := range languages {
			opts = append(opts, judgment.Option{Key: l.ID, Description: l.Label})
		}
		opts = append(opts, judgment.Option{Key: Unclear, Description: "cannot tell, or the text mixes languages evenly"})
		req.Questions[QLanguage] = judgment.Question{
			Instructions: "In which language are `video.title` and `video.description` written?",
			Options:      opts,
		}
	}
	return req
}

func builtinHelp(c video.ConfigOption) string {
	for _, b := range video.Categories {
		if b.ID == c.ID && b.Label == c.Label {
			return builtinCategoryHelp[c.ID]
		}
	}
	return ""
}

// Decision is the raw judgment (always stored) and what clears the bars.
type Decision struct {
	Model                      string
	CategoryPick, LanguagePick *string // nil = none_of_these / unclear / not asked
	CategoryProb, LanguageProb float64
	CategoryAsked, LanguageAsked bool
	Category, Language         *string // non-nil only when at/over the bar
}

// Decide reads an answer. Vocabulary validation happens at write time, in the
// worker (Task 8), against the live list.
func Decide(res judgment.Result, req Request) Decision {
	d := Decision{Model: res.Model}
	if a, ok := res.Answers[QCategory]; ok {
		d.CategoryAsked = true
		d.CategoryProb = a.Probabilities[a.Pick]
		if id, known := req.categoryByKey[a.Pick]; known {
			d.CategoryPick = &id
			if d.CategoryProb >= CategoryBar {
				d.Category = &id
			}
		}
	}
	if a, ok := res.Answers[QLanguage]; ok {
		d.LanguageAsked = true
		d.LanguageProb = a.Probabilities[a.Pick]
		if a.Pick != Unclear {
			code := a.Pick
			d.LanguagePick = &code
			if d.LanguageProb >= LanguageBar {
				d.Language = &code
			}
		}
	}
	return d
}
```

Before committing, check `builtinCategoryHelp` against the real labels in `internal/video/config.go:19-38`. The ids above follow PeerTube's standard order (1 Music … 18 Food), which the file mirrors. If any id differs, fix the map so each description matches its label, and add a test that iterates `video.Categories` and asserts every built-in id has non-empty help.

- [ ] **Step 4: Run them.** `go test ./internal/metadatafill/ -race` → PASS. Then `make ci`.

- [ ] **Step 5: Commit**

```bash
git add internal/metadatafill
git commit -m "feat(metadatafill): build the Jev request and decide against the bars

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 8: `judgment.Account` pause and `metadatafill.Service.Tick` (PR C8, core)

**Goal:** One leader-gated tick claims up to 25 videos, judges them, and records-and-applies each answer in one statement. It notifies search, pauses the account on account-level failures without spending attempts, and backs off only on per-video failures. It maintains `enabled_since` and runs from global facts only.

**Files:**
- Create: `internal/judgment/account.go`, `internal/judgment/account_test.go`
- Create: `internal/metadatafill/service.go`, `internal/metadatafill/service_test.go`, `internal/metadatafill/fakes_test.go`

**Acceptance Criteria:**
- [ ] The toggle off (a global DB setting) clears `enabled_since` and stops a running run. A missing key only idles: it never clears the cutoff, because "no key in this process" is not a global fact.
- [ ] Toggle on with a key: `enabled_since` is stamped once, and new claims pass it as `since`. A running run passes `since = NULL`.
- [ ] A run finishes `done` only when `CountUnjudgedEligibleVideos` and `CountOpenMetadataJudgments` are both 0. An empty claim alone never finishes it.
- [ ] `auth` pauses the account for 15 minutes; `rate_limited` and `unavailable` pause it for 2 minutes. Every claim still held is released without spending an attempt, and nothing is sent while paused. An expired pause is cleared.
- [ ] `bad_response` and `invalid_request` record a failure with backoff of exactly 1, 2, 4 and 8 minutes, capped at 1 h; the 5th failure is `failed`.
- [ ] A confident answer goes through `RecordAndApplyMetadataJudgment` with the id and code, and `NotifyInferredMetadata` fires only when a field was written. An unconfident answer is recorded with nil `category`/`language`.
- [ ] Vocabulary is validated against the live lists (`video.IsCategory`, `video.IsLanguage`) before the write.
- [ ] A database error mid-batch releases the remaining claims and returns the error; run counts for videos already judged are still added.
- [ ] A video that makes the **server** fail (a 5xx/529 with `ServerAnswered`) pays one bounded attempt while the rest of the batch is released for free, so it reaches `failed` after `MaxAttempts` instead of pinning the account. Transport errors, an open breaker, 404/405, 401 and 429 spend nothing.
- [ ] A video with nothing to ask (for example more than 254 categories and only the category empty) is recorded `done` once, and never claimed again.
- [ ] Category validation at write time uses the same `s.categories()` list the question was built from.
- [ ] `enabled_since` is stamped even while the account is paused, because a pause does not mean the feature is off.
- [ ] A lost lease (`recorded=false`) is not counted as judged. Rule: a video that lost eligibility *before* it was asked has its claim deleted, so it is judged again if republished. One that lost it *during* the ≤5 s ask is recorded as judged, with nothing written.

**Verify:** `go test ./internal/judgment/ ./internal/metadatafill/ -race -v` → PASS.

**Steps:**

- [ ] **Step 1: Failing test** `internal/judgment/account_test.go`:

```go
package judgment

import (
	"context"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgtype"

	"github.com/vidra/vidra-core/internal/store/sqlcgen"
)

type fakeAccountRepo struct{ until pgtype.Timestamptz; code *string }

func (f *fakeAccountRepo) GetTypeSafePause(context.Context) (sqlcgen.GetTypeSafePauseRow, error) {
	return sqlcgen.GetTypeSafePauseRow{PausedUntil: f.until, PausedCode: f.code}, nil
}
func (f *fakeAccountRepo) SetTypeSafePause(_ context.Context, a sqlcgen.SetTypeSafePauseParams) error {
	f.until, f.code = a.PausedUntil, a.PausedCode
	return nil
}

func TestAccountPauseLifecycle(t *testing.T) {
	now := time.Date(2026, 9, 26, 12, 0, 0, 0, time.UTC)
	repo := &fakeAccountRepo{}
	acct := NewAccount(repo, func() time.Time { return now })
	ctx := context.Background()
	if _, paused, err := acct.Paused(ctx); paused || err != nil {
		t.Fatal("fresh account is paused")
	}
	if err := acct.Pause(ctx, CodeAuth); err != nil {
		t.Fatal(err)
	}
	if code, paused, _ := acct.Paused(ctx); !paused || code != CodeAuth || !repo.until.Time.Equal(now.Add(AuthPause)) {
		t.Fatalf("pause = %q/%v until %v", code, paused, repo.until.Time)
	}
	now = now.Add(AuthPause)
	if _, paused, _ := acct.Paused(ctx); paused {
		t.Fatal("an expired pause still pauses")
	}
	if repo.code != nil {
		t.Fatal("an expired pause was not cleared")
	}
	_ = acct.Pause(ctx, CodeUnavailable)
	if !repo.until.Time.Equal(now.Add(ShortPause)) {
		t.Fatalf("unavailable pause until %v, want %v", repo.until.Time, now.Add(ShortPause))
	}
	_ = acct.ClearPause(ctx)
	if _, paused, _ := acct.Paused(ctx); paused {
		t.Fatal("ClearPause did not clear")
	}
}
```

- [ ] **Step 2: Implement `internal/judgment/account.go`:**

```go
package judgment

import (
	"context"
	"time"

	"github.com/jackc/pgx/v5/pgtype"

	"github.com/vidra/vidra-core/internal/store/sqlcgen"
)

const (
	// AuthPause: a rejected key will not fix itself within seconds.
	AuthPause = 15 * time.Minute
	// ShortPause: rate limits and outages usually clear within minutes.
	ShortPause = 2 * time.Minute
)

// AccountRepository is typesafe_state access. *sqlcgen.Queries satisfies it.
type AccountRepository interface {
	GetTypeSafePause(ctx context.Context) (sqlcgen.GetTypeSafePauseRow, error)
	SetTypeSafePause(ctx context.Context, arg sqlcgen.SetTypeSafePauseParams) error
}

// Account is the TypeSafe account state every Jev slice shares: one key, one
// rate limit, one outage. Task 15 adds the sealed key to it.
type Account struct {
	repo AccountRepository
	now  func() time.Time
}

func NewAccount(repo AccountRepository, now func() time.Time) *Account {
	return &Account{repo: repo, now: now}
}

// Paused reports an active pause, clearing one that has expired.
func (a *Account) Paused(ctx context.Context) (Code, bool, error) {
	row, err := a.repo.GetTypeSafePause(ctx)
	if err != nil {
		return "", false, err
	}
	if !row.PausedUntil.Valid {
		return "", false, nil
	}
	if a.now().Before(row.PausedUntil.Time) {
		code := CodeUnavailable
		if row.PausedCode != nil {
			code = Code(*row.PausedCode)
		}
		return code, true, nil
	}
	return "", false, a.ClearPause(ctx)
}

// Pause stops every caller of this account until the pause expires.
func (a *Account) Pause(ctx context.Context, code Code) error {
	d := ShortPause
	if code == CodeAuth {
		d = AuthPause
	}
	c := string(code)
	return a.repo.SetTypeSafePause(ctx, sqlcgen.SetTypeSafePauseParams{
		PausedUntil: pgtype.Timestamptz{Time: a.now().Add(d), Valid: true},
		PausedCode:  &c,
	})
}

// ClearPause ends a pause (an expired one, or after a successful test).
func (a *Account) ClearPause(ctx context.Context) error {
	return a.repo.SetTypeSafePause(ctx, sqlcgen.SetTypeSafePauseParams{})
}

// PausesAccount reports whether a code is about the account, not the video.
func PausesAccount(c Code) bool {
	return c == CodeAuth || c == CodeRateLimited || c == CodeUnavailable
}
```

Run `go test ./internal/judgment/ -race` → PASS.

- [ ] **Step 3: Failing worker tests** `internal/metadatafill/service_test.go`. The fakes go in `fakes_test.go` (about 180 lines), and all use the service clock:
  - `fakeRepo` implements `Repository` from Step 4 and mirrors the SQL semantics. It holds eligible videos, judgment rows with state, attempts, next attempt, picks and applied values, `enabledSince *time.Time`, and the run. `ClaimNew` inserts `running` rows, honours `Since`, and records `lastSince`. `ClaimDue` returns rows due at the fake clock. `Release` decrements attempts. `RecordAndApply` fills empty fields and returns the written flags. `CountUnjudgedEligibleVideos` and `CountOpenMetadataJudgments` are computed from its state, and `failNext error` injects one database error.
  - `fakeJudge` has `configured bool` and `next []any` (each a `judgment.Result` or an `error`), and it counts `calls`.
  - `newFakeAccountRepo()` returns an in-memory `judgment.AccountRepository`, defined in this package's `fakes_test.go` because `judgment`'s test fake is invisible here. The tests wrap it in a real `judgment.Account`. **Task 15 must extend it** with the two key methods.
  - `fakeJudge` also gets an optional `fn func(state any) (judgment.Result, error)`, used instead of `next` when set, and `fakeRepo` gets `addEligibleWith(id, updatedAt, title string, categoryEmpty, languageEmpty bool)` and `claimsOf(id) int`.
  - `fakeNotifier` records ids.

```go
package metadatafill

import (
	"context"
	"fmt"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/vidra/vidra-core/internal/judgment"
	"github.com/vidra/vidra-core/internal/video"
)

type fx struct {
	svc      *Service
	repo     *fakeRepo
	judge    *fakeJudge
	notify   *fakeNotifier
	now      *time.Time
	enabled  *bool
}

func fixture(t *testing.T) fx {
	t.Helper()
	now := time.Date(2026, 9, 26, 12, 0, 0, 0, time.UTC)
	enabled := true
	clock := func() time.Time { return now }
	repo := newFakeRepo(clock)
	judge := &fakeJudge{configured: true}
	notify := &fakeNotifier{}
	svc := New(repo, judge, judgment.NewAccount(newFakeAccountRepo(), clock), notify,
		func() bool { return enabled },
		WithClock(clock),
		WithCategories(func() []video.ConfigOption { return video.Categories }))
	return fx{svc, repo, judge, notify, &now, &enabled}
}

func confident() judgment.Result {
	return judgment.Result{Model: "jev-1.13.0", Answers: map[string]judgment.Answer{
		QCategory: {Pick: video.Categories[0].Label, Probabilities: map[string]float64{video.Categories[0].Label: 0.9}},
		QLanguage: {Pick: "en", Probabilities: map[string]float64{"en": 0.99}},
	}}
}

func TestToggleOffClearsCutoffAndStopsRun(t *testing.T) {
	f := fixture(t)
	*f.enabled = false
	f.repo.enabledSince = &time.Time{}
	f.repo.run = &fakeRun{id: uuid.New(), state: "running"}
	if _, err := f.svc.Tick(context.Background()); err != nil {
		t.Fatal(err)
	}
	if f.repo.enabledSince != nil || f.repo.run.state != "stopped" || f.repo.claims != 0 {
		t.Fatalf("since=%v run=%q claims=%d", f.repo.enabledSince, f.repo.run.state, f.repo.claims)
	}
}

func TestMissingKeyIdlesButKeepsCutoff(t *testing.T) {
	f := fixture(t)
	f.judge.configured = false
	stamp := f.now.Add(-time.Hour)
	f.repo.enabledSince = &stamp
	_, _ = f.svc.Tick(context.Background())
	if f.repo.enabledSince == nil || f.repo.claims != 0 {
		t.Fatal("a process without a key must idle, never clear the global cutoff")
	}
}

func TestStampsEnabledSinceAndCutsOff(t *testing.T) {
	f := fixture(t)
	f.repo.addEligible(uuid.New(), f.now.Add(time.Minute))
	f.judge.next = []any{confident()}
	_, _ = f.svc.Tick(context.Background())
	if f.repo.enabledSince == nil || !f.repo.enabledSince.Equal(*f.now) {
		t.Fatalf("enabled_since = %v, want %v", f.repo.enabledSince, *f.now)
	}
	if f.repo.lastSince == nil || !f.repo.lastSince.Equal(*f.now) {
		t.Fatal("new claims must be cut off at enabled_since")
	}
}

func TestRunLiftsCutoffAndFinishesOnlyWhenNothingRemains(t *testing.T) {
	f := fixture(t)
	f.repo.run = &fakeRun{id: uuid.New(), state: "running"}
	f.repo.addEligible(uuid.New(), f.now.Add(-48*time.Hour))
	f.judge.next = []any{confident()}
	_, _ = f.svc.Tick(context.Background())
	if f.repo.lastSince != nil {
		t.Fatal("a running run must lift the cutoff")
	}
	if f.repo.run.judged != 1 || f.repo.run.filled != 1 {
		t.Fatalf("run counts = %d/%d", f.repo.run.judged, f.repo.run.filled)
	}
	// An empty claim while a retry is still pending must NOT finish the run.
	f.repo.rows[uuid.New()] = &fakeRow{state: "pending", nextAttempt: f.now.Add(time.Hour)}
	_, _ = f.svc.Tick(context.Background())
	if f.repo.run.state != "running" {
		t.Fatal("run finished while a judgment was still pending")
	}
	for id := range f.repo.rows {
		f.repo.rows[id].state = "done"
	}
	_, _ = f.svc.Tick(context.Background())
	if f.repo.run.state != "done" {
		t.Fatalf("run = %q, want done once nothing remains", f.repo.run.state)
	}
}

func TestAppliesOnlyConfidentAndNotifies(t *testing.T) {
	f := fixture(t)
	id := uuid.New()
	f.repo.addEligible(id, *f.now)
	res := confident()
	res.Answers[QLanguage] = judgment.Answer{Pick: "en", Probabilities: map[string]float64{"en": 0.5}}
	f.judge.next = []any{res}
	_, _ = f.svc.Tick(context.Background())
	r := f.repo.rows[id]
	if r.state != "done" || r.languagePick == nil || r.languageApplied != nil || r.categoryApplied == nil {
		t.Fatalf("row = %+v, want category applied, language recorded only", r)
	}
	if len(f.notify.ids) != 1 || f.notify.ids[0] != id {
		t.Fatalf("notified %v", f.notify.ids)
	}
}

func TestBackoffScheduleIsExact(t *testing.T) {
	f := fixture(t)
	id := uuid.New()
	f.repo.addEligible(id, *f.now)
	want := []time.Duration{time.Minute, 2 * time.Minute, 4 * time.Minute, 8 * time.Minute}
	for i, d := range want {
		f.judge.next = []any{&judgment.Error{Code: judgment.CodeBadResponse}}
		_, _ = f.svc.Tick(context.Background())
		r := f.repo.rows[id]
		if r.state != "pending" || !r.nextAttempt.Equal(f.now.Add(d)) {
			t.Fatalf("attempt %d: %+v, want pending until +%v", i+1, r, d)
		}
		*f.now = r.nextAttempt
	}
	f.judge.next = []any{&judgment.Error{Code: judgment.CodeBadResponse}}
	_, _ = f.svc.Tick(context.Background())
	if f.repo.rows[id].state != "failed" {
		t.Fatalf("after %d attempts state = %q, want failed", MaxAttempts, f.repo.rows[id].state)
	}
	if backoff(20) != time.Hour {
		t.Fatalf("backoff cap = %v, want 1h", backoff(20))
	}
}

func TestOutagePausesWithoutSpendingAttempts(t *testing.T) {
	for _, code := range []judgment.Code{judgment.CodeAuth, judgment.CodeRateLimited, judgment.CodeUnavailable} {
		t.Run(string(code), func(t *testing.T) {
			f := fixture(t)
			a, b := uuid.New(), uuid.New()
			f.repo.addEligible(a, *f.now)
			f.repo.addEligible(b, *f.now)
			f.judge.next = []any{&judgment.Error{Code: code}}
			_, _ = f.svc.Tick(context.Background())
			for _, id := range []uuid.UUID{a, b} {
				if r := f.repo.rows[id]; r.state != "pending" || r.attempts != 0 {
					t.Fatalf("%s = %+v, want released with attempts=0", id, r)
				}
			}
			f.judge.calls = 0
			_, _ = f.svc.Tick(context.Background())
			if f.judge.calls != 0 {
				t.Fatal("a paused account called Jev")
			}
		})
	}
}

func TestDatabaseErrorReleasesTheRest(t *testing.T) {
	f := fixture(t)
	f.repo.run = &fakeRun{id: uuid.New(), state: "running"}
	a, b := uuid.New(), uuid.New()
	f.repo.addEligible(a, *f.now)
	f.repo.addEligible(b, *f.now)
	f.judge.next = []any{confident(), confident()}
	f.repo.failRecordAfter = 1 // the 2nd RecordAndApply errors
	if _, err := f.svc.Tick(context.Background()); err == nil {
		t.Fatal("the database error was swallowed")
	}
	if f.repo.run.judged != 1 {
		t.Fatalf("run judged = %d, want the 1 already done counted", f.repo.run.judged)
	}
	for _, r := range f.repo.rows {
		if r.state == "running" {
			t.Fatalf("a claim was stranded running: %+v", r)
		}
	}
}

func TestPoisonVideoDoesNotStallTheBatch(t *testing.T) {
	f := fixture(t)
	bad, good := uuid.New(), uuid.New()
	f.repo.addEligibleWith(bad, *f.now, "poison", true, true)
	f.repo.addEligibleWith(good, f.now.Add(-time.Second), "fine", true, true)
	f.judge.fn = func(state any) (judgment.Result, error) {
		if state.(map[string]any)["video"].(map[string]any)["title"] == "poison" {
			return judgment.Result{}, &judgment.Error{Code: judgment.CodeUnavailable, ServerAnswered: true}
		}
		return confident(), nil
	}
	for i := 0; i < 12 && (f.repo.rows[good] == nil || f.repo.rows[good].state != "done"); i++ {
		_, _ = f.svc.Tick(context.Background())
		*f.now = f.now.Add(judgment.ShortPause)
	}
	if r := f.repo.rows[good]; r == nil || r.state != "done" {
		t.Fatal("one video that makes the server fail stalled the whole batch")
	}
	if f.repo.rows[bad].attempts == 0 {
		t.Fatal("the failing video spent no attempt, so it would pin the account forever")
	}
}

func TestNothingToAskIsRecordedOnce(t *testing.T) {
	f := fixture(t)
	many := make([]video.ConfigOption, 255)
	for i := range many {
		many[i] = video.ConfigOption{ID: fmt.Sprint(i + 1), Label: fmt.Sprint("C", i+1)}
	}
	f.svc.categories = func() []video.ConfigOption { return many }
	id := uuid.New()
	f.repo.addEligibleWith(id, *f.now, "t", true, false) // category empty, language set
	_, _ = f.svc.Tick(context.Background())
	_, _ = f.svc.Tick(context.Background())
	if r := f.repo.rows[id]; r == nil || r.state != "done" || f.judge.calls != 0 || f.repo.claimsOf(id) != 1 {
		t.Fatalf("row=%+v calls=%d claims=%d, want one done row, no Jev call, claimed once", r, f.judge.calls, f.repo.claimsOf(id))
	}
}

func TestVocabularyShrinkDropsTheCategory(t *testing.T) {
	f := fixture(t)
	calls := 0
	f.svc.categories = func() []video.ConfigOption {
		calls++
		if calls == 1 {
			return video.Categories
		}
		return video.Categories[1:] // Categories[0], the confident pick, was deleted meanwhile
	}
	id := uuid.New()
	f.repo.addEligible(id, *f.now)
	f.judge.next = []any{confident()}
	_, _ = f.svc.Tick(context.Background())
	if r := f.repo.rows[id]; r.categoryPick == nil || r.categoryApplied != nil {
		t.Fatalf("row = %+v, want the pick recorded but not applied", r)
	}
}

func TestIneligibleVideoIsForgotten(t *testing.T) {
	f := fixture(t)
	id := uuid.New()
	f.repo.addEligible(id, *f.now)
	f.repo.makeIneligibleAfterClaim[id] = true
	_, _ = f.svc.Tick(context.Background())
	if _, ok := f.repo.rows[id]; ok || f.judge.calls != 0 {
		t.Fatal("an ineligible video must be forgotten, not judged")
	}
}

```

- [ ] **Step 4: Run them and watch them fail.** `go test ./internal/metadatafill/`. Expected: FAIL with `undefined: New`.

- [ ] **Step 5: Implement `internal/metadatafill/service.go`**

```go
package metadatafill

import (
	"context"
	"errors"
	"log/slog"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"

	"github.com/vidra/vidra-core/internal/judgment"
	"github.com/vidra/vidra-core/internal/store/sqlcgen"
	"github.com/vidra/vidra-core/internal/video"
)

const (
	// Batch is the claim size per tick: ~50 videos a minute from the leader,
	// far under the vendor's 1,200 requests/min.
	Batch = 25
	// MaxAttempts per-video failures (bad_response / invalid_request) before a
	// video is marked failed. Account-level failures never spend attempts.
	MaxAttempts = 5

	backoffBase = time.Minute
	backoffMax  = time.Hour
)

func backoff(attempts int32) time.Duration {
	d := backoffBase
	for i := int32(1); i < attempts; i++ {
		d *= 2
		if d >= backoffMax {
			return backoffMax
		}
	}
	return d
}

// Repository is the data access the worker needs. *sqlcgen.Queries satisfies it.
type Repository interface {
	GetMetadataFillState(ctx context.Context) (pgtype.Timestamptz, error)
	MarkMetadataFillActive(ctx context.Context) error
	MarkMetadataFillInactive(ctx context.Context) error
	GetRunningMetadataFillRun(ctx context.Context) (sqlcgen.MetadataFillRun, error)
	FinishMetadataFillRun(ctx context.Context, arg sqlcgen.FinishMetadataFillRunParams) (int64, error)
	AddMetadataFillRunCounts(ctx context.Context, arg sqlcgen.AddMetadataFillRunCountsParams) error
	ClaimDueMetadataJudgments(ctx context.Context, lim int32) ([]sqlcgen.ClaimDueMetadataJudgmentsRow, error)
	ClaimNewMetadataJudgments(ctx context.Context, arg sqlcgen.ClaimNewMetadataJudgmentsParams) ([]uuid.UUID, error)
	CountUnjudgedEligibleVideos(ctx context.Context) (int64, error)
	CountOpenMetadataJudgments(ctx context.Context) (int64, error)
	GetMetadataFillSubject(ctx context.Context, id uuid.UUID) (sqlcgen.GetMetadataFillSubjectRow, error)
	ListVideoTags(ctx context.Context, videoID uuid.UUID) ([]string, error)
	RecordAndApplyMetadataJudgment(ctx context.Context, arg sqlcgen.RecordAndApplyMetadataJudgmentParams) (sqlcgen.RecordAndApplyMetadataJudgmentRow, error)
	RecordMetadataJudgmentFailure(ctx context.Context, arg sqlcgen.RecordMetadataJudgmentFailureParams) error
	ReleaseMetadataJudgment(ctx context.Context, arg sqlcgen.ReleaseMetadataJudgmentParams) error
	DeleteMetadataJudgment(ctx context.Context, videoID uuid.UUID) error
}

// Judge is the judgment client surface.
type Judge interface {
	Configured(ctx context.Context) bool
	Ask(ctx context.Context, state any, qs map[string]judgment.Question) (judgment.Result, error)
}

// Notifier is video.Service's narrow inferred-metadata seam (search only).
type Notifier interface {
	NotifyInferredMetadata(ctx context.Context, videoID uuid.UUID)
}

// Service is the state-scan worker. Its loop is leader-gated (cmd/api), so
// every global decision below is made by exactly one process.
type Service struct {
	repo       Repository
	judge      Judge
	account    *judgment.Account
	notify     Notifier
	enabled    func() bool
	now        func() time.Time
	categories func() []video.ConfigOption
	logger     *slog.Logger
}

// Option customises a Service.
type Option func(*Service)

func WithClock(now func() time.Time) Option               { return func(s *Service) { s.now = now } }
func WithCategories(f func() []video.ConfigOption) Option { return func(s *Service) { s.categories = f } }
func WithLogger(l *slog.Logger) Option                     { return func(s *Service) { s.logger = l } }

// New builds the worker. enabled is the runtime toggle, re-read every tick.
func New(repo Repository, judge Judge, account *judgment.Account, notify Notifier, enabled func() bool, opts ...Option) *Service {
	s := &Service{repo: repo, judge: judge, account: account, notify: notify, enabled: enabled,
		now: time.Now, categories: video.CategoryOptions, logger: slog.Default()}
	for _, o := range opts {
		o(s)
	}
	return s
}

func (s *Service) Enabled() bool                       { return s.enabled() }
func (s *Service) Configured(ctx context.Context) bool { return s.judge.Configured(ctx) }

type claim struct {
	id       uuid.UUID
	attempts int32
}

type outcome int

const (
	outcomeSkipped outcome = iota
	outcomeJudged
	outcomeFilled
	outcomePause
	outcomePauseSpent // pause; the triggering video already paid an attempt
)

// Tick is one jobloop pass. It returns the number of videos judged.
func (s *Service) Tick(ctx context.Context) (int, error) {
	if !s.enabled() {
		// The toggle is a GLOBAL setting: only here is the cutoff cleared.
		if err := s.repo.MarkMetadataFillInactive(ctx); err != nil {
			return 0, err
		}
		return 0, s.stopRunningRun(ctx)
	}
	if !s.judge.Configured(ctx) {
		return 0, nil // idle; a missing key is not a reason to move the cutoff
	}
	// Stamp first: a pause is an account condition, not the feature being off.
	if err := s.repo.MarkMetadataFillActive(ctx); err != nil {
		return 0, err
	}
	if _, paused, err := s.account.Paused(ctx); err != nil || paused {
		return 0, err
	}
	since, err := s.repo.GetMetadataFillState(ctx)
	if err != nil {
		return 0, err
	}
	run, err := s.repo.GetRunningMetadataFillRun(ctx)
	hasRun := err == nil
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return 0, err
	}
	if hasRun {
		since = pgtype.Timestamptz{}
	}

	claims, err := s.claim(ctx, since)
	if err != nil {
		return 0, err
	}
	if hasRun && len(claims) == 0 {
		return 0, s.finishIfDrained(ctx, run.ID)
	}

	judged, filled := 0, 0
	var tickErr error
	for i, c := range claims {
		out, code, err := s.judgeOne(ctx, c)
		if err != nil {
			s.release(ctx, claims[i:])
			tickErr = err
			break
		}
		if out == outcomePause || out == outcomePauseSpent {
			rest := claims[i:]
			if out == outcomePauseSpent {
				rest = claims[i+1:]
			}
			s.release(ctx, rest)
			if perr := s.account.Pause(ctx, code); perr != nil {
				tickErr = perr
			}
			break
		}
		if out == outcomeJudged || out == outcomeFilled {
			judged++
		}
		if out == outcomeFilled {
			filled++
		}
	}
	if hasRun && judged > 0 {
		if err := s.repo.AddMetadataFillRunCounts(ctx, sqlcgen.AddMetadataFillRunCountsParams{
			ID: run.ID, Judged: int32(judged), Filled: int32(filled),
		}); err != nil && tickErr == nil {
			tickErr = err
		}
	}
	return judged, tickErr
}

func (s *Service) claim(ctx context.Context, since pgtype.Timestamptz) ([]claim, error) {
	var out []claim
	due, err := s.repo.ClaimDueMetadataJudgments(ctx, Batch)
	if err != nil {
		return nil, err
	}
	for _, d := range due {
		out = append(out, claim{d.VideoID, d.Attempts})
	}
	if room := Batch - len(out); room > 0 {
		ids, err := s.repo.ClaimNewMetadataJudgments(ctx, sqlcgen.ClaimNewMetadataJudgmentsParams{Since: since, Lim: int32(room)})
		if err != nil {
			s.release(ctx, out)
			return nil, err
		}
		for _, id := range ids {
			out = append(out, claim{id, 1})
		}
	}
	return out, nil
}

// finishIfDrained ends a run only when a QUERY says nothing is left — never
// because one claim came back empty.
func (s *Service) finishIfDrained(ctx context.Context, runID uuid.UUID) error {
	unjudged, err := s.repo.CountUnjudgedEligibleVideos(ctx)
	if err != nil {
		return err
	}
	open, err := s.repo.CountOpenMetadataJudgments(ctx)
	if err != nil {
		return err
	}
	if unjudged > 0 || open > 0 {
		return nil
	}
	_, err = s.repo.FinishMetadataFillRun(ctx, sqlcgen.FinishMetadataFillRunParams{ID: runID, State: "done"})
	return err
}

func (s *Service) stopRunningRun(ctx context.Context) error {
	run, err := s.repo.GetRunningMetadataFillRun(ctx)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil
	}
	if err != nil {
		return err
	}
	_, err = s.repo.FinishMetadataFillRun(ctx, sqlcgen.FinishMetadataFillRunParams{ID: run.ID, State: "stopped"})
	return err
}

// release hands claims back without spending an attempt.
func (s *Service) release(ctx context.Context, held []claim) {
	for _, c := range held {
		if err := s.repo.ReleaseMetadataJudgment(ctx, sqlcgen.ReleaseMetadataJudgmentParams{
			VideoID: c.id, NextAttemptAt: s.now(),
		}); err != nil {
			s.logger.Warn("metadata fill: release claim failed", "video_id", c.id, "error", err)
		}
	}
}

func (s *Service) judgeOne(ctx context.Context, c claim) (outcome, judgment.Code, error) {
	subj, err := s.repo.GetMetadataFillSubject(ctx, c.id)
	if errors.Is(err, pgx.ErrNoRows) || (err == nil && !subj.Eligible) {
		return outcomeSkipped, "", s.repo.DeleteMetadataJudgment(ctx, c.id)
	}
	if err != nil {
		return outcomeSkipped, "", err
	}
	tags, err := s.repo.ListVideoTags(ctx, c.id)
	if err != nil {
		return outcomeSkipped, "", err
	}
	req := BuildRequest(Subject{
		Title: subj.Title, Description: subj.Description, Channel: subj.ChannelName, Tags: tags,
		CategoryEmpty: subj.CategoryEmpty, LanguageEmpty: subj.LanguageEmpty,
	}, s.categories(), video.Languages)
	if len(req.Questions) == 0 {
		// Nothing this instance may ask (e.g. >254 categories and only the
		// category is empty): a terminal row, so it is never claimed again.
		_, err := s.repo.RecordAndApplyMetadataJudgment(ctx, sqlcgen.RecordAndApplyMetadataJudgmentParams{VideoID: c.id})
		return outcomeSkipped, "", err
	}
	res, err := s.judge.Ask(ctx, req.State, req.Questions)
	if err != nil {
		code := judgment.CodeOf(err)
		if code == "" {
			code = judgment.CodeUnavailable
		}
		if judgment.PausesAccount(code) || code == judgment.CodeNotConfigured {
			// A video whose text makes the SERVER fail must not pin the whole
			// account forever: it pays one bounded attempt; the rest of the
			// batch is released for free. A genuine vendor-wide 5xx therefore
			// costs at most one video an attempt per pause cycle.
			if judgment.ServerAnswered(err) {
				codeStr := string(code)
				if ferr := s.repo.RecordMetadataJudgmentFailure(ctx, sqlcgen.RecordMetadataJudgmentFailureParams{
					VideoID: c.id, MaxAttempts: MaxAttempts, NextAttemptAt: s.now().Add(backoff(c.attempts)), Code: &codeStr,
				}); ferr != nil {
					return outcomeSkipped, "", ferr
				}
				return outcomePauseSpent, code, nil
			}
			return outcomePause, code, nil
		}
		codeStr := string(code)
		return outcomeSkipped, code, s.repo.RecordMetadataJudgmentFailure(ctx, sqlcgen.RecordMetadataJudgmentFailureParams{
			VideoID: c.id, MaxAttempts: MaxAttempts, NextAttemptAt: s.now().Add(backoff(c.attempts)), Code: &codeStr,
		})
	}
	d := Decide(res, req)
	if d.Category != nil && !inOptions(s.categories(), *d.Category) {
		d.Category = nil // deleted from the live taxonomy since the question was built
	}
	if d.Language != nil && !video.IsLanguage(*d.Language) {
		d.Language = nil
	}
	model := d.Model
	row, err := s.repo.RecordAndApplyMetadataJudgment(ctx, sqlcgen.RecordAndApplyMetadataJudgmentParams{
		VideoID: c.id, Model: &model, Category: d.Category, Language: d.Language,
		CategoryPick: d.CategoryPick, CategoryProb: probPtr(d.CategoryAsked, d.CategoryProb),
		LanguagePick: d.LanguagePick, LanguageProb: probPtr(d.LanguageAsked, d.LanguageProb),
	})
	if err != nil {
		return outcomeSkipped, "", err
	}
	if !row.Recorded {
		return outcomeSkipped, "", nil // the claim was lost; whoever holds it records it
	}
	if !row.CategoryWritten && !row.LanguageWritten {
		return outcomeJudged, "", nil
	}
	s.notify.NotifyInferredMetadata(ctx, c.id)
	return outcomeFilled, "", nil
}

// inOptions checks an id against the SAME list the question was built from.
func inOptions(opts []video.ConfigOption, id string) bool {
	for _, o := range opts {
		if o.ID == id {
			return true
		}
	}
	return false
}

func probPtr(asked bool, p float64) *float32 {
	if !asked {
		return nil
	}
	v := float32(p)
	return &v
}
```

`GetMetadataFillState` returns `pgtype.Timestamptz` directly, because a single-column `:one` makes sqlc return the column type. `code == judgment.CodeNotConfigured` releases the claims and pauses the account for 2 minutes. That is reachable only if the key disappears between `Configured` and `Ask`. The `pause` branch passes the code on, and `Account.Pause` maps it to the 2-minute pause.

- [ ] **Step 6: Run.** `go test ./internal/judgment/ ./internal/metadatafill/ -race -v` → PASS. Then `make ci`.

- [ ] **Step 7: Commit**

```bash
git add internal/judgment internal/metadatafill
git commit -m "feat(metadatafill): leader-gated tick with atomic record-and-apply and account pauses

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 9: Toggle, infra row, category provider, wiring, metrics (PR C9, core)

**Goal:** The worker runs, leader-gated, in the api binary. It is switched on at runtime through the admin toggle, reports itself on the infrastructure snapshot, sees the instance's own category list in every role, and exports its queue depth.

**Files:**
- Modify: `internal/instancesettings/service.go` (const near L199; `Defaults` L576-606; `specs` row near L870)
- Modify: `internal/instancesettings/service_test.go` (`testDefaults()` L47; table L78-103), `internal/httpapi/admin_instance_settings_test.go` (`settingsDefaultsFromConfig` L63; count L199-200 **118 → 119**)
- Modify: `cmd/api/main.go` (Defaults L309-340; after `settingssvc.Load` L341; video service options ~L1331-1399; worker start beside the leader-gated sweeps ~L2443; queue-depth source L2866-2883; new worker func beside `runTranscodeHoldSweepWorker` L3340)
- Modify: `internal/httpapi/admin_infra.go` (`infraFeatures` L379; off notes L688; misconfigured notes L721), `internal/httpapi/admin_infra_test.go` (`wantKeys` L264-268; `TestInfrastructureFeatureDiscovery` L258)
- Modify: `internal/httpapi/server.go` (field and `WithMetadataFill` option)
- Modify: `internal/video/config.go` (`categoryProvider` L106-130: make it an `atomic.Pointer`)

**No `api/openapi.yaml` change in this PR.** The prose updates for the new setting key and infrastructure key ride in Task 10, so that vidra-user's contract check changes once (§0.3).

**Acceptance Criteria:**
- [ ] `metadata_autofill_enabled` is a `KindBool` on `PageVOD`, section `autofill`, whose default is `cfg.MetadataAutofillEnabled`. The settings count is 119.
- [ ] `video.SetCategoryProvider(settingssvc.Categories)` runs right after the boot `settingssvc.Load`, before any worker goroutine and in every role. The provider is stored in an `atomic.Pointer`: `httpapi.WithSettingsService` stores it again after the worker goroutine has started, and a plain package variable would be a data race under `-race`.
- [ ] The worker loop is `jobloop.Loop{Interval: 30s, Leader: <the cron leader>}` and starts whenever `runWorkers`.
- [ ] `infrastructure.features` ends with `metadata_autofill`, and it carries the missing-key note when enabled but not configured.
- [ ] `vidra_queue_depth{queue="video_metadata_judgments",state=…}` is exported when metrics are on.
- [ ] The search enqueuer is registered as the `WithInferredMetadataHook` consumer.

**Verify:** `go test ./internal/instancesettings/ ./internal/httpapi/ -race -run 'Registry|Settings|Infrastructure'` → PASS. Then `make ci` and the integration command (Step 5).

**Steps:**

- [ ] **Step 1: Failing tests.**
  - In the `service_test.go` table, add `{KeyMetadataAutofillEnabled, KindBool, false, PageVOD, "autofill"},`.
  - In `admin_instance_settings_test.go`, change `118` to `119` in the condition and the message, and add to the comment block above: `// +1 metadata_autofill_enabled (Jev auto-fill)`.
  - In `admin_infra_test.go`, append `"metadata_autofill"` to `wantKeys`. In the mutate table (~L306), the server built there has no fill provider, so the row reads `Enabled:false`. Add a dedicated test instead:

```go
func TestInfrastructureMetadataAutofillRow(t *testing.T) {
	srv := New(testConfig(), nil, nil, WithMetadataFill(fakeFillFlags{enabled: true, configured: false}))
	f := findInfraFeature(t, srv, "metadata_autofill") // build on the helper TestInfrastructureFeatureDiscovery uses to GET and decode
	if !f.Enabled || f.Configured || !strings.Contains(f.Note, "TYPESAFE_API_KEY") {
		t.Fatalf("row = %+v", f)
	}
}

type fakeFillFlags struct{ enabled, configured bool }

func (f fakeFillFlags) Enabled() bool                   { return f.enabled }
func (f fakeFillFlags) Configured(context.Context) bool { return f.configured }
```

  If `TestInfrastructureFeatureDiscovery` inlines its GET-and-decode, extract it into `findInfraFeature` in this PR. The infrastructure route requires an admin, so follow whatever auth setup that test already uses.

- [ ] **Step 2: Run them and watch them fail.** Expected: FAIL (undefined key, count 118, missing row).

- [ ] **Step 3: Implement.**

`internal/instancesettings/service.go`:

```go
	// KeyMetadataAutofillEnabled switches automatic category/language on. It is
	// effective only when a TypeSafe key resolves (env or admin panel).
	KeyMetadataAutofillEnabled = "metadata_autofill_enabled"
```

Add `MetadataAutofillEnabled bool` to `Defaults`, and after the transcription row add:

```go
		{key: KeyMetadataAutofillEnabled, kind: KindBool, defBool: func(d Defaults) bool { return d.MetadataAutofillEnabled }, validate: validateBool,
			page: PageVOD, section: "autofill"},
```

Map `MetadataAutofillEnabled` in `testDefaults()`, in `settingsDefaultsFromConfig`, and in `main.go`'s `Defaults` literal (`MetadataAutofillEnabled: cfg.MetadataAutofillEnabled,`).

`internal/httpapi/server.go`:

```go
// metadataFillProvider is the admin surface of the Jev auto-fill worker.
type metadataFillProvider interface {
	Enabled() bool
	Configured(ctx context.Context) bool
}

// WithMetadataFill wires the Jev auto-fill worker's admin surface.
func WithMetadataFill(p metadataFillProvider) Option {
	return func(s *Server) { s.metadatafillsvc = p }
}
```

Add the field `metadatafillsvc metadataFillProvider`. Task 10 widens the interface.

`internal/httpapi/admin_infra.go`: change `infraFeatures()` to `infraFeatures(ctx context.Context)`. It has one caller; pass `c.Request().Context()`. Append:

```go
		{
			Key:        "metadata_autofill",
			Enabled:    s.metadatafillsvc != nil && s.metadatafillsvc.Enabled(),
			Configured: s.metadatafillsvc != nil && s.metadatafillsvc.Configured(ctx),
		},
```

Add the two notes:

```go
	// infraFeatureOffNotes
	"metadata_autofill": "Automatic category and language for public videos. Off by default; switch it on under Config → VOD. When on, the title, description, channel name and tags of public videos are sent to TypeSafe (US-hosted).",
	// infraFeatureMisconfiguredNotes
	"metadata_autofill": "Switched on, but no TypeSafe API key is set, so nothing is sent and nothing is filled. Set TYPESAFE_API_KEY in the env file (the admin-panel key field arrives in a later release).",
```

`cmd/api/main.go`:

0. In `internal/video/config.go`, replace the plain variable (L115-130) with:

```go
var categoryProvider atomic.Pointer[func() []ConfigOption]

// SetCategoryProvider installs the live taxonomy; nil restores the built-in
// list (the documented contract config_test.go:49 relies on).
func SetCategoryProvider(f func() []ConfigOption) {
	if f == nil {
		categoryProvider.Store(nil)
		return
	}
	categoryProvider.Store(&f)
}

func CategoryOptions() []ConfigOption {
	if p := categoryProvider.Load(); p != nil {
		if opts := (*p)(); len(opts) > 0 {
			return opts
		}
	}
	return Categories
}
```

   Keep the existing doc comment, and add `"sync/atomic"` to the imports. Extend `TestCategoryProviderReplacesBuiltins` (`internal/video/config_test.go`) with `SetCategoryProvider(nil)` followed by `if !IsCategory("1") { t.Fatal("nil must restore the built-ins") }`. Storing a pointer to a nil func would panic there. `go test -race ./...` is the proof.

1. Directly after the `settingssvc.Load(startCtx)` error check (L341):

```go
	// The live category taxonomy, for EVERY role. httpapi also registers it,
	// but a VIDRA_ROLE=worker process returns before httpapi.New, and the
	// auto-fill worker must never judge or validate against the built-in list
	// on an instance whose custom list replaces it (and may reuse its ids).
	video.SetCategoryProvider(settingssvc.Categories)
```

2. In the `video.NewService(...)` options (~L1386-1398, inside `if searchEnqueuer != nil`):

```go
			video.WithInferredMetadataHook(func(ctx context.Context, videoID uuid.UUID) {
				searchEnqueuer.EnqueueVideoUpsert(ctx, videoID)
			}),
```

Search is the only consumer that indexes category and language (vidra-search filters on both: `internal/store/queries/search.sql:33-34,61-62`). Federation is deliberately absent (§0.2.9).

3. Construct the client and the worker after the video service and `settingssvc` exist:

```go
	typesafeAccount := judgment.NewAccount(db.Queries(), time.Now)
	judgeClient := judgment.New(cfg.TypeSafeEndpoint, cfg.TypeSafeModel,
		func(context.Context) string { return cfg.TypeSafeAPIKey })
	metadatafillsvc := metadatafill.New(db.Queries(), judgeClient, typesafeAccount, videosvc,
		func() bool { return settingssvc.Bool(instancesettings.KeyMetadataAutofillEnabled) },
		metadatafill.WithLogger(logger))
```

   Use the local name of the `*video.Service` (`grep -n 'video.NewService(' cmd/api/main.go`). Pass `httpapi.WithMetadataFill(metadatafillsvc)` with the other server options.

4. Beside the other leader-gated sweeps (~L2443, after `cronLeader` exists at L2295):

```go
	if runWorkers {
		workerCtx, workerCancel := context.WithCancel(context.Background())
		defer workerCancel()
		go runMetadataFillWorker(workerCtx, logger, cronLeader, metadatafillsvc)
		logger.Info("metadata auto-fill worker started")
	}
```

   Use the same leader value passed to `runTranscodeHoldSweepWorker`.

5. Beside `runTranscodeHoldSweepWorker` (L3340):

```go
// runMetadataFillWorker drives the Jev auto-fill state scan. Leader-gated:
// enabled_since, pauses and "run done" are global facts, decided by one
// process. Always started — the key may arrive at runtime — and each tick is a
// no-op unless the toggle is on and a key resolves.
func runMetadataFillWorker(ctx context.Context, logger *slog.Logger, leader jobloop.Leader, svc *metadatafill.Service) {
	jobloop.Loop{
		Interval: 30 * time.Second,
		Leader:   leader,
		Passes: []jobloop.Pass{{
			FailMsg: "metadata auto-fill tick failed",
			DoneMsg: "metadata auto-fill judged videos",
			Run:     func(ctx context.Context, _ time.Time) (int, error) { return svc.Tick(ctx) },
		}},
	}.Run(ctx, logger)
}
```

6. In the queue-depth source (L2866-2883), after the search-outbox block:

```go
			if rows, derr := db.Queries().MetadataJudgmentDepth(ctx); derr == nil {
				for _, r := range rows {
					out = append(out, observability.QueueDepth{Queue: "video_metadata_judgments", State: r.State, Count: r.Depth})
				}
			}
```

- [ ] **Step 4: Run.** `go test ./internal/instancesettings/ ./internal/httpapi/ -race` → PASS.

- [ ] **Step 5: Integration proof** in `internal/metadatafill/worker_integration_test.go` (`//go:build integration`, scratch database per §0.4). It uses a real `sqlcgen.Queries`, a real `video.Service` with a `WithInferredMetadataHook` that records ids, and an `httptest` Jev that answers built-in category "Music" at 0.95 and `en` at 0.99. Seed one eligible video, call `svc.Tick`, and assert:
  - `videos.category` is Music's id and `language='en'`;
  - `GetVideoAutoFilled` returns both;
  - the hook saw the id exactly once;
  - `updated_at` is unchanged.

  Run the §0.4 command → PASS. Then `make ci` and `go vet -tags=integration ./...`.

- [ ] **Step 6: Commit**

```bash
git add internal/instancesettings internal/httpapi cmd/api internal/metadatafill
git commit -m "feat(metadatafill): runtime toggle, infra row, category provider for every role, leader-gated worker

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 10: Admin endpoints, runs, audit, all OpenAPI prose (PR C10, core)

**Goal:** An admin can read status, test the connection (which also clears a pause), start a "fill existing videos" run and stop it. Every action is audited with closed codes, and the OpenAPI contract gets all of slice 1's prose in this one PR.

**Files:**
- Modify: `internal/metadatafill/service.go` (`Status`, `Test`, `StartRun`, `StopRun`), `internal/metadatafill/service_test.go`, `internal/metadatafill/fakes_test.go`
- Create: `internal/httpapi/admin_metadata_fill.go`, `internal/httpapi/admin_metadata_fill_test.go`
- Modify: `internal/httpapi/errors.go` (typed error, central switch next to `mtf` ~L203), `internal/httpapi/ratelimit.go` (sibling limiter after `mailTestRateLimit` L173-190), `internal/httpapi/server.go` (limiter field and option beside `mailTestLimit` L109/L476; routes beside L2225-2259; widen `metadataFillProvider`)
- Modify: `cmd/api/main.go` (construct the limiter exactly as the mail-test limiter is constructed; `grep -n 'WithMailTestRateLimit\|mailTestLimit' cmd/api/main.go`)
- Modify: `internal/observability/audit.go` (actions beside L111-127)
- Modify: `api/openapi.yaml` (4 operations and 2 schemas; the settings-key prose ~L14270-14280 gains `metadata_autofill_enabled`; the infrastructure key list ~L23521-23524 gains `metadata_autofill`)
- Modify: `internal/httpapi/openapi_contract_test.go` `fullRouteOptions()` (L62) to mount `WithMetadataFill`

**Contract:**

| Route | Success | Errors |
|---|---|---|
| `GET /api/v1/admin/metadata-fill/status` | 200 `MetadataFillStatus` | 401, 403 (the routes are mounted only when the service is wired, else 404) |
| `POST /api/v1/admin/metadata-fill/test` | 200 `{"status":"ok"}` | 409 `metadata_fill_not_configured`; 502 `metadata_fill_test_failed` with `reason` ∈ `auth`/`rate_limited`/`unavailable`/`bad_response`/`invalid_request`; 429 limiter |
| `POST /api/v1/admin/metadata-fill/runs` | 201 `MetadataFillRun` | 409 `metadata_fill_run_active`, 409 `metadata_fill_inactive` |
| `DELETE /api/v1/admin/metadata-fill/runs/current` | 204 | 404 |

```yaml
MetadataFillStatus:
  type: object
  required: [enabled, configured, model, counts, unjudged]
  properties:
    enabled: {type: boolean}
    configured: {type: boolean}
    model: {type: string, example: jev-1.13.0}
    paused_code: {type: string, nullable: true, enum: [auth, rate_limited, unavailable, not_configured]}
    counts:
      type: object
      required: [waiting, filled, not_confident, failed]
      properties:
        waiting: {type: integer}
        filled: {type: integer, description: Videos whose category or language still holds the automatic value.}
        not_confident: {type: integer}
        failed: {type: integer}
    unjudged: {type: integer, description: Eligible public videos never judged — the N on "Fill existing videos (N)".}
    run: {$ref: '#/components/schemas/MetadataFillRun', nullable: true}
MetadataFillRun:
  type: object
  required: [id, state, judged, filled, started_at]
  properties:
    id: {type: string, format: uuid}
    state: {type: string, enum: [running, stopped, done]}
    judged: {type: integer}
    filled: {type: integer}
    started_at: {type: string, format: date-time}
```

**Acceptance Criteria:**
- [ ] All four routes: anonymous gets 401 and a non-admin gets 403.
- [ ] Test sends one fixed state and a language-only question, never a real video. On success it clears any account pause.
- [ ] Start is atomic (Task 4's `StartMetadataFillRun`): a refused start requeues nothing, and a failed requeue leaves no run.
- [ ] The Test button has its own limiter (`"metadata-fill-test:"+userID`, audit reason `metadata_fill_test_rate_limited`) and never spends the mail probe's budget.
- [ ] Audit actions: `admin.metadata_fill.test`, `admin.metadata_fill.run_start` and `admin.metadata_fill.run_stop`. `Reason` is always a closed code, and `count` metadata carries requeued rows.
- [ ] `TestOpenAPIContract` passes in both directions.

**Verify:** `go test ./internal/httpapi/ ./internal/metadatafill/ -race -run 'MetadataFill'` → PASS. Then `make ci`.

**Steps:**

- [ ] **Step 1: Failing service tests** appended to `internal/metadatafill/service_test.go`:

```go
func TestStartRunRefusedWhenInactive(t *testing.T) {
	f := fixture(t)
	f.judge.configured = false
	if _, err := f.svc.StartRun(context.Background(), uuid.New()); !errors.Is(err, ErrInactive) {
		t.Fatalf("err = %v, want ErrInactive", err)
	}
}

func TestStartRunMapsTheUniqueViolation(t *testing.T) {
	f := fixture(t)
	f.repo.startErr = &pgconn.PgError{Code: "23505"}
	if _, err := f.svc.StartRun(context.Background(), uuid.New()); !errors.Is(err, ErrRunActive) {
		t.Fatalf("err = %v, want ErrRunActive", err)
	}
}

func TestTestSendsTheFixedProbeAndClearsThePause(t *testing.T) {
	f := fixture(t)
	_ = f.svc.account.Pause(context.Background(), judgment.CodeAuth)
	f.judge.next = []any{judgment.Result{Answers: map[string]judgment.Answer{QLanguage: {Pick: "en", Probabilities: map[string]float64{"en": 1}}}}}
	if err := f.svc.Test(context.Background()); err != nil {
		t.Fatal(err)
	}
	v := f.judge.lastState.(map[string]any)["video"].(map[string]any)
	if v["title"] != testProbeTitle || len(f.judge.lastQuestions) != 1 {
		t.Fatalf("probe = %v / %d questions", v, len(f.judge.lastQuestions))
	}
	if _, paused, _ := f.svc.account.Paused(context.Background()); paused {
		t.Fatal("a successful test must clear the pause")
	}
}
```

Add `errors` and `github.com/jackc/pgx/v5/pgconn` to the test imports. `fakeJudge` gains `lastState any`, `lastQuestions map[string]judgment.Question`; `fakeRepo` gains `startErr error` and implements `StartMetadataFillRun`, `CountMetadataJudgments` (returning a fixed row).

- [ ] **Step 2: Implement** in `internal/metadatafill/service.go`. Add these to `Repository`:
  - `StartMetadataFillRun(ctx, pgtype.UUID) (sqlcgen.StartMetadataFillRunRow, error)`
  - `CountMetadataJudgments(ctx, sqlcgen.CountMetadataJudgmentsParams) (sqlcgen.CountMetadataJudgmentsRow, error)`

  The `started_by` narg is a nullable uuid, so it is `pgtype.UUID` (§0.5, the same type as Task 4's test).

```go
var (
	ErrRunActive = errors.New("metadatafill: a run is already running")
	ErrInactive  = errors.New("metadatafill: not enabled or not configured")
	ErrNoRun     = errors.New("metadatafill: no running run")
)

const testProbeTitle = "Connection test"

// Test sends one fixed, harmless judgment — never a real video — and clears
// an account pause when it succeeds (an operator who just fixed the key
// should not wait out the 15-minute auth pause).
func (s *Service) Test(ctx context.Context) error {
	_, err := s.judge.Ask(ctx,
		map[string]any{"video": map[string]any{"title": testProbeTitle, "description": "A short check that the connection works."}},
		map[string]judgment.Question{QLanguage: {
			Instructions: "In which language is `video.title` written?",
			Options:      []judgment.Option{{Key: "en", Description: "English"}, {Key: Unclear}},
		}})
	if err != nil {
		return err
	}
	return s.account.ClearPause(ctx)
}

// StartRun creates the running run and requeues failed rows, atomically.
func (s *Service) StartRun(ctx context.Context, actor uuid.UUID) (sqlcgen.StartMetadataFillRunRow, error) {
	if !s.enabled() || !s.judge.Configured(ctx) {
		return sqlcgen.StartMetadataFillRunRow{}, ErrInactive
	}
	row, err := s.repo.StartMetadataFillRun(ctx, pgtype.UUID{Bytes: actor, Valid: true})
	if pgconv.IsUniqueViolation(err) {
		return sqlcgen.StartMetadataFillRunRow{}, ErrRunActive
	}
	return row, err
}

// StopRun flips the running run to stopped; the leader reads it every tick.
func (s *Service) StopRun(ctx context.Context) error {
	run, err := s.repo.GetRunningMetadataFillRun(ctx)
	if errors.Is(err, pgx.ErrNoRows) {
		return ErrNoRun
	}
	if err != nil {
		return err
	}
	_, err = s.repo.FinishMetadataFillRun(ctx, sqlcgen.FinishMetadataFillRunParams{ID: run.ID, State: "stopped"})
	return err
}

// Status is the admin card's read model.
type Status struct {
	Enabled, Configured bool
	Model               string
	PausedCode          judgment.Code
	Counts              sqlcgen.CountMetadataJudgmentsRow
	Unjudged            int64
	Run                 *sqlcgen.MetadataFillRun
}

func (s *Service) Status(ctx context.Context, model string) (Status, error) {
	st := Status{Enabled: s.enabled(), Configured: s.judge.Configured(ctx), Model: model}
	if code, paused, err := s.account.Paused(ctx); err != nil {
		return st, err
	} else if paused {
		st.PausedCode = code
	}
	var err error
	if st.Counts, err = s.repo.CountMetadataJudgments(ctx, sqlcgen.CountMetadataJudgmentsParams{
		CategoryBar: CategoryBar, LanguageBar: LanguageBar,
	}); err != nil {
		return st, err
	}
	if st.Unjudged, err = s.repo.CountUnjudgedEligibleVideos(ctx); err != nil {
		return st, err
	}
	if run, err := s.repo.GetRunningMetadataFillRun(ctx); err == nil {
		st.Run = &run
	} else if !errors.Is(err, pgx.ErrNoRows) {
		return st, err
	}
	return st, nil
}
```

Import `github.com/vidra/vidra-core/internal/pgconv` (its `IsUniqueViolation` is at `internal/pgconv/pgconv.go:115`).

- [ ] **Step 3: Failing HTTP tests** in `internal/httpapi/admin_metadata_fill_test.go`:

```go
package httpapi

import (
	"bytes"
	"context"
	"log/slog"
	"net/http"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/vidra/vidra-core/internal/auth"
	"github.com/vidra/vidra-core/internal/judgment"
	"github.com/vidra/vidra-core/internal/metadatafill"
	"github.com/vidra/vidra-core/internal/observability"
	"github.com/vidra/vidra-core/internal/store/sqlcgen"
)

type stubFill struct {
	enabled, configured bool
	testErr, startErr   error
	stopErr             error
}

func (s *stubFill) Enabled() bool                   { return s.enabled }
func (s *stubFill) Configured(context.Context) bool { return s.configured }
func (s *stubFill) Test(context.Context) error      { return s.testErr }
func (s *stubFill) StopRun(context.Context) error   { return s.stopErr }
func (s *stubFill) Status(context.Context, string) (metadatafill.Status, error) {
	return metadatafill.Status{Enabled: s.enabled, Configured: s.configured, Model: "jev-1.13.0"}, nil
}
func (s *stubFill) StartRun(context.Context, uuid.UUID) (sqlcgen.StartMetadataFillRunRow, error) {
	if s.startErr != nil {
		return sqlcgen.StartMetadataFillRunRow{}, s.startErr
	}
	return sqlcgen.StartMetadataFillRunRow{ID: uuid.New(), State: "running", CreatedAt: time.Now(), Requeued: 2}, nil
}

func fillServer(t *testing.T, fill *stubFill) (*Server, *bytes.Buffer, string, string) {
	t.Helper()
	issuer := auth.NewTokenIssuer("test-secret-test-secret-test-secret-0", "vidra", "vidra", 15*time.Minute)
	svc := auth.NewService(newAuthFakeRepo(), issuer, 720*time.Hour)
	srv := New(testConfig(), nil, nil, WithAuthService(svc, 15*time.Minute), WithMetadataFill(fill))
	var buf bytes.Buffer
	srv.logger = slog.New(slog.NewJSONHandler(&buf, nil))
	admin := registerAndToken(t, srv, `{"username":"ada","email":"ada@example.test","password":"supersecret"}`)
	user := registerAndToken(t, srv, `{"username":"bob","email":"bob@example.test","password":"supersecret"}`)
	return srv, &buf, admin, user
}

func TestMetadataFillRoutesAreAdminOnly(t *testing.T) {
	srv, _, _, user := fillServer(t, &stubFill{enabled: true, configured: true})
	for _, r := range [][2]string{
		{http.MethodGet, "/api/v1/admin/metadata-fill/status"},
		{http.MethodPost, "/api/v1/admin/metadata-fill/test"},
		{http.MethodPost, "/api/v1/admin/metadata-fill/runs"},
		{http.MethodDelete, "/api/v1/admin/metadata-fill/runs/current"},
	} {
		if rec := sendJSONAuth(srv, r[0], r[1], "", ""); rec.Code != http.StatusUnauthorized {
			t.Errorf("anon %s %s = %d, want 401", r[0], r[1], rec.Code)
		}
		if rec := sendJSONAuth(srv, r[0], r[1], "", user); rec.Code != http.StatusForbidden {
			t.Errorf("user %s %s = %d, want 403", r[0], r[1], rec.Code)
		}
	}
}

func TestMetadataFillTestOutcomes(t *testing.T) {
	cases := []struct {
		name   string
		fill   *stubFill
		status int
		code   string
		reason string
		result string
	}{
		{"ok", &stubFill{configured: true}, 200, "", "ok", observability.ResultSuccess},
		{"no key", &stubFill{configured: false}, 409, "metadata_fill_not_configured", "not_configured", observability.ResultFailure},
		{"rejected", &stubFill{configured: true, testErr: &judgment.Error{Code: judgment.CodeAuth}}, 502, "metadata_fill_test_failed", "auth", observability.ResultFailure},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			srv, buf, admin, _ := fillServer(t, tc.fill)
			rec := sendJSONAuth(srv, http.MethodPost, "/api/v1/admin/metadata-fill/test", "", admin)
			if rec.Code != tc.status || (tc.code != "" && !bytes.Contains(rec.Body.Bytes(), []byte(tc.code))) {
				t.Fatalf("= %d %s", rec.Code, rec.Body.String())
			}
			ev := findAudit(auditEvents(t, buf), observability.ActionAdminMetadataFillTest, tc.result)
			if ev == nil || ev["reason"] != tc.reason {
				t.Fatalf("audit = %v, want reason %q", ev, tc.reason)
			}
		})
	}
}

func TestMetadataFillRuns(t *testing.T) {
	fill := &stubFill{enabled: true, configured: true}
	srv, buf, admin, _ := fillServer(t, fill)
	if rec := sendJSONAuth(srv, http.MethodPost, "/api/v1/admin/metadata-fill/runs", "", admin); rec.Code != http.StatusCreated {
		t.Fatalf("start = %d %s", rec.Code, rec.Body.String())
	}
	if findAudit(auditEvents(t, buf), observability.ActionAdminMetadataFillRunStart, observability.ResultSuccess) == nil {
		t.Fatal("run start not audited")
	}
	fill.startErr = metadatafill.ErrRunActive
	if rec := sendJSONAuth(srv, http.MethodPost, "/api/v1/admin/metadata-fill/runs", "", admin); rec.Code != http.StatusConflict ||
		!bytes.Contains(rec.Body.Bytes(), []byte("metadata_fill_run_active")) {
		t.Fatalf("second start = %d %s", rec.Code, rec.Body.String())
	}
	if rec := sendJSONAuth(srv, http.MethodDelete, "/api/v1/admin/metadata-fill/runs/current", "", admin); rec.Code != http.StatusNoContent {
		t.Fatalf("stop = %d", rec.Code)
	}
	fill.stopErr = metadatafill.ErrNoRun
	if rec := sendJSONAuth(srv, http.MethodDelete, "/api/v1/admin/metadata-fill/runs/current", "", admin); rec.Code != http.StatusNotFound {
		t.Fatalf("stop with no run = %d", rec.Code)
	}
}
```

- [ ] **Step 4: Run them and watch them fail.** `go test ./internal/httpapi/ -run MetadataFill`. Expected: FAIL (the routes are missing).

- [ ] **Step 5: Implement.**

`internal/observability/audit.go`:

```go
	// ActionAdminMetadataFillTest: an admin probed the TypeSafe connection.
	// Reason is a closed code (ok / not_configured / a judgment code).
	ActionAdminMetadataFillTest = "admin.metadata_fill.test"
	// ActionAdminMetadataFillRunStart / Stop: the "fill existing videos" run.
	ActionAdminMetadataFillRunStart = "admin.metadata_fill.run_start"
	ActionAdminMetadataFillRunStop  = "admin.metadata_fill.run_stop"
```

`internal/httpapi/errors.go`: add the type, declare `var mfe *MetadataFillError` with the others, and add the case after `mtf`:

```go
// MetadataFillError renders with its own status and stable code. Reason is a
// closed judgment code (never upstream text) and rides in ErrorBody.Reason,
// the field the mail test's reason already uses.
type MetadataFillError struct {
	Status  int
	Code    string
	Message string
	Reason  string
}

func (e *MetadataFillError) Error() string { return e.Code }
```

```go
	case errors.As(err, &mfe):
		status, code, message = mfe.Status, mfe.Code, mfe.Message
		mailReason = mfe.Reason
```

Widen `ErrorBody.Reason`'s doc comment to name `metadata_fill_test_failed`.

`internal/httpapi/ratelimit.go`: after `mailTestRateLimit`:

```go
// metadataFillTestRateLimit throttles the TypeSafe connection probe per admin,
// with its OWN budget: pressing it must never spend the mail probe's.
func (s *Server) metadataFillTestRateLimit() echo.MiddlewareFunc {
	return s.limitBy(limitRule{
		resolve: func(c echo.Context) (*ratelimit.Limiter, string, bool) {
			if s.metadataFillTestLimit == nil {
				return nil, "", false
			}
			userID, _, ok := principalFromContext(c)
			if !ok {
				return nil, "", false
			}
			return s.metadataFillTestLimit, "metadata-fill-test:" + userID.String(), true
		},
		unavailable: "metadata fill test rate limiter unavailable, failing open",
		denied:      "you have tested the TypeSafe connection several times recently; wait before testing again",
		auditReason: "metadata_fill_test_rate_limited",
		auditActor: func(c echo.Context) string {
			userID, _, _ := principalFromContext(c)
			return userID.String()
		},
	})
}
```

In `server.go`, add the field `metadataFillTestLimit *ratelimit.Limiter` and an option `WithMetadataFillTestRateLimit(l *ratelimit.Limiter)` beside the mail one (L476). In `main.go`, construct the limiter exactly as the mail-test limiter is constructed, with the same budget (10 per hour per admin), and pass it in.

Widen `metadataFillProvider`:

```go
type metadataFillProvider interface {
	Enabled() bool
	Configured(ctx context.Context) bool
	Status(ctx context.Context, model string) (metadatafill.Status, error)
	Test(ctx context.Context) error
	StartRun(ctx context.Context, actor uuid.UUID) (sqlcgen.StartMetadataFillRunRow, error)
	StopRun(ctx context.Context) error
}
```

Task 9's `fakeFillFlags` must now satisfy it: add no-op methods to it.

Routes, beside the mail routes:

```go
	if s.metadatafillsvc != nil {
		adminOnly := []echo.MiddlewareFunc{s.requireAuth, s.requireRole(admin.RoleAdmin)}
		api.GET("/admin/metadata-fill/status", s.handleMetadataFillStatus, adminOnly...)
		api.POST("/admin/metadata-fill/test", s.handleMetadataFillTest, append(adminOnly, s.metadataFillTestRateLimit())...)
		api.POST("/admin/metadata-fill/runs", s.handleMetadataFillStartRun, adminOnly...)
		api.DELETE("/admin/metadata-fill/runs/current", s.handleMetadataFillStopRun, adminOnly...)
	}
```

`internal/httpapi/admin_metadata_fill.go`:

```go
package httpapi

import (
	"errors"
	"net/http"
	"strconv"
	"time"

	"github.com/labstack/echo/v4"

	"github.com/vidra/vidra-core/internal/audit"
	"github.com/vidra/vidra-core/internal/judgment"
	"github.com/vidra/vidra-core/internal/metadatafill"
	"github.com/vidra/vidra-core/internal/observability"
)

type metadataFillRunView struct {
	ID        string    `json:"id"`
	State     string    `json:"state"`
	Judged    int32     `json:"judged"`
	Filled    int32     `json:"filled"`
	StartedAt time.Time `json:"started_at"`
}

type metadataFillCountsView struct {
	Waiting      int64 `json:"waiting"`
	Filled       int64 `json:"filled"`
	NotConfident int64 `json:"not_confident"`
	Failed       int64 `json:"failed"`
}

type metadataFillStatusView struct {
	Enabled    bool                   `json:"enabled"`
	Configured bool                   `json:"configured"`
	Model      string                 `json:"model"`
	PausedCode *string                `json:"paused_code"`
	Counts     metadataFillCountsView `json:"counts"`
	Unjudged   int64                  `json:"unjudged"`
	Run        *metadataFillRunView   `json:"run"`
}

func (s *Server) handleMetadataFillStatus(c echo.Context) error {
	st, err := s.metadatafillsvc.Status(c.Request().Context(), s.cfg.TypeSafeModel)
	if err != nil {
		return err
	}
	v := metadataFillStatusView{
		Enabled: st.Enabled, Configured: st.Configured, Model: st.Model, Unjudged: st.Unjudged,
		Counts: metadataFillCountsView{Waiting: st.Counts.Waiting, Filled: st.Counts.Filled,
			NotConfident: st.Counts.NotConfident, Failed: st.Counts.Failed},
	}
	if st.PausedCode != "" {
		code := string(st.PausedCode)
		v.PausedCode = &code
	}
	if r := st.Run; r != nil {
		v.Run = &metadataFillRunView{ID: r.ID.String(), State: r.State, Judged: r.Judged, Filled: r.Filled, StartedAt: r.CreatedAt}
	}
	return c.JSON(http.StatusOK, v)
}

func (s *Server) handleMetadataFillTest(c echo.Context) error {
	callerID, _, err := mustPrincipal(c)
	if err != nil {
		return err
	}
	if !s.metadatafillsvc.Configured(c.Request().Context()) {
		s.audit(c, observability.ActionAdminMetadataFillTest, observability.ResultFailure, callerID.String(), "not_configured")
		return &MetadataFillError{Status: http.StatusConflict, Code: "metadata_fill_not_configured",
			Message: "no TypeSafe API key is set. Set TYPESAFE_API_KEY in the server's env file"}
	}
	if err := s.metadatafillsvc.Test(c.Request().Context()); err != nil {
		code := string(judgment.CodeOf(err))
		if code == "" {
			code = string(judgment.CodeUnavailable)
		}
		s.audit(c, observability.ActionAdminMetadataFillTest, observability.ResultFailure, callerID.String(), code)
		return &MetadataFillError{Status: http.StatusBadGateway, Code: "metadata_fill_test_failed",
			Message: "TypeSafe did not answer the test judgment", Reason: code}
	}
	s.audit(c, observability.ActionAdminMetadataFillTest, observability.ResultSuccess, callerID.String(), "ok")
	return c.JSON(http.StatusOK, map[string]string{"status": "ok"})
}

func (s *Server) handleMetadataFillStartRun(c echo.Context) error {
	callerID, _, err := mustPrincipal(c)
	if err != nil {
		return err
	}
	run, err := s.metadatafillsvc.StartRun(c.Request().Context(), callerID)
	switch {
	case errors.Is(err, metadatafill.ErrRunActive):
		s.audit(c, observability.ActionAdminMetadataFillRunStart, observability.ResultFailure, callerID.String(), "run_active")
		return &MetadataFillError{Status: http.StatusConflict, Code: "metadata_fill_run_active",
			Message: "a fill run is already running; stop it first or wait for it to finish"}
	case errors.Is(err, metadatafill.ErrInactive):
		s.audit(c, observability.ActionAdminMetadataFillRunStart, observability.ResultFailure, callerID.String(), "inactive")
		return &MetadataFillError{Status: http.StatusConflict, Code: "metadata_fill_inactive",
			Message: "switch automatic category and language on and set a TypeSafe key before filling existing videos"}
	case err != nil:
		return err
	}
	s.auditEvent(c, audit.Event{
		Action: observability.ActionAdminMetadataFillRunStart, Result: observability.ResultSuccess,
		ActorID: callerID.String(), Reason: "started",
		Metadata: []audit.MetadataField{{Key: "count", Value: strconv.FormatInt(run.Requeued, 10)}},
	})
	return c.JSON(http.StatusCreated, metadataFillRunView{ID: run.ID.String(), State: run.State,
		Judged: run.Judged, Filled: run.Filled, StartedAt: run.CreatedAt})
}

func (s *Server) handleMetadataFillStopRun(c echo.Context) error {
	callerID, _, err := mustPrincipal(c)
	if err != nil {
		return err
	}
	err = s.metadatafillsvc.StopRun(c.Request().Context())
	if errors.Is(err, metadatafill.ErrNoRun) {
		s.audit(c, observability.ActionAdminMetadataFillRunStop, observability.ResultFailure, callerID.String(), "no_run")
		return echo.NewHTTPError(http.StatusNotFound, "no fill run is running")
	}
	if err != nil {
		return err
	}
	s.audit(c, observability.ActionAdminMetadataFillRunStop, observability.ResultSuccess, callerID.String(), "stopped")
	return c.NoContent(http.StatusNoContent)
}
```

`api/openapi.yaml`: add the four operations, modelled on `/api/v1/admin/mail/test`, the two schemas, the `reason` enum for `metadata_fill_test_failed` (documented the way `mail_test_failed` documents its reason), and the two prose-list additions. In `openapi_contract_test.go` `fullRouteOptions()`, add `WithMetadataFill(&stubFill{})`.

- [ ] **Step 6: Run.** `go test ./internal/httpapi/ ./internal/metadatafill/ -race` → PASS. Then `make ci`, including `openapi-verify`.

- [ ] **Step 7: Commit**, then run **Task 12** straight after the merge.

```bash
git add internal cmd/api api/openapi.yaml
git commit -m "feat(httpapi): admin status, test and fill-run endpoints for metadata auto-fill

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 11: `auto_filled` on the video view (PR C11, core)

**Goal:** `GET /api/v1/videos/{id}` returns `auto_filled` to anyone who may manage the video (owner, channel editor, staff) and to no one else.

**Files:**
- Modify: `internal/httpapi/videos.go` (`videoView` beside `Category`/`Language` L230-233; `respondVideo` L585-628)
- Modify: `api/openapi.yaml` `components.schemas.Video` (~L18213; model the description on `blocked`, ~L18333-18350)
- Test: `internal/httpapi/videos_auto_filled_test.go` (new)

**Acceptance Criteria:**
- [ ] The owner, a channel editor (per `canManageChannelContent`, `channel_members.go:23`, the check `canManageVideo` makes, without its re-fetch) and staff (`isStaff`) get `auto_filled: ["category"]` when that field holds the worker's value.
- [ ] An anonymous caller or an unrelated user never sees the key, not even as an empty array.
- [ ] An error from `AutoFilled` omits the field and never fails the read.

**Verify:** `go test ./internal/httpapi/ -race -run AutoFilled` → PASS. Then `make ci`.

**Steps:**

- [ ] **Step 1: Failing test.** `s.videosvc` is the concrete `*video.Service` (`server.go:131`), so seed the **repo**: `videoFakeRepo.autoFilled[id] = [2]bool{true, false}` (added in Task 5). Build the server the way the existing video-detail tests do (`grep -n 'videoFakeRepo{' internal/httpapi/videos_test.go`, near `:1497`). GET as the owner, as an unrelated user and anonymously, and decode each body into `map[string]any`:

```go
	if got := ownerBody["auto_filled"]; !reflect.DeepEqual(got, []any{"category"}) {
		t.Fatalf("owner auto_filled = %v", got)
	}
	for name, body := range map[string]map[string]any{"anon": anonBody, "stranger": strangerBody} {
		if _, present := body["auto_filled"]; present {
			t.Fatalf("auto_filled leaked to %s", name)
		}
	}
```

Add a second test where the repo's `GetVideoAutoFilled` returns an error: the owner gets 200 with no `auto_filled` key.

- [ ] **Step 2: Run it and watch it fail.** Expected: FAIL (the owner body lacks the key).

- [ ] **Step 3: Implement.** In `videoView`, beside `Language`:

```go
	// AutoFilled lists which of category/language hold a value the Jev
	// auto-fill worker chose and no human has set since. Managers and staff only.
	AutoFilled []string `json:"auto_filled,omitempty"`
```

In `respondVideo`, before `s.attachVideoIPFS(...)`:

```go
	if viewerID, role, ok := principalFromContext(c); ok {
		ctx := c.Request().Context()
		// v is already loaded: owner and staff cost nothing; only a third
		// party pays the one channel-membership query (no GetByID re-fetch,
		// which canManageVideo would do).
		may := isStaff(role) || v.OwnerID == viewerID || s.canManageChannelContent(ctx, viewerID, v.ChannelID)
		if may {
			if af, err := s.videosvc.AutoFilled(ctx, id); err == nil && len(af) > 0 {
				view.AutoFilled = af
			}
		}
	}
```

In `api/openapi.yaml` `Video.properties`:

```yaml
        auto_filled:
          type: array
          items: {type: string, enum: [category, language]}
          description: >-
            Present only for callers who may manage the video (owner, channel
            editor, staff) and only when non-empty. Fields whose current value
            was chosen automatically (TypeSafe Jev auto-fill) and that no person
            has set since. Studio shows a "Set automatically" note.
```

- [ ] **Step 4: Run.** `go test ./internal/httpapi/ -race` → PASS. Then `make ci`.

- [ ] **Step 5: Commit**, then run **Task 12** straight after the merge.

```bash
git add internal/httpapi api/openapi.yaml
git commit -m "feat(httpapi): auto_filled on the video view for managers and staff

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 12: Contract sync, a codegen-only vidra-user PR (S1, S2, S3)

**Goal:** Keep vidra-user's required `contract-ci` green after each core PR that changes `api/openapi.yaml` (C10, C11, C14).

**When:** Immediately after C10, C11 or C14 merges on core `main`, and before any other vidra-user PR merges.

**Files:** `lib/api/generated.ts` only. Also `lib/api/types.ts` if a newly exported schema needs an alias in the same PR; the feature PRs add aliases otherwise.

**Acceptance Criteria:**
- [ ] `lib/api/generated.ts` equals codegen output from core `main`'s spec at the merge SHA, which the PR body names.
- [ ] `npx tsc --noEmit` passes: the new optional fields break no existing code.
- [ ] The PR's `contract-ci` is green.

**Verify:** In the vidra-user worktree:

```bash
# The spec at the MERGE commit, not the raw CDN (it serves stale content for
# minutes after a push, which would regenerate from the old spec):
SHA=$(gh api repos/yegamble/vidra-core/commits/main -q .sha)
gh api "repos/yegamble/vidra-core/contents/api/openapi.yaml?ref=$SHA" -H 'Accept: application/vnd.github.raw' > /tmp/openapi.yaml
OPENAPI_PATH=/tmp/openapi.yaml npm run codegen
git diff --stat -- lib/api/generated.ts     # non-empty: the core change
npx tsc --noEmit && npm run lint && npm run test
```

**Steps:**

- [ ] **Step 1:** Run the Verify block.
- [ ] **Step 2:** Commit and open a PR titled `[claude] api: regenerate types for <core PR #>`. The body links the core PR and states "codegen only".

```bash
git add lib/api/generated.ts
git commit -m "chore(api): regenerate types for vidra-core #<n>

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 3:** Merge once CI is green. Only then does other vidra-user work continue.

---

## Task 13: `api evaluate-metadata` (PR C12, core)

**Goal:** A read-only subcommand that measures Jev against human-labelled public videos, so the bars are set from data. It writes nothing.

**Files:**
- Create: `cmd/api/evaluate_metadata.go`, `cmd/api/evaluate_metadata_test.go`, `internal/metadatafill/evaluate.go`, `internal/metadatafill/evaluate_test.go`
- Modify: `cmd/api/main.go` (dispatch switch L118-136 and its usage string)

**Behaviour:** `api evaluate-metadata [--sample 300] [--seed vidra] [--json]`
- Loads config (`config.Load()`) and opens the store the way `verify-blobs` does (`cmd/api/verify_blobs.go:73`).
- Requires a key (`TYPESAFE_API_KEY` until Task 15; from then on `judgment.NewAccount(db.Queries(), time.Now, judgment.WithSealedKey(cipher, cfg.TypeSafeAPIKey)).Key`, the resolver the worker uses). With no key it exits 1 with `evaluate-metadata: no TypeSafe key`.
- Samples with `SampleLabelledVideosForEvaluation`. It skips only the **field** whose human value is not in the live vocabulary, so a dangling category never costs the language sample. It prints how many sampled videos carry a category id missing from the live list, the dangling-id count for §0.2.10.
- Asks both questions for every sample, as if both fields were empty, sequentially with a 5 s per-call timeout.
- Prints, per field: n, coverage (share at or over the bar), agreement among covered, agreement per probability band (`<0.5`, `0.5–0.7`, `0.7–0.8`, `0.8–0.9`, `0.9–0.95`, `≥0.95`), the count of `none_of_these`/`unclear`, and the 10 most-confused `human→jev` pairs.
- Exit codes: 0 when the report printed, 1 on usage, config or no-key errors, 2 when more than 10% of calls failed (the report still prints).

**Acceptance Criteria:**
- [ ] `Evaluate(samples, answers)` is pure and tested: band assignment, coverage at the bar, agreement, confusion ordering.
- [ ] `evaluate-metadata` appears in the usage line, and unknown flags or a positional argument exit 1.
- [ ] No `UPDATE`/`INSERT` is reachable. The subcommand's repository interface contains only `SampleLabelledVideosForEvaluation` and `ListVideoTags`.

**Verify:** `go test ./cmd/api/ ./internal/metadatafill/ -race -run 'Evaluate'` → PASS.

**Steps:**

- [ ] **Step 1: Failing test** `internal/metadatafill/evaluate_test.go`

```go
package metadatafill

import "testing"

func TestEvaluateBandsCoverageAndConfusion(t *testing.T) {
	obs := []Observation{
		{Field: QLanguage, Human: "en", Pick: "en", Prob: 0.99},
		{Field: QLanguage, Human: "fr", Pick: "en", Prob: 0.95},
		{Field: QLanguage, Human: "de", Pick: "de", Prob: 0.60},
		{Field: QLanguage, Human: "en", Pick: Unclear, Prob: 0.80},
	}
	r := Evaluate(obs)[QLanguage]
	if r.N != 4 || r.NoMatch != 1 {
		t.Fatalf("n=%d nomatch=%d", r.N, r.NoMatch)
	}
	if r.Covered != 2 || r.CoveredAgree != 1 {
		t.Fatalf("covered=%d agree=%d, want 2/1 at the 0.90 bar", r.Covered, r.CoveredAgree)
	}
	if b := r.Bands["≥0.95"]; b.N != 2 || b.Agree != 1 {
		t.Fatalf("top band = %+v", b)
	}
	if len(r.Confused) == 0 || r.Confused[0].Human != "fr" || r.Confused[0].Pick != "en" {
		t.Fatalf("confused = %+v", r.Confused)
	}
}
```

- [ ] **Step 2: Implement `internal/metadatafill/evaluate.go`**

```go
package metadatafill

import "sort"

// Observation is one field of one sampled video: the human value and Jev's
// pick (a category id or language code; NoneOfThese/Unclear for no match).
type Observation struct {
	Field, Human, Pick string
	Prob               float64
}

// Band is agreement within one probability band.
type Band struct{ N, Agree int }

// Pair is a human→jev disagreement and how often it happened.
type Pair struct {
	Human, Pick string
	Count       int
}

// FieldReport summarises one field.
type FieldReport struct {
	N, NoMatch, Covered, CoveredAgree int
	Bar                               float64
	Bands                             map[string]Band
	Confused                          []Pair
}

var bandEdges = []struct {
	label string
	min   float64
}{{"≥0.95", 0.95}, {"0.9–0.95", 0.9}, {"0.8–0.9", 0.8}, {"0.7–0.8", 0.7}, {"0.5–0.7", 0.5}, {"<0.5", 0}}

// Evaluate aggregates observations per field. Agreement is a FLOOR on
// accuracy: creator-chosen categories are themselves noisy.
func Evaluate(obs []Observation) map[string]*FieldReport {
	out := map[string]*FieldReport{}
	pairs := map[string]map[[2]string]int{}
	for _, o := range obs {
		r, ok := out[o.Field]
		if !ok {
			bar := CategoryBar
			if o.Field == QLanguage {
				bar = LanguageBar
			}
			r = &FieldReport{Bar: bar, Bands: map[string]Band{}}
			out[o.Field] = r
			pairs[o.Field] = map[[2]string]int{}
		}
		r.N++
		if o.Pick == NoneOfThese || o.Pick == Unclear {
			r.NoMatch++
			continue
		}
		agree := o.Pick == o.Human
		for _, e := range bandEdges {
			if o.Prob >= e.min {
				b := r.Bands[e.label]
				b.N++
				if agree {
					b.Agree++
				}
				r.Bands[e.label] = b
				break
			}
		}
		if o.Prob >= r.Bar {
			r.Covered++
			if agree {
				r.CoveredAgree++
			}
		}
		if !agree {
			pairs[o.Field][[2]string{o.Human, o.Pick}]++
		}
	}
	for f, r := range out {
		for k, n := range pairs[f] {
			r.Confused = append(r.Confused, Pair{Human: k[0], Pick: k[1], Count: n})
		}
		sort.Slice(r.Confused, func(i, j int) bool {
			if r.Confused[i].Count != r.Confused[j].Count {
				return r.Confused[i].Count > r.Confused[j].Count
			}
			return r.Confused[i].Human+r.Confused[i].Pick < r.Confused[j].Human+r.Confused[j].Pick
		})
		if len(r.Confused) > 10 {
			r.Confused = r.Confused[:10]
		}
	}
	return out
}
```

To read picks for the evaluator, add this to `request.go`:

```go
// CategoryIDForKey maps an answered option key back to its category id.
func (r Request) CategoryIDForKey(key string) (string, bool) { id, ok := r.categoryByKey[key]; return id, ok }
```

- [ ] **Step 3: Failing CLI tests** `cmd/api/evaluate_metadata_test.go`. Model them on `verify_blobs_test.go:15,103`:

```go
package main

import (
	"bytes"
	"strings"
	"testing"
)

func TestEvaluateMetadataUsageErrors(t *testing.T) {
	for _, args := range [][]string{{"--nope"}, {"extra"}} {
		var out, errb bytes.Buffer
		if code := runEvaluateMetadata(args, &out, &errb); code != 1 {
			t.Errorf("%v exit = %d, want 1", args, code)
		}
	}
}

func TestEvaluateMetadataIsInTheUsageLine(t *testing.T) {
	if !strings.Contains(topLevelUsage(), "evaluate-metadata") {
		t.Fatal("usage line does not name evaluate-metadata")
	}
}
```

If `main.go` builds the usage string inline, extract it as `func topLevelUsage() string` in this PR so it can be tested; the `verify-blobs` test's approach is the fallback.

- [ ] **Step 4: Implement `cmd/api/evaluate_metadata.go`**, following the `verify_blobs.go` skeleton: a `flag.NewFlagSet("evaluate-metadata", flag.ContinueOnError)` with `--sample` (int, default 300, max 2,000), `--seed` (string, default `vidra`) and `--json` (bool); `signal.NotifyContext`; `config.Load()`; `store.New`; `db.Queries()`.
  - For each sample, build `metadatafill.BuildRequest(Subject{..., CategoryEmpty: true, LanguageEmpty: true}, video.CategoryOptions(), video.Languages)` and call `judgment.New(cfg.TypeSafeEndpoint, cfg.TypeSafeModel, keyFunc).Ask`.
  - For category, map `res.Answers[QCategory].Pick` through `req.CategoryIDForKey`, with `NoneOfThese` passing through. The language pick is the code.
  - Collect `Observation`s and print `metadatafill.Evaluate(obs)` either as a table (human) or as JSON.
  - The header line states the model, sample size, seed and date. The footer states: "Agreement with creator-chosen values is a floor on accuracy, not ground truth. This run wrote nothing."
  - Add `case "evaluate-metadata": os.Exit(runEvaluateMetadata(os.Args[2:], os.Stdout, os.Stderr))` to the dispatch, and add `evaluateMetadataUsage` to the usage string.
  - `video.CategoryOptions()` falls back to the built-ins unless the settings provider is registered. To evaluate an instance with a custom taxonomy, load `instancesettings` and call `video.SetCategoryProvider(svc.Categories)` the way `server.go:944` does. Do that here: construct the settings service from the store and `Load` it.

- [ ] **Step 5: Run them.** `go test ./cmd/api/ ./internal/metadatafill/ -race -run Evaluate` → PASS. Then `make ci`. Also run it once locally against the dev stack with the real key, `TYPESAFE_API_KEY=… go run ./cmd/api evaluate-metadata --sample 20`, and paste the header and footer lines, not the key, into the PR.

- [ ] **Step 6: Commit**

```bash
git add cmd/api internal/metadatafill
git commit -m "feat(api): evaluate-metadata subcommand measures Jev against human labels

Read-only: samples public videos that already carry human category and
language, asks Jev, and reports agreement per probability band.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 14: `jev-stub` compose profile (PR C13, core)

**Goal:** A deterministic stand-in for `/v1/systemone` that backed e2e can start, so CI proves the whole chain with no real key.

**Files:**
- Create: `scripts/dev/jevstub.py`, `scripts/dev/jevstub_test.py`
- Modify: `docker-compose.yml` (a new profile-gated service near `whisper`, L880-897)

**Stub contract:** It requires `Authorization: Bearer stub` (anything else gets 401). For each `choice` question it picks, in order: the first option key found case-insensitively in `state.video.title`; then `en` if offered; then the last option, which is `none_of_these` or `unclear`. The pick gets 0.97 and the rest share 0.03. It returns the documented response shape with `model` echoed.

**Acceptance Criteria:**
- [ ] `python3 -m unittest discover -s scripts/dev -p 'jevstub_test.py'` passes: title match, `en` fallback, no-match, and 401.
- [ ] No core CI lane runs Python tests; the PR body says the stub test was run locally and pastes its output.
- [ ] `docker compose --profile jev-stub config` renders a service `jev-stub` on the compose network with **no published port**.

**Verify:** `python3 -m unittest discover -s scripts/dev -p 'jevstub_test.py' && docker compose --profile jev-stub config | grep -A3 'jev-stub:'`.

**Steps:**

- [ ] **Step 1: Failing test** `scripts/dev/jevstub_test.py`

```python
import json
import threading
import unittest
import urllib.request
from http.server import HTTPServer

import jevstub


class JevStubTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = HTTPServer(("127.0.0.1", 0), jevstub.Handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.srv.server_port}/v1/systemone"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def ask(self, title, key="stub"):
        body = {"model": "jev-1.13.0", "state": {"video": {"title": title}},
                "questions": {
                    "category": {"type": "choice", "instructions": "?", "criteria": {"Music": None, "Films": None, "none_of_these": None}},
                    "language": {"type": "choice", "instructions": "?", "criteria": {"fr": None, "en": None, "unclear": None}}}}
        req = urllib.request.Request(self.url, data=json.dumps(body).encode(),
                                     headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req) as r:
            return json.load(r)

    def test_title_match_and_en_fallback(self):
        a = self.ask("Live music night")["answers"]
        self.assertEqual(a["category"]["choice"], "Music")
        self.assertEqual(a["category"]["probabilities"]["Music"], 0.97)
        self.assertEqual(a["language"]["choice"], "en")

    def test_no_match(self):
        self.assertEqual(self.ask("zzz")["answers"]["category"]["choice"], "none_of_these")

    def test_bad_key(self):
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.ask("x", key="nope")
        self.assertEqual(cm.exception.code, 401)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Implement `scripts/dev/jevstub.py`**

```python
"""Deterministic stand-in for TypeSafe's POST /v1/systemone (backed e2e only).

Never deployed: it is started by the `jev-stub` compose profile, which no
production overlay enables. Picks are a function of the title so a spec can
predict them; see scripts/dev/jevstub_test.py.
"""
import json
from http.server import BaseHTTPRequestHandler, HTTPServer


def pick(title, options):
    t = (title or "").lower()
    for o in options:
        if o.lower() in t and o not in ("none_of_these", "unclear"):
            return o
    if "en" in options:
        return "en"
    return options[-1]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_POST(self):
        if self.path != "/v1/systemone":
            self.send_error(404)
            return
        if self.headers.get("Authorization") != "Bearer stub":
            self.send_response(401)
            self.end_headers()
            return
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        title = ((body.get("state") or {}).get("video") or {}).get("title", "")
        answers = {}
        for qid, q in (body.get("questions") or {}).items():
            opts = list((q.get("criteria") or {}).keys())
            choice = pick(title, opts)
            rest = 0.03 / max(len(opts) - 1, 1)
            probs = {o: (0.97 if o == choice else rest) for o in opts}
            answers[qid] = {"type": "choice", "choice": choice, "probabilities": probs, "confidence": 0.95}
        out = json.dumps({"model": body.get("model", "jev-stub"), "answers": answers,
                          "usage": {"input_tokens": 1, "output_tokens": 1}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
```

- [ ] **Step 3: Compose service**, beside `whisper`:

```yaml
  # Deterministic TypeSafe stand-in for backed e2e ONLY (profile jev-stub).
  # No published port: the api reaches it as http://jev-stub:8080 with
  # TYPESAFE_API_KEY=stub. Never enable this profile in production.
  jev-stub:
    image: python:3.12-alpine
    profiles: ["jev-stub"]
    command: ["python", "/stub/jevstub.py"]
    volumes:
      - ./scripts/dev/jevstub.py:/stub/jevstub.py:ro
    restart: "no"
```

Pin the image by digest if the file's other third-party images are pinned (`grep -n 'image:' docker-compose.yml`). Match the house practice.

- [ ] **Step 4: Run the Verify commands.** They pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/dev/jevstub.py scripts/dev/jevstub_test.py docker-compose.yml
git commit -m "test(compose): jev-stub profile, a deterministic TypeSafe stand-in for backed e2e

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 15: Sealed key setting (PR C14, core)

**Goal:** The admin can set or clear the TypeSafe key in the panel with no restart. It is stored sealed or not at all, in the account-level `typesafe_state` row, and it wins over `TYPESAFE_API_KEY`.

**Files:**
- Modify: `internal/judgment/account.go` (key methods), `internal/judgment/account_test.go`
- Modify: `internal/store/queries/metadata_fill.sql` (two queries; the column already exists from 0152), then `make sqlc`
- Modify: `internal/metadatafill/service.go` (`Status` gains the key source and status)
- Modify: `internal/httpapi/admin_metadata_fill.go`, `internal/httpapi/server.go` (route; provider gains key methods), `internal/observability/audit.go`, `api/openapi.yaml`
- Modify: `cmd/api/main.go` (pass the existing `secretbox` cipher built at L449-458 into `judgment.NewAccount`; replace the static `KeyFunc` with `typesafeAccount.Key`; the evaluator in Task 13 uses the same)
- Modify: `internal/setup/secrets.go:85-86` (the `MFA_KEY_KEK` rotation text)

**Contract:** `PUT /api/v1/admin/metadata-fill/key` with body `{"api_key":"<value>"}` replaces the key, and `{"api_key":""}` clears it. The response is 204. Errors: 400 for a malformed body; 409 `metadata_fill_secrets_key_missing` when there is no KEK; 422 when `api_key` is absent. `MetadataFillStatus` gains `key_source: admin | env | none` and `key_status: ok | undecryptable | none`. The key is never returned.

**Acceptance Criteria:**
- [ ] Resolution order: a sealed admin key that opens, then `TYPESAFE_API_KEY`, then "". An undecryptable sealed value is reported, and resolution falls back to env.
- [ ] A **database error** reading the key resolves to "" for this call. The Task 8 tick then idles and never moves the cutoff; no global state changes on a read error.
- [ ] With a nil cipher, a non-empty `PUT` gets 409 and stores nothing. Clearing works without a cipher.
- [ ] Audit `admin.metadata_fill.key_update` records `secret_changed=true` and `Reason` `set` or `cleared`. The key string never appears in a response, log or audit record (the test greps the captured log buffer).
- [ ] The key is read per call: a key saved in the panel is used by the next tick.
- [ ] `internal/setup/secrets.go` states that rotating `MFA_KEY_KEK` makes TOTP secrets, the stored mail credential and the stored TypeSafe key undecryptable.

**Verify:** `go test ./internal/judgment/ ./internal/httpapi/ -race -run 'Key|MetadataFill|Account'` → PASS. Then `make ci`.

**Steps:**

- [ ] **Step 1: Queries** (append to `metadata_fill.sql`, then `make sqlc`):

```sql
-- name: GetTypeSafeSealedKey :one
SELECT api_key_sealed FROM typesafe_state WHERE singleton;

-- name: SetTypeSafeSealedKey :exec
UPDATE typesafe_state SET api_key_sealed = sqlc.narg('api_key_sealed'), updated_at = now() WHERE singleton;
```

`GetTypeSafeSealedKey` returns `*string` (§0.5).

- [ ] **Step 2: Failing tests** appended to `internal/judgment/account_test.go`. Extend `fakeAccountRepo` with `sealed *string` and `readErr error`, and implement both new methods on it:

```go
func testCipher(t *testing.T) *secretbox.Cipher {
	t.Helper()
	c, err := secretbox.NewCipher(make([]byte, 32))
	if err != nil {
		t.Fatal(err)
	}
	return c
}

func TestKeyResolutionOrderAndLiveness(t *testing.T) {
	repo := &fakeAccountRepo{}
	acct := NewAccount(repo, time.Now, WithSealedKey(testCipher(t), "env-key"))
	ctx := context.Background()
	if got, src := acct.ResolveKey(ctx); got != "env-key" || src != KeySourceEnv {
		t.Fatalf("env fallback = %q/%s", got, src)
	}
	if err := acct.SetKey(ctx, "admin-key"); err != nil {
		t.Fatal(err)
	}
	if got, src := acct.ResolveKey(ctx); got != "admin-key" || src != KeySourceAdmin {
		t.Fatalf("admin key must win, read per call: %q/%s", got, src)
	}
	if repo.sealed == nil || *repo.sealed == "admin-key" || !strings.HasPrefix(*repo.sealed, "enc:") {
		t.Fatal("key stored in the clear")
	}
	if err := acct.SetKey(ctx, ""); err != nil || repo.sealed != nil {
		t.Fatalf("clear: err=%v sealed=%v", err, repo.sealed)
	}
}

func TestKeyRefusedWithoutCipher(t *testing.T) {
	acct := NewAccount(&fakeAccountRepo{}, time.Now, WithSealedKey(nil, ""))
	if err := acct.SetKey(context.Background(), "x"); !errors.Is(err, ErrSecretsKeyMissing) {
		t.Fatalf("err = %v, want ErrSecretsKeyMissing", err)
	}
	if err := acct.SetKey(context.Background(), ""); err != nil {
		t.Fatalf("clearing must work without a cipher: %v", err)
	}
}

func TestUndecryptableAndReadErrors(t *testing.T) {
	bad := "enc:not-valid"
	acct := NewAccount(&fakeAccountRepo{sealed: &bad}, time.Now, WithSealedKey(testCipher(t), "env-key"))
	if got, _ := acct.ResolveKey(context.Background()); got != "env-key" {
		t.Fatalf("got %q, want env fallback", got)
	}
	if acct.KeyStatus(context.Background()) != KeyStatusUndecryptable {
		t.Fatal("undecryptable not reported")
	}
	broken := NewAccount(&fakeAccountRepo{readErr: errors.New("db down")}, time.Now, WithSealedKey(testCipher(t), "env-key"))
	if got, _ := broken.ResolveKey(context.Background()); got != "env-key" {
		t.Fatalf("a read error must fall back to env for this call, got %q", got)
	}
}
```

Add `errors`, `strings` and `github.com/vidra/vidra-core/internal/secretbox` to the imports.

- [ ] **Step 3: Implement** in `internal/judgment/account.go`:

```go
// ErrSecretsKeyMissing: no KEK, so a key cannot be stored sealed and will not
// be stored in the clear. Same rule as mailconfig.ErrSecretsKeyMissing.
var ErrSecretsKeyMissing = errors.New("judgment: no key-encryption key")

type KeySource string
type KeyStatus string

const (
	KeySourceAdmin KeySource = "admin"
	KeySourceEnv   KeySource = "env"
	KeySourceNone  KeySource = "none"

	KeyStatusOK            KeyStatus = "ok"
	KeyStatusUndecryptable KeyStatus = "undecryptable"
	KeyStatusNone          KeyStatus = "none"
)

// KeyRepository is the sealed-key half of typesafe_state.
type KeyRepository interface {
	GetTypeSafeSealedKey(ctx context.Context) (*string, error)
	SetTypeSafeSealedKey(ctx context.Context, sealed *string) error
}

// AccountOption configures an Account.
type AccountOption func(*Account)

// WithSealedKey enables the admin-panel key (cipher may be nil: then a key is
// refused, never stored in the clear) with env as the fallback.
func WithSealedKey(cipher *secretbox.Cipher, env string) AccountOption {
	return func(a *Account) { a.cipher, a.env, a.sealedKeys = cipher, strings.TrimSpace(env), true }
}
```

Change the `Account` struct and its constructor:

```go
type Account struct {
	repo       AccountRepository
	now        func() time.Time
	cipher     *secretbox.Cipher
	env        string
	sealedKeys bool
}

func NewAccount(repo AccountRepository, now func() time.Time, opts ...AccountOption) *Account {
	a := &Account{repo: repo, now: now}
	for _, o := range opts {
		o(a)
	}
	return a
}
```

Widen `AccountRepository` to embed `KeyRepository`. `*sqlcgen.Queries` satisfies both. Then add:

```go
func (a *Account) adminKey(ctx context.Context) (string, KeyStatus) {
	if !a.sealedKeys {
		return "", KeyStatusNone
	}
	sealed, err := a.repo.GetTypeSafeSealedKey(ctx)
	if err != nil || sealed == nil || *sealed == "" {
		return "", KeyStatusNone
	}
	if a.cipher == nil {
		return "", KeyStatusUndecryptable
	}
	plain, err := a.cipher.Open(*sealed)
	if err != nil {
		return "", KeyStatusUndecryptable
	}
	return string(plain), KeyStatusOK
}

// ResolveKey: sealed admin key, else env, else "". Read per call.
func (a *Account) ResolveKey(ctx context.Context) (string, KeySource) {
	if v, st := a.adminKey(ctx); st == KeyStatusOK && v != "" {
		return v, KeySourceAdmin
	}
	if a.env != "" {
		return a.env, KeySourceEnv
	}
	return "", KeySourceNone
}

// Key adapts ResolveKey to KeyFunc.
func (a *Account) Key(ctx context.Context) string { v, _ := a.ResolveKey(ctx); return v }

// KeyStatus reports the admin key's health (for the status card).
func (a *Account) KeyStatus(ctx context.Context) KeyStatus { _, st := a.adminKey(ctx); return st }

// SetKey stores (sealed) or, with "", clears the admin key.
func (a *Account) SetKey(ctx context.Context, value string) error {
	value = strings.TrimSpace(value)
	if value == "" {
		return a.repo.SetTypeSafeSealedKey(ctx, nil)
	}
	if a.cipher == nil {
		return ErrSecretsKeyMissing
	}
	sealed, err := a.cipher.Seal([]byte(value))
	if err != nil {
		return err
	}
	return a.repo.SetTypeSafeSealedKey(ctx, &sealed)
}
```

Check `secretbox`'s signatures: `Seal([]byte) (string, error)` at L55, and `Open` at L66, which may return `[]byte` or `string`. Adjust `string(plain)` to match. Update both fake account repos to implement the two key methods: `judgment`'s `fakeAccountRepo` and `metadatafill`'s `newFakeAccountRepo()` from Task 8.

- [ ] **Step 4: Wire it.** In `main.go`:

```go
	typesafeAccount := judgment.NewAccount(db.Queries(), time.Now, judgment.WithSealedKey(mailCipher, cfg.TypeSafeAPIKey))
	judgeClient := judgment.New(cfg.TypeSafeEndpoint, cfg.TypeSafeModel, typesafeAccount.Key)
```

`mailCipher` is the local name of the `*secretbox.Cipher` built from `config.MailKEK()` at L449-458, and it may be nil. `metadatafill.Status` gains `KeySource judgment.KeySource` and `KeyStatus judgment.KeyStatus`, filled from the account. The service gets the account already (Task 8). Widen `metadataFillProvider` with `SetKey(ctx, value string) error`, and implement it on `metadatafill.Service` as a pass-through to `s.account.SetKey`.

Handler:

```go
type metadataFillKeyRequest struct {
	APIKey *string `json:"api_key"`
}

// Validate satisfies Validatable (validation.go:19): absent is 422; a
// malformed body is already 400 from bindAndValidate.
func (r *metadataFillKeyRequest) Validate() []FieldError {
	if r.APIKey == nil {
		return []FieldError{{Field: "api_key", Message: "required; send \"\" to remove the key"}}
	}
	return nil
}

func (s *Server) handleMetadataFillSetKey(c echo.Context) error {
	callerID, _, err := mustPrincipal(c)
	if err != nil {
		return err
	}
	var req metadataFillKeyRequest
	if err := bindAndValidate(c, &req); err != nil {
		return err
	}
	err = s.metadatafillsvc.SetKey(c.Request().Context(), *req.APIKey)
	if errors.Is(err, judgment.ErrSecretsKeyMissing) {
		s.audit(c, observability.ActionAdminMetadataFillKeyUpdate, observability.ResultFailure, callerID.String(), "secrets_key_missing")
		return &MetadataFillError{Status: http.StatusConflict, Code: "metadata_fill_secrets_key_missing",
			Message: "this deployment has no key-encryption key, so the TypeSafe key cannot be stored sealed — and vidra will not store it in the clear. Set MFA_KEY_KEK (or share FEDERATION_KEY_KEK) and restart the api, then save again. TYPESAFE_API_KEY in the env file still works"}
	}
	if err != nil {
		return err
	}
	reason := "set"
	if strings.TrimSpace(*req.APIKey) == "" {
		reason = "cleared"
	}
	s.auditEvent(c, audit.Event{
		Action: observability.ActionAdminMetadataFillKeyUpdate, Result: observability.ResultSuccess,
		ActorID: callerID.String(), Reason: reason,
		Metadata: []audit.MetadataField{{Key: "secret_changed", Value: "true"}},
	})
	return c.NoContent(http.StatusNoContent)
}
```

Confirm `FieldError`'s field names in `validation.go`. Register `api.PUT("/admin/metadata-fill/key", s.handleMetadataFillSetKey, adminOnly...)`, and add the audit constant:

```go
	// ActionAdminMetadataFillKeyUpdate: the admin-panel TypeSafe key was set or
	// cleared. Reason set|cleared; metadata secret_changed. Never the value.
	ActionAdminMetadataFillKeyUpdate = "admin.metadata_fill.key_update"
```

Update OpenAPI: the route, and `key_source`/`key_status` on the status schema. Replace the Task 9 misconfigured note's parenthesis with "or add the key under Config → VOD — no restart needed". Update `internal/setup/secrets.go:85-86`.

HTTP tests: admin-only; 204 on set and on clear; 409 with no cipher; 422 on a missing field; an audit record carrying `secret_changed`; and `!strings.Contains(buf.String(), "sk-test-key")` over the captured log.

- [ ] **Step 5: Run.** `make ci`, then `go vet -tags=integration ./...`.

- [ ] **Step 6: Commit**, then run **Task 12** (S3) straight after the merge.

```bash
git add internal cmd/api api/openapi.yaml
git commit -m "feat(judgment): admin-panel TypeSafe key, sealed or refused, in the account state

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 16: Toggle and warning, infrastructure labels, API wrappers (PR U1, user)

**Goal:** The admin can switch the feature on under Config → VOD, is warned when no key is set, sees the Infrastructure row, and the client can call the four endpoints.

**Files:**
- Modify: `lib/api/types.ts`, `lib/api/endpoints.ts`, `lib/admin-config-ia.ts` (VOD sections L282-341; META), `lib/admin-config-ia.test.ts` (`SERVER_REGISTRY` ~L108; wiring block L827-919), `components/AdminInfrastructureView.tsx` (`FEATURE_LABEL` L555-577; `FEATURE_CONFIG_PAGE` L590-619)

**Acceptance Criteria:**
- [ ] `metadata_autofill_enabled` renders as a toggle in a new VOD section `autofill` titled "Automatic category & language", with the §8 privacy text as help.
- [ ] The warning shows when `features` has `{key:"metadata_autofill", configured:false}`, and not otherwise.
- [ ] The Infrastructure row reads "Automatic category & language" and links to `/admin/config/vod#config-section-autofill`.
- [ ] `api.getMetadataFillStatus`, `testMetadataFill`, `startMetadataFillRun` and `stopMetadataFillRun` exist, and `npm run check:contract` passes.

**Verify:** `npx tsc --noEmit && npm run lint && npm run test -- lib/admin-config-ia components/AdminInfrastructureView && npm run check:contract`.

**Steps:**

- [ ] **Step 1: Confirm the contract is synced.** S1 and S2 (Task 12) must be merged: `grep -c "MetadataFillStatus\|auto_filled" lib/api/generated.ts` must print ≥ 2. Do not regenerate in this PR.

- [ ] **Step 2: Failing tests.** In `lib/admin-config-ia.test.ts`, add `["metadata_autofill_enabled","vod","autofill"]` to `SERVER_REGISTRY`. In the wiring block, add:

```ts
  it("warns on automatic category & language when no TypeSafe key is set", () => {
    const infra = { features: [{ key: "metadata_autofill", enabled: true, configured: false }] };
    expect(wiringWarnNote(META.metadata_autofill_enabled, infra)).toMatch(/no TypeSafe API key/);
    expect(
      wiringWarnNote(META.metadata_autofill_enabled, {
        features: [{ key: "metadata_autofill", enabled: true, configured: true }],
      }),
    ).toBeNull();
  });
```

In `components/AdminInfrastructureView.test.tsx`, add a case rendering a `metadata_autofill` row. It asserts the label "Automatic category & language" and a link to `/admin/config/vod#config-section-autofill`.

- [ ] **Step 3: Run them and watch them fail.** `npm run test -- lib/admin-config-ia components/AdminInfrastructureView`. Expected: FAIL.

- [ ] **Step 4: Implement.** In the VOD sections, after `transcription`:

```ts
    {
      // Server id "autofill": TypeSafe Jev automatic category & language.
      id: "autofill",
      title: "Automatic category & language",
      description:
        "Fill in a missing category and language on public videos (needs a TypeSafe key).",
    },
```

In `META`, after `transcription_enabled`:

```ts
  metadata_autofill_enabled: {
    label: "Automatic category & language",
    help: "Sends the title, description, channel name and tags of public videos to TypeSafe, a third-party service hosted in the United States, to choose a category and language for videos that have none. Private and unlisted videos, drafts, comments and messages are never sent. TypeSafe states it does not train on this data. Off by default.",
    control: "toggle",
    page: "vod",
    section: "autofill",
    warn: {
      note: "This server has no TypeSafe API key, so this switch currently does nothing — nothing is sent and nothing is filled. Set TYPESAFE_API_KEY in the server's env file.",
      isTriggered: (infra) =>
        infra.features?.some(
          (f) => f.key === "metadata_autofill" && f.configured === false,
        ) === true,
    },
  },
```

In `AdminInfrastructureView.tsx`: add `metadata_autofill: "Automatic category & language"` to `FEATURE_LABEL` and `metadata_autofill: "/admin/config/vod#config-section-autofill"` to `FEATURE_CONFIG_PAGE` (the anchor form `cdn` already uses).

In `lib/api/types.ts`:

```ts
export type MetadataFillStatus = Schemas["MetadataFillStatus"];
export type MetadataFillRun = Schemas["MetadataFillRun"];
```

In `lib/api/endpoints.ts`, beside `sendTestMail`:

```ts
  getMetadataFillStatus: (signal?: AbortSignal) =>
    apiRequest<MetadataFillStatus>("/api/v1/admin/metadata-fill/status", { signal }),
  testMetadataFill: () =>
    apiRequest<{ status: string }>("/api/v1/admin/metadata-fill/test", { method: "POST" }),
  startMetadataFillRun: () =>
    apiRequest<MetadataFillRun>("/api/v1/admin/metadata-fill/runs", { method: "POST" }),
  stopMetadataFillRun: () =>
    apiRequest<void>("/api/v1/admin/metadata-fill/runs/current", { method: "DELETE" }),
```

- [ ] **Step 5: Run the gates.** Every command in Verify is green.

- [ ] **Step 6: Commit**

```bash
git add lib components
git commit -m "feat(admin): automatic category & language toggle, warning and infrastructure row

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 17: `MetadataFillCard` on Config → VOD (PR U2, user)

**Goal:** The feature's controls sit beside its toggle: state, counts, **Test connection**, and **Fill existing videos (N)** / **Stop filling**. On a core that lacks the endpoints, the card renders nothing.

**Files:**
- Create: `components/admin/MetadataFillCard.tsx`, `components/admin/MetadataFillCard.test.tsx`
- Modify: `components/AdminInstanceConfigView.tsx` (`sectionPanel`, L605-640)
- Modify: `e2e/admin-config.spec.ts` (one mocked spec)

**Behaviour and copy:**
- The card loads `api.getMetadataFillStatus`.
  - A **404** means this core predates the feature (§0.3; releases can pair a newer user with an older core), and the card renders `null`.
  - Any other failure shows `ErrorState` with retry.
- Status line:
  - "Off" when not enabled.
  - "Needs setup — no TypeSafe key" when enabled but not configured.
  - "Paused — TypeSafe rejected the key" for `paused_code=auth`.
  - "Paused — rate limited, resuming shortly" for `rate_limited`.
  - "Paused — TypeSafe unreachable, retrying shortly" for `unavailable`.
  - "Active" otherwise.
- Counts: "Waiting N · Filled N · Not confident N · Failed N".
- **Test connection** follows the MailTestCard pattern: an `inFlight` ref, `aria-disabled`, and a `Spinner`.
  - Success: "TypeSafe answered. The key works."
  - `errorMessage` overrides:
    - `metadata_fill_not_configured`: "No TypeSafe API key is set."
    - reason `auth`: "TypeSafe rejected the key."
    - `rate_limited`: "TypeSafe is rate-limiting this key. Try again in a few minutes."
    - `unavailable`: "TypeSafe could not be reached from this server."
    - `bad_response`/`invalid_request`: "TypeSafe answered with something unexpected. Check TYPESAFE_ENDPOINT and TYPESAFE_MODEL."
  - The server returns the typed reason in `ErrorBody.reason`, which `ApiError.mailReason` already carries (`lib/api/client.ts` L37-58). Read it from there, with a comment saying the field is shared.
  - After a successful test, reload the status: the server clears a pause.
- **Fill existing videos (N)**, where N is `unjudged`.
  - It is `aria-disabled`, with the reason shown, when not enabled or not configured ("Switch it on and add a key first"), or when `unjudged == 0` ("Nothing to fill").
  - While `run.state === "running"`, it becomes **Stop filling**, with "Filled X of Y judged so far".
  - It polls status every 10 s only while a run is running, and clears the interval on unmount.
- The card never shows a probability.

**Acceptance Criteria:**
- [ ] Unit tests cover:
  - the six status lines;
  - a 404 rendering nothing;
  - test success, and test `auth` failure;
  - start, which flips the button to Stop; stop; a 409 `metadata_fill_run_active` message;
  - polling stopping on unmount.
- [ ] The card is mounted by `sectionPanel("vod", "autofill")` and nowhere else.
- [ ] A mocked e2e run renders the card on `/admin/config/vod` from a mocked status and clicks Test connection against a mocked 200.

**Verify:** `npm run test -- components/admin/MetadataFillCard components/AdminInstanceConfigView && npx tsc --noEmit && npm run lint && npm run lint:icons`.

**Steps:**

- [ ] **Step 1: Failing tests** `components/admin/MetadataFillCard.test.tsx`. Mock the API as `MailTestCard.test.tsx` does:

```tsx
// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api";
import { MetadataFillCard } from "./MetadataFillCard";

const mocks = vi.hoisted(() => ({
  getMetadataFillStatus: vi.fn(),
  testMetadataFill: vi.fn(),
  startMetadataFillRun: vi.fn(),
  stopMetadataFillRun: vi.fn(),
}));
vi.mock("@/lib/api", async (importActual) => {
  const actual = await importActual<typeof import("@/lib/api")>();
  return { ...actual, api: { ...actual.api, ...mocks } };
});

const base = {
  enabled: true, configured: true, model: "jev-1.13.0", paused_code: null,
  counts: { waiting: 1, filled: 2, not_confident: 3, failed: 4 }, unjudged: 120, run: null,
};

beforeEach(() => mocks.getMetadataFillStatus.mockResolvedValue(base));
afterEach(() => vi.clearAllMocks());

describe("MetadataFillCard", () => {
  it.each([
    [{ enabled: false }, "Off"],
    [{ configured: false }, "Needs setup — no TypeSafe key"],
    [{ paused_code: "auth" }, "Paused — TypeSafe rejected the key"],
    [{ paused_code: "rate_limited" }, "Paused — rate limited, resuming shortly"],
    [{ paused_code: "unavailable" }, "Paused — TypeSafe unreachable, retrying shortly"],
    [{}, "Active"],
  ])("shows the status for %o", async (patch, text) => {
    mocks.getMetadataFillStatus.mockResolvedValue({ ...base, ...patch });
    render(<MetadataFillCard />);
    expect(await screen.findByText(text)).toBeTruthy();
  });

  it("renders nothing on a core without the feature", async () => {
    mocks.getMetadataFillStatus.mockRejectedValue(new ApiError(404, "not_found", "x"));
    const { container } = render(<MetadataFillCard />);
    await waitFor(() => expect(mocks.getMetadataFillStatus).toHaveBeenCalled());
    expect(container.textContent).toBe("");
  });

  it("shows counts and the unjudged total on the button", async () => {
    render(<MetadataFillCard />);
    expect(await screen.findByText(/Waiting 1 · Filled 2 · Not confident 3 · Failed 4/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Fill existing videos (120)" })).toBeTruthy();
  });

  it("reports a rejected key from the test", async () => {
    mocks.testMetadataFill.mockRejectedValue(
      Object.assign(new ApiError(502, "metadata_fill_test_failed", "x"), { mailReason: "auth" }),
    );
    render(<MetadataFillCard />);
    await userEvent.click(await screen.findByRole("button", { name: "Test connection" }));
    expect(await screen.findByText("TypeSafe rejected the key.")).toBeTruthy();
  });

  it("starts and stops a run", async () => {
    mocks.startMetadataFillRun.mockResolvedValue({ id: "r", state: "running", judged: 0, filled: 0, started_at: "" });
    render(<MetadataFillCard />);
    await userEvent.click(await screen.findByRole("button", { name: "Fill existing videos (120)" }));
    mocks.getMetadataFillStatus.mockResolvedValue({ ...base, run: { id: "r", state: "running", judged: 5, filled: 4, started_at: "" } });
    await userEvent.click(await screen.findByRole("button", { name: "Stop filling" }));
    expect(mocks.stopMetadataFillRun).toHaveBeenCalledOnce();
  });

  it("explains a run already in progress", async () => {
    mocks.startMetadataFillRun.mockRejectedValue(new ApiError(409, "metadata_fill_run_active", "x"));
    render(<MetadataFillCard />);
    await userEvent.click(await screen.findByRole("button", { name: "Fill existing videos (120)" }));
    expect(await screen.findByText(/already running/)).toBeTruthy();
  });

  it("stops polling on unmount", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    mocks.getMetadataFillStatus.mockResolvedValue({ ...base, run: { id: "r", state: "running", judged: 0, filled: 0, started_at: "" } });
    const { unmount } = render(<MetadataFillCard />);
    await waitFor(() => expect(mocks.getMetadataFillStatus).toHaveBeenCalledTimes(1));
    unmount();
    vi.advanceTimersByTime(30_000);
    expect(mocks.getMetadataFillStatus).toHaveBeenCalledTimes(1);
    vi.useRealTimers();
  });
});
```

Check `ApiError`'s constructor argument order in `lib/api/client.ts` and match it.

- [ ] **Step 2: Run them and watch them fail.** Expected: FAIL (no module).

- [ ] **Step 3: Implement `components/admin/MetadataFillCard.tsx`**, structured like `MailTestCard.tsx`:
  - A `<section aria-label="Automatic category and language">` holding a `Card`.
  - The status `Badge`, using `FeatureRow`'s Off/Active/Needs-setup variant mapping (`AdminInfrastructureView.tsx:667-717`), with `warning` for the paused states.
  - The counts line, and two `Button`s using `aria-disabled`.
  - `Spinner`, plus `Alert variant="danger" | "success"` for outcomes.

  Load with `useApiResource(api.getMetadataFillStatus, [])` (`lib/use-api-resource.ts:57`). When the error is an `ApiError` with status 404, return `null`. The resource's `retry` refreshes the status. Poll with a `useEffect` that sets a 10 s interval only while `data?.run?.state === "running"` and clears it on cleanup. Read `.ralph/specs/design-system.md` first; all colours come from tokens.

- [ ] **Step 4: Mount it.** In `sectionPanel` (`AdminInstanceConfigView.tsx:605`):

```tsx
  if (page === "vod" && sectionId === "autofill") return <MetadataFillCard />;
```

- [ ] **Step 5: Mocked e2e.** In `e2e/admin-config.spec.ts`, add a `METADATA_FILL_STATUS = /\/api\/v1\/admin\/metadata-fill\/status$/` constant and a test. It signs in as admin with the file's existing helper, routes the status to `base` and `/metadata-fill/test` to `{ status: "ok" }`, opens `/admin/config/vod`, clicks "Test connection", and expects "TypeSafe answered. The key works.".

- [ ] **Step 6: Run the gates.** Verify is green. Do not run `npm run e2e` locally; CI runs it.

- [ ] **Step 7: Commit**

```bash
git add components e2e
git commit -m "feat(admin): metadata auto-fill card beside its toggle on Config → VOD

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 18: Studio marker and mocked e2e (PR U3, user)

**Goal:** In Studio's edit form, an automatically set category or language carries a quiet note that disappears when the creator changes the field.

**Files:**
- Modify: `components/studio/shared.tsx` (`TaxonomySelect`, L62-107), `components/studio/VideoRow.tsx` (state L71-72; `startEdit` L184-207; selects L238-257)
- Create: `components/studio/shared.test.tsx`
- Modify: `e2e/studio.spec.ts` (near the edit-flow block, ~L1209)

**Acceptance Criteria:**
- [ ] `TaxonomySelect` with `autoFilled` renders "Set automatically · change it if it's wrong" and wires it to the select with `aria-describedby`. Without the prop it renders exactly as before.
- [ ] `VideoRow` shows the note on a field while its value equals the value loaded with `auto_filled` including it, and hides it once the creator picks a different value.
- [ ] The note never names an engine and never shows a number.
- [ ] A mocked e2e run proves the note shows on a mocked `auto_filled:["category"]` video and disappears after changing the category.

**Verify:** `npm run test -- components/studio && npx tsc --noEmit && npm run lint`.

**Steps:**

- [ ] **Step 1: Failing test** `components/studio/shared.test.tsx`

```tsx
// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { TaxonomySelect } from "./shared";

const options = [{ id: "1", label: "Music" }, { id: "2", label: "Films" }];

describe("TaxonomySelect", () => {
  it("notes an automatically set value and links it to the select", () => {
    render(<TaxonomySelect label="Category" ariaLabel="Edit category" value="1" onChange={() => {}} options={options} autoFilled />);
    const note = screen.getByText("Set automatically · change it if it's wrong");
    const select = screen.getByLabelText("Edit category");
    expect(select.getAttribute("aria-describedby") ?? "").toContain(note.id);
  });

  it("renders no note without the flag", () => {
    render(<TaxonomySelect label="Category" ariaLabel="Edit category" value="1" onChange={() => {}} options={options} />);
    expect(screen.queryByText(/Set automatically/)).toBeNull();
  });
});
```

- [ ] **Step 2: Run it and watch it fail.** Expected: FAIL, because the note is missing.

- [ ] **Step 3: Implement.** Add `autoFilled?: boolean` to `TaxonomySelect`'s props. Inside it:

```tsx
  const noteId = useId();
  const describedBy = [errorId && error ? errorId : null, autoFilled ? noteId : null]
    .filter(Boolean)
    .join(" ") || undefined;
```

Put `aria-describedby={describedBy}` on the `<select>`, replacing whatever `aria-describedby` it already derives from `errorId`, and keep that behaviour. Then render after the select:

```tsx
      {autoFilled ? (
        <p id={noteId} className="text-xs text-fg-muted">
          Set automatically · change it if it's wrong
        </p>
      ) : null}
```

Use the existing muted-text token class that `FieldErrorText`'s neighbours use. Check `components/studio/shared.tsx` for the house class name.

In `VideoRow.tsx`, add `const [autoFilled, setAutoFilled] = useState<{ category?: string; language?: string }>(() => pickAuto(video));` with

```ts
function pickAuto(v: Video): { category?: string; language?: string } {
  const af = v.auto_filled ?? [];
  return {
    category: af.includes("category") ? v.category : undefined,
    language: af.includes("language") ? v.language : undefined,
  };
}
```

In `startEdit`, after `setLanguage(full.language ?? "")`, add `setAutoFilled(pickAuto(full));`. On the two selects, pass `autoFilled={autoFilled.category !== undefined && category === autoFilled.category}`, and the same for language. The note then disappears as soon as the value differs, and saving (decision §0.2.2) clears it server-side.

- [ ] **Step 4: Mocked e2e.** In `e2e/studio.spec.ts`, beside the existing edit test (~L1209), route the `GET /api/v1/videos/<id>` mock with `category: "1", auto_filled: ["category"]`, open the edit form, `expect(page.getByText("Set automatically · change it if it's wrong")).toBeVisible()`, then `selectOption` "Edit category" to `"2"` and expect the note to be hidden.

- [ ] **Step 5: Run the gates.** Verify is green.

- [ ] **Step 6: Commit**

```bash
git add components/studio e2e/studio.spec.ts
git commit -m "feat(studio): quiet note on automatically set category and language

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 19: Backed e2e spec and optional-workflow job (PR U4, user; touches `.github/workflows`)

**Goal:** Prove, against the real stack and the stub, that publishing leads to filling, then to the Studio marker, and that the category filter finds the video. This PR's task *is* the workflow change (AGENTS.md hard rule 6 exception); say so in the PR body.

**Files:**
- Create: `e2e-backed/metadata-autofill.spec.ts`
- Modify: `scripts/ci/allowed-skips-backed.txt` (the spec self-skips unless `E2E_JEV_STUB=true`, like `whisper-captions.spec.ts`)
- Modify: `.github/workflows/frontend-e2e-optional.yml` (a new job `metadata-autofill-backed`; update the header's list of lanes)

**Acceptance Criteria:**
- [ ] With the stub profile up, `METADATA_AUTOFILL_ENABLED=true TYPESAFE_API_KEY=stub TYPESAFE_ENDPOINT=http://jev-stub:8080`, the spec: publishes a public video titled "Music … <uuid>" with no category or language through the Studio UI; polls the API (up to 120 s, since the leader ticks every 30 s) until `category` is the id of "Music" and `language` is `en`; opens the edit form and sees the note; then queries the public video list filtered by that category and finds the video.
- [ ] In the ordinary backed lane the spec is skipped and listed in `allowed-skips-backed.txt`.
- [ ] The optional workflow job runs only on `workflow_dispatch` and the Sunday cron, never on push or PR.

**Verify:** In CI, trigger `frontend-e2e-optional.yml` via `gh workflow run frontend-e2e-optional.yml --ref <branch>` and paste the run link and the job's pass line into the PR. Locally: `npx tsc --noEmit && npm run lint`.

**Steps:**

- [ ] **Step 1: Write the spec** `e2e-backed/metadata-autofill.spec.ts`, built on `e2e-backed/fixtures.ts` (`API_URL`, `adminToken`, `videoDetail`, `startStudioUpload`, `createChannelViaStudioUI`, `SAMPLE_AV_MP4_4S_BASE64`):

```ts
import { expect, test } from "./fixtures";
import { API_URL, adminToken, createChannelViaStudioUI, startStudioUpload, videoDetail } from "./fixtures";

test.skip(process.env.E2E_JEV_STUB !== "true", "needs the jev-stub compose profile (optional workflow)");

test("@autofill a public video with no category is filled, marked, and filterable", async ({ page, request }) => {
  const title = `Music night ${crypto.randomUUID().slice(0, 8)}`;
  await createChannelViaStudioUI(page);
  const videoId = await startStudioUpload(page, { title, privacy: "public" });

  const token = await adminToken(request);
  const config = await (await request.get(`${API_URL}/api/v1/videos/config`)).json();
  const music = config.categories.find((c: { label: string }) => c.label === "Music").id;

  await expect
    .poll(async () => (await videoDetail(request, videoId, token)).category, { timeout: 120_000, intervals: [5_000] })
    .toBe(music);
  expect((await videoDetail(request, videoId, token)).language).toBe("en");

  await page.goto(`/studio?video=${videoId}`);
  await expect(page.getByText("Set automatically · change it if it's wrong").first()).toBeVisible();

  const list = await (await request.get(`${API_URL}/api/v1/videos?category=${music}`)).json();
  expect(list.videos.map((v: { id: string }) => v.id)).toContain(videoId);
});
```

Check the helper signatures in `e2e-backed/fixtures.ts` before writing: `startStudioUpload`'s options, whether it returns the id, and `videoDetail`'s arguments. Also check the category-filter query parameter name on the public list (`grep -n 'category' api/openapi.yaml` in core, near `/api/v1/videos`). Use the real names.

- [ ] **Step 2: Register the skip** in `scripts/ci/allowed-skips-backed.txt`, in the same format as the whisper entry.

- [ ] **Step 3: Workflow job.** Copy the structure of the backed job in `frontend-e2e-backed.yml`: checkout of `yegamble/vidra-core` into `.core`, `docker compose … up -d --build`, a health wait, build, and run. Change these parts:

```yaml
  metadata-autofill-backed:
    # Jev auto-fill against the deterministic jev-stub (vidra-core compose
    # profile). No real key in CI, ever.
    runs-on: ubuntu-latest
    env:
      METADATA_AUTOFILL_ENABLED: "true"
      TYPESAFE_API_KEY: stub
      TYPESAFE_ENDPOINT: http://jev-stub:8080
      E2E_JEV_STUB: "true"
    steps:
      # …same checkout/build/health steps as the backed job, with the compose
      # command gaining `--profile jev-stub` …
      - name: Run the auto-fill spec
        run: E2E_API_URL=http://localhost:8080 npm run e2e:backed -- --grep @autofill
```

Update the file's header comment, which lists wired and unwired lanes.

- [ ] **Step 4: Gates, push, and a dispatched run.** Run `npx tsc --noEmit && npm run lint`, push the branch, then `gh workflow run frontend-e2e-optional.yml --ref <branch>` and `gh run watch`. Paste the result. A red run means the PR is not ready; debug it with `superpowers-extended-cc:systematic-debugging`, and don't disable the spec.

- [ ] **Step 5: Commit**

```bash
git add e2e-backed/metadata-autofill.spec.ts scripts/ci/allowed-skips-backed.txt .github/workflows/frontend-e2e-optional.yml
git commit -m "test(e2e-backed): metadata auto-fill end to end against the jev stub

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 20: Key field on the card (PR U5, user)

**Goal:** The admin can paste, replace or remove the TypeSafe key on the card with `SecretInput`.

**Files:**
- Modify: `lib/api/endpoints.ts` (`setMetadataFillKey`), `components/admin/MetadataFillCard.tsx`, `components/admin/MetadataFillCard.test.tsx`

**Behaviour:** Under the status line, a `SecretInput` labelled "TypeSafe API key" with `isSet = key_source === "admin"`, `allowClear`, and a **Save key** button that is shown only when the value is not `undefined`. Hints:
- `key_source === "env"`: "Using the key from the server's env file. A key saved here takes priority."
- `key_status === "undecryptable"`: "The saved key can't be read with this server's encryption key. Save it again."
- 409 `metadata_fill_secrets_key_missing`: the server's message verbatim.

After a save, the card reloads the status.

**Acceptance Criteria:**
- [ ] Untouched: no request is made. Replace: a PUT with the value. Remove: a PUT with `""`.
- [ ] The key never appears in the rendered DOM after saving: the input resets to `undefined`.
- [ ] The three hints render in their conditions.

**Verify:** `npm run test -- components/admin/MetadataFillCard && npx tsc --noEmit && npm run lint`.

**Steps:**

- [ ] **Step 1: Confirm S3 (Task 12) merged** (`grep -c key_source lib/api/generated.ts` ≥ 1). Add the wrapper:

```ts
  setMetadataFillKey: (apiKey: string) =>
    apiRequest<void>("/api/v1/admin/metadata-fill/key", { method: "PUT", body: { api_key: apiKey } }),
```

- [ ] **Step 2: Failing tests** in `MetadataFillCard.test.tsx`:

```tsx
  it("saves a replaced key and forgets it", async () => {
    mocks.setMetadataFillKey = vi.fn().mockResolvedValue(undefined);
    mocks.getMetadataFillStatus.mockResolvedValue({ ...base, key_source: "env", key_status: "none" });
    render(<MetadataFillCard />);
    expect(await screen.findByText(/Using the key from the server's env file/)).toBeTruthy();
    await userEvent.type(screen.getByLabelText("TypeSafe API key"), "sk-test-key");
    await userEvent.click(screen.getByRole("button", { name: "Save key" }));
    expect(mocks.setMetadataFillKey).toHaveBeenCalledWith("sk-test-key");
    await waitFor(() => expect(document.body.innerHTML).not.toContain("sk-test-key"));
  });

  it("removes an admin key", async () => {
    mocks.setMetadataFillKey = vi.fn().mockResolvedValue(undefined);
    mocks.getMetadataFillStatus.mockResolvedValue({ ...base, key_source: "admin", key_status: "ok" });
    render(<MetadataFillCard />);
    await userEvent.click(await screen.findByRole("button", { name: /Remove/ }));
    await userEvent.click(screen.getByRole("button", { name: "Save key" }));
    expect(mocks.setMetadataFillKey).toHaveBeenCalledWith("");
  });
```

Add `setMetadataFillKey: vi.fn()` to the hoisted `mocks`. Check `SecretInput`'s actual button names (Replace, Remove, Cancel) in `components/ui/SecretInput.tsx` and match them.

- [ ] **Step 3: Implement** with `const [keyDraft, setKeyDraft] = useState<string | undefined>(undefined);` and render `<SecretInput label="TypeSafe API key" isSet={data.key_source === "admin"} value={keyDraft} onChange={setKeyDraft} allowClear hint={hint} autoComplete="off" />`. **Save key** calls `api.setMetadataFillKey(keyDraft)`, then `setKeyDraft(undefined)` and `retry()`. Errors go through `errorMessage(err, "Could not save the key.")`, which surfaces the 409 message.

- [ ] **Step 4: Run the gates.** Verify is green.

- [ ] **Step 5: Commit**

```bash
git add lib components
git commit -m "feat(admin): set the TypeSafe key from the auto-fill card

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 21: Env example and runbook (PR M1, meta)

**Goal:** An operator can find, understand, enable, measure and undo the feature from this repo alone.

**Files:**
- Modify: `env/production.env.example` (a new block after the outbound-email block, ~L976)
- Create: `docs/metadata-autofill.md`

**When:** after the first vidra-core release containing C9–C13 and the first vidra-user release containing U1–U2 exist. Meta CI builds core `main`, so it would pass earlier, but operators run the pinned tags, and a runbook for a feature their images lack is a silent no-op.

**Acceptance Criteria:**
- [ ] The runbook opens with "Requires vidra-core ≥ vX.Y.Z and vidra-user ≥ vA.B.C", with the numbers taken from those releases' notes. The panel-key paragraph carries its own "from vidra-core ≥ … / vidra-user ≥ …", from the releases containing C14 and U5, or "not yet released".
- [ ] Until the panel key ships, the runbook states that `TYPESAFE_API_KEY` must be identical for every api and worker service. The status card reads the key of the replica that serves it, while the elected worker leader uses its own.
- [ ] The four keys are present with empty or `false` values and the §8 privacy statement.
- [ ] The compose gate passes with the unedited example.
- [ ] The runbook covers: what is sent and never sent; enabling (env or panel); the `enabled_since` rule, stated plainly; "Fill existing videos"; the status meanings; the evaluation gate (`docker compose exec api /app/api evaluate-metadata`, with the real binary path checked against the api Dockerfile); turning it off; undoing fills (SQL below); and the operator's privacy-notice duty.

**Verify:**
```
cp env/production.env.example /tmp/check.env   # fill the ${VAR:?} keys with dummies
docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file /tmp/check.env config -q && echo OK
python3 -m unittest discover -s tests -p '*_test.py'
```

**Steps:**

- [ ] **Step 1: Env block**

```bash
# --- Automatic category & language (TypeSafe Jev) -----------------------------
# OFF by default. When on, the TITLE, DESCRIPTION, CHANNEL NAME and TAGS of
# PUBLIC, published videos that have no category or language are sent to
# TypeSafe, a third-party service hosted in the United States, which picks one
# from this instance's own lists. Private and unlisted videos, drafts,
# comments and messages are never sent. TypeSafe states it does not train on
# this data. You are the party deciding to send it: say so in your instance's
# privacy notice. Runbook: docs/metadata-autofill.md.
#
# The admin toggle (Config → VOD) overrides METADATA_AUTOFILL_ENABLED. Leave
# TYPESAFE_ENDPOINT / TYPESAFE_MODEL empty for the defaults (api.typesafe.ai,
# jev-1.13.0): the confidence bars were measured against that model.
# TYPESAFE_API_KEY is a SECRET — never commit a real value.
METADATA_AUTOFILL_ENABLED=false
TYPESAFE_API_KEY=
TYPESAFE_ENDPOINT=
TYPESAFE_MODEL=
```

- [ ] **Step 2: Runbook** `docs/metadata-autofill.md`, with these sections: *What it does*, *What is sent and what never is*, *Turning it on*, *Which videos it reaches* ("Videos published or edited after you switch this on are filled automatically; everything else waits for the Fill existing videos button"), *Reading the status card*, *Before you rely on it: the evaluation*, *Turning it off*, *Undoing fills*, *Privacy notice*, *Known limits* (a video whose category id is missing from the instance's list — possible after a PeerTube import — counts as set and is not filled, §0.2.10; PeerTube re-sync now keeps a category/language its source has none for; English-primary; a wrong answer is visible and correctable in Studio; an edited old video becomes eligible; federation peers are not sent auto-filled values). The undo SQL must say that it bypasses the hooks, so the search index converges at the next reconcile (24 h default), or at once after an api restart triggers the boot reconcile, which the implementer checks in `runSearchReconcileWorker` before claiming it:

```sql
-- Revert every automatic value no person has changed since.
BEGIN;
UPDATE videos v SET category = NULL
  FROM video_metadata_judgments j
 WHERE j.video_id = v.id AND j.category_applied IS NOT NULL AND v.category = j.category_applied;
UPDATE videos v SET language = NULL
  FROM video_metadata_judgments j
 WHERE j.video_id = v.id AND j.language_applied IS NOT NULL AND v.language = j.language_applied;
-- Keep the judgments so the worker does not re-ask; clear the marker.
UPDATE video_metadata_judgments SET category_applied = NULL, language_applied = NULL;
COMMIT;
```

- [ ] **Step 3: Run the gates** (Verify above). Expected: `OK`, and the unit suite passes with 0 skipped.

- [ ] **Step 4: Commit and open the PR**

```bash
git add env/production.env.example docs/metadata-autofill.md
git commit -m "docs: metadata auto-fill env keys and operator runbook

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 22: Beta evaluation, bars, scope ledger (PR M2, meta)

**Goal:** The confidence bars come from a measurement on the beta's human-labelled PeerTube imports, recorded honestly, before auto-fill is switched on there.

**Preconditions (owner steps; this plan does not do them):** a core release containing C1–C13 (C6 included, so a re-sync cannot erase fills) is cut and deployed to beta (`! ./deploy/release.sh --yes vX.Y.Z`, then the deploy). The feature stays **off**. `TYPESAFE_API_KEY` is set in beta's env file. Beta runs as a no-git bundle tree, so check the memory note on its local compose mount before editing anything there.

**Files:**
- Create: `docs/metadata-autofill-evaluation-<YYYY-MM-DD>.md`
- Modify: `docs/release-readiness.md` (the SCP-10 row, "AI moderation": note that the first Jev slice is built and what it does not cover)
- Possibly, in core as its own tiny PR: `internal/metadatafill/request.go` `CategoryBar`/`LanguageBar`

**Acceptance Criteria:**
- [ ] `api evaluate-metadata --sample 500 --json` ran on beta. The record contains the header (model, sample, seed, date), both field tables, the confused pairs, and the cost (input tokens × $0.042/M).
- [ ] The chosen bars are justified in one paragraph each. The rule: the lowest band whose agreement is at least 90% for category and at least 97% for language, rounded up to 0.05. If no band qualifies, the record says auto-fill should not be enabled for that field. The owner confirms the rule in the PR; this plan only proposes it.
- [ ] The record carries the caveat verbatim: "Agreement with creator-chosen values is a floor on accuracy, not ground truth; creator categories are noisy."
- [ ] If the bars change, a separate core PR updates the constants and cites the record.
- [ ] One manual run with the real key and the feature **on**, for a short window chosen by the owner, is recorded with before and after counts from the status card. Then the feature is switched back off, or left on, per the owner's call.

**Verify:** `python3 -m unittest discover -s tests -p '*_test.py'` (the docs tests, e.g. `docs_image_refs_test.py`, still pass), and the record renders on GitHub.

**Steps:**

- [ ] **Step 1: Run the evaluator on beta** as the `vidra` user, never root:

```bash
ssh vidra@<beta-host> 'cd <bundle-dir> && docker compose exec -T api /app/api evaluate-metadata --sample 500 --json' \
  > /tmp/eval.json
```

Check the api binary path inside the image (`docker compose exec api which api` or the Dockerfile's `ENTRYPOINT`) and use it.

- [ ] **Step 2: Write the record** from `/tmp/eval.json`, with tables in the house docs style (`docs/runtime-acceptance-*.md`). State what was not measured: non-English instances, custom taxonomies, and videos whose metadata is thin.

- [ ] **Step 3: Scope-ledger note.** In `docs/release-readiness.md`, append to the SCP-10 row: "First Jev slice (automatic category and language on public videos) built behind an off-by-default toggle; report triage and watched-word precision are separate, undesigned slices."

- [ ] **Step 4: Commit and open the PR**

```bash
git add docs/metadata-autofill-evaluation-*.md docs/release-readiness.md
git commit -m "docs: beta evaluation of Jev auto-fill and the confidence bars it sets

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---
## Self-review (revision 2, 2026-09-26)

**Spec coverage:**

| Spec section | Task(s) |
|---|---|
| §4.1 client, key resolution, model pin, timeout, cap, breaker, closed codes, denylist | 1, 2, 3, 8 (account pause), 15 (sealed key) |
| §4.2 always-started worker, eligibility, claim, retries, lease reclaim | 9 (leader-gated start), 4, 8 |
| §4.3 data model | 4 (plus `typesafe_state`, §0.2.8) |
| §4.4 `enabled_since`, runs, `job_runs` projection, stop, requeue | 4, 8, 10 |
| §4.5 guarded write, human-edit clear | 4 (`RecordAndApplyMetadataJudgment`), 5, 8 |
| §5 request | 7 |
| §6 bars and the evaluation | 7, 13, 22 |
| §7 failure table | 2, 4, 8, 5 (each row has a test: auth/rate/outage pause, backoff, vocabulary change, lost eligibility, >254 categories, cascade delete by FK) |
| §7 audit: toggle, key, run start/stop | toggle via instance-settings audit (`admin_instance_settings.go:419`); key 15; runs and test 10 |
| §8 privacy text | 16 (help), 21 (env and runbook) |
| §9 toggle, warn, infra row, card, key field, Studio marker | 16, 9, 17, 20, 18 |
| §10 contract and configuration; count 119 | 9, 10, 11, 3, 12 |
| §11 testing incl. stub-backed e2e and a real-service run | 2, 4, 5, 6, 8, 9, 10, 11, 17, 18, 19, 22 |
| §12 PR sequence | §0.3 (22 PRs; contract rule) |
| §14 risks | 22 (accuracy), 6 (import interplay), §0.3 (what runs when off) |

**Review findings folded in:**
- vidra-core reviewer: B1 → Task 9; B2 → Task 8 plus the Task 4 tie-break; B3 → Task 4 `RecordAndApplyMetadataJudgment`; M1 → Task 5; M2 → Task 5 (both fakes); M3 → §0.5; M4 → Task 5/9 narrow hook; M5 → Task 2 and 8; M6 → §0.4 scratch database; M7 → Task 4 cutoff test; M8 → Task 11 repo seeding; M9 → Task 14; M10 → Task 4; M11 → Task 10.
- Architect: 1 → §0.3 contract rule and Task 12; 2 → Task 6; 3 → Task 8; 4 → `typesafe_state` / `judgment.Account`; 5 → leader gating; 6 → narrow hook; 7 → §0.3 "what runs when off" plus Task 5 best-effort; 8 → Task 9 queue depth; 9 → Task 11 `canManageVideo`; 10 → Task 17; 11 → Task 21 timing; 12 → Task 17 renders nothing on 404; 13 → Task 4; 14 → Task 10; 15 → deferred (File structure); 16 → Task 15; 17 → §0.1 quotes corrected.
- Minor items: exact backoff literals; the fake clock; a run stuck when toggled off; an atomic start; a pause cleared by a successful test; `not_confident` computed from probabilities; the lease check on record (`state='running'` in the statement); the claim index; the actor on the projection; `pgconv.IsUniqueViolation`; `db.Queries()`; no `Pool()`; 404 rather than 501.

**Placeholder scan:** no code block carries a stub or a line meant to be deleted. Where a step says "match the real name", it names the file and line to read. Those are the sqlc field names (with §0.5 fixing the types), the `ApiError` constructor, the `ValidationError` shape, the seeding helper in `internal/video`, and the logger field.

**Type consistency:**
- `judgment.{Question,Option,Answer,Result,Code,KeyFunc,Account,PausesAccount,AuthPause,ShortPause,ErrSecretsKeyMissing,KeySource,KeyStatus}`: defined in Tasks 2, 8 and 15; used in 8, 10, 13 and 15.
- `metadatafill.{Subject,Request,Decision,BuildRequest,Decide,Q*,NoneOfThese,Unclear,CategoryBar,LanguageBar}`: defined in 7; used in 8 and 13.
- `metadatafill.{Service,New,Repository,Judge,Notifier,Status,ErrRunActive,ErrInactive,ErrNoRun}`: defined in 8 and 10.
- `video.{WithInferredMetadataHook,NotifyInferredMetadata,AutoFilled}`: defined in 5; used in 8, 9 and 11.
- Query names match Task 4 throughout.

**Revision 3 (the re-verification findings):**
- vidra-core reviewer:
  - N1 poison video → Task 2 `ServerAnswered` and Task 8 `outcomePauseSpent`, plus a test.
  - N2 nothing-to-ask → Task 8 terminal record, plus a test.
  - N3 → Task 10 `pgtype.UUID`.
  - N4 → Task 8 and Task 15 fakes.
  - N5 → Task 9 `atomic.Pointer`.
  - N6 → Task 8 `inOptions(s.categories())`, plus a test.
  - N7 → Task 8 stamps before the pause check.
  - N8 → Task 8 `Recorded` check and the documented rule.
  - N9 → Task 15 `bindAndValidate`.
  - N10 → §0.4 one scratch database per package.
- Architect:
  - N1 dangling ids → §0.2.10 (the owner's call), Task 13, and the runbook.
  - N2 → Task 11 `canManageChannelContent` plus §0.3.
  - N3 = core N2.
  - N4 → the Task 21 runbook requirement.
  - N5 → Task 12 fetches at the merge SHA.
  - N6 → Task 21 panel-key versioning.
- Final check: the N5 regression (a nil provider panics) → Task 9; M-a → §0.4 `TestMain`; M-b → Task 4 `not_confident` requires `model IS NOT NULL`.
