#!/usr/bin/env bash
# Print a private snapshot path for manual edits and rollback's recovery path.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
exec python3 "$REPO_ROOT/deploy/checkout-hygiene.py" snapshot "$REPO_ROOT" \
  --env-file "${ENV_FILE:-env/production.env}" \
  --directory "${VIDRA_ENV_BACKUP_DIR:-$HOME/.local/state/vidra/env-history}"
