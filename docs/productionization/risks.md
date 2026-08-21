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
7. **CMAF/DASH is a pipeline restructure, not new ffmpeg flags.** Packaging is fused into the
   encode; the storage tree, mediagc grammar, hls.go allowlists all assume the TS layout;
   `parseH264CodecString` dead-letters non-H.264-Main (also blocking hardware encoders);
   ~2k imported videos need the fMP4 pass-through route to survive.
8. **Live streaming is structurally single-host and edge-bypassing** (shared volume, raw
   0.0.0.0:1935, no playback tokens, no prod-overlay entry/restart policy). Phase 1
   firewall/doctor tooling must not assume 80/443 is the whole public surface.
9. **Player quality identity is the hls.js level index** across
   setLevel/AUTO_LEVEL/matchQualityLevel/QualityMenu. Deferring the re-key until Shaka/DRM time
   turns a cheap refactor into a breaking change; the native-HLS (iOS, MSE-less) branch needs
   its own FairPlay/credential path in any DRM or signed-URL design.

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
