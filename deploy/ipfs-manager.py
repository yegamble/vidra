#!/usr/bin/env python3
"""Root-owned, Unix-only control of one fixed Compose IPFS service. No DB access."""
import argparse
import contextlib
import copy
import datetime
import fcntl
import http.client
import http.server
import json
import os
from pathlib import Path
import re
import socket
import socketserver
import sqlite3
import stat
import struct
import subprocess
import tempfile
import threading
import time
import uuid

IMAGE = 'ipfs/kubo:v0.43.0'
# Never inherit a root user's remote Docker context or caller-selected daemon.
DOCKER_ENV = {'PATH':'/usr/local/bin:/usr/bin:/bin', 'DOCKER_HOST':'unix:///var/run/docker.sock'}
SOCKET = Path('/run/vidra-ipfs-control/manager.sock')
STATE = Path('/var/lib/vidra-ipfs-control')
SETTINGS = Path('/etc/vidra-ipfs-control')
BOUNDS = {'budget_bytes': (1024**2, 1024**5), 'min_free_bytes': (0, 1024**5),
          'copy_bytes_per_second': (65536, 1024**3), 'workers': (1, 8)}


class Rejected(Exception):
    def __init__(self, code='ipfs_invalid_request', status=400):
        self.code, self.status = code, status
        super().__init__(code)


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def decode(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result: raise Rejected()
            result[key] = value
        return result
    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(Rejected()))
    except (ValueError, UnicodeError):
        raise Rejected() from None


def integer(value, low, high):
    return type(value) is int and low <= value <= high


def validate(body):
    keys = {'protocol_version', 'operation_id', 'sequence', 'config_revision', 'config'}
    if not isinstance(body, dict) or set(body) != keys: raise Rejected()
    if type(body['protocol_version']) is not int or body['protocol_version'] != 1: raise Rejected()
    for key in ('sequence', 'config_revision'):
        if not integer(body[key], 1, 2**63 - 1): raise Rejected()
    try:
        if str(uuid.UUID(body['operation_id'])) != body['operation_id']: raise Rejected()
    except (ValueError, TypeError, AttributeError): raise Rejected() from None
    config = body['config']
    if not isinstance(config, dict) or set(config) != set(BOUNDS) | {'enabled'}: raise Rejected()
    if type(config['enabled']) is not bool: raise Rejected()
    for key, bounds in BOUNDS.items():
        if not integer(config[key], *bounds): raise Rejected()
    return copy.deepcopy(body)


def operation(row):
    return {'id': row['id'], 'sequence': row['sequence'], 'config_revision': row['revision'], 'state': row['state']}


