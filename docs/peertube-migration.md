# PeerTube → Vidra migration

This is an operator runbook for an independent Vidra installation, including a
Backblaze B2 destination. It describes **core v0.7.5**, paired with **user and
search v0.7.3**, as recorded in [the release manifest](../releases/v0.7.5.json).
Its source schema gate accepts PeerTube `application.migrationVersion` **700–1040**.
The transfer rehearsal section describes **unreleased, unqualified source
changes**: optional HLS server-side copy, concurrent trees, independent captions
and subtitle manifest normalization. These are not behavior available in v0.7.5;
the released pairing and its instructions remain unchanged.
Choose a qualified release and repeat its acceptance checks; a released image,
successful import, or healthy home page alone does not establish production
readiness. See [release readiness](release-readiness.md).

Keep the original service available throughout rehearsal. Use an isolated host,
database, media bucket, and temporary HTTPS hostname for Vidra. Do not redirect
the original domain until step 10 passes. Examples use `/opt/vidra` owned by the
`vidra` operator account; adapt paths and service ownership together.

## 1. Record what must survive

Save a private migration record containing:

- Source PeerTube version, schema version, snapshot time and SHA-256; local
  accounts/channels/videos split by visibility, moderation state, and media type.
- Original files, HLS objects, captions, artwork and storyboards: object counts,
  bytes, bucket/prefix or filesystem location, and missing/oversized objects.
  Count HLS dependencies, not just manifests. Keep local and remote videos
  separate when comparing totals.
