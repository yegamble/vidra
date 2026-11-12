# sizetube.com cutover — tracked checklist (living)

A working checklist for cutting `sizetube.com` over from PeerTube to the Vidra beta
(`beta.sizetube.com`, v0.7.19 = core `e6d83aa4`, user `ef1cb9c6`, search `baa6d74f`, deployed
2026-11-11 22:20 UTC; **v0.7.20 is released and recorded, 2026-11-12, and not yet deployed to
the beta**). It tracks **execution status**; the reasoning, evidence and decisions
live in the audit ([`sizetube-cutover-2026-11.md`](sizetube-cutover-2026-11.md)) and the run
record ([`sizetube-beta-migration-2026-11.md`](sizetube-beta-migration-2026-11.md)). When an
item here and the audit disagree, fix one of them in the same change — do not let them drift.

Update an item's status and date in the same commit that changes the fact. Keep the IDs
(`Dx`, `finding n`, `§x.y`) so every line ties back to the audit.

**Owners:** `OPERATOR` = a live prod / droplet / DNS / provider action (I will prepare, not
run). `LAWYER` = counsel. `AGENT` = code or an in-repo artifact I can produce. `WATCHER` = a
read-only monitor (none is running today: the queue watcher stopped 2026-11-08 09:34 UTC).

**Status:** `[ ]` open · `[~]` in progress / prepared-but-not-applied · `[x]` done (dated).

**Last status re-read: 2026-11-12 10:20–10:31 UTC, read-only.** Sources: the beta's public
API; its env file with secrets shown only as set or empty; its database in a read-only
session; the Caddy certificate directory; DNS; Backblaze bucket and key listings; prod's
public API. Nothing was changed anywhere. Evidence tags: `RUNTIME` = observed in that re-read
unless another date is given; `CODE` = read in the released source; `RECORD` = taken from the
run record or an earlier session, not observed again; `DEDUCED` = inferred. What is still not
checked is listed in section H.

**Rehearsed 2026-11-12 11:14–13:07 UTC** on a throwaway droplet built from that morning's beta
backup, with mail removed and its own secrets: window steps 1–5, the rollback, and one
read-path load check. Results are in section G and under each step in section C. The droplet,
its firewall and its temporary storage key were removed the same day; nothing on prod or the
beta was changed. `REHEARSAL` = observed in that run.

---

## A. Blocker — nothing ships until this clears

