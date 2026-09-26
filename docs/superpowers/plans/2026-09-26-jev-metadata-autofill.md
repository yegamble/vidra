# Automatic category and language (TypeSafe Jev), slice 1: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task by task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fill the empty `category` and `language` of public, published videos with TypeSafe Jev judgments. The feature is operator-enabled, off by default, never overwrites a human value, and marks each fill in Studio.

**Architecture:** vidra-core gets a small Jev HTTP client (`internal/judgment`) and a state-scan worker (`internal/metadatafill`) on `jobloop`. The worker claims eligible videos by inserting into `video_metadata_judgments` and asks Jev one request with two `choice` questions. It stores the raw answer, then applies confident picks through `video.Service.ApplyInferredMetadata`. That is a guarded write that fires the existing `onUpdate` hooks, so search sees the change the same way it sees a human edit. vidra-user adds a toggle, an infrastructure row, a status card and a Studio marker. The meta repo documents the env keys and the runbook, and records the beta measurement that sets the confidence bars.

**Tech Stack:** Go 1.x, Echo v4, sqlc v1.31.1, Postgres, golang-migrate (vidra-core). Next.js 16, Vitest, Playwright (vidra-user). Bash/Compose/Markdown (meta).

**Spec:** [`docs/superpowers/specs/2026-09-20-jev-metadata-autofill-design.md`](../specs/2026-09-20-jev-metadata-autofill-design.md) (meta PR #231).

---

## 0. Read this first

### 0.1 What the code check changed (2026-09-26)

The spec was written against core v0.7.5. The code was re-read at core `400c1a8`, user `8efd7c7` and meta `79a84cd`, together with the live TypeSafe docs and a live API call. Every row below differs from the spec's text. The plan follows the right-hand column.

| Spec says | Code / vendor fact | Plan does |
|---|---|---|
| Circuit breaker "with `searchclient`'s numbers" | The breaker is private to `internal/searchclient/breaker.go` | Task 1 extracts it into `internal/breaker` so both clients share one implementation. Copying it would break the house "reuse components" rule. |
| Error codes `auth`, `rate_limited`, `unavailable`, `bad_response` | The API also returns **422** (our request was invalid) and **529** (vendor overloaded) | Two more codes: `invalid_request`, where that video fails and the worker does not pause, and `not_configured`, meaning no key. 529 maps to `unavailable`. |
| "Laundered through `safeerr`" | `judgment.Error` carries only a closed code; upstream text is never read into it | No `safeerr` wrapping is needed. The HTTP layer maps the code to a typed error. |
| Reuse "the write-only secret mechanism the admin mail-settings work is building" | That work merged (core #266) as a mail-only store, `internal/mailconfig`, built on `internal/secretbox` and keyed by `MFA_KEY_KEK` | Task 18 reuses `secretbox` and the same cipher instance. It stores the sealed key in a column on `metadata_fill_state` and does not bend `mailconfig` into a general store. |
| Compose consumers in this repo (PR 5, "M") | The api's env block is the `x-api-env` anchor in **`vidra-core/docker-compose.yml`**, which meta `include:`s | The compose lines ship in core (Task 3). Meta gets only `env/production.env.example` and the runbook. |
| "Custom categories are sent as label only" beside the 18 built-ins | A non-empty `instance_custom_categories` **replaces** the built-ins | Descriptions attach only when an option's id *and* label match a built-in. |
| Federation "sees it like a human edit" | The federated video object carries neither category nor language | The Update is still sent through the hook and is harmless, but remote peers learn nothing new. The plan states this and does not change federation. |
| Search upsert is "an explicit app-level call" | It is also registered as a `video.WithUpdateHook` (`cmd/api/main.go:1386-1398`) | Firing `s.onUpdate` reaches search, federation and the IPFS sync, and that is enough. |
| Eligibility "mirrors the search index" | The only SQL predicate is `search_outbox.sql:116-118`: public, published, `NOT au.unlisted`, `NOT EXISTS video_blocks` | The claim query copies that predicate exactly. Blocked videos must be excluded by the worker itself, because the incremental search path carries no block flag. |
| Migration "0150 is the newest" | Newest is `0151_mail_config` | The plan writes `0152`. Take the next free number when the PR is opened. |
| Leases via `lease_expires_at` | Queue leases here use `next_attempt_at`, and `lease_expires_at` exists only on `job_runs` | The spec's own column is kept, because it is clearer on a table whose `next_attempt_at` means "retry after". `internal/jobrecovery` is **not** extended: expired `running` rows are reclaimed by the worker's own claim query. |
| One PR for "migration + worker + toggle + infra row + wiring" | Both component repos cap a PR at **< 300 changed lines** | The spec's nine PRs become the smaller PRs in §0.3. |

### 0.2 Decisions this plan makes that the owner should confirm

These are not owner rulings. They are the smallest reasonable choice, and each can be reversed in one task:

1. **An automatic fill does not bump `videos.updated_at`.** A human edit does. A backfill of tens of thousands of videos must not re-sort any `updated_at`-ordered listing or look like creator activity. Search and federation are reached through the hooks, not through `updated_at`. Before merging Task 5, grep `ORDER BY .*updated_at` in `internal/store/queries/` and record the result in the PR.
2. **Saving the Studio edit form confirms the shown values.** The edit form resends category and language on every save (`taxonomyFields`, `components/studio/shared.tsx:148-158`), so a save clears the "Set automatically" note even if the creator changed only the title. The creator saw the value and saved it. The alternative is to send only dirty fields, which is a vidra-user behaviour change beyond this slice.
3. **The marker is `applied IS NOT NULL AND applied = current value`.** A human edit through the API clears `*_applied`. The equality check also hides the marker when a PeerTube re-sync overwrites the field, a path that does not go through `video.Service`.
4. **The status card lives on the Infrastructure page**, beside `MailTestCard`, not on the VOD config page. `AdminInstanceConfigView` is a generic renderer, and the infrastructure page already hosts the equivalent card. The toggle's warning points there.
5. **The worker runs on every worker-role replica** (`Jitter: true`) and relies on insert-as-claim for exclusion, as the spec designs. It is not leader-gated like the storyboard backfill.
6. **Pausing.** When Jev rejects the key (`auth`), every replica waits 15 minutes. When it rate-limits (`rate_limited`), they wait 2 minutes. The pause is stored in `metadata_fill_state` so all replicas and the status endpoint agree. No per-video attempt is spent.

### 0.3 PR map

Each PR is merged before the next one starts. Each happens in its own worktree (`superpowers-extended-cc:using-git-worktrees`), and `git branch --show-current` runs before every commit and push. Line counts are estimates. If a PR goes over 300 changed lines, split it along the task boundaries listed and never inside one.

| PR | Repo | Tasks | Depends on |
|---|---|---|---|
| C1 | core | 1: extract `internal/breaker` | none |
| C2 | core | 2: `internal/judgment` client | C1 |
| C3 | core | 3: env config, compose consumers, `.env.example`, denylist | C2 |
| C4 | core | 4: migration 0152 and sqlc queries | C3 |
| C5 | core | 5: `video.Service.ApplyInferredMetadata`, human-edit clear, `AutoFilled` | C4 |
| C6 | core | 6: `metadatafill` request builder and decision (pure) | C5 |
| C7 | core | 7: `metadatafill.Service.Tick` | C6 |
| C8 | core | 8: setting toggle, infrastructure row, `main.go` wiring, integration test | C7 |
| C9 | core | 9: admin endpoints, runs, audit, OpenAPI | C8 |
| C10 | core | 10: `auto_filled` on the video view, OpenAPI | C9 |
| C11 | core | 11: `evaluate-metadata` subcommand | C8 |
| M1 | meta | 12: env example block and runbook | C3 |
| U1 | user | 13: codegen, toggle and warning, infrastructure labels, API wrappers | C10 |
| U2 | user | 14: `MetadataFillCard` | U1 |
| U3 | user | 15: Studio marker and mocked e2e | U1 |
| C12 | core | 16: `jev-stub` compose profile | C8 |
| U4 | user | 17: backed e2e spec and optional-workflow job (**touches `.github/workflows`: that is this PR's task**) | U3, C12 |
| C13 | core | 18: sealed key setting | C9 |
| U5 | user | 19: key field on the card | U2, C13 |
| M2 | meta | 20: beta evaluation record, bars, scope-ledger note | C11 released and deployed |

Nothing is released by this plan. A core release that contains C1–C11 is safe to deploy because the feature is off by default. Cutting the release is the owner's step (`! ./deploy/release.sh --yes vX.Y.Z`).

### 0.4 Verification gates (from each repo's AGENTS.md; paste the tail into every PR)

- **core:** `make ci` (fmt-check, vet, migrate-lint, openapi-verify, sqlc-verify, test-race), plus `go vet -tags=integration ./...`. For Tasks 4, 5 and 8, also run the integration suite against live Postgres:
  ```
  docker compose --profile core up -d postgres redis
  make migrate-up
  DATABASE_URL=postgres://vidra:vidra@localhost:5432/vidra?sslmode=disable \
  REDIS_URL=redis://localhost:6379/0 go test -tags=integration ./internal/store/... ./internal/metadatafill/...
  ```
  If docker is unavailable, say so in the PR.
- **user:** `npx tsc --noEmit && npm run lint && npm run lint:icons && npm run test`. Do not run the e2e suites locally; CI runs them. Name anything you did not run.
- **meta:** `bash -n`/`shellcheck` on touched scripts, the compose `config -q` gate, and `python3 -m unittest discover -s tests -p '*_test.py'`.

PR titles follow `[claude] <area>: <summary>`. The body opens with a one-line WHY.

---

## File structure

**vidra-core**

| File | Responsibility |
|---|---|
| `internal/breaker/breaker.go` (new) | Consecutive-failure circuit breaker, moved from searchclient unchanged |
| `internal/breaker/breaker_test.go` (new) | Open, cooldown, half-open probe, failed probe |
| `internal/searchclient/breaker.go` (deleted) | none |
| `internal/searchclient/client.go` | Uses `*breaker.Breaker` |
| `internal/judgment/judgment.go` (new) | Types, error codes, `Client.Ask` over `POST /v1/systemone` |
| `internal/judgment/judgment_test.go` (new) | `httptest` stand-in for every outcome |
| `internal/config/config.go` | `TypeSafe*` and `MetadataAutofillEnabled` fields, parsing, validation |
| `docker-compose.yml` | `x-api-env` consumers, and the `jev-stub` profile (Task 16) |
| `.env.example` | Documented keys |
| `internal/observability/audit.go` | Denylist entries and new audit actions |
| `migrations/0152_metadata_autofill.{up,down}.sql` (new) | Three tables and the run projection trigger |
| `internal/store/queries/metadata_fill.sql` (new) | Every query the worker, service, handlers and evaluator use |
| `internal/video/inferred.go` (new) | `ApplyInferredMetadata`, `AutoFilled`, `InferredApplied` |
| `internal/video/service.go` | Repository interface additions and the human-edit clear in `UpdateForActor` |
| `internal/metadatafill/request.go` (new) | Builds state and questions, maps answers back to ids, applies the bars |
| `internal/metadatafill/service.go` (new) | Tick, claim, judge, record, apply, pause, runs, status |
| `internal/metadatafill/key.go` (new, Task 18) | Sealed-then-env key resolution |
| `internal/instancesettings/service.go` | `KeyMetadataAutofillEnabled` registry row and default |
| `internal/httpapi/admin_infra.go` | `metadata_autofill` feature row and notes |
| `internal/httpapi/admin_metadata_fill.go` (new) | Status, test, runs, key handlers |
| `internal/httpapi/errors.go` | `MetadataFillError` typed error |
| `internal/httpapi/videos.go` | `auto_filled` on the owner/staff detail view |
| `cmd/api/main.go` | Construction, hooks, worker start, subcommand dispatch |
| `cmd/api/evaluate_metadata.go` (new) | `api evaluate-metadata` |
| `api/openapi.yaml` | New routes, schemas, `auto_filled`, infrastructure key list |
| `scripts/dev/jevstub.py` (new, Task 16) | Deterministic stand-in for `/v1/systemone` |

**vidra-user**

| File | Responsibility |
|---|---|
| `lib/api/generated.ts` | Regenerated only, never hand-edited |
| `lib/api/types.ts`, `lib/api/endpoints.ts` | Aliases and four or five wrappers |
| `lib/admin-config-ia.ts` | VOD `autofill` section and the `metadata_autofill_enabled` META entry with `warn` |
| `components/AdminInfrastructureView.tsx` | Label, config link, card placement |
| `components/admin/MetadataFillCard.tsx` (new) | Status, counts, Test connection, Fill existing / Stop, key field (Task 19) |
| `components/studio/shared.tsx` | `TaxonomySelect` `autoFilled` note |
| `components/studio/VideoRow.tsx` | Passes the flag |
| `e2e/studio.spec.ts`, `e2e/admin-infrastructure.spec.ts` | Mocked coverage |
| `e2e-backed/metadata-autofill.spec.ts` (new) | Real stack against the stub |

**meta**

| File | Responsibility |
|---|---|
| `env/production.env.example` | Four keys with the privacy statement |
| `docs/metadata-autofill.md` (new) | Operator runbook |
| `docs/metadata-autofill-evaluation-<date>.md` (new, Task 20) | The measured bars |
| `docs/release-readiness.md` | Scope-ledger note (Task 20) |

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

- [ ] **Step 4: Point searchclient at it.** Run `git rm internal/searchclient/breaker.go`. In `client.go`, import `github.com/vidra/vidra-core/internal/breaker`, change the field to `breakers map[group]*breaker.Breaker`, construct with `breaker.New(c.now)`, whatever the current `newBreaker` argument is, and rename the call sites `b.allow()`→`b.Allow()`, `b.failure()`→`b.Failure()`, `b.success()`→`b.Success()`, `isOpen()`→`IsOpen()`. In the two test files, rename `.failure()`→`.Failure()` and `breakerCooldown`→`breaker.Cooldown`. Find every site with `grep -rn 'breakerCooldown\|breakerThreshold\|\.allow()\|\.failure()\|\.success()\|isOpen()\|newBreaker' internal/searchclient`.

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
- [ ] 401 or 403 gives `auth`. 429 gives `rate_limited`. 400 or 422 gives `invalid_request`. 5xx, 529, a transport error or a timeout gives `unavailable`. A malformed body, a body over the cap, a missing answer, or a pick outside the options gives `bad_response`. An empty key gives `not_configured`, and no request is made.
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
type Error struct{ Code Code }

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
	case resp.StatusCode >= 500:
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
Expected: every test PASSes. `TestAskClassifiesFailures` has 10 subtests.

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

## Task 4: Migration 0152 and the sqlc queries (PR C4, core)

**Goal:** The three tables, the run projection into `job_runs`, and every query the later tasks call, proven against real Postgres.

**Files:**
- Create: `migrations/0152_metadata_autofill.up.sql`, `migrations/0152_metadata_autofill.down.sql`
- Create: `internal/store/queries/metadata_fill.sql`
- Generated: `internal/store/sqlcgen/metadata_fill.sql.go`, `models.go` (run `make sqlc`, never hand-edit)
- Create: `internal/store/metadata_fill_integration_test.go`

**Acceptance Criteria:**
- [ ] `make migrate-up` then `migrate down 1` then `migrate up` round-trips cleanly, and `make migrate-lint` passes.
- [ ] `ClaimNewMetadataJudgments` returns only public, published, unblocked videos of non-unlisted owners with an empty category or language and no judgment row, honouring `since`.
- [ ] Two concurrent `ClaimNewMetadataJudgments` calls return disjoint sets whose union covers every eligible video.
- [ ] `ApplyInferredMetadata` writes only empty fields on a still public+published video, reports which fields it wrote, and leaves `updated_at` alone.
- [ ] Only one `metadata_fill_runs` row can be `running`: a second insert violates `metadata_fill_runs_one_running_idx`.
- [ ] Inserting and then updating a run produces one `job_runs` row (`queue='metadata_fill_runs'`) whose state follows it.

**Verify:** The integration command in §0.4 with `-run MetadataFill`. All tests PASS.

**Steps:**

- [ ] **Step 1: Write `migrations/0152_metadata_autofill.up.sql`**

```sql
-- Automatic category & language via TypeSafe Jev (meta spec
-- 2026-09-20-jev-metadata-autofill-design.md). Three tables; `videos` and its
-- hot queries are untouched.

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
    language_pick    TEXT,   -- language code; NULL = unclear
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

-- Single row. enabled_since is when the feature last became ACTIVE (toggle on
-- AND a key resolves): videos updated at or after it are filled automatically;
-- everything older waits for an operator-started run. The pause columns let
-- every replica, and the status endpoint, agree that Jev rejected the key or
-- rate-limited us.
CREATE TABLE metadata_fill_state (
    singleton      BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
    enabled_since  TIMESTAMPTZ,
    paused_until   TIMESTAMPTZ,
    paused_code    TEXT CHECK (paused_code IS NULL OR paused_code ~ '^[a-z_]{1,32}$'),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO metadata_fill_state (singleton) VALUES (TRUE) ON CONFLICT DO NOTHING;

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
-- At most one running run; a racing second POST fails on this index (409).
CREATE UNIQUE INDEX metadata_fill_runs_one_running_idx
    ON metadata_fill_runs ((TRUE)) WHERE state = 'running';

-- Operational projection (0083): one job_runs row per RUN, never per video.
-- Its own small function per the 0107/0120 convention: sync_legacy_job_run()
-- raises on an unknown table.
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
        type, queue, source_id, state, stage, progress_percent, priority, attempt,
        resource_type, resource_id, input_metadata, output_metadata,
        error_class, error_code, error_detail, error_retryable,
        created_at, started_at, updated_at, finished_at
    ) VALUES (
        'metadata_fill', 'metadata_fill_runs', NEW.id::text, canonical_state,
        '', NULL, 0, 1, 'instance', '',
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

Before running it, check two things against `migrations/0083_operational_job_runs.up.sql` and `0133`: that `job_events.kind` accepts `'started'`/`'cancelled'`/`'succeeded'` (copy the CHECK list if one exists), and that `progress_percent`/`error_retryable` accept NULL. If either CHECK rejects a value, use the nearest allowed one and note it in a comment.

- [ ] **Step 2: Write `migrations/0152_metadata_autofill.down.sql`**

```sql
DROP TRIGGER IF EXISTS metadata_fill_runs_operational_projection ON metadata_fill_runs;
DROP FUNCTION IF EXISTS sync_metadata_fill_run_job_run();
DELETE FROM job_runs WHERE queue = 'metadata_fill_runs';
DROP TABLE IF EXISTS metadata_fill_runs;
DROP TABLE IF EXISTS metadata_fill_state;
DROP TABLE IF EXISTS video_metadata_judgments;
```

- [ ] **Step 3: Write `internal/store/queries/metadata_fill.sql`**

```sql
-- Eligibility mirrors ListVideoSearchDocsPage (search_outbox.sql:116-118): the
-- worker never sends a video the instance does not already serve in discovery.

-- name: ClaimNewMetadataJudgments :many
-- The INSERT is the claim: the primary key makes two replicas' claims
-- disjoint. `since` NULL lifts the cutoff (an operator run is active).
INSERT INTO video_metadata_judgments (video_id, state, attempts, lease_expires_at)
SELECT v.id, 'running', 1, now() + interval '5 minutes'
FROM videos v
JOIN channels c ON c.id = v.channel_id
JOIN users au ON au.id = c.owner_id
WHERE v.privacy = 'public' AND v.state = 'published'
  AND NOT au.unlisted
  AND NOT EXISTS (SELECT 1 FROM video_blocks b WHERE b.video_id = v.id)
  AND (NULLIF(v.category, '') IS NULL OR NULLIF(v.language, '') IS NULL)
  AND (sqlc.narg('since')::timestamptz IS NULL OR v.updated_at >= sqlc.narg('since')::timestamptz)
  AND NOT EXISTS (SELECT 1 FROM video_metadata_judgments j WHERE j.video_id = v.id)
ORDER BY v.updated_at DESC
LIMIT sqlc.arg('lim')::int
ON CONFLICT (video_id) DO NOTHING
RETURNING video_id;

-- name: ClaimDueMetadataJudgments :many
-- Retries whose backoff elapsed, plus claims a dead replica left running.
UPDATE video_metadata_judgments
SET state = 'running', attempts = attempts + 1, lease_expires_at = now() + interval '5 minutes'
WHERE video_id IN (
    SELECT video_id FROM video_metadata_judgments
    WHERE (state = 'pending' AND next_attempt_at <= now())
       OR (state = 'running' AND lease_expires_at <= now())
    ORDER BY next_attempt_at
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

-- name: RecordMetadataJudgment :exec
UPDATE video_metadata_judgments
SET state = 'done', model = sqlc.arg('model'), judged_at = now(),
    category_pick = sqlc.narg('category_pick'), category_prob = sqlc.narg('category_prob'),
    language_pick = sqlc.narg('language_pick'), language_prob = sqlc.narg('language_prob'),
    lease_expires_at = NULL, last_error_code = NULL
WHERE video_id = sqlc.arg('video_id');

-- name: RecordMetadataJudgmentFailure :exec
UPDATE video_metadata_judgments
SET state = CASE WHEN attempts >= sqlc.arg('max_attempts')::int THEN 'failed' ELSE 'pending' END,
    next_attempt_at = sqlc.arg('next_attempt_at'), lease_expires_at = NULL,
    last_error_code = sqlc.arg('code')
WHERE video_id = sqlc.arg('video_id');

-- name: ReleaseMetadataJudgment :exec
-- Hand a claim back without spending an attempt (the whole worker paused).
UPDATE video_metadata_judgments
SET state = 'pending', attempts = GREATEST(attempts - 1, 0),
    next_attempt_at = sqlc.arg('next_attempt_at'), lease_expires_at = NULL
WHERE video_id = sqlc.arg('video_id');

-- name: DeleteMetadataJudgment :exec
-- The video stopped being eligible before it was judged; forget the claim so
-- it becomes eligible again if it is republished.
DELETE FROM video_metadata_judgments WHERE video_id = $1;

-- name: ApplyInferredMetadata :one
-- Guarded write: fills only EMPTY fields on a video that is STILL public and
-- published, locks the row against a concurrent human edit, reports which
-- fields it wrote, and deliberately does not bump updated_at.
WITH cur AS (
    SELECT id,
           (NULLIF(category, '') IS NULL AND sqlc.narg('category')::text IS NOT NULL) AS write_category,
           (NULLIF(language, '') IS NULL AND sqlc.narg('language')::text IS NOT NULL) AS write_language
    FROM videos
    WHERE id = sqlc.arg('id') AND privacy = 'public' AND state = 'published'
    FOR UPDATE
)
UPDATE videos v
SET category = CASE WHEN cur.write_category THEN sqlc.narg('category')::text ELSE v.category END,
    language = CASE WHEN cur.write_language THEN sqlc.narg('language')::text ELSE v.language END
FROM cur
WHERE v.id = cur.id AND (cur.write_category OR cur.write_language)
RETURNING cur.write_category::bool AS category_written, cur.write_language::bool AS language_written;

-- name: SetInferredApplied :exec
UPDATE video_metadata_judgments
SET category_applied = COALESCE(sqlc.narg('category_applied'), category_applied),
    language_applied = COALESCE(sqlc.narg('language_applied'), language_applied)
WHERE video_id = sqlc.arg('video_id');

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
SELECT enabled_since, paused_until, paused_code FROM metadata_fill_state WHERE singleton;

-- name: MarkMetadataFillActive :exec
-- First replica to see the feature active stamps the moment; later ones no-op.
UPDATE metadata_fill_state SET enabled_since = now(), updated_at = now()
WHERE singleton AND enabled_since IS NULL;

-- name: MarkMetadataFillInactive :exec
UPDATE metadata_fill_state SET enabled_since = NULL, updated_at = now()
WHERE singleton AND enabled_since IS NOT NULL;

-- name: SetMetadataFillPause :exec
UPDATE metadata_fill_state
SET paused_until = sqlc.narg('paused_until'), paused_code = sqlc.narg('paused_code'), updated_at = now()
WHERE singleton;

-- name: GetRunningMetadataFillRun :one
SELECT * FROM metadata_fill_runs WHERE state = 'running';

-- name: CreateMetadataFillRun :one
INSERT INTO metadata_fill_runs (started_by) VALUES ($1) RETURNING *;

-- name: RequeueFailedMetadataJudgments :execrows
UPDATE video_metadata_judgments
SET state = 'pending', attempts = 0, next_attempt_at = now(), last_error_code = NULL
WHERE state = 'failed';

-- name: FinishMetadataFillRun :execrows
UPDATE metadata_fill_runs
SET state = sqlc.arg('state'), finished_at = now(), updated_at = now()
WHERE id = sqlc.arg('id') AND state = 'running';

-- name: AddMetadataFillRunCounts :exec
UPDATE metadata_fill_runs
SET judged = judged + sqlc.arg('judged')::int, filled = filled + sqlc.arg('filled')::int, updated_at = now()
WHERE id = sqlc.arg('id') AND state = 'running';

-- name: CountMetadataJudgments :one
SELECT
  count(*) FILTER (WHERE state IN ('pending','running'))::bigint AS waiting,
  count(*) FILTER (WHERE category_applied IS NOT NULL OR language_applied IS NOT NULL)::bigint AS filled,
  count(*) FILTER (WHERE state = 'done' AND category_applied IS NULL AND language_applied IS NULL)::bigint AS not_confident,
  count(*) FILTER (WHERE state = 'failed')::bigint AS failed
FROM video_metadata_judgments;

-- name: CountUnjudgedEligibleVideos :one
SELECT count(*)::bigint
FROM videos v
JOIN channels c ON c.id = v.channel_id
JOIN users au ON au.id = c.owner_id
WHERE v.privacy = 'public' AND v.state = 'published'
  AND NOT au.unlisted
  AND NOT EXISTS (SELECT 1 FROM video_blocks b WHERE b.video_id = v.id)
  AND (NULLIF(v.category, '') IS NULL OR NULLIF(v.language, '') IS NULL)
  AND NOT EXISTS (SELECT 1 FROM video_metadata_judgments j WHERE j.video_id = v.id);

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

- [ ] **Step 4: Generate** with `make sqlc && make sqlc-verify`. Expected: no diff after generation, and `sqlcgen.ClaimNewMetadataJudgmentsParams{Since pgtype.Timestamptz; Lim int32}` and the other params structs exist. Read the generated names and use them verbatim in Tasks 5–11. The plan's later code assumes the names sqlc derives from the query names above.

- [ ] **Step 5: Write the failing integration test** `internal/store/metadata_fill_integration_test.go`. It uses the store package's existing `dsn(t)` and fixture helpers (`internal/store/integration_test.go`); find the helpers that insert a user, a channel and a video, which other `*_integration_test.go` files in the package already use.

```go
//go:build integration

package store

import (
	"context"
	"sync"
	"testing"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgtype"

	"github.com/vidra/vidra-core/internal/store/sqlcgen"
)

func TestMetadataFillClaimEligibility(t *testing.T) {
	ctx := context.Background()
	st, err := New(ctx, dsn(t))
	if err != nil {
		t.Fatal(err)
	}
	q := st.Queries()
	f := newMetadataFillFixture(t, ctx, st) // see helper below
	eligible := f.video(t, "public", "published", nil, nil)
	_ = f.video(t, "private", "published", nil, nil)          // private
	_ = f.video(t, "public", "draft", nil, nil)               // not published
	_ = f.video(t, "public", "published", strp("10"), strp("en")) // nothing empty
	blocked := f.video(t, "public", "published", nil, nil)
	f.block(t, blocked)

	got, err := q.ClaimNewMetadataJudgments(ctx, sqlcgen.ClaimNewMetadataJudgmentsParams{Lim: 100})
	if err != nil {
		t.Fatal(err)
	}
	if !containsOnly(got, eligible, f.all()) {
		t.Fatalf("claimed %v, want exactly the one eligible video %s among the fixture's", got, eligible)
	}
	again, _ := q.ClaimNewMetadataJudgments(ctx, sqlcgen.ClaimNewMetadataJudgmentsParams{Lim: 100})
	if containsAny(again, f.all()) {
		t.Fatal("a judged video was claimed twice")
	}
}

func TestMetadataFillConcurrentClaimsAreDisjoint(t *testing.T) {
	ctx := context.Background()
	st, err := New(ctx, dsn(t))
	if err != nil {
		t.Fatal(err)
	}
	f := newMetadataFillFixture(t, ctx, st)
	for i := 0; i < 40; i++ {
		f.video(t, "public", "published", nil, nil)
	}
	var mu sync.Mutex
	seen := map[uuid.UUID]int{}
	var wg sync.WaitGroup
	for w := 0; w < 4; w++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			ids, err := st.Queries().ClaimNewMetadataJudgments(ctx, sqlcgen.ClaimNewMetadataJudgmentsParams{Lim: 25})
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
	for _, id := range f.all() {
		if seen[id] > 1 {
			t.Fatalf("video %s claimed %d times", id, seen[id])
		}
	}
}

func TestApplyInferredMetadataGuards(t *testing.T) {
	ctx := context.Background()
	st, err := New(ctx, dsn(t))
	if err != nil {
		t.Fatal(err)
	}
	q := st.Queries()
	f := newMetadataFillFixture(t, ctx, st)
	v := f.video(t, "public", "published", strp("10"), nil) // category set by a human
	before := f.updatedAt(t, v)
	row, err := q.ApplyInferredMetadata(ctx, sqlcgen.ApplyInferredMetadataParams{ID: v, Category: strp("2"), Language: strp("en")})
	if err != nil {
		t.Fatal(err)
	}
	if row.CategoryWritten || !row.LanguageWritten {
		t.Fatalf("written = %+v, want language only", row)
	}
	if c, l := f.taxonomy(t, v); c != "10" || l != "en" {
		t.Fatalf("taxonomy = %q/%q, want the human category kept", c, l)
	}
	if !f.updatedAt(t, v).Equal(before) {
		t.Fatal("an automatic fill must not bump updated_at")
	}
	priv := f.video(t, "private", "published", nil, nil)
	if _, err := q.ApplyInferredMetadata(ctx, sqlcgen.ApplyInferredMetadataParams{ID: priv, Language: strp("en")}); err == nil {
		t.Fatal("a private video was written (want pgx.ErrNoRows)")
	}
}

func TestMetadataFillOneRunningRunAndProjection(t *testing.T) {
	ctx := context.Background()
	st, err := New(ctx, dsn(t))
	if err != nil {
		t.Fatal(err)
	}
	q := st.Queries()
	f := newMetadataFillFixture(t, ctx, st)
	run, err := q.CreateMetadataFillRun(ctx, pgtype.UUID{Bytes: f.admin, Valid: true})
	if err != nil {
		t.Fatal(err)
	}
	if _, err := q.CreateMetadataFillRun(ctx, pgtype.UUID{Bytes: f.admin, Valid: true}); err == nil {
		t.Fatal("a second running run was allowed")
	}
	if got := f.jobRunState(t, run.ID); got != "running" {
		t.Fatalf("projected state = %q, want running", got)
	}
	if n, _ := q.FinishMetadataFillRun(ctx, sqlcgen.FinishMetadataFillRunParams{ID: run.ID, State: "stopped"}); n != 1 {
		t.Fatal("stop did not update the run")
	}
	if got := f.jobRunState(t, run.ID); got != "cancelled" {
		t.Fatalf("projected state = %q, want cancelled", got)
	}
}

func strp(s string) *string { return &s }
```

Put `newMetadataFillFixture` (methods `video`, `block`, `all`, `updatedAt`, `taxonomy`, `jobRunState`, and an `admin` user id), `containsOnly` and `containsAny` in the same file. Build them on the package's existing insert helpers, or plain `st.Pool().Exec` SQL if there are none. `t.Cleanup` must delete the fixture's rows, and because the claim test shares a database with other tests, assertions stay scoped to the fixture's ids. Fixture videos use unique channel handles (`"mf-" + uuid.NewString()[:8]`).

- [ ] **Step 6: Run** the §0.4 integration command with `-run 'MetadataFill|ApplyInferred'`. Expected: 4 PASS. Also run `go vet -tags=integration ./...` and `make ci`.

- [ ] **Step 7: Commit**

```bash
git add migrations/0152_* internal/store/queries/metadata_fill.sql internal/store/sqlcgen internal/store/metadata_fill_integration_test.go
git commit -m "feat(store): metadata auto-fill tables, run projection and queries (0152)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 5: `video.Service.ApplyInferredMetadata`, the human-edit clear, `AutoFilled` (PR C5, core)

**Goal:** An automatic fill has the same hook side effects as a human edit, a human edit clears the marker, and callers can ask which fields are auto-filled.

**Files:**
- Create: `internal/video/inferred.go`, `internal/video/inferred_test.go`
- Modify: `internal/video/service.go` (`Repository` interface near L134-174; `UpdateForActor` after the `repo.UpdateVideo` call, L2089-2107)
- Modify: the video package's in-memory fake repo (find it with `grep -rln 'func (f \*fakeRepo) UpdateVideo' internal/video`)

**Acceptance Criteria:**
- [ ] `ApplyInferredMetadata` drops values that are not in the live vocabulary (`IsCategory`, `IsLanguage`) before writing.
- [ ] It fires every `onUpdate` hook with `wasFederated=true` only when something was written.
- [ ] It records what it wrote in `*_applied`.
- [ ] A guarded write that matched nothing (`pgx.ErrNoRows`) returns an empty result and no error, and fires no hooks.
- [ ] `UpdateForActor` with `Category` and/or `Language` set calls `ClearInferredApplied` for exactly those fields, including when the value equals the current one.
- [ ] `AutoFilled` returns `[]string{"category","language"}` subsets, and `nil` when there is no judgment row.

**Verify:** `go test ./internal/video/ -race -run 'Inferred|AutoFilled|ClearsInferred'` shows every test PASS.

**Steps:**

- [ ] **Step 1: Add to the `Repository` interface**

```go
	ApplyInferredMetadata(ctx context.Context, arg sqlcgen.ApplyInferredMetadataParams) (sqlcgen.ApplyInferredMetadataRow, error)
	SetInferredApplied(ctx context.Context, arg sqlcgen.SetInferredAppliedParams) error
	ClearInferredApplied(ctx context.Context, arg sqlcgen.ClearInferredAppliedParams) error
	GetVideoAutoFilled(ctx context.Context, videoID uuid.UUID) (sqlcgen.GetVideoAutoFilledRow, error)
```

Add the matching methods to the fake repo. They record calls, and `ApplyInferredMetadata` mirrors the SQL: it writes only empty fields on a public+published fake video and returns `pgx.ErrNoRows` when the guard fails.

- [ ] **Step 2: Failing tests** `internal/video/inferred_test.go`. Build the service the way the package's other tests do, with the fake repo, `NewService(repo, nil, WithUpdateHook(...))`, and a helper that seeds a fake video with a privacy, state, category and language.

```go
package video

import (
	"context"
	"testing"

	"github.com/google/uuid"
)

func TestApplyInferredMetadataFillsEmptyAndFiresHooks(t *testing.T) {
	repo := newFakeRepo()
	var fired []bool
	svc := NewService(repo, nil, WithUpdateHook(func(_ context.Context, _ uuid.UUID, was bool) { fired = append(fired, was) }))
	id := repo.seedVideo(t, "public", "published", nil, nil)

	got, err := svc.ApplyInferredMetadata(context.Background(), id, ptr("10"), ptr("en"))
	if err != nil {
		t.Fatal(err)
	}
	if got.Category == nil || *got.Category != "10" || got.Language == nil || *got.Language != "en" {
		t.Fatalf("applied = %+v", got)
	}
	if len(fired) != 1 || !fired[0] {
		t.Fatalf("hooks = %v, want one call with wasFederated=true", fired)
	}
	if a := repo.applied[id]; a.CategoryApplied == nil || *a.CategoryApplied != "10" {
		t.Fatalf("*_applied not recorded: %+v", a)
	}
}

func TestApplyInferredMetadataDropsUnknownVocabulary(t *testing.T) {
	repo := newFakeRepo()
	svc := NewService(repo, nil)
	id := repo.seedVideo(t, "public", "published", nil, nil)
	got, err := svc.ApplyInferredMetadata(context.Background(), id, ptr("9999"), ptr("xx"))
	if err != nil || got.Category != nil || got.Language != nil || repo.applyCalls != 0 {
		t.Fatalf("got=%+v err=%v calls=%d; unknown values must never reach the write", got, err, repo.applyCalls)
	}
}

func TestApplyInferredMetadataNoOpWhenNoLongerPublic(t *testing.T) {
	repo := newFakeRepo()
	hooks := 0
	svc := NewService(repo, nil, WithUpdateHook(func(context.Context, uuid.UUID, bool) { hooks++ }))
	id := repo.seedVideo(t, "unlisted", "published", nil, nil)
	got, err := svc.ApplyInferredMetadata(context.Background(), id, ptr("10"), nil)
	if err != nil || got.Category != nil || hooks != 0 {
		t.Fatalf("got=%+v err=%v hooks=%d, want a silent no-op", got, err, hooks)
	}
}

func TestUpdateClearsInferredAppliedEvenOnSameValue(t *testing.T) {
	repo := newFakeRepo()
	svc := NewService(repo, nil)
	id := repo.seedVideo(t, "public", "published", ptr("10"), ptr("en"))
	owner := repo.videos[id].OwnerID
	if _, err := svc.Update(context.Background(), owner, id, UpdateInput{Category: ptr("10")}); err != nil {
		t.Fatal(err)
	}
	c := repo.lastClear
	if c == nil || c.VideoID != id || !c.Category || c.Language {
		t.Fatalf("clear = %+v, want category only", c)
	}
}

func TestUpdateWithoutTaxonomyDoesNotClear(t *testing.T) {
	repo := newFakeRepo()
	svc := NewService(repo, nil)
	id := repo.seedVideo(t, "public", "published", nil, nil)
	if _, err := svc.Update(context.Background(), repo.videos[id].OwnerID, id, UpdateInput{Title: ptr("t")}); err != nil {
		t.Fatal(err)
	}
	if repo.lastClear != nil {
		t.Fatal("a title-only edit cleared the auto-fill marker")
	}
}

func TestAutoFilled(t *testing.T) {
	repo := newFakeRepo()
	svc := NewService(repo, nil)
	id := repo.seedVideo(t, "public", "published", nil, nil)
	if got, _ := svc.AutoFilled(context.Background(), id); got != nil {
		t.Fatalf("no row: got %v, want nil", got)
	}
	repo.autoFilled[id] = [2]bool{false, true}
	if got, _ := svc.AutoFilled(context.Background(), id); len(got) != 1 || got[0] != "language" {
		t.Fatalf("got %v, want [language]", got)
	}
}

func ptr(s string) *string { return &s }
```

If the package already has a `ptr`/`strPtr` helper, use it and drop the duplicate. The fake's fields (`applied`, `applyCalls`, `lastClear`, `autoFilled`, `seedVideo`) are additions to the existing fake. Categories "10" and language "en" are in the built-in lists (`internal/video/config.go:19-38`, `:55-86`).

- [ ] **Step 3: Run them and watch them fail**

Run: `go test ./internal/video/ -run 'Inferred|AutoFilled|ClearsInferred'`
Expected: FAIL with `svc.ApplyInferredMetadata undefined`.

- [ ] **Step 4: Write `internal/video/inferred.go`**

```go
package video

import (
	"context"
	"errors"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"github.com/vidra/vidra-core/internal/store/sqlcgen"
)

// InferredApplied reports which values an automatic fill actually wrote.
type InferredApplied struct {
	Category *string
	Language *string
}

// ApplyInferredMetadata writes machine-chosen category/language into EMPTY
// fields of a video that is still public and published, then fires the same
// onUpdate hooks a human edit fires (search upsert, federation Update, IPFS
// sync). It never overwrites a value, validates against the LIVE vocabulary
// (a custom category deleted since the judgment is dropped), and does not bump
// updated_at: a backfill must not look like creator activity.
func (s *Service) ApplyInferredMetadata(ctx context.Context, id uuid.UUID, category, language *string) (InferredApplied, error) {
	if category != nil && !IsCategory(*category) {
		category = nil
	}
	if language != nil && !IsLanguage(*language) {
		language = nil
	}
	if category == nil && language == nil {
		return InferredApplied{}, nil
	}
	row, err := s.repo.ApplyInferredMetadata(ctx, sqlcgen.ApplyInferredMetadataParams{ID: id, Category: category, Language: language})
	if errors.Is(err, pgx.ErrNoRows) {
		return InferredApplied{}, nil // no longer public+published, or a human filled both first
	}
	if err != nil {
		return InferredApplied{}, err
	}
	var out InferredApplied
	if row.CategoryWritten {
		out.Category = category
	}
	if row.LanguageWritten {
		out.Language = language
	}
	if err := s.repo.SetInferredApplied(ctx, sqlcgen.SetInferredAppliedParams{
		VideoID: id, CategoryApplied: out.Category, LanguageApplied: out.Language,
	}); err != nil {
		return out, err
	}
	// The guard required public+published, so peers already hold this video.
	for _, hook := range s.onUpdate {
		hook(ctx, id, true)
	}
	return out, nil
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

In `UpdateForActor`, directly after the `if err != nil { return sqlcgen.Video{}, err }` that follows `s.repo.UpdateVideo(...)`, insert:

```go
	// A human set the field: the Studio "set automatically" marker must never
	// claim their value, including when they re-selected the machine's pick.
	if in.Category != nil || in.Language != nil {
		if err := s.repo.ClearInferredApplied(ctx, sqlcgen.ClearInferredAppliedParams{
			VideoID: id, Category: in.Category != nil, Language: in.Language != nil,
		}); err != nil {
			return sqlcgen.Video{}, err
		}
	}
```

If the video package imports a different `pgx` major or wraps no-rows in its own sentinel (`grep -n 'ErrNoRows' internal/video/service.go`), use that.

- [ ] **Step 5: Run them.** `go test ./internal/video/ -race` passes, and so do `make ci` and the §0.4 integration run.

- [ ] **Step 6: Record decision §0.2.1.** Run `grep -rn 'ORDER BY[^;]*updated_at' internal/store/queries/` and paste the result and one sentence into the PR body.

- [ ] **Step 7: Commit**

```bash
git add internal/video
git commit -m "feat(video): ApplyInferredMetadata fires update hooks; human edits clear the marker

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 6: `metadatafill` request builder and decision (PR C6, core)

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

// Decide reads an answer. Vocabulary validation happens once, at apply time
// (video.Service.ApplyInferredMetadata), against the live list.
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

## Task 7: `metadatafill.Service.Tick` (PR C7, core)

**Goal:** One tick claims up to 25 videos, judges them, records raw answers, applies what clears the bars, backs off on transient failures, pauses the whole worker on `auth`/`rate_limited`, and maintains `enabled_since` and runs.

**Files:**
- Create: `internal/metadatafill/service.go`, `internal/metadatafill/service_test.go`

**Acceptance Criteria:**
- [ ] Inactive (toggle off or no key): no claims, and `enabled_since` is cleared.
- [ ] Active: `enabled_since` is stamped on first sight, new claims pass `since=enabled_since`, and a running run passes `since=NULL`.
- [ ] A confident answer records the raw judgment, then calls the applier with the id/code. An unconfident answer records and does not apply.
- [ ] `unavailable`/`bad_response`/`invalid_request` records a failure with backoff `1m·2^(attempts-1)` capped at 1h; `MaxAttempts`=5 makes it `failed`.
- [ ] `auth` pauses 15 minutes and `rate_limited` pauses 2 minutes. Every claim still held in the tick is released without spending an attempt, and later ticks do nothing until `paused_until`.
- [ ] A video that is no longer eligible, or no longer exists, has its claim deleted.
- [ ] A running run with nothing claimed is finished as `done`, and a run's counts are incremented per tick.

**Verify:** `go test ./internal/metadatafill/ -race -v` → PASS.

**Steps:**

- [ ] **Step 1: Failing tests** `internal/metadatafill/service_test.go`, using an in-memory `fakeRepo` that implements `Repository` below. It mirrors the SQL semantics: a claim inserts `running` rows, `ClaimDue` returns due rows, and `ReleaseMetadataJudgment` decrements attempts. `fakeJudge` returns scripted results or errors, and `fakeApplier` records calls.

```go
package metadatafill

import (
	"context"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/vidra/vidra-core/internal/judgment"
	"github.com/vidra/vidra-core/internal/video"
)

func fixture(t *testing.T) (*Service, *fakeRepo, *fakeJudge, *fakeApplier, *time.Time) {
	t.Helper()
	now := time.Date(2026, 9, 26, 12, 0, 0, 0, time.UTC)
	repo, judge, app := newFakeRepo(), &fakeJudge{configured: true}, &fakeApplier{}
	svc := New(repo, judge, app, func() bool { return true },
		WithClock(func() time.Time { return now }),
		WithCategories(func() []video.ConfigOption { return video.Categories }))
	return svc, repo, judge, app, &now
}

func confident() judgment.Result {
	return judgment.Result{Model: "jev-1.13.0", Answers: map[string]judgment.Answer{
		QCategory: {Pick: video.Categories[0].Label, Probabilities: map[string]float64{video.Categories[0].Label: 0.9}},
		QLanguage: {Pick: "en", Probabilities: map[string]float64{"en": 0.99}},
	}}
}

func TestTickIdlesAndClearsWhenInactive(t *testing.T) {
	svc, repo, judge, _, _ := fixture(t)
	judge.configured = false
	repo.enabledSince = ptrTime(time.Unix(1, 0))
	repo.addEligible(uuid.New())
	n, err := svc.Tick(context.Background())
	if err != nil || n != 0 || repo.claims != 0 || repo.enabledSince != nil {
		t.Fatalf("n=%d err=%v claims=%d since=%v", n, err, repo.claims, repo.enabledSince)
	}
}

func TestTickStampsEnabledSinceAndPassesIt(t *testing.T) {
	svc, repo, judge, _, now := fixture(t)
	judge.next = []any{confident()}
	repo.addEligible(uuid.New())
	_, _ = svc.Tick(context.Background())
	if repo.enabledSince == nil || !repo.enabledSince.Equal(*now) {
		t.Fatalf("enabled_since = %v, want %v", repo.enabledSince, *now)
	}
	if repo.lastSince == nil || !repo.lastSince.Equal(*now) {
		t.Fatal("new claims must be cut off at enabled_since")
	}
}

func TestTickRunLiftsCutoffAndFinishes(t *testing.T) {
	svc, repo, judge, _, _ := fixture(t)
	repo.run = &fakeRun{id: uuid.New()}
	repo.addEligible(uuid.New())
	judge.next = []any{confident()}
	_, _ = svc.Tick(context.Background())
	if repo.lastSince != nil {
		t.Fatal("a running run must lift the enabled_since cutoff")
	}
	if repo.run.judged != 1 || repo.run.filled != 1 {
		t.Fatalf("run counts = %d/%d", repo.run.judged, repo.run.filled)
	}
	_, _ = svc.Tick(context.Background())
	if repo.run.state != "done" {
		t.Fatalf("run state = %q, want done once nothing is left", repo.run.state)
	}
}

func TestTickAppliesOnlyConfidentAnswers(t *testing.T) {
	svc, repo, judge, app, _ := fixture(t)
	id := uuid.New()
	repo.addEligible(id)
	res := confident()
	res.Answers[QLanguage] = judgment.Answer{Pick: "en", Probabilities: map[string]float64{"en": 0.5}}
	judge.next = []any{res}
	_, _ = svc.Tick(context.Background())
	if repo.rows[id].state != "done" || repo.rows[id].languagePick == nil {
		t.Fatalf("raw judgment not recorded: %+v", repo.rows[id])
	}
	if len(app.calls) != 1 || app.calls[0].category == nil || app.calls[0].language != nil {
		t.Fatalf("apply = %+v, want category only", app.calls)
	}
}

func TestTickBacksOffThenFails(t *testing.T) {
	svc, repo, judge, _, now := fixture(t)
	id := uuid.New()
	repo.addEligible(id)
	for attempt := 1; attempt <= MaxAttempts; attempt++ {
		judge.next = []any{&judgment.Error{Code: judgment.CodeUnavailable}}
		_, _ = svc.Tick(context.Background())
		r := repo.rows[id]
		if attempt < MaxAttempts {
			want := now.Add(backoff(int32(attempt)))
			if r.state != "pending" || !r.nextAttempt.Equal(want) || r.code != "unavailable" {
				t.Fatalf("attempt %d: %+v, want pending until %v", attempt, r, want)
			}
			*now = r.nextAttempt
		} else if r.state != "failed" {
			t.Fatalf("after %d attempts state = %q, want failed", attempt, r.state)
		}
	}
}

func TestTickPausesOnAuthWithoutSpendingAttempts(t *testing.T) {
	svc, repo, judge, _, now := fixture(t)
	a, b := uuid.New(), uuid.New()
	repo.addEligible(a)
	repo.addEligible(b)
	judge.next = []any{&judgment.Error{Code: judgment.CodeAuth}}
	_, _ = svc.Tick(context.Background())
	if repo.pausedCode != "auth" || !repo.pausedUntil.Equal(now.Add(authPause)) {
		t.Fatalf("pause = %q until %v", repo.pausedCode, repo.pausedUntil)
	}
	for _, id := range []uuid.UUID{a, b} {
		if r := repo.rows[id]; r.state != "pending" || r.attempts != 0 {
			t.Fatalf("%s = %+v, want released with attempts=0", id, r)
		}
	}
	judge.calls = 0
	_, _ = svc.Tick(context.Background())
	if judge.calls != 0 {
		t.Fatal("a paused worker called Jev")
	}
}

func TestTickDropsVideosNoLongerEligible(t *testing.T) {
	svc, repo, judge, _, _ := fixture(t)
	id := uuid.New()
	repo.addEligible(id)
	repo.makeIneligibleAfterClaim[id] = true
	_, _ = svc.Tick(context.Background())
	if _, ok := repo.rows[id]; ok || judge.calls != 0 {
		t.Fatal("an ineligible video must be forgotten, not judged")
	}
}

func ptrTime(t time.Time) *time.Time { return &t }
```

Write `fakeRepo`, `fakeRun`, `fakeJudge` (`next []any` popped per `Ask`: a `judgment.Result` or an `error`; `calls` counter; `configured`) and `fakeApplier` (`calls []struct{ id uuid.UUID; category, language *string }`, returning the inputs as `video.InferredApplied`) in `service_fakes_test.go`. They are about 150 lines and implement exactly the `Repository` interface from Step 3.

- [ ] **Step 2: Run them and watch them fail**

Run: `go test ./internal/metadatafill/`
Expected: FAIL with `undefined: New`.

- [ ] **Step 3: Write `internal/metadatafill/service.go`**

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
	// Batch is the claim size per tick: at 25 per 30 s tick one replica
	// judges ~50 videos a minute, far under the vendor's 1,200 requests/min.
	Batch = 25
	// MaxAttempts transient failures before a video is marked failed. The
	// next operator run returns failed rows to pending.
	MaxAttempts = 5

	backoffBase      = time.Minute
	backoffMax       = time.Hour
	authPause        = 15 * time.Minute
	rateLimitedPause = 2 * time.Minute
)

func backoff(attempts int32) time.Duration {
	d := backoffBase
	for i := int32(1); i < attempts && d < backoffMax; i++ {
		d *= 2
	}
	if d > backoffMax {
		d = backoffMax
	}
	return d
}

// Repository is the data access the worker needs. *sqlcgen.Queries satisfies it.
type Repository interface {
	GetMetadataFillState(ctx context.Context) (sqlcgen.GetMetadataFillStateRow, error)
	MarkMetadataFillActive(ctx context.Context) error
	MarkMetadataFillInactive(ctx context.Context) error
	SetMetadataFillPause(ctx context.Context, arg sqlcgen.SetMetadataFillPauseParams) error
	GetRunningMetadataFillRun(ctx context.Context) (sqlcgen.MetadataFillRun, error)
	FinishMetadataFillRun(ctx context.Context, arg sqlcgen.FinishMetadataFillRunParams) (int64, error)
	AddMetadataFillRunCounts(ctx context.Context, arg sqlcgen.AddMetadataFillRunCountsParams) error
	ClaimDueMetadataJudgments(ctx context.Context, lim int32) ([]sqlcgen.ClaimDueMetadataJudgmentsRow, error)
	ClaimNewMetadataJudgments(ctx context.Context, arg sqlcgen.ClaimNewMetadataJudgmentsParams) ([]uuid.UUID, error)
	GetMetadataFillSubject(ctx context.Context, id uuid.UUID) (sqlcgen.GetMetadataFillSubjectRow, error)
	ListVideoTags(ctx context.Context, videoID uuid.UUID) ([]string, error)
	RecordMetadataJudgment(ctx context.Context, arg sqlcgen.RecordMetadataJudgmentParams) error
	RecordMetadataJudgmentFailure(ctx context.Context, arg sqlcgen.RecordMetadataJudgmentFailureParams) error
	ReleaseMetadataJudgment(ctx context.Context, arg sqlcgen.ReleaseMetadataJudgmentParams) error
	DeleteMetadataJudgment(ctx context.Context, videoID uuid.UUID) error
}

// Judge is the judgment client surface.
type Judge interface {
	Configured(ctx context.Context) bool
	Ask(ctx context.Context, state any, qs map[string]judgment.Question) (judgment.Result, error)
}

// Applier is video.Service's guarded write.
type Applier interface {
	ApplyInferredMetadata(ctx context.Context, id uuid.UUID, category, language *string) (video.InferredApplied, error)
}

// Service is the state-scan worker.
type Service struct {
	repo       Repository
	judge      Judge
	apply      Applier
	enabled    func() bool
	now        func() time.Time
	categories func() []video.ConfigOption
	logger     *slog.Logger
}

// Option customises a Service.
type Option func(*Service)

func WithClock(now func() time.Time) Option                    { return func(s *Service) { s.now = now } }
func WithCategories(f func() []video.ConfigOption) Option      { return func(s *Service) { s.categories = f } }
func WithLogger(l *slog.Logger) Option                          { return func(s *Service) { s.logger = l } }

// New builds the worker. enabled is the runtime toggle, re-read every tick.
func New(repo Repository, judge Judge, apply Applier, enabled func() bool, opts ...Option) *Service {
	s := &Service{repo: repo, judge: judge, apply: apply, enabled: enabled,
		now: time.Now, categories: video.CategoryOptions, logger: slog.Default()}
	for _, o := range opts {
		o(s)
	}
	return s
}

// Enabled is the toggle; Configured is "a key resolves".
func (s *Service) Enabled() bool                         { return s.enabled() }
func (s *Service) Configured(ctx context.Context) bool   { return s.judge.Configured(ctx) }

// claim is one video this tick holds, with its attempt count after claiming.
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
)

// Tick is one jobloop pass. It returns the number of videos judged.
func (s *Service) Tick(ctx context.Context) (int, error) {
	if !s.enabled() || !s.judge.Configured(ctx) {
		return 0, s.repo.MarkMetadataFillInactive(ctx)
	}
	if err := s.repo.MarkMetadataFillActive(ctx); err != nil {
		return 0, err
	}
	st, err := s.repo.GetMetadataFillState(ctx)
	if err != nil {
		return 0, err
	}
	if st.PausedUntil.Valid {
		if s.now().Before(st.PausedUntil.Time) {
			return 0, nil
		}
		if err := s.repo.SetMetadataFillPause(ctx, sqlcgen.SetMetadataFillPauseParams{}); err != nil {
			return 0, err
		}
	}
	run, err := s.repo.GetRunningMetadataFillRun(ctx)
	hasRun := err == nil
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return 0, err
	}

	var claims []claim
	due, err := s.repo.ClaimDueMetadataJudgments(ctx, Batch)
	if err != nil {
		return 0, err
	}
	for _, d := range due {
		claims = append(claims, claim{d.VideoID, d.Attempts})
	}
	if room := Batch - len(claims); room > 0 {
		since := st.EnabledSince
		if hasRun {
			since = pgtype.Timestamptz{}
		}
		ids, err := s.repo.ClaimNewMetadataJudgments(ctx, sqlcgen.ClaimNewMetadataJudgmentsParams{Since: since, Lim: int32(room)})
		if err != nil {
			return 0, err
		}
		for _, id := range ids {
			claims = append(claims, claim{id, 1})
		}
	}
	if hasRun && len(claims) == 0 {
		_, err := s.repo.FinishMetadataFillRun(ctx, sqlcgen.FinishMetadataFillRunParams{ID: run.ID, State: "done"})
		return 0, err
	}

	judged, filled := 0, 0
	for i, c := range claims {
		out, code, err := s.judgeOne(ctx, c.id, c.attempts)
		if err != nil {
			return judged, err
		}
		if out == outcomePause {
			s.pause(ctx, code, claims[i:])
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
		}); err != nil {
			return judged, err
		}
	}
	return judged, nil
}

func (s *Service) judgeOne(ctx context.Context, id uuid.UUID, attempts int32) (outcome, judgment.Code, error) {
	subj, err := s.repo.GetMetadataFillSubject(ctx, id)
	if errors.Is(err, pgx.ErrNoRows) || (err == nil && !subj.Eligible) {
		return outcomeSkipped, "", s.repo.DeleteMetadataJudgment(ctx, id)
	}
	if err != nil {
		return outcomeSkipped, "", err
	}
	tags, err := s.repo.ListVideoTags(ctx, id)
	if err != nil {
		return outcomeSkipped, "", err
	}
	req := BuildRequest(Subject{
		Title: subj.Title, Description: subj.Description, Channel: subj.ChannelName, Tags: tags,
		CategoryEmpty: subj.CategoryEmpty, LanguageEmpty: subj.LanguageEmpty,
	}, s.categories(), video.Languages)
	if len(req.Questions) == 0 {
		return outcomeSkipped, "", s.repo.RecordMetadataJudgment(ctx, sqlcgen.RecordMetadataJudgmentParams{VideoID: id, Model: ""})
	}
	res, err := s.judge.Ask(ctx, req.State, req.Questions)
	if err != nil {
		code := judgment.CodeOf(err)
		switch code {
		case judgment.CodeAuth, judgment.CodeRateLimited, judgment.CodeNotConfigured:
			return outcomePause, code, nil
		}
		if code == "" {
			code = judgment.CodeUnavailable
		}
		return outcomeSkipped, code, s.repo.RecordMetadataJudgmentFailure(ctx, sqlcgen.RecordMetadataJudgmentFailureParams{
			VideoID: id, MaxAttempts: MaxAttempts, NextAttemptAt: pgtype.Timestamptz{Time: s.now().Add(backoff(attempts)), Valid: true},
			Code: pgtype.Text{String: string(code), Valid: true},
		})
	}
	d := Decide(res, req)
	if err := s.repo.RecordMetadataJudgment(ctx, sqlcgen.RecordMetadataJudgmentParams{
		VideoID: id, Model: d.Model,
		CategoryPick: d.CategoryPick, CategoryProb: probPtr(d.CategoryAsked, d.CategoryProb),
		LanguagePick: d.LanguagePick, LanguageProb: probPtr(d.LanguageAsked, d.LanguageProb),
	}); err != nil {
		return outcomeSkipped, "", err
	}
	if d.Category == nil && d.Language == nil {
		return outcomeJudged, "", nil
	}
	applied, err := s.apply.ApplyInferredMetadata(ctx, id, d.Category, d.Language)
	if err != nil {
		return outcomeJudged, "", err
	}
	if applied.Category != nil || applied.Language != nil {
		return outcomeFilled, "", nil
	}
	return outcomeJudged, "", nil
}

// pause stops every replica until the pause expires and hands back every
// claim this tick still holds without spending an attempt.
func (s *Service) pause(ctx context.Context, code judgment.Code, held []claim) {
	d := rateLimitedPause
	if code == judgment.CodeAuth {
		d = authPause
	}
	until := s.now().Add(d)
	for _, c := range held {
		if err := s.repo.ReleaseMetadataJudgment(ctx, sqlcgen.ReleaseMetadataJudgmentParams{
			VideoID: c.id, NextAttemptAt: pgtype.Timestamptz{Time: until, Valid: true},
		}); err != nil {
			s.logger.Warn("metadata fill: release claim failed", "video_id", c.id, "error", err)
		}
	}
	if err := s.repo.SetMetadataFillPause(ctx, sqlcgen.SetMetadataFillPauseParams{
		PausedUntil: pgtype.Timestamptz{Time: until, Valid: true},
		PausedCode:  pgtype.Text{String: string(code), Valid: true},
	}); err != nil {
		s.logger.Warn("metadata fill: pause not recorded", "error", err)
	}
}

func probPtr(asked bool, p float64) *float32 {
	if !asked {
		return nil
	}
	v := float32(p)
	return &v
}
```

The generated param field types (`*string` versus `pgtype.Text`, `*float32` versus `pgtype.Float4`) depend on sqlc's overrides in `sqlc.yaml`. Match whatever `make sqlc` produced in Task 4, and adjust `probPtr` and the `Code`/`PausedCode` literals to those types. Add `TestTickClearsAnExpiredPause`: seed `pausedUntil` in the past, tick, and assert the pause is cleared and a claim is made.

- [ ] **Step 4: Run them.** `go test ./internal/metadatafill/ -race -v` → PASS. Then `make ci`.

- [ ] **Step 5: Commit**

```bash
git add internal/metadatafill
git commit -m "feat(metadatafill): state-scan worker tick with backoff, pause and runs

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 8: Setting toggle, infrastructure row, wiring (PR C8, core)

**Goal:** The worker runs in the api binary. The admin toggle turns it on at runtime, and the infrastructure snapshot reports it Off, Active or Needs setup.

**Files:**
- Modify: `internal/instancesettings/service.go` (const near L199; `Defaults` L576-606; `specs` row near L870)
- Modify: `internal/instancesettings/service_test.go` (`testDefaults()` L47; table L78-103), `internal/httpapi/admin_instance_settings_test.go` (`settingsDefaultsFromConfig` L63; count L199-200 **118 → 119**)
- Modify: `cmd/api/main.go` (Defaults L309-340; video service hooks ~L1331-1399; worker start after the captions worker L2487-2492; new worker func beside `runCaptionJobWorker` L3414)
- Modify: `internal/httpapi/admin_infra.go` (`infraFeatures` L379; off notes L688; misconfigured notes L721), `internal/httpapi/admin_infra_test.go` (`wantKeys` L264-268; mutate table ~L306)
- Modify: `internal/httpapi/server.go` (field and `WithMetadataFill` option)
- Modify: `api/openapi.yaml` (the settings-key prose ~L14270-14280; infrastructure key list ~L23521-23524)

**Acceptance Criteria:**
- [ ] `metadata_autofill_enabled` is a `KindBool` setting on `PageVOD`, section `autofill`, whose default is `cfg.MetadataAutofillEnabled`. The settings count is 119.
- [ ] The api binary always starts the worker when `cfg.Role.RunsWorkers()`, never gated on boot config. Each tick re-reads the toggle and the key.
- [ ] `infrastructure.features` ends with `{"key":"metadata_autofill","enabled":<toggle>,"configured":<key resolves>}`, with an off note and a missing-key note that names `TYPESAFE_API_KEY`.
- [ ] `make ci` is green, including `TestOpenAPIContract`.

**Verify:** `go test ./internal/instancesettings/ ./internal/httpapi/ -race -run 'Settings|Infrastructure|Registry'` → PASS. Then `make ci`.

**Steps:**

- [ ] **Step 1: Failing tests.**
  - `service_test.go` table: `{KeyMetadataAutofillEnabled, KindBool, false, PageVOD, "autofill"},`.
  - `admin_instance_settings_test.go`: bump `118` to `119` in both the condition and the message, and add a line to the comment block above: `// +1 metadata_autofill_enabled (Jev auto-fill, meta spec 2026-09-20)`.
  - `admin_infra_test.go`: append `"metadata_autofill"` to `wantKeys`, and add a mutate row: `"autofill on without a key": {func(c *config.Config){ c.MetadataAutofillEnabled = true }, "metadata_autofill", "TYPESAFE_API_KEY"}`. That row assumes the test server wires the provider from config. If the infra test builds `Server` without `WithMetadataFill`, construct a stub provider in the test that reports `Enabled()==true`, `Configured()==false`, and pass it via `WithMetadataFill`.

- [ ] **Step 2: Run them and watch them fail**

Run: `go test ./internal/instancesettings/ ./internal/httpapi/ -run 'Registry|Settings|Infrastructure'`
Expected: FAIL (undefined key, count 118, missing feature).

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

In `testDefaults()` and `settingsDefaultsFromConfig`, map `MetadataAutofillEnabled`. In `cmd/api/main.go` Defaults: `MetadataAutofillEnabled: cfg.MetadataAutofillEnabled,`.

`internal/httpapi/server.go`:

```go
// metadataFillProvider is the admin surface of the auto-fill worker.
type metadataFillProvider interface {
	Enabled() bool
	Configured(ctx context.Context) bool
}

// WithMetadataFill wires the Jev auto-fill worker's admin surface.
func WithMetadataFill(p metadataFillProvider) Option {
	return func(s *Server) { s.metadatafillsvc = p }
}
```

Add the `metadatafillsvc metadataFillProvider` field. Task 9 widens the interface.

`internal/httpapi/admin_infra.go`: `infraFeatures()` has no context. Change it to `infraFeatures(ctx context.Context)` and pass `c.Request().Context()` from its caller or callers (`grep -n 'infraFeatures(' internal/httpapi/*.go`). Then append:

```go
		{
			Key:        "metadata_autofill",
			Enabled:    s.metadatafillsvc != nil && s.metadatafillsvc.Enabled(),
			Configured: s.metadatafillsvc != nil && s.metadatafillsvc.Configured(ctx),
		},
```

Notes:
- `infraFeatureOffNotes["metadata_autofill"] = "Automatic category and language for public videos. Off by default; switch it on under Config → VOD. When on, the title, description, channel name and tags of public videos are sent to TypeSafe (US-hosted)."`
- `infraFeatureMisconfiguredNotes["metadata_autofill"] = "Switched on, but no TypeSafe API key is set, so nothing is sent and nothing is filled. Set TYPESAFE_API_KEY (or add the key in the admin panel once available) — no restart needed for the panel key."`

`cmd/api/main.go`:
- Construct the judgment client and the worker next to the captions construction (L2092-2115):

```go
	judgeClient := judgment.New(cfg.TypeSafeEndpoint, cfg.TypeSafeModel,
		func(context.Context) string { return cfg.TypeSafeAPIKey })
	metadatafillsvc := metadatafill.New(q, judgeClient, videosvc,
		func() bool { return settingssvc.Bool(instancesettings.KeyMetadataAutofillEnabled) },
		metadatafill.WithLogger(logger))
```

  Use the local names this file actually uses: `q` for `*sqlcgen.Queries`, `videosvc` for `*video.Service`, and `settingssvc` for the settings service (grep for them). `*sqlcgen.Queries` satisfies `metadatafill.Repository` only if `ListVideoTags` has the same signature. It does: the video `Repository` uses `ListVideoTags(ctx, uuid.UUID) ([]string, error)`.
- Pass `httpapi.WithMetadataFill(metadatafillsvc)` in the server options.
- After the captions worker start:

```go
	// Always started: its capability can arrive at runtime (a key saved in the
	// admin panel), so a boot-time gate would strand it. Each tick is a no-op
	// unless the toggle is on and a key resolves.
	if runWorkers {
		workerCtx, workerCancel := context.WithCancel(context.Background())
		defer workerCancel()
		go runMetadataFillWorker(workerCtx, logger, metadatafillsvc)
		logger.Info("metadata auto-fill worker started")
	}
```

- Beside `runCaptionJobWorker`:

```go
// runMetadataFillWorker drives the Jev auto-fill state scan. Every worker-role
// replica runs it (Jitter): the INSERT-is-the-claim query keeps replicas
// disjoint.
func runMetadataFillWorker(ctx context.Context, logger *slog.Logger, svc *metadatafill.Service) {
	jobloop.Loop{
		Interval: 30 * time.Second,
		Jitter:   true,
		Passes: []jobloop.Pass{{
			FailMsg: "metadata auto-fill tick failed",
			DoneMsg: "metadata auto-fill judged videos",
			Run:     func(ctx context.Context, _ time.Time) (int, error) { return svc.Tick(ctx) },
		}},
	}.Run(ctx, logger)
}
```

`api/openapi.yaml`: add `metadata_autofill_enabled` to the settings-key prose list, and append `metadata_autofill` to the infrastructure feature key list and order prose.

- [ ] **Step 4: Integration proof** (`internal/metadatafill/worker_integration_test.go`, `//go:build integration`). This runs a real `sqlcgen.Queries` against Postgres with an `httptest` Jev that always answers built-in category 1 at 0.95 and `en` at 0.99, and a real `video.Service`. The test seeds one eligible video, calls `svc.Tick`, and asserts that `videos.category='1'`, `language='en'`, and `GetVideoAutoFilled` returns both. It uses the store package's `dsn(t)` idiom: copy `func dsn(t)` locally, because the helper is unexported in `store`.

- [ ] **Step 5: Run everything.** `make ci`, then `go vet -tags=integration ./...`, then the §0.4 integration command. All green.

- [ ] **Step 6: Commit**

```bash
git add internal/instancesettings internal/httpapi cmd/api api/openapi.yaml internal/metadatafill
git commit -m "feat(metadatafill): runtime toggle, infrastructure row and worker wiring

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 9: Admin endpoints, runs, audit, OpenAPI (PR C9, core)

**Goal:** An admin can read the status, test the connection, start a "fill existing videos" run and stop it. Each action is audited with closed codes.

**Files:**
- Modify: `internal/metadatafill/service.go` (add `Status`, `Test`, `StartRun`, `StopRun`), `internal/metadatafill/service_test.go`
- Create: `internal/httpapi/admin_metadata_fill.go`, `internal/httpapi/admin_metadata_fill_test.go`
- Modify: `internal/httpapi/errors.go` (typed error), `internal/httpapi/server.go` (routes near L2225-2259; widen `metadataFillProvider`)
- Modify: `internal/observability/audit.go` (actions near L111-127)
- Modify: `api/openapi.yaml` (4 operations, 2 schemas); `internal/httpapi/openapi_contract_test.go` `fullRouteOptions()` (L62) must mount `WithMetadataFill`

**Contract:**

| Route | 200/2xx body | Errors |
|---|---|---|
| `GET /api/v1/admin/metadata-fill/status` | `MetadataFillStatus` | 401, 403, 501 when not wired |
| `POST /api/v1/admin/metadata-fill/test` | `{"status":"ok"}` | 409 `metadata_fill_not_configured`, 502 `metadata_fill_test_failed` with `reason` ∈ `auth`/`rate_limited`/`unavailable`/`bad_response`/`invalid_request` |
| `POST /api/v1/admin/metadata-fill/runs` | 201 `MetadataFillRun` | 409 `metadata_fill_run_active`, 409 `metadata_fill_inactive` |
| `DELETE /api/v1/admin/metadata-fill/runs/current` | 204 | 404 `not_found` |

```yaml
MetadataFillStatus:
  type: object
  required: [enabled, configured, model, counts, unjudged]
  properties:
    enabled: {type: boolean}
    configured: {type: boolean}
    model: {type: string, example: jev-1.13.0}
    paused_code: {type: string, nullable: true, enum: [auth, rate_limited, not_configured]}
    paused_until: {type: string, format: date-time, nullable: true}
    counts:
      type: object
      required: [waiting, filled, not_confident, failed]
      properties:
        waiting: {type: integer}
        filled: {type: integer}
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
- [ ] All four routes require an admin: anonymous gets 401 and a non-admin gets 403.
- [ ] A successful test sends one fixed, harmless state (language question only), never a real video.
- [ ] Starting a run returns `failed` rows to `pending`. A second start while one is running gets 409 because of the unique index, including under a race.
- [ ] Audit actions `admin.metadata_fill.test`, `admin.metadata_fill.run_start` and `admin.metadata_fill.run_stop` are recorded with `Reason` from a closed set only (`ok`, `not_configured`, a judgment code, `run_active`, `inactive`, `no_run`) and metadata `count` for requeued rows. No model output reaches the audit log.
- [ ] `TestOpenAPIContract` passes in both directions.

**Verify:** `go test ./internal/httpapi/ ./internal/metadatafill/ -race -run 'MetadataFill'` → PASS. Then `make ci`.

**Steps:**

- [ ] **Step 1: Failing service tests.** Append to `internal/metadatafill/service_test.go`:

```go
func TestStartRunRequeuesFailedAndRefusesASecond(t *testing.T) {
	svc, repo, _, _, _ := fixture(t)
	repo.rows[uuid.New()] = &fakeRow{state: "failed", attempts: 5}
	run, requeued, err := svc.StartRun(context.Background(), uuid.New())
	if err != nil || run.State != "running" || requeued != 1 {
		t.Fatalf("run=%+v requeued=%d err=%v", run, requeued, err)
	}
	if _, _, err := svc.StartRun(context.Background(), uuid.New()); !errors.Is(err, ErrRunActive) {
		t.Fatalf("second start err = %v, want ErrRunActive", err)
	}
}

func TestStartRunRefusedWhenInactive(t *testing.T) {
	svc, _, judge, _, _ := fixture(t)
	judge.configured = false
	if _, _, err := svc.StartRun(context.Background(), uuid.New()); !errors.Is(err, ErrInactive) {
		t.Fatalf("err = %v, want ErrInactive", err)
	}
}

func TestTestSendsTheFixedProbeOnly(t *testing.T) {
	svc, _, judge, _, _ := fixture(t)
	judge.next = []any{judgment.Result{Answers: map[string]judgment.Answer{QLanguage: {Pick: "en", Probabilities: map[string]float64{"en": 1}}}}}
	if err := svc.Test(context.Background()); err != nil {
		t.Fatal(err)
	}
	v := judge.lastState.(map[string]any)["video"].(map[string]any)
	if v["title"] != testProbeTitle || len(judge.lastQuestions) != 1 {
		t.Fatalf("probe = %v / %d questions", v, len(judge.lastQuestions))
	}
}
```

Add `errors` to the imports. `fakeJudge` gains `lastState any` and `lastQuestions map[string]judgment.Question`.

- [ ] **Step 2: Implement the service methods** in `internal/metadatafill/service.go`. First add these to `Repository`: `CreateMetadataFillRun(ctx, pgtype.UUID) (sqlcgen.MetadataFillRun, error)`, `RequeueFailedMetadataJudgments(ctx) (int64, error)`, `CountMetadataJudgments(ctx) (sqlcgen.CountMetadataJudgmentsRow, error)` and `CountUnjudgedEligibleVideos(ctx) (int64, error)`. Then write:

```go
var (
	// ErrRunActive: a run is already running (unique index).
	ErrRunActive = errors.New("metadatafill: a run is already running")
	// ErrInactive: the toggle is off or no key resolves.
	ErrInactive = errors.New("metadatafill: not enabled or not configured")
	// ErrNoRun: nothing to stop.
	ErrNoRun = errors.New("metadatafill: no running run")
)

const testProbeTitle = "Connection test"

// Test sends one fixed, harmless judgment. It never sends a real video.
func (s *Service) Test(ctx context.Context) error {
	_, err := s.judge.Ask(ctx,
		map[string]any{"video": map[string]any{"title": testProbeTitle, "description": "A short check that the connection works."}},
		map[string]judgment.Question{QLanguage: {
			Instructions: "In which language is `video.title` written?",
			Options:      []judgment.Option{{Key: "en", Description: "English"}, {Key: Unclear}},
		}})
	return err
}

// StartRun creates the running run and returns failed rows to pending.
func (s *Service) StartRun(ctx context.Context, actor uuid.UUID) (sqlcgen.MetadataFillRun, int64, error) {
	if !s.enabled() || !s.judge.Configured(ctx) {
		return sqlcgen.MetadataFillRun{}, 0, ErrInactive
	}
	run, err := s.repo.CreateMetadataFillRun(ctx, pgtype.UUID{Bytes: actor, Valid: true})
	if isUniqueViolation(err) {
		return sqlcgen.MetadataFillRun{}, 0, ErrRunActive
	}
	if err != nil {
		return sqlcgen.MetadataFillRun{}, 0, err
	}
	n, err := s.repo.RequeueFailedMetadataJudgments(ctx)
	return run, n, err
}

// StopRun flips the running run to stopped; the worker reads it every tick.
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
	PausedCode          string
	PausedUntil         *time.Time
	Counts              sqlcgen.CountMetadataJudgmentsRow
	Unjudged            int64
	Run                 *sqlcgen.MetadataFillRun
}

func (s *Service) Status(ctx context.Context, model string) (Status, error) {
	st := Status{Enabled: s.enabled(), Configured: s.judge.Configured(ctx), Model: model}
	fs, err := s.repo.GetMetadataFillState(ctx)
	if err != nil {
		return st, err
	}
	if fs.PausedUntil.Valid && s.now().Before(fs.PausedUntil.Time) {
		st.PausedCode = fs.PausedCode.String
		t := fs.PausedUntil.Time
		st.PausedUntil = &t
	}
	if st.Counts, err = s.repo.CountMetadataJudgments(ctx); err != nil {
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

func isUniqueViolation(err error) bool {
	var pgErr *pgconn.PgError
	return errors.As(err, &pgErr) && pgErr.Code == "23505"
}
```

Import `github.com/jackc/pgx/v5/pgconn`. If the repo already has an `isUniqueViolation` helper (`grep -rn '23505' internal/`), reuse it instead of adding one. The `Status(ctx, model)` parameter avoids a `Model()` method on the `Judge` interface; the handler passes `cfg.TypeSafeModel`.

- [ ] **Step 3: Failing HTTP tests** `internal/httpapi/admin_metadata_fill_test.go`. They use `mailTestServer`-style construction (`New(cfg, nil, nil, WithAuthService(...), WithMetadataFill(stub))`) with a stub provider, `registerAndToken` (first user is admin), `sendJSONAuth`, and the log-capture buffer with `auditEvents`/`findAudit`:

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
	testErr             error
	startErr            error
	stopErr             error
	started             int
}

func (s *stubFill) Enabled() bool                       { return s.enabled }
func (s *stubFill) Configured(context.Context) bool     { return s.configured }
func (s *stubFill) Test(context.Context) error          { return s.testErr }
func (s *stubFill) StopRun(context.Context) error       { return s.stopErr }
func (s *stubFill) Status(context.Context, string) (metadatafill.Status, error) {
	return metadatafill.Status{Enabled: s.enabled, Configured: s.configured, Model: "jev-1.13.0"}, nil
}
func (s *stubFill) StartRun(context.Context, uuid.UUID) (sqlcgen.MetadataFillRun, int64, error) {
	s.started++
	return sqlcgen.MetadataFillRun{ID: uuid.New(), State: "running", CreatedAt: time.Now()}, 2, s.startErr
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
		name     string
		fill     *stubFill
		status   int
		code     string
		reason   string
		result   string
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

Because the stub returns `(run, 2, ErrRunActive)` on the second start, the handler must check `err` before using `run`.

- [ ] **Step 4: Run them and watch them fail.** Run `go test ./internal/httpapi/ -run MetadataFill`. Expected: FAIL, because the routes are not registered.

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

`internal/httpapi/errors.go`: a single typed error, and a case in the central switch next to `mtf`:

```go
// MetadataFillError renders with its own status and stable code. Reason is a
// closed judgment code (never upstream text) and rides in ErrorBody.Reason.
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
		mailReason = mfe.Reason // ErrorBody.Reason: a closed classification, safe to return
```

Declare `var mfe *MetadataFillError` with the others. `ErrorBody.Reason` is the existing field the mail test uses. Check its JSON name and doc comment (`grep -n 'Reason' internal/httpapi/errors.go | head`), and widen the comment to mention this code. If the scrubber drops 5xx bodies without a code, this case supplies one, so it survives.

`internal/httpapi/server.go`: widen the interface.

```go
type metadataFillProvider interface {
	Enabled() bool
	Configured(ctx context.Context) bool
	Status(ctx context.Context, model string) (metadatafill.Status, error)
	Test(ctx context.Context) error
	StartRun(ctx context.Context, actor uuid.UUID) (sqlcgen.MetadataFillRun, int64, error)
	StopRun(ctx context.Context) error
}
```

Add the routes beside the mail routes:

```go
	if s.metadatafillsvc != nil {
		admin := []echo.MiddlewareFunc{s.requireAuth, s.requireRole(admin.RoleAdmin)}
		api.GET("/admin/metadata-fill/status", s.handleMetadataFillStatus, admin...)
		api.POST("/admin/metadata-fill/test", s.handleMetadataFillTest, append(admin, s.mailTestRateLimit())...)
		api.POST("/admin/metadata-fill/runs", s.handleMetadataFillStartRun, admin...)
		api.DELETE("/admin/metadata-fill/runs/current", s.handleMetadataFillStopRun, admin...)
	}
```

`mailTestRateLimit()` is reused for the test button because it has the same abuse shape: an admin repeatedly pressing a button that calls a third party. If its key or name is mail-specific (for example its limiter label), add a sibling `metadataFillTestRateLimit()` built the same way instead.

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
	"github.com/vidra/vidra-core/internal/store/sqlcgen"
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
	Enabled     bool                   `json:"enabled"`
	Configured  bool                   `json:"configured"`
	Model       string                 `json:"model"`
	PausedCode  *string                `json:"paused_code"`
	PausedUntil *time.Time             `json:"paused_until"`
	Counts      metadataFillCountsView `json:"counts"`
	Unjudged    int64                  `json:"unjudged"`
	Run         *metadataFillRunView   `json:"run"`
}

func runView(r sqlcgen.MetadataFillRun) *metadataFillRunView {
	return &metadataFillRunView{ID: r.ID.String(), State: r.State, Judged: r.Judged, Filled: r.Filled, StartedAt: r.CreatedAt}
}

func (s *Server) handleMetadataFillStatus(c echo.Context) error {
	st, err := s.metadatafillsvc.Status(c.Request().Context(), s.cfg.TypeSafeModel)
	if err != nil {
		return err
	}
	v := metadataFillStatusView{
		Enabled: st.Enabled, Configured: st.Configured, Model: st.Model, PausedUntil: st.PausedUntil,
		Counts: metadataFillCountsView{Waiting: st.Counts.Waiting, Filled: st.Counts.Filled,
			NotConfident: st.Counts.NotConfident, Failed: st.Counts.Failed},
		Unjudged: st.Unjudged,
	}
	if st.PausedCode != "" {
		v.PausedCode = &st.PausedCode
	}
	if st.Run != nil {
		v.Run = runView(*st.Run)
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
			Message: "no TypeSafe API key is set. Set TYPESAFE_API_KEY in the server's env file, or add the key in the admin panel"}
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
	run, requeued, err := s.metadatafillsvc.StartRun(c.Request().Context(), callerID)
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
		Metadata: []audit.MetadataField{{Key: "count", Value: strconv.FormatInt(requeued, 10)}},
	})
	return c.JSON(http.StatusCreated, runView(run))
}

func (s *Server) handleMetadataFillStopRun(c echo.Context) error {
	callerID, _, err := mustPrincipal(c)
	if err != nil {
		return err
	}
	if err := s.metadatafillsvc.StopRun(c.Request().Context()); errors.Is(err, metadatafill.ErrNoRun) {
		s.audit(c, observability.ActionAdminMetadataFillRunStop, observability.ResultFailure, callerID.String(), "no_run")
		return echo.NewHTTPError(http.StatusNotFound, "no fill run is running")
	} else if err != nil {
		return err
	}
	s.audit(c, observability.ActionAdminMetadataFillRunStop, observability.ResultSuccess, callerID.String(), "stopped")
	return c.NoContent(http.StatusNoContent)
}
```

If the server's config field is not `s.cfg`, grep for how handlers read config (e.g. `s.config`).

`api/openapi.yaml`: add the four operations under `/api/v1/admin/metadata-fill/...` with `security` and the status codes above. Copy the structure of `/api/v1/admin/mail/test`. Add the two schemas. Document `reason` in the error schema as a closed enum for `metadata_fill_test_failed`, the way `mail_test_failed` documents its reason.

`openapi_contract_test.go` `fullRouteOptions()`: add `WithMetadataFill(&stubFill{})`, or a minimal no-op stub if the contract test file cannot see `stubFill`. Define a tiny one there.

- [ ] **Step 6: Run them.** `go test ./internal/httpapi/ ./internal/metadatafill/ -race` → PASS. Then `make ci`, including `openapi-verify`.

- [ ] **Step 7: Commit**

```bash
git add internal/httpapi internal/metadatafill internal/observability api/openapi.yaml
git commit -m "feat(httpapi): admin status, test and fill-run endpoints for metadata auto-fill

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 10: `auto_filled` on the video view (PR C10, core)

**Goal:** `GET /api/v1/videos/{id}` returns `auto_filled` to the owner and to staff only, so Studio can show the marker.

**Files:**
- Modify: `internal/httpapi/videos.go` (`videoView` beside `Category`/`Language`, L230-233; `respondVideo` L585-628)
- Modify: the httpapi video service interface, if handlers depend on one (`grep -n 'videosvc ' internal/httpapi/server.go`), to include `AutoFilled`
- Modify: `api/openapi.yaml` `components.schemas.Video` (~L18213; model the description on `blocked`, ~L18333-18350)
- Test: `internal/httpapi/videos_auto_filled_test.go` (new)

**Acceptance Criteria:**
- [ ] The owner and a moderator or admin get `auto_filled: ["category"]` when that field holds the worker's value.
- [ ] An anonymous caller or another user never sees the field, not even as an empty array.
- [ ] An error from `AutoFilled` omits the field and never fails the read.

**Verify:** `go test ./internal/httpapi/ -race -run AutoFilled` → PASS. Then `make ci`.

**Steps:**

- [ ] **Step 1: Failing test.** Use the existing video-detail test scaffolding in `internal/httpapi` (find a test that calls `GET /api/v1/videos/{id}` as owner vs anon; `grep -ln 'api/v1/videos/"' internal/httpapi/*_test.go`). Wire a fake video service whose `AutoFilled` returns `[]string{"category"}`, and assert:

```go
	if got := decodeVideo(t, ownerRec)["auto_filled"]; !reflect.DeepEqual(got, []any{"category"}) {
		t.Fatalf("owner auto_filled = %v", got)
	}
	if _, present := decodeVideo(t, anonRec)["auto_filled"]; present {
		t.Fatal("auto_filled leaked to an anonymous viewer")
	}
	if _, present := decodeVideo(t, otherUserRec)["auto_filled"]; present {
		t.Fatal("auto_filled leaked to another user")
	}
```

- [ ] **Step 2: Run it and watch it fail.** Expected: FAIL, because the owner response lacks the field.

- [ ] **Step 3: Implement.** In `videoView`, next to `Language`:

```go
	// AutoFilled lists which of category/language hold a value the Jev
	// auto-fill worker chose and no human has since set. Owner and staff only.
	AutoFilled []string `json:"auto_filled,omitempty"`
```

In `respondVideo`, before `s.attachVideoIPFS(...)`:

```go
	if viewerID, role, ok := principalFromContext(c); ok && (viewerID == v.OwnerID || isStaff(role)) {
		if af, err := s.videosvc.AutoFilled(c.Request().Context(), id); err == nil && len(af) > 0 {
			view.AutoFilled = af
		}
	}
```

In `api/openapi.yaml` `Video.properties`:

```yaml
        auto_filled:
          type: array
          items: {type: string, enum: [category, language]}
          description: >-
            Owner and staff only; omitted otherwise and when empty. Fields whose
            current value was chosen automatically (TypeSafe Jev auto-fill) and
            that no person has set since. Studio shows a "Set automatically" note.
```

- [ ] **Step 4: Run it.** `go test ./internal/httpapi/ -race` → PASS. Then `make ci`.

- [ ] **Step 5: Commit**

```bash
git add internal/httpapi api/openapi.yaml
git commit -m "feat(httpapi): auto_filled on the owner/staff video view

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 11: `api evaluate-metadata` (PR C11, core)

**Goal:** A read-only subcommand that measures Jev against human-labelled public videos, so the bars are set from data. It writes nothing.

**Files:**
- Create: `cmd/api/evaluate_metadata.go`, `cmd/api/evaluate_metadata_test.go`, `internal/metadatafill/evaluate.go`, `internal/metadatafill/evaluate_test.go`
- Modify: `cmd/api/main.go` (dispatch switch L118-136 and its usage string)

**Behaviour:** `api evaluate-metadata [--sample 300] [--seed vidra] [--json]`
- Loads config (`config.Load()`) and opens the store the way `verify-blobs` does (`cmd/api/verify_blobs.go:73`).
- Requires a key (`TYPESAFE_API_KEY`; after Task 18, the same resolver the worker uses). With no key it exits 1 with `evaluate-metadata: no TypeSafe key`.
- Samples with `SampleLabelledVideosForEvaluation` and skips any row whose human value is not in the live vocabulary.
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

## Task 12: Env example and runbook (PR M1, meta)

**Goal:** An operator can find, understand, enable, measure and undo the feature from this repo alone.

**Files:**
- Modify: `env/production.env.example` (a new block after the outbound-email block, ~L976)
- Create: `docs/metadata-autofill.md`

**Acceptance Criteria:**
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

- [ ] **Step 2: Runbook** `docs/metadata-autofill.md`, with these sections: *What it does*, *What is sent and what never is*, *Turning it on*, *Which videos it reaches* ("Videos published or edited after you switch this on are filled automatically; everything else waits for the Fill existing videos button"), *Reading the status card*, *Before you rely on it: the evaluation*, *Turning it off*, *Undoing fills*, *Privacy notice*, *Known limits* (English-primary; a wrong answer is visible and correctable in Studio; an edited old video becomes eligible; federation peers do not receive category or language). The undo SQL must say that it bypasses the hooks, so the search index converges at the next reconcile (24 h default), or at once after an api restart triggers the boot reconcile, which the implementer checks in `runSearchReconcileWorker` before claiming it:

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

## Task 13: Codegen, toggle and warning, infrastructure labels, API wrappers (PR U1, user)

**Goal:** The admin can switch the feature on under Config → VOD, is warned when no key is set, sees the Infrastructure row, and the client can call the four endpoints.

**Files:**
- Regenerate: `lib/api/generated.ts`
- Modify: `lib/api/types.ts`, `lib/api/endpoints.ts`, `lib/admin-config-ia.ts` (VOD sections L282-341; META), `lib/admin-config-ia.test.ts` (`SERVER_REGISTRY` ~L108; wiring block L827-919), `components/AdminInfrastructureView.tsx` (`FEATURE_LABEL` L555-577; `FEATURE_CONFIG_PAGE` L590-619)

**Acceptance Criteria:**
- [ ] `metadata_autofill_enabled` renders as a toggle in a new VOD section `autofill` titled "Automatic category & language", with the §8 privacy text as help.
- [ ] The warning shows when `features` has `{key:"metadata_autofill", configured:false}`, and not otherwise.
- [ ] The Infrastructure row reads "Automatic category & language" and links to `/admin/config/vod`.
- [ ] `api.getMetadataFillStatus`, `testMetadataFill`, `startMetadataFillRun` and `stopMetadataFillRun` exist, and `npm run check:contract` passes.

**Verify:** `npx tsc --noEmit && npm run lint && npm run test -- lib/admin-config-ia components/AdminInfrastructureView && npm run check:contract`.

**Steps:**

- [ ] **Step 1: Regenerate.** `curl -fsSL https://raw.githubusercontent.com/yegamble/vidra-core/main/api/openapi.yaml -o /tmp/openapi.yaml && OPENAPI_PATH=/tmp/openapi.yaml npm run codegen`. Expected: `generated.ts` gains `MetadataFillStatus`, `MetadataFillRun` and `Video.auto_filled`.

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

In `components/AdminInfrastructureView.test.tsx`, add a case rendering a `metadata_autofill` row. It asserts the label "Automatic category & language" and a link to `/admin/config/vod`.

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
      note: "This server has no TypeSafe API key, so this switch currently does nothing — nothing is sent and nothing is filled. See Infrastructure → Optional features.",
      isTriggered: (infra) =>
        infra.features?.some(
          (f) => f.key === "metadata_autofill" && f.configured === false,
        ) === true,
    },
  },
