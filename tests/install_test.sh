#!/usr/bin/env bash
# The unpack_bundle section below stubs log/die/fetch_verified/make_install_dir
# for a function this file sources at RUNTIME, which shellcheck cannot see - so
# it reports the stubs as never invoked (SC2317 on shellcheck <= 0.9, SC2329 on
# >= 0.10). 0.9 honours neither line- nor function-level directives for SC2317
# (shellcheck issue #2542), so the disable has to be file-wide.
# shellcheck disable=SC2317,SC2329

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

# ---------------------------------------------------------------------------
# The release pins in the env templates: the FLOOR is not the RECOMMENDATION.
#
# Two numbers sit one paragraph apart in env/production.env.example and they rot
# in opposite directions. deploy/deploy.sh's MIN_EMBEDDED_MIGRATE_TAG is a
# compatibility FLOOR: deliberately old, and it never moves down. The VIDRA_*_TAG
# values are a RECOMMENDATION: the release a fresh install deploys, which has to
# be bumped on every release. They were left equal for three releases, and that
# failure is SILENT on the checkout path — deploy.sh pins ./vidra-core to
# VIDRA_CORE_TAG *before* it reads expected_version out of that checkout's
# migrations, so the ledger assertion compares the stale release against itself,
# matches, and the deploy exits 0 on release-old code.
#
# So: the six pins must parse, agree, clear the floor, and must not have
# collapsed back onto it. The strict-greater assertion is the one with teeth —
# ">= the floor" is what the deploy scripts already enforce and it passes
# trivially on the stale value. It has one deliberate cost: raising the floor to
# the newest release would trip it. That is the right trade against a production
# deploy that exits 0 on the wrong code, and the message says what to do.
#
# The comparison is deploy.sh's OWN semver_ge, extracted the way
# compose_at_least_2_24 is above, so this test cannot drift from the gate it is
# asserting about.
# ---------------------------------------------------------------------------

log "Testing the release pins in the env templates..."

sed -n '/^semver_ge() {/,/^}/p' deploy/deploy.sh > /tmp/semver_ge_to_test.sh
# shellcheck disable=SC1091
source /tmp/semver_ge_to_test.sh

pins_ok=1

floor="$(grep -vE '^[[:space:]]*#' deploy/deploy.sh \
  | sed -n 's/^MIN_EMBEDDED_MIGRATE_TAG="\([^"]*\)".*/\1/p' | head -n1)"
if [ -z "$floor" ]; then
  echo "FAIL: env pins -> deploy/deploy.sh declares no MIN_EMBEDDED_MIGRATE_TAG to compare against"
  pins_ok=0
fi

pin_values=""
for tmpl in env/production.env.example env/staging.env.example; do
  for key in VIDRA_CORE_TAG VIDRA_USER_TAG VIDRA_SEARCH_TAG; do
    tag="$(sed -n "s/^${key}=//p" "$tmpl" | head -n1 | tr -d '\r')"
    if [ -z "$tag" ]; then
      echo "FAIL: env pins -> ${tmpl} sets no ${key}; docker-compose.prod.yml requires it, because an untagged production deploy has nothing to roll back to"
      pins_ok=0
      continue
    fi
    pin_values="${pin_values}${key}=${tag}
"
    [ -n "$floor" ] || continue

    rc=0
    semver_ge "$tag" "$floor" || rc=$?
    case "$rc" in
      0) ;;
      1)
        echo "FAIL: env pins -> ${tmpl}'s ${key}=${tag} is BELOW deploy/deploy.sh's MIN_EMBEDDED_MIGRATE_TAG=${floor}; that image has no embedded 'migrate' subcommand, so the migration one-shot boots an API server that never exits and the deploy hangs with no error"
        pins_ok=0
        continue
        ;;
      *)
        echo "FAIL: env pins -> ${tmpl}'s ${key}=${tag} is not a vMAJOR.MINOR.PATCH release tag, so it cannot be checked against the ${floor} floor at all"
        pins_ok=0
        continue
        ;;
    esac

    # Strictly above the floor: semver_ge both ways means equal.
    rc=0
    semver_ge "$floor" "$tag" || rc=$?
    if [ "$rc" -eq 0 ]; then
      echo "FAIL: env pins -> ${tmpl}'s ${key}=${tag} is still sitting ON the ${floor} floor. That floor is a compatibility bound; these pins are the release a fresh install deploys and must be bumped every release (tests/env_template_pins_test.py fails the release PR until they are). If you deliberately RAISED the floor to the newest release, bump these to it and relax this assertion in the same commit."
      pins_ok=0
    fi
  done
