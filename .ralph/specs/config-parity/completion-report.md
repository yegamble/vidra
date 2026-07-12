# PeerTube Admin-Config Parity — Completion Report (W0–W15)

**Date:** 2026-07-12 · **Program docs:** `.ralph/specs/config-parity/{waves.md, ledger.md, instance-contract.md, gap-matrix.json}`
**Audited tips:** vidra-core `main @ 74cecb1` · vidra-user `main @ 3d03c23`
**Baseline:** 105 PeerTube settings assessed (gap-matrix, 2026-07-11); registry grew from 37 to 92 admin-mutable keys across 7 canonical admin pages.

---

## 1. Program scoreboard

| Wave | Scope | Commits | Audit result |
|---|---|---|---|
| W0 | Parity ledger & deviation record (N/A / deferred / env-only / equivalence, 40+ PT keys) | meta-repo `41be49d` (+ `3675b18` gap matrix & wave plan) | ledger evidence re-verified; line-number drift recorded (§6) |
| W1 | Core config surface: /instance additive blocks + ETag/s-maxage, instance_documents store, instance asset store + admin endpoints, registry page/section metadata | `b062f0d` (vidra-core) | verified (part of 9/10 foundations items) |
| W2 | Admin multi-page IA + HIG patterns, `lib/instance-config.server.ts` SSR fetch, layout.tsx seams | `a464b5f` (vidra-user) | verified; 1 low finding (layout.tsx "never this file" invariant, see §3.5) |
| W3 | Broadcast banner end-to-end (enabled/message/level/dismissable, hash-keyed dismissal) | `8f80811` | 6/6 verified, clean |
| W4 | Branding assets (avatar/banner/4 logos), generateMetadata favicon/og, header_hide_instance_name, twitter:site | `a2965c6` + `945f887` | 6/6 verified, clean (watch-page og precedence closed by W15) |
| W5 | Browse/landing/theme/player defaults, miniature display-name | `139a42e` + `9cb1a4d` (autoplay hold-until-settle fix) | 8/8 verified; `login_redirect_single_oauth` NOT built — now ledgered as deferred (§5) |
| W6 | Homepage document, custom CSS/JS with security posture, primary color + WCAG guard, email prefix/signature | `fdd02d6` | 5/6 verified; optional `CUSTOM_JS_ALLOWED` kill-switch not built — recorded as-built deviation (§4) |
| W7 | Signup: email-verification gate, user limit, minimum age, daily quota, new-user history | `a2d7193` + `13d5e23` | 6/6 verified, clean |
| W8 | Shipped-feature toggle batch (import_http, channel_sync ×2, storyboards, transcription, user import/export ×4, max_channels_per_user) | `8fcf50c` | 9/9 verified, clean (gate is the `storyboardGate` seam at video/service.go:918/:826, not media/storyboard.go — citation corrected) |
| W9 | Publish defaults + per-video comment/download policies | `7b556d5` + `d2b8cd9` (privacy default=private) + `0583850` | 12/12 verified, clean; `requires_approval` deferral held |
| W10 | Transcoding runtime knobs: master toggle, parameterized ladder, fps/threads, shared bounded worker pool, extra extensions | `8cb784b` | 9/10; **1 medium finding**: ladder not editable in admin UI (§3.1) |
| W11 | Live enforcement knobs: replay gates, instance/user caps at RTMP callback, duration watchdog; no dormant live.transcoding keys | `41f0941` | 6/6 verified; force-close is server-side state flip, not RTMP socket drop — as-built deviation recorded (§4) |
| W12 | Federation policy gates at the inbox seam + follower-approval queue + auto-follow-back | `2971f19` | 5/6; **1 medium finding**: no AP/ATProto per-key labels in admin UI (§3.2) |
| W13 | Remote-URI search (users on / anonymous off), SSRF-guarded, rate-limited, non-blocking | `b1cb824` + `2e50f1d` | 11/11 verified, clean |
| W14 | Video file replacement: source-version model, replace + replace-session endpoints, re-transcode via W10 pipeline, mediagc, owner-charged quota, `video_replace_enabled` | `74cecb1` (core) + `3d03c23` (user, incl. StudioView prefill-race fix) | 12/12 verified, clean; as-built docs backfilled at close (§6) |
| W15 | Reconciliation: follower-approval admin queue UI, watch-page SSR metadata (og:image thumbnail→opengraph-logo precedence) | `b216134` (vidra-user) | verified; closes W12 "pending frontend slice" and the W4 watch-metadata item |

