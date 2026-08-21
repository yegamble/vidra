# Phase 2 — Storage abstraction

**Outcome:** an operator moves videos from local disk to S3 (or between buckets) with a
background job — progress, retries, integrity verification — and viewers can be served objects
without every byte proxying through the Go API. Local-only installs notice nothing.

## What already exists (don't rebuild)

- `internal/storage/storage.go`: clean `Backend` interface with optional capabilities
  (PathProvider/ObjectLister/PrefixDeleter, and since the lean-S3 wave also
  Presigner/SizedPutter); traversal-safe `local.go`; `s3.go` with streaming
  multipart + seekable ranged reads via minio-go; MinIO dev profile; prod defaults to s3;
  integration-tested. ~~Missing only presign.~~ *Presign shipped 2026-08-20 (item 3).*
- Opaque relative `storage_key` doctrine (migration 0008) — URLs are always minted at response
  time, so delivery changes need zero data migration.
- The IPFS mirror as a separated *delivery* concept (authority-vs-distribution split).

## Concept separation (binding)

```text
Canonical storage   — where Vidra can reliably recover this video (Backend)
Delivery sources    — where this viewer should fetch this segment (internal/delivery resolver)
Peer delivery       — can another node/viewer supply this segment (IPFS mirror, later P2P)
```

A video may exist simultaneously in S3, local cache, IPFS, CDN edges, and browser peers —
those systems are not equivalent and must not share one interface.

## Work items

- [x] **1. Media-GC safety (LANDS FIRST — prerequisite for all bucket/migration work)** — the
  daily sweep runs destructive, unconditionally. Add: enable flag, dry-run-first mode,
  orphan-ratio circuit breaker, bucket-ownership marker. Without this, pointing Vidra at a
  shared/pre-populated bucket — or running GC mid-migration against a destination bucket —
  deletes unreferenced objects within 24h.
  *Done 2026-08-21, core#58.* `MEDIA_GC_ENABLED` + `MEDIA_GC_MAX_ORPHAN_PERCENT` (breaker:
  >100 orphans AND >25% of scanned refuses to delete); first sweep per process is always dry-run
  plus a dry sweep ~5 min after boot; `.vidra/owner` marker carrying the new one-row
  `instance_identity` (0105) — buckets this boot created or found empty are claimed, a populated
  unmarked bucket is never claimed (`POST /admin/media/gc/adopt-bucket` is the audited operator
  action), a foreign marker is a conflict; every rail degrades to dry-run, never an error; local
  backend exempt by design; `EnsureBucket` now reports creation; doctor gained "media GC posture"
  and "bucket ownership". MinIO integration proofs cover the full ownership matrix.
- [x] **2. Content hashes** — compute + store sha256 (and/or etag) on Put and backfill via a
  background job; `video_files` has only size_bytes today. Foundation for integrity-verified
  migration and post-restore consistency checks.
  *Done 2026-08-21, core#59.* `video_files.sha256` (0106; `''` = uncomputed, `'missing'` =
  backfill found no object — item 7's verify-blobs consumes the sentinel);
  `storage.PutSizedHashed` tees SHA-256 in one pass; all ten row-creating Put chokepoints
  converted (incl. the PeerTube importer, which was computing and discarding digests for both
  originals and thumbnails); leader-gated backfill worker, 25 rows/min. HLS segments are
  deliberately hash-less (no `video_files` rows) — migration verifies them in-flight (item 5).
- [x] **3. `Presigner` capability** — optional interface on Backend (interfaces.md §2);
  s3 implements, local doesn't.
  *Already shipped 2026-08-20 by the lean-S3 wave* (`1485eac`): `storage.Presigner` +
  `S3.PresignGet` via minio `PresignedGetObject`, first consumer ffprobe's source-open ladder
  (local path → presigned URL → download), which is also the fail-open feature-detection
  pattern item 6's resolver should copy. The wave also added `SizedPutter`. Remaining
  presign work is delivery-side consumption only (item 6).
- [x] **4. Per-object location record** — table/column recording which backend holds each
  object (interfaces.md §3), enabling dual-read during migration.
  *Done 2026-08-21, core#60 (with item 5).* `storage_migration_objects` (0107) is the record —
  keyed on `object_key` like the pin ledger, carrying state/sha256/byte_size; `verified` /
  `source_deleted` = present in target. Dual-read = `storage.Fallback` (Backend only, no
  capabilities — GC/doctor keep the raw primary); new `Describer` + `RootLister` capabilities.
