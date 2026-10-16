"""Public verdict export must preserve proof scope and reject private input."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
RECORD, TOOL = 'a' * 40, 'b' * 40
PHASES = 'install data fp backup inject upgrade-fail recover backup2 rollback restore-refuse repin restore-ok split report'.split()


def rec03():
    phases = {}
    for phase in PHASES:
        item = {'status': 'PASS', 'media_fingerprint_verified': phase in
                ('data', 'fp', 'upgrade-fail', 'recover', 'rollback', 'restore-ok')}
        if phase not in ('backup', 'backup2', 'split', 'report'):
            item['ledger'] = ('core=151:false' if phase in ('install', 'data', 'fp', 'inject') else
                              'core=152:true' if phase == 'upgrade-fail' else 'core=182:false') + ' search=18:false'
        phases[phase] = item
    return dict(status='PASS', pair=['v0.7.7', 'v0.7.8'], phases=phases,
                record_commit=RECORD, installer_commit=TOOL)


def sealed(restore=False):
    result = dict(status='PASS', scope='published-image synthetic cross-VM sealed-secret subset',
                  synthetic_only=True, phase='complete', external_delivery_blocked=True,
                  release='v0.7.8', record_commit=RECORD, tool_commit=TOOL, core_schema=182, search_schema=18)
    if restore:
        result.update({key: True for key in ('different_runner_boot', 'empty_destination', 'backup_hash_match',
            'schema_and_catalogue_match', 'wrong_key_refused', 'mfa_wrong_code_refused', 'mfa_correct_code_accepted', 'oidc_disabled')})
        result.update(mail_secret_status='ok', oidc_secret_status='ok')
    return result


class RuntimeVerdictExportTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root, self.serial = Path(temporary.name), 0

    def run_export(self, kind='rec03', source=None, replacement=None, job='success', replacement_job='success', extra=()):
        self.serial += 1
        out = self.root / f'payload-{self.serial}.json'
        args = [sys.executable, str(ROOT / 'scripts/ci/export-runtime-verdict.py'), '--kind', kind,
                '--source-result', job, '--record-commit', RECORD, '--tool-commit', TOOL,
                '--run-id', '123', '--run-attempt', '2', '--repository', 'yegamble/vidra', '--out', str(out)]
        args += extra
        for role, value in (('source', source), ('replacement', replacement)):
            if value is not None:
                path = self.root / f'{role}-{self.serial}.json'
                path.write_bytes(value if isinstance(value, bytes) else (json.dumps(value, indent=2) + '\n').encode())
                args += ['--' + role, str(path)]
        if kind == 'sealed':
            args += ['--release', 'v0.7.8', '--replacement-result', replacement_job]
        process = subprocess.run(args, capture_output=True, text=True)
        payload = json.loads(out.read_text()) if out.exists() else None
        return process, payload

    def summary(self, payload):
        return json.loads(re.search(r'```(?:json)?\s*\n(.*?)\n```', payload['output']['summary'], re.S)[1])

    def rejected(self, result):
        process, payload = result
        self.assertEqual(process.returncode, 1)
        self.assertEqual(process.stderr.strip(), 'runtime verdict rejected')
        self.assertIsNone(payload)
        self.assertNotIn('PRIVATE_CANARY', process.stdout + process.stderr)

    def not_pass(self, result):
        process, payload = result
        if payload is None:
            self.assertEqual(process.returncode, 1)
        else:
            self.assertNotEqual(self.summary(payload)['status'], 'PASS')
            self.assertEqual(payload['conclusion'], 'neutral')

    def test_valid_public_payloads_and_raw_byte_hash(self):
        for kind, source, replacement in (('rec03', rec03(), None), ('sealed', sealed(), sealed(True))):
            with self.subTest(kind=kind):
                raw = (json.dumps(source, indent=4) + '\n\n').encode()
                process, payload = self.run_export(kind, raw, replacement)
                self.assertEqual(process.returncode, 0, process.stderr)
                self.assertEqual(payload['name'], f'runtime-verdict/{kind}/123/2')
                self.assertEqual((payload['head_sha'], payload['status'], payload['conclusion']), (TOOL, 'completed', 'neutral'))
                self.assertEqual(payload['details_url'], 'https://github.com/yegamble/vidra/actions/runs/123/attempts/2')
                self.assertIn(RECORD, payload['external_id'])
                summary = self.summary(payload)
                self.assertEqual(summary['status'], 'PASS')
                self.assertEqual(summary['context'], dict(record_commit=RECORD, tool_commit=TOOL, run_id=123,
                    run_attempt=2, repository='yegamble/vidra', **({'release': 'v0.7.8'} if kind == 'sealed' else {})))
                self.assertEqual(summary['roles']['source']['sha256'], hashlib.sha256(raw).hexdigest())
                self.assertEqual(summary['roles']['source']['job_result'], 'success')
        failed = dict(status='FAIL', pair=['v0.7.7', 'v0.7.8'], phases={}, failed_phase='preflight', failure='immutable commits required')
        partial = dict(status='FAIL', scope=sealed()['scope'], synthetic_only=True, phase='preconditions')
        for result in (self.run_export(source=failed), self.run_export('sealed', partial, partial)):
            self.assertEqual(result[0].returncode, 0, result[0].stderr)
            self.assertEqual((self.summary(result[1])['status'], result[1]['conclusion']), ('FAIL', 'neutral'))

    def test_missing_or_failed_job_never_passes(self):
        for job in ('failure', 'cancelled', 'skipped'):
            self.not_pass(self.run_export(source=rec03(), job=job))
            self.not_pass(self.run_export('sealed', sealed(), sealed(True), replacement_job=job))
        for result, missing in ((self.run_export(), 'source'), (self.run_export('sealed', sealed()), 'replacement')):
            process, payload = result
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertEqual((self.summary(payload)['status'], self.summary(payload)['missing']), ('INCOMPLETE', [missing]))

    def test_incomplete_proof_never_passes(self):
        source, replacement = rec03(), sealed(True)
        del source['phases']['recover']
        del replacement['wrong_key_refused']
        for result, role in ((self.run_export(source=source), 'source'),
                             (self.run_export('sealed', sealed(), replacement), 'replacement')):
            self.not_pass(result)
            if result[1]:
                self.assertNotEqual(self.summary(result[1])['roles'][role]['verdict']['status'], 'PASS')

    def test_untrusted_fields_context_types_and_oversize_are_rejected(self):
        for base, key, value in ((rec03(), 'private', 'PRIVATE_CANARY'),
                (dict(rec03(), status='FAIL'), 'failure', 'PRIVATE_CANARY'),
                (rec03(), 'record_commit', 'c' * 40), (rec03(), 'installer_commit', 'c' * 40),
                (sealed(), 'core_schema', 151), (sealed(), 'core_schema', True),
                (sealed(), 'synthetic_only', 1), (sealed(), 'different_runner_boot', True)):
            with self.subTest(key=key, value=value):
                base[key] = value
                kind = 'sealed' if 'scope' in base else 'rec03'
                self.rejected(self.run_export(kind, base, sealed(True) if kind == 'sealed' else None))
        for raw in (b' ' * (2 * 1024 * 1024), b'{"status":"PASS","status":"PRIVATE_CANARY"}', b'PRIVATE_CANARY'):
            self.rejected(self.run_export(source=raw))
        for field, value in (('ledger', 'core=151:false search=18:false'), ('media_fingerprint_verified', 1)):
            source = rec03()
            source['phases']['recover'][field] = value
            self.rejected(self.run_export(source=source))
        for flag in ('--repository', '--tool-commit', '--run-id', '--kind'):
            self.rejected(self.run_export(source=rec03(), extra=(flag, 'PRIVATE_CANARY')))


if __name__ == '__main__':
    unittest.main()
