#!/usr/bin/env bash
# Shared helpers for the reference-pinning spike. Sourced by every t*.sh.
# shellcheck disable=SC2034  # a sourced library: the constants are read by the t*.sh callers, not here
set -euo pipefail

SPIKE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="$SPIKE_DIR/out"
DATA="$SPIKE_DIR/origin-root"        # what the origin serves == what we stream to Kubo
MODEFILE="$SPIKE_DIR/mode.txt"
ORIGIN_LOG="$OUT/origin-requests.txt"

KUBO_IMAGE="ipfs/kubo:v0.43.0"
KUBO_NAME="refpin-spike-kubo"
KUBO_VOL="refpin-spike-repo"
API="http://127.0.0.1:15001/api/v0"
GW="http://127.0.0.1:18080"
ORIGIN_PORT=18090
# Kubo runs in a container; the origin runs on the macOS host. Docker Desktop
# maps host.docker.internal to the host, so this is the URL Kubo must fetch.
ORIGIN_BASE="http://host.docker.internal:$ORIGIN_PORT"

mkdir -p "$OUT" "$DATA"

step() { printf '\n=== %s ===\n' "$*"; }
log()  { printf '%s\n' "$*"; }
die()  { printf 'FATAL: %s\n' "$*" >&2; exit 1; }

# Kubo RPC is POST-only.
api() { local ep="$1"; shift; curl -sS -X POST "$API/$ep" "$@"; }

origin_mode() { printf '%s' "$1" > "$MODEFILE"; }

# Mark a spot in the origin log so a test can count only its own requests.
origin_mark() { printf -- '---- MARK %s ----\n' "$1" >> "$ORIGIN_LOG"; }
origin_since() { awk -v m="---- MARK $1 ----" 'f{print} $0==m{f=1}' "$ORIGIN_LOG"; }

reposize() { api repo/stat | python3 -c 'import json,sys; print(json.load(sys.stdin)["RepoSize"])'; }

# Poll instead of sleeping (foreground sleep is blocked in this harness).
wait_for() { # wait_for <desc> <cmd...>
  local desc="$1"; shift
  local i=0
  until "$@" >/dev/null 2>&1; do
    i=$((i+1)); [ "$i" -gt 600 ] && die "timeout waiting for $desc"
    python3 -c 'import time; time.sleep(0.25)'
  done
  log "ready: $desc (after $i polls)"
}

# Wipe every recursive pin and gc, so a test starts from a known-empty store.
# (Tests share one daemon; without this, refs left by an earlier test make
# "first writer wins" results ambiguous.)
clean_slate() {
  api "pin/ls?type=recursive&enc=json" \
    | python3 -c 'import json,sys
d=json.load(sys.stdin).get("Keys",{})
print("\n".join(d.keys()))' \
    | while read -r c; do [ -n "$c" ] && api "pin/rm?arg=$c" >/dev/null 2>&1 || true; done
  api "repo/gc?enc=json&quiet=true" >/dev/null
  echo "clean slate: $(api 'filestore/ls?enc=json' | grep -c . || true) filestore refs, RepoSize=$(reposize)"
}
