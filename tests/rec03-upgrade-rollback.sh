#!/usr/bin/env bash
# REC-03 / A38 drill driver — runs ON the disposable host as root:
#   ssh root@HOST 'bash -s -- <phase>' < rec03.sh
# Phases: install | data | fp <label> | backup | inject | upgrade-fail | recover | backup2 | rollback | restore-refuse | repin | restore-ok | split | report
#
# NOTHING RELEASE-SPECIFIC HAS A DEFAULT, and that is the whole point of the parameters below.
# This driver used to be hard-wired to one pair: the release tags defaulted to it, the injected
# DDL was the column ONE migration of that pair adds, and the recovery forced a literal ledger
# version. Pointed at a later host every one of those is silently wrong in the same direction —
# the column already exists, so the INJECTION errors instead of the migrator (the drill "fails"
# at the wrong step for the wrong reason) and the recovery then stamps the ledger at a version
# the schema is nowhere near. None of it is visible until the paid host is already running.
#
#   REC03_OLD / REC03_NEW      the release pair, e.g. REC03_OLD=v0.6.6 REC03_NEW=v0.7.5.
#                              REQUIRED, vX.Y.Z; they become a git ref and a raw.githubusercontent
#                              URL, so they are pattern-checked rather than trusted.
#   REC03_INJECT=column|dirty  how the upgrade is made to fail. `column` pre-creates a column the
#                              upgrade's FIRST pending migration adds without IF NOT EXISTS, so
#                              the real, unmodified migrator fails on it. `dirty` marks the ledger
#                              dirty — the only failure a pair that ships no new migration can
#                              have. Default: column.
#   REC03_INJECT_TABLE         the column to pre-create. REQUIRED when REC03_INJECT=column; there
#   REC03_INJECT_COLUMN        is deliberately no fallback, because a fallback here is another
#   REC03_INJECT_TYPE          release's fact. The script BUILDS both the `ALTER TABLE .. ADD
#                              COLUMN` and its exact `DROP COLUMN` undo from these three
#                              (inject_ddl / inject_undo_ddl) so the two cannot drift apart, and
#                              validates each against a strict identifier / type pattern — this
#                              is operator text executed as SQL against the drill database, not
#                              a label.
#   REC03_SAME_SCHEMA=1        assert the pair carries the SAME core schema, so `restore-refuse`
#                              has no input and is recorded not applicable. Checked against the
#                              ledger versions the drill actually captured: a contradiction is
#                              refused in BOTH directions, so the phase can neither be skipped
#                              when it applies nor demanded when it cannot.
#   REC03_ROOT                 where logs/facts/state live. Default /root/rec03.
#   REC03_ALLOW_DOCKER=1       proceed on a host that already has Docker (i.e. not a blank host).
#
# The recovery `force` target is DERIVED, never typed: the clean pre-upgrade ledger version the
# `backup` phase captured, and only once force_target() has confirmed the ledger went dirty at
# exactly pre+1 — i.e. that the injected conflict stopped the FIRST pending migration. See
# force_target for what happens when it did not.
#
# The two historical invocations, restated in this parameter shape, are in
# docs/runtime-acceptance-rec03-v0.7.5-prepared.md — deliberately there and not here, so that no
# release's literals live in this file at all.
#
# Every phase appends to $REC03_ROOT/<phase>.log and writes facts to $REC03_ROOT/facts/<phase>.json.
# Deliberately no `set -e`: a phase's whole point is to capture a non-zero exit
# (a refused deploy, a refused restore) as a fact rather than to stop on it.
set -uo pipefail

# >>> BEGIN validators — tests/rec03_script_test.py lifts this REGION verbatim and asserts on it
# (the same trick tests/scanner_profile_test.py uses on deploy.sh). The drill itself cannot run
# without a paid host, so these guards are the only part of it CI can honestly keep true. Nothing
# between the markers may touch the host.
R="${REC03_ROOT:-/root/rec03}"
DOMAIN=rec03.video.test
API=http://127.0.0.1:8080/api/v1
DIR=/opt/vidra
PHASE="${1:-}"
OLD="${REC03_OLD:-}"
NEW="${REC03_NEW:-}"
INJECT="${REC03_INJECT:-column}"
INJECT_TABLE="${REC03_INJECT_TABLE:-}"
INJECT_COLUMN="${REC03_INJECT_COLUMN:-}"
INJECT_TYPE="${REC03_INJECT_TYPE:-}"

