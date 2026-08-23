# Program risk register

Live risks that shape sequencing. Review when opening each phase; strike through with a note
when retired.

## Architectural

1. **Frontend origin baking is architectural, not incidental.** `NEXT_PUBLIC_API_BASE_URL` is
   inlined at build time. Every Phase 1 promise — one-command install, domain automation,
   generic images — is blocked until vidra-user gets runtime origin config. *(Fix in flight.)*
2. **First-account-gets-admin race.** A streamlined installer that opens the site before owner
   registration hands the instance to the first bot. Owner bootstrap is a security fix with
   priority over convenience. *(Fix in flight.)*
3. **Media GC is the Phase 2 landmine.** The daily sweep runs destructive, unconditionally.
   Pointing at a shared/pre-populated bucket, or running mid-migration against a destination
   bucket, deletes unreferenced objects within 24h. Enable flag / dry-run / orphan-ratio
   breaker / ownership marker land **before** any bucket or migration tooling.
4. **2 API replicas silently corrupt jobs three ways at once**: double-claims on 6 state-flip
   queues; double-delivery on 3 bare-SELECT queues (federation double-POSTs signed activities,
   ATProto double-posts — visible to other servers); boot jobrecovery requeuing the other
   node's in-flight work. Failure is data-visible, not a crash. The SELECT-only queues are the
   easiest to miss in a lease retrofit because they look like reads.
5. **Auto-rollback is only safe under the one-release schema-compat policy — which is enforced
   by documentation alone.** One destructive migration turns every rollback into
   old-code-on-new-schema corruption. CI enforcement (migration lint + N−1-binary-vs-N-schema
   job) is the highest-leverage prerequisite for `vidra update`.
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
   Two things the entry missed, both now the real risk: `autoLevelCapForNetwork` in
   `lib/hls-bandwidth.ts` *returns an hls.js index* out of an otherwise pure module, so it must be
   re-keyed in the same change or the menu speaks heights while the ABR cap speaks indexes; and
   **quality identity has no faithful implementation on the native-HLS branch at all** — the browser
   owns variant selection there, driven by the `SCORE` attribute, so the adapter can neither read
   nor set the active variant. Phase 4 item 4 must design the QoE schema knowing "selected
   rendition" is permanently unknowable for that engine, rather than discovering it when the admin
   playback-health page shows a third of sessions with a null rendition.
10. **In-manifest subtitles are blocked at the packager, not the player** (added 2026-08-23).
   `internal/media/cmaf.go` states it outright: WebVTT hard-fails the dash muxer, so captions stay
   out-of-band. Any plan that puts in-manifest subtitles in the player work item is mis-scoped —
   it needs a second packager (Shaka, already reserved for phase 5) or a separate WebVTT-segmenting
   pass. Multi-audio is the same shape: the pipeline emits exactly one hardcoded `-map 0:a:0` audio
   representation with no language tag, so a track selector would be a UI for a set of size one.

## Operational

10. **Compose semantics are silent-failure-shaped**, and every new entrypoint re-inherits them:
    bare `docker compose up` on a prod host auto-loads the dev override (rate limiting off, dev
    HMAC secret) and drops the prod overlay; Compose < 2.24 silently ignores `!reset` leaving
    Postgres/Redis on 0.0.0.0; a stray `vidra-core/.env` poisons included-file substitution.
    The CLI/wizard reproduce the exact `-f` chain and version guards; doctor checks the stray
    file.
11. **Secret-rotation asymmetry.** MFA/FEDERATION/ATPROTO KEK rotation is destructive (no
    re-wrap job; unset MFA KEK ⇒ plaintext TOTP with only a log warning). "Re-run the
    installer" must never silently mint new KEKs; generated secrets must be persisted durably
    and included in backups (`env/production.env` is currently backed up nowhere).
12. **Stale-tag trap.** The 2026-08 upstream history rewrite changed every v0.1.x tag SHA;
    `deploy.sh` fetched tags without `--force`, so live hosts pin stale tag objects.
    *(Fix in flight; the live beta droplet needs it before its next deploy.)*
13. **Silent env-parse fallbacks** (malformed bool/duration values boot "successfully" wrong)
    undermine any generated-env pipeline. *(Fix in flight.)*
14. **Plain-HTTP and external-proxy modes require code, not config** — CookieSecure()
    hardcodes production⇒https (login silently breaks over HTTP); HSTS emitted unconditionally
    by both apps; public-IP TLS terminators need TrustIPRange wiring. Shipping these as
    compose-only options yields silently broken deployments.
15. **Everything is currently one-provider-and-owner-shaped** (hardcoded ghcr owner, /opt/vidra
    + service-user assumptions in systemd units, provider-specific sizing/firewall docs,
    release.sh requiring maintainer gh auth). Generalize by parameterizing with the existing
    single-host recipe as the tested default — don't break the one proven deployment.
16. **Doc drift can misdirect the program.** Several runbook claims are stale (restore-drill
    warnings outdated; migration counts wrong in prose; old perf notes superseded). Doctor and
    update logic derive facts from files/DB, never prose.
