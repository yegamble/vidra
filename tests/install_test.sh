#!/usr/bin/env bash

set -euo pipefail

log()  { printf '[test] %s\n' "$*"; }
die()  { printf '[test] ERROR: %s\n' "$*" >&2; exit 1; }

# Source the function to test from install.sh
# We extract just the function to avoid running the whole installer
sed -n '/compose_at_least_2_24() {/,/^}/p' install.sh > /tmp/func_to_test.sh
# shellcheck disable=SC1091
source /tmp/func_to_test.sh

failures=0

assert_exit_code() {
  local version="$1"
  local expected="$2"
  set +e
  compose_at_least_2_24 "$version"
  local actual=$?
  set -e

  if [ "$actual" -ne "$expected" ]; then
    echo "FAIL: compose_at_least_2_24 '$version' -> expected $expected, got $actual"
    failures=$((failures + 1))
  else
    echo "PASS: compose_at_least_2_24 '$version' -> $actual"
  fi
}

log "Testing compose_at_least_2_24 function..."

# 1. Happy paths (valid versions >= 2.24) - Should return 0
assert_exit_code "2.24.0" 0
assert_exit_code "v2.24.0" 0
assert_exit_code "2.25.0" 0
assert_exit_code "2.30.1" 0
assert_exit_code "3.0.0" 0
assert_exit_code "3.0" 0
assert_exit_code "v10.0.0" 0
assert_exit_code "2.24" 0
assert_exit_code "v2.24" 0
assert_exit_code "2.24.0-rc1" 0
assert_exit_code "2.24-rc1" 0
assert_exit_code "2.24-alpha" 0
assert_exit_code "2.25.0-beta.1" 0

# 2. Older versions (valid versions < 2.24) - Should return 1
assert_exit_code "2.23.9" 1
assert_exit_code "2.23.0" 1
assert_exit_code "2.0.0" 1
assert_exit_code "1.29.2" 1
assert_exit_code "v1.29.2" 1
assert_exit_code "2.1.5" 1
assert_exit_code "2.9.9" 1
assert_exit_code "2.23" 1
assert_exit_code "1.30" 1

# 3. Invalid or unparseable versions - Should return 2
assert_exit_code "abc" 2
assert_exit_code "v.2.24" 2
assert_exit_code "" 2
assert_exit_code ".." 2
assert_exit_code "." 2
assert_exit_code "v2.x" 2
assert_exit_code "2.a" 2
assert_exit_code "a.24" 2
assert_exit_code "v2.24x" 2

# ---------------------------------------------------------------------------
# unpack_bundle: the tarball-unpacking error paths.
#
# fetch_verified proves the bytes are the ones the release published — it says
# nothing about whether they are safe to unpack. unpack_bundle itself refuses
# member names that could write outside ${DIR} (../ traversal, absolute paths,
# anything not ./-anchored) and tarballs that are not deployment bundles (no
# ./vidra-bundle.manifest at the root), precisely because the host's tar cannot
# be trusted to enforce any of that uniformly. So the hostile fixtures below
# are built with `tar -P` (both GNU tar and bsdtar keep the dangerous names
# under -P) and the assertions check that the FUNCTION, not tar, refuses them.
# ---------------------------------------------------------------------------

log "Testing unpack_bundle error paths..."

UNPACK_TMP="$(mktemp -d)"
trap 'rm -rf "$UNPACK_TMP"' EXIT
UNPACK_ASSET="vidra-bundle_vTEST.tar.gz"
unpack_stderr="$UNPACK_TMP/stderr"

sed -n '/^unpack_bundle() {/,/^}/p' install.sh > "$UNPACK_TMP/unpack_func.sh"
grep -q 'TREE_MODE=bundle' "$UNPACK_TMP/unpack_func.sh" \
  || die "extraction self-check: sed did not capture the whole unpack_bundle function from install.sh"
# shellcheck source=/dev/null
source "$UNPACK_TMP/unpack_func.sh"

# Run unpack_bundle in a subshell under install.sh's own shell options, with
# stubs for everything that would touch the network (fetch_verified) or need
# root (make_install_dir). The die() stub exits 9 so an assertion can tell
# "the guard fired" apart from tar or grep failing on their own. Prints
# TREE_MODE on success, because the caller branches on it later.
run_unpack() {
  local fetch_rc="$1" tarball="$2" work="$3" dir="$4"
  # shellcheck disable=SC2329  # the stubs are invoked indirectly, by the sourced unpack_bundle
  (
    set -euo pipefail
    WORK="$work"; DIR="$dir"; BUNDLE_ASSET="$UNPACK_ASSET"; TREE_MODE=""
    log() { :; }
    die() { printf 'DIE: %s\n' "$*" >&2; exit 9; }
    make_install_dir() { mkdir -p "$DIR"; }
    fetch_verified() {
      [ "$fetch_rc" -eq 0 ] || return "$fetch_rc"
      cp "$tarball" "${WORK}/${BUNDLE_ASSET}"
    }
    unpack_bundle
    printf 'TREE_MODE=%s\n' "$TREE_MODE"
  )
}

