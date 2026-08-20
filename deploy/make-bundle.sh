#!/usr/bin/env bash
#
# Assemble the no-git deployment bundle — the tarball an operator can unpack on
# a host with no git, no clone and no knowledge of this repository's layout, and
# then deploy from.
#
#   ./deploy/make-bundle.sh --core ../vidra-core --tag v0.3.0 --out dist/vidra-bundle_v0.3.0.tar.gz
#
# THIS INTERFACE IS A CROSS-REPO CONTRACT. vidra-core's release-assets.yml calls
# exactly this — `--core <path> --tag <tag> --out <file>` — from a checkout of
# this repo at the SAME tag, and uploads the result next to the CLI binaries with
# its checksum in the release's one SHA256SUMS. Changing the flags changes that
# workflow too, in the same release.
#
# WHAT GOES IN, and why it is so small
#
# A production deploy needs exactly two things from the component repositories:
# vidra-core/docker-compose.yml (this repo's docker-compose.yml `include:`s it —
# without it the production model does not exist at all) and the handful of
# vidra-core/deploy/** files the compose model BIND-MOUNTS. Nothing else: the
# images come from GHCR, the migrations are compiled into them, and the `vidra`
# CLI is its own release asset. So the bundle carries this repo's deployment
# tree plus those files AT THE SAME RELATIVE PATHS a checkout would have them —
# `vidra-core/docker-compose.yml`, `vidra-core/deploy/...` — which is what lets
# compose, the Caddyfile and every script here work unchanged, with no path
# surgery and no bundle-specific mode.
#
# WHAT STAYS OUT, deliberately:
#
#   * bootstrap.sh — it clones the three component repositories. In a tree that
#     exists precisely because there is no git, an entry point whose whole job is
#     `git clone` is a trap.
#   * docker-compose.override.yml — a plain `docker compose` AUTO-LOADS it, and
#     it re-adds the dev build contexts and the dev search wiring. In a bundle
#     those contexts do not exist, so the file would turn every bare compose
#     command into an error about a directory nobody asked for.
#   * docker-compose.dev.yml — the hot-reload overlay, which builds both Go
#     repositories from source. Same reason, one step further.
#   * the component checkouts themselves. That is the point.
#
# THE MARKER. `vidra-bundle.manifest` at the tree root is how deploy.sh and
# rollback.sh recognise a bundle: it is never committed to git, so its PRESENCE
# is the statement "this tree was unpacked, not cloned". It also carries the
# schema version those scripts would otherwise compute from
# `ls vidra-core/migrations/*.up.sql` — the migrations are not in the bundle, and
# the second opinion they give the migrator is worth keeping.
#
# DETERMINISM. Sorted member order, one fixed mtime, uid/gid 0, normalised modes
# and `gzip -n` (no name, no timestamp in the header), so two runs from the same
# two commits produce byte-identical bytes. The CLI binaries next to it in the
# release already have that property; an asset that does not is an asset nobody
# can reproduce and therefore nobody can audit.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

log() { printf '[bundle] %s\n' "$*"; }
die() { printf '[bundle] ERROR: %s\n' "$*" >&2; exit 1; }

usage() {
  sed -n '2,10p' "$0"
}

CORE=""
TAG=""
OUT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --core) CORE="${2:-}"; shift 2 ;;
    --tag)  TAG="${2:-}";  shift 2 ;;
    --out)  OUT="${2:-}";  shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; die "unknown argument: $1" ;;
  esac
done

[ -n "$CORE" ] || { usage >&2; die "--core <path to a vidra-core checkout> is required"; }
[ -n "$TAG" ]  || { usage >&2; die "--tag <vX.Y.Z> is required — it names the release this bundle belongs to and it is written into the manifest"; }
[ -n "$OUT" ]  || { usage >&2; die "--out <file.tar.gz> is required"; }

[ -d "$CORE" ] || die "--core '$CORE' is not a directory"
CORE="$(cd "$CORE" && pwd)"
[ -f "$CORE/docker-compose.yml" ] \
  || die "$CORE/docker-compose.yml does not exist, so --core does not point at a vidra-core checkout. That one file is what this repo's docker-compose.yml include:s; without it the production model cannot be rendered at all."
[ -d "$CORE/migrations" ] \
  || die "$CORE/migrations does not exist, so the bundle's core_schema_version cannot be computed. It is the second opinion deploy.sh checks the migrator's own ledger against."

