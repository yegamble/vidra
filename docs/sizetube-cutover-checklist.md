# sizetube.com cutover — tracked checklist (living)

A working checklist for cutting `sizetube.com` over from PeerTube to the Vidra beta
(`beta.sizetube.com`, v0.7.19 = core `e6d83aa4`, user `ef1cb9c6`, search `baa6d74f`, deployed
2026-11-11 22:20 UTC). It tracks **execution status**; the reasoning, evidence and decisions
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
run record or an earlier session, not observed again; `DEDUCED` = inferred. What the re-read
could not check is listed in section H.

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
  Code needed whichever way counsel answers — **scoped 2026-11-11, not built**; whether to
  build ahead of the answers is the operator's call (engineering guidance, not legal advice):
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
- [ ] **D13 · Record the proven imported-account login** (account + date) in the private log.
  Not in the run record. Supporting evidence only: one imported account holds 92 sessions on
  the beta, all from 2026-11-06 02:24–05:01 UTC (RUNTIME 2026-11-12; counts only, the account
  was not read). That shows a sign-in, not which password proved it. `OPERATOR`.
- [ ] **D3 prerequisite · Origin CA cert for `sizetube.com`** on the droplet and
  `VIDRA_SKIP_DNS_PREFLIGHT=1` in the env file (Cloudflare-proxied path). **Neither is there**
  (RUNTIME 2026-11-12): the certificate directory holds only the `cdn-beta` pair, the key is
  absent from the env file, and the origin refuses a TLS handshake for `sizetube.com`.
  `OPERATOR`.
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
- [ ] `HEALTHCHECKS_URL` in `/etc/vidra/backup.env` (silent on failure today). Absent: the
  file sets only the rclone remote and config path. The nightly backup itself last succeeded
  2026-11-12 03:26 UTC (RUNTIME). `OPERATOR`.
- [ ] Clear the 11 stranded B2 unfinished large files (427.6 MB, 2026-11-05). Still 11
  (RUNTIME). `OPERATOR`.

## C. The cutover window (§5 steps 1–7)

Not started. None of these has been rehearsed on this data yet — see G.

- [ ] **1 · Freeze prod (D2):** nginx returns 503 for non-GET/HEAD on `/api/v1/`; verify a
  write is refused; record T0. Snippet prepared in `cutover-prep/`. `OPERATOR`.
  The prepared snippet is wider than that wording: it refuses every request that is not
  GET, HEAD or OPTIONS on the whole site, so logins, view pings and the ActivityPub inbox
  answer 503 too (read 2026-11-12). That is what a consistent snapshot needs; expect it.
- [ ] **2 · Snapshot (Step 25):** dump → SHA-256 both ends → restore as a new DB → §3 grants →
  swap names; keep the previous snapshot. `OPERATOR`.
- [ ] **3 · Hostname flip on the beta:** `backup.sh` → env (`PUBLIC_BASE_URL`,
  `NEXT_PUBLIC_API_BASE_URL`, `CORS_ALLOWED_ORIGINS` → `https://sizetube.com`;
  `VIDRA_SKIP_DNS_PREFLIGHT=1`) → `vidra setup` → re-add the hand-added Caddy blocks (site
  `sizetube.com`, cdn `Host`, drop the IP gate and `noindex`) → `deploy.sh` → verify
  `/healthz` via `--resolve` and the admin infra `public_base_url`. `OPERATOR`.
  Today all three URLs are `https://beta.sizetube.com` and the hand-edited `Caddyfile.local`
  is unchanged since 2026-11-05 (RUNTIME 2026-11-12).
- [ ] **4 · Final rerun:** dry run, then `run` with `source_authoritative=true` (D1); confirm
  `remote_follower.imported=20`, the state-8 pair's HLS, the 8 drafts now `published`, zero
  transient failures; re-run the §9.5 / §9.6 / §9.12 diffs and apply D10 by hand. `OPERATOR`.
  No run has used `source_authoritative=true` yet; `remote_follows` is empty (RUNTIME
  2026-11-12). Prod has moved on since the 2026-11-06 snapshot: its public stats show 5,577
  accounts against 5,539 on the beta.
- [ ] **5 · Re-accept on the real hostname** via a hosts override: D13 login, reset mail,
  playback (public / private / internal as a permitted user), old links incl. embeds, admin
  pages, a synthetic upload. `OPERATOR`.
- [ ] **6 · DNS:** Cloudflare `sizetube.com` → 159.203.29.27 (proxied, D3). Recheck TLS,
  cookies/CORS, playback, search, old URLs publicly; watch api logs for 429/5xx; then enable
  registration / mail / federation per decisions, each with its own check. `OPERATOR`.
- [ ] **7 · Rollback window (length per D14):** PeerTube frozen-but-running, env pinned at
  the release deployed on the day (v0.7.19 today), both snapshots + dumps kept, source bucket
  untouched, GC still off. Rollback = DNS back + unfreeze + a final `backup.sh`. `OPERATOR`.

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

## G. Rehearsal and load check — planned 2026-11-11, not run

- [ ] **Dress rehearsal of window steps 1–5 and the rollback** on a throwaway droplet built
  from the beta's latest backup, with mail removed, GC off and a storage key that cannot
  delete. It replaces the 75–125 min freeze-to-DNS estimate with measured times. Waits on the
  operator: approval of the droplet spend and of a temporary storage key, and a working
  `doctl` login (its token is rejected today). `AGENT` runs, `OPERATOR` approves.
  It cannot rehearse the real Origin CA certificate, Cloudflare in front, the DNS change, or
  prod's own nginx config around the freeze snippet.
- [ ] **One read-path load check** against that droplet at 1× and 3× prod's peak. Sized today
  from the 30-day bandwidth figure only (7.1 Mbps average, 68.7 Mbps peak, 2026-11-04);
  prod's real request rate is unknown (section H). `AGENT`.

## H. What the 2026-11-12 re-read could not check

- **Prod's transcoding queue now, and prod's real request rate.** Both need read-only SSH to
  prod, which had not been approved when the re-read ran. D16 therefore rests on the
  2026-11-09 reading.
- **The admin infrastructure page.** No signed-in admin session was available. Its
  `public_base_url` was read from the running api container's environment instead.
- **D13's account and date, and whether counsel has answered D15.** Both are the operator's
  to supply.
- **Ads:** real fill and a real blocker on the six display formats; mid-roll and post-roll
  beacons; the ExoClick dashboard.
- **Why three more import runs happened on 2026-11-10** (14:13, 16:33 and 19:24 UTC, started
  by the owner; the last with conflict policy `merge`). What they did is known: each ended
  `done` with nothing imported or updated, and the same failure sets as the 2026-11-08 run
  (HLS 687, captions 669, thumbnails 683, one video, and storyboards with a missing source
  image, falling 8,082 → 7,983 → 7,861). The "imported 687" in the 16:33 run's audit line is
  the media-less-video counter, not new content (RUNTIME 2026-11-12).