# Postgres folds an unquoted identifier to lower case and allows 63 bytes; this drill only ever
# names vidra's own snake_case tables and columns. Anything else — a quote, a semicolon, a space,
# a newline, an accent, upper case — is a typo or an injection attempt, and is REFUSED rather
# than escaped: a refusal is checkable, escaping is a thing to get wrong exactly once.
IDENT_RE='^[a-z_][a-z0-9_]{0,62}$'
# An allowlist, not a pattern: the type is the one field where a DEFAULT, a CHECK, a REFERENCES
# clause or a second statement could ride in behind something that still looks like a type.
TYPE_RE='^(UUID|TEXT|BOOLEAN|SMALLINT|INT|INTEGER|BIGINT|REAL|NUMERIC|JSONB|DATE|TIMESTAMP|TIMESTAMPTZ)$'
TAG_RE='^v[0-9]+\.[0-9]+\.[0-9]+$'

log() { printf '[rec03 %s %s] %s\n' "${PHASE:-init}" "$(date -u +%H:%M:%S)" "$*"; }
# REFUSED, not "error": every one of these fires before the thing it guards has happened.
die() { log "REFUSED: $*" >&2; exit 1; }
# The second argument is a regex, so it is deliberately unquoted.
matches() { [[ "$1" =~ $2 ]]; }

require_release_pair() {
  { [ -n "$OLD" ] && [ -n "$NEW" ]; } || die "REC03_OLD and REC03_NEW are required, e.g. REC03_OLD=v0.6.6 REC03_NEW=v0.7.5. There is no default: this driver shipped wired to one pair, and a forgotten export would silently drill that pair instead of the candidate."
  matches "$OLD" "$TAG_RE" || die "REC03_OLD=\"$OLD\" is not a release tag (vX.Y.Z). It is used as a git ref and inside a raw.githubusercontent.com URL."
  matches "$NEW" "$TAG_RE" || die "REC03_NEW=\"$NEW\" is not a release tag (vX.Y.Z). It is used as a git ref and inside a raw.githubusercontent.com URL."
  [ "$OLD" != "$NEW" ] || die "REC03_OLD and REC03_NEW are both $OLD — an upgrade drill needs two releases."
}

# The injection preflight. Called from ONE place, before the phase dispatch, so that no phase can
# reach a psql call carrying a value nothing checked.
require_injection_setup() {
  case "$INJECT" in
    dirty)  return 0 ;;
    column) ;;
    *)      die "REC03_INJECT=\"$INJECT\" is neither column nor dirty; a misspelling must not fall through to a column injection." ;;
  esac
  local missing=''
  [ -n "$INJECT_TABLE" ]  || missing="$missing REC03_INJECT_TABLE"
  [ -n "$INJECT_COLUMN" ] || missing="$missing REC03_INJECT_COLUMN"
  [ -n "$INJECT_TYPE" ]   || missing="$missing REC03_INJECT_TYPE"
  [ -z "$missing" ] || die "REC03_INJECT=column needs the column to pre-create; unset:$missing. No default is supplied on purpose: a column taken from another release's migration either already exists on this host — in which case the injection errors instead of the migrator — or belongs to a migration this upgrade never runs."
  matches "$INJECT_TABLE" "$IDENT_RE" || die "REC03_INJECT_TABLE=\"$INJECT_TABLE\" is not a bare lower-case SQL identifier; this value is executed as SQL against the drill database."
  matches "$INJECT_COLUMN" "$IDENT_RE" || die "REC03_INJECT_COLUMN=\"$INJECT_COLUMN\" is not a bare lower-case SQL identifier; this value is executed as SQL against the drill database."
  matches "$(printf '%s' "$INJECT_TYPE" | tr '[:lower:]' '[:upper:]')" "$TYPE_RE" || die "REC03_INJECT_TYPE=\"$INJECT_TYPE\" is not one of the column types vidra's migrations add (UUID TEXT BOOLEAN SMALLINT INT INTEGER BIGINT REAL NUMERIC JSONB DATE TIMESTAMP TIMESTAMPTZ). What the drill needs is a clash on the column NAME, so no DEFAULT, CHECK or REFERENCES clause is accepted here."
}

# The injection and its undo, built from the SAME three parameters so they cannot drift: an undo
# that names a different column leaves the drill database permanently off-script, on a host that
# costs money and has to be rebuilt to retry.
inject_ddl() { printf 'ALTER TABLE %s ADD COLUMN %s %s' "$INJECT_TABLE" "$INJECT_COLUMN" "$(printf '%s' "$INJECT_TYPE" | tr '[:lower:]' '[:upper:]')"; }
inject_undo_ddl() { printf 'ALTER TABLE %s DROP COLUMN %s' "$INJECT_TABLE" "$INJECT_COLUMN"; }

