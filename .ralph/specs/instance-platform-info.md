# Instance Platform Info — PeerTube-parity config + About page

Architect-approved contract (2026-07-08). Two executors: vidra-core (backend), vidra-user (frontend).
Reference: PeerTube's admin "Platform information" form and `/about/instance` page (example: sizetube.com/about).

## Scope

1. Backend: ~21 new instance settings keys (key-value overlay, no schema migration), two new kinds
   (`enum`, `list`), extended `GET /api/v1/instance`, new `GET /api/v1/instance/about`, new
   `POST /api/v1/instance/contact` (rate-limited, mails admin), video-level `is_sensitive` flag +
   `hide` policy enforcement on public browse/search.
2. Frontend: redesigned `/admin/config` page (new sections below, markdown preview modals, fixes the
   current visual clutter), PeerTube-style `/about` page, contact-form modal, sensitive-content
   presentation (blur/warn) on video cards + watch pages, markdown rendering infra.

## Backend contract (vidra-core)

### New settings keys (register in `internal/instancesettings/service.go` specs registry)

String kind (existing), all default "" unless noted. Markdown = stored/served as raw markdown text:

| key | limit | validator |
|---|---|---|
| `instance_short_description` | ≤250 | length only |
| `server_country` | ≤100 | length only (free string, frontend offers a country select) |
| `support_text` | ≤5000 | markdown |
| `website_link` | ≤2000 | validateOptionalURL |
| `mastodon_link` | ≤2000 | validateOptionalURL |
| `x_link` | ≤2000 | validateOptionalURL |
| `bluesky_link` | ≤2000 | validateOptionalURL |
| `terms` | ≤10000 | markdown (distinct from existing `terms_url`) |
| `code_of_conduct` | ≤10000 | markdown |
| `moderation_info` | ≤10000 | markdown |
| `administrator_info` | ≤5000 | markdown ("Who is behind the instance?") |
| `creation_reason` | ≤5000 | markdown ("Why did you create this instance?") |
| `maintenance_lifetime` | ≤5000 | markdown ("How long do you plan to maintain it?") |
| `business_model` | ≤5000 | markdown ("How will you finance the server?") |
| `hardware_info` | ≤5000 | markdown |
| `default_language` | — | must be a taxonomy language id (see `GET /api/v1/videos/config` source); default "en" |

Bool kind (existing): `contact_form_enabled` (default false), `instance_is_sensitive` (default false).

New kind `enum`: `sensitive_content_policy` ∈ {`hide`,`warn`,`blur`,`display`}, default `hide`.
The admin settings view for enum kinds gains an `options: []string` field.

New kind `list` (TEXT column stores canonical JSON array of strings; API value is a JSON array):
`instance_categories` (each item a taxonomy category id), `moderator_languages` (each a taxonomy
language id). Default: empty list. PATCH accepts JSON array; per-item taxonomy validation.

Existing key changes: `instance_description` limit raised to 10000 (it becomes the long markdown
description; `instance_short_description` is the new short one). No key renames — `contact_email`
is reused as the admin/contact-form address.

Defaults: hardcode in the Defaults wiring (no new env vars) — zero values, plus `default_language`
"en" and `sensitive_content_policy` "hide".

### `PATCH /api/v1/admin/instance-settings`

Extend per-key kind handling: enum expects JSON string validated against options; list expects JSON
array of strings. `null` still clears an override. All-or-nothing validation stays. Audit still logs
key names only.

### `GET /api/v1/instance` (extend `instanceResponse`, all effective/overlay values)

Add (snake_case): `short_description`, `default_language`, `categories` ([]string),
`moderator_languages` ([]string), `server_country`, `is_sensitive` (bool),
`sensitive_content_policy` (string enum), `contact_form_enabled` (bool — effective availability:
toggle AND effective contact_email non-empty AND mail enabled), and
`social_links` object `{website, mastodon, x, bluesky}` (strings, "" when unset).

### `GET /api/v1/instance/about` (new, public, unauthenticated)

Response (raw markdown strings, "" when unset):
`{description, terms, code_of_conduct, moderation_info, administrator_info, creation_reason,
maintenance_lifetime, business_model, hardware_info, support_text}`.

### `POST /api/v1/instance/contact` (new, public)

