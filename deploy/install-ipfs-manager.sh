#!/usr/bin/env bash
# Install the opt-in manager, without starting/reconfiguring Kubo or the stack.
# Explicit --yes is suitable for provision.sh; target paths are host inputs only.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
log() { printf '[ipfs-manager-install] %s\n' "$*"; }
die() { printf '[ipfs-manager-install] ERROR: %s\n' "$*" >&2; exit 1; }
[ "${1:-}" = '--yes' ] && [ "$#" = 1 ] || die 'usage: sudo deploy/install-ipfs-manager.sh --yes'
[ "$(id -u)" = 0 ] && [ "$(uname -s)" = Linux ] || die 'requires Linux root'
[ -d /run/systemd/system ] || die 'requires systemd'
command -v python3 >/dev/null || die 'install python3 first'
log 'Installing the fixed host manager; no IPFS publication is requested.'
exec python3 "$REPO_ROOT/deploy/ipfs-manager.py" --install --project-dir "$REPO_ROOT" \
  --env-file "${ENV_FILE:-$REPO_ROOT/env/production.env}"