class Controller:
    def __init__(self, directory, backend):
        self.directory, self.backend = Path(directory), backend
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lock = threading.Lock()
        self.observation = self.unknown()
        with self.db() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS operations (
                sequence INTEGER PRIMARY KEY, id TEXT NOT NULL UNIQUE, revision INTEGER NOT NULL,
                kind TEXT NOT NULL, envelope TEXT NOT NULL, state TEXT NOT NULL, error TEXT);
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);''')
            # The fixed apply is replayable after a power loss; sequence/id never change.
            db.execute("UPDATE operations SET state='pending' WHERE state='running'")

    @contextlib.contextmanager
    def db(self):
        connection = sqlite3.connect(self.directory / 'operations.sqlite3', timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA synchronous=FULL')
        try:
            with connection: yield connection
        finally: connection.close()

    @staticmethod
    def unknown():
        return {'observed_state': 'unknown', 'repo_used_bytes': None,
                'filesystem_free_bytes': None, 'observed_at': now()}

    @staticmethod
    def get(db, key, default=None):
        row = db.execute('SELECT value FROM metadata WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else default

    @staticmethod
    def put(db, key, value):
        db.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)', (key, json.dumps(value)))

    def accept(self, kind, body):
        if kind not in ('apply', 'restart'): raise Rejected()
        body = validate(body)
        encoded = json.dumps(body, sort_keys=True, separators=(',', ':'))
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT * FROM operations WHERE id=?', (body['operation_id'],)).fetchone()
            if existing:
                if existing['kind'] != kind or existing['envelope'] != encoded:
                    raise Rejected('ipfs_operation_conflict', 409)
                return operation(existing)
            latest = db.execute('SELECT * FROM operations ORDER BY sequence DESC LIMIT 1').fetchone()
            if latest and (body['sequence'] <= latest['sequence'] or body['config_revision'] < latest['revision']):
                raise Rejected('ipfs_sequence_conflict', 409)
            same_revision = db.execute('SELECT envelope FROM operations WHERE revision=? LIMIT 1', (body['config_revision'],)).fetchone()
            if same_revision and json.loads(same_revision[0])['config'] != body['config']:
                raise Rejected('ipfs_config_conflict',409)
            count = db.execute("SELECT COUNT(*) FROM operations WHERE state IN ('pending','running')").fetchone()[0]
            if count >= 128: raise Rejected('ipfs_manager_busy', 503)
            db.execute('INSERT INTO operations VALUES (?,?,?,?,?,?,NULL)',
                       (body['sequence'], body['operation_id'], body['config_revision'], kind, encoded, 'pending'))
            self.put(db, 'recovery', {'attempts': 0, 'after': 0})
            return operation(db.execute('SELECT * FROM operations WHERE id=?', (body['operation_id'],)).fetchone())

    def process_next(self):
        if not self.lock.acquire(blocking=False): return False
        try:
            with self.db() as db:
                row = db.execute("SELECT * FROM operations WHERE state='pending' ORDER BY sequence LIMIT 1").fetchone()
                if not row: return False
                db.execute("UPDATE operations SET state='running' WHERE sequence=?", (row['sequence'],))
            error = None
            try:
                self.finalize_committed()
                self.backend.apply(row['kind'], json.loads(row['envelope']))
            except Rejected as exc: error = exc.code
            except Exception: error = 'ipfs_apply_failed'
            with self.db() as db:
                db.execute('UPDATE operations SET state=?,error=? WHERE sequence=?',
                           ('failed' if error else 'succeeded', error, row['sequence']))
                self.put(db, 'last_error_code', error)
                if not error:
                    self.put(db, 'applied_revision', row['revision'])
                    self.put(db, 'last_working', json.loads(row['envelope']))
            if not error:
                try: self.finalize_committed()
                except Exception:
                    with self.db() as db: self.put(db,'last_error_code','ipfs_snapshot_cleanup_failed')
            self.observe()
            return True
        finally: self.lock.release()

    def finalize_committed(self):
        # A crash before this commit needs the original rollback snapshot; a
        # crash after it must never let that older config undo confirmed success.
        with self.db() as db: applied = self.get(db,'last_working')
        if applied: self.backend.finalize(applied)

    def observe(self):
        try: self.observation = self.backend.probe()
        except Exception: self.observation = self.unknown()

    def status(self):
        with self.db() as db:
            row = db.execute('SELECT * FROM operations ORDER BY sequence DESC LIMIT 1').fetchone()
            return {'protocol_version': 1, **self.observation,
                    'applied_config_revision': self.get(db, 'applied_revision', 0),
                    'last_operation_id': row['id'] if row else None,
                    'last_operation_sequence': row['sequence'] if row else 0,
                    'operation': operation(row) if row else None,
                    'last_error_code': self.get(db, 'last_error_code')}

    def watchdog(self, clock=None):
        clock = time.time() if clock is None else clock
        self.observe()
        with self.db() as db:
            desired = self.get(db, 'last_working')
            pending = db.execute("SELECT 1 FROM operations WHERE state IN ('pending','running') LIMIT 1").fetchone()
            recovery = self.get(db, 'recovery', {'attempts': 0, 'after': 0})
        if not desired or pending or self.observation['observed_state'] == 'running': return
        if recovery['attempts'] >= 3:
            with self.db() as db: self.put(db, 'last_error_code', 'ipfs_recovery_exhausted')
            return
        if clock < recovery['after']: return
        if not self.lock.acquire(blocking=False): return
        try:
            # Durable lifetime budget, reset only by a new explicit admin operation.
            # Restarting this daemon must not turn three failed attempts into a loop.
            recovery = {'attempts': recovery['attempts'] + 1, 'after': clock + 60 * 2**recovery['attempts']}
            with self.db() as db: self.put(db, 'recovery', recovery)
            try:
                self.finalize_committed()
                self.backend.apply('restart', desired)
                self.backend.finalize(desired)
            except Exception:
                with self.db() as db: self.put(db, 'last_error_code', 'ipfs_recovery_failed')
            self.observe()
        finally: self.lock.release()


def require_public(config, private_key):
    denied = {'/ip4/0.0.0.0/ipcidr/0', '/ip6/::/ipcidr/0'}
    # Kubo 0.43 uses optionalString: omitted/null means the public auto default.
    if (private_key or config.get('Routing', {}).get('Type') not in (None, 'auto', 'dht', 'dhtclient')
        or not config.get('Bootstrap') or config.get('Provide', {}).get('Enabled') is False
        or denied.intersection(config.get('Swarm', {}).get('AddrFilters', []))):
        raise Rejected('ipfs_existing_repo_not_public', 409)


def public_config(original, policy):
    config = copy.deepcopy(original)
    for section, key, value in [('Gateway','NoFetch',True), ('Routing','Type','auto'),
                                ('Provide','Enabled',True), ('Provide','Strategy','pinned+unique'),
                                ('Datastore','StorageMax',f"{policy['budget_bytes']}B")]:
        config.setdefault(section, {})[key] = value
    return config


def compose_model(project, volume, network, swarm, rpc, gateway):
    return {'name': project, 'services': {'ipfs': {
        'image': IMAGE, 'restart': 'unless-stopped', 'cpus': '1.0', 'mem_limit': '1g',
        'environment': {'IPFS_PROFILE':'server', 'IPFS_TELEMETRY':'off'},
        'ports':[f'{swarm}:4001', f'{swarm}:4001/udp', f'127.0.0.1:{rpc}:5001', f'127.0.0.1:{gateway}:8080'],
        'volumes':['ipfs_data:/data/ipfs'], 'networks':['default'],
        'logging':{'driver':'json-file','options':{'max-size':'10m','max-file':'5'}},
        'healthcheck':{'test':['CMD','ipfs','--api=/ip4/127.0.0.1/tcp/5001','id'],
                       'interval':'10s','timeout':'5s','retries':5,'start_period':'30s'}}},
        'volumes':{'ipfs_data':{'external':True,'name':volume}},
        'networks':{'default':{'external':True,'name':network}}}


def install_settings(stack, repo_dir):
    """Extract a secret-free fixed target; never save the rendered application env."""
    node = stack['services']['ipfs']
    project = stack['name']
    volume = stack['volumes']['ipfs_data']['name']
    network = stack['networks']['default']['name']
    for value in (project, volume, network):
        if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}', value): raise Rejected()
    if not re.fullmatch(r'/[a-zA-Z0-9_./-]+', repo_dir): raise Rejected()
    if node['image'] != IMAGE: raise Rejected('ipfs_image_mismatch')
    mounts = [v for v in node['volumes'] if v['target'] == '/data/ipfs']
    if len(mounts) != 1 or mounts[0]['type'] != 'volume' or mounts[0]['source'] != 'ipfs_data': raise Rejected()
    def port(target, protocol='tcp'):
        matches = [p for p in node['ports'] if p['target'] == target and p.get('protocol','tcp') == protocol]
        if len(matches) != 1: raise Rejected()
        item = matches[0]
        value = int(item['published'])
        if not 1024 <= value <= 65535: raise Rejected()
        if target != 4001 and item.get('host_ip') != '127.0.0.1': raise Rejected('ipfs_rpc_must_be_loopback')
        return value
    swarm = port(4001)
    if swarm != port(4001,'udp'): raise Rejected()
    return {'project':project,'volume':volume,'network':network,'repo_dir':repo_dir,
            'swarm_port':swarm,'rpc_port':port(5001),'gateway_port':port(8080)}


def install(project_dir, env_file):
    if os.geteuid() != 0 or not hasattr(socket,'SO_PEERCRED'): raise SystemExit('requires Linux root')
    root = Path(project_dir).resolve()
    def command(args):
        return subprocess.run(args,check=True,text=True,stdout=subprocess.PIPE,timeout=120,env=DOCKER_ENV).stdout
    # A render is read only. Its complete output may contain secrets, so it is
    # kept in memory and discarded after extracting the one fixed public node.
    rendered = json.loads(command(['docker','compose','--project-directory',str(root),
        '-f',str(root/'docker-compose.yml'),'-f',str(root/'docker-compose.prod.yml'),
        '--env-file',str(Path(env_file).resolve()),'--profile','ipfs','config','--format','json']))
    # Validate every field BEFORE creating a volume or installing anything.
    draft = install_settings(rendered,'/pending')
    volume = draft['volume']
    inspected = subprocess.run(['docker','volume','inspect',volume],capture_output=True,text=True,timeout=15,env=DOCKER_ENV)
    if inspected.returncode:
        command(['docker','volume','create','--label','com.docker.compose.project='+draft['project'],
                 '--label','com.docker.compose.volume=ipfs_data',volume])
        inspected = subprocess.run(['docker','volume','inspect',volume],capture_output=True,text=True,check=True,timeout=15,env=DOCKER_ENV)
    disk = json.loads(inspected.stdout)[0]
    if disk['Driver'] != 'local' or disk.get('Options'):
        raise SystemExit('managed IPFS requires a local Docker volume with measurable host headroom')
    labels = disk.get('Labels') or {}
    if labels.get('com.docker.compose.project',draft['project']) != draft['project']:
        raise SystemExit('IPFS volume belongs to another Compose project')
    config = install_settings(rendered,disk['Mountpoint'])
    if SETTINGS.exists() and SETTINGS.is_symlink(): raise SystemExit('manager directory must not be a symlink')
    SETTINGS.mkdir(mode=0o700,exist_ok=True)
    os.chown(SETTINGS,0,0); os.chmod(SETTINGS,0o700)
    existing = SETTINGS/'manager.json'
    if existing.exists() and json.loads(existing.read_text()) != config:
        raise SystemExit('installed manager target differs; refuse automatic retargeting')
    command(['docker','pull',IMAGE])
    atomic(existing,json.dumps(config,indent=2).encode())
    model = compose_model(config['project'],config['volume'],config['network'],
                          config['swarm_port'],config['rpc_port'],config['gateway_port'])
    atomic(SETTINGS/'compose.json',json.dumps(model,indent=2).encode())
    program = Path('/usr/local/lib/vidra/ipfs-manager.py')
    program.parent.mkdir(parents=True,exist_ok=True)
    atomic(program,Path(__file__).read_bytes())
    unit = (root/'deploy/vidra-ipfs-manager.service').read_text().replace('@@IPFS_REPO@@',config['repo_dir'])
    atomic(Path('/etc/systemd/system/vidra-ipfs-manager.service'),unit.encode())
    command(['systemctl','daemon-reload'])
    command(['systemctl','enable','vidra-ipfs-manager.service'])
    command(['systemctl','restart','vidra-ipfs-manager.service'])
    command(['systemctl','is-active','--quiet','vidra-ipfs-manager.service'])
    print('Installed IPFS manager; no node is started or published until an admin apply operation.')


def atomic(path, body, owner=None):
    path = Path(path)
    descriptor, temporary_name = tempfile.mkstemp(prefix=path.name + '.', dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(body); stream.flush(); os.fsync(stream.fileno())
            if owner: os.fchown(stream.fileno(), *owner)
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try: os.fsync(directory)
        finally: os.close(directory)
    finally:
        if temporary.exists(): temporary.unlink()


class Node:
    def __init__(self, settings, directory=STATE, runner=subprocess.run):
        self.settings, self.directory, self.runner = settings, Path(directory), runner
        self.repo = Path(settings['repo_dir'])
        self.compose = ['docker','compose','--project-name',settings['project'], '-f',str(SETTINGS/'compose.json')]

    def command(self, args, timeout=30):
        result = self.runner(args, capture_output=True, text=True, timeout=timeout,
                             env=DOCKER_ENV)
        if result.returncode: raise Rejected('ipfs_node_command_failed', 503)
        return result.stdout

    def container(self):
        ids = self.command(self.compose + ['ps','--all','-q','ipfs'], 10).split()
        if not ids: return None
        if len(ids) != 1 or not re.fullmatch('[a-f0-9]{12,64}', ids[0]): raise Rejected('ipfs_node_identity_invalid',503)
        node = json.loads(self.command(['docker','inspect',ids[0]],10))[0]
        labels = node['Config'].get('Labels', {})
        if labels.get('com.docker.compose.project') != self.settings['project'] or labels.get('com.docker.compose.service') != 'ipfs':
            raise Rejected('ipfs_node_identity_invalid',503)
        data_mounts = [m for m in node.get('Mounts',[]) if m.get('Destination') == '/data/ipfs']
        if node['Config'].get('Image') != IMAGE or len(data_mounts) != 1 or data_mounts[0].get('Name') != self.settings['volume']:
            raise Rejected('ipfs_node_identity_invalid',503)
        return node

    def rpc(self, endpoint):
        connection = http.client.HTTPConnection('127.0.0.1', self.settings['rpc_port'], timeout=3)
        try:
            connection.request('POST', '/api/v0/' + endpoint, body=b'')
            response = connection.getresponse()
            data = response.read(1048577)
            if response.status != 200 or len(data) > 1048576: raise Rejected('ipfs_rpc_unavailable',503)
            return json.loads(data)
        finally: connection.close()

    def config(self):
        if (self.repo/'config').is_symlink() or (self.repo/'swarm.key').exists():
            raise Rejected('ipfs_existing_repo_not_public',409)
        raw = (self.repo/'config').read_bytes()
        if len(raw) > 1048576: raise Rejected('ipfs_config_invalid',503)
        config = json.loads(raw)
        require_public(config, False)
        return config, raw

    def probe(self):
        info = Controller.unknown()
        filesystem = os.statvfs(self.repo)
        info['filesystem_free_bytes'] = filesystem.f_bavail * filesystem.f_frsize
        node = self.container()
        if not node: info['observed_state'] = 'absent'
        elif not node['State']['Running']: info['observed_state'] = 'stopped'
        elif node['State'].get('OOMKilled') or node['State'].get('Health',{}).get('Status') == 'unhealthy':
            info['observed_state'] = 'unhealthy'
        else:
            config, _ = self.config()
            self.rpc('id')
            if config.get('Gateway',{}).get('NoFetch') is not True: raise Rejected('ipfs_gateway_fetch_enabled',503)
            info['observed_state'] = 'running'
            used = self.rpc('repo/stat?size-only=true').get('RepoSize')
            info['repo_used_bytes'] = used if integer(used,0,2**63-1) else None
        info['observed_at'] = now()
        return info

    def finalize(self, envelope):
        backup = self.directory / ('before-' + envelope['operation_id'] + '.json')
        if not backup.exists(): return
        backup.unlink()
        directory = os.open(backup.parent, os.O_RDONLY)
        try: os.fsync(directory)
        finally: os.close(directory)

    def apply(self, kind, envelope):
        policy = envelope['config']
        backup = self.directory / ('before-' + envelope['operation_id'] + '.json')
        if not (self.repo/'config').exists():
            # Only a genuinely empty volume may be initialized. Never delete or
            # republish an unknown persisted repo, even if its config is missing.
            if any(self.repo.iterdir()): raise Rejected('ipfs_existing_repo_not_public',409)
            self.command(['docker','run','--rm','--network','none','-e','IPFS_PROFILE=server',
                          '-e','IPFS_TELEMETRY=off','-v',self.settings['volume']+':/data/ipfs', IMAGE,'version'],90)
        configured, original = self.config()
        node = self.container()
        previous = {'config':json.loads(original), 'running': bool(node and node['State']['Running'])}
        if backup.exists(): previous = json.loads(backup.read_text())
        else: atomic(backup, json.dumps(previous).encode())
        metadata = (self.repo/'config').stat()
        owner = (metadata.st_uid,metadata.st_gid)
        try:
            self.command(self.compose + ['stop','-t','20','ipfs'])
            atomic(self.repo/'config',json.dumps(public_config(configured,policy),indent=2).encode(),owner)
            self.command(self.compose + ['up','-d','--no-deps','--no-build','--pull','never','ipfs'],90)
            deadline = time.monotonic() + 45
            for _ in range(30):
                if time.monotonic() >= deadline: break
                try:
                    if self.probe()['observed_state'] == 'running':
                        return  # Controller finalizes only after the SQLite success commit.
                except Exception: pass
                time.sleep(1)
            raise Rejected('ipfs_readiness_timeout',503)
        except Exception:
            # Bounded rollback, same service and same volume. No stack-wide down.
            try:
                self.command(self.compose + ['stop','-t','20','ipfs'])
                atomic(self.repo/'config',json.dumps(previous['config'],indent=2).encode(),owner)
                if previous['running']:
                    self.command(self.compose + ['up','-d','--no-deps','--no-build','--pull','never','ipfs'],90)
            except Exception: raise Rejected('ipfs_rollback_failed',503) from None
            raise


def peer_allowed(connection, uid=10001, gid=10001):
    # Linux SO_PEERCRED authenticates the process, independent of HTTP headers.
    _, actual_uid, actual_gid = struct.unpack('3i', connection.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
    return actual_uid == 0 or (actual_uid == uid and actual_gid == gid)


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_): pass  # Do not echo request bodies, paths, or headers.
    def setup(self):
        super().setup(); self.connection.settimeout(3)
    def reply(self, status, body):
        data = json.dumps(body).encode()
        self.send_response(status); self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(data))); self.send_header('Connection','close'); self.end_headers()
        self.wfile.write(data)
    def authorized(self):
        if not self.server.allowed(self.connection):
            self.reply(403,{'code':'ipfs_peer_forbidden'}); return False
        return True
    def do_GET(self):
        if not self.authorized(): return
        if self.path != '/v1/status': self.reply(404,{'code':'ipfs_not_found'}); return
        self.reply(200,self.server.control.status())
    def do_POST(self):
        if not self.authorized(): return
        if self.path not in ('/v1/apply','/v1/restart'): self.reply(404,{'code':'ipfs_not_found'}); return
        try:
            length = int(self.headers.get('Content-Length','-1'))
            if not 0 < length <= 8192 or self.headers.get('Transfer-Encoding'): raise Rejected()
            if self.headers.get('Content-Type','').split(';')[0] != 'application/json': raise Rejected()
            body = decode(self.rfile.read(length))
            self.reply(202,{'operation':self.server.control.accept(self.path.rsplit('/',1)[1],body)})
        except Rejected as exc: self.reply(exc.status,{'code':exc.code})
        except (ValueError, TimeoutError): self.reply(400,{'code':'ipfs_invalid_request'})
        except Exception: self.reply(503,{'code':'ipfs_manager_unavailable'})


class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True
    def __init__(self, path, control, allowed=peer_allowed):
        self.control, self.allowed = control, allowed
        self.slots = threading.BoundedSemaphore(16)
        super().__init__(str(path), Handler)
    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False): request.close(); return
        super().process_request(request,address)
    def process_request_thread(self, request, address):
        try: super().process_request_thread(request,address)
        finally: self.slots.release()


def serve():
    if os.geteuid() != 0 or not hasattr(socket,'SO_PEERCRED'): raise SystemExit('requires Linux root')
    for path in (SETTINGS/'manager.json', SETTINGS/'compose.json'):
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != 0 or metadata.st_mode & 0o022:
            raise SystemExit('manager configuration must be root-owned and not writable by others')
    settings = json.loads((SETTINGS/'manager.json').read_text())
    STATE.mkdir(mode=0o700,exist_ok=True)
    with (STATE/'manager.lock').open('w') as lease:
        fcntl.flock(lease,fcntl.LOCK_EX | fcntl.LOCK_NB)
        control = Controller(STATE, Node(settings))
        control.observe()
        SOCKET.parent.mkdir(mode=0o755,exist_ok=True)
        if SOCKET.exists():
            if not stat.S_ISSOCK(SOCKET.lstat().st_mode): raise SystemExit('socket path is not a socket')
            SOCKET.unlink()
        with Server(SOCKET,control) as server:
            os.chown(SOCKET,0,10001); os.chmod(SOCKET,0o660)
            threading.Thread(target=server.serve_forever,daemon=True).start()
            while True:
                if not control.process_next(): control.watchdog(); time.sleep(10)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--install',action='store_true')
    parser.add_argument('--project-dir')
    parser.add_argument('--env-file')
    args = parser.parse_args()
    if args.install:
        if not args.project_dir or not args.env_file: parser.error('install requires project-dir and env-file')
        install(args.project_dir,args.env_file)
    else:
        if args.project_dir or args.env_file: parser.error('target paths are install-only')
        serve()
