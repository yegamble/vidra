"""Backup artifact confidentiality and failed-dump publication regressions."""
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class BackupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for directory in ('deploy', 'env', 'bin'):
            (self.root / directory).mkdir()
        for name in ('backup.sh', 'lib.sh'):
            shutil.copy2(ROOT / 'deploy' / name, self.root / 'deploy' / name)
        (self.root / 'env/production.env').write_text('POSTGRES_DB=vidra\nPOSTGRES_USER=vidra\n')
        (self.root / 'deploy/Caddyfile.local').write_text('localhost {}\n')
        docker = self.root / 'bin/docker'
        docker.write_text('''#!/usr/bin/env python3
import json,os,pathlib,sys
args=sys.argv[1:]
if args[0]=='compose' and args[-3:]==['ps','-q','postgres']:
 print('test-postgres')
elif 'pg_dump' in args:
 sys.stdout.buffer.write(b'synthetic archive')
 sys.exit(int(os.environ.get('DUMP_EXIT','0')))
elif 'pg_restore' in args:
 sys.stdin.buffer.read()
 root=pathlib.Path(os.environ['BACKUP_DIR'])
 pathlib.Path(os.environ['PROBE']).write_text(json.dumps({p.name:p.stat().st_mode & 0o777 for p in root.iterdir()}))
else:
 raise SystemExit('unexpected docker invocation')
''')
        docker.chmod(0o755)
        self.backups = self.root / 'backups'
        self.env = {**os.environ, 'PATH': str(self.root / 'bin') + ':' + os.environ['PATH'],
                    'BACKUP_DIR': str(self.backups), 'PROBE': str(self.root / 'probe.json'),
                    'ENV_FILE': 'env/production.env', 'HEALTHCHECKS_URL': '',
                    'BACKUP_RCLONE_REMOTE': '', 'BACKUP_S3_URI': '',
                    'VIDRA_EXTERNAL_POSTGRES': 'false', 'VIDRA_EXTERNAL_REDIS': 'false'}

    def run_backup(self, **env):
        return subprocess.run(['bash', '-c', 'umask 022; exec bash deploy/backup.sh'],
                              cwd=self.root, env={**self.env, **env}, capture_output=True, text=True)

    def test_archives_and_plaintext_verification_are_private_from_creation(self):
        run = self.run_backup()
        self.assertEqual(run.returncode, 0, run.stderr)
        probe = json.loads((self.root / 'probe.json').read_text())
        self.assertTrue(any(name.endswith('.verify') for name in probe))
        for name, mode in probe.items():
            self.assertEqual(mode & 0o077, 0, name)
        for path in self.backups.iterdir():
            self.assertEqual(stat.S_IMODE(path.stat().st_mode) & 0o077, 0, path.name)
        self.assertEqual(stat.S_IMODE(self.backups.stat().st_mode), 0o700)

    def test_failed_dump_never_publishes_or_advances_success(self):
        self.backups.mkdir()
        marker = self.backups / 'last_success'
        marker.write_text('previous successful backup\n')
        run = self.run_backup(DUMP_EXIT='9')
        self.assertNotEqual(run.returncode, 0)
        self.assertEqual(marker.read_text(), 'previous successful backup\n')
        self.assertEqual(list(self.backups.glob('*.dump.gz')), [])
        self.assertEqual(list(self.backups.glob('*.tar.gz')), [])
        partials = list(self.backups.glob('*.part'))
        self.assertEqual(len(partials), 1)
        self.assertEqual(stat.S_IMODE(partials[0].stat().st_mode) & 0o077, 0)


if __name__ == '__main__':
    unittest.main()
