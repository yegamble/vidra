#!/usr/bin/env bash
#
# Roll the APPLICATION back to a previously released tag. 60 seconds, no schema
# change.
#
#   ./deploy/rollback.sh v0.2.0
#   ./deploy/rollback.sh --core v0.2.1 --user v0.2.0 --search v0.2.0
#   ./deploy/rollback.sh v0.7.7 --remap-internal-to-private
#
# The bare form pins the pairing releases/<tag>.json records (v0.7.5 is core
# v0.7.5 with user and search at v0.7.3); with no record, <tag> for all three.
# A flag overrides its component either way.
#
# Rewrites VIDRA_CORE_TAG / VIDRA_USER_TAG / VIDRA_SEARCH_TAG in the env file
# (snapshotting it outside the checkout first), pulls, restarts and re-probes.
#
# It REFUSES a core/search tag below MIN_EMBEDDED_MIGRATE_TAG (set below): those
# images have no embedded `migrate` subcommand, so the migration one-shots `up -d`
# depends on would boot API servers that never exit, and the rollback would hang.
# Before the env file is touched it also holds the target triple against
# releases/<tag>.json. A digest that contradicts a record, or an unreadable
# record, stops it. A triple no record pairs, such as a single --user, continues
# with a WARNING naming what was not verified.
#
# It also REFUSES an app-only rollback that would run a core release unaware of
# a privacy tier present in the data: a target core whose release records do
# not show the vidra-core migration that adds the 'internal' video privacy tier
# (INTERNAL_PRIVACY_MIGRATION) while the database holds videos at 'internal'.
# That check is one bounded, read-only SELECT, and a check that cannot be made
# refuses too. Two flags, both explicit:
#   --remap-internal-to-private     remap those videos to 'private' (the UPDATE
#                                   in 0160's down migration) just before the
#                                   restart, record their ids under backups/,
#                                   and proceed
#   --allow-unchecked-privacy-tier  proceed when the check could NOT be made
#                                   (or the target could not be placed), on
#                                   your word, after checking by hand
#
# It likewise REFUSES an app-only rollback below WORD_LISTS_MIGRATION while the
# database holds any per-account watched-word list or any list whose action is
# 'hold' (see the word-lists gate). Old code ignores both: it would match a
# creator's PRIVATE terms into the staff review queue and publish comments a
# 'hold' list was holding. A check that cannot be made refuses too, unless
# --allow-unchecked-word-lists.
#
# And it REFUSES an app-only rollback below OIDC_PROVIDERS_MIGRATION while
# oidc_providers holds any row: admin-managed providers can OVERRIDE or DISABLE
# the environment-configured ones (stricter domain allow-lists, disabled). Old
# code ignores the table, so the environment providers come back WITHOUT those
# restrictions. An empty table only WARNS (nothing to lose). A check that cannot
# be made refuses too. Both are overridden by --allow-oidc-env-fallback, after
# you have reviewed or disabled the environment providers (OAUTH_PROVIDERS).
#
# WHAT THIS DOES NOT DO: it does not touch the database (the one exception is
# the remap above, which runs only when asked for by name). That is deliberate and
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
#
# But `up -d` below DOES start both migration one-shots — api and search depend
# on them with service_completed_successfully — so the release you roll back to
# still has to survive meeting a newer ledger. Since A38 (2026-09-07) it does: a
# migrator whose newest embedded migration is below a CLEAN ledger logs
# "schema version N is newer than this binary's newest migration M; nothing to
# apply" and exits 0. Rolling back to a release cut BEFORE that fix exits 1 there
# instead, and nothing that depends on the one-shot starts — the failure this
# script now names for you rather than dying silently on.

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

# The vidra-core migration that adds the 'internal' video privacy tier,
# IDENTIFIED BY ITS FILE NAME. It MUST match vidra-core's
# migrations/<this file> exactly: if vidra-core renumbers or renames it before
# it merges, change this line and nothing else. A core release whose release
# record does not list this file does not know the tier; see the privacy-tier
# gate below. A file name, because a number would identify nothing: several
# core PRs held neighbouring numbers at once, and a release can pass 0160
# without this migration. Not a release tag either, so cutting the release
# that ships it needs no edit here. A stale value fails toward checking: the
# records then never list it, and every rollback asks the database.
INTERNAL_PRIVACY_MIGRATION="0160_video_privacy_internal.up.sql"

# The vidra-core migration that adds named watched-word lists (per-account lists
# and the 'hold' action), IDENTIFIED BY ITS FILE NAME for the same reasons as
# INTERNAL_PRIVACY_MIGRATION above; see the word-lists gate below.
WORD_LISTS_MIGRATION="0172_watched_word_lists.up.sql"

# The vidra-core migration that adds admin-managed OIDC providers
# (oidc_providers), IDENTIFIED BY ITS FILE NAME for the same reasons as above;
# see the OIDC-providers gate below.
OIDC_PROVIDERS_MIGRATION="0182_oidc_providers.up.sql"

log() { printf '[rollback] %s\n' "$*"; }
die() { printf '[rollback] ERROR: %s\n' "$*" >&2; exit 1; }

CORE_TAG=""; USER_TAG=""; SEARCH_TAG=""; BARE_TAG=""
REMAP_INTERNAL=0; ALLOW_UNCHECKED_PRIVACY=0; ALLOW_UNCHECKED_WORD_LISTS=0
ALLOW_OIDC_ENV_FALLBACK=0
while [ $# -gt 0 ]; do
  case "$1" in
    --core)   CORE_TAG="${2:-}";   shift 2 ;;
    --user)   USER_TAG="${2:-}";   shift 2 ;;
    --search) SEARCH_TAG="${2:-}"; shift 2 ;;
    --remap-internal-to-private)    REMAP_INTERNAL=1;          shift ;;
    --allow-unchecked-privacy-tier) ALLOW_UNCHECKED_PRIVACY=1; shift ;;
    --allow-unchecked-word-lists)   ALLOW_UNCHECKED_WORD_LISTS=1; shift ;;
    --allow-oidc-env-fallback)      ALLOW_OIDC_ENV_FALLBACK=1; shift ;;
    -h|--help) sed -n '2,60p' "$0"; exit 0 ;;
    -*) die "unknown option: $1" ;;
    *)  BARE_TAG="$1"; shift ;;
  esac
