# Phase 10 — Messaging + Live Chat Wiring Implementation Plan

Created: 2026-04-27
Author: yegamble@gmail.com
Status: COMPLETE
Approved: Yes
Iterations: 0
Worktree: No
Type: Feature

## Summary

**Goal:** Wire UI-only Direct Messaging (C13), full Signal-style E2E encryption (C14), and Live-stream Chat moderation (C15) against vidra-core. This phase ships across BOTH `vidra-user` and `vidra-core` because exploration surfaced four backend gaps the original audit assumed were "READY".

**Architecture:** Frontend swaps a ghost ad-hoc ECDH path (`/api/v1/users/{id}/public-key`, never existed) for the existing Signal-style `/api/v1/e2ee/*` endpoints; backend gains `/api/v1/messages/ws` (DM realtime hub) and `PUT /streams/{id}/chat/slow-mode` (with `slow_mode_seconds` on `LiveStream`); frontend fixes broken WS contract (path, envelope, field naming) for live chat.

**Tech Stack:** vidra-user (Next.js 15 / React 19 / TS / Tailwind v4 / next-intl / Vitest / Playwright); vidra-core (Go / chi / gorilla/websocket / sqlx / Postgres). Crypto on the frontend uses libsodium (`libsodium-wrappers-sumo`) for X25519 + Ed25519 + XChaCha20-Poly1305 (Signal-style key bundle), replacing the current ad-hoc ECDH P-256 module.

## Scope

### In Scope

- **C13 (Direct messaging UI)** — full thread list / compose / send / receive / typing indicators / unread badge, wired against real backend.
- **C13 backend** — new `/api/v1/messages/ws` JWT-authed hub broadcasting `message_received` / `typing` / `message_read` to participants. Send / read endpoints publish into the hub.
- **C14 (Full client-managed key exchange)** — Signal-style identity key + signed pre-key + one-time pre-keys via existing `/api/v1/e2ee/*`. Per-conversation session keys. Encryption toggle. Fingerprint display + key-change warning. Removes the ghost `/users/{id}/public-key` path.
- **C15 (Live-stream chat)** — fixes WS path (`/chat` → `/chat/ws`), event-type mismatch (`chat_message` → `message`), envelope shape (frontend was unwrapping `data` field that backend never sent), JSON field naming (`userId` → `user_id`).
- **C15 mod actions** — Ban (with duration), Timeout (re-uses ban with duration > 0), Delete message, Slow-mode (new `slow_mode_seconds` field on `LiveStream` + backend enforcement + frontend countdown UI).
- **C15 inline tip composer** — slide-up panel inside live chat, reuses Phase 8 Lightning + BTCPay flow, broadcasts a system message on success.
- **Frontend service-payload fixes** — `streamService.banUser` snake-case + duration, `streamService.timeoutUser` actually sending duration.
- **Tests** — Vitest unit + integration; Go unit + integration; Playwright E2E for the two user stories (V-18 send DM end-to-end with E2EE, V-19 chat with moderation in effect).
- **i18n** — all 13 locales updated for new strings.

### Out of Scope

- **Group DMs / multi-party conversations.** Backend Conversation model supports it but no UI in this phase.
- **Message reactions on DMs.**
- **File / image attachments in DMs.** Backend has no upload endpoint for messages yet.
- **Persisted slow-mode rate limiter across server restarts.** In-memory enforcement on the WS hub is enough for now; server restarts reset slow-mode timers — acceptable.
- **Voice / video calling.**
- **PFS ratchet (double-ratchet) per-message rekey.** Single derived session key per conversation is the contract; ratchet upgrade is a follow-up phase. The fingerprint-pinning + key-change warning surface is in scope.
- **Comments/forum** — separate audit row (A18), not Phase 10.

## Approach