done

# Compared PER KEY: a core-only release (v0.7.5 is core v0.7.5 with user and
# search at v0.7.3) is three tags, not one, so "all six values equal" was only
# ever true for uniform releases. Production and staging must still agree on
# each key, and tests/env_template_pins_test.py holds both to the newest record.
if [ -n "$pin_values" ]; then
  distinct="$(printf '%s' "$pin_values" | sort -u | wc -l | tr -d ' ')"
  if [ "$distinct" -ne 3 ]; then
    echo "FAIL: env pins -> production and staging do not pin the same tag per key ($(printf '%s' "$pin_values" | sort -u | tr '\n' ' ')). Staging validates the exact tags production runs; if they differ, a green staging says nothing about the artifact production pulls."
    pins_ok=0
  fi
fi

# The durable half of the same defect. vidra-core's setup interview only asks
# "Release tag to deploy" when no tag flag was given, and defaults that prompt to
# the TEMPLATE's value — so without this flag a stale template silently becomes
# the pinned release of every fresh install, chosen by an operator pressing
# enter. Passing the release install.sh already resolved is also what makes its
# own closing message ("...if you want something other than ${TAG}") true.
# Searching install.sh's SOURCE for that literal argument, so $TAG must not
# expand here — hence -F and the single quotes.
# shellcheck disable=SC2016
if grep -qF -- '--release-tag "$TAG"' install.sh; then
  echo "PASS: install.sh pins 'vidra setup' to the release it resolved"
else
  echo "FAIL: install.sh no longer passes --release-tag \"\$TAG\" to 'vidra setup'; the interview then defaults the release to env/production.env.example's value, and a stale template becomes every fresh install's pinned release"
  pins_ok=0
fi

if [ "$pins_ok" -eq 1 ]; then
  echo "PASS: env template release pins name one release above the ${floor} floor, and install.sh does not defer to them"
else
  failures=$((failures + 1))
fi

# ---------------------------------------------------------------------------
# resolve_pairing: a fresh install must establish the released component triple,
# including when today's installer unpacks an older bundle. v0.7.5 has no
# fetch_release_record shell function and no `resolve` checker command. The
# original tests copied today's helpers into the fake bundle and missed that.
# Exercise both helper surfaces; only curl is stubbed. Every successful result
# must pass the installed checker's deploy check using the installed records,
# proving the fetched record survives for the first `vidra deploy` as well.
# ---------------------------------------------------------------------------

log "Testing resolve_pairing (per-component pins for a fresh install)..."

PAIR_TMP="$(mktemp -d)"
trap 'rm -rf "$UNPACK_TMP" "$PAIR_TMP"' EXIT
sed -n '/^resolve_pairing() {/,/^}/p' install.sh > "$PAIR_TMP/func.sh"
# shellcheck disable=SC2016  # a literal to find in install.sh's source
grep -q 'SEARCH_TAG="\$p_tag"' "$PAIR_TMP/func.sh" \
  || die "extraction self-check: sed did not capture the whole resolve_pairing function from install.sh"

mkdir -p "$PAIR_TMP/tree/deploy" "$PAIR_TMP/tree/releases" "$PAIR_TMP/bin" "$PAIR_TMP/served"
cp deploy/lib.sh deploy/release-mapping.py "$PAIR_TMP/tree/deploy/"
cp releases/v0.7.3.json releases/v0.7.5.json "$PAIR_TMP/served/"
cat > "$PAIR_TMP/bin/curl" <<'STUB'
#!/bin/sh
# Serves $SERVED/<tag>.json for .../<tag>.json; anything else is curl's 404 exit.
out=""; url=""
while [ $# -gt 0 ]; do
  case "$1" in
    --output) out="$2"; shift 2 ;;
    https://*) url="$1"; shift ;;
    *) shift ;;
  esac