- [ ] **D15 · Compliance intake (five questions) — `LAWYER`.** Two BLOCKERs inside it:
  (a) NSFW catalogue plays for anonymous visitors with no age assurance (12,401 of 15,508
  videos `is_sensitive`; only `hide` is server-enforced); (b) signup records no terms/privacy
  consent (`INSTANCE_TERMS_URL` / `INSTANCE_PRIVACY_URL` empty). Plus HIGH: GDPR Art 13/14
  notice to 5,538 imported users, missing `List-Unsubscribe`, no non-user abuse/DMCA path.
  See audit §8. *Blocks the whole window.*
  **Still open 2026-11-12.** No answer is recorded. On the beta `terms_url` and `privacy_url`
  are empty, `sensitive_content_policy=display`, `registration_minimum_age=0`; the counts are
  unchanged at 12,401 of 15,508 (RUNTIME).
  Code needed whichever way counsel answers — **built and released in v0.7.20, 2026-11-12;
  not yet deployed to the beta.** Both pieces are CODE, covered by their PRs' tests; neither
  has run on the beta. What exists (engineering guidance, not legal advice):
  - *Signup consent record* (core #545–#549, user #470). Migration `0189` adds `user_consents`
    (document `terms` / `privacy` / `age`, the operator's version label, URL, source,
    accepted-at; append-only by trigger; removed with the account). While `terms_url` or
    `privacy_url` is set, `POST /auth/register` without `terms_accepted` is a 422 and no
    account is created; the approval queue keeps the applicant's acceptance and its time; a
    first sign-in through OIDC or ATProto without it returns `oauth_error=terms_required`;
    an existing account is never asked. The record is in the account export. New settings
    `terms_version` / `privacy_version` (Admin → General → About). **Does nothing until the
    two URLs are set**, which is still the case on the beta. Not built: asking the existing
    5,541 accounts to accept on their next sign-in (the `reaccept` source exists for it).
    Also found: a provider signup is not asked for the age attestation the form requires.
  - *Sign-in wall for sensitive videos* (core #550, #551, user #471). Setting
    `sensitive_anonymous_access`: `open` (default, today's behaviour) or `sign_in` (Admin →
    General → Moderation). With `sign_in`, every read of a sensitive video by a visitor
    without an account answers 401 `sign_in_required` (detail, embed policy, captions,
    chapters, downloads, poster, storyboard, HLS, original), its bytes are no longer sent to
    the CDN, RSS / podcast / sitemap / oEmbed leave it out, and a listed card carries
    `sign_in_required` and no poster. Switching it on is refused while CDN delivery is on
    with no purge endpoint; with one, the response says to purge the CDN zone. **Shipped
    `open`.** A sign-in wall, not age verification. Not covered: the IPFS mirror (a gated
    video's CIDs stay on a public gateway), and playlist item cards.
  The scoping notes of 2026-11-11 that this replaced:
  - *Signup consent record.* The only consent field signup sends is `age_attestation`, which
    the api checks and does not store (CODE core `e6d83aa4`
    `internal/httpapi/auth.go:100-103,358`; user `ef1cb9c6`
    `components/auth/SignupForm.tsx:133`). Needs an additive migration for a
    consent record, `terms_accepted` on every registration path, the record in the account
    export, and an unticked checkbox with live links. One core PR, one user PR, one release.
  - *Anonymous gate for sensitive videos.* Only `hide` is enforced, and only on browse,
    search, RSS and the sitemap; a direct watch page is never filtered and `warn` / `blur` are
    browser-only (CODE `internal/httpapi/instance.go:699-706`). Needs a separate anonymous
    policy enforced where `internal` privacy is (`videos.go:1866-1890`), with gated videos off
    the publicly cached CDN path. Larger than the consent record. Switched on, it makes 12,401
    of 15,508 videos sign-in-only for visitors. The age-verification vendor, per-region
    routing and wording wait for counsel.

## B. Gates before the window (§5 step 0)

- [x] **D12 · `MEDIA_GC_ENABLED=false`** — applied 2026-11-08 02:55 UTC, kept off through the
  rollback window. `OPERATOR`. Still `false` in the env file and in the running api container
  (RUNTIME 2026-11-12).
- [x] **10.5 · Post-import restore drill + `verify-blobs`** — PASS 2026-11-08 03:34 UTC
  (RTO ≈ 45 s DB / ≈ 5 min with blob check). `OPERATOR`. *Re-drill on the final pre-cutover
  dump before T0 — see F.*
- [x] **D16 · Prod transcode backlog drains, then move + publish the state-8 pair**
  (`6f2fdd7e`, `892d1947`) — done 2026-11-09: queue read empty at 06:03 UTC; the pair moved
  to object storage 06:13–06:17 UTC, both state 1 with 0 local files and 8 in the bucket
  (RECORD). `OPERATOR`. **Not re-read since:** the watcher stopped 2026-11-08 09:34 UTC and
  uploads after 2026-11-09 may have refilled the queue. Read it again before the freeze
  (needs prod SSH — section H).
- [~] **D4 · Mail (Resend, HTTPS API via Admin → Email).** Done 2026-11-09: domain verified,
  key sealed in Admin → Email, one test message delivered (RECORD). Confirmed 2026-11-12: the
  DKIM record and both Resend CNAMEs resolve, the saved transport is `resend` with its secret
  set, and the instance reports `features.mail=true` (RUNTIME). **Open:** a password-reset
  mail to an imported account. None has been requested on the beta: `password_reset_tokens`
  has no rows (RUNTIME; whether used rows are purged was not checked). `OPERATOR`.
- [~] **Finding 10 · White-label on.** `branding_hide_software_name=true` since 2026-11-11
  14:28 UTC (RUNTIME). **Open:** the imagery — avatar, banner, favicon, both header logos and
  OpenGraph are all still the fallback, and no instance image is stored (RUNTIME). Set them in
  Admin → General → Branding. Survives deploys and the flip. `OPERATOR`.
- [~] **D5 · `profile_public` for imported accounts.** Audited one-off `UPDATE` prepared with
  dry-run counts in the private `cutover-prep/`; **not applied** — the dry-run still counts
  5,538 imported accounts, none public (RUNTIME 2026-11-12). Needs backup + approval.
  `OPERATOR`. (Alt: importer fix + release — see audit D5.)
- [~] **D7 · Block the remaining 289 media-less published videos** via `video_blocks` (394 of
  683 already blocked; all one inactive owner, all private). SQL prepared, **not applied** —
  the dry-run still counts 289 of 683 (RUNTIME 2026-11-12). `OPERATOR`.
- [ ] **D6 · New-signup policy applied:** registration open with e-mail verification,
  `registration_minimum_age=18`, terms/privacy acceptance first, `INSTANCE_DEFAULT_QUOTA_BYTES=0`.
  **Nothing applied** (RUNTIME 2026-11-12): registration off, e-mail verification off,
  minimum age 0, quota `5368709120`. The acceptance step needs code — the consent record under
  D15. `OPERATOR` + `AGENT`.
- [ ] **Anonymous-NSFW policy decided + applied** (`display` vs `hide`/`warn`/`blur` + login)
  pending D15. Still `display`, last set 2026-11-06 (RUNTIME 2026-11-12). `OPERATOR`.
- [~] **Instance metadata set.** Contact e-mail set in Admin → General on 2026-11-09 and
  served by the instance (RUNTIME). **Open:** terms and privacy URLs, both empty (RUNTIME
  2026-11-12); they wait for counsel's texts. `OPERATOR`.
- [x] **D13 · Record the proven imported-account login** (account + date) in the private log.
  Done 2026-11-12 12:17 UTC: the operator named an imported moderator account and signed in
  with its existing PeerTube password on the first attempt, typing it into a browser pointed
  at the rehearsal copy (REHEARSAL; account and time are in the private log). The copy was
  restored from the beta's 2026-11-12 03:26 UTC backup and ran the same release, so the
  password hash and the code are the beta's. It was not repeated on the beta itself.
  `OPERATOR`.
- [ ] **D3 prerequisite · Origin CA cert for `sizetube.com`** on the droplet and
  `VIDRA_SKIP_DNS_PREFLIGHT=1` in the env file (Cloudflare-proxied path). **Neither is there**
  (RUNTIME 2026-11-12): the certificate directory holds only the `cdn-beta` pair, the key is
  absent from the env file, and the origin refuses a TLS handshake for `sizetube.com`.
  `OPERATOR`.
  **When issuing it, name `sizetube.com` only** (REHEARSAL 2026-11-12). Cloudflare's form
  pre-fills `*.sizetube.com` as well. With a wildcard certificate loaded, Caddy logged
  "skipping automatic certificate management because one or more matching certificates are
  already loaded" for `beta.sizetube.com` and served the loaded certificate on that name. On
  the beta that would replace the Let's Encrypt certificate on the DNS-only `beta.` redirect
  with one browsers do not trust. The existing `cdn-beta` certificate is single-name (RUNTIME).
- [ ] **Read-path capacity — found 2026-11-12; fix released in v0.7.20, not deployed, not
  re-measured end to end.** Three anonymous endpoints take
  about a second each with nobody else on the box, and a repeat call costs the same:
  `GET /api/v1/videos?sort=trending` 1.1–1.2 s, `GET /api/v1/videos/search` 0.5–0.7 s,
  `GET /api/v1/recommendations/home` 0.5–0.7 s (RUNTIME 2026-11-12, the beta itself, one
  request at a time; every other path a page uses answers in 0.1 s or less). Under load the
  database is what runs out (section G). Either make those three cheaper (`AGENT`, then a
  release) or accept the measured ceiling for the window (`OPERATOR`). Prod's real peak is
  still unknown (section H), so how close that ceiling is cannot be said.
  Operator decision 2026-11-12: a plan to make the three cheaper first; no code before the
  plan is approved.
  **Explained and fixed in code, 2026-11-12** (plan approved the same day). Read-only
  `EXPLAIN (ANALYZE, BUFFERS)` on the beta (RUNTIME): the list built all 13,776 public rows to
  keep 20 and counted them again in a second statement (246 ms); 10,702 of the 13,792 public
  rows are sensitive and each called a policy function the planner cannot inline (about 190 ms
  per statement); trending used numeric `power()` (about 350 ms; the home rail's 426 ms is the
  same expression in vidra-search); JIT compiled each statement (74–94 ms). v0.7.20 changes:
  statements for the anonymous unfiltered feed (core #542), the per-row costs (#539, search
  #103), a 15-second shared cache for anonymous lists, search totals and the home rail, with
  publish, edit, delete and block effective at once (#540, #543, #544), and `jit=off` for the
  bundled Postgres (meta #379; the first deploy that carries it restarts Postgres once).
  The new statements on the beta's data, by EXPLAIN only (RUNTIME): recent page 5 ms (was
  467), trending 56 ms (was 807), the total 15 ms (was 246), search total 56 ms with JIT off
  (was 334). On a 15,000-video fixture (Apple M2, PostgreSQL 18.6, each call = list + total):
  trending 932.7 → 70.2 ms with JIT on and 378.3 → 27.7 ms with it off; a cached call is under
  0.02 ms. **Not established:** the endpoints' real response times on the beta (v0.7.20 is not
  deployed there) and the 270-page-views-a-minute target (the load ladder has not been
  rerun). The cache is per process; a second api container would need shared invalidation.
  Signed-in callers and filtered lists still run the general statement.
- [x] **This checklist + the audit merged to `main`** — #369, 2026-11-10. `AGENT`.
- [~] **Ads parity.** Prod earns from HilltopAds + ExoClick through a PeerTube custom script,
  a PHP anti-adblock file and the `vast-ads` plugin (still registered on prod, RUNTIME
  2026-11-12); none of it carries over by itself. Two tracks.
  **Display and popunder** (HilltopAds, ExoClick banners). Done: the vidra-core ad proxy
  (core #530, #531, #536) and the frontend policy switches `CSP_ALLOW_EVAL` / `CSP_FRAME_SRC`
  / `CSP_ALLOW_INLINE_EVENT_HANDLERS` (vidra-user #465, passthrough #371), all in v0.7.17 and
  applied on the beta 2026-11-10; the ported custom script installed in Admin → Advanced →
  Custom JavaScript on 2026-11-10 17:47 UTC. Confirmed 2026-11-12 (RUNTIME): the installed
  script's SHA-256 equals the prepared `cutover-prep/ads-custom.js` less its final newline;
  the provider path returns JavaScript through Caddy; the enforced page policy carries all
  three allowances. **Open:** real ad fill and a real blocker on the six formats.
  **In-player VAST** (replaces the `vast-ads` plugin). Done: core #537 and vidra-user #466 in
  v0.7.18, the progress-beacon fix vidra-user #467 in v0.7.19; pre-roll, mid-roll and
  post-roll tags are set and enabled on the beta (RUNTIME 2026-11-12). Checked on the beta
  2026-11-11 (RECORD, that day's session): pre-roll, skip, mid-roll at 300 s repeating every
  60 s, post-roll, embed on and off, cooldown; one filled pre-roll sent its five ExoClick view
  beacons once each, HTTP 200. **Open:** mid-roll and post-roll beacons, and the ExoClick
  dashboard showing the impressions.
  The script's consent and Global Privacy Control defaults are the cautious ones and belong
  to D15. `OPERATOR` (admin).

### D12 media-DR tail (open, not all window-blocking)

All four re-read 2026-11-12 and all four still open.

- [ ] B2 replication **or** Object Lock to a separate account. Neither bucket replicates and
  file lock is off on both (RUNTIME). `OPERATOR`.
- [ ] A media key **without** `deleteFiles`. The key the beta runs with still carries it
  (RUNTIME). `OPERATOR`.
  Such a key protects less than its name suggests (REHEARSAL 2026-11-12): the api's own
  storage probe hid its test object with a key that had no `deleteFiles`, because hiding and
  overwriting need only `writeFiles`. Nothing is destroyed, but a hidden or overwritten
  object stops being served until someone with a delete-capable key removes the marker or
  the newer version, and only while no lifecycle rule has cleared the old versions.
- [ ] `HEALTHCHECKS_URL` in `/etc/vidra/backup.env` (silent on failure today). Absent: the
  file sets only the rclone remote and config path. The nightly backup itself last succeeded
  2026-11-12 03:26 UTC (RUNTIME). `OPERATOR`.
- [ ] Clear the 11 stranded B2 unfinished large files (427.6 MB, 2026-11-05). Still 11
  (RUNTIME). `OPERATOR`.

## C. The cutover window (§5 steps 1–7)

Not started on prod or the beta. Steps 1–5 and the rollback in step 7 were rehearsed on a
throwaway copy on 2026-11-12; what each showed is under the step. Measured times are in G.

- [ ] **1 · Freeze prod (D2):** nginx returns 503 for non-GET/HEAD on `/api/v1/`; verify a
  write is refused; record T0. Snippet prepared in `cutover-prep/`. `OPERATOR`.
  The prepared snippet is wider than that wording: it refuses every request that is not
  GET, HEAD or OPTIONS on the whole site, so logins, view pings and the ActivityPub inbox
  answer 503 too (read 2026-11-12). That is what a consistent snapshot needs; expect it.
  **The first prepared snippet does not load** (REHEARSAL 2026-11-12): `nginx -t` rejects it
  with `"add_header" directive is not allowed here`, because a server-level `if` may hold only
  rewrite directives. The reload would never have happened: no outage, but no freeze either.
  The corrected snippet (the `if` only returns 503; the headers are added in a named location
  reached through `error_page 503`) passed all 26 checks on a throwaway nginx: POST, PUT,
  PATCH and DELETE on four paths answer 503 with `Retry-After`, GET and HEAD reach the
  upstream, OPTIONS is not refused, and removing or restoring the include line takes effect
  within a second of the reload. It replaced the first one in `cutover-prep/` the same day.
  Not covered: prod's own server block. If that block already sets `error_page 503`, the two
  compete and `nginx -t` will not say so; read `nginx -T` first.
- [ ] **2 · Snapshot (Step 25):** dump → SHA-256 both ends → restore as a new DB → §3 grants →
  swap names; keep the previous snapshot. `OPERATOR`.
  Rehearsed 2026-11-12 with the 2026-11-06 dump: restore into a new database 117 s; grants,
  rename swap and check 4 s. Through the importer's own connection string the reader could
  read, and an `UPDATE` was refused twice: by the read-only default, then by the missing
  grant once that default was switched off. The role's read-only setting followed the rename.
- [ ] **3 · Hostname flip on the beta:** `backup.sh` → env (`PUBLIC_BASE_URL`,
  `NEXT_PUBLIC_API_BASE_URL`, `CORS_ALLOWED_ORIGINS` → `https://sizetube.com`;
  `VIDRA_SKIP_DNS_PREFLIGHT=1`) → `vidra setup` → re-add the hand-added Caddy blocks (site
  `sizetube.com`, cdn `Host`, drop the IP gate and `noindex`) → `deploy.sh` → verify
  `/healthz` via `--resolve` and the admin infra `public_base_url`. `OPERATOR`.
  Today all three URLs are `https://beta.sizetube.com` and the hand-edited `Caddyfile.local`
  is unchanged since 2026-11-05 (RUNTIME 2026-11-12).
  Rehearsed 2026-11-12. The command the prepared notes did not spell out is
  `vidra setup --template env/production.env.example --non-interactive --yes`. At v0.7.19 it
  rewrites the env file from the current template (1,576 → 1,621 lines), keeps every value
  and secret, **adds two blank keys** new in the template (`PEERTUBE_IMPORT_S3_COPY_ACCESS_KEY`,
  `PEERTUBE_IMPORT_S3_COPY_SECRET_KEY`) and drops keys whose value is empty, so the env diff
  is the patch plus those two. It regenerates `Caddyfile.local` **without** the hand-added
  parts; the prepared target file differs from its output by 40 added lines and nothing else,
  so it is still valid for this release. `vidra setup --check` passed (103 variables).
  `deploy.sh` took 76 s and **recreated the Caddy container** (the regenerated file is a new
  inode, so the bind mount was stale): a few seconds with no edge, inside the freeze.
  Afterwards `/healthz` answered on `sizetube.com`, the admin infrastructure page reported
  `public_base_url=https://sizetube.com`, the sitemap and the RSS feed carried only the new
  origin (5,143 and 152 occurrences, none of the old), and `beta.sizetube.com` answered 301.
- [ ] **4 · Final rerun:** dry run, then `run` with `source_authoritative=true` (D1); confirm
  `remote_follower.imported=20`, the state-8 pair's HLS, the 8 drafts now `published`, zero
  transient failures; re-run the §9.5 / §9.6 / §9.12 diffs and apply D10 by hand. `OPERATOR`.
  No run has used `source_authoritative=true` yet; `remote_follows` is empty (RUNTIME
  2026-11-12). **Runs between now and the window import nothing new, and that is expected:**
  the importer reads `peertube_source_snapshot`, a copy on the beta's own Postgres restored
  2026-11-06 16:59 UTC, whose newest video is from 11-06 15:06; the beta already holds all
  15,508 of its videos, and the run after the last swap did import the 10 that copy had
  gained. Prod's public API shows 38 public videos created since (RUNTIME 2026-11-12 14:16
  UTC). Step 2 of this window is what refreshes the copy. From v0.7.20 the import report and
  the admin import page show the newest video date in the source (core #541, user #469).
  Prod has moved on since the 2026-11-06 snapshot: its public stats show 5,577
  accounts against 5,539 on the beta.
  Rehearsed 2026-11-12 on the copy, against the 2026-11-06 snapshot. Dry run with
  `source_authoritative=true`: 79 s. It lists planned totals per kind and **does not say what
  a real run will change**. Real run with `source_authoritative=true` and `media_mode=none`:
  334 s, `done`, no failure in any kind; 10 videos and 18,970 playlist entries updated,
  146 playlist entries and 1 follow added, users and channels unchanged.
  **`remote_follower.imported` was 13, not 20**: seven followers' servers did not answer
  ("retried on the next run"). Expect a number below 20 on the day and read the report's
  note rather than failing the step on it.
  **Not rehearsed: the same run in copy mode**, the form the window uses. From a second box
  sharing the beta's bucket it could overwrite objects the beta serves: posters and
  storyboards sit at keys derived from the video id, the importer's writes overwrite, and in
  this mode a poster changed on Vidra since import is replaced (CODE core `e6d83aa4`
  `internal/peertubeimport/importer.go:865`, `entities_videoimages.go`). The operator decided
  against it. Its media part therefore has no measured time: the earlier gap-fill runs on the
  beta took 12–43 min, and each run retries about 9,900 fetches that are known to fail.
- [ ] **5 · Re-accept on the real hostname** via a hosts override: D13 login, reset mail,
  playback (public / private / internal as a permitted user), old links incl. embeds, admin
  pages, a synthetic upload. `OPERATOR`.
  Rehearsed 2026-11-12 from a real browser with the site's names mapped to the copy.
  Passed: sign-in with an imported account's existing password (D13); public playback with a
  seek; a private video (anonymous 404, plays for its owner); an internal video (anonymous
  401 `sign_in_required`, plays signed in); `/w/<short id>`, `/videos/watch/<uuid>`,
  `/videos/embed/<uuid>?start=` and `/video-playlists/embed/<uuid>` (each 302 to a page that
  loads); a synthetic upload (published in about 6 s, plays, found through the search
  service); the ad proxy script, no policy violation, VAST tag requests answered.
  **Still 404, as on 2026-11-08:** `/c/<handle>/videos`, `/channels/<handle>/videos`,
  `/video-channels/<handle>` and `/accounts/<name>`.
  Not rehearsed: the reset mail (the copy had mail removed) and the admin pages beyond the
  infrastructure and import pages. The upload ran as the copy's owner, not as the imported
  account.
- [ ] **6 · DNS:** Cloudflare `sizetube.com` → 159.203.29.27 (proxied, D3). Recheck TLS,
  cookies/CORS, playback, search, old URLs publicly; watch api logs for 429/5xx; then enable
  registration / mail / federation per decisions, each with its own check. `OPERATOR`.
- [ ] **7 · Rollback window (length per D14):** PeerTube frozen-but-running, env pinned at
  the release deployed on the day (v0.7.19 today), both snapshots + dumps kept, source bucket
  untouched, GC still off. Rollback = DNS back + unfreeze + a final `backup.sh`. `OPERATOR`.
  The beta's side of a rollback was rehearsed 2026-11-12 on the copy: `restore.sh` with the
  pre-flip backup 340 s including its media existence pass (every referenced object
  present), the saved env and `Caddyfile.local` back, `deploy.sh` 91 s: about 7 minutes.
  Everything written after the backup was gone (13 remote follows, the test upload, two
  import runs), and 163 of 165 tables had exactly the row counts the backup held; the other
  two are written by the apps as they start.

## D. Post-window cleanup (after the rollback window)

- [ ] `PEERTUBE_IMPORT_ENABLED=false`; drop `pt_import_reader` and both snapshot DBs; delete
  the read-only B2 key. `OPERATOR`.
- [ ] Re-enable GC only after a dry-run sweep reads 0 unexpected orphans. `OPERATOR`.
- [ ] Decide the fate of `beta.sizetube.com`, `cdn-beta.sizetube.com` and `cdn.sizetube.com`
  (stays on B2 for rollback). `OPERATOR`.

## E. Decisions — all answered except D15

D1–D14 and D16 were answered 2026-11-08 (audit §6 table). **D15 is the only open decision**
(section A). This checklist tracks their *execution*, not the decisions themselves.

## F. Standing reminders

- Re-drill the restore on the **final** pre-cutover dump (10.5 passed on the 2026-11-08 dump).
- Keep `MEDIA_GC_ENABLED=false` for the entire rollback window.
- A fresh off-site backup immediately before T0.

## G. Rehearsal and load check — run 2026-11-12

- [x] **Dress rehearsal of window steps 1–5 and the rollback** — 2026-11-12 11:14–13:07 UTC
  on a throwaway droplet of the beta's size, built from the beta's 03:26 UTC backup. Mail
  configuration deleted before the api first started; storyboards, registration and GC off;
  new JWT, database and Redis secrets; no backup remote; a firewall admitting one address;
  a temporary storage key without `deleteFiles`. `AGENT` ran, `OPERATOR` approved and typed
  one password. Per-step results are in section C.
  **Measured machine time** (REHEARSAL): freeze reload, seconds · snapshot restore, grants,
  swap and check 121 s · backup 33 s · env patch, `vidra setup`, hand-added Caddy parts and
  `--check`, seconds of commands · deploy 76 s · dry run 79 s · authoritative rerun without
  media 334 s · acceptance driver about 3.5 min. **About 15 minutes for steps 2–5.**
  **Not in that figure:** the prod dump and its transfer (the dump took about 5 min on
  2026-11-06); the media part of the rerun in copy mode (12–43 min on earlier gap-fill runs,
  never run in authoritative mode); reading results and typing; the Origin CA certificate;
  Cloudflare and DNS. So the earlier 75–125 min freeze-to-DNS estimate is narrowed, not
  replaced: the rerun's media part is still the unknown that dominates it.
  **Rollback:** about 7 minutes (section C, step 7).
  **Found:** the freeze snippet did not load (C1, fixed); the Origin CA certificate must be
  single-name (B, D3); `vidra setup` adds two keys and the deploy recreates Caddy (C3); the
  dry run does not show what will change, and 13 of 20 remote followers were reachable (C4);
  four old channel and account URL forms still 404 (C5); a key without `deleteFiles` can
  still overwrite and hide (B, D12 tail).
  **What it touched outside itself:** public GETs only: follower profiles on 12 other
  servers and a handful to prod's public site. In the beta's media bucket: one test upload
  (27 object versions, 13.6 MB) and about 20 hidden 62-byte write probes, listed in the
  private log. A listing of
  every version written to that bucket during the run shows nothing else from the
  rehearsal: none of the beta's own objects was overwritten or hidden. Removing the test
  objects needs a delete-capable key; the operator decided on 2026-11-12 to leave them.
  **It could not rehearse** the real Origin CA certificate, Cloudflare in front, the DNS
  change, prod's own nginx config around the freeze snippet, or the reset mail.
- [x] **One read-path load check — run 2026-11-12; FAILED at the estimated peak.** `AGENT`.
  Method: anonymous page views replayed from a browser recording, about 25 requests each
  (1 page, about 10 api calls, about 15 thumbnails; watch pages add playlists and three
  media segments), every view under its own visitor address so the per-address limit sees
  many visitors. One generator on a home line; no Cloudflare in front, so thumbnails and
  media are heavier than they will be.
  Sizing: prod's request rate is unknown (section H). "1×" is the page rate at which this mix
  produces prod's 68.7 Mbps bandwidth peak: **270 page views a minute**. Its 7.1 Mbps average
  is 28 a minute; prod reports 318 daily active accounts.

  | Page views / min asked | Completed | Page p50 / p95 | Api p50 / p95 | Timeouts |
  |---|---|---|---|---|
  | 30 | 32 | 0.35 / 1.42 s | 0.08 / 0.72 s | 0 |
  | 58 (90 s, caches cold) | 58 | 0.40 / 1.77 s | 0.08 / 0.57 s | 0 |
  | 90 | 95 | 0.58 / 2.88 s | 0.12 / 1.06 s | 0 |
  | 120 | 115 | 1.27 / 3.71 s | 0.21 / 1.93 s | 0 |
  | 150 | 140 | 1.15 / 3.23 s | 0.20 / 1.85 s | 0 |
  | **270 (1×)** | **74** | over 60 s | over 60 s | **15,358** |

  The 270 row ran 10 minutes, the others 3 unless marked. Passing needed page p95 ≤ 1.5 s and
  api p95 ≤ 0.4 s at 1×. At 1× the box completed 74 of 270 page views a minute, 15,358
  requests timed out at 30 s and 1,893 views were still waiting at the end; Postgres held all
  8 vCPUs, running the public video list, its count and the search count. **3× was not run.**
  No 5xx, no container restart, and no visitor other than the deliberately over-limit one
  was rate-limited at any level: the limiter does key on the visitor's own address behind a
  trusted proxy, which had not been shown before.
  Reading: the box keeps up to roughly 120–150 page views a minute with page p95 near 3 s,
  and falls over between 150 and 270. The api p95 limit is missed at every level because of
  the three slow endpoints (section B, read-path capacity).
  Also measured: a page view makes 19–31 requests under `/api/v1` (7–20 of them thumbnails),
  not the 8.4 the parity QA recorded; thumbnails average 137 KB.
  Limits: the 1× figure is an estimate from bandwidth, not prod's measured peak; ladder steps
  were 3 minutes; latencies include the generator's own line.

## H. What is still not checked (after the 2026-11-12 re-read and rehearsal)

- **Prod's transcoding queue now, and prod's real request rate.** Both need read-only SSH to
  prod, which the operator declined on 2026-11-12. D16 therefore rests on the 2026-11-09
  reading, and the load check's "1×" is an estimate (section G).
- **The final rerun in copy mode with `source_authoritative=true`.** Never run anywhere
  (section C, step 4).
- **The admin infrastructure page on the beta.** Read on the rehearsal copy only; on the beta
  `public_base_url` was read from the running api container's environment.
- **Whether counsel has answered D15.** The operator's to supply.
- **What `www.sizetube.com` should do.** It answers 526 today (public GET 2026-11-12) and the
  prepared Caddy file has no `www` block, so it stays broken after the cutover unless one is
  added. No decision covers it.
- **Ads:** real fill and a real blocker on the six display formats; mid-roll and post-roll
  beacons; the ExoClick dashboard.
- **Why three more import runs happened on 2026-11-10** (14:13, 16:33 and 19:24 UTC, started
  by the owner; the last with conflict policy `merge`). What they did is known: each ended
  `done` with nothing imported or updated, and the same failure sets as the 2026-11-08 run
  (HLS 687, captions 669, thumbnails 683, one video, and storyboards with a missing source
  image, falling 8,082 → 7,983 → 7,861). The "imported 687" in the 16:33 run's audit line is
  the media-less-video counter, not new content (RUNTIME 2026-11-12).
