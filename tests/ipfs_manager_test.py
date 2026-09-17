"""Host IPFS boundary: no caller-selected command, durable fencing, safe adoption."""
import importlib.util
import json
from pathlib import Path
import tempfile
import http.client
import socket
import threading
from unittest.mock import patch
import unittest
from unittest.mock import Mock

SPEC = importlib.util.spec_from_file_location('ipfs_manager', Path(__file__).resolve().parents[1] / 'deploy/ipfs-manager.py')
manager = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(manager)


def envelope(sequence=1, operation_id=None):
    return {'protocol_version': 1, 'operation_id': operation_id or f'00000000-0000-4000-8000-{sequence:012d}',
            'sequence': sequence, 'config_revision': sequence,
            'config': {'enabled': True, 'budget_bytes': 20 * 1024**3, 'min_free_bytes': 20 * 1024**3,
                       'copy_bytes_per_second': 2 * 1024**2, 'workers': 1}}


class ProtocolTests(unittest.TestCase):
    def test_accepts_explicit_beta_policy(self):
        self.assertEqual(manager.validate(envelope()), envelope())

    def test_rejects_commands_paths_extra_keys_booleans_and_out_of_bounds(self):
        changes = [('command', 'docker rm api'), ('sequence', True), ('sequence', 0),
                   ('config_revision', 2**63), ('protocol_version', 2), ('operation_id', '../state')]
        for key, value in changes:
            with self.subTest(key=key, value=value):
                body = envelope(); body[key] = value
                with self.assertRaises(manager.Rejected): manager.validate(body)
        for key, value in [('enabled', 1), ('workers', 9), ('workers', True), ('budget_bytes', 0),
                           ('min_free_bytes', -1), ('copy_bytes_per_second', 65535), ('url', 'http://other')]:
            with self.subTest(key=key):
                body = envelope(); body['config'][key] = value
                with self.assertRaises(manager.Rejected): manager.validate(body)

    def test_peer_credentials_require_both_api_uid_and_gid(self):
        connection=Mock()
        with patch.object(manager.socket,'SO_PEERCRED',17,create=True):
            for uid,gid,allowed in [(10001,10001,True),(10001,99,False),(99,10001,False),(0,0,True)]:
                connection.getsockopt.return_value=manager.struct.pack('3i',123,uid,gid)
                self.assertEqual(manager.peer_allowed(connection),allowed)

    def test_duplicate_json_keys_are_not_silently_last_wins(self):
        with self.assertRaises(manager.Rejected):
            manager.decode(b'{"sequence":1,"sequence":2}')


class OperationsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        self.backend = Mock()
        self.backend.probe.return_value = {'observed_state':'running', 'repo_used_bytes':123,
                                          'filesystem_free_bytes':99*1024**3, 'observed_at':'2026-09-17T10:00:00Z'}
        self.control = manager.Controller(self.path, self.backend)

    def test_same_request_is_durable_idempotent_and_reuse_different_body_conflicts(self):
        first = self.control.accept('apply', envelope())
        self.control.process_next()
        reopened = manager.Controller(self.path, self.backend)
        self.assertEqual(reopened.accept('apply', envelope())['state'], 'succeeded')
        self.assertEqual(first['id'], reopened.status()['last_operation_id'])
        self.backend.apply.assert_called_once()
        altered = envelope(); altered['config']['workers'] = 2
        with self.assertRaises(manager.Rejected) as failure: reopened.accept('apply', altered)
        self.assertEqual(failure.exception.status, 409)
        with self.assertRaises(manager.Rejected): reopened.accept('restart', envelope())

    def test_sequence_and_revision_cannot_regress_even_after_restart(self):
        self.control.accept('apply', envelope(5))
        for doc in (envelope(4), dict(envelope(6), config_revision=4)):
            with self.assertRaises(manager.Rejected): self.control.accept('apply', doc)
        self.assertEqual(self.control.status()['last_operation_sequence'], 5)

    def test_same_revision_cannot_describe_different_policy(self):
        self.control.accept('apply',envelope())
        conflicting=envelope(2); conflicting['config_revision']=1; conflicting['config']['workers']=2
        with self.assertRaises(manager.Rejected) as failure: self.control.accept('apply',conflicting)
        self.assertEqual(failure.exception.status,409)
        retry=envelope(2); retry['config_revision']=1
        self.assertEqual(self.control.accept('restart',retry)['sequence'],2)

    def test_operations_serialize_and_disabled_does_not_stop_the_node(self):
        self.control.accept('apply', envelope())
        paused = envelope(2); paused['config']['enabled'] = False
        self.control.accept('restart', paused)
        self.control.process_next(); self.control.process_next()
        self.assertEqual(self.backend.apply.call_args_list[1].args, ('restart', paused))
        self.assertEqual(self.control.status()['applied_config_revision'], 2)
        self.backend.stop.assert_not_called()

    def test_failed_apply_preserves_last_applied_revision_and_hides_exception_details(self):
        self.control.accept('apply', envelope()); self.control.process_next()
        self.backend.apply.side_effect = RuntimeError('SECRET /host/path')
        self.control.accept('apply', envelope(2)); self.control.process_next()
        state = self.control.status()
        self.assertEqual(state['operation']['state'], 'failed')
        self.assertEqual(state['applied_config_revision'], 1)
        self.assertEqual(state['last_error_code'], 'ipfs_apply_failed')
        self.assertNotIn('SECRET', json.dumps(state))

    def test_interrupted_operation_replays_with_its_original_id(self):
        self.control.accept('restart', envelope())
        with self.control.db() as db: db.execute("UPDATE operations SET state='running'")
        reopened = manager.Controller(self.path, self.backend)
        reopened.process_next()
        self.backend.apply.assert_called_once_with('restart', envelope())
        self.assertEqual(reopened.status()['operation']['state'], 'succeeded')

    def test_status_timestamp_is_probe_time_not_request_time_and_unknown_is_null(self):
        initial = self.control.status()
        self.assertIsNone(initial['repo_used_bytes'])
        self.control.observe()
        self.assertEqual(self.control.status()['observed_at'], '2026-09-17T10:00:00Z')
        self.backend.probe.side_effect = RuntimeError('unavailable')
        self.control.observe()
        self.assertEqual(self.control.status()['observed_state'], 'unknown')
        self.assertIsNone(self.control.status()['filesystem_free_bytes'])

    def test_watchdog_is_bounded_and_survives_daemon_restart(self):
        self.control.accept('apply', envelope()); self.control.process_next()
        self.backend.probe.return_value['observed_state'] = 'unhealthy'
        self.backend.apply.side_effect = RuntimeError('failed restart')
        for now in [1000, 1061, 1182, 1423, 1900]: self.control.watchdog(now)
        self.assertEqual(self.backend.apply.call_count, 4)  # initial + three recovery attempts
        reopened = manager.Controller(self.path, self.backend)
        reopened.watchdog(2000)
        self.assertEqual(self.backend.apply.call_count, 4)
        self.assertEqual(reopened.status()['last_error_code'], 'ipfs_recovery_exhausted')


