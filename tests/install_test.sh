#!/usr/bin/env bash

set -euo pipefail

log()  { printf '[test] %s\n' "$*"; }
die()  { printf '[test] ERROR: %s\n' "$*" >&2; exit 1; }

# Source the function to test from install.sh
# We extract just the function to avoid running the whole installer
sed -n '/compose_at_least_2_24() {/,/^}/p' install.sh > /tmp/func_to_test.sh
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

if [ "$failures" -gt 0 ]; then
  die "$failures tests failed!"
else
  log "All tests passed!"
fi
