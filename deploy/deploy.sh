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
# How long to wait for the TLS EDGE specifically, which is a different question
# from "is the api up". Longer than READY_TIMEOUT because on a first deploy Caddy
# is still obtaining a certificate at this point: an ACME HTTP-01 round-trip is
# usually seconds but can take the better part of a minute, and none of it starts
# until the site is loaded — i.e. after everything READY_TIMEOUT covers.
EDGE_TIMEOUT="${EDGE_TIMEOUT:-180}"
# How many pre-deploy dumps to keep. These are separate from backup.sh's nightly
# family and are pruned by count, because their cadence is "however often you
# deploy" rather than daily.
PREDEPLOY_KEEP="${PREDEPLOY_KEEP:-10}"

# The FIRST release whose vidra-core / vidra-search images carry the embedded
# `migrate` subcommand. ADJUST THIS AT RELEASE TIME — set it to the tag actually
# cut with the embedded migrator, and never lower it afterwards.
#
# WHY IT IS A HARD GATE: docker-compose.prod.yml runs both migration one-shots
# from the SERVICE image, whose compose command is `migrate up`. An OLDER image's
# main() ignores argv completely and starts the API SERVER instead, so the
# one-shot never exits — deploy.sh's `run --rm migrate` step blocks forever, and
# `up -d` blocks on the api/search `service_completed_successfully` edges. Both
# failure modes are a hang with no error message, which is the worst kind. The
# tag comparison below turns them into a refusal before anything is touched.
# Kept identical in rollback.sh and restore.sh.
MIN_EMBEDDED_MIGRATE_TAG="v0.2.0"

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

# semver_ge <tag> <floor> — numeric MAJOR.MINOR.PATCH comparison of two vX.Y.Z
# tags. Exit 0 when <tag> >= <floor>, 1 when it is older, and 2 when <tag> is not
# semver-shaped at all (so the caller can say "cannot check" instead of guessing).
# A prerelease/build suffix is ignored on purpose: v0.2.0-rc1 is built from the
# v0.2.0 code and carries the same migrator, so it counts as v0.2.0 here.
# Kept identical in rollback.sh and restore.sh.
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
# MIN_EMBEDDED_MIGRATE_TAG above for what such an image does to a deploy.
# An empty tag is left alone: the compose render check reports unset image tags
# with a better message than this can (`${VIDRA_*_TAG:?}`).
# Kept identical in rollback.sh and restore.sh, apart from the closing sentence of
# the final message, which names the operation each one would have hung.
require_embedded_migrate_tag() {
  local what="$1" tag="$2" rc=0
  [ -n "$tag" ] || return 0
  semver_ge "$tag" "$MIN_EMBEDDED_MIGRATE_TAG" || rc=$?
  case "$rc" in
    0) return 0 ;;
    2) die "$what=$tag is not a vMAJOR.MINOR.PATCH tag, so it cannot be checked against the ${MIN_EMBEDDED_MIGRATE_TAG} floor. Releases are semver tags (see 'Cutting a release' in deploy/README.md). An image built before the embedded 'migrate' subcommand ignores the one-shots' 'migrate up' command and boots an API server that never exits, hanging this run with no error. Retag the release, or probe the image by hand and WATCH the output: 'docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file $ENV_FILE run --rm migrate migrate version' prints 'version=N dirty=false' on an image that has the subcommand, and starts an HTTP server you have to interrupt on one that does not" ;;
  esac
  die "$what=$tag is older than $MIN_EMBEDDED_MIGRATE_TAG, the first release whose image carries the embedded 'migrate' subcommand. docker-compose.prod.yml runs the migration one-shots from the SERVICE image with the command 'migrate up'; an older binary ignores those arguments and starts the API server instead, so the one-shot never exits and this run would HANG (on 'run --rm migrate' here, or on the api/search service_completed_successfully edges during 'up -d') rather than fail. Use $MIN_EMBEDDED_MIGRATE_TAG or newer. Going further back means also checking out that release's compose files, which drove the golang-migrate CLI container instead."
}

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

