"""rollback.sh refuses an app-only rollback that would run a core release
unaware of a privacy tier present in the data.

vidra-core migration 0160 adds the 'internal' video privacy tier. A core release
whose embedded migrations stop below 0160 does not know it, and rollback.sh
never migrates down — so with videos at 'internal' it must refuse, or remap
them when told to by name, or proceed on an explicit override when the check
could not be made.

Two layers, no stack:
  * `deploy/release-mapping.py core-migration`, the record reader that decides
    whether a target core "predates" a migration, against synthetic records;
  * the REAL rollback.sh, lib.sh and release-mapping.py end to end, with
    docker/git/curl stubbed the way tests/rollback_pairing_test.py stubs them.
    The docker stub plays a postgres whose answers each test scripts, and logs
    every call so ordering (refuse before rewrite, remap after pull and before
    `up -d`) is asserted on what actually ran.
"""
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
MAPPING = ROOT / 'deploy' / 'release-mapping.py'
MIGRATION = '160'
CARRIES, PREDATES, UNKNOWN = 0, 4, 3


def future_record(directory, release, core, schema, user=None):
    """A valid record for a release that does not exist yet, cloned from the
    newest real one so it passes the checker's own validate()."""
    data = json.loads((ROOT / 'releases' / 'v0.7.7.json').read_text())
    data['release'] = release
    data['core_schema_version'] = schema
    data['components']['core']['tag'] = core
    data['components']['user']['tag'] = user or release
    (Path(directory) / f'{release}.json').write_text(json.dumps(data, indent=2))


