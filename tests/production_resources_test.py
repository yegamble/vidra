"""Exercise shipped resource expressions before component checkouts exist in CI."""
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]


class ProductionResources(unittest.TestCase):
    def test_fresh_template_fits_documented_four_core_floor_with_scanning(self):
        template = (ROOT / 'env/production.env.example').read_text()
        # Read actual overlay fields, including their fallback expressions. YAML
        # nodes avoid interpreting unrelated !reset/!override tags. The complete
        # model is validated later by CI after its pinned component checkouts.
        def field(node, key):
            return next(value for name, value in node.value if name.value == key)

        def value(node):
            return [value(item) for item in node.value] if isinstance(node, yaml.SequenceNode) else node.value

        services = field(yaml.compose((ROOT / 'docker-compose.prod.yml').read_text()), 'services')
        api, postgres = field(services, 'api'), field(services, 'postgres')
        model = {'services': {
            'api': {'image': 'scratch', **{key: value(field(api, key)) for key in ('cpus', 'mem_limit')}},
            'postgres': {'image': 'scratch', 'command': value(field(postgres, 'command'))}}}
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / 'check.env'
            env_file.write_text(template)
            compose_file = Path(directory) / 'compose.yml'
            compose_file.write_text(yaml.safe_dump(model))
            # Ambient operator overrides must not hide a broken fresh template.
            env = {key: value for key, value in os.environ.items()
                   if key in ('PATH', 'HOME', 'DOCKER_CONFIG')}
            result = subprocess.run(
                ['docker', 'compose', '-f', str(compose_file), '--env-file', str(env_file),
                 'config', '--format', 'json'],
                cwd=ROOT, env=env, text=True, capture_output=True, check=True)
        services = json.loads(result.stdout)['services']
        self.assertEqual(float(services['api']['cpus']), 3)
        self.assertEqual(int(services['api']['mem_limit']), 4 * 1024**3)
        self.assertIn('shared_buffers=512MB', services['postgres']['command'])
        self.assertIn('effective_cache_size=3GB', services['postgres']['command'])
        self.assertRegex(template, r'(?m)^MALWARE_SCAN_MODE=fail-closed$')
        self.assertIn('scan', re.search(r'^VIDRA_COMPOSE_PROFILES=(.+)$', template, re.M).group(1).split())


if __name__ == '__main__':
    unittest.main()