done

[ -n "$BARE_TAG$CORE_TAG$USER_TAG$SEARCH_TAG" ] || die "usage: $0 <tag>  |  $0 [--core T] [--user T] [--search T]   [--remap-internal-to-private] [--allow-unchecked-privacy-tier] [--allow-unchecked-word-lists] [--allow-oidc-env-fallback]"
[ -f "$ENV_FILE" ] || die "env file not found: $ENV_FILE"

# THE BARE TAG'S PAIRING. v0.7.4 and v0.7.5 re-released vidra-core alone, so
# writing <tag> into all three keys pinned ghcr.io/yegamble/vidra-user:v0.7.5,
# which has never existed: the rollback died at `compose pull` with the broken
# release still serving — and `rollback.sh v0.7.5` is the command an operator
# types to leave a broken v0.7.7. The record is read by the SAME resolver pin-release.sh
# uses (deploy/release-mapping.py resolve), so there is one reader of records.
#
# Only this tree's copy is read, never a fetch: a rollback targets an OLDER
# release, whose record a newer tree already carries, and a network wait
# mid-incident buys nothing. Flags are applied AFTER, not passed to the
# resolver as --component-tag: an operator's explicit flag mid-incident wins
# over a record, and is logged as overriding it. Every answer other than "a
# record decided it" falls back to the uniform triple this script always wrote
# — the release-mapping preflight below then WARNS that it was not verified —
# because refusing here predicts nothing the pull does not already catch, and
# a failed pull restores the env file.
resolve_bare_tag() {
  local record="$REPO_ROOT/releases/${BARE_TAG}.json" resolved='' rc=0 role value _
  local core="$BARE_TAG" user="$BARE_TAG" search="$BARE_TAG"
  if [ -f "$record" ] && command -v python3 >/dev/null 2>&1; then
    resolved="$(python3 "$REPO_ROOT/deploy/release-mapping.py" resolve \
      --release "$BARE_TAG" --record "$record")" || rc=$?
    if [ "$rc" -eq 0 ]; then
      # A here-document, not a pipe: `while read` in a pipeline runs in a
      # subshell and the assignments would be gone by the next line.
      while read -r role value _; do
        case "$role" in
          core) core="$value" ;; user) user="$value" ;; search) search="$value" ;;
        esac
      done <<EOF
$resolved
EOF
      log "releases/${BARE_TAG}.json pairs core=${core} user=${user} search=${search}"
    else
      log "WARNING: deploy/release-mapping.py could not resolve releases/${BARE_TAG}.json (exit ${rc}); using ${BARE_TAG} for every component no flag names"
    fi
  fi
  # `if`, not `[ ] || log`: the last command's status is the function's, and a
  # false test there would fire errexit at the call site.
  if [ -n "$CORE_TAG" ] && [ "$CORE_TAG" != "$core" ]; then log "--core ${CORE_TAG} overrides core=${core}"; fi
  if [ -n "$USER_TAG" ] && [ "$USER_TAG" != "$user" ]; then log "--user ${USER_TAG} overrides user=${user}"; fi
  if [ -n "$SEARCH_TAG" ] && [ "$SEARCH_TAG" != "$search" ]; then log "--search ${SEARCH_TAG} overrides search=${search}"; fi
  CORE_TAG="${CORE_TAG:-$core}"
  USER_TAG="${USER_TAG:-$user}"
  SEARCH_TAG="${SEARCH_TAG:-$search}"
}
if [ -n "$BARE_TAG" ]; then
  resolve_bare_tag
fi

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
#
# A core/search DIGEST PIN (`--core v0.6.4@sha256:...`) dies HERE: semver_ge
# cannot parse it, so it never reaches the release-mapping digest comparison
# below. Deliberate for now: on a git tree deploy.sh's checkout sync would run
# `git checkout "v0.6.4@sha256:..."` on the same pin. Only --user reaches the
# digest comparison.
require_embedded_migrate_tag VIDRA_CORE_TAG   "$CORE_TAG"
require_embedded_migrate_tag VIDRA_SEARCH_TAG "$SEARCH_TAG"

# env_get, is_true and the compose chain live in deploy/lib.sh — every script
# that addresses the running stack must assemble the SAME project. Sourced here,
# after log/die and ENV_FILE, which is the contract lib.sh documents.
#
# MOVED ABOVE THE CADDYFILE GATE (it used to sit below it) because that gate now
# has to know the TLS mode, and reading a key out of the env file is env_get's
# job. Sourcing only defines functions and reads nothing, so its position
# relative to the gates changes no behaviour — the ORDER OF THE GATES is what
# matters here, and it is unchanged.
# shellcheck source=deploy/lib.sh
. "$REPO_ROOT/deploy/lib.sh"
command -v python3 >/dev/null 2>&1 || die "Python 3 is required for checkout preflight; install python3 before deploying"
# --env-backups warn, and ONLY here. A rollback runs mid-incident and commits
# nothing, so a file whose NAME looks like an env backup cannot affect it —
# refusing on one would mean a hygiene lint decides how long the outage lasts.
# It is still printed, loudly, so the finding is not lost. Metadata ownership
# stays fatal: the component fetch below genuinely cannot write such a tree,
# and failing here beats failing after the tag pins have been rewritten. Same
# reasoning as the bundle branch further down — see its comment.
python3 "$REPO_ROOT/deploy/checkout-hygiene.py" check "$REPO_ROOT" --env-backups warn || die "checkout hygiene preflight failed"

