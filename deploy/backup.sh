#!/usr/bin/env bash
#
# Nightly PostgreSQL backup for a single-host Vidra deployment.
#
#   ./deploy/backup.sh
#   ENV_FILE=env/staging.env ./deploy/backup.sh
#
# Produces backups/vidra-<UTC timestamp>.dump.gz — a custom-format (-Fc) dump,
# which is what pg_restore's parallel (-j) restore requires; a plain SQL dump
# cannot be restored in parallel and takes far longer on a real dataset.
#
# ONE dump covers BOTH services: vidra-search shares the core database and lives
# in its own `search` schema, so a database-wide pg_dump already contains it.
# Redis is deliberately NOT backed up — it holds only cache, rate-limit counters
# and dedup keys, and may be flushed at any time.
#
# What this script does NOT back up: media. With STORAGE_BACKEND=s3 use the
# object store's own versioning/replication; with `local`, snapshot the
# media_data volume on the same cadence so DB rows and files stay consistent.
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

# Reads KEY from the env file WITHOUT sourcing it — that file is operator-edited
# and holds secrets; `source`ing it would execute whatever is in there. A real
# exported environment variable of the same name wins, so
# `POSTGRES_DB=other ./deploy/backup.sh` works for one-off runs.
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

# The same explicit -f chain deploy.sh uses. It must match, or `ps -q` resolves
# against a different rendering of the stack. `--profile core` is what makes the
# postgres service visible to `ps`.
COMPOSE=(docker compose
  -f docker-compose.yml
  -f docker-compose.prod.yml
  --env-file "$ENV_FILE"
  --profile core --profile frontend)

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

# --- optional off-site copy ----------------------------------------------------
# A dump that only exists on the droplet dies with the droplet. Put it in a
# DIFFERENT region from the media Space so one regional incident cannot take both.
# Both paths are opt-in: configure one, or neither.
if [ -n "${BACKUP_RCLONE_REMOTE:-}" ]; then
  if command -v rclone >/dev/null 2>&1; then
    log "uploading to rclone remote ${BACKUP_RCLONE_REMOTE}"
    rclone copyto "$OUT" "${BACKUP_RCLONE_REMOTE%/}/$(basename "$OUT")"
  else
    die "BACKUP_RCLONE_REMOTE is set but rclone is not installed"
  fi
elif [ -n "${BACKUP_S3_URI:-}" ]; then
  if command -v aws >/dev/null 2>&1; then
    log "uploading to ${BACKUP_S3_URI}"
    # BACKUP_S3_ENDPOINT is required for DO Spaces / MinIO and must include the
    # scheme here (unlike the application's STORAGE_S3_ENDPOINT, which must not).
    aws ${BACKUP_S3_ENDPOINT:+--endpoint-url "$BACKUP_S3_ENDPOINT"} \
      s3 cp "$OUT" "${BACKUP_S3_URI%/}/$(basename "$OUT")"
  else
    die "BACKUP_S3_URI is set but the aws CLI is not installed"
  fi
else
  log "no off-site target configured (set BACKUP_RCLONE_REMOTE or BACKUP_S3_URI) — LOCAL COPY ONLY"
fi

# --- retention -----------------------------------------------------------------
# Newest-first listing; the timestamp format sorts lexicographically the same way
# it sorts chronologically, so no stat(1) portability problems.
#
# The week bucket is computed as a Julian day number divided by 7. Deliberately
# pure arithmetic: `date -d` is GNU-only and mawk (Ubuntu's default awk) has no
# mktime(), so anything else would be silently wrong on one platform or the other.
log "pruning: keeping ${KEEP_DAILY} daily + ${KEEP_WEEKLY} weekly"
DELETE_LIST="$(
  # shellcheck disable=SC2012  # ls is deliberate: these names are generated by this
  # script (vidra-<UTC stamp>.dump.gz), so they are alphanumeric by construction, and
  # `sort -r` on them is exactly reverse-chronological. find(1) would need -printf
  # (GNU-only) to sort the same way.
  ls -1 "$BACKUP_DIR"/vidra-*.dump.gz 2>/dev/null | sort -r | awk -v kd="$KEEP_DAILY" -v kw="$KEEP_WEEKLY" '
    function jdn(y, m, d,   a) {
      a = int((m - 14) / 12)
      return int((1461 * (y + 4800 + a)) / 4) \
           + int((367 * (m - 2 - 12 * a)) / 12) \
           - int((3 * int((y + 4900 + a) / 100)) / 4) \
           + d - 32075
    }
    {
      n = split($0, parts, "/"); f = parts[n]
      # f = vidra-YYYYMMDDTHHMMSSZ.dump.gz
      y = substr(f, 7, 4) + 0; mo = substr(f, 11, 2) + 0; da = substr(f, 13, 2) + 0
      if (y == 0) next                      # unrecognised name: never delete it
      day  = substr(f, 7, 8)
      week = int(jdn(y, mo, da) / 7)

      keep = 0
      if (!(day in seenDay)) { seenDay[day] = ++nDay }
      if (seenDay[day] <= kd) keep = 1      # every dump on the newest kd days

      if (!(week in seenWeek)) {            # newest dump of the newest kw weeks
        seenWeek[week] = ++nWeek
        if (nWeek <= kw) keep = 1
      }

      if (!keep) print $0
    }
  '
)"
if [ -n "$DELETE_LIST" ]; then
  printf '%s\n' "$DELETE_LIST" | while IFS= read -r f; do
    log "pruning $(basename "$f")"
    rm -f -- "$f"
  done
else
  log "nothing to prune"
fi

# --- success marker ------------------------------------------------------------
# Machine-readable "when did a backup last actually succeed". Point a file-age
# check or the RUNBOOK at this rather than at the directory listing, which also
# contains failures from before the .part rename.
printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$(basename "$OUT")" > "$BACKUP_DIR/last_success"

hc_ping
log "done"
