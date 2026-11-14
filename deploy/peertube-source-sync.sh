#!/usr/bin/env bash
# Refresh the PeerTube source snapshot the importer reads.
#
#   ./deploy/peertube-source-sync.sh --dump-file /secure/peertube.dump
#   ssh source 'pg_dump --format=custom peertube_prod' \
#     | ssh candidate /opt/vidra/deploy/peertube-source-sync.sh --dump-file -
#   PEERTUBE_SYNC_SSH=dump@source ./deploy/peertube-source-sync.sh   # unattended
#
# WHY this exists. The importer never talks to the live PeerTube database: it
# reads a restored copy (PEERTUBE_SOURCE_DATABASE_URL) through a read-only role,
# so "import everything new" silently means "everything new AS OF THE LAST TIME
# SOMEONE RESTORED A DUMP BY HAND". docs/peertube-migration.md §3 is that hand
# procedure — eleven commands across two hosts — and a stale snapshot looks
# exactly like a healthy import that found nothing to do. This script is §3 as
# one command, safe to put on a timer (deploy/vidra-peertube-source-sync.timer).
#
# What it does, in order — every step is a gate, and nothing the importer can
# see changes until the last one:
#
#   1. Spool the dump to disk (.part, 0600), record its SHA-256, and parse its
#      table of contents. A truncated stream is rejected here, not half-restored.
#   2. Refuse while an import run is pending or running. The run holds a
#      snapshot of the source open for its whole duration; swapping the database
#      under it would hand one run two different sources.
#   3. Restore into a NEW database (<name>_incoming) and apply the read-only
#      grants from migration.md §3 there. The live snapshot is untouched, so a
#      failed restore costs nothing.
#   4. Verify the new copy: the reader role really is read-only, and it does not
#      hold FEWER local videos than the snapshot it replaces (see the shrink
#      guard below).
#   5. Swap by rename in ONE transaction: current → <name>_prev_<stamp>,
#      incoming → current. Grants and the per-database read-only default follow
#      the database through a rename (they are keyed by OID), and the DSN in
#      the env file never changes, so the api needs no restart.
#   6. Drop all but the newest KEEP_PREVIOUS retired snapshots — only databases
#      THIS script named (<name>_prev_<digits>); a hand-made copy is never
#      touched.
#
# It does NOT start an import run. That is an authenticated admin action
# (Admin → Import from PeerTube, or POST /api/v1/admin/peertube-import) and is
# deliberately left one: a refreshed snapshot is inert until an operator, or
# their own credentialed automation, launches a run against it.
#
# The source side. For unattended runs give the source host a key that can do
# exactly one thing — in the dumping user's ~/.ssh/authorized_keys:
#
#   restrict,command="pg_dump --format=custom <source_db>" ssh-ed25519 AAAA… vidra-peertube-sync
#
# `restrict` + a forced command means the key yields a dump and nothing else,
# whatever command the client asks for. pg_dump takes an MVCC snapshot and does
# not lock writers out; it is safe against a serving PeerTube.
#
# Bundled Postgres only: the restore goes through `docker exec` into the
# compose `postgres` service. With an external database, restore the snapshot
# with your provider's tooling and follow migration.md §3 by hand.

set -euo pipefail

# The dump is the source instance's whole database — password hashes, emails,
# private video rows. Restrict creation, including the .part file.
umask 077

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

ENV_FILE="${ENV_FILE:-env/production.env}"

log()  { printf '[peertube-source-sync] %s\n' "$*"; }
die()  { printf '[peertube-source-sync] ERROR: %s\n' "$*" >&2; exit 1; }

usage() {
  cat <<'EOF'
Usage: deploy/peertube-source-sync.sh [--dump-file PATH|-] [--allow-shrink]

  --dump-file PATH   restore this pg_dump custom-format archive ('-' = stdin).
                     Without it, the dump is pulled over SSH from
                     PEERTUBE_SYNC_SSH (user@host; see the header).
  --allow-shrink     swap even if the new snapshot holds fewer local videos
                     than the current one.

Environment (process value wins, else ENV_FILE):
  PEERTUBE_SYNC_SSH            user@host to pull the dump from
  PEERTUBE_SYNC_SSH_KEY        identity file for that connection (optional)
  PEERTUBE_SYNC_SPOOL_DIR      where the dump is spooled (default backups/peertube-source)
  PEERTUBE_SYNC_KEEP_DUMP      true keeps the spooled dump after a good restore
  PEERTUBE_SYNC_KEEP_PREVIOUS  retired snapshots to keep (default 2)
  PEERTUBE_SYNC_HEALTHCHECKS_URL  dead-man's-switch ping (/start, /fail)
EOF
}

