# sizetube.com cutover — tracked checklist (living)

A working checklist for cutting `sizetube.com` over from PeerTube to the Vidra beta
(`beta.sizetube.com`, v0.7.17 = core `d419f11c` since 2026-11-10). It tracks **execution status**; the
reasoning, evidence and decisions live in the audit
([`sizetube-cutover-2026-11.md`](sizetube-cutover-2026-11.md)) and the run record
([`sizetube-beta-migration-2026-11.md`](sizetube-beta-migration-2026-11.md)). When an item
here and the audit disagree, fix one of them in the same change — do not let them drift.

Update an item's status and date in the same commit that changes the fact. Keep the IDs
(`Dx`, `finding n`, `§x.y`) so every line ties back to the audit.

**Owners:** `OPERATOR` = a live prod / droplet / DNS / provider action (I will prepare, not
run). `LAWYER` = counsel. `AGENT` = code or an in-repo artifact I can produce. `WATCHER` = a
read-only monitor already running.

**Status:** `[ ]` open · `[~]` in progress / prepared-but-not-applied · `[x]` done (dated).

---

## A. Blocker — nothing ships until this clears

- [ ] **D15 · Compliance intake (five questions) — `LAWYER`.** Two BLOCKERs inside it:
  (a) NSFW catalogue plays for anonymous visitors with no age assurance (12,401 of 15,508
  videos `is_sensitive`; only `hide` is server-enforced); (b) signup records no terms/privacy
  consent (`INSTANCE_TERMS_URL` / `INSTANCE_PRIVACY_URL` empty). Plus HIGH: GDPR Art 13/14
  notice to 5,538 imported users, missing `List-Unsubscribe`, no non-user abuse/DMCA path.
  See audit §8. *Blocks the whole window.*

## B. Gates before the window (§5 step 0)

- [x] **D12 · `MEDIA_GC_ENABLED=false`** — applied 2026-11-08 02:55 UTC, kept off through the
  rollback window. `OPERATOR`.
- [x] **10.5 · Post-import restore drill + `verify-blobs`** — PASS 2026-11-08 03:34 UTC
  (RTO ≈ 45 s DB / ≈ 5 min with blob check). `OPERATOR`. *Re-drill on the final pre-cutover
  dump before T0 — see F.*
- [~] **D16 · Prod transcode backlog drains, then move + publish the state-8 pair**
  (`6f2fdd7e`, `892d1947`). Backlog 70 → 61 jobs at last read; `WATCHER` running. Then run the
  approved move script only once their jobs are gone. `OPERATOR`.
- [~] **D4 · Mail (Resend, HTTPS API via Admin → Email).** Account created; **pending**: domain
  DNS records (SPF/DKIM/DMARC for `sizetube.com`), API key into Admin → Email, send + receive
  one test, then prove a password-reset mail arrives. `OPERATOR` (+ `AGENT` for config/env
  wiring and the step-by-step).
- [ ] **Finding 10 · White-label on.** Turn on `branding_hide_software_name` and set instance
  imagery (avatar, banner, favicon, header logos, OpenGraph) in Admin → General → Branding
  (all off / fallback today). Survives deploys and the flip. `OPERATOR`.
- [~] **D5 · `profile_public` for imported accounts.** Audited one-off `UPDATE` prepared with
  dry-run counts in the private `cutover-prep/`; **not applied**. Needs backup + approval.
  `OPERATOR`. (Alt: importer fix + release — see audit D5.)
- [~] **D7 · Block the remaining 289 media-less published videos** via `video_blocks` (394 of
  683 already blocked; all one inactive owner, all private). SQL prepared, **not applied**.
  `OPERATOR`.
- [ ] **D6 · New-signup policy applied:** registration open with e-mail verification,
  `registration_minimum_age=18`, terms/privacy acceptance first, `INSTANCE_DEFAULT_QUOTA_BYTES=0`.
  `OPERATOR` (+ `AGENT` if the consent-capture needs code — ties to D15).
- [ ] **Anonymous-NSFW policy decided + applied** (`display` vs `hide`/`warn`/`blur` + login)
  pending D15. `OPERATOR`.
- [ ] **Instance metadata set:** `INSTANCE_TERMS_URL`, `INSTANCE_PRIVACY_URL`,
  `INSTANCE_CONTACT_EMAIL` (all empty today). `OPERATOR`.
- [ ] **D13 · Record the proven imported-account login** (account + date) in the private log.
  `OPERATOR`.
- [ ] **D3 prerequisite · Origin CA cert for `sizetube.com`** on the droplet and
  `VIDRA_SKIP_DNS_PREFLIGHT=1` in the env file (Cloudflare-proxied path). `OPERATOR`.
