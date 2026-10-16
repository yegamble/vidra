"""Run the Node fixture contract tests as part of the required meta unit lane."""
from pathlib import Path
import subprocess
import unittest


class SealedRecoveryAPI(unittest.TestCase):
    def test_fixture_contract_and_secret_boundaries(self):
        result = subprocess.run(['node', '--test', str(Path(__file__).with_name('sealed-recovery-api.test.mjs'))],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