# Same key, same default as deploy/lib.sh's edge_profile() and deploy.sh's
# pre-flight. `external` means the operator's own proxy terminates TLS and this
# project therefore contains no caddy service at all.
TLS_MODE="$(env_get VIDRA_TLS_MODE acme)"

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
#
# CHECKED HERE, WITH THE TAG GATES, AND NOT DOWN AT `up -d`: this gate reads a
# path and nothing else — it does not depend on a single value the rewrite below
# changes — so the only thing its old position bought was a refusal that had
# ALREADY overwritten the env-file history. A legacy host (no Caddyfile.local)
# that ran two rollbacks lost the tags it started the incident on to a script
# that never got as far as pulling an image.
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
# Skipped, LOUDLY, for the one mode that has no caddy service to mount it into.
# The three copies of the function itself stay byte-identical across deploy.sh,
# rollback.sh and restore.sh — the mode decision lives at the call site precisely
# so that hand-synced trio does not fork.
if [ "$TLS_MODE" = "external" ]; then
  log "VIDRA_TLS_MODE=external — your proxy terminates TLS and this project has no caddy service (deploy/lib.sh withholds the 'edge' profile), so deploy/Caddyfile.local is not needed and was NOT checked."
else
  require_caddyfile_local
fi

# THE RELEASE MAPPING, on the TARGET triple (a flag not given keeps the tag
# being served), BEFORE the env snapshot and rewrite below, so a stop leaves
# $ENV_FILE and the running stack exactly as they were.
#
# Severity follows what each finding predicts for a ROLLBACK (see the header of
# deploy/release-mapping.py). A digest that contradicts a record that loaded, or
# an unparseable target tag (this script would write it into $ENV_FILE), stops
# it. A triple no record pairs is a WARNING that names what was not verified,
# not a refusal: the single-component rollback in this script's usage is
# exactly such a triple, and refusing it mid-incident would predict nothing
# about whether the rollback works. A tag that does not exist still fails the
# pull below, which restores the env file. So is a releases/ directory that
# cannot be used (missing, or a corrupt record for some OTHER release): it says
# nothing about the target's images, so the run continues with a WARNING that
# NOTHING about the target was verified. The bundle manifest is not compared
# either: a bundle host rolls back under the newer bundle on purpose.
# VIDRA_RELEASE_MAPPING=warn changes nothing here; an unpaired triple already
# warns.
#
# `declare -F` first: a tree whose lib.sh predates this function (a released
# bundle with only rollback.sh replaced) would otherwise exit 127 with a message
# blaming the tags.
declare -F release_mapping_check >/dev/null \
  || die "deploy/lib.sh does not define release_mapping_check, so it is from an older revision than this rollback.sh. Nothing was changed. Take deploy/lib.sh, deploy/release-mapping.py and releases/ from the same revision as this script."
release_mapping_check "$REPO_ROOT" rollback \
  "${CORE_TAG:-$(env_get VIDRA_CORE_TAG '')}" \
  "${USER_TAG:-$(env_get VIDRA_USER_TAG '')}" \
  "${SEARCH_TAG:-$(env_get VIDRA_SEARCH_TAG '')}" \
  || die "the release mapping preflight stopped this rollback (findings above). $ENV_FILE was NOT rewritten and nothing was pulled or restarted; the release you are serving is untouched."

# Sets COMPOSE, EXTERNAL_POSTGRES and EXTERNAL_REDIS. It used to be called just
# before `config -q` below; it moved up because the privacy-tier gate has to
# reach the database BEFORE the env file is rewritten. Moving it changes no
# command: it reads only the datastore and profile keys, which the tag rewrite
# does not touch, and every compose call it builds reads the tags out of
# $ENV_FILE when it runs, i.e. after the rewrite exactly as before.
vidra_compose_chain

# THE PRIVACY-TIER GATE, on the TARGET core, BEFORE the env snapshot and
# rewrite below, so a refusal — like every gate above — leaves $ENV_FILE and the
# running stack exactly as they were.
#
# WHY. The one-release compat policy (deploy/README.md) keeps old code able to
# READ a newer schema. It says nothing about what old code DOES with a value it
# has never seen. vidra-core's INTERNAL_PRIVACY_MIGRATION adds the 'internal'
# video privacy tier, and a core release without that migration does not know
# the tier. This script never migrates down, so it must not put such a release
# in front of data that uses the tier.
#
# "WITHOUT THAT MIGRATION" COMES FROM THE RELEASE RECORDS, by FILE NAME:
# deploy/release.sh lists each core's migration files in releases/<tag>.json
# (core_migrations), and `deploy/release-mapping.py core-migration` places a
# tag that has no record by the recorded cores around it. A record cut before
# that list existed can only say "no" — when its newest migration is below the
# file's number — and otherwise says nothing, so the database is asked. No
# future release tag is written down here, and nothing has to be filled in when
# the release that ships the migration is cut.
#
# SEVERITY — a finding may only stop what it PREDICTS:
#   - core not being rolled (`--user` / `--search` alone): not checked; the core
#     that runs afterwards is the one running now.
#   - the target carries the migration: not checked.
#   - no video at 'internal': proceeds.
#   - videos at 'internal' and a target that does NOT carry the migration:
#     REFUSED unless --remap-internal-to-private. No flag waves this through,
#     because the finding is definite.
#   - the database cannot be asked (external Postgres, postgres not running,
#     compose cannot list it, a psql error or TIMEOUT), or videos are at
#     'internal' and the records cannot place the target: REFUSED unless
#     --allow-unchecked-privacy-tier. Fail closed, not locked out. The override
#     exists for the second case because a remap would needlessly demote videos
#     for a target that may well know the tier.
PGUSER="$(env_get POSTGRES_USER vidra)"
PGDB="$(env_get POSTGRES_DB vidra)"
BACKUP_DIR="${BACKUP_DIR:-$REPO_ROOT/backups}"
# EVERY query below is bounded, because this runs mid-incident: a lock held by a
# stuck migration or a wedged server must turn into a refusal that says so, not
# into a rollback that hangs with the broken release still serving. The connect
# bound is psql's own PGCONNECT_TIMEOUT; the other two are server settings sent
# with the session.
PG_TIMEOUTS="-c statement_timeout=15s -c lock_timeout=5s"
PG_CONNECT_TIMEOUT=10
INTERNAL_SQL="SELECT EXISTS (SELECT 1 FROM videos WHERE privacy = 'internal');"
# Verbatim from the down migration of INTERNAL_PRIVACY_MIGRATION, which is the
# only remap anyone has reviewed. Kept separate from RETURNING so the messages
# can quote it as is.
REMAP_SQL="UPDATE videos SET privacy = 'private' WHERE privacy = 'internal';"
REMAP_IDS_FILE="$BACKUP_DIR/internal-privacy-remap-$(date -u +%FT%H%M%S).ids"
REMAPPED_TOTAL=0
PRIVACY_STATE=off        # off | clean | remap | accepted
PRIVACY_UNASKED=""

