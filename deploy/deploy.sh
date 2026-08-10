#!/usr/bin/env bash
#
# Deploy the pinned image tags from env/production.env to this host.
#
#   $EDITOR env/production.env          # bump VIDRA_CORE_TAG / _USER_TAG / _SEARCH_TAG
#   ./deploy/deploy.sh
#
# Ordering is the whole point of this script:
#
#   1. pre-deploy dump          — abort the deploy if it fails; this is the only
#                                 escape hatch for a migration that goes wrong
#   2. pull                     — fetch the images BEFORE stopping anything, so a
#                                 registry outage costs zero downtime
#   3. migrate, then            — each as a DISCRETE, exit-code-gated step. Never
#      search-migrate             let `up -d` fan them out: a migration failure
#                                 would then race the api's start and you would
#                                 be debugging a half-started stack instead of
#                                 reading one error
#   4. up -d --no-build         — the images are already local; nothing compiles
#                                 on the droplet
#   5. probe /readyz + frontend — and exit non-zero if either never comes up, so
#                                 CI/cron/the operator's shell notices
#
# Idempotent: re-running with the same tags is a no-op apart from a fresh dump.
#
# It does NOT `git pull`. Update the meta-repo checkout yourself first (compose
# files + Caddyfile), so you always know exactly which change you are shipping.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

ENV_FILE="${ENV_FILE:-env/production.env}"
BACKUP_DIR="${BACKUP_DIR:-$REPO_ROOT/backups}"
READY_TIMEOUT="${READY_TIMEOUT:-120}"
# How many pre-deploy dumps to keep. These are separate from backup.sh's nightly
# family and are pruned by count, because their cadence is "however often you
# deploy" rather than daily.
PREDEPLOY_KEEP="${PREDEPLOY_KEEP:-10}"

log()  { printf '[deploy] %s\n' "$*"; }
die()  { printf '[deploy] ERROR: %s\n' "$*" >&2; exit 1; }
step() { printf '\n[deploy] ===== %s =====\n' "$*"; }

[ -f "$ENV_FILE" ] || die "env file not found: $ENV_FILE (cp env/production.env.example env/production.env)"

# The prod overlay closes Postgres/Redis/search with the `!reset` / `!override`
# merge tags, which need Compose >= 2.24. An older Compose does not error on
# them — it IGNORES them, sequence-merges the ports, and the deploy "succeeds"
# with Postgres and Redis published on 0.0.0.0. Refuse rather than warn.
# Kept identical in rollback.sh and restore.sh.
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
    die "docker compose $v is too old. docker-compose.prod.yml uses the !reset/!override merge tags (Compose >= 2.24); an older Compose silently ignores them and leaves Postgres and Redis published on 0.0.0.0. Upgrade the docker-compose-plugin / docker-compose-v2 package before deploying."
  fi
}

# Caddy provisions a Let's Encrypt certificate for every hostname in a site
# block, so an unedited deploy/Caddyfile means a failed ACME order and a site
# that serves nothing over TLS. Only NON-comment lines are checked: the file's
# explanatory comments and its commented-out split-subdomain variant mention
# example.com on purpose and must not trip this forever.
#
# DELIBERATELY NOT in rollback.sh or restore.sh, unlike require_compose_version
# above. Those two run during an incident, and refusing an emergency rollback
# over a cosmetic file check would be the wrong trade. A first deploy is the only
# moment the Caddyfile can still be unedited anyway.
#
# The match is anchored on the left so a real domain that merely ENDS in the
# placeholder (myexample.com) is not refused, while a subdomain OF it
# (sub.example.com) still is — '.' is intentionally absent from the excluded
# character class for exactly that reason.
require_real_domain() {
  local f="$REPO_ROOT/deploy/Caddyfile"
  [ -f "$f" ] || return 0
  if grep -vE '^[[:space:]]*#' "$f" | grep -qE '(^|[^A-Za-z0-9-])example\.com'; then
    die "deploy/Caddyfile still contains the placeholder domain example.com — replace it with your real domain (comments may keep it). Caddy would order a certificate for example.com and fail."
  fi
}

# See backup.sh: read, never source, an operator-edited secrets file.
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
FRONTEND_PORT="$(env_get FRONTEND_PORT 3000)"

