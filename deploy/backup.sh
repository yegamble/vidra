#!/usr/bin/env bash
#
# Nightly PostgreSQL + configuration backup for a single-host Vidra deployment.
#
#   ./deploy/backup.sh
#   ENV_FILE=env/staging.env ./deploy/backup.sh
#
# Produces TWO files per run, sharing one UTC stamp:
#
#   backups/vidra-<stamp>.dump.gz          the database, custom-format (-Fc),
#                                          which is what pg_restore's parallel
#                                          (-j) restore requires; a plain SQL
#                                          dump cannot be restored in parallel
#                                          and takes far longer on real data.
#   backups/vidra-config-<stamp>.tar.gz    $ENV_FILE + deploy/Caddyfile.local,
#                                          stored repo-relative so recovery is
#                                          `tar -xzf … -C /opt/vidra`.
#
# ONE dump covers BOTH services: vidra-search shares the core database and lives
# in its own `search` schema, so a database-wide pg_dump already contains it.
# Redis is deliberately NOT backed up — it holds only cache, rate-limit counters
# and dedup keys, and may be flushed at any time.
#
# What this script does NOT back up: media. With STORAGE_BACKEND=s3 use the
# object store's own versioning/replication; with `local`, snapshot the
# media_data volume on the same cadence so DB rows and files stay consistent —
# see "Local media volume snapshots" in deploy/README.md for the one-liner.
#
# Because the media is captured on its own schedule, the dump and the store are
# NOT a matched pair: this dump is a snapshot at T and the bucket is whatever it
# is at T+n. Two things close that loop rather than a knob here — the media-GC
# safety rails (which refuse to delete from a store this install has not been
# shown to own, and refuse a sweep that finds an implausible share to be
# garbage), and `verify-blobs`, which deploy/restore.sh runs automatically after
# a restore to name every row whose object is not there. Read "S3-canonical
# deployments" in deploy/README.md before choosing a bucket's durability
# settings: versioning without a non-current-version expiry rule is the trap
# that quietly doubles a media bill forever.
#
# Safe to re-run at any time, and safe to run while the stack is serving traffic
# (pg_dump takes a consistent MVCC snapshot; it does not lock writers out).
#
# Optional off-site copy and dead-man's-switch ping are both opt-in and are
# skipped silently-but-loudly (a log line) when unconfigured — see the
# BACKUP_RCLONE_REMOTE / BACKUP_S3_URI / HEALTHCHECKS_URL blocks below.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

ENV_FILE="${ENV_FILE:-env/production.env}"
BACKUP_DIR="${BACKUP_DIR:-$REPO_ROOT/backups}"
# Retention. "14 daily + 8 weekly" as documented in deploy/README.md: every dump
# taken on the 14 most recent days that have a dump, plus the newest dump in each
# of the 8 most recent 7-day buckets.
KEEP_DAILY="${KEEP_DAILY:-14}"
KEEP_WEEKLY="${KEEP_WEEKLY:-8}"

log()  { printf '[backup] %s\n' "$*"; }
die()  { printf '[backup] ERROR: %s\n' "$*" >&2; exit 1; }

[ -f "$ENV_FILE" ] || die "env file not found: $ENV_FILE (cp env/production.env.example env/production.env)"

# env_get, is_true and the compose chain live in deploy/lib.sh — every script
# that addresses the running stack must assemble the SAME project. Sourced here,
# after log/die and ENV_FILE, which is the contract lib.sh documents.
# shellcheck source=deploy/lib.sh
. "$REPO_ROOT/deploy/lib.sh"

PGUSER="$(env_get POSTGRES_USER vidra)"
PGDB="$(env_get POSTGRES_DB vidra)"

# Sets COMPOSE, EXTERNAL_POSTGRES and EXTERNAL_REDIS.
vidra_compose_chain

# This script dumps by `docker exec`-ing pg_dump inside the BUNDLED postgres
# container. With VIDRA_EXTERNAL_POSTGRES=true there is no such container, so
# refuse in one sentence rather than fail at `ps -q postgres` with a message
# about a stack that is not running.
#
# Deliberately placed BEFORE the healthchecks.io trap and the /start ping: a
# refusal is not a backup attempt, so the dead-man's switch stays silent and
# the "no ping since <t>" alert fires — which is the correct signal, because
# this host is genuinely taking no backups from here.
if [ "$EXTERNAL_POSTGRES" -eq 1 ]; then
  die "VIDRA_EXTERNAL_POSTGRES=true in $ENV_FILE — external Postgres: use your provider's backup/restore (automated backups + point-in-time recovery), and point HEALTHCHECKS_URL at that schedule instead of this script. Backing up a managed database is deliberately not reimplemented here. Nothing was written."
