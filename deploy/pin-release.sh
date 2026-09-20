#!/usr/bin/env bash
#
# Pin this host to a released tag — the two steps an operator otherwise does by
# hand, as ONE command, as the checkout owner:
#
#   1. move this meta-repo checkout to <tag>   (compose files, Caddyfile, scripts)
#   2. set VIDRA_CORE_TAG / VIDRA_USER_TAG / VIDRA_SEARCH_TAG in the env file to
#      the tag the release pairs EACH COMPONENT at
#
#   ./deploy/pin-release.sh v0.6.4        # then: ./deploy/deploy.sh
#
# The nested vidra-core / vidra-user / vidra-search checkouts are NOT moved
# here: deploy.sh's checkout sync moves each of them to its own VIDRA_*_TAG, so
# writing the three keys correctly is what puts each component tree on its own
# component tag — including the vidra-core checkout deploy.sh reads to compute
# the EXPECTED migration version for its independent ledger assertion.
#
# WHY THE THREE KEYS ARE NOT ONE TAG (2026-09-20)
#
# They were, and for exactly as long as every release moved every component.
# v0.7.4 and v0.7.5 re-released vidra-core ALONE and pair vidra-user and
# vidra-search at v0.7.3 (releases/v0.7.5.json states it), so
# `pin-release.sh v0.7.5` wrote VIDRA_USER_TAG=v0.7.5 — and
# ghcr.io/yegamble/vidra-user:v0.7.5 has never existed. The documented upgrade
# command therefore could not deploy the release beta is running: the deploy
# died at `compose pull`, and the only way through was to hand-edit the env
# file, which is the step this script exists to remove.
#
# The pairing comes from releases/<tag>.json — this tree's copy when it has
# one, else the copy deploy/lib.sh's fetch_release_record downloads (the vN
# tree cannot carry vN's record: release.sh tags this repository before any
# image exists). deploy/release-mapping.py resolves it, because that script is
# already the one reader of release records and a second parser in shell would
# drift from it.
#
# NO RECORD IS NOT A REFUSAL. An absent record predicts nothing — most
# releases are uniform — so an offline host, or one running inside the window
# before the record PR merges, still pins all three keys to <tag> exactly as
# before, with a WARNING naming the failure that would follow if <tag> turned
# out to be core-only, and `--component-tag <role>=<tag>` to state the pairing
# by hand. A flag that CONTRADICTS a record that loaded does predict the wrong
# bytes, so that one stops before anything is written.
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
# ORDERING: preflight → fetch → RESOLVE THE PAIRING → snapshot env →
# checkout <tag> → rewrite pins.
# The checkout goes before the rewrite because it is the step git can refuse
# (a dirty tracked file), and a refusal there leaves the env file untouched — so
# the tree and the pins never disagree, which is exactly the skew REL-01
# recorded (an env file naming a release the tree is not on; deploy.sh then runs
# those images against the previous revision's compose files). If a rewrite
# fails after the checkout, the snapshot is put back for the same reason. The
# snapshot goes before the checkout because its helper lives in THIS tree and
# the target release may predate it (v0.6.3 and v0.6.4 do) — see the note at
# the call site.
#
# The pairing is resolved before ALL of those, for two reasons. It must be read
# out of the tree the run STARTED on: releases/<tag>.json is written after the
# tag is cut, so the record for the newest release lives on main and not at the
# tag, and reading it after the checkout would find nothing for exactly the
# releases this exists for. And every refusal it can produce — a nonsense flag,
# a flag contradicting the record — then lands with nothing moved, no snapshot
# taken and the env file byte-for-byte as it was.
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

CHECKER="$REPO_ROOT/deploy/release-mapping.py"
USAGE="usage: $0 <vMAJOR.MINOR.PATCH> [--component-tag <core|user|search>=<tag>]... [--force]"

# The directory a fetched release record is downloaded into. Cleaned up
# however this run ends — a die(), a Ctrl-C during the download, a normal
# exit. Unlike deploy.sh and rollback.sh, this script is EXECUTED rather than
# sourcing its own traps into somebody else's shell, so it can own EXIT here;
# `return 0` is not tidiness but load-bearing, because under `set -e` a
# failing command in an EXIT trap rewrites the exit status (measured in
# lib.sh's own re-check subshell) and would turn a clean pin into a failure.
RECORD_TMPDIR=''
cleanup_record_tmpdir() {
  if [ -n "$RECORD_TMPDIR" ]; then
    rm -rf "$RECORD_TMPDIR" 2>/dev/null \
      || printf '[pin] WARNING: could not remove %s; remove it by hand.\n' "$RECORD_TMPDIR" >&2
  fi
  return 0
}
trap cleanup_record_tmpdir EXIT

