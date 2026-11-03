"""Render the shipped fresh-install template against the real production model."""
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ProductionResources(unittest.TestCase):
    def test_fresh_template_fits_documented_four_core_floor_with_scanning(self):
        template = (ROOT / 'env/production.env.example').read_text()
        compose = '\n'.join((ROOT / name).read_text() for name in
                            ('docker-compose.yml', 'docker-compose.prod.yml'))
        # Required secrets are dummies; keep every shipped resource/scan choice.
        required = set(re.findall(r'\$\{([A-Z0-9_]+):\?', compose))
        profiles = re.search(r'^VIDRA_COMPOSE_PROFILES=(.+)$', template, re.M).group(1).split()
        for key in required:
            template = re.sub(r'^' + key + r'=.*$', key + '=resource-test-dummy',
                              template, flags=re.M)
            if not re.search(r'^' + key + '=', template, flags=re.M):
                template += '\n' + key + '=resource-test-dummy\n'
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / 'check.env'
            env_file.write_text(template)
            # Ambient operator overrides must not hide a broken fresh template.
            env = {key: value for key, value in os.environ.items()
                   if key in ('PATH', 'HOME', 'DOCKER_CONFIG')}
            result = subprocess.run(
                ['docker', 'compose', '-f', 'docker-compose.yml', '-f',
                 'docker-compose.prod.yml', '--env-file', str(env_file),
                 *[arg for profile in profiles for arg in ('--profile', profile)],
                 'config', '--format', 'json'],
                cwd=ROOT, env=env, text=True, capture_output=True, check=True)
        services = json.loads(result.stdout)['services']
        self.assertEqual(float(services['api']['cpus']), 3)
        self.assertEqual(int(services['api']['mem_limit']), 4 * 1024**3)
        self.assertIn('shared_buffers=512MB', services['postgres']['command'])
        self.assertIn('effective_cache_size=3GB', services['postgres']['command'])
        self.assertEqual(services['api']['environment']['MALWARE_SCAN_MODE'], 'fail-closed')
        self.assertIn('clamav', services)


if __name__ == '__main__':
    unittest.main()
