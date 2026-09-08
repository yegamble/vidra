"""The A38 rollback floor: restore.sh must refuse a dump the pinned images
cannot reach BEFORE it drops anything, and rollback.sh must never lose its
"the rollback target is also unhealthy" trailer to `set -e`.

Both failures were found by the 2026-09-07 rehearsal (runs 4 and 13): each one
left the site down with nothing in the output saying why. The functions are
lifted out of the real scripts — the same trick tests/caddy_reload_test.py uses
— so these tests fail if the scripts change and the guards do not come with
them.
"""
from pathlib import Path
import gzip
import subprocess
import tempfile
import unittest

DEPLOY = Path(__file__).resolve().parents[1] / 'deploy'


def extract(script, name):
    """The shell function `name` as written in deploy/<script>."""
    source = (DEPLOY / script).read_text()
    marker = name + '() {'
    if marker not in source:
        raise AssertionError(f'{script} no longer defines {name}() — the guard it '
                             f'implements was removed or renamed')
    body = source.split(marker, 1)[1].split('\n}', 1)[0]
    return marker + body + '\n}\n'


# --- restore.sh: the schema preflight -----------------------------------------

PREFLIGHT_HARNESS = '''set -euo pipefail
ENV_FILE=env/production.env
PG_CID=fake-postgres
CONTAINER_TMP=/tmp/fake.dump
ALLOW_SCHEMA_MISMATCH=${ALLOW_SCHEMA_MISMATCH:-0}
COMPOSE=(compose)

log() { printf '[restore] %s\\n' "$*"; }
die() { printf '[restore] ERROR: %s\\n' "$*" >&2; exit 1; }
env_get() { printf '%s' "${PINNED_TAG:-v0.6.2}"; }

# Stands in for `docker exec … pg_restore --data-only -t <table> -f - <dump>`.
# DUMP_CORE / DUMP_SEARCH are "<version> <dirty>" or empty for "not in the dump".
docker() {
  local table=""
  while [ $# -gt 0 ]; do
    if [ "$1" = "-t" ]; then table="$2"; fi
    shift
  done
  local row=""
  case "$table" in
    schema_migrations)       row="${DUMP_CORE:-}" ;;
    vidra_search_migrations) row="${DUMP_SEARCH:-}" ;;
  esac
  [ -n "$row" ] || return 0
  printf 'SET statement_timeout = 0;\\n'
  printf 'COPY public.%s (version, dirty) FROM stdin;\\n' "$table"
  printf '%s\\t%s\\n' "${row%% *}" "${row##* }"
  printf '\\\\.\\n'
}

# Stands in for `compose run --rm --no-deps <svc> migrate embedded-max`.
# EMBEDDED_MAX empty means an image that does not know the subcommand.
compose() {
  if [ -z "${EMBEDDED_MAX:-}" ]; then
    printf 'unknown migrate subcommand "embedded-max"\\n' >&2
    return 1
  fi
  printf '%s\\n' "$EMBEDDED_MAX"
}
'''


