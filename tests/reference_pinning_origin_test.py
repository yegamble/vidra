"""The spike teardown must never signal an unrelated recycled PID."""
import os
import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPIKE = ROOT / 'docs/evidence/ipfs-reference-pinning-spike-2026-09-20'


class OriginStopTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.spike = self.root / 'spike'
        self.spike.mkdir()
        (self.spike / 'out').mkdir()
        for name in ('run.sh', 'lib.sh', 'stop-origin.py'):
            if (SPIKE / name).exists():
                shutil.copy2(SPIKE / name, self.spike / name)
        self.origin = self.spike / 'origin.py'
        # A process fixture with the production argv; no listener or lab stack.
        self.origin.write_text('import signal\nprint("ready", flush=True)\nsignal.pause()\n')
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        docker = self.bin / 'docker'
        docker.write_text('#!/bin/sh\nexit 0\n')
        docker.chmod(0o755)

    def start(self, script=None, extra=()):
        child = subprocess.Popen(
            [sys.executable, str(script or self.origin), *extra],
            stdout=subprocess.PIPE, text=True)

        def cleanup():
            if child.poll() is None:
                child.terminate()
            child.wait(timeout=5)
            child.stdout.close()
        self.addCleanup(cleanup)
        self.assertEqual(child.stdout.readline().strip(), 'ready')
        (self.spike / 'out/origin.pid').write_text(str(child.pid))
        return child

    def argv(self):
        return (str(self.spike / 'origin-root'), '18090',
                str(self.spike / 'out/origin-requests.txt'), str(self.spike / 'mode.txt'))

    def teardown(self):
        return subprocess.run(
            ['bash', str(self.spike / 'run.sh'), 'teardown'],
            env={**os.environ, 'PATH': str(self.bin) + ':' + os.environ['PATH']},
            capture_output=True, text=True, timeout=10)

    def test_stale_pid_that_now_names_another_process_is_not_signalled(self):
        other = self.root / 'unrelated.py'
        shutil.copy2(self.origin, other)
        child = self.start(other)
        result = self.teardown()
        self.assertIsNone(child.poll(), 'teardown killed an unrelated process')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('does not match this spike origin', result.stderr)

    def test_same_script_name_elsewhere_is_not_the_fixture(self):
        other = self.root / 'origin.py'
        shutil.copy2(self.origin, other)
        child = self.start(other, self.argv())
        result = self.teardown()
        self.assertIsNone(child.poll(), 'basename-only matching killed another origin')
        self.assertNotEqual(result.returncode, 0)

    def test_correct_script_with_other_arguments_is_not_signalled(self):
        child = self.start(extra=('different-fixture',))
        result = self.teardown()
        self.assertIsNone(child.poll(), 'origin arguments must identify this fixture')
        self.assertNotEqual(result.returncode, 0)

    def test_matching_origin_is_stopped_and_its_pid_file_removed(self):
        child = self.start(extra=self.argv())
        result = self.teardown()
        self.assertEqual(result.returncode, 0, result.stderr)
        child.wait(timeout=5)
        self.assertFalse((self.spike / 'out/origin.pid').exists())

    def test_missing_pid_file_is_harmless(self):
        self.assertEqual(self.teardown().returncode, 0)

    def test_invalid_or_process_group_pids_are_never_signalled(self):
        for value in ('0', '1', '-1', '-20', 'not-a-pid', ''):
            with self.subTest(value=value):
                (self.spike / 'out/origin.pid').write_text(value)
                result = self.teardown()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('invalid origin PID', result.stderr)

    def test_already_exited_origin_is_harmless(self):
        child = self.start(extra=self.argv())
        child.terminate()
        child.wait(timeout=5)
        self.assertEqual(self.teardown().returncode, 0)
        self.assertFalse((self.spike / 'out/origin.pid').exists())

    def test_macos_fallback_compares_the_entire_fixture_command(self):
        spec = importlib.util.spec_from_file_location('stop_origin', SPIKE / 'stop-origin.py')
        helper = importlib.util.module_from_spec(spec)
        with mock.patch.object(sys, 'dont_write_bytecode', True):
            spec.loader.exec_module(helper)
        expected = [str(self.origin), *self.argv()]
        command = ' '.join([sys.executable, *expected])
        with mock.patch.object(helper.sys, 'platform', 'darwin'):
            with mock.patch.object(helper.subprocess, 'run', return_value=
                                   subprocess.CompletedProcess([], 0, command + '\n', '')):
                self.assertTrue(helper.matches(12345, expected))
                self.assertFalse(helper.matches(12345, [str(self.root / 'origin.py'), *self.argv()]))
                self.assertFalse(helper.matches(12345, [str(self.origin), 'different-fixture']))


if __name__ == '__main__':
    unittest.main()
