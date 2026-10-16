"""Run unchanged published backup/restore scripts on an isolated synthetic VM."""
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import tarfile
import urllib.request

from blank_server_smoke import require
import release_acceptance as runtime
import recovery_release_acceptance as recovery
from sealed_recovery_route import internal_origin, unpublished

INSTALL = runtime.INSTALL
SAFE = {'VIDRA_ENV': 'production', 'STORAGE_BACKEND': 'local', 'MAIL_ENABLED': 'false',
        'DEV_MAIL_CAPTURE_ENABLED': 'false', 'FEDERATION_ENABLED': 'false', 'OAUTH_PROVIDERS': '',
        'OIDC_ALLOW_PRIVATE_ISSUERS': 'false', 'TRANSCODING_ENABLED': 'false',
        'MALWARE_SCAN_MODE': 'disabled', 'CLAMAV_ADDR': '',
        'VIDRA_TLS_MODE': 'external', 'VIDRA_COMPOSE_PROFILES': 'core frontend'}
SERVICES = ('api', 'search', 'frontend', 'postgres', 'redis')


def set_values(text, values):
    for key, value in values.items():
        require(re.fullmatch(r'[A-Z][A-Z0-9_]*', key) and '\n' not in value and '\r' not in value,
                'invalid fixture setting')
        text, count = re.subn(r'(?m)^' + key + r'=.*$', key + '=' + value, text)
        require(count <= 1, 'duplicate fixture setting')
        if not count:
            text = text.rstrip('\n') + '\n' + key + '=' + value + '\n'
    return text


def extract_bundle(bundle, destination):
    require(not destination.exists(), 'existing install refused')
    with tarfile.open(bundle) as archive:
        for member in archive.getmembers():
            path = Path(member.name)
            require(not path.is_absolute() and '..' not in path.parts
                    and (member.isfile() or member.isdir()), 'invalid published bundle member')
        destination.mkdir(mode=0o700)
        archive.extractall(destination, filter='data')


def check_isolation(model):
    api = model['services']['api']
    for key in ('VIDRA_ENV', 'STORAGE_BACKEND', 'MAIL_ENABLED', 'DEV_MAIL_CAPTURE_ENABLED',
                'FEDERATION_ENABLED', 'OAUTH_PROVIDERS', 'MALWARE_SCAN_MODE', 'CLAMAV_ADDR'):
        require(str(api['environment'].get(key, '')).lower() == SAFE[key], 'unsafe fixture configuration')
    require(model['networks']['default'].get('internal') is True, 'external fixture network refused')
    for service in model['services'].values():
        require(not service.get('network_mode') and set(service.get('networks', {})) <= {'default'},
                'alternate fixture network refused')