# privacy_pg OPTIONS SQL [PSQL FLAG...] — run ONE statement in the bundled
# postgres container with the PG_TIMEOUTS bounds. Its output is in PG_OUT.
# Exit 0 on success; on anything else exit 2 with PRIVACY_UNASKED saying why,
# naming a TIMEOUT as one. No `docker exec -i`: nothing is piped in, and an
# attached stdin would swallow the rest of a script fed to `bash -s`.
privacy_pg() {
  local options="$1" sql="$2" cid errf rc=0
  shift 2
  if [ "$EXTERNAL_POSTGRES" -eq 1 ]; then
    PRIVACY_UNASKED="VIDRA_EXTERNAL_POSTGRES=true, so there is no bundled postgres container to ask"
    return 2
  fi
  # Not `2>/dev/null || true`: a compose model that does not render is not "the
  # container is not running", and an operator sent to start postgres would be
  # chasing the wrong fault. Compose's own error stays on the terminal.
  if ! cid="$("${COMPOSE[@]}" ps -q postgres)"; then
    PRIVACY_UNASKED="'docker compose ps' could not list the postgres container (its error is above)"
    return 2
  fi
  if [ -z "$cid" ]; then
    PRIVACY_UNASKED="the bundled postgres container is not running"
    return 2
  fi
  errf="$(mktemp)" || { PRIVACY_UNASKED="mktemp failed, so psql's error could not be captured"; return 2; }
  PG_OUT="$(docker exec -e "PGCONNECT_TIMEOUT=${PG_CONNECT_TIMEOUT}" -e "PGOPTIONS=${options} ${PG_TIMEOUTS}" "$cid" \
    psql -X -q -t -A -v ON_ERROR_STOP=1 "$@" -U "$PGUSER" -d "$PGDB" -c "$sql" 2>"$errf")" || rc=$?
  PG_ERR="$(tr '\n' ' ' < "$errf")"
  rm -f "$errf"
  [ "$rc" -ne 0 ] || return 0
  case "$PG_ERR" in
    *"statement timeout"*|*"lock timeout"*|*"timeout expired"*)
      PRIVACY_UNASKED="psql TIMED OUT (statement_timeout=15s, lock_timeout=5s, connect ${PG_CONNECT_TIMEOUT}s): ${PG_ERR}" ;;
    *) PRIVACY_UNASKED="psql failed (exit ${rc}): ${PG_ERR:-no error text}" ;;
  esac
  return 2
}

# internal_privacy_rows — exit 0 when a video is at privacy 'internal', 1 when
# none is, and 2 when the question could not be asked (PRIVACY_UNASKED says
# why). READ-ONLY twice over: a SELECT, in a session the SERVER holds read-only
# (default_transaction_read_only), so no later edit of the query can turn the
# check into a write.
internal_privacy_rows() {
  privacy_pg '-c default_transaction_read_only=on' "$INTERNAL_SQL" || return 2
  case "$PG_OUT" in
    t) return 0 ;;
    f) return 1 ;;
  esac
  PRIVACY_UNASKED="psql answered '${PG_OUT}', which is neither t nor f"
  return 2
}

# remap_internal_to_private — REMAP_SQL and nothing else: every 'internal' video
# becomes 'private', the stricter tier, so the remap can only narrow who sees a
# video. One statement under psql --single-transaction: all of them or none.
# On failure PRIVACY_UNASKED says why. The ids go to REMAP_IDS_FILE (0600,
# appended, one per line) because once remapped they cannot be told apart from
# videos that were always private; a later roll-forward needs the list.
remap_internal_to_private() {
  local count
  privacy_pg '' "${REMAP_SQL%;} RETURNING id;" -1 || return 1
  count="$(printf '%s\n' "$PG_OUT" | awk 'NF { n++ } END { print n + 0 }')"
  REMAPPED_TOTAL=$((REMAPPED_TOTAL + count))
  log "remapped ${count} video(s) from privacy 'internal' to 'private' (${REMAP_SQL})"
  [ "$count" -gt 0 ] || return 0
  if mkdir -p "$BACKUP_DIR" && (umask 077 && printf '%s\n' "$PG_OUT" >> "$REMAP_IDS_FILE"); then
    log "their ids are in ${REMAP_IDS_FILE}. After rolling forward to a release that knows the tier, an owner can set them back, or: UPDATE videos SET privacy = 'internal' WHERE id = '<id>';"
  else
    log "WARNING: could not write ${REMAP_IDS_FILE}; the remapped ids follow, so they are not lost:"
    printf '%s\n' "$PG_OUT" >&2
  fi
}

# remap_note — one sentence for every failure message printed after a remap ran:
# the ids file is the only record of what it changed.
remap_note() {
  if [ "$REMAPPED_TOTAL" -gt 0 ]; then
    printf " This run already remapped %s video(s) from 'internal' to 'private'; their ids are in %s — keep that file." \
      "$REMAPPED_TOTAL" "$REMAP_IDS_FILE"
  fi
}

