#!/usr/bin/env bash
# Continue an A02 disposable VM, keeping private logs and test secrets in guest.
set -euo pipefail
log() { printf '[a03] %s\n' "$*"; }
die() { printf '[a03] ERROR: %s\n' "$*" >&2; exit 1; }
step() { printf '\n[a03] ===== %s =====\n' "$*"; }
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[ "$#" -eq 3 ] || die "usage: $0 A02_OUTPUT_DIRECTORY MANIFEST NEW_OUTPUT_DIRECTORY"
VM="$(cat "$1/vm-name.txt")"
[[ "$VM" =~ ^vidra-a02-[0-9]+-[0-9]+$ ]] || die "not an A02 VM"
python3 "$ROOT/tests/blank_server_smoke.py" --validate "$2" >/dev/null
[ ! -e "$3" ] || die "output exists; preserve evidence"
mkdir -m 700 "$3"
OUT="$(cd "$3" && pwd)"
STAGE="/home/ubuntu/vidra-a03-$(date -u +%Y%m%d%H%M%S)-$$"
printf '%s\n' "$STAGE" > "$OUT/guest-stage.txt"
printf '%s\n' "$VM" > "$OUT/vm-name.txt"
finish() {
  local rc=$?
  trap - EXIT
  if ! multipass transfer "$VM:$STAGE/result.json" "$OUT/result.json"; then rc=1; fi
  if ! python3 -c 'import json,sys; assert json.load(open(sys.argv[1]))["status"] == "PASS"' "$OUT/result.json"; then rc=1; fi
  if ! multipass stop "$VM" > "$OUT/stop.log" 2>&1; then rc=1; fi
  if [ "$rc" -eq 0 ]; then printf 'PASS\n' > "$OUT/status.txt"; else printf 'FAIL\n' > "$OUT/status.txt"; fi
  log "evidence: $OUT; private logs retained at $VM:$STAGE/private"
  exit "$rc"
}
trap finish EXIT
step "start retained disposable VM"
multipass start "$VM" > "$OUT/start.log" 2>&1
multipass exec "$VM" -- mkdir "$STAGE"
multipass transfer "$2" "$VM:$STAGE/candidate.json"
multipass transfer "$ROOT/deploy/deploy.sh" "$VM:$STAGE/deploy-under-test.sh"
for file in runtime_smoke.py blank_server_smoke.py; do
  multipass transfer "$ROOT/tests/$file" "$VM:$STAGE/$file"
done
step "verify real released-stack startup and migration refusal"
multipass exec "$VM" -- sudo python3 "$STAGE/runtime_smoke.py" "$STAGE" > "$OUT/progress.log" 2>&1