# url_host <url> — the bare hostname of a URL, with scheme, userinfo, port and
# path removed. Pure parameter expansion so it works with no external tools.
url_host() {
  local u="${1#*://}"
  u="${u%%/*}"
  u="${u##*@}"
  u="${u%%\?*}"
  # Strip the port, but not from a bracketed IPv6 literal.
  case "$u" in
    \[*\]*) u="${u%%\]*}]" ;;
    *:*)    u="${u%%:*}" ;;
  esac
  printf '%s' "$u"
}

# caddyfile_site_address <file> — the first SITE ADDRESS line, i.e. the first
# non-comment line that starts at column 0 and opens a block. Directives inside
# a block are indented (both this repo's template and `vidra setup`'s renderer
# emit tabs), and the global options block opens with a bare `{`, so those two
# are excluded structurally rather than by name.
#
# The brace is written `[{]` in the sed script, not `\{`: an ESCAPED brace opens
# an interval expression in POSIX BRE, and BSD sed (macOS) rejects the result
# outright — "RE error: invalid repetition count(s)". Verified by running this
# on both.
caddyfile_site_address() {
  grep -E '^[^[:space:]#].*[{][[:space:]]*$' "$1" 2>/dev/null \
    | head -n1 \
    | sed -e 's/[[:space:]]*[{][[:space:]]*$//' -e 's/[[:space:]]*$//'
}

# Caddy provisions a certificate for every hostname in a site block, so a
# placeholder domain means a failed ACME order and a site that serves nothing
# over TLS. This now checks deploy/Caddyfile.local — the file that is actually
# mounted — and additionally that its site address agrees with PUBLIC_BASE_URL:
# a Caddyfile serving `old.example.net` while the api mints links for
# `new.example.net` is a site that answers on a hostname nothing points at.
# Only NON-comment lines are searched for placeholders: a rendered file may
# still carry the template's explanatory comments, which mention example.com on
# purpose and must not trip this forever.
#
# DELIBERATELY NOT in rollback.sh or restore.sh, unlike require_compose_version
# and require_caddyfile_local. Those two run during an incident, and refusing an
# emergency rollback over a cosmetic file check would be the wrong trade.
#
# The placeholder match is anchored on the left so a real domain that merely
# ENDS in one (myexample.com) is not refused, while a subdomain OF it
# (sub.example.com) still is — '.' is intentionally absent from the excluded
# character class for exactly that reason.
require_real_domain() {
  local f="$REPO_ROOT/deploy/Caddyfile.local" site addr host matched=0
  [ -f "$f" ] || return 0
  if grep -vE '^[[:space:]]*#' "$f" | grep -qE '(^|[^A-Za-z0-9-])(example\.(com|org|net)|your-domain|yourdomain|YOUR_DOMAIN)'; then
    die "deploy/Caddyfile.local still contains a placeholder domain (example.com / your-domain / YOUR_DOMAIN) — replace it with your real domain, or re-run 'vidra setup' (comments may keep it). Caddy would order a certificate for the placeholder and fail."
  fi

  site="$(caddyfile_site_address "$f")"
  [ -n "$site" ] || die "could not find a site address in deploy/Caddyfile.local — expected a line like 'vidra.example.org {' at the start of a line. Re-run 'vidra setup' to regenerate it."

  host="$(url_host "$(env_get PUBLIC_BASE_URL '')")"
  [ -n "$host" ] || die "PUBLIC_BASE_URL is not set in $ENV_FILE, so the Caddyfile's site address cannot be checked against it. Set it to the https origin this instance serves (no path, no trailing slash)."

  # A site address line may list several addresses ("a.example.org,
  # www.example.org {"), and each may carry a scheme or a port.
  for addr in $(printf '%s' "$site" | tr ',' ' '); do
    [ "$(url_host "$addr")" = "$host" ] || continue
    matched=1
    break
  done
  [ "$matched" -eq 1 ] || die "deploy/Caddyfile.local serves '${site}' but PUBLIC_BASE_URL in $ENV_FILE is 'https://${host}'. Caddy would answer on one hostname while the api mints links, OAuth callbacks and federation actor ids for the other. Fix whichever is wrong (re-run 'vidra setup' to regenerate the Caddyfile from PUBLIC_BASE_URL)."
}