privacy_tier_gate() {
  local how rc=0 rows=0 target nothing_changed
  nothing_changed="Nothing was changed: $ENV_FILE was NOT rewritten and nothing was pulled or restarted."
  if [ -z "$CORE_TAG" ]; then
    log "privacy-tier check: core is not being rolled back, so the core that runs afterwards is the one running now — not checked"
    if [ "$REMAP_INTERNAL" -eq 1 ]; then log "--remap-internal-to-private: nothing to do, and NOTHING was remapped"; fi
    return 0
  fi
  how="$(python3 "$REPO_ROOT/deploy/release-mapping.py" core-migration --releases "$REPO_ROOT/releases" \
    --core "$CORE_TAG" --migration "$INTERNAL_PRIVACY_MIGRATION")" || rc=$?
  case "$rc" in
    0)
      log "privacy-tier check: core ${CORE_TAG} carries migration ${INTERNAL_PRIVACY_MIGRATION} (${how}) — not checked"
      if [ "$REMAP_INTERNAL" -eq 1 ]; then log "--remap-internal-to-private: not needed for this target, and NOTHING was remapped"; fi
      return 0 ;;
    4) target="core ${CORE_TAG} does not carry migration ${INTERNAL_PRIVACY_MIGRATION} (${how})" ;;
    *) target="core ${CORE_TAG} could not be placed relative to migration ${INTERNAL_PRIVACY_MIGRATION} (${how:-deploy/release-mapping.py core-migration exited ${rc}}), so it is treated as not carrying it" ;;
  esac
  internal_privacy_rows || rows=$?
  if [ "$rows" -eq 1 ]; then
    log "privacy-tier check: ${target}; no video is at privacy 'internal' — proceeding"
    PRIVACY_STATE=clean
    return 0
  fi
  if [ "$rows" -eq 0 ] && [ "$REMAP_INTERNAL" -eq 1 ]; then
    log "privacy-tier check: ${target}; videos ARE at privacy 'internal'. --remap-internal-to-private was given: they are remapped after the pull, immediately before the restart"
    PRIVACY_STATE=remap
    return 0
  fi
  if [ "$rows" -eq 0 ] && [ "$rc" -eq 4 ]; then
    die "this app-only rollback would run ${target} against a database with videos at privacy 'internal', a tier that release does not know. Refusing. Remap them first: re-run with --remap-internal-to-private, which runs the UPDATE from that migration's down migration (${REMAP_SQL}) as one transaction just before the restart, records the ids it changed under ${BACKUP_DIR}/, and proceeds. ${nothing_changed}"
  fi
  if [ "$ALLOW_UNCHECKED_PRIVACY" -eq 1 ]; then
    log "WARNING: privacy-tier check NOT settled: ${PRIVACY_UNASKED:-videos are at privacy 'internal' and the target could not be placed}. ${target}. --allow-unchecked-privacy-tier was given, so this rollback proceeds on your word."
    # Only reachable with REMAP_INTERNAL=1 when the database could not be asked.
    if [ "$REMAP_INTERNAL" -eq 1 ]; then log "--remap-internal-to-private needs that same connection, so NOTHING was remapped"; fi
    PRIVACY_STATE=accepted
    return 0
  fi
  if [ "$rows" -eq 0 ]; then
    die "${target}, and the database has videos at privacy 'internal'. Refusing rather than guessing. If the target DOES carry migration ${INTERNAL_PRIVACY_MIGRATION} (its release record is missing from this tree, say), re-run with --allow-unchecked-privacy-tier; otherwise re-run with --remap-internal-to-private. ${nothing_changed}"
  fi
  die "the privacy-tier check could not be made: ${PRIVACY_UNASKED}. ${target}, so this rollback is refused rather than guessed. Check by hand against the database: SELECT count(*) FROM videos WHERE privacy = 'internal'; — if it is 0, or once you have run ${REMAP_SQL} yourself, re-run with --allow-unchecked-privacy-tier.$( [ "$REMAP_INTERNAL" -eq 0 ] || printf ' (--remap-internal-to-private cannot help here: it needs the same database connection.)' ) ${nothing_changed}"
}
privacy_tier_gate

# THE WORD-LISTS GATE, same place and same shape as the privacy-tier gate, same
# bounded read-only psql (privacy_pg). vidra-core's WORD_LISTS_MIGRATION adds
# per-account watched-word lists and a 'hold' action per list. A core release
# without it does not know either: it matches EVERY term in watched_words
# (including creators' private ones) and files the hit in the staff review queue,
# and a comment a 'hold' list would have held is published. This script never
# migrates down, so it must not put such a release in front of that data.
#
# Severity, as for the privacy tier: core not being rolled, or a target that
# carries the migration: not checked. No private list and no 'hold' list:
# proceeds (a missing watched_word_lists table is that case too). Otherwise
# REFUSED, with no flag, because the finding is definite - clear the data by
# hand (the SQL is in the message), then re-run. A check that cannot be made, or
# a target the records cannot place with the data present, is refused unless
# --allow-unchecked-word-lists.
WORD_LISTS_SQL="SELECT count(*) > 0 FROM watched_word_lists WHERE owner_id IS NOT NULL OR action = 'hold';"
WORD_LISTS_FIX_SQL="DELETE FROM watched_word_lists WHERE owner_id IS NOT NULL; UPDATE watched_word_lists SET action = 'flag' WHERE action = 'hold';"

word_lists_in_use() {
  PG_ERR=""
  privacy_pg '-c default_transaction_read_only=on' "$WORD_LISTS_SQL" && {
    case "$PG_OUT" in
      t) return 0 ;;
      f) return 1 ;;
    esac
    PRIVACY_UNASKED="psql answered '${PG_OUT}', which is neither t nor f"
    return 2
  }
  # A database below the migration has no such table: nothing to protect.
  case "$PG_ERR" in *'"watched_word_lists" does not exist'*) return 1 ;; esac
  return 2
}