```

In `AdminInfrastructureView.tsx`: add `metadata_autofill: "Automatic category & language"` to `FEATURE_LABEL` and `metadata_autofill: "/admin/config/vod"` to `FEATURE_CONFIG_PAGE`.

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

## Task 14: `MetadataFillCard` (PR U2, user)

**Goal:** One card on the Infrastructure page shows the state and counts, and offers **Test connection** and **Fill existing videos (N)** / **Stop filling**.

**Files:**
- Create: `components/admin/MetadataFillCard.tsx`, `components/admin/MetadataFillCard.test.tsx`
- Modify: `components/AdminInfrastructureView.tsx` (render after `<MailTestCard …/>`, L315)
- Modify: `e2e/admin-infrastructure.spec.ts` (one mocked spec)

**Behaviour and copy:**
- Loads `api.getMetadataFillStatus` on mount. A failed load shows `ErrorState` with a retry button, and the rest of the page stays usable.
- Status line: "Off" (not enabled), "Needs setup — no TypeSafe key" (enabled and not configured), "Paused — TypeSafe rejected the key" (`paused_code=auth`), "Paused — rate limited, resuming shortly" (`rate_limited`), otherwise "Active".
- Counts: "Waiting N · Filled N · Not confident N · Failed N".
- **Test connection**, following the MailTestCard pattern (an `inFlight` ref, `aria-disabled`, a `Spinner`). On success: "TypeSafe answered. The key works." On error, the `errorMessage` overrides are:
  `metadata_fill_not_configured`: "No TypeSafe API key is set."
  `reason` `auth`: "TypeSafe rejected the key."
  `rate_limited`: "TypeSafe is rate-limiting this key. Try again in a few minutes."
  `unavailable`: "TypeSafe could not be reached from this server."
  `bad_response`/`invalid_request`: "TypeSafe answered with something unexpected. Check TYPESAFE_ENDPOINT and TYPESAFE_MODEL."
  To read the typed `reason`, check how `MailTestCard` reads `err.mailReason` (`lib/api/client.ts` L37-58). The server puts it in the same `ErrorBody.Reason`, so `ApiError.mailReason` carries it. Rename nothing in this slice; read it and note in a code comment that the field is shared.
- **Fill existing videos (N)**, where N is `unjudged`. It is disabled with an explanation when not enabled or not configured, or when `unjudged == 0` ("Nothing to fill"). While `run` is running, the button becomes **Stop filling** and shows "Filled X of Y judged so far". The card polls status every 10 s while a run is running and stops polling on unmount.
- The card never shows a model name or a probability. The engine name "TypeSafe" appears only in admin copy.

**Acceptance Criteria:**
- [ ] Unit tests cover the five status lines, a test success, a test `auth` failure, a start (the button flips to Stop), a stop, a 409 `metadata_fill_run_active` message, and that polling stops on unmount.
- [ ] A mocked e2e run renders the card from a mocked status and clicks Test connection against a mocked 200.

**Verify:** `npm run test -- components/admin/MetadataFillCard components/AdminInfrastructureView && npx tsc --noEmit && npm run lint && npm run lint:icons`.

**Steps:**

- [ ] **Step 1: Failing tests** `components/admin/MetadataFillCard.test.tsx`. Mock the API the way `MailTestCard.test.tsx` does:

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
  enabled: true, configured: true, model: "jev-1.13.0", paused_code: null, paused_until: null,
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
    [{}, "Active"],
  ])("shows the status for %o", async (patch, text) => {
    mocks.getMetadataFillStatus.mockResolvedValue({ ...base, ...patch });
    render(<MetadataFillCard />);
    expect(await screen.findByText(text)).toBeTruthy();
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
    const stop = await screen.findByRole("button", { name: "Stop filling" });
    await userEvent.click(stop);
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

Check the `ApiError` constructor's argument order in `lib/api/client.ts` and match it. The object-assign form above assumes `(status, code, message)`.

- [ ] **Step 2: Run them and watch them fail.** Expected: FAIL (no module).

- [ ] **Step 3: Implement `components/admin/MetadataFillCard.tsx`.** Structure it like `MailTestCard.tsx`: a `<section aria-label="Automatic category and language">` holding a `Card` with a heading, the status `Badge` (reuse the Off/Active/Needs setup variant mapping from `FeatureRow`, `AdminInfrastructureView.tsx:667-717`), the counts line, and two `Button`s that use `aria-disabled` rather than `disabled`, matching MailTestCard. It uses `Spinner`, and `Alert variant="danger"`/`"success"` for outcomes. Load with `useApiResource(api.getMetadataFillStatus, [])` (`lib/use-api-resource.ts:57`); its `retry` refreshes after start and stop. Poll with a `useEffect` that sets a 10 s `setInterval` only while `data?.run?.state === "running"` and clears it on cleanup. Copy is exactly the strings above, and all colours come from design tokens. Read `.ralph/specs/design-system.md` before writing the JSX.

- [ ] **Step 4: Place it.** In `AdminInfrastructureView.tsx`, directly after `<MailTestCard configureHref="/admin/config/email" />`, add `<MetadataFillCard />`.

- [ ] **Step 5: Mocked e2e.** In `e2e/admin-infrastructure.spec.ts`, add a `METADATA_FILL_STATUS = /\/api\/v1\/admin\/metadata-fill\/status$/` constant and a test. It uses `signIn(page, "admin")`, `openInfrastructure`, routes the status to `base` and `/metadata-fill/test` to `{ status: "ok" }`, clicks "Test connection", and expects "TypeSafe answered. The key works.".

- [ ] **Step 6: Run the gates.** Verify is green. Do not run `npm run e2e` locally; CI runs it.

- [ ] **Step 7: Commit**

```bash
git add components e2e
git commit -m "feat(admin): metadata auto-fill status card with test and fill-existing run

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 15: Studio marker and mocked e2e (PR U3, user)

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

