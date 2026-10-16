"""Cross-job provenance and sanitized failure regressions; no VM execution."""
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / 'tests/hosted-sealed-recovery.py'
spec = importlib.util.spec_from_file_location('hosted_sealed', TOOL)
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)


class CrossJobBoundaryTest(unittest.TestCase):
    def test_same_vm_and_changed_release_or_tool_are_refused(self):
        record = {'release': 'v0.7.8', 'core_schema_version': 182}
        proof = dict.fromkeys(driver.PROOF_KEYS, {})
        proof.update(scope=driver.SCOPE, record_commit='a' * 40, tool_commit='b' * 40,
                     record_hash=driver.record_hash(record), source_stopped=True, source_boot='source')
        driver.verify_proof(proof, record, 'a' * 40, 'b' * 40, 'replacement')
        for changes in ({'source_boot': 'replacement'}, {'record_commit': 'c' * 40},
                        {'tool_commit': 'c' * 40}, {'source_stopped': False},
                        {'record_hash': '0' * 64}, {'unexpected_secret': 'fixture-value'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                driver.verify_proof({**proof, **changes}, record, 'a' * 40, 'b' * 40, 'replacement')

    def test_config_archive_duplicate_and_link_members_do_not_extract(self):
        for extra in ('duplicate', 'link'):
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                stream = io.BytesIO()
                with tarfile.open(fileobj=stream, mode='w:gz') as archive:
                    for name in driver.recovery.CONFIG_MEMBERS:
                        info = tarfile.TarInfo(name)
                        info.size = 1
                        archive.addfile(info, io.BytesIO(b'x'))
                    info = tarfile.TarInfo('env/production.env' if extra == 'duplicate' else 'link')
                    if extra == 'link':
                        info.type, info.linkname = tarfile.SYMTYPE, '/outside'
                    archive.addfile(info)
                path = root / 'config.tar.gz'
                path.write_bytes(stream.getvalue())
                expected = driver.recovery.check_config_archive(path, None)
                with self.assertRaises(ValueError):
                    driver.restore_config(path, root, expected)
                self.assertFalse((root / 'env').exists())

    def test_failed_precondition_does_not_leak_or_overwrite_prior_attempt(self):
        with tempfile.TemporaryDirectory() as temporary:
            stage = Path(temporary)
            (stage / 'private').mkdir()
            verdict = stage / 'verdict.json'
            verdict.write_text('prior-attempt')
            result = subprocess.run([sys.executable, str(TOOL), 'source', '--release', 'v0.7.8',
                '--record-commit', 'a' * 40, '--tool-commit', '0' * 40, '--record-root', str(ROOT),
                '--stage', str(stage)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stderr, '')
            self.assertEqual(json.loads(result.stdout), {'status': 'FAIL', 'scope': driver.SCOPE,
                                                         'synthetic_only': True, 'phase': 'preconditions'})
            self.assertEqual(verdict.read_text(), 'prior-attempt')


if __name__ == '__main__':
    unittest.main()