- [x] **5. Storage migration jobs** — local→s3 / bucket→bucket as background jobs born on the
  SKIP LOCKED + lease worker convention (interfaces.md §7): copy → verify hash → flip location
  record → (grace period) → delete source. Progress/retries surfaced through the existing
  jobstatus machinery. IPFS pin-ledger rows key on object keys — keep keys stable or migrate
  the ledger with them.
  *Done 2026-08-21, core#60.* Campaign table + object ledger (0107); unleadered leased copy
  workers, leader-gated enumerate/reconcile sweep; verify = re-open + re-hash the TARGET,
  cross-checked against item 2's `video_files.sha256`; cutover is *observed* (operator swaps
  both env sets + restarts — runbook in core docs/operations.md "Moving the media store"),
  source deletion needs zero-pending + `STORAGE_MIGRATION_GRACE_HOURS` (168) + an identity
  match, and the copy pass carries a direction guard against half-done swaps. Keys stay stable
  so the pin ledger is untouched; GC is forced dry-run for the campaign's life. Progress rides
  jobstatus via a campaign sync trigger (7th queue). Follow-ups noted: S3→S3 copy loses the
  single-PUT size hint (16 MiB part buffers); a doctor "migration in flight" check.
- [x] **6. Direct object delivery (signed URLs)** — presign-redirect for eligible
  public/authorized objects via the delivery resolver (interfaces.md §4). **Must land as a
  package with:** cache-header policy work (Cache-Control is deliberately private today) and
  the entity-ID-filename privacy analysis — unguessable names are currently safe *only*
  because serving is API-proxied. The API-proxy path remains the authoritative fallback and
  the only path for password-protected/private media until sessions (Phase 4).
  *Done 2026-08-21, core#61, as the package.* `internal/delivery` resolver (mirror → presigned →
  api-proxy terminal, all fail-open, `Purge` hook day one); the 5 IPFS redirect sites folded in
  behavior-identically; presign behind runtime `delivery_presign_enabled` (default off), 1h TTL,
  fully-public path only — never past the password gate, never playlists, never storyboard VTTs
  (relative sprite refs). New `storage.ResponsePresigner` signs content-type/disposition/cache
  into the URL (objects carry no Content-Type — bare presign would break inline playback);
  presigner withheld entirely during a storage migration. Cache policy added to every
  previously header-less media route. Privacy analysis: risks.md corrected — keys ARE
  deterministic from public UUIDs; the controls are the private bucket, the auth gates, TTL.
  Captions deferred (stream-only service seam, few-KB win) — wiring, not redesign, later.
- [x] **7. Backup/restore integration** — restore gains a blob-reference consistency check
  (DB rows ↔ objects, using item 2's hashes); backup docs cover S3-canonical deployments
  (provider-side durability + lifecycle guidance).
  *Done 2026-08-21, core#62 + meta deploy edits.* `verify-blobs` on the api image (Exists pass;
  `--hash` re-verifies item 2's digests; `--deep` catches hollow HLS trees; exit 0/3/1; the
  `'missing'` sentinel reports but never fails — it was dangling at dump time; new StaleSentinel
  class); restore.sh runs it between migrators and service start, warns with ranked causes,
  never blocks; deploy/README.md "S3-canonical deployments" reconciles versioning-for-durability
  with doctor's retention warning (pair versioning with noncurrent-version expiry) and documents
  the dump-at-T vs bucket-at-T+n hazard both ways; doctor gains a "storage migration" check.
- [x] **8. Wizard/admin surfacing** — "Where should Vidra store your videos?" (This server /
  Cloud storage / Advanced) in the wizard; migration progress in admin; graceful-discovery
  card when S3 isn't configured.
  *Done 2026-08-21.* The wizard question already existed in both wizards (phase-1 work);
  user#57 added the rest to the admin Infrastructure page: live object-store probe row (from
  `/admin/system`, missing key renders "Not reported" — never healthy) with re-check, a
  read-only migration campaign card (progress via a shared ProgressBar extracted from the jobs
  browser, deep link to /admin/jobs; deliberately no start/cancel — ops-driven runbook), the
  graceful-discovery card for local installs, and the `object_storage` feature deep link.
  Migration progress in the jobs browser itself came free with item 5's sync trigger.

## Exit criteria

- A local install migrates its full media library to S3 with zero downtime and verified hashes,
  then serves via presigned redirects, with `vidra doctor` green throughout.
- Rollback: flipping back to api-proxy delivery is a config change, not a migration.

**MET — validated 2026-08-21** on a real local→MinIO run against core main: 69 objects across 5
videos (originals, HLS ladders, thumbnails, storyboards), 68/68 clean 1 Hz probe triples during
enumerate→copy→synced (zero non-200s), byte-exact sha256 end-to-end (row == disk == presigned
bytes), env-swap cutover through automatic source deletion (grace=0; local media dir emptied,
counters exact), `verify-blobs --hash` and `--deep` exit 0, presigned 307s with pinned
Content-Type (stored objects are octet-stream — the response-header pin is load-bearing), all
negative cases held (private/password/scheduled/credentialed never presigned), doctor's only ✗
was the validation host's own full disk, and rollback was a single settings PATCH with no
restart. Validation findings (destination-bucket adoption on completion, runbook cleanup step,
curl recipes, .env.example knobs) fixed same day in core#63. Caveats recorded: single-instance
cutover is a brief restart outage (multi-instance roll not exercised); cutover→done costs ~3
reconcile ticks (~3 min) even at grace 0.