done
f="$SERVED/${url##*/}"
[ -f "$f" ] || exit 22
cp "$f" "$out"
STUB
chmod +x "$PAIR_TMP/bin/curl"

run_pairing() {
  local tag="$1"; shift
  mkdir -p "$PAIR_TMP/work"
  # shellcheck disable=SC2016  # the inline script expands its own positionals
  env "$@" PATH="$PAIR_TMP/bin:$PATH" SERVED="$PAIR_TMP/served" sh -eu -c '
    OWNER=yegamble
    log()  { :; }
    warn() { echo "WARNING: $*" >&2; }
    die()  { echo "DIE: $*" >&2; exit 9; }
    . "$1"
    TAG="$2"; DIR="$3"; WORK="$4"; PAIRING_DONE=0
    resolve_pairing
    echo "$CORE_TAG $USER_TAG $SEARCH_TAG"
  ' pairing "$PAIR_TMP/func.sh" "$tag" "$PAIR_TMP/tree" "$PAIR_TMP/work"
}

assert_pairing() {
  local tag="$1" want="$2" out core user search
  shift 2
  out="$(run_pairing "$tag" "$@" 2>&1)" || { echo "FAIL: resolve_pairing ${tag} exited non-zero: ${out}"; failures=$((failures + 1)); return; }
  if [ "$out" != "$want" ]; then
    echo "FAIL: resolve_pairing ${tag} ($*) -> '${out}', expected '${want}'"
    failures=$((failures + 1)); return
  fi
  read -r core user search <<< "$out"
  if ! python3 "$PAIR_TMP/tree/deploy/release-mapping.py" check --mode deploy \
       --core "$core" --user "$user" --search "$search" \
       --releases "$PAIR_TMP/tree/releases" >/dev/null 2>&1; then
    echo "FAIL: resolve_pairing ${tag} -> '${out}', which the installed deploy checker REFUSES using the installed records"
    failures=$((failures + 1)); return
  fi
  echo "PASS: resolve_pairing ${tag} ($*) -> ${out}; installed deploy checker accepts it"
}

assert_pairing_refused() {
  local label="$1" tag="$2" reason="$3" out
  shift 3
  if out="$(run_pairing "$tag" "$@" 2>&1)"; then
    echo "FAIL: resolve_pairing ${label} succeeded: ${out}"
    failures=$((failures + 1)); return
  fi
  if ! printf '%s\n' "$out" | grep -qF "$reason" || ! printf '%s\n' "$out" | grep -q 'no component tags were guessed'; then
    echo "FAIL: resolve_pairing ${label} did not explain its refusal: ${out}"
    failures=$((failures + 1)); return
  fi
  echo "PASS: resolve_pairing ${label} -> refused before setup/bootstrap"
}

# Today's helpers, followed by the helper API actually present in v0.7.5.
assert_pairing v0.7.5 "v0.7.5 v0.7.3 v0.7.3"
rm -f "$PAIR_TMP/tree/releases/"*.json
printf '# Old bundles have no fetch_release_record function.\n' > "$PAIR_TMP/tree/deploy/lib.sh"
if [ -n "${INSTALL_TEST_RELEASE_MAPPING:-}" ]; then
  # Optional real historical source, e.g. `git show v0.7.5:deploy/release-mapping.py`.
  # CI's shallow checkout need not fetch old tags to run the API regression.
  cp "$INSTALL_TEST_RELEASE_MAPPING" "$PAIR_TMP/tree/deploy/release-mapping.py"
else
  cp deploy/release-mapping.py "$PAIR_TMP/tree/deploy/record-validator.py"
  cat > "$PAIR_TMP/tree/deploy/release-mapping.py" <<'LEGACY'
import argparse
from pathlib import Path
import runpy

source = str(Path(__file__).with_name("record-validator.py"))
validate = runpy.run_path(source)["validate"]
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("check",))
    parser.parse_known_args()
    runpy.run_path(source, run_name="__main__")
