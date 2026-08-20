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
#
# It REFUSES a core/search tag below MIN_EMBEDDED_MIGRATE_TAG (set below): those
# images have no embedded `migrate` subcommand, so the two migrators run after the
# drop would boot API servers that never exit, hanging the restore with the
# database already replaced.

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
DUMP=""
while [ $# -gt 0 ]; do
  case "$1" in
    --yes|-y) FORCE=1 ;;
    -h|--help) sed -n '2,27p' "$0"; exit 0 ;;
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

# Before the confirmation prompt, and long before the drop: the two migrators run
# at the far end of this script, and a tag below the floor would hang there with
# the database already gone. These are the same pins the restored stack comes
# back up on, so gating them here also gates what `up -d` starts at the end.
require_embedded_migrate_tag VIDRA_CORE_TAG   "$(env_get VIDRA_CORE_TAG '')"
require_embedded_migrate_tag VIDRA_SEARCH_TAG "$(env_get VIDRA_SEARCH_TAG '')"

# The compose invocation, assembled from the env file rather than hardcoded so
# `vidra setup` can change the SHAPE of the stack (external datastores, extra
# profiles) without editing these scripts. Kept TEXTUALLY IDENTICAL in
# deploy.sh, rollback.sh, restore.sh and backup.sh: the four must address the
# same project, or `ps -q postgres` and `up -d` resolve against different
# renderings of it.
#
# An env file that predates these keys — or sets them empty — produces exactly
# the command line these scripts used before:
#   docker compose -f docker-compose.yml -f docker-compose.prod.yml \
#     --env-file "$ENV_FILE" --profile core --profile frontend
COMPOSE=(docker compose
  -f docker-compose.yml
  -f docker-compose.prod.yml)

# External/managed datastores. Each overlay parks the bundled service on a
# profile nothing enables and deletes every depends_on edge that named it —
# leaving one in place makes the whole project INVALID, not merely wasteful
# ("service search-migrate depends on undefined service postgres"). See the
# header of docker-compose.external-postgres.yml for the merge-tag reasoning.
#
# Both overlays MUST come after docker-compose.prod.yml (they build on its
# `!reset` tags and `${...:?}` assertions), and postgres before redis so every
# host renders the same chain. `is_true` rather than `= true` because operators
# type true/yes/1 interchangeably and a typo here silently starts a second,
# empty database next to the managed one.
is_true() {
  case "$1" in
    true|TRUE|True|yes|YES|Yes|1|on|ON|On) return 0 ;;
    *) return 1 ;;
  esac
}
EXTERNAL_POSTGRES=0
EXTERNAL_REDIS=0
if is_true "$(env_get VIDRA_EXTERNAL_POSTGRES false)"; then
  EXTERNAL_POSTGRES=1
  COMPOSE+=(-f docker-compose.external-postgres.yml)
fi
if is_true "$(env_get VIDRA_EXTERNAL_REDIS false)"; then
  EXTERNAL_REDIS=1
  COMPOSE+=(-f docker-compose.external-redis.yml)
fi

COMPOSE+=(--env-file "$ENV_FILE")

# Profiles: VIDRA_COMPOSE_PROFILES (default `core frontend` — exactly what these
# scripts hardcoded before) plus EXTRA_COMPOSE_PROFILES, which stays a separate
# key because `vidra setup` rewrites the first and the operator owns the second.
# Both are space-separated lists, so the command substitutions are deliberately
# unquoted. Duplicates are collapsed in first-seen order: passing --profile core
# twice changes nothing, but it makes two `ps` outputs annoying to compare.
seen_profiles=""
for profile in $(env_get VIDRA_COMPOSE_PROFILES "core frontend") $(env_get EXTRA_COMPOSE_PROFILES ""); do
  case " $seen_profiles " in
    *" $profile "*) continue ;;
  esac
  seen_profiles="$seen_profiles $profile"
  COMPOSE+=(--profile "$profile")
done

if [ "$EXTERNAL_POSTGRES" -eq 1 ] || [ "$EXTERNAL_REDIS" -eq 1 ]; then
  log "external datastores: postgres=${EXTERNAL_POSTGRES} redis=${EXTERNAL_REDIS} (the bundled service is disabled by its overlay)"
fi

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
#
# Each call passes NO command: the compose `command:` is `migrate up` on that
# service's own release image, whose migrations are compiled in (no CLI
# container, no bind-mounted migrations directory). `set -e` is the gate — a
# non-zero exit from either migrator aborts before api/frontend are started.
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