**Registry integrity:** all 92 keys carry server page+section metadata and place on exactly one of the 7 admin pages; no orphans, no dead META keys, "Other settings" fallback present. Conventions held program-wide: 0=unlimited, null-PATCH clears override, provider-func seams, workers gated at enqueue/pickup (never construction), every wave shipped behind `make ci` / `npm run ci`.

---

## 2. Audit methodology & outcome

- **Exhaustive completion audit** across 15 areas at the tips above: **118 items verified** against code with line-level evidence (registry kind/default/validator, enforcement point, /instance exposure, admin-UI surface, test coverage) — not against docs.
- **Adversarial verification:** every candidate discrepancy was independently challenged by **3 refuters** (grounds: code-handles-it / ledgered-deferred / evidence-misread). 10 raw area-level flags consolidated to **6 upheld findings** (5 upheld 3/3, 1 upheld 2/3), which dedup to **5 distinct issues** (the transcoding-ladder control surfaced in two areas).
- **Ledger/contract accuracy:** 8/8 spot-checks verified (deferrals real, N/A rationales still hold, endpoint paths match the router, /instance shapes match the contract). The ledger's own evidence line numbers had drifted at the W14 tip — refreshed at close (§6).
- **Severity split:** 0 high, 4 medium, 1–2 low. **No backend enforcement, validation, or contract defect survived verification.** Every confirmed issue lives in the vidra-user admin-config presentation layer or in documentation.

---

## 3. Confirmed residual issues

| # | Issue | Severity | Disposition |
|---|---|---|---|
| 3.1 | **`transcoding_resolutions` is not editable in the admin UI.** The only KindList key without META falls to the generic text control, which blanks the array value and emits a string the server's `validateTranscodingResolutions` rejects (422). W10's "admin-tunable ladder" is unmet on `/admin/config` (API PATCH works). The only functional defect in the program. | medium | **FIXED** — `6d048af` (generic `list` ControlKind + rung validation; any future KindList key now editable) |
| 3.2 | **W12 federation gate keys carry no AP-vs-ATProto label** — an explicit W12 acceptance rule (waves.md:22/:231/:242, ledger §11). The four keys have no META, `ProtocolBadge` is never imported by the config view, and the client `policy` section whose blurb promises the labels never renders. Enforcement itself is fully correct. | medium | **FIXED** — `6d048af` (ProtocolBadge on the four AP inbox gates; ActivityPub-only, verified against inbox.go) |
| 3.3 | **Client PAGE_SECTIONS ids diverge from the authoritative server section ids** (live→streaming/replay/limits, federation→comments/followers/search, advanced data→user-data, general contact/channels/about). Six curated SectionDefs are dead code; keys render in auto-titled sections with empty descriptions. Nothing hidden (auto-render invariant held). | medium | **FIXED** — `6d048af` (PAGE_SECTIONS mirrors server ids exactly; 7 dead defs removed; MIRROR RULE documented) |
| 3.4 | **29 shipped W8–W13 keys have no META entry**: raw snake_case labels, no help/bootDep/inline validators, no progressive disclosure. Functional (bool→toggle, int→number fallbacks work; server validates everything) but below the program's HIG bar. Upheld 2/3 — one refuter classed it polish, not defect. | medium (polish) | **FIXED** — `6d048af` (META now 1:1 with all 92 registry keys; transitive progressive disclosure) |
| 3.5 | **layout.tsx "never this file" invariant literally contradicted**: W4 (`a2965c6`) made a sanctioned 2-line wiring edit (`<Header instance={instance} />`). Seam design held in substance; the comment and waves.md:85 overstate it. | low | **FIXED** — `6d048af` (comment softened) + ledgered exception |