Request: `{from_name (1..120), from_email (valid email ≤254), subject (1..120), body (10..5000)}`.
- 409 (error code `contact_form_disabled`) when effective availability is false (toggle off, no
  contact email, or mail not enabled).
- 422 validation errors via the standard FieldError path.
- Rate limit: dedicated fixed-window limiter, 1 request per IP per hour (new server option following
  the authRateLimit pattern; use existing ratelimit package). 429 + Retry-After on deny.
- On success: 202, sends mail to effective `contact_email`.
- Mailer: add `SendContactForm(ctx, to, fromName, fromEmail, subject, body)` to the `auth.Mailer`
  interface; implement in SMTP (set Reply-To: from_email; sanitize headers like existing sends),
  noopMailer, and CaptureMailer. Do not log body/emails.

### Video sensitive flag

- Migration `0082_video_sensitive.up.sql`/`.down.sql`: `ALTER TABLE videos ADD COLUMN is_sensitive
  BOOLEAN NOT NULL DEFAULT false`.
- sqlc: update queries touching video rows as needed; `make sqlc` + commit sqlcgen.
- Create/upload + update video DTOs accept optional `is_sensitive` bool; all video responses include
  `is_sensitive`.
- Enforcement: when effective `sensitive_content_policy == "hide"`, exclude `is_sensitive` videos
  from the PUBLIC browse/list and search endpoints only (owner studio listings, admin surfaces, and
  direct watch-by-id stay unfiltered). Other policies are presentation-only (frontend).
- OpenAPI for all of the above (openapi-verify gate). Tests: settings kinds (enum/list validate +
  round-trip), /instance extension, /instance/about, contact (disabled→409, valid→202 via capture
  mailer, rate-limit→429), hide filtering.

`make ci` must pass in vidra-core.

## Frontend contract (vidra-user)

### Markdown infra
New dep: `react-markdown` + `remark-gfm` (no raw HTML — do NOT add rehype-raw; default sanitization
stance). Wrapper `components/Markdown.tsx`, token-driven typography (no `dark:`, no hex). Unit test.

### `/admin/config` redesign (AdminInstanceConfigView.tsx)
Fix current issues: input/card overflow, "Default" badge clutter under every label. Badge treatment:
show a badge ONLY when overridden (accent "Overridden" + "Reset to default" action); default state
shows nothing. Keep partial-PATCH save, dirty tracking, 422 field mapping.

New/updated groups (order):
1. ADMINISTRATORS — "Admin email" (`contact_email`), "Enable contact form" (`contact_form_enabled`).
2. PLATFORM — Name, "Short description" (`instance_short_description`, Textarea), "Description"
   (`instance_description`, Textarea + markdown Preview button), "Default language" (Select from
   `getVideoConfigCached().languages`), "Main instance categories" (multi-select from taxonomy
   categories), "Main languages you/your moderators speak" (multi-select), "Server country" (Select
   from new `lib/countries.ts` ISO-3166 name list; stores the name string).
3. SOCIAL — "Support text" (`support_text`, Textarea + Preview), "External link" (`website_link`),
   "Mastodon link", "X link", "Bluesky link".
4. MODERATION & SENSITIVE CONTENT — "This instance is dedicated to sensitive content"
   (`instance_is_sensitive` Toggle), "Policy on videos containing sensitive content"
   (`sensitive_content_policy` SegmentedControl: Hide / Warn / Blur / Display), "Terms" (`terms`,
   Textarea + Preview), "Code of conduct" (Textarea + Preview), "Moderation information" (Textarea +
   Preview). Keep `quarantine_new_uploads` here.
5. YOU AND YOUR PLATFORM — the four PeerTube questions (each Textarea + Preview):
   `administrator_info`, `creation_reason`, `maintenance_lifetime`, `business_model`.
6. OTHER INFORMATION — "What server/hardware does the instance run on?" (`hardware_info`).
7. REGISTRATION and FEATURES groups: keep, restyled consistently.
Markdown preview = Modal (variant dialog) rendering `<Markdown>`; one shared preview mechanism.
Multi-select: token-conformant checkbox dropdown or checkbox list (no new UI library).
List values: draft state supports `string | boolean | string[]`; PATCH sends JSON arrays.
Legacy fields `terms_url`/`privacy_url` remain (Instance identity/Platform group).

