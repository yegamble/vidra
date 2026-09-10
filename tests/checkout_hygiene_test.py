"""Exercise filesystem guards without root access or a running stack."""
import importlib.util
import os
from pathlib import Path
import stat
import subprocess
import shutil
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    'hygiene', Path(__file__).resolve().parents[1] / 'deploy/checkout-hygiene.py')
hygiene = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(hygiene)


class CheckoutHygieneTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'checkout'
        self.root.mkdir()

    def init_git(self, root=None):
        root = root or self.root
        subprocess.run(['git', 'init', '-q', str(root)], check=True)

    def test_clean_bundle_and_checkout_pass(self):
        hygiene.check(self.root)
        self.init_git()
        hygiene.check(self.root)

    def test_wrong_invoking_user_refused_before_git(self):
        self.init_git()
        with patch.object(hygiene.os, 'geteuid', return_value=os.getuid() + 1):
            with patch.object(hygiene.subprocess, 'check_output') as git:
                with self.assertRaisesRegex(ValueError, 'Run deployment as checkout owner'):
                    hygiene.check(self.root)
                git.assert_not_called()

    def test_foreign_owned_object_in_nested_checkout_refused(self):
        nested = self.root / 'vidra-core'
        self.init_git(nested)
        bad = (nested / '.git/objects/foreign').resolve()
        bad.write_text('object')
        original = Path.lstat

        def lstat(path, *args, **kwargs):
            result = original(path, *args, **kwargs)
            if path == bad:
                fields = list(result)
                fields[4] = os.getuid() + 1
                return os.stat_result(fields)
            return result

        with patch.object(Path, 'lstat', lstat):
            with self.assertRaisesRegex(ValueError, 'sudo chown -h'):
                hygiene.check(self.root)

    def test_stray_backup_patterns_refused_without_reading_secrets(self):
        for name in ('production.env.bak', '.env.bak-prestorage',
                     'staging.env.old', '.env~', 'production.env.save.1'):
            with self.subTest(name=name):
                path = self.root / name
                path.write_text('SECRET_MUST_NOT_APPEAR')
                try:
                    with self.assertRaises(ValueError) as caught:
                        hygiene.check(self.root)
                    self.assertNotIn('SECRET_MUST_NOT_APPEAR', str(caught.exception))
                finally:
                    path.unlink()

    def test_live_env_and_templates_allowed(self):
        for name in ('production.env', '.env.example', 'production.env.example'):
            (self.root / name).touch()
        hygiene.check(self.root)

    def test_snapshots_unique_private_and_exact(self):
        source = self.root / 'production.env'
        source.write_bytes(b'KEY=secret\n')
        destination = Path(self.temp.name) / 'history'
        first = Path(hygiene.snapshot(self.root, source, destination))
        source.write_bytes(b'KEY=next\n')
        second = Path(hygiene.snapshot(self.root, source, destination))
        self.assertNotEqual(first, second)
        self.assertEqual(first.read_bytes(), b'KEY=secret\n')
        self.assertEqual(second.read_bytes(), b'KEY=next\n')
        self.assertEqual(stat.S_IMODE(first.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o700)

    def test_inside_checkout_and_symlink_into_checkout_refused(self):
        source = self.root / 'production.env'
        source.touch()
        alias = Path(self.temp.name) / 'alias'
        alias.symlink_to(self.root, target_is_directory=True)
        for destination in (self.root, self.root / 'backups', alias / 'backups'):
            with self.assertRaisesRegex(ValueError, 'outside the checkout'):
                hygiene.snapshot(self.root, source, destination)

    def test_failed_copy_leaves_no_snapshot(self):
        destination = Path(self.temp.name) / 'history'
        with self.assertRaises(FileNotFoundError):
            hygiene.snapshot(self.root, self.root / 'missing.env', destination)
        self.assertEqual(list(destination.iterdir()), [])

    def test_deploy_refuses_stray_backup_before_docker(self):
        deploy = self.root / 'deploy'
        deploy.mkdir()
        source = Path(__file__).resolve().parents[1] / 'deploy'
        for name in ('deploy.sh', 'lib.sh', 'checkout-hygiene.py'):
            shutil.copyfile(source / name, deploy / name)
        (self.root / 'env').mkdir()
        (self.root / 'env/production.env').write_text('VIDRA_TLS_MODE=plain-http\n')
        (self.root / 'env/production.env.bak').write_text('secret')
        commands = Path(self.temp.name) / 'bin'
        commands.mkdir()
        docker = commands / 'docker'
        docker.write_text('#!/bin/sh\necho DOCKER_WAS_CALLED >&2\nexit 99\n')
        docker.chmod(0o755)
        result = subprocess.run(['bash', str(deploy / 'deploy.sh')],
                                env={**os.environ, 'PATH': str(commands) + ':' + os.environ['PATH']},
                                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Stray environment backup', result.stderr)
        self.assertNotIn('DOCKER_WAS_CALLED', result.stderr)


if __name__ == '__main__':
    unittest.main()


class SeverityTests(unittest.TestCase):
    """A rollback runs mid-incident: only findings that stop it may stop it."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'checkout'
        self.root.mkdir()

    def foreign_metadata(self, repo):
        """Make one object in repo's metadata look owned by somebody else."""
        subprocess.run(['git', 'init', '-q', str(repo)], check=True)
        bad = (repo / '.git/objects/foreign').resolve()
        bad.write_text('object')
        original = Path.lstat

        def lstat(path, *args, **kwargs):
            result = original(path, *args, **kwargs)
            if path == bad:
                fields = list(result)
                fields[4] = os.getuid() + 1
                return os.stat_result(fields)
            return result

        return patch.object(Path, 'lstat', lstat)

    def test_stray_backup_warns_instead_of_refusing_for_rollback(self):
        (self.root / 'production.env.bak').write_text('SECRET_MUST_NOT_APPEAR')
        warnings = hygiene.check(self.root, env_backups='warn')
        self.assertTrue(any('Stray environment backup' in w for w in warnings))
        self.assertFalse(any('SECRET_MUST_NOT_APPEAR' in w for w in warnings))

    def test_stray_backup_still_fatal_by_default(self):
        (self.root / 'production.env.bak').write_text('secret')
        with self.assertRaisesRegex(ValueError, 'Stray environment backup'):
            hygiene.check(self.root)

    def test_unwritable_metadata_stays_fatal_even_for_rollback(self):
        # Rollback fetches and checks out the nested repositories, so metadata
        # it cannot write fails the run regardless. Warning would only move the
        # failure later and make it less readable.
        with self.foreign_metadata(self.root / 'vidra-core'):
            with self.assertRaisesRegex(ValueError, 'wrong owner'):
                hygiene.check(self.root, env_backups='warn')

    def test_every_finding_reported_in_one_run(self):
        for name in ('production.env.bak', 'staging.env.old'):
            (self.root / name).write_text('secret')
        with self.assertRaises(ValueError) as caught:
            hygiene.check(self.root)
        for name in ('production.env.bak', 'staging.env.old'):
            self.assertIn(name, str(caught.exception))

    def test_repair_command_covers_every_bad_path_at_once(self):
        with self.foreign_metadata(self.root):
            with self.assertRaises(ValueError) as caught:
                hygiene.check(self.root)
        message = str(caught.exception)
        self.assertIn('sudo chown -h', message)
        self.assertIn('chown -R', message)

    def test_clean_checkout_warns_about_nothing(self):
        self.assertEqual(hygiene.check(self.root, env_backups='warn'), [])

    def test_rollback_continues_past_a_stray_backup(self):
        repo = self.root
        (repo / 'deploy').mkdir()
        source = Path(__file__).resolve().parents[1] / 'deploy'
        for name in ('rollback.sh', 'lib.sh', 'checkout-hygiene.py', 'backup-env.sh'):
            shutil.copyfile(source / name, repo / 'deploy' / name)
        (repo / 'env').mkdir()
        (repo / 'env/production.env').write_text('VIDRA_TLS_MODE=acme\n')
        (repo / 'env/production.env.bak').write_text('secret')
        commands = Path(self.temp.name) / 'bin'
        commands.mkdir()
        docker = commands / 'docker'
        docker.write_text('#!/bin/sh\ncase "$*" in\n'
                          '"compose version --short") echo "v2.30.0" ;;\n'
                          '*) echo DOCKER_CALLED >&2; exit 99 ;;\nesac\n')
        docker.chmod(0o755)
        result = subprocess.run(
            ['bash', str(repo / 'deploy/rollback.sh'), 'v9.9.9'],
            env={**os.environ, 'PATH': str(commands) + ':' + os.environ['PATH'],
                 'HOME': self.temp.name},
            capture_output=True, text=True)
        combined = result.stdout + result.stderr
        self.assertIn('Stray environment backup', combined)
        self.assertNotIn('checkout hygiene preflight failed', combined)


class ScanHardeningTests(unittest.TestCase):
    """The scan must not miss a secret, nor die on a directory it cannot read."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'checkout'
        self.root.mkdir()

    def test_plausible_copies_are_caught(self):
        for name in ('production.env.backup', 'production.env.bak2',
                     'production.env.swp', 'production.env.2026-09-10',
                     'production.env.copy', 'production.env.old.1',
                     'staging.env.orig', '.env.saved', 'production.env.1'):
            with self.subTest(name=name):
                path = self.root / name
                path.write_text('SECRET_MUST_NOT_APPEAR')
                try:
                    with self.assertRaises(ValueError) as caught:
                        hygiene.check(self.root)
                    self.assertIn(name, str(caught.exception))
                    self.assertNotIn('SECRET_MUST_NOT_APPEAR', str(caught.exception))
                finally:
                    path.unlink()

    def test_real_config_and_templates_are_not_flagged(self):
        # Next.js keeps .env.local and friends; a template is not a copy.
        for name in ('production.env', '.env', '.env.example', '.env.template',
                     '.env.sample', '.env.dist', '.env.local', '.env.production',
                     '.env.development', '.env.test', 'production.env.example'):
            with self.subTest(name=name):
                path = self.root / name
                path.touch()
                try:
                    hygiene.check(self.root)
                finally:
                    path.unlink()

    def test_unreadable_directory_does_not_stop_a_rollback(self):
        blocked = self.root / 'unreadable'
        blocked.mkdir()
        blocked.chmod(0o000)
        self.addCleanup(blocked.chmod, 0o755)
        warnings = hygiene.check(self.root, env_backups='warn')
        self.assertTrue(any('unreadable' in w for w in warnings), warnings)

    def test_unreadable_directory_is_reported_not_swallowed(self):
        blocked = self.root / 'unreadable'
        blocked.mkdir()
        blocked.chmod(0o000)
        self.addCleanup(blocked.chmod, 0o755)
        with self.assertRaises(ValueError) as caught:
            hygiene.check(self.root)
        self.assertIn('unreadable', str(caught.exception))

    def test_unreadable_git_metadata_stays_fatal(self):
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        blocked = self.root / '.git/objects/blocked'
        blocked.mkdir()
        blocked.chmod(0o000)
        self.addCleanup(blocked.chmod, 0o755)
        with self.assertRaises(ValueError) as caught:
            hygiene.check(self.root, env_backups='warn')
        self.assertIn('blocked', str(caught.exception))