# force_target <clean pre-upgrade version> <version the ledger is DIRTY at> -> the force target.
#
# golang-migrate stamps the ledger at N and marks it dirty BEFORE running migration N and clears
# the flag on success, so a dirty N means N is the migration that died and N-1 is the newest one
# fully applied (vidra-core internal/dbmigrate/dbmigrate.go, Status.Dirty). The runbook's `migrate
# force` must name that fully-applied version: it rewrites the ledger while running NO SQL, so
# naming anything else strands the database. When the injected conflict stops the FIRST pending
# migration that version is exactly the pre-upgrade one `backup` recorded — which is why it is
# derived from the host instead of typed. When it is not, forcing back to the pre-upgrade version
# would re-run migrations that already applied, so this refuses rather than guesses.
force_target() {
  local pre="$1" dirty_at="$2"
  { [ -n "$pre" ] && [ -n "$dirty_at" ]; } || die "force_target needs both ledger versions (pre=\"$pre\" dirty_at=\"$dirty_at\"); an empty one means a psql read failed, not that the ledger is at 0."
  case "$pre" in *[!0-9]*) die "pre-upgrade ledger version \"$pre\" is not a number" ;; esac
  case "$dirty_at" in *[!0-9]*) die "dirty ledger version \"$dirty_at\" is not a number" ;; esac
  if [ "$dirty_at" -ne $((pre + 1)) ]; then
    die "the ledger is dirty at $dirty_at, not at $((pre + 1)): the injected conflict did not stop the FIRST pending migration, so everything up to $((dirty_at - 1)) has already applied and forcing back to $pre would re-run it. Undo $dirty_at's partial effect by hand and force $((dirty_at - 1)) instead."
  fi
  printf '%s' "$pre"
}

# check_same_schema_expectation <pre-upgrade core schema> <post-upgrade core schema>
#
# REC03_SAME_SCHEMA decides whether `restore-refuse` runs, and it used to be a bare operator
# claim. Set it on a migrating pair and the one case that proves restore.sh refuses a dump AHEAD
# of the pinned binary is quietly skipped; leave it unset on a non-migrating pair and the drill
# demands a refusal that has no possible input. Both readings are now checked against the ledger
# versions the drill itself captured.
check_same_schema_expectation() {
  local pre="$1" post="$2" same="${REC03_SAME_SCHEMA:-0}"
  if [ "$pre" != "$post" ] && [ "$same" = 1 ]; then
    die "REC03_SAME_SCHEMA=1, but this drill captured core schema $pre -> $post: the pair DOES migrate, so a dump taken after the upgrade IS ahead of the $OLD binary and restore-refuse has a real input. Unset REC03_SAME_SCHEMA and run it."
  fi
  if [ "$pre" = "$post" ] && [ "$same" != 1 ]; then
    die "REC03_SAME_SCHEMA is unset, but this drill captured core schema $pre -> $post (unchanged): no dump can be ahead of the $OLD binary, so restore-refuse has no input and cannot be run. Set REC03_SAME_SCHEMA=1 so it is recorded not applicable."
  fi
}
# <<< END validators

[ -n "$PHASE" ] || { echo "usage: bash -s -- <phase>   (install|data|fp <label>|backup|inject|upgrade-fail|recover|backup2|rollback|restore-refuse|repin|restore-ok|split|report)" >&2; exit 1; }
shift; set -- "$PHASE" "${1:-}"
F="$R/facts/$PHASE.json"; mkdir -p "$R/facts" "$R/state"
exec > >(tee -a "$R/$PHASE.log") 2>&1

# The preflight, ahead of ANY host call in any phase: a bad parameter has to be refused here and
# not discovered halfway through a drill, on a host that must be rebuilt before it can be retried.
require_release_pair
case "$PHASE" in
  inject|recover) require_injection_setup ;;
esac

