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
#
# BUNDLE TREES (D6, 2026-10-01). The default install is an unpacked
# vidra-bundle (vidra-bundle.manifest, no .git), and `git checkout` does not
# exist there. The same command does what the runbook's first five steps did by
# hand: resolve the pairing, download vidra-bundle_<core tag>.tar.gz and
# SHA256SUMS from the vidra-core release, VERIFY BEFORE UNPACKING, unpack, then
# write the three tags. It stops there: ./deploy/deploy.sh is still the
# operator's next, separate command.
# The archive is untrusted until proven otherwise, and unpacking it over a live
# tree is the dangerous step, so: members are listed first and an archive with
# an absolute or `..` path, a link of any kind, a device, no manifest, or an
# env/*.env or deploy/Caddyfile.local of its own is refused; it is unpacked into
# a staging directory INSIDE the tree (same filesystem) and copied over only
# after every check passed, manifest last, so any refusal leaves the tree and
# the env file byte-for-byte as they were. This script replaces ITSELF during
# the copy, which is why main() ends in an explicit exit - see there.
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
STAGE=''   # the bundle staging directory, inside the tree (see stage_bundle)
# Invoked by the EXIT trap below; shellcheck stops seeing that once main() ends
# in an explicit exit, and reports the function as unused.
# shellcheck disable=SC2317,SC2329  # SC2317 on older shellcheck, SC2329 on newer
cleanup_record_tmpdir() {
  local d
  for d in "$RECORD_TMPDIR" "$STAGE"; do
    [ -z "$d" ] || rm -rf "$d" 2>/dev/null \
      || printf '[pin] WARNING: could not remove %s; remove it by hand.\n' "$d" >&2
  done
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
    record-tree|record-fetched) origin="$where" ;;
    --component-tag)            origin='--component-tag (by hand, unverified)' ;;
    *)                          origin='the release tag (no pairing record)' ;;
  esac
  log "  ${key}=${value}  <- ${origin}"
}

# Why the resolver did not answer. Its exit codes are a contract and each one
# means exactly ONE thing, so the operator is told which of four different
# problems they have instead of the single unattributed "nothing was changed"
# this used to print:
#   0   a record decided the pairing        (not a failure)
#   3   no usable record, uniform fallback  (not a failure)
#   1   refused: a flag is wrong, or contradicts the record
#   2   this tree's checker has no `resolve` command — mixed revisions
#   70  the resolver crashed
# Anything else is undefined. Undefined is NOT a licence to guess a uniform
# triple: unlike deploy.sh's and rollback.sh's preflight, pinning is not an
# incident path, nothing is mutated yet, and continuing after the tool that
# decides the pairing has fallen over is how a host ends up on images nobody
# released. Absence of a record is a different thing entirely — that is the
# clean exit 3 above, and it still falls back to uniform with a warning.
resolve_failure() {
  case "$1" in
    1)  printf 'deploy/release-mapping.py refused it — see its message above' ;;
    2)  printf 'the deploy/release-mapping.py in this tree has no "resolve" command, so it predates this feature. This tree mixes revisions: take deploy/release-mapping.py and deploy/pin-release.sh from the same one' ;;
    70) printf 'deploy/release-mapping.py crashed while reading the release record. That is a bug in it, not in anything you typed; re-run with the record path it names, and report it' ;;
    *)  printf 'deploy/release-mapping.py exited %s, which is not an answer this contract defines (0, 1, 2, 3 or 70)' "$1" ;;
  esac
}

# download <url> <dest> - HTTPS-only, bounded, ~/.curlrc ignored (-q first: a
# deploy host's curl config can add --insecure or a proxy, and this fetches what
# becomes the deployment tree).
download() {
  curl -q --proto '=https' --proto-redir '=https' --tlsv1.2 --fail --silent --show-error \
       --location --max-redirs 5 --connect-timeout 10 --max-time 900 --output "$2" "$1"
}

