#!/usr/bin/env bash
#
# DESTRUCTIVE. Restores a pg_dump archive over the live Vidra database.
#
#   RESTORE_CONFIRM=vidra ./deploy/restore.sh backups/vidra-20260728T030000Z.dump.gz
#   ./deploy/restore.sh --yes backups/pre-deploy-2026-07-28T031500.dump.gz
#
# Options:
#   --yes, -y                 skip the confirmation prompt (see CONFIRMATION)
#   --allow-schema-mismatch   proceed even when the SCHEMA PREFLIGHT says the
#                             pinned images cannot reach the dump's schema. Only
#                             do this if you know why: the default refusal exists
#                             because the migrators run AFTER the database has
#                             been dropped and reloaded, so the failure it
#                             prevents is unrecoverable from the script's output.
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
#
# It REFUSES a core/search tag below MIN_EMBEDDED_MIGRATE_TAG (set below): those
# images have no embedded `migrate` subcommand, so the two migrators run after the
# drop would boot API servers that never exit, hanging the restore with the
# database already replaced.
#
# SCHEMA PREFLIGHT. It also refuses, BEFORE the drop, a dump whose schema the
# PINNED images cannot reach — a dump at 137 under VIDRA_CORE_TAG=v0.6.2, whose
# migrator embeds up to 125. Exactly one pairing works and nothing used to check
# it (A38, 2026-09-07): the script dropped the database, reloaded it, and then
# died at "running core migrations" with the site dark and nothing in the output
# saying why. --allow-schema-mismatch overrides.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

ENV_FILE="${ENV_FILE:-env/production.env}"
READY_TIMEOUT="${READY_TIMEOUT:-120}"
JOBS="${RESTORE_JOBS:-4}"

# The FIRST release whose vidra-core / vidra-search images carry the embedded
# `migrate` subcommand. ADJUST THIS AT RELEASE TIME — set it to the tag actually
# cut with the embedded migrator, and never lower it afterwards.
#
# WHY IT IS A HARD GATE, HERE OF ALL PLACES: this script drops the database and
# then runs BOTH migration one-shots to bring the restored dump up to HEAD.
# docker-compose.prod.yml runs them from the SERVICE image, whose compose command
# is `migrate up`, and an OLDER image's main() ignores argv completely and starts
# the API SERVER instead. The one-shot never exits, so the restore HANGS after the
# drop — with the archive already restored but the schema unverified and the site
# still down. Refusing the tag up front is the readable outcome.
# Kept identical in deploy.sh and rollback.sh.
MIN_EMBEDDED_MIGRATE_TAG="v0.2.0"

log() { printf '[restore] %s\n' "$*"; }
die() { printf '[restore] ERROR: %s\n' "$*" >&2; exit 1; }

FORCE=0
ALLOW_SCHEMA_MISMATCH=0
DUMP=""
while [ $# -gt 0 ]; do
  case "$1" in
    --yes|-y) FORCE=1 ;;
    --allow-schema-mismatch) ALLOW_SCHEMA_MISMATCH=1 ;;
    -h|--help) sed -n '2,43p' "$0"; exit 0 ;;
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

