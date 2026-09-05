#!/usr/bin/env bash
# A02: create a NEW Ubuntu VM; preserve it stopped for A03 or failure diagnosis.
# Usage: bash tests/blank-server-smoke.sh MANIFEST.json NEW_OUTPUT_DIRECTORY
set -euo pipefail
log()  { printf '[a02] %s\n' "$*"; }
die()  { printf '[a02] ERROR: %s\n' "$*" >&2; exit 1; }
step() { printf '\n[a02] ===== %s =====\n' "$*"; }
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[ "$#" -eq 2 ] || die "usage: $0 MANIFEST.json NEW_OUTPUT_DIRECTORY"
for tool in multipass python3 curl; do
  command -v "$tool" >/dev/null || die "required tool missing: $tool"
done
REVISION="$(python3 "$ROOT/tests/blank_server_smoke.py" --validate "$1")"
[ ! -e "$2" ] || die "output exists; preserve prior evidence and use a new directory"
mkdir -p "$(dirname "$2")"
mkdir -m 700 "$2"
OUT="$(cd "$2" && pwd)"
cp "$1" "$OUT/candidate.json"
cp "$ROOT/tests/blank_server_smoke.py" "$OUT/blank_server_smoke.py"
VM="vidra-a02-$(date -u +%Y%m%d%H%M%S)-$$"
printf '%s\n' "$VM" > "$OUT/vm-name.txt"
printf 'UNVERIFIED\n' > "$OUT/status.txt"
# A unique new name is mandatory: never accept an existing operator VM, attach
# the workstation Docker socket, or install packages on the workstation.
step "download immutable installer"
curl -fsSL "https://raw.githubusercontent.com/yegamble/vidra/${REVISION}/install.sh" -o "$OUT/install.sh"
finish() {
  local rc=$?
  trap - EXIT
  if ! multipass info "$VM" --format json > "$OUT/vm.json" 2> "$OUT/vm-info-error.txt"; then rc=1; fi
  if ! multipass transfer "$VM:/home/ubuntu/a02-evidence/result.json" "$OUT/result.json" 2> "$OUT/evidence-error.txt"; then rc=1; fi
  if ! python3 -c 'import json,sys; assert json.load(open(sys.argv[1]))["status"] == "PASS"' "$OUT/result.json"; then rc=1; fi
  if ! multipass stop "$VM" > "$OUT/stop.log" 2>&1; then rc=1; fi
  if [ "$rc" -eq 0 ]; then printf 'PASS\n' > "$OUT/status.txt"; else printf 'FAIL\n' > "$OUT/status.txt"; fi
  log "evidence: $OUT; retained VM: $VM; status: $(cat "$OUT/status.txt")"
  exit "$rc"
}
trap finish EXIT
step "create blank Ubuntu 24.04 VM $VM"
multipass launch 24.04 --name "$VM" --cpus 2 --memory 4G --disk 20G --timeout 600 > "$OUT/launch.log" 2>&1
for file in candidate.json install.sh blank_server_smoke.py; do
  multipass transfer "$OUT/$file" "$VM:/home/ubuntu/$file"
done
multipass exec "$VM" -- sudo sh -c 'hostname > /run/vidra-a02-disposable'
step "execute real installer, corruption, rerun and image checks"
multipass exec "$VM" -- sudo python3 /home/ubuntu/blank_server_smoke.py --guest /home/ubuntu/candidate.json \
  > "$OUT/guest-progress.log" 2>&1
