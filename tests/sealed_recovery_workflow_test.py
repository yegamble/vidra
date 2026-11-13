"""Dispatch scope, VM separation and artifact boundaries in the actual workflow."""
import importlib.util
from pathlib import Path
import re
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ('rec03.yml', 'release-runtime-qualification.yml', 'runtime-verdict-report.yml', 'sealed-recovery.yml')
spec = importlib.util.spec_from_file_location('release_pair', ROOT / 'scripts/ci/release-pair.py')
release_pair = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release_pair)


def workflow(name):
    loaded = yaml.safe_load((ROOT / '.github/workflows' / name).read_text())
    return loaded, loaded.get('on', loaded.get(True))


class SealedWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.workflow = yaml.safe_load((ROOT / '.github/workflows/sealed-recovery.yml').read_text())
        self.jobs = self.workflow['jobs']

    def test_dispatch_or_explicit_call_runs_two_distinct_hosted_jobs(self):
        events = self.workflow.get('on', self.workflow.get(True))
        self.assertEqual(set(events), {'workflow_dispatch', 'workflow_call'})
        self.assertEqual(set(self.jobs), {'source', 'replacement', 'report'})
        self.assertEqual(self.jobs['replacement']['needs'], 'source')
        for job in (self.jobs['source'], self.jobs['replacement']):
            self.assertEqual(job['runs-on'], 'ubuntu-24.04')
            self.assertNotIn('container', job)
            self.assertNotIn('services', job)
        self.assertFalse(self.workflow['concurrency']['cancel-in-progress'])

    def test_callable_drills_keep_dispatch_input_contracts(self):
        for name in ('rec03.yml', 'sealed-recovery.yml'):
            workflow = yaml.safe_load((ROOT / '.github/workflows' / name).read_text())
            events = workflow.get('on', workflow.get(True))
            self.assertEqual(set(events), {'workflow_dispatch', 'workflow_call'})
            expected = {name: {key: value for key, value in field.items()
                        if key != 'default' or not field.get('required')}
                        for name, field in events['workflow_dispatch']['inputs'].items()}
            self.assertEqual(events['workflow_call']['inputs'], expected)
            record = events['workflow_call']['inputs']['record_commit']
            self.assertIs(record['required'], True)
            self.assertEqual(record['type'], 'string')
            self.assertIn('inputs.record_commit', workflow['concurrency']['group'])
            self.assertFalse(workflow['concurrency']['cancel-in-progress'])
            # No release is a default: a dispatch that names none must not drill an old one.
            release = events['workflow_dispatch']['inputs']['release']
            self.assertEqual((release['required'], release['type'], 'default' in release), (True, 'string', False))
            self.assertIn('inputs.release', workflow['concurrency']['group'])

    def test_rec03_takes_the_pair_as_inputs_and_keys_concurrency_on_it(self):
        rec03, events = workflow('rec03.yml')
        self.assertEqual(list(events['workflow_dispatch']['inputs']), ['release', 'previous', 'record_commit'])
        previous = events['workflow_dispatch']['inputs']['previous']
        self.assertEqual((previous['required'], previous['default'], previous['type']), (False, '', 'string'))
        self.assertEqual(rec03['concurrency']['group'],
                         'rec03-release-drill-${{ inputs.release }}-${{ inputs.previous }}-${{ inputs.record_commit }}')
        steps = rec03['jobs']['rec03']['steps']
        checkouts = [s['with'] for s in steps if s.get('uses', '').startswith('actions/checkout@')]
        self.assertEqual(checkouts, [
            {'ref': '${{ github.sha }}', 'persist-credentials': False},
            {'ref': '${{ inputs.record_commit }}', 'path': 'record', 'persist-credentials': False}])
        drill = next(s for s in steps if 'rec03-runner.py' in s.get('run', ''))
        self.assertEqual(drill['env'], {'RELEASE': '${{ inputs.release }}', 'PREVIOUS': '${{ inputs.previous }}',
                                        'RECORD_COMMIT': '${{ inputs.record_commit }}', 'INSTALLER_COMMIT': '${{ github.sha }}'})
        for passed in ('REC03_RELEASE="$RELEASE"', 'REC03_PREVIOUS="$PREVIOUS"', 'REC03_RECORD_REF="$RECORD_COMMIT"',
                       'REC03_RECORD_ROOT="$GITHUB_WORKSPACE/record"', 'REC03_INSTALLER_REF="$INSTALLER_COMMIT"'):
            self.assertIn(passed, drill['run'])

    def test_the_reporter_downloads_the_verdict_rec03_uploads_and_reads_the_record_commit(self):
        rec03, _ = workflow('rec03.yml')
        reporter, events = workflow('runtime-verdict-report.yml')
        upload = next(s['with'] for s in rec03['jobs']['rec03']['steps'] if s.get('uses', '').startswith('actions/upload-artifact@'))
        self.assertEqual(upload['name'], 'rec03-verdict-${{ github.run_id }}-${{ github.run_attempt }}')
        steps = reporter['jobs']['publish']['steps']
        download = next(s['with'] for s in steps if s.get('uses', '').startswith('actions/download-artifact@'))
        expected = upload['name'].replace('${{ github.run_id }}', '{0}').replace('${{ github.run_attempt }}', '{1}')
        self.assertIn(f"inputs.kind == 'rec03' && format('{expected}', github.run_id, github.run_attempt)", download['name'])
        inputs = events['workflow_call']['inputs']
        self.assertEqual(inputs['release'], {'required': True, 'type': 'string'})
        self.assertEqual(inputs['previous'], {'default': '', 'type': 'string'})
        checkouts = [s['with'] for s in steps if s.get('uses', '').startswith('actions/checkout@')]
        self.assertEqual(checkouts, [
            {'ref': '${{ github.sha }}', 'persist-credentials': False},
            {'ref': '${{ inputs.record_commit }}', 'path': 'record', 'persist-credentials': False}])
        publish = steps[-1]
        self.assertEqual((publish['env']['RELEASE'], publish['env']['PREVIOUS']),
                         ('${{ inputs.release }}', '${{ inputs.previous }}'))
        for passed in ('--release "$RELEASE"', '--record-root "$GITHUB_WORKSPACE/record"', '--previous "$PREVIOUS"',
                       '--record-commit "$RECORD_COMMIT"'):
            self.assertIn(passed, publish['run'])

    def test_only_same_repository_release_record_prs_call_runtime_drills(self):
        caller, events = workflow('release-runtime-qualification.yml')
        self.assertEqual(events, {'pull_request': {'paths': ['releases/v*.json']}})
        self.assertEqual(caller['permissions'], {'contents': 'read', 'actions': 'read'})
        self.assertEqual(set(caller['jobs']), {'release', 'rec03', 'sealed'})
        same_repository = 'github.event.pull_request.head.repo.full_name == github.repository'
        for name, filename in (('rec03', 'rec03.yml'), ('sealed', 'sealed-recovery.yml')):
            job = caller['jobs'][name]
            self.assertEqual(job['if'], same_repository)
            self.assertEqual(job['needs'], 'release')
            self.assertEqual(job['uses'], './.github/workflows/' + filename)
            self.assertEqual(job['permissions'], {'contents': 'read', 'actions': 'read', 'checks': 'write'})
            self.assertEqual(job['with'], {'release': '${{ needs.release.outputs.release }}',
                                           'record_commit': '${{ github.event.pull_request.head.sha }}'})
            self.assertNotIn('secrets', job)
            self.assertNotIn('steps', job)
            self.assertNotIn('continue-on-error', job)

    def test_the_release_is_the_one_record_the_pr_adds(self):
        caller, _ = workflow('release-runtime-qualification.yml')
        job = caller['jobs']['release']
        self.assertEqual(job['if'], 'github.event.pull_request.head.repo.full_name == github.repository')
        self.assertEqual(job['runs-on'], 'ubuntu-24.04')
        self.assertNotIn('permissions', job)
        self.assertNotIn('continue-on-error', str(job))
        checkout, added = job['steps']
        # No `ref`: the PR merge commit, whose first parent is the base branch. Depth 2 reaches it.
        self.assertRegex(checkout['uses'], r'^actions/checkout@[0-9a-f]{40}$')
        self.assertEqual(checkout['with'], {'fetch-depth': 2, 'persist-credentials': False})
        self.assertEqual(job['outputs'], {'release': '${{ steps.added.outputs.release }}'})
        self.assertEqual(added['id'], 'added')
        self.assertNotIn('env', added)
        self.assertNotIn('${{', added['run'])
        command = ' '.join(added['run'].replace('\\\n', ' ').split())
        self.assertIn('git diff -z --name-only --diff-filter=A HEAD^1 HEAD -- releases | python3 scripts/ci/release-pair.py '
                      'added --root "$GITHUB_WORKSPACE" --github-output "$GITHUB_OUTPUT"', command)

    def test_the_path_filter_and_the_added_record_count_agree_on_what_a_record_is(self):
        caller, events = workflow('release-runtime-qualification.yml')
        pattern, = events['pull_request']['paths']
        # GitHub's filter: `*` matches any character but `/`.
        triggers = re.compile('[^/]*'.join(map(re.escape, pattern.split('*'))))
        names = ['releases/' + path.name for path in (ROOT / 'releases').iterdir()]
        names += ['releases/vNEXT.json', 'releases/v.json', 'releases/v/x.json', 'releases/old/v0.7.20.json',
                  'docs/releases/v0.7.20.json', 'releases/v0.7.20.json.bak', 'releases/0.7.20.json', 'releases/V0.7.20.json']
        self.assertIn('releases/README.md', names)
        for name in names:
            with self.subTest(name=name):
                self.assertEqual(release_pair.ADDED.fullmatch(name) is not None, triggers.fullmatch(name) is not None)
        # deploy/release.sh adds releases/<tag>.json: every record it has written triggers the drills.
        self.assertIn('"releases/${TAG}.json"', (ROOT / 'deploy/release.sh').read_text())
        for path in (ROOT / 'releases').glob('v*.json'):
            self.assertIsNotNone(triggers.fullmatch('releases/' + path.name))

    def test_every_input_a_caller_passes_is_declared_and_every_required_one_is_passed(self):
        calls = 0
        for name in WORKFLOWS:
            for job_name, job in workflow(name)[0]['jobs'].items():
                if 'uses' not in job:
                    continue
                calls += 1
                self.assertRegex(job['uses'], r'^\./\.github/workflows/[a-z0-9-]+\.yml$')
                declared = workflow(job['uses'].rsplit('/', 1)[1])[1]['workflow_call']['inputs']
                with self.subTest(caller=name, job=job_name):
                    self.assertLessEqual(set(job['with']), set(declared))
                    required = {key for key, field in declared.items() if field.get('required')}
                    self.assertLessEqual(required, set(job['with']))
                    self.assertTrue(all(field.get('required') or 'default' in field for field in declared.values()))
        self.assertEqual(calls, 4)

    def test_no_run_script_interpolates_an_expression(self):
        scripts = 0
        for name in WORKFLOWS:
            for job in workflow(name)[0]['jobs'].values():
                for step in job.get('steps', []):
                    if 'run' in step:
                        scripts += 1
                        self.assertNotIn('${{', step['run'], f'{name}: {step.get("name")}')
        self.assertGreater(scripts, 5)

    def test_no_recorded_release_is_typed_into_the_drills(self):
        recorded = {path.stem for path in (ROOT / 'releases').glob('v*.json')}
        self.assertIn('v0.7.8', recorded)
        files = ['.github/workflows/' + name for name in WORKFLOWS]
        files += ['tests/rec03-runner.py', 'scripts/ci/export-runtime-verdict.py', 'tests/hosted-sealed-recovery.py',
                  'scripts/ci/release-pair.py', 'tests/rec03_pair.py']
        for name in files:
            with self.subTest(file=name):
                typed = set(re.findall(r'v[0-9]+\.[0-9]+\.[0-9]+', (ROOT / name).read_text()))
                self.assertEqual(typed & recorded, set())

    def test_tool_and_record_checkouts_are_separate_and_immutable(self):
        rec03 = yaml.safe_load((ROOT / '.github/workflows/rec03.yml').read_text())
        self.assertEqual(rec03['jobs']['rec03']['steps'][0]['with'], {
            'ref': '${{ github.sha }}', 'persist-credentials': False})
        steps = self.jobs['source']['steps']
        self.assertEqual(steps, self.jobs['replacement']['steps'])
        checkouts = [s['with'] for s in steps if s.get('uses', '').startswith('actions/checkout@')]
        self.assertEqual(checkouts, [
            {'ref': '${{ github.sha }}', 'path': 'tools', 'persist-credentials': False},
            {'ref': '${{ inputs.record_commit }}', 'path': 'record', 'persist-credentials': False}])
        script = next(s['run'] for s in steps if s.get('name', '').startswith('Exercise unchanged'))
        self.assertIn('sudo env -i PATH=', script)
        self.assertIn('python3 tools/tests/hosted-sealed-recovery.py', script)
        self.assertIn('--record-root "$GITHUB_WORKSPACE/record"', script)
        self.assertIn('--tool-commit "$TOOL_COMMIT"', script)
        for step in steps:
            if 'uses' in step:
                self.assertRegex(step['uses'], r'@[0-9a-f]{40}$')

    def test_cross_job_bytes_are_hashed_and_uploads_are_exact_files(self):
        source = self.jobs['source']
        self.assertEqual(source['outputs']['handoff_sha'], '${{ steps.export.outputs.sha }}')
        self.assertEqual(self.jobs['replacement']['env']['EXPECTED_SHA'], '${{ needs.source.outputs.handoff_sha }}')
        uploads = [s['with'] for s in source['steps'] if s.get('uses', '').startswith('actions/upload-artifact@')]
        self.assertEqual([s['path'] for s in uploads], [
            '${{ runner.temp }}/sealed-public/synthetic-handoff.age',
            '${{ runner.temp }}/sealed-verdict/verdict.json'])
        self.assertEqual(uploads[0]['retention-days'], 1)
        for upload in uploads:
            self.assertNotRegex(upload['path'], r'\*|private|\.env|\.log')
        script = '\n'.join(s.get('run', '') for s in source['steps'])
        self.assertIn('--handoff-sha "$EXPECTED_SHA"', script)
        self.assertIn('sha256sum "$RUNNER_TEMP/sealed-public/synthetic-handoff.age"', script)
        self.assertIn('7df45a6cc87d4da11cc03a539a7470c15b1041ab2b396af088fe9990f7c79d50', script)
        self.assertNotIn('GITHUB_TOKEN', script)

    def test_checks_write_is_confined_to_sanitized_reporter_jobs(self):
        reporter = yaml.safe_load((ROOT / '.github/workflows/runtime-verdict-report.yml').read_text())
        self.assertEqual(set(reporter.get('on', reporter.get(True))), {'workflow_call'})
        allowed = {'contents': 'read', 'actions': 'read', 'checks': 'write'}
        self.assertEqual(reporter['permissions'], allowed)
        for filename, kind in (('rec03.yml', 'rec03'), ('sealed-recovery.yml', 'sealed')):
            workflow = yaml.safe_load((ROOT / '.github/workflows' / filename).read_text())
            self.assertTrue(all(value == 'read' for value in workflow['permissions'].values()))
            report = workflow['jobs'].pop('report')
            self.assertEqual(report['permissions'], allowed)
            self.assertEqual(report['if'], 'always()')
            self.assertEqual(report['uses'], './.github/workflows/runtime-verdict-report.yml')
            self.assertEqual(report['with']['kind'], kind)
            for job in workflow['jobs'].values():
                self.assertNotIn('permissions', job)
                self.assertNotIn('GH_TOKEN', str(job))
                self.assertIn('verdict_id', job['outputs'])
                self.assertTrue(all('continue-on-error' not in step for step in job['steps']))
        steps = reporter['jobs']['publish']['steps']
        downloads = [step for step in steps if step.get('uses', '').startswith('actions/download-artifact@')]
        self.assertEqual(len(downloads), 2)
        for step in downloads:
            self.assertIs(step['continue-on-error'], True)
            self.assertEqual(set(step['with']), {'name', 'path'})
            self.assertIn('artifact_id', step['if'])
            self.assertIn('verdict', step['with']['name'])
            self.assertNotRegex(str(step), r'handoff|\.env|\.log|pattern:')
        self.assertTrue(all('continue-on-error' not in step for step in steps if step not in downloads))
        publish = steps[-1]
        self.assertEqual(publish['env']['GH_TOKEN'], '${{ github.token }}')
        self.assertIn('--input "$RUNNER_TEMP/verdict-check.json"', publish['run'])
        self.assertIn('--jq .html_url', publish['run'])
        self.assertNotIn('${{ inputs.', publish['run'])


if __name__ == '__main__':
    unittest.main()
