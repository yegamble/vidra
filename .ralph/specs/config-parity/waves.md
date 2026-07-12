# PeerTube Admin-Config Parity — Wave Plan (2026-07-11)

Source: 16-section gap analysis (105 settings) + Fable architect pass, workflow `wf_fbd2cacd-c4e`.
Gap matrix: `gap-matrix.json` (per-setting status/kind/apply-points/size). Contract: `instance-contract.md`.

## Scoreboard
Per-setting gap matrix across all 16 PeerTube admin-config sections: 105 settings assessed against vidra-core's 37-key instance_settings DB-overlay registry, its env-only config surface, and vidra-user's metadata-driven /admin/config UI. Scoreboard: only 6 settings are at full admin-mutable parity today (signup.enabled, signup.requires_approval, user.video_quota, auto_blacklist/quarantine, live.enabled, plus federation.enabled which is boot-only in PeerTube too, so env-only IS parity); ~7 more are env-only knobs over shipped features that just need the established provider-func-seam overlay (HTTP import, channel-sync enable + max-per-user, transcription/Whisper, transcoding master toggle with the boot-baked-worker gotcha). The largest cheap wins are settings over features that ALREADY exist but have no knob: storyboards (settings reader wrongly called the feature absent — internal/media/storyboard.go exists; codebase reader preferred), user import/export toggles + export TTL/quota gate (internal/account fully shipped), live replay + save-replay default, defaults.publish privacy/licence, max channels per user, signup limit, email subject-prefix/signature, and the broadcast-message 4-key slice already designated as the next increment. Medium items need real wiring: email-verification gate, daily quota accounting, per-video comment/download policies, import+transcoding concurrency worker pools, parameterizing the hardcoded HLS ladder/FPS/threads, live simultaneous/duration caps at the nginx-rtmp callback, inbound-federation policy gates at inbox.go, remote-URI search, homepage document + custom CSS/JS + theme/primary-color (all sharing one prerequisite: a server-side instance-config fetch in vidra-user, which today fetches /instance client-side only — build it once for branding metadata, twitter:site, theme, and injection). L/defer/N-A items are honest feature absences or deliberate deviations worth recording in the ledger: no P2P (custom plain-HLS player — all p2p/tracker keys N/A), no remote-runner protocol (all 4 remote_runners keys N/A), no torrent import, no video studio, no live transcoding ladder (passthrough packaging), no plugin system (transcoding profiles N/A), Whisper is already an external endpoint (transcription runners moot), vidra always keeps originals and serves them progressively (inverts original_file.keep and substitutes for web_videos), and PT's cache.* block is deprecated upstream on develop so cache-count knobs should be skipped. Vidra conventions to hold: 0=unlimited (not PT's -1), null-PATCH-clears-override, new keys auto-render in AdminInstanceConfigView. One flagged uncertainty: whether signup auto-creates a channel (determines default_channel_name applicability) — no reader confirmed it; verify in vidra-core before scoping that key.

## Architecture notes (cross-cutting decisions)
CROSS-CUTTING DECISIONS

1) ASSET STORE SHAPE (branding). Reuse the profileimage multi-size pipeline (migration 0040) with a new instance-scoped subject rather than a parallel storage system: add an owner discriminator (owner_type='instance', singleton owner row) or a thin instance_assets table that delegates to the same resize/store service. Assets are NOT registry keys — they get dedicated pick/delete admin endpoints, mirroring PeerTube: POST/DELETE /api/v1/admin/instance-avatar, /admin/instance-banner, /admin/instance-logo/{type} with type enum favicon|header-wide|header-square|opengraph. GET /instance gains a `branding` block: URL maps per slot with isFallback flags. The opengraph slot doubles as the social-card image (pairs with social_meta_twitter_username). storage.client_overrides is ledgered N/A (legacy PT boot mechanism superseded by the upload API upstream too).