## Task 16: `jev-stub` compose profile (PR C12, core)

**Goal:** A deterministic stand-in for `/v1/systemone` that backed e2e can start, so CI proves the whole chain with no real key.

**Files:**
- Create: `scripts/dev/jevstub.py`, `scripts/dev/jevstub_test.py`
- Modify: `docker-compose.yml` (a new profile-gated service near `whisper`, L880-897)

**Stub contract:** It requires `Authorization: Bearer stub` (anything else gets 401). For each `choice` question it picks, in order: the first option key found case-insensitively in `state.video.title`; then `en` if offered; then the last option, which is `none_of_these` or `unclear`. The pick gets 0.97 and the rest share 0.03. It returns the documented response shape with `model` echoed.

**Acceptance Criteria:**
- [ ] `python3 -m unittest scripts/dev/jevstub_test.py` passes: title match, `en` fallback, no-match, and 401.
- [ ] `docker compose --profile jev-stub config` renders a service `jev-stub` on the compose network with **no published port**.

**Verify:** `python3 -m unittest scripts/dev/jevstub_test.py && docker compose --profile jev-stub config | grep -A3 'jev-stub:'`.

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

## Task 17: Backed e2e spec and optional-workflow job (PR U4, user; touches `.github/workflows`)

**Goal:** Prove, against the real stack and the stub, that publishing leads to filling, then to the Studio marker, and that the category filter finds the video. This PR's task *is* the workflow change (AGENTS.md hard rule 6 exception); say so in the PR body.