# One row of the table printed before anything is written: what each key will
# carry, and on whose authority. An operator who is about to upgrade a
# production host should not have to diff the env file afterwards to find out
# whether a release moved one component or three.
pin_row() {
  local key="$1" value="$2" source="$3" where="$4" origin
  case "$source" in
    record)           origin="$where" ;;
    --component-tag)  origin='--component-tag (by hand, unverified)' ;;
    *)                origin='the release tag (no pairing record)' ;;
  esac
  log "  ${key}=${value}  <- ${origin}"
}

main() {
  local tag='' force='' owner snapshot rc=0 resolved record='' record_from='' paired=''
  local core_tag='' user_tag='' search_tag=''
  local core_from='' user_from='' search_from='' role value source
  local -a overrides=() resolve_args=()

  while [ $# -gt 0 ]; do
    case "$1" in
      --component-tag)
        [ $# -ge 2 ] || die "--component-tag needs a <role>=<tag> value. $USAGE"
        overrides+=(--component-tag "$2"); shift 2 ;;
      --force) force=1; shift ;;
      -*) die "unknown option: $1. $USAGE" ;;
      *)
        [ -z "$tag" ] || die "only one release tag may be given ($tag and $1). $USAGE"
        tag="$1"; shift ;;
    esac
  done
  [ -n "$tag" ] || die "$USAGE"
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
  [ -f "$CHECKER" ] || die "deploy/release-mapping.py is missing from $REPO_ROOT, so this release's component pairing cannot be read. This tree is incomplete or mixes revisions; take deploy/release-mapping.py from the same revision as deploy/pin-release.sh"
  # Every finding is fatal here, as in deploy.sh: pinning is deploy-side work,
  # and this is the moment to fix the host, not to work around it.
  python3 "$REPO_ROOT/deploy/checkout-hygiene.py" check "$REPO_ROOT" || die "checkout hygiene preflight failed"

  # FLAG VALIDATION BEFORE THE FIRST GIT COMMAND. The resolver is the only
  # thing that knows what a --component-tag value may be, and asking it with
  # no record is the cheapest way to ask "are these flags sane?" without a
  # second copy of that rule in shell. Exit 3 is "no record, uniform" — the
  # expected answer with nothing to resolve against — and 1 is a flag that
  # will never be acceptable, whatever record turns up. A typo must not leave
  # a checkout that has already moved.
  #
  # `if`, not `[ ... ] && die`: under `set -e` a trailing `&&` whose test is
  # false makes the whole statement the last command of the script's current
  # list and fires errexit, which would abort a perfectly good run.
  rc=0
  python3 "$CHECKER" resolve --release "$tag" \
    ${overrides[@]+"${overrides[@]}"} >/dev/null || rc=$?
  case "$rc" in
    0|3) ;;
    *) die "nothing was changed" ;;
  esac

  log "fetching tags from origin"
  git -C "$REPO_ROOT" fetch --tags --force --quiet origin \
    || die "git fetch failed — nothing was changed"
  git -C "$REPO_ROOT" rev-parse -q --verify "refs/tags/${tag}^{commit}" >/dev/null \
    || die "${tag} is not a tag on origin — was the release cut? (deploy/release.sh --yes ${tag}). Nothing was changed"

  # THE PAIRING, read off the tree the run STARTED on and before the first
  # mutation. A tree on main carries the records for every published release;
  # a tree already at vN does not carry vN's, which is why the fetch exists.
  if [ -f "$REPO_ROOT/releases/${tag}.json" ]; then
    record="$REPO_ROOT/releases/${tag}.json"
    record_from="releases/${tag}.json"
  else
    # Best-effort, bounded, HTTPS-only, and never fatal — the same helper and
    # the same VIDRA_RECORD_FETCH / VIDRA_RECORD_BASE_URL knobs deploy.sh
    # uses, so a host configured for one is configured for both.
    RECORD_TMPDIR="$(mktemp -d "${TMPDIR:-/tmp}/vidra-record.XXXXXX" 2>/dev/null)" || RECORD_TMPDIR=''
    if [ -z "$RECORD_TMPDIR" ]; then
      log "could not create a temporary directory, so ${tag}'s release record was not fetched"
    elif fetch_release_record "$tag" "$RECORD_TMPDIR/${tag}.json"; then
      record="$RECORD_TMPDIR/${tag}.json"
      record_from="$RECORD_FETCHED_FROM"
    fi
  fi

  resolve_args=(resolve --release "$tag")
  [ -z "$record" ] || resolve_args+=(--record "$record")
  [ -z "$force" ] || resolve_args+=(--force)
  resolve_args+=(${overrides[@]+"${overrides[@]}"})
  # stderr is deliberately NOT captured: the resolver's warnings and its
  # refusal message belong in the operator's terminal as they happen, and
  # stdout is the machine answer.
  rc=0
  resolved="$(python3 "$CHECKER" "${resolve_args[@]}")" || rc=$?
  case "$rc" in
    0) paired=1 ;;
    3) paired='' ;;
    *) die "could not resolve ${tag}'s component pairing (exit ${rc}) — nothing was changed" ;;
  esac
  # A here-document, not a pipe: a `while read` on the right of a pipe runs in
  # a subshell and every variable it sets is gone by the next line.
  while read -r role value source; do
    case "$role" in
      core)   core_tag="$value";   core_from="$source" ;;
      user)   user_tag="$value";   user_from="$source" ;;
      search) search_tag="$value"; search_from="$source" ;;
    esac
  done <<EOF
