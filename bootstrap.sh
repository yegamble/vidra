#!/usr/bin/env bash
# Clone or update the two Vidra component repositories into this meta-repo.
#
# Idempotent: clones a component if it is missing, otherwise fast-forward pulls.
# The ./vidra-core and ./vidra-user directories are independent git checkouts and
# are git-ignored by this meta-repo.
set -euo pipefail

OWNER="${VIDRA_GH_OWNER:-yegamble}"
COMPONENTS=(vidra-core vidra-user)

for r in "${COMPONENTS[@]}"; do
  if [ -d "$r/.git" ]; then
    echo "==> updating $r"
    git -C "$r" pull --ff-only
  elif [ -e "$r" ]; then
    echo "!!  $r exists but is not a git checkout — skipping (move it aside and re-run)." >&2
  else
    echo "==> cloning $r"
    git clone "https://github.com/$OWNER/$r.git" "$r"
  fi
done

cat <<'EOF'

Done. Next:
  docker compose --profile core up --build                         # backend on http://localhost:8080
  cd vidra-user && npm ci && NEXT_PUBLIC_API_BASE_URL=http://localhost:8080 npm run dev
EOF
