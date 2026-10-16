"""Strict five-service health and identity gates, without Docker or wall-clock waits."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import sealed_recovery_host as host


class FixtureHealthTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        images = {repo: {'reference': 'ghcr.io/fixture/' + repo + '@sha256:' + 'a' * 64,
                         'revision': 'b' * 40} for repo in set(host.runtime.SERVICES.values())}
        self.fixture = host.Host(Path(temporary.name), {}, {'images': images})
        self.containers, self.images = [], {}
        for index, name in enumerate(host.SERVICES, 1):
            image = images.get(host.runtime.SERVICES.get(name), {'reference': 'fixture/' + name, 'revision': ''})
            identity = f'{index:064x}'
            self.containers.append({'Id': identity, 'Image': identity,
                'State': {'Running': True, 'Restarting': False, 'Health': {'Status': 'healthy'}},
                'Config': {'Image': image['reference'], 'Labels': {'com.docker.compose.service': name,
                    'com.docker.compose.project': self.fixture.env['COMPOSE_PROJECT_NAME']}},
                'NetworkSettings': {'Ports': {}, 'Networks': {'fixture_default': {}}}})
            self.images[identity] = {'Id': identity, 'RepoDigests': [image['reference']], 'Os': 'linux',
                'Architecture': 'amd64', 'Config': {'Labels': {'org.opencontainers.image.revision': image['revision']}}}
        self.ids = [container['Id'] for container in self.containers]
        self.fixture.readyz_status = Mock(return_value=200)
        self.fixture.compose = Mock(side_effect=lambda *args: '\n'.join(self.ids))
        self.fixture.run = Mock(side_effect=self.docker)

    def docker(self, args, label):
        if args[:2] == ['docker', 'inspect']:
            return json.dumps(self.containers)
        if args[:3] == ['docker', 'image', 'inspect']:
            return json.dumps([self.images[args[3]]])
        self.assertEqual(args[:3], ['docker', 'network', 'inspect'])
        return '[{"Internal":true}]'

    def ready(self, after_probe=None):
        actual_wait = host.runtime.wait_for_health
        actual_loads = json.loads
        inspected = []

        def decoded(data):
            value = actual_loads(data)
            if value and isinstance(value, list) and 'State' in value[0]:
                inspected[:] = value
            return value

        def bounded(probe, timeout):
            result = actual_wait(probe, timeout=timeout, clock=iter([0, 301]).__next__, pause=lambda _: None)
            if after_probe:
                after_probe(inspected)
            return result

        with patch.object(host.runtime, 'wait_for_health', side_effect=bounded) as wait, \
                patch.object(host.json, 'loads', side_effect=decoded):
            self.fixture.ready()
            self.assertEqual(wait.call_args.kwargs['timeout'], 300)

    def test_all_five_healthy_owned_containers_pass_real_image_and_network_guards(self):
        self.ready()
        self.fixture.compose.assert_called_once_with('ps', '-q', *host.SERVICES)
        self.assertEqual(self.fixture.run.call_args_list[0].args[0], ['docker', 'inspect', *self.ids])
        self.assertEqual(sum(call.args[0][:3] == ['docker', 'image', 'inspect']
                             for call in self.fixture.run.call_args_list), 3)

    def test_each_service_requires_actual_health_in_probe_and_final_guard(self):
        for index, container in enumerate(self.containers):
            for state in [{'Running': True, 'Restarting': False},
                          {'Running': True, 'Restarting': False, 'Health': {}},
                          {'Running': True, 'Restarting': False, 'Health': {'Status': 'unknown'}},
                          {'Running': True, 'Restarting': True, 'Health': {'Status': 'healthy'}},
                          {'Running': False, 'Restarting': False, 'Health': {'Status': 'healthy'}},
                          {'Running': 1, 'Restarting': False, 'Health': {'Status': 'healthy'}},
                          {'Running': True, 'Restarting': 0, 'Health': {'Status': 'healthy'}},
                          {'Running': True, 'Health': {'Status': 'healthy'}}]:
                with self.subTest(service=container['Config']['Labels']['com.docker.compose.service'], state=state):
                    original = container['State']
                    try:
                        container['State'] = state
                        with self.assertRaisesRegex(ValueError, 'runtime health timeout'):
                            self.ready()
                        container['State'] = original
                        with self.assertRaisesRegex(ValueError, 'unhealthy fixture service'):
                            self.ready(lambda inspected: inspected[index].update(State=state))
                    finally:
                        container['State'] = original

    def test_duplicate_compose_ids_never_reach_inspect(self):
        for ids in [self.ids[:-1], self.ids[:-1] + [self.ids[0]], self.ids + ['f' * 64]]:
            self.ids = ids
            with self.assertRaisesRegex(ValueError, 'runtime health timeout'):
                self.ready()
        self.fixture.run.assert_not_called()

    def test_stale_duplicate_or_missing_inspect_identities_are_rejected(self):
        for mutation in [lambda: self.containers[0].update(Id='f' * 64),
                         lambda: self.containers[0].update(Id=self.ids[1]),
                         lambda: self.containers.append(self.containers[0]),
                         lambda: self.containers.pop()]:
            with self.subTest(mutation=mutation):
                original = json.loads(json.dumps(self.containers))
                try:
                    mutation()
                    with self.assertRaisesRegex(ValueError, 'stale fixture container identities'):
                        self.ready()
                finally:
                    self.containers = original

    def test_foreign_project_missing_or_duplicate_service_labels_are_rejected(self):
        labels = self.containers[0]['Config']['Labels']
        for key, value in [('com.docker.compose.project', 'foreign'), ('com.docker.compose.project', None),
                           ('com.docker.compose.service', 'worker'), ('com.docker.compose.service', 'search'),
                           ('com.docker.compose.service', None)]:
            with self.subTest(key=key, value=value):
                original = labels[key]
                try:
                    labels[key] = value
                    with self.assertRaisesRegex(ValueError, 'foreign fixture services'):
                        self.ready()
                finally:
                    labels[key] = original


if __name__ == '__main__':
    unittest.main()
