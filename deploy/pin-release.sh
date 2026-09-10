#!/usr/bin/env bash
#
# Pin this host to a released tag — the two steps an operator otherwise does by
# hand, as ONE command, as the checkout owner:
#
#   1. move this meta-repo checkout to <tag>   (compose files, Caddyfile, scripts)
#   2. set VIDRA_CORE_TAG / VIDRA_USER_TAG / VIDRA_SEARCH_TAG=<tag> in the env file
#
#   ./deploy/pin-release.sh v0.6.4        # then: ./deploy/deploy.sh
#
# WHY THIS EXISTS (beta, 2026-09-10)
#
# deploy.sh refuses, on purpose, to move the checkout it runs from: bash reads a
# script incrementally, and a checkout underneath a running deploy.sh would
# execute half of one revision and half of another. So the runbook told the
# operator to fetch and check out the tag themselves, then edit the env file.
# Both steps got done in a root shell. A root-run `git fetch` in a checkout
# owned by `vidra` leaves object directories only root can write — 74 of them
# on beta — and the next deploy AS vidra dies inside `git fetch` with
# "insufficient permission for adding an object". The hand edit, done twice,
# left two copies of every production secret in env/ under names nothing
# ignored. Git's own refusal to run as root in somebody else's checkout
# ("dubious ownership") would have prevented the first; it had been switched
# off in root's ~/.gitconfig to make the runbook's step work.
#
# This script removes the reason to open that shell at all, and closes both
# failure modes on its own:
#   - it REFUSES to run as root, before touching anything, so the wrong shell
#     gets an explanation instead of a silently poisoned checkout;
#   - it snapshots the env file OUTSIDE the checkout (deploy/backup-env.sh), so
#     there is never a reason to `cp production.env production.env.bak`.
#
# ORDERING: preflight → fetch → checkout <tag> → snapshot env → rewrite pins.
# The checkout goes first because it is the step git can refuse (a dirty
# tracked file), and a refusal there leaves the env file untouched — so the
# tree and the pins never disagree, which is exactly the skew REL-01 recorded
# (an env file naming a release the tree is not on; deploy.sh then runs those
# images against the previous revision's compose files). If a rewrite fails
# after the checkout, the snapshot is put back for the same reason.
#
# The body is a function called on the last line, so bash has parsed every
# statement before the checkout changes the file it is reading from.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
ENV_FILE="${ENV_FILE:-env/production.env}"
log() { printf '[pin] %s\n' "$*"; }
die() { printf '[pin] ERROR: %s\n' "$*" >&2; exit 1; }
# env_set_key lives in deploy/lib.sh — the same rewrite rollback.sh uses, so a
# pin looks the same whichever script wrote it. Sourced after log/die and
# ENV_FILE, which is the contract lib.sh documents.
# shellcheck source=deploy/lib.sh
. "$REPO_ROOT/deploy/lib.sh"

main() {
  local tag="${1:-}" owner snapshot key
  [ $# -eq 1 ] || die "usage: $0 <vMAJOR.MINOR.PATCH>"
  case "$tag" in
    v[0-9]*.[0-9]*.[0-9]*) ;;
    *) die "$tag is not a vMAJOR.MINOR.PATCH tag — releases are semver tags (see 'Cutting a release' in deploy/README.md)" ;;
  esac

  # Before ANY git command. Root's git succeeds in a checkout it does not own
  # (if someone has added safe.directory for it) and leaves objects the deploy
  # user cannot write; the failure surfaces one deploy later, in a different
  # shell, as a git error that names none of this.
  owner="$(stat -c %U "$REPO_ROOT" 2>/dev/null || stat -f %Su "$REPO_ROOT")"  # GNU, then BSD
  if [ "$(id -u)" -eq 0 ]; then
    die "refusing to run as root. This checkout belongs to '${owner}'; git objects written by root are unwritable for the deploy user and break the next deploy. Run it as the owner: sudo -u ${owner} -- $0 ${tag}"
  fi
  [ -f "$ENV_FILE" ] || die "env file not found: $ENV_FILE"
  [ -d "$REPO_ROOT/.git" ] || die "$REPO_ROOT is not a git checkout. An unpacked bundle is pinned by unpacking the release's bundle over it — see 'Upgrading a bundle install' in deploy/README.md"
  command -v python3 >/dev/null 2>&1 || die "Python 3 is required for checkout preflight; install python3 first"
  # Every finding is fatal here, as in deploy.sh: pinning is deploy-side work,
  # and this is the moment to fix the host, not to work around it.
  python3 "$REPO_ROOT/deploy/checkout-hygiene.py" check "$REPO_ROOT" || die "checkout hygiene preflight failed"

  log "fetching tags from origin"
  git -C "$REPO_ROOT" fetch --tags --force --quiet origin \
    || die "git fetch failed — nothing was changed"
  git -C "$REPO_ROOT" rev-parse -q --verify "refs/tags/${tag}^{commit}" >/dev/null \
    || die "${tag} is not a tag on origin — was the release cut? (deploy/release.sh --yes ${tag}). Nothing was changed"
  log "checking out ${tag}"
  git -C "$REPO_ROOT" checkout --detach --quiet "$tag" \
    || die "could not check out ${tag} — nothing else was changed; the env file still names the previous release"
  log "checkout: $(git -C "$REPO_ROOT" describe --tags --always)"

  snapshot="$(ENV_FILE="$ENV_FILE" bash "$REPO_ROOT/deploy/backup-env.sh")" || die "env snapshot failed — the tree is at ${tag}, the env file is untouched"
  log "env snapshot: ${snapshot}"
  for key in VIDRA_CORE_TAG VIDRA_USER_TAG VIDRA_SEARCH_TAG; do
    if ! env_set_key "$key" "$tag"; then
      cat "$snapshot" > "$ENV_FILE"
      die "could not set ${key} — env file restored from ${snapshot}; the tree is at ${tag}"
    fi
  done
  log "pinned ${tag}: core=$(env_get VIDRA_CORE_TAG) user=$(env_get VIDRA_USER_TAG) search=$(env_get VIDRA_SEARCH_TAG)"
  log "next: ./deploy/deploy.sh"
}
main "$@"
