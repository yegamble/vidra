# Program risk register

Live risks that shape sequencing. Review when opening each phase; strike through with a note
when retired.

## Architectural

1. ~~**Frontend origin baking is architectural, not incidental.**~~ **RETIRED — verified
   2026-09-03.** `NEXT_PUBLIC_API_BASE_URL` survives only as the dev/e2e fallback: compose passes
   the value as `PUBLIC_API_BASE_URL` (`vidra-core/docker-compose.yml:76`), which
   `vidra-user/lib/config.ts:68` resolves *first*, served per-request from `/runtime-config.js`.
   It is now a **restart**, not a rebuild, and it is the only `NEXT_PUBLIC_*` in the codebase —
   so no feature flag anywhere in Vidra is build-baked. A non-`http(s)` value is rejected and
   downgraded to same-origin with a logged error rather than throwing on every call
   (`lib/config.ts:20-27`).
2. ~~**First-account-gets-admin race.**~~ **RETIRED — verified 2026-09-03.** Migration 0104 plus
   `vidra-core/internal/auth/ownerclaim.go`: the first admin redeems a one-time 256-bit claim
   token minted at boot and printed to the operator console exactly once (only its SHA-256 is
   persisted, so a lost token is re-minted, never recovered). While the claim is pending — empty
   users table and an unclaimed token — every normal signup path answers
   `ErrOwnerClaimRequired`. Instances that already have users are implicitly claimed and never
   mint a new token, but an unclaimed leftover from an earlier boot still rotates.
3. **Media GC is the Phase 2 landmine.** The daily sweep runs destructive, unconditionally.
   Pointing at a shared/pre-populated bucket, or running mid-migration against a destination
   bucket, deletes unreferenced objects within 24h. Enable flag / dry-run / orphan-ratio
   breaker / ownership marker land **before** any bucket or migration tooling.
4. **2 API replicas silently corrupt jobs three ways at once**: double-claims on 6 state-flip
   queues; double-delivery on 3 bare-SELECT queues (federation double-POSTs signed activities,
   ATProto double-posts — visible to other servers); boot jobrecovery requeuing the other
   node's in-flight work. Failure is data-visible, not a crash. The SELECT-only queues are the
   easiest to miss in a lease retrofit because they look like reads.
5. ~~**Auto-rollback is only safe under the one-release schema-compat policy — which is enforced
   by documentation alone.**~~ **RETIRED — verified 2026-09-03.** Both halves of the CI
   enforcement this entry asks for exist in vidra-core. The cheap static half, `make migrate-lint`,
   is inside the canonical `make ci` gate — and `.github/workflows/ci-guard.yml:64` fails the build
   if `backend-ci.yml` ever stops invoking `make ci`, so the gate cannot be quietly removed. The
   expensive dynamic half is `.github/workflows/schema-compat.yml`: HEAD's migrations are applied
   to a fresh database, then the **previous release tag's tree runs its own integration suite
   against that already-migrated schema**, so a column this PR drops, renames, narrows or makes
   NOT NULL fails N−1's store tests hard. It is path-filtered to `migrations/**`. The workflow
   documents its own blind spot, which remains a reviewer's job: it proves N−1 still reads and
   writes fine, not that release N−1 had already stopped depending on what release N removes — so
   staged two-release drops still need the reviewer to confirm the write path went away in the
   prior release.
6. **Signed-URL/CDN/byte-path is an entangled triple.** ~~Entity-ID filenames are unguessable
   only because serving is API-proxied~~ — **correction (phase-2 item 6): the filenames were
   never unguessable.** Every media key is a deterministic function of a PUBLIC entity UUID:
   `web-videos/<video-id>.mp4`, `thumbnails/<video-id>.jpg`, `storyboards/<video-id>.jpg`,
   `avatars/users/<user-id>.png`, `playlist-thumbnails/<playlist-id>.jpg`,
   `streaming-playlists/<video-id>/<height>p/seg_NNNNN.ts`. Anyone holding an id that the API
   hands out on any public surface can compute the key. What actually protects private media is
   (a) the bucket being private, so a key is worthless without credentials, and (b) per-request
   authorization on the API byte path. Delivery must therefore be reasoned about as
   "who can be given a credential", never as "who can guess a name".
   *Item 6 shipped under exactly that reading:* presign only behind the same gates that gate the
   bytes (public AND published, not password-protected, all download gates open, no `?pt=`, no
   Authorization header), a 1-hour signature TTL with a 5-minute redirect cache so no expired
   signature is replayed, private/unpublished/password media never signed at all, and a runtime
   kill switch (`delivery_presign_enabled`, default off). Still true and still live: authorization
   is per-request in the API; cache headers are private for the same reason (item 6 gave the
   previously header-less byte routes an explicit private policy rather than promoting anything);
   and **header promotion and CDN purge machinery still have to land together** — `delivery.Resolver`
   carries `Purge` from day one precisely so nothing is promoted to shared caching before there is
   something to invalidate it with (a CDN entry outliving the auth decision; `?pt=` tokens in
   edge logs).