class RepositoryTests(unittest.TestCase):
    def test_private_or_local_repo_cannot_be_silently_published(self):
        public = {'Routing':{'Type':'auto'}, 'Bootstrap':['auto'], 'Provide':{'Enabled':True}}
        manager.require_public(public, False)
        for config, key in [(public, True), ({**public,'Routing':{'Type':'none'}}, False),
                            ({**public,'Provide':{'Enabled':False}}, False),
                            ({**public,'Bootstrap':[]}, False),
                            ({**public,'Swarm':{'AddrFilters':['/ip4/0.0.0.0/ipcidr/0']}}, False)]:
            with self.assertRaises(manager.Rejected): manager.require_public(config, key)

    def test_kubo_043_implicit_public_routing_defaults_are_safe_to_adopt(self):
        # Actual offline `ipfs init --profile server` output omits Routing.Type.
        fresh={'Routing':{'DelegatedRouters':['auto']},'Bootstrap':['auto'],'Provide':{'DHT':{}}}
        manager.require_public(fresh,False)
        manager.require_public({**fresh,'Routing':{'Type':None}},False)
        for routing in ['none','custom','',False]:
            with self.subTest(routing=routing), self.assertRaises(manager.Rejected):
                manager.require_public({**fresh,'Routing':{'Type':routing}},False)

    def test_managed_config_keeps_identity_and_enables_public_providing_without_fetch(self):
        original = {'Identity':{'PeerID':'keep'}, 'Routing':{'Type':'auto'}, 'Bootstrap':['auto']}
        configured = manager.public_config(original, envelope()['config'])
        self.assertEqual(configured['Identity'], original['Identity'])
        self.assertTrue(configured['Gateway']['NoFetch'])
        self.assertEqual(configured['Provide']['Strategy'], 'pinned+unique')
        self.assertEqual(configured['Datastore']['StorageMax'], '21474836480B')
        self.assertNotIn('Gateway', original)

    def test_fixed_compose_only_has_ipfs_and_no_host_control_socket(self):
        model = manager.compose_model('vidra', 'vidra_ipfs_data', 'vidra_default', 4001, 5001, 9090)
        self.assertEqual(set(model['services']), {'ipfs'})
        node = model['services']['ipfs']
        self.assertEqual(node['image'], 'ipfs/kubo:v0.43.0')
        self.assertEqual(node['restart'], 'unless-stopped')
        self.assertNotIn('docker.sock', json.dumps(model))
        self.assertIn('127.0.0.1:5001:5001', node['ports'])
        self.assertIn('127.0.0.1:9090:8080', node['ports'])