word_lists_gate() {
  local how rc=0 rows=0 target nothing_changed
  nothing_changed="Nothing was changed: $ENV_FILE was NOT rewritten and nothing was pulled or restarted."
  if [ -z "$CORE_TAG" ]; then
    log "word-lists check: core is not being rolled back — not checked"
    return 0
  fi
  how="$(python3 "$REPO_ROOT/deploy/release-mapping.py" core-migration --releases "$REPO_ROOT/releases" \
    --core "$CORE_TAG" --migration "$WORD_LISTS_MIGRATION")" || rc=$?
  case "$rc" in
    0) log "word-lists check: core ${CORE_TAG} carries migration ${WORD_LISTS_MIGRATION} (${how}) — not checked"; return 0 ;;
    4) target="core ${CORE_TAG} does not carry migration ${WORD_LISTS_MIGRATION} (${how})" ;;
    *) target="core ${CORE_TAG} could not be placed relative to migration ${WORD_LISTS_MIGRATION} (${how:-deploy/release-mapping.py core-migration exited ${rc}}), so it is treated as not carrying it" ;;
  esac
  word_lists_in_use || rows=$?
  if [ "$rows" -eq 1 ]; then
    log "word-lists check: ${target}; no per-account or 'hold' watched-word list exists — proceeding"
    return 0
  fi
  if [ "$rows" -eq 0 ] && [ "$rc" -eq 4 ]; then
    die "this app-only rollback would run ${target} against a database with per-account or 'hold' watched-word lists. That release would put creators' private terms in the staff review queue and publish comments a 'hold' list holds. Refusing. Clear them first, by hand: ${WORD_LISTS_FIX_SQL} then re-run. ${nothing_changed}"
  fi
  if [ "$ALLOW_UNCHECKED_WORD_LISTS" -eq 1 ]; then
    log "WARNING: word-lists check NOT settled: ${PRIVACY_UNASKED:-lists exist and the target could not be placed}. ${target}. --allow-unchecked-word-lists was given, so this rollback proceeds on your word."
    return 0
  fi
  if [ "$rows" -eq 0 ]; then
    die "${target}, and the database has per-account or 'hold' watched-word lists. Refusing rather than guessing. If the target DOES carry migration ${WORD_LISTS_MIGRATION}, re-run with --allow-unchecked-word-lists; otherwise clear them by hand: ${WORD_LISTS_FIX_SQL} ${nothing_changed}"
  fi
  die "the word-lists check could not be made: ${PRIVACY_UNASKED}. ${target}, so this rollback is refused rather than guessed. Check by hand: ${WORD_LISTS_SQL} - if it is f, re-run with --allow-unchecked-word-lists. ${nothing_changed}"
}
word_lists_gate

# THE OIDC-PROVIDERS GATE, same place, same bounded read-only psql. vidra-core's
# OIDC_PROVIDERS_MIGRATION adds admin-managed OIDC providers that can OVERRIDE or
# DISABLE the environment-configured ones (stricter domain allow-lists, off). A
# core release without it ignores the table, so the environment providers come
# back WITHOUT the admin's restrictions. This script never migrates down.
#
# Severity: a finding may only stop what it PREDICTS. Core not being rolled, or a
# target that carries the migration: not checked. No rows (or no table): the
# environment providers are all there is, so WARN and proceed. Rows present and
# the target known to predate it: REFUSED unless --allow-oidc-env-fallback. A
# check that cannot be made, or a target the records cannot place with rows
# present, is refused the same way.
OIDC_SQL="SELECT count(*) > 0 FROM oidc_providers;"

oidc_providers_in_use() {
  PG_ERR=""
  privacy_pg '-c default_transaction_read_only=on' "$OIDC_SQL" && {
    case "$PG_OUT" in
      t) return 0 ;;
      f) return 1 ;;
    esac
    PRIVACY_UNASKED="psql answered '${PG_OUT}', which is neither t nor f"
    return 2
  }
  # A database below the migration has no such table: nothing to protect.
  case "$PG_ERR" in *'"oidc_providers" does not exist'*) return 1 ;; esac
  return 2
}

oidc_providers_gate() {
  local how rc=0 rows=0 target nothing_changed
  nothing_changed="Nothing was changed: $ENV_FILE was NOT rewritten and nothing was pulled or restarted."
  if [ -z "$CORE_TAG" ]; then
    log "oidc-providers check: core is not being rolled back — not checked"
    return 0
  fi
  how="$(python3 "$REPO_ROOT/deploy/release-mapping.py" core-migration --releases "$REPO_ROOT/releases" \
    --core "$CORE_TAG" --migration "$OIDC_PROVIDERS_MIGRATION")" || rc=$?
  case "$rc" in
    0) log "oidc-providers check: core ${CORE_TAG} carries migration ${OIDC_PROVIDERS_MIGRATION} (${how}) — not checked"; return 0 ;;
    4) target="core ${CORE_TAG} does not carry migration ${OIDC_PROVIDERS_MIGRATION} (${how})" ;;
    *) target="core ${CORE_TAG} could not be placed relative to migration ${OIDC_PROVIDERS_MIGRATION} (${how:-deploy/release-mapping.py core-migration exited ${rc}}), so it is treated as not carrying it" ;;
  esac
  oidc_providers_in_use || rows=$?
  if [ "$rows" -eq 1 ]; then
    log "WARNING: oidc-providers check: ${target}; oidc_providers is empty, so only environment-configured providers (OAUTH_PROVIDERS) apply — proceeding. Providers an admin adds after this rollback will be ignored by that release."
    return 0
  fi
  if [ "$ALLOW_OIDC_ENV_FALLBACK" -eq 1 ]; then
    log "WARNING: oidc-providers check: ${target}; ${PRIVACY_UNASKED:-oidc_providers has rows}. --allow-oidc-env-fallback was given, so this rollback proceeds on your word: environment providers will return without any admin override or disable."
    return 0
  fi
  if [ "$rows" -eq 0 ]; then
    die "this app-only rollback would run ${target} against a database with admin-managed OIDC providers. That release ignores them, so environment-configured providers come back WITHOUT the admin's overrides, stricter domain allow-lists or disables. Refusing. Review OAUTH_PROVIDERS and the oidc_providers table first (disable any environment provider the admin had turned off or restricted), then re-run with --allow-oidc-env-fallback. ${nothing_changed}"
  fi
  die "the oidc-providers check could not be made: ${PRIVACY_UNASKED}. ${target}, so this rollback is refused rather than guessed. Check by hand: ${OIDC_SQL} - if it is f, re-run with --allow-oidc-env-fallback. ${nothing_changed}"
}
oidc_providers_gate

