"""Render the opt-in mount independently of component checkout availability."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = "docker-compose.ipfs-reference-status.yml"


class ReferenceStatusComposeTest(unittest.TestCase):
    def test_overlay_is_opt_in_and_only_the_api_can_read_the_aggregate(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            fixture = directory / 'compose.yml'
            fixture.write_text('services:\n  api:\n    image: alpine\n  worker:\n    image: alpine\n')
            for path in ('', str(directory)):
                with self.subTest(enabled=bool(path)):
                    env = {**os.environ, 'ENV_FILE': '/dev/null', 'IPFS_REFERENCE_STATUS_DIR': path}
                    chain = subprocess.check_output(
                        ['bash', '-ec', '. deploy/lib.sh; vidra_compose_chain; printf "%s\\n" "${COMPOSE[@]}"'],
                        cwd=ROOT, env=env, text=True).splitlines()
                    self.assertEqual(OVERLAY in chain, bool(path))
                    command = ['docker', 'compose', '-p', 'reference-status-test', '-f', str(fixture)]
                    if OVERLAY in chain:
                        command += ['-f', str(ROOT / OVERLAY)]
                    rendered = subprocess.check_output(command + ['config', '--format', 'json'], env=env)
                    services = json.loads(rendered)['services']
                    self.assertNotIn('volumes', services['worker'])
                    self.assertNotIn('environment', services['worker'])
                    if not path:
                        self.assertNotIn('volumes', services['api'])
                        self.assertNotIn('environment', services['api'])
                        continue
                    api = services['api']
                    self.assertEqual(api['environment'], {
                        'IPFS_REFERENCE_STATUS_FILE': '/run/vidra-reference-status/status.json'})
                    self.assertEqual(len(api['volumes']), 1)
                    mount = api['volumes'][0]
                    self.assertEqual(mount['type'], 'bind')
                    self.assertEqual(Path(mount['source']).resolve(), directory.resolve())
                    self.assertEqual(mount['target'], '/run/vidra-reference-status')
                    self.assertTrue(mount['read_only'])
                    # Compose omits false from canonical output on some versions.
                    self.assertFalse(mount.get('bind', {}).get('create_host_path', False))
                    self.assertIn('create_host_path: false', (ROOT / OVERLAY).read_text())
