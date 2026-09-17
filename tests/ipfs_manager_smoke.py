#!/usr/bin/env python3
"""Explicit Linux/root/Docker smoke. Uses only uniquely named temporary resources.

Run: sudo python3 tests/ipfs_manager_smoke.py
Kubo's network is internal: this test never publishes content to the Internet.
This is a live integration harness, not part of the stack-free *_test.py suite.
"""
import argparse
import http.client
import http.server
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('ipfs_manager', ROOT/'deploy/ipfs-manager.py')
manager = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(manager)


def command(args):
    result = subprocess.run(args, capture_output=True, text=True, timeout=180)
    if result.returncode:
        raise RuntimeError(f'{args[:3]} failed: {result.stderr[-2000:]}')
    return result.stdout


def cleanup(commands):
    errors=[]
    for args in commands:
        try: command(args)
        except Exception as error: errors.append(str(error))
    if errors: raise RuntimeError('test resource cleanup failed: '+repr(errors))


def ensure_image(image):
    if subprocess.run(['docker','image','inspect',image],capture_output=True,timeout=15).returncode:
        command(['docker','pull',image])


def port():
    with socket.socket() as connection:
        connection.bind(('127.0.0.1', 0))
        return connection.getsockname()[1]


def envelope(sequence, revision=None):
    return {'protocol_version':1, 'operation_id':str(uuid.uuid4()), 'sequence':sequence,
            'config_revision':revision or sequence, 'config':{'enabled':True,
            'budget_bytes':20*1024**3, 'min_free_bytes':20*1024**3,
            'copy_bytes_per_second':2*1024**2, 'workers':1}}


def wait_running(node):
    for _ in range(30):
        try:
            if node.probe()['observed_state'] == 'running': return
        except Exception: pass
        time.sleep(1)
    raise AssertionError('isolated Kubo did not become ready')


def rpc_relay(node, network, listen):
    # Docker internal networks intentionally do not publish ports. Keep Kubo
    # offline and relay only the two read-only probes from host loopback to its
    # test-network address; no extra network, container privilege, or API proxy.
    class Relay(http.server.BaseHTTPRequestHandler):
        def log_message(self,*_): pass
        def do_POST(self):
            connection=None
            try:
                if self.path not in ('/api/v0/id','/api/v0/repo/stat?size-only=true'):
                    self.send_error(404); return
                container=node.container()
                address=container['NetworkSettings']['Networks'][network]['IPAddress']
                connection=http.client.HTTPConnection(address,5001,timeout=3)
                connection.request('POST',self.path,body=b'')
                response=connection.getresponse(); body=response.read(1048577)
                if len(body)>1048576: raise ValueError('oversized probe')
                self.send_response(response.status)
                self.send_header('Content-Type','application/json')
                self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)
            except Exception: self.send_error(503)
            finally:
                if connection: connection.close()
    server=http.server.ThreadingHTTPServer(('127.0.0.1',listen),Relay)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    return server


