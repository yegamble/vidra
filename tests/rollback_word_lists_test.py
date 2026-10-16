"""rollback.sh refuses an app-only rollback that would run a core release
unaware of named watched-word lists while the data uses them.

vidra-core migration 0172_watched_word_lists adds per-account lists and a
'hold' action. A core release without that migration FILE ignores both: it
matches creators' PRIVATE terms into the staff review queue and publishes
comments a 'hold' list holds. rollback.sh never migrates down, so it must
refuse - in the style of tests/rollback_privacy_tier_test.py, which this reuses
the stubbing approach of: the REAL rollback.sh, lib.sh and release-mapping.py,
with docker/git/curl stubbed and every call logged.
"""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def rollback_constant(name):
    for line in (ROOT / 'deploy' / 'rollback.sh').read_text().splitlines():
        if line.startswith(name + '='):
            return line.split('=', 1)[1].strip().strip('"')
    raise AssertionError(f'deploy/rollback.sh no longer assigns {name}')


MIGRATION = rollback_constant('WORD_LISTS_MIGRATION')

# WL_ANSWERS scripts the answer to the word-lists question: t, f, err, timeout or
# norel (the table does not exist yet). The privacy-tier question always answers f.
DOCKER_STUB = r'''#!/bin/sh
printf 'docker %s\n' "$*" >> "$STUB_LOG"
case "$*" in
  "compose version --short") echo v2.30.0 ;;
  *" ps -q postgres")
    [ "${PG_DOWN:-0}" = 1 ] || echo pgcid ;;
  exec*"FROM watched_word_lists"*)
    case "$WL_ANSWER" in
      err) echo 'psql: error: connection to server failed' >&2; exit 2 ;;
      timeout) echo 'ERROR:  canceling statement due to statement timeout' >&2; exit 1 ;;
      norel) echo 'ERROR:  relation "watched_word_lists" does not exist' >&2; exit 1 ;;
    esac
    echo "$WL_ANSWER" ;;
  exec*"FROM comments WHERE held_for_review"*) printf 'f\nf\n' ;;
  exec*"FROM oidc_providers"*) echo f ;;
  exec*"SELECT EXISTS"*) echo f ;;
esac
exit 0
'''


class RollbackWordListsGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.tree = base / 'tree'
        (self.tree / 'deploy').mkdir(parents=True)
        (self.tree / 'env').mkdir()
        for name in ('rollback.sh', 'lib.sh', 'checkout-hygiene.py', 'backup-env.sh',
                     'release-mapping.py'):
            shutil.copyfile(ROOT / 'deploy' / name, self.tree / 'deploy' / name)
        shutil.copytree(ROOT / 'releases', self.tree / 'releases')
        (self.tree / 'vidra-bundle.manifest').write_text('tag=v0.8.1\ncore_schema_version=0172\n')
        self.env_file = self.tree / 'env/production.env'
        self.env_file.write_text('VIDRA_TLS_MODE=external\nPOSTGRES_USER=vidra\nPOSTGRES_DB=vidra\n'
                                 'VIDRA_CORE_TAG=v0.8.1\nVIDRA_USER_TAG=v0.8.1\nVIDRA_SEARCH_TAG=v0.7.3\n')
        (base / 'home').mkdir()
        self.bin = base / 'bin'
        self.bin.mkdir()
        self.log = base / 'stub.log'
        for name, body in (('docker', DOCKER_STUB), ('git', '#!/bin/sh\nexit 0\n'),
                           ('curl', '#!/bin/sh\nexit 0\n')):
            (self.bin / name).write_text(body)
            (self.bin / name).chmod(0o755)

    def rollback(self, *args, answer='f'):
        result = subprocess.run(
            ['bash', str(self.tree / 'deploy/rollback.sh'), *args],
            env={**os.environ, 'PATH': f'{self.bin}:{os.environ["PATH"]}',
                 'HOME': str(self.temp.name) + '/home', 'STUB_LOG': str(self.log),
                 'READY_TIMEOUT': '1', 'VIDRA_RECORD_FETCH': '0', 'WL_ANSWER': answer,
                 'PG_DOWN': '0'},
            capture_output=True, text=True, cwd=str(self.tree))
        return result.returncode, result.stdout + result.stderr

    def calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def ran(self, needle):
        return any(needle in line for line in self.calls())

    def assert_untouched(self, before, out):
        self.assertEqual(self.env_file.read_bytes(), before, 'the env file was rewritten')
        for mutation in (' pull', ' up -d'):
            self.assertFalse(self.ran(mutation), f'{mutation!r} ran before the refusal:\n{out}')

    def test_the_migration_is_identified_by_file_name(self):
        self.assertEqual(MIGRATION, '0172_watched_word_lists.up.sql')

    def test_a_target_below_the_migration_is_refused_while_lists_are_in_use(self):
        before = self.env_file.read_bytes()
        code, out = self.rollback('v0.7.7', answer='t')
        self.assertNotEqual(code, 0, out)
        self.assertIn(f'does not carry migration {MIGRATION}', out)
        self.assertIn("per-account or 'hold' watched-word lists", out)
        self.assertIn('Nothing was changed', out)
        self.assert_untouched(before, out)

    def test_no_flag_waves_through_a_definite_finding(self):
        before = self.env_file.read_bytes()
        code, out = self.rollback('v0.7.7', '--allow-unchecked-word-lists', answer='t')
        self.assertNotEqual(code, 0, out)
        self.assertIn('DELETE FROM watched_word_lists WHERE owner_id IS NOT NULL', out)
        self.assert_untouched(before, out)

    def test_it_proceeds_when_no_private_or_hold_list_exists(self):
        code, out = self.rollback('v0.7.7', answer='f')
        self.assertEqual(code, 0, out)
        self.assertIn("no per-account or 'hold' watched-word list exists", out)
        self.assertTrue(self.ran(' up -d'))

    def test_a_database_below_the_migration_has_nothing_to_protect(self):
        code, out = self.rollback('v0.7.7', answer='norel')
        self.assertEqual(code, 0, out)
        self.assertTrue(self.ran(' up -d'))

    def test_a_rollback_that_leaves_core_alone_is_not_checked(self):
        code, out = self.rollback('--user', 'v0.7.7', answer='t')
        self.assertEqual(code, 0, out)
        self.assertIn('word-lists check: core is not being rolled back', out)
        self.assertFalse(self.ran('FROM watched_word_lists'), out)

    def test_every_query_is_read_only_and_bounded(self):
        self.rollback('v0.7.7', answer='f')
        asks = [line for line in self.calls() if 'FROM watched_word_lists' in line]
        self.assertTrue(asks, 'the database was never asked')
        for line in asks:
            self.assertIn('default_transaction_read_only=on', line)
            self.assertIn('statement_timeout=15s', line)
            self.assertIn('lock_timeout=5s', line)
            self.assertIn('PGCONNECT_TIMEOUT=', line)

    def test_a_check_that_cannot_run_refuses_unless_overridden(self):
        for label, kwargs, says in (
                ('psql error', {'answer': 'err'}, 'connection to server failed'),
                ('statement timeout', {'answer': 'timeout'}, 'TIMED OUT')):
            with self.subTest(case=label):
                self.log.unlink(missing_ok=True)
                before = self.env_file.read_bytes()
                code, out = self.rollback('v0.7.7', **kwargs)
                self.assertNotEqual(code, 0, out)
                self.assertIn('word-lists check could not be made', out)
                self.assertIn(says, out)
                self.assertIn('--allow-unchecked-word-lists', out)
                self.assert_untouched(before, out)

                self.log.unlink(missing_ok=True)
                code, out = self.rollback('v0.7.7', '--allow-unchecked-word-lists', **kwargs)
                self.assertEqual(code, 0, out)
                self.assertIn('WARNING: word-lists check NOT settled', out)

    def test_a_target_no_record_places_is_treated_as_predating(self):
        before = self.env_file.read_bytes()
        code, out = self.rollback('--core', 'v0.7.9', answer='t')
        self.assertNotEqual(code, 0, out)
        self.assertIn('could not be placed', out)
        self.assert_untouched(before, out)


if __name__ == '__main__':
    unittest.main()