fi

# Dead-man's switch. A backup that never runs is the failure mode monitoring
# usually misses, so the ping is what alerts — not the script. Configure
# HEALTHCHECKS_URL=https://hc-ping.com/<uuid> (healthchecks.io, Better Stack,
# anything with the same /start + /fail convention).
HC_URL="${HEALTHCHECKS_URL:-}"
hc_ping() {
  [ -n "$HC_URL" ] || return 0
  curl -fsS -m 10 --retry 3 -o /dev/null "${HC_URL}${1:-}" || true
}
# Fires on ANY non-zero exit below, including a failed pg_dump or a failed
# integrity check, so a broken backup pages instead of silently succeeding.
# Written as an explicit `if` rather than `[ ... ] && hc_ping /fail`: a
# short-circuited AND-list is itself a failing command, and how `set -e` treats
# that inside a trap body varies between shell versions.
# shellcheck disable=SC2154  # rc IS assigned — by the first statement of this very trap body.
trap 'rc=$?; if [ "$rc" -ne 0 ]; then hc_ping /fail; fi; exit "$rc"' EXIT

hc_ping /start

mkdir -p "$BACKUP_DIR"

PG_CID="$("${COMPOSE[@]}" ps -q postgres || true)"
[ -n "$PG_CID" ] || die "the postgres service is not running (start the stack first, or check ENV_FILE=$ENV_FILE)"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="$BACKUP_DIR/vidra-${STAMP}.dump.gz"
TMP="${OUT}.part"

log "dumping database '${PGDB}' as '${PGUSER}' from container ${PG_CID:0:12}"
# Written to .part first and renamed only after the integrity check passes, so a
# half-written file can never be mistaken for a good backup by restore.sh or by
# the retention pass below. `set -o pipefail` makes a pg_dump failure fail the
# whole pipeline even though gzip would exit 0.
docker exec -i "$PG_CID" pg_dump -U "$PGUSER" -Fc "$PGDB" | gzip -c > "$TMP"

# Integrity check: pg_restore -l parses the archive's table of contents. It
# catches truncation and corruption for the price of a few hundred milliseconds,
# and it is the difference between "we have 8 weeks of backups" and "we have 8
# weeks of unusable files". Reuses the container's pg_restore so the client
# version always matches the server.
log "verifying archive"
gzip -dc "$TMP" | docker exec -i "$PG_CID" pg_restore -l > /dev/null \
  || die "archive failed pg_restore -l — NOT keeping $TMP"

mv "$TMP" "$OUT"
SIZE="$(du -h "$OUT" | cut -f1)"
log "wrote $OUT ($SIZE)"

# --- configuration archive -----------------------------------------------------
# The dump is only half a recovery. Restoring it needs the env file — every
# secret, every image tag, and MFA_KEY_KEK, which is the key-encryption key for
# stored TOTP secrets and is generated once and never derivable again — plus
# deploy/Caddyfile.local, which `vidra setup` generates and .gitignore keeps out
# of the repo on purpose. Before this, an off-site bucket full of dumps survived
# the host and the configuration needed to read them did not: a rebuild meant
# re-running setup, minting a NEW MFA_KEY_KEK, and discovering that every
# restored user's second factor was undecryptable.
#
# Members are stored RELATIVE TO THE REPO ROOT so recovery is one command with no
# path surgery — `tar -xzf backups/vidra-config-<stamp>.tar.gz -C /opt/vidra`
# lands env/production.env and deploy/Caddyfile.local exactly where the compose
# chain looks for them.
#
# Same STAMP as the dump, deliberately: the pair is one point in time, they
# retain into the same daily/weekly buckets, and an operator matching a config
# archive to a dump does it by reading, not by guessing at mtimes.
CONFIG_OUT="$BACKUP_DIR/vidra-config-${STAMP}.tar.gz"
CONFIG_MEMBERS=()
CONFIG_MISSING=()

# The env file may be given as an absolute path. tar members have to be
# repo-relative for the extract command above to be true, so an env file outside
# the checkout is named as UNCOVERED rather than silently stored under a path
# that would extract to the wrong place.
if [ -f "$REPO_ROOT/$ENV_FILE" ]; then
  CONFIG_MEMBERS+=("$ENV_FILE")
