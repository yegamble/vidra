#!/usr/bin/env bash
# REC-03 / A38 drill driver — runs ON the disposable host as root:
#   ssh root@HOST 'bash -s -- <phase>' < rec03.sh
# Phases: install | data | fp <label> | backup | inject | upgrade-fail | recover | backup2 | rollback | restore-refuse | repin | restore-ok | split | report
# Release pair and variant: REC03_OLD / REC03_NEW (default v0.6.3 / v0.6.4); REC03_INJECT=column|dirty (a pair with no new
# migration cannot conflict on a column, so inject a dirty ledger); REC03_SAME_SCHEMA=1 skips the refusal phase that needs
# a dump ahead of the pinned binary. The v0.6.4 -> v0.6.5 run used REC03_OLD=v0.6.4 REC03_NEW=v0.6.5 REC03_INJECT=dirty REC03_SAME_SCHEMA=1.
# Every phase appends to /root/rec03/<phase>.log and writes facts to /root/rec03/facts/<phase>.json.
# Deliberately no `set -e`: a phase's whole point is to capture a non-zero exit
# (a refused deploy, a refused restore) as a fact rather than to stop on it.
set -uo pipefail
PHASE="${1:?phase}"; shift; set -- "$PHASE" "${1:-}"
R=/root/rec03; mkdir -p "$R/facts"; F="$R/facts/$PHASE.json"
DOMAIN=rec03.video.test
API=http://127.0.0.1:8080/api/v1
DIR=/opt/vidra
OLD="${REC03_OLD:-v0.6.3}"; NEW="${REC03_NEW:-v0.6.4}"   # override per candidate, e.g. REC03_OLD=v0.6.4 REC03_NEW=v0.6.5
exec > >(tee -a "$R/$PHASE.log") 2>&1
log() { printf '[rec03 %s %s] %s\n' "$PHASE" "$(date -u +%H:%M:%S)" "$*"; }
asv() { su - vidra -c "cd $DIR && VIDRA_SKIP_DNS_PREFLIGHT=1 $*"; }   # run as the checkout owner
psq() { su - vidra -c "cd $DIR && ./deploy/compose.sh exec -T postgres psql -U vidra -d vidra -tA -c \"$1\""; }
imgs() { docker ps --format '{{.Names}} {{.Image}}' | grep -E 'api|frontend|search' | sort | tr '\n' ';'; }
ledger() { echo "core=$(psq 'SELECT version||chr(58)||dirty FROM schema_migrations') search=$(psq 'SELECT version||chr(58)||dirty FROM vidra_search_migrations')"; }
counts() { echo "users=$(psq 'SELECT count(*) FROM users') channels=$(psq 'SELECT count(*) FROM channels') videos=$(psq 'SELECT count(*) FROM videos') titles=$(psq 'SELECT string_agg(title, chr(124) ORDER BY title) FROM videos')"; }
token() { curl -sf -X POST "$API/auth/login" -H 'content-type: application/json' -d "$(cat $R/owner.json)" | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])'; }
fingerprint() {  # original + master playlist + first segment sha256, via the api proxy
  local vid t; vid="$(cat $R/video_id)"; t="$(token)"
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
  log "fixture via the api image's ffmpeg"; mkdir -p $R/fx; chmod 777 $R/fx
  docker run --rm --entrypoint ffmpeg -v $R/fx:/out "ghcr.io/yegamble/vidra-core:$OLD" -y -loglevel error -f lavfi -i testsrc2=duration=12:size=1280x720:rate=25 -f lavfi -i sine=frequency=440:duration=12 -c:v libx264 -pix_fmt yuv420p -c:a aac -shortest /out/fixture.mp4
  ls -la $R/fx/fixture.mp4; sha256sum $R/fx/fixture.mp4 | tee $R/fixture.sha
  log "owner claim"
  tok="$(su - vidra -c "cd $DIR && ./deploy/compose.sh logs --no-color api" | grep -oE 'owner_claim_required until claimed\): [A-Za-z0-9_-]+' | tail -1 | awk '{print $NF}')"
  [ -n "$tok" ] || { log "no boot claim token in api logs"; exit 1; }
  printf '{"email":"owner@%s","password":"rec03-drill-password-2026"}' "$DOMAIN" > $R/owner.json
  code=$(curl -s -o $R/claim.json -w '%{http_code}' -X POST $API/setup/claim-owner -H 'content-type: application/json' -d "{\"token\":\"$tok\",\"username\":\"owner\",\"email\":\"owner@$DOMAIN\",\"password\":\"rec03-drill-password-2026\"}"); log "claim-owner http=$code"
  t="$(token)"; [ -n "$t" ] || { log "login failed"; exit 1; }
  code=$(curl -s -o /dev/null -w '%{http_code}' -X POST $API/channels -H "Authorization: Bearer $t" -H 'content-type: application/json' -d '{"handle":"drill","display_name":"REC-03 drill channel"}'); log "channel http=$code"
  vid=$(curl -sf -X POST $API/channels/drill/videos -H "Authorization: Bearer $t" -H 'content-type: application/json' -d '{"title":"REC-03 fixture v0.6.3","privacy":"public"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["id"])'); echo "$vid" > $R/video_id; log "video id=$vid"
  code=$(curl -s -o $R/upload.json -w '%{http_code}' -X POST "$API/videos/$vid/file" -H "Authorization: Bearer $t" -F "file=@$R/fx/fixture.mp4;type=video/mp4"); log "upload http=$code"
  for i in $(seq 1 120); do st=$(curl -sf -H "Authorization: Bearer $t" "$API/videos/$vid" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("state"))'); [ "$st" = published ] && break; sleep 5; done; log "state=$st after $((i*5))s"
  fingerprint | tee $R/fp.data; counts; ledger; probe
  facts "state=$st" "fp=$(cat $R/fp.data)" "counts=$(counts)" "ledger=$(ledger)" "probe=$(probe)"
  ;;
fp)
  fingerprint | tee "$R/fp.$2"; counts; ledger; probe; echo "renditions_rows=$(psq 'SELECT count(*) FROM video_renditions') files_rows=$(psq 'SELECT count(*) FROM video_files')"
  facts "fp=$(cat "$R/fp.$2")" "counts=$(counts)" "ledger=$(ledger)" "probe=$(probe)"
  ;;
