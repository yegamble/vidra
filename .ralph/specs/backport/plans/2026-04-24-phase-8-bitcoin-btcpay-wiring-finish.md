# Phase 8 — Bitcoin/BTCPay Wiring Finish Implementation Plan

Created: 2026-04-24
Author: yegamble@gmail.com
Status: COMPLETE
Approved: Yes
Iterations: 1
PendingLiveVerification: docs/plans/2026-04-25-phase-8b-bitcoin-btcpay-finish.md (Phase 8B Live Follow-Up). Parent stays COMPLETE — VERIFIED held until live regtest run is green. Per spec-verify F02.
Worktree: No
Type: Feature
ScopeNote: Mid-Plan Checkpoint exercised 2026-04-25 — this plan ships as Phase 8A (backend foundation: Tasks 0-4). Tasks 5-18 (LND wiring + frontend) become Phase 8B in a fresh `/spec`.

## Summary

**Goal:** Finish C2–C5 from `docs/plans/2026-04-22-feature-parity-audit.md`: tip UX polish (celebration toast, error/expiry recovery, tip-on-comment, **Lightning BOLT11**), a unified transaction history page (Sent + Received with toggle), low-balance + payout-ready notifications, and a manual/auto payout request flow (admin-approves every payout). End-to-end, dual-repo — vidra-core backend + vidra-user frontend.

**Architecture:** Introduce a `payment_ledger` table in vidra-core as the canonical money-movement store (entries: `tip_in`, `tip_out`, `payout_requested`, `payout_approved`, `payout_completed`, `payout_rejected`, `subscription_in`). Backfill from `btcpay_invoices.metadata` on migration. Add a `btcpay_payouts` table (state machine). Wallet balance = running sum of ledger for a given user. Extend BTCPay client with Lightning (LND regtest node added to compose) so the existing `POST /api/v1/payments/invoices` accepts `payment_method: "on_chain" | "lightning"`. New handler surfaces: wallet, transactions (ledger query), payouts (creator + admin). Frontend adds `/settings/transactions` + `/studio/wallet` + `PayoutRequestDialog` + `LowBalanceBanner` + notification consumers. 13-locale i18n. Playwright E2E for all user flows. TDD enforced.

**Tech Stack:** Go (vidra-core, chi router, goose migrations, PostgreSQL), BTCPay Greenfield v1, LND regtest in docker-compose, Next.js 15 App Router (vidra-user), React 19, Tailwind v4, Vitest, Playwright, next-intl. Notifications infrastructure (`/api/v1/notifications`) already exists — we register new types.

## Scope

### In Scope

**Backend (vidra-core):**
- Migration: create `payment_ledger` (UUID PK, `user_id`, `counterparty_user_id NULL`, `channel_id NULL`, `entry_type` enum, `amount_sats BIGINT`, `currency`, `invoice_id NULL`, `payout_id NULL`, `metadata JSONB`, timestamps, indexes on `(user_id, created_at DESC)` and `(entry_type)`).
- Migration: create `btcpay_payouts` (UUID PK, `requester_user_id`, `amount_sats`, `destination` TEXT — on-chain address OR LN invoice, `destination_type` enum, `status` enum — `pending|approved|executing|completed|rejected|cancelled`, `requested_at`, `approved_at NULL`, `approved_by_admin_id NULL`, `executed_at NULL`, `txid NULL`, `rejection_reason NULL`, `auto_trigger BOOL`, timestamps, indexes on `(requester_user_id, status)` and `(status, requested_at)`).
- Migration: backfill existing `btcpay_invoices` rows into `payment_ledger` using `metadata->>'channel_id'` and `metadata->>'type'`. Idempotent (no-op if entries already exist for an invoice).
- Migration: add new `NotificationType` enum values (SQL CHECK updated if present) — `tip_received`, `payout_ready`, `payout_pending_approval`, `payout_approved`, `payout_completed`, `payout_rejected`, `low_balance_stuck`.
- Domain types: `PaymentLedgerEntry`, `LedgerEntryType`, `Payout`, `PayoutStatus`, `PayoutDestinationType`, `LightningInvoice` (LN-specific fields on `BTCPayInvoice`).
- Usecase `LedgerService`: record entries atomically with invoice settlement (webhook handler) and payout state transitions. Running-sum balance query. Ledger list query with `direction=sent|received|all` and `type` filter.
- Usecase `PayoutService`: `RequestPayout(userID, amount, destination, destinationType, autoTrigger)` — validates amount ≤ available balance, writes ledger `payout_requested` entry (reserves funds), writes `btcpay_payouts` row, emits notifications. `ApprovePayout` / `RejectPayout` (admin only). `MarkExecuted` (admin, post-on-chain-send, records txid, writes `payout_completed` ledger entry). `CancelPayout` (creator, only when `pending`). `ListMyPayouts`, `ListPendingPayouts` (admin).
- BTCPay client additions:
  - `CreateInvoice` accepts `PaymentMethodConfig` (on-chain, lightning, or both) — Greenfield supports `POST /api/v1/stores/{id}/invoices` with `checkout.paymentMethods: ["BTC","BTC-LightningNetwork"]`.
  - `GetInvoicePaymentMethods(invoiceID)` — returns both on-chain and LN destinations + per-method status.
  - `CreateStorePayout(amount, destination, paymentMethod)` — for Task: admin-executed payout via Greenfield `/stores/{id}/payouts`.
