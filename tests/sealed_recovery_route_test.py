"""The fixture control route must belong to its current isolated API container."""
import unittest
import json
from pathlib import Path
import tempfile
from unittest.mock import Mock, patch

import sealed_recovery_host as host
from sealed_recovery_route import internal_origin, unpublished

PROJECT, CID, NID = 'vidra-synthetic-sealed', 'a' * 64, 'b' * 64
NAME = PROJECT + '_default'


def proof():
    container = {'Id': CID, 'State': {'Running': True, 'Restarting': False}, 'Config': {'Labels': {
        'com.docker.compose.service': 'api', 'com.docker.compose.project': PROJECT}}, 'NetworkSettings': {
        'Ports': {'8080/tcp': None}, 'Networks': {NAME: {'NetworkID': NID, 'IPAddress': '172.30.0.2', 'IPPrefixLen': 24}}}}
    network = {'Id': NID, 'Name': NAME, 'Driver': 'bridge', 'Internal': True, 'Labels': {
        'com.docker.compose.project': PROJECT, 'com.docker.compose.network': 'default'},
        'IPAM': {'Config': [{'Subnet': '172.30.0.0/24'}]}, 'Containers': {CID: {'IPv4Address': '172.30.0.2/24'}}}
    return container, network


class InternalRouteTest(unittest.TestCase):
    def test_host_resolves_fresh_container_after_recreation_and_rejects_stale_inspect(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = host.Host(Path(temporary), {}, {})
            first, net1 = proof()
            second, net2 = proof()
            second['Id'] = 'c' * 64
            second['NetworkSettings']['Networks'][NAME]['IPAddress'] = '172.30.0.3'
            net2['Containers'] = {second['Id']: {'IPv4Address': '172.30.0.3/24'}}
            with patch.object(fixture, 'compose', side_effect=[CID, second['Id'], second['Id']]), \
                    patch.object(fixture, 'run', side_effect=[json.dumps([value]) for value in (first, net1, second, net2, first)]):
                self.assertEqual(fixture.api_origin(), 'http://172.30.0.2:8080')
                self.assertEqual(fixture.api_origin(), 'http://172.30.0.3:8080')
                with self.assertRaises(ValueError):
                    fixture.api_origin()

    def test_http_probe_does_not_follow_redirect_and_node_gets_matching_fresh_opt_in(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = host.Host(Path(temporary), {}, {})
            connection = Mock()
            connection.getresponse.return_value.status = 302
            origins = ['http://172.30.0.2:8080', 'http://172.30.0.3:8080', 'http://172.30.0.4:8080']
            with patch.object(fixture, 'api_origin', side_effect=origins), \
                    patch.object(host.http.client, 'HTTPConnection', return_value=connection), \
                    patch.object(fixture, 'run', return_value='{"status":"PASS"}') as run:
                self.assertEqual(fixture.readyz_status(), 302)
                connection.request.assert_called_once_with('GET', '/readyz')
                connection.close.assert_called_once()
                fixture.api_fixture('verify', Path(temporary) / 'fixture.json')
                fixture.api_fixture('wrong-key', Path(temporary) / 'fixture.json')
            for call, expected in zip(run.call_args_list, origins[1:]):
                self.assertEqual(call.kwargs['env']['VIDRA_BASE_URL'], expected)
                self.assertEqual(call.kwargs['env']['VIDRA_INTERNAL_ORIGIN'], expected)

    def test_current_running_owned_private_container_and_no_actual_binding(self):
        container, network = proof()
        # Docker may retain requested loopback bindings while internal networking
        # suppresses all actual mappings. Requested production intent is untouched.
        container['HostConfig'] = {'PortBindings': {'8080/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '8080'}]}}
        self.assertEqual(internal_origin(container, network, PROJECT), 'http://172.30.0.2:8080')
        unpublished({'NetworkSettings': {'Ports': {}}})

    def test_foreign_stale_nonprivate_or_published_route_is_refused(self):
        mutations = [
            lambda c, n: c['State'].update(Running=False), lambda c, n: c['State'].update(Restarting=True),
            lambda c, n: c['Config']['Labels'].update({'com.docker.compose.service': 'frontend'}),
            lambda c, n: c['Config']['Labels'].update({'com.docker.compose.project': 'foreign'}),
            lambda c, n: c['NetworkSettings']['Networks'].update(foreign={}),
            lambda c, n: c['NetworkSettings']['Networks'][NAME].update(NetworkID='c' * 64),
            lambda c, n: n.update(Internal=False), lambda c, n: n.update(Driver='host'),
            lambda c, n: n.update(Name='foreign'), lambda c, n: n['Labels'].update({'com.docker.compose.project': 'foreign'}),
            lambda c, n: n.update(Id=None),
            lambda c, n: n['Containers'].clear(), lambda c, n: c.update(Id='c' * 64),
            lambda c, n: n['Containers'][CID].update(IPv4Address='172.30.0.3/24'),
            lambda c, n: n['IPAM'].update(Config=[{'Subnet': '172.31.0.0/24'}]),
            lambda c, n: n['IPAM'].update(Config=[{'Subnet': '0.0.0.0/0'}]),
            lambda c, n: c['NetworkSettings']['Networks'][NAME].update(IPPrefixLen=16),
            lambda c, n: c['NetworkSettings']['Ports'].update({'8080/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '8080'}]}),
        ]
        for mutate in mutations:
            container, network = proof()
            mutate(container, network)
            with self.subTest(mutation=mutations.index(mutate)), self.assertRaises(ValueError):
                internal_origin(container, network, PROJECT)
        for address in ('8.8.8.8', '169.254.169.254', '127.0.0.1', '172.31.0.2', '172.30.0.0',
                        '172.30.0.255', '::1', '2887647234', '172.030.0.2'):
            container, network = proof()
            container['NetworkSettings']['Networks'][NAME]['IPAddress'] = address
            with self.subTest(address=address), self.assertRaises(ValueError):
                internal_origin(container, network, PROJECT)


if __name__ == '__main__':
    unittest.main()
