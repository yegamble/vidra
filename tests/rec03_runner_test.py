"""REC03 verdicts fail closed without exporting private driver material."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('runner', Path(__file__).with_name('rec03-runner.py'))
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
FP = 'orig=1111111111111111 master=2222222222222222 renditions=720,480 segsha=3333333333333333 state=published'
DATA = {'fp': FP, 'counts': 'users=1 channels=1 videos=1 titles=fixture'}
IMAGES = 'ghcr.io/yegamble/vidra-core:v0.7.7;ghcr.io/yegamble/vidra-user:v0.7.7;ghcr.io/yegamble/vidra-search:v0.7.3;'


class Verdict(unittest.TestCase):
    def upgrade(self, **changes):
        return {'deploy_exit': '1', 'pin_exit': '0', 'ledger': 'core=152:true search=18:false',
                'probe': runner.PROBE, 'images': IMAGES, 'fp': FP, **changes}

    def check_upgrade(self, **changes):
        return runner.verify('upgrade-fail', self.upgrade(**changes), {'data': DATA}, 'column "is_sensitive" already exists')

    def test_actual_first_migration_failure_is_required(self):
        self.assertEqual(self.check_upgrade()['status'], 'PASS')
        for change in ({'deploy_exit': '0'}, {'ledger': 'core=151:false search=18:false'},
                       {'pin_exit': '1'}, {'probe': 'healthz=503'}, {'images': IMAGES.replace('v0.7.7', 'v0.7.8')}):
            with self.subTest(change=change), self.assertRaises(AssertionError):
                self.check_upgrade(**change)
        with self.assertRaises(AssertionError):
            runner.verify('upgrade-fail', self.upgrade(), {'data': DATA}, 'network failure')

    def test_corrupt_or_empty_media_cannot_become_the_baseline(self):
        for bad in (FP.replace('1111111111111111', 'e3b0c44298fc1c14'), FP.replace('published', 'draft')):
            with self.assertRaises(AssertionError):
                runner.fingerprint(bad)
        with self.assertRaises(AssertionError):
            self.check_upgrade(fp=FP.replace('1111111111111111', '4444444444444444'))

    def test_wrong_refusal_and_changed_data_fail(self):
        facts = {'restore_exit': '1', 'counts_before': 'a', 'counts_after': 'a',
                 'ledger': 'core=182:false search=18:false', 'probe': runner.PROBE}
        with self.assertRaises(AssertionError):
            runner.verify('restore-refuse', facts, {}, 'permission denied')
        facts['counts_after'] = 'lost data'
        with self.assertRaises(AssertionError):
            runner.verify('restore-refuse', facts, {}, 'dump is at 182 carries up to 151 Nothing was changed')

    def test_unknown_secret_fields_are_not_exported(self):
        verdict = self.check_upgrade(password='private-canary', config='JWT_SECRET=private-canary')
        self.assertNotIn('private-canary', json.dumps(verdict))
        self.assertEqual(set(verdict), {'status', 'ledger', 'media_fingerprint_verified'})

    def test_missing_media_or_probes_cannot_pass(self):
        for field in ('fp', 'probe', 'images'):
            facts = self.upgrade()
            del facts[field]
            with self.assertRaises(AssertionError):
                runner.verify('upgrade-fail', facts, {'data': DATA}, 'column "is_sensitive" already exists')

    def test_split_needs_a_published_worker_and_an_idle_api(self):
        facts = {'deploy_exit': '0', 'probe': runner.PROBE, 'workers': '1', 'images': IMAGES.replace('v0.7.7', 'v0.7.8').replace('v0.7.3', 'v0.7.8'),
                 'video2_state': 'published', 'api_ffmpeg_mentions': '0'}
        self.assertEqual(runner.verify('split', facts, {}, '')['status'], 'PASS')
        for change in ({'workers': '0'}, {'video2_state': 'failed'}, {'api_ffmpeg_mentions': '1'}):
            with self.assertRaises(AssertionError):
                runner.verify('split', {**facts, **change}, {}, '')

    def test_bad_input_writes_only_a_safe_failure_before_host_calls(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'REC03_RECORD_REF': 'private-canary'}), \
                patch.object(runner.subprocess, 'run') as command:
            self.assertEqual(runner.main(Path(tmp)), 1)
            command.assert_not_called()
            summary = (Path(tmp) / 'summary.json').read_text()
            self.assertNotIn('private-canary', summary)
            self.assertEqual(json.loads(summary)['failed_phase'], 'preflight')


if __name__ == '__main__':
    unittest.main()