# assert_unpack <desc> <expected-exit> <required-stderr-substring|-> <fetch-rc> <tarball|->
# Every refusal case additionally asserts ${DIR} was never created: all the
# guards run before make_install_dir, so a refused bundle must not leave a
# half-written install directory behind.
assert_unpack() {
  local desc="$1" expected="$2" want_err="$3" fetch_rc="$4" tarball="$5"
  local work dir actual
  work="$(mktemp -d "${UNPACK_TMP}/work.XXXXXX")"
  dir="${work}/never-created/target"
  set +e
  run_unpack "$fetch_rc" "$tarball" "$work" "$dir" >/dev/null 2>"$unpack_stderr"
  actual=$?
  set -e
  if [ "$actual" -ne "$expected" ]; then
    echo "FAIL: unpack_bundle [$desc] -> expected exit $expected, got $actual"
    sed 's/^/       stderr: /' "$unpack_stderr"
    failures=$((failures + 1))
    return 0
  fi
  if [ "$want_err" != "-" ] && ! grep -qF "$want_err" "$unpack_stderr"; then
    echo "FAIL: unpack_bundle [$desc] -> stderr does not mention: $want_err"
    sed 's/^/       stderr: /' "$unpack_stderr"
    failures=$((failures + 1))
    return 0
  fi
  if [ "$expected" -ne 0 ] && [ -e "$dir" ]; then
    echo "FAIL: unpack_bundle [$desc] -> refused the bundle but still created ${dir}"
    failures=$((failures + 1))
    return 0
  fi
  echo "PASS: unpack_bundle [$desc] -> $actual"
}

# --- fixtures ---
fixtures="$UNPACK_TMP/fixtures"
mkdir -p "$fixtures/good/deploy" "$fixtures/good/env"
printf 'tag=vTEST\n' > "$fixtures/good/vidra-bundle.manifest"
printf '#!/bin/sh\n' > "$fixtures/good/deploy/deploy.sh"
printf 'X=1\n' > "$fixtures/good/env/production.env.example"

# good.tgz — every member ./-anchored with the manifest at the root, the shape
# deploy/make-bundle.sh produces.
tar -czf "$fixtures/good.tgz" -C "$fixtures/good" .

# notdot.tgz — members relative but not ./-anchored (deploy/…): refused by the
# tree-root check.
tar -czf "$fixtures/notdot.tgz" -C "$fixtures/good" deploy

# abs.tgz — an absolute member name, kept absolute by -P. Also refused by the
# tree-root check, because an absolute path does not start with ./ either.
tar -cPzf "$fixtures/abs.tgz" "$fixtures/good/deploy/deploy.sh"

# dotdot.tgz — a ./-anchored name that escapes upward with ../, which -P keeps
# tar from sanitizing at create time.
(cd "$fixtures/good/deploy" && tar -cPzf "$fixtures/dotdot.tgz" ./../vidra-bundle.manifest)

# Self-check the hostile fixtures: a tar that silently normalized these names
# on create would leave the two tests below asserting nothing.
tar -tzf "$fixtures/dotdot.tgz" | grep -qF './../' \
  || die "fixture self-check: this tar sanitized './../' at create time, so the traversal test would prove nothing"
tar -tzf "$fixtures/abs.tgz" | grep -q '^/' \
  || die "fixture self-check: this tar stripped the leading / at create time, so the absolute-path test would prove nothing"

# nomanifest.tgz — well-shaped members, but no ./vidra-bundle.manifest at the
# root, i.e. a tarball that is not a deployment bundle.
mkdir -p "$fixtures/plain/deploy"
cp "$fixtures/good/deploy/deploy.sh" "$fixtures/plain/deploy/"
tar -czf "$fixtures/nomanifest.tgz" -C "$fixtures/plain" .