def lifecycle(directory, name):
    volume, network = name+'-data', name+'-network'
    node = None; relay = None; created_volume = False; created_network = False
    ensure_image(manager.IMAGE)
    try:
        command(['docker','network','create','--internal',network]); created_network=True
        command(['docker','volume','create',volume]); created_volume=True
        repo = Path(json.loads(command(['docker','volume','inspect',volume]))[0]['Mountpoint'])
        assert repo.is_dir(), 'run as Linux root with access to Docker volume mountpoints'
        settings = {'project':name, 'volume':volume, 'network':network, 'repo_dir':str(repo),
                    'swarm_port':port(), 'rpc_port':port(), 'gateway_port':port()}
        manager.SETTINGS = directory
        model=manager.compose_model(name,volume,network,settings['swarm_port'],settings['rpc_port'],settings['gateway_port'])
        # The production swarm can receive peers; the disposable smoke must not.
        model['services']['ipfs']['ports']=[p if p.startswith('127.0.0.1:') else '127.0.0.1:'+p
                                           for p in model['services']['ipfs']['ports'] if not p.endswith(':5001')]
        manager.atomic(directory/'compose.json',json.dumps(model).encode())
        node = manager.Node(settings,directory)
        relay=rpc_relay(node,network,settings['rpc_port'])
        observations=[]
        real_probe=node.probe
        def probe():
            try:
                value=real_probe(); observations.append({'state':value['observed_state']}); return value
            except Exception as error:
                observed={'error_class':type(error).__name__,'code':getattr(error,'code',None),
                          'target_rpc_port':settings['rpc_port']}
                container=node.container()
                if container:
                    observed.update({'running':container['State']['Running'],
                                     'port_bindings':container['HostConfig'].get('PortBindings'),
                                     'network_ports':container['NetworkSettings'].get('Ports')})
                observations.append(observed)
                raise
        node.probe=probe
        control = manager.Controller(directory,node)
        request = envelope(1)
        control.accept('apply',request); control.process_next()
        state = control.status()
        if state['operation']['state'] != 'succeeded':
            # Disposable-node logs only: never dump its config or private identity.
            logs=command(node.compose+['logs','--no-color','--tail','100','ipfs'])
            lines=[line for line in logs.splitlines() if not any(key in line for key in ('PrivKey','PrivateKey','Authorization','Cookie'))]
            print(json.dumps({'failure_status':state,'recent_probes':observations[-8:],
                              'disposable_node_logs':'\n'.join(lines)[-12000:]},indent=2),file=sys.stderr)
        assert state['operation']['state'] == 'succeeded', state
        assert state['observed_state'] == 'running', state
        assert state['repo_used_bytes'] is not None and state['filesystem_free_bytes'] > 0
        original = json.loads((repo/'config').read_text())
        assert original['Gateway']['NoFetch'] is True
        assert original['Datastore']['StorageMax'] == '21474836480B'
        assert control.accept('apply',request)['state'] == 'succeeded'
        control.accept('restart',envelope(2,1)); control.process_next()
        assert control.status()['operation']['state'] == 'succeeded'
        assert json.loads((repo/'config').read_text())['Identity'] == original['Identity']
        # Actual stop/write/start/restore commands, with readiness alone faulted.
        failing = envelope(3,2); failing['config']['budget_bytes'] = 21*1024**3
        with patch.object(node,'probe',side_effect=RuntimeError('injected readiness failure')), patch.object(manager.time,'sleep'):
            control.accept('apply',failing); control.process_next()
        wait_running(node)
        assert control.status()['operation']['state'] == 'failed'
        assert control.status()['applied_config_revision'] == 1
        assert json.loads((repo/'config').read_text()) == original
        # No private/local conversion: failure precedes even a stop command.
        private = dict(original, Routing={'Type':'none'})
        metadata = (repo/'config').stat()
        manager.atomic(repo/'config',json.dumps(private).encode(),(metadata.st_uid,metadata.st_gid))
        before = node.container()['State']['StartedAt']
        control.accept('apply',envelope(4,3)); control.process_next()
        assert control.status()['last_error_code'] == 'ipfs_existing_repo_not_public'
        assert node.container()['State']['StartedAt'] == before
        assert json.loads((repo/'config').read_text()) == private
        return {'apply':True,'durable_idempotence':True,'restart_preserves_identity':True,
                'rollback':True,'private_conversion_refused':True,'no_fetch':True,
                'isolated_network':True,'isolated_readonly_rpc_relay':True,'actual_capacity':True}
    finally:
        if relay: relay.shutdown(); relay.server_close()
        commands=[]
        if node: commands.append(node.compose+['down','--timeout','10'])
        if created_volume: commands.append(['docker','volume','rm',volume])
        if created_network: commands.append(['docker','network','rm',network])
        cleanup(commands)


