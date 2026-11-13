"""Public verdict export must hold a verdict to the release records, preserve proof scope and reject private input."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import rec03_pair
import rec03_pair_cases as cases

ROOT = Path(__file__).resolve().parents[1]
TOOL = 'b' * 40
PHASES = 'install data fp backup inject upgrade-fail recover backup2 rollback restore-refuse repin restore-ok split report'.split()
# Typed by hand from releases/v0.7.8.json and releases/v0.7.20.json.
SEALED_SCHEMAS = {'v0.7.8': (182, 18), 'v0.7.20': (189, 21)}
FIRST = cases.CASES[0]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


release_pair = load('release_pair', 'scripts/ci/release-pair.py')
runner = load('export_test_runner', 'tests/rec03-runner.py')


def setUpModule():
    """A checkout holding the real records at one commit, as the report job's record checkout is."""
    global CHECKOUT, REPO, RECORD
    CHECKOUT = tempfile.TemporaryDirectory()
    REPO = Path(CHECKOUT.name).resolve() / 'record'
    shutil.copytree(ROOT / 'releases', REPO / 'releases')
    git = ['git', '-C', str(REPO), '-c', 'user.name=test', '-c', 'user.email=test@example.invalid',
           '-c', 'commit.gpgsign=false']
    for command in (['init', '-q'], ['add', 'releases'], ['commit', '-q', '-m', 'records']):
        subprocess.run(git + command, check=True, capture_output=True)
    RECORD = subprocess.check_output(git + ['rev-parse', 'HEAD'], text=True).strip()


def tearDownModule():
    CHECKOUT.cleanup()


def rec03(case=FIRST):
    phases = {}
    for phase in PHASES:
        item = {'status': 'PASS', 'media_fingerprint_verified': phase in
                ('data', 'fp', 'upgrade-fail', 'recover', 'rollback', 'restore-ok')}
        if phase not in ('backup', 'backup2', 'split', 'report'):
            item['ledger'] = (case.ledger_old if phase in ('install', 'data', 'fp', 'inject') else
                              case.ledger_failed if phase == 'upgrade-fail' else case.ledger_new)
        phases[phase] = item
    return dict(status='PASS', pair=[case.old, case.new], phases=phases,
                record_commit=RECORD, installer_commit=TOOL)