# lyingmanifest.tgz — ./vidra-bundle.manifest IS in the listing but is a
# dangling symlink, so only the post-extract [ -f ] re-check can catch it.
mkdir -p "$fixtures/lying/deploy"
cp "$fixtures/good/deploy/deploy.sh" "$fixtures/lying/deploy/"
ln -s /nonexistent-target "$fixtures/lying/vidra-bundle.manifest"
tar -czf "$fixtures/lyingmanifest.tgz" -C "$fixtures/lying" .

# corrupt.tgz — "verified" in name only: not a gzip stream at all.
printf 'this is not a tarball\n' > "$fixtures/corrupt.tgz"

# --- cases ---
assert_unpack "release carries no bundle asset -> 44 for the clone fallback" \
  44 - 44 -
assert_unpack "members not ./-relative are refused" \
  9 "not relative to the tree root" 0 "$fixtures/notdot.tgz"
assert_unpack "absolute member names are refused" \
  9 "not relative to the tree root" 0 "$fixtures/abs.tgz"
assert_unpack "../ traversal members are refused" \
  9 "with '..' in the path" 0 "$fixtures/dotdot.tgz"
assert_unpack "no manifest at the root -> not a deployment bundle" \
  9 "has no vidra-bundle.manifest" 0 "$fixtures/nomanifest.tgz"
assert_unpack "manifest listed but not a regular file after extract" \
  9 "unpacked without a vidra-bundle.manifest" 0 "$fixtures/lyingmanifest.tgz"

# A corrupt tarball must fail the install LOUDLY — neither succeed nor return
# 44, which the caller reads as "no bundle in this release" and answers with a
# git clone, silently papering over a bad asset. The exact exit code is tar's
# own (bsdtar 1, GNU tar 2), so assert the class, not the number.
corrupt_work="$(mktemp -d "${UNPACK_TMP}/work.XXXXXX")"
corrupt_dir="${corrupt_work}/never-created/target"
set +e
run_unpack 0 "$fixtures/corrupt.tgz" "$corrupt_work" "$corrupt_dir" >/dev/null 2>"$unpack_stderr"
corrupt_rc=$?
set -e
if [ "$corrupt_rc" -eq 0 ] || [ "$corrupt_rc" -eq 44 ]; then
  echo "FAIL: unpack_bundle [corrupt tarball] -> exit $corrupt_rc; a corrupt asset must fail loudly, not succeed or fall back to the clone"
  failures=$((failures + 1))
elif [ -e "$corrupt_dir" ]; then
  echo "FAIL: unpack_bundle [corrupt tarball] -> failed but still created ${corrupt_dir}"
  failures=$((failures + 1))
else
  echo "PASS: unpack_bundle [corrupt tarball] -> $corrupt_rc (failed loudly, no clone fallback, no directory)"
fi

# Happy path: a well-formed bundle lands in ${DIR} with the manifest in place
# (it is copied LAST, after the tree) and TREE_MODE flips to bundle.
happy_work="$(mktemp -d "${UNPACK_TMP}/work.XXXXXX")"
happy_dir="${happy_work}/target"
set +e
happy_out="$(run_unpack 0 "$fixtures/good.tgz" "$happy_work" "$happy_dir" 2>"$unpack_stderr")"
happy_rc=$?
set -e
happy_ok=1
if [ "$happy_rc" -ne 0 ]; then
  echo "FAIL: unpack_bundle [happy path] -> exit $happy_rc"
  sed 's/^/       stderr: /' "$unpack_stderr"
  happy_ok=0
else
  case "$happy_out" in
    *"TREE_MODE=bundle"*) ;;
    *) echo "FAIL: unpack_bundle [happy path] -> TREE_MODE not set to bundle (got: ${happy_out})"; happy_ok=0 ;;
  esac
  for f in vidra-bundle.manifest deploy/deploy.sh env/production.env.example; do
    if [ ! -f "$happy_dir/$f" ]; then
      echo "FAIL: unpack_bundle [happy path] -> $f missing from ${happy_dir}"
      happy_ok=0
    fi
  done
  if [ -f "$happy_dir/vidra-bundle.manifest" ] && ! grep -q '^tag=vTEST$' "$happy_dir/vidra-bundle.manifest"; then
    echo "FAIL: unpack_bundle [happy path] -> manifest content did not survive the unpack"
    happy_ok=0
  fi
fi
if [ "$happy_ok" -eq 1 ]; then
  echo "PASS: unpack_bundle [happy path] -> tree + manifest in place, TREE_MODE=bundle"
else
  failures=$((failures + 1))
fi

if [ "$failures" -gt 0 ]; then
  die "$failures tests failed!"
else
  log "All tests passed!"
fi
