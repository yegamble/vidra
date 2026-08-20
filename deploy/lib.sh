#!/usr/bin/env bash
# shellcheck shell=bash
#
# deploy/lib.sh — the parts of the production compose invocation that every
# script touching the running stack MUST agree on. SOURCED, never executed:
# `. "$REPO_ROOT/deploy/lib.sh"`.
#
# WHY THIS FILE EXISTS: deploy.sh, rollback.sh, restore.sh, backup.sh and
# deploy/compose.sh all address the SAME docker-compose project. If two of them
# assemble a different `-f` chain or a different `--profile` set, `ps -q
# postgres` and `up -d` resolve against different renderings of that project —
# `backup.sh` dumps a database `deploy.sh` is not migrating, or `prod-config`
# validates a stack nobody runs. That is not a theoretical drift: this block
# lived as five copies, kept in step by a comment asking future editors to paste
# carefully, and the fifth (the Makefile's PROD_COMPOSE) had already fallen
# behind — it hardcoded `--profile core --profile frontend`, ignored both
# external-datastore overlays, and reported "renders cleanly" for an
# external-Postgres env file while rendering the BUNDLED postgres.
#
# CONTRACT FOR THE CALLER (all five already satisfy it, source this after them):
#   * ENV_FILE  — set, and the file exists. Read at CALL time, not source time.
#   * log()     — defined. The messages below carry the caller's own [tag]
#                 prefix on purpose, so a line about external datastores reads
#                 as `[backup]` or `[deploy]` rather than as coming from here.
#
# PROVIDES
#   env_get KEY [DEFAULT]  value from the process env, else $ENV_FILE, else DEFAULT
#   is_true VALUE          exit 0 for the spellings of "yes" an operator types
#   vidra_compose_chain    sets COMPOSE=(...), EXTERNAL_POSTGRES, EXTERNAL_REDIS

# Reads KEY from the env file WITHOUT sourcing it — that file is operator-edited
# and holds secrets; `source`ing it would execute whatever is in there. A real
# exported environment variable of the same name wins, so
# `POSTGRES_DB=other ./deploy/backup.sh` works for one-off runs.
#
# shellcheck disable=SC2154  # ENV_FILE is the caller's, per the contract above.
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

# `is_true` rather than `= true` because operators type true/yes/1
# interchangeably and a typo silently starts a second, empty database next to
# the managed one.
#
# THIS WORD LIST IS THE CONTRACT between the shell here and vidra-core's setup
# engine. The engine only ever WRITES literal `true`/`false`; this list is the
# wider set it must be safe to READ. Do not narrow it — an env file hand-edited
# to `yes` predates the engine and still has to work.
is_true() {
  case "$1" in
    true|TRUE|True|yes|YES|Yes|1|on|ON|On) return 0 ;;
    *) return 1 ;;
  esac
}

# vidra_compose_chain — build the compose invocation from the env file rather
# than hardcoding it, so `vidra setup` can change the SHAPE of the stack
# (external datastores, extra profiles) without editing any of these scripts.
#
# Sets three globals, deliberately: the callers use `"${COMPOSE[@]}"` dozens of
# times and branch on the two flags (backup.sh and restore.sh refuse outright
# when Postgres is managed elsewhere).
#
# An env file that predates these keys — or sets them empty — produces exactly
# the command line these scripts used before there were any:
#   docker compose -f docker-compose.yml -f docker-compose.prod.yml \
#     --env-file "$ENV_FILE" --profile core --profile frontend
vidra_compose_chain() {
  local profile seen_profiles=""

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
  # host renders the same chain.
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

  # Profiles: VIDRA_COMPOSE_PROFILES (default `core frontend` — exactly what
  # these scripts hardcoded before) plus EXTRA_COMPOSE_PROFILES, which stays a
  # separate key because `vidra setup` rewrites the first and the operator owns
  # the second. Both are space-separated lists, so the command substitutions are
  # deliberately unquoted. Duplicates are collapsed in first-seen order: passing
  # --profile core twice changes nothing, but it makes two `ps` outputs annoying
  # to compare.
  # shellcheck disable=SC2046  # word splitting is the point: these are lists.
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
}