def sealed(restore=False, release='v0.7.20'):
    core, search = SEALED_SCHEMAS[release]
    result = dict(status='PASS', scope='published-image synthetic cross-VM sealed-secret subset',
                  synthetic_only=True, phase='complete', external_delivery_blocked=True,
                  release=release, record_commit=RECORD, tool_commit=TOOL, core_schema=core, search_schema=search)
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

    def run_export(self, kind='rec03', source=None, replacement=None, job='success', replacement_job='success', extra=(),
                   release=None, previous=None):
        self.serial += 1
        out = self.root / f'payload-{self.serial}.json'
        if release is None:
            release = 'v0.7.20' if kind == 'sealed' else FIRST.new
        args = [sys.executable, str(ROOT / 'scripts/ci/export-runtime-verdict.py'), '--kind', kind,
                '--source-result', job, '--record-commit', RECORD, '--tool-commit', TOOL, '--record-root', str(REPO),
                '--run-id', '123', '--run-attempt', '2', '--repository', 'yegamble/vidra', '--out', str(out),
                '--release', release]
        if previous:
            args += ['--previous', previous]
        for role, value in (('source', source), ('replacement', replacement)):
            if value is not None:
                path = self.root / f'{role}-{self.serial}.json'
                path.write_bytes(value if isinstance(value, bytes) else (json.dumps(value, indent=2) + '\n').encode())
                args += ['--' + role, str(path)]
        if kind == 'sealed':
            args += ['--replacement-result', replacement_job]
        args += extra
        process = subprocess.run(args, capture_output=True, text=True)
        payload = json.loads(out.read_text()) if out.exists() else None
        return process, payload

    def export_case(self, case, source, **options):
        return self.run_export(source=source, release=case.new, previous=case.explicit_previous, **options)

    def summary(self, payload):
        return json.loads(re.search(r'```(?:json)?\s*\n(.*?)\n```', payload['output']['summary'], re.S)[1])

    def rejected(self, result):
        process, payload = result
        self.assertEqual(process.returncode, 1)
        self.assertEqual(process.stderr.strip(), 'runtime verdict rejected')
        self.assertIsNone(payload)
        self.assertNotIn('PRIVATE_CANARY', process.stdout + process.stderr)

    def published(self, result, status):
        process, payload = result
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual((self.summary(payload)['status'], payload['conclusion']), (status, 'neutral'))
        return self.summary(payload)

    def not_pass(self, result):
        process, payload = result
        if payload is None:
            self.assertEqual(process.returncode, 1)
        else:
            self.assertNotEqual(self.summary(payload)['status'], 'PASS')
            self.assertEqual(payload['conclusion'], 'neutral')

    def test_valid_public_payloads_and_raw_byte_hash(self):
        runs = [('rec03', rec03(case), None, case.new, case.explicit_previous) for case in cases.CASES]
        runs += [('sealed', sealed(release=release), sealed(True, release), release, '') for release in SEALED_SCHEMAS]
        for kind, source, replacement, release, previous in runs:
            with self.subTest(kind=kind, release=release, previous=previous):
                raw = (json.dumps(source, indent=4) + '\n\n').encode()
                process, payload = self.run_export(kind, raw, replacement, release=release, previous=previous)
                self.assertEqual(process.returncode, 0, process.stderr)
                self.assertEqual(payload['name'], f'runtime-verdict/{kind}/123/2')
                self.assertEqual((payload['head_sha'], payload['status'], payload['conclusion']), (TOOL, 'completed', 'neutral'))
                self.assertEqual(payload['details_url'], 'https://github.com/yegamble/vidra/actions/runs/123/attempts/2')
                self.assertIn(RECORD, payload['external_id'])
                summary = self.summary(payload)
                self.assertEqual(summary['status'], 'PASS')
                self.assertEqual(summary['context'], dict(record_commit=RECORD, tool_commit=TOOL, run_id=123,
                    run_attempt=2, repository='yegamble/vidra', release=release, **({'previous': previous} if previous else {})))
                self.assertEqual(summary['roles']['source']['sha256'], hashlib.sha256(raw).hexdigest())
                self.assertEqual(summary['roles']['source']['job_result'], 'success')
        failed = dict(status='FAIL', pair=[FIRST.old, FIRST.new], phases={}, failed_phase='preflight', failure='existing deployment refused')
        partial = dict(status='FAIL', scope=sealed()['scope'], synthetic_only=True, phase='preconditions')
        for result in (self.run_export(source=failed), self.run_export('sealed', partial, partial)):
            self.published(result, 'FAIL')

    def test_a_verdict_for_one_pair_is_rejected_under_another(self):
        for case in cases.CASES:
            for other in cases.others(case):
                with self.subTest(verdict=case.name, exported_as=other.name):
                    self.rejected(self.export_case(other, rec03(case)))
                    # The right label over another pair's ledgers is no better.
                    self.rejected(self.export_case(other, dict(rec03(case), pair=[other.old, other.new])))
                    failed = dict(status='FAIL', pair=[case.old, case.new], phases={}, failed_phase='install')
                    self.rejected(self.export_case(other, failed))
        self.rejected(self.run_export(source=rec03(), previous='v0.7.5'))
        self.rejected(self.run_export(source=dict(rec03(), pair=[FIRST.new, FIRST.old])))
        self.rejected(self.run_export(source=dict(rec03(), pair=[FIRST.new])))
        self.rejected(self.run_export(source=dict(rec03(), pair=FIRST.old + ' ' + FIRST.new)))

    def test_a_sealed_verdict_is_held_to_its_own_releases_recorded_schemas(self):
        for release in SEALED_SCHEMAS:
            other, = set(SEALED_SCHEMAS) - {release}
            with self.subTest(release=release):
                self.rejected(self.run_export('sealed', sealed(release=release), sealed(True, release), release=other))
                for field, index in (('core_schema', 0), ('search_schema', 1)):
                    wrong = dict(sealed(release=release), **{field: SEALED_SCHEMAS[other][index]})
                    self.rejected(self.run_export('sealed', wrong, sealed(True, release), release=release))
        self.rejected(self.run_export('sealed', sealed(), sealed(True), previous='v0.7.19'))

    def test_a_sealed_verdict_for_an_unrecorded_release_may_fail_but_states_no_schema(self):
        partial = dict(status='FAIL', scope=sealed()['scope'], synthetic_only=True, phase='preconditions')
        self.published(self.run_export('sealed', partial, partial, job='failure', release='v0.7.10'), 'FAIL')
        for field in ('core_schema', 'search_schema'):
            self.rejected(self.run_export('sealed', dict(partial, **{field: 189}), partial, release='v0.7.10'))

    def test_an_unnamed_pair_is_only_ever_a_preflight_failure(self):
        unnamed = dict(status='FAIL', pair=[], phases={}, failed_phase='preflight', failure='immutable commits required',
                       diagnostics={})
        for release, previous in ((FIRST.new, ''), ('v0.7.10', ''), ('v0.7.20', 'v0.7.10'), ('v0.6.4', '')):
            with self.subTest(release=release, previous=previous):
                summary = self.published(self.run_export(source=unnamed, job='failure', release=release, previous=previous), 'FAIL')
                self.assertEqual(summary['roles']['source']['verdict']['pair'], [])
        for change in ({'status': 'PASS'}, {'failed_phase': 'install'}, {'phases': rec03()['phases']},
                       {'phases': {'install': rec03()['phases']['install']}}):
            with self.subTest(change=change):
                self.rejected(self.run_export(source={**unnamed, **change}, job='failure'))
        del unnamed['failed_phase']
        self.rejected(self.run_export(source=unnamed, job='failure'))
        # Records that name no pair cannot vouch for one the verdict states.
        named = dict(status='FAIL', pair=['v0.7.9', 'v0.7.10'], phases={}, failed_phase='preflight')
        self.rejected(self.run_export(source=named, job='failure', release='v0.7.10'))

    def test_a_pair_with_no_core_migration_is_published_as_fail_and_can_never_pass(self):
        refused = dict(status='FAIL', pair=['v0.7.9', 'v0.7.11'], phases={}, failed_phase='preflight',
                       failure='pair carries no core migration', diagnostics={})
        summary = self.published(self.run_export(source=refused, job='failure', release='v0.7.11'), 'FAIL')
        self.assertEqual(summary['roles']['source']['verdict'], refused)
        flat = dict(rec03(), pair=['v0.7.9', 'v0.7.11'])
        for phase, item in flat['phases'].items():
            if 'ledger' in item:
                item['ledger'] = 'core=189:true search=21:false' if phase == 'upgrade-fail' else 'core=188:false search=21:false'
        self.rejected(self.run_export(source=flat, release='v0.7.11'))
        self.rejected(self.run_export(source=dict(flat, status='FAIL', failed_phase='report'), release='v0.7.11'))

    def test_every_fixed_refusal_reason_is_publishable_and_nothing_else_is(self):
        for reason in (*release_pair.REASONS, *rec03_pair.REASONS, 'record checkout differs',
                       'first pending migration too large', 'disposable hosted runner required'):
            with self.subTest(reason=reason):
                failed = dict(status='FAIL', pair=[], phases={}, failed_phase='preflight', failure=reason)
                summary = self.published(self.run_export(source=failed, job='failure'), 'FAIL')
                self.assertEqual(summary['roles']['source']['verdict']['failure'], reason)
        for reason in ('PRIVATE_CANARY', 'candidate schema mismatch', 'pair carries no core migration ', ''):
            with self.subTest(reason=reason):
                self.rejected(self.run_export(source=dict(status='FAIL', pair=[], phases={}, failed_phase='preflight',
                                                          failure=reason), job='failure'))

    def test_the_runners_own_preflight_refusals_are_published_as_fail(self):
        for env, pair, reason in (
                ({'REC03_RELEASE': 'v0.7.11'}, ['v0.7.9', 'v0.7.11'], 'pair carries no core migration'),
                ({'REC03_RELEASE': 'v0.7.7'}, ['v0.7.5', 'v0.7.7'], 'release record does not list the first pending migration'),
                ({'REC03_RELEASE': 'v0.7.10'}, [], 'release is not a recorded release'),
                ({'REC03_RELEASE': 'v0.6.4'}, [], 'release has no previous record'),
                ({'REC03_RELEASE': 'v0.7.20', 'REC03_PREVIOUS': 'v0.7.10'}, [], 'previous release is not a recorded release'),
                ({'REC03_RELEASE': 'v0.7.20', 'REC03_RECORD_REF': 'c' * 40}, [], 'record checkout differs')):
            with self.subTest(env=env):
                env = {'REC03_RECORD_REF': RECORD, 'REC03_INSTALLER_REF': TOOL, 'REC03_RECORD_ROOT': str(REPO),
                       'RUNNER_ENVIRONMENT': 'github-hosted', 'PATH': os.environ['PATH'], **env}
                out = self.root / f'runner-{self.serial}'
                with patch.dict(os.environ, env, clear=True), patch.object(runner.os, 'geteuid', return_value=0), \
                        patch.object(runner.os, 'cpu_count', return_value=4), \
                        patch.object(runner.urllib.request, 'urlopen', side_effect=AssertionError('no fetch')), \
                        patch('builtins.print'):
                    self.assertEqual(runner.main(out), 1)
                verdict = json.loads((out / 'summary.json').read_text())
                self.assertEqual((verdict['pair'], verdict['failure']), (pair, reason))
                result = self.run_export(source=(out / 'summary.json').read_bytes(), job='failure', release=env['REC03_RELEASE'],
                                         previous=env.get('REC03_PREVIOUS', ''))
                self.assertEqual(self.published(result, 'FAIL')['roles']['source']['verdict'], verdict)

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
                (sealed(), 'core_schema', 182), (sealed(), 'core_schema', True), (sealed(), 'core_schema', '189'),
                (sealed(), 'release', 'v0.7.8'),
                (sealed(), 'synthetic_only', 1), (sealed(), 'different_runner_boot', True)):
            with self.subTest(key=key, value=value):
                base[key] = value
                kind = 'sealed' if 'scope' in base else 'rec03'
                self.rejected(self.run_export(kind, base, sealed(True) if kind == 'sealed' else None))
        for raw in (b' ' * (2 * 1024 * 1024), b'{"status":"PASS","status":"PRIVATE_CANARY"}', b'PRIVATE_CANARY'):
            self.rejected(self.run_export(source=raw))
        for field, value in (('ledger', FIRST.ledger_old), ('ledger', FIRST.ledger_failed), ('media_fingerprint_verified', 1)):
            source = rec03()
            source['phases']['recover'][field] = value
            self.rejected(self.run_export(source=source))
        for flag in ('--repository', '--tool-commit', '--run-id', '--kind', '--release', '--previous', '--record-root',
                     '--record-commit'):
            with self.subTest(flag=flag):
                self.rejected(self.run_export(source=rec03(), extra=(flag, 'PRIVATE_CANARY')))

    def test_the_record_checkout_must_be_the_record_commit_and_the_release_a_tag(self):
        self.rejected(self.run_export(source=dict(rec03(), record_commit='c' * 40), extra=('--record-commit', 'c' * 40)))
        self.rejected(self.run_export(source=rec03(), extra=('--record-root', 'releases')))
        self.rejected(self.run_export(source=rec03(), extra=('--record-root', str(self.root))))
        for release in ('v0.07.8', 'latest', '', 'v0.7.8\n'):
            with self.subTest(release=release):
                self.rejected(self.run_export(source=rec03(), extra=('--release', release)))
                self.rejected(self.run_export(source=rec03(), extra=('--previous', release or 'v0.7')))

    def test_failure_diagnostics_are_bounded_public_facts_and_never_a_pass(self):
        failed = dict(status='FAIL', pair=[FIRST.old, FIRST.new], phases={}, failed_phase='install',
                      failure='driver phase failed', record_commit=RECORD, installer_commit=TOOL)
        for diagnostic in ({}, {'install_steps': {}, 'running_services': [], 'probe_statuses': {}},
                {'probe_statuses': {'site': 0}},
                {'install_steps': {'installer': 0, 'setup': 0, 'setup_check': 0, 'provision': 0, 'deploy': 255},
                 'running_services': ['api', 'frontend', 'search', 'postgres', 'redis', 'worker', 'caddy',
                                      'clamav', 'migrate', 'search-migrate', 'prep-volumes'],
                 'probe_statuses': {'instance': 100, 'healthz': 200, 'site': 599, 'watch': 404}}):
            with self.subTest(diagnostic=diagnostic):
                process, payload = self.run_export(source={**failed, 'diagnostics': diagnostic}, job='failure')
                self.assertEqual(process.returncode, 0, process.stderr)
                summary = self.summary(payload)
                self.assertEqual((summary['status'], payload['conclusion']), ('FAIL', 'neutral'))
                self.assertEqual(summary['roles']['source']['verdict']['diagnostics'], diagnostic)
        for diagnostic in ({}, {'install_steps': {'deploy': 1}}):
            self.rejected(self.run_export(source={**rec03(), 'diagnostics': diagnostic}))
        self.rejected(self.run_export('sealed', {**sealed(), 'diagnostics': {}}, sealed(True)))

    def test_private_malformed_and_nonfinite_diagnostics_are_rejected(self):
        failed = dict(status='FAIL', pair=[FIRST.old, FIRST.new], phases={}, failed_phase='install')
        self.published(self.run_export(source=failed, job='failure'), 'FAIL')
        invalid = [None, [], 'PRIVATE_CANARY', {'PRIVATE_CANARY': 1},
                   {'install_steps': []}, {'install_steps': {'PRIVATE_CANARY': 1}},
                   {'probe_statuses': []}, {'probe_statuses': {'PRIVATE_CANARY': 200}},
                   {'running_services': 'api'}, {'running_services': ['api', 'api']},
                   {'running_services': ['PRIVATE_CANARY']}, {'running_services': [{}]},
                   {'running_services': [True]}, {'running_services': ['api'] * 12}]
        for field, name, numbers in (('install_steps', 'deploy', [-1, 256, True, 0.0, '0', {},
                                      float('nan'), float('inf'), float('-inf')]),
                                    ('probe_statuses', 'healthz', [1, 99, 600, False, 0.0, 200.0, '200', [],
                                      float('nan'), float('inf'), float('-inf')])):
            invalid.extend({field: {name: number}} for number in numbers)
        for diagnostic in invalid:
            with self.subTest(diagnostic=diagnostic):
                self.rejected(self.run_export(source={**failed, 'diagnostics': diagnostic}))

    def test_sealed_failure_milestones_and_diagnostics_preserve_failure(self):
        roles = {'source': 'migrations start-services ready owner-claim api-fixture snapshot'.split(),
                 'replacement': ('restore-infrastructure restore-relay restore restore-ready restore-snapshot restore-verify wrong-key-start wrong-key-ready '
                                 'wrong-key-verify original-key-start original-key-ready original-key-verify').split()}
        for role, phases in roles.items():
            for phase in phases:
                with self.subTest(role=role, phase=phase):
                    failed = dict(status='FAIL', scope=sealed()['scope'], synthetic_only=True, phase=phase,
                                  diagnostics={'readyz_status': 0, 'services': {'api': 'restarting', 'frontend': 'unhealthy'}})
                    source, replacement = (failed, sealed(True)) if role == 'source' else (sealed(), failed)
                    process, payload = self.run_export('sealed', source, replacement,
                        job='failure' if role == 'source' else 'success', replacement_job='failure')
                    self.assertEqual(process.returncode, 0, process.stderr)
                    self.assertEqual(self.summary(payload)['status'], 'FAIL')
                    self.assertEqual(self.summary(payload)['roles'][role]['verdict'], failed)

    def test_sealed_diagnostics_reject_private_nonfinite_or_pass_values(self):
        failed = dict(status='FAIL', scope=sealed()['scope'], synthetic_only=True, phase='ready')
        for diagnostic in ({}, None, {'services': {}}, {'services': {'worker': 'running'}},
                {'services': {'api': 'PRIVATE_CANARY'}}, {'services': {'api': True}},
                {'services': {'api': []}}, {'PRIVATE_CANARY': 200}, {'readyz_status': True},
                {'readyz_status': 200.0}, {'readyz_status': '200'}, {'readyz_status': float('nan')},
                {'readyz_status': float('inf')}, {'readyz_status': 99}, {'readyz_status': 600}):
            with self.subTest(diagnostic=diagnostic):
                self.rejected(self.run_export('sealed', {**failed, 'diagnostics': diagnostic}, sealed(True)))
        self.rejected(self.run_export('sealed', {**sealed(), 'diagnostics': {'readyz_status': 200}}, sealed(True)))
        self.rejected(self.run_export('sealed', {**failed, 'phase': 'PRIVATE_CANARY'}, sealed(True)))
        self.rejected(self.run_export('sealed', {**failed, 'phase': 'wrong-key-ready'}, sealed(True)))
        for phase in ('restore-infrastructure', 'restore-relay'):
            self.rejected(self.run_export('sealed', {**failed, 'phase': phase}, sealed(True)))


if __name__ == '__main__':
    unittest.main()
