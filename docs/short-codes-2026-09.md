# YouTube-style short codes as the canonical watch URL (2026-09)

Cross-repo plan for replacing the derived PeerTube-style short URL with a stored
opaque short code, while keeping every URL Vidra has ever published — including
an imported PeerTube instance's — resolving.

**Status:** stage 1 of 6 **merged** (vidra-core#154, 2026-09-04), not yet
released or deployed. Nothing user-visible has shipped — both columns exist and
are populated, but no URL has changed.

## What was decided

1. The new short code is **11 characters of Bitcoin base58**, stored per video,
   opaque and random. It becomes the **canonical** watch URL: `/v/{code}`
   renders the watch page and `/videos/{uuid}` redirects to it.
2. An imported PeerTube instance's old links keep working: `/w/{shortUUID}` and
   `/videos/watch/{uuid}` redirect to the new canonical.
3. The pre-existing derived `/v/{sid}` links keep working forever.

## Three encodings, and why they cannot share a route

| Scheme | Route | Alphabet | Length |
|---|---|---|---|
| **New stored code** | `/v/{code}` | Bitcoin base58 | exactly 11 |
| Legacy derived sid | `/v/{sid}` | Bitcoin base58 | 16–22, unpadded |
| PeerTube shortUUID | `/w/{sid}` | **Flickr** base58 | exactly 22, `1`-padded |

The Bitcoin and Flickr alphabets contain the **same 58 characters in a different
order** (`short-uuid` defaults to `flickrBase58`, with `consistentLength: true`
and `maxLength = ceil(128/log2(58)) = 22`, padding with `alphabet[0]`). So a
PeerTube shortUUID handed to `shortid.ToUUID` does not error — it decodes to a
*different, wrong* uuid.

That is the whole reason `/w/` exists as a separate route. On `/v/` the stored
code and the legacy sid are separable **by length** (11 vs 16–22). A 22-char
Bitcoin sid and a 22-char Flickr sid are **not separable by shape at all**, so
they must never share a prefix.

## Identifiers stay, links move

The rule that keeps this survivable. Anything a remote system uses as a **key**
is frozen; anything a human **clicks** moves.

| Site | Ruling | Why |
|---|---|---|
| AP `id` (`outbox.go:150-159`, `:128`, `:173`, `collections.go:113`) | **stays** `/videos/{uuid}` | It is the object's identity in every remote database. `notes.go`'s comment states the policy: those ids "live in remote servers' databases, out of our reach." |
| AP `url` | → `/v/{code}` | `id` ≠ `url` is idiomatic AP. Remote copies pick it up on the next Update; no mass re-send. |
| `inReplyTo` (`outbox_comments.go:139`) | **stays** | Must equal the object id remote servers know, or new comments detach from the thread. |
| RSS `<guid isPermaLink="true">` | **stays** | It is the subscriber-side dedup key. Changing it re-notifies every subscriber of every item in the 50-item window. A permanently-redirecting URL is still a valid permalink. |
| RSS `<link>` | → `/v/{code}` | What readers click; no dedup semantics. |
| sitemap `<loc>` | → `/v/{code}` | Must match `rel=canonical`. No dedup key; safest place to adopt a new canonical. |
| Bluesky (`atproto/worker.go:114`) | → `/v/{code}` | New posts only — posted records are immutable. |
| `/embed/{uuid}` | **stays** | Embeds are addressed by uuid; out of scope. |
| Inbound parsers (`notes.go:243`) | **unchanged** | AP ids never take the `/v/` form, so there is nothing new to parse. |

## Verified facts (measured, not estimated)

Against `postgres:18-alpine`, the version pinned in both `docker-compose.yml`
and `backend-ci.yml`:

- A **VOLATILE** `DEFAULT` on `ADD COLUMN` is evaluated **per row**: 13,500 rows
  produced 13,500 **distinct** 11-character codes in one statement.
- Lock duration (ACCESS EXCLUSIVE, table rewrite): **0.6s at 13.5k rows**,
  **2.6s at 135k** — roughly 19µs/row.
- An INSERT that **omits** the column still gets a code. This is the
  rolling-deploy property: the N-1 binary's explicit column list cannot know
  about the new column.
- **v0.6.2's own test suite passes against schema 127** (run in a worktree),
  which is the `schema-compat.yml` property: rollback stays a tag flip.
- `migrate-lint` accepts a `$$`-quoted plpgsql body — its statement splitting is
  not confused by the semicolons inside.

## Why the import ledger is not the resolver

`peertube_import_ledger` holds `(entity_kind='video', source_id) -> vidra_id`
and is where the backfill reads from, but it must not serve a public URL:

- `resolveParent` **retires** a mapping (`status='skipped', vidra_id=NULL`) when
  the row it points at is gone; `UpsertImportLedgerEntry` **repoints** it.
- It carries **no FK to videos by design**, so between runs it is *expected* to
  hold dangling pointers.
- Several entity kinds share the same `source_id` for one video.
- Its down migration drops the whole table.

Hence `videos.peertube_uuid`, with a **partial unique** index: a plain index
would let two videos claim one legacy URL, and the resolver would then send half
that URL's traffic to the wrong video *silently*.

## Staging

Each stage is independently mergeable, green on its own gates, and safe to
deploy alone given everything before it is deployed.

| # | Repo | Content | Status |
|---|---|---|---|
| **1** | core | `short_code` + `peertube_uuid` migrations, `GET /videos/resolve`, oEmbed short-code branch, importer writes the source uuid | **merged** (#154) |
| 2 | core | `short_code` on feed/search/playlist cards (`video.FeedItem`, `playlist.VideoCard`) — needed before the frontend can build card links | not started |
| 3 | user | `npm run codegen`; `/v/[code]/page.tsx` replaces the route handler and renders; `watchPath()` helper adopted everywhere but still returning `/videos/{id}`; `rel=canonical` introduced | not started |
| 4 | user | `/w/[shortUUID]` + `/videos/watch/[id]` route handlers, Flickr decoder (**frontend only** — core never needs it), delete the stale `next.config.ts` redirect | not started |
| 5 | user | **THE FLIP.** `watchPath()` → `/v/{code}`; `/videos/[id]` redirects; canonical + oEmbed discovery move; ShareButton uses the stored code | not started |
| 6 | core | Emitter flip: RSS `<link>`, sitemap `<loc>`, Bluesky, AP `url`. `guid`/`id`/`inReplyTo`/embed untouched, each pinned by a test | not started |

**Rollback invariant:** never roll back stage 3 once any `/v/{code}` has been
emitted (i.e. after stage 5 or 6). Before the flip, `0126`'s down migration is
usable; after it, rollback is a tag flip — the codes are random and not
re-derivable, so dropping the column kills every link ever shared.

### Gates still to clear

- **Stage 3, blocking:** confirm the `/videos/{uuid}` page redirect does not
  break ActivityPub dereference. See the open bug below — it likely cannot,
  because that dereference already does not work, but it must be checked rather
  than assumed.
- **Stage 3 — answered, and it needs a core change.** The locked
  (password-protected) response does **not** carry `id`:
  `PasswordRequiredError` is an empty struct (`errors.go:272`), deliberately
  carrying "no secret (no token, no hash, no password)". So a `/v/{code}` page
  for a locked video gets a 401 with no uuid in it, and cannot hand
  `WatchView` an id for `PasswordUnlockPanel`, whose unlock POST is
  `/videos/{id}/unlock`. Two ways out, both core-side and both small: put the
  video's `id` (and `short_code`) on the 401 body — neither is a secret, the
  caller already holds one of them — or teach the unlock route to accept a
  short code. Prefer the former; it also lets the watch page render its title
  and poster behind the prompt. Do this in stage 2, before the frontend needs
  it.
- **Stage 5 — mechanism verified.** The ~40 e2e specs that `goto("/videos/v1")`
  need no changes. `getPublicVideo` goes through `serverJson`, which is typed
  `Promise<T | null>` and returns `null` on any failure rather than throwing
  (`lib/server-json.ts:50-68`). Playwright's `page.route` intercepts browser
  requests only, so in the mocked suite that server-side fetch fails, the page
  gets `null`, `video?.short_code` is undefined, and the conditional redirect
  does not fire — the page renders exactly as it does today. That conditional is
  therefore load-bearing twice over: it keeps the mocked suite green AND keeps
  owner-private/locked videos reachable, where the anonymous server fetch also
  fails but the client fetch with a session succeeds.

  Corollary: do **not** add `short_code` to the shared e2e fixtures. Doing so
  would flip those pages into a redirect whose target's `resolve` call nobody
  has mocked.

## Open bugs found while planning (not caused by this work)

- **AP video objects are unresolvable as ActivityPub.** `/videos/*` is not in
  Caddy's `@api` matcher, so it routes to Next.js. Since AP object ids are
  `{origin}/videos/{uuid}`, a remote server dereferencing one gets **HTML, not
  JSON-LD**. Video objects are only consumable when pushed inline. Deserves its
  own ticket.
- **`vidra-user/next.config.ts:22-30` is stale.** It claims core still emits
  `/videos/watch/{uuid}` and that the redirect "cannot be removed until core
  mints `/videos/{id}`" — core now does; the only remaining reference is the
  deliberate inbound parser.
- **oEmbed does not accept `/w/{shortUUID}` verbatim.** Supporting it needs a
  Flickr decoder in core. Unfurlers that follow the redirect are unaffected.

## Security posture

The short code is a valid URL for **unlisted** videos, whose only protection is
URL obscurity. Effective strength drops from 122 bits (uuid) to **64.5 bits**
(58^11), because both URLs stay valid and security equals the weaker one.

Accepted deliberately: this is precisely what YouTube uses for unlisted videos,
and brute-forcing 1,000 of them at 10k req/s is ~80,000 years. Two things make
it hold, and neither may be dropped:

- Entropy is `gen_random_uuid()` (`pg_strong_random`, a CSPRNG). **Never
  `random()`** — for an unlisted video the code *is* the secret.
- Malformed and unknown identifiers are **indistinguishable 404s**. A 400/404
  split would make the resolver an enumeration oracle, which matters more for a
  64.5-bit code than for a uuid.