asv() { su - vidra -c "cd $DIR && VIDRA_SKIP_DNS_PREFLIGHT=1 $*"; }   # run as the checkout owner
psq() { su - vidra -c "cd $DIR && ./deploy/compose.sh exec -T postgres psql -U vidra -d vidra -tA -c \"$1\""; }
imgs() { docker ps --format '{{.Names}} {{.Image}}' | grep -E 'api|frontend|search' | sort | tr '\n' ';'; }
ledger() { echo "core=$(psq 'SELECT version||chr(58)||dirty FROM schema_migrations') search=$(psq 'SELECT version||chr(58)||dirty FROM vidra_search_migrations')"; }
core_version() { psq 'SELECT version FROM schema_migrations'; }
counts() { echo "users=$(psq 'SELECT count(*) FROM users') channels=$(psq 'SELECT count(*) FROM channels') videos=$(psq 'SELECT count(*) FROM videos') titles=$(psq 'SELECT string_agg(title, chr(124) ORDER BY title) FROM videos')"; }
token() { curl -sf -X POST "$API/auth/login" -H 'content-type: application/json' -d "$(cat "$R/owner.json")" | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])'; }
# The captured ledger versions, written by `backup` (pre) and `recover` (post). They are state,
# not facts-file cosmetics: `recover` forces back to the first and `restore-refuse` is gated on
# the pair, so a missing one is a refusal rather than a default.
remembered() { cat "$R/state/$1" 2>/dev/null; }
remember() { printf '%s\n' "$2" > "$R/state/$1"; }
assert_schema_expectation() {
  local pre post
  pre="$(remembered pre_core_version)"; post="$(remembered post_core_version)"
  [ -n "$pre" ] || die "no pre-upgrade core schema recorded — run the 'backup' phase, which captures the clean ledger one phase before 'inject' mutates anything."
  [ -n "$post" ] || die "no post-upgrade core schema recorded — run the 'recover' phase, which captures the ledger the upgrade actually reached."
  check_same_schema_expectation "$pre" "$post"
}
fingerprint() {  # original + master playlist + first segment sha256, via the api proxy
  local vid t; vid="$(cat "$R/video_id")"; t="$(token)"
  local orig master variant seg hls_url renditions
  orig="$(curl -sf -H "Authorization: Bearer $t" "$API/videos/$vid/original" | sha256sum | cut -c1-16)"
  hls_url="$(curl -sf "$API/videos/$vid" | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d.get("hls_url",""))')"
  renditions="$(curl -sf "$API/videos/$vid" | python3 -c 'import sys,json;d=json.load(sys.stdin);print(",".join(str(r.get("height")) for r in d.get("renditions",[])))')"
  master="$(curl -sf "http://127.0.0.1:8080$hls_url" | sha256sum | cut -c1-16)"
  variant="$(curl -sf "http://127.0.0.1:8080$hls_url" | grep -vE '^#|^$' | head -1)"
  seg="$(curl -sf "http://127.0.0.1:8080${hls_url%/*}/$variant" | grep -vE '^#|^$' | head -1)"
  segsha="$(curl -sf "http://127.0.0.1:8080${hls_url%/*}/${variant%/*}/$seg" | sha256sum | cut -c1-16)"
  echo "orig=$orig master=$master renditions=$renditions variant=$variant seg=$seg segsha=$segsha state=$(curl -sf "$API/videos/$vid" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("state"))')"
}
probe() { echo "instance=$(curl -s -o /dev/null -w '%{http_code}' $API/instance) healthz=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/healthz) site=$(curl -sk -o /dev/null -w '%{http_code}' --resolve $DOMAIN:443:127.0.0.1 https://$DOMAIN/) watch=$(curl -sk -o /dev/null -w '%{http_code}' --resolve $DOMAIN:443:127.0.0.1 "https://$DOMAIN/videos/$(cat "$R/video_id" 2>/dev/null || echo none)")"; }
facts() { python3 - "$F" "$@" <<'PY'
import json,sys
out=sys.argv[1]; d={}
for kv in sys.argv[2:]:
    k,_,v=kv.partition('='); d[k]=v
json.dump(d, open(out,'w'), indent=1)
PY
}

case "$PHASE" in
install)
  log "blank-host check"
  if docker info >/dev/null 2>&1 && [ "${REC03_ALLOW_DOCKER:-0}" != 1 ]; then log "docker already present — not a blank host (REC03_ALLOW_DOCKER=1 to proceed anyway)"; exit 1; fi
  [ -e "$DIR" ] && { log "$DIR exists — not blank"; exit 1; }
  grep -q "$DOMAIN" /etc/hosts || echo "127.0.0.1 $DOMAIN" >> /etc/hosts
  log "released installer $OLD (git path)"
  curl -fsSL "https://raw.githubusercontent.com/yegamble/vidra/$OLD/install.sh" -o "/root/install-$OLD.sh"
  sha256sum "/root/install-$OLD.sh"
  sh "/root/install-$OLD.sh" --git --ref "$OLD" --yes </dev/null; rc=$?; log "install.sh exit=$rc"
  vidra --help 2>&1 | head -2; find "$DIR" -maxdepth 1 -mindepth 1 | sort | head; git -C "$DIR" describe --tags --always; for c in vidra-core vidra-user vidra-search; do echo "$c $(git -C $DIR/$c describe --tags --always)"; done
  log "vidra setup --non-interactive"
  ( cd $DIR && vidra setup --non-interactive --yes --domain $DOMAIN --instance-name "REC-03 drill" --registration closed --tls-mode internal --storage local --scan=false --release-tag "$OLD" --template env/production.env.example ); log "setup exit=$?"
  ( cd $DIR && vidra setup --check env/production.env ); log "setup --check exit=$?"
  grep -E '^(VIDRA_[A-Z_]*TAG|VIDRA_TLS_MODE|VIDRA_COMPOSE_PROFILES|STORAGE_BACKEND|MALWARE_SCAN_MODE|HTTP_PORT|PUBLIC_BASE_URL)=' $DIR/env/production.env || true
  python3 "$(dirname "$0")/rec03-envfix.py" 2>/dev/null || python3 /root/rec03-envfix.py   # F2: setup --scan=false leaves CLAMAV_ADDR + fail-closed; apply beta's posture before the first deploy
  grep -nE '^MALWARE_SCAN_MODE=|CLAMAV_ADDR unset' "$DIR/env/production.env"
  log "provision.sh --yes (vidra user, chown, docker group)"
  ( cd $DIR && ./deploy/provision.sh --yes ); log "provision exit=$?"
  id vidra; stat -c '%U %n' $DIR $DIR/env/production.env
  log "deploy $OLD as vidra"
  asv ./deploy/deploy.sh; rc=$?; log "deploy.sh exit=$rc"
  probe; imgs; ledger
  facts install_exit=$rc "images=$(imgs)" "ledger=$(ledger)" "probe=$(probe)"
  ;;