# resolve_host <name> — every A record, one per line, using whatever resolver
# tool the host has. getent is the Linux default (and honours /etc/hosts, which
# a split-horizon setup may rely on); dig and host cover macOS and minimal
# images. First tool that answers wins; an empty result means "does not
# resolve", which the caller treats as fatal.
resolve_host() {
  local name="$1" out=""
  if command -v getent >/dev/null 2>&1; then
    out="$(getent ahostsv4 "$name" 2>/dev/null | awk '{print $1}' | sort -u || true)"
  fi
  if [ -z "$out" ] && command -v dig >/dev/null 2>&1; then
    out="$(dig +short +time=3 +tries=1 A "$name" 2>/dev/null | grep -E '^[0-9]+(\.[0-9]+){3}$' || true)"
  fi
  if [ -z "$out" ] && command -v host >/dev/null 2>&1; then
    out="$(host -t A -W 3 "$name" 2>/dev/null | awk '/has address/ {print $NF}' || true)"
  fi
  printf '%s' "$out"
}

# discover_public_ip — this host's address as the internet sees it. The env
# override comes first (a NAT'd or air-gapped box cannot ask), then two
# independent echo services so one being down is not a deploy blocker.
#
# The two services and their ORDER are kept identical to vidra-core's
# internal/preflight/dns.go, so `vidra doctor` and this script cannot disagree
# about what this host's address is — a mismatch there reads as a DNS problem
# and sends the operator after the wrong thing.
#
# The override is whitespace-stripped exactly like the echo replies: a trailing
# space in the env file otherwise fails the comparison below with two
# identical-looking addresses printed in the message.
discover_public_ip() {
  local ip svc
  ip="$(env_get VIDRA_PUBLIC_IP '' | tr -d '[:space:]')"
  if [ -n "$ip" ]; then
    printf '%s' "$ip"
    return 0
  fi
  for svc in https://api.ipify.org https://icanhazip.com; do
    ip="$(curl -fsS -m 5 "$svc" 2>/dev/null | tr -d '[:space:]' || true)"
    case "$ip" in
      [0-9]*.[0-9]*.[0-9]*.[0-9]*) printf '%s' "$ip"; return 0 ;;
    esac
  done
  printf ''
}

