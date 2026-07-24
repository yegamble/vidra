# Vidra Platform Audit — vs PeerTube v7.3 and YouTube (2026-07-24)

Method: three parallel research tracks — (1) code-verified inventory of vidra-core / vidra-user / vidra-search (file-level evidence, internal ledgers cross-checked against code), (2) PeerTube v6→v7.3 feature audit from primary sources, (3) YouTube user-facing functionality audit (2025–26 state) with published UX-research ranking. Synthesized into the gap matrix and prioritized plan below.

## 1. What works — verified, end-to-end

Backend + UI + backed e2e proof unless noted:

- **Accounts/auth**: register/login/rotating-refresh with reuse detection, TOTP 2FA + recovery codes, password reset, email verify, reversible deactivate + anonymizing delete, account export/import (JSON). *Matches or beats PeerTube's account story; export answers their portability differentiator.*
- **Upload → publish**: resumable/chunked upload, SSRF-guarded URL import (yt-dlp), per-user quota, opt-in ClamAV (fail-closed), HLS ladder + WebM alternate + storyboards + chapters (backend), publish-after-transcode, **Whisper auto-captions** (PeerTube's v6.2 flagship — we have it).
- **Watch interactions**: single-level threaded comments, ratings, save/watch-later, watch history + resume + Continue-watching (≥5s, <95% finished threshold), report flow.
- **Playlists**: CRUD, reorder, thumbnails, privacy.
- **Search (vidra-search)**: hybrid full-text + trigram + prefix suggest, decayed trending, co-visitation related/home rails, per-user history/purge, LightGBM ranker in shadow mode. *Deeper than PeerTube's local search.*
- **Live (basics)**: RTMP(S) ingest → privacy-gated HLS → replay-to-VOD, hashed stream keys.
- **Messaging**: 1:1 DMs with attachments (ClamAV, allowlists), link previews, read receipts — plus **client-side Olm E2EE with disappearing messages**. *Neither PeerTube nor YouTube has an answer.*
- **IPFS dual-tier mirror** (public pin tier + swarm-keyed private tier), fail-closed privacy. *Unique.*
- **Moderation/admin**: reports pipeline, quarantine, watched-words + auto-match, account/instance mutes, audit log, jobs dashboard (SSE), registration approval, ~108-key runtime settings overlay, admin homepage/branding documents, **admin featured banner** (2026-07-23).
- **Migration on-ramps**: one-way PeerTube importer (accounts/channels/videos/comments/playlists/subs); channel-sync code exists (ledger row stale — see §5 gotchas).
- **Home/discover** (2026-07-23): YouTube-style uniform grid, Continue Watching semantics, admin featured banner, zero-CLS loading.

## 2. Design decisions that are working — keep them

| Decision | Why it's right |
|---|---|
| Polling DMs, no WebSockets (documented INTENTIONAL_DIFFERENCE) | Removes a whole ops class; revisit only when live chat forces a realtime layer |
| No plugin/theme marketplace | PeerTube's ecosystem is its moat but also its security/compat tax; settings-overlay + documents cover the 80% |
| Non-custodial wallet display only | Monetization deferred without becoming a payments processor |
| Env-default + DB-overlay settings with typed kinds | Made the featured banner a 6-key drop-in; every future admin feature is cheap |
| IPFS as mirror, never authoritative (rejected `STORAGE_BACKEND=ipfs`) | Keeps privacy fail-closed and the serving path boring |
| Contract-first OpenAPI + generated frontend client + drift CI | The two-repo split stays honest |
| Search as a separate HMAC-only service with circuit-breaker fallback | Search can evolve/fail without taking core down |

## 3. Gap matrix (vidra vs the ranked external lists)

Against **PeerTube's 12 capabilities a competitor must answer** (research ranking):

| # | PeerTube capability | Vidra status |
|---|---|---|
| 1 | Remote transcoding runners | ❌ single-tier — *Later (architectural)* |
| 2 | ActivityPub federation depth | ⚠️ fully coded, **off by default, integration-unproven** — *Next: proving harness* |
| 3 | Whisper auto-transcription | ✅ shipped |
| 4 | Granular NSFW (Display/Warn/Blur/Hide + reasons + tag rules) | ⚠️ binary blur/warn + restricted mode — *Next* |
| 5 | Account export/import portability | ✅ shipped (JSON archive) |
| 6 | Web Studio editor (cut/intro/outro/watermark) | ❌ — *Later* |
| 7 | Channel sync from YouTube | ⚠️ code + endpoints + specs exist; ledger stale; needs runtime verification — *Next* |
| 8 | Live maturity (scheduling, latency modes, permanent lives) | ⚠️ ingest/replay only — *Next tier with live chat* |
| 9 | Password-protected + granular visibility | ✅ shipped (HMAC unlock tokens) |
| 10 | Plugin/theme + external auth (LDAP/OAuth/OIDC) | ⚠️ OAuth/OIDC + ATProto login exist; no LDAP; plugins intentionally out |
| 11 | Admin config surface + onboarding wizard | ✅ overlay shipped; ❌ wizard — *Later, low* |
| 12 | Embeds + oEmbed + RSS/Podcast + sitemap | ⚠️ embeds ✅ (privacy-aware); **oEmbed ❌, RSS ❌, sitemap ❌ — THIS SESSION** |

Against **YouTube's 15 capabilities that make a clone feel complete** (research ranking):

| # | YouTube capability | Vidra status |
|---|---|---|
| 1 | Autoplay-next + up-next queue | ⚠️ endcard + Add-to-queue exist (frontend, mocked tests) — *Next: verify + finish + persist toggle* |
| 2 | Subscriptions feed + bell modes | ⚠️ feed ✅; per-channel bell modes ❌ — *Next* |
| 3 | Threaded comments UX | ✅ (single-level threads, sort; hearts/pinning ❌ — *Next, S*) |
| 4 | Captions + auto-captions | ✅ (translation ❌ — *Later*) |
| 5 | Chapters + timestamp deep links | ⚠️ chapters backend ✅, `?t=` ✅; **share-at-timestamp UI + clickable comment/description timestamps — THIS SESSION** |
| 6 | Playlists + Watch Later | ✅ (collaboration ❌ — *Later*) |
| 7 | History + resume | ✅ shipped (incl. finished-threshold, 2026-07) |
| 8 | Search filters + autocomplete | ✅ shipped |
| 9 | Creator analytics + retention curve | ⚠️ totals + 30-day sparkline only — *Next tier (needs watch-position beacon)* |
| 10 | Channel pages (tabs/trailer/handles) | ✅ mostly (trailer/featured-video ❌ — *Next, S*) |
| 11 | Player UX bundle (speed/theater/shortcuts/PiP) | ✅ frontend (persistence partial) |
| 12 | Comment moderation (held-for-review, blocked words) | ⚠️ admin watched-words ✅; creator-level held-queue ❌ — *Next* |
| 13 | Share-timestamp + oEmbed + RSS + not-interested | ⚠️→ **plumbing trio THIS SESSION**; not-interested ❌ — *Next* |
| 14 | Most-replayed heatmap | ❌ — *Later (needs aggregated position data)* |
| 15 | Premieres + live chat + tipping | ❌ live chat — *Next tier decision (SSE v1?)*; tipping deferred |

**Structural gaps neither list captures** (from the code inventory's top-10): no i18n at all (hard-coded English), no PWA/manifest/favicon, no off-site notifications (web-push/email digests), no realtime layer anywhere, federation unproven.

## 4. Prioritized plan

**THIS SESSION (implemented + pushed to main — see §6):**
1. **Distribution plumbing**: RSS feeds (instance + per-channel), oEmbed endpoint + discovery links, sitemap. Highest leverage-per-line in both external rankings; pure add, zero collision.
2. **PWA/branding floor**: favicon set + web manifest + installability + theme-color. Fixes an embarrassing verified gap (`public/` had an SVG and a wasm blob).
3. **Timestamp affordances**: share-at-current-time on watch page; clickable `mm:ss` timestamps in comments and descriptions (seek, `?t=` links).

**NEXT (1–2 sessions each, in value order):**
1. Federation proving harness (compose fake-remote + inbound/outbound e2e) — turns "coded" into "true"; flip default after proof.
2. Per-channel notification bell modes + web-push (needs the VAPID/service-worker decision — PWA floor from this session unblocks it) + email digests.
3. Creator analytics v2: watch-position beacon → watch-time + retention curve (also feeds most-replayed later).
4. Live chat v1 (SSE, reuse jobs-stream plumbing; polling fallback) + live scheduling surface.
5. Granular NSFW: adopt PeerTube's four-mode viewer policy + creator content-warning reasons.
6. Comment tools: creator held-for-review queue, pinned/hearted comments; "not interested" feedback on rails.
7. Channel-sync runtime verification + UI polish; channel trailer/featured video.
8. i18n foundation (next-intl + extraction); start with locale scaffolding, translate incrementally.
9. Autoplay-next completion: verify endcard, add persisted toggle + up-next list.

**LATER (architectural):** remote transcode runners (biggest PeerTube envy; design as pull-workers reusing the jobs framework), web studio editor, most-replayed heatmap, caption translation, playlist collaboration, monetization (per existing deferral).

**KEEP REJECTED (existing product decisions, reaffirmed by this audit):** torrent import, plugin marketplace, custodial payments, IPFS-as-authoritative storage.

## 5. Gotchas for whoever picks up the backlog

- `.ralph/specs/backport/FEATURE_VISION.md` is badly stale — it calls shipped features broken. Trust `peertube-feature-ledger.md` + code; ignore FEATURE_VISION for current state.
- `federation.md` header still says "no code yet" — false; `internal/federation/` is complete but `FEDERATION_ENABLED` defaults false and the frontend remote surface is mock-only.
- Ledger marks channel-sync DEFERRED but `internal/channelsync` + `/channel-syncs/*` + migration 0081 + specs exist — reconcile before building "again".
- The ML search ranker ships in shadow mode; live ranking is heuristic until an operator runs `make activate-model`.
- Scale facts (verified 2026-07-24): 209 OpenAPI paths, 98 migrations / ~84 tables, ~108 settings keys, 90 mocked + 70 backed e2e specs.

## 6. This session's implementation record

Landed to `main` on both repos (2026-07-24), verified by a fresh-eyes adversarial pass (XML-injection/escaping, oEmbed URL-validation bypass, privacy leaks, tokenizer XSS/ReDoS, icon/manifest correctness) with all gates green:

- **vidra-core** `1e98917` — *Merge feat/distribution-plumbing: RSS feeds, oEmbed, sitemap.* Three root-mounted public endpoints (`/feeds/videos.xml[?channel=]`, `/services/oembed`, `/sitemap.xml`), mounted only when `PUBLIC_BASE_URL` is set; public+published+local videos only; `encoding/xml` structs throughout; `make ci` green.
- **vidra-user** `a469744` — *Merge feat/pwa-timestamps: PWA/branding floor, clickable timestamps, feed/oembed discovery.* Web manifest + generated icon set (favicon/192/512/maskable/apple-touch) + theme-color; safe React-level timestamp tokenizer (no `dangerouslySetInnerHTML`) seeking the player in comments/description; share-at-time coverage; RSS/oEmbed `<link rel=alternate>` discovery; tsc/vitest/lint/build + targeted e2e green.