# semver_ge <tag> <floor> — numeric MAJOR.MINOR.PATCH comparison of two vX.Y.Z
# tags. Exit 0 when <tag> >= <floor>, 1 when it is older, and 2 when <tag> is not
# semver-shaped at all (so the caller can say "cannot check" instead of guessing).
# A prerelease/build suffix is ignored on purpose: v0.2.0-rc1 is built from the
# v0.2.0 code and carries the same migrator, so it counts as v0.2.0 here.
# Kept identical in deploy.sh and rollback.sh.
semver_ge() {
  local a="${1#v}" b="${2#v}" i ai bi
  a="${a%%-*}"; a="${a%%+*}"
  b="${b%%-*}"; b="${b%%+*}"
  local -a A B
  IFS=. read -r -a A <<<"$a"
  IFS=. read -r -a B <<<"$b"
  [ "${#A[@]}" -eq 3 ] || return 2
  for i in 0 1 2; do
    case "${A[i]}" in ''|*[!0-9]*) return 2 ;; esac
    ai=$((10#${A[i]}))
    bi=$((10#${B[i]:-0}))
    if [ "$ai" -gt "$bi" ]; then return 0; fi
    if [ "$ai" -lt "$bi" ]; then return 1; fi
  done
  return 0
}

# Refuse a tag whose image predates the embedded `migrate` subcommand — see
# MIN_EMBEDDED_MIGRATE_TAG above for what such an image does to a restore.
# An empty tag is left alone: the compose render reports unset image tags with a
# better message than this can (`${VIDRA_*_TAG:?}`).
# Kept identical in deploy.sh and rollback.sh.
require_embedded_migrate_tag() {
  local what="$1" tag="$2" rc=0
  [ -n "$tag" ] || return 0
  semver_ge "$tag" "$MIN_EMBEDDED_MIGRATE_TAG" || rc=$?
  case "$rc" in
    0) return 0 ;;
    2) die "$what=$tag is not a vMAJOR.MINOR.PATCH tag, so it cannot be checked against the ${MIN_EMBEDDED_MIGRATE_TAG} floor. Releases are semver tags (see 'Cutting a release' in deploy/README.md). An image built before the embedded 'migrate' subcommand ignores the one-shots' 'migrate up' command and boots an API server that never exits, hanging this run with no error. Retag the release, or probe the image by hand and WATCH the output: 'docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file $ENV_FILE run --rm migrate migrate version' prints 'version=N dirty=false' on an image that has the subcommand, and starts an HTTP server you have to interrupt on one that does not" ;;
  esac
  die "$what=$tag is older than $MIN_EMBEDDED_MIGRATE_TAG, the first release whose image carries the embedded 'migrate' subcommand. docker-compose.prod.yml runs the migration one-shots from the SERVICE image with the command 'migrate up'; an older binary ignores those arguments and starts the API server instead, so the one-shot never exits and this run would HANG after the database has already been dropped and reloaded. Restore with $MIN_EMBEDDED_MIGRATE_TAG or newer pinned in $ENV_FILE. Going further back means also checking out that release's compose files, which drove the golang-migrate CLI container instead."
}

# env_get, is_true and the compose chain live in deploy/lib.sh — every script
# that addresses the running stack must assemble the SAME project. Sourced here,
# after log/die and ENV_FILE, which is the contract lib.sh documents.
# shellcheck source=deploy/lib.sh
. "$REPO_ROOT/deploy/lib.sh"

PGUSER="$(env_get POSTGRES_USER vidra)"
PGDB="$(env_get POSTGRES_DB vidra)"
HTTP_PORT="$(env_get HTTP_PORT 8080)"

# Before the confirmation prompt, and long before the drop: the two migrators run
# at the far end of this script, and a tag below the floor would hang there with
# the database already gone. These are the same pins the restored stack comes
# back up on, so gating them here also gates what `up -d` starts at the end.
require_embedded_migrate_tag VIDRA_CORE_TAG   "$(env_get VIDRA_CORE_TAG '')"
require_embedded_migrate_tag VIDRA_SEARCH_TAG "$(env_get VIDRA_SEARCH_TAG '')"

# Sets COMPOSE, EXTERNAL_POSTGRES and EXTERNAL_REDIS.
vidra_compose_chain

# This whole script is `docker exec` into the BUNDLED postgres container:
# dropdb, createdb, pg_restore. With VIDRA_EXTERNAL_POSTGRES=true that container
# does not exist, and every step below would fail one after another with
# container-not-found noise instead of one sentence. Refuse before the
# confirmation prompt, not after it. Restoring a managed database is the
# provider's job and deliberately NOT reimplemented here.
if [ "$EXTERNAL_POSTGRES" -eq 1 ]; then
  die "VIDRA_EXTERNAL_POSTGRES=true in $ENV_FILE — external Postgres: use your provider's backup/restore (point-in-time recovery or a snapshot), then bring the stack back with ./deploy/deploy.sh. This script only knows how to restore into the bundled postgres container, which docker-compose.external-postgres.yml keeps stopped. Nothing was changed."
fi

# docker-compose.prod.yml mounts deploy/Caddyfile.local — generated by
# `vidra setup`, gitignored, and NOT the committed deploy/Caddyfile template.
# The file must exist BEFORE `up -d`: a bind-mount source that is missing is
# created by Docker as an empty DIRECTORY, and Caddy then crash-loops on a
# config path that is not a file, i.e. the whole site is down with the app
# containers perfectly healthy. Refusing up front is the readable outcome.
#
# The dirty-template branch is the legacy-install case: a host set up before
# this layout has its real domain hand-edited into deploy/Caddyfile itself.
# Kept identical in deploy.sh, rollback.sh and restore.sh.
caddyfile_template_is_dirty() {
  command -v git >/dev/null 2>&1 || return 1
  git -C "$REPO_ROOT" rev-parse --git-dir >/dev/null 2>&1 || return 1
  [ -n "$(git -C "$REPO_ROOT" status --porcelain -- deploy/Caddyfile 2>/dev/null)" ]
}
require_caddyfile_local() {
  # An explicit `if`, not `[ -f … ] && return 0`: under `set -e` a failing
  # AND-list is itself a failing command and would kill the script here.
  if [ -f "$REPO_ROOT/deploy/Caddyfile.local" ]; then
    return 0
  fi
  if caddyfile_template_is_dirty; then
    die "deploy/Caddyfile.local is missing and deploy/Caddyfile has UNCOMMITTED edits — this looks like an install from before the managed-Caddy layout, with a real domain hand-written into the template. docker-compose.prod.yml now mounts deploy/Caddyfile.local only. Two ways forward:
  1. keep the hand edits verbatim:  cp deploy/Caddyfile deploy/Caddyfile.local
  2. regenerate from the template:  vidra setup
Option 1 changes nothing about how the site is served, which is what you want mid-incident."
  fi
  die "deploy/Caddyfile.local is missing. docker-compose.prod.yml mounts it (not the committed deploy/Caddyfile template) into the caddy container, and a missing bind-mount source is created as a DIRECTORY, which crash-loops Caddy. Generate it with 'vidra setup'."
}
require_caddyfile_local

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

# `|| die` on both branches, not just `set -e`. A tampered .gz dies inside gzip
# with "invalid compressed data--crc error" and NOTHING else: `set -e` kills the
# script silently, so the operator reads a CRC error and no line saying the
# restore refused or that the database was left alone (A37-4). The message is the
# whole point of the guard — the exit code was already right.
case "$DUMP" in
  *.gz)
    log "decompressing $(basename "$DUMP")"
    gzip -dc "$DUMP" > "$HOST_TMP" \
      || die "$(basename "$DUMP") could not be decompressed — the archive is truncated or corrupt (gzip's own message is above). Nothing was stopped and nothing was dropped; the stack is still serving. Try another copy of this backup, or an earlier one."
    ;;
  *)
    cp "$DUMP" "$HOST_TMP" \
      || die "$DUMP could not be read. Nothing was stopped and nothing was dropped; the stack is still serving."
    ;;
