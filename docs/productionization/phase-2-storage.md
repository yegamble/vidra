# Phase 2 — Storage abstraction

**Outcome:** an operator moves videos from local disk to S3 (or between buckets) with a
background job — progress, retries, integrity verification — and viewers can be served objects
without every byte proxying through the Go API. Local-only installs notice nothing.

## What already exists (don't rebuild)

- `internal/storage/storage.go`: clean `Backend` interface with optional capabilities
  (PathProvider/ObjectLister/PrefixDeleter); traversal-safe `local.go`; `s3.go` with streaming
  multipart + seekable ranged reads via minio-go; MinIO dev profile; prod defaults to s3;
  integration-tested. **Missing only presign.**
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

- [ ] **1. Media-GC safety (LANDS FIRST — prerequisite for all bucket/migration work)** — the
  daily sweep runs destructive, unconditionally. Add: enable flag, dry-run-first mode,
  orphan-ratio circuit breaker, bucket-ownership marker. Without this, pointing Vidra at a
  shared/pre-populated bucket — or running GC mid-migration against a destination bucket —
  deletes unreferenced objects within 24h.
- [ ] **2. Content hashes** — compute + store sha256 (and/or etag) on Put and backfill via a
  background job; `video_files` has only size_bytes today. Foundation for integrity-verified
  migration and post-restore consistency checks.
- [ ] **3. `Presigner` capability** — optional interface on Backend (interfaces.md §2);
  s3 implements, local doesn't.
- [ ] **4. Per-object location record** — table/column recording which backend holds each
  object (interfaces.md §3), enabling dual-read during migration.
- [ ] **5. Storage migration jobs** — local→s3 / bucket→bucket as background jobs born on the
  SKIP LOCKED + lease worker convention (interfaces.md §7): copy → verify hash → flip location
  record → (grace period) → delete source. Progress/retries surfaced through the existing
  jobstatus machinery. IPFS pin-ledger rows key on object keys — keep keys stable or migrate
  the ledger with them.
- [ ] **6. Direct object delivery (signed URLs)** — presign-redirect for eligible
  public/authorized objects via the delivery resolver (interfaces.md §4). **Must land as a
  package with:** cache-header policy work (Cache-Control is deliberately private today) and
  the entity-ID-filename privacy analysis — unguessable names are currently safe *only*
  because serving is API-proxied. The API-proxy path remains the authoritative fallback and
  the only path for password-protected/private media until sessions (Phase 4).
- [ ] **7. Backup/restore integration** — restore gains a blob-reference consistency check
  (DB rows ↔ objects, using item 2's hashes); backup docs cover S3-canonical deployments
  (provider-side durability + lifecycle guidance).
- [ ] **8. Wizard/admin surfacing** — "Where should Vidra store your videos?" (This server /
  Cloud storage / Advanced) in the wizard; migration progress in admin; graceful-discovery
  card when S3 isn't configured.

## Exit criteria

- A local install migrates its full media library to S3 with zero downtime and verified hashes,
  then serves via presigned redirects, with `vidra doctor` green throughout.
- Rollback: flipping back to api-proxy delivery is a config change, not a migration.
