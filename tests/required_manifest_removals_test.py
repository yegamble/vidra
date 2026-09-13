"""Retiring a required lane must be a deliberate, tombstoned edit.

.github/required-checks.txt defines "required for merge" and was the one file
no gate watched: a PR whose only change deleted a line from it merged with a
lane silently dropped. scripts/ci/check-required-manifest-removals.sh compares
the head's manifest with the base's and fails on a removed entry that has no
`# retired: <name> — <reason>` line; scripts/ci/check-required-manifest-removals_test.sh
is its twin regression suite (byte-identical in vidra-core, vidra-search and
vidra-user, where ci-guard runs it). This repo has no ci-guard, so the suite
runs here, in the unit lane meta-ci already runs with a skip failing the job.
It needs bash and git; neither missing may pass as a skip, so a missing tool
fails the test.
"""
from pathlib import Path
import shutil
import subprocess
import unittest

SUITE = Path(__file__).resolve().parents[1] / 'scripts/ci/check-required-manifest-removals_test.sh'


class RequiredManifestRemovalsTests(unittest.TestCase):
    def test_twin_suite_passes(self):
        for tool in ('bash', 'git'):
            if shutil.which(tool) is None:
                self.fail(f'{tool} is required to run {SUITE.name}')
        p = subprocess.run(['bash', str(SUITE)], capture_output=True, text=True, timeout=300)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertRegex(p.stdout, r'assertions, 0 failed')
        self.assertNotIn('not ok', p.stdout)


if __name__ == '__main__':
    unittest.main()
