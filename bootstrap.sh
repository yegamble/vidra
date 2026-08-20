#!/usr/bin/env bash
# Clone or update the two Vidra component repositories into this meta-repo.
#
# Idempotent: clones a component if it is missing, otherwise fast-forward pulls.
# The ./vidra-core and ./vidra-user directories are independent git checkouts and
# are git-ignored by this meta-repo.
set -euo pipefail

OWNER="${VIDRA_GH_OWNER:-yegamble}"
COMPONENTS=(vidra-core vidra-user vidra-search)

# Optional ref pin (readiness plan step 4.5). Unset — the default — keeps the
# historical behaviour exactly: clone the default branch, or fast-forward an
# existing checkout. Set VIDRA_REF to a tag or a commit sha to put all three
# components on precisely that ref instead:
#
#   VIDRA_REF=v0.1.0 ./bootstrap.sh
#
# That is what a production host wants. The droplet runs the meta-repo's compose
# files, but `docker-compose.yml` `include:`s vidra-core's — so a floating
# component checkout means the compose definition being applied is not the one
# that was reviewed with the release. The checkout is detached on purpose: a
# deploy host tracks a release, not a branch.
#
# MERGE-ORDER NOTE: with VIDRA_REF unset this syncs the components to their
# DEFAULT BRANCH. The compose files in this repo run the migration one-shots as
# `migrate up` on the service images, a subcommand that exists only from the
# releases listed in deploy/README.md ("Upgrade notes: the embedded-migrator tag
# floor"). Against an older component checkout the one-shot starts an API server
# instead of migrating and never exits — i.e. `make dev` / `make dev-hot` hang on
# `migrate`. vidra-core and vidra-search release FIRST; this repo follows.
VIDRA_REF="${VIDRA_REF:-}"

for r in "${COMPONENTS[@]}"; do
  if [ -d "$r/.git" ]; then
    if [ -n "$VIDRA_REF" ]; then
      echo "==> updating $r -> $VIDRA_REF"
      # --force: without it git refuses to move a tag this checkout already
      # has, so a tag re-pointed upstream would pin the stale object forever.
      git -C "$r" fetch --tags --force --prune origin
      git -C "$r" checkout --detach "$VIDRA_REF"
    else
      echo "==> updating $r"
      git -C "$r" pull --ff-only
    fi
  elif [ -e "$r" ]; then
    echo "!!  $r exists but is not a git checkout — skipping (move it aside and re-run)." >&2
  else
    echo "==> cloning $r"
    git clone "https://github.com/$OWNER/$r.git" "$r"
    if [ -n "$VIDRA_REF" ]; then
      echo "==> pinning $r to $VIDRA_REF"
      git -C "$r" checkout --detach "$VIDRA_REF"
    fi
  fi
done

cat <<'EOF'

Done. Next:
  docker compose --profile core up --build                         # backend + search on http://localhost:8080 (search :8081)
  cd vidra-user && npm ci && NEXT_PUBLIC_API_BASE_URL=http://localhost:8080 npm run dev
EOF