7. ~~**CMAF/DASH is a pipeline restructure, not new ffmpeg flags.**~~ **RETIRED 2026-08-23** by
   phase 3. It was the correct read — the restructure touched the packager seam, the storage
   tree, the mediagc grammar and the hls.go allowlists together, and `parseH264CodecString` had
   to stop dead-lettering non-H.264-Main before any codec or hardware work could run. All of it
   landed; the fMP4 pass-through route for the ~2k imported videos survived, and old TS trees
   keep playing because packaging format is now recorded per video rather than assumed. What
   replaces this risk is narrower and documented in the phase-3 carry-forwards: back-catalog
   re-packaging is optional and unbuilt, and host-binary deployments on ffmpeg 6.x emit a weaker
   (legal) bare `hvc1` CODECS string than the shipped Alpine image's 8.1.
8. **Live streaming is structurally single-host and edge-bypassing** (shared volume, raw
   0.0.0.0:1935, no playback tokens). Phase 1 firewall/doctor tooling must not assume 80/443 is
   the whole public surface.
   *Amended 2026-08-23:* the original "no prod-overlay entry/restart policy" clause is **stale** —
   the prod overlay now gives `rtmp` `restart: unless-stopped` plus the logging anchor, and
   documents 1935 as a standing exception gated in the cloud firewall. The other three clauses were
   re-verified and all still hold. Two things to add: live has **no `password` privacy tier at
   all**, so unlike VOD there is no token, no expiry and no revocation — anyone with the stream
   UUID can pull segments for the whole broadcast. And "single-host" is a **volume** problem, not a
   delivery-abstraction one: an api replica on another node sees an empty local volume and 404s
   indistinguishably from "stream not live". No resolver work fixes that; see phase-4 item 7 for
   the scope decision.
