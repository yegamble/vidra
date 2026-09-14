# v0.6.5 off-site backup on an independent provider — 2026-09-14

**Full release scope stays NO-GO; the off-site retrieval gap is closed.** The
shipped off-site backup mechanism — `deploy/backup.sh` with
`BACKUP_RCLONE_REMOTE` — was run **unmodified** on the running restored v0.6.5
host to push an encrypted backup to **Cloudflare R2**, a provider chosen for
geographic **and** company independence from the primary Backblaze B2 media
store (`us-east-005`). The copy was retrieved and decrypted from a separate
workstation and verified byte-exact. This is the one input REC-01 was still
BLOCKED on, so **REC-01 moves BLOCKED [B3] → PASS**; the restore half is the
already-merged recovery drill (REC-02 PASS, meta#208). Counts move from
**4 PASS / 45 UNVERIFIED / 10 BLOCKED** to **5 / 45 / 9**. Rows and reasons:
[disposition](evidence/release-v0.6.5-verification/offsite-runtime/disposition.json)
(baseline `docs/evidence/release-v0.6.5-verification/recovery-runtime/disposition.json`,
sha256 `45c9ccbd6f9c65d4b7ab468597f191a42eed3b3c6ddf9c9a96ade4378400594d`).

This record extends the native v0.6.5 record's labelling: every value is
**file-asserted** from
[`offsite-runtime/result.json`](evidence/release-v0.6.5-verification/offsite-runtime/result.json)
unless marked **session-reported** (host, provider, bucket and rclone-version
facts).

## Candidate, host and tool boundary

- **Candidate.** The [immutable manifest](evidence/release-v0.6.5-verification/manifest.json)
  is unchanged: core `ghcr.io/yegamble/vidra-core@sha256:a6e08b93…3bb1`, user
  `vidra-user@sha256:08e920ba…3178`, search `vidra-search@sha256:55196d27…a0f8`,
  ledgers `146|f` / `18|f`. No image or code changed for this drill.
- **Product path.** `deploy/backup.sh` with
  `BACKUP_RCLONE_REMOTE=offsite:` — the shipped off-site mechanism, **no code
  change**. `offsite:` is an rclone **crypt** remote (client-side encryption,
  filename encryption `standard`) layered over an R2 S3 remote.
- **Host.** The restored v0.6.5 replacement, droplet 599514574
  (159.65.249.255), `COMPOSE_PROJECT_NAME=vidra-release-acceptance`, its stack
  running — the same host the recovery drill (meta#208) left up. Session-reported.
- **Off-site target.** Cloudflare R2, bucket `vidra-backup`, endpoint
  `https://<account-id>.r2.cloudflarestorage.com` (the 32-hex account id is
  redacted here and in every committed file). Session-reported.
- **Independence.** A **different company AND geography** than the primary
  Backblaze B2 media store in `us-east-005`: this protects against a Backblaze
  account or provider failure, not only a region outage. Session-reported.
- **Retrieval boundary.** The independent retrieval ran on a **separate
  workstation** holding only the **scoped R2 key** and the **crypt password** —
  nothing from the host. The crypt password/salt are stored privately by the
  operator (gitignored `env/offsite.env`) and never entered the repo.
- **Scope.** This exercises the **off-site push → independent retrieve →
  decrypt → integrity** leg for the DB dump and config archive. Media stays
  S3-canonical in B2 (itself off-host); no local-storage media snapshot was
  pushed off-site.

## Executed evidence

Every value below is read from
`evidence/release-v0.6.5-verification/offsite-runtime/result.json`.

| Run | Dump | dump sha256 host == off-site (decrypted) | gzip -t | PGDMP magic | rclone result |
|---|---|---|---|---|---|
| distro rclone **1.60.1** | `vidra-20260914T170105Z.dump.gz` | `f02ac5f2…e322e` — **match** | OK | (see clean run + retrieval) | harmless **HTTP 501** on the mod-time set, **succeeded on retry**; bytes verified intact |
| rclone **1.75.1** (clean) | `vidra-20260914T170228Z.dump.gz` | `3f83f1d5…7031` — **match** | OK | **present** | **clean, no errors** |

- **Config archive.** Both runs carried the config archive at
  `config_sha256` `8db945e2…4f64` (the same config handoff hash the recovery
  drill recorded).
- **Independent retrieval.** From the separate workstation with only the scoped
  R2 key + the crypt password: `rclone crypt` decrypt → **byte-exact match** of
  the host dump, `gzip -t` **OK**, **PGDMP magic present** (a valid Postgres
  custom-format dump).
- **Encryption at rest (client-side, provider stores only ciphertext).** The
  raw R2 objects have **encrypted filenames** (filename encryption `standard`),
  and their first bytes are the rclone crypt header `b'RCLONE\x00\x00'` — not
  the plaintext dump names or contents. The provider never sees plaintext.

## rclone version note (operator guidance)

The distro rclone **v1.60.1** emitted a **harmless HTTP 501** when setting the
object mod-time against R2 and then **succeeded on retry**; the upload and the
decrypted bytes were intact. After upgrading to rclone **v1.75.1** the run was
**clean, with no errors**. **Operator guidance: use current rclone** (≥ the
version that handles R2 cleanly; **1.75.1 verified**, distro 1.60.1 works but
logs the 501-then-retry noise).

## What this proves and does not

**Proves, using the shipped off-site mechanism unchanged:**

- **Independent provider + geography.** An encrypted backup pushed to Cloudflare
  R2 — different company and region than the B2 media store — so a Backblaze
  account/provider loss does not take the backups with it.
- **Client-side encryption.** rclone crypt encrypts filenames and contents
  before upload; the raw R2 objects carry the crypt header, not plaintext
  (`b'RCLONE\x00\x00'`).
- **Byte-exact retrieval.** From a separate workstation with only the scoped R2
  key + the crypt password, the copy decrypts to a byte-exact match of the host
  dump, passes `gzip -t`, and shows PGDMP magic.

**Does not prove:**

- **Not a single-pass off-site → restore chain.** A full restore FROM the
  off-site copy onto a host was not run in one pass here; the restore leg is the
  already-merged recovery drill (REC-02 PASS, meta#208), which restored from a
  host-to-host handoff. This drill adds only REC-01's off-site retrieval leg.
- **Not wired into the production beta deploy.** The beta instance was
  untouched; this is an operator-configured off-site target on the acceptance
  host. Off-site remains **opt-in** — see the operator documentation in
  [`deploy/README.md`](../deploy/README.md).
- **Media not pushed off-site.** Media stays S3-canonical in B2; local-storage
  media snapshots are a separate, documented manual step and were not exercised.
- **No other B3 provider input.** Selected IdP/mail (AUTH-03/04), selected CDN
  (INT-10/A33) and presign providers were **not** exercised, so those rows stay
  as the recovery-runtime baseline left them.

## Disposition delta

- **REC-01** ("Backup includes DB, settings/sealing keys and required media"):
  BLOCKED [B3] → **PASS**. Off-site push to an independent provider +
  independent retrieval/decrypt/integrity demonstrated; the backup-completeness
  and replacement-host-restore halves are the recovery drill (REC-02 PASS).
- **A36 off-site-backup facet** → **DEMONSTRATED** in `provider_facets`.
- **A37** stays PARTIAL: replacement-host restore passed (REC-02 PASS), and the
  off-site copy is now retrievable/decryptable, but a single-pass
  off-site → restore chain was not run, so A37 is not fully closed.
- **AUTH-03 / AUTH-04 (B3)**, **INT-10 (B3)** and **MIG-01…06 (B2)** stay
  **BLOCKED**: none of their inputs were exercised by an off-site backup drill.
- **B3** is now marked **partially resolved** (off-site object store
  demonstrated); it remains open for the other selected-provider inputs. B4 was
  already resolved in the recovery baseline. Counts **4/45/10 → 5/45/9**.

## Evidence integrity and export

The sanitized drill evidence is
[`offsite-runtime/result.json`](evidence/release-v0.6.5-verification/offsite-runtime/result.json)
(account id redacted; no keys or passwords). One
[`committed-hashes.json`](evidence/release-v0.6.5-verification/offsite-runtime/committed-hashes.json)
is the independent sha256 index recomputed over **every committed file in the
`offsite-runtime` tree except itself** (`result.json` and the derived
`disposition.json`). `git check-ignore` reports nothing under this tree.

Next executable: the owner inputs still open — the selected IdP/mail (B3,
AUTH-03/04), the selected CDN (B3, INT-10/A33), the representative migration
source (B2, MIG-01…06), the browser/Safari/iOS matrix, and the remaining OPS-01
clauses (API/worker split, two-worker interruption, settings propagation,
leader failover).