$resolved
EOF
  if [ -z "$core_tag" ] || [ -z "$user_tag" ] || [ -z "$search_tag" ]; then
    die "deploy/release-mapping.py resolved no tag for one of core/user/search — nothing was changed. This tree mixes revisions: take deploy/release-mapping.py and deploy/pin-release.sh from the same one"
  fi

  if [ -n "$paired" ]; then
    log "${tag} pairs its components as follows (${record_from}):"
  else
    log "WARNING: ${tag}'s component pairing could not be determined — this tree carries no releases/${tag}.json and none could be fetched. Pinning as shown below, which is what this script has always done and is right for the uniform releases that are the norm. If ${tag} re-released ONE component (v0.7.4 and v0.7.5 re-released vidra-core alone), the images for the other two do not exist at ${tag} and the next deploy will fail at 'compose pull' — nothing is broken by that, but nothing upgrades either. The release notes say which components moved; state the pairing by hand with: $0 ${tag} --component-tag user=<tag> --component-tag search=<tag>"
  fi
  pin_row VIDRA_CORE_TAG   "$core_tag"   "$core_from"   "$record_from"
  pin_row VIDRA_USER_TAG   "$user_tag"   "$user_from"   "$record_from"
  pin_row VIDRA_SEARCH_TAG "$search_tag" "$search_from" "$record_from"

  # The snapshot is taken BEFORE the checkout, with this tree's helper. The
  # helper (deploy/backup-env.sh + deploy/checkout-hygiene.py) landed after
  # v0.6.4, so a target release may not carry it — every v0.6.3/v0.6.4 tree does
  # not — and running it after the checkout meant it had just been removed from
  # under this script: the tree had moved, the pins had not, and the operator
  # was left in exactly the skew this script exists to prevent. A snapshot is a
  # private copy outside the tree, so taking it first costs nothing when the
  # checkout below is refused: the env file is untouched either way.
  snapshot="$(ENV_FILE="$ENV_FILE" bash "$REPO_ROOT/deploy/backup-env.sh")" || die "env snapshot failed — nothing was changed: the tree has not moved and the env file is untouched"
  log "env snapshot: ${snapshot}"

  log "checking out ${tag}"
  git -C "$REPO_ROOT" checkout --detach --quiet "$tag" \
    || die "could not check out ${tag} — nothing else was changed; the env file still names the previous release (${snapshot} is a plain copy of it)"
  log "checkout: $(git -C "$REPO_ROOT" describe --tags --always)"

  # Each key gets ITS OWN component's tag. deploy.sh's checkout sync then
  # moves each nested checkout to the matching tag, which is what keeps its
  # independent ledger assertion honest: the expected migration version is
  # computed from vidra-core/migrations in a checkout pinned to
  # VIDRA_CORE_TAG, the same tag the api and migrate images are pulled at.
  set -- VIDRA_CORE_TAG "$core_tag" VIDRA_USER_TAG "$user_tag" VIDRA_SEARCH_TAG "$search_tag"
  while [ $# -gt 0 ]; do
    if ! env_set_key "$1" "$2"; then
      cat "$snapshot" > "$ENV_FILE"
      die "could not set $1 — env file restored from ${snapshot}; the tree is at ${tag}"
    fi
    shift 2
  done
  log "pinned ${tag}: core=$(env_get VIDRA_CORE_TAG) user=$(env_get VIDRA_USER_TAG) search=$(env_get VIDRA_SEARCH_TAG)"
  log "next: ./deploy/deploy.sh"
}
main "$@"