2) DOCUMENT STORE SHAPE. Long documents live OUTSIDE the instancesettings registry (10k string cap, PATCH-scalar semantics, and diff-scale auditing don't fit). New table instance_documents(name enum PK: homepage|custom_css|custom_js, body TEXT, sha256, updated_at, updated_by), writes audit-enveloped. Admin API: GET/PUT /admin/instance-documents/{name}. Public delivery: homepage via GET /instance/homepage (markdown JSON, rendered by the existing components/Markdown.tsx pipeline); custom CSS/JS served as same-origin text endpoints /instance/custom.css and /instance/custom.js with the content hash as a cache-busting query param. The broadcast message body stays a registry string (short, PT caps it similarly) so the whole broadcast slice rides the existing registry/PATCH/UI machinery. Registry remains the single home for all scalar settings.

3) PUBLIC EFFECTIVE-CONFIG EXPOSURE. Extend GET /instance (no new endpoint) with additive structured blocks: branding{}, defaults{feed_sort, feed_scope, landing_page, theme, player_autoplay, publish...}, broadcast{}, customization{css_hash, js_hash, primary_color}, social{twitter_username}, alongside the existing features block. Documents are referenced by hash/URL, never inlined. Add ETag + short s-maxage. vidra-user gains a server-side fetch helper (lib/instance-config.server.ts, React cache() + ~60s revalidate) — this single shared prerequisite unlocks generateMetadata (favicon/og/twitter:site), flash-free default_theme in the pre-paint bootstrap, primary-color and custom-CSS/JS injection, and the '/' landing switch. The same payload keeps serving existing client-side consumers; one source of truth.

4) ADMIN UI INFORMATION ARCHITECTURE (PeerTube grouping, Apple HIG interaction). /admin/config becomes a layout route with a persistent left rail of pages, each page with in-page sectioned side-labels (anchor rail): 
- General: instance identity + descriptions/ToS (existing keys), Branding assets (uploaders with preview + remove), Broadcast message, Landing & browse defaults, Sign-up & new users, Moderation (quarantine).
- VOD: Uploads (extensions, quota incl. daily), Imports (http/yt-dlp, channel sync), Transcoding (master, ladder, FPS, threads, concurrency), Storyboards, Transcription, Publish defaults (privacy/licence/comments/download).
- Live: master toggle, replay + save-replay default, simultaneous caps, max duration.
- Federation: remote comments, channel followers, follower approval, auto-follow-back — every key labeled with which protocol it governs (AP vs ATProto; ATProto has no PT analogue).
- Customization: default theme, primary color, header options, player defaults, email subject prefix/signature.
- Homepage: markdown document editor with live preview + enable toggle (enabling unlocks the 'home' landing-page option).
- Advanced: custom CSS, custom JS (danger-styled), remote-URI search, user import/export.
HIG patterns throughout: grouped inset form sections with clear headers and footnote help text; progressive disclosure — child settings render indented/hidden until the parent toggle is on, and settings whose boot-env dependency is absent (e.g. email verification without MAIL_ENABLED, transcription without WHISPER_ENDPOINT) render disabled with an explanatory note rather than silently ineffective; immediate inline validation (hex color, int ranges, rung sets); explicit effective-value display showing env default vs DB override with a 'Reset to default' affordance (null-PATCH-clears-override convention); sticky save bar with dirty-diff and per-section save; safe defaults preselected; destructive styling + typed confirmation for JS injection. The registry spec table gains page/section metadata so new keys keep auto-rendering into the right page — preserving the metadata-driven-UI invariant. Everything stays inside the light-dark() token architecture and redesign guardrails; no new colors outside tokens.

5) EMAIL TEMPLATE CUSTOMIZATION MECHANISM. vidra mail is plaintext with a single sender seam (internal/mail/smtp.go Send). Mechanism = two registry strings applied at that one seam: email_subject_prefix (with {instance_name} substitution, PT-compatible semantics) prepended to every subject, email_body_signature appended to every body. Full template/HTML customization is explicitly out of scope until an HTML mail layer exists — record in ledger. Both effective only when MAIL_ENABLED; SMTP wiring stays env (secrets).

