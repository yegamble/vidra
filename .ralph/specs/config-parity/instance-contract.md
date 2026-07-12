# Contract: public effective-config exposure (W1 backend ↔ W2 frontend)

Agreed up front so W1 (vidra-core) and W2 (vidra-user) build in parallel. All additions are
**additive** to the existing `GET /instance` document (snake_case, matching current tags in
`internal/httpapi/instance.go`). Fields land incrementally by wave; absent field = feature not
yet shipped, frontend must tolerate absence. Documents are referenced by hash/URL, never inlined.

## GET /instance — new blocks

```jsonc
{
  // ...existing fields unchanged...

  "branding": {                       // W1 shape, W4 populates
    "avatar":  { "url": "", "is_fallback": true },   // "" + is_fallback when unset
    "banner":  { "url": "", "is_fallback": true },
    "logos": {
      "favicon":       { "url": "", "is_fallback": true },
      "header_wide":   { "url": "", "is_fallback": true },
      "header_square": { "url": "", "is_fallback": true },
      "opengraph":     { "url": "", "is_fallback": true }
    },
    "hide_instance_name": false       // W4 (header_hide_instance_name)
  },

  "defaults": {                       // W1 shape; W5/W9 populate
    "feed_sort": "recent",            // enum: recent|popular|trending
    "feed_scope": "local",            // enum: local|all
    "landing_page": "home-recent",    // enum: home-recent|trending|local|home (home only when homepage doc enabled)
    "theme": "system",                // enum: system|light|dark
    "player_autoplay": true,
    "miniature_prefer_author_display_name": false,
    "publish": {                      // W9 (AS BUILT)
      "privacy": "private",           // keeps shipped omit-means-private; admins opt into public-by-default
      "licence": 0,                   // 0 = no default
      "comment_policy": "enabled",    // enum: enabled|disabled
      "download_enabled": true        // shipped behaviour: downloadable while the instance downloads gate is on
    }
  },

  "broadcast": {                      // W3
    "enabled": false,
    "message": "",                    // markdown
    "level": "info",                  // enum: info|warning|error
    "dismissable": false
  },

  "customization": {                  // W6
    "css_hash": "",                   // sha256 of custom_css doc; "" = none
    "js_hash": "",
    "primary_color": ""               // "#rrggbb" or ""
  },

  "social": {                         // W4
    "twitter_username": ""            // e.g. "@sizetube"; distinct from social_links.x
  },

  "homepage": {                       // W6
    "enabled": false,
    "hash": ""
  },

  "live": {                           // W11 (AS BUILT — added post-contract, backfilled here)
    "allow_replay": true,
    "default_save_replay": false,     // EFFECTIVE seed: setting AND allow_replay
    "max_instance_lives": 0,          // 0 = unlimited
    "max_user_lives": 0,
    "max_duration_secs": 0            // 0 = no limit
  },

  "search": {                         // W13 (AS BUILT — added post-contract, backfilled here)
    "remote_uri_users": true,         // EFFECTIVE: setting AND federation enabled+wired
    "remote_uri_anonymous": false     // default false (anonymous SSRF/abuse surface, PT parity)
  }
}
```

Caching: response gains `ETag` + `Cache-Control: s-maxage=60` (short; settings changes must show
within ~a minute).

## W12 backfills (AS BUILT)

- `features.mail` (bool) on GET /instance: true when a contact mailer is wired (SMTP or dev capture) —
  drives disabled-with-explanation on email_subject_prefix / email_body_signature admin rows.
- Follower approval admin API: `GET /api/v1/admin/federation/follower-requests`,
  `POST /api/v1/admin/federation/follower-requests/{id}/approve|reject` (audit actions
  `admin.federation.follower_approve/reject`). Admin UI SHIPPED in W15 (vidra-user b216134):
  `app/admin/federation/follower-requests/page.tsx` + `components/AdminFederationFollowerRequestsView.tsx`,
  nav entries in `AdminTabs.tsx`/`AdminConsole.tsx`, e2e coverage in `e2e/admin-federation-followers.spec.ts`.
- Auto-follow-back is signed by the FOLLOWED CHANNEL's actor (no instance actor exists).

## W13 backfills (AS BUILT)

- Remote-URI search: `GET /api/v1/videos/search` gains an additive `remote` array (omitted unless a
  URI/handle-shaped first-page query resolved): items `{"type":"video","video":{RemoteVideo}}` or
  `{"type":"channel"|"account","actor":{"actor_url","handle","domain"}}`. Resolution runs through the
  SSRF-guarded federation fetcher, concurrently with the local search under a ~2.5s deadline,
  rate-limited per caller (10/min default; Redis-backed when rate limiting is on); every failure
  degrades silently to local-only. The q<=100-char cap still applies to shaped queries.
- Registry keys `search_remote_uri_users` (default true) / `search_remote_uri_anonymous`
  (default false), page `federation`, section `search`.