class RestorePreflightTests(unittest.TestCase):
    def preflight(self, dump_core='', embedded='', allow='0', dirty_core=None,
                  dump_search='', label='core', service='migrate',
                  table='schema_migrations', tagkey='VIDRA_CORE_TAG'):
        script = (PREFLIGHT_HARNESS
                  + extract('restore.sh', 'dump_ledger_row')
                  + extract('restore.sh', 'image_embedded_max')
                  + extract('restore.sh', 'preflight_schema')
                  + f'\npreflight_schema {label} {service} {table} {tagkey}\n')
        env = {
            'PATH': '/usr/bin:/bin:/usr/sbin:/sbin',
            'DUMP_CORE': dump_core,
            'DUMP_SEARCH': dump_search,
            'EMBEDDED_MAX': embedded,
            'ALLOW_SCHEMA_MISMATCH': allow,
        }
        p = subprocess.run(['bash', '-c', script], capture_output=True, text=True, env=env)
        return p.returncode, p.stdout + p.stderr

    def test_dump_ahead_of_the_pinned_image_is_refused_before_the_drop(self):
        """A38 run 13: dump at 137, pinned v0.6.2 embeds 125."""
        code, out = self.preflight(dump_core='137 f', embedded='125')
        self.assertNotEqual(code, 0, out)
        self.assertIn('the dump is at 137', out)
        self.assertIn('carries up to 125', out)
        self.assertIn('--allow-schema-mismatch', out)
        self.assertIn('Nothing was changed', out)

    def test_the_override_downgrades_the_refusal_to_a_warning(self):
        code, out = self.preflight(dump_core='137 f', embedded='125', allow='1')
        self.assertEqual(code, 0, out)
        self.assertIn('WARNING', out)

    def test_dump_behind_the_image_is_the_documented_forward_path(self):
        code, out = self.preflight(dump_core='125 f', embedded='135')
        self.assertEqual(code, 0, out)
        self.assertIn('apply the difference', out)

    def test_dump_equal_to_the_image_passes(self):
        code, out = self.preflight(dump_core='135 f', embedded='135')
        self.assertEqual(code, 0, out)
        self.assertIn('nothing to apply', out)

    def test_a_dirty_dump_ledger_is_refused(self):
        """Both migrators refuse a dirty ledger, and they run AFTER the drop."""
        code, out = self.preflight(dump_core='137 t', embedded='999')
        self.assertNotEqual(code, 0, out)
        self.assertIn('DIRTY at version 137', out)

    def test_an_image_that_cannot_answer_is_reported_as_not_checked(self):
        """Every release cut before `migrate embedded-max` lands here. It must
        not refuse (that would break every restore today) and it must not claim
        the pairing was checked."""
        code, out = self.preflight(dump_core='137 f', embedded='')
        self.assertEqual(code, 0, out)
        self.assertIn('could NOT be checked', out)

    def test_a_ledger_absent_from_the_dump_is_skipped(self):
        code, out = self.preflight(dump_core='', embedded='135')
        self.assertEqual(code, 0, out)
        self.assertIn('nothing to compare', out)

    def test_the_search_ledger_is_read_from_its_own_table(self):
        code, out = self.preflight(dump_search='18 f', embedded='16',
                                   label='search', service='search-migrate',
                                   table='vidra_search_migrations',
                                   tagkey='VIDRA_SEARCH_TAG')
        self.assertNotEqual(code, 0, out)
        self.assertIn('the dump is at 18', out)
        self.assertIn('carries up to 16', out)

    def test_nothing_stops_the_site_until_every_validation_has_passed(self):
        """A37-3: the stop used to be the FIRST thing the script did, so a
        corrupt archive or a mismatched pairing took the site down and then
        correctly refused to change anything. Every refusal must now happen with
        api/search/frontend still serving. Indexes are taken over the COMMANDS,
        not the prose, so a comment mentioning `stop` cannot move them."""
        source = (DEPLOY / 'restore.sh').read_text()
        code = '\n'.join(l for l in source.splitlines()
                         if l.strip() and not l.lstrip().startswith('#'))
        stop = code.index('stop api search frontend')
        self.assertLess(code.index('gzip -dc'), stop,
                        'the archive must be decompressed before the site is stopped')
        self.assertLess(code.index('pg_restore -l'), stop,
                        'the archive must be validated before the site is stopped')
        self.assertLess(code.index('preflight_schema "core"'), stop,
                        'the schema preflight must run before the site is stopped')
        self.assertLess(stop, code.index('dropdb -U'),
                        'the site must be stopped before the database is dropped')

    def test_the_preflight_runs_before_the_drop(self):
        """Ordering is the whole point: a refusal must mean nothing happened.
        Indexes are taken over the COMMANDS, not the prose, so a comment
        mentioning dropdb cannot make this pass or fail by accident."""
        source = (DEPLOY / 'restore.sh').read_text()
        code = '\n'.join(l for l in source.splitlines()
                         if l.strip() and not l.lstrip().startswith('#'))
        self.assertLess(code.index('preflight_schema "core"'),
                        code.index('dropdb -U'),
                        'the schema preflight must run BEFORE the database is dropped')
        self.assertLess(code.index('pg_restore -l'),
                        code.index('preflight_schema "core"'),
                        'the archive must be validated before the preflight reads it')
        self.assertLess(code.index('preflight_schema "core"'),
                        code.index('log "running core migrations"'),
                        'the preflight must run before the real migrator step')