DUMP_FILE=""
ALLOW_SHRINK=0
while [ $# -gt 0 ]; do
  case "$1" in
    --dump-file) [ $# -ge 2 ] || die "--dump-file needs a path (or '-')"; DUMP_FILE="$2"; shift 2 ;;
    --dump-file=*) DUMP_FILE="${1#*=}"; shift ;;
    --allow-shrink) ALLOW_SHRINK=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; die "unknown argument: $1" ;;
  esac
done

[ -f "$ENV_FILE" ] || die "env file not found: $ENV_FILE (cp env/production.env.example env/production.env)"

# shellcheck source=deploy/lib.sh
. "$REPO_ROOT/deploy/lib.sh"

PGUSER="$(env_get POSTGRES_USER vidra)"
PGDB="$(env_get POSTGRES_DB vidra)"

# Sets COMPOSE, EXTERNAL_POSTGRES and EXTERNAL_REDIS.
vidra_compose_chain

SYNC_SSH="${PEERTUBE_SYNC_SSH-$(env_get PEERTUBE_SYNC_SSH '')}"
SYNC_SSH_KEY="${PEERTUBE_SYNC_SSH_KEY-$(env_get PEERTUBE_SYNC_SSH_KEY '')}"
SPOOL_DIR="${PEERTUBE_SYNC_SPOOL_DIR-$(env_get PEERTUBE_SYNC_SPOOL_DIR '')}"
SPOOL_DIR="${SPOOL_DIR:-$REPO_ROOT/backups/peertube-source}"
KEEP_DUMP="${PEERTUBE_SYNC_KEEP_DUMP-$(env_get PEERTUBE_SYNC_KEEP_DUMP false)}"
KEEP_PREVIOUS="${PEERTUBE_SYNC_KEEP_PREVIOUS-$(env_get PEERTUBE_SYNC_KEEP_PREVIOUS 2)}"
HC_URL="${PEERTUBE_SYNC_HEALTHCHECKS_URL-$(env_get PEERTUBE_SYNC_HEALTHCHECKS_URL '')}"

case "$KEEP_PREVIOUS" in
  ''|*[!0-9]*) die "PEERTUBE_SYNC_KEEP_PREVIOUS must be a non-negative integer, got '$KEEP_PREVIOUS'" ;;
esac

if [ "$EXTERNAL_POSTGRES" -eq 1 ]; then
  die "VIDRA_EXTERNAL_POSTGRES=true in $ENV_FILE — this script restores through the bundled postgres container. Restore the snapshot with your provider's tooling and follow docs/peertube-migration.md §3. Nothing was changed."
fi

# The snapshot database and the reader role are whatever the importer is
# ACTUALLY configured to read — parsed from the DSN rather than assumed, so
# this can never refresh a database the importer is not looking at.
DSN="$(env_get PEERTUBE_SOURCE_DATABASE_URL '')"
[ -n "$DSN" ] || die "PEERTUBE_SOURCE_DATABASE_URL is empty in $ENV_FILE — nothing reads a snapshot here, so there is nothing to refresh"
case "$DSN" in
  postgres://*|postgresql://*) ;;
  *) die "PEERTUBE_SOURCE_DATABASE_URL is not a postgres:// URL" ;;
esac
dsn_rest="${DSN#*://}"
dsn_userinfo="${dsn_rest%@*}"
dsn_hostpath="${dsn_rest##*@}"
[ "$dsn_userinfo" != "$dsn_rest" ] || die "PEERTUBE_SOURCE_DATABASE_URL carries no user — the importer must connect as the read-only role"
READER_ROLE="${dsn_userinfo%%:*}"
dsn_hostport="${dsn_hostpath%%/*}"
dsn_host="${dsn_hostport%%:*}"
dsn_path="${dsn_hostpath#*/}"
SNAP_DB="${dsn_path%%\?*}"

# The DSN's host must be the compose service this script execs into. Anything
# else means the importer reads a database on another machine, and restoring
# here would refresh a copy nothing looks at while reporting success.
[ "$dsn_host" = "postgres" ] || die "PEERTUBE_SOURCE_DATABASE_URL points at host '$dsn_host', not the bundled 'postgres' service — refresh that database where it lives. Nothing was changed."

