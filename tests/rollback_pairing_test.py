"""`rollback.sh <tag>` pins the pairing releases/<tag>.json records.

v0.7.4 and v0.7.5 re-released vidra-core ALONE and pair vidra-user and
vidra-search at v0.7.3. The bare form wrote one tag into all three keys, so
`rollback.sh v0.7.5` — the command an operator types to leave v0.7.6 — pinned
ghcr.io/yegamble/vidra-user:v0.7.5, which has never existed, and the rollback
died at `compose pull` with the broken release still serving (council ruling
D10, P0-4). The pairing is read by the resolver pin-release.sh uses, so there
is still exactly one reader of release records.

End to end through the real rollback.sh, lib.sh and release-mapping.py, with
docker/git/curl stubbed exactly as tests/release_mapping_test.py stubs them.
"""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

DOCKER_STUB = '''#!/bin/sh
printf 'docker %s\\n' "$*" >> "$STUB_LOG"
case "$*" in
  "compose version --short") echo v2.30.0 ;;
esac
exit 0
'''


class RollbackPairingTests(unittest.TestCase):
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
        # An unpacked bundle: no git to sync, and rollback mode skips the
        # manifest comparison, so the stubs see every step to `up -d`.
        (self.tree / 'vidra-bundle.manifest').write_text(
            'tag=v0.7.6\ncore_schema_version=0151\n')
        self.env_file = self.tree / 'env/production.env'
        self.env_file.write_text('VIDRA_TLS_MODE=external\nPOSTGRES_USER=vidra\n'
                                 'VIDRA_CORE_TAG=v0.7.6\nVIDRA_USER_TAG=v0.7.6\n'
                                 'VIDRA_SEARCH_TAG=v0.7.3\n')
        self.home = base / 'home'
        self.home.mkdir()
        self.bin = base / 'bin'
        self.bin.mkdir()
        self.log = base / 'stub.log'
        for name, body in (('docker', DOCKER_STUB),
                           ('git', '#!/bin/sh\nexit 0\n'),
                           ('curl', '#!/bin/sh\nexit 0\n')):
            (self.bin / name).write_text(body)
            (self.bin / name).chmod(0o755)

    def rollback(self, *args):
        result = subprocess.run(
            ['bash', str(self.tree / 'deploy/rollback.sh'), *args],
            env={**os.environ, 'PATH': f'{self.bin}:{os.environ["PATH"]}', 'HOME': str(self.home),
                 'STUB_LOG': str(self.log), 'READY_TIMEOUT': '1',
                 # Offline: the tree's record must be enough on its own.
                 'VIDRA_RECORD_FETCH': '0'},
            capture_output=True, text=True, cwd=str(self.tree))
        return result.returncode, result.stdout + result.stderr

    def pins(self):
        keys = ('VIDRA_CORE_TAG', 'VIDRA_USER_TAG', 'VIDRA_SEARCH_TAG')
        values = dict(line.split('=', 1) for line in self.env_file.read_text().splitlines()
                      if line.startswith(keys))
        return tuple(values[k] for k in keys)

    def test_a_bare_core_only_tag_pins_the_recorded_pairing(self):
        code, out = self.rollback('v0.7.5')
        self.assertEqual(code, 0, out)
        self.assertEqual(self.pins(), ('v0.7.5', 'v0.7.3', 'v0.7.3'))
        self.assertIn('releases/v0.7.5.json pairs core=v0.7.5 user=v0.7.3 search=v0.7.3', out)
        self.assertNotIn('NOT verified', out)
        self.assertIn(' pull', self.log.read_text())

    def test_an_explicit_flag_overrides_the_record_in_either_position(self):
        for args in (('v0.7.5', '--user', 'v0.7.2'), ('--user', 'v0.7.2', 'v0.7.5')):
            with self.subTest(args=args):
                code, out = self.rollback(*args)
                self.assertEqual(code, 0, out)
                self.assertEqual(self.pins(), ('v0.7.5', 'v0.7.2', 'v0.7.3'))
                self.assertIn('--user v0.7.2 overrides', out)

    def test_negative_control_a_bare_tag_with_no_record_stays_uniform_and_warns(self):
        self.assertFalse((self.tree / 'releases/v0.7.9.json').exists())
        code, out = self.rollback('v0.7.9')
        self.assertEqual(code, 0, out)
        self.assertEqual(self.pins(), ('v0.7.9', 'v0.7.9', 'v0.7.9'))
        self.assertIn('NOT verified', out)
        self.assertNotIn('pairs core=', out)


if __name__ == '__main__':
    unittest.main()