# DNS PREFLIGHT — the cheapest protection against Let's Encrypt's rate limits.
#
# Caddy orders a certificate the moment it starts, and a failed HTTP-01
# challenge counts against the "5 failures per account, hostname and hour"
# limit. The classic first-deploy story is a domain whose A record still points
# at the old host (or nowhere): five restarts later the hostname is locked out
# for an hour and the site serves nothing, with the real fix — a DNS record —
# untouched. So this runs BEFORE anything is started, and refuses.
#
# Only for the ACME modes. VIDRA_TLS_MODE=internal issues from Caddy's own CA
# and never talks to an ACME server, so DNS is irrelevant to it.
require_dns_points_here() {
  local mode host resolved ip
  mode="$(env_get VIDRA_TLS_MODE acme)"
  case "$mode" in
    acme|acme-staging) ;;
    internal)
      log "VIDRA_TLS_MODE=internal — Caddy issues from its own CA, skipping the DNS preflight"
      return 0
      ;;
    *)
      die "VIDRA_TLS_MODE=$mode is not one of: acme, acme-staging, internal (see env/production.env.example)"
      ;;
  esac

  # Read through env_get, not straight off the process env: env/production.env
  # documents this key right next to VIDRA_PUBLIC_IP, and `vidra doctor` honours
  # both places — so an operator who sets it in the FILE (which is what the
  # template shows) had it silently ignored here while doctor reported it as
  # active. env_get still gives the process env precedence, so
  # `VIDRA_SKIP_DNS_PREFLIGHT=1 ./deploy/deploy.sh` is unchanged.
  case "$(env_get VIDRA_SKIP_DNS_PREFLIGHT 0)" in
    ""|0|false|no) ;;
    *)
      printf '[deploy] WARNING: VIDRA_SKIP_DNS_PREFLIGHT is set — NOT checking that the domain resolves here. A wrong A record now costs a Let'"'"'s Encrypt rate-limit lockout (5 failed authorisations per hostname per hour) instead of one refusal.\n' >&2
      return 0
      ;;
  esac

  host="$(url_host "$(env_get PUBLIC_BASE_URL '')")"
  [ -n "$host" ] || die "PUBLIC_BASE_URL is not set in $ENV_FILE — the DNS preflight has no hostname to check. Set it, or set VIDRA_TLS_MODE=internal if this instance is not on a public domain."

  resolved="$(resolve_host "$host")"
  [ -n "$resolved" ] || die "$host does not resolve (no A record). Caddy would immediately fail an ACME order for it and burn Let's Encrypt rate limit. Create the A record pointing at this host, wait for it to propagate, and re-run. To deploy anyway: VIDRA_SKIP_DNS_PREFLIGHT=1 ./deploy/deploy.sh (or VIDRA_TLS_MODE=internal for a private instance)."

  ip="$(discover_public_ip)"
  if [ -z "$ip" ]; then
    printf '[deploy] WARNING: %s resolves to [%s] but this host'"'"'s public IP could not be determined (no VIDRA_PUBLIC_IP, and neither IP echo service answered). Continuing WITHOUT the match check — if that record does not point here, the ACME order will fail.\n' \
      "$host" "$(printf '%s' "$resolved" | tr '\n' ' ' | sed 's/ *$//')" >&2
    return 0
  fi

  if printf '%s\n' "$resolved" | grep -qxF "$ip"; then
    log "DNS OK: $host -> $ip (this host)"
    return 0
  fi

  die "$host resolves to [$(printf '%s' "$resolved" | tr '\n' ' ' | sed 's/ *$//')] but this host is $ip. Caddy would fail the HTTP-01 challenge (the CA connects to whatever the A record names) and burn Let's Encrypt rate limit. Point the A record at $ip and wait for the TTL to expire, or — if this box really is behind a proxy/NAT — set VIDRA_PUBLIC_IP to the address the record uses. VIDRA_SKIP_DNS_PREFLIGHT=1 skips this check entirely."
}

# env_get, is_true and the compose chain live in deploy/lib.sh — every script
# that addresses the running stack must assemble the SAME project. Sourced here,
# after log/die and ENV_FILE, which is the contract lib.sh documents. The
# functions defined above call env_get, but none of them RUNS before this line.
# shellcheck source=deploy/lib.sh
. "$REPO_ROOT/deploy/lib.sh"

PGUSER="$(env_get POSTGRES_USER vidra)"
PGDB="$(env_get POSTGRES_DB vidra)"
HTTP_PORT="$(env_get HTTP_PORT 8080)"
FRONTEND_PORT="$(env_get FRONTEND_PORT 3000)"

# Sets COMPOSE, EXTERNAL_POSTGRES and EXTERNAL_REDIS.
vidra_compose_chain