# Both names are interpolated into SQL as identifiers. Postgres would accept
# far more under quoting; this script deliberately does not.
ident_ok() { case "$1" in ''|[!a-z_]*|*[!a-z0-9_]*) return 1 ;; *) return 0 ;; esac; }
ident_ok "$SNAP_DB"     || die "snapshot database name '$SNAP_DB' is not a plain lowercase identifier"
ident_ok "$READER_ROLE" || die "reader role '$READER_ROLE' is not a plain lowercase identifier"
ident_ok "$PGDB"        || die "POSTGRES_DB '$PGDB' is not a plain lowercase identifier"
[ "$SNAP_DB" != "$PGDB" ] || die "PEERTUBE_SOURCE_DATABASE_URL names the application database '$PGDB' — refusing to replace it"
[ "$READER_ROLE" != "$PGUSER" ] || die "PEERTUBE_SOURCE_DATABASE_URL connects as the admin role '$PGUSER' — the importer must use a dedicated read-only role (docs/peertube-migration.md §3)"

INCOMING_DB="${SNAP_DB}_incoming"
STAMP="$(date -u +%Y%m%d%H%M%S)"
PREV_DB="${SNAP_DB}_prev_${STAMP}"

if [ -z "$DUMP_FILE" ] && [ -z "$SYNC_SSH" ]; then
  usage >&2
  die "no dump to restore: pass --dump-file, or set PEERTUBE_SYNC_SSH"
fi

hc_ping() {
  [ -n "$HC_URL" ] || return 0
  curl -fsS -m 10 --retry 3 -o /dev/null "${HC_URL}${1:-}" || true
}
# shellcheck disable=SC2154  # rc IS assigned — by the first statement of this very trap body.
trap 'rc=$?; [ -z "${SPOOL_PART:-}" ] || rm -f "$SPOOL_PART"; if [ "$rc" -ne 0 ]; then hc_ping /fail; fi; exit "$rc"' EXIT
hc_ping /start

PG_CID="$("${COMPOSE[@]}" ps -q postgres || true)"
[ -n "$PG_CID" ] || die "the postgres service is not running (start the stack first, or check ENV_FILE=$ENV_FILE)"

# psql_at DB SQL — one statement batch, tuples only, stop on the first error.
# stdin is /dev/null on purpose: with `--dump-file -` this script's own stdin
# IS the dump, and a child that inherited it would eat part of the archive.
psql_at() {
  docker exec "$PG_CID" psql -X -At -v ON_ERROR_STOP=1 -U "$PGUSER" -d "$1" -c "$2" </dev/null
}

db_exists() {
  [ "$(psql_at "$PGDB" "SELECT 1 FROM pg_database WHERE datname = '$1'")" = "1" ]
}

# An import run reads the source for its whole duration. `to_regclass` keeps
# this honest on a core old enough to have no importer tables: no table means
# no run can be active, which is different from "the query failed".
active_import_runs() {
  psql_at "$PGDB" "SELECT CASE WHEN to_regclass('public.peertube_import_runs') IS NULL THEN 0 ELSE (SELECT count(*) FROM peertube_import_runs WHERE state IN ('pending','running')) END"
}
refuse_if_import_active() {
  local n
  n="$(active_import_runs)"
  [ "$n" = "0" ] || die "$n PeerTube import run(s) pending or running — refusing to replace the source under a live run. Wait for it to finish (Admin → Import from PeerTube) and re-run. $1"
}

refuse_if_import_active "Nothing was changed."

# ---------------------------------------------------------------- 1. spool --
mkdir -p "$SPOOL_DIR"
SPOOL="$SPOOL_DIR/peertube-source-${STAMP}.dump"
SPOOL_PART="${SPOOL}.part"

if [ -n "$DUMP_FILE" ] && [ "$DUMP_FILE" != "-" ]; then
  [ -r "$DUMP_FILE" ] || die "dump file not readable: $DUMP_FILE"
  log "reading dump from $DUMP_FILE"
  cp -- "$DUMP_FILE" "$SPOOL_PART"
elif [ "$DUMP_FILE" = "-" ]; then
  log "reading dump from stdin"
  cat > "$SPOOL_PART"
