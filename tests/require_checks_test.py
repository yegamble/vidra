"""The `ci-required` fan-in must stay fail-closed.

scripts/ci/require-checks.sh is the one check branch protection trusts, and
scripts/ci/require-checks_test.sh is its twin regression suite (byte-identical
in vidra-core, vidra-search and vidra-user, where ci-guard runs it). This repo
has no ci-guard, so the suite runs here, in the unit lane meta-ci already runs
with a skip failing the job. It needs bash and jq; neither missing may pass as
a skip, so a missing tool fails the test.
"""
from pathlib import Path
import shutil
import subprocess
import unittest

SUITE = Path(__file__).resolve().parents[1] / 'scripts/ci/require-checks_test.sh'


class RequireChecksFanInTests(unittest.TestCase):
    def test_twin_suite_passes(self):
        for tool in ('bash', 'jq'):
            if shutil.which(tool) is None:
                self.fail(f'{tool} is required to run {SUITE.name}')
        p = subprocess.run(['bash', str(SUITE)], capture_output=True, text=True, timeout=300)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertRegex(p.stdout, r'assertions, 0 failed')
        self.assertNotIn('not ok', p.stdout)


if __name__ == '__main__':
    unittest.main()