data)
  log "fixture via the api image's ffmpeg"; mkdir -p "$R/fx"; chmod 777 "$R/fx"
  docker run --rm --entrypoint ffmpeg -v "$R/fx:/out" "ghcr.io/yegamble/vidra-core:$OLD" -y -loglevel error -f lavfi -i testsrc2=duration=12:size=1280x720:rate=25 -f lavfi -i sine=frequency=440:duration=12 -c:v libx264 -pix_fmt yuv420p -c:a aac -shortest /out/fixture.mp4
  ls -la "$R/fx/fixture.mp4"; sha256sum "$R/fx/fixture.mp4" | tee "$R/fixture.sha"
  log "owner claim"
  tok="$(su - vidra -c "cd $DIR && ./deploy/compose.sh logs --no-color api" | grep -oE 'owner_claim_required until claimed\): [A-Za-z0-9_-]+' | tail -1 | awk '{print $NF}')"
  [ -n "$tok" ] || { log "no boot claim token in api logs"; exit 1; }
  printf '{"email":"owner@%s","password":"rec03-drill-password-2026"}' "$DOMAIN" > "$R/owner.json"
  code=$(curl -s -o "$R/claim.json" -w '%{http_code}' -X POST $API/setup/claim-owner -H 'content-type: application/json' -d "{\"token\":\"$tok\",\"username\":\"owner\",\"email\":\"owner@$DOMAIN\",\"password\":\"rec03-drill-password-2026\"}"); log "claim-owner http=$code"
  t="$(token)"; [ -n "$t" ] || { log "login failed"; exit 1; }
  code=$(curl -s -o /dev/null -w '%{http_code}' -X POST $API/channels -H "Authorization: Bearer $t" -H 'content-type: application/json' -d '{"handle":"drill","display_name":"REC-03 drill channel"}'); log "channel http=$code"
  vid=$(curl -sf -X POST $API/channels/drill/videos -H "Authorization: Bearer $t" -H 'content-type: application/json' -d "{\"title\":\"REC-03 fixture $OLD\",\"privacy\":\"public\"}" | python3 -c 'import sys,json;print(json.load(sys.stdin)["id"])'); echo "$vid" > "$R/video_id"; log "video id=$vid"
  code=$(curl -s -o "$R/upload.json" -w '%{http_code}' -X POST "$API/videos/$vid/file" -H "Authorization: Bearer $t" -F "file=@$R/fx/fixture.mp4;type=video/mp4"); log "upload http=$code"
  for i in $(seq 1 120); do st=$(curl -sf -H "Authorization: Bearer $t" "$API/videos/$vid" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("state"))'); [ "$st" = published ] && break; sleep 5; done; log "state=$st after $((i*5))s"
  fingerprint | tee "$R/fp.data"; counts; ledger; probe
  facts "state=$st" "fp=$(cat "$R/fp.data")" "counts=$(counts)" "ledger=$(ledger)" "probe=$(probe)"
  ;;