LEGACY
fi
if python3 "$PAIR_TMP/tree/deploy/release-mapping.py" resolve --release v0.7.5 >/dev/null 2>&1; then
  die "legacy fixture must refuse the resolve command that did not exist in v0.7.5"
fi
assert_pairing v0.7.5 "v0.7.5 v0.7.3 v0.7.3"
assert_pairing v0.7.3 "v0.7.3 v0.7.3 v0.7.3"
rm -f "$PAIR_TMP/tree/releases/"*.json
# No record means no guessed pins, even for an apparently uniform release.
assert_pairing_refused "missing record" v0.9.9 "no release record is available"
assert_pairing_refused "fetch disabled without a local record" v0.7.5 "no release record is available" VIDRA_RECORD_FETCH=off
# Offline/retry operation is safe with a validated local record.
cp releases/v0.7.5.json "$PAIR_TMP/tree/releases/"
assert_pairing v0.7.5 "v0.7.5 v0.7.3 v0.7.3" VIDRA_RECORD_FETCH=off
assert_pairing v0.7.5 "v0.7.5 v0.7.3 v0.7.3" 'VIDRA_RECORD_FETCH= OFF # offline'
mv "$PAIR_TMP/served/v0.7.5.json" "$PAIR_TMP/served/saved.json"
assert_pairing v0.7.5 "v0.7.5 v0.7.3 v0.7.3"
mv "$PAIR_TMP/served/saved.json" "$PAIR_TMP/served/v0.7.5.json"

# A well-formed but changed fetched record must not overwrite installed truth.
python3 - "$PAIR_TMP/served/v0.7.5.json" <<'CONFLICT'
import json
from pathlib import Path
import sys
p = Path(sys.argv[1])
data = json.loads(p.read_text())
data["components"]["user"]["tag"] = "v0.7.4"
p.write_text(json.dumps(data))
CONFLICT
assert_pairing_refused "contradictory record" v0.7.5 "contradicts the installed record"
cmp -s releases/v0.7.5.json "$PAIR_TMP/tree/releases/v0.7.5.json" \
  || die "a refused fetched record modified the installed record"
rm -f "$PAIR_TMP/tree/releases/"*.json

# Structurally valid does not establish the requested release's pairing.
python3 - "$PAIR_TMP/served/v0.7.5.json" <<'FUTURE'
import json
from pathlib import Path
import sys
p = Path(sys.argv[1])
data = json.loads(p.read_text())
data["components"]["user"]["tag"] = "v0.7.6"
p.write_text(json.dumps(data))
FUTURE
assert_pairing_refused "component newer than release" v0.7.5 "component tags do not belong"
printf '{"invalid": true}\n' > "$PAIR_TMP/served/v0.7.5.json"
assert_pairing_refused "malformed record" v0.7.5 "the record is missing"
[ ! -f "$PAIR_TMP/tree/releases/v0.7.5.json" ] || die "a refused record was installed"
cp releases/v0.7.5.json "$PAIR_TMP/served/"
assert_pairing_refused "unencrypted record URL" v0.7.5 "must use https://" VIDRA_RECORD_BASE_URL=http://example.invalid/releases

# ---------------------------------------------------------------------------
# The --git clone path: bootstrap.sh puts EACH component on its own tag.
#
# install.sh --git (and any release without a bundle asset) clones this repo and
# runs bootstrap.sh, which detached every component at the one VIDRA_REF. For a
# core-only release that is a tag vidra-user and vidra-search do not have, so the
# install died in bootstrap before setup ever ran. Real git against local repos
# laid out like v0.7.5 (core has v0.7.5; user/search stop at v0.7.3); the
# https://github.com/<owner>/ URLs bootstrap.sh builds are redirected to them
# with url.insteadOf, so nothing touches the network.
# ---------------------------------------------------------------------------

log "Testing bootstrap.sh per-component refs (the --git install path)..."