esac

log "copying archive into the postgres container"
docker cp "$HOST_TMP" "${PG_CID}:${CONTAINER_TMP}"

# Validate BEFORE dropping anything. A corrupt archive discovered after the drop
# leaves the instance with no database at all.
docker exec -i "$PG_CID" pg_restore -l "$CONTAINER_TMP" > /dev/null \
  || die "archive is not a readable custom-format dump — nothing was dropped"

# --- schema preflight: can the PINNED images reach this dump's schema? ---------
# THE FAILURE THIS CLOSES (A38 rehearsal, 2026-09-07, run 13). Everything below
# this point is irreversible: the database is dropped, the archive is reloaded,
# and only THEN are the two migrators run — from the images pinned in $ENV_FILE.
# Exactly one pairing works, a dump whose schema the pinned migrator can reach,
# and nothing checked it. With the tags already rewritten to the previous
# release (which rollback.sh does before it fails), this script dropped the
# database, reloaded it successfully, and died at "running core migrations" —
# leaving the site dark, `verify-blobs` and `up -d` never run, and nothing in
# the output explaining any of it.
#
# The dump's ledger is read OUT OF THE ARCHIVE, with no temporary database:
# `pg_restore --data-only -t <ledger>` prints that table's COPY block straight
# from the custom-format dump. The IMAGE is asked what it embeds rather than a
# checkout being read, because migrations are compiled into the release binaries
# and what matters is what the container that runs after the drop can do.
#
# It runs after the archive has been validated and copied in (both needed) and
# before the drop, so a refusal here means NOTHING happened.