6) CUSTOM JS/CSS INJECTION + SECURITY POSTURE. Stored in instance_documents; delivered as same-origin EXTERNAL files (<link href="/instance/custom.css?v={hash}">, <script defer src="/instance/custom.js?v={hash}">) injected by layout.tsx only when non-empty per the SSR snapshot — external-file delivery avoids inline eval, keeps a future script-src 'self' CSP viable, and gives natural cache-busting. Posture: this is XSS-as-a-feature by definition, but it is admin-only — a malicious admin already controls the server, so there is no privilege escalation; the real risks are accidents and compromised admin accounts. Mitigations: admin auth + audit-envelope every change with hash; editor gated behind a loud warning and typed confirmation ("this code runs in every visitor's browser"); optional boot env kill-switch (CUSTOM_JS_ALLOWED) for managed-hosting operators; CSS ships first (much lower risk), JS in the same wave but behind the confirmation flow.

7) LIVE CONFIG WITH THE MEDIA SERVER PARTIALLY BUILT. Decision: ship ONLY knobs that have real enforcement points today — replay gating (pipeline shipped, migrations 0061/0076), save-replay default, simultaneous caps and duration watchdog at the secret-handled nginx-rtmp publish callbacks. Do NOT ship dormant settings for the unbuilt live-transcoding ladder (live.transcoding.*, DVR, latency): registry keys without apply points mislead admins and freeze naming before the subsystem is designed. Record them as deferred in the ledger and revisit when/if a live ffmpeg ladder is built. (Passthrough already delivers original resolution — partial equivalence noted in ledger.)

8) CONVENTIONS HELD ACROSS ALL WAVES: 0=unlimited (never PT's -1); null-PATCH clears override; config-env default where an env knob exists; provider-func seams for runtime reads; boot-wired workers are always constructed and gated at enqueue/pickup time (the transcoding gotcha); every wave lands additive and independently shippable behind make ci (vidra-core) and npm run ci (vidra-user).

9) VERIFIED THIS PASS (previously flagged uncertainties): (a) signup does NOT auto-create a channel — nothing channel-related in internal/auth/registration.go — so default_channel_name is N/A until auto-channel-creation exists (ledger); (b) upload validation IS an extension allowlist (video.AcceptedVideoExt, enforced at internal/httpapi/uploads.go:170 and again at AttachOriginal) — upload_additional_extensions_enabled is feasible as a gated extended-extension set; (c) NO instance-level AP actor exists (only Person/Group account/channel actors in internal/federation/actor.go) — followers.instance.* deferred until one is designed; (d) inbound channel Follows are auto-accepted in HandleInbox — the federation_allow_channel_followers gate is exactly one Reject branch at that site.

10) EXPLICIT BUILD-VS-DEFER ON L ITEMS: BUILD — video file replacement (W14, only L with clear demand and no architectural blocker; schedule last). DEFER — global search index (4 keys land together if ever; Sepia-compatible client is a whole subsystem), trending algorithms (meaningless with one algorithm; build a second first), video studio, live transcoding cluster, audio-file upload, split A/V HLS. N/A — torrent import (BitTorrent client out of proportion to demand), all remote_runners keys (no runner protocol; Whisper is already an external endpoint), P2P/tracker/latency (custom plain-HLS player deviation), transcoding profiles (no plugin system), HLS toggle (transcoding_enabled IS the HLS toggle), web_videos (vidra serves the retained original progressively — documented equivalence), cache.* (deprecated upstream on PT develop), player themes, max collaborators.

## Waves

