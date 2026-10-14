"""rollback.sh refuses an app-only rollback that would run a core release
unaware of a privacy tier present in the data.

vidra-core migration 0160_video_privacy_internal adds the 'internal' video
privacy tier. A core release that does not carry that migration FILE does not
know the tier, and rollback.sh never migrates down — so with videos at
'internal' it must refuse, or remap them when told to by name, or proceed on an
explicit override when the check could not be made.

The tier is identified by the migration's FILE NAME, never by a number: a
record's core_schema_version says how far the ledger reaches, not what is in
it, and core PRs 0158-0161 were open at once — a later-numbered migration
shipping first must not make a release read as carrying this one.

Two layers, no stack:
  * `deploy/release-mapping.py core-migration`, the record reader that decides
    whether a target core carries the migration, against synthetic records;
  * the REAL rollback.sh, lib.sh and release-mapping.py end to end, with
    docker/git/curl stubbed the way tests/rollback_pairing_test.py stubs them.
    The docker stub plays a postgres whose answers each test scripts, and logs
    every call so ordering (refuse before rewrite, remap after pull and before
    `up -d`) is asserted on what actually ran.
"""
import importlib.util
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
CARRIES, PREDATES, UNKNOWN = 0, 4, 3


def rollback_constant(name):
    """A constant as rollback.sh assigns it, so the tests ask about exactly the
    migration the script does and a renumber stays a one-line change."""
    for line in (ROOT / 'deploy' / 'rollback.sh').read_text().splitlines():
        if line.startswith(name + '='):
            return line.split('=', 1)[1].strip().strip('"')
    raise AssertionError(f'deploy/rollback.sh no longer assigns {name}')


MIGRATION = rollback_constant('INTERNAL_PRIVACY_MIGRATION')
OTHER = '0161_something_else.up.sql'

_spec = importlib.util.spec_from_file_location('release_mapping_privacy', MAPPING)
mapping = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mapping)


def future_record(directory, release, core, schema, user=None, migrations=None):
    """A valid record for a release that does not exist yet, cloned from the
    newest real one so it passes the checker's own validate(). `migrations` is
    the core_migrations list a record cut by deploy/release.sh carries."""
    data = json.loads((ROOT / 'releases' / 'v0.7.7.json').read_text())
    data['release'] = release
    data['core_schema_version'] = schema
    data['components']['core']['tag'] = core
    data['components']['user']['tag'] = user or release
    if migrations is not None:
        data['core_migrations'] = sorted(migrations)
    (Path(directory) / f'{release}.json').write_text(json.dumps(data, indent=2))
    return data


class IdentifierTests(unittest.TestCase):
    def test_the_tier_is_identified_by_vidra_cores_migration_file_name(self):
        """It must match vidra-core's migrations/<file> exactly; see the
        comment on INTERNAL_PRIVACY_MIGRATION in deploy/rollback.sh."""
        self.assertEqual(MIGRATION, '0160_video_privacy_internal.up.sql')


class RecordValidationTests(unittest.TestCase):
    """core_migrations is optional (records cut before it lack it), and when
    present it must be the list release.sh would write, or it vouches for
    nothing."""

    def problems(self, mutate):
        with tempfile.TemporaryDirectory() as tmp:
            data = future_record(tmp, 'v0.8.0', 'v0.8.0', 160,
                                 migrations=['0001_init.up.sql', MIGRATION])
            mutate(data)
            path = Path(tmp) / 'v0.8.0.json'
            return mapping.validate(path, data)

    def test_a_well_formed_list_passes(self):
        self.assertEqual(self.problems(lambda d: None), [])

    def test_a_record_without_the_list_still_passes(self):
        self.assertEqual(self.problems(lambda d: d.pop('core_migrations')), [])

    def test_bad_lists_are_refused(self):
        for label, mutate in (
                ('not a list', lambda d: d.update(core_migrations='0160_x.up.sql')),
                ('empty', lambda d: d.update(core_migrations=[])),
                ('not a file name', lambda d: d.update(core_migrations=['0001_init.up.sql', '0160'])),
                ('a down migration', lambda d: d.update(
                    core_migrations=['0001_init.up.sql', '0160_video_privacy_internal.down.sql'])),
                ('duplicates', lambda d: d.update(core_migrations=[MIGRATION, MIGRATION])),
                ('disagrees with core_schema_version', lambda d: d.update(core_schema_version=161))):
            with self.subTest(case=label):
                self.assertTrue(self.problems(mutate), label)