elif [ "${ENV_FILE#"$REPO_ROOT"/}" != "$ENV_FILE" ]; then
  CONFIG_MEMBERS+=("${ENV_FILE#"$REPO_ROOT"/}")
else
  CONFIG_MISSING+=("$ENV_FILE (outside $REPO_ROOT — cannot be stored repo-relative)")
fi

if [ -f "$REPO_ROOT/deploy/Caddyfile.local" ]; then
  CONFIG_MEMBERS+=(deploy/Caddyfile.local)
else
  CONFIG_MISSING+=("deploy/Caddyfile.local (not generated yet — run 'vidra setup')")
fi

if [ ${#CONFIG_MEMBERS[@]} -eq 0 ]; then
  log "WARNING: no configuration file could be archived: ${CONFIG_MISSING[*]}"
  CONFIG_OUT=""
else
  if [ ${#CONFIG_MISSING[@]} -gt 0 ]; then
    log "WARNING: config archive is INCOMPLETE, missing: ${CONFIG_MISSING[*]}"
  fi
  CONFIG_TMP="${CONFIG_OUT}.part"
  # `umask 077` around the create, not chmod afterwards: this archive contains
  # JWT_SECRET and MFA_KEY_KEK in plaintext, and a chmod leaves a window in which
  # every account on the host can read them. The .part + verify + rename dance is
  # the dump's, for the dump's reason — a half-written archive must never be
  # mistaken for a usable one.
  ( umask 077; tar -czf "$CONFIG_TMP" -C "$REPO_ROOT" "${CONFIG_MEMBERS[@]}" )
  tar -tzf "$CONFIG_TMP" > /dev/null \
    || die "config archive failed tar -tzf — NOT keeping $CONFIG_TMP"
  chmod 600 "$CONFIG_TMP"
  mv "$CONFIG_TMP" "$CONFIG_OUT"
  log "wrote $CONFIG_OUT ($(du -h "$CONFIG_OUT" | cut -f1)): ${CONFIG_MEMBERS[*]}"
fi

# --- optional off-site copy ----------------------------------------------------
# A dump that only exists on the droplet dies with the droplet. Put it in a
# DIFFERENT region from the media Space so one regional incident cannot take both.
# Both paths are opt-in: configure one, or neither.
#
# The config archive rides along on the SAME target. Sending the dump off-site
# and leaving its configuration on the dead host is the exact failure the archive
# exists to close, so there is deliberately no separate knob to get that wrong.
OFFSITE=("$OUT")
if [ -n "$CONFIG_OUT" ]; then
  OFFSITE+=("$CONFIG_OUT")
fi

if [ -n "${BACKUP_RCLONE_REMOTE:-}" ]; then
  if command -v rclone >/dev/null 2>&1; then
    for f in "${OFFSITE[@]}"; do
      log "uploading $(basename "$f") to rclone remote ${BACKUP_RCLONE_REMOTE}"
      rclone copyto "$f" "${BACKUP_RCLONE_REMOTE%/}/$(basename "$f")"
    done
  else
    die "BACKUP_RCLONE_REMOTE is set but rclone is not installed"
  fi
elif [ -n "${BACKUP_S3_URI:-}" ]; then
  if command -v aws >/dev/null 2>&1; then
    for f in "${OFFSITE[@]}"; do
      log "uploading $(basename "$f") to ${BACKUP_S3_URI}"
      # BACKUP_S3_ENDPOINT is required for DO Spaces / MinIO and must include the
      # scheme here (unlike the application's STORAGE_S3_ENDPOINT, which must not).
      aws ${BACKUP_S3_ENDPOINT:+--endpoint-url "$BACKUP_S3_ENDPOINT"} \
        s3 cp "$f" "${BACKUP_S3_URI%/}/$(basename "$f")"
    done
  else
    die "BACKUP_S3_URI is set but the aws CLI is not installed"
  fi
else
  log "no off-site target configured (set BACKUP_RCLONE_REMOTE or BACKUP_S3_URI) — LOCAL COPY ONLY"
fi

# --- retention -----------------------------------------------------------------
# prune_generation <label> <stamp-offset> <file>... — apply the 14-daily +
# 8-weekly policy to ONE family of generated filenames. Called once per family
# (dumps, config archives) rather than forked into two awk programs: two copies
# of a bucketing rule drift, and a retention rule that keeps 8 weeks of dumps
# next to 3 weeks of the configuration needed to restore them is a recovery
# that fails at exactly the moment it is being relied on.
#
# <stamp-offset> is the 1-based index of the UTC stamp's first character in the
# basename, which is all that differs between the families:
#   vidra-YYYYMMDDTHHMMSSZ.dump.gz            -> 7   ("vidra-"        is 6)
#   vidra-config-YYYYMMDDTHHMMSSZ.tar.gz      -> 14  ("vidra-config-" is 13)
#
# Newest-first listing; the timestamp format sorts lexicographically the same way
# it sorts chronologically, so no stat(1) portability problems.
#
# The week bucket is computed as a Julian day number divided by 7. Deliberately
# pure arithmetic: `date -d` is GNU-only and mawk (Ubuntu's default awk) has no
# mktime(), so anything else would be silently wrong on one platform or the other.
prune_generation() {
  local label="$1" off="$2" delete_list
  shift 2
  delete_list="$(
    # shellcheck disable=SC2012  # ls is deliberate: these names are generated by this
    # script, so they are alphanumeric by construction and `sort -r` on them is exactly
    # reverse-chronological. find(1) would need -printf (GNU-only) to sort the same way.
    # `|| true` because an unmatched glob arrives here as a literal and must be an empty
    # list, not a failed pipeline under `set -o pipefail`.
    { ls -1 -- "$@" 2>/dev/null || true; } | sort -r | awk -v kd="$KEEP_DAILY" -v kw="$KEEP_WEEKLY" -v off="$off" '
      function jdn(y, m, d,   a) {
        a = int((m - 14) / 12)
        return int((1461 * (y + 4800 + a)) / 4) \
             + int((367 * (m - 2 - 12 * a)) / 12) \
             - int((3 * int((y + 4900 + a) / 100)) / 4) \
             + d - 32075
      }
      {
        n = split($0, parts, "/"); f = parts[n]
        y = substr(f, off, 4) + 0; mo = substr(f, off + 4, 2) + 0; da = substr(f, off + 6, 2) + 0
        if (y == 0) next                      # unrecognised name: never delete it
        day  = substr(f, off, 8)
        week = int(jdn(y, mo, da) / 7)

        keep = 0
        if (!(day in seenDay)) { seenDay[day] = ++nDay }
        if (seenDay[day] <= kd) keep = 1      # every file on the newest kd days

        if (!(week in seenWeek)) {            # newest file of the newest kw weeks
          seenWeek[week] = ++nWeek
          if (nWeek <= kw) keep = 1
        }

        if (!keep) print $0
      }
    '
  )"
  if [ -n "$delete_list" ]; then
    printf '%s\n' "$delete_list" | while IFS= read -r f; do
      log "pruning $(basename "$f")"
      rm -f -- "$f"
    done
  else
    log "nothing to prune among the ${label}"
  fi
}

log "pruning: keeping ${KEEP_DAILY} daily + ${KEEP_WEEKLY} weekly"
prune_generation "database dumps"   7  "$BACKUP_DIR"/vidra-*.dump.gz
prune_generation "config archives" 14  "$BACKUP_DIR"/vidra-config-*.tar.gz

# --- success marker ------------------------------------------------------------
# Machine-readable "when did a backup last actually succeed". Point a file-age
# check or the RUNBOOK at this rather than at the directory listing, which also
# contains failures from before the .part rename.
#
# THE FORMAT IS `<RFC3339Z> <basename-of-dump>` AND IT IS PARSED ELSEWHERE:
# vidra-core's doctor (internal/doctor/checks_state.go) splits on the first
# space and time.Parse's field one as RFC3339, failing back to the file's mtime,
# to decide whether the newest backup is inside its 26-hour window. The config
# archive deliberately does NOT change this line — it gets its own log line
# instead. A second filename here would either be swallowed by that split (a
# silent no-op) or, if the format were "improved" to a list, break an age check
# whose whole job is to be the last thing that still works when everything else
# has stopped reporting.
printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$(basename "$OUT")" > "$BACKUP_DIR/last_success"

hc_ping
if [ -n "$CONFIG_OUT" ]; then
  log "done — database $(basename "$OUT"), config $(basename "$CONFIG_OUT")"
else
  log "done — database $(basename "$OUT"); NO config archive (see the warning above)"
fi
