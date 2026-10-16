"""provision.sh must leave backups/ owned by the service user, and repair a root-owned one.

THE TRAP. backup.sh does `umask 077; mkdir -p "$BACKUP_DIR"`. An operator's first manual
backup.sh (or deploy.sh, whose pre-deploy dump calls it) usually runs as root, so backups/ is
born a root-owned 0700 directory and vidra-backup.timer (User=vidra) can never write into it
again. provision.sh's blanket chown is skipped once /opt/vidra itself is vidra's, so the repair
has to be its own step.

provision.sh needs root, apt and systemd and cannot run here, so the function is lifted VERBATIM
out of the real script (the technique tests/rec03_script_test.py and tests/caddy_reload_test.py
use) and run against a temp tree with `chown` replaced by a recorder: ownership is observed
through the argv chown receives, not by needing a second real user. Nothing here skips.
"""
from pathlib import Path
import os
import re
import stat
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'deploy' / 'provision.sh'
TEXT = SCRIPT.read_text()
FUNC = re.search(r'^ensure_backups_dir\(\) \{\n.*?^\}\n', TEXT, re.S | re.M)

CHOWN_STUB = '#!/bin/sh\nprintf "%s\\n" "$*" >> "$CHOWN_LOG"\nexit "${CHOWN_EXIT:-0}"\n'


class EnsureBackupsDirTest(unittest.TestCase):
    def run_fn(self, vidra_dir, user, chown_exit=0):
        stub_dir = Path(tempfile.mkdtemp(dir=vidra_dir.parent))
        stub = stub_dir / 'chown'
        stub.write_text(CHOWN_STUB)
        stub.chmod(0o755)
        log = stub_dir / 'chown.log'
        script = ('set -euo pipefail\n'
                  'log() { printf "[provision] %s\\n" "$*"; }\n'
                  'die() { printf "[provision] ERROR: %s\\n" "$*" >&2; exit 1; }\n'
                  + FUNC.group(0) + 'ensure_backups_dir\n')
        env = dict(os.environ, PATH=f'{stub_dir}:{os.environ["PATH"]}', CHOWN_LOG=str(log),
                   CHOWN_EXIT=str(chown_exit), VIDRA_DIR=str(vidra_dir), VIDRA_USER=user)
        r = subprocess.run(['bash', '-c', script], env=env, capture_output=True, text=True)
        calls = log.read_text().splitlines() if log.exists() else []
        return r, calls

    def setUp(self):
        self.assertIsNotNone(FUNC, 'provision.sh no longer defines ensure_backups_dir')
        self.tmp = Path(tempfile.mkdtemp())
        self.vdir = self.tmp / 'vidra'
        self.vdir.mkdir()
        self.me = subprocess.run(['id', '-un'], capture_output=True, text=True).stdout.strip()

    def test_creates_backups_0700_when_absent(self):
        r, calls = self.run_fn(self.vdir, self.me)
        self.assertEqual(r.returncode, 0, r.stderr)
        mode = stat.S_IMODE((self.vdir / 'backups').stat().st_mode)
        self.assertEqual(mode, 0o700)
        self.assertEqual(calls, [], 'a dir already owned by the user needs no chown')

    def test_foreign_owner_is_repaired_recursively(self):
        # "vidra-other" stands in for root: the directory is owned by someone who is
        # not the service user, which is all the repair keys on.
        (self.vdir / 'backups').mkdir()
        (self.vdir / 'backups' / 'vidra-1.dump.gz').write_text('x')
        r, calls = self.run_fn(self.vdir, 'vidra-other')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(calls, [f'-R vidra-other:vidra-other {self.vdir}/backups'])

    def test_loose_mode_is_tightened(self):
        (self.vdir / 'backups').mkdir(mode=0o755)
        (self.vdir / 'backups').chmod(0o755)
        r, _ = self.run_fn(self.vdir, self.me)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(stat.S_IMODE((self.vdir / 'backups').stat().st_mode), 0o700)

    def test_idempotent_when_already_correct(self):
        self.run_fn(self.vdir, self.me)
        r, calls = self.run_fn(self.vdir, self.me)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(calls, [])

    def test_failed_chown_is_fatal(self):
        r, _ = self.run_fn(self.vdir, 'vidra-other', chown_exit=1)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('Permission denied', r.stderr)

    def test_provision_calls_it_after_the_directory_chown(self):
        # A lifted function proves nothing if the script never calls it, or calls it
        # before the blanket chown could undo the repair's ordering assumptions.
        call = TEXT.index('\nensure_backups_dir\n')
        self.assertGreater(call, TEXT.index('chowned ${VIDRA_DIR} to ${VIDRA_USER}'))


if __name__ == '__main__':
    unittest.main()