COMPOSE=(docker compose
  -f docker-compose.yml
  -f docker-compose.prod.yml
  --env-file "$ENV_FILE"
  --profile core --profile frontend)

# Optional extra compose profiles from the env file (space-separated), e.g.
# EXTRA_COMPOSE_PROFILES=ipfs — kept in the env file so a profile enabled once
# stays enabled on every subsequent deploy instead of relying on operator memory.
for extra_profile in $(env_get EXTRA_COMPOSE_PROFILES ""); do
  COMPOSE+=(--profile "$extra_profile")
done

step "0/5 pre-flight"
require_compose_version
require_real_domain
log "compose $(docker compose version --short), deploy/Caddyfile has a real domain"

for repo in vidra-core vidra-search vidra-user; do
  [ -e "$repo" ] || continue
  [ -d "$repo/.git" ] || die "$repo exists but is not a git checkout"
  case "$repo" in
    vidra-core)   tag="$(env_get VIDRA_CORE_TAG '?')" ;;
    vidra-search) tag="$(env_get VIDRA_SEARCH_TAG '?')" ;;
    vidra-user)   tag="$(env_get VIDRA_USER_TAG '?')" ;;
  esac
  [ "$tag" != "?" ] || continue
  log "syncing $repo to $tag"
  git -C "$repo" fetch --tags --quiet || die "git fetch failed in $repo"
  git -C "$repo" checkout --detach --quiet "$tag" || die "failed to checkout tag $tag in $repo"
done

# The render check catches every `${VAR:?}` reference in the chain BEFORE
# anything is touched. Those are, exhaustively: JWT_SECRET (asserted by
# docker-compose.prod.yml's api environment), REDIS_PASSWORD (asserted by the
# redis command, its healthcheck, and both REDIS_URL rewrites) and the three
# VIDRA_*_TAG image tags. `:?` fails on an EMPTY value as well as an unset one,
# which is what makes it catch the shipped `JWT_SECRET=` blank in an env file
# that was copied but never edited.
"${COMPOSE[@]}" config -q || die "compose config is invalid — fix $ENV_FILE and retry"
log "tags: core=$(env_get VIDRA_CORE_TAG '?') user=$(env_get VIDRA_USER_TAG '?') search=$(env_get VIDRA_SEARCH_TAG '?')"

step "1/5 pre-deploy database dump"
mkdir -p "$BACKUP_DIR"
PG_CID="$("${COMPOSE[@]}" ps -q postgres || true)"
if [ -z "$PG_CID" ]; then
  # First deploy on a fresh host: there is no database to dump yet. Any other
  # time, a stopped postgres means something is already wrong — do not deploy
  # on top of it blind.
  if "${COMPOSE[@]}" ps -aq postgres | grep -q .; then
    die "postgres exists but is not running — start it and retry, or investigate before deploying"
  fi
  log "no postgres container yet (first deploy on this host) — skipping pre-deploy dump"
else
  DUMP="$BACKUP_DIR/pre-deploy-$(date -u +%FT%H%M%S).dump.gz"
  # `set -e` + pipefail: a failed pg_dump aborts the deploy here, which is the
  # single most important line in this file.
  docker exec -i "$PG_CID" pg_dump -U "$PGUSER" -Fc "$PGDB" | gzip -c > "${DUMP}.part"
  gzip -dc "${DUMP}.part" | docker exec -i "$PG_CID" pg_restore -l > /dev/null \
    || die "pre-deploy dump failed its integrity check — NOT deploying"
  mv "${DUMP}.part" "$DUMP"
  log "wrote $DUMP ($(du -h "$DUMP" | cut -f1))"

  # Prune by count, newest first.
  # shellcheck disable=SC2012  # ls is deliberate: these names are generated a few
  # lines above (pre-deploy-<UTC stamp>.dump.gz), so `sort -r` on them is exactly
  # reverse-chronological without needing GNU find's -printf.
  ls -1 "$BACKUP_DIR"/pre-deploy-*.dump.gz 2>/dev/null | sort -r | tail -n "+$((PREDEPLOY_KEEP + 1))" \
    | while IFS= read -r old; do log "pruning $(basename "$old")"; rm -f -- "$old"; done
