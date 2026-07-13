# Vidra search, autosuggest & recommendations (cross-repo system spec)

> Canonical meta-repo overview of the `vidra-search` service and how it plugs into
> `vidra-core` and `vidra-user`. Lives here because it spans three repos. The
> authoritative deep-dives live in `vidra-search/docs/` (architecture, privacy,
> operations, evaluation) and `vidra-search/api/openapi.yaml` (the internal
> contract). This file is the map, not the territory.

## Repos & topology

`vidra-search` is a **standalone Go service** (own repo, own CI, own Docker),
integrated into the meta-repo the same way as the others: cloned by
`bootstrap.sh`, git-ignored, wired into the compose stack.

```
vidra-user (browser)  ─HTTP→  vidra-core (api)  ─HMAC HTTP→  vidra-search
                                    │                              │
                                    └── shared Postgres ───────────┘  (schema `search`)
                                    └── shared Redis (core DB 0, search DB 1)
```

**Invariant: the frontend NEVER talks to `vidra-search`.** Every search /
suggestion / recommendation request goes `vidra-user → vidra-core → vidra-search`.
Search returns ranked **video IDs only**; core hydrates them through its own
visibility predicate (per-viewer mutes/blocks/sensitivity), so search never sees
or decides policy.

## Storage & wiring (meta compose)

- **Postgres**: `vidra-search` owns a dedicated `search` schema inside the shared
  `vidra` DB (migration `0001` creates it). golang-migrate's version ledger lands
  in `vidra_search_migrations` (in `public`) via the `x-migrations-table` URL
  param, so it never collides with core's `schema_migrations`. A one-shot
  `search-migrate` compose service (mirroring core's `migrate`) applies it.
- **Redis**: same instance as core, **DB index 1** (`redis://redis:6379/1`); core
  uses DB 0.
- **Auth**: HMAC over `(ts, method, path)` with a shared secret —
  `SEARCH_INTERNAL_SECRET` on the api side == `INTERNAL_SECRET` on the search side.
- **Ports**: internal `:8080`; host `SEARCH_HTTP_PORT` (default `:8081`, inspection
  only — the service is not browser/proxy-exposed).

## Modes

- **Simple** (default): deterministic SQL — full-text (`tsvector`) + trigram +
  exact tag/channel matches, popularity/freshness weighted. Works with **zero**
  behavioral data. Always available.
- **Advanced**: adds learned signals (query/engagement aggregates, co-watch /
  co-search neighbors, per-user affinity) on top of the simple recall; heuristics
  always present, learned models only once data thresholds are met and a model is
  shadow-evaluated and activated. Anonymous / cold requests degrade to simple.

## Instance settings (owned by vidra-core, pushed to search)

`search_mode` (simple|advanced), `search_suggestions_enabled`,
`personalized_search_enabled`, `personalized_recommendations_enabled`,
`search_history_enabled`, `search_event_retention_days`,
`search_min_query_user_count`. Users additionally control three prefs:
`search_history_enabled`, `personalized_search_enabled`,
`personalized_recommendations_enabled`. When any search setting changes, core
enqueues a `search.config_updated` event so the service tracks the effective config.

## Event flow (outbox → inbox, at-least-once + idempotent)

Core emits domain + behavioral events to a durable `search_outbox` table and a
5s worker POSTs batches to `POST /internal/v1/events`. Search dedupes on
`event_id` (UUID) via an `events_inbox` ledger (`ON CONFLICT DO NOTHING`), so
retries are safe. Domain events (`video.upsert/suppress/stats`,
`channel.upsert/delete`, `user.suppress`, `user.history_deleted`,
`search.config_updated`, `reconcile.*`) keep the index eligible-in-sync;
behavioral events (`search.*`, `video.play_started/watch_progress/completed`) feed
aggregates, trending, and personalization. A periodic **reconcile** sweep
(begin/page/end, default 24h) repairs any drift and suppresses orphans.

## Degradation guarantees (never a search-caused 5xx)

Core wraps every search call in a per-endpoint timeout + circuit breaker and
**fails soft**:
- suggestions → empty list (optional local title-prefix fallback);
- search → existing `SearchPublicVideos` SQL;
- home recs → trending/recent; related recs → same-channel + same-category.

An empty `SEARCH_SERVICE_URL` disables the whole integration cleanly (no client,
no outbox/reconcile worker) — the platform runs exactly as it did before search.

## Privacy model

- Personalization is decided **in core** per request: `effective_personalized =
  instance_setting AND user_pref AND signed_in`. Search receives only flags, never
  policy, and learns from events **only** when core marks `allow_history=true`.
- Rare/personal queries never become global suggestions (min distinct-user gate).
- History delete + account deletion purge user rows in search and anonymize logged
  queries (`user_id` NULLed). Search stores only static eligibility + an
  `is_sensitive` flag per doc; the viewer-specific visibility filter stays in core.

## Pointers

- Deep-dives: `vidra-search/docs/{architecture,privacy,operations,evaluation}.md`.
- Internal API contract: `vidra-search/api/openapi.yaml` (all `/internal/v1`).
- Env matrix & DX guarantees: [`environments.md`](environments.md).
- Where it sits in the core backend: [`architecture.md`](architecture.md).