step "0/6 pre-flight"
require_compose_version
# Order matters: the mounted Caddyfile must EXIST before it can be checked for a
# real domain, and the domain must be trustworthy before it is looked up.
require_caddyfile_local
require_real_domain
require_dns_points_here
# Before the checkout loop below moves anything: a tag that predates the embedded
# migrator would hang step 3/6 instead of failing it.
require_embedded_migrate_tag VIDRA_CORE_TAG   "$(env_get VIDRA_CORE_TAG '')"
require_embedded_migrate_tag VIDRA_SEARCH_TAG "$(env_get VIDRA_SEARCH_TAG '')"
log "compose $(docker compose version --short), deploy/Caddyfile.local serves $(url_host "$(env_get PUBLIC_BASE_URL '')"), migrator tags >= $MIN_EMBEDDED_MIGRATE_TAG"

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
  # --force: without it git refuses to move a tag the host already has, so a
  # tag re-pointed upstream (e.g. after a history rewrite) would silently pin
  # the STALE object forever. Kept identical in rollback.sh.
  git -C "$repo" fetch --tags --force --quiet || die "git fetch failed in $repo"
  git -C "$repo" checkout --detach --quiet "$tag" || die "failed to checkout tag $tag in $repo"
done

# The render check catches every `${VAR:?}` reference in the chain BEFORE
# anything is touched. Those are, exhaustively: JWT_SECRET (asserted by
# docker-compose.prod.yml's api environment), REDIS_PASSWORD (asserted by the
# redis command, its healthcheck, and both REDIS_URL rewrites),
# POSTGRES_PASSWORD (asserted by the overlay's postgres environment) and the
# three VIDRA_*_TAG image tags. `:?` fails on an EMPTY value as well as an unset one,
# which is what makes it catch the shipped `JWT_SECRET=` blank in an env file
# that was copied but never edited.
"${COMPOSE[@]}" config -q || die "compose config is invalid — fix $ENV_FILE and retry"
log "tags: core=$(env_get VIDRA_CORE_TAG '?') user=$(env_get VIDRA_USER_TAG '?') search=$(env_get VIDRA_SEARCH_TAG '?')"

step "1/6 pre-deploy database dump"
mkdir -p "$BACKUP_DIR"
PG_CID=""
if [ "$EXTERNAL_POSTGRES" -eq 0 ]; then
  PG_CID="$("${COMPOSE[@]}" ps -q postgres || true)"
fi
if [ "$EXTERNAL_POSTGRES" -eq 1 ]; then
  # There is no bundled container to pg_dump, and dumping a managed database
  # from here is deliberately not implemented (deploy/backup.sh refuses for the
  # same reason). This is the one safety net this script otherwise always has,
  # so it is a warning on stderr rather than a log line nobody reads.
  printf '[deploy] WARNING: VIDRA_EXTERNAL_POSTGRES=true — NO pre-deploy dump was taken. Take a snapshot / set a point-in-time-recovery marker with your database provider BEFORE continuing; a migration that goes wrong has no local escape hatch on this host.\n' >&2
elif [ -z "$PG_CID" ]; then
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

step "2/6 pull images"
"${COMPOSE[@]}" pull || die "pull failed — the tags in $ENV_FILE may not exist in GHCR yet, or the host needs 'docker login ghcr.io'"

step "3/6 migrations"
# Two separate ledgers, two separate gates. The search migrator writes
# vidra_search_migrations; core writes schema_migrations. Either can go dirty
# independently — see "Migration failed mid-deploy" in deploy/README.md.
#
# Both `run --rm` calls below deliberately pass NO command: each service's
# compose `command:` is `migrate up` on that service's OWN release image (the
# migrations are compiled into the api and search binaries — no golang-migrate
# CLI container, no bind-mounted migrations directory), and the image is pinned
# from the same VIDRA_*_TAG as the running service by docker-compose.prod.yml.
# Overriding the command here would silently change WHICH migrator runs, so the
# gate stays "the service binary's own exit code".
log "core schema (schema_migrations)"
# `|| mrc=$?` rather than `if ! ...` so the real migrator exit code survives
# (inside `if ! cmd`, $? is the status of the negation, i.e. always 0).
mrc=0; "${COMPOSE[@]}" run --rm migrate || mrc=$?
[ "$mrc" -eq 0 ] || die "CORE MIGRATION FAILED (exit $mrc). The stack has NOT been restarted; the previous release is still serving. See 'Migration failed mid-deploy' in deploy/README.md."

