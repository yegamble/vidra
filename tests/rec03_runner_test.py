"""REC03 verdicts fail closed, per release pair, without exporting private driver material."""
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import rec03_pair_cases as cases

spec = importlib.util.spec_from_file_location('runner', Path(__file__).with_name('rec03-runner.py'))
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
ROOT = Path(__file__).resolve().parents[1]
FP = 'orig=1111111111111111 master=2222222222222222 renditions=720,480 segsha=3333333333333333 state=published'
DATA = {'fp': FP, 'counts': 'users=1 channels=1 videos=1 titles=fixture'}
REF = 'a' * 40


def drill(case):
    return runner.drill(*cases.records(case), cases.sql(case))


def event(case, **changes):
    return {'level': 'ERROR', 'msg': 'migrate failed',
            'error': 'dbmigrate: apply migrations: migration failed: ' + case.error, **changes}


class PerPair(unittest.TestCase):
    def each(self):
        for case in cases.CASES:
            with self.subTest(pair=case.name):
                yield case, drill(case)


class Verdict(PerPair):
    def upgrade(self, case, **changes):
        return {'deploy_exit': '1', 'pin_exit': '0', 'ledger': case.ledger_failed,
                'probe': runner.PROBE, 'images': case.images_old, 'fp': FP, **changes}

    def check_upgrade(self, case, pair, log=None, **changes):
        log = json.dumps(event(case)) if log is None else log
        return runner.verify('upgrade-fail', self.upgrade(case, **changes), {'data': DATA}, log, pair)

    def test_actual_first_migration_failure_is_required(self):
        for case, pair in self.each():
            self.assertEqual(self.check_upgrade(case, pair), {'status': 'PASS', 'media_fingerprint_verified': True,
                                                              'ledger': case.ledger_failed})
            for change in ({'deploy_exit': '0'}, {'ledger': case.ledger_old}, {'ledger': case.ledger_new},
                           {'pin_exit': '1'}, {'probe': 'healthz=503'}, {'images': case.images_new}):
                with self.subTest(change=change), self.assertRaises(runner.Failure):
                    self.check_upgrade(case, pair, **change)
            with self.assertRaisesRegex(runner.Failure, 'migration conflict not observed'):
                self.check_upgrade(case, pair, log='network failure')

    def test_another_pairs_upgrade_facts_are_refused(self):
        for case, pair in self.each():
            for other in cases.others(case):
                with self.subTest(other=other.name):
                    with self.assertRaisesRegex(runner.Failure, 'unexpected migration ledger'):
                        self.check_upgrade(case, pair, ledger=other.ledger_failed)
                    with self.assertRaisesRegex(runner.Failure, 'wrong running image tag'):
                        self.check_upgrade(case, pair, images=other.images_old)
                    with self.assertRaisesRegex(runner.Failure, 'migration conflict not observed'):
                        self.check_upgrade(case, pair, log=json.dumps(event(other)))

    def test_published_json_conflict_is_decoded_without_exporting_private_fields(self):
        for case, pair in self.each():
            log = '\n'.join(('unrelated deploy progress', '{malformed JSON',
                json.dumps({'level': 'INFO', 'msg': 'migrating'}),
                json.dumps(event(case, private='private-canary'))))
            self.assertIn('\\"', log)
            self.assertIsNone(pair.conflict.search(log))
            verdict = self.check_upgrade(case, pair, log=log)
            self.assertEqual(verdict['status'], 'PASS')
            self.assertNotIn('private-canary', json.dumps(verdict))

    def test_unrelated_or_malformed_conflicts_cannot_pass(self):
        for case, pair in self.each():
            good = event(case)
            names = [value for key, value in case.injection.items() if key not in ('REC03_INJECT', 'REC03_INJECT_TYPE')]
            errors = [good['error'].replace(name, 'different_object') for name in names]
            errors += [good['error'].replace('already exists', 'does not exist'),
                       good['error'].replace('dbmigrate: apply migrations: ', ''), None, 1, ['private-canary']]
            self.assertEqual(len(set(map(str, errors))), len(errors))
            events = [{**good, 'error': error} for error in errors]
            events += [{**good, 'level': 'INFO'}, {**good, 'msg': 'request failed'},
                       {'level': 'ERROR', 'msg': 'migrate failed', 'other': good['error']}, list(good.values())]
            logs = [json.dumps(item) for item in events]
            logs += [good['error'], json.dumps(good)[:-1], json.dumps(json.dumps(good))]
            for log in logs:
                with self.subTest(log=log), self.assertRaisesRegex(runner.Failure, 'migration conflict not observed'):
                    self.check_upgrade(case, pair, log=log)

    def test_corrupt_or_empty_media_cannot_become_the_baseline(self):
        for bad in (FP.replace('1111111111111111', 'e3b0c44298fc1c14'), FP.replace('published', 'draft')):
            with self.assertRaises(AssertionError):
                runner.fingerprint(bad)
        for case, pair in self.each():
            with self.assertRaisesRegex(runner.Failure, 'media changed across upgrade or restore'):
                self.check_upgrade(case, pair, fp=FP.replace('1111111111111111', '4444444444444444'))

    def test_backup_and_recovery_are_held_to_the_pairs_own_ledgers(self):
        for case, pair in self.each():
            with tempfile.TemporaryDirectory() as tmp:
                dump = Path(tmp) / 'dump.gz'
                dump.write_bytes(b'x')
                backup = {'backup_exit': '0', 'dump_pre': str(dump), 'pre_core_version': case.pre_core,
                          'pre_search_version': case.pre_search}
                self.assertEqual(runner.verify('backup', backup, {}, '', pair)['status'], 'PASS')
                for change in ({'pre_core_version': case.post_core}, {'pre_core_version': ''},
                               {'pre_search_version': '0'}, {'pre_search_version': case.pre_search + '0'}):
                    with self.subTest(change=change), self.assertRaisesRegex(runner.Failure, 'wrong backup ledger'):
                        runner.verify('backup', {**backup, **change}, {}, '', pair)
            recover = {'deploy_exit': '0', 'probe': runner.PROBE, 'ledger': case.ledger_new, 'fp': FP,
                       'images': case.images_new, 'force_target': case.pre_core, 'post_core_version': case.post_core}
            self.assertEqual(runner.verify('recover', recover, {'data': DATA}, '', pair)['status'], 'PASS')
            for change in ({'force_target': case.first[0]}, {'force_target': str(case.first[0])},
                           {'force_target': case.post_core}, {'post_core_version': case.pre_core}):
                with self.subTest(change=change), self.assertRaisesRegex(runner.Failure, 'wrong recovery force target'):
                    runner.verify('recover', {**recover, **change}, {'data': DATA}, '', pair)
            for other in cases.others(case):
                if other.pre_core != case.pre_core:
                    with self.subTest(other=other.name), self.assertRaisesRegex(runner.Failure, 'wrong recovery force target'):
                        runner.verify('recover', {**recover, 'force_target': other.pre_core}, {'data': DATA}, '', pair)

    def test_wrong_refusal_and_changed_data_fail(self):
        for case, pair in self.each():
            facts = {'restore_exit': '1', 'counts_before': 'a', 'counts_after': 'a',
                     'ledger': case.ledger_new, 'probe': runner.PROBE}
            self.assertEqual(runner.verify('restore-refuse', facts, {}, case.refusal, pair)['status'], 'PASS')
            with self.assertRaisesRegex(runner.Failure, 'schema refusal not observed'):
                runner.verify('restore-refuse', facts, {}, 'permission denied', pair)
            for other in cases.others(case):
                if (other.pre_core, other.post_core) != (case.pre_core, case.post_core):
                    with self.subTest(other=other.name), self.assertRaisesRegex(runner.Failure, 'schema refusal not observed'):
                        runner.verify('restore-refuse', facts, {}, other.refusal, pair)
            with self.assertRaisesRegex(runner.Failure, 'refused restore changed data'):
                runner.verify('restore-refuse', {**facts, 'counts_after': 'lost data'}, {}, case.refusal, pair)

    def test_unknown_secret_fields_are_not_exported(self):
        for case, pair in self.each():
            verdict = self.check_upgrade(case, pair, password='private-canary', config='JWT_SECRET=private-canary')
            self.assertNotIn('private-canary', json.dumps(verdict))
            self.assertEqual(set(verdict), {'status', 'ledger', 'media_fingerprint_verified'})

    def test_missing_media_or_probes_cannot_pass(self):
        for case, pair in self.each():
            for field in ('fp', 'probe', 'images'):
                facts = self.upgrade(case)
                del facts[field]
                with self.subTest(field=field), self.assertRaises(runner.Failure):
                    runner.verify('upgrade-fail', facts, {'data': DATA}, json.dumps(event(case)), pair)

    def split(self, case, **changes):
        return {'deploy_exit': '0', 'probe': runner.PROBE, 'images': case.images_new,
                'video2_state': 'published', 'video2_packaging': 'cmaf', 'video2_fp': FP, **changes}

    def test_split_needs_published_cmaf_media_before_executor_checks(self):
        for case, pair in self.each():
            facts = self.split(case)
            self.assertEqual(runner.verify('split', facts, {}, '', pair)['status'], 'PASS')
            for change in ({'video2_packaging': 'hls-ts'}, {'video2_state': 'failed'}, {'video2_fp': ''},
                           {'images': case.images_old}):
                with self.subTest(change=change), self.assertRaises(runner.Failure):
                    runner.verify('split', {**facts, **change}, {}, '', pair)

    def test_no_split_pass_until_persisted_executor_proof_passes(self):
        for case, pair in self.each():
            containers, _, inspect = RunningImages().fixture(case, 'split')
            proof = runner.rec03_split_proof
            with patch.object(proof, 'verify', side_effect=proof.Invalid()) as validate:
                with self.assertRaisesRegex(runner.Failure, 'split worker not proven'):
                    runner.verify_phase('split', self.split(case), {}, '', pair, inspect)
                self.assertEqual(validate.call_args.args[:3], (self.split(case),
                    {row['Config']['Labels']['com.docker.compose.service']: row for row in containers},
                    cases.records(case)[1]['components']['core']))
            with patch.object(proof, 'verify') as validate:
                self.assertEqual(runner.verify_phase('split', self.split(case), {}, '', pair, inspect)['status'], 'PASS')
                validate.assert_called_once()

    def test_install_exit_and_probe_failures_precede_image_inspection(self):
        for case, pair in self.each():
            facts = {'install_exit': '1', 'probe': runner.PROBE}
            for change, reason in (({}, 'unexpected command exit'),
                                   ({'install_exit': '0', 'probe': 'healthz=503'}, 'HTTP probes failed'),
                                   ({'install_exit': '0'}, 'unexpected migration ledger'),
                                   ({'install_exit': '0', 'ledger': case.ledger_new}, 'unexpected migration ledger'),
                                   ({'install_exit': '0', 'ledger': case.ledger_old, 'images': case.images_new},
                                    'wrong running image tag')):
                inspect = Mock(side_effect=AssertionError('image failure must not mask install facts'))
                with self.subTest(change=change), self.assertRaisesRegex(runner.Failure, reason):
                    runner.verify_phase('install', {**facts, **change}, {}, '', pair, inspect)
                inspect.assert_not_called()
            facts.update(install_exit='0', ledger=case.ledger_old, images=case.images_old)
            with self.assertRaisesRegex(runner.Failure, 'missing running image services'):
                runner.verify_phase('install', facts, {}, '', pair, Mock(return_value=''))

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


