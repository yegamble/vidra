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
#   edge_profile           prints `edge` unless VIDRA_TLS_MODE=external
#   vidra_compose_chain    sets COMPOSE=(...), EXTERNAL_POSTGRES, EXTERNAL_REDIS
#   env_snapshot FILE ROOT keeps 10 timestamped generations of an env file

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

# edge_profile — prints `edge` when this deployment runs Vidra's own Caddy, and
# nothing when it does not. Called unquoted inside the profile loop below, so
# "nothing" contributes no word at all.
#
# WHY THE ENGINE DECIDES AND NOT THE OPERATOR: docker-compose.prod.yml's caddy
# service is on the `edge` profile, and if that profile had to be typed into
# VIDRA_COMPOSE_PROFILES then every env file written before this change — every
# one in existence — would silently stop starting the TLS terminator on its next
# deploy. The whole site, gone, because a compose file grew a profile. So the
# rule is inverted: caddy is ON unless the env file says somebody else is
# terminating TLS.
#
# `external` is the ONLY mode that turns it off. plain-http still runs Caddy (as
# a plain-HTTP site — one managed front door, whatever the scheme), and an unset
# or unrecognised value keeps it too: an operator who typos the mode gets a
# refusal from deploy.sh's mode switch, not a silently edge-less stack.
edge_profile() {
  case "$(env_get VIDRA_TLS_MODE acme)" in
    external) ;;
    *) printf 'edge' ;;
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
# the command line these scripts used before there were any, plus the `edge`
# profile that now carries the caddy service (see edge_profile above; the
# service used to have no profile, so this is the same set of containers):
#   docker compose -f docker-compose.yml -f docker-compose.prod.yml \
#     --env-file "$ENV_FILE" --profile core --profile frontend --profile edge
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
  for profile in $(env_get VIDRA_COMPOSE_PROFILES "core frontend") $(env_get EXTRA_COMPOSE_PROFILES "") $(edge_profile); do
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

# env_snapshot <env-file> <repo-root> — copy the env file into
# <repo-root>/backups/env-history/<basename>.<UTC %Y%m%dT%H%M%SZ> and keep the
# ten newest snapshots OF THAT BASENAME.
#
# WHY A DIRECTORY AND NOT ANOTHER .bak: `cp "$ENV_FILE" "$ENV_FILE.bak"` records
# exactly ONE generation, and it is overwritten by the next run. Two rollbacks in
# an incident — v0.3.0 is bad, roll to v0.2.1, that is bad too, roll to v0.2.0 —
# and the .bak now holds v0.2.1, the state nobody wants to return to. The tags
# you were serving before the incident started are gone, and they are exactly
# what the incident notes need. Ten generations is cheap (an env file is a couple
# of kilobytes) and covers any plausible run of rollbacks.
#
# THE PATH SHAPE IS A CROSS-LANGUAGE CONTRACT. `vidra update` writes the same
# history from Go; both must agree on the directory, the separator and the stamp
# format or the two halves prune each other's snapshots (or, worse, neither
# prunes and the directory grows without bound). Change it in one place only by
# changing it in both.
#
# The stamp is UTC and fixed-width for the same reason backup.sh's is: these
# names sort lexicographically exactly as they sort chronologically, so the
# retention pass below needs no stat(1), no `date -d` and no mktime().
#
# 0700 on the directory and 0600 on each file because these ARE the secrets —
# JWT_SECRET, POSTGRES_PASSWORD, MFA_KEY_KEK. `cat >` under `umask 077`, not
# `cp` then `chmod`: cp creates the destination with the SOURCE's mode (so a
# hand-created 0644 env file would be copied 0644), and a later chmod leaves a
# window, however short, in which the whole host can read the key-encryption key.
#
# shellcheck disable=SC2154  # log() is the caller's, per the contract above.
env_snapshot() {
  local src="$1" root="$2" base dir stamp dest keep stale
  base="$(basename "$src")"
  dir="$root/backups/env-history"
  keep="${VIDRA_ENV_HISTORY_KEEP:-10}"

  mkdir -p "$dir"
  chmod 700 "$dir"
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  dest="$dir/${base}.${stamp}"
  ( umask 077; cat "$src" > "$dest" )
  log "env snapshot: backups/env-history/${base}.${stamp}"

  # Only this basename's own snapshots, and only names whose suffix really is a
  # stamp: env/staging.env and env/production.env share the directory, and
  # `production.env.*` would otherwise also sweep a hypothetical
  # `production.env.old.<stamp>`. The character classes are spelled out instead
  # of using {8}/{6} because mawk — Ubuntu's default awk, which is what runs this
  # on a droplet — has not always supported interval expressions.
  stale="$(
    { ls -1 -- "$dir" 2>/dev/null || true; } | awk -v b="$base" '
      {
        n = length(b)
        if (substr($0, 1, n + 1) != b ".") next
        s = substr($0, n + 2)
        if (s ~ /^[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]T[0-9][0-9][0-9][0-9][0-9][0-9]Z$/) print
      }
    ' | sort -r | tail -n +"$((keep + 1))"
  )"
  if [ -n "$stale" ]; then
    printf '%s\n' "$stale" | while IFS= read -r f; do
      log "pruning env snapshot $f"
      rm -f -- "$dir/$f"
    done
  fi
}