fp)
  fingerprint | tee "$R/fp.$2"; counts; ledger; probe; echo "renditions_rows=$(psq 'SELECT count(*) FROM video_renditions') files_rows=$(psq 'SELECT count(*) FROM video_files')"
  facts "fp=$(cat "$R/fp.$2")" "counts=$(counts)" "ledger=$(ledger)" "probe=$(probe)"
  ;;
backup)
  log "backup.sh at $OLD (pre-upgrade dump)"; asv ./deploy/backup.sh; rc=$?; find "$DIR/backups" -maxdepth 1 -type f -newer "$R/fixture.sha" | sort
  d=$(find "$DIR/backups" -maxdepth 1 -name "vidra-*.dump.gz" -newer "$R/fixture.sha" | sort | tail -1); echo "$d" > "$R/dump_pre"
  # Capture the clean pre-upgrade ledger HERE: this is the last phase before `inject` mutates the
  # database, and it is what `recover` forces back to. Read off the host rather than typed,
  # because a typed version becomes another release's fact the moment the candidate changes.
  pre="$(core_version)"; predirty="$(psq 'SELECT dirty FROM schema_migrations')"
  [ -n "$pre" ] || die "cannot read schema_migrations — the pre-upgrade version is what recover forces back to, so the drill cannot continue without it."
  [ "$predirty" = f ] || die "the core ledger is already dirty at $pre; this drill starts from a clean $OLD install."
  remember pre_core_version "$pre"
  log "dump_pre=$d exit=$rc pre_core_version=$pre"
  facts "backup_exit=$rc" "dump_pre=$d" "pre_core_version=$pre"
  ;;
inject)
  if [ "$INJECT" = dirty ]; then
    log "inject: mark the core ledger DIRTY at its current version (this pair ships no new migration, so the failure the migrator must refuse is a dirty ledger)"
    psq "UPDATE schema_migrations SET dirty = true"; ledger
    facts injected=dirty_ledger "ledger=$(ledger)"
  else
    log "inject: pre-create the column the upgrade's first pending migration adds (it carries no IF NOT EXISTS, so the real, unmodified migrator must fail on it): $(inject_ddl)"
    psq "$(inject_ddl)"; ledger
    facts "injected=$(inject_ddl)" "undo=$(inject_undo_ddl)" "ledger=$(ledger)"
  fi
  ;;
upgrade-fail)
  su - vidra -c "git -C $DIR fetch --tags --force origin"
  if su - vidra -c "git -C $DIR cat-file -e $NEW:deploy/pin-release.sh" 2>/dev/null; then
    log "README procedure for a pre-v0.6.5 tree: one-time move to $NEW as the deploy user, then pin-release.sh $NEW"
    su - vidra -c "git -C $DIR checkout --detach --quiet $NEW && git -C $DIR describe --tags --always"
  else
    log "tree -> origin/main (to obtain pin-release.sh), then pin-release.sh $NEW"
    su - vidra -c "git -C $DIR checkout --detach --quiet origin/main && git -C $DIR describe --tags --always"
  fi
  asv ./deploy/pin-release.sh "$NEW"; prc=$?; log "pin-release.sh exit=$prc"; su - vidra -c "git -C $DIR describe --tags --always"; grep -E '^VIDRA_[A-Z_]*TAG=' $DIR/env/production.env
  if [ $prc -ne 0 ]; then
    log "pin-release.sh failed — falling back to the pre-v0.6.5 runbook: tree at tag + rewrite pins as vidra"
    su - vidra -c "git -C $DIR checkout --detach --quiet $NEW && cd $DIR && python3 - <<'PY'
import re,os
p='env/production.env'; s=open(p).read()
for k in ('VIDRA_CORE_TAG','VIDRA_USER_TAG','VIDRA_SEARCH_TAG'):
    s=re.sub(r'(?m)^'+k+r'=.*$', k+'=$NEW', s)
tmp=p+'.tmp'; open(tmp,'w').write(s); os.chmod(tmp,0o600); os.replace(tmp,p)
PY"
    grep -E '^VIDRA_[A-Z_]*TAG=' $DIR/env/production.env
  fi
  log "deploy.sh (expected: abort inside the migrate step, no restart)"; asv ./deploy/deploy.sh; rc=$?; log "deploy.sh exit=$rc"
  imgs; ledger; probe; fingerprint | tee "$R/fp.fail"
  facts pin_release_exit=$prc deploy_exit=$rc "images=$(imgs)" "ledger=$(ledger)" "probe=$(probe)" "fp=$(cat "$R/fp.fail")"
  ;;