BOOT_TMP="$PAIR_TMP/boot"
mkdir -p "$BOOT_TMP/remotes" "$BOOT_TMP/meta"
boot_git() {
  git -c user.name=t -c user.email=t@example.invalid -c init.defaultBranch=main \
      -c commit.gpgsign=false -c tag.gpgsign=false "$@"
}
# Named <repo>.git: bootstrap.sh clones https://github.com/<owner>/<repo>.git.
for r in vidra-core vidra-user vidra-search; do
  boot_git init -q "$BOOT_TMP/remotes/$r.git"
  for t in v0.7.3 v0.7.5; do
    if [ "$t" = v0.7.5 ] && [ "$r" != vidra-core ]; then continue; fi
    boot_git -C "$BOOT_TMP/remotes/$r.git" commit -q --allow-empty -m "$t"
    boot_git -C "$BOOT_TMP/remotes/$r.git" tag "$t"
  done
done
cp bootstrap.sh "$BOOT_TMP/meta/"

# run_bootstrap_at <env...> - bootstrap.sh from $BOOT_TMP/meta; prints "core user search" tags.
run_bootstrap_at() {
  (
    cd "$BOOT_TMP/meta"
    env GIT_CONFIG_COUNT=1 \
        GIT_CONFIG_KEY_0="url.file://$BOOT_TMP/remotes/.insteadOf" \
        GIT_CONFIG_VALUE_0="https://github.com/boot-test/" \
        GIT_TERMINAL_PROMPT=0 VIDRA_GH_OWNER=boot-test "$@" ./bootstrap.sh >/dev/null 2>&1
  ) || return 1
  for r in vidra-core vidra-user vidra-search; do
    git -C "$BOOT_TMP/meta/$r" describe --tags --exact-match HEAD 2>/dev/null || echo "?"
  done | tr '\n' ' ' | sed 's/ $//'
}

# assert_bootstrap <label> <expected "core user search"|FAIL> <env...>
assert_bootstrap() {
  local label="$1" want="$2" got rc=0
  shift 2
  got="$(run_bootstrap_at "$@")" || rc=$?
  if [ "$want" = FAIL ]; then
    if [ "$rc" -eq 0 ]; then
      echo "FAIL: bootstrap.sh ${label} -> exit 0 (${got}); expected a refusal"; failures=$((failures + 1))
    else
      echo "PASS: bootstrap.sh ${label} -> refused"
    fi
  elif [ "$rc" -ne 0 ] || [ "$got" != "$want" ]; then
    echo "FAIL: bootstrap.sh ${label} -> exit ${rc}, checkouts '${got}', expected '${want}'"
    failures=$((failures + 1))
  else
    echo "PASS: bootstrap.sh ${label} -> ${got}"
  fi
}

# The defect, as the old installer called it: one tag, and two repos lack it.
assert_bootstrap "fresh clone, VIDRA_REF=v0.7.5 alone" FAIL VIDRA_REF=v0.7.5
rm -rf "$BOOT_TMP/meta/vidra-"*
# The fix, on a fresh clone...
assert_bootstrap "fresh clone, per-component refs" "v0.7.5 v0.7.3 v0.7.3" \
  VIDRA_REF=v0.7.5 VIDRA_CORE_REF=v0.7.5 VIDRA_USER_REF=v0.7.3 VIDRA_SEARCH_REF=v0.7.3
# ...and on the update path an installer re-run takes over an existing checkout.
assert_bootstrap "existing checkouts, uniform VIDRA_REF" "v0.7.3 v0.7.3 v0.7.3" VIDRA_REF=v0.7.3
assert_bootstrap "existing checkouts, per-component refs" "v0.7.5 v0.7.3 v0.7.3" \
  VIDRA_REF=v0.7.5 VIDRA_CORE_REF=v0.7.5 VIDRA_USER_REF=v0.7.3 VIDRA_SEARCH_REF=v0.7.3

# And install.sh hands bootstrap.sh the pairing on BOTH git paths (fresh clone,
# existing checkout): run_bootstrap is the one call site, run with the real
# resolve_pairing and a stand-in bootstrap.sh that reports what it was given.
sed -n '/^run_bootstrap() {/,/^}/p' install.sh > "$PAIR_TMP/boot_func.sh"
if ! grep -q 'bootstrap.sh' "$PAIR_TMP/boot_func.sh"; then
  echo "FAIL: install.sh has no run_bootstrap() wrapping bootstrap.sh"
  failures=$((failures + 1))
