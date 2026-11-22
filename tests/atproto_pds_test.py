import concurrent.futures
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'deploy/atproto-pds.py'


class LocalPDSTest(unittest.TestCase):
    def test_secrets_survive_concurrent_deploys_and_missing_key_refuses_existing_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'pds.env'
            data = Path(tmp) / 'data'
            args = ['python3', str(SCRIPT), '--prepare', str(path), '--data-dir', str(data)]
            with concurrent.futures.ThreadPoolExecutor() as pool:
                results = list(pool.map(lambda _: subprocess.run(args, capture_output=True), range(4)))
            self.assertEqual([r.returncode for r in results], [0] * 4)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            initial = path.read_bytes()
            self.assertEqual(data.stat().st_mode & 0o777, 0o700)
            (data / 'account.sqlite').touch()
            subprocess.run(args, check=True)
            self.assertEqual(path.read_bytes(), initial)
            path.unlink()
            self.assertNotEqual(subprocess.run(args, capture_output=True).returncode, 0)
            self.assertFalse(path.exists())

    def test_invalid_restored_rotation_key_is_refused_and_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'pds.env'
            args = ['python3', str(SCRIPT), '--prepare', str(path), '--data-dir', str(Path(tmp) / 'data')]
            subprocess.run(args, check=True)
            lines = path.read_text().splitlines()
            for scalar in ('123', 'g' * 64, '0' * 64, 'f' * 64):
                with self.subTest(scalar=scalar[:3]):
                    damaged = '\n'.join(
                        f'{key}={scalar}' if key.endswith('PRIVATE_KEY_HEX') else f'{key}={value}'
                        for key, value in (line.split('=', 1) for line in lines)
                    ) + '\n'
                    path.write_text(damaged)
                    result = subprocess.run(args, capture_output=True, text=True)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('restore the original credentials', result.stderr)
                    self.assertEqual(path.read_text(), damaged)

    def test_host_and_profile_selection(self):
        for enabled, url, expected in [('false', '', False), ('true', '', True),
                                       ('true', 'https://service.example', False)]:
            with self.subTest(enabled=enabled, url=url):
                result = subprocess.run(
                    ['bash', '-ec', '. deploy/lib.sh; vidra_compose_chain; printf "%s\\n" "${COMPOSE[@]}"'],
                    cwd=ROOT, env={**os.environ, 'REPO_ROOT': str(ROOT), 'ENV_FILE': '/dev/null',
                                   'PUBLIC_BASE_URL': 'https://video.example', 'ATPROTO_ENABLED': enabled,
                                   'ATPROTO_PDS_URL': url}, text=True, capture_output=True, check=True)
                self.assertEqual('docker-compose.atproto-pds.yml' in result.stdout, expected)
        self.assertEqual(subprocess.check_output(['python3', str(SCRIPT), '--hostname', 'https://video.example'], text=True).strip(), 'pds.video.example')