HTTP_PORT="$(env_get HTTP_PORT 8080)"
FRONTEND_PORT="$(env_get FRONTEND_PORT 3000)"

log "current: core=$(env_get VIDRA_CORE_TAG '(unset)') user=$(env_get VIDRA_USER_TAG '(unset)') search=$(env_get VIDRA_SEARCH_TAG '(unset)')"

# Rewrite in place via a temp file + mv rather than `sed -i`, whose syntax
# differs between GNU and BSD sed. Appends the key when it is not already
# present, so this also works on an env file that inherited its tags from the
# shell.
#
# Preserve the pre-rollback state outside the checkout, at a unique 0600 path.
# Keep it after success too: a second rollback must not overwrite this recovery.
ENV_SNAPSHOT="$(ENV_FILE="$ENV_FILE" bash "$REPO_ROOT/deploy/backup-env.sh")" || die "env snapshot failed"
log "env snapshot: $ENV_SNAPSHOT"

# EVERY refusal between here and `up -d` puts the env file back (A38 rehearsal,
# 2026-09-08, finding A38R-2). Above this line the file still holds the tags you
# were serving; below it, it holds the rollback target — and the failures that
# can happen in between (a checkout that will not sync, a compose model that no
# longer renders, a tag that is not in the registry) all leave the RUNNING STACK
# untouched. Leaving the file rewritten after one of those is the worst of both:
# nothing rolled back, and the next `deploy.sh`, `compose ps` or `restore.sh` the
# operator types reads tags that were never deployed.
#
# It used to be uneven. `config -q` restored the .bak; `pull` did not, and its
# message — "($ENV_FILE restored from $ENV_SNAPSHOT if you need to undo)" —
# reads mid-incident like a statement that it HAD been, which is exactly the
# sentence an operator should not have to parse twice. One helper now, so the
# paths cannot drift apart again.
restore_env_and_die() {
  if [ -f "$ENV_SNAPSHOT" ] && cat "$ENV_SNAPSHOT" > "$ENV_FILE"; then
    log "restored ${ENV_FILE} from $ENV_SNAPSHOT — the tags in it are the ones you were serving before this run"
  else
    log "WARNING: could not restore ${ENV_FILE} from $ENV_SNAPSHOT; ${ENV_FILE} still pins the ROLLBACK TARGET tags and the recovery snapshot is $ENV_SNAPSHOT"
  fi
  die "$*"
}

env_set_key VIDRA_CORE_TAG   "$CORE_TAG"
env_set_key VIDRA_USER_TAG   "$USER_TAG"
env_set_key VIDRA_SEARCH_TAG "$SEARCH_TAG"

# An unpacked release bundle has no .git anywhere and nothing to sync — see the
# same block in deploy.sh for the reasoning. It matters more here than there:
# this script runs mid-incident, and dying on a missing .git while rolling back
# would strand the operator on the broken release for the sake of a checkout that
# was never going to exist. The env file has already been rewritten at this
# point, so the tags are pinned; a bundle simply has no second copy of the source
# to move alongside them.
if is_bundle_tree "$REPO_ROOT"; then
  log "vidra-bundle.manifest is present and vidra-core is not a git checkout — this tree was unpacked from the $(bundle_manifest_get "$REPO_ROOT" tag '(unknown)') bundle. Nothing to sync; the rollback is the VIDRA_*_TAG rewrite above plus the pull below."
else
  for repo in vidra-core vidra-search vidra-user; do
    [ -e "$repo" ] || continue
    [ -d "$repo/.git" ] || restore_env_and_die "$repo exists but is not a git checkout"
    case "$repo" in
      vidra-core)   tag="$(env_get VIDRA_CORE_TAG '?')" ;;
      vidra-search) tag="$(env_get VIDRA_SEARCH_TAG '?')" ;;
      vidra-user)   tag="$(env_get VIDRA_USER_TAG '?')" ;;
    esac
    [ "$tag" != "?" ] || continue
    log "syncing $repo to $tag"
    # --force: a tag re-pointed upstream is otherwise refused and the checkout
    # pins the stale object. Kept identical in deploy.sh.
    # A repo that already moved is NOT moved back: the next run re-syncs every
    # checkout from the env file, and unwinding a partial sweep here would be a
    # second, quieter thing that can fail mid-incident. What is restored is the
    # env file, which is what the next command reads.
    git -C "$repo" fetch --tags --force --quiet || restore_env_and_die "git fetch failed in $repo — nothing was changed on the running stack. Any checkout already synced by this run stays where it is; the next deploy or rollback re-syncs them all from ${ENV_FILE}"
    git -C "$repo" checkout --detach --quiet "$tag" || restore_env_and_die "failed to checkout tag $tag in $repo — nothing was changed on the running stack. Any checkout already synced by this run stays where it is; the next deploy or rollback re-syncs them all from ${ENV_FILE}"
  done
fi