# dump_ledger_row <table> — prints "<version> <dirty>" for the first row of that
# ledger in the archive, or nothing at all when the dump does not carry it (a
# database the service has never migrated). Never fails the script: an
# unreadable ledger is reported as "not checked", never as "checked and fine".
dump_ledger_row() {
  local table="$1"
  docker exec -i "$PG_CID" pg_restore --data-only -t "$table" -f - "$CONTAINER_TMP" 2>/dev/null \
    | awk -v t="$table" 'index($0, "COPY ") == 1 && index($0, t) > 0 { getline; print $1, $2; exit }' \
    || true
}

# image_embedded_max <service> — the newest migration compiled into that
# service's PINNED image, or nothing when the image cannot answer. `run --rm
# --no-deps` starts no database: `migrate embedded-max` reads the embedded
# migrations and never opens a connection. The image is pulled here if it is not
# on the host yet, which is the same pull `run --rm migrate` does after the drop
# — better to discover an unreachable registry now than then.
image_embedded_max() {
  local svc="$1"
  "${COMPOSE[@]}" run --rm --no-deps "$svc" migrate embedded-max 2>/dev/null \
    | tr -d '\r' | grep -xE '[0-9]+' | tail -1 || true
}

# preflight_schema <label> <compose service> <ledger table> <tag key>
preflight_schema() {
  local what="$1" svc="$2" table="$3" tagkey="$4"
  local tag row version dirty embedded
  tag="$(env_get "$tagkey" '(unset)')"

  row="$(dump_ledger_row "$table")"
  if [ -z "$row" ]; then
    log "${what}: the dump carries no ${table} ledger, so there is nothing to compare (a database this service has never migrated)."
    return 0
  fi
  version="${row%% *}"
  dirty="${row##* }"
  case "$version" in
    ''|*[!0-9]*)
      log "${what}: could not read a version out of the dump's ${table} ledger (got '${row}'). NOT CHECKED — this is not a statement that the pairing is fine."
      return 0
      ;;
  esac
  version="$((10#$version))"

  # A dirty ledger in the dump fails in the same place and the same way as an
  # unreachable version: both migrators refuse it, AFTER the drop. Same gate,
  # same override.
  if [ "$dirty" = "t" ] || [ "$dirty" = "true" ]; then
    if [ "$ALLOW_SCHEMA_MISMATCH" -ne 1 ]; then
      die "${what}: the dump's ${table} ledger is DIRTY at version ${version} — a migration was half-applied when it was taken, and both migrators refuse a dirty ledger. They run AFTER this script has dropped and reloaded the database, so restoring would leave you with the site down and a database whose schema nobody can vouch for. Restore an earlier, clean dump instead; or, if you have already worked out what that migration did, restore with --allow-schema-mismatch and repair the ledger by hand afterwards (see 'Migration failed mid-deploy' in deploy/README.md). Nothing was changed."
    fi
    log "${what}: WARNING — the dump's ${table} ledger is DIRTY at version ${version}; continuing because --allow-schema-mismatch was passed. Expect the migrator step below to refuse it."
  fi

  embedded="$(image_embedded_max "$svc")"
  if [ -z "$embedded" ]; then
    log "${what}: the pinned image (${tagkey}=${tag}) does not answer 'migrate embedded-max', so the dump's schema ${version} could NOT be checked against it. Every release cut before that subcommand existed lands here. Continuing — but if the migrator step below refuses the restored database, this pairing is the first thing to look at."
    return 0
  fi
  embedded="$((10#$embedded))"

  if [ "$version" -gt "$embedded" ]; then
    if [ "$ALLOW_SCHEMA_MISMATCH" -ne 1 ]; then
      die "${what}: the dump is at ${version}; pinned ${tagkey}=${tag} carries up to ${embedded}. The migrator runs AFTER the drop and the reload, and it cannot walk a ledger that is ahead of it, so this restore would end with the database replaced, the site down, and no way back from this script's output — this is exactly A38 run 13. Set ${tagkey} in ${ENV_FILE} to the release that carries schema ${version} (the release this dump was taken on), or pass --allow-schema-mismatch if you know better. Nothing was changed."
    fi
    log "${what}: WARNING — the dump is at ${version} and pinned ${tagkey}=${tag} carries up to ${embedded}; continuing because --allow-schema-mismatch was passed."
    return 0
  fi

  if [ "$version" -lt "$embedded" ]; then
    log "${what}: dump schema ${version}, pinned ${tagkey}=${tag} carries up to ${embedded} — the migrator step below will apply the difference. This is the documented forward path."
    return 0
  fi
  log "${what}: dump schema ${version} matches what ${tagkey}=${tag} carries — nothing to apply."
}