backup)
  log "backup.sh at $OLD (pre-upgrade dump)"; asv ./deploy/backup.sh; rc=$?; find "$DIR/backups" -maxdepth 1 -type f -newer "$R/fixture.sha" | sort
  d=$(find "$DIR/backups" -maxdepth 1 -name "vidra-*.dump.gz" -newer "$R/fixture.sha" | sort | tail -1); echo "$d" > "$R/dump144"; log "dump144=$d exit=$rc"
  facts "backup_exit=$rc" "dump144=$d"
  ;;
inject)
  if [ "${REC03_INJECT:-column}" = dirty ]; then
    log "inject: mark the core ledger DIRTY at its current version (this pair ships no new migration, so the failure the migrator must refuse is a dirty ledger)"
    psq "UPDATE schema_migrations SET dirty = true"; ledger
    facts injected=dirty_ledger "ledger=$(ledger)"
  else
    log "inject: pre-create the column migration 0145 adds (ALTER TABLE ... ADD COLUMN paused_reason has no IF NOT EXISTS)"
    psq "ALTER TABLE storage_migrations ADD COLUMN paused_reason TEXT NOT NULL DEFAULT ''"; ledger
    facts injected=paused_reason "ledger=$(ledger)"
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
    log "pin-release.sh failed — falling back to the v0.6.4-era runbook: tree at tag + rewrite pins as vidra"
    su - vidra -c "git -C $DIR checkout --detach --quiet $NEW && cd $DIR && python3 - <<'PY'
import re,os
p='env/production.env'; s=open(p).read()
for k in ('VIDRA_CORE_TAG','VIDRA_USER_TAG','VIDRA_SEARCH_TAG'):
    s=re.sub(r'(?m)^'+k+r'=.*$', k+'=$NEW', s)
