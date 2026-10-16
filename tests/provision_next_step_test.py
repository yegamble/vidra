"""provision.sh's closing line must name the step the operator is actually at, as the right user.

The quickstart runs install.sh (which writes env/production.env) BEFORE provision.sh, and
provision.sh hands the tree and that 0600 file to the service user. Its old closing line said
"then 'vidra setup'" (a step already done) and, like install.sh, implied running vidra as the
login user, which fails on a permission error. provision.sh needs root, so the function is lifted
VERBATIM (the tests/provision_backups_test.py technique). Nothing here skips.
"""
from pathlib import Path
import os
import re
import subprocess
import tempfile
import unittest

TEXT = (Path(__file__).resolve().parents[1] / 'deploy' / 'provision.sh').read_text()
FUNC = re.search(r'^print_next_step\(\) \{\n.*?^\}\n', TEXT, re.S | re.M)


class PrintNextStepTest(unittest.TestCase):
    def run_fn(self, with_env):
        self.assertIsNotNone(FUNC, 'provision.sh no longer defines print_next_step')
        vdir = Path(tempfile.mkdtemp())
        if with_env:
            (vdir / 'env').mkdir()
            (vdir / 'env' / 'production.env').write_text('')
        script = 'log() { printf "[provision] %s\\n" "$*"; }\n' + FUNC.group(0) + 'print_next_step\n'
        env = dict(os.environ, VIDRA_DIR=str(vdir), VIDRA_USER='svc')
        r = subprocess.run(['bash', '-c', script], env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_installed_tree_is_sent_to_deploy_and_claim_as_the_service_user(self):
        out = self.run_fn(with_env=True)
        self.assertIn('sudo -u svc vidra deploy', out)
        self.assertIn('sudo -u svc vidra claim', out)
        self.assertNotIn('vidra setup', out)

    def test_bare_host_is_sent_to_install_then_deploy_as_the_service_user(self):
        out = self.run_fn(with_env=False)
        self.assertIn('install.sh', out)
        self.assertIn('sudo -u svc vidra deploy', out)

    def test_install_sh_closing_commands_run_as_the_service_user(self):
        install = (Path(__file__).resolve().parents[1] / 'install.sh').read_text()
        for verb in ('deploy', 'doctor', 'status', 'claim'):
            self.assertIn(f'cd ${{DIR}} && sudo -u vidra vidra {verb}', install, verb)
            self.assertNotIn(f'cd ${{DIR}} && vidra {verb}', install, verb)


if __name__ == '__main__':
    unittest.main()
