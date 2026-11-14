"""deploy/peertube-source-sync.sh: nothing the importer reads changes until every gate passed."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

DSN = 'postgres://pt_import_reader:s3cret@postgres:5432/peertube_source_snapshot?sslmode=disable'

# A stand-in for `docker`: records every invocation and answers the script's
# catalog questions from STATE (a JSON file the test seeds and can read back).
FAKE_DOCKER = r'''#!/usr/bin/env python3
import json, os, pathlib, re, sys
args = sys.argv[1:]
state_path = pathlib.Path(os.environ['FAKE_STATE'])
state = json.loads(state_path.read_text())
def save():
    state_path.write_text(json.dumps(state))
def record(kind, detail):
    state['calls'].append([kind, detail]); save()
if args[0] == 'compose' and args[-3:] == ['ps', '-q', 'postgres']:
    print('test-postgres'); sys.exit(0)
if 'pg_restore' in args:
    data = sys.stdin.buffer.read()
    if '-l' in args:
        record('toc', len(data))
        sys.exit(0 if data.startswith(b'PGDMP') else 1)
    db = args[args.index('-d') + 1]
    record('restore', db)
    if state.get('restore_fails'):
        sys.exit(1)
    state['videos'][db] = state['incoming_videos']; save()
    sys.exit(0)
if 'psql' in args:
    db = args[args.index('-d') + 1]
    sql = args[args.index('-c') + 1]
    if 'peertube_import_runs' in sql:
        record('active-check', db)
        n = state['active_runs'].pop(0) if state['active_runs'] else 0
        save(); print(n); sys.exit(0)
    m = re.search(r"FROM pg_database WHERE datname = '(\w+)'", sql)
    if m:
        print('1' if m.group(1) in state['videos'] else ''); sys.exit(0)
    if sql.startswith('CREATE DATABASE'):
        record('create', sql.split()[-1]); state['videos'][sql.split()[-1]] = 0; save(); sys.exit(0)
    if sql.startswith('DROP DATABASE'):
        record('drop', sql.split()[-1]); state['videos'].pop(sql.split()[-1], None); save(); sys.exit(0)
    if 'GRANT SELECT ON ALL TABLES' in sql:
        record('grants', sql); sys.exit(0)
    if 'has_table_privilege' in sql:
        print('t' if "'SELECT'" in sql else state.get('reader_can_write', 'f')); sys.exit(0)
    if 'FROM video WHERE remote = false' in sql:
        print(state['videos'][db]); sys.exit(0)
    if 'migrationVersion' in sql:
        print(800); sys.exit(0)
    if 'RENAME TO' in sql:
        record('swap', sql)
        if state.get('swap_fails'):
            sys.exit(1)
        for src, dst in re.findall(r'ALTER DATABASE (\w+) RENAME TO (\w+)', sql):
            state['videos'][dst] = state['videos'].pop(src)
        save(); sys.exit(0)
    if 'pg_db_role_setting' in sql:
        print(1); sys.exit(0)
    if "LIKE '" in sql:
        prefix = re.search(r"LIKE '(\w+)%'", sql).group(1)
        for name in sorted((d for d in state['videos'] if d.startswith(prefix)), reverse=True):
            print(name)
        sys.exit(0)
raise SystemExit('unexpected docker invocation: %r' % (args,))
'''


class PeertubeSourceSyncTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for directory in ('deploy', 'env', 'bin'):
            (self.root / directory).mkdir()
        for name in ('peertube-source-sync.sh', 'lib.sh'):
            shutil.copy2(ROOT / 'deploy' / name, self.root / 'deploy' / name)
        self.env_file = self.root / 'env/production.env'
        self.env_file.write_text(
            'POSTGRES_DB=vidra\nPOSTGRES_USER=vidra\nPEERTUBE_SOURCE_DATABASE_URL=%s\n' % DSN)
        (self.root / 'deploy/Caddyfile.local').write_text('localhost {}\n')
        docker = self.root / 'bin/docker'
        docker.write_text(FAKE_DOCKER)
        docker.chmod(0o755)
        self.state_path = self.root / 'state.json'
        self.seed(videos={'vidra': 0, 'peertube_source_snapshot': 100}, incoming_videos=106)
        self.dump = self.root / 'source.dump'
        self.dump.write_bytes(b'PGDMP synthetic archive')
        self.spool = self.root / 'spool'
        self.env = {**os.environ, 'PATH': str(self.root / 'bin') + ':' + os.environ['PATH'],
                    'FAKE_STATE': str(self.state_path), 'ENV_FILE': 'env/production.env',
                    'PEERTUBE_SYNC_SPOOL_DIR': str(self.spool),
                    'PEERTUBE_SYNC_HEALTHCHECKS_URL': '', 'PEERTUBE_SYNC_SSH': '',
                    'VIDRA_EXTERNAL_POSTGRES': 'false', 'VIDRA_EXTERNAL_REDIS': 'false'}
        self.env.pop('PEERTUBE_SOURCE_DATABASE_URL', None)

    def seed(self, **state):
        self.state_path.write_text(json.dumps({'calls': [], 'active_runs': [], **state}))

    def state(self):
        return json.loads(self.state_path.read_text())

    def kinds(self):
        return [kind for kind, _ in self.state()['calls']]

    def sync(self, *args, stdin=None, **env):
        return subprocess.run(['bash', 'deploy/peertube-source-sync.sh', *args], cwd=self.root,
                              env={**self.env, **env}, capture_output=True, text=stdin is None,
                              input=stdin)

    def test_refresh_restores_beside_the_live_snapshot_then_swaps(self):
        result = self.sync('--dump-file', str(self.dump))
        self.assertEqual(result.returncode, 0, result.stderr)
        kinds = self.kinds()
        # Every gate before the swap, and the second active-run check directly before it.
        self.assertEqual(kinds, ['active-check', 'toc', 'create', 'restore', 'grants',
                                 'active-check', 'swap'])
        calls = dict((kind, detail) for kind, detail in self.state()['calls'])
        self.assertEqual(calls['restore'], 'peertube_source_snapshot_incoming')
        self.assertIn('TO pt_import_reader', calls['grants'])
        self.assertIn('default_transaction_read_only = on', calls['grants'])
        self.assertTrue(calls['swap'].lstrip().startswith('BEGIN;'))
        videos = self.state()['videos']
        self.assertEqual(videos['peertube_source_snapshot'], 106)
        retired = [d for d in videos if d.startswith('peertube_source_snapshot_prev_')]
        self.assertEqual(len(retired), 1)
        self.assertEqual(videos[retired[0]], 100)
        self.assertNotIn('peertube_source_snapshot_incoming', videos)
        # The spooled plaintext copy of the source does not outlive a good restore.
        self.assertEqual(list(self.spool.iterdir()), [])

    def test_dump_on_stdin_reaches_the_restore_whole(self):
        payload = b'PGDMP' + os.urandom(4096)
        result = self.sync('--dump-file', '-', stdin=payload)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(dict(map(tuple, self.state()['calls']))['toc'], len(payload))

    def test_active_import_run_blocks_before_anything_is_read(self):
        self.seed(videos={'vidra': 0, 'peertube_source_snapshot': 100}, incoming_videos=106,
                  active_runs=[1])
        result = self.sync('--dump-file', str(self.dump))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('pending or running', result.stderr)
        self.assertEqual(self.kinds(), ['active-check'])

    def test_run_started_during_the_restore_blocks_the_swap(self):
        self.seed(videos={'vidra': 0, 'peertube_source_snapshot': 100}, incoming_videos=106,
                  active_runs=[0, 1])
        result = self.sync('--dump-file', str(self.dump))
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('swap', self.kinds())
        self.assertEqual(self.state()['videos']['peertube_source_snapshot'], 100)

    def test_truncated_archive_never_creates_a_database(self):
        self.dump.write_bytes(b'not an archive')
        result = self.sync('--dump-file', str(self.dump))
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('create', self.kinds())
        self.assertEqual(list(self.spool.iterdir()), [])

    def test_failed_restore_leaves_the_live_snapshot_alone(self):
        self.seed(videos={'vidra': 0, 'peertube_source_snapshot': 100}, incoming_videos=106,
                  restore_fails=True)
        result = self.sync('--dump-file', str(self.dump))
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('swap', self.kinds())
        self.assertEqual(self.state()['videos']['peertube_source_snapshot'], 100)
        # A run that dies after the archive was verified still leaves no
        # plaintext copy of the source's accounts, and no lock, behind.
        self.assertEqual(list(self.spool.iterdir()), [])

    def test_kept_dump_survives_only_a_published_refresh(self):
        result = self.sync('--dump-file', str(self.dump), PEERTUBE_SYNC_KEEP_DUMP='true')
        self.assertEqual(result.returncode, 0, result.stderr)
        kept = list(self.spool.iterdir())
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0].read_bytes(), self.dump.read_bytes())
        self.assertEqual(kept[0].stat().st_mode & 0o077, 0)

    def test_second_run_refuses_while_the_first_holds_the_lock(self):
        lock = self.spool / '.lock'
        lock.mkdir(parents=True)
        (lock / 'pid').write_text('%d\n' % os.getpid())      # a live process: this test
        result = self.sync('--dump-file', str(self.dump))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('another peertube-source-sync is running', result.stderr)
        self.assertEqual(self.kinds(), [])
        # The loser must not remove the winner's lock on its way out.
        self.assertTrue((lock / 'pid').exists())

    def test_lock_orphaned_by_a_dead_run_is_taken_over(self):
        dead = subprocess.Popen(['true'])
        dead.wait()
        lock = self.spool / '.lock'
        lock.mkdir(parents=True)
        (lock / 'pid').write_text('%d\n' % dead.pid)
        result = self.sync('--dump-file', str(self.dump))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('stale lock', result.stderr + result.stdout)
        self.assertEqual(list(self.spool.iterdir()), [])

    def test_swap_is_one_transaction_in_the_safe_order(self):
        result = self.sync('--dump-file', str(self.dump))
        self.assertEqual(result.returncode, 0, result.stderr)
        swap = dict(map(tuple, self.state()['calls']))['swap']
        order = [swap.index(part) for part in (
            'BEGIN;', 'ALLOW_CONNECTIONS false', 'pg_terminate_backend',
            'ALTER DATABASE peertube_source_snapshot RENAME TO peertube_source_snapshot_prev_',
            'ALTER DATABASE peertube_source_snapshot_incoming RENAME TO peertube_source_snapshot;',
            'COMMIT;')]
        self.assertEqual(order, sorted(order))

    def test_smaller_snapshot_is_refused_unless_allowed(self):
        self.seed(videos={'vidra': 0, 'peertube_source_snapshot': 100}, incoming_videos=3)
        result = self.sync('--dump-file', str(self.dump))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('FEWER local videos', result.stderr)
        self.assertNotIn('swap', self.kinds())

        self.seed(videos={'vidra': 0, 'peertube_source_snapshot': 100}, incoming_videos=3)
        result = self.sync('--dump-file', str(self.dump), '--allow-shrink')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.state()['videos']['peertube_source_snapshot'], 3)

    def test_writable_reader_role_is_never_published(self):
        self.seed(videos={'vidra': 0, 'peertube_source_snapshot': 100}, incoming_videos=106,
                  reader_can_write='t')
        result = self.sync('--dump-file', str(self.dump))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('can write', result.stderr)
        self.assertNotIn('swap', self.kinds())

    def test_first_refresh_with_no_current_snapshot(self):
        self.seed(videos={'vidra': 0}, incoming_videos=106)
        result = self.sync('--dump-file', str(self.dump))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.state()['videos'], {'vidra': 0, 'peertube_source_snapshot': 106})

    def test_leftover_incoming_database_is_rebuilt(self):
        self.seed(videos={'vidra': 0, 'peertube_source_snapshot': 100,
                          'peertube_source_snapshot_incoming': 7}, incoming_videos=106)
        result = self.sync('--dump-file', str(self.dump))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.kinds()[2:4], ['drop', 'create'])

    def test_retention_drops_only_names_this_script_made(self):
        videos = {'vidra': 0, 'peertube_source_snapshot': 100,
                  'peertube_source_snapshot_20261104': 90,          # hand-made: never touched
                  'peertube_source_snapshot_prev_20010101000000': 80,
                  'peertube_source_snapshot_prev_20010102000000': 81,
                  'peertube_source_snapshot_prev_notastamp': 82}
        self.seed(videos=videos, incoming_videos=106)
        result = self.sync('--dump-file', str(self.dump), PEERTUBE_SYNC_KEEP_PREVIOUS='2')
        self.assertEqual(result.returncode, 0, result.stderr)
        dropped = [detail for kind, detail in self.state()['calls'] if kind == 'drop']
        self.assertEqual(dropped, ['peertube_source_snapshot_prev_20010101000000'])
        left = self.state()['videos']
        self.assertIn('peertube_source_snapshot_20261104', left)
        self.assertIn('peertube_source_snapshot_prev_notastamp', left)

    def test_refuses_configurations_it_would_refresh_wrongly(self):
        cases = {
            'external host': ('postgres://pt_import_reader:x@db.internal:5432/peertube_source_snapshot',
                              "not the bundled 'postgres' service"),
            'application database': ('postgres://pt_import_reader:x@postgres:5432/vidra',
                                     'refusing to replace it'),
            'admin role': ('postgres://vidra:x@postgres:5432/peertube_source_snapshot',
                           'dedicated read-only role'),
            'quoted identifier': ('postgres://pt_import_reader:x@postgres:5432/Snap-Shot',
                                  'not a plain lowercase identifier'),
            # No /db path: the host is "postgres", which is also the maintenance database.
            'no database': ('postgres://pt_import_reader:x@postgres:5432', 'names no database'),
            'system database': ('postgres://pt_import_reader:x@postgres:5432/postgres',
                                'system database'),
            'name too long': ('postgres://pt_import_reader:x@postgres:5432/' + 's' * 44,
                              'too long'),
            'unset': ('', 'nothing to refresh'),
        }
        for name, (dsn, message) in cases.items():
            with self.subTest(name):
                self.seed(videos={'vidra': 0, 'peertube_source_snapshot': 100}, incoming_videos=106)
                self.env_file.write_text(
                    'POSTGRES_DB=vidra\nPOSTGRES_USER=vidra\nPEERTUBE_SOURCE_DATABASE_URL=%s\n' % dsn)
                result = self.sync('--dump-file', str(self.dump))
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stderr)
                self.assertEqual(self.kinds(), [])

    def test_external_postgres_is_refused(self):
        result = self.sync('--dump-file', str(self.dump), VIDRA_EXTERNAL_POSTGRES='true')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('VIDRA_EXTERNAL_POSTGRES=true', result.stderr)
        self.assertEqual(self.kinds(), [])

    def test_no_dump_source_is_a_usage_error(self):
        result = self.sync()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('no dump to restore', result.stderr)
        self.assertEqual(self.kinds(), [])

    def test_failed_swap_reports_the_rollback(self):
        self.seed(videos={'vidra': 0, 'peertube_source_snapshot': 100}, incoming_videos=106,
                  swap_fails=True)
        result = self.sync('--dump-file', str(self.dump))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('rolled back', result.stderr)
        self.assertEqual(self.state()['videos']['peertube_source_snapshot'], 100)


if __name__ == '__main__':
    unittest.main()