tmp=p+'.tmp'; open(tmp,'w').write(s); os.chmod(tmp,0o600); os.replace(tmp,p)
PY"
    grep -E '^VIDRA_[A-Z_]*TAG=' $DIR/env/production.env
  fi
  log "deploy.sh (expected: abort at 3/6 migrations, no restart)"; asv ./deploy/deploy.sh; rc=$?; log "deploy.sh exit=$rc"
  imgs; ledger; probe; fingerprint | tee $R/fp.fail
  facts pin_release_exit=$prc deploy_exit=$rc "images=$(imgs)" "ledger=$(ledger)" "probe=$(probe)" "fp=$(cat $R/fp.fail)"
  ;;
recover)
  log "runbook: migrate version, undo partial effect, force N-1, rerun"
  asv "./deploy/compose.sh run --rm migrate migrate version"
  if [ "${REC03_INJECT:-column}" = dirty ]; then
    cur=$(psq "SELECT version FROM schema_migrations"); log "dirty at $cur: nothing partial to undo; force the ledger clean at the SAME version"
    asv "./deploy/compose.sh run --rm migrate migrate force $cur --yes-i-know"; log "force exit=$?"
  else
    psq "ALTER TABLE storage_migrations DROP COLUMN paused_reason"
    asv "./deploy/compose.sh run --rm migrate migrate force 144 --yes-i-know"; log "force exit=$?"
  fi
  asv ./deploy/deploy.sh; rc=$?; log "deploy.sh exit=$rc"
  imgs; ledger; probe; fingerprint | tee $R/fp.recover; counts
  facts deploy_exit=$rc "images=$(imgs)" "ledger=$(ledger)" "probe=$(probe)" "fp=$(cat $R/fp.recover)" "counts=$(counts)"
  ;;
backup2)
  log "backup.sh at $NEW (post-upgrade dump) + a post-backup marker write"
  asv ./deploy/backup.sh; rc=$?; d=$(find "$DIR/backups" -maxdepth 1 -name "vidra-*.dump.gz" -newer "$(cat "$R/dump144")" | sort | tail -1); echo "$d" > "$R/dump146"; log "dump146=$d exit=$rc"
  t="$(token)"; vid=$(cat $R/video_id)
  code=$(curl -s -o /dev/null -w '%{http_code}' -X PATCH "$API/videos/$vid" -H "Authorization: Bearer $t" -H 'content-type: application/json' -d '{"title":"REC-03 fixture RENAMED after the 146 backup"}'); log "marker PATCH http=$code"; counts
  facts "backup_exit=$rc" "dump146=$d" "marker_http=$code" "counts=$(counts)"
  ;;
rollback)
  log "rollback.sh $OLD (app-only; the schema stays where the upgrade left it)"; asv ./deploy/rollback.sh "$OLD"; rc=$?; log "rollback.sh exit=$rc"
  imgs; ledger; probe; fingerprint | tee $R/fp.rollback; counts; grep -E '^VIDRA_[A-Z_]*TAG=' $DIR/env/production.env
  facts rollback_exit=$rc "images=$(imgs)" "ledger=$(ledger)" "probe=$(probe)" "fp=$(cat $R/fp.rollback)" "counts=$(counts)"
  ;;
restore-refuse)
  if [ "${REC03_SAME_SCHEMA:-0}" = 1 ]; then log "not applicable: $OLD and $NEW carry the same schema, so no dump can be ahead of the pinned binary"; facts not_applicable=same_schema; exit 0; fi
  log "restore.sh of the newer-schema dump under $OLD pins — expected refusal BEFORE dropdb"; before="$(counts)"
  asv "./deploy/restore.sh --yes $(cat $R/dump146)"; rc=$?; log "restore.sh exit=$rc"
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
  asv "./deploy/restore.sh --yes $(cat $R/dump144)"; rc=$?; log "restore.sh exit=$rc"
  imgs; ledger; probe; fingerprint | tee $R/fp.restore; counts
  facts restore_exit=$rc "images=$(imgs)" "ledger=$(ledger)" "probe=$(probe)" "fp=$(cat $R/fp.restore)" "counts=$(counts)"
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