### W0 — Parity Ledger & Deviation Record
**Goal:** Bank the free wins: write the definitive parity ledger recording every N/A and deferred key with rationale, so the remaining program is purely buildable items and future audits stop re-litigating deviations.
**Repos:** vidra (meta-repo docs/ledger) | **Parallelizable:** True
**Items:**
- client_overrides → N/A (superseded upstream)
- trending algorithms enabled/default/interval → defer until a 2nd algorithm exists
- torrent import → N/A
- all 4 remote_runners keys → N/A (no runner protocol; Whisper already external)
- P2P webapp/embed, tracker, live latency → N/A (plain-HLS custom player)
- transcoding profile (VOD+live) → N/A (no plugins)
- hls.enabled → N/A (transcoding_enabled IS the HLS toggle)
- web_videos → N/A-for-now (original served progressively — documented equivalence)
- podcast audio, split A/V, audio-file upload → defer
- video studio + studio runners → defer/N-A
- cache.* counts → N/A (deprecated upstream)
- player theme → N/A
- max collaborators per channel → N/A
- default_channel_name → N/A (VERIFIED: signup creates no channel)
- signup CIDR filters + history max age → env-only-if-ever (boot-only in PT too)
- federation.enabled → already at parity env-only (boot-only in PT)
- followers.instance.* → deferred (VERIFIED: no instance AP actor)
- transcription remote runners → N/A (WHISPER_ENDPOINT already external)
**Risks:** None technical; only risk is the ledger drifting from reality — cite file evidence (e.g. uploads.go:170, inbox.go auto-accept) per entry so it stays trustworthy like the reconciled fix_plans.

### W1 — Core Config Surface Foundations
**Goal:** Build the backend plumbing every value wave needs: structured effective-config on GET /instance, the instance_documents store, the instance asset store + admin endpoints, and registry page/section metadata.
**Repos:** vidra-core | **Parallelizable:** True
**Items:**
- GET /instance additive blocks: branding{}, defaults{}, broadcast{}, customization{hashes}, social{} + ETag/s-maxage
- instance_documents table + GET/PUT /admin/instance-documents/{name} + public /instance/homepage, /instance/custom.css, /instance/custom.js (hash-busted)
- instance-scoped subject in profileimage pipeline + POST/DELETE /admin/instance-avatar, /admin/instance-banner, /admin/instance-logo/{favicon|header-wide|header-square|opengraph}
- registry spec metadata: page/section grouping fields so keys auto-place in the new admin IA
**Dependencies:**
- Contract agreement with W2 on the /instance block JSON shapes (agree schema up front, then build in parallel)
**Risks:** GET /instance is a hot cached path — keep additions inside the existing lock-guarded settings cache pattern; asset-owner modeling in profileimage must not disturb user/channel avatar rows (migration + integration tests); document endpoints need size caps and content-type discipline (text/css, application/javascript).

### W2 — Admin IA Restructure & SSR Config Fetch (frontend foundations)
**Goal:** Split the single admin config page into the PeerTube-mirroring multi-page IA with Apple HIG interaction patterns, and land the server-side instance-config fetch + layout.tsx extension seams so later waves touch only their own modules (this is what makes W3–W9 parallelizable).
**Repos:** vidra-user | **Parallelizable:** True
**Items:**
- /admin/config/{general,vod,live,federation,customization,homepage,advanced} layout route + left rail + in-page sectioned side-labels
- HIG patterns: grouped inset forms, progressive disclosure for dependent settings, disabled-with-explanation for absent boot-env deps, inline validation, effective-value/override display with null-PATCH reset, sticky dirty-diff save bar
- lib/instance-config.server.ts (React cache + short revalidate) consumed by generateMetadata and the theme bootstrap
- layout.tsx extension seams: metadata builder, Banner slot, theme-bootstrap-reads-SSR-snapshot, injection points — so W3–W6 never edit layout.tsx directly
- preserve metadata-driven auto-render: existing 37 keys re-home into the new pages via W1's section metadata
**Dependencies:**
- Contract agreement with W1 on /instance block shapes (parallel-safe once agreed)
**Risks:** Biggest UI churn of the program — admin E2E specs and AdminInstanceConfigView tests need migration; theme-flash regression if the SSR snapshot is mis-cached (verify with e2e:backed, remember E2E_PORT=3181); must stay strictly inside light-dark() tokens and redesign guardrails.

