"""REC03's explicit small fixture profile preserves private operator settings."""
from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'tests' / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


envfix = load('rec03_envfix', 'rec03-envfix.py')
runner = load('rec03_resource_runner', 'rec03-runner.py')
CANARY = 'private-canary-$literal-backslash\\-must-survive'
SMALL = {'API_CPUS': '3.0', 'API_MEM_LIMIT': '4g',
         'POSTGRES_SHARED_BUFFERS': '512MB', 'POSTGRES_EFFECTIVE_CACHE_SIZE': '3GB'}


def values(text):
    return dict(line.split('=', 1) for line in text.splitlines()
                if '=' in line and not line.startswith('#'))


class FixtureEnv(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'production.env'

    def test_real_template_gets_documented_small_caps_and_keeps_secret(self):
        source = (ROOT / 'env/production.env.example').read_text()
        source += f'\nPRIVATE_OPERATOR_VALUE={CANARY}\n'
        self.path.write_text(source)
        envfix.apply(self.path, 'small')
        output = self.path.read_text()
        actual = values(output)
        for key, expected in SMALL.items():
            self.assertEqual(actual[key], expected, key)
        self.assertEqual(actual['MALWARE_SCAN_MODE'], 'disabled')
        self.assertNotIn('CLAMAV_ADDR', actual)
        self.assertEqual(actual['PRIVATE_OPERATOR_VALUE'], CANARY)
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        envfix.apply(self.path, 'small')
        self.assertEqual(self.path.read_text(), output, 'profile is not idempotent')

    def test_small_replaces_existing_caps_without_rewriting_unrelated_bytes(self):
        unrelated = f'# keep this exact comment\nJWT_SECRET={CANARY}\nCUSTOM=value with spaces\n'
        self.path.write_text(unrelated + '\n'.join(f'{key}=old' for key in SMALL))
        envfix.apply(self.path, 'small')
        output = self.path.read_text()
        self.assertTrue(output.startswith(unrelated))
        for key, expected in SMALL.items():
            self.assertEqual(values(output)[key], expected)
            self.assertEqual(output.count(f'\n{key}='), 1)

    def test_absent_profile_keeps_historical_operator_resource_settings(self):
        resources = '\n'.join(f'{key}=operator-choice' for key in SMALL) + '\n'
        self.path.write_text(resources + f'JWT_SECRET={CANARY}')
        envfix.apply(self.path)
        output = self.path.read_text()
        self.assertTrue(output.startswith(resources))
        self.assertEqual(values(output)['JWT_SECRET'], CANARY)
        self.assertEqual(values(output)['MALWARE_SCAN_MODE'], 'disabled')

    def test_unknown_nonempty_profile_refuses_before_any_file_access(self):
        self.path.write_text(f'JWT_SECRET={CANARY}\n')
        before = self.path.read_bytes()
        for bad in ('SMALL', 'small ', 'large', CANARY):
            with self.subTest(profile=bad), patch.object(Path, 'read_text') as read, \
                    patch.object(envfix.tempfile, 'NamedTemporaryFile') as temporary:
                with self.assertRaisesRegex(ValueError, '^unknown REC03 resource profile$'):
                    envfix.apply(self.path, bad)
                read.assert_not_called()
                temporary.assert_not_called()
        self.assertEqual(self.path.read_bytes(), before)

    def test_atomic_replacement_never_exposes_a_public_secret_copy(self):
        self.path.write_text(f'JWT_SECRET={CANARY}\n')
        original = self.path.read_bytes()
        def refused(source, destination):
            self.assertEqual(destination, self.path)
            self.assertEqual(stat.S_IMODE(Path(source).stat().st_mode), 0o600)
            self.assertEqual(self.path.read_bytes(), original)
            raise OSError('replacement refused')
        with patch.object(envfix.os, 'replace', side_effect=refused):
            with self.assertRaises(OSError):
                envfix.apply(self.path, 'small')
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_cli_prints_only_fixed_labels_even_for_private_bad_profile(self):
        for profile, expected, status in (
                ('', 'scan posture applied\n', 0),
                ('small', 'scan posture and small resource profile applied\n', 0),
                (CANARY, 'REC03 resource profile refused\n', 1)):
            with self.subTest(profile=profile):
                output = io.StringIO()
                call = envfix.apply
                with patch.dict(os.environ, {'REC03_RESOURCE_PROFILE': profile}), \
                        patch.object(envfix, 'apply', side_effect=lambda path, profile: call(self.path, profile)), \
                        redirect_stdout(output), redirect_stderr(output):
                    self.path.write_text(f'JWT_SECRET={CANARY}\n')
                    self.assertEqual(envfix.main(), status)
                self.assertEqual(output.getvalue(), expected)
                self.assertNotIn(CANARY, output.getvalue())


class HostedResourceFloor(unittest.TestCase):
    def test_two_cpus_and_unknown_count_refuse_but_four_cpus_pass(self):
        for cpus in (None, 0, 2, 3):
            with self.subTest(cpus=cpus), patch.object(runner.os, 'cpu_count', return_value=cpus):
                with self.assertRaisesRegex(runner.Failure, '^small resource profile requires four CPUs$'):
                    runner.require_small_resource_host()
        with patch.object(runner.os, 'cpu_count', return_value=4):
            runner.require_small_resource_host()

    def test_two_cpu_runner_exports_safe_preflight_failure_before_host_calls(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch.dict(os.environ, {'REC03_RECORD_REF': 'a' * 40,
                                       'REC03_INSTALLER_REF': 'b' * 40,
                                       'RUNNER_ENVIRONMENT': 'github-hosted'}), \
                patch.object(runner.os, 'geteuid', return_value=0), \
                patch.object(runner.os, 'cpu_count', return_value=2), \
                patch.object(runner.subprocess, 'run') as command, \
                patch.object(runner.urllib.request, 'urlopen') as fetch, \
                redirect_stdout(io.StringIO()):
            self.assertEqual(runner.main(Path(tmp)), 1)
            command.assert_not_called()
            fetch.assert_not_called()
            result = json.loads((Path(tmp) / 'summary.json').read_text())
            self.assertEqual(result['failed_phase'], 'preflight')
            self.assertEqual(result['failure'], 'small resource profile requires four CPUs')
            self.assertEqual(result['phases'], {})


if __name__ == '__main__':
    unittest.main()
