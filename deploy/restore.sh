#!/usr/bin/env bash
#
# DESTRUCTIVE. Restores a pg_dump archive over the live Vidra database.
#
#   RESTORE_CONFIRM=vidra ./deploy/restore.sh backups/vidra-20260728T030000Z.dump.gz
#   ./deploy/restore.sh --yes backups/pre-deploy-2026-07-28T031500.dump.gz
#
# Accepts either a .dump or a .dump.gz produced by deploy/backup.sh or
# deploy/deploy.sh (both write custom-format archives).
#
# THIS DROPS THE DATABASE. Everything written since the dump is gone — accounts,
# videos, comments, moderation decisions. It refuses to run without an explicit
# confirmation (see CONFIRMATION below).
#
# Why drop-and-create rather than `pg_restore --clean` into a live database:
# --clean issues DROP for each object it knows about, which leaves behind
# anything the dump does not mention (a table added by a migration that ran after
# the dump, for instance) and produces a hybrid schema that then fails migration.
# A fresh database is the only state we can reason about.
#
# Run this at least once against a real dump BEFORE you need it. Neither the 101
# down-migrations nor this path have ever been exercised end to end.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

ENV_FILE="${ENV_FILE:-env/production.env}"
READY_TIMEOUT="${READY_TIMEOUT:-120}"
JOBS="${RESTORE_JOBS:-4}"

log() { printf '[restore] %s\n' "$*"; }
die() { printf '[restore] ERROR: %s\n' "$*" >&2; exit 1; }

FORCE=0
DUMP=""
while [ $# -gt 0 ]; do
  case "$1" in
    --yes|-y) FORCE=1 ;;
    -h|--help) sed -n '2,25p' "$0"; exit 0 ;;
    -*) die "unknown option: $1" ;;
    *)  DUMP="$1" ;;
  esac
  shift
done

[ -n "$DUMP" ] || die "usage: $0 [--yes] <dump-file>"
[ -f "$DUMP" ] || die "dump not found: $DUMP"
[ -f "$ENV_FILE" ] || die "env file not found: $ENV_FILE"

# The prod overlay closes Postgres/Redis/search with the `!reset` / `!override`
# merge tags, which need Compose >= 2.24. An older Compose does not error on
# them — it IGNORES them, sequence-merges the ports, and the `up -d` at the end
# of this script would republish Postgres and Redis on 0.0.0.0 — while the
# database is at its most valuable, freshly restored. Refuse rather than warn.
# Kept identical in deploy.sh and rollback.sh.
require_compose_version() {
  local v major minor
  v="$(docker compose version --short 2>/dev/null || true)"
  [ -n "$v" ] || die "docker compose (v2) not found — 'docker compose version' must work; need >= 2.24"
  v="${v#v}"
  major="${v%%.*}"
  minor="${v#*.}"; minor="${minor%%.*}"
  case "${major}.${minor}" in
    *[!0-9.]*|.*|*.) die "cannot parse docker compose version '$v' — need >= 2.24" ;;
  esac
  if [ "$major" -lt 2 ] || { [ "$major" -eq 2 ] && [ "$minor" -lt 24 ]; }; then
    die "docker compose $v is too old. docker-compose.prod.yml uses the !reset/!override merge tags (Compose >= 2.24); an older Compose silently ignores them and leaves Postgres and Redis published on 0.0.0.0. Upgrade the docker-compose-plugin / docker-compose-v2 package before restoring."
  fi
}
require_compose_version