Plus two stale in-code doc notes (lib/layout-metadata.ts W4 deviation note superseded by W15; admin-config-ia.test.ts placement test doesn't exercise the full 92-key server snapshot) — both also fixed in `6d048af` (note updated; placement test now runs a hand-verified full 92-key server fixture).

---

## 4. Recorded deviations (as-built, deliberate)

All entered or re-confirmed in `ledger.md`:

- `default_video_privacy` defaults **private** (not PT's public) — omit-means-private was shipped behavior (`d2b8cd9`).
- `default_player_autoplay` seeds BOTH start-on-open and autoplay-next; never overrides per-user prefs.
- Feed sort is a 3-way enum (recent|popular|trending) vs PT's 7.
- Per-video comment policy is `enabled|disabled` only — `requires_approval` deferred (no approval queue in v1).
- Vidra ALWAYS keeps + progressively serves the original file (inverts `original_file.keep`; substitutes for `web_videos`).
- `transcoding_enabled` IS the HLS toggle (HLS is the only ABR format).
- **W10:** `transcoding_max_fps` applies uniformly to all rungs (not per-rung) and only when the KNOWN source fps exceeds the cap (`media/hls.go:73-77`).
- **W11:** `live_max_duration_secs` force-close is a server-side state flip (stops HLS serving + delists immediately); no nginx-rtmp socket-drop endpoint exists — the publisher's ingest socket lingers until disconnect, which then drives the normal stop/replay path (`live/service.go:648-658`, `main.go:1484-1487`).
- **W12:** `federation_follower_approval` applies to CHANNEL followers (no instance actor exists); auto-follow-back is signed by the followed channel's actor.
- **W6:** the optional `CUSTOM_JS_ALLOWED` boot kill-switch was NOT built — custom JS is gated by admin-only auth + typed confirmation + audit envelope instead.
- **W2/W4:** one sanctioned layout.tsx wiring edit (Header seam prop pass-through) — the seam-extension rule otherwise held for all waves.
- Whisper is an external HTTP endpoint by construction (transcription remote-runners structurally moot); no P2P/tracker (plain-HLS custom player); no plugin system (profiles N/A).

---

## 5. Deferred items & unlock conditions

| Deferred item | Unlocks when |
|---|---|
| `login_redirect_single_oauth` (W5 ride-along, **newly ledgered**) | OAuth/external-auth subsystem ships |
| `live.transcoding.*` cluster + DVR window + latency modes | live ffmpeg ladder subsystem is designed/built (architecture note 7 — no dormant keys) |
| Global search-index quartet (`search.search_index.*`) | Sepia-compatible index client is built (all four land together) |
| `followers.instance.enabled` / `manual_approval` | instance-level AP actor is designed |
| `auto_follow_index` + `index_url` | index-consumer subsystem is designed |
| Comment `requires_approval` tier | per-video comment-approval queue is built |
| Email HTML template customization | HTML mail layer exists (plaintext single-seam today) |
| `original_file.keep` delete option | disk-pressure demand; must resolve progressive-playback substitute jointly with web_videos equivalence |
| Trending algorithm choice/default/interval | a second trending algorithm exists |
| Audio-file upload, split A/V HLS, podcast audio, video studio | per-ledger §§3/6/7 feature decisions |
| CIDR signup filters, history max-age (env-only-if-ever) | operator demand (boot-only in PT too) |

---

## 6. Doc reconciliation applied at close

- **instance-contract.md:** W7 backfill (registration fields + effective `registration_enabled`); W8/W10/W14 features-block backfill (`import_http`, `channel_sync`, `storyboards`, `transcription`, `user_import`, `user_export`, `transcoding`, `upload_additional_extensions`, `video_replace`) + replace/replace-session endpoints + the effective-vs-capability caveat for the disabled-with-explanation pattern; W12 follower-queue UI marked SHIPPED (W15); W2 SSR-snapshot note that the `live` block is intentionally consumed off-snapshot.
- **ledger.md:** new §16 deferred row for `login_redirect_single_oauth` (supersedes waves.md:129's "implement the branch"); W14 + W15 as-built records; program-close as-built deviation block (CUSTOM_JS_ALLOWED, uniform MaxFPS, server-side live force-close, layout.tsx exception, storyboards gate location); full 2026-07-12 line-number re-verification of the corrections block and §6/§8/§11/§13/§14 citations; note that gap-matrix.json `vidra_status` is a frozen 2026-07-11 pre-implementation snapshot superseded by W1–W15.

---

## 7. Verdict

**The config-parity program is functionally complete.** All 15 waves shipped with verified backend enforcement, contract exposure, and validation (118/118 audited items; zero backend defects survived adversarial verification). The residual gap was confined to admin-UI presentation in vidra-user: one functional defect (the transcoding ladder was not editable from `/admin/config`), one unmet explicit acceptance rule (W12 protocol labels), and cosmetic META/section-id polish.

**PROGRAM CLOSED 2026-07-12.** All seven fixes (F1–F7) landed together as vidra-user `6d048af` — full `npm run ci` green (typecheck, lint, 1141 unit tests, build, e2e; one pre-existing watch-player load flake proven 4/4 in isolation) — and passed adversarial review with verdict SHIP and zero defects. Two non-blocking nits are on record for any future polish pass: the test fixture's last two rows are swapped relative to registry order, and `federation_follower_approval`/`federation_auto_follow_back` could optionally disclose under `federation_allow_channel_followers` (currently independent, matching the server's semantics).