### W3 — Broadcast Message
**Goal:** Ship the designated-next slice: full broadcast banner (the single most admin-visible daily feature) end to end.
**Repos:** vidra-core, vidra-user | **Parallelizable:** True
**Items:**
- broadcast_enabled (bool)
- broadcast_message (registry string, markdown, reuse Markdown.tsx + admin preview modal)
- broadcast_level (enum info|warning|error)
- broadcast_dismissable (bool, localStorage dismissal keyed by message hash so edits re-show)
- new Banner component filling W2's layout slot, styled per level via tokens
**Dependencies:**
- W1 (broadcast block on /instance)
- W2 (Banner slot + General page)
**Risks:** Low — all existing registry kinds. Only care: banner must render for anonymous users from the public config fetch and never block paint; dismissal-hash semantics need a test.

### W4 — Branding & Social Identity
**Goal:** Close the highest-visibility gap: instance avatar/banner/logos (vidra-user has zero instance imagery and no favicon at all today) plus social link-card metadata.
**Repos:** vidra-core, vidra-user | **Parallelizable:** True
**Items:**
- instance avatar (instance.avatars) via asset endpoint
- instance banner (instance.banners) — About header + optional home hero
- instance logos: favicon / header-wide / header-square / opengraph (instance.logo) wired into generateMetadata icons + og:image and Header.tsx
- header_hide_instance_name (bool — only meaningful now that a logo exists)
- social_meta_twitter_username (twitter:site meta; distinct from the existing x_link About-page key — do not conflate)
**Dependencies:**
- W1 (asset store + branding block)
- W2 (SSR metadata seam)
**Risks:** SSR metadata correctness (favicon/og caching, isFallback handling); image-type/size validation on upload endpoints; watch page og:image should prefer video thumbnail over instance opengraph — define precedence.