if [ "$EXTERNAL_POSTGRES" -eq 1 ]; then
  # The independent ledger read below is a `docker exec` into the bundled
  # postgres container, which does not exist here. The migrator's own exit code
  # (checked above) remains the gate; what is lost is only the second opinion.
  # Reproduce it by hand against the managed instance if you want it:
  #   psql "$DATABASE_URL" -c 'SELECT version, dirty FROM schema_migrations;'
  log "external Postgres — skipping the independent schema_migrations read (no bundled container to exec into)"
else
  PG_CID="$("${COMPOSE[@]}" ps -q postgres || true)"
  [ -n "$PG_CID" ] || die "postgres container missing during migration verification"
  # The expected version still comes from the FILENAMES in the vidra-core checkout,
  # which the pre-flight above pinned to VIDRA_CORE_TAG — the same tag the api
  # image (and therefore its embedded copy of these files) was built from, so the
  # two agree by construction. This is an independent second opinion on purpose:
  # reading it out of the migrator would only prove the migrator agrees with itself.
  # shellcheck disable=SC2012  # ls is deliberate: filenames are numeric by construction, and sort -n works correctly.
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
fi

log "search schema (vidra_search_migrations)"
src=0; "${COMPOSE[@]}" run --rm search-migrate || src=$?
[ "$src" -eq 0 ] || die "SEARCH MIGRATION FAILED (exit $src). The stack has NOT been restarted; the previous release is still serving. See 'Migration failed mid-deploy' in deploy/README.md."

step "4/6 start"
# --no-build is a guarantee, not an optimisation: the base compose file still
# carries the dev `build:` sections, and a droplet that starts compiling Go or
# running `next build` will run out of memory rather than deploy.
"${COMPOSE[@]}" up -d --no-build

step "5/6 reload Caddy"
# THE GAP THIS CLOSES: deploy/Caddyfile.local is a BIND MOUNT. Editing it (by
# hand, or by re-running `vidra setup`) changes the file the running container
# already has open, and `up -d` sees no change to the caddy service — same
# image, same config, same volumes — so it does not recreate it and the old
# configuration keeps serving. Nothing about that is visible in the deploy
# output, which is what makes it worth an explicit step.
#
# `caddy reload` is a graceful, zero-downtime config swap through the local
# admin API; on a config the running Caddy already has, it is a no-op.
#
# The retry loop is for the OTHER order of events: on a first deploy (or after
# `down`), the container was created seconds ago by the `up -d` above and its
# admin endpoint is not listening yet. Five attempts at 2s covers that without
# turning a wedged Caddy into a five-minute wait.
#
# Exhausting those five attempts is FATAL. It used to be a warning, on the
# reasoning that the stack was up and the previous config was still serving —
# but that reasoning does not survive the two cases that actually produce this
# failure. On a FIRST deploy there is no previous config: caddy is not running
# at all (or is crash-looping on a Caddyfile.local it cannot adapt), and the
# site is down. On a subsequent deploy it means the edge is still routing the
# PREVIOUS release's configuration while the operator's shell reported success.
# Both are exactly the "green deploy, dead site" outcome this script exists to
# prevent, and neither is visible in the loopback probes below — they connect
# to api and frontend directly, behind Caddy.
reload_caddy() {
  local attempt
  for attempt in 1 2 3 4 5; do
    if "${COMPOSE[@]}" exec -T caddy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null 2>&1; then
      log "caddy reloaded (attempt $attempt)"
      return 0
    fi
    sleep 2
  done
  return 1
}
if ! reload_caddy; then
  "${COMPOSE[@]}" logs --tail=50 caddy >&2 || true
  die "caddy reload did not succeed after 5 attempts, so the TLS edge is NOT serving deploy/Caddyfile.local — either it never started, or it is still serving the PREVIOUS configuration. The application containers are up and the database has already been migrated; nothing was rolled back. Caddy's last 50 log lines are above. Reproduce the adapt failure by hand:
  ./deploy/compose.sh exec caddy caddy validate --config /etc/caddy/Caddyfile
  ./deploy/compose.sh logs --tail=50 caddy
  ./deploy/compose.sh restart caddy
