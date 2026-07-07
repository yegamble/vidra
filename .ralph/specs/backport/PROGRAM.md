# Backport Program — mining `vidra-core-bk` / `vidra-user-bk` into the clean-room repos

**Status:** ACTIVE — W0 wired 2026-07-07 (root gate + `vidra-user` fix_plan W0.1–W0.13);
W1–W7 pending, wire one wave at a time (see §5–§6)
**Sources:** https://github.com/yegamble/vidra-core-bk, https://github.com/yegamble/vidra-user-bk (archived 2026)
**Local reference copies:** this directory (`FEATURE_VISION.md`, `API-DEVIATIONS.md`, `plans/`, `api-reference/`)

## 1. Principle: port contracts and ideas, NOT code

The backups were archived because the project got messy. Their own post-mortem audits
(`plans/2026-04-28-feature-wiring-audit-runtime-gaps.md`, `...-part2.md`) show the failure
mode: **UI-first features whose backend wiring was broken, shape-mismatched, or stubbed.**
The current repos are a clean-room rewrite with different architecture (sqlc vs sqlx,
different package layout, different frontend structure). Therefore:

- ✅ Mine: OpenAPI contracts (`api-reference/*.yaml`), DB schema ideas (migration files as
  reference), feature definitions (`FEATURE_VISION.md`, 149 IDs), test scenarios, compose
  topology for BTCPay/LND/IPFS/ClamAV, phase plan documents.
- ❌ Do not copy: Go/TS source. Re-implement in current conventions with current gates.
- Every backported endpoint goes through the existing route↔spec drift guard
  (`vidra-core/api/openapi.yaml` + `TestOpenAPIContract`) — the old spec files here are
  *reference*, never served.

## 2. What the backups have that the current repos lack (gap map)

Feature IDs refer to `FEATURE_VISION.md`. Already-shipped areas (auth/TOTP/OAuth login,
channels, playlists, comments, moderation suite, AP federation, e2ee messaging, donations
addresses, PeerTube import, captions, quota, S3, transcoding/HLS, notifications) are NOT
listed — do not re-port them.

**Backend (`vidra-core`):**
- Payments stack: BTCPay on-chain + Lightning (LND), invoices, tips, wallet/ledger,
  balance worker + cooldowns, payouts, Polar checkout (PAY-01…07, PAY-09, PAY-11)
- Inner Circle memberships: tiers, badges, content gating (PAY-08) + Premium (PAY-10)
- Analytics: per-video retention curves, channel/stream analytics aggregation (ANALY-01…05)
- Live completion: RTMP ingest, live chat WS hub + slow mode + tips-in-chat, chat
  moderation, scheduling, permanent live + replay/VOD conversion (LIVE-01…08)
- Upload/import: chunked resumable upload, drafts, schedule publication, batch, yt-dlp
  URL/torrent import, channel auto-sync, ClamAV scan (UPLOAD-02/03/07/09/10/12/13)
- Player-adjacent: chapters, storyboards, video passwords, embed privacy, per-user player
  settings (CORE-15/16/17, PLAY-07)
- P2P/decentralization: IPFS hybrid storage, WebTorrent, magnet/trackers/DHT, redundancy
  (cross-instance replication), backup endpoints (P2P-01…04, STOR-04/05)
- Platform: plugin system (hooks, Ed25519 signatures, marketplace), themes, remote
  transcoding runners, OAuth2 provider apps, auto-tag policies, oEmbed/RSS
  (PLUG-01…03, ADMIN-07, USER-15, MOD-04, FED-09)

**Frontend (`vidra-user`):**
- i18n: next-intl, 13 locales, `[locale]` routing (UX-03)
- Money UX: `/settings/wallet`, `/settings/transactions`, `/premium`, `/studio/wallet`,
  `/studio/inner-circle`, tip flows on watch/comments, admin payments + payouts
- Studio/analytics dashboards: channel + per-video analytics with retention curve
- Player UX: theater mode, PiP, speed 0.25–4×, keyboard shortcuts, autoplay-next end
  card, storyboard hover previews, chapter markers (PLAY-03/04/05/08/09)
- Upload UX: resumable with progress, draft recovery, thumbnail frame-pick, schedule,
  batch (UPLOAD-01…10 UI)
- Discovery: `/discover`, `/category/[name]`, richer `/library/[section]`
- Admin: plugins, runners, roles, logs viewer, federation UI, branding/custom CSS editor
- Embed playlist player + embed privacy/password UX

## 3. Wave plan (one wave = one Ralph engagement)

Ordered by user priority (design first), dependency, and loop convergence (small phases).