# COMPOSE was set by vidra_compose_chain, above the privacy-tier gate.
"${COMPOSE[@]}" config -q \
  || restore_env_and_die "the compose model does not render with the rollback tags — aborted; nothing was changed on the running stack"

log "pulling"
# `pull` runs BEFORE anything is stopped on purpose, so a tag that is not in the
# registry costs an operator nothing but this message — including the released
# images that exist for only one architecture, which is how the A38 rehearsal met
# this path (`no matching manifest for linux/arm64/v8`).
"${COMPOSE[@]}" pull \
  || restore_env_and_die "pull failed — does that tag exist in the registry, for this architecture? Nothing was changed on the running stack"

# THE PRIVACY-TIER GATE, SECOND LOOK: after the pull, immediately before the
# restart. The remap runs HERE and not at the gate, so a refusal or a failed
# pull above leaves every video exactly as it was. A "no 'internal' videos"
# answer is asked AGAIN, because the pull can take minutes with the newer
# release still serving, and still able to put a video at 'internal'.
case "$PRIVACY_STATE" in
  remap)
    remap_internal_to_private \
      || restore_env_and_die "--remap-internal-to-private failed: ${PRIVACY_UNASKED}. Nothing was restarted. The remap is one transaction, so it changed every such video or none; re-running this command retries it" ;;
  clean)
    privacy_rows=0; internal_privacy_rows || privacy_rows=$?
    case "$privacy_rows" in
      0) restore_env_and_die "a video was put at privacy 'internal' while this rollback was pulling, so the target would now meet the tier it does not know. Nothing was restarted. Re-run with --remap-internal-to-private" ;;
      2) restore_env_and_die "the privacy-tier check passed before the pull but could not be repeated now: ${PRIVACY_UNASKED}. Nothing was restarted. Re-run once the database answers, or see --allow-unchecked-privacy-tier" ;;
    esac ;;
esac

# THE TRAILER, and it is a function so that EVERY path that leaves the site down
# reaches it (A38 rehearsal, 2026-09-07, run 4). It used to be inline at the very
# bottom, reachable only from the readiness probes — so when `up -d` itself
# failed, `set -e` killed the script first and the operator got a raw compose
# error, a dark site, and no sentence telling them what to do next. `up -d` is
# now `|| rollback_target_unhealthy`, and the probes call the same function.
rollback_target_unhealthy() {
  cat >&2 <<EOF

[rollback] THE ROLLBACK TARGET IS ALSO UNHEALTHY.
  $1

  If the newer release ran an incompatible migration, the old code cannot read
  the new schema — restore the pre-deploy dump before rolling back again:
      ./deploy/restore.sh backups/pre-deploy-<ts>.dump.gz
EOF
  # After a remap, the ids file is the only record of what it changed, and an
  # operator about to restore or roll forward again needs it. Plain variables
  # with defaults, not remap_note: this function must stand on its own
  # (tests/rollback_floor_test.py runs it in isolation).
  if [ "${REMAPPED_TOTAL:-0}" -gt 0 ]; then
    printf "\n  This run remapped %s video(s) from privacy 'internal' to 'private' before the\n  restart. Their ids are in %s — keep that file:\n  rolling forward again needs it to set them back.\n" \
      "$REMAPPED_TOTAL" "${REMAP_IDS_FILE:-backups/}" >&2
  fi
  exit 1
}

log "restarting"
# WHY THIS IS GUARDED. `up -d` starts the 'migrate' and 'search-migrate'
# one-shots too — api and search depend on them with
# service_completed_successfully — and they run 'migrate up' on the release
# being rolled BACK to. A release whose migrator predates the "ledger is ahead
# of this binary" no-op (vidra-core / vidra-search, A38) exits 1 there against a
# newer schema, and every service waiting on it is never started. Unguarded,
# that took the whole site down with nothing but a compose error to show for it.
"${COMPOSE[@]}" up -d --no-build || rollback_target_unhealthy \
  "compose up -d exited non-zero; its output is above. Check the migration one-shots FIRST: '${COMPOSE[*]} logs migrate search-migrate'. A message like 'no migration found for version N' means this release's migrator is older than the schema in front of it — the app itself is fine on that schema, but the one-shot has to exit 0 before api, search and frontend are allowed to start."

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

# THE PRIVACY-TIER GATE, LAST LOOK, now that the target owns the data. The newer
# api kept serving until `up -d` replaced it — through the migration one-shots —
# so the remap is repeated (normally 0 rows) and a clean answer is re-asked. It
# sits after probe()'s definition only so the `up -d` block above stays one
# contiguous unit (tests/rollback_floor_test.py runs it in isolation); nothing
# has executed in between.
case "$PRIVACY_STATE" in
  remap)
    remap_internal_to_private \
      || die "the rollback target is RUNNING, but the post-restart remap failed: ${PRIVACY_UNASKED}. Run it by hand now: ${REMAP_SQL}$(remap_note)" ;;
  clean)
    privacy_rows=0; internal_privacy_rows || privacy_rows=$?
    case "$privacy_rows" in
      0) die "the rollback target is RUNNING, and a video was put at privacy 'internal' before the newer release stopped. Remap it now: ./deploy/rollback.sh --core ${CORE_TAG} --remap-internal-to-private" ;;
      2) log "WARNING: the rollback target is running, and the privacy-tier check could not be repeated: ${PRIVACY_UNASKED}. Check by hand: SELECT count(*) FROM videos WHERE privacy = 'internal';" ;;
    esac ;;
esac

rc=0
probe "api /readyz" "http://127.0.0.1:${HTTP_PORT}/readyz" || rc=1
probe "frontend"    "http://127.0.0.1:${FRONTEND_PORT}/"   || rc=1

if [ "$rc" -ne 0 ]; then
  rollback_target_unhealthy "The containers started, but a readiness probe never passed; recent logs are above."
fi

log "rolled back to core=${CORE_TAG:-unchanged} user=${USER_TAG:-unchanged} search=${SEARCH_TAG:-unchanged}"