# stage_bundle <core tag> - everything that can be refused, before the tree is
# touched. Leaves the verified, listing-checked archive unpacked in
# $STAGE/tree and its manifest in $STAGE/vidra-bundle.manifest.
stage_bundle() {
  local core="$1" asset base listing verbose offenders mtag
  asset="vidra-bundle_${core}.tar.gz"
  base="https://github.com/yegamble/vidra-core/releases/download/${core}"
  command -v sha256sum >/dev/null 2>&1 || die "no sha256sum on this host (coreutils), so the download cannot be verified - nothing was changed"
  command -v tar >/dev/null 2>&1 || die "no tar on this host - nothing was changed"
  # Inside the tree so the later copy never crosses a filesystem and a full
  # /tmp cannot fail it half-way; removed by the EXIT trap whatever happens.
  STAGE="$(mktemp -d "$REPO_ROOT/.vidra-upgrade.XXXXXX")" || die "could not create a staging directory in $REPO_ROOT (is the tree writable by $(id -un)?) - nothing was changed"
  log "downloading ${asset} from ${base}"
  download "${base}/${asset}" "$STAGE/${asset}" || die "downloading ${base}/${asset} failed - nothing was changed. A release cut before the bundle existed has none; unpack by hand per 'Upgrade a bundle tree' in deploy/README.md"
  download "${base}/SHA256SUMS" "$STAGE/SHA256SUMS" || die "downloading ${base}/SHA256SUMS failed - nothing was changed; the bundle cannot be verified without it"
  # Matched on the exact NAME (as install.sh does), not a regex over the file.
  awk -v want="$asset" '$2 == want || $2 == "*" want { print; found = 1 } END { exit !found }' \
    "$STAGE/SHA256SUMS" > "$STAGE/SHA256SUMS.one" \
    || die "SHA256SUMS lists no entry for ${asset}, so it cannot be verified - nothing was changed"
  ( cd "$STAGE" && sha256sum -c SHA256SUMS.one >/dev/null 2>&1 ) \
    || die "CHECKSUM MISMATCH on ${asset} - nothing was unpacked or changed. A corrupted transfer or a tampered asset; re-run, and if it repeats do not work around it"
  log "checksum verified: ${asset}"

  # Verified means "the bytes the release published", not "safe to unpack":
  # the member names are checked from the listing BEFORE tar writes anything,
  # so the answer does not depend on which tar this host has. Every member of a
  # real bundle is ./-relative by construction (make-bundle.sh).
  listing="$(tar -tzf "$STAGE/${asset}")" || die "${asset} is not a readable gzip tarball - nothing was changed"
  verbose="$(tar -tvzf "$STAGE/${asset}")" || die "${asset} is not a readable gzip tarball - nothing was changed"
  [ "$(printf '%s\n' "$listing" | wc -l)" -eq "$(printf '%s\n' "$verbose" | wc -l)" ] \
    || die "${asset}: the member list and the typed listing disagree (a member name with a newline in it?) - refusing to unpack, nothing was changed"
  offenders="$(printf '%s\n' "$listing" | grep -vE '^\./' || true)"
  [ -z "$offenders" ] || die "${asset} has member(s) not relative to the tree root (absolute or bare paths) - refusing to unpack, nothing was changed: ${offenders}"
  offenders="$(printf '%s\n' "$listing" | grep -F '..' || true)"
  [ -z "$offenders" ] || die "${asset} has member(s) with '..' in the path - refusing to unpack, nothing was changed: ${offenders}"
  # A regular file is '-' and a directory 'd'; everything else (l symlink, h
  # hardlink, c/b device, p fifo) can aim a later write outside the tree.
  offenders="$(printf '%s\n' "$verbose" | grep -vE '^[-d]' || true)"
  [ -z "$offenders" ] || die "${asset} has symlink, hardlink or special-file member(s) - refusing to unpack, nothing was changed: ${offenders}"
  printf '%s\n' "$listing" | grep -qx './vidra-bundle.manifest' \
    || die "${asset} has no vidra-bundle.manifest at its root, so it is not a deployment bundle - nothing was changed"
  # The two things that belong to THIS host. A bundle must never ship them, and
  # one that does is not to be trusted to overwrite your secrets or Caddyfile.
  offenders="$(printf '%s\n' "$listing" | grep -E '^\./deploy/Caddyfile\.local$|^\./env/' | grep -vE '^\./env/$|\.env\.example$' || true)"
  [ -z "$offenders" ] || die "${asset} contains host-local file(s) a bundle must never ship (env/*.env, deploy/Caddyfile.local) - refusing to unpack, nothing was changed: ${offenders}"

  mkdir "$STAGE/tree"
  tar -xzf "$STAGE/${asset}" -C "$STAGE/tree" --no-same-owner || die "unpacking ${asset} into the staging directory failed - the tree itself was not touched"
  [ -f "$STAGE/tree/vidra-bundle.manifest" ] || die "${asset} unpacked without a vidra-bundle.manifest - nothing was changed"
  mv "$STAGE/tree/vidra-bundle.manifest" "$STAGE/vidra-bundle.manifest"
  mtag="$(bundle_manifest_get "$STAGE" tag)"
  [ "$mtag" = "$core" ] || log "WARNING: the bundle's manifest says tag=${mtag:-<none>}, not ${core}; deploy.sh's release-mapping preflight judges the tree by the manifest"
}