recover)
  log "runbook: migrate version, undo the partial effect, force the newest FULLY applied version, rerun"
  asv "./deploy/compose.sh run --rm migrate migrate version"
  if [ "$INJECT" = dirty ]; then
    target=$(core_version); log "dirty at $target: nothing partial to undo; force the ledger clean at the SAME version"
  else
    pre="$(remembered pre_core_version)"
    [ -n "$pre" ] || die "no pre-upgrade core schema recorded — run the 'backup' phase before 'inject'. There is no literal to fall back to: such a literal is exactly what made this driver wrong for every pair but one."
    dirty_at="$(core_version)"
    target="$(force_target "$pre" "$dirty_at")" || exit 1
    log "ledger dirty at $dirty_at; newest fully applied = $target (the pre-upgrade ledger this drill captured)"
    psq "$(inject_undo_ddl)"
  fi
  asv "./deploy/compose.sh run --rm migrate migrate force $target --yes-i-know"; log "force $target exit=$?"
  asv ./deploy/deploy.sh; rc=$?; log "deploy.sh exit=$rc"
  post="$(core_version)"; [ -n "$post" ] && remember post_core_version "$post"
  imgs; ledger; probe; fingerprint | tee "$R/fp.recover"; counts
  facts deploy_exit=$rc "force_target=$target" "post_core_version=$post" "images=$(imgs)" "ledger=$(ledger)" "probe=$(probe)" "fp=$(cat "$R/fp.recover")" "counts=$(counts)"
  ;;
backup2)
  # Both ledger versions are known by now, so this is the first moment REC03_SAME_SCHEMA can be
  # checked against reality — ahead of the rollback and restore phases whose shape it decides.
  assert_schema_expectation
  log "backup.sh at $NEW (post-upgrade dump) + a post-backup marker write"
  asv ./deploy/backup.sh; rc=$?; d=$(find "$DIR/backups" -maxdepth 1 -name "vidra-*.dump.gz" -newer "$(cat "$R/dump_pre")" | sort | tail -1); echo "$d" > "$R/dump_post"; log "dump_post=$d exit=$rc"
  t="$(token)"; vid=$(cat "$R/video_id")
  code=$(curl -s -o /dev/null -w '%{http_code}' -X PATCH "$API/videos/$vid" -H "Authorization: Bearer $t" -H 'content-type: application/json' -d "{\"title\":\"REC-03 fixture RENAMED after the schema $(remembered post_core_version) backup\"}"); log "marker PATCH http=$code"; counts
  facts "backup_exit=$rc" "dump_post=$d" "marker_http=$code" "counts=$(counts)"
  ;;
rollback)
  log "rollback.sh $OLD (app-only; the schema stays where the upgrade left it)"; asv ./deploy/rollback.sh "$OLD"; rc=$?; log "rollback.sh exit=$rc"
  imgs; ledger; probe; fingerprint | tee "$R/fp.rollback"; counts; grep -E '^VIDRA_[A-Z_]*TAG=' $DIR/env/production.env
  facts rollback_exit=$rc "images=$(imgs)" "ledger=$(ledger)" "probe=$(probe)" "fp=$(cat "$R/fp.rollback")" "counts=$(counts)"
  ;;
restore-refuse)
  assert_schema_expectation
  if [ "${REC03_SAME_SCHEMA:-0}" = 1 ]; then log "not applicable: $OLD and $NEW both carry core schema $(remembered pre_core_version), so no dump can be ahead of the pinned binary"; facts not_applicable=same_schema "pre_core_version=$(remembered pre_core_version)" "post_core_version=$(remembered post_core_version)"; exit 0; fi
  log "restore.sh of the newer-schema dump under $OLD pins — expected refusal BEFORE dropdb"; before="$(counts)"
  asv "./deploy/restore.sh --yes $(cat "$R/dump_post")"; rc=$?; log "restore.sh exit=$rc"
  imgs; ledger; probe; after="$(counts)"; if [ "$before" = "$after" ]; then log "counts unchanged"; else log "COUNTS CHANGED: $before -> $after"; fi
  facts restore_exit=$rc "counts_before=$before" "counts_after=$after" "ledger=$(ledger)" "probe=$(probe)"
  ;;
repin)
  log "re-pin $NEW + deploy (roll forward)"
  su - vidra -c "cd $DIR && python3 - <<'PY'