class Preflight(unittest.TestCase):
    """main() on a simulated hosted runner, up to the first host change: the pair is resolved, or
    refused for a fixed reason."""

    def run_main(self, head=REF, sql=None, **env):
        env = {'REC03_RECORD_REF': REF, 'REC03_INSTALLER_REF': 'b' * 40, 'REC03_RECORD_ROOT': str(ROOT),
               'RUNNER_ENVIRONMENT': 'github-hosted', **env}
        fetch = Mock(side_effect=AssertionError('no fetch before the pair is accepted')) if sql is None \
            else Mock(return_value=io.BytesIO(sql))
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, env, clear=True), \
                patch.object(runner.os, 'geteuid', return_value=0), patch.object(runner.os, 'cpu_count', return_value=4), \
                patch.object(runner.Path, 'exists', return_value=True), \
                patch.object(runner.sealed_recovery_support, 'head', return_value=head) as checkout, \
                patch.object(runner.urllib.request, 'urlopen', fetch), \
                patch.object(runner.subprocess, 'run') as command, \
                patch.object(runner.subprocess, 'check_output') as output:
            self.assertEqual(runner.main(Path(tmp)), 1)
            command.assert_not_called()
            output.assert_not_called()
            summary = (Path(tmp) / 'summary.json').read_text()
        self.assertNotIn('private-canary', summary)
        return json.loads(summary), checkout, fetch

    def refused(self, reason, pair, **env):
        verdict, _, _ = self.run_main(**env)
        self.assertEqual(verdict, {'status': 'FAIL', 'pair': pair, 'phases': {}, 'failed_phase': 'preflight',
                                   'failure': reason, 'diagnostics': {}})

    def test_bad_input_writes_only_a_safe_failure_before_host_calls(self):
        for env in ({'REC03_RECORD_REF': 'private-canary'}, {'REC03_INSTALLER_REF': 'private-canary'},
                    {'REC03_RECORD_REF': 'main'}):
            with self.subTest(env=env):
                verdict, checkout, _ = self.run_main(REC03_RELEASE='v0.7.20', **env)
                self.assertEqual((verdict['failed_phase'], verdict['failure'], verdict['pair']),
                                 ('preflight', 'immutable commits required', []))
                checkout.assert_not_called()

    def test_the_record_checkout_must_be_the_record_commit(self):
        self.refused('record checkout differs', [], REC03_RELEASE='v0.7.20', head='c' * 40)
        for root in ('', 'releases', '.'):
            with self.subTest(root=root):
                verdict, checkout, _ = self.run_main(REC03_RELEASE='v0.7.20', REC03_RECORD_ROOT=root)
                self.assertEqual((verdict['failure'], verdict['pair']), ('record checkout differs', []))
                checkout.assert_not_called()

    def test_a_release_or_previous_the_records_do_not_name_is_refused_without_a_pair(self):
        for reason, env in (('release is not a recorded release', {}),
                            ('release is not a recorded release', {'REC03_RELEASE': 'private-canary'}),
                            ('release is not a recorded release', {'REC03_RELEASE': 'v0.7.10'}),
                            ('release has no previous record', {'REC03_RELEASE': 'v0.6.4'}),
                            ('previous release is not a recorded release', {'REC03_RELEASE': 'v0.7.20', 'REC03_PREVIOUS': 'v0.7.10'}),
                            ('previous release is not a recorded release', {'REC03_RELEASE': 'v0.7.20', 'REC03_PREVIOUS': 'private-canary'}),
                            ('previous release is not older than the release', {'REC03_RELEASE': 'v0.7.8', 'REC03_PREVIOUS': 'v0.7.20'})):
            with self.subTest(env=env):
                self.refused(reason, [], **env)

    def test_a_pair_with_no_core_migration_is_a_fail_naming_the_pair(self):
        self.refused('pair carries no core migration', ['v0.7.9', 'v0.7.11'], REC03_RELEASE='v0.7.11')
        self.refused('pair carries no core migration', ['v0.7.18', 'v0.7.19'], REC03_RELEASE='v0.7.19')
        self.refused('pair carries no core migration', ['v0.7.9', 'v0.7.19'], REC03_RELEASE='v0.7.19', REC03_PREVIOUS='v0.7.9')

    def test_a_record_that_does_not_list_its_migrations_is_a_fail_naming_the_pair(self):
        self.refused('release record does not list the first pending migration', ['v0.7.5', 'v0.7.7'], REC03_RELEASE='v0.7.7')

    def test_the_host_floor_is_checked_before_any_record_is_read(self):
        verdict, checkout, _ = self.run_main(REC03_RELEASE='v0.7.20', RUNNER_ENVIRONMENT='self-hosted')
        self.assertEqual((verdict['failure'], verdict['pair']), ('disposable hosted runner required', []))
        checkout.assert_not_called()

    def test_the_first_pending_migration_is_read_at_the_newer_records_core_commit(self):
        for case in cases.CASES:
            with self.subTest(pair=case.name):
                verdict, _, fetch = self.run_main(sql=cases.sql(case).encode(), REC03_RELEASE=case.new,
                                                  REC03_PREVIOUS=case.explicit_previous)
                commit = cases.records(case)[1]['components']['core']['commit']
                self.assertEqual(fetch.call_args.args, (
                    f'https://raw.githubusercontent.com/yegamble/vidra-core/{commit}/migrations/{case.first[1]}',))
                # Past the derivation: the next refusal is the (mocked) existing deployment.
                self.assertEqual((verdict['failure'], verdict['pair']), ('existing deployment refused', [case.old, case.new]))

    def test_a_migration_with_nothing_to_clash_on_is_refused_not_downgraded(self):
        for sql, reason in ((b'CREATE INDEX videos_x_idx ON videos (title);', 'first pending migration has no injectable statement'),
                            (b'CREATE TABLE IF NOT EXISTS user_consents (id UUID);', 'first pending migration has no injectable statement'),
                            (b'', 'first pending migration has no injectable statement'),
                            (b'-- ' + b'x' * runner.MIGRATION_LIMIT, 'first pending migration too large'),
                            (b'\xff\xfe', 'UnicodeDecodeError')):
            with self.subTest(sql=sql[:40]):
                verdict, _, _ = self.run_main(sql=sql, REC03_RELEASE='v0.7.20')
                self.assertEqual((verdict['failure'], verdict['pair'], verdict['phases']), (reason, ['v0.7.19', 'v0.7.20'], {}))