else
  # shellcheck disable=SC2016  # a script body for the stand-in, expanded when IT runs
  printf '#!/bin/sh\necho "$VIDRA_REF $VIDRA_CORE_REF $VIDRA_USER_REF $VIDRA_SEARCH_REF" > "$REPORT"\n' \
    > "$PAIR_TMP/tree/bootstrap.sh"
  chmod +x "$PAIR_TMP/tree/bootstrap.sh"
  # shellcheck disable=SC2016  # the inline script expands its own positionals
  PATH="$PAIR_TMP/bin:$PATH" SERVED="$PAIR_TMP/served" REPORT="$PAIR_TMP/boot_report" sh -eu -c '
    WARNINGS=""; OWNER=yegamble
    log()  { :; }
    warn() { :; }
    die()  { echo "DIE: $*" >&2; exit 9; }
    . "$1"; . "$2"
    TAG=v0.7.5; DIR="$3"; WORK="$4"; ENV_FILE="$DIR/env/production.env"; PAIRING_DONE=0
    run_bootstrap 2>/dev/null
  ' boot "$PAIR_TMP/func.sh" "$PAIR_TMP/boot_func.sh" "$PAIR_TMP/tree" "$PAIR_TMP/work" || true
  got="$(cat "$PAIR_TMP/boot_report" 2>/dev/null || echo 'bootstrap.sh never ran')"
  if [ "$got" = "v0.7.5 v0.7.5 v0.7.3 v0.7.3" ]; then
    echo "PASS: install.sh run_bootstrap v0.7.5 -> VIDRA_REF/CORE/USER/SEARCH = ${got}"
  else
    echo "FAIL: install.sh run_bootstrap v0.7.5 -> '${got}', expected 'v0.7.5 v0.7.5 v0.7.3 v0.7.3'"
    failures=$((failures + 1))
  fi
  rm -f "$PAIR_TMP/tree/bootstrap.sh"
fi
if [ "$(grep -c 'run_bootstrap$' install.sh)" -lt 2 ]; then
  echo "FAIL: install.sh must call run_bootstrap on both the fresh-clone and existing-checkout paths"
  failures=$((failures + 1))
fi
# shellcheck disable=SC2016  # a literal to find in install.sh's source
if grep -q 'VIDRA_REF="\$TAG".*bootstrap.sh' install.sh; then
  echo "FAIL: install.sh still runs bootstrap.sh with VIDRA_REF alone somewhere; a core-only release then dies in bootstrap"
  failures=$((failures + 1))
fi

# And the pins actually reach the interview. Source-level, like --release-tag
# above: $CORE_TAG etc must not expand here.
# shellcheck disable=SC2016
if grep -qF -- '--core-tag "$CORE_TAG" --user-tag "$USER_TAG" --search-tag "$SEARCH_TAG"' install.sh; then
  echo "PASS: install.sh passes the resolved per-component pins to 'vidra setup'"
else
  echo "FAIL: install.sh does not pass --core-tag/--user-tag/--search-tag from resolve_pairing to 'vidra setup'; --release-tag alone pins a core-only release's user and search images at a tag that was never published"
  failures=$((failures + 1))
fi

# ---------------------------------------------------------------------------
# Both migration one-shots bound how long they will WAIT for a lock.
#
# Several core migrations build indexes and none uses CREATE INDEX
# CONCURRENTLY, so each holds a SHARE lock for the whole build. Postgres lock
# queues are FIFO: one long write transaction is enough to make CREATE INDEX
# queue behind it, and then every write to that table queues behind the CREATE
# INDEX. With no lock_timeout that is a HANG — deploy.sh stops at "3/6
# migrations", after the pre-deploy dump and before the restart, and the `die`
# it already carries for a FAILED migration is never reached, because a hang is
# not an exit code.
#
# So this asserts the bound is present on BOTH one-shots, fed by ONE variable,
# and that the variable is documented in the template an operator actually
# edits. It also asserts what must NOT be there: statement_timeout. Bounding the
# work rather than the wait would kill a legitimately long index build that has
# already acquired its lock — the opposite of the intent, and the easy wrong
# turn for whoever next reads "the migration timed out" in a ticket.
#
# Static, not a render: `docker compose config` needs the nested vidra-core
# checkout that provides the included model, and this file must keep running on
# a bare clone. meta-ci's "production overlay" job renders the real thing.
# ---------------------------------------------------------------------------

