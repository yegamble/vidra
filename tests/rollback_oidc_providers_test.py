"""rollback.sh refuses an app-only rollback that would run a core release
unaware of admin-managed OIDC providers while the data holds some.

vidra-core migration 0182_oidc_providers adds providers that can OVERRIDE or
DISABLE the environment-configured ones. A core release without that migration
FILE ignores the table, so environment providers return without the admin's
restrictions. Severity: rows + older target refuses (unless
--allow-oidc-env-fallback); an empty table only warns. Same stubbing approach as
tests/rollback_word_lists_test.py: the REAL rollback.sh, lib.sh and
release-mapping.py, with docker/git/curl stubbed and every call logged.
"""
import json
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


MIGRATION = rollback_constant('OIDC_PROVIDERS_MIGRATION')

# OIDC_ANSWER scripts the answer to the OIDC-providers question: t, f, err, timeout or
# norel (the table does not exist yet). The word-lists and privacy-tier questions always answer f.
DOCKER_STUB = r'''#!/bin/sh
printf 'docker %s\n' "$*" >> "$STUB_LOG"
case "$*" in
  "compose version --short") echo v2.30.0 ;;
  *" ps -q postgres")
    [ "${PG_DOWN:-0}" = 1 ] || echo pgcid ;;
  exec*"FROM watched_word_lists"*) echo f ;;
  exec*"FROM oidc_providers"*)
    case "$OIDC_ANSWER" in
      err) echo 'psql: error: connection to server failed' >&2; exit 2 ;;
      timeout) echo 'ERROR:  canceling statement due to statement timeout' >&2; exit 1 ;;
      norel) echo 'ERROR:  relation "oidc_providers" does not exist' >&2; exit 1 ;;
    esac
    echo "$OIDC_ANSWER" ;;
  exec*"FROM oidc_providers"*) echo f ;;
  exec*"SELECT EXISTS"*) echo f ;;
esac
exit 0
'''


class RollbackOidcProvidersGateTests(unittest.TestCase):
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
        (self.tree / 'vidra-bundle.manifest').write_text('tag=v0.8.1\ncore_schema_version=0182\n')
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

    def carrying_record(self):
        """A synthetic v0.8.0 record whose core lists the migration file."""
        data = json.loads((ROOT / 'releases' / 'v0.7.7.json').read_text())
        data['release'] = 'v0.8.0'
        data['components']['core']['tag'] = 'v0.8.0'
        data['core_schema_version'] = 182
        data['core_migrations'] = sorted(['0001_init.up.sql', MIGRATION])
        (self.tree / 'releases' / 'v0.8.0.json').write_text(json.dumps(data, indent=2))

    def rollback(self, *args, answer='f'):
        result = subprocess.run(
            ['bash', str(self.tree / 'deploy/rollback.sh'), *args],
            env={**os.environ, 'PATH': f'{self.bin}:{os.environ["PATH"]}',
                 'HOME': str(self.temp.name) + '/home', 'STUB_LOG': str(self.log),
                 'READY_TIMEOUT': '1', 'VIDRA_RECORD_FETCH': '0', 'OIDC_ANSWER': answer,
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
        self.assertEqual(MIGRATION, '0182_oidc_providers.up.sql')

    def test_rows_and_an_older_target_are_refused(self):
        before = self.env_file.read_bytes()
        code, out = self.rollback('v0.7.7', answer='t')
        self.assertNotEqual(code, 0, out)
        self.assertIn(f'does not carry migration {MIGRATION}', out)
        self.assertIn('admin-managed OIDC providers', out)
        self.assertIn('--allow-oidc-env-fallback', out)
        self.assertIn('Nothing was changed', out)
        self.assert_untouched(before, out)

    def test_an_empty_table_only_warns(self):
        code, out = self.rollback('v0.7.7', answer='f')
        self.assertEqual(code, 0, out)
        self.assertIn('WARNING: oidc-providers check', out)
        self.assertIn('oidc_providers is empty', out)
        self.assertTrue(self.ran(' up -d'))

    def test_a_database_below_the_migration_has_nothing_to_protect(self):
        code, out = self.rollback('v0.7.7', answer='norel')
        self.assertEqual(code, 0, out)
        self.assertTrue(self.ran(' up -d'))

    def test_a_target_carrying_the_migration_passes_without_asking(self):
        self.carrying_record()
        code, out = self.rollback('v0.8.0', answer='t')
        self.assertEqual(code, 0, out)
        self.assertIn(f'carries migration {MIGRATION}', out)
        self.assertFalse(self.ran('FROM oidc_providers'), out)

    def test_the_override_flag_proceeds_with_a_warning(self):
        code, out = self.rollback('v0.7.7', '--allow-oidc-env-fallback', answer='t')
        self.assertEqual(code, 0, out)
        self.assertIn('WARNING: oidc-providers check', out)
        self.assertIn('--allow-oidc-env-fallback was given', out)
        self.assertTrue(self.ran(' up -d'))

    def test_a_rollback_that_leaves_core_alone_is_not_checked(self):
        code, out = self.rollback('--user', 'v0.7.7', answer='t')
        self.assertEqual(code, 0, out)
        self.assertIn('oidc-providers check: core is not being rolled back', out)
        self.assertFalse(self.ran('FROM oidc_providers'), out)

    def test_every_query_is_read_only_and_bounded(self):
        self.rollback('v0.7.7', answer='f')
        asks = [line for line in self.calls() if 'FROM oidc_providers' in line]
        self.assertTrue(asks, 'the database was never asked')
        for line in asks:
            self.assertIn('default_transaction_read_only=on', line)
            self.assertIn('statement_timeout=15s', line)
            self.assertIn('lock_timeout=5s', line)
            self.assertIn('PGCONNECT_TIMEOUT=', line)

    def test_a_check_that_cannot_run_refuses_unless_overridden(self):
        for label, answer, says in (('psql error', 'err', 'connection to server failed'),
                                    ('statement timeout', 'timeout', 'TIMED OUT')):
            with self.subTest(case=label):
                self.log.unlink(missing_ok=True)
                before = self.env_file.read_bytes()
                code, out = self.rollback('v0.7.7', answer=answer)
                self.assertNotEqual(code, 0, out)
                self.assertIn('oidc-providers check could not be made', out)
                self.assertIn(says, out)
                self.assert_untouched(before, out)

                self.log.unlink(missing_ok=True)
                code, out = self.rollback('v0.7.7', '--allow-oidc-env-fallback', answer=answer)
                self.assertEqual(code, 0, out)
                self.assertIn('WARNING: oidc-providers check', out)


if __name__ == '__main__':
    unittest.main()