then re-run ./deploy/deploy.sh — it is idempotent."
fi

step "6/6 health probes"
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

# EDGE PROBE. THE GAP THIS CLOSES: both probes above connect to 127.0.0.1 —
# INSIDE the box, to the loopback publishes, BYPASSING Caddy completely. They
# pass in full while the site serves nothing: a Caddyfile.local that adapts but
# reverse_proxies to the wrong upstream, a certificate that never issued, a
# caddy container that exited, a site address that does not match the hostname
# users type. Combined with a reload failure that was only ever a warning, a
# deploy could exit 0 with the public site dark. This is the one probe that
# answers the question the operator actually has.
#
# --resolve pins the connection to THIS host, so it tests the edge that was just
# deployed rather than whatever the public A record resolves to right now (it
# may still be propagating, or point at a proxy). /healthz is routed to the api
# by deploy/Caddyfile's @api matcher, so a 200 proves TLS termination, the site
# address, and one reverse_proxy hop all work.
#
# -k because the certificate is NOT what is under test and all three
# VIDRA_TLS_MODE values have to pass here: `internal` issues from Caddy's own
# CA and `acme-staging` from a deliberately untrusted root, neither of which
# curl has any reason to trust. A genuinely broken chain still fails loudly in a
# browser; this asks only "does the edge answer for this domain".
#
# The probe does not trigger extra ACME orders — Caddy manages issuance on its
# own schedule — so retrying it costs nothing against Let's Encrypt's limits.
EDGE_HOST="$(url_host "$(env_get PUBLIC_BASE_URL '')")"
probe_edge() {
  local host="$1" deadline
  deadline=$(( $(date +%s) + EDGE_TIMEOUT ))
  log "waiting up to ${EDGE_TIMEOUT}s for the TLS edge at https://${host}/healthz (pinned to 127.0.0.1)"
  until curl -fsSk -m 5 -o /dev/null --resolve "${host}:443:127.0.0.1" "https://${host}/healthz"; do
    if [ "$(date +%s)" -ge "$deadline" ]; then
      printf '[deploy] ERROR: the TLS edge never answered for %s. The api and frontend are healthy on the loopback, so this is Caddy: a Caddyfile.local that adapts but routes wrong, a certificate that never issued, or a container that is not running. Recent caddy logs:\n' "$host" >&2
      "${COMPOSE[@]}" logs --tail=50 caddy >&2 || true
      printf '[deploy] Check by hand:\n  ./deploy/compose.sh ps caddy\n  ./deploy/compose.sh exec caddy caddy validate --config /etc/caddy/Caddyfile\n  ./deploy/compose.sh logs --tail=100 caddy\n' >&2
      return 1
    fi
    sleep 3
  done
  log "TLS edge OK"
}
if [ -n "$EDGE_HOST" ]; then
  probe_edge "$EDGE_HOST" || rc=1
else
  # Unreachable in practice: require_real_domain and the DNS preflight both die
  # on an empty PUBLIC_BASE_URL long before this. Kept so a future edit to those
  # gates cannot turn this probe into a silent no-op.
  printf '[deploy] WARNING: PUBLIC_BASE_URL is empty, so the TLS edge was NOT probed. The checks above only cover the loopback ports, behind Caddy.\n' >&2
fi

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