class RestoreArchiveDecompressionTests(unittest.TestCase):
    """A37-4: a corrupt .gz died on gzip's own message and nothing else, because
    the `*.gz)` branch was not `|| die`-guarded. `set -e` got the exit code right
    and left the operator reading a CRC error with no line saying the restore
    refused or that the database was untouched."""

    HARNESS = (
        'set -euo pipefail\n'
        'DUMP="$1"\n'
        'HOST_TMP="$2"\n'
        "log() { printf '[restore] %s\\n' \"$*\"; }\n"
        "die() { printf '[restore] ERROR: %s\\n' \"$*\" >&2; exit 1; }\n"
    )

    # A real pg_dump custom-format archive starts with this magic; the body is
    # filler, because nothing here parses the archive — it only decompresses it.
    FAKE_ARCHIVE = b'PGDMP not-a-real-dump-just-filler\n' * 64

    def decompress_block(self):
        """The `case "$DUMP" in … esac` normalisation block, verbatim from the
        real script, so this test fails if the guard is removed."""
        source = (DEPLOY / 'restore.sh').read_text()
        start = source.index('case "$DUMP" in')
        end = source.index('\nesac', start) + len('\nesac')
        return source[start:end]

    def run_block(self, dump):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out'
            script = self.HARNESS + self.decompress_block()
            p = subprocess.run(['bash', '-c', script, 'restore', str(dump), str(out)],
                               capture_output=True, text=True,
                               env={'PATH': '/usr/bin:/bin:/usr/sbin:/sbin'})
            return p.returncode, p.stdout + p.stderr

    def test_a_corrupt_gz_prints_the_scripts_own_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / 'vidra-corrupt.dump.gz'
            # Flip a byte inside the deflate stream: a real CRC failure, which is
            # what a truncated or bit-rotted transfer produces.
            corrupt = bytearray(gzip.compress(self.FAKE_ARCHIVE))
            corrupt[len(corrupt) // 2] ^= 0xFF
            bad.write_bytes(bytes(corrupt))
            code, out = self.run_block(bad)
        self.assertNotEqual(code, 0, out)
        self.assertIn('[restore] ERROR:', out)
        self.assertIn('could not be decompressed', out)
        self.assertIn('nothing was dropped', out)

    def test_a_file_that_is_not_gzip_at_all_lands_in_the_same_branch(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / 'not-really.dump.gz'
            bad.write_bytes(b'this is not a gzip stream')
            code, out = self.run_block(bad)
        self.assertNotEqual(code, 0, out)
        self.assertIn('[restore] ERROR:', out)

    def test_a_valid_gz_decompresses_without_complaint(self):
        with tempfile.TemporaryDirectory() as tmp:
            ok = Path(tmp) / 'vidra-good.dump.gz'
            ok.write_bytes(gzip.compress(self.FAKE_ARCHIVE))
            code, out = self.run_block(ok)
        self.assertEqual(code, 0, out)
        self.assertIn('decompressing', out)


class RollbackEnvRestoreTests(unittest.TestCase):
    """A38R-2: a refusal AFTER the env rewrite used to leave env/production.env
    pinned to the ROLLBACK TARGET while the pull message read
    "($ENV_FILE restored from ${ENV_FILE}.bak if you need to undo)" — which an
    operator mid-incident can read as a statement that it was. It was not. The
    running stack is untouched on every one of these paths, so the next command
    they type is the only casualty, and it reads tags that were never deployed."""

    HARNESS = (
        'set -euo pipefail\n'
        'ENV_FILE="$1"\n'
        "log() { printf '[rollback] %s\\n' \"$*\"; }\n"
        "die() { printf '[rollback] ERROR: %s\\n' \"$*\" >&2; exit 1; }\n"
    )

    BEFORE = 'VIDRA_CORE_TAG=v0.6.3\nVIDRA_USER_TAG=v0.6.3\n'
    AFTER = 'VIDRA_CORE_TAG=v0.6.2\nVIDRA_USER_TAG=v0.6.2\n'

    def run_helper(self, with_bak=True):
        with tempfile.TemporaryDirectory() as tmp:
            env = Path(tmp) / 'production.env'
            env.write_text(self.AFTER)          # already rewritten to the target
            if with_bak:
                Path(str(env) + '.bak').write_text(self.BEFORE)
            script = (self.HARNESS
                      + extract('rollback.sh', 'restore_env_and_die')
                      + '\nrestore_env_and_die "pull failed"\n')
            p = subprocess.run(['bash', '-c', script, 'rollback', str(env)],
                               capture_output=True, text=True,
                               env={'PATH': '/usr/bin:/bin'})
            return p.returncode, p.stdout + p.stderr, env.read_text()

    def test_a_refusal_puts_the_env_file_back(self):
        code, out, content = self.run_helper()
        self.assertNotEqual(code, 0, out)
        self.assertEqual(content, self.BEFORE,
                         'the env file must hold the tags that were being served')
        self.assertIn('restored', out)
        self.assertIn('[rollback] ERROR: pull failed', out)

    def test_a_missing_bak_says_so_instead_of_claiming_a_restore(self):
        """The one thing worse than not restoring is saying you did."""
        code, out, content = self.run_helper(with_bak=False)
        self.assertNotEqual(code, 0, out)
        self.assertEqual(content, self.AFTER)
        self.assertIn('could not restore', out)
        self.assertIn('backups/env-history/', out)

    def test_every_refusal_after_the_rewrite_goes_through_the_helper(self):
        """Counted over the CODE so the explanatory comments do not inflate it:
        the definition plus the checkout-sync trio, `config -q` and `pull`."""
        source = (DEPLOY / 'rollback.sh').read_text()
        code = [l for l in source.splitlines()
                if l.strip() and not l.lstrip().startswith('#')]
        uses = sum(1 for l in code if 'restore_env_and_die' in l)
        self.assertEqual(uses, 6, 'expected the definition plus the five refusal '
                                  'paths between the env rewrite and `up -d` '
                                  f'(checkout sync x3, config -q, pull), found {uses}')
        self.assertNotIn('restored from ${ENV_FILE}.bak if you need to undo',
                         '\n'.join(code),
                         'the message that reads as if the .bak had been restored '
                         'must not survive the fix (the comment above the helper '
                         'quotes it deliberately, which is why this reads the code)')

    def test_the_helper_sits_between_the_rewrite_and_up_d(self):
        source = (DEPLOY / 'rollback.sh').read_text()
        code = '\n'.join(l for l in source.splitlines()
                         if l.strip() and not l.lstrip().startswith('#'))
        self.assertLess(code.index('cp "$ENV_FILE" "${ENV_FILE}.bak"'),
                        code.index('restore_env_and_die() {'),
                        'the .bak must exist before anything can restore from it')
        self.assertLess(code.index('restore_env_and_die "pull failed'),
                        code.index('log "restarting"'),
                        'every path the helper guards must come before `up -d`')


# --- rollback.sh: the trailer survives a failing `up -d` ----------------------

class RollbackTrailerTests(unittest.TestCase):
    def run_up(self, up_fails):
        source = (DEPLOY / 'rollback.sh').read_text()
        # The `up -d` call and its guard, verbatim from the script.
        start = source.index('log "restarting"')
        end = source.index('probe() {')
        up_block = source[start:end]
        script = '''set -euo pipefail
COMPOSE=(compose)
log() { printf '[rollback] %s\\n' "$*"; }
compose() {
  printf 'compose %s\\n' "$*"
  [ "${UP_FAILS:-0}" = "1" ] || return 0
  printf 'dependency failed to start: container vidra-migrate-1 exited (1)\\n' >&2
  return 1
}
''' + extract('rollback.sh', 'rollback_target_unhealthy') + up_block
        p = subprocess.run(['bash', '-c', script], capture_output=True, text=True,
                           env={'PATH': '/usr/bin:/bin', 'UP_FAILS': '1' if up_fails else '0'})
        return p.returncode, p.stdout + p.stderr

    def test_a_failing_up_still_prints_the_trailer(self):
        """A38 run 4: `set -e` used to kill the script here, so the operator got
        a raw compose error, a dark site, and no next step."""
        code, out = self.run_up(up_fails=True)
        self.assertNotEqual(code, 0, out)
        self.assertIn('THE ROLLBACK TARGET IS ALSO UNHEALTHY', out)
        self.assertIn('restore.sh backups/pre-deploy-', out)
        self.assertIn('logs migrate search-migrate', out)

    def test_a_successful_up_prints_no_trailer(self):
        code, out = self.run_up(up_fails=False)
        self.assertEqual(code, 0, out)
        self.assertNotIn('UNHEALTHY', out)

    def test_the_probe_path_uses_the_same_trailer(self):
        """One trailer, two failure paths — counted over the CODE so the
        explanatory comments above `up -d` do not inflate it."""
        source = (DEPLOY / 'rollback.sh').read_text()
        code = [l for l in source.splitlines()
                if l.strip() and not l.lstrip().startswith('#')]
        uses = sum(1 for l in code if 'rollback_target_unhealthy' in l)
        self.assertEqual(uses, 3, 'expected the definition plus both failure '
                                  'paths (`up -d` and the readiness probes), '
                                  f'found {uses}')
        self.assertEqual(source.count('THE ROLLBACK TARGET IS ALSO UNHEALTHY'), 1,
                         'the trailer text must live in exactly one place')


if __name__ == '__main__':
    unittest.main()
