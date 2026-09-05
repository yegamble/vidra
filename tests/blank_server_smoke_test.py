"""A02 assertions must reject incomplete or misleading host evidence."""
import copy
import importlib.util
import json
import os
import subprocess
import tempfile
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('smoke', Path(__file__).with_name('blank_server_smoke.py'))
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


class SmokeTests(unittest.TestCase):
    def candidate(self):
        return json.loads((Path(__file__).resolve().parents[1] / 'docs/evidence/a01-v0.6.2-linux-amd64.json').read_text())

    def test_only_complete_a01_candidate_can_create_vm(self):
        candidate = self.candidate()
        p.validate_candidate(candidate)
        for field in ('repositories', 'images', 'assets', 'checks'):
            bad = copy.deepcopy(candidate)
            bad[field] = {}
            with self.assertRaises(ValueError):
                p.validate_candidate(bad)
        candidate['status'] = 'UNVERIFIED'
        with self.assertRaises(ValueError):
            p.validate_candidate(candidate)

    def test_moving_image_tag_is_rejected(self):
        candidate = self.candidate()
        candidate['images']['vidra-core']['reference'] = 'ghcr.io/yegamble/vidra-core:latest'
        with self.assertRaises(ValueError):
            p.validate_candidate(candidate)

    def model(self):
        return {'services': {**{name: {} for name in ('postgres', 'redis', 'search')},
            'api': {'ports': [{'host_ip': '127.0.0.1', 'target': 8080, 'published': '8080'}]},
            'frontend': {'ports': [{'host_ip': '127.0.0.1', 'target': 3000, 'published': '3000'}]}}}

    def test_exact_loopback_ports_and_no_datastore_publication(self):
        p.check_ports(self.model())
        for name in ('postgres', 'redis', 'search'):
            model = self.model()
            model['services'][name]['ports'] = [{'host_ip': '0.0.0.0', 'target': 5432}]
            with self.assertRaises(ValueError):
                p.check_ports(model)
        for name in ('api', 'frontend'):
            model = self.model()
            model['services'][name]['ports'][0].pop('host_ip')
            with self.assertRaises(ValueError):
                p.check_ports(model)

    def test_empty_profile_render_cannot_pass(self):
        with self.assertRaises(ValueError):
            p.check_ports({'services': {}})
        model = self.model()
        model['services']['api']['ports'] = []
        with self.assertRaises(ValueError):
            p.check_ports(model)

    def test_native_cli_checksum_is_selected_exactly_once(self):
        sums = 'a' * 64 + '  vidra_v0.6.2_linux_arm64\n' + 'b' * 64 + '  vidra_v0.6.2_linux_amd64\n'
        self.assertEqual(p.expected_hash(sums, 'vidra_v0.6.2_linux_arm64'), 'a' * 64)
        for text in ('', sums + sums):
            with self.assertRaises(ValueError):
                p.expected_hash(text, 'vidra_v0.6.2_linux_arm64')

    def test_existing_output_refused_before_any_vm_operation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            marker = root / 'multipass-called'
            tool = root / 'multipass'
            tool.write_text('#!/bin/sh\ntouch "' + str(marker) + '"\nexit 99\n')
            tool.chmod(0o755)
            candidate = root / 'candidate.json'
            candidate.write_text(json.dumps(self.candidate()))
            script = Path(__file__).with_name('blank-server-smoke.sh')
            result = subprocess.run(['bash', str(script), str(candidate), tmp],
                env=dict(os.environ, PATH=str(root) + ':' + os.environ['PATH']),
                capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('output exists', result.stderr)
            self.assertFalse(marker.exists())


if __name__ == '__main__':
    unittest.main()