**Files:**
- Create: `e2e-backed/metadata-autofill.spec.ts`
- Modify: `scripts/ci/allowed-skips-backed.txt` (the spec self-skips unless `E2E_JEV_STUB=true`, like `whisper-captions.spec.ts`)
- Modify: `.github/workflows/frontend-e2e-optional.yml` (a new job `metadata-autofill-backed`; update the header's list of lanes)

**Acceptance Criteria:**
- [ ] With the stub profile up, `METADATA_AUTOFILL_ENABLED=true TYPESAFE_API_KEY=stub TYPESAFE_ENDPOINT=http://jev-stub:8080`, the spec: publishes a public video titled "Music … <uuid>" with no category or language through the Studio UI; polls the API (up to 120 s, since ticks run every 30 s with jitter) until `category` is the id of "Music" and `language` is `en`; opens the edit form and sees the note; then queries the public video list filtered by that category and finds the video.
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

## Task 18: Sealed key setting (PR C13, core)

**Goal:** The admin can set or clear the TypeSafe key in the panel with no restart. It is stored sealed or not at all, and it wins over `TYPESAFE_API_KEY`.

**Files:**
- Create: `migrations/0153_metadata_fill_key.{up,down}.sql`, `internal/metadatafill/key.go`, `internal/metadatafill/key_test.go`
- Modify: `internal/store/queries/metadata_fill.sql` (two queries), `internal/metadatafill/service.go` (`Status` gains the key source)
- Modify: `internal/httpapi/admin_metadata_fill.go`, `internal/httpapi/server.go` (route), `internal/httpapi/errors.go` (reuse `MetadataFillError`), `internal/observability/audit.go`, `api/openapi.yaml`
- Modify: `cmd/api/main.go` (pass the existing `secretbox` cipher, built at L449-458, and replace the static KeyFunc)

**Contract:** `PUT /api/v1/admin/metadata-fill/key` with body `{"api_key":"<value>"}` replaces the key, and `{"api_key":""}` clears it. The response is 204. Errors: 409 `metadata_fill_secrets_key_missing` when no KEK is configured, and 422 when `api_key` is absent. `MetadataFillStatus` gains `key_source: "admin" | "env" | "none"` and `key_status: "ok" | "undecryptable" | "none"`. The key itself is never returned.

**Acceptance Criteria:**
- [ ] Resolution order: a sealed admin key that opens, then `TYPESAFE_API_KEY`, then "". An undecryptable sealed value is reported, and resolution falls back to env.
- [ ] With a nil cipher, `PUT` with a non-empty key gets 409 and nothing is stored. Clearing still works.
- [ ] Audit `admin.metadata_fill.key_update` with `secret_changed=true` and `Reason` `set` or `cleared`. The value never appears in any log or audit record, and `TestNoSensitiveLogKeys` stays green.
- [ ] A key saved in the panel is used by the next tick with no restart. A unit test proves the resolver reads per call.

**Verify:** `go test ./internal/metadatafill/ ./internal/httpapi/ -race -run 'Key|MetadataFill'` → PASS. Then `make ci`, and the integration command for the new queries.

**Steps:**

- [ ] **Step 1: Migration.**

```sql
-- 0153_metadata_fill_key.up.sql
-- The admin-panel TypeSafe key, SEALED (internal/secretbox, the MFA KEK) or
-- absent. Never plaintext: the handler refuses a key when no KEK is set.
ALTER TABLE metadata_fill_state ADD COLUMN api_key_sealed TEXT
    CHECK (api_key_sealed IS NULL OR api_key_sealed LIKE 'enc:%');
```

```sql
-- 0153_metadata_fill_key.down.sql
ALTER TABLE metadata_fill_state DROP COLUMN IF EXISTS api_key_sealed;
```

`make migrate-lint` may flag the down's `DROP COLUMN` as destructive DDL. Down files are normally exempt; if not, follow the lint's documented escape (read `scripts/migrate-lint.sh`).

Queries:

```sql
-- name: GetMetadataFillSealedKey :one
SELECT api_key_sealed FROM metadata_fill_state WHERE singleton;

-- name: SetMetadataFillSealedKey :exec
UPDATE metadata_fill_state SET api_key_sealed = sqlc.narg('api_key_sealed'), updated_at = now() WHERE singleton;
```

Run `make sqlc`.

- [ ] **Step 2: Failing tests** `internal/metadatafill/key_test.go`

```go
package metadatafill

import (
	"context"
	"testing"

	"github.com/vidra/vidra-core/internal/secretbox"
)

type fakeKeyRepo struct{ sealed *string }

func (f *fakeKeyRepo) GetMetadataFillSealedKey(context.Context) (*string, error) { return f.sealed, nil }
func (f *fakeKeyRepo) SetMetadataFillSealedKey(_ context.Context, v *string) error { f.sealed = v; return nil }

func cipher(t *testing.T) *secretbox.Cipher {
	t.Helper()
	c, err := secretbox.NewCipher(make([]byte, 32))
	if err != nil {
		t.Fatal(err)
	}
	return c
}

func TestKeyResolutionOrderAndLiveness(t *testing.T) {
	repo := &fakeKeyRepo{}
	k := NewKeyStore(repo, cipher(t), "env-key")
	ctx := context.Background()
	if got, src := k.Resolve(ctx); got != "env-key" || src != KeySourceEnv {
		t.Fatalf("env fallback = %q/%s", got, src)
	}
	if err := k.Set(ctx, "admin-key"); err != nil {
		t.Fatal(err)
	}
	if got, src := k.Resolve(ctx); got != "admin-key" || src != KeySourceAdmin {
		t.Fatalf("admin key must win, read per call: %q/%s", got, src)
	}
	if repo.sealed == nil || *repo.sealed == "admin-key" {
		t.Fatal("stored in the clear")
	}
	if err := k.Set(ctx, ""); err != nil || repo.sealed != nil {
		t.Fatalf("clear: err=%v sealed=%v", err, repo.sealed)
	}
}

func TestKeyRefusedWithoutCipher(t *testing.T) {
	k := NewKeyStore(&fakeKeyRepo{}, nil, "")
	if err := k.Set(context.Background(), "x"); err != ErrSecretsKeyMissing {
		t.Fatalf("err = %v, want ErrSecretsKeyMissing", err)
	}
	if err := k.Set(context.Background(), ""); err != nil {
		t.Fatalf("clearing must work without a cipher: %v", err)
	}
}

func TestUndecryptableFallsBackToEnv(t *testing.T) {
	bad := "enc:not-valid"
	k := NewKeyStore(&fakeKeyRepo{sealed: &bad}, cipher(t), "env-key")
	if got, _ := k.Resolve(context.Background()); got != "env-key" {
		t.Fatalf("got %q, want env fallback", got)
	}
	if k.Status(context.Background()) != KeyStatusUndecryptable {
		t.Fatal("undecryptable not reported")
	}
}
```

The generated type of `api_key_sealed` may be `pgtype.Text` rather than `*string`, depending on the sqlc overrides. Match it in the fake and in `key.go`.

- [ ] **Step 3: Implement `internal/metadatafill/key.go`**

```go
package metadatafill

import (
	"context"
	"errors"
	"strings"

	"github.com/vidra/vidra-core/internal/secretbox"
)

// ErrSecretsKeyMissing: no KEK, so a key cannot be stored sealed and will not
// be stored in the clear.
var ErrSecretsKeyMissing = errors.New("metadatafill: no key-encryption key")

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

// KeyRepository is the sealed-key storage. *sqlcgen.Queries satisfies it.
type KeyRepository interface {
	GetMetadataFillSealedKey(ctx context.Context) (*string, error)
	SetMetadataFillSealedKey(ctx context.Context, sealed *string) error
}

// KeyStore resolves the TypeSafe key per call: sealed admin value, else env.
type KeyStore struct {
	repo   KeyRepository
	cipher *secretbox.Cipher
	env    string
}

func NewKeyStore(repo KeyRepository, cipher *secretbox.Cipher, env string) *KeyStore {
	return &KeyStore{repo: repo, cipher: cipher, env: strings.TrimSpace(env)}
}

func (k *KeyStore) admin(ctx context.Context) (string, KeyStatus) {
	sealed, err := k.repo.GetMetadataFillSealedKey(ctx)
	if err != nil || sealed == nil || *sealed == "" {
		return "", KeyStatusNone
	}
	if k.cipher == nil {
		return "", KeyStatusUndecryptable
	}
	plain, err := k.cipher.Open(*sealed)
	if err != nil {
		return "", KeyStatusUndecryptable
	}
	return string(plain), KeyStatusOK
}

// Resolve returns the key and where it came from. It is the judgment.KeyFunc.
func (k *KeyStore) Resolve(ctx context.Context) (string, KeySource) {
	if v, st := k.admin(ctx); st == KeyStatusOK && v != "" {
		return v, KeySourceAdmin
	}
	if k.env != "" {
		return k.env, KeySourceEnv
	}
	return "", KeySourceNone
}

// Key adapts Resolve to judgment.KeyFunc.
func (k *KeyStore) Key(ctx context.Context) string { v, _ := k.Resolve(ctx); return v }

// Status reports the admin key's health.
func (k *KeyStore) Status(ctx context.Context) KeyStatus { _, st := k.admin(ctx); return st }

// Set stores (sealed) or, with "", clears the admin key.
func (k *KeyStore) Set(ctx context.Context, value string) error {
	value = strings.TrimSpace(value)
	if value == "" {
		return k.repo.SetMetadataFillSealedKey(ctx, nil)
	}
	if k.cipher == nil {
		return ErrSecretsKeyMissing
	}
	sealed, err := k.cipher.Seal([]byte(value))
	if err != nil {
		return err
	}
	return k.repo.SetMetadataFillSealedKey(ctx, &sealed)
}
```

Check the signatures in `internal/secretbox/secretbox.go`: `Seal([]byte) (string, error)` at L55, and whether `Open` returns `[]byte` or `string` at L66. Adjust the conversions.

- [ ] **Step 4: Wire it.** In `main.go`:

```go
	keyStore := metadatafill.NewKeyStore(q, mailCipher, cfg.TypeSafeAPIKey)
	judgeClient := judgment.New(cfg.TypeSafeEndpoint, cfg.TypeSafeModel, keyStore.Key)
```

`mailCipher` stands for the local name of the `*secretbox.Cipher` built from `config.MailKEK()` at L449-458; it may be nil. Pass `keyStore` to the server through `WithMetadataFillKeys(keyStore)` and to the evaluator, replacing the static KeyFunc in Task 11.

Add the handler, the `PUT /admin/metadata-fill/key` route (admin-only), and the audit constant `ActionAdminMetadataFillKeyUpdate = "admin.metadata_fill.key_update"`, recorded with `Metadata: []audit.MetadataField{{Key: "secret_changed", Value: "true"}}` and `Reason` `set` or `cleared`. The status view gains `key_source` and `key_status`. Map `ErrSecretsKeyMissing` to `&MetadataFillError{Status: 409, Code: "metadata_fill_secrets_key_missing", Message: "this deployment has no key-encryption key, so the TypeSafe key cannot be stored sealed — and vidra will not store it in the clear. Set MFA_KEY_KEK (or share FEDERATION_KEY_KEK) and restart the api, then save again. TYPESAFE_API_KEY in the env file still works"}`. Update OpenAPI.

HTTP tests: admin-only; 204 set and clear; 409 without a cipher; an audit record with `secret_changed`; and the response body and log buffer never contain the key string. Scan `buf.String()` and fail if `strings.Contains(buf.String(), "sk-test-key")`.

- [ ] **Step 5: Run everything.** `make ci`, `go vet -tags=integration ./...`, and the integration command.

- [ ] **Step 6: Commit**

```bash
git add migrations/0153_* internal cmd/api api/openapi.yaml
git commit -m "feat(metadatafill): admin-panel TypeSafe key, sealed or refused

Reuses internal/secretbox and the MFA KEK the mail settings use; the admin
key wins over TYPESAFE_API_KEY and takes effect on the next tick.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 19: Key field on the card (PR U5, user)

**Goal:** The admin can paste, replace or remove the TypeSafe key on the card with `SecretInput`.

**Files:**
- Regenerate: `lib/api/generated.ts`
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

- [ ] **Step 1: Regenerate** (Task 13, Step 1). Add the wrapper:

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

## Task 20: Beta evaluation, bars, scope ledger (PR M2, meta)

**Goal:** The confidence bars come from a measurement on the beta's human-labelled PeerTube imports, recorded honestly, before auto-fill is switched on there.

**Preconditions (owner steps; this plan does not do them):** a core release containing C1–C11 is cut and deployed to beta (`! ./deploy/release.sh --yes vX.Y.Z`, then the deploy). The feature stays **off**. `TYPESAFE_API_KEY` is set in beta's env file. Beta runs as a no-git bundle tree, so check the memory note on its local compose mount before editing anything there.

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

## Self-review (run 2026-09-26 against the spec)

**Spec coverage:**

| Spec section | Task(s) |
|---|---|
| §4.1 client: key resolution, endpoint, model pin, 5 s timeout, size cap, breaker, closed codes, denylist | 2, 3, 18 (key resolution in two stages: env in 2/8, sealed in 18) |
| §4.2 always-started worker, eligibility, claim, retries, lease reclaim | 7, 8, 4 |
| §4.3 data model (three tables) | 4 |
| §4.4 `enabled_since`, runs, `job_runs` projection, stop, requeue failed | 4, 7, 9 |
| §4.5 `ApplyInferredMetadata`, human-edit clear | 5 |
| §5 request (state, two questions, labels, descriptions, `none_of_these`, `unclear`, 255 cap) | 6 |
| §6 bars and the evaluation subcommand | 6, 11, 20 |
| §7 failure table | 2, 5, 7 (every row has a test) |
| §7 audit rows: toggle, key, run start/stop | toggle via the existing instance-settings audit (`keys=` reason, `admin_instance_settings.go:419`); key 18; runs 9; plus test 9 |
| §8 privacy text | 13 (help), 12 (env and runbook) |
| §9 admin toggle, warn, infra row, status card, key field; Studio marker | 13, 8, 14, 19, 15 |
| §10 contract and configuration, settings count 119 | 8, 9, 10, 3 |
| §11 testing (client, worker, video service, HTTP, frontend unit, mocked e2e, backed against a stub, real service) | 2, 7, 4, 5, 9, 10, 14, 15, 17, 20 |
| §12 PR sequence | §0.3 (split further for the 300-line rule) |

**Gaps knowingly left:** none from the spec. The spec's "per-video fills are recorded in `video_metadata_judgments`, not the audit log" holds by construction: no task writes a per-video audit row.

**Placeholder scan:** Four places tell the implementer to confirm a name against the code rather than guess: the config test helper, the generated sqlc field types, the fixture helpers, and the `ApiError` constructor. Each names the exact file to read. No code block carries a stub or a line meant to be deleted.

**Type consistency:** `judgment.Question`/`Option`/`Answer`/`Result`/`Code`/`KeyFunc` (Task 2) are used unchanged in 6, 7, 9, 11 and 18. `metadatafill.Subject`/`Request`/`Decision`/`BuildRequest`/`Decide`/`QCategory`/`QLanguage`/`NoneOfThese`/`Unclear`/`CategoryBar`/`LanguageBar` (Task 6) are used unchanged in 7 and 11. `video.InferredApplied`/`ApplyInferredMetadata`/`AutoFilled` (Task 5) are used in 7 and 10. `metadatafill.Status`/`ErrRunActive`/`ErrInactive`/`ErrNoRun` (Task 9) are used by the HTTP layer. `ErrSecretsKeyMissing`/`KeyStore` (Task 18) are used in 18 and 11's follow-up.