# Absolute, and its directory created, BEFORE the staging tree is built: the tar
# runs from inside a temporary directory, where a relative --out would land
# somewhere that is deleted a line later.
case "$OUT" in
  /*) ;;
  *) OUT="$PWD/$OUT" ;;
esac
mkdir -p "$(dirname "$OUT")"

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT INT TERM
TREE="$STAGE/tree"
mkdir -p "$TREE"

# copy_in <relative path> — one file from this repo into the same relative path
# in the bundle. Missing is fatal: every path below is load-bearing for either a
# render or a deploy, and a bundle that quietly lacks one fails on the operator's
# host instead of on the release runner.
copy_in() {
  local rel="$1"
  [ -f "$REPO_ROOT/$rel" ] || die "$rel is missing from this checkout — the bundle would be incomplete"
  mkdir -p "$TREE/$(dirname "$rel")"
  cp "$REPO_ROOT/$rel" "$TREE/$rel"
}

log "meta tree from $REPO_ROOT"
copy_in docker-compose.yml
copy_in docker-compose.prod.yml
copy_in docker-compose.external-postgres.yml
copy_in docker-compose.external-redis.yml
copy_in LICENSE

# Every template, not just production.env.example: `vidra setup --template` is
# pointed at one of them by name, and an operator running a staging instance from
# a bundle should not have to go and find the file the docs quote.
for f in "$REPO_ROOT"/env/*.env.example; do
  [ -e "$f" ] || die "env/*.env.example matched nothing — the setup wizard is rendered FROM one of these"
  copy_in "env/$(basename "$f")"
done

# The whole deploy/ directory, minus three things:
#   Caddyfile.local  generated per host, gitignored, and carries a real domain
#   .*               the setup engine's atomic-write temp files
#   make-bundle.sh   this script. It needs a vidra-core checkout to run, which is
#                    exactly what a bundle tree does not have.
# Everything else — deploy.sh, rollback.sh, restore.sh, backup.sh, provision.sh,
# compose.sh, lib.sh, release.sh, the Caddyfile template, the systemd units the
# backup timer needs, cloud-init.yaml.example and README.md — is what an operator
# runs or reads on the host.
while IFS= read -r f; do
  copy_in "deploy/$(basename "$f")"
done <<EOF
$(LC_ALL=C find "$REPO_ROOT/deploy" -maxdepth 1 -type f \
    ! -name 'Caddyfile.local' ! -name '.*' ! -name 'make-bundle.sh' | LC_ALL=C sort)
EOF

# --- the component half -----------------------------------------------------
# vidra-core/docker-compose.yml, plus every path it BIND-MOUNTS out of the
# checkout. The mount list is DERIVED from the file rather than hard-coded here:
# a new `- ./deploy/something:/…:ro` in vidra-core would otherwise ship a bundle
# whose media or IPFS profile crash-loops on a bind-mount source Docker created
# as an empty directory — and nothing in either repository would have noticed.
# The paths are printed below so a review of a release can see exactly what was
# picked up.
mkdir -p "$TREE/vidra-core"
cp "$CORE/docker-compose.yml" "$TREE/vidra-core/docker-compose.yml"

MOUNTS="$(
  grep -oE '^[[:space:]]*-[[:space:]]*\./[^:]+:' "$CORE/docker-compose.yml" \
    | sed -e 's/^[[:space:]]*-[[:space:]]*\.\///' -e 's/:$//' \
    | LC_ALL=C sort -u
)"
[ -n "$MOUNTS" ] \
  || die "found no './…' bind mounts in $CORE/docker-compose.yml. That file has always mounted at least the media nginx template and the otel collector config; finding none means this grep no longer matches the file's syntax, and a bundle built on it would be missing every one of them."

count=0
while IFS= read -r rel; do
  [ -n "$rel" ] || continue
  [ -f "$CORE/$rel" ] \
    || die "vidra-core/docker-compose.yml bind-mounts ./$rel but $CORE/$rel does not exist. A missing bind-mount source is created by Docker as an empty DIRECTORY and the container crash-loops on it, so this is refused here rather than discovered on a production host."
  mkdir -p "$TREE/vidra-core/$(dirname "$rel")"
  cp "$CORE/$rel" "$TREE/vidra-core/$rel"
  log "  vidra-core/$rel"
  count=$((count + 1))
done <<EOF
$MOUNTS
EOF
log "vidra-core: docker-compose.yml + $count bind-mounted file(s)"

# --- the manifest -----------------------------------------------------------
# core_schema_version is computed with the SAME pipeline deploy.sh uses on a git
# checkout (`ls vidra-core/migrations/*.up.sql` -> leading number, numerically
# highest), and stored with its filename zero-padding intact — deploy.sh applies
# `10#` to it either way, so the two paths compare identical values.
# shellcheck disable=SC2012  # ls is deliberate: these filenames are numeric by construction.
CORE_SCHEMA="$(ls -1 "$CORE"/migrations/*.up.sql 2>/dev/null | awk -F/ '{print $NF}' | awk -F_ '{print $1}' | sort -n | tail -1)"
[ -n "$CORE_SCHEMA" ] || die "no *.up.sql files in $CORE/migrations — the expected schema version cannot be determined"

git_head() {
  git -C "$1" rev-parse HEAD 2>/dev/null || printf 'unknown'
}
META_COMMIT="$(git_head "$REPO_ROOT")"
CORE_COMMIT="$(git_head "$CORE")"

# key=value, one per line, no quoting: deploy.sh and rollback.sh read it with the
# same `sed`-based reader lib.sh uses for env files, and `vidra doctor` may later
# read it from Go. Nothing here is a secret and nothing here is operator-edited.
cat > "$TREE/vidra-bundle.manifest" <<EOF
# vidra deployment bundle. The PRESENCE of this file is what tells deploy.sh and
# rollback.sh that this tree was unpacked rather than cloned: they then skip the
# checkout-sync loop (there is nothing to sync) and read core_schema_version from
# here instead of from vidra-core/migrations, which a bundle does not carry.
#
# Generated by deploy/make-bundle.sh. Do not edit: the schema version below is
# the one the images in this release expect, and a hand-edited value turns
# deploy.sh's independent check of the migrator into an agreement with whoever
# typed it.
tag=$TAG
core_schema_version=$CORE_SCHEMA
meta_commit=$META_COMMIT
core_commit=$CORE_COMMIT
EOF

# --- deterministic tar ------------------------------------------------------
# Modes are SET rather than copied: cp applies the builder's umask to new files,
# so an operator with umask 077 and a CI runner with 022 would otherwise produce
# two different tarballs from one commit. .sh is the executable set; everything
# else is data.
find "$TREE" -type d -exec chmod 0755 {} +
find "$TREE" -type f -exec chmod 0644 {} +
find "$TREE" -type f -name '*.sh' -exec chmod 0755 {} +
# One fixed mtime for every member, interpreted in UTC so the builder's timezone
# does not leak into the archive.
TZ=UTC find "$TREE" -exec touch -t 197001010000.00 {} +

# GNU tar and bsdtar spell "own nothing, sort by name" differently, and this
# script runs on both (Ubuntu in CI, macOS on a maintainer's laptop). The member
# list is produced by find + sort instead of by either tar's own --sort, so the
# ORDER is identical on both regardless of which flags exist.
TAR_FLAGS=(--format=ustar --no-recursion -T -)
if tar --version 2>/dev/null | head -n1 | grep -qi 'gnu tar'; then
  TAR_FLAGS=(--owner=0 --group=0 --numeric-owner "${TAR_FLAGS[@]}")
else
  TAR_FLAGS=(--uid 0 --gid 0 --uname '' --gname '' "${TAR_FLAGS[@]}")
fi

# `gzip -n`: without it the compressed stream carries the source filename and the
# time of compression, and two identical trees produce two different files.
( cd "$TREE" && LC_ALL=C find . -print | LC_ALL=C sort | tar -cf - "${TAR_FLAGS[@]}" ) \
  | gzip -9n > "$OUT"

log "wrote $OUT"
log "$(tar -tzf "$OUT" | LC_ALL=C sort | wc -l | tr -d ' ') members, $(wc -c < "$OUT" | tr -d ' ') bytes"
log "tag=$TAG core_schema_version=$CORE_SCHEMA meta_commit=$META_COMMIT core_commit=$CORE_COMMIT"
if command -v sha256sum >/dev/null 2>&1; then
  log "sha256 $(sha256sum "$OUT" | awk '{print $1}')"
elif command -v shasum >/dev/null 2>&1; then
  log "sha256 $(shasum -a 256 "$OUT" | awk '{print $1}')"
fi
