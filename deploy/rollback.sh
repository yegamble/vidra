#!/usr/bin/env bash
#
# Roll the APPLICATION back to a previously released tag. 60 seconds, no schema
# change.
#
#   ./deploy/rollback.sh v0.1.0
#   ./deploy/rollback.sh --core v0.2.1 --user v0.2.0 --search v0.2.0
#
# Rewrites VIDRA_CORE_TAG / VIDRA_USER_TAG / VIDRA_SEARCH_TAG in the env file
# (keeping a .bak of the previous values), pulls, restarts and re-probes.
#
# WHAT THIS DOES NOT DO: it does not touch the database. That is deliberate and
# it is only safe because of the release policy stated in deploy/README.md —
# SCHEMA CHANGES STAY BACKWARD-COMPATIBLE FOR ONE RELEASE, so release N-1's code
# can always run against release N's schema. If you are rolling back ACROSS an
# incompatible schema change, this script is not enough:
#
#     docker compose ... stop api frontend
#     ./deploy/restore.sh backups/pre-deploy-<ts>.dump.gz
#     ./deploy/rollback.sh <previous-tag>
#
# Migrations are NOT re-run here: `migrate up` cannot walk backwards, and running
# it would simply re-apply the newer schema you are trying to leave.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

ENV_FILE="${ENV_FILE:-env/production.env}"
READY_TIMEOUT="${READY_TIMEOUT:-120}"

log() { printf '[rollback] %s\n' "$*"; }
die() { printf '[rollback] ERROR: %s\n' "$*" >&2; exit 1; }

CORE_TAG=""; USER_TAG=""; SEARCH_TAG=""
while [ $# -gt 0 ]; do
  case "$1" in
    --core)   CORE_TAG="${2:-}";   shift 2 ;;
    --user)   USER_TAG="${2:-}";   shift 2 ;;
    --search) SEARCH_TAG="${2:-}"; shift 2 ;;
    -h|--help) sed -n '2,22p' "$0"; exit 0 ;;
    -*) die "unknown option: $1" ;;
    *)  CORE_TAG="$1"; USER_TAG="$1"; SEARCH_TAG="$1"; shift ;;
  esac
done

[ -n "$CORE_TAG$USER_TAG$SEARCH_TAG" ] || die "usage: $0 <tag>  |  $0 [--core T] [--user T] [--search T]"
[ -f "$ENV_FILE" ] || die "env file not found: $ENV_FILE"

# The prod overlay closes Postgres/Redis/search with the `!reset` / `!override`
# merge tags, which need Compose >= 2.24. An older Compose does not error on
# them — it IGNORES them, sequence-merges the ports, and the `up -d` below would
# republish Postgres and Redis on 0.0.0.0. Refuse rather than warn.
# Kept identical in deploy.sh and restore.sh.
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
    die "docker compose $v is too old. docker-compose.prod.yml uses the !reset/!override merge tags (Compose >= 2.24); an older Compose silently ignores them and leaves Postgres and Redis published on 0.0.0.0. Upgrade the docker-compose-plugin / docker-compose-v2 package before rolling back."
  fi
}
require_compose_version

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

HTTP_PORT="$(env_get HTTP_PORT 8080)"
FRONTEND_PORT="$(env_get FRONTEND_PORT 3000)"

log "current: core=$(env_get VIDRA_CORE_TAG '(unset)') user=$(env_get VIDRA_USER_TAG '(unset)') search=$(env_get VIDRA_SEARCH_TAG '(unset)')"

# Rewrite in place via a temp file + mv rather than `sed -i`, whose syntax
# differs between GNU and BSD sed. Appends the key when it is not already
# present, so this also works on an env file that inherited its tags from the
# shell. The .bak is the only record of what you were running a minute ago.
cp "$ENV_FILE" "${ENV_FILE}.bak"
set_key() {
  local key="$1" val="$2" tmp
  [ -n "$val" ] || return 0
  tmp="$(mktemp)"
  if grep -qE "^[[:space:]]*${key}[[:space:]]*=" "$ENV_FILE"; then
    awk -v k="$key" -v v="$val" '
      $0 ~ "^[[:space:]]*" k "[[:space:]]*=" { print k "=" v; next }
      { print }
    ' "$ENV_FILE" > "$tmp"
  else
    cat "$ENV_FILE" > "$tmp"
    printf '%s=%s\n' "$key" "$val" >> "$tmp"
  fi
  cat "$tmp" > "$ENV_FILE"
  rm -f "$tmp"
  log "set ${key}=${val}"
}

set_key VIDRA_CORE_TAG   "$CORE_TAG"
set_key VIDRA_USER_TAG   "$USER_TAG"
set_key VIDRA_SEARCH_TAG "$SEARCH_TAG"

COMPOSE=(docker compose
  -f docker-compose.yml
  -f docker-compose.prod.yml
  --env-file "$ENV_FILE"
  --profile core --profile frontend)

"${COMPOSE[@]}" config -q || {
  log "compose config invalid after rewrite — restoring ${ENV_FILE} from .bak"
  cat "${ENV_FILE}.bak" > "$ENV_FILE"
  die "aborted; nothing was changed on the running stack"
}

log "pulling"
"${COMPOSE[@]}" pull || die "pull failed — does that tag exist in GHCR? ($ENV_FILE restored from ${ENV_FILE}.bak if you need to undo)"

log "restarting"
"${COMPOSE[@]}" up -d --no-build

probe() {
  local name="$1" url="$2" deadline
  deadline=$(( $(date +%s) + READY_TIMEOUT ))
  log "waiting up to ${READY_TIMEOUT}s for ${name} at ${url}"
  until curl -fsS -m 5 -o /dev/null "$url"; do
    if [ "$(date +%s)" -ge "$deadline" ]; then
      printf '[rollback] ERROR: %s never became healthy. Recent logs:\n' "$name" >&2
      "${COMPOSE[@]}" logs --tail=50 api frontend >&2 || true
      return 1
    fi
    sleep 3
  done
  log "${name} OK"
}

rc=0
probe "api /readyz" "http://127.0.0.1:${HTTP_PORT}/readyz" || rc=1
probe "frontend"    "http://127.0.0.1:${FRONTEND_PORT}/"   || rc=1

if [ "$rc" -ne 0 ]; then
  cat >&2 <<EOF

[rollback] THE ROLLBACK TARGET IS ALSO UNHEALTHY.
  If the newer release ran an incompatible migration, the old code cannot read
  the new schema — restore the pre-deploy dump before rolling back again:
      ./deploy/restore.sh backups/pre-deploy-<ts>.dump.gz
EOF
  exit 1
fi

log "rolled back to core=${CORE_TAG:-unchanged} user=${USER_TAG:-unchanged} search=${SEARCH_TAG:-unchanged}"
