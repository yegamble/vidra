# YouTube-style short codes as the canonical watch URL (2026-09)

Cross-repo plan for replacing the derived PeerTube-style short URL with a stored
opaque short code, while keeping every URL Vidra has ever published — including
an imported PeerTube instance's — resolving.

**Status:** backend complete (vidra-core#154, #155, #156) and **stages 3-4
merged** (vidra-user#136, #137), 2026-09-04. Not released, not deployed.
`/v/{code}` renders and an imported PeerTube instance's legacy links resolve, but
nothing links to the new code yet — cards, the share dialog and every piece of
metadata still point at `/videos/{uuid}`. **Next: stage 5, THE FLIP.** Nothing user-visible has shipped — the columns
exist and `short_code` reaches every local view, but no URL has changed.

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
| **2** | core | `short_code` on feed/search/playlist cards (`video.FeedItem`, `playlist.VideoCard`) — needed before the frontend can build card links | **merged** (#155) |
| **2b** | core | Put `id` + `short_code` on the password-locked 401 | **merged** (#156) |
| **3** | user | `npm run codegen`; `/v/[code]/page.tsx` replaces the route handler and renders; WatchView accepts either name | **merged** (#136) |
| **4** | user | `/w/[shortUUID]` + `/videos/watch/[id]` route handlers, Flickr decoder (**frontend only** — core never needs it), delete the stale `next.config.ts` redirect | **merged** (#137) |
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

## Notes from stage 2 (vidra-core#155)

- **`ListPublicVideosByIDs` is the vidra-search card path.** Search returns
  scored ids and core re-hydrates through that query, so omitting it would have
  left the code present with built-in search and absent with the search service
  enabled — the configuration beta actually runs.
- **A local-only assertion cannot police a UNION.** The outer SELECT projects
  `feed.short_code` BY NAME, so reordering the local branch changes nothing for
  local rows; only REMOTE rows are corrupted by a positional mismatch. And two
  adjacent `''::text` literals are interchangeable by definition, so the
  assertion that actually bites is `short_code` against a differently-valued
  column. The integration test asserts both branches on that basis.
- **Admin listings deliberately carry no code.** `GET /admin/videos` uses its own
  `adminVideoView`; admin links are internal, and they ride the stage-5 redirect.

## Stage 3 notes (vidra-user#136)

**A competing approach landed mid-flight.** vidra-user#135 added
`useShortWatchUrl`, which rewrites the address bar to `/v/{derived sid}` after
render, and explicitly declined to make `/v/` render a page because its 301 is
cached forever. That objection holds for the sids that were EMITTED — all 16-22
chars, and #136 keeps redirecting every one — but not for the stored code: 11
characters is a disjoint space, so no 11-char `/v/` URL was ever requested and
none can sit in a redirect cache. A unit test pins that disjointness for every
golden uuid; if it fails, `/v/` is ambiguous and the route must stop
discriminating by length.

**Two bugs came from the same blind spot: a route handler is not a page.**

1. A route handler forwards `req.nextUrl.search`; a Server Component never sees
   it. `permanentRedirect` silently dropped the query, which would have started
   every shared `?t=` link at zero.
2. A `loading.tsx` puts the segment behind Suspense, so Next streams the shell
   and COMMITS 200 before the component runs — `notFound()` then paints a SOFT
   404. Measured on a real build: with the file `/v/not-a-valid-sid` is 200,
   without it 404.

Neither was visible to `tsc`, lint, or 2245 unit tests, because the unit tests
mock `notFound`/`permanentRedirect` and cannot observe an HTTP status. Only a
production build could. **When this route changes again, verify against
`npm run build && next start` and curl the statuses**, not just the unit suite.

Consequence carried forward: `/v/[code]` has NO loading skeleton, deliberately.
Restoring it needs the shape check to run before streaming (middleware), not a
loading file.

**Still on the derived sid, to flip together at stage 5:** the share dialog
(`ShareButton` calls `uuidToShortId`) and `useShortWatchUrl`. Moving one alone
relocates the two-short-forms problem instead of solving it.

## Stage 4 notes (vidra-user#137)

**`/videos/watch/:id` had to leave `next.config.ts`.** It carries TWO uuid
namespaces — this instance's own id (the form remote ActivityPub servers hold)
and an imported video's SOURCE uuid — and only a backend lookup tells them
apart. The old static rewrite to `/videos/:id` was right for the first and
404'd every one of the second. An unresolvable id still falls back to the old
behaviour, so it is never worse than before.

**The cross-alphabet hazard, precisely.** Both alphabets hold the same 58
characters in a different order, so each encoding is a well-formed input to the
other's decoder and cross-decoding never fails on SHAPE. Two outcomes:

- usually the value overflows 16 bytes (flickr sorts uppercase last, so a
  leading capital is a huge digit) and the guard rejects it;
- **sometimes it lands in range and yields a well-formed uuid naming a DIFFERENT
  video** — e.g. `4UVm9F6k8z6EDn7yc4QxHt`, vidra's sid for `1c2238ef-…`, decodes
  under PeerTube's table to `1faef7f1-…`.

No shape check catches the second. The only defence is never pointing the two
decoders at one route, which is why `/v/` and `/w/` are separate.

Golden vectors are generated by running **short-uuid 6.0.3 itself**; re-deriving
them would only prove our decoder agrees with our own encoder.

**Redirect permanence is a migration decision.** `/w/` and `/videos/watch/` use
**302, not 301**: a permanent redirect is cached forever and these targets become
`/v/{code}` at the flip. They become 301 at stage 5, pointing at the final URL.

**Route handlers, not pages** — applying #136's lesson directly. A handler
controls its own status code and reads the query string; a Server Component does
neither. Verified against a production build with a stub backend, because unit
tests mock the resolve away.
