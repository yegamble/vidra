"""Cross-job provenance and sanitized failure regressions; no VM execution."""
import importlib.util
import io
import json
from contextlib import contextmanager, redirect_stdout
from types import SimpleNamespace
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / 'tests/hosted-sealed-recovery.py'
spec = importlib.util.spec_from_file_location('hosted_sealed', TOOL)
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)


class CrossJobBoundaryTest(unittest.TestCase):
    def test_unchanged_restore_command_is_inside_relay_and_failure_propagates(self):
        events = []
        @contextmanager
        def relay(host):
            events.append('enter')
            try:
                yield
            finally:
                events.append('exit')
        host = Mock()
        def run(command, label, *, timeout):
            self.assertEqual(events, ['enter'])
            self.assertEqual(command, ['bash', 'deploy/restore.sh', '--yes', '/synthetic/backup.dump.gz'])
            self.assertEqual((label, timeout), ('published-restore', 1800))
            events.append('command')
            raise ValueError('synthetic command failure')
        host.run.side_effect = run
        with patch.object(driver, 'readiness_relay', side_effect=relay), self.assertRaises(ValueError):
            driver.restore_dump(host, Path('/synthetic/backup.dump.gz'))
        self.assertEqual(events, ['enter', 'command', 'exit'])

    def test_source_operation_failures_keep_their_fixed_milestone(self):
        for milestone, method in (('migrations', 'compose'), ('start-services', 'compose'), ('ready', 'ready'),
                                  ('owner-claim', 'sql'), ('api-fixture', 'api_fixture'), ('snapshot', 'snapshot')):
            with self.subTest(milestone=milestone), tempfile.TemporaryDirectory() as temporary:
                args = SimpleNamespace(tool_commit='a' * 40, record_commit='b' * 40, release='v0.7.8',
                    record_root=ROOT, stage=Path(temporary) / 'stage', action='source')
                result, hosts = {}, []
                host = Mock(private=args.stage / 'private')
                host.run.return_value = ''
                def observe(*command):
                    if result.get('phase') == milestone:
                        raise ValueError('PRIVATE_CANARY')
                    if command and command[0] == 'logs':
                        return '403 owner_claim_required until claimed): synthetic-token'
                    return ''
                host.compose.side_effect = observe
                host.sql.return_value = '0'
                if method != 'compose':
                    getattr(host, method).side_effect = observe
                record = {'core_schema_version': 182, 'search_schema_version': 18}
                with patch.object(driver.support, 'head', return_value=args.tool_commit), \
                        patch.object(driver.support, 'published', return_value=(record, {})), \
                        patch.object(driver.support, 'check_vm'), patch.object(driver.runtime, 'host_facts'), \
                        patch.object(driver, 'Host', return_value=host), patch.object(driver, 'no_smtp_listener'):
                    with self.assertRaises(ValueError):
                        driver.execute(args, result, hosts)
                self.assertEqual(result['phase'], milestone)
                self.assertEqual(hosts, [host])

    def test_pass_does_not_collect_failure_diagnostics(self):
        host, output = Mock(), io.StringIO()
        def execute(args, result, hosts):
            hosts.append(host)
            result.update(status='PASS', phase='complete')
        with tempfile.TemporaryDirectory() as temporary:
            argv = [str(TOOL), 'source', '--release', 'v0.7.8', '--record-commit', 'a' * 40,
                    '--tool-commit', 'b' * 40, '--record-root', str(ROOT), '--stage', temporary]
            with patch.object(sys, 'argv', argv), patch.object(driver, 'execute', side_effect=execute), redirect_stdout(output):
                self.assertEqual(driver.main(), 0)
        host.failure_diagnostics.assert_not_called()
        self.assertNotIn('diagnostics', json.loads(output.getvalue()))

    def test_failure_diagnostics_cannot_mask_failure_or_expose_exception_text(self):
        with tempfile.TemporaryDirectory() as temporary:
            for fails in (False, True):
                stage = Path(temporary) / str(fails)
                host = Mock()
                host.failure_diagnostics.return_value = {'readyz_status': 0, 'services': {'api': 'restarting'}}
                if fails:
                    host.failure_diagnostics.side_effect = ValueError('PRIVATE_CANARY')
                def execute(args, result, hosts):
                    args.stage.mkdir()
                    (args.stage / 'private').mkdir()
                    hosts.append(host)
                    result['phase'] = 'ready'
                    raise ValueError('PRIVATE_CANARY')
                output = io.StringIO()
                argv = [str(TOOL), 'source', '--release', 'v0.7.8', '--record-commit', 'a' * 40,
                        '--tool-commit', 'b' * 40, '--record-root', str(ROOT), '--stage', str(stage)]
                with patch.object(sys, 'argv', argv), patch.object(driver, 'execute', side_effect=execute), redirect_stdout(output):
                    self.assertEqual(driver.main(), 1)
                verdict = json.loads(output.getvalue())
                self.assertEqual((verdict['status'], verdict['phase']), ('FAIL', 'ready'))
                self.assertEqual('diagnostics' in verdict, not fails)
                self.assertEqual(json.loads((stage / 'verdict.json').read_text()), verdict)
                self.assertNotIn('PRIVATE_CANARY', output.getvalue())

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