| Wave | Scope (feature IDs) | Size | Notes |
|------|--------------------|------|-------|
| **W0 Design/template parity** | UX-12 + `W0-DESIGN-AUDIT.md` | M | Token migration is already 100% done (audited 2026-07-07). W0 = screen-by-screen visual parity with the canonical templates `vidra-user/.ralph/specs/design/{app,desktop}-template.jpeg` |
| **W1 Watch & player** | CORE-15/16/17, PLAY-03/04/05/07/08/09 | M | Pure product polish, no new infra, high visibility |
| **W2 Upload & import** | UPLOAD-02/03/07/09/10/12/13 + UI | L | yt-dlp import is the marquee feature; ClamAV needs compose service |
| **W3 Analytics** | ANALY-01…05 + studio dashboards | M | View-event aggregation first, then retention curves |
| **W4 Live completion** | LIVE-01…08 | L | RTMP ingest + WS chat hub; reuse current HLS serving; unblocks "live media server" long pole |
| **W5 Payments & memberships** | PAY-01…11 | XL | ⚠️ Currently "Optional / out of scope" in root fix_plan — wiring this wave is an explicit scope decision. BTCPay+LND compose reference in `plans/2026-04-24…8b…` docs |
| **W6 Decentralization** | P2P-01…04, STOR-04/05, ADMIN-07 | XL | IPFS/WebTorrent hybrid, redundancy, runners |
| **W7 Extensibility & i18n** | PLUG-01…03, USER-15, UX-03, ADMIN-16 | L | Plugins need a security review gate (Ed25519 signing model from backup) |

## 4. Completeness contract (the anti-half-baked rules)

Every wave's fix_plan tasks MUST carry these, so a Ralph loop cannot tick a box on a stub:

1. **Vertical slices only.** One loop iteration ships backend + frontend + tests for one
   feature ID. Never merge a UI that talks to a non-existent endpoint; never merge an
   endpoint with no consumer or e2e. (This is precisely how the backup died.)
2. **Contract first.** Update `vidra-core/api/openapi.yaml` in the same slice; the drift
   guard and `openapi` workflow stay green.
3. **Evidence integrity rule** (adopted from the backup's own audits): a checkbox flips
   only with (a) unit/service tests, (b) a Playwright e2e, and (c) for data-mutating
   flows, a backend-backed e2e proving the DB row changed AND the UI shows it after
   refetch (already a root-gate requirement).
4. **1:1 traceability.** fix_plan checkboxes are labeled with FEATURE_VISION IDs, so
   "done" is auditable against this program.
5. **Design guardrail.** No new/edited screen may use non-token colors or off-system
   components; templates in `vidra-user/.ralph/specs/design/` are canonical. (Guardrail
   already in the orchestrator PROMPT since b7584df — extend it to cite the templates.)
6. **Canonical gates.** `make ci` / `npm run ci` green locally AND on branch CI before a
   phase box ticks. True deferrals go under an `## Optional / Deferred / Non-Blocking`
   heading (respected by `OPTIONAL_SECTIONS` in `.ralphrc`).

## 5. Ralph execution mechanics

- Run from the monorepo root (`ralph` → root orchestrator). `.ralphrc` already pins
  `CLAUDE_MODEL="opus"`, `CLAUDE_EFFORT="xhigh"`, 2M tokens/hour governor — no changes needed.
- **Wire exactly one wave at a time** into the subdirectory `fix_plan.md` files (+ one
  phase line in the root gate). Multiple open waves = the convergence failures seen
  before. A wave's spec lives at `vidra-<core|user>/.ralph/specs/backport-w<N>-<name>.md`.
- Per-wave seeding procedure (a normal Claude session, not the loop):
  1. Write the wave spec(s) from this program + the relevant `plans/*.md` +
     `api-reference/*.yaml`.
  2. Append the wave's tasks (with feature IDs + completeness contract) to
     `vidra-core/.ralph/fix_plan.md` and/or `vidra-user/.ralph/fix_plan.md`.
  3. Add one `- [ ] W<N> — <name>` line to each project section of root
     `.ralph/fix_plan.md`.
  4. Launch/resume the loop; monitor with `ralph_monitor.sh` / `.ralph/status.json`.
- Never edit fix_plans while a loop is executing (check `.ralph/status.json` +
  `ps aux | grep ralph_loop`).

## 6. Suggested root fix_plan lines (paste when wiring a wave)

```
## Backport programme (specs/backport/PROGRAM.md) — phase gate
- [ ] W0 — Design completion to Apple-HIG token system (vidra-user)
- [ ] W1 — Watch & player backports (both projects)
- [ ] W2 — Upload & import pipeline (both projects)
- [ ] W3 — Analytics (both projects)
- [ ] W4 — Live streaming completion (both projects)
- [ ] W5 — Payments & memberships (both projects; scope decision recorded <date>)
- [ ] W6 — Decentralization: IPFS/WebTorrent/redundancy/runners (vidra-core-led)
- [ ] W7 — Extensibility & i18n (both projects)
```

## 7. W0 design audit findings (current `vidra-user`)

See `W0-DESIGN-AUDIT.md`. Key result: the token system is fully adopted (zero legacy
color utilities anywhere) — so W0 is a **visual/layout parity pass against the two
template JPEGs**, one task per feature area, each requiring before/after screenshots
(light+dark, mobile+desktop) and a green token-grep guard as acceptance.
