"""pin-release.sh against a real local origin: the two hand steps it replaces."""
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import unittest

DEPLOY = Path(__file__).resolve().parents[1] / 'deploy'
SCRIPTS = ('pin-release.sh', 'lib.sh', 'backup-env.sh', 'checkout-hygiene.py')


def git(*args, cwd):
    return subprocess.run(['git', *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


class PinReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        # An origin with the deploy scripts committed and one release tag, and a
        # clone standing in for /opt/vidra. The scripts are committed so that
        # checking out the tag reproduces them — the real trap this script is
        # built around is that it changes the tree it is running from.
        seed = base / 'seed'
        (seed / 'deploy').mkdir(parents=True)
        (seed / 'env').mkdir()
        for name in SCRIPTS:
            shutil.copyfile(DEPLOY / name, seed / 'deploy' / name)
        (seed / 'env/production.env.example').write_text('VIDRA_CORE_TAG=\n')
        env = {**os.environ, 'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@example.com',
               'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@example.com'}
        subprocess.run(['git', 'init', '-q', '-b', 'main', str(seed)], check=True)
        subprocess.run(['git', 'add', '-A'], cwd=seed, check=True)
        subprocess.run(['git', 'commit', '-q', '-m', 'seed'], cwd=seed, check=True, env=env)
        subprocess.run(['git', 'tag', '-a', 'v9.9.9', '-m', 'v9.9.9'], cwd=seed, check=True, env=env)
        self.origin = base / 'origin.git'
        subprocess.run(['git', 'clone', '-q', '--bare', str(seed), str(self.origin)], check=True)
        self.root = base / 'checkout'
        subprocess.run(['git', 'clone', '-q', str(self.origin), str(self.root)], check=True)
        self.env_file = self.root / 'env/production.env'
        self.env_file.write_text('VIDRA_CORE_TAG=v0.0.1\nVIDRA_USER_TAG=v0.0.1\nJWT_SECRET=fake-not-a-secret\n')
        self.home = base / 'home'
        self.home.mkdir()
        self.bin = base / 'bin'
        self.bin.mkdir()

    def run_pin(self, *args):
        return subprocess.run(
            ['bash', str(self.root / 'deploy/pin-release.sh'), *args],
            env={**os.environ, 'HOME': str(self.home), 'PATH': f'{self.bin}:{os.environ["PATH"]}'},
            capture_output=True, text=True)

    def pins(self):
        return {l.split('=')[0]: l.split('=', 1)[1] for l in self.env_file.read_text().splitlines() if '=' in l}

    def test_pins_tree_and_env_together_and_snapshots_outside(self):
        result = self.run_pin('v9.9.9')
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(git('describe', '--tags', cwd=self.root), 'v9.9.9')
        self.assertEqual(git('rev-parse', '--abbrev-ref', 'HEAD', cwd=self.root), 'HEAD')  # detached
        pins = self.pins()
        self.assertEqual({pins['VIDRA_CORE_TAG'], pins['VIDRA_USER_TAG'], pins['VIDRA_SEARCH_TAG']}, {'v9.9.9'})
        self.assertEqual(pins['JWT_SECRET'], 'fake-not-a-secret')
        history = self.home / '.local/state/vidra/env-history'
        snapshots = list(history.iterdir())
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(stat.S_IMODE(snapshots[0].stat().st_mode), 0o600)
        self.assertIn('VIDRA_CORE_TAG=v0.0.1', snapshots[0].read_text())
        self.assertFalse(list(self.root.glob('env/*.bak*')))
        self.assertIn('next: ./deploy/deploy.sh', result.stdout)

    def test_rerun_is_a_no_op_apart_from_a_fresh_snapshot(self):
        self.assertEqual(self.run_pin('v9.9.9').returncode, 0)
        before = self.env_file.read_text()
        self.assertEqual(self.run_pin('v9.9.9').returncode, 0)
        self.assertEqual(self.env_file.read_text(), before)
        self.assertEqual(len(list((self.home / '.local/state/vidra/env-history').iterdir())), 2)

    def test_root_is_refused_before_any_git_command(self):
        fake_id = self.bin / 'id'
        fake_id.write_text('#!/bin/sh\necho 0\n')
        fake_id.chmod(0o755)
        before_head = git('rev-parse', 'HEAD', cwd=self.root)
        result = self.run_pin('v9.9.9')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('refusing to run as root', result.stderr)
        self.assertIn('sudo -u', result.stderr)
        self.assertNotIn('fetching', result.stdout)
        self.assertEqual(git('rev-parse', 'HEAD', cwd=self.root), before_head)
        self.assertEqual(self.pins()['VIDRA_CORE_TAG'], 'v0.0.1')

    def test_unreleased_tag_changes_nothing(self):
        result = self.run_pin('v9.9.8')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('not a tag on origin', result.stderr)
        self.assertEqual(git('rev-parse', '--abbrev-ref', 'HEAD', cwd=self.root), 'main')
        self.assertEqual(self.pins()['VIDRA_CORE_TAG'], 'v0.0.1')
        self.assertFalse((self.home / '.local/state/vidra/env-history').exists())

    def test_malformed_tag_is_refused(self):
        for bad in ('latest', '0.6.4', 'v0.6'):
            with self.subTest(tag=bad):
                result = self.run_pin(bad)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('not a vMAJOR.MINOR.PATCH tag', result.stderr)

    def test_stray_env_copy_stops_it_before_the_tree_moves(self):
        (self.root / 'env/production.env.backup').write_text('copy')
        result = self.run_pin('v9.9.9')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Stray environment backup', result.stderr)
        self.assertEqual(git('rev-parse', '--abbrev-ref', 'HEAD', cwd=self.root), 'main')
        self.assertEqual(self.pins()['VIDRA_CORE_TAG'], 'v0.0.1')


if __name__ == '__main__':
    unittest.main()