# install_bundle - copy the staged tree over this one. cp -R, not -a/-p: files
# become the invoking user's (the tree owner) and existing directories, notably
# a 0700 env/, keep their modes. The manifest goes LAST, so a copy that dies
# half-way leaves the OLD manifest in place and the tree reports unfinished.
install_bundle() {
  local f
  cp -R "$STAGE/tree/." "$REPO_ROOT/" || die "copying the bundle over $REPO_ROOT failed part-way - the tree may be MIXED, the env file is untouched and the manifest still names the previous release; re-run this command"
  # cp does not chmod a file it overwrites, so a script the new release made
  # executable would stay non-executable.
  while IFS= read -r f; do
    [ -z "$f" ] || chmod u+x "$REPO_ROOT/$f" 2>/dev/null || true
  done <<EOF
$(cd "$STAGE/tree" && find . -type f -perm -u+x)
EOF
  cp "$STAGE/vidra-bundle.manifest" "$REPO_ROOT/vidra-bundle.manifest" || die "could not write vidra-bundle.manifest - re-run this command"
}

main() {
  local tag='' force='' owner snapshot rc=0 resolved paired='' unpaired_note='' bundle=''
  local record='' fetched_record='' record_from=''
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
  if is_bundle_tree "$REPO_ROOT"; then
    bundle=1
  elif [ ! -d "$REPO_ROOT/.git" ]; then
    die "$REPO_ROOT is neither a git checkout nor an unpacked release bundle (no vidra-bundle.manifest) — it cannot be pinned"
  fi
  command -v python3 >/dev/null 2>&1 || die "Python 3 is required for checkout preflight; install python3 first"
  [ -f "$CHECKER" ] || die "deploy/release-mapping.py is missing from $REPO_ROOT, so this release's component pairing cannot be read. This tree is incomplete or mixes revisions; take deploy/release-mapping.py from the same revision as deploy/pin-release.sh"
  # Every finding is fatal here, as in deploy.sh: pinning is deploy-side work,
  # and this is the moment to fix the host, not to work around it.
  # Checkout hygiene is about git object ownership; a bundle tree has no git.
  if [ -z "$bundle" ]; then
    python3 "$REPO_ROOT/deploy/checkout-hygiene.py" check "$REPO_ROOT" || die "checkout hygiene preflight failed"
  fi

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
    *) die "$(resolve_failure "$rc"). Nothing was changed: the tree has not moved and the env file is untouched" ;;
  esac

  if [ -z "$bundle" ]; then
    log "fetching tags from origin"
    git -C "$REPO_ROOT" fetch --tags --force --quiet origin \
      || die "git fetch failed — nothing was changed"
    git -C "$REPO_ROOT" rev-parse -q --verify "refs/tags/${tag}^{commit}" >/dev/null \
      || die "${tag} is not a tag on origin — was the release cut? (deploy/release.sh --yes ${tag}). Nothing was changed"
  fi

  # THE PAIRING, resolved before the first mutation, from up to TWO copies of
  # the record.
  #
  # The tree copy is read off the revision the run STARTED on — and the
  # checkout below replaces it with the tag's own tree, which carries no
  # record for itself (release.sh tags this repository before any image
  # exists). deploy.sh then runs from that moved tree, finds no record, and
  # FETCHES the canonical one. So a tree copy that disagrees with main pins
  # from one record and is judged against another: the host is moved and the
  # next deploy is refused. That is why the fetch is attempted even when this
  # tree has a copy, and why the fetched copy wins — the resolver names the
  # disagreement rather than resolving it silently.
  #
  # The fetch is best-effort, bounded, HTTPS-only and never fatal, through the
  # same helper and the same VIDRA_RECORD_FETCH / VIDRA_RECORD_BASE_URL knobs
  # deploy.sh uses, so a host configured for one is configured for both. When
  # it cannot be made, the tree copy is used exactly as before.
  if [ -f "$REPO_ROOT/releases/${tag}.json" ]; then
    record="$REPO_ROOT/releases/${tag}.json"
  fi
  RECORD_TMPDIR="$(mktemp -d "${TMPDIR:-/tmp}/vidra-record.XXXXXX" 2>/dev/null)" || RECORD_TMPDIR=''
  if [ -z "$RECORD_TMPDIR" ]; then
    log "could not create a temporary directory, so ${tag}'s canonical release record was not fetched"
  elif fetch_release_record "$tag" "$RECORD_TMPDIR/${tag}.json"; then
    fetched_record="$RECORD_TMPDIR/${tag}.json"
  fi

  resolve_args=(resolve --release "$tag")
  [ -z "$record" ] || resolve_args+=(--record "$record")
  [ -z "$fetched_record" ] || resolve_args+=(--fetched-record "$fetched_record")
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
    *) die "could not resolve ${tag}'s component pairing: $(resolve_failure "$rc"). Nothing was changed: the tree has not moved and the env file is untouched" ;;
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

  # install.sh's rule for bundles: no record, no guess. A uniform triple for a
  # core-only release names images that do not exist, and a bundle host cannot
  # recover by re-checking out a tag.
  if [ -n "$bundle" ] && [ -z "$paired" ] && [ "${#overrides[@]}" -eq 0 ]; then
    die "no release record for ${tag} could be read (none in this tree, none fetched), and a bundle upgrade will not guess the pairing. Nothing was changed. Retry with network access, or state it: $0 ${tag} --component-tag user=<tag> --component-tag search=<tag>"
  fi

  # Which copy of the record actually decided it. Only one of the two ever
  # does, so one lookup covers every record-sourced row below.
  case "${core_from}${user_from}${search_from}" in
    *record-fetched*) record_from="$RECORD_FETCHED_FROM" ;;
    *record-tree*)    record_from="releases/${tag}.json" ;;
  esac

  if [ -n "$paired" ]; then
    log "${tag} pairs its components as follows (${record_from}):"
  else
    # The failure named here is the one an operator will actually meet.
    # pin-release.sh only ever runs on a GIT tree, and there deploy.sh's
    # component checkout sync reaches a tag that does not exist before it
    # pulls anything: `failed to checkout tag vX in vidra-user`. It used to
    # say `compose pull`, which is a later step and the wrong line of the log
    # to go looking at (it is the one a bundle host would see, and a bundle
    # host cannot run this script at all).
    #
    # And the second sentence is conditional: with --component-tag the pins
    # below are NOT "what this script has always done", and claiming they are
    # would describe the operator's own correction back at them.
    if [ "${#overrides[@]}" -eq 0 ]; then
      unpaired_note="Pinning as shown below, which is what this script has always done and is right for the uniform releases that are the norm. If ${tag} re-released ONE component (v0.7.4 and v0.7.5 re-released vidra-core alone), the images for the other two do not exist at ${tag}: the next deploy stops at the component checkout sync with 'failed to checkout tag ${tag} in vidra-user' before it changes anything. The release notes say which components moved; state the pairing by hand with: $0 ${tag} --component-tag user=<tag> --component-tag search=<tag>"
    else
      unpaired_note="The --component-tag values below are taken on trust: nothing here could check them against a record. If one of them is wrong the next deploy stops at the component checkout sync with 'failed to checkout tag <that tag> in <that repo>' before it changes anything."
    fi
    log "WARNING: ${tag}'s component pairing could not be determined — this tree carries no releases/${tag}.json and none could be fetched. ${unpaired_note}"
  fi
  pin_row VIDRA_CORE_TAG   "$core_tag"   "$core_from"   "$record_from"
  pin_row VIDRA_USER_TAG   "$user_tag"   "$user_from"   "$record_from"
  pin_row VIDRA_SEARCH_TAG "$search_tag" "$search_from" "$record_from"

  # Bundle trees: everything that can be refused happens here, with the tree
  # still untouched (download, checksum, member listing, staging unpack).
  if [ -n "$bundle" ]; then
    stage_bundle "$core_tag"
  fi

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

  if [ -n "$bundle" ]; then
    log "unpacking the verified ${core_tag} bundle over ${REPO_ROOT}"
    install_bundle
  else
    log "checking out ${tag}"
    git -C "$REPO_ROOT" checkout --detach --quiet "$tag" \
      || die "could not check out ${tag} — nothing else was changed; the env file still names the previous release (${snapshot} is a plain copy of it)"
    log "checkout: $(git -C "$REPO_ROOT" describe --tags --always)"
  fi

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
  log "next: ./deploy/deploy.sh   (or: vidra deploy) — nothing has been deployed yet"
  # main EXITS rather than returning: on a bundle tree the unpack overwrote this
  # very file, and bash reads a script incrementally, so returning to the last
  # line would resume at the old byte offset inside the NEW file.
  exit 0
}
main "$@"
