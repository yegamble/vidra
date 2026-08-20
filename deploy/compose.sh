#!/usr/bin/env bash
#
# `docker compose` against THE production chain — the same one deploy.sh,
# rollback.sh, restore.sh and backup.sh assemble, read out of the env file.
#
#   ./deploy/compose.sh config -q
#   ./deploy/compose.sh ps
#   ./deploy/compose.sh logs -f --tail=100 api
#   ./deploy/compose.sh down
#   ENV_FILE=env/staging.env ./deploy/compose.sh exec caddy caddy validate --config /etc/caddy/Caddyfile
#
# WHY THIS EXISTS: every ad-hoc `docker compose -f docker-compose.yml -f
# docker-compose.prod.yml --profile core --profile frontend ...` typed into a
# runbook is a sixth copy of the chain, and a copy is a chance to address a
# DIFFERENT project than the deploy scripts do. `make prod-config`'s copy had
# already drifted: it hardcoded core+frontend, never applied the
# external-Postgres/-Redis overlays, and so reported "renders cleanly" for a
# managed-datastore env file while validating the bundled postgres — a green
# check for a stack nobody was running. Use this instead of exporting $COMPOSE.
#
# The explicit -f chain deliberately DISABLES auto-loading of
# docker-compose.override.yml, which carries dev defaults such as
# RATE_LIMIT_ENABLED=false. See deploy/README.md.
#
# This wrapper does NOT gate anything: no compose-version check, no migrator-tag
# floor, no Caddyfile checks. It is for reading and for stopping, and the
# gating scripts are for changing. `up -d` through here skips every one of
# those refusals — use ./deploy/deploy.sh.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

ENV_FILE="${ENV_FILE:-env/production.env}"

# Both on stderr, unlike the other scripts: stdout here belongs to docker
# compose, and `./deploy/compose.sh config | yq ...` must not find a log line
# in the middle of the YAML.
log() { printf '[compose] %s\n' "$*" >&2; }
die() { printf '[compose] ERROR: %s\n' "$*" >&2; exit 1; }

[ $# -gt 0 ] || die "usage: $0 <docker compose args...>   e.g. $0 config -q | $0 ps | $0 logs -f"
[ -f "$ENV_FILE" ] || die "env file not found: $ENV_FILE (cp env/production.env.example env/production.env)"

# shellcheck source=deploy/lib.sh
. "$REPO_ROOT/deploy/lib.sh"

# Sets COMPOSE, EXTERNAL_POSTGRES and EXTERNAL_REDIS.
vidra_compose_chain

exec "${COMPOSE[@]}" "$@"
