"""Fail-closed checks for the read-only release preflight."""
import importlib.util
import hashlib
import json
from unittest.mock import patch
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('preflight', Path(__file__).resolve().parents[1] / 'deploy/release-preflight.py')
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


class PreflightTests(unittest.TestCase):
    def test_image_requires_digest_platform_and_matching_source(self):
        image = {'manifest': {'digest': 'sha256:' + 'a' * 64}, 'image': {
            'os': 'linux', 'architecture': 'amd64', 'config': {'Labels': {
                'org.opencontainers.image.revision': 'b' * 40,
                'org.opencontainers.image.source': 'https://github.com/yegamble/vidra-core'}}}}
        self.assertEqual(p.image_pin(image, 'yegamble/vidra-core', 'b' * 40, 'linux/amd64')['digest'], 'sha256:' + 'a' * 64)
        for revision, platform in [('c' * 40, 'linux/amd64'), ('b' * 40, 'linux/arm64')]:
            with self.assertRaises(ValueError):
                p.image_pin(image, 'yegamble/vidra-core', revision, platform)
        image['manifest']['digest'] = 'latest'
        with self.assertRaises(ValueError):
            p.image_pin(image, 'yegamble/vidra-core', 'b' * 40, 'linux/amd64')

    def test_checksum_missing_duplicate_or_corrupt_never_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'bundle.tar.gz'
            path.write_bytes(b'actual release bytes')
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            line = f'{digest}  {path.name}\n'
            self.assertEqual(p.verify_checksum(path, line), digest)
            for sums in ['', line + line, '0' * 64 + '  ' + path.name]:
                with self.assertRaises(ValueError):
                    p.verify_checksum(path, sums)

    def test_resolver_regression_removes_only_resolver(self):
        yaml = 'paths:\n  /api/v1/videos/resolve:\n    get:\n      summary: Resolve\n  /api/v1/videos/{id}:\n    get:\ncomponents:\n  schemas: {}\n'
        result = p.without_resolver(yaml)
        self.assertNotIn('/api/v1/videos/resolve:', result)
        self.assertIn('/api/v1/videos/{id}:', result)
        self.assertIn('components:', result)
        with self.assertRaises(ValueError):
            p.without_resolver(result)

    def test_asset_names_are_explicit_linux_and_bundle(self):
        self.assertEqual(p.asset_names('v0.6.2', 'linux/amd64'),
                         ['vidra-bundle_v0.6.2.tar.gz', 'vidra_v0.6.2_linux_amd64'])

    def test_failed_dependency_preserves_manifest_and_nonzero_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'candidate'
            with patch('sys.argv', ['preflight', '--tag', 'v0.6.2', '--out', str(out)]), \
                    patch.object(p, 'freeze', side_effect=RuntimeError('registry unavailable')):
                self.assertEqual(p.main(), 1)
            manifest = json.loads((out / 'manifest.json').read_text())
            self.assertEqual(manifest['status'], 'FAIL')
            self.assertEqual(manifest['error'], 'registry unavailable')
            self.assertEqual(manifest['checks'], {})

    def test_existing_evidence_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / 'manifest.json'
            marker.write_text('previous evidence')
            with patch('sys.argv', ['preflight', '--tag', 'v0.6.2', '--out', tmp]):
                with self.assertRaises(FileExistsError):
                    p.main()
            self.assertEqual(marker.read_text(), 'previous evidence')

    def test_command_failure_is_not_accepted(self):
        with self.assertRaises(RuntimeError):
            p.run(['python3', '-c', 'raise SystemExit(7)'])

    def test_unsupported_node_rejected_before_network(self):
        with patch.object(p, 'run', return_value='v22.14.0') as run:
            with self.assertRaisesRegex(ValueError, 'Node >=24'):
                p.freeze(None, None, {})
            run.assert_called_once_with(['node', '--version'])


if __name__ == '__main__':
    unittest.main()