9. **Player quality identity is the hls.js level index** across
   setLevel/AUTO_LEVEL/matchQualityLevel/QualityMenu. Deferring the re-key until Shaka/DRM time
   turns a cheap refactor into a breaking change; the native-HLS (iOS, MSE-less) branch needs
   its own FairPlay/credential path in any DRM or signed-URL design.
   *Scoped down 2026-08-23 after reading the code:* **there is no data migration here.** No level
   index is persisted anywhere — the only durable quality preference is server-side
   `user_player_settings.default_quality`, already validated as `"auto" | "<height>p"`, i.e. already
   height-keyed. The re-key is a pure in-memory/prop-shape refactor of four internal contracts.
   **RETIRED — verified 2026-09-03.** The re-key landed in phase 4 (user#59): quality is keyed on
   height throughout (`vidra-user/lib/hls.ts:82-89,119-123`) and the level index never escapes the
   adapter. The entry's own follow-up is stale twice over — the symbol is
   `autoHeightCapForNetwork` (`lib/hls-bandwidth.ts:125`) and it already **returns a height**
   (480/720/null), translated to an index only at `use-playback-engine.ts:388-391`.
   The second half was not fixed but *designed for*, which is the correct outcome: quality identity
   still has no faithful implementation on the native-HLS branch — the browser owns variant
   selection via `SCORE`, so `levels` is deliberately empty there
   (`use-playback-engine.ts:492`), the quality menu self-hides (`QualityMenu.tsx:40`), and QoE
   emits a first-class *unsupported* rather than a null or a zero
   (`vidra-user/lib/playback-qoe.ts:257`). The admin playback-health page renders three explicit
   known-unknowns instead of empty cells (`AdminPlaybackHealthView.tsx:664-675`).
10. **In-manifest subtitles are blocked at the packager, not the player** (added 2026-08-23).
   `internal/media/cmaf.go` states it outright: WebVTT hard-fails the dash muxer, so captions stay
   out-of-band. Any plan that puts in-manifest subtitles in the player work item is mis-scoped —
   it needs a second packager (Shaka, already reserved for phase 5) or a separate WebVTT-segmenting
   pass. Multi-audio is the same shape: the pipeline emits exactly one hardcoded `-map 0:a:0` audio
   representation with no language tag, so a track selector would be a UI for a set of size one.

## Operational

11. **Compose semantics are silent-failure-shaped**, and every new entrypoint re-inherits them:
    bare `docker compose up` on a prod host auto-loads the dev override (rate limiting off, dev
    HMAC secret) and drops the prod overlay; Compose < 2.24 silently ignores `!reset` leaving
    Postgres/Redis on 0.0.0.0; a stray `vidra-core/.env` poisons included-file substitution.
    The CLI/wizard reproduce the exact `-f` chain and version guards; doctor checks the stray
    file.
12. **Secret-rotation asymmetry.** MFA/FEDERATION/ATPROTO KEK rotation is destructive (no
    re-wrap job; unset MFA KEK ⇒ plaintext TOTP with only a log warning). "Re-run the
    installer" must never silently mint new KEKs; generated secrets must be persisted durably
    and included in backups. *Amended 2026-09-03: the "backed up nowhere" clause is **stale** —
    `deploy/backup.sh` writes `backups/vidra-config-<stamp>.tar.gz` containing `$ENV_FILE` plus
    `deploy/Caddyfile.local` (`backup.sh:15,183-188`), and refuses rather than writing a partial
    archive when the env file sits outside the repo root and so cannot be stored repo-relative
    (`:188`). The destructive-rotation half of this entry still stands.*
13. ~~**Stale-tag trap.**~~ **RETIRED — verified 2026-09-03.** `deploy/deploy.sh` pre-flight now
    runs `git -C "$repo" fetch --tags --force` before `checkout --detach "$tag"`, with the reason
    written at the call site: without `--force` git refuses to move a tag the host already has.
    The same loop pins every component checkout to its `VIDRA_*_TAG`, and
    `require_embedded_migrate_tag` rejects a tag that predates migrations being embedded in the
    images. Bundle-unpacked trees skip the loop deliberately — there is no remote to fetch and the
    images are pinned by the same tags.
14. ~~**Silent env-parse fallbacks**~~ **RETIRED — verified 2026-09-03.** `envParser` collects a
    typed error per key instead of falling back: `Bool` appends `"%s must be a boolean
    (true|false)"` (`vidra-core/internal/config/config.go:2563`), and `Int`/`Int64`/`Duration`
    have the same shape (`:2530-2569`), surfaced together through `Err()` (`:2526`). A malformed
    value now refuses to boot and names the key.
15. ~~**Plain-HTTP and external-proxy modes require code, not config**~~ **RETIRED — verified
    2026-09-03**, all three clauses. `CookieSecure()` now returns `PublicOriginIsHTTPS()`
    (`vidra-core/internal/config/config.go:2471`) rather than hardcoding production⇒https. HSTS is
    conditional in *both* apps: core adds it only when the public origin is HTTPS
    (`internal/httpapi/secure_headers.go:13,35`), and the frontend deliberately keeps it out of
    `next.config`'s build-time `headers()` — because that is evaluated when the image is BUILT
    while the origin is only known when the container RUNS — emitting it per-request from
    `proxy.ts` instead (`vidra-user/lib/security-headers.ts:35-45`), failing secure in every
    ambiguous case. `TRUSTED_PROXY_CIDRS` has one validating parser that rejects a non-CIDR entry
    with a worked example (`config.go:2431-2440`).
16. **Everything is currently one-provider-and-owner-shaped** (/opt/vidra + service-user
    assumptions in systemd units, provider-specific sizing/firewall docs, release.sh requiring
    maintainer gh auth). Generalize by parameterizing with the existing single-host recipe as the
    tested default — don't break the one proven deployment.
    *Amended 2026-09-03: the "hardcoded ghcr owner" clause is **stale**. Every image in
    `docker-compose.prod.yml` expands `ghcr.io/${VIDRA_IMAGE_OWNER:-yegamble}/...` (`:273, :290,
    :308, :373, :403, :428`), documented in `env/production.env.example:75-80`. The registry HOST
    is still literal `ghcr.io`, so a self-hosted registry remains unparameterized — that is the
    narrower risk that survives.*
17. **Doc drift can misdirect the program.** Several runbook claims are stale (restore-drill
    warnings outdated; migration counts wrong in prose; old perf notes superseded). Doctor and
    update logic derive facts from files/DB, never prose.
    *Confirmed against this register 2026-09-03, which is the sharpest available example: an audit
    of all 17 entries found **nine** stale — five fully retired in code while still reading "Fix in
    flight" (1, 2, 9, 14, 15), two more fully retired (5, 13), and two carrying stale clauses
    (12's "backed up nowhere", 16's "hardcoded ghcr owner"). The register meant to track risk had
    become a source of it: entries 1 and 2 were listed as blocking Phase 1 promises that in fact
    shipped, and entry 5 called for CI enforcement that already exists and runs. **Practice
    adopted: an entry is not retired by the PR that fixes it — it is retired by an audit that
    re-derives it from the code, and every retirement above carries the file:line it was verified
    against.** Review the whole register at the start of each phase, not just the entries the
    current work touches.*