class CoreMigrationTests(unittest.TestCase):
    """Which side of migration 0160 a core tag is on, from the records alone."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.releases = Path(self.temp.name) / 'releases'
        shutil.copytree(ROOT / 'releases', self.releases)

    def ask(self, core, releases=None):
        p = subprocess.run(['python3', str(MAPPING), 'core-migration',
                            '--releases', str(releases or self.releases),
                            '--core', core, '--migration', MIGRATION],
                           capture_output=True, text=True)
        return p.returncode, p.stdout + p.stderr

    def test_a_recorded_core_below_the_migration_predates_it(self):
        code, out = self.ask('v0.7.7')
        self.assertEqual(code, PREDATES, out)
        self.assertIn('releases/v0.7.7.json records core v0.7.7 with migrations through 151', out)

    def test_an_unrecorded_older_core_is_placed_by_the_nearest_newer_record(self):
        """v0.2.0 to v0.6.3 have no records; v0.7.6 was never recorded either."""
        for core, nearest in (('v0.7.6', 'v0.7.7'), ('v0.6.3', 'v0.6.4'), ('v0.2.0', 'v0.6.4')):
            with self.subTest(core=core):
                code, out = self.ask(core)
                self.assertEqual(code, PREDATES, out)
                self.assertIn(f'records core {nearest} (the nearest recorded core to {core})', out)

    def test_a_recorded_core_at_or_past_the_migration_carries_it(self):
        future_record(self.releases, 'v0.8.0', 'v0.8.0', 160)
        for core in ('v0.8.0', 'v0.8.1'):   # v0.8.1: unrecorded, newer than one that carries it
            with self.subTest(core=core):
                code, out = self.ask(core)
                self.assertEqual(code, CARRIES, out)

    def test_a_core_no_record_places_is_unknown_never_carries(self):
        code, out = self.ask('v0.7.9')   # newer than every record, none carries 160
        self.assertEqual(code, UNKNOWN, out)
        future_record(self.releases, 'v0.8.0', 'v0.8.0', 160)
        code, out = self.ask('v0.7.9')   # between a record below 160 and one at 160
        self.assertEqual(code, UNKNOWN, out)

    def test_a_prerelease_is_not_vouched_for_by_its_release(self):
        """v0.8.0-rc1 may have been cut before 0160 merged."""
        future_record(self.releases, 'v0.8.0', 'v0.8.0', 160)
        code, out = self.ask('v0.8.0-rc1')
        self.assertEqual(code, UNKNOWN, out)

    def test_records_that_disagree_decide_nothing(self):
        future_record(self.releases, 'v0.8.0', 'v0.8.0', 160)
        future_record(self.releases, 'v0.8.2', 'v0.8.2', 155)   # non-linear history
        code, out = self.ask('v0.8.1')
        self.assertEqual(code, UNKNOWN, out)
        self.assertIn('disagree', out)

    def test_no_releases_directory_is_unknown(self):
        code, out = self.ask('v0.7.7', releases=Path(self.temp.name) / 'nowhere')
        self.assertEqual(code, UNKNOWN, out)

    def test_both_arguments_are_required(self):
        p = subprocess.run(['python3', str(MAPPING), 'core-migration', '--core', 'v0.7.7'],
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 2, p.stderr)


# The postgres this stub plays answers `SELECT EXISTS` from DB_ANSWERS — one
# word per ask (t, f, or err), the last repeating — and the remap UPDATE from
# REMAP_IDS, once: after it the database really has no 'internal' video left.
DOCKER_STUB = r'''#!/bin/sh
printf 'docker %s\n' "$*" >> "$STUB_LOG"
case "$*" in
  "compose version --short") echo v2.30.0 ;;
  *" ps -q postgres") [ "${PG_DOWN:-0}" = 1 ] || echo pgcid ;;
  exec*"SELECT EXISTS"*)
    n=$(( $(cat "$STUB_STATE/asked" 2>/dev/null || echo 0) + 1 ))
    echo "$n" > "$STUB_STATE/asked"
    answer=$(echo $DB_ANSWERS | awk -v n="$n" '{ print (n <= NF) ? $n : $NF }')
    [ ! -f "$STUB_STATE/remapped" ] || answer=f
    if [ "$answer" = err ]; then
      echo 'psql: error: connection to server failed' >&2
      exit 2
    fi
    echo "$answer" ;;
  exec*"UPDATE videos"*)
    [ ! -f "$STUB_STATE/remapped" ] || exit 0
    touch "$STUB_STATE/remapped"
    for id in $REMAP_IDS; do echo "$id"; done ;;
esac
exit 0
'''

IDS = ('3f1c2a4e-0000-4000-8000-000000000001', '3f1c2a4e-0000-4000-8000-000000000002')


class RollbackPrivacyGateTests(unittest.TestCase):
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
        # An unpacked bundle: no git to sync, so the stubs see every step.
        (self.tree / 'vidra-bundle.manifest').write_text('tag=v0.8.1\ncore_schema_version=0160\n')
        self.env_file = self.tree / 'env/production.env'
        self.write_env()
        self.home = base / 'home'
        self.home.mkdir()
        self.state = base / 'state'
        self.state.mkdir()
        self.bin = base / 'bin'
        self.bin.mkdir()
        self.log = base / 'stub.log'
        for name, body in (('docker', DOCKER_STUB),
                           ('git', '#!/bin/sh\nexit 0\n'),
                           ('curl', '#!/bin/sh\nexit 0\n')):
            (self.bin / name).write_text(body)
            (self.bin / name).chmod(0o755)

    def write_env(self, extra=''):
        self.env_file.write_text('VIDRA_TLS_MODE=external\nPOSTGRES_USER=vidra\nPOSTGRES_DB=vidra\n'
                                 'VIDRA_CORE_TAG=v0.8.1\nVIDRA_USER_TAG=v0.8.1\n'
                                 'VIDRA_SEARCH_TAG=v0.7.3\n' + extra)

    def rollback(self, *args, answers='f', pg_down=False):
        result = subprocess.run(
            ['bash', str(self.tree / 'deploy/rollback.sh'), *args],
            env={**os.environ, 'PATH': f'{self.bin}:{os.environ["PATH"]}', 'HOME': str(self.home),
                 'STUB_LOG': str(self.log), 'STUB_STATE': str(self.state), 'READY_TIMEOUT': '1',
                 'VIDRA_RECORD_FETCH': '0', 'DB_ANSWERS': answers,
                 'PG_DOWN': '1' if pg_down else '0', 'REMAP_IDS': ' '.join(IDS)},
            capture_output=True, text=True, cwd=str(self.tree))
        return result.returncode, result.stdout + result.stderr

    def calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def first(self, needle):
        for index, line in enumerate(self.calls()):
            if needle in line:
                return index
        self.fail(f'{needle!r} never ran:\n' + '\n'.join(self.calls()))

    def assert_untouched(self, before, out):
        """A refusal at the gate: env byte-for-byte, nothing pulled, restarted
        or written to the database."""
        self.assertEqual(self.env_file.read_bytes(), before, 'the env file was rewritten')
        for mutation in (' pull', ' up -d', 'UPDATE videos'):
            self.assertFalse(any(mutation in line for line in self.calls()),
                             f'{mutation!r} ran before the refusal:\n{out}')

    def assert_read_only(self):
        asks = [line for line in self.calls() if 'SELECT EXISTS' in line]
        self.assertTrue(asks, 'the database was never asked')
        for line in asks:
            self.assertIn('PGOPTIONS=-c default_transaction_read_only=on', line)

    # --- the five cases the gate exists for --------------------------------

    def test_a_target_that_predates_the_tier_is_refused_while_videos_use_it(self):
        before = self.env_file.read_bytes()
        code, out = self.rollback('v0.7.7', answers='t')
        self.assertNotEqual(code, 0, out)
        self.assertIn('predates migration 160', out)
        self.assertIn('--remap-internal-to-private', out)
        self.assertIn('Nothing was changed', out)
        self.assert_untouched(before, out)
        self.assert_read_only()

    def test_a_target_that_predates_the_tier_proceeds_when_no_video_uses_it(self):
        code, out = self.rollback('v0.7.7', answers='f')
        self.assertEqual(code, 0, out)
        self.assertIn("no video is at privacy 'internal'", out)
        self.assertLess(self.first(' pull'), self.first(' up -d'))
        # Asked at the gate, again after the pull, and once the target runs.
        self.assertEqual(sum('SELECT EXISTS' in line for line in self.calls()), 3)
        self.assertFalse(any('UPDATE videos' in line for line in self.calls()))
        self.assert_read_only()

    def test_a_target_that_carries_the_tier_never_asks_the_database(self):
        future_record(self.tree / 'releases', 'v0.8.0', 'v0.8.0', 160, user='v0.8.0')
        code, out = self.rollback('--core', 'v0.8.0', answers='t')
        self.assertEqual(code, 0, out)
        self.assertIn('carries migration 160', out)
        self.assertFalse(any('SELECT EXISTS' in line for line in self.calls()), out)
        self.assertIn(' up -d', '\n'.join(self.calls()))

    def test_a_rollback_that_leaves_core_alone_is_not_checked(self):
        code, out = self.rollback('--user', 'v0.7.7', answers='t')
        self.assertEqual(code, 0, out)
        self.assertIn('core is not being rolled back', out)
        self.assertFalse(any('SELECT EXISTS' in line for line in self.calls()), out)

    def test_a_check_that_cannot_run_refuses_unless_overridden(self):
        for label, kwargs, extra in (
                ('psql error', {'answers': 'err'}, ''),
                ('postgres not running', {'pg_down': True}, ''),
                ('external postgres', {}, 'VIDRA_EXTERNAL_POSTGRES=true\n'
                                          'DATABASE_URL=postgres://u:p@db.example:5432/vidra\n')):
            with self.subTest(case=label):
                self.write_env(extra)
                self.log.unlink(missing_ok=True)
                before = self.env_file.read_bytes()
                code, out = self.rollback('v0.7.7', **kwargs)
                self.assertNotEqual(code, 0, out)
                self.assertIn('could not be made', out)
                self.assertIn('--allow-unchecked-privacy-tier', out)
                self.assert_untouched(before, out)

                self.log.unlink(missing_ok=True)
                code, out = self.rollback('v0.7.7', '--allow-unchecked-privacy-tier', **kwargs)
                self.assertEqual(code, 0, out)
                self.assertIn('WARNING: privacy-tier check NOT settled', out)
                self.assertIn(' up -d', '\n'.join(self.calls()))

    def test_the_remap_flag_remaps_after_the_pull_and_before_the_restart(self):
        code, out = self.rollback('v0.7.7', '--remap-internal-to-private', answers='t')
        self.assertEqual(code, 0, out)
        self.assertLess(self.first(' pull'), self.first('UPDATE videos'))
        self.assertLess(self.first('UPDATE videos'), self.first(' up -d'))
        update = self.calls()[self.first('UPDATE videos')]
        self.assertIn("UPDATE videos SET privacy = 'private' WHERE privacy = 'internal' RETURNING id;",
                      update)
        self.assertIn(' -1 ', update, 'the remap must run as one transaction')
        self.assertIn("remapped 2 video(s) from privacy 'internal' to 'private'", out)
        self.assertIn('remapped 0 video(s)', out, 'the post-restart pass must run too')
        [ids] = list((self.tree / 'backups').glob('internal-privacy-remap-*.ids'))
        self.assertEqual(ids.read_text().split(), list(IDS))
        self.assertEqual(stat.S_IMODE(ids.stat().st_mode), 0o600)
        self.assertIn('VIDRA_CORE_TAG=v0.7.7', self.env_file.read_text())

    # --- the edges around them ---------------------------------------------

    def test_the_override_does_not_wave_through_a_definite_finding(self):
        before = self.env_file.read_bytes()
        code, out = self.rollback('v0.7.7', '--allow-unchecked-privacy-tier', answers='t')
        self.assertNotEqual(code, 0, out)
        self.assertIn('--remap-internal-to-private', out)
        self.assert_untouched(before, out)

    def test_a_target_no_record_places_is_treated_as_predating(self):
        before = self.env_file.read_bytes()
        code, out = self.rollback('--core', 'v0.7.9', answers='t')
        self.assertNotEqual(code, 0, out)
        self.assertIn('could not be placed', out)
        self.assert_untouched(before, out)
        code, out = self.rollback('--core', 'v0.7.9', '--allow-unchecked-privacy-tier', answers='t')
        self.assertEqual(code, 0, out)

    def test_a_video_put_at_internal_during_the_pull_stops_the_restart(self):
        before = self.env_file.read_bytes()
        code, out = self.rollback('v0.7.7', answers='f t')
        self.assertNotEqual(code, 0, out)
        self.assertIn('while this rollback was pulling', out)
        self.assertIn(' pull', '\n'.join(self.calls()))
        self.assertFalse(any(' up -d' in line for line in self.calls()), out)
        self.assertEqual(self.env_file.read_bytes(), before, 'the env file was not restored')


if __name__ == '__main__':
    unittest.main()