log "checking that the pinned images can reach this dump's schema"
preflight_schema "core"   migrate        schema_migrations       VIDRA_CORE_TAG
preflight_schema "search" search-migrate vidra_search_migrations VIDRA_SEARCH_TAG

# --- stop everything holding a connection --------------------------------------
# api is the obvious one. search is the easy one to forget: it shares this exact
# database in the `search` schema, so leaving it up means it reconnects into a
# half-restored database and logs errors for the whole restore. frontend goes
# too, so nobody sees a site backed by a database mid-restore.
#
# THIS RUNS AFTER EVERY VALIDATION, and that ordering is the point (A37-3). It
# used to be the first thing the script did, so a corrupt archive or a refused
# schema pairing took the site down and THEN correctly refused to change
# anything: the refusal was right and the outage in front of it was pure loss.
# Everything above this line only reads — the archive is decompressed, copied in,
# proved to be a readable custom-format dump, and checked against what the pinned
# images can migrate — so a refusal now means the stack never stopped serving.
# Everything below it is irreversible.
log "stopping api, search and frontend"
"${COMPOSE[@]}" stop api search frontend

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
#
# Each call passes NO command: the compose `command:` is `migrate up` on that
# service's own release image, whose migrations are compiled in (no CLI
# container, no bind-mounted migrations directory). `set -e` is the gate — a
# non-zero exit from either migrator aborts before api/frontend are started.
log "running core migrations"
"${COMPOSE[@]}" run --rm migrate
log "running search migrations"
"${COMPOSE[@]}" run --rm search-migrate