### W5 — Browse, Landing & Player Defaults
**Goal:** Make the daily-visible behavior defaults admin-tunable: what anonymous visitors see first and how the player behaves.
**Repos:** vidra-core, vidra-user | **Parallelizable:** True
**Items:**
- default_feed_sort (enum recent|popular|trending — deliberate 3-way deviation from PT's 7)
- default_feed_scope (enum local|all; keep local as shipped default)
- default_landing_page (enum home-recent|trending|local; 'home' option appears conditionally once W6 homepage ships)
- default_theme (enum system|light|dark seeding the pre-paint bootstrap via SSR snapshot — no flash)
- default_player_autoplay (seeds BOTH start-on-open and autoplay-next for anonymous/unset users — documented deviation)
- miniature_prefer_author_display_name (incl. adding uploader display name to feed/search payloads if absent — the M part)
- login_redirect_single_oauth (S ride-along; dormant until OAuth ships — implement the branch, note dependency)
**Dependencies:**
- W1 (defaults block)
- W2 (SSR fetch + theme seam)
- soft: W6 for the 'home' landing option
**Risks:** Feed payload change for author display name touches list endpoints — keep additive; landing-page switch at '/' must not add a client redirect flash (do it server-side); autoplay-seeding must never override an explicit per-user pref (migration 0075).

### W6 — Customization Documents & Theme (homepage, CSS/JS, primary color, email)
**Goal:** Land the document-store consumers: admin-authored homepage, custom CSS/JS injection with the defined security posture, primary color, and the two email-customization strings.
**Repos:** vidra-core, vidra-user | **Parallelizable:** True
**Items:**
- instance_homepage (document; admin editor page with markdown preview; rendered on '/'; unlocks 'home' in default_landing_page)
- custom_css (document; SSR <link> injection via hash-busted same-origin file)
- custom_javascript (document; external same-origin <script defer>; typed-confirmation warning flow; audit-enveloped; optional CUSTOM_JS_ALLOWED env kill-switch)
- theme_primary_color (validated hex → --accent override; live WCAG contrast check in the editor with warning when deltas break; one color only — PT's 10-color palette out of scope)
- email_subject_prefix (string, {instance_name} substitution, applied at mail/smtp.go Send seam)
- email_body_signature (string, appended at same seam; plaintext-only makes this trivial)
**Dependencies:**
- W1 (document store + customization block)
- W2 (injection seams + Homepage/Advanced/Customization pages)
- Design decision: primary-color contrast-guard approach (design-gated per redesign guardrails)
**Risks:** custom_javascript is XSS-by-design — posture per architecture notes must be implemented exactly (warning, audit, external-file delivery); theme_primary_color can break the hand-tuned WCAG deltas — the contrast validator is mandatory, not optional; email strings must be no-ops when MAIL_ENABLED is false (disabled-with-explanation UI).

### W7 — Sign-up & New Users
**Goal:** Complete the registration section: verification gate, limits, age attestation, and daily quota accounting.
**Repos:** vidra-core, vidra-user | **Parallelizable:** True
**Items:**
- registration_require_email_verification (hold activation until verified; effective only with MAIL_ENABLED — surfaced in UI)
- registration_user_limit (count-and-refuse; effective registration_enabled on /instance reflects limit reached)
- registration_minimum_age (signup-form attestation, matching PT — no birthdate identity check)
- default_user_daily_quota_bytes (NEW daily-usage window in internal/quota + upload-session gate + upload UI display — the real M here)
- new_user_history_enabled (build per-user history on/off preference + SettingsView toggle FIRST, then this key seeds it)
- optional env-only ride-alongs: HISTORY_MAX_AGE pruning sweeper (SweepExpiredExports pattern), REGISTRATION_CIDR_ALLOW/DENY
**Dependencies:**
- W2 (General page grouping)
- minor: W1 for /instance effective-registration semantics
**Risks:** Daily-quota accounting design (rolling 24h vs calendar day — pick rolling, document) touches the upload hot path; verification gate must not lock out existing unverified accounts retroactively (grandfather clause + test); user-limit check needs to be race-tolerant (approximate count acceptable).

### W8 — Shipped-Feature Toggle Batch (provider-seam overlays)
**Goal:** One agent pass, many settings: overlay every env-boot-only knob and missing toggle over features that already exist, using the shipped provider-func seam + int-key patterns. Highest settings-per-effort wave in the program.
**Repos:** vidra-core, vidra-user | **Parallelizable:** True
**Items:**
- import_http_enabled (gate yt-dlp resolver; YTDLP_PATH/TIMEOUT/PROXY stay env — PT keeps companions boot-only too)
- channel_sync_enabled (gate sync-create + ticker; INTERVAL/BATCH/COOLDOWN stay env)
- channel_sync_max_per_user (swap existing cap read at channelsync/service.go:112-236 to seam; default 5 kept)
- storyboards_enabled (gate at generation call site — feature VERIFIED present: internal/media/storyboard.go + migration 0060)
- transcription_enabled (effective = settingBool AND WHISPER_ENDPOINT set — contact_form_enabled pattern)
- user_import_enabled + user_export_enabled (403 feature_disabled gates on shipped internal/account flows)
- user_export_expiration_hours (swap hardcoded 7d at export.go:35-37 to seam; keep 7d default vs PT 2d)
- user_export_max_quota_bytes (one comparison against internal/quota; note vidra archives exclude media — cheap, implement anyway)
- max_channels_per_user (count-and-refuse at channel create; 0=unlimited; distinct from CHANNEL_SYNC_MAX_PER_USER)
**Dependencies:**
- W1 (features block exposure)
- W2 (VOD/General/Advanced page placement)
**Risks:** Low individually — every item is an isolated seam; the batch risk is inconsistency, so define the gate idiom once (403 feature_disabled + /instance features flag + UI hide/disable) and apply uniformly. Items within the wave can be split across parallel agents (disjoint files).

### W9 — Publish Defaults & Per-Video Policies
**Goal:** Ship defaults.publish parity: seed privacy/licence defaults over the existing model and build the two missing per-video policy fields (comments, downloads) that their defaults require.
**Repos:** vidra-core, vidra-user | **Parallelizable:** True
**Items:**
- default_video_privacy (enum; seed video-create handler + StudioView prefill — model fully built incl. password/embed privacy)
- default_video_licence (int; 0='no default' mirroring PT null; IDs already PT-compatible)
- default_comment_policy (build per-video comments policy enabled|disabled FIRST + comment-create gate; requires_approval deliberately deferred — no comment-approval queue in v1, ledger note)
- default_download_enabled (build per-video download_enabled column + enforcement in downloads.go — downloads unconditionally allowed today; then the default is trivial)
**Dependencies:**
- W2 (VOD page)
- Design decision: comment-policy deviation (enabled|disabled only) signed off
**Risks:** Two migrations + backfill semantics (existing videos inherit 'enabled' for both new columns); download gate must cover all download routes incl. original file; federation outbox representation of comment policy needs checking against contract golden tests.

### W10 — VOD Transcoding Runtime Knobs & Worker Pools
**Goal:** Make the shipped transcoding pipeline admin-tunable: master toggle (enqueue-gated), parameterized ladder, FPS/threads, and the shared bounded-worker-pool refactor covering both transcoding and import concurrency.
**Repos:** vidra-core, vidra-user | **Parallelizable:** True
**Items:**
- transcoding_enabled (gate at job-enqueue/pickup, NEVER worker construction — the boot-baked-worker gotcha)
- transcoding_resolutions (parameterize hardcoded 1080/720/480/360 ladder at hls.go:24-28; validated rung set; only rungs <= source; NO 0p audio-only in v1)
- transcoding_max_fps (ffmpeg fps filter once ladder is parameterized — bundle)
- transcoding_threads (per-job -threads read via seam)
- transcoding_concurrency + import_jobs_concurrency (ONE worker-pool refactor pass across internal/transcode and internal/videoimport service.go:268 single-ticker)
- transcoding_original_resolution (rendition planning; only matters for HLS rung above ladder max since original is kept — document)
- upload_additional_extensions_enabled (VERIFIED feasible: gate an extended set behind video.AcceptedVideoExt, uploads.go:170 + AttachOriginal + StudioView accept attr)
- keep_original_file → recommend DEFER the delete-after-transcode option (deleting breaks progressive playback of source, vidra's web_videos substitute) — ledger the inverted deviation, decide jointly with web_videos equivalence
**Dependencies:**
- W2 (VOD page)
- W8 seam idiom (convention only, not blocking)
**Risks:** Highest regression surface in the program: worker-pool refactor can change job ordering/retry semantics (needs integration tests against the job-run observability foundation); ffmpeg arg changes need golden/e2e coverage; ladder changes must not orphan existing renditions (mediagc interaction); concurrency values read per-tick so changes apply without restart.

### W11 — Live Streaming Enforcement Knobs
**Goal:** Land every live knob with a real enforcement point (replay gates, caps, duration watchdog) at the existing nginx-rtmp callback seam; explicitly do NOT ship dormant live-transcoding settings.
**Repos:** vidra-core, vidra-user | **Parallelizable:** True
**Items:**
- live_allow_replay (gate replay creation in internal/live recording.go/replay.go; simpler than PT — no transcoding dependency)
- live_default_save_replay (seed live-create handler + form; no effect when allow_replay off, mirroring PT)
- live_max_instance_lives (count active sessions at RTMP publish callback, reject; 0=unlimited)
- live_max_user_lives (same callback, per-user count — one enforcement pass with the above)
- live_max_duration_secs (watchdog against live_stream.started_at (migration 0076) force-closing via nginx-rtmp control; 0=no limit)
- DEFERRED per architecture note 7: live.transcoding.* cluster, DVR max window, latency modes — no dormant registry keys
**Dependencies:**
- W2 (Live page)
- Design decision: live-limits enforcement design at the callback seam (this wave IS that deferred work from the config-parity memory)
**Risks:** Testing requires the compose stack (nginx-rtmp callbacks are hard to unit-test — build a callback-simulator test harness); force-close control wiring is new (verify nginx-rtmp drop/control endpoint in deploy/media/nginx.conf.template); race between concurrent publish callbacks on the caps check (advisory lock or tolerate small overshoot, document).

### W12 — Federation Policy Gates
**Goal:** Give admins inbound-federation policy control at the verified inbox seam: comment ingestion, channel-follower acceptance, follower approval queue, and auto-follow-back — each key labeled AP vs ATProto.
**Repos:** vidra-core, vidra-user | **Parallelizable:** True
**Items:**
- federation_accept_remote_comments (drop at inbox.go comment ingest, after the existing blocked-domain check; not retroactive, matches PT)
- federation_allow_channel_followers (Reject branch at the VERIFIED auto-Accept site in HandleInbox)
- federation_follower_approval (pending-follower state + admin followers-queue page modeled on registration-requests; applies to CHANNEL followers as a vidra deviation since no instance actor exists)
- federation_auto_follow_back (instance-initiated follow-back over existing follow.go machinery; PT's reactive-moderation warning in help text)
- DEFERRED: followers.instance.enabled/manual approval (VERIFIED no instance AP actor — requires designing one first), auto_follow_index + index_url (index-consumer subsystem, design-gated)
**Dependencies:**
- W2 (Federation page)
- Design decision: inbound-federation policy sign-off (project memory marks inbound federation design-gated — this wave adds only drop/reject/pending gates to EXISTING inbound surface, no new surface)
**Risks:** Contract/golden tests (contract_golden_test.go) will need Reject/pending fixtures; pending-follower state is a migration + delivery-slice interaction (Accept sent later on approval); auto-follow-back must respect domain blocklist and not loop with reciprocal instances; ATProto path must be explicitly out of scope per key or gated identically — decide per key and label in UI.

### W13 — Remote-URI Search
**Goal:** Wire the existing WebFinger/URL resolution machinery into the search endpoint so URI/handle-shaped queries resolve remote content, gated separately for logged-in and anonymous users.
**Repos:** vidra-core, vidra-user | **Parallelizable:** True
**Items:**
- search_remote_uri_users (detect URI/handle-shaped queries in handleSearchVideos; reuse follow.go resolution + SSRF-guarded fetcher)
- search_remote_uri_anonymous (auth-state branch; default FALSE — SSRF/abuse surface, matching PT)
- frontend: SearchResults.tsx + lib/search-url.ts remote-result rendering
- DEFERRED with recommendation: search_index_enabled/url/disable_local/is_default (all four land together if a Sepia-compatible index client is ever built; do not ship the two cheap UI flags standalone)
**Dependencies:**
- W2 (Advanced page)
**Risks:** SSRF is the whole game — route every remote fetch through the existing guarded fetcher, never raw; rate-limit resolution per user; resolution latency must not block normal search (resolve async or with tight timeout); anonymous default stays false.

### W14 — Video File Replacement (isolated L — recommendation: BUILD, last)
**Goal:** Build the one L-sized parity feature worth building: replace-source endpoint with a source-version model and re-transcode flow, with video_replace_enabled riding on it.
**Repos:** vidra-core, vidra-user | **Parallelizable:** False
**Items:**
- source-version model + replace-source endpoint in internal/video
- re-transcode flow reusing W10's parameterized pipeline (old renditions swapped atomically, mediagc cleans up)
- video_replace_enabled (bool gate over the new endpoint)
- StudioView edit-page replace flow with progress + quota check
**Dependencies:**
- W10 (parameterized transcode pipeline + worker pool — replacement re-enqueues through it; also avoids file collisions in internal/transcode)
**Risks:** Largest single feature in the program: versioning semantics (URLs stable across replacement? playback sessions mid-swap? federation Update activity for remote copies?), storage lifecycle of the old original vs keep-original policy, and quota accounting on replacement. Sequence strictly after W10; acceptable to re-evaluate build-vs-defer at that point if demand hasn't materialized.