else
  log "pulling dump over ssh from $SYNC_SSH"
  SSH_ARGS=(-o BatchMode=yes -o ConnectTimeout=20 -o ServerAliveInterval=30)
  [ -z "$SYNC_SSH_KEY" ] || SSH_ARGS+=(-i "$SYNC_SSH_KEY" -o IdentitiesOnly=yes)
  # The remote command is a label, not an instruction: the source's forced
  # command decides what runs. BatchMode makes a missing key fail at once
  # instead of a timer unit waiting forever at a password prompt.
  ssh "${SSH_ARGS[@]}" "$SYNC_SSH" vidra-peertube-source-dump </dev/null > "$SPOOL_PART" \
    || die "the ssh dump from $SYNC_SSH failed — the current snapshot is untouched"
fi

[ -s "$SPOOL_PART" ] || die "the dump is empty — the current snapshot is untouched"

# pg_restore -l parses the archive's table of contents without touching a
# database. A stream cut short mid-transfer fails here; so does a plain-SQL
# dump, which this script does not restore.
log "verifying archive"
docker exec -i "$PG_CID" pg_restore -l < "$SPOOL_PART" > /dev/null \
  || die "the dump is not a readable pg_dump custom-format archive (truncated transfer, or made without --format=custom) — the current snapshot is untouched"

if command -v sha256sum >/dev/null 2>&1; then
  SHA="$(sha256sum "$SPOOL_PART" | cut -d' ' -f1)"
else
  SHA="$(shasum -a 256 "$SPOOL_PART" | cut -d' ' -f1)"
fi
mv "$SPOOL_PART" "$SPOOL"
SPOOL_PART=""
log "dump $(du -h "$SPOOL" | cut -f1)  sha256=$SHA"

# -------------------------------------------------------------- 3. restore --
# A leftover incoming database is a previous run that died mid-restore. Nothing
# references it, so dropping it is safe — and plain DROP (no FORCE) fails if a
# CONCURRENT run of this script is still restoring into it, which is the one
# case where it must not go.
if db_exists "$INCOMING_DB"; then
  log "dropping leftover $INCOMING_DB from an earlier interrupted run"
  psql_at "$PGDB" "DROP DATABASE $INCOMING_DB" \
    || die "could not drop $INCOMING_DB — is another peertube-source-sync still running?"
fi

log "restoring into $INCOMING_DB"
psql_at "$PGDB" "CREATE DATABASE $INCOMING_DB"
# --no-owner/--no-acl: the source's roles do not exist here and must not be
# recreated; the only access this database gets is the grant block below.
docker exec -i "$PG_CID" pg_restore --exit-on-error --no-owner --no-acl \
  -U "$PGUSER" -d "$INCOMING_DB" < "$SPOOL" \
  || die "pg_restore failed — $INCOMING_DB is incomplete and will be dropped by the next run; the current snapshot is untouched"

log "applying read-only grants for $READER_ROLE"
psql_at "$INCOMING_DB" "
REVOKE ALL ON DATABASE $INCOMING_DB FROM PUBLIC;
GRANT CONNECT ON DATABASE $INCOMING_DB TO $READER_ROLE;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO $READER_ROLE;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO $READER_ROLE;
ALTER ROLE $READER_ROLE IN DATABASE $INCOMING_DB SET default_transaction_read_only = on;
" > /dev/null

# --------------------------------------------------------------- 4. verify --
# Asked of the catalog rather than assumed from the block above having exited
# 0: this is the property the whole design leans on.
can_write="$(psql_at "$INCOMING_DB" "SELECT has_table_privilege('$READER_ROLE', 'public.video', 'INSERT, UPDATE, DELETE')")"
[ "$can_write" = "f" ] || die "$READER_ROLE can write to $INCOMING_DB.public.video (got '$can_write') — refusing to publish a writable source"
can_read="$(psql_at "$INCOMING_DB" "SELECT has_table_privilege('$READER_ROLE', 'public.video', 'SELECT')")"
[ "$can_read" = "t" ] || die "$READER_ROLE cannot read $INCOMING_DB.public.video — the importer would fail on its first query"

local_videos_sql='SELECT count(*) FROM video WHERE remote = false'
new_videos="$(psql_at "$INCOMING_DB" "$local_videos_sql")"
new_schema="$(psql_at "$INCOMING_DB" 'SELECT "migrationVersion" FROM application')"
log "new snapshot: $new_videos local videos, PeerTube schema $new_schema"