- Compose: add `lnd` (Lightning Network Daemon) service in `vidra-core/docker-compose.yml` pinned to a specific regtest image with `bitcoind` backend, healthcheck, persistent volume. `btcpay-server` gets LN connection env pointing at `lnd`. Bootstrap script (`btcpay-bootstrap.sh`) extended: mint LND wallet seed, open channel to a second LN node if needed (optional for regtest), wire LN payment method into the `vidra-dev` store.
- Handlers (`/api/v1/payments`):
  - `GET /wallet/balance` → `{ available_sats, pending_sats, currency }`.
  - `GET /wallet/transactions?direction=sent|received|all&type=&start=&count=&start_date=&end_date=` → paginated ledger list with `counterparty_name` hydrated from users/channels.
  - `POST /payouts` (request payout) — body `{ amount_sats, destination, destination_type: "on_chain" | "lightning_bolt11", auto_trigger: bool }`.
  - `GET /payouts/me` (creator's own list).
  - `DELETE /payouts/{id}` (creator cancels own `pending`).
  - `PATCH /payouts/{id}/approve` (admin, with optional note).
  - `PATCH /payouts/{id}/reject` (admin, with `rejection_reason`).
  - `PATCH /payouts/{id}/mark-executed` (admin, with `txid` or LN-payment-hash).
  - `GET /admin/payments/payouts?status=` (admin queue).
- Webhook (`POST /payments/webhooks/btcpay`): on `InvoiceSettled`, write ledger entries — `tip_out` for payer, `tip_in` for recipient (resolved from `metadata->>'channel_id'` → channel.owner_user_id). Emit `tip_received` notification. On `InvoiceExpired` / `InvoiceInvalid`, no ledger write but update invoice row.
- Background worker (lightweight goroutine, interval 1h): scans users whose received balance > 0 AND < `min_payout_sats` (config, default 50_000 sats) for > 7 days → emit `low_balance_stuck`; users who just crossed above `min_payout_sats` → emit `payout_ready` (idempotent via `payment_notification_cooldowns` table from migration 098; 24h cooldown per user per type).
- Unit tests for ledger, payout service, balance math; handler-level integration tests with testcontainer-postgres.

**Frontend (vidra-user):**
- `paymentService` extension: `getWalletBalance`, `getWalletTransactions`, `createInvoice` accepts `payment_method`, `requestPayout`, `listMyPayouts`, `cancelPayout`, admin `listPendingPayouts`, `approvePayout`, `rejectPayout`, `markPayoutExecuted`, `getInvoicePaymentMethods`.
- Every new service method has sibling tests (hard-rule: stop-hook enforced).
- `TipModal` (`src/components/tip-modal.tsx`):
  - Add method selector: **On-chain BTC** / **Lightning** (with sat/USD conversion). Default Lightning when enabled.
  - After `Settled` status: celebration toast (`sonner`-style or existing toaster) + animated confetti-free success panel ("You tipped @{channel}!"), dismissable.
  - `Expired` / `Invalid` status polling transitions: surface reason from `invoice.metadata->>'failure_reason'` or default, provide **Try again** CTA that creates a fresh invoice with same params.
  - Auto-refresh status every 3s while open (bounded to 2 min, then user-initiated).
- Tip-on-comment (`src/components/comment-section.tsx` OR new `tip-comment-button.tsx`): small Heart icon next to comment metadata — only visible when comment-author's channel is active and has a bitcoin_wallet set. Opens `TipModal` prefilled with the comment's author+channel.
- Route: `/settings/transactions` (new). Component `TransactionsPage` with segmented `Sent` / `Received` / `All` toggle, `type` filter (All / Tips / Inner Circle / Payouts / Subscriptions), date range, pagination, CSV export.
- Route: `/studio/wallet` (new; gated behind `user.is_creator` OR channel ownership). Component `WalletPage` with:
  - Balance card (`available_sats`, `pending_sats`, USD equivalent).
  - `LowBalanceBanner` (dismissable) when balance > 0 AND < min-payout OR `payout_ready`.
  - `Request Payout` CTA → `PayoutRequestDialog`.
  - Recent Transactions preview (last 10).
  - My Payouts list with status.
- `PayoutRequestDialog`:
  - Form fields: `amount_sats` (slider + input, max = available balance), `destination_type` (On-chain / Lightning), `destination` (address OR BOLT11 invoice with paste/scan), `auto_trigger` toggle ("Auto-request future payouts when balance crosses this amount").
  - Client-side validation: address format per type, amount > min payout, amount ≤ balance.
- Admin payouts queue: new route `/admin/payments/payouts` (admin role gated). Page lists `pending` requests. Per-row Approve / Reject with confirmation dialog + optional note / reason. After approve, admin can mark executed with `txid` (or LN payment hash).
- Notifications consumption (`src/components/notification-bell.tsx` or equivalent): icon + message + link for each new notification type. Full-locale i18n keys in 13 locales.
- i18n keys (added to all 13 locales; `pnpm i18n:check` parity):
  - `Tip.*`: `celebration`, `tryAgain`, `expiredReason`, `methodOnChain`, `methodLightning`, etc.
  - `Transactions.*`: page title, toggle labels, type filter, empty states, export CSV, pagination.
  - `Wallet.*`: balance card, low-balance banner variants, payout CTA.
  - `Payout.*`: dialog copy, validation, statuses, admin approval + rejection flows.
  - `Notifications.*`: titles + messages for 7 new notification types.
  - `AdminPayouts.*`: queue page copy.
- Playwright E2E (10 specs total, scoped to `e2e/payments-*`): on-chain tip, Lightning tip, tip-on-comment, transaction history toggle, payout request (on-chain), payout request (Lightning), admin approve + mark executed, admin reject, low-balance notification trigger, auto-payout queueing (creator side only — no hot wallet).
- Update `docs/plans/2026-04-22-feature-parity-audit.md` — C2–C5 move to `done ✓`, Lightning note added.
- Update memory (`project_payments_architecture.md` + `project_payment_reconciliation.md`) with ledger + payout + LN flow.

### Out of Scope

- Polar (card) changes — this spec is 100% BTCPay/Bitcoin. Polar stays as-is (Inner Circle only).
- Inner Circle membership persistence/gating (C6–C9) — separate Phase 9 per audit.
- Hot-wallet automation: admin approves every payout. No automated on-chain broadcast; ops executes outside the app (phase 12 or later).
- KYC / AML workflows — deferred.
- Multi-currency ledger — BTC only.
- Tip refund flow — out of scope; tips are final per BTCPay semantics.
- Push notifications (email / FCM) for payment events — only in-app notifications in this spec.
- Running the stop-hook enforced `pnpm i18n:check` for ALL keys — only new keys in this spec must cover 13 locales; pre-existing gaps are not introduced nor fixed here.

## Approach

**Chosen:** Dual-repo, single large spec, all four items end-to-end.

**Why:** The user explicitly chose "One big dual-repo spec — all 4 items at once" + "Include LN fully" + "payment_ledger table" + "Admin approves every payout." Splitting would have been safer; the plan reflects that choice with correspondingly more tasks, more risks documented, and explicit verification gates per subsystem to keep each task independently shippable and revertible.

**Alternatives considered:**
- *Phase 8A / 8B split (recommended in Batch 2):* Smaller review surface, shippable in 1–2 weeks; rejected because user asked for all-at-once.
- *Frontend-only with 404 degradation:* Avoids backend work; rejected because it creates UI-only features the audit explicitly flagged as anti-pattern.
- *Metadata-JSONB transaction model:* Simpler migration; rejected in favor of `payment_ledger` per user choice (flexibility for future multi-currency, fees, refunds).
- *Hot-wallet automated payouts:* Higher UX; rejected for attack-surface reasons per user choice.

## Context for Implementer

> Written for an implementer who has never seen the codebase.

- **Patterns to follow:**
  - Frontend service layer: thin fetch wrappers returning typed results — `src/lib/api/services/payments.ts`. Every service file has a sibling test under `src/lib/api/services/__tests__/` (hard rule, stop-hook enforced).
  - Next.js page wrappers are trivial: `src/app/[locale]/(main)/<route>/page.tsx` imports a component from `src/components/pages/<name>.tsx`.
  - Modals follow `src/components/tip-modal.tsx` shape (fixed backdrop-blur, rounded card, escape-close).
  - Go handlers follow `vidra-core/internal/httpapi/handlers/payments/btcpay_handlers.go` — receive service via constructor, parse + validate request, call usecase, write JSON.
  - Go usecases follow `vidra-core/internal/usecase/payments/btcpay_service.go` — interface-driven, repo injected.
  - Domain types mirror DB row shape in `vidra-core/internal/domain/*.go` — JSON tags explicit, `uuid.UUID` for PKs.
  - Migrations: `vidra-core/migrations/NNN_description.sql` with `-- +goose Up` / `-- +goose Down` blocks; see `091_drop_iota_add_btcpay.sql`.
  - Notifications: add new `NotificationType` constant in `vidra-core/internal/domain/notification.go`; use existing `NotificationService.Create` from any usecase.
  - E2E specs live under `e2e/`; helpers in `e2e/helpers/`; seeded admin login via `e2e/fixtures/auth.ts`.
- **Conventions:**
  - `'use client'` required for any React component using hooks/events.
  - `@/` alias maps to `src/` in vidra-user.
  - Errors go through `@/lib/telemetry/logger`, not `console.*`.
  - TypeScript strict mode — no `any`.
  - Go: handlers never call DB directly; always via usecase; usecase never imports http/handlers packages.
  - Every migration has a real Down that reverses the Up.
  - Every service function gets a test (frontend); every usecase function gets a test (backend).
- **Key files:**
  - `../vidra-core/internal/domain/btcpay.go` — existing BTCPay domain types; extend for LN and ledger references.
  - `../vidra-core/internal/usecase/payments/btcpay_service.go` — existing invoice usecase; extend for LN payment method pass-through.
  - `../vidra-core/internal/httpapi/handlers/payments/btcpay_handlers.go` — existing handlers; this spec adds new handlers in the same package.
  - `../vidra-core/internal/httpapi/routes.go:441–453` — payment routes registration site.
  - `../vidra-core/internal/domain/notification.go:10–31` — NotificationType constants.
  - `../vidra-core/docker-compose.yml` — compose for dev; extend with `lnd` service + networking.
  - `../vidra-core/migrations/091_drop_iota_add_btcpay.sql` — last BTCPay migration; numbering reference for new migrations.
  - `src/lib/api/services/payments.ts` — frontend payments service (extend).
  - `src/lib/api/services/__tests__/payments.test.ts` — sibling test (extend).
  - `src/components/tip-modal.tsx` — existing tip UI (extend).
  - `src/components/comment-section.tsx` — comment list (integrate tip-on-comment button).
  - `src/components/pages/settings-page.tsx:337–412` — existing invoice list (link to new transactions page).
  - `messages/en.json` — 33-section i18n file; new keys added to sections, mirrored to all 12 other locales.
  - `scripts/i18n-check.mjs` (existing) — verifies locale-key parity.
  - `scripts/btcpay-bootstrap.sh` — extend for LND wiring.
- **Gotchas:**
  - vidra-core's `btcpay_invoices` stores recipient info only in `metadata` JSONB — backfill task must parse `metadata->>'channel_id'` and resolve to `channel.owner_user_id`. Invoices without `channel_id` metadata (paid by non-tip flow) skip recipient assignment.
  - Balance math is AUTHORITATIVE from ledger; never re-derive from invoices (tip_in on InvoiceSettled writes the ledger — not invoice lookup).
  - Payout request reserves funds: write a `payout_requested` ledger entry (negative amount) at request time, NOT at admin approval. If admin rejects, write a compensating `payout_rejected` (positive) entry. If creator cancels `pending`, write same compensating entry.
  - LN invoices via BTCPay Greenfield: `checkout.paymentMethods` in the request body; response exposes BOTH on-chain address AND LN bolt11 via `GET /invoices/{id}/payment-methods`. The existing `/payments/invoices/{id}` handler's response shape needs extending to include LN fields (`lightning_invoice`, `lightning_expires_at`).
  - LND regtest in docker-compose needs network access to `bitcoind` service. Existing compose uses the `vidra-network` bridge (verified line 22–23 of `../vidra-core/docker-compose.yml`); add `lnd` to the same network. BTCPay connects to LND via gRPC (TLS cert + admin.macaroon, base64-encoded into a Greenfield connection string). BTCPay 2.3.3 Greenfield endpoint: `PUT /api/v1/stores/{storeId}/payment-methods/LightningNetwork/BTC` with body `{ connectionString, enabled: true, internalNodeRef: null }`. NOT `POST` with `BTC-LightningNetwork` — that's the OLDER path shape.
  - Stop-hook rule "every service must have a test or be removed" — for each new service method added to `paymentService`, append cases to `src/lib/api/services/__tests__/payments.test.ts` in the SAME commit.
  - `messages/en.json` is the source of truth; `scripts/i18n-check.mjs` fails CI if other locales have missing keys. We add keys to ALL 13 files in the same commit.
  - `window.open` for LN BOLT11 deep links (`lightning:<invoice>`) varies by OS — fall back to copy-to-clipboard + QR render.
  - Notifications spawn via background worker: the worker must be registered in `vidra-core/cmd/vidra/main.go` startup alongside existing ones. Idempotency key: `(user_id, notification_type, day_bucket)` in Redis if available, else in memory.
  - Stop-hook enforcing vision also wants `## PeerTube Parity Check` + `## Vidra-Specific / Requested Features` + `## Verification Plan` headings — this plan has them.
- **Domain context:**
  - **BTCPay Greenfield v1 Lightning:** `POST /api/v1/stores/{id}/invoices` with body `{ amount, currency, checkout: { paymentMethods: ["BTC","BTC-LightningNetwork"] } }`. GET `/invoices/{id}/payment-methods` returns array with `paymentMethod: "BTC"` or `"BTC-LightningNetwork"` and a `destination` (address or BOLT11).
  - **BTCPay payouts:** `POST /api/v1/stores/{id}/payouts` with `{ destination, amount, paymentMethod }`. Response tracks status; admin pays manually via BTCPay UI in this spec (we store the destination/amount and surface it; no auto-broadcast).
  - **Regtest Lightning:** LND + bitcoind + optional `lightning-channel-faucet` pattern; we DON'T open real LN channels in E2E — instead we use BTCPay's "pay-to-regtest-LN-invoice" capability where it generates an invoice and we generate+pay a second-node invoice locally. For MVP, payment of LN invoice is driven by `lncli` inside the `lnd` container in the E2E spec.
  - **Payment ledger invariant:** `SUM(amount_sats) per user_id` = available balance. Reservations use negative entries. Balance is always computed at query time (no materialized cache in v1); add a `get_balance(user_id)` SQL function if query perf degrades.

## Runtime Environment

- **Start command:** `pnpm dev:full` (vidra-user script `scripts/start-dev.sh`; brings up `../vidra-core/docker-compose.yml` stack + Next.js dev server).
- **Frontend port:** 3000 — http://localhost:3000
- **Backend port:** 8080 — http://localhost:8080 (vidra-core `app` service; 9000 is occupied by `whisper`)
- **BTCPay port:** 14080 (host) → 49392 (container) — http://localhost:14080
- **LND REST port (new):** 18080 (host) → 8080 (container). 18443 is bitcoind's container-internal RPC — do NOT reuse.
- **LND gRPC port (new, BTCPay uses this internally):** 10009 (container-internal on `vidra-network`). No host publish needed.
- **Docker compose network:** `vidra-network` (defined in `../vidra-core/docker-compose.yml`). All new services (`lnd`) attach to this network.
- **Bitcoind regtest CID:** resolve dynamically `BITCOIND_CID=$($COMPOSE ps -q bitcoind)`; auth `-regtest -rpcuser=vidra -rpcpassword=vidra`.
- **LND container CID (new):** resolve dynamically `LND_CID=$($COMPOSE ps -q lnd)`; `docker exec -i $LND_CID lncli --network=regtest ...`.
- **Health checks:** `/health` (core, port 8080); `/api/v1/health` (BTCPay); `lncli getinfo` (LND); BTCPay → LN connectivity: `POST /api/v1/stores/{id}/lightning/BTC/info` returns 200.
- **Restart:** `pnpm dev:clean && pnpm dev:full`.

## Assumptions

- User running `pnpm dev:full` on macOS / Linux Docker Desktop with ≥ 8GB RAM available — LND adds ~500MB. Tasks 5, 17 depend on this.
- vidra-core `main` branch allows breaking changes via migrations — Tasks 1, 2, 5 depend on this.
- No production data exists yet (pre-launch); the `payment_ledger` backfill migration runs against clean or near-empty data in dev. Tasks 1, 2 depend on this.
- BTCPay Server 2.3.3 running in regtest supports the Lightning Network payment method configuration via Greenfield API (verified via BTCPay docs 2.x).
- `scripts/i18n-check.mjs` exists and is wired to CI (per memory: Phase 6 remediation added it). Tasks 16, 18 depend on this.
- Existing `e2e/payments-tip-btcpay.spec.ts` regtest harness still works (CID resolution, seeded admin, mine-101 bootstrap from `btcpay-bootstrap.sh`). Tasks 10, 17 depend on this.
- Notifications bell component (`src/components/notification-bell.tsx` or similar) already handles new notification types by rendering `title` + `message` from the payload, so adding enum values on the backend is sufficient visibility; if display is ENUM-switched on frontend, Task 15 adds the new cases explicitly.
- vidra-core does NOT need to broadcast on-chain payouts (ops executes externally); the app only records approval + txid. This is codified in Task 4 acceptance.

## Risks and Mitigations

⚠️ Mitigations are commitments — verification checks they're implemented.

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Ledger double-write on webhook retry | High | High (balance corruption) | Webhook idempotency key = `(invoice_id, entry_type)` UNIQUE constraint on `payment_ledger`; INSERT … ON CONFLICT DO NOTHING. Integration test simulates duplicate webhook delivery; balance invariant holds. |
| Payout reservation bypassed (creator spends funds already reserved for a pending payout) | Medium | Critical | `PayoutService.RequestPayout` runs in a transaction: SELECT SUM(amount) … FOR UPDATE on ledger, verify ≥ requested amount, then INSERT `payout_requested` negative entry + INSERT `btcpay_payouts` row. Integration test forces concurrent requests; second fails with `InsufficientBalance`. |
| LND regtest flakiness blocks E2E | High | Medium | Task 17 has `test.skip()` guards that detect LND health — if unhealthy, Lightning specs skip with clear reason; on-chain specs still run. Bootstrap script `btcpay-bootstrap.sh` extended to init LND wallet + connect to BTCPay idempotently; retries 60s then errors. |
| Migration backfill loses data | Medium | High | Migration 096 is IDEMPOTENT — `ON CONFLICT DO NOTHING` via unique-per-invoice key. Before-after row counts logged. Down migration truncates `payment_ledger` and leaves `btcpay_invoices` untouched (ledger is derivative). |
| Admin approves a payout twice (double-send risk) | Medium | Critical | `PATCH /payouts/{id}/approve` transitions `pending → approved` only; validates current status. Integration test asserts second call returns `409 Conflict`. Admin UI disables Approve button after first click + optimistic status update. |
| Balance query N+1 on transactions page | Medium | Medium | Ledger query joins users + channels ONCE (`LEFT JOIN users cu ON counterparty_user_id = cu.id`); returns hydrated `counterparty_name`. No per-row additional queries. Explicit `EXPLAIN` check in DoD. |
| Stop-hook fails because new services lack test files | High | Medium | Every new service method gets sibling test cases in the SAME commit; Tasks 6, 8, 11, 12, 13, 14 DoDs include `pnpm test:run <path>` + `grep` for test cases count ≥ method count. |
| i18n parity break (keys added only to en.json) | High | Medium | Tasks 16 + 18 require `pnpm i18n:check` exit 0. Translations use reasonable native equivalents (not machine-translated placeholder). CI blocks merge on gap. |
| LN invoice decode shows raw BOLT11 string (UX regression) | Medium | Low | `PayoutRequestDialog` uses `bolt11` npm package (existing or added) to decode + display amount + description; rejects if decoded amount ≠ user-entered amount. Task 13 covers this. |
| Ledger `payout_requested` never gets compensated if payout row is soft-deleted | Low | High | Cancellations/rejections ALWAYS write a compensating entry in the same transaction; payout rows are NEVER hard-deleted — status goes `cancelled` / `rejected`. Integration test covers reject path + balance restoration. |
| TypeScript `any` / strict mode violations | Medium | Low | CI `pnpm typecheck` exit 0 gate. Task 18 verifies. |
| Codex adversarial review finds design flaw | Medium | Medium | Step 11 runs Codex if enabled; must_fix/should_fix applied before approval. |
| Playwright flake via LN invoice popup blocker | Medium | Low | Tests use `page.context().waitForEvent('page')` with 10s tolerant timeout; primary proof is `/api/v1/payments/invoices` response body + DOM state, not popup behavior. |
| Frontend service methods added without backend deploy available | Low | Medium | All 19 tasks are ordered: backend tasks (1–5, 15) precede frontend service tasks (6+). CI runs `go build ./...` + `go test ./...` green gates. |
| Plan tasks > 12 (over spec-plan guideline) | Given | **High** | Spec-plan rule says suggest splitting at 12. User explicitly chose single-spec scope — documented as an autonomous decision. **MITIGATION: explicit MID-PLAN CHECKPOINT after Task 5 (`## Mid-Plan Checkpoint` section below) — implementation pauses, re-confirms green backend before touching frontend. Each task remains independently shippable + revertible.** |
| LND regtest flakiness blocks E2E even with skip-guards | Medium | High | `payments-health.spec.ts` is un-skippable; per-run skip-ratio guard in reporter fails CI when > 50% of payments specs skip (even if backend /health passes). |
| Debug endpoint leaks into production build | Low | Critical | Build tag `debug` compiles the endpoint OUT of production builds. Runtime startup check: if `ENV=production` and debug-tagged binary is run, log.Fatal. |

## Goal Verification

### Truths (falsifiable, user-perspective)

1. **T1**: `POST /api/v1/payments/invoices` with `{amount_sats:1000, payment_method:"lightning"}` returns a body containing non-empty `lightning_invoice` (BOLT11) and the corresponding invoice on `GET /invoices/{id}/payment-methods` shows `paymentMethod: "BTC-LightningNetwork"`.
2. **T2**: After a BTCPay `InvoiceSettled` webhook for a tip to channel X, `GET /api/v1/payments/wallet/balance` for X's owner returns `available_sats` increased by exactly the tipped amount; `GET /wallet/transactions?direction=received` lists one new `tip_in` entry with correct counterparty name. Replaying the same webhook payload does NOT double-count (balance unchanged).
3. **T3**: `POST /api/v1/payments/payouts {amount_sats:5000, destination:"bcrt1q...", destination_type:"on_chain"}` returns 201, `GET /wallet/balance` shows `available_sats` dropped by 5000 (reserved), and a new row in `btcpay_payouts` with `status:"pending"`. Concurrent second request (balance insufficient) returns `409 Conflict` with `code:"insufficient_balance"`.
4. **T4**: Admin `PATCH /payouts/{id}/approve` transitions `pending→approved`; second call returns `409`. Admin `PATCH /payouts/{id}/mark-executed {txid:"abc"}` transitions `approved→completed` and writes `payout_completed` ledger entry (balance unchanged from reservation).
5. **T5**: In the browser, opening a video watch page → clicking Tip → selecting **Lightning** → pasting the BOLT11 into `lncli payinvoice` in the LND container → polling shows invoice status → `Settled` → celebration toast appears with "$X to @channel".
6. **T6**: Inline Heart button beside a comment opens `TipModal` prefilled with the comment-author's channel; tipping behaves identically to watch-page tip. Inline button is HIDDEN for anonymous commenters (no channel).
7. **T7**: `/settings/transactions` page renders Sent/Received/All toggle; switching to Received after a tip settles shows the tip. Type filter "Tips" narrows the list correctly. CSV export downloads a UTF-8 CSV with expected columns.
8. **T8**: `/studio/wallet` shows balance card, `LowBalanceBanner` (when < min-payout and > 0), Request Payout CTA, and the 10 most recent transactions.
9. **T9**: `PayoutRequestDialog` submission creates a payout; backend receives a `payout_pending_approval` notification (for admin) and `payout_approved` / `payout_rejected` notifications reach the creator upon admin action. Notifications are visible in the existing bell UI with locale-correct title/message.
10. **T10**: Admin page `/admin/payments/payouts` lists pending requests across all users; Approve + Mark Executed transitions the row and advances notifications. Reject with reason restores creator balance in `GET /wallet/balance`.
11. **T11**: Background worker emits `payout_ready` when a user's balance first crosses `min_payout_sats`, and `low_balance_stuck` when balance > 0 AND < `min_payout_sats` for 7+ days. Both are idempotent per 24h cooldown.
12. **T12**: `pnpm typecheck` exit 0; `pnpm lint` no errors; `pnpm test:run` fail count ≤ baseline; `pnpm i18n:check` exit 0 for 13 locales; `pnpm build` exit 0; `go test ./...` in vidra-core exit 0.
13. **T13**: All 10 Playwright specs (`e2e/payments-*.spec.ts`) pass against `pnpm dev:full` stack with LND + BTCPay regtest running.
14. **T14**: `docs/plans/2026-04-22-feature-parity-audit.md` marks C2–C5 as `done ✓` and Phase 8 of the Recommended phases is annotated complete. Memory files updated.

### Artifacts

- `../vidra-core/migrations/094_payment_ledger.sql`
- `../vidra-core/migrations/095_btcpay_payouts.sql`
- `../vidra-core/migrations/096_backfill_ledger_from_invoices.sql`
- `../vidra-core/migrations/097_payment_notification_types.sql`
- `../vidra-core/internal/domain/payment_ledger.go`, `payout.go` (+ tests)
- `../vidra-core/internal/usecase/payments/ledger_service.go`, `payout_service.go`, `balance_worker.go` (+ tests)
- `../vidra-core/internal/httpapi/handlers/payments/wallet_handlers.go`, `payout_handlers.go`, `admin_payout_handlers.go` (+ tests)
- `../vidra-core/internal/payments/btcpay_lightning.go` (LN methods on client + tests)
- `../vidra-core/docker-compose.yml` (LND service added)
- `src/lib/api/services/payments.ts` (extended)
- `src/lib/api/services/__tests__/payments.test.ts` (extended)
- `src/components/tip-modal.tsx` (extended)
- `src/components/__tests__/tip-modal.test.tsx` (extended)
- `src/components/tip-comment-button.tsx` + tests
- `src/components/pages/transactions-page.tsx`, `wallet-page.tsx`, `admin-payouts-page.tsx` + tests
- `src/components/payout-request-dialog.tsx`, `low-balance-banner.tsx` + tests
- `src/app/[locale]/(main)/settings/transactions/page.tsx`, `src/app/[locale]/(main)/studio/wallet/page.tsx`, `src/app/[locale]/(main)/admin/payments/payouts/page.tsx`
- `messages/{en,es,fr,de,ja,zh,ko,pt,ru,ar,it,pl,nl}.json` (new keys across 13 locales)
- 10 new `e2e/payments-*.spec.ts` files
- `scripts/btcpay-bootstrap.sh` (LND wiring extension)
- `docs/plans/2026-04-22-feature-parity-audit.md` (C2–C5 updates)
- Memory: `project_payments_architecture.md`, `project_payment_reconciliation.md` (refreshed)

## E2E Test Scenarios

### TS-001: Tip via on-chain BTC (celebration + polish)
**Priority:** Critical
**Preconditions:** `pnpm dev:full` up; BTCPay bootstrap complete; 101+ regtest blocks mined; seeded video.
**Mapped Tasks:** Task 8, Task 10

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Log in as seeded admin, navigate to seeded video | Watch page renders, Tip button visible |
| 2 | Click Tip, select $5 preset, ensure method = On-chain, click Create | Modal shows invoice with bitcoin address + QR |
| 3 | In bitcoind: `sendtoaddress <addr> 0.00007250 && generatetoaddress 6 <mining-addr>` | 6 blocks mined, invoice status polled to Settled |
| 4 | Wait up to 30s for poll | Celebration toast appears: "You tipped @seededchannel — $5.00" + success panel |
| 5 | Click Done | Modal closes, toast persists for 5s then fades |

### TS-002: Tip via Lightning BOLT11
**Priority:** Critical
**Preconditions:** LND healthy in compose; `btcpay-bootstrap.sh` has wired LND to the `vidra-dev` store.
**Mapped Tasks:** Task 5, Task 8, Task 10

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Login, open a seeded video, click Tip | Modal opens |
| 2 | Select $1 preset, switch method to Lightning, click Create | Invoice shows BOLT11 string + QR + "Pay with any Lightning wallet" |
| 3 | In LND container: `lncli --network=regtest payinvoice <bolt11>` | LN payment completes; BTCPay marks invoice Settled |
| 4 | Poll status (≤30s) | Status → Settled, celebration toast shown |

### TS-003: Tip on comment
**Priority:** High
**Preconditions:** Seeded comment under a seeded video; comment author's channel has `bitcoin_wallet` set.
**Mapped Tasks:** Task 9

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Open the watch page with comments | Comment list renders; each eligible comment shows a Heart tip icon |
| 2 | Click Heart next to the seeded comment | TipModal opens with commenter's channel prefilled |
| 3 | Tip $1 via on-chain, complete as TS-001 steps 3–4 | Ledger `tip_in` entry appears for commenter's channel owner |

### TS-004: Transaction history Sent ↔ Received toggle
**Priority:** High
**Preconditions:** At least one Settled tip exists (TS-001 run first).
**Mapped Tasks:** Task 11

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Navigate to `/settings/transactions` as the tipper | Page renders, Sent tab active, tip row visible with correct amount/counterparty |
| 2 | Click Received | Empty state (no tips received) |
| 3 | Logout, login as seeded admin (the channel owner), revisit the page, click Received | The tip appears with correct sender + amount |
| 4 | Apply "Tips" type filter | Only tip rows remain |
| 5 | Click Export CSV | `.csv` downloads; first row header, subsequent rows match filtered set |

### TS-005: Wallet page balance + low-balance banner
**Priority:** High
**Preconditions:** Creator has pending balance < min_payout (configure `MIN_PAYOUT_SATS=50000`, seeded balance ~7250 sats from TS-001).
**Mapped Tasks:** Task 12

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Login as creator, navigate to `/studio/wallet` | Balance card shows 7,250 sats (~$0.05); LowBalanceBanner visible: "Your balance is below the 50,000 sat minimum payout" |
| 2 | Dismiss banner | Banner hidden; localStorage flag set |

### TS-006: Payout request (on-chain) + admin approve + mark executed
**Priority:** Critical
**Preconditions:** Creator balance ≥ 50,000 sats (seed additional Settled tips to meet threshold).
**Mapped Tasks:** Task 12, Task 13, Task 14

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Creator navigates to `/studio/wallet`, clicks Request Payout | Dialog opens; balance displayed |
| 2 | Enter amount 50,000 sats, destination `bcrt1q...` (any regtest address), type On-chain, submit | Dialog closes; toast "Payout request submitted"; My Payouts list shows new row status=pending; balance card drops by 50,000 sats (reserved) |
| 3 | Login as admin, navigate `/admin/payments/payouts` | Page lists the pending request with creator name + amount |
| 4 | Click Approve with note "Verified", confirm | Row status=approved; creator gets `payout_approved` notification in their bell |
| 5 | Admin clicks Mark Executed, enters `txid=abc123def`, confirm | Row status=completed; creator gets `payout_completed` notification; balance unchanged (already reserved) |
| 6 | Back on creator wallet page | My Payouts row shows status=completed with txid link |

### TS-007: Payout request (Lightning BOLT11)
**Priority:** High
**Preconditions:** Same as TS-006 + `lncli` available to mint a BOLT11 invoice.
**Mapped Tasks:** Task 13

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | In LND: `lncli --network=regtest addinvoice --amt_msat=50000000` | BOLT11 invoice generated |
| 2 | Creator opens PayoutRequestDialog, type=Lightning, paste BOLT11, submit | Decoded amount matches entered; row created pending |
| 3 | Admin approves + marks executed with LN payment hash | State machine advances to completed |

### TS-008: Payout reject restores balance
**Priority:** High
**Preconditions:** A payout request from TS-006 in pending state.
**Mapped Tasks:** Task 14

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Admin rejects with reason "duplicate request" | Row status=rejected; reason stored |
| 2 | Creator refreshes wallet page | Balance restored by payout amount; notification "Payout rejected — duplicate request" in bell |

### TS-009: Low-balance + payout-ready notifications fire
**Priority:** Medium
**Preconditions:** Ability to trigger the background worker interval (shorten to 10s in test env).
**Mapped Tasks:** Task 15

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Seed a user with balance 5,000 sats older than 7 days | After worker tick, `low_balance_stuck` notification exists in bell |
| 2 | Credit user by 100,000 sats (via seed, not real tip) | After next tick, `payout_ready` notification appears |
| 3 | Wait 24h (or simulate cooldown) + tick again | No duplicates (idempotency) |

### TS-010: Invoice expiry recovery
**Priority:** Medium
**Preconditions:** TipModal opened with a short-TTL invoice (mock `expires_at` to 1min in future).
**Mapped Tasks:** Task 8

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Wait for invoice to expire | Status panel updates to "Expired"; red banner with "Try again" CTA |
| 2 | Click Try again | Fresh invoice created with same amount/method; status returns to New |

---

## Mid-Plan Checkpoint (per spec-review F01)

**After Task 5 completes — STOP before Task 6.** The backend is a cohesive, testable unit; the frontend work is separable. Re-confirm readiness before touching frontend:

1. Run `(cd ../vidra-core && go build ./... && go test ./...)` — green.
2. Run `pnpm dev:full`; verify BTCPay + LND are healthy; run `scripts/btcpay-bootstrap.sh` + `scripts/lnd-bootstrap.sh`; end with `curl -sS http://localhost:14080/api/v1/stores/$BTCPAY_STORE_ID/lightning/BTC/info` returning 200.
3. Manual smoke: `curl -sS -X POST http://localhost:8080/api/v1/payments/invoices -H "Authorization: Bearer $JWT" -d '{"amount_sats":1000,"payment_method":"lightning"}'` returns invoice with non-empty `lightning_invoice`.
4. Manual smoke: `curl -sS http://localhost:8080/api/v1/payments/wallet/balance -H "Authorization: Bearer $JWT"` returns 200 with `{available_sats, pending_payout_sats, ...}`.
5. **Re-approval checkpoint** — `AskUserQuestion`: continue to Task 6+, or stop here (split Phase 8A complete, start Phase 8B as a new spec)? User's answer is BINDING; if "stop," this plan's status flips to VERIFIED for backend-only scope, and a fresh spec picks up Task 6 onward.

This checkpoint is non-optional — plan execution cannot silently blow through it.

## Progress Tracking

- [x] Task 0: Capture baseline `pnpm test:run` + `go test ./...` snapshots
- [x] Task 1: vidra-core migrations 094–098 (ledger, payouts, backfill, notification types, cooldowns) + down tested
- [x] Task 2: Domain types + `LedgerService` + webhook integration + unit tests (5/5 LedgerService + 6/6 ledger repo tests pass; build green)
- [x] Task 3: Wallet balance + transactions handlers + integration tests (7/7 wallet handler tests pass; F02 balance-math invariant verified)
- [x] Task 4: `PayoutService` + creator + admin handlers + integration tests (9/9 service + 3/3 handler tests; F03 idempotency keys + F04 dropped executing + F05 race-safe transitions all verified)
- [ ] Task 5: BTCPay client Lightning support + `lnd` service in compose + bootstrap extension + `scripts/lnd-bootstrap.sh`
- [x] **MID-PLAN CHECKPOINT — exercised 2026-04-25; user elected to split. Tasks 5-18 deferred to Phase 8B `/spec`.**

> **Tasks 5-18 below are PHASE 8B SCOPE — handed off to a fresh `/spec`. They remain in this plan as the canonical reference.**

- [ ] Task 5 *(Phase 8B)*: BTCPay client Lightning support + `lnd` service in compose + bootstrap extension + `scripts/lnd-bootstrap.sh`
- [ ] Task 6 *(Phase 8B)*: Frontend `paymentService` extension + sibling test + pre-flight coverage check
- [ ] Task 7 *(Phase 8B)*: Frontend notification consumers for 7 new types + sibling tests (header.tsx, notifications-page.tsx)
- [ ] Task 8: TipModal polish (Lightning, celebration, error/expiry recovery) + test updates
- [ ] Task 9: Tip-on-comment component + integration in CommentSection + tests
- [ ] Task 10: Playwright — TS-001, TS-002, TS-003, TS-010 + `payments-health.spec.ts` floor
- [ ] Task 11: `/settings/transactions` page + Sent/Received toggle + CSV export + tests
- [ ] Task 12: `/studio/wallet` page + balance card + LowBalanceBanner + tests
- [ ] Task 13: PayoutRequestDialog + **backend** BOLT11 decode endpoint + tests
- [ ] Task 14: `/admin/payments/payouts` queue + approve + reject + mark executed + tests
- [ ] Task 15: Background balance worker + notification emission + unit tests
- [ ] Task 16: i18n keys — all new sections added to all 13 locales; `pnpm i18n:check` passes
- [ ] Task 17: Playwright — TS-004, TS-005, TS-006, TS-007, TS-008, TS-009 + build-tag-gated debug endpoint
- [ ] Task 18: Audit plan + memory updates + final verification sweep

**Total Tasks:** 19 (+ mid-plan checkpoint gate) | **Completed:** 5 | **Remaining:** 14

---

## Implementation Tasks

### Task 0: Capture baselines

**Objective:** Pin current test/build state in both repos before any edits so Task 18 can assert no regressions.
**Dependencies:** None
**Mapped Scenarios:** T12

**Files:**
- Output: `/tmp/phase-8-baseline-frontend.log`, `/tmp/phase-8-baseline-backend.log`

**Key Decisions / Notes:**
- Commands:
  - `pnpm test:run 2>&1 | tee /tmp/phase-8-baseline-frontend.log`
  - `(cd ../vidra-core && go test ./... 2>&1 | tee /tmp/phase-8-baseline-backend.log)`
- Record file/test pass/fail counts + sha256 in plan's `## Verification Output` section.

**Definition of Done:**
- [ ] Both logs exist with vitest-style / go-test summary
- [ ] Plan has `baseline_fe_pass/fail/sha256` + `baseline_be_pass/fail/sha256` recorded
- [ ] `git status --porcelain src/ e2e/ ../vidra-core/internal/ ../vidra-core/migrations/ | wc -l` == 0

**Verify:**
- `tail -5 /tmp/phase-8-baseline-*.log`

---

### Task 1: vidra-core migrations (094–098)

**Objective:** Create ledger + payouts tables + notification type migration + backfill + notification cooldowns. All idempotent, all with working Down migrations.
**Dependencies:** Task 0
**Mapped Scenarios:** T2, T11

**Files:**
- Create: `../vidra-core/migrations/094_payment_ledger.sql`
- Create: `../vidra-core/migrations/095_btcpay_payouts.sql`
- Create: `../vidra-core/migrations/096_backfill_ledger_from_invoices.sql`
- Create: `../vidra-core/migrations/097_payment_notification_types.sql`
- Create: `../vidra-core/migrations/098_payment_notification_cooldowns.sql`

**Key Decisions / Notes:**
- 094 schema:
  ```sql
  CREATE TYPE ledger_entry_type AS ENUM ('tip_in','tip_out','payout_requested','payout_completed','payout_rejected','payout_cancelled','subscription_in');
  -- NOTE: 'payout_approved' intentionally NOT in the enum. Approval is a state transition on btcpay_payouts,
  -- not a money-movement entry. A `payout_approved` ledger row would have amount=0 and is redundant. Approval is
  -- captured by btcpay_payouts.status + approved_at + approved_by_admin_id.
  CREATE TABLE payment_ledger (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    counterparty_user_id UUID NULL REFERENCES users(id) ON DELETE SET NULL,
    channel_id UUID NULL REFERENCES channels(id) ON DELETE SET NULL,
    entry_type ledger_entry_type NOT NULL,
    amount_sats BIGINT NOT NULL,
    currency VARCHAR(10) NOT NULL DEFAULT 'BTC',
    invoice_id UUID NULL REFERENCES btcpay_invoices(id) ON DELETE SET NULL,
    payout_id UUID NULL, -- resolves in 095
    metadata JSONB,
    idempotency_key VARCHAR(255) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
  );
  CREATE UNIQUE INDEX idx_payment_ledger_idempotency ON payment_ledger(idempotency_key);
  CREATE INDEX idx_payment_ledger_user ON payment_ledger(user_id, created_at DESC);
  CREATE INDEX idx_payment_ledger_counterparty ON payment_ledger(counterparty_user_id) WHERE counterparty_user_id IS NOT NULL;
  CREATE INDEX idx_payment_ledger_type ON payment_ledger(entry_type);
  ```
- 095 schema — NOTE: `executing` state DROPPED per spec-review F04 (redundant with `approved`; on-chain broadcast is external to the app, and the transition from approved to completed is the "admin marks executed" action. No intermediate state is needed). If a future hot-wallet automation phase is introduced, add `executing` via a dedicated migration then.
  ```sql
  CREATE TYPE payout_status AS ENUM ('pending','approved','completed','rejected','cancelled');
  CREATE TYPE payout_destination_type AS ENUM ('on_chain','lightning_bolt11');
  CREATE TABLE btcpay_payouts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    requester_user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    amount_sats BIGINT NOT NULL CHECK (amount_sats > 0),
    destination TEXT NOT NULL,
    destination_type payout_destination_type NOT NULL,
    status payout_status NOT NULL DEFAULT 'pending',
    auto_trigger BOOLEAN NOT NULL DEFAULT FALSE,
    requested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    approved_at TIMESTAMPTZ NULL,
    approved_by_admin_id UUID NULL REFERENCES users(id),
    executed_at TIMESTAMPTZ NULL,
    txid TEXT NULL,
    rejection_reason TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
  );
  CREATE INDEX idx_btcpay_payouts_requester_status ON btcpay_payouts(requester_user_id, status);
  CREATE INDEX idx_btcpay_payouts_status_requested ON btcpay_payouts(status, requested_at);
  ALTER TABLE payment_ledger ADD CONSTRAINT fk_payment_ledger_payout FOREIGN KEY (payout_id) REFERENCES btcpay_payouts(id) ON DELETE SET NULL;
  ```
- 096 backfill semantics (ONE-SHOT, not re-run friendly for corrections):
  - SELECT settled invoices, for each derive (payer_user_id=user_id, recipient_user_id from `metadata->>'channel_id'` → channels.owner_user_id, amount_sats, invoice_id), INSERT two ledger rows (`tip_out` negative on payer, `tip_in` positive on recipient), idempotency key `invoice-{id}-{entry_type}`. ON CONFLICT DO NOTHING.
  - **Important:** this migration is one-shot best-effort. If post-backfill corrections are needed (e.g., a `channel_id` was added to metadata AFTER the backfill), operators MUST write NEW compensating ledger entries — they MUST NOT attempt to re-run 096 and rely on conflicts to do the right thing. Silent no-ops would mask corruption.
  - End of migration: `RAISE NOTICE 'backfilled % tip_in rows, % tip_out rows', ...` so operators see the counts.
  - Post-migration invariant assertion (inside migration, after INSERT): `DO $$ BEGIN IF (SELECT COUNT(*) FROM btcpay_invoices WHERE status='Settled' AND metadata->>'channel_id' IS NOT NULL) <> (SELECT COUNT(*) FROM payment_ledger WHERE entry_type='tip_in') THEN RAISE EXCEPTION 'backfill invariant violated: settled-with-channel count <> tip_in count'; END IF; END $$;` — fails the migration if the counts don't match (and therefore fails CI).
- 097: if `notifications.type` is a CHECK-constrained VARCHAR (not ENUM), ALTER CHECK to include new values: `tip_received`, `payout_pending_approval`, `payout_approved`, `payout_completed`, `payout_rejected`, `payout_ready`, `low_balance_stuck`. If ENUM, `ALTER TYPE notification_type ADD VALUE IF NOT EXISTS ...` per value. Domain-level Go constants added in Task 2.
- 098 schema (per F09 — moved from Task 15 so it's not a surprise):
  ```sql
  CREATE TABLE payment_notification_cooldowns (
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    notification_type VARCHAR(50) NOT NULL,
    emitted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, notification_type)
  );
  ```
  Worker writes with `ON CONFLICT (user_id, notification_type) DO UPDATE SET emitted_at = EXCLUDED.emitted_at WHERE EXCLUDED.emitted_at > payment_notification_cooldowns.emitted_at + INTERVAL '24 hours'` — natural 24h cooldown.
- All Down migrations reverse cleanly: drop tables, remove constraints, remove ENUM values / CHECK values. 094 Down is effectively a no-op (truncate `payment_ledger` rows where `invoice_id IS NOT NULL` — ledger is derivative of invoices for pre-092 data).

**Definition of Done:**
- [ ] `goose up` against a fresh db succeeds; `goose down 5` reverts cleanly
- [ ] Backfill is idempotent: running twice produces identical row counts
- [ ] Post-migration invariant assertion in 094 executed successfully (RAISE NOTICE count matches)
- [ ] `\d+ payment_ledger`, `\d+ btcpay_payouts`, `\d+ payment_notification_cooldowns` show expected indexes + constraints
- [ ] `payout_status` enum has exactly 5 values (no `executing`)
- [ ] Plan registered

**Verify:**
- `(cd ../vidra-core && goose -dir=migrations postgres "..." up && goose -dir=migrations postgres "..." down 5 && goose -dir=migrations postgres "..." up)` clean
- `psql -c "SELECT unnest(enum_range(NULL::payout_status))"` returns `pending, approved, completed, rejected, cancelled`

---

### Task 2: Domain + LedgerService + webhook integration

**Objective:** Add Go domain types, `LedgerService`, extend webhook handler to write ledger entries atomically. Unit + integration tests for idempotency and balance invariants.
**Dependencies:** Task 1
**Mapped Scenarios:** T2, T11

**Files:**
- Create: `../vidra-core/internal/domain/payment_ledger.go` (+ `_test.go`)
- Create: `../vidra-core/internal/usecase/payments/ledger_service.go` (+ `_test.go`)
- Create: `../vidra-core/internal/repo/payment_ledger_repo.go` (+ `_test.go`)
- Modify: `../vidra-core/internal/httpapi/handlers/payments/btcpay_handlers.go` (webhook writes ledger)
- Modify: `../vidra-core/internal/domain/notification.go` (new type constants)

**Key Decisions / Notes:**
- Ledger repo: `Record(ctx, entry) error` uses `ON CONFLICT (idempotency_key) DO NOTHING`, returning error only on non-conflict failures.
- Webhook flow: parse `InvoiceSettled` → fetch invoice → derive recipient → in a single DB tx: `Record(tip_out)` + `Record(tip_in)` + NotificationService.Create(`tip_received`). ANY failure rolls back, BTCPay will retry webhook.
- Tests: golden-path settle, replay idempotency (count stays 2), no-recipient case (skip tip_in, still record tip_out — tip sent into the void is tracked on the sender side).

**Definition of Done:**
- [ ] `go test ./internal/domain/... ./internal/usecase/payments/... ./internal/repo/...` passes
- [ ] Webhook integration test with 2 replays asserts ledger row count stays at 2
- [ ] Balance query function in repo returns correct sum

**Verify:**
- `(cd ../vidra-core && go test ./internal/... -run '.*Ledger.*|.*Webhook.*Settle.*' -v)` passes

---

### Task 3: Wallet + transactions handlers

**Objective:** New handlers for `GET /payments/wallet/balance` and `GET /payments/wallet/transactions` with filters and pagination.
**Dependencies:** Task 2
**Mapped Scenarios:** T2, T7

**Files:**
- Create: `../vidra-core/internal/httpapi/handlers/payments/wallet_handlers.go` (+ `_test.go`)
- Modify: `../vidra-core/internal/httpapi/routes.go` (register new routes inside existing `r.Route("/payments", …)` block, auth-gated)

**Key Decisions / Notes:**
- **Balance invariant (corrected per spec-review F02):**
  - `available_sats = SUM(amount_sats) WHERE user_id = $1` — this is the SPENDABLE balance. Reservations (`payout_requested` negative entries) are ALREADY folded in. Approving / completing a payout does NOT change `available_sats` (the reservation becomes realized). Rejecting / cancelling a payout writes a COMPENSATING positive entry, which restores the balance.
  - `pending_payout_sats = ABS(SUM(amount_sats)) WHERE user_id = $1 AND entry_type = 'payout_requested' AND payout_id IN (SELECT id FROM btcpay_payouts WHERE status IN ('pending', 'approved'))` — absolute value of reservations that have not yet been finalized (completed) nor compensated (rejected/cancelled). Informational only — this is NOT subtracted from `available_sats` again; it's there so the UI can render "X sats available · Y sats pending payout".
  - Unit test asserts that `available + settled_payouts_total ≡ lifetime_tips_received_plus_subs_in - lifetime_tips_sent` (balance sanity) and that `pending_payout_sats` does not double-count against `available_sats`.
- Response shape for `/wallet/balance`:
  ```json
  { "available_sats": number, "pending_payout_sats": number, "currency": "BTC", "as_of": "ISO8601" }
  ```
  UI renders "Available: {available_sats} sats" with a secondary line "Pending payout: {pending_payout_sats} sats" (hidden when 0).
- `/wallet/transactions` query params: `direction` (sent | received | all, default all), `type` (entry_type), `start`, `count` (default 20), `start_date`, `end_date`. Response includes hydrated `counterparty_name` + `channel_name` via LEFT JOIN to avoid N+1.
- Pagination: offset-based to match existing patterns in the repo.

**Definition of Done:**
- [ ] Handler + repo tests pass
- [ ] Routes wired in `routes.go`; manual `curl` against `/wallet/balance` authenticated returns 200 with expected JSON shape
- [ ] EXPLAIN shows no N+1 on transactions query

**Verify:**
- `(cd ../vidra-core && go test ./internal/httpapi/handlers/payments/... -run 'Wallet' -v)` passes

---

### Task 4: PayoutService + creator + admin handlers

**Objective:** Service layer for payout lifecycle. HTTP handlers for creator (request/list/cancel) and admin (list/approve/reject/mark-executed). Transaction-safe reservation + balance consistency.
**Dependencies:** Task 2, Task 3
**Mapped Scenarios:** T3, T4, T10

**Files:**
- Create: `../vidra-core/internal/usecase/payments/payout_service.go` (+ `_test.go`)
- Create: `../vidra-core/internal/repo/btcpay_payouts_repo.go` (+ `_test.go`)
- Create: `../vidra-core/internal/httpapi/handlers/payments/payout_handlers.go` (+ `_test.go`)
- Create: `../vidra-core/internal/httpapi/handlers/payments/admin_payout_handlers.go` (+ `_test.go`)
- Modify: `../vidra-core/internal/httpapi/routes.go` (register new routes; admin-protected via `RequireRole(RoleAdmin)`)

**Key Decisions / Notes:**
- **Idempotency keys — all four payout-lifecycle ledger entries specified (per F03):**
  - Reservation on request: `payout-{payout_id}-requested`
  - Compensation on reject: `payout-{payout_id}-rejected`
  - Compensation on cancel: `payout-{payout_id}-cancelled`
  - Marker on mark-executed (amount=0): `payout-{payout_id}-completed`
  - All four share the payout UUID prefix so they are enumerable per payout (useful for auditing).
  - A replay of RejectPayout (admin double-click) hits the UNIQUE constraint on `idempotency_key` — the second INSERT is a no-op. Service reads back the status and returns the CURRENT state (idempotent at API layer).

- **Race-condition-safe state transitions (per F05):** every transition uses a **conditional UPDATE** that returns affected rows; zero rows → return `409 Conflict`. Never a read-then-write.
  ```sql
  UPDATE btcpay_payouts
     SET status = 'approved',
         approved_at = NOW(),
         approved_by_admin_id = $admin,
         updated_at = NOW()
   WHERE id = $id AND status = 'pending'
  RETURNING id;
  ```
  Same pattern for cancel, reject, mark-executed (only `status='approved'` → `'completed'`). Concurrent cancel + approve: the first UPDATE wins, the second's WHERE-clause fails (row no longer in `pending`), returns 0 rows → 409. Integration test simulates this with two goroutines.

- **State machine (corrected per F04 — `executing` dropped):**
  - Valid transitions: `pending → approved`, `pending → cancelled`, `pending → rejected`, `approved → completed`, `approved → rejected` (admin changes mind before ops executes — balance compensates).
  - All other transitions return 409.

- `RequestPayout` runs in a tx (serializable isolation) :
  1. `SELECT COALESCE(SUM(amount_sats),0) FROM payment_ledger WHERE user_id=$1 FOR UPDATE` (advisory lock on rows; OK at Postgres SERIALIZABLE level).
  2. Assert ≥ requested amount else return `ErrInsufficientBalance` (HTTP 409 `{code: "insufficient_balance"}`).
  3. INSERT `btcpay_payouts` row `status=pending`.
  4. INSERT `payment_ledger { entry_type: payout_requested, amount_sats: -X, payout_id: new.id, idempotency_key: "payout-{new.id}-requested" }` — fails loudly if idempotency_key collides (shouldn't, since it's keyed on the freshly-minted UUID).
  5. NotificationService.Create(`payout_pending_approval`) for all admins; mark any existing `payout_ready` notification for this user as read.
- `ApprovePayout`: conditional UPDATE (see above). No ledger entry — approval is a state change, not a money movement.
- `RejectPayout`: conditional UPDATE `pending→rejected` OR `approved→rejected`; INSERT compensating ledger entry (`payout_rejected`, amount=+X, idempotency_key=`payout-{id}-rejected`). NotificationService.Create(`payout_rejected`) on requester.
- `MarkExecuted`: conditional UPDATE `approved→completed` + INSERT ledger `payout_completed` (amount=0, txid in metadata, idempotency_key=`payout-{id}-completed`). NotificationService.Create(`payout_completed`).
- `CancelPayout` (creator, self only, `pending` only): conditional UPDATE `pending→cancelled`; INSERT compensating ledger `payout_cancelled` (amount=+X, idempotency_key=`payout-{id}-cancelled`).

- **Validation strictness (per F15):**
  - Backend is the source of truth for destination validation (frontend passes through).
  - On-chain regtest addresses: use `btcsuite/btcd/btcutil.DecodeAddress(str, &chaincfg.RegressionNetParams)` — validates bech32 checksum + prefix. Reject unsupported address types.
  - LN BOLT11: use `github.com/lightningnetwork/lnd/zpay32.Decode(str, &chaincfg.RegressionNetParams)` — validates BOLT11 structure + network match.
  - Reject early with `400 Bad Request {code: "invalid_destination", reason: "..."}`.
  - Amount: `> 0` AND `≤ available_sats` AND `>= 546` (dust limit on-chain; LN-BOLT11 has no lower bound but we enforce the same for consistency).

**Definition of Done:**
- [ ] Handler + service + repo tests pass with concurrent-request scenarios (second returns 409)
- [ ] Reject restores balance (integration test)
- [ ] All state transitions enforced; invalid transitions return 409
- [ ] Routes wired + admin middleware active

**Verify:**
- `(cd ../vidra-core && go test ./... -run 'Payout' -v)` passes

---

### Task 5: BTCPay client Lightning + LND compose + bootstrap

**Objective:** Extend `BTCPayClient` to create invoices with Lightning payment method and fetch per-method destinations. Add `lnd` regtest service to docker-compose. Extend `btcpay-bootstrap.sh` to wire LND ↔ BTCPay idempotently.
**Dependencies:** Task 0
**Mapped Scenarios:** T1, T5

**Files:**
- Create: `../vidra-core/internal/payments/btcpay_lightning.go` (+ `_test.go` using `httptest.Server`)
- Create: `scripts/lnd-bootstrap.sh` (NEW — separate from btcpay-bootstrap.sh per F07)
- Modify: `../vidra-core/internal/payments/btcpay_client.go` (invoice request shape supports `checkout.paymentMethods`; GetInvoicePaymentMethods)
- Modify: `../vidra-core/internal/domain/btcpay.go` (BTCPayInvoice gains `LightningInvoice *string`, `LightningExpiresAt *time.Time`)
- Modify: `../vidra-core/internal/httpapi/handlers/payments/btcpay_handlers.go` (CreateInvoice accepts `payment_method` ["on_chain"|"lightning"|"both"]; GetInvoice response includes LN fields)
- Modify: `../vidra-core/docker-compose.yml` (add `lnd` service on `vidra-network`, depends_on=bitcoind, volumes, healthcheck)
- Modify: `scripts/btcpay-bootstrap.sh` (at end, delegate to `lnd-bootstrap.sh` if LND container is healthy)
- Modify: `.env.example` (document `ENABLE_BITCOIN_LIGHTNING`; no per-LND secrets in vidra-user env — all secrets live inside the LND container and are extracted by the bootstrap script)

**Key Decisions / Notes — stepped checklist (rewrite per F07):**

Compose `lnd` service block (exact shape):
```yaml
lnd:
  profiles: ["bitcoin", "full"]
  image: lightninglabs/lnd:v0.17.4-beta
  restart: on-failure:3
  depends_on:
    bitcoind:
      condition: service_healthy
  environment:
    NETWORK: regtest
  command:
    - --bitcoin.active
    - --bitcoin.regtest
    - --bitcoin.node=bitcoind
    - --bitcoind.rpchost=bitcoind:18443
    - --bitcoind.rpcuser=vidra
    - --bitcoind.rpcpass=vidra
    - --bitcoind.zmqpubrawblock=tcp://bitcoind:28332
    - --bitcoind.zmqpubrawtx=tcp://bitcoind:28333
    - --rpclisten=0.0.0.0:10009
    - --restlisten=0.0.0.0:8080
    - --alias=vidra-dev-lnd
    - --tlsextraip=lnd
    - --tlsextradomain=lnd
    - --no-macaroons=false
    - --debuglevel=info
  ports:
    - "18080:8080"    # LND REST (host:container). Host port chosen to avoid conflicts (app uses 8080)
  volumes:
    - lnd_data:/root/.lnd
  healthcheck:
    test: ["CMD-SHELL", "lncli --network=regtest getinfo >/dev/null 2>&1"]
    interval: 10s
    timeout: 5s
    retries: 10
    start_period: 30s
  networks:
    - vidra-network
```
Plus `volumes: lnd_data:` at the top-level `volumes` block. NOTE: bitcoind compose MUST publish zmq ports 28332/28333 internally — if not present, add them (check during Task 5 — include in Files: if modified).

`scripts/lnd-bootstrap.sh` — stepped provisioning:
1. Resolve `LND_CID=$($COMPOSE ps -q lnd)`; refuse if empty.
2. Wait for LND healthcheck (up to 120s).
3. `docker exec $LND_CID lncli --network=regtest create` with a generated seed (save to `.lnd-bootstrap.state` — gitignored) IF wallet doesn't exist. Detect via `lncli getinfo` vs `wallet locked` output.
4. Mine 101 blocks to bitcoind to give it mature UTXOs (reuse btcpay-bootstrap.sh mining helper; same mining address). Then fund LND by sending ~1 BTC from bitcoind to an LND address (`lncli newaddress p2wkh` → bitcoind sendtoaddress → mine 6 blocks). This is enough for regtest payout tests WITHOUT opening channels — LN invoices on a single LND node can be settled via BTCPay's own LN node IF BTCPay uses the SAME node (we configure BTCPay to use this same LND, so invoices generated by BTCPay are payable by this LND as long as it has on-chain funds and can open channels on demand — BTCPay 2.3 auto-opens channels when needed).
5. Extract admin.macaroon + tls.cert:
   ```bash
   MACAROON=$(docker exec "$LND_CID" base64 -w0 /root/.lnd/data/chain/bitcoin/regtest/admin.macaroon)
   TLS_CERT=$(docker exec "$LND_CID" base64 -w0 /root/.lnd/tls.cert)
   CONN_STRING="type=lnd-grpc;server=lnd:10009;macaroon=${MACAROON};certthumbprint=$(printf '%s' "$TLS_CERT" | base64 -d | openssl x509 -noout -fingerprint -sha256 | cut -d'=' -f2 | tr -d ':')"
   ```
6. POST to BTCPay Greenfield:
   ```bash
   curl -sS -X PUT "http://localhost:14080/api/v1/stores/$BTCPAY_STORE_ID/payment-methods/LightningNetwork/BTC" \
     -H "Authorization: token $BTCPAY_API_KEY" \
     -H "Content-Type: application/json" \
     -d "{\"connectionString\":\"$CONN_STRING\",\"enabled\":true}"
   ```
   Expect 200 with `enabled: true`. Non-2xx → print BTCPay body + exit.
7. Verify: `curl http://localhost:14080/api/v1/stores/$BTCPAY_STORE_ID/lightning/BTC/info` returns 200 with LN node info.
8. Idempotency: bootstrap checks `GET /stores/{id}/payment-methods/LightningNetwork/BTC` first; if `enabled: true` and connection string matches, skip steps 5-6.

Go client additions (`btcpay_client.go`):
- `CreateInvoice` accepts an optional `CheckoutOptions` struct including `PaymentMethods []string` (e.g., `["BTC","BTC-LightningNetwork"]`); defaults to `["BTC"]` when nil (preserves existing callers).
- `GetInvoicePaymentMethods(ctx, invoiceID) ([]BTCPayInvoicePaymentMethod, error)` — hits `/invoices/{id}/payment-methods`; returns array with per-method `destination` + `payment_link` + status.

Frontend invoice shape (`BTCPayInvoice`):
- `lightning_invoice *string` (BOLT11 from LN payment method if requested)
- `lightning_expires_at *time.Time`
- On-chain fields unchanged.

**Definition of Done:**
- [ ] Unit tests for Lightning client methods pass (using `httptest` against a mock BTCPay)
- [ ] `docker compose --profile bitcoin up -d lnd` succeeds; `docker exec $LND_CID lncli --network=regtest getinfo` returns synced_to_chain=true
- [ ] `lnd-bootstrap.sh` runs twice idempotently: first run wires LN store, second run detects `enabled: true` and skips
- [ ] `POST /api/v1/payments/invoices {amount_sats:1000, payment_method:"lightning"}` returns `lightning_invoice` non-empty BOLT11
- [ ] BTCPay store LN info endpoint (`/stores/{id}/lightning/BTC/info`) returns 200 after bootstrap

**Verify:**
- `(cd ../vidra-core && go test ./internal/payments/... -v)` passes
- `docker exec -i $LND_CID lncli --network=regtest getinfo | jq -r '.synced_to_chain'` returns `true`
- `curl -sS http://localhost:14080/api/v1/stores/$BTCPAY_STORE_ID/lightning/BTC/info -H "Authorization: token $BTCPAY_API_KEY" | jq .`

---

### Task 6: Frontend paymentService extension + tests

**Objective:** Extend `src/lib/api/services/payments.ts` with new methods and types. Sibling test coverage.
**Dependencies:** Task 3, Task 4, Task 5
**Mapped Scenarios:** T2, T3, T4, T7, T8

**Files:**
- Modify: `src/lib/api/services/payments.ts`
- Modify: `src/lib/api/types.ts` (new types: `LedgerEntry`, `LedgerEntryType`, `PayoutRequest`, `Payout`, `PayoutStatus`, `PayoutDestinationType`, `WalletBalance`, `TransactionListParams`, extend `BTCPayInvoice` with LN fields)
- Modify: `src/lib/api/services/__tests__/payments.test.ts`

**Key Decisions / Notes:**
- Mock `@/lib/api/client` `api.get/post/put/patch/delete` and assert URL + body for each new method.
- One `it(…)` per new method success + one per failure branch where non-trivial; aim for ≥ 24 new test cases.
- **Pre-flight coverage check (per F14):** before adding any new file under `src/lib/api/services/`, run `bash -c 'for f in src/lib/api/services/*.ts; do name=$(basename "$f" .ts); [ "$name" = "index" ] && continue; [ -f "src/lib/api/services/__tests__/${name}.test.ts" ] || echo "MISSING TEST: $name"; done'` — output must be empty. If any service lacks a test, STOP and either add the test or delete the unused service FIRST (stop-hook would block completion otherwise).
- In this Task 6, do NOT create any NEW `.ts` files under `src/lib/api/services/` — extend the existing `payments.ts` + add types to `types.ts`. If a new service file is genuinely needed (e.g., `payouts.ts` split from payments), create the sibling test in the same commit.

**Definition of Done:**
- [ ] Pre-flight coverage check prints empty (no orphan services)
- [ ] Tests pass, coverage adds to existing percentage
- [ ] `pnpm typecheck && pnpm lint` clean
- [ ] `grep -c "^  async " src/lib/api/services/payments.ts` equals the number of distinct service methods; `grep -c '  it(' src/lib/api/services/__tests__/payments.test.ts` ≥ that number × 1.5
- [ ] No new file under `src/lib/api/services/` without its sibling test in the same commit

**Verify:**
- `pnpm test:run src/lib/api/services/__tests__/payments.test.ts -- --reporter=dot`
- Pre-flight check passes on a clean workspace

---

### Task 7: Notification types — frontend consumers + i18n

**Objective:** Surface 7 new notification types in the header dropdown + full notifications page with correct icons, routing, and locale copy.
**Dependencies:** Task 1 (migration 095 + 096), Task 2 (domain types), **Task 15 (worker emits `payout_ready` + `low_balance_stuck`)** — for admin-triggered + payer-triggered types, Task 7 can ship without Task 15; for worker-triggered types, Task 7 alone would render "for an event that never fires" until Task 15 lands. Ordering kept: Task 7 before Task 15, documented dead-code risk mitigated by Task 15 shipping in the SAME phase.
**Mapped Scenarios:** T9, T10, T11

**Files (per F10 — actual files in codebase):**
- Modify: `src/components/pages/notifications-page.tsx` (add new types to `getDisplayType` type map + `DisplayType` union; add icon + gradient entries if existing Heart/Coin/etc. don't suffice; NEW display types `tip`, `payout`, `wallet_low`)
- Modify: `src/components/header.tsx` (dropdown preview — iterates over `notificationService.list` result; already renders `n.title` + `n.time` so the new types get picked up automatically. Only modify if any type-specific rendering is needed for titles that the backend didn't translate.)
- Modify: `src/components/pages/__tests__/notifications-page.test.tsx`
- Modify: `src/components/__tests__/header.test.tsx` (extend to cover tip/payout preview rendering)
- Modify: `messages/en.json` (base keys); other 12 locales covered by Task 16

**Key Decisions / Notes:**
- Backend is the source of truth for notification title + message — both are stored on the `notifications` row (already the case per `Notification.title` / `Notification.message` fields). Frontend just picks the icon + link based on `type`.
- `getDisplayType` extended with: `tip_received → "tip"`, `payout_* → "payout"`, `low_balance_stuck → "wallet_low"`. Each gets an icon + gradient entry (BitcoinLogo / Wallet / AlertTriangle from lucide).
- Link-out per type:
  - `tip_received` → `/settings/transactions?direction=received`
  - `payout_pending_approval` → `/admin/payments/payouts` (only for admins; backend should only send to admins)
  - `payout_approved`, `payout_completed`, `payout_rejected`, `payout_ready`, `low_balance_stuck` → `/studio/wallet`
- i18n keys under `Notifications.types.*`: seven keys (one per new type) each with `display_label` (e.g., "Tip", "Payout"). Actual title/message come from backend (already translated if backend supports locale per `NotificationService`; otherwise English — out-of-scope).

**Definition of Done:**
- [ ] `grep -rn "notification-bell" src/` returns zero matches (plan reference removed)
- [ ] Unit test covers each new notification type → correct rendered title, link, icon
- [ ] `pnpm typecheck && pnpm lint` clean
- [ ] `notifications.ts` sibling test exists (verified at plan time: `src/lib/api/services/__tests__/notifications.test.ts` exists)

**Verify:**
- `pnpm test:run src/components/pages/__tests__/notifications-page.test.tsx src/components/__tests__/header.test.tsx`

---

### Task 8: TipModal polish — Lightning + celebration + error/expiry

**Objective:** Upgrade TipModal with method toggle (On-chain / Lightning), celebration toast on Settled, detect Expired/Invalid and show retry CTA.
**Dependencies:** Task 6
**Mapped Scenarios:** TS-001, TS-002, TS-010

**Files:**
- Modify: `src/components/tip-modal.tsx`
- Modify: `src/components/__tests__/tip-modal.test.tsx`
- Add (if missing): a lightweight toast provider in `src/components/ui/` — reuse `sonner` if installed else a local minimal one

**Key Decisions / Notes:**
- Keep modal under 400 lines; extract `TipSuccessPanel`, `TipMethodToggle`, `TipErrorRecovery` sub-components into same file or adjacent files.
- Polling: while modal open with status New/Processing, poll `getInvoice` every 3s (bounded to 40 polls = 2 min). Then user-initiated only.
- On Settled: render success panel (big check + "$X to @channel") + fire toast with same message; auto-close modal after 3s or user clicks Done.
- On Expired/Invalid: red panel + "Try again" button that calls `createInvoice` with the same amount + method (new invoice); success state.
- Test updates must cover: Lightning method path, celebration render, expired-recovery retry path.

**Definition of Done:**
- [ ] All test paths pass (BTCPay on-chain, Lightning, celebration, expired-retry)
- [ ] Manual browser verification with `pnpm dev:full`: both methods render correctly
- [ ] `pnpm typecheck && pnpm lint` clean

**Verify:**
- `pnpm test:run src/components/__tests__/tip-modal.test.tsx`
- Browser: open Tip on a seeded video, confirm Lightning panel shows QR + BOLT11

---

### Task 9: Tip-on-comment button

**Objective:** Inline tip trigger on comments; opens TipModal with commenter's channel prefilled.
**Dependencies:** Task 8
**Mapped Scenarios:** TS-003

**Files:**
- Create: `src/components/tip-comment-button.tsx` (+ `__tests__/tip-comment-button.test.tsx`)
- Modify: `src/components/comment-section.tsx` (render the button when comment author has an eligible channel)
- Modify: i18n keys for the button label (`Comment.tip`, `Comment.tipAria`) in all 13 locales (Task 16 does the 12 non-en)

**Key Decisions / Notes:**
- Button is hidden entirely for anonymous authors or channels without `bitcoin_wallet`. Check via an inexpensive field on the comment author shape if present; else defer hiding to on-open modal feedback ("creator hasn't enabled tips").
- Reuse TipModal verbatim; `videoId` can be empty string (optional in metadata) for inline tips; pass `channelId` + `channelName`.
- Keep the UI minimal: small icon button next to timestamp.

**Definition of Done:**
- [ ] Component test covers: renders when channel eligible; hidden when not; click opens modal
- [ ] Integration test or updated comment-section test verifies placement
- [ ] A11y: button has `aria-label`; modal focus-trap still works

**Verify:**
- `pnpm test:run src/components/__tests__/tip-comment-button.test.tsx src/components/__tests__/comment-section.test.tsx`

---

### Task 10: Playwright — tip flows (TS-001, TS-002, TS-003, TS-010)

**Objective:** End-to-end coverage for all tip polish scenarios against `pnpm dev:full` stack.
**Dependencies:** Task 5, Task 8, Task 9
**Mapped Scenarios:** TS-001, TS-002, TS-003, TS-010

**Files:**
- Create: `e2e/payments-tip-onchain-polish.spec.ts`
- Create: `e2e/payments-tip-lightning.spec.ts`
- Create: `e2e/payments-tip-on-comment.spec.ts`
- Create: `e2e/payments-tip-expiry-recovery.spec.ts`
- Use existing helpers: `e2e/helpers/api.ts`, `e2e/fixtures/auth.ts`

**Key Decisions / Notes:**
- Use existing on-chain CID resolution from `e2e/payments-tip-btcpay.spec.ts`.
- LN spec resolves `LND_CID` dynamically and runs `lncli` via `docker exec` as the test action.
- Tests skip INDIVIDUAL specs with clear reason if LND/bitcoind containers unhealthy.
- **MINIMUM-ASSERTION FLOOR (per F08):** add a top-of-suite sanity test in a shared `e2e/payments-health.spec.ts` (NEW) that asserts backend `/health` returns 200. This spec never skips — if it fails, the entire E2E run fails in CI, preventing a "100% skipped, green CI" false signal. Also emit a `__skipped-summary.json` artifact in `playwright.config.ts` reporter and fail if `skipped / total > 0.5`.
- Expiry test mocks `expires_at` via request interception — intercept `POST /invoices` and modify response to have expires_at in the near future.

**Definition of Done:**
- [ ] 4 specs + `payments-health.spec.ts` compile + run locally against `pnpm dev:full`
- [ ] `payments-health.spec.ts` always runs (not skippable)
- [ ] Each spec is < 90s and auto-skips with reason when deps unhealthy
- [ ] CI fails when skip-ratio > 50% (unit test or reporter-level check)
- [ ] Bitcoin-cli and lncli invocations include explicit auth flags

**Verify:**
- `pnpm test:e2e -- 'payments-tip-*.spec.ts' --project=chromium`

---

### Task 11: Transactions page + Sent/Received toggle + CSV export

**Objective:** New `/settings/transactions` page with unified viewer + creator transaction list.
**Dependencies:** Task 6
**Mapped Scenarios:** TS-004

**Files:**
- Create: `src/components/pages/transactions-page.tsx` (+ `__tests__/transactions-page.test.tsx`)
- Create: `src/app/[locale]/(main)/settings/transactions/page.tsx`
- Modify: `src/components/pages/settings-page.tsx` — add a "View all transactions" link from the existing Payments tab to the new page

**Key Decisions / Notes:**
- URL: `/settings/transactions?direction=all&type=&from=&to=&start=0&count=20`
- Segmented Sent | Received | All syncs to `direction` query param.
- Type filter multi-select chip group: Tips / Inner Circle / Payouts / Subscriptions / All.
- Pagination: "Load more" button (matches Phase 4 comments pattern).
- CSV export: client-side blob of current filtered result, headers `Date,Type,Direction,Counterparty,Amount (sats),Amount (USD),Status`.
- Reuse existing skeleton pattern from settings-page invoice list.

**Definition of Done:**
- [ ] Component test covers toggle + filter + CSV-export round-trip
- [ ] Page registers under `/settings/transactions`; middleware allows authed access

**Verify:**
- `pnpm test:run src/components/pages/__tests__/transactions-page.test.tsx`

---

### Task 12: Studio wallet page + LowBalanceBanner

**Objective:** New `/studio/wallet` page with balance card, low-balance banner, recent transactions, my payouts list, Request Payout CTA.
**Dependencies:** Task 6, Task 7
**Mapped Scenarios:** TS-005, TS-006, T8

**Files:**
- Create: `src/components/pages/wallet-page.tsx` (+ `__tests__/wallet-page.test.tsx`)
- Create: `src/components/low-balance-banner.tsx` (+ tests)
- Create: `src/app/[locale]/(main)/studio/wallet/page.tsx`
- Modify: `src/components/sidebar.tsx` — add a "Wallet" link under creator nav

**Key Decisions / Notes:**
- **"Config disables payments" definition (per F15):** the route + sidebar entry are hidden iff `PaymentConfig.BitcoinEnabled === false` OR `PaymentConfig.PayoutsEnabled === false` (new field added to `PaymentConfig` in Task 3/4) OR the current user does not own any channel (resolved via `channelsService.listMyChannels`).
- Balance card uses `MIN_PAYOUT_SATS` from the same `/api/v1/payments/config` response (new field; default 50_000; override via env `MIN_PAYOUT_SATS`).
- LowBalanceBanner dismissable, localStorage flag `vidra_low_balance_dismissed_<balance_bucket>` where bucket is the floor(balance/10_000) — re-shows the banner every 10k sats of change so a new tip doesn't leave a stale dismissal.

**Definition of Done:**
- [ ] Component tests cover balance render, banner visibility transitions, empty state
- [ ] Manual browser verification with a seeded creator

**Verify:**
- `pnpm test:run src/components/pages/__tests__/wallet-page.test.tsx`

---

### Task 13: PayoutRequestDialog + backend BOLT11 decode

**Objective:** Modal for creator to submit a payout request. BOLT11 decoded via backend (not NPM) for accuracy + security.
**Dependencies:** Task 4 (handlers), Task 5 (LND client), Task 12
**Mapped Scenarios:** TS-006, TS-007

**Files:**
- Create: `src/components/payout-request-dialog.tsx` (+ tests)
- Modify: `src/components/pages/wallet-page.tsx` to mount the dialog
- Create: `../vidra-core/internal/httpapi/handlers/payments/bolt11_decode_handlers.go` (+ `_test.go`) — NEW per F11
- Modify: `../vidra-core/internal/httpapi/routes.go` — register `POST /api/v1/payments/bolt11/decode` inside the existing `/payments` block, auth-gated.
- Modify: `../vidra-core/internal/payments/btcpay_client.go` — helper wrapping `POST /lnd/decodepayreq` via LND REST (or call LND gRPC directly; gRPC preferred to avoid another HTTP hop).

**Key Decisions / Notes (per F11 — BACKEND decode, no npm `bolt11`):**
- Frontend address prefix check (UX only, not security):
  - On-chain: regex `/^(bc1|tb1|bcrt1|[123mn])[a-zA-Z0-9]+$/` — shape check only, backend is authoritative.
  - Lightning: regex `/^ln(bc|tb|bcrt)[0-9a-z]+$/i` — shape check only.
- When BOLT11 pasted (≥20 chars + matches LN prefix), debounce 400ms then POST `/api/v1/payments/bolt11/decode {bolt11}` → returns `{amount_sats, description, expires_at, destination_pubkey, network}`. Render decoded fields. If backend returns `amount_sats` and the user entered a different amount, surface warning: "The invoice is for X sats, but you entered Y sats. The network will settle for the invoice amount."
- Reject the pasted BOLT11 if `network !== "regtest"` (dev) OR `network !== "mainnet"` (prod, detected from `PaymentConfig.BitcoinNetwork`).
- Decode endpoint is pure (stateless): backend wraps LND's `DecodePayReq` RPC; no LN payment is initiated.
- Failure mode: if backend returns 400 / 502, show "Could not validate invoice. You can still submit and the backend will validate on submit." — never crash the dialog.
- Auto-trigger toggle persists preference to backend field `auto_trigger` on submit.
- Dialog a11y: focus-trap via existing modal pattern; escape closes; submit button disabled while async decode in-flight.

**Definition of Done:**
- [ ] Backend decode handler test: valid BOLT11 returns decoded fields; invalid returns 400; non-BOLT11 returns 400.
- [ ] Frontend dialog test: valid on-chain submit; valid LN submit with decoded amount shown; amount-mismatch warning; network-mismatch rejection; backend-502 fallback still allows submit.
- [ ] A11y: dialog is focus-trapped, escape closes; tested via Playwright a11y assertion.
- [ ] No `bolt11` npm package added.

**Verify:**
- `pnpm test:run src/components/__tests__/payout-request-dialog.test.tsx`
- `(cd ../vidra-core && go test ./internal/httpapi/handlers/payments/... -run Bolt11 -v)`

---

### Task 14: Admin payouts queue page

**Objective:** Admin-only route `/admin/payments/payouts` listing pending requests with Approve/Reject/Mark Executed actions.
**Dependencies:** Task 6
**Mapped Scenarios:** TS-006, TS-007, TS-008

**Files:**
- Create: `src/components/pages/admin-payouts-page.tsx` (+ tests)
- Create: `src/app/[locale]/(main)/admin/payments/payouts/page.tsx`
- Modify: admin nav in `src/components/sidebar.tsx` under Admin section

**Key Decisions / Notes:**
- Route guarded in middleware via role check (pattern from other admin routes).
- Table columns: Requester, Channel, Amount, Destination (truncated), Type, Requested At, Actions.
- Actions per row: Approve (prompt for optional note) → Mark Executed (prompt for txid / LN payment hash) → Reject (prompt for reason).
- Confirmation dialog on Approve + on Reject.
- Status badges color-coded.

**Definition of Done:**
- [ ] Test covers all three actions, each triggers correct API call + optimistic update
- [ ] Non-admin user sees 403 page

**Verify:**
- `pnpm test:run src/components/pages/__tests__/admin-payouts-page.test.tsx`

---

### Task 15: Background balance worker

**Objective:** Vidra-core goroutine scanning users for low-balance + payout-ready conditions, emitting notifications with idempotency.
**Dependencies:** Task 2
**Mapped Scenarios:** TS-009, T11

**Files:**
- Create: `../vidra-core/internal/usecase/payments/balance_worker.go` (+ `_test.go`)
- Modify: `../vidra-core/cmd/vidra/main.go` — register worker in startup alongside existing ones (goroutine launched with the parent ctx; graceful shutdown on SIGTERM)
- Modify: `../vidra-core/internal/repo/payment_notification_cooldowns_repo.go` — NEW, created here (table was migrated in Task 1's migration 096)

**Key Decisions / Notes:**
- Tick interval: 1h in production, configurable via `BALANCE_WORKER_INTERVAL` (default 1h).
- Idempotency: per-user per-type cooldown of 24h via `payment_notification_cooldowns` table (migration 096, created in Task 1 per F09 — no deferred migration surprise).
- For `low_balance_stuck`: users where `available_sats > 0 AND available_sats < MIN_PAYOUT_SATS AND oldest_positive_ledger_entry.created_at < NOW() - INTERVAL '7 days'`. Uses the balance helper from Task 3 (not an ad-hoc SUM here) to keep the definition of "balance" in one place.
- For `payout_ready`: users who JUST crossed above `MIN_PAYOUT_SATS` since last-emitted; record emission with `ON CONFLICT DO UPDATE WHERE emitted_at > stored.emitted_at + INTERVAL '24h'` per the 096 schema.
- `MinPayoutSats` config lives on `PaymentConfig` (Task 3/4, not here) — worker reads from config, not its own env.

**Definition of Done:**
- [ ] Tests cover: first-time fire, cooldown suppresses second, cross-threshold detection
- [ ] Worker can be manually ticked in integration test

**Verify:**
- `(cd ../vidra-core && go test ./internal/usecase/payments/... -run Balance -v)`

---

### Task 16: i18n — 13 locales, parity enforced

**Objective:** Add all new keys to `messages/en.json` and translations for 12 other locales. `pnpm i18n:check` must pass.
**Dependencies:** Tasks 7, 8, 9, 11, 12, 13, 14
**Mapped Scenarios:** T9, T12

**Files:**
- Modify: `messages/{en,es,fr,de,ja,zh,ko,pt,ru,ar,it,pl,nl}.json`

**Key Decisions / Notes:**
- New sections: `Transactions`, `Wallet`, `Payout`, `AdminPayouts`, extensions to `Tip`, `Notifications.types`, `Comment`.
- Use natural translations, not placeholder strings. If a term has no native equivalent, keep English (e.g., "Bitcoin", "Lightning", "BOLT11") and wrap with locale-appropriate framing copy.
- RTL consideration for Arabic — ensure no direction-sensitive hard-coded strings.

**Definition of Done:**
- [ ] `pnpm i18n:check` exit 0
- [ ] Every locale has all new keys (tested via the script + manual spot-check of 3 locales)

**Verify:**
- `pnpm i18n:check`

---

### Task 17: Playwright — wallet/payout/admin/notification flows

**Objective:** End-to-end coverage for TS-004 through TS-009.
**Dependencies:** Tasks 11, 12, 13, 14, 15, 16
**Mapped Scenarios:** TS-004, TS-005, TS-006, TS-007, TS-008, TS-009

**Files:**
- Create: `e2e/payments-transactions-toggle.spec.ts` (TS-004)
- Create: `e2e/payments-wallet-low-balance.spec.ts` (TS-005)
- Create: `e2e/payments-payout-onchain-approve.spec.ts` (TS-006)
- Create: `e2e/payments-payout-lightning.spec.ts` (TS-007)
- Create: `e2e/payments-payout-reject-restores.spec.ts` (TS-008)
- Create: `e2e/payments-notifications-worker.spec.ts` (TS-009, uses a debug endpoint to force a worker tick)
- Modify: vidra-core — add admin-only `POST /api/v1/debug/balance-worker/tick` — **gated by Go build tag `debug` per F12**. Production builds must NOT compile the debug package.
  - Files: `../vidra-core/internal/httpapi/handlers/debug/balance_worker_debug.go` with `//go:build debug` at the top.
  - Production build command: `go build ./...` (no `-tags=debug`) compiles WITHOUT the file.
  - Debug build command: `go build -tags=debug ./...` for dev/E2E stacks only.

**Key Decisions / Notes:**
- TS-009 uses the debug tick endpoint to avoid waiting 1h. Build tag + env `ENABLE_DEBUG_ENDPOINTS=true` + admin role ALL required. Startup check: if `ENV=production` AND the debug handler is compiled in, log.Fatal with explicit message. Every call to the endpoint logs at WARN with admin user id + timestamp.
- Seed admin auth + second seeded creator account needed — reuse existing fixtures + add if absent.
- All specs auto-skip INDIVIDUAL tests when backend unhealthy; the `payments-health.spec.ts` floor (from Task 10) still runs and is mandatory.
- Skipped-spec ratio guard from Task 10 applies here too.

**Definition of Done:**
- [ ] All 6 specs pass against `pnpm dev:full` with debug-tagged build
- [ ] `go build ./...` (production, no tags) succeeds and debug endpoint is NOT registered — verified via `curl POST /api/v1/debug/balance-worker/tick` returns 404
- [ ] `go build -tags=debug ./...` compiles debug endpoint; startup with `ENV=production` + debug compiled = fatal exit
- [ ] Every debug-endpoint call logs at WARN

**Verify:**
- `pnpm test:e2e -- 'payments-*.spec.ts'`

---

### Task 18: Audit + memory + final verification sweep

**Objective:** Update the parity audit to reflect completed C2–C5, refresh memory, run the full verification gauntlet.
**Dependencies:** All prior tasks
**Mapped Scenarios:** T12, T13, T14

**Files:**
- Modify: `docs/plans/2026-04-22-feature-parity-audit.md` (C2–C5 → done ✓; Phase 8 annotated complete; Lightning captured)
- Modify: `~/.claude/projects/-Users-yosefgamble-github-vidra-user/memory/project_payments_architecture.md`
- Modify: `~/.claude/projects/-Users-yosefgamble-github-vidra-user/memory/project_payment_reconciliation.md`
- Append: plan's `## Verification Output` section

**Key Decisions / Notes:**
- Verification commands:
  - `pnpm test:run` (compare to Task 0 baseline; fail count ≤ baseline)
  - `pnpm lint`
  - `pnpm typecheck`
  - `pnpm i18n:check`
  - `pnpm build`
  - `pnpm test:e2e -- 'payments-*.spec.ts'` (full suite)
  - `(cd ../vidra-core && go build ./... && go test ./...)` (compare to Task 0 baseline)
- If any test that was passing before now fails, stop and investigate.
- Record sha256 of final test-run logs alongside Task 0 baselines.

**Definition of Done:**
- [ ] All verification commands exit 0
- [ ] Audit plan marks C1–C5 done; Phase 8 annotated
- [ ] Memory files updated with ledger + payout + LN flow
- [ ] Final verification table added to this plan

**Verify:**
- Paste last 20 lines of each command into this plan

---

## PeerTube Parity Check

This spec is outside PeerTube's stock feature set. PeerTube supports a basic tipping plugin and a payment plugin ecosystem, but wallet / transaction-history / admin-approved payouts + Lightning are Vidra-specific monetization features. No PeerTube behavior is regressed; the existing PeerTube-compatible endpoints (`/videos`, `/channels`, `/notifications`, etc.) remain untouched.

## Vidra-Specific / Requested Features

Backend extensions impacted by this plan:
- **Bitcoin Payments (BTCPay)** — extended with Lightning Network support, `payment_ledger`, `btcpay_payouts`, wallet/balance/transactions/payouts handlers.
- **ATProto Federation, Video Studio, Auto-Captioning, Advanced Analytics, Direct Messaging, Real-time Stream Chat, IPFS Distribution** — no backend extension impact.
- **Inner Circle** — no changes here; C6–C9 remain Phase 9 scope.

## Verification Plan

- **Per-task:** unit tests after any code change; `go test` for backend tasks; `pnpm typecheck && pnpm lint` before commit.
- **Before declaring done:** `pnpm test:run` (delta vs baseline ≤ 0 regressions), `pnpm typecheck`, `pnpm lint`, `pnpm i18n:check`, `pnpm build`, `pnpm test:e2e -- 'payments-*.spec.ts'`, `(cd ../vidra-core && go build ./... && go test ./...)`.
- **Manual browser walkthrough** of TS-001 through TS-010 captured as final evidence before plan-verify moves the plan to VERIFIED.
- **Live-stack ops test:** run `pnpm dev:full`, run `btcpay-bootstrap.sh`, exercise tip → settle → transaction list → payout request → admin approve → mark executed. Record screenshots.

---

## Autonomous Decisions

- Spec kept as a SINGLE plan with 19 tasks despite spec-plan guidance to split at 12 — user explicitly chose "One big dual-repo spec — all 4 items at once" in Batch 2. **Mitigation: mandatory Mid-Plan Checkpoint after Task 5** (per spec-review F01) — re-approval required before frontend work begins. Plan cannot silently blow through this gate.
- Lightning Network regtest node chosen as LND (`lightninglabs/lnd:v0.17.4-beta`) — widely used with BTCPay, good regtest tooling. Core Lightning (CLN) was a plausible alternative; LND's wider docs and regtest ergonomics won.
- Ledger is the AUTHORITATIVE balance source; invoice table rows act only as the originator reference. This removes divergence risk vs computing balance from invoice status.
- `payout_status` enum has FIVE values (`pending, approved, completed, rejected, cancelled`) — NOT six. `executing` was dropped per spec-review F04; it had no documented transition and would have been dead state risking future bugs.
- BOLT11 decode happens on the BACKEND (wrapping LND's `DecodePayReq` RPC), not a frontend `bolt11` npm package — per spec-review F11 (unmaintained package + browser-incompat + security surface).
- Debug endpoints (e.g., worker-tick) are compiled out of production via Go build tag `debug` — per spec-review F12. Runtime + build-time safety in depth.
- Min payout default fixed at 50,000 sats (~$35 at current price reference); configurable via env for test overrides. Config surfaced to frontend via `/api/v1/payments/config`.
- Balance worker default tick interval 1h; shortened in E2E via build-tag-gated debug endpoint.
- Notification cooldown table (`payment_notification_cooldowns`) promoted from Task 15 to Task 1 migration 096 — per spec-review F09. No deferred surprise migrations.
- Admin approves EVERY payout; no hot-wallet automation in this spec — reflects user choice and removes attack surface.
- No push / email notifications for new event types in this spec — in-app only. Deferred to a separate spec.

## Verification Output

### Task 0 — Baseline (captured 2026-04-24, pre-Task-1, clean tree)

**Frontend (`pnpm test:run`):**
- `baseline_fe_sha256:` `c09c9eafcb81691214092380608e5b2cc8eec947b944619f089ae9d25a3ff297`
- `baseline_fe_files:` 167 passed (167)
- `baseline_fe_pass:` 1367
- `baseline_fe_fail:` 0
- Duration: 57.23s
- Log: `/tmp/phase-8-baseline-frontend.log`

**Backend (`go test ./...`):**
- `baseline_be_sha256:` `79b88098c5ff5ed136714b8e8d50682c8e3bf995335fc133deaafa38e4c2561d`
- `baseline_be_ok_packages:` 86
- `baseline_be_fail_packages:` 5
- Log: `/tmp/phase-8-baseline-backend.log`

**Pre-existing backend failures (NOT introduced by this spec — must remain no-worse at Task 18):**
1. `vidra-core/internal/livestream` — FAIL (runtime)
2. `vidra-core/internal/repository` — FAIL (runtime, 7+ min duration)
3. `vidra-core/internal/setup` — build failed (orphan IOTA references after Bitcoin migration)
4. `vidra-core/internal/usecase` — FAIL (runtime)
5. `vidra-core/tests/integration` — build failed (`setup_wizard_e2e_test.go:37: w.HandleTestIOTA undefined`)

**Commitment:** Task 18 verification asserts `baseline_be_fail_packages` unchanged (5) or reduced. Task implementations MUST NOT touch these packages or they'll be counted against the baseline.

**Working tree state at baseline:** only `tsconfig.tsbuildinfo` (build cache, ignored) and `docs/plans/2026-04-24-phase-8-bitcoin-btcpay-wiring-finish.md` (this plan). No source-code changes.

### Task 18 — Final sweep (to be filled at completion)

_pending_