## W7 backfills (AS BUILT)

- GET /instance gains additive top-level fields: `registration_requires_email_verification`
  (bool; EFFECTIVE = setting AND mail wired — `internal/httpapi/instance.go:201`),
  `registration_minimum_age` (int; 0 = off — `instance.go:205`), and
  `registration_disabled_reason` (string; `""` or `"user_limit_reached"` — `instance.go:197`).
  `registration_enabled` is now the EFFECTIVE value: it reads false once
  `registration_user_limit` headroom is exhausted.

## W8/W10/W14 backfills (AS BUILT)

- The `features` block gains six W8 flags — `import_http`, `channel_sync`, `storyboards`,
  `transcription`, `user_import`, `user_export` — plus `transcoding` and
  `upload_additional_extensions` (W10) and `video_replace` (W14)
  (`internal/httpapi/instance.go:39-59`, populated at `:328-337`). Each is the EFFECTIVE
  availability: the runtime setting AND (where one exists) the boot capability (yt-dlp for
  import_http, Whisper + caption worker for transcription, ffmpeg pipeline for transcoding),
  matching the server's 403 `feature_disabled` gate — the UI hides/disables in lock-step.
- `features.video_replace` (bool): true when `video_replace_enabled` AND uploads are both on.
  W14 endpoints: `POST /api/v1/videos/{id}/replace` (multipart source swap, dynamic body
  limit) and `POST /api/v1/videos/{id}/replace-session` (resumable), both `requireAuth` +
  owner/moderator gated and 403 `feature_disabled` via `videoReplaceAvailable()`
  (`internal/httpapi/replace.go:35-38`; routes `server.go:1010`/`:1020`).
- NOTE for the admin UI: because these flags are EFFECTIVE (setting AND capability), they
  cannot drive the disabled-with-explanation HIG pattern on the config pages — that pattern
  needs the bare boot capability, which today is exposed only for mail (`features.mail` is
  pure capability, which is why the email rows work). A raw transcoding/whisper capability
  signal is future work if that pattern is wanted for the transcription/transcoding rows.

## Documents (W1 store, W6 consumers)

- Table `instance_documents(name PK enum: homepage|custom_css|custom_js, body TEXT, sha256, updated_at, updated_by)`; writes audit-enveloped.
- Admin: `GET/PUT /api/v1/admin/instance-documents/{name}` — PUT body `{"body": "..."}`; size caps: homepage 100KB, custom_css 200KB, custom_js 200KB.
- Public (AS BUILT in W1 — all public routes live under the API prefix, consistent with every other
  vidra-core route): `GET /api/v1/instance/homepage` → `{"body": "...", "hash": "..."}` (markdown JSON);
  `GET /api/v1/instance/custom.css` → `text/css`; `GET /api/v1/instance/custom.js` → `application/javascript`.
  vidra-user and vidra-core are separate origins, so the frontend consumes them via its API base URL:
  `<link href="{apiBaseUrl}/api/v1/instance/custom.css?v={css_hash}">` / `<script defer src="{apiBaseUrl}/api/v1/instance/custom.js?v={js_hash}">`
  (W2 already builds hrefs this way). Branding asset URLs in the /instance payload are full `/api/v1/...` paths.

## Branding assets (W1 store, W4 consumers)

- `POST/DELETE /api/v1/admin/instance-avatar`, `/admin/instance-banner`, `/admin/instance-logo/{type}` with
  `type ∈ favicon|header-wide|header-square|opengraph`; multipart upload, image validation, reuse profileimage resize pipeline with an instance-scoped owner.

## Registry metadata (W1)

`instancesettings` spec gains `page` + `section` fields (e.g. `page: "general", section: "broadcast"`),
exposed in `GET /admin/instance-settings` so the admin UI auto-places keys into the new IA.
Pages: `general | vod | live | federation | customization | homepage | advanced`.

## Frontend SSR fetch (W2)

`vidra-user/lib/instance-config.server.ts`: server-side fetch of `GET /instance` with React `cache()`
+ ~60s revalidate; consumed by `generateMetadata`, theme bootstrap, layout injection seams, `/` landing
switch. Client-side consumers keep using the same payload — one source of truth.

AS BUILT note (W11): the typed `InstanceConfigSnapshot` in `lib/instance-config.server.ts`
(lines 97-105) deliberately omits the `live` block that GET /instance now returns
(`internal/httpapi/instance.go:250`, `:351-357`). Live limits are consumed by the live UI via a
separate client-side fetch of the same payload, not the SSR snapshot type — the omission is
intentional, not a contract gap.

## Conventions (all waves)

- `0` = unlimited (never PeerTube's `-1`); null-PATCH clears an override back to default.
- Provider-func seams for runtime reads; workers always constructed, gated at enqueue/pickup.
- Every wave ships independently behind `make ci` / `npm run ci`.