class Host(runtime.Recorder):
    def __init__(self, stage, record, candidate):
        super().__init__(stage)
        self.record, self.candidate = record, candidate
        self.env = {'PATH': os.environ['PATH'], 'HOME': str(self.private / 'home'), 'LANG': 'C.UTF-8',
                    'COMPOSE_PROJECT_NAME': 'vidra-synthetic-sealed', 'READY_TIMEOUT': '600',
                    'API_CPUS': '2.0', 'API_MEM_LIMIT': '1536m', 'ENV_FILE': 'env/production.env'}
        Path(self.env['HOME']).mkdir(mode=0o700)
        self.env['DOCKER_CONFIG'] = str(self.private / 'docker')
        Path(self.env['DOCKER_CONFIG']).mkdir(mode=0o700)

    def failure_diagnostics(self):
        """Fresh, bounded read-only probes; never export Docker text or HTTP bodies."""
        facts = {}
        try:
            code = self.readyz_status(timeout=2)
            if code is None or type(code) is int and 100 <= code <= 599:
                facts['readyz_status'] = 0 if code is None else code
        except Exception:
            pass
        try:
            output = self.run(['bash', 'deploy/compose.sh', 'ps', '--all', '--format',
                '{{.Service}}\t{{.State}}\t{{.Health}}', *SERVICES], 'failure-service-states', timeout=10)
            observed = {}
            for line in output.splitlines():
                service, state, health = line.split('\t')
                require(service in SERVICES and service not in observed, 'unknown service observation')
                require(state in {'created', 'running', 'paused', 'restarting', 'removing', 'exited', 'dead'}
                        and health in {'', 'starting', 'healthy', 'unhealthy'}, 'unknown state observation')
                observed[service] = (health or 'running') if state == 'running' else (
                    'restarting' if state == 'restarting' else 'stopped')
            facts['services'] = {service: observed.get(service, 'missing') for service in SERVICES}
        except Exception:
            pass  # Unavailable or malformed observations never become healthy/missing facts.
        return facts

    def api_origin(self, timeout=5):
        cid = self.run(['bash', 'deploy/compose.sh', 'ps', '-q', 'api'], 'fixture-api-current', timeout=timeout).strip()
        require(re.fullmatch(r'[0-9a-f]{64}', cid), 'current API container required')
        containers = json.loads(self.run(['docker', 'inspect', cid], 'fixture-api-route', timeout=timeout))
        require(len(containers) == 1 and containers[0]['Id'] == cid, 'stale API container')
        name = self.env['COMPOSE_PROJECT_NAME'] + '_default'
        networks = json.loads(self.run(['docker', 'network', 'inspect', name], 'fixture-api-network', timeout=timeout))
        require(len(networks) == 1, 'one fixture network required')
        return internal_origin(containers[0], networks[0], self.env['COMPOSE_PROJECT_NAME'])

    def readyz_status(self, timeout=5):
        connection = http.client.HTTPConnection(self.api_origin(timeout=timeout).removeprefix('http://'), timeout=timeout)
        try:
            connection.request('GET', '/readyz')
            return connection.getresponse().status  # No redirects, body reads or proxy changes.
        except (OSError, http.client.HTTPException):
            return None
        finally:
            connection.close()

    def install(self):
        assets = self.private / 'assets'
        assets.mkdir(mode=0o700)
        tag = self.record['release']
        for name in ('SHA256SUMS', f'vidra-bundle_{tag}.tar.gz', f'vidra_{tag}_linux_amd64'):
            asset = self.candidate['assets'][name]
            with urllib.request.urlopen(asset['url'], timeout=120) as response:
                data = response.read(256 * 1024 * 1024 + 1)
            require(len(data) <= 256 * 1024 * 1024 and hashlib.sha256(data).hexdigest() == asset['sha256'],
                    'published asset checksum differs')
            (assets / name).write_bytes(data)
        extract_bundle(assets / f'vidra-bundle_{tag}.tar.gz', INSTALL)
        manifest = dict(line.split('=', 1) for line in (INSTALL / 'vidra-bundle.manifest').read_text().splitlines()
                        if '=' in line and not line.startswith('#'))
        schema = manifest.get('core_schema_version', '')
        require(manifest.get('tag') == tag and manifest.get('meta_commit') == self.record['meta_commit']
                and manifest.get('core_commit') == self.record['components']['core']['commit']
                and re.fullmatch(r'[0-9]+', schema) and int(schema) == self.record['core_schema_version'], 'bundle provenance differs')
        self.cli = assets / f'vidra_{tag}_linux_amd64'
        self.cli.chmod(0o700)
        self.script_hashes = {name: runtime.sha(INSTALL / name) for name in ('deploy/backup.sh', 'deploy/restore.sh', 'deploy/lib.sh')}

    def configure(self):
        self.run([str(self.cli), 'setup', '--non-interactive', '--yes', '--domain', 'https://synthetic-recovery.invalid',
                  '--instance-name', 'Synthetic sealed recovery', '--registration', 'closed', '--tls-mode', 'internal',
                  '--storage', 'local', '--release-tag', self.record['release'], '--template', 'env/production.env.example'], 'fixture-setup')
        path = INSTALL / 'env/production.env'
        tags = {'VIDRA_' + role.upper() + '_TAG': component['tag'] for role, component in self.record['components'].items()}
        path.write_text(set_values(path.read_text(), {**SAFE, **tags}))
        path.chmod(0o600)

    def pin_and_check(self):
        path = INSTALL / 'docker-compose.prod.yml'
        text = runtime.pin_images(path.read_text(), self.candidate)
        require('\nnetworks:' not in text, 'review new published network definitions')
        path.write_text(text + '\nnetworks:\n  default:\n    internal: true\n')
        model = json.loads(self.compose('config', '--format', 'json'))
        check_isolation(model)
        for service, repo in runtime.SERVICES.items():
            if service in model['services']:
                require(model['services'][service]['image'] == self.candidate['images'][repo]['reference'], 'mutable fixture image')
        self.compose('pull', 'postgres', 'redis', 'api', 'search', 'frontend')

    def ready(self):
        recovery.wait(lambda: self.readyz_status() == 200, 600)
        containers = []
        def health():
            nonlocal containers
            ids = self.compose('ps', '-q', 'api', 'search', 'frontend', 'postgres', 'redis').split()
            if len(ids) != 5:
                return {'fixture': 'missing'}
            containers = json.loads(self.run(['docker', 'inspect', *ids], 'verify-isolated-containers'))
            return {c['Id']: c['State'].get('Health', {}).get('Status', 'healthy')
                    if c['State']['Running'] else 'stopped' for c in containers}
        runtime.wait_for_health(health, timeout=300)
        for container in containers:
            require(container['State']['Running'] and container['State'].get('Health', {}).get('Status', 'healthy') == 'healthy',
                    'unhealthy fixture service')
            name = container['Config']['Labels']['com.docker.compose.service']
            unpublished(container)
            if name in runtime.SERVICES:
                image = json.loads(self.run(['docker', 'image', 'inspect', container['Image']], 'verify-published-image'))[0]
                runtime.verify_image(image, self.candidate['images'][runtime.SERVICES[name]], container)
            networks = container['NetworkSettings']['Networks']
            require(len(networks) == 1, 'running container has alternate network')
            network = json.loads(self.run(['docker', 'network', 'inspect', next(iter(networks))], 'verify-internal-network'))[0]
            require(network.get('Internal') is True, 'running container has external egress')

    def snapshot(self):
        for role, table in (('core', 'schema_migrations'), ('search', 'vidra_search_migrations')):
            runtime.check_ledger(self.sql(f'SELECT version, dirty FROM {table}'), self.record[role + '_schema_version'])
        require(self.sql('SELECT count(*) FROM users').splitlines()[-1] == '1', 'unexpected fixture accounts')
        require(self.sql('SELECT count(*) FROM videos').splitlines()[-1] == '0', 'media fixture is out of scope')
        return recovery.fingerprint(self, self.record['core_schema_version'])

    def assert_scripts(self):
        require(all(runtime.sha(INSTALL / name) == digest for name, digest in self.script_hashes.items()),
                'published backup/restore script changed')

    def api_fixture(self, mode, fixture, setup_token=None):
        origin = self.api_origin()  # Resolve again after every key-control recreation.
        env = {**self.env, 'VIDRA_BASE_URL': origin, 'VIDRA_INTERNAL_ORIGIN': origin}
        if setup_token:
            env['VIDRA_SETUP_TOKEN'] = setup_token
        tool = Path(__file__).with_name('sealed-recovery-api.mjs')
        result = json.loads(self.run(['node', str(tool), mode, str(fixture)], 'api-' + mode, env=env))
        require(result['status'] == 'PASS', 'fixture API verification failed')
        return result
