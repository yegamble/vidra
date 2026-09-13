"""A03 must reject dirty, incomplete, or misleading runtime evidence."""
import copy
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
import runtime_smoke
from runtime_smoke import check_ledger, check_abort, check_runtime_ports

ROOT = Path(__file__).resolve().parents[1]


class RuntimeTests(unittest.TestCase):
    def test_ledger_requires_exact_version_and_clean_single_row(self):
        check_ledger('125|f\n', 125)
        for value in ('', '125|t', '124|f', '125|f\n125|f', '125|unknown'):
            with self.assertRaises(ValueError):
                check_ledger(value, 125)

    def test_abort_requires_real_failure_and_no_start_or_container_change(self):
        before = {'api': ['id', 'timestamp', 0]}
        check_abort(1, 'CORE MIGRATION FAILED', 'CORE', before, before)
        for code, log, after in ((0, 'CORE MIGRATION FAILED', before),
                                 (1, 'pull failed', before),
                                 (1, 'CORE MIGRATION FAILED\n4/6 start', before),
                                 (1, 'CORE MIGRATION FAILED', {})):
            with self.assertRaises(ValueError):
                check_abort(code, log, 'CORE', before, after)

    def test_runtime_ports_examine_actual_bindings(self):
        ports = {s: {} for s in ('postgres', 'redis', 'search')}
        for name, port in (('api', 8080), ('frontend', 3000)):
            ports[name] = {f'{port}/tcp': [{'HostIp': '127.0.0.1', 'HostPort': str(port)}]}
        check_runtime_ports(ports)
        bad = copy.deepcopy(ports)
        bad['postgres'] = {'5432/tcp': [{'HostIp': '0.0.0.0', 'HostPort': '5432'}]}
        with self.assertRaises(ValueError):
            check_runtime_ports(bad)
        bad = copy.deepcopy(ports)
        bad['api']['8080/tcp'][0]['HostIp'] = '0.0.0.0'
        with self.assertRaises(ValueError):
            check_runtime_ports(bad)


class DeployUnderTestTests(unittest.TestCase):
    """A03 swaps the CURRENT deploy.sh into a RELEASED bundle. deploy.sh now
    sources lib.sh's release_mapping_check and runs deploy/release-mapping.py
    against releases/, none of which a released bundle's copy has. Swapping
    deploy.sh alone made every A03 deploy exit before doing anything, with a
    message blaming the tag mapping."""

    def installer(self):
        install = getattr(runtime_smoke, 'install_under_test', None)
        self.assertIsNotNone(install, 'runtime_smoke.install_under_test is missing')
        return install

    def test_the_released_tree_receives_everything_the_new_deploy_sh_needs(self):
        install = self.installer()
        with tempfile.TemporaryDirectory() as tmp:
            source, root = Path(tmp) / 'under-test', Path(tmp) / 'installation'
            for rel in runtime_smoke.UNDER_TEST:
                (source / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / rel, source / rel)
            shutil.copytree(ROOT / 'releases', source / 'releases')
            # The released tree: an older lib.sh, no checker, a stale record set.
            (root / 'deploy').mkdir(parents=True)
            (root / 'deploy/deploy.sh').write_text('#!/bin/sh\n# released\n')
            (root / 'deploy/lib.sh').write_text('env_get() { :; }\n')
            (root / 'releases').mkdir()
            (root / 'releases/v0.0.1.json').write_text('{}')
            hashes = install(source, root)
            for rel in runtime_smoke.UNDER_TEST:
                self.assertEqual((root / rel).read_bytes(), (ROOT / rel).read_bytes(), rel)
                self.assertIn(rel, hashes)
            self.assertFalse((root / 'releases/v0.0.1.json').exists(), 'stale records were merged, not replaced')
            self.assertEqual((root / 'releases/v0.6.4.json').read_bytes(), (ROOT / 'releases/v0.6.4.json').read_bytes())
            self.assertIn('releases/v0.6.4.json', hashes)
            defined = subprocess.run(['bash', '-c', 'log() { :; }; . deploy/lib.sh; declare -F release_mapping_check'],
                                     cwd=root, capture_output=True, text=True)
            self.assertEqual(defined.returncode, 0, defined.stderr)

    def test_the_under_test_set_covers_what_deploy_sh_loads(self):
        self.installer()
        deploy = (ROOT / 'deploy/deploy.sh').read_text()
        lib = (ROOT / 'deploy/lib.sh').read_text()
        self.assertIn('deploy/lib.sh', deploy)
        self.assertIn('deploy/release-mapping.py', lib)
        for rel in ('deploy/deploy.sh', 'deploy/lib.sh', 'deploy/release-mapping.py'):
            self.assertIn(rel, runtime_smoke.UNDER_TEST)

    def test_the_launcher_transfers_the_same_set(self):
        self.installer()
        launcher = (ROOT / 'tests/runtime-smoke.sh').read_text()
        match = re.search(r'^under_test=\(([^)]*)\)$', launcher, re.MULTILINE)
        self.assertIsNotNone(match, 'runtime-smoke.sh no longer declares under_test=(...)')
        self.assertEqual(tuple(match.group(1).split()), runtime_smoke.UNDER_TEST)
        self.assertIn('"$ROOT"/releases/*.json', launcher)
        self.assertIn('$STAGE/under-test/$file', launcher)