import re,os
p='env/production.env'; s=open(p).read()
for k in ('VIDRA_CORE_TAG','VIDRA_USER_TAG','VIDRA_SEARCH_TAG'):
    s=re.sub(r'(?m)^'+k+r'=.*$', k+'=$NEW', s)
tmp=p+'.tmp'; open(tmp,'w').write(s); os.chmod(tmp,0o600); os.replace(tmp,p)
PY"
  asv ./deploy/deploy.sh; rc=$?; log "deploy.sh exit=$rc"; imgs; ledger; probe
  facts deploy_exit=$rc "images=$(imgs)" "ledger=$(ledger)" "probe=$(probe)"
  ;;
restore-ok)
  log "restore.sh of the pre-upgrade dump under $NEW pins — the documented forward path; the marker rename must be gone"
  asv "./deploy/restore.sh --yes $(cat "$R/dump_pre")"; rc=$?; log "restore.sh exit=$rc"
  imgs; ledger; probe; fingerprint | tee "$R/fp.restore"; counts
  facts restore_exit=$rc "images=$(imgs)" "ledger=$(ledger)" "probe=$(probe)" "fp=$(cat "$R/fp.restore")" "counts=$(counts)"
  ;;
split)
  log "OPS-01: API/worker split on $NEW — EXTRA_COMPOSE_PROFILES=worker + API_ROLE=api, then deploy"
  su - vidra -c "cd $DIR && python3 - <<'PY'
import re,os
p='env/production.env'; s=open(p).read()
for k,v in (('EXTRA_COMPOSE_PROFILES','worker'),('API_ROLE','api')):
    if re.search(r'(?m)^'+k+'=', s): s=re.sub(r'(?m)^'+k+r'=.*$', k+'='+v, s)
    else: s+=('' if s.endswith('\n') else '\n')+k+'='+v+'\n'
tmp=p+'.tmp'; open(tmp,'w').write(s); os.chmod(tmp,0o600); os.replace(tmp,p)
PY"
  grep -E '^(EXTRA_COMPOSE_PROFILES|API_ROLE)=' $DIR/env/production.env
  asv ./deploy/deploy.sh; rc=$?; log "deploy.sh exit=$rc"; imgs; docker ps --format '{{.Names}} {{.Status}}' | grep -E 'worker|api'
  t="$(token)"
  vid=$(curl -sf -X POST $API/channels/drill/videos -H "Authorization: Bearer $t" -H 'content-type: application/json' -d '{"title":"REC-03 split-topology upload","privacy":"public"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["id"])'); log "video2 id=$vid"
  code=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$API/videos/$vid/file" -H "Authorization: Bearer $t" -F "file=@$R/fx/fixture.mp4;type=video/mp4"); log "upload2 http=$code"
  for i in $(seq 1 120); do st=$(curl -sf -H "Authorization: Bearer $t" "$API/videos/$vid" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("state"))'); [ "$st" = published ] && break; sleep 5; done; log "video2 state=$st after $((i*5))s"
  log "who transcoded it: ffmpeg/transcode lines per container"
  for c in $(docker ps --format '{{.Names}}' | grep -E 'worker|api'); do echo "$c: $(docker logs "$c" 2>&1 | grep -ciE 'transcod|ffmpeg|rendition')"; done
  api_ffmpeg=$(docker logs "$(docker ps --format '{{.Names}}' | grep -E '[-_]api[-_]' | head -1)" 2>&1 | grep -ciE 'ffmpeg'); log "api container ffmpeg mentions=$api_ffmpeg"
  probe; counts
  facts deploy_exit=$rc "images=$(imgs)" "video2_state=$st" "probe=$(probe)" "counts=$(counts)" "api_ffmpeg_mentions=$api_ffmpeg" "workers=$(docker ps --format '{{.Names}}' | grep -c worker)"
  ;;
report)
  asv "vidra doctor" || true; docker --version; docker compose version; python3 --version; lsb_release -ds
  log "pair=$OLD -> $NEW inject=$INJECT pre_core_version=$(remembered pre_core_version) post_core_version=$(remembered post_core_version) same_schema=${REC03_SAME_SCHEMA:-0}"
  python3 - "$R/facts" <<'PY'
import json,os,sys
d=sys.argv[1]; out={}
for f in sorted(os.listdir(d)):
    out[f[:-5]]=json.load(open(os.path.join(d,f)))
print(json.dumps(out, indent=1))
PY
  ;;
*) echo "unknown phase $PHASE"; exit 2 ;;
esac
