# Search filters backlog — decisions and scoping (2026-08)

Follow-up to the list/count/pagination audit: the four candidate search filters, in
delivery order. Items 1 and 2 are built and in review (PR links below); item 3 is a
settled structural decision awaiting implementation; item 4 is scoped but
deliberately not started.

## 1. Licence filter — BUILT (PR open)

`videos.license` existed in core but was never projected into the search index.
Delivered end to end as a clone of the language filter at every layer: core projects
license into the search event doc; vidra-search stores it (migration 0015) and
filters on it; core's search API accepts+validates `license` (422 on unknown) on
both the search-service path and the local SQL fallback (including the
remote-videos UNION arm's filter exclusion); the search page gains a License
select. Backfill needed **no code**: core's reconcile sweep re-upserts every
eligible document at startup and every 24h, so the column fills itself on the next
deploy.

Two properties worth recording: license is deliberately NOT part of the
narrows-to-local routing decision (a license-only search still reaches
vidra-search), and vidra-search does no vocabulary validation (core owns the
taxonomy — established convention).

Deploy-ordering note: between the vidra-search deploy (migration 0015) and core's
first reconcile sweep, `documents.license` is NULL everywhere, so a
license-filtered search on the service path returns an empty page while core's
`total` (local SQL) reports the true count. Core's startup sweep closes the window
— restart core promptly after the search deploy.

PRs: [vidra-core#105](https://github.com/yegamble/vidra-core/pull/105), [vidra-search#24](https://github.com/yegamble/vidra-search/pull/24), [vidra-user#80](https://github.com/yegamble/vidra-user/pull/80).

## 2. Original publication date — BUILT (PR open, core side)

`videos.originally_published_at` (nullable timestamptz, migration 0119): detail-API
read, PATCH write, PeerTube importer mapping (optional-column probe — old sources
lack the column), and a dedicated importer backfill pass (own ledger kind, keyed
off the existing `video` ledger rows) so the already-imported catalogue gets values
on the next importer run.

Two safety rules baked in, worth recording:
- Under `--source-authoritative` resync, a nil source date falls back to the stored
  value (mirroring duration). Without this, one resync against a source whose
  schema predates the column would erase every stored date.
- The backfill pass does NOT write a terminal ledger row for NULL source dates —
  they are re-examined each run and filled if the still-live source gains a value
  later (same convention as the view-count pass).

PR: [vidra-core#106](https://github.com/yegamble/vidra-core/pull/106).

Deliberately out of scope this round, in order:
- projection into the search index + year filter (rides the same mechanism as item 1);
- frontend display + `npm run codegen` in the user app.

## 3. Live vs VOD — DECISION

### The problem

`live_streams` is disjoint from `videos`; a replay becomes an ordinary draft with a
`" (replay)"` title suffix and no structural marker. The admin inventory already
refuses a `?live` filter for exactly this reason ("a filter that lies",
`internal/httpapi/admin_videos.go`). So the filter needs a representation decision
first.

### Constraint that settles the shape

A *permanent* stream goes live repeatedly, and every `RunReplay` creates a fresh
draft video — one stream produces **many** replay videos. So a
`live_streams.replay_video_id` column is structurally wrong; the reference must live
on the video side.

### Decision

Two columns on `videos`, one migration:

1. `origin TEXT NOT NULL DEFAULT 'upload' CHECK (origin IN ('upload', 'live_replay', 'import'))`
   — the durable, filterable marker. This is what gets projected into the search
   document and faceted on.
2. `live_stream_id UUID REFERENCES live_streams(id) ON DELETE SET NULL` (nullable)
   — provenance for UX ("watch the original stream") only. It is deliberately NOT
   the marker: `ON DELETE SET NULL` means it vanishes with the stream, while
   `origin` survives.

Writers:
- `RunReplay` sets `origin = 'live_replay'` + `live_stream_id`.
- The PeerTube importer sets `origin = 'import'` on insert.
- Everything else defaults to `'upload'`.

Backfill policy:
- **Imports: yes, exactly** — `peertube_import_ledger` (`entity_kind = 'video'`,
  `status = 'done'`) identifies every imported video precisely; a one-shot
  `UPDATE … FROM` backfills `origin = 'import'`.
- **Replays: no.** The only signal for a pre-existing replay is the title suffix,
  and the codebase has already (correctly) rejected the suffix as a source of
  truth. Pre-existing replays stay `'upload'`; the memo is the record of why.

What "Live vs VOD" then means in search:
- **VOD facet on `origin`** (upload / live replay / import) — cheap once the column
  exists; same projection mechanism as items 1–2.
- **Currently-live streams in search** — a separate feature (indexing
  `live_streams` with state-transition events), and NOT recommended now: live
  discovery already has its own dedicated surface (`GET /api/v1/live`, the live
  rail), the live catalogue of a single instance at any instant is a handful of
  rows, and ephemeral state fights index freshness for no user value.

The `" (replay)"` title suffix stays for now (titles are user-visible and
user-editable; silently rewriting them is worse). Once the UI badges from `origin`,
dropping the suffix for *new* replays is a one-line follow-up.

## 4. Instance host — SCOPED, NOT STARTED

### Reframe

The index stores only `kind IN ('local','remote')` with no domain string, and core
only ever emits `kind='local'` — remote videos are not indexed at all. "Filter by
host" is therefore three stacked features: (a) index federated content, (b) store a
per-document host, (c) expose the facet. For a single-instance deployment with
little federation traffic, (b) and (c) are no-op UI until (a) exists.

### Quick win first (independent of all of the above)

When vidra-search is the active search path, core bypasses the `remote_videos`
UNION arm entirely (`searchViaService` → `HydrateByIDs`, local only) — ingested
remote videos are **invisible in search** on any instance running the search
service, even though they appear on the local-SQL fallback. Fix: when the search
service handles the query, also run the existing remote ILIKE arm in core and
attach the results to the response's existing `remote` array (the seam the live
URI-resolution feature already uses). Small, self-contained, restores parity.

### Full feature, in dependency order

1. **Schema**: `search.documents` gains `domain TEXT NOT NULL DEFAULT ''`
   (lowercase, empty for local; or the instance's own host — decide at build time).
   Wire doc gains `domain`; search API responses gain `kind` alongside ids so the
   hydrator knows which table to hit.
2. **Core emits remote events**: upsert at federation ingest (`storeRemoteVideo`),
   suppress on `remote_video_blocks` insert and on instance block (bulk, by
   domain). New doc-source query joining `remote_videos` + `remote_actors`.
3. **Moderation semantics**: `blocked_instances` is global → suppress in the index;
   `muted_instances` is per-viewer → must be applied at hydration in core, never
   baked into the index.
4. **Reconcile**: the orphan sweep is deliberately `kind='local'`-scoped; remote
   needs its own reconcile arm (or remote docs will never be orphan-suppressed).
5. **Hydration**: `HydrateByIDs` must learn remote ids (route by `kind` from the
   search response).
6. **Facet + UI** last.

### Honest quality caveats

- Remote docs carry no tags/category/language and no views/likes — ranking degrades
  to text relevance + recency for the remote slice.
- `is_sensitive` is unknown for remote content (the SQL arm hardcodes `false`);
  indexing remote content without a sensitivity answer has policy implications —
  settle that before step 2.

### Recommendation

Ship the quick win now; defer the full feature until federation traffic justifies
it, and when it happens run it as its own multi-PR wave (comparable in size to a
small phase, not a filter ticket).
