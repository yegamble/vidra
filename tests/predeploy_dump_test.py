"""Exercise the dump step from deploy.sh with a permissive caller umask."""

import gzip
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest


SCRIPT = (Path(__file__).resolve().parents[1] / 'deploy' / 'deploy.sh').read_text()
STEP = SCRIPT.split('step "1/6 pre-deploy database dump"\n', 1)[1].split(
    'step "2/6 pull images"\n', 1
)[0]

HARNESS = r'''
set -euo pipefail
umask 000
log() { :; }
die() { echo "$*" >&2; exit 1; }
compose() { [[ "$*" == "ps -q postgres" ]] && echo fixture-postgres; }
COMPOSE=(compose)
EXTERNAL_POSTGRES=0 PGUSER=vidra PGDB=vidra PREDEPLOY_KEEP=10
docker() {
    case "$4" in
        pg_dump) echo fixture; [[ "$FAIL" != pg_dump ]] ;;
        pg_restore)
            "$TEST_PYTHON" -c '
from pathlib import Path
import os, stat, sys
files = [p for p in Path(os.environ["BACKUP_DIR"]).rglob("*") if p.is_file()]
assert len(files) == 2, files
assert all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in files)
assert sys.stdin.buffer.read() == b"fixture\n"
' || return 1
            [[ "$FAIL" != pg_restore ]] ;;
        *) return 1 ;;
    esac
}
'''


class PredeployDumpTest(unittest.TestCase):
    def run_step(self, work, fail=''):
        env = dict(os.environ, BACKUP_DIR=work, FAIL=fail, TEST_PYTHON=sys.executable)
        return subprocess.run(['bash', '-c', HARNESS + STEP + '\ntouch reached_pull\n'],
                              cwd=work.parent, env=env, capture_output=True, text=True)

    def test_private_during_verification_and_after_publish(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp) / 'backups'
            result = self.run_step(work)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(stat.S_IMODE(work.stat().st_mode), 0o700)
            archive, = work.iterdir()
            self.assertRegex(archive.name, r'^pre-deploy-.*\.dump\.gz$')
            self.assertEqual(stat.S_IMODE(archive.stat().st_mode), 0o600)
            self.assertEqual(gzip.decompress(archive.read_bytes()), b'fixture\n')
            self.assertTrue((work.parent / 'reached_pull').exists())

    def test_failed_dump_or_verification_stops_deploy_and_cleans_partial_files(self):
        for fail in ('pg_dump', 'pg_restore'):
            with self.subTest(fail=fail), tempfile.TemporaryDirectory() as tmp:
                work = Path(tmp) / 'backups'
                result = self.run_step(work, fail)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(list(work.iterdir()), [])
                self.assertFalse((work.parent / 'reached_pull').exists())