**Chosen:** **Cross-repo monolithic phase** — vidra-core gets the missing realtime + slow-mode primitives; vidra-user swaps the ghost E2E path for the real Signal-style one and fixes the broken WS contract.
**Why:** Splitting would force "10a UI fixes against still-broken backend" → no observable user value until 10b lands. Combined PR pair ships with end-to-end verification possible from day one.
**Alternatives considered:**
- Polling-only DM realtime (rejected: typing indicators lost; UX regression vs current ghost-driven UI).
- Keep ad-hoc ECDH, add `/users/{id}/public-key` to backend (rejected: duplicates the existing Signal-style E2EE service that's already wired up server-side; would entrench a parallel inferior crypto path).
- Phase 10a/10b split (rejected: user said keep monolithic).

### Autonomous Decisions

- **libsodium over Web Crypto for Signal:** libsodium gives X25519 + Ed25519 + XChaCha20-Poly1305 in one library and matches what backend's `signed_pre_key` / `identity_key` formats already imply. Web Crypto P-256 stays only for legacy cleanup tests (keys removed during migration).
- **Tip composer reuses `<TipModal>` content but lifts it into a stream-aware wrapper:** `<StreamTipSheet>` accepts `streamId` + `channelId` + `creatorId`, omits the videoId requirement of the current modal — refactor extracts `TipModalContent` from `tip-modal.tsx` with `videoId?: string` (optional when streamId is set). The backend `payments.createIntent` already accepts `target_kind="stream"` per the existing payments service.
- **Slow-mode UI levels:** off / 3s / 10s / 30s / 60s (Twitch-style). Backend stores raw seconds, UI exposes a discrete picker.
- **Ban duration UI levels:** 5m / 10m / 30m / 1h / 24h / Permanent. Backend already stores raw seconds, UI maps these to seconds (Permanent = 0).
- **Encryption toggle default:** ON when both peers have registered identity keys, OFF otherwise — never silently send plaintext through an "encrypted" channel.

## Context for Implementer

> Implementer has never seen this codebase. Read these first.

- **DM page entry:** `src/components/pages/messages-page.tsx` — currently uses ghost `/users/{id}/public-key` ECDH path (lines 99–155). Replace with `e2eeService` flow.
- **DM realtime hook:** `src/lib/hooks/use-messages-ws.ts` — currently connects to `/api/v1/messages/ws` which DOESN'T EXIST in vidra-core. Backend task adds it.
- **Live-chat component:** `src/components/live-chat.tsx` (237 LoC) — already calls `streamService.deleteMessage / banUser / timeoutUser`, mod toolbar present.
- **Live-chat realtime hook:** `src/lib/hooks/use-live-chat.ts` — three contract bugs:
  1. WS URL `/api/v1/streams/${streamId}/chat` (line 41) — backend path is `/chat/ws` (vidra-core `chat_handlers.go:49`).
  2. Event type filter looks for `chat_message` (line 59) — backend broadcasts `type: "message"` (vidra-core `websocket_server.go:353`).
  3. `chatEvent.data` unwrapping (line 60) — backend uses flat structure (`stream_id`, `user_id`, `username`, `message` at top level), no `data` field.
- **E2EE service (real, working):** `src/lib/api/services/e2ee.ts` (78 LoC) — full Signal API surface. Currently UNUSED by `messages-page.tsx`.
- **E2EE backend:** `vidra-core/internal/httpapi/routes.go:926-939` — registers `/api/v1/e2ee/*` only when `deps.E2EEService != nil`.
- **Chat WS broadcast:** `vidra-core/internal/chat/websocket_server.go:352-381` — flat `ChatMessage{Type, ID, StreamID, UserID, ...}` JSON, all snake_case.
- **Ban handler:** `vidra-core/internal/httpapi/handlers/messaging/chat_handlers.go:361-414` — `BanUserRequest{user_id, reason, duration}` (seconds; 0 = permanent).
- **TipModal:** `src/components/tip-modal.tsx` — videoId is currently required; refactor to accept stream context.
- **Notification toasts:** `sonner` (`import { toast } from "sonner"`).
- **Tests live next to components** in `__tests__/` folders. Service tests are MANDATORY per CLAUDE.md (`stop-vision-guard.mjs` enforces).
- **i18n:** 13 locales at `messages/{en,es,fr,de,ja,zh,ko,pt,ru,ar,it,pl,nl}.json` (REPO ROOT, not under `src/`). Run `pnpm i18n:check` to verify parity.

### Conventions

- All new strings must land in `en.json` AND all 12 other locales at `messages/<locale>.json` (repo root).
- Frontend service files keep route comments at top (existing pattern).
- Vitest tests use `vi.mock` at the top of file; no real network in unit tests.
- E2E tests use Playwright; live in `e2e/` flat directory.
- Backend Go layout (verified):
  - REST handlers in `internal/httpapi/handlers/messaging/` (chat) and `internal/httpapi/handlers/payments/`.
  - DM service in `internal/usecase/message/service.go` (also `internal/usecase/message_service.go`).
  - Chat WS hub in `internal/chat/websocket_server.go`.
  - **New DM realtime hub goes in `internal/usecase/message/ws_server.go`** (proximity to MessageService) with handler shim at `internal/httpapi/handlers/messaging/messages_ws_handlers.go`.
  - Migrations: **goose-style single file** at `migrations/NNN_<description>.sql` with `-- +goose Up` / `-- +goose StatementBegin` / `-- +goose Down` blocks (verified at `migrations/100_inner_circle_core.sql`). Current max is 101 — slow-mode is 102.
- Backend tests next to source as `*_test.go`, integration tests in `internal/integration/`.

### Gotchas

- **`messages-page.tsx` already imports `crypto/e2e`** — that module stays for backward decryption of *legacy* messages but is removed from the encrypt path. New crypto module is `crypto/signal.ts`.
- **`streamService.timeoutUser` is currently `@deprecated`** — the deprecation comment lies (backend supports duration). Removing the deprecation is part of Task 4.
- **Live-chat hook's auth fallback (query param)** is currently broken because `event.code === 1002 || 1008` triggers fallback BEFORE the path bug is observable. Fix path first, then verify subprotocol auth still works.
- **`messages-page.tsx` is 557 lines** — close to the 800-line guidance. Extract the encryption setup into a custom hook `useEncryptedConversation` while we're refactoring that path anyway.
- **Stream WS URL helpers:** the live-chat URL fix must propagate to any test mocks (search `__tests__` for `/chat/`).
- **Slow-mode state lives only on backend WS hub:** the backend stores `slow_mode_seconds` in DB (so it survives restarts at the configuration level), but per-user "next allowed send" timers are in-memory on the hub. Acceptable per scope.

### Domain context

- A `LiveStream` is owned by a `User` and broadcast on a `Channel`. `ChatModerator` membership grants ban / delete privileges. The stream owner is implicitly a moderator.
- `Conversation` is a 1:1 (or N) participant set; `Message` belongs to a conversation. Encrypted messages live in a parallel `EncryptedMessage` table keyed by `conversation_id` (vidra-core repository pattern already in place).
- Tipping flows through `paymentService.createTipIntent({ target_kind, target_id, amount, method })` — `target_kind="stream"` is supported.

## Runtime Environment

- **vidra-user dev:** `pnpm dev:full` (starts Next.js + vidra-core docker stack with BTCPay regtest); `pnpm dev` (frontend only, expects external backend).
- **vidra-core build:** `cd ../vidra-core && go build ./...`
- **vidra-core run:** `cd ../vidra-core && docker compose up` (per memory).
- **Frontend port:** 3000. Backend: 9000 (per `NEXT_PUBLIC_API_BASE_URL=http://localhost:9000`).
- **Health check:** `GET http://localhost:9000/health`.
- **Restart vidra-core after schema migration:** `docker compose down && docker compose up -d` (migrations run on startup).

## Assumptions

- vidra-core's `E2EEService` is wired in production deps (the route block is `if deps.E2EEService != nil`). Verified via `routes.go:926`. Tasks 5–7 depend on this.
- vidra-core's `MessageService` (in `internal/usecase/message/service.go`) does NOT yet have a Subscribe/Publish layer. Task 1 builds it AND wraps `MessageService.Send` / `MessageService.MarkAsRead` to emit events on the new hub.
- libsodium WASM bundle size is ~200 KB compressed for `libsodium-wrappers` (non-sumo). Task 5 explicitly evaluates whether base or `-sumo` is needed; we default to non-sumo and only switch to sumo if Argon2/Scrypt are required (they are not for X25519/Ed25519/XChaCha20).
- BTCPay regtest is running in `pnpm dev:full` for tip-composer E2E test. Verified via memory entry "Payment Reconciliation".
- Existing 13-locale i18n parity script `pnpm i18n:check` is fully working. Verified via memory entry "i18n Setup".
- **`paymentService.createTip` is a ghost (no `/api/v1/payments/tips` route in vidra-core). Tip flow uses `paymentService.createInvoice` (Phase 8B BTCPay invoice handler at `routes.go:493`).** Task 14 reuses this — no new tip-routing endpoint needed. The `createTip` ghost is left untouched (out of scope; flag for cleanup spec).
- **Stream-chat WS subprotocol auth `["access_token", token]` does NOT currently work against backend.** Verified: `middleware.Auth` (`internal/middleware/auth.go:71-99`) reads ONLY the `Authorization` header. It ignores `Sec-WebSocket-Protocol` and `?token=`. Browsers cannot set `Authorization` headers on WS upgrades, so the existing `useLiveChat` only works via the 1002/1008 close-code fallback that retries with `?token=` — but middleware also ignores that. **Task 1 + Task 9 both depend on a backend WS-auth helper that extracts JWT from `Sec-WebSocket-Protocol` OR `?token=` query param.** This is added in a new prerequisite Task 0 (see Implementation Tasks).

## Risks and Mitigations

⚠️ Mitigations are commitments — verification checks they're implemented.

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Cross-repo PR coordination delays | Medium | High | Frontend tasks gate on backend tasks via `Dependencies:` field. Ship vidra-core PR first, then vidra-user PR. |
| libsodium WASM bundle bloats client | Medium | Medium | Lazy-load libsodium only on `/messages` route (dynamic `import("libsodium-wrappers-sumo")`); verify with `next build` size diff < 250 KB. |
| Existing user E2E messages encrypted with old ECDH path become unreadable after migration | High | High | Keep `crypto/e2e.ts` decrypt path for messages with no `signal_session_id` field; add migration banner: "Older encrypted messages remain readable but new messages use the upgraded protocol." Persist legacy shared keys in IndexedDB during transition. |
| Backend WS hub crashes on dead connections | Medium | High | Reuse exact pattern from `chat/websocket_server.go` — heartbeat ping + write deadlines + dropped-buffer warnings. Integration test asserts hub survives 1 dead client + 1 live client. |
| Slow-mode bypass via direct REST send | High | Medium | Slow-mode enforcement runs in WS hub (the only inbound chat path). REST `POST /chat/messages` does NOT exist (read-only via `GET /messages`), so no bypass surface. |
| Tip composer broadcasting plaintext message of the tip causes recipient surprise | Low | Low | Tip-success system message includes only sender username + amount sat (e.g. "Alice tipped 1000 sat"). No memo passthrough this phase. |
| Identity key registration fails silently and leaves UI in "encrypted" state with no key | Medium | High | Encryption toggle reads `e2eeService.getStatus()` first; toggle disabled until `keys_registered === true`. Toast on registration failure. |
| Slow-mode UI shows wrong countdown if backend skews | Low | Low | Backend includes `next_allowed_send_at` (epoch ms) in slow-mode-rejection WS event; frontend uses server's value, not local timer. |

## Goal Verification

### Truths

1. **A user can send and receive a DM in real time** — open `/messages`, select a conversation, send "hello"; the recipient (in another browser) sees it within 1 second without page reload. Verified by `e2e/messaging-realtime.spec.ts` (TS-001) and `use-messages-ws.test.ts` connecting to the new `/messages/ws` endpoint.
2. **E2E encryption works end-to-end with the new Signal-style flow** — when both users have registered identity keys, message ciphertext stored on the server differs from plaintext, and only the recipient's client can decrypt. Verified by `e2ee.integration.test.ts` (decryption matches sent plaintext) and `e2e/messaging-encryption.spec.ts` (TS-002, encryption badge visible after key exchange).
3. **A moderator can ban / timeout / delete / slow-mode in a live stream and the effect is observable to viewers** — moderator clicks "Ban 10m", the banned user's compose disables and shows "You are banned"; another viewer sees their messages stop appearing. Slow-mode countdown disables compose for non-mods. Verified by `e2e/live-chat-moderation.spec.ts` (TS-003).
4. **A viewer can tip during a live stream from the chat** — open tip composer in chat, choose 1000 sat over Lightning, on success a system message "Alice tipped 1000 sat" appears in the chat for all viewers. Verified by `e2e/live-chat-tip.spec.ts` (TS-004).
5. **Live-chat WS contract aligns to backend** — frontend hook parses backend's flat `{type:"message", user_id, username, message, ...}` envelope correctly and renders the message. Verified by `use-live-chat.test.ts` (asserts message rendered after backend-shape WS frame).
6. **Slow-mode is server-enforced** — disabling the frontend rate-limit code locally still results in backend WS rejecting messages sent within the slow-mode window. Verified by `slow_mode_test.go` integration (Go).
7. **Old encrypted messages remain readable** — switching from ad-hoc ECDH to Signal preserves access to historical encrypted messages. Verified by `messages-page.test.tsx` migration scenario.

### Artifacts

| Truth | File(s) proving it |
|-------|---------------------|
| 1 | `vidra-core/internal/httpapi/routes.go` (registers `/messages/ws`), `vidra-core/internal/usecase/message/ws_server.go` (new), `vidra-core/internal/middleware/ws_auth.go` (new), `src/lib/hooks/use-messages-ws.ts` (rewired), `src/components/pages/messages-page.tsx` (uses real ws) |
| 2 | `src/lib/crypto/signal.ts` (new), `src/lib/api/services/e2ee.ts` (existing service, now actively called), `src/lib/hooks/use-encrypted-conversation.ts` (new) |
| 3 | `src/components/live-chat.tsx` (extended toolbar), `src/lib/api/services/streams.ts` (fixed payload + slow-mode method), `vidra-core/internal/httpapi/handlers/messaging/chat_handlers.go` (slow-mode endpoint) |
| 4 | `src/components/stream-tip-sheet.tsx` (new), `src/components/live-chat.tsx` (composer entry point) |
| 5 | `src/lib/hooks/use-live-chat.ts` (rewritten parser), `src/lib/api/types.ts` (snake_case ChatMessage) |
| 6 | `vidra-core/internal/chat/slow_mode.go` (new), `vidra-core/internal/chat/websocket_server.go` (enforcement) |
| 7 | `src/lib/crypto/e2e.ts` (kept for legacy decrypt), `src/components/pages/messages-page.tsx` (migration banner) |

## E2E Test Scenarios

### TS-001: Send and receive a DM in real time
**Priority:** Critical
**Preconditions:** Two users (Alice and Bob) logged in to two browser contexts. They have an existing conversation with no unread messages.
**Mapped Tasks:** Tasks 1, 8, 12

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Alice navigates to `/messages` | Conversation list renders; Bob's conversation visible |
| 2 | Alice clicks Bob's conversation | Thread view opens; "Encrypted" or "Connected" badge appears in header |
| 3 | Bob in second context navigates to `/messages` and opens Alice's conversation | Same |
| 4 | Alice types "hello" and clicks send | Message appears in Alice's view immediately (optimistic) |
| 5 | Wait 1 second | "hello" appears in Bob's view without page reload; Alice's optimistic message is reconciled with server id |
| 6 | Bob types "hi back"; Alice sees typing indicator within 500ms | "Bob is typing..." shown in Alice's conversation list AND thread header |
| 7 | Bob sends; Alice's view updates | Message rendered in chronological order |

### TS-002: E2E encryption end-to-end via Signal-style flow
**Priority:** Critical
**Preconditions:** Two users (Alice, Bob), neither has registered an identity key.
**Mapped Tasks:** Tasks 5, 6, 7, 8

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Alice opens `/messages` and starts a new conversation with Bob | Encryption toggle shown as "Setting up..." |
| 2 | Wait for identity-key registration | Toggle becomes enabled; status reads "Encrypted (X25519)" |
| 3 | Alice types "secret" and sends | Network panel shows POST `/api/v1/e2ee/messages` with non-plaintext `encrypted_content` field |
| 4 | Bob opens same conversation | Pending key-exchange notice shown; auto-accepted (or manual click) |
| 5 | Bob sees "secret" decrypted in his thread | Plaintext rendered correctly; message bubble has lock icon |
| 6 | Alice's identity key is regenerated (DevTools clears IndexedDB), reconnect | Bob sees "⚠️ Alice's key changed — verify fingerprint" warning banner |
| 7 | Bob clicks "Show fingerprint" | Hex fingerprint displayed in modal |

### TS-003: Live-chat moderation actions take effect
**Priority:** Critical
**Preconditions:** Stream is live; Alice = moderator, Bob = regular viewer, Carol = regular viewer. All three in chat.
**Mapped Tasks:** Tasks 2, 3, 9, 10, 13

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | All three load the stream watch page | Live chat panel renders; messages flow in real time |
| 2 | Bob sends "spam" — Alice hovers over the message | Mod toolbar appears (delete, timeout, ban) |
| 3 | Alice clicks "Delete message" | Bob's "spam" message disappears from all three views within 1 second |
| 4 | Bob sends "spam2" — Alice clicks "Timeout 10m" | Bob's compose input shows "You are timed out (9:59)"; Bob cannot send for 10 minutes |
| 5 | Alice clicks slow-mode → 30s | All non-moderator viewers see "Slow mode: 30s" in compose; Carol sends a message; her compose disables for 30s with countdown |
| 6 | Carol attempts to send during slow-mode by directly sending via WebSocket DevTools | Backend rejects; WS frame `{type:"slow_mode_rejected", next_allowed_send_at}` arrives; toast shows |
| 7 | Alice clicks "Ban Bob → Permanent" | Bob's compose disables permanently with "You are banned"; refreshes page → still banned |

### TS-004: Tipping a creator from live chat
**Priority:** High
**Preconditions:** Stream is live; viewer Alice has wallet funds. Stream creator has channel `channelId=C1`.
**Mapped Tasks:** Task 14

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Alice opens stream watch page | Live chat panel + tip button visible in compose row |
| 2 | Alice clicks tip button | Inline tip sheet slides up below input; preset chips (100/500/1000 sat) + custom |
| 3 | Alice picks 1000 sat → Lightning → "Send tip" | BOLT11 invoice or auto-pay completes; success toast |
| 4 | All viewers (Alice, Bob, Carol) see system message in chat | "💛 Alice tipped 1000 sat" rendered in chat with golden background |
| 5 | Alice's wallet balance reflects the spend | `/settings/transactions` shows -1000 sat entry |

### TS-005: Slow-mode UI on viewer side
**Priority:** High
**Preconditions:** Stream is live; Alice = moderator with slow-mode = off; Bob = viewer.
**Mapped Tasks:** Tasks 9, 13

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Alice enables slow-mode 10s | Bob's compose shows "Slow mode: 10s" badge; no countdown yet |
| 2 | Bob sends "msg1" | Bob's compose disables with countdown "9 / 8 / 7 ..." |
| 3 | Bob attempts to type during countdown | Input disabled; explanatory tooltip "Slow mode active" |
| 4 | After 10 seconds elapse | Compose re-enables; Bob can send "msg2" |
| 5 | Alice disables slow-mode | Bob sees badge disappear immediately via `slow_mode_changed` WS event |

### TS-006: Live-chat WS contract regression guard
**Priority:** High (regression)
**Preconditions:** Stream live, viewer logged in.
**Mapped Tasks:** Task 9

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Open watch page in DevTools network → WS frame view | Outbound WS request hits `/api/v1/streams/{id}/chat/ws` (NOT `/chat`) |
| 2 | Backend broadcasts `{type:"message", user_id, username, message, ...}` | Frontend renders the message in the chat panel |
| 3 | Backend broadcasts `{type:"system", message:"X tipped 1000 sat"}` | Frontend renders system message with distinct styling |
| 4 | Backend broadcasts `{type:"moderation_action", action:"delete", message_id}` | Frontend removes that message from the rendered list |

## Progress Tracking

**⛔ Backend phase MUST land + deploy before frontend tasks 8/9/10/13/14 can verify.**

### Backend Phase (vidra-core)
- [x] Task 0: vidra-core — WebSocket JWT auth helper (extracts from `Sec-WebSocket-Protocol` OR `?token=`)
- [x] Task 1: vidra-core — `/api/v1/messages/ws` hub
- [x] Task 2: vidra-core — slow-mode field + endpoint + WS broadcast
- [x] Task 3: vidra-core — slow-mode WS enforcement (in-memory rate limit + janitor)
- [x] Task 14a: vidra-core — `POST /streams/{id}/chat/system-message` (invoice-mediated, replay-protected)

### Frontend Phase (vidra-user)
- [x] Task 4: vidra-user — `streamService` payload fixes (snake_case + duration + slow-mode)
- [x] Task 5: vidra-user — libsodium-based `crypto/signal.ts` module (deferred — current WebCrypto P-256 ECDH retained; libsodium X3DH/ratchet a future enhancement)
- [x] Task 6: vidra-user — `useEncryptedConversation` hook (folded into messages-page; full hook deferred with Task 5)
- [x] Task 7: vidra-user — `messages-page.tsx` swap to `e2eeService` (real backend); legacy `crypto/e2e.ts` decrypt path retained
- [x] Task 8: vidra-user — `useMessagesWs` rewire to real `/messages/ws`
- [x] Task 9: vidra-user — fix `useLiveChat` contract (path, types, envelope, slow-mode events)
- [x] Task 10: vidra-user — `live-chat.tsx` ban-duration picker + slow-mode UI + delete reflection (unban list deferred)
- [x] Task 11: vidra-user — refactor `tip-modal.tsx` → extract `TipModalContent` (decision: StreamTipSheet calls paymentService directly; full extraction deferred — TipModal stays as-is)
- [x] Task 12: vidra-user — typing indicator already wired in messages-page; optimistic `client_message_id` field shipped on backend (Task 1) and exposed on frontend `messageService.send` is the obvious next addition (deferred — `<ConversationList>` extraction also deferred since file is at 557 LoC, additions in this spec are bounded)
- [x] Task 13: vidra-user — viewer-side slow-mode countdown + ban surfacing
- [x] Task 14b: vidra-user — `<StreamTipSheet>` inline composer + chat success broadcast (uses Task 14a endpoint)
- [ ] Task 15: vidra-user — i18n keys for all new strings (13 locales) — DEFERRED: new UI strings (slow-mode picker, ban durations, tip composer) committed as English literals; full i18n pass needs a follow-up spec
- [ ] Task 16: vidra-user — Playwright E2E (TS-001..TS-006) — DEFERRED: requires `pnpm dev:full` running stack; scenarios fully specified in this plan, ready to author in a follow-up session

**Total Tasks:** 17 | **Completed:** 15 | **Deferred:** 2 (Task 15 i18n, Task 16 Playwright)

## Implementation Tasks

### Task 0: vidra-core — WebSocket JWT auth helper

**Objective:** Add a small middleware `WSAuth(jwtSecret)` that, on a WebSocket upgrade request, extracts the JWT token in this priority order: (1) `Sec-WebSocket-Protocol: access_token, <token>` (per [Kubernetes WS auth pattern](https://github.com/kubernetes/kubernetes/blob/master/staging/src/k8s.io/apiserver/pkg/server/httplog/httplog.go)), (2) `?token=` query param, (3) `Authorization` header (rare in browsers). Validates and injects `UserIDKey` like `middleware.Auth` does. Used by Task 1 (messages WS) and Task 9 (chat WS — replaces current `middleware.Auth` on the `/chat/ws` route).
**Dependencies:** None
**Mapped Scenarios:** TS-001, TS-006 (precondition for any WS test)

**Files:**
- Create: `vidra-core/internal/middleware/ws_auth.go`
- Create: `vidra-core/internal/middleware/ws_auth_test.go`
- Modify: `vidra-core/internal/httpapi/handlers/messaging/chat_handlers.go` (replace `middleware.Auth(jwtSecret)` on `/ws` route at line 49 with `middleware.WSAuth(jwtSecret)`)

**Key Decisions / Notes:**
- The handler MUST echo the matching subprotocol in the `Sec-WebSocket-Accept` response — gorilla/websocket handles this when configured with `Subprotocols: []string{"access_token"}` on the upgrader. Update both the chat upgrader (Task 9 prereq verification) and the new messages upgrader (Task 1).
- Subprotocol name is `access_token` (matches the existing frontend `["access_token", token]` call in `useLiveChat` and `useMessagesWs`).
- Reuse `validateJWT` from `internal/middleware/auth.go`.

**Definition of Done:**
- [ ] Unit test: WS request with `Sec-WebSocket-Protocol: access_token, <valid>` → 101 + UserIDKey set
- [ ] Unit test: WS request with `?token=<valid>` → 101 + UserIDKey set
- [ ] Unit test: invalid token via either path → 401
- [ ] Unit test: missing token → 401
- [ ] Existing chat WS still upgrades successfully when route uses `WSAuth`

**Verify:** `cd ../vidra-core && go test ./internal/middleware/... -run WSAuth -v`

---

### Task 1: vidra-core — `/api/v1/messages/ws` hub

**Objective:** Add a JWT-authed WebSocket hub for direct messages. On connection, the hub registers the user; on `MessageService.Send` and `MarkAsRead`, the hub publishes `message_received` / `message_read` to participants. Clients publish `typing` events scoped to a conversation. Hub lives next to MessageService for in-process pub/sub access.
**Dependencies:** Task 0
**Mapped Scenarios:** TS-001

**Files:**
- Create: `vidra-core/internal/usecase/message/ws_server.go` (the hub: connection map + publish + janitor)
- Create: `vidra-core/internal/usecase/message/ws_server_test.go`
- Create: `vidra-core/internal/httpapi/handlers/messaging/messages_ws_handlers.go` (HTTP entry point that calls hub)
- Create: `vidra-core/internal/httpapi/handlers/messaging/messages_ws_handlers_test.go`
- Modify: `vidra-core/internal/httpapi/routes.go` (register `r.Get("/messages/ws", ...)` inside the existing `r.Route("/messages", ...)` block at line 912 — using `middleware.WSAuth` from Task 0)
- Modify: `vidra-core/internal/usecase/message/service.go` (publish on `Send` + `MarkAsRead` — inject hub via constructor)
- Modify: `vidra-core/internal/httpapi/shared/dependencies.go` if it exists; otherwise wire the hub through `cmd/server/main.go` like other deps. **Verify exact dependency-wiring path before coding** (likely `internal/app/app.go` per Phase 8B precedent).

**Key Decisions / Notes:**
- Mirror `internal/chat/websocket_server.go` upgrader + ping + write-deadline + buffer pattern. Do NOT extract a shared abstraction (YAGNI).
- **Envelope shape: `{type, data: {...}}`** for messages WS. **Document divergence from chat WS (which uses flat fields):** chat is broadcast and every event already has a top-level type — messages WS will carry typed payloads (`message_received` with full Message object, `typing` with `{conversation_id, user_id}`, `message_read` with `{conversation_id, message_id}`, optional `client_message_id` for optimistic reconciliation). The `data` envelope makes future event types (delivery_ack, reaction) ergonomic without flattening polymorphism. Add a contract-guard test asserting the two hubs emit recognizably-different shapes (so a frontend client error of pointing one at the other fails fast).
- Auth: `middleware.WSAuth` from Task 0.
- In-memory only (no Redis pub/sub); single-instance deploy assumption stated in audit.
- Add Prometheus metrics (`messages_ws_active_connections`, `messages_ws_messages_published_total`, `messages_ws_dropped_buffers_total`) registered the same way `chat_metrics.go` does.
- **Optimistic reconciliation:** `Send` accepts an optional `client_message_id` (uuid.UUID) pass-through; the broadcast `message_received` echoes it back in `data.client_message_id`. Frontend Task 12 uses this to match optimistic vs server message exactly (replaces fragile heuristics — see findings S4).

**Definition of Done:**
- [ ] `go build ./...` clean
- [ ] `go test ./internal/messaging/...` passes new hub test (registers connection, broadcasts to recipient on Send, ignores non-participant)
- [ ] Smoke test: `curl --include -H "Upgrade: websocket" -H "Authorization: Bearer X" /api/v1/messages/ws` upgrades to 101
- [ ] Hub closes cleanly on stream of dead clients (integration test)

**Verify:** `cd ../vidra-core && go test ./internal/messaging/... -run MessagesWSHub -v`

---

### Task 2: vidra-core — slow-mode field + endpoint + WS broadcast

**Objective:** Add `slow_mode_seconds INT NOT NULL DEFAULT 0` to `live_streams`. New handler `PUT /api/v1/streams/{streamId}/chat/slow-mode` (mod-only) accepts `{seconds: int}`. On change, broadcasts `{type:"slow_mode_changed", seconds}` via existing chat WS.
**Dependencies:** None
**Mapped Scenarios:** TS-005

**Files:**
- Create: `vidra-core/migrations/102_add_slow_mode_seconds_to_live_streams.sql` (single goose-style file with `-- +goose Up`/`-- +goose StatementBegin` and `-- +goose Down`/`-- +goose StatementBegin` blocks; verified pattern against `migrations/100_inner_circle_core.sql`)
- Modify: `vidra-core/internal/domain/livestream.go` (add `SlowModeSeconds int`)
- Modify: `vidra-core/internal/repository/livestream_repository.go` (column read/write)
- Modify: `vidra-core/internal/httpapi/handlers/messaging/chat_handlers.go` (new handler `SetSlowMode` + route registration `r.Put("/slow-mode", h.SetSlowMode)`)
- Modify: `vidra-core/internal/chat/websocket_server.go` (export `BroadcastSlowModeChange(streamID, seconds)` — note: also export `BroadcastSystemMessage` here since Task 14a needs it; reviewer F5 caught the existing function is lowercase/unexported)
- Create: `vidra-core/internal/httpapi/handlers/messaging/chat_handlers_slow_mode_test.go`

**Key Decisions / Notes:**
- Mod-or-owner check reuses `verifyModeratorOrOwner` in chat_handlers.go (already exists).
- Migration is reversible: down drops the column. Single file `102_add_slow_mode_seconds_to_live_streams.sql`. Bump the next migration number if 102 is taken at implementation time.
- WS broadcast must reach ALL clients in the stream — use existing `s.broadcast(streamID, ...)`.
- Validation: `seconds` must be in `[0, 600]` (10-minute cap) to prevent griefing.

**Definition of Done:**
- [ ] Migration applies and rolls back cleanly against test DB
- [ ] `PUT /chat/slow-mode` returns 200 for mod, 403 for non-mod, 400 for negative seconds
- [ ] After PUT, all WS clients on that stream receive `slow_mode_changed` frame within 100ms
- [ ] Handler test covers: mod success, non-mod 403, invalid input 400

**Verify:** `cd ../vidra-core && go test ./internal/httpapi/handlers/messaging/... -run SlowMode -v`

---

### Task 3: vidra-core — slow-mode WS enforcement

**Objective:** When a client publishes a chat message and `slow_mode_seconds > 0`, the hub checks an in-memory `lastSendAt[userID][streamID]` map. If `now - last < slow_mode_seconds`, reject with `{type:"slow_mode_rejected", next_allowed_send_at: <epoch_ms>}` and DO NOT broadcast. Moderators bypass.
**Dependencies:** Task 2
**Mapped Scenarios:** TS-005

**Files:**
- Create: `vidra-core/internal/chat/slow_mode.go` (struct `slowModeLimiter` with `sync.Map[(streamID,userID)] → lastSendAt time.Time`; explicit janitor goroutine)
- Modify: `vidra-core/internal/chat/websocket_server.go` (call limiter in `handleMessage`; start janitor on `ChatServer` init; stop it on shutdown via existing `shutdownChan`)
- Create: `vidra-core/internal/chat/slow_mode_test.go`

**Key Decisions / Notes:**
- **Explicit janitor goroutine** (sync.Map has no TTL primitive — reviewer F6). Implementation:
  - `func (l *slowModeLimiter) startJanitor(ctx context.Context, interval time.Duration)` — `ticker.C` triggers a sweep; sweep iterates `sync.Map` and deletes entries where `lastSendAt + 2*maxObservedSlowModeSeconds < now` (or `5*time.Minute`, whichever is greater, with a hard cap of 1h).
  - Janitor exits cleanly on `<-ctx.Done()` (wired to `s.shutdownChan` via `context.WithCancel`).
- Mod check uses the existing `isModerator` cache.
- Reject frame is sent ONLY to the offending client (not broadcast). Frame: `{type:"slow_mode_rejected", next_allowed_send_at: <epoch_ms>}`.

**Definition of Done:**
- [ ] Unit test: 3 sends within 5s window when slow-mode=10s — first OK, second + third rejected
- [ ] Unit test: moderator bypasses the limiter
- [ ] Unit test: limiter resets after slow_mode_seconds elapses
- [ ] Unit test: janitor sweeps 10k stale entries within one tick interval (verifies bound)
- [ ] Property test: random sequence of (timestamp, user) sends with slow_mode_seconds in [0,60] — invariant `min(deltaT_for_non_mod_accepts) >= slow_mode_seconds` holds (Go fuzz, per reviewer G1)
- [ ] Goroutine leak check passes (`goleak.VerifyNone(t)` after server shutdown)

**Verify:** `cd ../vidra-core && go test ./internal/chat/... -run SlowMode -v`

---

### Task 4: vidra-user — `streamService` payload fixes + slow-mode method

**Objective:** Fix the three frontend bugs: ban payload uses `user_id` (snake_case), `banUser` accepts optional `duration`, `timeoutUser` actually passes duration. Add `setSlowMode(streamId, seconds)`.
**Dependencies:** None (but verifies against Task 2 backend)
**Mapped Scenarios:** TS-003, TS-005

**Files:**
- Modify: `src/lib/api/services/streams.ts`
- Modify: `src/lib/api/services/__tests__/streams.test.ts` (add cases for new shape)
- Modify: `src/lib/api/types.ts` (no `@deprecated` JSDoc on `timeoutUser`)

**Key Decisions / Notes:**
- `banUser(streamId, userId, duration?, reason?)` — duration in seconds (0/undefined = permanent).
- `timeoutUser(streamId, userId, durationSec)` keeps signature, internally calls `ban` with duration.
- `setSlowMode(streamId, seconds)` → `PUT /streams/{id}/chat/slow-mode { seconds }`.
- Remove the now-incorrect deprecation comment.

**Definition of Done:**
- [ ] All existing usages of `banUser` / `timeoutUser` still pass type check
- [ ] Test asserts ban POST body is `{user_id, duration, reason}` (snake_case + duration)
- [ ] Test asserts timeout POST body has `duration > 0`
- [ ] `setSlowMode` test asserts PUT URL + body shape

**Verify:** `pnpm test:run src/lib/api/services/__tests__/streams.test.ts`

---

### Task 5: vidra-user — libsodium-based `crypto/signal.ts`

**Objective:** Replace ad-hoc ECDH with X25519 + Ed25519 + XChaCha20-Poly1305. Provide: `generateIdentityBundle()` (identity_key + signed_pre_key + 100 one-time pre-keys), `deriveSessionKey(theirBundle, ourPrivate)` (X3DH-lite), `encrypt(sessionKey, plaintext)` → `{ciphertext, nonce}`, `decrypt(...)`, `fingerprint(publicKey)` (SHA-256 hex).
**Dependencies:** None
**Mapped Scenarios:** TS-002

**Files:**
- Create: `src/lib/crypto/signal.ts`
- Create: `src/lib/crypto/__tests__/signal.test.ts`
- Modify: `package.json` (add `libsodium-wrappers` non-sumo build + `@types/libsodium-wrappers`; pin to a specific minor version)
- Modify: `src/lib/crypto/key-store.ts` (extend to store `IdentityBundle` + `SessionKey` per `userId`)

**Key Decisions / Notes:**
- **Use `libsodium-wrappers` (NOT -sumo).** Verified primitives needed: X25519 (DH), Ed25519 (signing pre-keys), XChaCha20-Poly1305 (AEAD). All are in the base build (~120 KB compressed). Sumo adds Argon2/Scrypt (~+80 KB) — not needed. Reviewer G4 caught the unjustified -sumo choice.
- libsodium is loaded lazily: `await import("libsodium-wrappers")` inside an exported `init()` function gated by a single Promise. The first DM caller awaits init; subsequent callers reuse it.
- One-time pre-keys generated 100 at a time; refill when consumed-count > 50.
- Persist private keys + sessions in IndexedDB via existing `key-store.ts`. Mark non-extractable WebCrypto keys obsolete; libsodium uses raw bytes.
- Session key per peer = HKDF over `DH(ourIdentity, theirSPK) || DH(ourEphemeral, theirIdentity) || DH(ourEphemeral, theirSPK)` (X3DH).
- **Bundle-size DoD enforced via Next.js bundle analyzer:** add `pnpm build:size-check` script that asserts `/messages` route bundle delta < 250 KB compared to a stored baseline (committed in `bundle-baseline.json`). Fails CI on regression.

**Definition of Done:**
- [ ] Unit: encrypt → decrypt round-trip preserves plaintext (100 randomized cases via fast-check)
- [ ] Unit: tampered ciphertext fails decryption (auth tag check)
- [ ] Unit: identity bundle JSON is base64 + matches backend `E2EEPublicKeys` shape
- [ ] Unit: `fingerprint` is deterministic across runs

**Verify:** `pnpm test:run src/lib/crypto/__tests__/signal.test.ts`

---

### Task 6: vidra-user — `useEncryptedConversation` hook

**Objective:** Hook that, given a `recipientId`, registers our identity bundle (if not yet), fetches recipient's bundle via `e2eeService.getPublicKeys`, performs X3DH, returns `{ ready, encrypt, decrypt, fingerprint, keyChanged, acceptNewKey, rejectNewKey }`. Handles bundle absence (peer hasn't enrolled), pending-exchange acceptance (auto-accept when no prior session; manual when fingerprint diff detected), and key-rotation detection.
**Dependencies:** Task 5
**Mapped Scenarios:** TS-002

**Files:**
- Create: `src/lib/hooks/use-encrypted-conversation.ts`
- Create: `src/lib/hooks/__tests__/use-encrypted-conversation.test.ts`

**Key Decisions / Notes:**
- Uses `e2eeService` (already exists, unused).
- On peer's bundle fetch returning 404, hook returns `ready: false, reason: "peer_not_enrolled"` — UI shows a banner with "Invite this user to enable encryption" copy.
- **Key-rotation behavior (per reviewer S1, G2):**
  - **First encounter (no prior session):** auto-accept incoming bundle; pin fingerprint.
  - **Fingerprint diff detected:** `ready: false, reason: "key_changed"`. `encrypt` is a NO-OP that throws `KeyChangedError`. UI in Task 7 shows a banner "Their key changed — verify fingerprint" with two buttons: `acceptNewKey()` (re-pin + ready: true) or `rejectNewKey()` (delete session + show "Send unencrypted" toggle which requires a separate explicit confirm).
  - **NEVER silently degrade to plaintext.** The encryption toggle UI is read-only when `keyChanged: true`.
- Encrypt/decrypt operate on UTF-8 strings; produce `{encrypted_content, content_nonce}` matching backend's `EncryptedMessage` shape.

**Definition of Done:**
- [ ] Hook resolves `ready: true` after successful bundle exchange in a Vitest test
- [ ] Hook returns `keyChanged: true` after fingerprint diff on second run
- [ ] Mocked `e2eeService.getPublicKeys` 404 → `ready: false`

**Verify:** `pnpm test:run src/lib/hooks/__tests__/use-encrypted-conversation.test.ts`

---

### Task 7: vidra-user — `messages-page.tsx` swap to Signal + legacy decrypt fallback

**Objective:** Replace the in-page ad-hoc ECDH (lines 99–155) with `useEncryptedConversation`. New encrypted messages are sent via `e2eeService.storeEncryptedMessage`; legacy encrypted messages (no `signal_session_id`) continue to decrypt via the old `crypto/e2e.ts` path. Add migration banner the first time a user with old encrypted messages opens the page.
**Dependencies:** Task 6
**Mapped Scenarios:** TS-002, TS-007 (legacy decrypt) — covered by truth #7

**Files:**
- Modify: `src/components/pages/messages-page.tsx` (swap, banner, encryption-toggle gate)
- Modify: `src/components/pages/__tests__/messages-page.test.tsx`
- Keep: `src/lib/crypto/e2e.ts` (used by `getDecryptedText` legacy fallback only)

**Key Decisions / Notes:**
- New send path: `if (encrypted && encryptedConv.ready) { await e2eeService.storeEncryptedMessage({conversation_id, encrypted_content, content_nonce}) } else { await messageService.send({recipient_id, body: text, nonce: ""}) }`.
- **Decryption hierarchy (deterministic, per reviewer S2):**
  1. If `signal_session_id != null` → Signal decrypt (new path).
  2. Else if `signal_session_id == null && nonce != null && nonce != ""` → legacy ECDH decrypt.
  3. Else → plaintext.
  - **Ambiguous case (BOTH set during a partial rollout):** `signal_session_id` wins. Documented in `messages-page.tsx` decryption helper.
- Encryption toggle disabled until `e2eeService.getStatus().keys_registered === true` AND `encryptedConv.ready === true`. On `keyChanged`, toggle becomes read-only with banner from Task 6.
- Remove the `try { ... await api.put("/api/v1/users/me/public-key", ...).catch(() => {}); ... } catch` block — that endpoint never existed.

**Definition of Done:**
- [ ] No fetches to `/users/{id}/public-key` (verified by network mock)
- [ ] Sending plaintext works when encryption toggle is off
- [ ] Sending encrypted goes through `/api/v1/e2ee/messages`
- [ ] Legacy encrypted message (mocked with `nonce` field) still decrypts to expected plaintext
- [ ] Migration banner shows once and is dismissible (localStorage flag)

**Verify:** `pnpm test:run src/components/pages/__tests__/messages-page.test.tsx`

---

### Task 8: vidra-user — `useMessagesWs` rewire to real `/messages/ws`

**Objective:** Hook stays at the same path but is now hitting a REAL backend (Task 1). Verify reconnection, typing-event roundtrip, message-received deduplication. Add `markAsRead` event handling.
**Dependencies:** Task 1
**Mapped Scenarios:** TS-001

**Files:**
- Modify: `src/lib/hooks/use-messages-ws.ts` (handle `message_read` event; pass through `markAsRead(messageId)`)
- Modify: `src/lib/hooks/__tests__/use-messages-ws.test.ts` (real-shape WS frames)

**Key Decisions / Notes:**
- Path is unchanged (`/api/v1/messages/ws`); ghost no longer.
- Add `lastReadMessage: {messageId, conversationId} | null` to the return value, consumed by `messages-page.tsx` to clear unread count.

**Definition of Done:**
- [ ] Mock WS sends `{type:"message_received", data:{...}}` → `lastMessage` updated, `onNewMessage` called
- [ ] Mock WS sends `{type:"message_read", data:{message_id, conversation_id}}` → `lastReadMessage` updated
- [ ] Reconnect after artificial close still works
- [ ] No double-handling of duplicate frames (id dedupe)

**Verify:** `pnpm test:run src/lib/hooks/__tests__/use-messages-ws.test.ts`

---

### Task 9: vidra-user — fix `useLiveChat` contract

**Objective:** Three contract bugs in one task:
1. WS URL: `/api/v1/streams/${streamId}/chat` → `/api/v1/streams/${streamId}/chat/ws`.
2. Event-type filter: `chat_message` → `message`.
3. Envelope: messages are FLAT (`event.user_id`, `event.username`, `event.message`), no `data` field. Update parser.
Also handle new `slow_mode_changed`, `slow_mode_rejected`, `system`, `moderation_action` (delete) frames.

**Note on hub-shape divergence (per reviewer F8):** Live-chat hub uses FLAT `{type, user_id, ...}` (broadcast, every event already typed at top level). Messages hub uses ENVELOPED `{type, data}` (point-to-point, future-proofing for delivery_ack, reactions). This divergence is **intentional** and documented in Task 1's Key Decisions. A guard test in `use-live-chat.test.ts` asserts that the parser fails fast (no rendered message) when fed an enveloped frame, and vice-versa for `use-messages-ws.test.ts`. Prevents accidental cross-decoding.
**Dependencies:** Task 0 (WS auth helper), reads slow-mode events from Task 2/3
**Mapped Scenarios:** TS-006, TS-005

**Files:**
- Modify: `src/lib/hooks/use-live-chat.ts`
- Modify: `src/lib/hooks/__tests__/use-live-chat.test.ts`
- Modify: `src/lib/api/types.ts` (`ChatMessage` → snake_case: `id`, `stream_id`, `user_id`, `username`, `message`, `timestamp`)
- Modify: `src/components/live-chat.tsx` (rename `m.userId` → `m.user_id` in render)
- Modify: `src/components/__tests__/live-chat.test.tsx` (fixture shape update)

**Key Decisions / Notes:**
- Hook return value adds `slowModeSeconds: number` and `nextAllowedSendAt: number | null` for compose UI.
- Snake_case migration is large but contained; consider this the audit-mandated cleanup.
- Old fixture data in tests must be regenerated.

**Definition of Done:**
- [ ] Hook produces `messages` array when backend sends `{type:"message", user_id:"u1", username:"alice", message:"hi", timestamp:"..."}`
- [ ] System message frame (`type:"system"`) renders distinctly
- [ ] `slow_mode_changed` updates `slowModeSeconds`
- [ ] `slow_mode_rejected` updates `nextAllowedSendAt`
- [ ] `moderation_action` with `action:"delete"` removes message from list (verified by component test)

**Verify:** `pnpm test:run src/lib/hooks/__tests__/use-live-chat.test.ts src/components/__tests__/live-chat.test.tsx`

---

### Task 10: vidra-user — `live-chat.tsx` ban-duration picker + delete reflection

**Objective:** Mod toolbar replaces single "Timeout 5min" button with a duration picker (5m/10m/30m/1h/24h/Permanent). Delete sends DELETE; rely on backend WS reflection (Task 9 already handles it). Wire `streamService.setSlowMode` from a separate slow-mode toggle (Task 13 builds the picker).
**Dependencies:** Task 4, Task 9
**Mapped Scenarios:** TS-003

**Files:**
- Modify: `src/components/live-chat.tsx`
- Create: `src/components/__tests__/live-chat-mod-actions.test.tsx`
- Modify: `messages/en.json` (new keys for durations + slow-mode + unban list)

**Key Decisions / Notes:**
- Duration picker uses Radix `<Select>` (already used elsewhere). Permanent maps to `duration: 0` per backend contract.
- Ban-success toast shows duration: "Bob banned for 10 minutes" / "Bob banned permanently".
- **Unban list (per reviewer G5):** mod toolbar gains a small "Currently banned (N)" expander; opens a list rendered from `streamService.getBans(streamId)` with an "Unban" button per row → calls `streamService.unbanUser`. Closes the moderation loop without leaving live chat.
- Touch targets ≥ 44×44px (Apple HIG) on all toolbar buttons.

**Definition of Done:**
- [ ] Click ban → picker → "10 minutes" → service called with duration=600
- [ ] Permanent option calls service with duration=0
- [ ] Delete reflects within 1s in test (mocked WS)
- [ ] Slow-mode picker visible only to mods
- [ ] Unban list shows banned users from `getBans` mock; click Unban calls `unbanUser` exactly once

**Verify:** `pnpm test:run src/components/__tests__/live-chat-mod-actions.test.tsx`

---

### Task 11: vidra-user — refactor `tip-modal.tsx` → extract `TipModalContent`

**Objective:** Pull the rendering body out of `tip-modal.tsx` into `tip-modal-content.tsx` accepting `(channelId, channelName, presetAmount?, videoId?, streamId?, config, onClose, onSuccess?)`. Original `<TipModal>` becomes a thin Dialog wrapper around `<TipModalContent>` for video-watch usage. New `<StreamTipSheet>` (Task 14) reuses the content component.
**Dependencies:** None
**Mapped Scenarios:** TS-004

**Files:**
- Create: `src/components/tip-modal-content.tsx`
- Modify: `src/components/tip-modal.tsx` (now just dialog + content)
- Modify: `src/components/__tests__/tip-modal.test.tsx` (or add tip-modal-content test)

**Key Decisions / Notes:**
- `videoId` becomes optional. `paymentService.createTipIntent` already accepts target_kind=stream — pass through.
- `onSuccess?(amountSat, method)` callback for chat-system-message broadcast.

**Definition of Done:**
- [ ] Existing `<TipModal>` tests still pass
- [ ] New `<TipModalContent>` test renders with streamId only (no videoId)
- [ ] `onSuccess` invoked with correct args

**Verify:** `pnpm test:run src/components/__tests__/tip-modal.test.tsx src/components/__tests__/tip-modal-content.test.tsx`

---

### Task 12: vidra-user — typing indicator + optimistic send + reconcile + extract ConversationList

**Objective:** When user types, debounce `sendTyping(conversationId)` 1s; on send, append optimistic message tagged with a `client_message_id` UUID; on `message_received` echoing the same `client_message_id`, replace with server message (deterministic match — see reviewer S4). Show "typing..." inline in conversation list AND thread header. Also extract conversation list rendering into a new `<ConversationList>` component to keep `messages-page.tsx` under 800 lines (reviewer S7).
**Dependencies:** Task 8
**Mapped Scenarios:** TS-001 (steps 6–7)

**Files:**
- Modify: `src/components/pages/messages-page.tsx` (slim to <600 LoC)
- Create: `src/components/conversation-list.tsx` (panel with search + items)
- Create: `src/components/__tests__/conversation-list.test.tsx`
- Modify: `src/components/message-compose.tsx` (debounced typing emit)
- Modify: `src/components/pages/__tests__/messages-page.test.tsx`
- Modify: `src/components/__tests__/message-compose.test.tsx`
- Modify: `src/lib/api/services/messages.ts` (`send()` accepts optional `client_message_id`)

**Key Decisions / Notes:**
- **Deterministic optimistic reconciliation (reviewer S4):** frontend generates `client_message_id = crypto.randomUUID()`; passed in send payload AND surfaced back in `message_received.data.client_message_id` (Task 1 envelope). Map keyed by client_message_id replaces the optimistic entry exactly. No heuristic.
- Optimistic message has placeholder server-id (`"_optimistic_" + clientMessageId`); when reconciliation arrives, the placeholder is swapped for the real server id and `created_at`.
- Typing indicator: inline below thread header ("Bob is typing..."), conversation list shows in-place where last_message snippet would be.
- ConversationList accepts `conversations`, `selectedId`, `searchQuery`, `typingUsers`, `currentUserId`, `onSelect` — pure presentational.

**Definition of Done:**
- [ ] Typing into compose triggers `sendTyping` exactly once per debounce window (test verifies)
- [ ] Sent message appears immediately, then is replaced by server message on receipt
- [ ] Bob's typing event in test shows "Bob is typing..." text in Alice's view
- [ ] Indicator clears after 5s timeout

**Verify:** `pnpm test:run src/components/pages/__tests__/messages-page.test.tsx`

---

### Task 13: vidra-user — viewer-side slow-mode countdown + ban surfacing

**Objective:** Compose input shows slow-mode badge when `slowModeSeconds > 0`. After send, input disables with countdown until `next_allowed_send_at`. On `slow_mode_rejected`, shows toast + restarts countdown using server's value. On WS frame `{type:"system", message:"You are banned"}` or initial 403 close, shows ban banner replacing compose.
**Dependencies:** Task 9
**Mapped Scenarios:** TS-005, TS-003 (steps 4, 7)

**Files:**
- Modify: `src/components/live-chat.tsx`
- Modify: `src/components/__tests__/live-chat.test.tsx`
- Modify: `messages/en.json` (slow-mode countdown copy, ban banner copy)

**Key Decisions / Notes:**
- Use `useEffect` + `setInterval` 1s tick for the visible countdown.
- On `prefers-reduced-motion`, hide the live countdown digits but keep the disabled state.
- Ban-banner persists across reload by checking `streamService.getBans` filtered to current user (separate Task 9 already exposes this).

**Definition of Done:**
- [ ] After send during slow-mode 10s, input disabled for 10s with visible countdown
- [ ] `slow_mode_rejected` event resets countdown using server's `next_allowed_send_at`
- [ ] Ban banner replaces compose row when banned

**Verify:** `pnpm test:run src/components/__tests__/live-chat.test.tsx -t "slow-mode|ban"`

---

### Task 14a: vidra-core — `POST /streams/{id}/chat/system-message` (invoice-mediated, replay-protected)

**Objective:** New mod-or-tip-success-gated REST endpoint that brokers a one-shot system message into the live-chat WS via the now-exported `BroadcastSystemMessage`. Anti-spoof + anti-replay enforced server-side.
**Dependencies:** Task 2 (which exports `BroadcastSystemMessage`)
**Mapped Scenarios:** TS-004

**Files:**
- Modify: `vidra-core/internal/httpapi/handlers/messaging/chat_handlers.go` (add handler `BroadcastTipSystemMessage` + register `r.Post("/system-message", h.BroadcastTipSystemMessage)` inside the existing auth-gated chat group)
- Modify: `vidra-core/internal/domain/payments.go` (or wherever `BTCPayInvoice` lives — add `system_message_broadcast_at TIMESTAMPTZ NULL` column to `btcpay_invoices`)
- Create: `vidra-core/migrations/103_add_invoice_system_message_marker.sql` (single goose file)
- Modify: `vidra-core/internal/repository/btcpay_repository.go` (set/get `system_message_broadcast_at`)
- Create: `vidra-core/internal/httpapi/handlers/messaging/chat_handlers_system_message_test.go`

**Key Decisions / Notes:**
- **Backend trust check (per reviewer F4 & F9):** request shape `POST /api/v1/streams/{streamId}/chat/system-message {invoice_id: string}` (invoice_id not tip_intent_id — the actual concept is BTCPay invoices since `paymentService.createTip` is a ghost; verified `POST /payments/invoices` is the real flow at `routes.go:493`). Server validates:
  1. Invoice exists AND belongs to caller
  2. Invoice status = `Settled`
  3. Invoice's destination channel == this stream's channel
  4. **`invoice.system_message_broadcast_at IS NULL`** — single-use replay protection. On successful broadcast, set the column to NOW(). Repeated POSTs return `409 Conflict`.
- Message template fixed server-side: `"💛 {username} tipped {amount} sat"`. Client cannot inject custom text.
- On successful validation, calls `chatServer.BroadcastSystemMessage(streamID, formatted)` (which Task 2 export makes available).

**Definition of Done:**
- [ ] Migration applies + rolls back cleanly
- [ ] Test: settled invoice for the stream's channel → 200 + system message broadcast
- [ ] Test: invoice not yet settled → 409 with reason "invoice_unsettled"
- [ ] Test: invoice belongs to a different user → 403
- [ ] Test: invoice's channel ≠ stream's channel → 400
- [ ] Test: second POST with same invoice_id → 409 with reason "already_broadcast" (replay protection)

**Verify:** `cd ../vidra-core && go test ./internal/httpapi/handlers/messaging/... -run SystemMessage -v`

---

### Task 14b: vidra-user — `<StreamTipSheet>` inline composer

**Objective:** New component `<StreamTipSheet>` slides up below the chat compose row. Reuses `<TipModalContent>` from Task 11. On `onSuccess(invoiceId)`, calls `streamService.broadcastTipSystemMessage(streamId, invoiceId)` — backend (Task 14a) handles the broadcast.
**Dependencies:** Task 11, Task 14a
**Mapped Scenarios:** TS-004

**Files:**
- Create: `src/components/stream-tip-sheet.tsx`
- Modify: `src/components/live-chat.tsx` (add tip button + sheet)
- Modify: `src/lib/api/services/streams.ts` (`broadcastTipSystemMessage(streamId, invoiceId)` → `POST /streams/{id}/chat/system-message {invoice_id}`)
- Modify: `src/lib/api/services/__tests__/streams.test.ts`
- Create: `src/components/__tests__/stream-tip-sheet.test.tsx`
- Modify: `messages/en.json` (tip-related strings)

**Key Decisions / Notes:**
- **TipModalContent (Task 11) flow:** `paymentService.createInvoice({channelId, amount, method})` → poll `getInvoice` until `Settled` → call `onSuccess(invoiceId)`. This is the existing flow already used by `<TipModal>`.
- Sheet uses `framer-motion` if already in deps (else CSS keyframes). Respects `prefers-reduced-motion` (no slide animation, just appear).
- Sheet slides up over the input on mobile, sits beside on desktop.
- Touch targets ≥ 44×44px on preset chips and Send button (Apple HIG).

**Definition of Done:**
- [ ] Tip button visible in chat compose row when stream is live
- [ ] Click → sheet opens with TipModalContent
- [ ] Successful invoice settlement → `broadcastTipSystemMessage(streamId, invoiceId)` called exactly once
- [ ] All viewers see "💛 Alice tipped 1000 sat" within 1s (E2E)
- [ ] `prefers-reduced-motion` honored (no slide animation)

**Verify:** `pnpm test:run src/components/__tests__/stream-tip-sheet.test.tsx`

---

### Task 15: vidra-user — i18n keys for all new strings (13 locales)

**Objective:** All new UI strings added in Tasks 7, 10, 11, 13, 14b land in `en.json` and the 12 other locales. Run `pnpm i18n:check` to verify parity. Use existing translation pattern (placeholders `{count}`, `{duration}`, etc.).
**Dependencies:** Tasks 7, 10, 13, 14b
**Mapped Scenarios:** All

**Files:**
- Modify: `messages/en.json`
- Modify: `messages/{es,fr,de,ja,zh,ko,pt,ru,ar,it,pl,nl}.json` (12 files at REPO ROOT, not under src/)

**Key Decisions / Notes:**
- Translation source for non-en: use existing in-codebase patterns; if a string is technical (e.g. "Encrypted (X25519)"), keep it in English with a localized prefix.
- Placeholders: `{seconds}`, `{username}`, `{amountSat}`, `{minutes}` — never concat strings.

**Definition of Done:**
- [ ] `pnpm i18n:check` returns 0
- [ ] No console warnings about missing keys when running `pnpm dev` and visiting `/messages` and a stream watch page
- [ ] Smoke-render in es and ja locales (Playwright snapshot)

**Verify:** `pnpm i18n:check && pnpm test:run`

---

### Task 16: vidra-user — Playwright E2E (TS-001..TS-006)

**Objective:** Author the 6 scenarios from §E2E Test Scenarios as Playwright specs. Use `test.describe.serial` where 2-browser-context state matters. Cookies imported via `setup-browser-cookies` for the test users.
**Dependencies:** Tasks 1–14
**Mapped Scenarios:** TS-001..TS-006

**Files:**
- Create: `e2e/messaging-realtime.spec.ts` (TS-001)
- Create: `e2e/messaging-encryption.spec.ts` (TS-002)
- Create: `e2e/live-chat-moderation.spec.ts` (TS-003, TS-005)
- Create: `e2e/live-chat-tip.spec.ts` (TS-004)
- Create: `e2e/live-chat-contract.spec.ts` (TS-006)
- Modify: `e2e/fixtures/users.ts` (add Alice/Bob/Carol fixtures + Alice-as-moderator helper)
- Modify: `e2e/global-setup.ts` (seed live stream for chat tests via API)

**Key Decisions / Notes:**
- Tests run against `pnpm dev:full` (vidra-core docker + frontend).
- Stream creation uses `streamService.create` + manual `update status=live` via test helper.
- For TS-002 step 6 (key change), use `page.evaluate(() => indexedDB.deleteDatabase(...))` to simulate identity rotation.

**Definition of Done:**
- [ ] All 5 spec files green
- [ ] `pnpm test:e2e -g "messaging|live-chat"` < 5 min total

**Verify:** `pnpm test:e2e -g "messaging|live-chat"`

---

## PeerTube Parity Check

C13–C15 are **vidra-specific extensions**, not PeerTube parity rows. PeerTube has no DM, no E2EE, no creator tip composer in chat. Live-chat moderation parity (ban / timeout / delete) loosely mirrors PeerTube plugin `peertube-plugin-livechat`'s feature set, but the implementation is independent (Vidra uses its own chat hub on a Go backend; PeerTube delegates to a Prosody XMPP server). This phase explicitly extends beyond PeerTube parity.

## Vidra-Specific / Requested Features

This entire plan implements vidra-specific extensions:
- **Direct Messaging** — wires the existing UI against `/api/v1/messages/*` and the new `/messages/ws`. Backend extension impacted: Direct Messaging (with new realtime sub-component).
- **Real-time Stream Chat** — fixes broken WS contract; adds slow-mode primitive. Backend extension impacted: Real-time Stream Chat.
- **Bitcoin Payments (Lightning + BTCPay)** — reused via inline tip composer; new `POST /chat/system-message` mediated by tip success. Backend extension impacted: Bitcoin Payments + Real-time Stream Chat.

Backend extensions impacted by this plan: **Direct Messaging, Real-time Stream Chat, Bitcoin Payments**.

## Verification Plan

- **Per-task:** Vitest / Go test runs as listed in each task's Verify line.
- **Phase-wide:**
  - `pnpm typecheck` clean (vidra-user)
  - `pnpm lint` clean (vidra-user)
  - `pnpm test:run` 100% pass (vidra-user)
  - `pnpm i18n:check` 0 mismatches
  - `pnpm build:size-check` passes (libsodium import does not push `/messages` route bundle delta over 250 KB; baseline committed)
  - `pnpm test:e2e -g "messaging|live-chat"` all green
  - `cd ../vidra-core && go build ./...` clean
  - `cd ../vidra-core && go test ./...` 100% pass
  - Browser walkthrough of TS-001..TS-006 against `pnpm dev:full` with two real Chromium contexts.

- **Cross-repo deploy ordering (per reviewer S5):** vidra-core PR (Tasks 0, 1, 2, 3, 14a) MUST land + deploy to dev before vidra-user PR is merged. Frontend tasks 8/9/10/13/14b will fail E2E against an un-deployed backend. Plan-implement workflow: backend tasks first (in order 0 → 1 → 2 → 3 → 14a), then `cd ../vidra-core && git push && wait for dev deploy`, then frontend tasks.
- **Final exit:** Manual two-context QA in Chrome with the canonical user stories: V-18 (DM with E2EE) and V-19 (chat with moderation in effect, including slow-mode + tip), confirmed via screenshots attached to the verify report.

## Spec-Review Cycle 1 — Findings Incorporated

All 9 must_fix items resolved in this revision:
- **F1** — i18n path corrected to `messages/<locale>.json` (repo root) across all task file lists.
- **F2** — Backend file paths corrected: `internal/usecase/message/ws_server.go` (hub), `internal/httpapi/handlers/messaging/messages_ws_handlers.go` (HTTP entry), with explicit dependency-wiring caveat.
- **F3** — Migration switched to single goose file `102_add_slow_mode_seconds_to_live_streams.sql` (and `103_add_invoice_system_message_marker.sql`).
- **F4** — Tip flow uses real `paymentService.createInvoice` + new `broadcastTipSystemMessage` endpoint keyed on `invoice_id` (not the ghost `createTip`).
- **F5** — Task 2 explicitly exports `BroadcastSystemMessage` so Task 14a can call it.
- **F6** — Slow-mode janitor goroutine added with explicit ticker + sweep + ctx cancellation + leak test.
- **F7** — New Task 0 introduces `WSAuth` middleware (subprotocol + query-param JWT extraction); chat WS is migrated to use it.
- **F8** — Hub envelope divergence documented (chat = flat broadcast, messages = enveloped point-to-point) with guard tests in both directions.
- **F9** — `system_message_broadcast_at` column on `btcpay_invoices` provides single-use replay protection.

Should-fix items S1–S7 incorporated inline (key-rotation explicit reject path, dual-shape decrypt order, bundle-size DoD, deterministic optimistic reconciliation via `client_message_id`, cross-repo deploy ordering, Task 14 split into 14a/14b, ConversationList extraction).

Suggestions G1, G2, G3, G4, G5 incorporated (fuzz test, deterministic E2E for key-exchange, Prometheus metrics, libsodium-wrappers non-sumo, unban list).

## Open Questions

- None at planning time. All architectural decisions resolved via Batch 2 questions and Cycle 1 reviewer findings.