log "Testing the migration one-shots' lock-wait bound..."

# The body of one top-level service in docker-compose.prod.yml. A service key is
# the only thing indented exactly two spaces that is not a comment, so the next
# such line ends the block; everything a service owns is indented deeper.
prod_service_block() {
  awk -v svc="$1" '
    /^services:/            { in_services = 1; next }
    in_services && /^[^ #]/ { in_services = 0 }
    !in_services            { next }
    $0 == "  " svc ":"      { in_svc = 1; next }
    in_svc && /^  [^ #]/    { in_svc = 0 }
    in_svc                  { print }
  ' docker-compose.prod.yml
}

lock_ok=1

for svc in migrate search-migrate; do
  block="$(prod_service_block "$svc")"
  if [ -z "$block" ]; then
    echo "FAIL: migrate lock wait -> docker-compose.prod.yml declares no '${svc}' service body; deploy.sh runs both one-shots through the same exit-code-gated step and both need the bound"
    lock_ok=0
    continue
  fi

  if printf '%s\n' "$block" | grep -qE '^[[:space:]]+PGOPTIONS:.*lock_timeout='; then
    echo "PASS: docker-compose.prod.yml bounds ${svc}'s lock wait"
  else
    echo "FAIL: migrate lock wait -> docker-compose.prod.yml's '${svc}' sets no PGOPTIONS lock_timeout. Without it a migration that cannot take its lock waits forever instead of failing, and deploy.sh hangs at '3/6 migrations' with the previous release still serving reads and silently refusing writes to the locked tables"
    lock_ok=0
  fi

  if printf '%s\n' "$block" | grep -qE 'statement_timeout'; then
    echo "FAIL: migrate lock wait -> docker-compose.prod.yml's '${svc}' sets statement_timeout. Only the WAIT is meant to be bounded: an index build that already HOLDS its lock must be allowed to finish, and killing it mid-build leaves the ledger dirty for no benefit"
    lock_ok=0
  fi
done

# The variable name is read out of the compose file rather than hard-coded here,
# so renaming the knob cannot leave the template documenting something nothing
# reads (or the compose file reading something nothing documents).
lock_var="$(sed -n 's/.*PGOPTIONS: "-c lock_timeout=\${\([A-Z_][A-Z0-9_]*\).*/\1/p' \
  docker-compose.prod.yml | sort -u)"
lock_var_count="$(printf '%s' "$lock_var" | grep -c . || true)"

if [ "$lock_var_count" -ne 1 ]; then
  echo "FAIL: migrate lock wait -> the two one-shots must read ONE substitution variable, not ${lock_var_count} ($(printf '%s' "$lock_var" | tr '\n' ' ')); two knobs means an operator can raise one migrator's bound and leave the other hanging"
  lock_ok=0
else
  lock_default="$(sed -n "s/^${lock_var}=//p" env/production.env.example | head -n1 | tr -d '\r')"
  if [ -z "$lock_default" ]; then
    echo "FAIL: migrate lock wait -> env/production.env.example does not set ${lock_var}. The compose default still applies, but a bound nobody can find is a bound nobody will raise when a deploy legitimately needs to wait longer"
    lock_ok=0
  else
    echo "PASS: env/production.env.example documents ${lock_var}=${lock_default}"
  fi
fi

if [ "$lock_ok" -eq 1 ]; then
  echo "PASS: both migration one-shots bound their lock WAIT (not their work) from one documented knob"
else
  failures=$((failures + 1))
fi

if [ "$failures" -gt 0 ]; then
  die "$failures tests failed!"
else
  log "All tests passed!"
fi
