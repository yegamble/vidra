"""REC03 verdicts fail closed without exporting private driver material."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location('runner', Path(__file__).with_name('rec03-runner.py'))
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
FP = 'orig=1111111111111111 master=2222222222222222 renditions=720,480 segsha=3333333333333333 state=published'
DATA = {'fp': FP, 'counts': 'users=1 channels=1 videos=1 titles=fixture'}
IMAGES = 'ghcr.io/yegamble/vidra-core:v0.7.7;ghcr.io/yegamble/vidra-user:v0.7.7;ghcr.io/yegamble/vidra-search:v0.7.3;'
MIGRATION_EVENT = {'level': 'ERROR', 'msg': 'migrate failed',
                   'error': 'dbmigrate: apply migrations: migration failed: column "is_sensitive" of relation "remote_videos" already exists'}
MIGRATION_LOG = json.dumps(MIGRATION_EVENT)


class Verdict(unittest.TestCase):
    def upgrade(self, **changes):
        return {'deploy_exit': '1', 'pin_exit': '0', 'ledger': 'core=152:true search=18:false',
                'probe': runner.PROBE, 'images': IMAGES, 'fp': FP, **changes}

    def check_upgrade(self, **changes):
        return runner.verify('upgrade-fail', self.upgrade(**changes), {'data': DATA}, MIGRATION_LOG)

    def test_actual_first_migration_failure_is_required(self):
        self.assertEqual(self.check_upgrade()['status'], 'PASS')
        for change in ({'deploy_exit': '0'}, {'ledger': 'core=151:false search=18:false'},
                       {'pin_exit': '1'}, {'probe': 'healthz=503'}, {'images': IMAGES.replace('v0.7.7', 'v0.7.8')}):
            with self.subTest(change=change), self.assertRaises(AssertionError):
                self.check_upgrade(**change)
        with self.assertRaises(AssertionError):
            runner.verify('upgrade-fail', self.upgrade(), {'data': DATA}, 'network failure')

    def test_published_json_conflict_is_decoded_without_exporting_private_fields(self):
        log = '\n'.join(('unrelated deploy progress', '{malformed JSON',
            json.dumps({'level': 'INFO', 'msg': 'migrating'}),
            json.dumps({**MIGRATION_EVENT, 'private': 'private-canary'})))
        self.assertIn('\\"is_sensitive\\"', log)
        self.assertIsNone(runner.re.search(r'column "is_sensitive".*already exists', log))
        verdict = runner.verify('upgrade-fail', self.upgrade(), {'data': DATA}, log)
        self.assertEqual(verdict['status'], 'PASS')
        self.assertNotIn('private-canary', json.dumps(verdict))

    def test_unrelated_or_malformed_conflicts_cannot_pass(self):
        errors = (MIGRATION_EVENT['error'].replace('is_sensitive', 'different_column'),
                  MIGRATION_EVENT['error'].replace('remote_videos', 'different_table'),
                  MIGRATION_EVENT['error'].replace('already exists', 'does not exist'),
                  MIGRATION_EVENT['error'].removeprefix('dbmigrate: apply migrations: '),
                  None, 1, ['private-canary'])
        events = [{**MIGRATION_EVENT, 'error': error} for error in errors]
        events += [{**MIGRATION_EVENT, 'level': 'INFO'}, {**MIGRATION_EVENT, 'msg': 'request failed'},
                   {'level': 'ERROR', 'msg': 'migrate failed', 'other': MIGRATION_EVENT['error']},
                   list(MIGRATION_EVENT.values())]
        logs = [json.dumps(event) for event in events]
        logs += [MIGRATION_EVENT['error'], MIGRATION_LOG[:-1], json.dumps(MIGRATION_LOG)]
        for log in logs:
            with self.subTest(log=log), self.assertRaisesRegex(runner.Failure, 'migration conflict not observed'):
                runner.verify('upgrade-fail', self.upgrade(), {'data': DATA}, log)

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
                runner.verify('upgrade-fail', facts, {'data': DATA}, MIGRATION_LOG)

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

    def test_install_exit_and_probe_failures_precede_image_inspection(self):
        facts = {'install_exit': '1', 'probe': runner.PROBE}
        for change, reason in (({}, 'unexpected command exit'),
                               ({'install_exit': '0', 'probe': 'healthz=503'}, 'HTTP probes failed')):
            inspect = Mock(side_effect=AssertionError('image failure must not mask install facts'))
            with self.assertRaisesRegex(runner.Failure, reason):
                runner.verify_phase('install', {**facts, **change}, {}, '', {}, inspect)
            inspect.assert_not_called()
        facts.update(install_exit='0', ledger='core=151:false search=18:false', images=IMAGES)
        with self.assertRaisesRegex(runner.Failure, 'missing running image services'):
            runner.verify_phase('install', facts, {}, '', {'v0.7.7': {}}, Mock(return_value=''))

    def test_failure_diagnostics_export_only_finite_values(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'install.private.log').write_text('\n'.join([
                '[rec03 install 12:34:56] install.sh exit=0',
                '[rec03 install 12:34:56] setup exit=2',
                '[rec03 install 12:34:56] setup --check exit=255',
                '[rec03 install 12:34:56] provision exit=1',
                '[rec03 install 12:34:56] deploy.sh exit=127',
                '[rec03 install 12:34:56] setup exit=256',
                '[rec03 install 12:34:56] setup exit=-1',
                '[rec03 install 12:34:56] setup exit=0 private-canary',
                '[rec03 install 12:34:56] private-canary exit=0',
                'JWT_SECRET=private-canary']))
            with patch.object(runner.subprocess, 'check_output', return_value='api\npostgres\napi\nprivate-canary\napi private-canary\n') as command:
                result = runner.diagnostics(root, {'probe': 'instance=200 healthz=503 site=000 watch=502',
                                                   'private': 'private-canary'})
            self.assertEqual(result, {'install_steps': {'installer': 0, 'setup': 2, 'setup_check': 255,
                'provision': 1, 'deploy': 127}, 'running_services': ['api', 'postgres'],
                'probe_statuses': {'instance': 200, 'healthz': 503, 'site': 0, 'watch': 502}})
            self.assertNotIn('private-canary', json.dumps(result))
            self.assertEqual(command.call_args.kwargs['stderr'], runner.subprocess.DEVNULL)
            for probe in ('instance=200 healthz=200 site=200 watch=200 private-canary', None, 200):
                with patch.object(runner.subprocess, 'check_output', side_effect=OSError('private-canary')):
                    self.assertEqual(runner.diagnostics(root / 'absent', {'probe': probe}), {})
            with patch.object(runner.subprocess, 'check_output', side_effect=runner.subprocess.TimeoutExpired('private-canary', 10)):
                self.assertEqual(runner.diagnostics(root / 'absent', ['private-canary']), {})


class RunningImages(unittest.TestCase):
    def fixture(self, phase, digest_kind='index_digest'):
        records = {}
        for release in ('v0.7.7', 'v0.7.8'):
            first = 1 if release == 'v0.7.7' else 4
            records[release] = {'components': {role: {
                'commit': str(index) * 40, 'tag': 'v0.7.3' if role == 'search' and release == 'v0.7.7' else release,
                'image': {'repository': 'ghcr.io/yegamble/vidra-' + role,
                          'index_digest': 'sha256:' + str(index) * 64,
                          'platforms': {'linux/amd64': 'sha256:' + str(index + 3) * 64}}}
                for index, role in enumerate(('core', 'user', 'search'), first)}}
        record = records['v0.7.7' if phase in {'install', 'upgrade-fail', 'rollback'} else 'v0.7.8']
        services = {'api': 'core', 'frontend': 'user', 'search': 'search'}
        if phase == 'split':
            services['worker'] = 'core'
        containers, images = [], {}
        for index, (service, role) in enumerate(services.items()):
            component = record['components'][role]
            image = component['image']
            image_id = 'sha256:' + 'abcdef'[index] * 64
            digest = image[digest_kind] if digest_kind == 'index_digest' else image['platforms']['linux/amd64']
            containers.append({'Id': service, 'Image': image_id, 'State': {'Running': True},
                'Config': {'Image': image['repository'] + ':' + component['tag'],
                           'Labels': {'com.docker.compose.service': service}, 'Env': ['PRIVATE=private-canary']}})
            images[image_id] = {'Id': image_id, 'Os': 'linux', 'Architecture': 'amd64',
                'RepoDigests': [image['repository'] + '@' + digest],
                'Config': {'Labels': {'org.opencontainers.image.revision': component['commit']}}}
        def command(argv):
            if argv[:2] == ['bash', 'deploy/compose.sh']:
                self.assertEqual(argv[2:], ['ps', '-q', *services])
                return '\n'.join(container['Id'] for container in containers)
            if argv[:2] == ['docker', 'inspect']:
                return json.dumps(containers)
            self.assertEqual(argv[:3], ['docker', 'image', 'inspect'])
            return json.dumps([images[argv[3]]])
        return records, containers, images, Mock(side_effect=command)

    def test_every_runtime_phase_accepts_recorded_index_or_platform_digest(self):
        for phase in ('install', 'upgrade-fail', 'recover', 'rollback', 'repin', 'restore-ok', 'split'):
            for kind in ('index_digest', 'platform'):
                with self.subTest(phase=phase, digest=kind):
                    records, _, _, inspect = self.fixture(phase, kind)
                    runner.verify_running_images(phase, records, inspect)
                    self.assertEqual(inspect.call_count, 6 if phase == 'split' else 5)

    def test_matching_tags_cannot_hide_wrong_loaded_bytes_or_identity(self):
        changes = ({'RepoDigests': ['ghcr.io/yegamble/vidra-core@sha256:' + '0' * 64]},
                   {'Architecture': 'arm64'}, {'Os': 'windows'}, {'Id': 'sha256:' + '0' * 64},
                   {'Config': {'Labels': {'org.opencontainers.image.revision': '0' * 40}}})
        for change in changes:
            with self.subTest(change=change):
                records, containers, images, inspect = self.fixture('recover')
                images[containers[0]['Image']].update(copy.deepcopy(change))
                with self.assertRaises(runner.Failure) as refused:
                    runner.verify_running_images('recover', records, inspect)
                self.assertNotIn('private-canary', str(refused.exception))

    def test_split_worker_and_exact_services_cannot_be_omitted(self):
        for change in ('missing', 'duplicate', 'stopped', 'wrong-worker', 'wrong-tag'):
            with self.subTest(change=change):
                records, containers, images, inspect = self.fixture('split')
                if change == 'missing':
                    containers.pop()
                elif change == 'duplicate':
                    containers[-1]['Config']['Labels']['com.docker.compose.service'] = 'api'
                elif change == 'stopped':
                    containers[-1]['State']['Running'] = False
                elif change == 'wrong-tag':
                    containers[-1]['Config']['Image'] = 'ghcr.io/yegamble/vidra-core:latest'
                else:
                    images[containers[-1]['Image']]['RepoDigests'] = []
                with self.assertRaises(runner.Failure):
                    runner.verify_running_images('split', records, inspect)

    def test_non_runtime_phases_do_not_request_container_config(self):
        inspect = Mock()
        runner.verify_running_images('report', {}, inspect)
        inspect.assert_not_called()


if __name__ == '__main__':
    unittest.main()