- Source configuration, including `production.yaml`, `local-production.json`,
  storage layout, canonical origin, custom categories, and mail/federation needs.
  Instance title, description and terms are not all in the database; transfer
  approved settings explicitly. PeerTube's admin configuration can override its
  YAML files. [PeerTube configuration](https://docs.joinpeertube.org/maintain/configuration)
- Required user workflows and a rollback owner/window. Decide what to do with
  pre-existing beta accounts, uploads, comments and moderation decisions before
  importing; a fresh candidate does not merge those automatically.

Identify the authoritative source explicitly. If that is the original server
and its configured storage, an older beta or unrelated backup is not an
additional import source. For missing media, record the expected source location,
the read result and the affected capability (playback, captions or preview).
Distinguish absent objects from denied reads and transient transfer failures.
Retain the metadata and failure evidence; neither a successful retry of another
asset nor a `done` run makes unavailable source bytes recoverable.

The importer carries local content and supported relationships, not a complete
PeerTube server clone. Password hashes and actor keys can be carried, but plugins,
sessions, every moderation/audit record, remote subscriptions and federation
identity continuity need separate review. Lifetime view totals are carried;
historical daily analytics are not reconstructed.

Budget duplicate storage for the source, destination and recovery copies. In
v0.7.5, `copy` streams through the Vidra host and hashes the bytes. It does **not**
use B2 server-side bucket copying, even when both buckets share an account.
The optional feature below accelerates only HLS binary dependencies on a future
qualified release; its benefit depends on the source's HLS share.
Estimate transfer time from measured sustained throughput; include source
downloads, destination writes, requests, retries and retained object versions.
An inventory of video/HLS bytes alone is a lower bound if artwork and captions
are excluded. Never substitute a provider ETag for a SHA-256 checksum.

## 2. Prepare the isolated installation

Use a reviewed installer checkout containing the required bundle compatibility
fixes, and record its commit separately from the application release. From that
checkout, install the selected release. On Debian/Ubuntu, install the basic
download/verification prerequisites, then replace `REVIEWED_META_COMMIT` below
with the approved tooling commit (not a component release tag):

```sh
sudo apt-get update
sudo apt-get install -y ca-certificates curl git python3
git clone https://github.com/yegamble/vidra.git vidra-migration-tooling
cd vidra-migration-tooling
git checkout --detach REVIEWED_META_COMMIT
git rev-parse HEAD
sh ./install.sh --ref v0.7.5 --dir /opt/vidra
cd /opt/vidra
```

The installer prepares the installation and setup; deployment is a separate
step. Follow [the deployment guide](../deploy/README.md). Resolve each component
from the release manifest: do not assign `v0.7.5` to user/search, which use
`v0.7.3` in this release. Keep nested checkouts pinned; the deployment script uses
them to check expected migration versions. Do not bypass missing helper,
release-mapping, migration-ledger or Compose-version failures.

The corrected installer requires `python3` and a validated release record; it
refuses to guess component tags if pairing cannot be established. For an offline
installation, provision a trusted `releases/v0.7.5.json` in the installation tree
and the required release assets/images before using `VIDRA_RECORD_FETCH=off`.
That switch only disables record fetching; it does not make other downloads
offline or waive record validation. The v0.7.5 bundle predates this installer fix,
so keep the reviewed current installer and the pinned application bundle distinct.

Choose host resources for PostgreSQL, Redis, ClamAV, import streaming and any
workers. Adjust Compose CPU/memory limits to fit the actual host; its production
defaults target a larger host than the minimum installation. Leave disk for
database growth, dumps and upload/transcode scratch. More workers do not imply a
faster importer and can compete for the same I/O.

Restrict SSH and candidate HTTPS access to operators. Permit certificate
validation as required by your ACME method. Publish no PostgreSQL, Redis or
search ports; API/frontend host bindings should be loopback only. Use Compose
2.24 or later and validate both files before deploying:

```sh
docker compose -f docker-compose.yml -f docker-compose.prod.yml \
  --env-file env/production.env config -q
```

Inspect the render with `--profile core --profile frontend config` when checking
ports. Treat the rendered configuration as secret-bearing; do not attach it to a
public issue. Configure `PUBLIC_BASE_URL`, `NEXT_PUBLIC_API_BASE_URL` and
`CORS_ALLOWED_ORIGINS` for the candidate HTTPS origin. Verify trusted TLS, browser
rendering, `/version`, `/healthz`, `/readyz`, actual running image manifests and
both migration ledgers after deployment. For the pairing above, the expected
core/search schema versions are **150/18**.

## 3. Restore a snapshot behind a read-only role

Prefer a separate restored source database over reading live production during
a long import. Keep the original dump and selected source configuration encrypted
off site, independently of Vidra's own backups. Use PostgreSQL client tools
compatible with the source server.

Configure private PostgreSQL service/password files for `peertube_source`,
`candidate_admin` and, later, `peertube_snapshot_reader`. Keep passwords out of
arguments and shell history. These examples assume `candidate_admin` connects
to an administrative database on the isolated candidate PostgreSQL server:

```sh
umask 077
PGSERVICE=peertube_source pg_dump --format=custom \
  --file=/secure/migration/peertube.dump
sha256sum /secure/migration/peertube.dump
# Transfer the archive securely; verify the same digest on the candidate.
PGSERVICE=candidate_admin createdb peertube_source_snapshot
PGSERVICE=candidate_admin pg_restore --exit-on-error --no-owner --no-acl \
  --dbname=peertube_source_snapshot /secure/migration/peertube.dump
PGSERVICE=candidate_admin psql --dbname=peertube_source_snapshot
```

In that interactive `psql` session, create a reader that does not own the restored
objects. The following revocations apply to this dedicated snapshot database:

```sql
CREATE ROLE pt_import_reader LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
\password pt_import_reader
REVOKE ALL ON DATABASE peertube_source_snapshot FROM PUBLIC;
GRANT CONNECT ON DATABASE peertube_source_snapshot TO pt_import_reader;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO pt_import_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO pt_import_reader;
ALTER ROLE pt_import_reader IN DATABASE peertube_source_snapshot
  SET default_transaction_read_only = on;
```

Reconnect through the reader service and verify that reads work, the transaction
default is read-only, and table writes are not granted:

```sql
SHOW default_transaction_read_only;
SELECT "migrationVersion" FROM application;
SELECT has_table_privilege(current_user, 'public.application', 'SELECT') AS can_read,
       has_table_privilege(current_user, 'public.application', 'UPDATE') AS can_update;
```

Expect `on`, the recorded schema version, `true` and `false`. A read-only default
alone is not access control: verify the role has no ownership, write grants or
privileged memberships. Reapply and check these grants after replacing the
snapshot. Keep database access on a private network, with TLS where appropriate.
[`pg_restore` options](https://www.postgresql.org/docs/17/app-pgrestore.html)

Place the reader DSN in a private file and use setup's secret-file input, or a
protected editor for `env/production.env`:

```sh
vidra setup --template env/production.env.example --yes \
  --peertube-source-url @/secure/migration/source-dsn
```

Do not put a literal DSN into the standalone importer's `--source-dsn` argument.
The admin import route uses the server's configured credentials and avoids
exposing them in process arguments.

## 4. Configure source and destination storage separately

Use three credentials: source read-only, destination media read/write, and backup
storage. Scope each to its intended bucket. B2's application key ID is the S3
access key ID; the application key is the secret. The master key cannot be used
with S3. Source reads normally need listing/read capabilities; bucket discovery
may additionally require `listAllBucketNames`. Grant destination operations and
deletion capabilities only as required by its normal lifecycle.
[B2 application keys](https://www.backblaze.com/docs/cloud-storage-s3-compatible-app-keys)

For B2, get each bucket's actual region and endpoint from the provider. Vidra's
endpoint fields take **host only, without `https://` or a bucket name**. For
example, a bucket in `us-east-005` uses `s3.us-east-005.backblazeb2.com` and region
`us-east-005`. Keep TLS enabled; B2 supports both virtual-host and path-style
addressing. [B2 S3 endpoints](https://www.backblaze.com/docs/en/cloud-storage-call-the-s3-compatible-api)

Edit the protected environment file; the following deliberately omits secrets:

```dotenv
STORAGE_BACKEND=s3
STORAGE_S3_ENDPOINT=s3.us-east-005.backblazeb2.com
STORAGE_S3_BUCKET=vidra-candidate-media
STORAGE_S3_REGION=us-east-005
STORAGE_S3_USE_SSL=true
STORAGE_S3_FORCE_PATH_STYLE=false
# Fill STORAGE_S3_ACCESS_KEY and STORAGE_S3_SECRET_KEY privately.

PEERTUBE_IMPORT_ENABLED=true
# Fill PEERTUBE_SOURCE_DATABASE_URL privately with the snapshot reader DSN.
PEERTUBE_SOURCE_STORAGE_BACKEND=s3
PEERTUBE_SOURCE_S3_ENDPOINT=s3.us-east-005.backblazeb2.com
PEERTUBE_SOURCE_S3_BUCKET=peertube-source-media
PEERTUBE_SOURCE_S3_REGION=us-east-005
PEERTUBE_SOURCE_S3_USE_SSL=true
PEERTUBE_SOURCE_S3_FORCE_PATH_STYLE=false
# Fill PEERTUBE_SOURCE_S3_ACCESS_KEY and PEERTUBE_SOURCE_S3_SECRET_KEY privately.
PEERTUBE_IMPORT_MEDIA_MODE=copy
PEERTUBE_IMPORT_CONFLICT_POLICY=skip
```

Source and destination regions may differ. Verify source keys match the
importer's expected `web-videos/`, `streaming-playlists/hls/` and `captions/`
layout, including private media. The source configuration names one bucket;
custom prefixes or separate buckets per media family need an explicit compatible
mapping, not a guessed endpoint. Preview cannot prove every source object exists.

For a filesystem source, use `PEERTUBE_SOURCE_STORAGE_BACKEND=local` and set
`PEERTUBE_SOURCE_STORAGE_LOCAL_ROOT` to a read-only bind mount visible at the same
path inside the API and any worker container. Verify actual files from inside
those containers before importing; an empty automatically created directory can
otherwise appear healthy. The released scripts explicitly select Compose files;
they do not automatically load an arbitrary `docker-compose.override.yml`. Add
the mount to `x-core-prod-volumes` in the selected production definition, preserving
the existing mounts, and retain this reviewed local deployment change across
updates. For example, append `/srv/peertube-storage:/source/peertube:ro` and set
the source root to `/source/peertube`; inspect the rendered API/worker mounts.

A mixed local/S3 source needs a separate inventory: the source backend selector
does not automatically fall back from S3 to the PeerTube host's filesystem.
Preserve every local original and its database/key mapping. The prerelease
[three-pass repair procedure](#mixed-locals3-repair-prerelease) below covers
local originals whose captions or HLS remain in object storage; it is not a
capability qualification for v0.7.5.

Keep the source HTTP origin reachable too. Actor images, posters and storyboard
sheets may live on the PeerTube host even when video storage is S3. The importer
tries supported local artwork paths and source `/lazy-static/` routes; it derives
the source origin from actor URLs. Retiring or redirecting that hostname early
can strand artwork imports.

Choose one media strategy before the first actual run:

| Mode | What it does | Operational consequence |
| --- | --- | --- |
| `copy` | Streams supported media into Vidra's destination bucket. | Enables independence only after required media and artwork are verified. Recommended for replacing the old installation. |
| `reference` | Keeps source keys for originals, HLS and captions; **still copies artwork**. | Vidra's runtime `STORAGE_*` must access the same source bucket/layout and allow destination artwork writes. The source bucket remains a runtime dependency. Never force media GC ownership onto a shared source bucket. |
| `none` | Imports metadata without media. | Use a disposable destination for a mapping rehearsal; it is not a playable migration. |

Do not change an active run to `reference` to avoid transfer time. The durable
ledger and already-imported rows survive reruns; changing mode is not a general
conversion or recopy mechanism.

### Prerelease transfer rehearsal

**Unreleased and unqualified: do not enable this on v0.7.5 or assume that updating
this env template updates the running binary.** Test the implementation on an
isolated candidate first. Record exact source commits, source archive checksums,
image digests and build arguments for all components, then qualify that exact
pairing before promotion. A private candidate build is not a public release or
production acceptance. This remains `media_mode=copy`; it reuses source media
without encoding.

The prerelease importer copies up to **four independent HLS trees concurrently**.
Each tree is still copied in dependency order and becomes ready only after its
required objects succeed. A ready tree, including one created on Vidra, is
preserved on rerun. This bound is built into the importer; starting extra import
runs or workers is not the way to increase it. Measure throughput and memory on
the candidate with its database and scanner running.

In copy mode, captions run in a separate pass after videos and HLS, with up to
four caption transfers at once. An absent VTT track records a retryable caption
failure without discarding the video or blocking an otherwise valid HLS tree.
Repair the source track and rerun against the same ledger. Existing same-language
tracks and previously recorded creator deletions remain protected. A playable
video does not make a missing caption acceptable: reconcile caption failures
separately before acceptance.

PeerTube HLS can reference subtitle playlists containing absolute VTT URLs.
The prerelease copy removes `#EXT-X-MEDIA` declarations with `TYPE=SUBTITLES` and
the `SUBTITLES` group attribute on `#EXT-X-STREAM-INF`; it does not open or copy those
subtitle playlists or follow their URLs. Supported VTT tracks are imported from
the configured source storage and served through Vidra's caption API/player
tracks instead. Audio, video and closed-caption declarations remain, and their
dependencies retain the flat-name restriction. Malformed attributes and external
audio/video URLs still fail. Required source originals, manifests and media
objects that are actually missing remain failures; this is not a general
missing-object bypass.

#### Optional server-side copy credentials

Both of the following values are empty by default. Populate them together using
a protected editor on `env/production.env`, without shell arguments or history:

```dotenv
PEERTUBE_IMPORT_S3_COPY_ACCESS_KEY=
PEERTUBE_IMPORT_S3_COPY_SECRET_KEY=
```

Use a dedicated, short-lived migration key. Leave the ordinary
`PEERTUBE_SOURCE_S3_*` reader and destination `STORAGE_S3_*` credentials unchanged.
For B2, a Multi-Bucket Application Key can be restricted to the source and
destination buckets. However, its `readFiles`/`writeFiles` capabilities apply
across that set: **this copy credential also permits source writes**. It is not
a read-only source credential, even though the importer only copies from the
source. No permission is broadened automatically. If that scope is unacceptable,
leave the pair empty and retain streaming. Do not use an account master key.
[B2 multi-bucket keys](https://www.backblaze.com/docs/cloud-storage-application-keys)

The fast path requires matching S3 endpoint, TLS scheme and region; B2 buckets
must also belong to the same account. A source HEAD through the normal read-only
credential fixes its version, size and ETag before copying. Incompatible storage
or an unsupported/unauthorized copy request rejected before a copy starts permits
the ordinary streamed path. The first deterministic `ErrCopyUnavailable` disables
the fast copier for the rest of that import run and emits one warning, avoiding
the same denied request for every subsequent HLS object. A later run attempt
reevaluates availability. Source HEAD failures, quota failures, cancellation and
source-version/precondition failures do not take that fallback; neither does an
error after multipart upload initialization. These remain failures rather than
silently retrying against a newer source. Separate source and
destination credentials cannot be combined to authorize one server-side copy.
[B2 copy API](https://www.backblaze.com/apidocs/s3-copy-object),
[same-account restriction](https://www.backblaze.com/apidocs/b2-copy-file)

Only **HLS binary dependencies** use the fast path. Originals still stream and
compute their true SHA-256; captions and artwork retain their streamed paths.
HLS manifests are read once, normalized as above and validated; those normalized
bytes are PUT to the destination. Manifests without subtitle declarations or
group attributes retain their bytes, and the media bytes are unchanged. Binary
objects up to **4 GiB** use one copy; larger objects use
**128 MiB** multipart copy ranges, within the existing **16 GiB per-object**
cap. The HLS tree still has **10,000-object, 64 GiB, 30-minute** limits and
**1 MiB** manifests. A provider copy result/ETag is not a freshly computed
whole-file SHA-256. Preserve that distinction in migration evidence.
[B2 multipart copy](https://www.backblaze.com/apidocs/s3-upload-part-copy)

Enable this only for the **next controlled run or resume**. Record the source
snapshot, run UUID, ledger checkpoint and destination state first. If an import
is active, complete the agreed freeze/checkpoint procedure before a release
change or restart; do not edit credentials and restart an active copy to speed it
up. Deploy the approved release with both values passed to API and worker, verify
the running images and configuration privately, then resume against the same
snapshot and ledger. Completed ready HLS trees stay intact. Verify representative
copied objects, multipart completion, playback and seeking; retain failure and
fallback evidence. Successful HLS trees that used server-side copying log
`server_side_objects`, `server_side_bytes` and `streamed_bytes`; record these to
verify that the optimization actually ran. These are per-tree transfer counters,
not an independent checksum or whole-catalogue completeness proof. Remove/revoke
the temporary copy key after the reconciliation window using another controlled
configuration restart.

Record the expiry and bucket scope of every credential separately. Temporary
media and backup keys need an approved replacement before a lasting beta opens;
successful migration access does not establish that next week's playback or
backup will work. Install and verify replacements before revoking old keys.
Change importer credentials only at a terminal run boundary, then verify the
actual API/worker configuration. Never extend the copy key's source permissions
as a shortcut for ordinary destination access.

#### Mixed local/S3 repair (prerelease)

An original can remain on the PeerTube filesystem while its captions or HLS are
in S3. The importer selects one source backend for an entire run. If the S3 pass
cannot read that original, it does not create the video, so its child assets
cannot be imported yet. A local pass supplies the parent; a final S3 pass can
then supply its children. Two passes alone can leave those children missing.

This procedure has a PostgreSQL regression using two disjoint source stores,
including unchanged media, true original hashes and preserved creator edits or
deletions. It does not replace a provider test or playback verification on the
operator's exact deployment.

1. Inventory and stage the local files on the Vidra host, preserving their
   relative paths, including `web-videos/private/` where applicable. Record
   sizes and SHA-256 values, then verify the staged copies. Mount the staged
   root read-only into both API and worker as described above; verify that the
   container UID can read the files. Do not change source file permissions.
2. Use the same restored source database, destination database, destination
   bucket and pinned component images for every pass. The ledger is keyed by
   entity kind and source identifier (numeric ID or video UUID), not by instance
   or backend: never reuse it with a different PeerTube instance. Keep `media_mode=copy`, the reviewed
   conflict policy, and `source_authoritative=false` unchanged.
3. Launch the S3 pass through the authenticated admin import page/API from
   [section 6](#6-preview-resolve-exceptions-then-launch-the-actual-copy), with
   `PEERTUBE_SOURCE_STORAGE_BACKEND=s3`. Save the terminal report and failed
   asset inventory. Local-only originals are expected to remain failed here;
   identify those exact rows before proceeding.
4. Wait for that run to become terminal. Disable importing, stop its executors,
   set `PEERTUBE_SOURCE_STORAGE_BACKEND=local` and
   `PEERTUBE_SOURCE_STORAGE_LOCAL_ROOT=/source/peertube` in the protected env,
   and recreate API/worker through the reviewed deployment procedure. Verify
   the running configuration and read-only mount before enabling imports and
   launching the next run. The local pass repairs missing parent videos and
   hashes their originals. S3-only captions/HLS can still fail in this pass.
5. After the local run is terminal and checkpointed, repeat the controlled
   configuration change back to `PEERTUBE_SOURCE_STORAGE_BACKEND=s3`, retaining
   the original source S3 settings. Launch the final repair run against the
   same ledger. Available S3 captions/HLS for the newly created videos can now
   import; completed videos, captions and ready HLS trees are preserved.
6. Reconcile every pass and verify the repaired originals' hashes, stable video
   IDs, source state/privacy, captions and HLS dependencies. Source drafts must
   stay drafts. Artwork is reconsidered but unchanged imported assets need no
   new transfer; the prerelease preserves creator changes and cleared slots
   across repeated runs, even if the source later selects a new artwork ID.

Keep the [side-effect pauses](#5-pause-side-effects-and-choose-account-policy)
throughout. Do not run the passes concurrently or delete destination objects
between them: ready database rows would otherwise conceal missing bytes. Each
pass also revisits other retryable failures; this is not an import limited to
the staged files. Genuinely missing source assets remain failures to reconcile,
never entries to mark done manually.

## 5. Pause side effects and choose account policy

Before the actual import, configure and verify:

```dotenv
REGISTRATION_ENABLED=false
FEDERATION_ENABLED=false
MAIL_ENABLED=false
IPFS_ENABLED=false
CHANNEL_SYNC_ENABLED=false
MEDIA_GC_ENABLED=false
FEATURE_LIVE_ENABLED=false
TRANSCODING_ENABLED=false
CLAMAV_ADDR=clamav:3310
MALWARE_SCAN_MODE=fail-closed
INSTANCE_DEFAULT_QUOTA_BYTES=0
```

Keep the `scan` Compose profile enabled and ClamAV healthy. Do not disable the
scanner to make ordinary uploads pass. An imported object is not proof that the
normal upload/scanning pipeline works. Validate and deploy as the installation
owner, then complete the health/TLS/image checks from step 2:

```sh
vidra setup --check env/production.env
vidra deploy
vidra doctor
```

**On v0.7.5, also turn the runtime admin setting `storyboards_enabled` off before
starting the actual run.** `TRANSCODING_ENABLED=false` does not stop storyboard
backfill. Without this step, backfill can decode originals before the importer's
later storyboard pass, and the default rerun policy can preserve that generated
sheet instead of the source one. The setting takes effect without an API restart;
existing source sheets can still be copied and served. Do not assume an unreleased
worker guard is present in a released image. Keep this pause step even with a
guard for queued imports: a decode may already be running, and the standalone
CLI does not create the admin/API run record that such a guard checks.

The example intentionally chooses **unlimited storage for all users**: default
quota `0` is unlimited. Newly imported accounts also receive a per-user quota of
`0`; PeerTube's quota values are not preserved. Existing finite user overrides
still win over the default, and reruns do not automatically clear them. Inventory
those overrides and apply the chosen policy through supported administration
before opening the service. Unlimited quota does not create unlimited disk or
remove upload-size, rate or provider limits.

Claim the candidate owner through HTTPS using a unique username/email that does
not collide with a source account. Store its credentials privately. `skip` maps
colliding source entities onto existing rows; it is not a reason to ignore an
owner collision. If using `API_ROLE=api`, enable and verify a worker too;
otherwise imports stay pending. The default `API_ROLE=all` runs workers itself.

## 6. Preview, resolve exceptions, then launch the actual copy

Sign in as the owner and open `/admin/import-peertube`. Select `copy`, the chosen
conflict policy and a preview. The equivalent authenticated API body for
`POST /api/v1/admin/peertube-import` is:

```json
{"mode":"dry_run","media_mode":"copy","conflict_policy":"skip","source_authoritative":false}
```

Use the signed-in admin UI or a client that reads credentials from a private
file; never paste bearer tokens/passwords into command history. Preview creates
an operational run and may write/delete a small destination storage probe; it
does not import persistent users/videos/media. Review the detected schema,
collisions, planned entity counts and unsupported mappings. Outside the released
schema range, stop for an explicit compatibility investigation rather than
automatically acknowledging the version gate.

Preview is not a full read, copy, image decode, playback or quota-policy audit.
Record anticipated exceptions with a reason, including system actors that do not
map to user/channel artwork. Exception counts are specific to the source: an
observed set of seven artwork exceptions on one migration is **not** an expected
or acceptable default for another.

After review, launch the same request with `"mode":"run"`. Save its run UUID,
snapshot identity, exact flags and start time. Only one run can be active; an
HTTP 409 means inspect the existing run. Do not launch concurrent standalone and
admin imports.

Monitor the admin run detail (`GET /api/v1/admin/peertube-import/{id}`), host
memory/disk/network, worker logs and destination storage errors. This read-only
query gives aggregate ledger progress without exporting account data:

```sql
BEGIN READ ONLY;
SET LOCAL statement_timeout = '30s';
SELECT entity_kind, status, count(*) AS entities, max(updated_at) AS last_write
FROM peertube_import_ledger GROUP BY 1, 2 ORDER BY 1, 2;
SELECT id, state, attempts, updated_at, next_attempt_at, finished_at
FROM peertube_import_runs ORDER BY created_at DESC LIMIT 5;
COMMIT;
```

The ledger is cumulative across runs, keyed by entity kind/source ID; it is not
a per-run byte counter. Run counters can lag an active entity pass. A changing
heartbeat is not evidence of bytes copied, and `done` does not mean zero failed
or unsupported entities. Resolve every required failed/unsupported item and
reconcile final counts. Failed entries are retryable; v0.7.5 treats unsupported
entries as terminal on ordinary reruns. Do not clear the whole ledger or restart
from an empty database merely to retry one asset.

### Deliberately restart a disposable candidate

A clean restart discards candidate state and its ledger. Use it only when that
loss is explicitly intended, with source data and recovery copies preserved.
It is not required to retry failed captions or incomplete HLS trees. Keep the
source domain serving PeerTube throughout this rehearsal.

1. Identify and stop every candidate writer: the API, worker containers and any
   standalone importer. Confirm the old run is
   no longer executing before resetting anything. Record its UUID, parameters,
   ledger counts and checkpoint time; a heartbeat is not a transfer checkpoint.
2. Save the candidate database, configuration, encryption keys and exact image
   references. Preserve the source snapshot, configuration and local media
   separately. Retrieve and verify the recovery copies **outside every bucket
   scheduled for deletion**. Vidra's database/config backup does not contain S3
   media: retain that media separately if exact candidate rollback is required,
   or explicitly accept reconstructing it from the intact source.
3. Build a reviewed deletion allowlist using each **exact destination bucket
   name and immutable bucket ID**, account, endpoint and purpose. Match the
   provider inventory immediately before each deletion; stop on any mismatch.
   No prefix, wildcard or account-wide deletion is appropriate. Exclude all
   source buckets. A candidate backup bucket belongs on the list only after its
   required recovery artifacts have been preserved and verified elsewhere.
4. Reset only the identified **Vidra destination database**. The restored
   PeerTube snapshot may share the PostgreSQL cluster or volume; preserve it
   and its read-only role. Never remove the whole PostgreSQL volume or use
   `docker compose down -v` as a database-reset shortcut. Account for the search
   schema and candidate caches in the reviewed reset procedure.
5. Recreate only the approved destination buckets and record their new IDs.
   Reissue/update scoped destination, backup and optional copy keys where the
   changed IDs require it. Keep ordinary source credentials read-only. Verify
   the new keys against the intended bucket IDs before starting the importer.
6. Deploy the recorded candidate images using the normal gated ordering:
   pre-deploy backup, pull, discrete migrations, service start, then health and
   migration-ledger checks. Configure the intended beta HTTPS origin before
   claiming the fresh owner. Reapply the paused side effects from
   [section 5](#5-pause-side-effects-and-choose-account-policy),
   preview, then create one new run and record its new UUID. An empty destination
   has no previous import ledger to resume; do not describe it as a resume or a
   domain cutover.

## 7. Verify asset reuse, without a blanket re-encode

The released importer does not enqueue a fresh video transcode for each imported
video. Verify these paths against representative public and restricted videos:

| Asset | v0.7.5 behavior | Evidence to collect |
| --- | --- | --- |
| Original/web video | Copies the highest-resolution eligible source file unchanged and records its SHA-256; reference retains its key. It does not copy every old web resolution. | Source/destination byte count and checksum, playable file, correct access control. |
| HLS | Copies a flat master/variant/dependency graph, including byte-range MP4, audio and init objects, without encoding. Publishes the tree after completion; an existing ready tree is preserved. | Fetch master, variants, init/media ranges; decode and seek in a real browser. Check audio and recorded renditions. Do not require native CMAF packaging from a preserved PeerTube tree. |
| Posters, avatars, banners | Copies supported source image bytes. Posters use the selected source preview/thumbnail; a `.jpg` destination name does not imply JPEG conversion. | Image loads and has the right content/type; compare bytes where applicable. |
| Storyboards | Copies the existing sprite sheet and creates WebVTT text from source geometry/duration. No video encoding is needed. | Sheet checksum, VTT URLs/timing and hover preview near the end of the video. |
| Captions | Copies/references supported VTT tracks; reruns fill missing languages without replacing an existing same-language track. | Track language, timing and restricted-video access. |

Copy limits include **16 GiB per source object**; HLS additionally allows at most
**10,000 objects, 64 GiB and 30 minutes per tree**, with **1 MiB manifests** and
flat local dependency names. URLs, nested paths or oversized trees need an
explicit remediation plan. Artwork accepts JPEG/PNG/WebP within the **8 MiB**
cap; a 200 response containing an HTML error page is not a valid image. Classify
missing, inaccessible, oversized and unsupported assets separately.

After source artwork is reconciled, re-enable `storyboards_enabled` if desired.
Missing-sheet backfill samples supported media to generate preview images; it
does not rebuild the video rendition ladder. It is bounded and may not support
every segmented, encrypted or live source layout. Do not enable a blanket
transcode to remedy a missing poster, stale rendition row or transfer failure.

Behavior is grounded in the tagged importer:
[media streaming](https://github.com/yegamble/vidra-core/blob/v0.7.5/internal/peertubeimport/importer.go),
[HLS copy](https://github.com/yegamble/vidra-core/blob/v0.7.5/internal/peertubeimport/copyhls.go),
[artwork](https://github.com/yegamble/vidra-core/blob/v0.7.5/internal/peertubeimport/entities_videoimages.go),
[rerun updates](https://github.com/yegamble/vidra-core/blob/v0.7.5/internal/peertubeimport/resync.go).

## 8. Establish encrypted backups and prove recovery

Vidra's [backup script](../deploy/backup.sh) pairs
`vidra-<stamp>.dump.gz` with `vidra-config-<stamp>.tar.gz`. The latter contains the
selected environment file and local Caddy configuration, including necessary
keys. These archives do **not** contain the media bucket, source snapshot database,
all external configuration, or the keys needed to decrypt an rclone crypt remote.
Plan those separately. Preserve federation/MFA encryption keys; generating new
ones does not recover data encrypted under the old ones.

Configure a current supported rclone with an S3 remote for the backup bucket and
a `crypt` remote wrapping a specific `bucket/path`. For rclone's S3 endpoint use
the full **`https://s3.<region>.backblazeb2.com`** form, unlike Vidra's host-only
field. Test the installed client, not merely its configuration parser. Older
distribution rclone packages can fail with obsolete B2 native API calls; the S3
transport is an alternative, not proof that all native B2 clients are broken.
[rclone S3](https://rclone.org/s3/), [rclone crypt](https://rclone.org/crypt/)

Create the configuration as the backup service user in a private terminal:

```sh
sudo -u vidra -H mkdir -p /home/vidra/.config/rclone
sudo -u vidra -H rclone config --config /home/vidra/.config/rclone/rclone.conf
```

In the interactive prompts:

1. Create `b2-s3`, choose storage `s3`, provider `Other`, and credential entry
   (`env_auth=false`). Enter the **backup bucket's** application key ID/secret
   privately. Set its region and `https://s3.<region>.backblazeb2.com` endpoint.
   Keep ACL private/default; do not choose public-read.
2. Create `offsite`, choose storage `crypt`, and remote
   `b2-s3:YOUR_BACKUP_BUCKET/vidra`. Choose filename encryption `standard` and
   directory-name encryption. Enter a password-manager-generated crypt password
   and salt privately; retain both off server. Save and quit.
3. Restrict the file, then verify access to this specific bucket:

```sh
sudo chmod 700 /home/vidra/.config/rclone
sudo chmod 600 /home/vidra/.config/rclone/rclone.conf
sudo -u vidra -H rclone lsf b2-s3:YOUR_BACKUP_BUCKET \
  --config /home/vidra/.config/rclone/rclone.conf --max-depth 1
```

This listing tests access, not backup success. The service run below proves the
write path. If media and this backup both use the same provider/account, retain
an additional independent recovery copy for provider/account loss.

Store the crypt password/salt and rclone configuration in a separate off-server
recovery location. Keep the service user's local rclone configuration readable
only by that user. Set up `/etc/vidra/backup.env` with a protected editor, owned by
root with mode `0600`:

```dotenv
BACKUP_RCLONE_REMOTE=offsite:
RCLONE_CONFIG=/home/vidra/.config/rclone/rclone.conf
# HEALTHCHECKS_URL=<private dead-man monitoring endpoint, if used>
```

**Released v0.7.5 backup tooling reads its off-site settings from the process
environment.** Merely putting `BACKUP_RCLONE_REMOTE` in `env/production.env` can
leave backups local-only. Newer tooling may load those documented values from
the selected env file; an active systemd `EnvironmentFile` works across both.
`RCLONE_CONFIG` must reach the rclone process environment either way.

Install the timer and make its environment file explicit:

```sh
sudo cp deploy/vidra-backup.service deploy/vidra-backup.timer /etc/systemd/system/
sudo systemctl edit vidra-backup.service
```

Save this drop-in, adapting service paths/user if needed:

```ini
[Service]
EnvironmentFile=/etc/vidra/backup.env
```

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now vidra-backup.timer
sudo systemctl start vidra-backup.service
systemctl list-timers vidra-backup.timer
journalctl -u vidra-backup.service -n 50
```

Require successful uploads of **both archives with the same stamp**. Independently
retrieve/decrypt them on another machine, compare SHA-256 with the originals,
validate gzip/tar and inspect the PostgreSQL archive. Retrieve files before
testing; do not treat a remote listing as recovery. Then perform a full restore
on an isolated host with the same release pairing, config keys and an independent
media recovery source. [Restore procedure](../deploy/restore.sh)

A successful download/checksum is not a database restore, and a database restore
is not media disaster recovery. Establish media version retention/replication,
test lost-object recovery, and document provider/account loss. Keep the source
snapshot/config encrypted separately. Do not prune the source or old object
versions until the retention and rollback decision is explicit.

## 9. Reconcile the final delta and domain behavior

Before the cutover window, account for source writes since the first snapshot.
Freeze source uploads, edits, account changes and moderation writes using a
tested maintenance procedure; refresh the snapshot and any filesystem copy, then
rerun the importer against the **same destination ledger**. Keep source storage
and artwork reachable. Capturing database, files and configuration together is
also the basis of [PeerTube's migration procedure](https://docs.joinpeertube.org/maintain/migration).

The default rerun fills gaps and preserves existing edits. Use
`source_authoritative=true` only after deciding which system owns changes: it can
overwrite supported fields of importer-created rows, while protecting linked
native rows. It is not a full synchronization or deletion mirror. Source-deleted
videos, accounts and comments need explicit reconciliation; supported removal
handling for chapters, ratings, playlist membership and follows does not cover
those entities. Destination-deleted parents are retired rather than resurrected.
Check replaced media/captions and existing renditions separately from metadata.

Compare final identities and visibility/moderation states, not just one catalogue
total. Public/unlisted/private visibility is mapped; PeerTube internal and
password-protected videos become private, and their video-password access
mechanism is not carried. Only source state `published` becomes published;
other states become drafts. Initial inserts carry account suspension and video
blacklist dispositions, but v0.7.5 reruns do not mirror later suspension/blacklist
changes. Reconcile those changes explicitly. Test restricted access anonymously
and as permitted/denied users. Decide how to preserve beta-only activity before
allowing source-authoritative updates or replacing an existing beta installation.

### Preserve account and content restrictions

Keep beta accessible only to operators until these checks pass on the exact
importer build. A copied password hash is not proof that all login protections
survived, and a matching catalogue count does not prove policy parity.

| Source protection | Required destination check |
| --- | --- |
| Per-video downloads and comments | Compare the stored policies, including disabled comments and any approval-only policy. If an approval queue is unsupported, keep comments disabled and report that stricter mapping. |
| User sensitive-content preferences | Compare both the overall policy and category-specific flags. A conservative mapping must not display content the user hid; report lost category granularity. |
| MFA | Inventory enabled status only, without exporting OTP secrets. Require native MFA or an inactive account hold before imported passwords can be used publicly. |
| Personal account/server mutes | Verify the mapped owner and muted target. A content mute is not a symmetric interaction block or an account suspension. |
| Instance account mutes and video blocks | Verify effective discovery/access behavior separately from login suspension; retain the restriction for future content too. |
| Moderation reports | Preserve original status, repeated reports, remote reporters, deleted targets and staff history. A native uniqueness conflict must not silently discard source history. |

For held MFA accounts, keep recovery restricted to a verified operator process.
Do not remove source MFA or treat a password reset as replacement enrollment.
If the selected Vidra build requires an active session to enroll native MFA,
activate only inside an operator-restricted enrollment window, enroll and verify
the factor, then prove a fresh login requires the challenge before public
access. Otherwise leave the account held. Recheck that later import/resync
passes cannot release a hold, and that default reruns preserve intentional
destination edits. Source-authoritative policy repair is a separate, explicit
choice. These are acceptance requirements, not claims that every listed mapping
exists in v0.7.5.

Exercise old `/w/<short-id>` and legacy UUID links against a known sample and
recent source videos; inspect `/api/v1/videos/resolve?legacy_uuid=<uuid>`. Test
embeds, query strings and non-video routes before proposing path-preserving
redirects. A new hostname changes ActivityPub actor/object identities even if
private keys were imported. Core v0.7.5 does not implement a complete ActivityPub
Move migration; an HTTP redirect alone does not preserve old-domain WebFinger,
actors, inboxes or remote followers. Keep federation disabled until the chosen
same-origin or domain-migration strategy is tested end to end. If preserving the
old identity requires serving protocol routes on the original hostname, retain
those routes explicitly rather than redirecting the entire host.

## 10. Accept, switch traffic, and retain rollback

Record pass/fail evidence on the **exact running release manifests**, with the
candidate storage and settings, for:

- Final import counts, required media/artwork and moderation/visibility mapping;
  no unexplained failures or unresolved tombstones.
- Login with imported accounts, owner/admin permissions, password reset and mail
  delivery after deliberate SMTP enablement; registration policy and quotas.
- A small synthetic upload through the real scanner, transcode, browser playback,
  seek, captions, previews, search and deletion lifecycle. Use a dedicated test
  account/channel and clean up only its own test objects through supported APIs.
- Representative imported originals/HLS including restricted media; old links,
  mobile/browser playback, and federation behavior if federation will be enabled.
- Independent database/config **restore**, media recovery, backup alerting and
  recovery from a dependency outage.

The [runtime smoke](../tests/runtime-smoke.sh) and
[release acceptance](../tests/release-acceptance.mjs) harnesses have broader
setup/destructive-test assumptions. Read their prerequisites first; use a
disposable acceptance installation when they require a fresh owner, empty bucket
or recovery drill. Do not run an entire destructive harness on an importing
candidate merely to test one upload.

Only then change DNS/proxy routing. Recheck TLS, runtime API origin, cookies/CORS,
public and restricted playback, search and old URLs through the public hostname.
Enable mail/federation/background features deliberately, with their own checks.
Revoke importer access when the final reconciliation window is closed.

Keep the original service, exact config/release pins, frozen snapshot and source
media available for the rollback window. Define whether rollback returns traffic
to the frozen source and how new Vidra writes will be preserved; a DNS reversal
does not merge them back. Database rollback must match schema compatibility.
For a mixed component release, use the script's explicit component flags rather
than assuming one shared tag:

```sh
# Example release pairing; execute only as part of the agreed rollback plan.
./deploy/rollback.sh --core v0.7.5 --user v0.7.3 --search v0.7.3
```

Until the acceptance and rollback evidence exists, keep the candidate private and
the original domain serving the source.
