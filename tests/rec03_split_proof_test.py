"""Split proof must bind fresh work to actual current worker processes."""
import copy
import json
import unittest

from rec03_split_proof import Invalid, verify


VIDEO, JOB, RUN = ('1' * 8 + '-1111-4111-8111-' + '1' * 12,
                   '2' * 8 + '-2222-4222-8222-' + '2' * 12,
                   '3' * 8 + '-3333-4333-8333-' + '3' * 12)
COMMIT = '04a7f0e127177b631eb323d04d330673fee044f9'


def fixture():
    facts = dict(video2_id=VIDEO, split_before='1000.000001', split_cursor='7')
    containers = {}
    processes = []
    for role, boot in (('api', '15:00'), ('worker', '15:50')):
        hostname = role + '-fixture'
        containers[role] = {'Path': '/app/api', 'Args': [], 'HostConfig': {'Init': None, 'PidMode': ''},
                            'Config': {'Hostname': hostname, 'Env': ['SECRET=canary', 'VIDRA_ROLE=' + role]},
                            'State': {'StartedAt': '1970-01-01T00:' + boot + '.000000001Z'}}
        processes.append(dict(process_id=hostname + ':1', hostname=hostname, pid=1, role=role,
                              version='v0.7.8', build_commit=COMMIT[:7], state='running',
                              started_epoch='951' if role == 'worker' else '901', last_seen_epoch='1499'))
    events = [dict(cursor=8, kind='started', state='running', worker_id='worker-fixture:1', occurred_epoch='1003'),
              dict(cursor=9, kind='succeeded', state='succeeded', worker_id='worker-fixture:1', occurred_epoch='1100')]
    run = dict(id=RUN, type='video_transcode', queue='transcode_jobs', source_id=JOB,
               resource_type='video', resource_id=VIDEO, state='succeeded', worker_id='worker-fixture:1',
               created_epoch='1002', claimed_epoch='1003', started_epoch='1003', finished_epoch='1100', events=events)
    snapshot = dict(observed_epoch='1500', video=dict(id=VIDEO, created_epoch='1001'), processes=processes,
                    jobs=[dict(id=JOB, video_id=VIDEO, state='done', transcode_type='all', created_epoch='1002', runs=[run])],
                    hls_succeeded=1, api_runs=0, api_events=0)
    return facts, containers, dict(tag='v0.7.8', commit=COMMIT), snapshot