HAVE_CURRENT=0
if db_exists "$SNAP_DB"; then
  HAVE_CURRENT=1
  old_videos="$(psql_at "$SNAP_DB" "$local_videos_sql")"
  old_schema="$(psql_at "$SNAP_DB" 'SELECT "migrationVersion" FROM application')"
  log "current snapshot: $old_videos local videos, PeerTube schema $old_schema"
  # Shrink guard. A live instance loses the odd video to deletion, but a
  # snapshot with fewer local videos than the last one is far more often the
  # WRONG database (a staging copy, an empty install) restored successfully —
  # and with source_authoritative that reads as "delete everything missing".
  if [ "$new_videos" -lt "$old_videos" ] && [ "$ALLOW_SHRINK" -ne 1 ]; then
    die "the new snapshot holds FEWER local videos ($new_videos) than the current one ($old_videos). If the source really shrank, re-run with --allow-shrink. $INCOMING_DB is left in place for inspection; the current snapshot is untouched."
  fi
  if [ "$new_schema" != "$old_schema" ]; then
    log "WARNING: the source's PeerTube schema changed ($old_schema → $new_schema). The importer pins the schema it was acknowledged against; expect the next run to ask for a new acknowledgement."
  fi
fi

# ----------------------------------------------------------------- 5. swap --
# Checked again here, not only at the top: the restore takes minutes, and an
# operator may have started a run in the meantime.
refuse_if_import_active "$INCOMING_DB is restored and left in place; re-running will rebuild it."

log "publishing: $INCOMING_DB → $SNAP_DB"
# One transaction, so there is no moment at which the DSN names nothing — a
# failure anywhere rolls the whole swap back. ALLOW_CONNECTIONS false before the
# terminate closes the window in which a pooled client reconnects between the
# two statements and makes the rename fail with "being accessed by other
# users". The retired copy STAYS closed to new connections: nothing should be
# reading a superseded source by accident (ALTER DATABASE … ALLOW_CONNECTIONS
# true to inspect one).
if [ "$HAVE_CURRENT" -eq 1 ]; then
  psql_at "$PGDB" "
BEGIN;
ALTER DATABASE $SNAP_DB ALLOW_CONNECTIONS false;
SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname IN ('$SNAP_DB', '$INCOMING_DB') AND pid <> pg_backend_pid();
ALTER DATABASE $SNAP_DB RENAME TO $PREV_DB;
ALTER DATABASE $INCOMING_DB RENAME TO $SNAP_DB;
COMMIT;
" > /dev/null || die "the swap failed and was rolled back — $SNAP_DB is still the previous snapshot; $INCOMING_DB is left in place"
  log "previous snapshot retired as $PREV_DB"
else
  psql_at "$PGDB" "ALTER DATABASE $INCOMING_DB RENAME TO $SNAP_DB" > /dev/null
fi

# The read-only default is stored per (role, database OID), so it should have
# followed the rename. Asserted as the reader's own setting on the PUBLISHED
# name, because that is what the importer will get.
ro="$(psql_at "$PGDB" "SELECT count(*) FROM pg_db_role_setting s JOIN pg_database d ON d.oid = s.setdatabase JOIN pg_roles r ON r.oid = s.setrole WHERE d.datname = '$SNAP_DB' AND r.rolname = '$READER_ROLE' AND 'default_transaction_read_only=on' = ANY (s.setconfig)")"
[ "$ro" = "1" ] || die "$READER_ROLE has no default_transaction_read_only=on on $SNAP_DB after the swap — investigate before starting an import run"

# ------------------------------------------------------------ 6. retention --
# Only names this script generates: <name>_prev_ + 14 digits. `_` is a LIKE
# wildcard, so the SQL match is a prefilter and the shell pattern is the gate.
kept=0
while IFS= read -r db; do
  case "$db" in
    "${SNAP_DB}_prev_"[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]) ;;
    *) continue ;;
  esac
  kept=$((kept + 1))
  if [ "$kept" -gt "$KEEP_PREVIOUS" ]; then
    log "dropping retired snapshot $db (keeping $KEEP_PREVIOUS)"
    psql_at "$PGDB" "DROP DATABASE $db" > /dev/null \
      || log "WARNING: could not drop $db — drop it by hand; the refresh itself succeeded"
  fi
done < <(psql_at "$PGDB" "SELECT datname FROM pg_database WHERE datname LIKE '${SNAP_DB}_prev_%' ORDER BY datname DESC")

if is_true "$KEEP_DUMP"; then
  log "kept the spooled dump at $SPOOL"
else
  # The restored database IS the copy; a second plaintext copy of the source's
  # accounts on disk is only exposure.
  rm -f "$SPOOL"
fi

hc_ping
log "done: $SNAP_DB now holds $new_videos local videos (sha256=$SHA)."
log "this did not start an import. Launch one from Admin → Import from PeerTube."