### `/about` page (InstanceAboutView.tsx rewrite, PeerTube structure)
Data: `api.getInstance()` + new `api.getInstanceAbout()`. Sub-nav (Tabs primitive or anchor
sections), sections hidden when ALL their fields are empty:
- General: instance name + short description header; Contact button (opens contact modal; only when
  `contact_form_enabled`) + Support button (modal with `support_text` markdown; only when set);
  badges for categories + languages (resolve labels via video-config taxonomy); "\<name\> is
  dedicated to sensitive content." notice when `is_sensitive`; "Description" (markdown); "Terms"
  (markdown `terms`, plus external `terms_url`/`privacy_url` links when set); server country line
  when set. Social links row (website/Mastodon/X/Bluesky) — add needed icons to
  `components/icons/index.tsx` (single source; no ad-hoc SVG, no emoji).
- Team: "Who we are" (`administrator_info`), "Why we created \<name\>" (`creation_reason`), "How long
  we plan to maintain \<name\>" (`maintenance_lifetime`), "How we will pay for keeping \<name\>
  running" (`business_model`).
- Moderation and code of conduct: `moderation_info`, `code_of_conduct`.
- Technical information: `hardware_info`, software version, features (existing `features` object),
  federation status (keep existing content).
Contact modal: name/email/subject/body form → `POST /api/v1/instance/contact`; map 422 field errors;
friendly copy for 409 (disabled) and 429 (one message per hour).

### Sensitive content presentation
`VideoCard` (and equivalents): when `video.is_sensitive` and effective policy is `blur` → blurred
thumbnail + "Sensitive" badge; `warn` → badge only; `display` → nothing (hide is server-side).
Watch pages: for blur/warn, a confirmation scrim ("This video contains sensitive content") before
playback. Upload/edit forms (StudioView): "Contains sensitive content" Toggle → `is_sensitive`.
Per-user policy override: OUT OF SCOPE (follow-up).

### Nav
Verify the About link renders pinned at the bottom of the left Sidebar for both guests and
logged-in users (exists at Sidebar.tsx ~:104); keep label "About". Add an e2e assertion if missing.

### Types & tests
After backend lands: `npm run codegen` (sibling spec) + aliases in `lib/api/types.ts` + endpoint fns
`getInstanceAbout`, `contactInstance` in `lib/api/endpoints.ts`. Update mocked e2e
(`admin-config.spec.ts`, `about.spec.ts`) to the new structure; add contact-form + markdown-preview
coverage; unit tests for Markdown + countries module. `npm run ci` must pass.

## Notes
- No video-level sensitive flag existed before this change; per-user NSFW preference is follow-up.
- Header wordmark stays static (not instance name) — unchanged in this scope.
- Design authority: vidra-user/.ralph/specs/design-system.md (tokens only, shape language, icons
  single-source, SegmentedControl for single-select).

## Implementation status

Ralph wave, 2026-07-09:

- Backend implementation is on `vidra-core/main` at `584807b`
  (`feat(core): implement instance platform info backend`).
- Frontend implementation is on `vidra-user/main` at `b41850e`
  (`feat(user): implement instance platform info UI`).
- Root spec update is on `vidra/main` at `1d7c187`
  (`docs(ralph): add instance platform info spec`).
- Follow-up CI hardening: `vidra-user` `contract-ci` was updated to checkout
  `yegamble/vidra-core` with `actions/checkout` instead of anonymously fetching
  `raw.githubusercontent.com`, after GitHub returned HTTP 429 during the contract
  gate. Local contract verification passed against `../vidra-core/api/openapi.yaml`.
- Follow-up backed-e2e hardening: `e2e-backed/instance-settings.spec.ts` was
  updated from the pre-redesign `Instance identity`/`Instance name` selectors to
  the current `Platform`/`Name` admin config UI. Local real-backend verification
  passed: `E2E_API_URL=http://localhost:8080 npm run e2e:backed --
  e2e-backed/instance-settings.spec.ts` (3 passed).
- Playwright design guardrails for the frontend passed locally on Chromium:
  `e2e/a11y.spec.ts`, `e2e/responsive.spec.ts`, `e2e/about.spec.ts`,
  `e2e/admin-config.spec.ts`, and `e2e/sensitive-content.spec.ts`.
