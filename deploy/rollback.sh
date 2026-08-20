#!/usr/bin/env bash
#
# Roll the APPLICATION back to a previously released tag. 60 seconds, no schema
# change.
#
#   ./deploy/rollback.sh v0.2.0
#   ./deploy/rollback.sh --core v0.2.1 --user v0.2.0 --search v0.2.0
#
# Rewrites VIDRA_CORE_TAG / VIDRA_USER_TAG / VIDRA_SEARCH_TAG in the env file
# (keeping a .bak of the previous values), pulls, restarts and re-probes.
#
# It REFUSES a core/search tag below MIN_EMBEDDED_MIGRATE_TAG (set below): those
# images have no embedded `migrate` subcommand, so the migration one-shots `up -d`
# depends on would boot API servers that never exit, and the rollback would hang.
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

# The FIRST release whose vidra-core / vidra-search images carry the embedded
# `migrate` subcommand. ADJUST THIS AT RELEASE TIME — set it to the tag actually
# cut with the embedded migrator, and never lower it afterwards.
#
# WHY IT IS A HARD GATE, HERE OF ALL PLACES: this script does not run migrations,
# but `up -d` below still STARTS both one-shots — the api and search services
# depend on them with `condition: service_completed_successfully`. Their compose
# command is `migrate up` on the service image, and an OLDER image's main()
# ignores argv completely and starts the API SERVER instead. The one-shot then
# never exits, so the rollback hangs with the broken release still serving,
# instead of failing fast. Refusing the tag is the readable outcome.
# Kept identical in deploy.sh and restore.sh.
MIN_EMBEDDED_MIGRATE_TAG="v0.2.0"

log() { printf '[rollback] %s\n' "$*"; }
die() { printf '[rollback] ERROR: %s\n' "$*" >&2; exit 1; }

CORE_TAG=""; USER_TAG=""; SEARCH_TAG=""
while [ $# -gt 0 ]; do
  case "$1" in
    --core)   CORE_TAG="${2:-}";   shift 2 ;;
    --user)   USER_TAG="${2:-}";   shift 2 ;;
    --search) SEARCH_TAG="${2:-}"; shift 2 ;;
    -h|--help) sed -n '2,27p' "$0"; exit 0 ;;
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

# semver_ge <tag> <floor> — numeric MAJOR.MINOR.PATCH comparison of two vX.Y.Z
# tags. Exit 0 when <tag> >= <floor>, 1 when it is older, and 2 when <tag> is not
# semver-shaped at all (so the caller can say "cannot check" instead of guessing).
# A prerelease/build suffix is ignored on purpose: v0.2.0-rc1 is built from the
# v0.2.0 code and carries the same migrator, so it counts as v0.2.0 here.
# Kept identical in deploy.sh and restore.sh.
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
# MIN_EMBEDDED_MIGRATE_TAG above for what such an image does to a rollback.
# An empty tag is left alone: `rollback.sh --user vX` legitimately leaves the two
# migrator tags untouched, and an unset one is reported by the render check.
# Kept identical in deploy.sh and restore.sh, apart from the closing sentence of
# the final message, which names the operation each one would have hung.
require_embedded_migrate_tag() {
  local what="$1" tag="$2" rc=0
  [ -n "$tag" ] || return 0
  semver_ge "$tag" "$MIN_EMBEDDED_MIGRATE_TAG" || rc=$?
  case "$rc" in
    0) return 0 ;;
    2) die "$what=$tag is not a vMAJOR.MINOR.PATCH tag, so it cannot be checked against the ${MIN_EMBEDDED_MIGRATE_TAG} floor. Releases are semver tags (see 'Cutting a release' in deploy/README.md). An image built before the embedded 'migrate' subcommand ignores the one-shots' 'migrate up' command and boots an API server that never exits, hanging this run with no error. Retag the release, or probe the image by hand and WATCH the output: 'docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file $ENV_FILE run --rm migrate migrate version' prints 'version=N dirty=false' on an image that has the subcommand, and starts an HTTP server you have to interrupt on one that does not" ;;
  esac
  die "$what=$tag is older than $MIN_EMBEDDED_MIGRATE_TAG, the first release whose image carries the embedded 'migrate' subcommand. docker-compose.prod.yml runs the migration one-shots from the SERVICE image with the command 'migrate up'; an older binary ignores those arguments and starts the API server instead, so the one-shot never exits and this run would HANG (on the api/search service_completed_successfully edges during 'up -d') rather than fail. Roll back to $MIN_EMBEDDED_MIGRATE_TAG or newer. Going further back means also checking out that release's compose files, which drove the golang-migrate CLI container instead."
}

# Gate the two migrator tags BEFORE the env file is rewritten, so a refusal
# leaves the running stack and $ENV_FILE exactly as they were. vidra-user has no
# migrator, so --user is not gated.
require_embedded_migrate_tag VIDRA_CORE_TAG   "$CORE_TAG"
require_embedded_migrate_tag VIDRA_SEARCH_TAG "$SEARCH_TAG"

# env_get, is_true and the compose chain live in deploy/lib.sh — every script
# that addresses the running stack must assemble the SAME project. Sourced here,
# after log/die and ENV_FILE, which is the contract lib.sh documents.
# shellcheck source=deploy/lib.sh
. "$REPO_ROOT/deploy/lib.sh"

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
  # --force: a tag re-pointed upstream is otherwise refused and the checkout
  # pins the stale object. Kept identical in deploy.sh.
  git -C "$repo" fetch --tags --force --quiet || die "git fetch failed in $repo"
  git -C "$repo" checkout --detach --quiet "$tag" || die "failed to checkout tag $tag in $repo"
done

# Sets COMPOSE, EXTERNAL_POSTGRES and EXTERNAL_REDIS.
vidra_compose_chain

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