class SplitProofTest(unittest.TestCase):
    def check(self, mutate=None, valid=False):
        facts, containers, record, snapshot = fixture()
        if mutate:
            mutate(facts, containers, record, snapshot)
        calls = []
        def query(sql):
            calls.append(sql)
            return json.dumps(snapshot)
        if valid:
            self.assertIsNone(verify(facts, containers, record, query))
        else:
            with self.assertRaisesRegex(Invalid, '^split worker not proven$'):
                verify(facts, containers, record, query)
        return calls

    def test_fresh_worker_completes_fixture_and_api_executes_nothing(self):
        calls = self.check(valid=True)
        self.assertEqual(len(calls), 1)
        self.assertNotIn('SECRET', calls[0])
        self.assertNotIn('canary', calls[0])

    def test_worker_can_boot_after_pre_upload_boundary(self):
        def late(f, c, r, s):
            c['worker']['State']['StartedAt'] = '1970-01-01T00:16:41.000000001Z'
            s['processes'][1]['started_epoch'] = '1002'
        self.check(late, valid=True)

    def test_full_and_longer_matching_build_prefixes(self):
        for length in (7, 12, 40):
            self.check(lambda f, c, r, s: s['processes'][1].update(build_commit=COMMIT[:length]), valid=True)

    def test_actual_roles_and_pid_one_execution_are_required(self):
        mutations = [
            lambda f, c, r, s: c['api']['Config'].update(Env=['VIDRA_ROLE=all']),
            lambda f, c, r, s: c['worker']['Config'].update(Env=['VIDRA_ROLE=api']),
            lambda f, c, r, s: c['api']['Config']['Env'].append('VIDRA_ROLE=api'),
            lambda f, c, r, s: c['worker']['Config']['Env'].clear(),
            lambda f, c, r, s: c['worker'].update(Path='/bin/sh'),
            lambda f, c, r, s: c['api'].update(Args=['--role=api']),
            lambda f, c, r, s: c['worker']['HostConfig'].update(Init=True),
            lambda f, c, r, s: c['api']['HostConfig'].update(PidMode='host'),
            lambda f, c, r, s: c['worker']['Config'].update(Hostname='api-fixture'),
            lambda f, c, r, s: c['api']['Config'].update(Hostname="bad'host"),
        ]
        for mutate in mutations:
            with self.subTest(case=mutations.index(mutate)):
                self.assertEqual(self.check(mutate), [])

    def test_current_healthy_process_identity_and_build_are_required(self):
        for fields in (dict(process_id='stale-worker:1'), dict(hostname='stale-worker'), dict(pid=2),
                       dict(pid=True), dict(role='all'), dict(version='v0.7.7'), dict(build_commit='04a7f0'),
                       dict(build_commit='04a7f0f'), dict(build_commit='unknown'), dict(state='stopped'),
                       dict(started_epoch='950'), dict(started_epoch='1501'), dict(last_seen_epoch='1469'),
                       dict(last_seen_epoch='1501')):
            with self.subTest(fields=fields):
                self.check(lambda f, c, r, s: s['processes'][1].update(fields))
        self.check(lambda f, c, r, s: s['processes'].pop())
        self.check(lambda f, c, r, s: s['processes'].append(copy.deepcopy(s['processes'][1])))

    def test_fresh_video_and_complete_hls_work_are_required(self):
        for mutate in (
                lambda f, c, r, s: s.update(video=None),
                lambda f, c, r, s: s['video'].update(id=JOB),
                lambda f, c, r, s: s['video'].update(created_epoch='1000'),
                lambda f, c, r, s: s['jobs'].clear(),
                lambda f, c, r, s: s['jobs'][0].update(video_id=JOB),
                lambda f, c, r, s: s['jobs'][0].update(state='running'),
                lambda f, c, r, s: s['jobs'][0].update(transcode_type='web_video'),
                lambda f, c, r, s: s['jobs'][0].update(created_epoch='999'),
                lambda f, c, r, s: s.update(hls_succeeded=0),
                lambda f, c, r, s: s.update(hls_succeeded=True),
                lambda f, c, r, s: s['jobs'].append(copy.deepcopy(s['jobs'][0]))):
            self.check(mutate)

    def test_missing_wrong_or_ambiguous_parent_projection_is_refused(self):
        self.check(lambda f, c, r, s: s['jobs'][0]['runs'].clear())
        self.check(lambda f, c, r, s: s['jobs'][0]['runs'].append(copy.deepcopy(s['jobs'][0]['runs'][0])))
        for fields in (dict(source_id=VIDEO), dict(resource_id=JOB), dict(resource_type='channel'),
                       dict(type='video_import'), dict(queue='transcode_steps'), dict(state='running'),
                       dict(worker_id='api-fixture:1'), dict(worker_id='old-worker:1'), dict(worker_id=''),
                       dict(claimed_epoch=None), dict(started_epoch='950'), dict(finished_epoch='1002'),
                       dict(finished_epoch='1501')):
            with self.subTest(fields=fields):
                self.check(lambda f, c, r, s: s['jobs'][0]['runs'][0].update(fields))

    def test_old_missing_wrong_or_api_first_events_are_refused(self):
        self.check(lambda f, c, r, s: s['jobs'][0]['runs'][0]['events'].pop())
        for fields in (dict(cursor=7), dict(cursor=True), dict(occurred_epoch='999'), dict(state='queued'),
                       dict(worker_id='api-fixture:1'), dict(worker_id='old-worker:1'), dict(worker_id='')):
            with self.subTest(fields=fields):
                self.check(lambda f, c, r, s: s['jobs'][0]['runs'][0]['events'][0].update(fields))
        def api_first(f, c, r, s):
            event = dict(cursor=10, kind='started', state='running', worker_id='api-fixture:1', occurred_epoch='1002')
            s['jobs'][0]['runs'][0]['events'].append(event)
        self.check(api_first)

    def test_api_execution_in_other_jobs_is_also_refused(self):
        for key in ('api_runs', 'api_events'):
            for value in (1, -1, True, '0'):
                self.check(lambda f, c, r, s: s.update({key: value}))

    def test_invalid_inputs_do_not_reach_sql(self):
        for key, value in (('video2_id', VIDEO.replace('4111', 'A111')), ('video2_id', "x'; SELECT secret"),
                           ('split_before', 'NaN'), ('split_before', '-1'), ('split_before', '1e3'),
                           ('split_cursor', '-1'), ('split_cursor', '0; SELECT secret')):
            self.assertEqual(self.check(lambda f, c, r, s: f.update({key: value})), [])

    def test_parse_and_query_failures_are_fixed_and_private(self):
        f, c, r, _ = fixture()
        for raw in ('canary-private', '{}', 'null', '[]', '{"observed_epoch":NaN}'):
            with self.subTest(raw=raw), self.assertRaisesRegex(Invalid, '^split worker not proven$') as caught:
                verify(f, c, r, lambda sql: raw)
            self.assertIsNone(caught.exception.__cause__)
        with self.assertRaisesRegex(Invalid, '^split worker not proven$') as caught:
            verify(f, c, r, lambda sql: (_ for _ in ()).throw(RuntimeError('canary-private')))
        self.assertIsNone(caught.exception.__cause__)


if __name__ == '__main__':
    unittest.main()