fi

step "2/5 pull images"
"${COMPOSE[@]}" pull || die "pull failed — the tags in $ENV_FILE may not exist in GHCR yet, or the host needs 'docker login ghcr.io'"

step "3/5 migrations"
# Two separate ledgers, two separate gates. The search migrator writes
# vidra_search_migrations; core writes schema_migrations. Either can go dirty
# independently — see "Migration failed mid-deploy" in deploy/README.md.
log "core schema (schema_migrations)"
# `|| mrc=$?` rather than `if ! ...` so the real migrator exit code survives
# (inside `if ! cmd`, $? is the status of the negation, i.e. always 0).
mrc=0; "${COMPOSE[@]}" run --rm migrate || mrc=$?
[ "$mrc" -eq 0 ] || die "CORE MIGRATION FAILED (exit $mrc). The stack has NOT been restarted; the previous release is still serving. See 'Migration failed mid-deploy' in deploy/README.md."

PG_CID="$("${COMPOSE[@]}" ps -q postgres || true)"
[ -n "$PG_CID" ] || die "postgres container missing during migration verification"
expected_version="$(ls -1 vidra-core/migrations/*.up.sql 2>/dev/null | awk -F/ '{print $NF}' | awk -F_ '{print $1}' | sort -n | tail -1)"
[ -n "$expected_version" ] || die "failed to determine expected core migration version"
expected_version_int="$((10#$expected_version))"

ledger="$(docker exec -i "$PG_CID" psql -U "$PGUSER" -d "$PGDB" -t -c "SELECT version, dirty FROM schema_migrations LIMIT 1;" 2>/dev/null | tr -d ' ')"
[ -n "$ledger" ] || die "could not read schema_migrations ledger"
db_version="${ledger%|*}"
db_dirty="${ledger#*|}"

if [ "$db_dirty" = "t" ] || [ "$db_dirty" = "true" ]; then
  die "schema_migrations is DIRTY after migrate step. See 'Migration failed mid-deploy' in deploy/README.md."
fi
if [ "$db_version" != "$expected_version_int" ]; then
  die "schema_migrations version mismatch: expected $expected_version_int, found $db_version. The stack has NOT been restarted."
fi
log "core schema OK (version $db_version)"

log "search schema (vidra_search_migrations)"
src=0; "${COMPOSE[@]}" run --rm search-migrate || src=$?
[ "$src" -eq 0 ] || die "SEARCH MIGRATION FAILED (exit $src). The stack has NOT been restarted; the previous release is still serving. See 'Migration failed mid-deploy' in deploy/README.md."

step "4/5 start"
# --no-build is a guarantee, not an optimisation: the base compose file still
# carries the dev `build:` sections, and a droplet that starts compiling Go or
# running `next build` will run out of memory rather than deploy.
"${COMPOSE[@]}" up -d --no-build

step "5/5 health probes"
probe() {
  local name="$1" url="$2" deadline
  deadline=$(( $(date +%s) + READY_TIMEOUT ))
  log "waiting up to ${READY_TIMEOUT}s for ${name} at ${url}"
  until curl -fsS -m 5 -o /dev/null "$url"; do
    if [ "$(date +%s)" -ge "$deadline" ]; then
      printf '[deploy] ERROR: %s never became healthy. Recent logs:\n' "$name" >&2
      "${COMPOSE[@]}" logs --tail=50 api frontend >&2 || true
      return 1
    fi
    sleep 3
  done
  log "${name} OK"
}

rc=0
probe "api /readyz"  "http://127.0.0.1:${HTTP_PORT}/readyz" || rc=1
probe "frontend"     "http://127.0.0.1:${FRONTEND_PORT}/"   || rc=1

if [ "$rc" -ne 0 ]; then
  cat >&2 <<EOF

[deploy] DEPLOY FAILED HEALTH CHECKS.
  Roll the application back with:   ./deploy/rollback.sh <previous-tag>
  If the failure is a schema change, restore the pre-deploy dump first:
      ./deploy/restore.sh ${DUMP:-backups/pre-deploy-<ts>.dump.gz}
EOF
  exit 1
fi

log "deploy complete"