- [x] **This checklist + the audit merged to `main`** — #369, 2026-11-10. `AGENT`.
- [~] **Ads parity.** Prod earns from HilltopAds + ExoClick through a PeerTube custom script
  and a PHP anti-adblock file; none of it carries over by itself (the audit's §8 notes the
  `vast-ads` plugin, not this). Three pieces, all needed:
  (a) vidra-core ad proxy for the anti-adblock tag — **done**: core #530, #531 and #536
  (the last one makes a provider path both accepted and reachable through Caddy), in v0.7.17;
  (b) frontend policy switches `CSP_ALLOW_EVAL` / `CSP_FRAME_SRC` /
  `CSP_ALLOW_INLINE_EVENT_HANDLERS` — **done**: vidra-user #465, passthrough and template
  in this repo (#371), in v0.7.17. Measured in headless Chrome against the real tags: the popunder and ExoClick
  need eval, the banners need https frames, ExoClick recommendations need inline handlers;
  under the strict policy the popunder does not run at all;
  (c) the ported custom script, prepared in the private `cutover-prep/ads-custom.js`,
  **not applied**.
  Applied on the beta 2026-11-10: `AD_ANTIADBLOCK_PROVIDERS` (built from the network's PHP
  file by `deploy/ad-provider-from-php.py`) and the three switches in the env file, 16:21
  UTC; v0.7.17 deployed 16:56 UTC. Verified there: the api logs the proxy route as mounted,
  the provider path returns the network's JavaScript through Caddy, and the enforced page
  policy carries all three allowances. No ad is shown yet: that is (c).
  Still to do: paste (c) into Admin → Advanced → Custom JavaScript; then check on the beta
  with real ad fill and a real blocker (neither was exercised). The script's consent and
  Global Privacy Control defaults are the cautious ones and belong to D15. `OPERATOR`
  (admin).

### D12 media-DR tail (open, not all window-blocking)

- [ ] B2 replication **or** Object Lock to a separate account. `OPERATOR`.
- [ ] A media key **without** `deleteFiles`. `OPERATOR`.
- [ ] `HEALTHCHECKS_URL` in `/etc/vidra/backup.env` (silent on failure today). `OPERATOR`.
- [ ] Clear the 11 stranded B2 unfinished large files (427.6 MB, 2026-11-05). `OPERATOR`.

## C. The cutover window (§5 steps 1–7)

- [ ] **1 · Freeze prod (D2):** nginx returns 503 for non-GET/HEAD on `/api/v1/`; verify a
  write is refused; record T0. Snippet prepared in `cutover-prep/`. `OPERATOR`.
- [ ] **2 · Snapshot (Step 25):** dump → SHA-256 both ends → restore as a new DB → §3 grants →
  swap names; keep the previous snapshot. `OPERATOR`.
- [ ] **3 · Hostname flip on the beta:** `backup.sh` → env (`PUBLIC_BASE_URL`,
  `NEXT_PUBLIC_API_BASE_URL`, `CORS_ALLOWED_ORIGINS` → `https://sizetube.com`;
  `VIDRA_SKIP_DNS_PREFLIGHT=1`) → `vidra setup` → re-add the hand-added Caddy blocks (site
  `sizetube.com`, cdn `Host`, drop the IP gate and `noindex`) → `deploy.sh` → verify
  `/healthz` via `--resolve` and the admin infra `public_base_url`. `OPERATOR`.
- [ ] **4 · Final rerun:** dry run, then `run` with `source_authoritative=true` (D1); confirm
  `remote_follower.imported=20`, the state-8 pair's HLS, the 8 drafts now `published`, zero
  transient failures; re-run the §9.5 / §9.6 / §9.12 diffs and apply D10 by hand. `OPERATOR`.
- [ ] **5 · Re-accept on the real hostname** via a hosts override: D13 login, reset mail,
  playback (public / private / internal as a permitted user), old links incl. embeds, admin
  pages, a synthetic upload. `OPERATOR`.
- [ ] **6 · DNS:** Cloudflare `sizetube.com` → 159.203.29.27 (proxied, D3). Recheck TLS,
  cookies/CORS, playback, search, old URLs publicly; watch api logs for 429/5xx; then enable
  registration / mail / federation per decisions, each with its own check. `OPERATOR`.
- [ ] **7 · Rollback window (length per D14):** PeerTube frozen-but-running, env pinned
  v0.7.15, both snapshots + dumps kept, source bucket untouched, GC still off. Rollback = DNS
  back + unfreeze + a final `backup.sh`. `OPERATOR`.

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