class CoreMigrationTests(unittest.TestCase):
    """Whether a core tag carries the migration FILE, from the records alone."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.releases = Path(self.temp.name) / 'releases'
        shutil.copytree(ROOT / 'releases', self.releases)

    def ask(self, core, releases=None, migration=None):
        p = subprocess.run(['python3', str(MAPPING), 'core-migration',
                            '--releases', str(releases or self.releases),
                            '--core', core, '--migration', migration or MIGRATION],
                           capture_output=True, text=True)
        return p.returncode, p.stdout + p.stderr

    def test_a_recorded_core_whose_ledger_stops_below_the_file_number_predates_it(self):
        """No record cut so far lists its migrations. One whose newest migration
        is below 0160 cannot contain a file numbered 0160 — that is the only
        thing a number may decide."""
        code, out = self.ask('v0.7.7')
        self.assertEqual(code, PREDATES, out)
        self.assertIn('releases/v0.7.7.json records core v0.7.7', out)

    def test_an_unrecorded_older_core_is_placed_by_the_nearest_newer_record(self):
        """v0.2.0 to v0.6.3 have no records; v0.7.6 was never recorded either."""
        for core, nearest in (('v0.7.6', 'v0.7.7'), ('v0.6.3', 'v0.6.4'), ('v0.2.0', 'v0.6.4')):
            with self.subTest(core=core):
                code, out = self.ask(core)
                self.assertEqual(code, PREDATES, out)
                self.assertIn(f'records core {nearest} (the nearest recorded core to {core})', out)

    def test_a_recorded_core_listing_the_file_carries_it(self):
        future_record(self.releases, 'v0.8.0', 'v0.8.0', 160,
                      migrations=['0001_init.up.sql', MIGRATION])
        for core in ('v0.8.0', 'v0.8.1'):   # v0.8.1: unrecorded, newer than one that carries it
            with self.subTest(core=core):
                code, out = self.ask(core)
                self.assertEqual(code, CARRIES, out)

    def test_a_higher_numbered_migration_without_the_file_is_not_carries(self):
        """THE review finding: 0161 shipping first (or 0160 renumbered) gives a
        release whose ledger passes 160 without the tier. By number that read
        as "carries" and the database was never asked."""
        future_record(self.releases, 'v0.8.0', 'v0.8.0', 161,
                      migrations=['0001_init.up.sql', OTHER])
        code, out = self.ask('v0.8.0')
        self.assertEqual(code, PREDATES, out)

    def test_a_same_numbered_migration_with_another_name_is_not_carries(self):
        """Pins the match to the exact FILE NAME: a release whose 0160 is some
        other migration (a renumber on the core side) must not read as carrying
        the tier. Matching by number alone would pass every other test here."""
        future_record(self.releases, 'v0.8.0', 'v0.8.0', 160,
                      migrations=['0001_init.up.sql', '0160_support_text.up.sql'])
        code, out = self.ask('v0.8.0')
        self.assertNotEqual(code, CARRIES, out)
        self.assertEqual(code, PREDATES, out)

    def test_a_record_past_the_number_that_does_not_list_its_files_decides_nothing(self):
        future_record(self.releases, 'v0.8.0', 'v0.8.0', 161)   # no core_migrations
        code, out = self.ask('v0.8.0')
        self.assertEqual(code, UNKNOWN, out)

    def test_a_core_no_record_places_is_unknown_never_carries(self):
        code, out = self.ask('v0.7.9')   # newer than every record, none carries it
        self.assertEqual(code, UNKNOWN, out)
        future_record(self.releases, 'v0.8.0', 'v0.8.0', 160,
                      migrations=['0001_init.up.sql', MIGRATION])
        code, out = self.ask('v0.7.9')   # between a record without it and one with it
        self.assertEqual(code, UNKNOWN, out)

    def test_a_prerelease_is_not_vouched_for_by_its_release(self):
        """v0.8.0-rc1 may have been cut before the migration merged."""
        future_record(self.releases, 'v0.8.0', 'v0.8.0', 160,
                      migrations=['0001_init.up.sql', MIGRATION])
        code, out = self.ask('v0.8.0-rc1')
        self.assertEqual(code, UNKNOWN, out)

    def test_records_that_disagree_decide_nothing(self):
        future_record(self.releases, 'v0.8.0', 'v0.8.0', 160,
                      migrations=['0001_init.up.sql', MIGRATION])
        future_record(self.releases, 'v0.8.2', 'v0.8.2', 161,       # non-linear history
                      migrations=['0001_init.up.sql', OTHER])
        code, out = self.ask('v0.8.1')
        self.assertEqual(code, UNKNOWN, out)
        self.assertIn('disagree', out)

    def test_no_releases_directory_is_unknown(self):
        code, out = self.ask('v0.7.7', releases=Path(self.temp.name) / 'nowhere')
        self.assertEqual(code, UNKNOWN, out)

    def test_the_migration_must_be_a_file_name_and_both_arguments_are_required(self):
        for argv in (['--core', 'v0.7.7'], ['--core', 'v0.7.7', '--migration', '160']):
            with self.subTest(argv=argv):
                p = subprocess.run(['python3', str(MAPPING), 'core-migration', *argv],
                                   capture_output=True, text=True)
                self.assertEqual(p.returncode, 2, p.stdout + p.stderr)


# The postgres this stub plays:
#   SELECT EXISTS  answers from DB_ANSWERS, one word per ask (t, f, err or
#                  timeout), the last repeating; after a remap, always f.
#   UPDATE         results from REMAP_RESULTS, one word per call (ok, fail or
#                  timeout), the last repeating; an `ok` prints REMAP_IDS once,
#                  after which the database really has no 'internal' video.
#   compose ps     prints the container id, nothing (PG_DOWN=1), or fails as a
#                  compose model that does not render (PS_FAIL=1).
DOCKER_STUB = r'''#!/bin/sh
printf 'docker %s\n' "$*" >> "$STUB_LOG"
nth() { echo $1 | awk -v n="$2" '{ print (n <= NF) ? $n : $NF }'; }
count() { n=$(( $(cat "$STUB_STATE/$1" 2>/dev/null || echo 0) + 1 )); echo "$n" > "$STUB_STATE/$1"; echo "$n"; }
case "$*" in
  "compose version --short") echo v2.30.0 ;;
  *" ps -q postgres")
    if [ "${PS_FAIL:-0}" = 1 ]; then echo 'service "postgres" refers to undefined network' >&2; exit 1; fi
    [ "${PG_DOWN:-0}" = 1 ] || echo pgcid ;;
  exec*"SELECT EXISTS"*)
    answer=$(nth "$DB_ANSWERS" "$(count asked)")
    [ ! -f "$STUB_STATE/remapped" ] || answer=f
    case "$answer" in
      err) echo 'psql: error: connection to server failed' >&2; exit 2 ;;
      timeout) echo 'ERROR:  canceling statement due to statement timeout' >&2; exit 1 ;;
    esac
    echo "$answer" ;;
  exec*"FROM watched_word_lists"*)
    # The word-lists gate (tests/rollback_word_lists_test.py owns its cases):
    # here it always finds nothing, or the database is unreachable like the rest.
    [ "${DB_ANSWERS%% *}" != err ] || { echo 'psql: error: connection to server failed' >&2; exit 2; }
    echo f ;;
  exec*"FROM oidc_providers"*)
    # The OIDC-providers gate (tests/rollback_oidc_providers_test.py owns it).
    [ "${DB_ANSWERS%% *}" != err ] || { echo 'psql: error: connection to server failed' >&2; exit 2; }
    echo f ;;
  exec*"UPDATE videos"*)
    result=$(nth "${REMAP_RESULTS:-ok}" "$(count updates)")
    case "$result" in
      fail) echo 'ERROR:  could not serialize access' >&2; exit 1 ;;
      timeout) echo 'ERROR:  canceling statement due to lock timeout' >&2; exit 1 ;;
    esac
    [ ! -f "$STUB_STATE/remapped" ] || exit 0
    touch "$STUB_STATE/remapped"
    for id in $REMAP_IDS; do echo "$id"; done ;;
esac
exit 0
'''

CURL_STUB = '#!/bin/sh\n[ "${CURL_FAIL:-0}" = 1 ] && exit 7\nexit 0\n'

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
        for name, body in (('docker', DOCKER_STUB), ('git', '#!/bin/sh\nexit 0\n'),
                           ('curl', CURL_STUB)):
            (self.bin / name).write_text(body)
            (self.bin / name).chmod(0o755)

    def write_env(self, extra=''):
        self.env_file.write_text('VIDRA_TLS_MODE=external\nPOSTGRES_USER=vidra\nPOSTGRES_DB=vidra\n'
                                 'VIDRA_CORE_TAG=v0.8.1\nVIDRA_USER_TAG=v0.8.1\n'
                                 'VIDRA_SEARCH_TAG=v0.7.3\n' + extra)

    def rollback(self, *args, answers='f', remaps='ok', pg_down=False, ps_fail=False,
                 curl_fail=False):
        result = subprocess.run(
            ['bash', str(self.tree / 'deploy/rollback.sh'), *args],
            env={**os.environ, 'PATH': f'{self.bin}:{os.environ["PATH"]}', 'HOME': str(self.home),
                 'STUB_LOG': str(self.log), 'STUB_STATE': str(self.state), 'READY_TIMEOUT': '1',
                 'VIDRA_RECORD_FETCH': '0', 'DB_ANSWERS': answers, 'REMAP_RESULTS': remaps,
                 'PG_DOWN': '1' if pg_down else '0', 'PS_FAIL': '1' if ps_fail else '0',
                 'CURL_FAIL': '1' if curl_fail else '0', 'REMAP_IDS': ' '.join(IDS)},
            capture_output=True, text=True, cwd=str(self.tree))
        return result.returncode, result.stdout + result.stderr

    def reset(self, extra=''):
        self.write_env(extra)
        self.log.unlink(missing_ok=True)
        for leftover in self.state.iterdir():
            leftover.unlink()

    def calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def ran(self, needle):
        return any(needle in line for line in self.calls())

    def first(self, needle):
        for index, line in enumerate(self.calls()):
            if needle in line:
                return index
        self.fail(f'{needle!r} never ran:\n' + '\n'.join(self.calls()))

    def ids_file(self):
        [ids] = list((self.tree / 'backups').glob('internal-privacy-remap-*.ids'))
        return ids

    def assert_untouched(self, before, out):
        """A refusal at the gate: env byte-for-byte, nothing pulled, restarted
        or written to the database."""
        self.assertEqual(self.env_file.read_bytes(), before, 'the env file was rewritten')
        for mutation in (' pull', ' up -d', 'UPDATE videos'):
            self.assertFalse(self.ran(mutation), f'{mutation!r} ran before the refusal:\n{out}')

    def assert_restored_before_restart(self, before, out):
        """A refusal at the second look: the pull ran, nothing restarted, and
        the env file holds the tags that are still being served."""
        self.assertTrue(self.ran(' pull'), out)
        self.assertFalse(self.ran(' up -d'), f'the target was started:\n{out}')
        self.assertEqual(self.env_file.read_bytes(), before, 'the env file was not restored')

    def assert_bounded(self):
        """Every query the gate makes is read-only (the check) and carries the
        statement/lock timeouts, so a wedged database refuses instead of hanging."""
        asks = [line for line in self.calls() if 'SELECT EXISTS' in line]
        self.assertTrue(asks, 'the database was never asked')
        for line in asks:
            self.assertIn('default_transaction_read_only=on', line)
        for line in asks + [line for line in self.calls() if 'UPDATE videos' in line]:
            self.assertIn('statement_timeout=15s', line)
            self.assertIn('lock_timeout=5s', line)
            self.assertIn('PGCONNECT_TIMEOUT=', line)

    # --- the five cases the gate exists for --------------------------------

    def test_a_target_that_predates_the_tier_is_refused_while_videos_use_it(self):
        before = self.env_file.read_bytes()
        code, out = self.rollback('v0.7.7', answers='t')
        self.assertNotEqual(code, 0, out)
        self.assertIn(f'does not carry migration {MIGRATION}', out)
        self.assertIn('--remap-internal-to-private', out)
        self.assertIn('Nothing was changed', out)
        self.assert_untouched(before, out)
        self.assert_bounded()

    def test_a_target_that_predates_the_tier_proceeds_when_no_video_uses_it(self):
        code, out = self.rollback('v0.7.7', answers='f')
        self.assertEqual(code, 0, out)
        self.assertIn("no video is at privacy 'internal'", out)
        self.assertLess(self.first(' pull'), self.first(' up -d'))
        # Asked at the gate, again after the pull, and once the target runs.
        self.assertEqual(sum('SELECT EXISTS' in line for line in self.calls()), 3)
        self.assertFalse(self.ran('UPDATE videos'))
        self.assert_bounded()

    def test_a_target_that_carries_the_tier_never_asks_the_database(self):
        future_record(self.tree / 'releases', 'v0.8.0', 'v0.8.0', 160,
                      migrations=['0001_init.up.sql', MIGRATION])
        code, out = self.rollback('--core', 'v0.8.0', answers='t')
        self.assertEqual(code, 0, out)
        self.assertIn(f'carries migration {MIGRATION}', out)
        self.assertFalse(self.ran('SELECT EXISTS'), out)
        self.assertTrue(self.ran(' up -d'))

    def test_a_target_past_the_number_without_the_file_is_still_checked(self):
        """End to end for the review finding: by number this target "carried"
        the tier and the database was never asked."""
        future_record(self.tree / 'releases', 'v0.8.0', 'v0.8.0', 161,
                      migrations=['0001_init.up.sql', OTHER])
        before = self.env_file.read_bytes()
        code, out = self.rollback('--core', 'v0.8.0', answers='t')
        self.assertNotEqual(code, 0, out)
        # Decided BY THE RECORD (it lists its files, and not this one), not by
        # the record failing to load and the target falling to "unknown".
        self.assertIn(f'does not carry migration {MIGRATION}', out)
        self.assertIn('does not list it in core_migrations', out)
        self.assertTrue(self.ran('SELECT EXISTS'), out)
        self.assert_untouched(before, out)

    def test_a_rollback_that_leaves_core_alone_is_not_checked(self):
        code, out = self.rollback('--user', 'v0.7.7', answers='t')
        self.assertEqual(code, 0, out)
        self.assertIn('core is not being rolled back', out)
        self.assertFalse(self.ran('SELECT EXISTS'), out)

    def test_a_check_that_cannot_run_refuses_unless_overridden(self):
        for label, kwargs, extra, says in (
                ('psql error', {'answers': 'err'}, '', 'connection to server failed'),
                ('statement timeout', {'answers': 'timeout'}, '', 'TIMED OUT'),
                ('postgres not running', {'pg_down': True}, '', 'is not running'),
                ('compose cannot list it', {'ps_fail': True}, '', 'could not list'),
                ('external postgres', {}, 'VIDRA_EXTERNAL_POSTGRES=true\n'
                                          'DATABASE_URL=postgres://u:p@db.example:5432/vidra\n',
                 'VIDRA_EXTERNAL_POSTGRES=true')):
            with self.subTest(case=label):
                self.reset(extra)
                before = self.env_file.read_bytes()
                code, out = self.rollback('v0.7.7', **kwargs)
                self.assertNotEqual(code, 0, out)
                self.assertIn('could not be made', out)
                self.assertIn(says, out)
                self.assertIn('--allow-unchecked-privacy-tier', out)
                self.assert_untouched(before, out)
                if label == 'compose cannot list it':
                    self.assertNotIn('is not running', out)

                self.reset(extra)
                code, out = self.rollback('v0.7.7', '--allow-unchecked-privacy-tier', '--allow-unchecked-word-lists', '--allow-oidc-env-fallback', **kwargs)
                self.assertEqual(code, 0, out)
                self.assertIn('WARNING: privacy-tier check NOT settled', out)
                self.assertTrue(self.ran(' up -d'))

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
        ids = self.ids_file()
        self.assertEqual(ids.read_text().split(), list(IDS))
        self.assertEqual(stat.S_IMODE(ids.stat().st_mode), 0o600)
        self.assertIn('VIDRA_CORE_TAG=v0.7.7', self.env_file.read_text())
        self.assert_bounded()

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

    def test_the_remap_flag_when_the_database_cannot_be_asked(self):
        before = self.env_file.read_bytes()
        code, out = self.rollback('v0.7.7', '--remap-internal-to-private', pg_down=True)
        self.assertNotEqual(code, 0, out)
        self.assertIn('--remap-internal-to-private cannot help here', out)
        self.assert_untouched(before, out)

        self.reset()
        code, out = self.rollback('v0.7.7', '--remap-internal-to-private',
                                  '--allow-unchecked-privacy-tier', '--allow-unchecked-word-lists', '--allow-oidc-env-fallback', pg_down=True)
        self.assertEqual(code, 0, out)
        self.assertIn('NOTHING was remapped', out)
        self.assertFalse(self.ran('UPDATE videos'), out)

    # --- the second look, after the pull ------------------------------------

    def test_a_video_put_at_internal_during_the_pull_stops_the_restart(self):
        before = self.env_file.read_bytes()
        code, out = self.rollback('v0.7.7', answers='f t')
        self.assertNotEqual(code, 0, out)
        self.assertIn('while this rollback was pulling', out)
        self.assert_restored_before_restart(before, out)

    def test_a_re_check_that_errors_after_the_pull_stops_the_restart(self):
        before = self.env_file.read_bytes()
        code, out = self.rollback('v0.7.7', answers='f err')
        self.assertNotEqual(code, 0, out)
        self.assertIn('could not be repeated', out)
        self.assert_restored_before_restart(before, out)

    def test_a_remap_that_fails_after_the_pull_stops_the_restart(self):
        for result, says in (('fail', 'could not serialize access'), ('timeout', 'TIMED OUT')):
            with self.subTest(result=result):
                self.reset()
                before = self.env_file.read_bytes()
                code, out = self.rollback('v0.7.7', '--remap-internal-to-private',
                                          answers='t', remaps=result)
                self.assertNotEqual(code, 0, out)
                self.assertIn('--remap-internal-to-private failed', out)
                self.assertIn(says, out)
                self.assert_restored_before_restart(before, out)

    # --- the last look, once the target runs --------------------------------

    def test_a_post_restart_remap_that_fails_names_the_ids_already_remapped(self):
        code, out = self.rollback('v0.7.7', '--remap-internal-to-private',
                                  answers='t', remaps='ok fail')
        self.assertNotEqual(code, 0, out)
        self.assertTrue(self.ran(' up -d'), out)
        [error] = [line for line in out.splitlines() if 'post-restart remap failed' in line]
        self.assertIn('the rollback target is RUNNING', error)
        self.assertIn('could not serialize access', error)
        self.assertIn(str(self.ids_file()), error)

    def test_a_video_put_at_internal_during_the_restart_is_reported_with_the_fix(self):
        code, out = self.rollback('v0.7.7', answers='f f t')
        self.assertNotEqual(code, 0, out)
        self.assertTrue(self.ran(' up -d'), out)
        self.assertIn('./deploy/rollback.sh --core v0.7.7 --remap-internal-to-private', out)

    def test_a_post_restart_check_that_cannot_run_warns_and_finishes(self):
        code, out = self.rollback('v0.7.7', answers='f f err')
        self.assertEqual(code, 0, out)
        self.assertIn('WARNING: the rollback target is running, and the privacy-tier check '
                      'could not be repeated', out)
        self.assertIn('rolled back to core=v0.7.7', out)

    def test_the_unhealthy_trailer_names_the_ids_file_after_a_remap(self):
        code, out = self.rollback('v0.7.7', '--remap-internal-to-private', answers='t',
                                  curl_fail=True)
        self.assertNotEqual(code, 0, out)
        trailer = out[out.index('THE ROLLBACK TARGET IS ALSO UNHEALTHY'):]
        self.assertIn('This run remapped 2 video(s)', trailer)
        self.assertIn(str(self.ids_file()), trailer)


if __name__ == '__main__':
    unittest.main()
