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
import subprocess
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
