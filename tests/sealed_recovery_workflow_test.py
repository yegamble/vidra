"""Dispatch scope, VM separation and artifact boundaries in the actual workflow."""
from pathlib import Path
import re
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]


class SealedWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.workflow = yaml.safe_load((ROOT / '.github/workflows/sealed-recovery.yml').read_text())
        self.jobs = self.workflow['jobs']

    def test_only_explicit_dispatch_runs_two_distinct_hosted_jobs(self):
        events = self.workflow.get('on', self.workflow.get(True))
        self.assertEqual(set(events), {'workflow_dispatch'})
        self.assertEqual(set(self.jobs), {'source', 'replacement', 'report'})
        self.assertEqual(self.jobs['replacement']['needs'], 'source')
        for job in (self.jobs['source'], self.jobs['replacement']):
            self.assertEqual(job['runs-on'], 'ubuntu-24.04')
            self.assertNotIn('container', job)
            self.assertNotIn('services', job)
        self.assertFalse(self.workflow['concurrency']['cancel-in-progress'])

    def test_tool_and_record_checkouts_are_separate_and_immutable(self):
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
        steps = reporter['jobs']['publish']['steps']
        downloads = [step for step in steps if step.get('uses', '').startswith('actions/download-artifact@')]
        self.assertEqual(len(downloads), 2)
        for step in downloads:
            self.assertEqual(set(step['with']), {'name', 'path'})
            self.assertIn('artifact_id', step['if'])
            self.assertIn('verdict', step['with']['name'])
            self.assertNotRegex(str(step), r'handoff|\.env|\.log|pattern:')
        publish = steps[-1]
        self.assertEqual(publish['env']['GH_TOKEN'], '${{ github.token }}')
        self.assertIn('--input "$RUNNER_TEMP/verdict-check.json"', publish['run'])
        self.assertIn('--jq .html_url', publish['run'])
        self.assertNotIn('${{ inputs.', publish['run'])


if __name__ == '__main__':
    unittest.main()