def gateway(directory, name):
    requests = {'auth':[], 'content':[]}
    class Upstream(http.server.BaseHTTPRequestHandler):
        def log_message(self,*_): pass
        def do_GET(self):
            kind = self.server.kind
            requests[kind].append({'path':self.path,'headers':dict(self.headers)})
            allowed = '/ipfs/public/' in self.headers.get('X-Forwarded-Uri','')
            status = (204 if allowed else 404) if kind == 'auth' else (206 if self.headers.get('Range') else 200)
            self.send_response(status)
            self.send_header('Cache-Control','public, max-age=999')
            self.send_header('Content-Length','0'); self.end_headers()
        do_HEAD = do_GET
    servers=[]; container=name+'-caddy'; created=False
    try:
        for kind in ('auth','content'):
            server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Upstream); server.kind=kind
            threading.Thread(target=server.serve_forever,daemon=True).start(); servers.append(server)
        listen=port()
        config=(ROOT/'deploy/Caddyfile.ipfs-managed.example').read_text()
        linux=hasattr(socket,'SO_PEERCRED')
        origin='127.0.0.1' if linux else 'host.docker.internal'
        address=f'127.0.0.1:{listen}' if linux else ':8080'
        config=config.replace('ipfs.example.com','http://'+address)
        config=config.replace('api:8080',f'{origin}:{servers[0].server_port}')
        config=config.replace('ipfs:8080',f'{origin}:{servers[1].server_port}')
        (directory/'Caddyfile').write_text('{\n admin off\n}\n'+config)
        image='caddy:2.11.4-alpine'
        ensure_image(image)
        network=['--network','host'] if linux else ['-p',f'127.0.0.1:{listen}:8080']
        command(['docker','create','--name',container,'--memory','128m','--cpus','0.25',*network,image,
                 'caddy','run','--config','/etc/caddy/Caddyfile','--adapter','caddyfile'])
        created=True
        command(['docker','cp',str(directory/'Caddyfile'),container+':/etc/caddy/Caddyfile'])
        command(['docker','start',container])
        def request(method,path,headers=None):
            connection=http.client.HTTPConnection('127.0.0.1',listen,timeout=3)
            try:
                connection.request(method,path,headers=headers or {})
                response=connection.getresponse(); response.read()
                return response.status,dict(response.getheaders())
            finally: connection.close()
        for _ in range(30):
            try: request('GET','/ready'); break
            except OSError: time.sleep(.2)
        else: raise AssertionError('isolated Caddy did not start')
        code,headers=request('GET','/ipfs/public/segment?part=1',{
            'Authorization':'test-only-token','Cookie':'test-only-cookie','Range':'bytes=0-7',
            'X-Forwarded-Uri':'/ipfs/private/spoof','X-Forwarded-Method':'DELETE'})
        assert code == 206, code
        assert headers.get('Cache-Control') == 'no-store', headers
        for kind in requests:
            observed=requests[kind][-1]['headers']
            assert not observed.get('Authorization') and not observed.get('Cookie'), (kind,observed)
        assert requests['auth'][-1]['headers']['X-Forwarded-Uri'] == '/ipfs/public/segment?part=1'
        assert requests['auth'][-1]['headers']['X-Forwarded-Method'] == 'GET'
        assert requests['content'][-1]['headers']['Range'] == 'bytes=0-7'
        count=len(requests['content'])
        code,headers=request('GET','/ipfs/private/segment')
        assert code == 404 and headers.get('Cache-Control') == 'no-store', (code,headers)
        assert len(requests['content']) == count
        count_auth=len(requests['auth'])
        code,headers=request('POST','/ipfs/public/segment')
        assert code == 404 and headers.get('Cache-Control') == 'no-store', (code,headers)
        assert len(requests['auth']) == count_auth and len(requests['content']) == count
        assert request('HEAD','/ipfs/public/segment')[0] == 200
        return {'authorized_range':True,'denial_blocks_content':True,'headers_not_spoofable':True,
                'credentials_stripped':True,'all_responses_no_store':True,'get_head_only':True}
    finally:
        try:
            if created: cleanup([['docker','rm','-f',container]])
        finally:
            for server in servers: server.shutdown(); server.server_close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gateway-only',action='store_true',help='portable Caddy regression only; does not certify node lifecycle')
    args=parser.parse_args()
    if not args.gateway_only and (os.geteuid() != 0 or not hasattr(socket,'SO_PEERCRED')):
        raise SystemExit('requires Linux root and a local Docker daemon; refusing to skip')
    name='vidra-ipfs-smoke-'+uuid.uuid4().hex[:10]
    with tempfile.TemporaryDirectory(prefix=name) as temporary:
        directory=Path(temporary)
        # Gateway runs first, so header/authorization failures are fast.
        result={'gateway':gateway(directory,name)}
        if not args.gateway_only: result['node']=lifecycle(directory,name)
        print(json.dumps({'ok':True,**result},indent=2))


if __name__ == '__main__': main()