# See the identical helper in backup.sh: read, never source, an operator-edited
# secrets file.
env_get() {
  local key="$1" def="${2-}" val
  val="$(printenv "$key" 2>/dev/null || true)"
  if [ -z "$val" ]; then
    val="$(sed -n "s/^[[:space:]]*${key}[[:space:]]*=[[:space:]]*//p" "$ENV_FILE" | tail -n1 | tr -d '\r')"
    case "$val" in
      \"*\") val="${val%\"}"; val="${val#\"}" ;;
      \'*\') val="${val%\'}"; val="${val#\'}" ;;
    esac
  fi
  printf '%s' "${val:-$def}"
}

PGUSER="$(env_get POSTGRES_USER vidra)"
PGDB="$(env_get POSTGRES_DB vidra)"
HTTP_PORT="$(env_get HTTP_PORT 8080)"

COMPOSE=(docker compose
  -f docker-compose.yml
  -f docker-compose.prod.yml
  --env-file "$ENV_FILE"
  --profile core --profile frontend)

# --- CONFIRMATION --------------------------------------------------------------
# Two accepted forms, because the two callers are different: a human at a
# terminal passes --yes after reading the warning; an automated drill (the
# rehearsal on a throwaway droplet) sets RESTORE_CONFIRM to the database name so
# a copy-pasted command cannot destroy the wrong instance.
if [ "$FORCE" -ne 1 ] && [ "${RESTORE_CONFIRM:-}" != "$PGDB" ]; then
  cat >&2 <<EOF
[restore] REFUSING TO RUN.

  This will DROP the database '${PGDB}' on the stack described by ${ENV_FILE}
  and replace it with the contents of:

      ${DUMP}

  Every row written after that dump was taken will be permanently lost.

  To proceed, either:
      RESTORE_CONFIRM=${PGDB} $0 ${DUMP}
  or:
      $0 --yes ${DUMP}
EOF
  exit 1
fi

PG_CID="$("${COMPOSE[@]}" ps -q postgres || true)"
[ -n "$PG_CID" ] || die "the postgres service is not running — start it first: ${COMPOSE[*]} up -d postgres"

# --- stop everything holding a connection --------------------------------------
# api is the obvious one. search is the easy one to forget: it shares this exact
# database in the `search` schema, so leaving it up means it reconnects into a
# half-restored database and logs errors for the whole restore. frontend goes
# too, so nobody sees a site backed by a database mid-restore.
log "stopping api, search and frontend"
"${COMPOSE[@]}" stop api search frontend

# --- normalise the archive to an uncompressed file INSIDE the container --------
# pg_restore -j (parallel) requires a SEEKABLE archive: it cannot read from a
# pipe or from stdin. So the dump is decompressed on the host and copied in,
# rather than streamed. The temp files are removed on every exit path.
HOST_TMP="$(mktemp -t vidra-restore.XXXXXX)"
CONTAINER_TMP="/tmp/vidra-restore-$$.dump"
cleanup() {
  rm -f "$HOST_TMP"
  docker exec "$PG_CID" rm -f "$CONTAINER_TMP" >/dev/null 2>&1 || true
}
trap cleanup EXIT

case "$DUMP" in
  *.gz) log "decompressing $(basename "$DUMP")"; gzip -dc "$DUMP" > "$HOST_TMP" ;;
  *)    cp "$DUMP" "$HOST_TMP" ;;
esac

log "copying archive into the postgres container"
docker cp "$HOST_TMP" "${PG_CID}:${CONTAINER_TMP}"

# Validate BEFORE dropping anything. A corrupt archive discovered after the drop
# leaves the instance with no database at all.
docker exec -i "$PG_CID" pg_restore -l "$CONTAINER_TMP" > /dev/null \
  || die "archive is not a readable custom-format dump — nothing was dropped"

# --- drop + create -------------------------------------------------------------
# --force (PG13+) terminates remaining backends; there should be none left after
# the stop above, but a stray psql or a slow-draining connection would otherwise
# make dropdb fail. Connecting through the maintenance `postgres` database
# because you cannot drop the database you are connected to.
log "dropping and recreating '${PGDB}'"
docker exec -i "$PG_CID" dropdb -U "$PGUSER" --force --if-exists "$PGDB"
docker exec -i "$PG_CID" createdb -U "$PGUSER" -O "$PGUSER" "$PGDB"

log "restoring with ${JOBS} parallel jobs"
docker exec -i "$PG_CID" pg_restore -U "$PGUSER" -d "$PGDB" -j "$JOBS" "$CONTAINER_TMP"

# --- confirm the schema version ------------------------------------------------
# The dump carries whatever schema version was current when it was taken. Running
# both migrators brings it to HEAD if the dump is older than the deployed code,
# and is a no-op otherwise. If a migrator reports "dirty", follow the
# "Migration failed mid-deploy" runbook section in deploy/README.md.
log "running core migrations"
"${COMPOSE[@]}" run --rm migrate
log "running search migrations"
"${COMPOSE[@]}" run --rm search-migrate

# --- back up ---------------------------------------------------------------
log "starting api, search and frontend"
"${COMPOSE[@]}" up -d --no-build api search frontend

log "waiting up to ${READY_TIMEOUT}s for http://127.0.0.1:${HTTP_PORT}/readyz"
deadline=$(( $(date +%s) + READY_TIMEOUT ))
until curl -fsS -m 5 -o /dev/null "http://127.0.0.1:${HTTP_PORT}/readyz"; do
  [ "$(date +%s)" -lt "$deadline" ] || die "api did not become ready within ${READY_TIMEOUT}s — check: ${COMPOSE[*]} logs api"
  sleep 3
done

log "restore complete; /readyz is 200"