class RunningImages(PerPair):
    def fixture(self, case, phase, digest_kind='index_digest'):
        old, new = cases.records(case)
        record = old if phase in {'install', 'upgrade-fail', 'rollback'} else new
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
        return containers, images, Mock(side_effect=command)

    def test_every_runtime_phase_accepts_recorded_index_or_platform_digest(self):
        for case, pair in self.each():
            for phase in ('install', 'upgrade-fail', 'recover', 'rollback', 'repin', 'restore-ok', 'split'):
                for kind in ('index_digest', 'platform'):
                    with self.subTest(phase=phase, digest=kind):
                        _, _, inspect = self.fixture(case, phase, kind)
                        runner.verify_running_images(phase, pair, inspect)
                        self.assertEqual(inspect.call_count, 6 if phase == 'split' else 5)

    def test_another_pairs_running_images_are_refused(self):
        for case, pair in self.each():
            for other in cases.others(case):
                for phase, side in (('install', 0), ('rollback', 0), ('recover', 1), ('split', 1)):
                    if cases.records(other)[side] == cases.records(case)[side]:
                        continue
                    with self.subTest(other=other.name, phase=phase), self.assertRaises(runner.Failure):
                        runner.verify_running_images(phase, pair, self.fixture(other, phase)[2])

    def test_matching_tags_cannot_hide_wrong_loaded_bytes_or_identity(self):
        changes = ({'RepoDigests': ['ghcr.io/yegamble/vidra-core@sha256:' + '0' * 64]},
                   {'Architecture': 'arm64'}, {'Os': 'windows'}, {'Id': 'sha256:' + '0' * 64},
                   {'Config': {'Labels': {'org.opencontainers.image.revision': '0' * 40}}})
        for case, pair in self.each():
            for change in changes:
                with self.subTest(change=change):
                    containers, images, inspect = self.fixture(case, 'recover')
                    images[containers[0]['Image']].update(copy.deepcopy(change))
                    with self.assertRaises(runner.Failure) as refused:
                        runner.verify_running_images('recover', pair, inspect)
                    self.assertNotIn('private-canary', str(refused.exception))

    def test_split_worker_and_exact_services_cannot_be_omitted(self):
        for case, pair in self.each():
            for change in ('missing', 'duplicate', 'stopped', 'wrong-worker', 'wrong-tag'):
                with self.subTest(change=change):
                    containers, images, inspect = self.fixture(case, 'split')
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
                        runner.verify_running_images('split', pair, inspect)

    def test_non_runtime_phases_do_not_request_container_config(self):
        inspect = Mock()
        runner.verify_running_images('report', None, inspect)
        inspect.assert_not_called()


if __name__ == '__main__':
    unittest.main()