# --- blob-reference consistency ------------------------------------------------
# The dump was taken at time T; the object store is whatever it is at T+n. The
# two are only a matched pair if they were captured together, and they usually
# are not: media is backed up by the provider's versioning (S3) or by a separate
# volume snapshot (local), on its own schedule. A video deleted after the dump
# comes back as a row with no object, and nothing else in the system notices —
# the api simply 404s that one video, forever, and an operator finds out from a
# viewer.
#
# `verify-blobs` asks the store about every object the restored database
# references. It only ever READS: no repair mode, no deletes.
#
# It runs on the **api** service, not the migrate one-shot: the migrator is given
# DATABASE_URL and nothing else, and this needs the whole STORAGE_* set to know
# which bucket or directory to ask. Same image, same env file, same compose
# chain as every other call in this script.
#
# THIS NEVER BLOCKS THE RESTORE. `set -e` is deliberately suspended for the call
# (the `|| rc=$?` form), because a restore that aborted here would leave the site
# down over a media problem that not booting does not fix. Exit codes:
#   0  consistent
#   3  verified, and it is wrong  -> WARN and continue
#   1  could not verify at all    -> WARN and continue
# The two are kept apart on purpose: "the media is gone" and "I could not reach
# the bucket" send an operator to completely different places.
#
# --timeout is short here, unlike the command's own generous default: this is
# the fast existence-only pass, and a hung object store must not add an hour to
# a restore that is otherwise finished.
log "verifying that the restored database's media is present"
verify_rc=0
"${COMPOSE[@]}" run --rm api verify-blobs --timeout=10m || verify_rc=$?
case "$verify_rc" in
  0)
    log "media consistency: every object the restored database references is present"
    ;;
  3)
    cat >&2 <<EOF
[restore] ================================ WARNING ================================
[restore] MEDIA REFERENCED BY THE RESTORED DATABASE IS NOT ALL PRESENT.
[restore]
[restore] The restore itself SUCCEEDED and is continuing. This is about the object
[restore] store, not the database: rows point at media the store does not have.
[restore]
[restore] The usual causes, in order of likelihood:
[restore]   * the dump is OLDER than the media store, and the missing objects were
[restore]     deleted after it was taken — in which case the rows are stale, not the
[restore]     media, and the affected videos were already gone before this restore;
[restore]   * the media was restored SEPARATELY from a different point in time (an
[restore]     S3 bucket restore, a media_data volume snapshot) and has not caught up;
[restore]   * STORAGE_* points at a different bucket or directory than the one this
[restore]     database was written against. Check that FIRST — it is the one cause
[restore]     that is a configuration mistake rather than a data fact.
[restore]
[restore] The key list above names what is missing. Nothing was changed: this check
[restore] only reads.
[restore]
[restore] Next: once the stack is up, re-run it with content hashes, which also
[restore] detects media that is present but CORRUPT (it reads the whole library, so
[restore] give it a real timeout):
[restore]
[restore]   ${COMPOSE[*]} run --rm api verify-blobs --hash --deep --timeout=4h
[restore]
[restore] See "Backups & restore" in deploy/README.md and "Verifying media
[restore] consistency" in vidra-core/docs/operations.md.
[restore] =========================================================================
EOF
    ;;
  *)
    cat >&2 <<EOF
[restore] ================================ WARNING ================================
[restore] MEDIA CONSISTENCY COULD NOT BE VERIFIED (verify-blobs exited ${verify_rc}).
[restore]
[restore] The restore itself SUCCEEDED and is continuing. This is NOT a finding
[restore] about your media — it means the check could not be made at all: the
[restore] object store or the database was unreachable, the STORAGE_* configuration
[restore] is unusable, or the run timed out. The output above says which.
[restore]
[restore] Do not read this as "the media is fine". Re-run it by hand once the stack
[restore] is up:
[restore]
[restore]   ${COMPOSE[*]} run --rm api verify-blobs
[restore]
[restore] An image older than the release that added the subcommand refuses it as an
[restore] unknown subcommand and exits 1, which also lands here.
[restore]
[restore] See "Backups & restore" in deploy/README.md and "Verifying media
[restore] consistency" in vidra-core/docs/operations.md.
[restore] =========================================================================
EOF
    ;;
esac

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
