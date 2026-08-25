# List, count and pagination audit — 2026-08

Triggered by an admin "All videos" page reporting `100 videos` on an instance
holding far more. The number was not a rendering slip: it was the only number
the API was capable of returning.

This is the inventory that came out of the sweep, the decisions taken, and the
things deliberately not built.

---

## 1. What was actually broken

### API (`vidra-core`)

- **43 of 47 collection endpoints returned no `total`.** A client could learn how
  many rows it had just received and nothing else.
- `clampInt(queryInt(c, "limit", defaultVideoFeedLimit), 1, maxVideoFeedLimit)`
  was copy-pasted verbatim across **31 handlers**. `maxVideoFeedLimit = 100`
  lived in `internal/httpapi/videos.go` and was borrowed by 26 unrelated ones,
  including every admin list.
- **20 hand-written `…ListResponse` structs**, each redeclaring `limit`/`offset`.
- **7 endpoints had no pagination at all**, and their SQL had no `LIMIT`:
  `/channels/:handle/videos`, `/me/channels`, `/me/playlists`, `/playlists/:id`,
  `/channel-syncs`, `/channels/:handle/live`, `/channels/:handle/members`.
  A channel with 50k videos serialised 50k rows into one response.
- Two filters silently meant "all", because the check was an equality against a
  single literal: `?status=resolved` on reports and `?status=approved` on
  registration-requests both returned everything.

Two endpoints already did it correctly and became the template for the rest:
`/admin/users` and `/admin/jobs/runs`, each pairing a List query with a Count
query over a byte-identical `WHERE`.

### Admin / moderation UI (`vidra-user`)

- **14 surfaces** fetched with a hardcoded `limit: 100`, **never sent an offset**,
  and rendered `items.length` as though it were a total. Only 4 paginated.
- One pager existed (`AdminPagination`) — prev/next only, no page-size control.
- **Three separate hand-rolled** filter-button implementations.
- **No table shell**: every admin table was a hand-written `<table>` with a
  duplicated `<thead>` class string.
- List state was local-only everywhere, so no admin list view was shareable.

### Public UI

- Search displayed no count at all. `hasMore` was a short-page guess
  (`res.videos.length === PAGE_SIZE`) on every list.
- `Comments (100)` was a hard cap presented as a total. `{streams.length} streams`
  was capped at 20.
- Studio's "Your videos" rendered every video a channel owns — no pagination,
  no count, no sort, no filter.
- The only `IntersectionObserver` in the codebase was an analytics impression
  tracker. No infinite-scroll infrastructure existed.

### Search

- `vidra-search` indexes **videos only**. No channel, account or playlist
  document types — channels exist only as denormalised columns on video rows,
  so **a channel with zero videos was invisible to search**.
- No channel-search or account-search endpoint existed in core at all.
- No `total` on either the service or the core response. No `sort` param.
- Advanced mode recalled a fixed 500 candidates and sliced offset/limit in Go,
  so paging past ~500 returned an empty page — indistinguishable from the end
  of results.

---

## 2. Decisions

**Page sizes are 5 / 10 / 20 / 50 / 100.** Verified identical to PeerTube
(`client/src/app/shared/shared-tables/table.component.ts`, `rowsPerPageOptions`).

**The API accepts any limit in `[1, max]`, not a fixed option set.** The option
set is a UI affordance; restricting the contract would break existing callers.

**Clamping is preserved, not replaced with a 4xx.** PeerTube returns 400 above
its max; this codebase clamps, and changing that would break clients.

**Channel and account search is backed by core's own Postgres, not the search
service.** At this cardinality a trigram query over `channels`/`users` is fast,
needs no new index infrastructure, avoids adding document types plus a reconcile
backfill to `vidra-search`, and fixes the zero-video-channel blind spot for free.

**Auto-load-on-scroll is an instance setting the admin controls**
(`browse_scroll_mode`, `button` | `auto`, default `button`), not a user
preference — operators carry the load and abuse consequences. Default `button`
reproduces today's behaviour exactly, so a missing settings snapshot changes
nothing. Note this is *better* than PeerTube, whose infinite scroll is hardcoded
at a 70% threshold with no server config, no user setting and no toggle.

**Admin tables paginate; public browse scrolls.** Also matches PeerTube, where
no admin data table uses infinite scroll.

---

## 3. Deliberately not built

Each of these was requested or implied by PeerTube parity and each is absent
because the data does not exist. They are recorded here rather than shipped as
controls that quietly do nothing.

| Filter | Why not |
|---|---|
| **Storage location** | `object_storage` is computed as `it.IsLocal && cfg.StorageBackend == "s3"` — a global config value, identical on every local row. PeerTube can filter this because it stores a per-file `storage` enum; there is no such column here, so the filter would be over a constant. |
| **Live vs VOD** | `live_streams` is a table disjoint from `videos` with no FK either way. A replay becomes an ordinary draft with a `"(replay)"` title suffix and no structural marker. No column to filter on. |
| **Original publication year** | `originally_published_at` exists in no migration, no struct, no API field, in either repo. Needs a core migration, an import mapping and a backfill. |
| **Licence** | Exists in core (`videos.license`) but is never projected into the search index. Needs a document-schema change and a reconcile sweep. |
| **Instance host** | The index stores only `kind ∈ {local, remote}` — no domain string — and core's outbox only ever emits `kind='local'`, so remote videos are not indexed at all. |

---

## 4. Reusability outcome

The audit's core finding was duplication, so the fix is measured by consolidation
rather than by features added:

| Before | After |
|---|---|
| 31 copy-pasted limit/offset blocks | one `parsePage` in `internal/httpapi/paginate.go` |
| 20 structs redeclaring `limit`/`offset` | one embedded `pageMeta{Total,Limit,Offset}` |
| inline filter parsing per handler | `internal/httpapi/listfilters.go` |
| 21 inline limit + 23 inline offset blocks in OpenAPI | `PageLimit` / `PageOffset` components, `PageMeta` composed via `allOf` |
| 3 hand-rolled filter buttons | one `FilterChips` |
| 0 table shells, N hand-written `<table>` | one `AdminTable` |
| ~16 copy-pasted list-state idioms | one `useListQuery`, URL-synced |

---

## 5. Verification notes for future work

- **`make ci` reports cached Go test results.** A green gate can be stale. Run
  `go test -count=1 -race ./...` separately; only the uncached run proves anything.
- **`go vet` under build tags catches what the gate cannot.** Three build-tagged
  files were still compiling against old signatures after a green `make ci`.
- **`AdminUsersView.test.tsx` fails under CPU contention on `main` too.** Its
  debounce-driven tests run 1.1–1.4s against a 5s limit. Before concluding a
  regression, stash and reproduce on a clean base.
- **gopls cross-contaminates across in-repo worktrees.** Five stale worktrees
  under `vidra-core/.claude/worktrees/` share one module path, so the editor
  reports undefined symbols and mismatched signatures that `go build` does not.
  Verify with a real build before chasing them.
- **Never put `default:` on an OpenAPI request-body property.** With
  `openapi-typescript` it makes the property mandatory for typed clients and
  breaks the frontend build — and core CI cannot see it.