class InstallModelTests(unittest.TestCase):
    def test_install_creates_early_boot_directory_rule_before_applying_it(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'tmpfiles.d'
            def apply(args):
                self.assertEqual(args, ['systemd-tmpfiles', '--create', str(root/'vidra-ipfs-control.conf')])
                self.assertEqual((root/'vidra-ipfs-control.conf').read_text(),
                                 'd /run/vidra-ipfs-control 0755 root root -\n')
                self.assertEqual((root/'vidra-ipfs-control.conf').stat().st_mode & 0o777, 0o644)
            command = Mock(side_effect=apply)
            manager.install_runtime_directory(command, root)
            command.assert_called_once()

    def test_failed_early_boot_directory_creation_aborts_installation(self):
        with tempfile.TemporaryDirectory() as directory:
            command = Mock(side_effect=RuntimeError('tmpfiles failed'))
            with self.assertRaisesRegex(RuntimeError, 'tmpfiles failed'):
                manager.install_runtime_directory(command, Path(directory))

    def test_runtime_socket_directory_survives_explicit_stop_for_container_bind_mounts(self):
        import configparser
        unit=configparser.ConfigParser(interpolation=None)
        unit.read(Path(__file__).resolve().parents[1]/'deploy/vidra-ipfs-manager.service')
        self.assertEqual(unit['Service']['RuntimeDirectory'],'vidra-ipfs-control')
        # 'restart' is insufficient: paired backups explicitly stop then start.
        self.assertEqual(unit['Service'].get('RuntimeDirectoryPreserve'),'yes')

    def test_snapshot_resolves_only_fixed_service_storage_network_and_loopback_ports(self):
        stack={'name':'vidra','services':{'api':{'environment':{'PASSWORD':'SECRET'}},'ipfs':{
            'image':manager.IMAGE,'volumes':[{'type':'volume','source':'ipfs_data','target':'/data/ipfs'}],
            'ports':[{'target':4001,'published':'4001','protocol':'tcp'},
                     {'target':4001,'published':'4001','protocol':'udp'},
                     {'target':5001,'published':'5001','host_ip':'127.0.0.1'},
                     {'target':8080,'published':'9090','host_ip':'127.0.0.1'}]}},
            'volumes':{'ipfs_data':{'name':'vidra_ipfs_data'}},'networks':{'default':{'name':'vidra_default'}}}
        result=manager.install_settings(stack,'/var/lib/docker/volumes/vidra_ipfs_data/_data')
        self.assertEqual(result['volume'],'vidra_ipfs_data')
        self.assertNotIn('SECRET',json.dumps(result))
        stack['services']['ipfs']['ports'][2]['host_ip']='0.0.0.0'
        with self.assertRaises(manager.Rejected): manager.install_settings(stack,'/data')

    def test_managed_compose_is_opt_in_and_never_mounts_daemon_socket(self):
        root=Path(__file__).resolve().parents[1]
        overlay=(root/'docker-compose.ipfs-managed.yml').read_text()
        self.assertNotIn('docker.sock',overlay)
        self.assertIn('read_only: true',overlay)
        self.assertIn('create_host_path: false',overlay)
        self.assertIn('IPFS_MANAGER_SOCKET: /run/vidra-ipfs-control/manager.sock',overlay)
        self.assertIn('IPFS_MANAGED_NODE', (root/'deploy/lib.sh').read_text())



class UnixHTTPTests(unittest.TestCase):
    setUp = OperationsTests.setUp
    def test_real_socket_rejects_peers_bad_envelopes_and_serves_acceptance(self):
        path = self.path/'manager.sock'
        server = manager.Server(path, self.control, allowed=lambda _: True)
        thread = threading.Thread(target=server.serve_forever,daemon=True); thread.start()
        self.addCleanup(lambda: (server.shutdown(),server.server_close(),thread.join()))
        def request(method, route, body=None):
            conn = http.client.HTTPConnection('localhost',timeout=2)
            conn.sock = socket.socket(socket.AF_UNIX,socket.SOCK_STREAM); conn.sock.connect(str(path))
            conn.request(method,route,body=json.dumps(body).encode() if body else None,
                         headers={'Content-Type':'application/json'})
            response=conn.getresponse(); result=(response.status,json.loads(response.read())); conn.close()
            return result
        code, data=request('POST','/v1/apply',envelope())
        self.assertEqual(code,202); self.assertEqual(data['operation']['state'],'pending')
        self.assertEqual(request('POST','/v1/restart',envelope())[0],409)
        self.assertEqual(request('GET','/v1/status')[1]['last_operation_sequence'],1)
        self.assertEqual(request('POST','/v1/apply?command=down',envelope())[0],404)
        server.allowed=lambda _: False
        self.assertEqual(request('GET','/v1/status'),(403,{'code':'ipfs_peer_forbidden'}))


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name); self.repo=self.path/'repo'; self.repo.mkdir()
        self.original={'Identity':{'PeerID':'keep'},'Routing':{'Type':'auto'},'Bootstrap':['auto'],
                       'Gateway':{'NoFetch':True},'Provide':{'Enabled':True}}
        (self.repo/'config').write_text(json.dumps(self.original))
        self.node=manager.Node({'repo_dir':str(self.repo),'volume':'vidra_ipfs_data','project':'vidra','rpc_port':5001},self.path)
        self.node.command=Mock(return_value='')
        self.node.container=Mock(return_value={'State':{'Running':True}})

    def test_readiness_failure_restores_previous_config_and_only_ever_targets_ipfs(self):
        self.node.probe=Mock(side_effect=RuntimeError('not ready'))
        with patch.object(manager.time,'sleep'), self.assertRaises(manager.Rejected):
            self.node.apply('apply',envelope())
        self.assertEqual(json.loads((self.repo/'config').read_text()),self.original)
        for call in self.node.command.call_args_list:
            self.assertEqual(call.args[0][-1],'ipfs')
            self.assertNotIn('down',call.args[0])

    def test_crash_after_readiness_keeps_original_until_ledger_commits(self):
        control=manager.Controller(self.path,self.node)
        control.accept('apply',envelope())
        with control.db() as db: db.execute("UPDATE operations SET state='running'")
        self.node.probe=Mock(return_value={'observed_state':'running'})
        self.node.apply('apply',envelope())  # simulated crash before SQLite success
        self.assertTrue(list(self.path.glob('before-*.json')))
        reopened=manager.Controller(self.path,self.node)
        self.node.probe.side_effect=RuntimeError('replay readiness failure')
        with patch.object(manager.time,'sleep'): reopened.process_next()
        self.assertEqual(json.loads((self.repo/'config').read_text()),self.original)
        self.assertEqual(reopened.status()['applied_config_revision'],0)

    def test_crash_after_ledger_commit_cannot_rollback_a_later_recovery_to_old_config(self):
        control=manager.Controller(self.path,self.node)
        control.accept('apply',envelope())
        self.node.probe=Mock(return_value={'observed_state':'running'})
        with patch.object(self.node,'finalize',side_effect=KeyboardInterrupt,create=True):
            with self.assertRaises(KeyboardInterrupt): control.process_next()
        self.assertEqual(control.status()['applied_config_revision'],1)
        self.assertTrue(list(self.path.glob('before-*.json')))
        reopened=manager.Controller(self.path,self.node)
        self.node.probe.side_effect=RuntimeError('failed recovery')
        with patch.object(manager.time,'sleep'): reopened.watchdog(1000)
        self.assertEqual(json.loads((self.repo/'config').read_text())['Datastore']['StorageMax'],'21474836480B')

    def test_finalization_durably_removes_snapshot_only_after_ledger_success(self):
        control=manager.Controller(self.path,self.node)
        control.accept('apply',envelope())
        self.node.probe=Mock(return_value={'observed_state':'running'})
        synchronized=[]
        real_fsync=manager.os.fsync
        def sync(descriptor):
            with control.db() as db: revision=control.get(db,'applied_revision',0)
            synchronized.append((bool(list(self.path.glob('before-*.json'))),revision))
            real_fsync(descriptor)
        with patch.object(manager.os,'fsync',side_effect=sync): control.process_next()
        self.assertEqual(synchronized[-1],(False,1))

    def test_nonempty_unknown_repo_never_runs_init_or_stops_the_node(self):
        (self.repo/'config').unlink(); (self.repo/'datastore').write_text('private data')
        with self.assertRaises(manager.Rejected): self.node.apply('apply',envelope())
        self.node.command.assert_not_called()

    def test_docker_target_cannot_inherit_a_remote_operator_context(self):
        runner=Mock(return_value=Mock(returncode=0,stdout='ok'))
        node=manager.Node(self.node.settings,self.path,runner=runner)
        with patch.dict(manager.os.environ,{'DOCKER_HOST':'tcp://elsewhere:2375','DOCKER_CONTEXT':'remote'}):
            self.assertEqual(node.command(['docker','info']),'ok')
        environment=runner.call_args.kwargs['env']
        self.assertEqual(environment.get('DOCKER_HOST'),'unix:///var/run/docker.sock')
        self.assertNotIn('DOCKER_CONTEXT',environment)

    def test_actual_headroom_is_from_repo_filesystem_and_measurement_failure_is_not_zero(self):
        self.node.container.return_value=None
        result=self.node.probe()
        self.assertEqual(result['observed_state'],'absent')
        self.assertGreater(result['filesystem_free_bytes'],0)
        self.assertIsNone(result['repo_used_bytes'])


if __name__ == '__main__': unittest.main()
