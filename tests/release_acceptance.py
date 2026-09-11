#!/usr/bin/env python3
"""Prepare/run the bounded v0.6.4 milestone on an explicitly disposable host.

Reuses A02 installer assertions and A03 port/ledger assertions. Never accepts
the old emulated VM, replaces deploy.sh, builds application images or repairs
a failed installation. All raw output (including boot tokens) stays private.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import time

import blank_server_smoke as blank
from blank_server_smoke import require, sha, validate_candidate, check_ports
from runtime_smoke import check_ledger, check_runtime_ports

ROOT = Path(__file__).resolve().parent.parent
SERVICES = {'api': 'vidra-core', 'migrate': 'vidra-core', 'worker': 'vidra-core',
            'frontend': 'vidra-user', 'search': 'vidra-search', 'search-migrate': 'vidra-search'}
ORIGIN = 'https://secure.video.test'
PROJECT = 'vidra-release-acceptance'
INSTALL = Path('/opt/vidra')


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')
    path.chmod(0o600)


def pin_images(content, candidate):
    for repo, expected in (('vidra-core', 3), ('vidra-user', 1), ('vidra-search', 2)):
        image = candidate['images'][repo]
        pattern = r'(?m)^([ \t]*)image: \S*/' + repo + r':[^\n]+$'
        content, count = re.subn(pattern, lambda m: m[1] + 'image: ' + image['reference']
                                + '\n' + m[1] + 'platform: linux/amd64', content)
        require(count == expected, f'{repo}: unexpected released image mapping ({count})')
    return content


def check_host(facts):
    require(facts['system'] == 'Linux' and facts['architecture'] == 'x86_64',
            'requires native Linux AMD64; ARM64/emulation is not acceptance')
    require(facts['os'].get('ID') == 'ubuntu' and facts['os'].get('VERSION_ID') == '24.04',
            'requires Ubuntu 24.04')
    require(facts['root'] and facts['systemd'] and not facts['container'], 'requires root in a systemd VM/host')
    require(not facts['existing'], 'host is not blank: ' + ', '.join(facts['existing']))


def host_facts():
    release = Path('/etc/os-release')
    os_info = dict(line.split('=', 1) for line in release.read_text().splitlines() if '=' in line) if release.exists() else {}
    return {'system': platform.system(), 'architecture': platform.machine(), 'hostname': platform.node(),
            'os': {k: v.strip('"') for k, v in os_info.items()}, 'root': os.geteuid() == 0,
            'systemd': Path('/run/systemd/system').exists(),
            'container': Path('/.dockerenv').exists() or Path('/run/.containerenv').exists(),
            'existing': [p for p in ('/opt/vidra', '/usr/local/bin/vidra', '/var/lib/docker',
                                    '/var/lib/containerd', '/etc/docker') if Path(p).exists()]
                        + [name for name in ('docker', 'podman', 'containerd', 'vidra') if shutil.which(name)]}


def minimal_browser_lock(lock):
    names = ('@playwright/test', 'playwright', 'playwright-core')
    packages = {f'node_modules/{name}': copy.deepcopy(lock['packages'][f'node_modules/{name}']) for name in names}
    for entry in packages.values():
        for key in ('dev', 'devOptional', 'optional'):
            entry.pop(key, None)
        require(entry.get('integrity') and entry.get('resolved', '').startswith('https://registry.npmjs.org/'),
                'browser dependency lacks frozen registry integrity')
        for dependency in {**entry.get('dependencies', {}), **entry.get('optionalDependencies', {})}:
            require(dependency in names, 'browser lock acquired another dependency; review it explicitly')
    package = {'name': 'vidra-release-acceptance', 'version': '1.0.0', 'private': True,
               'dependencies': {'@playwright/test': packages['node_modules/@playwright/test']['version']}}
    return package, {'name': package['name'], 'version': package['version'], 'lockfileVersion': 3,
                     'requires': True, 'packages': {'': package, **packages}}


def prepare(frozen, out, node_archive, node_sums):
    candidate_path = ROOT / 'docs/evidence/release-v0.6.4-verification/manifest.json'
    candidate = json.loads(candidate_path.read_text())
    validate_candidate(candidate)
    require(candidate['tag'] == 'v0.6.4' and candidate['platform'] == 'linux/amd64', 'wrong frozen candidate')
    sources = frozen / 'source'
    for repo, source in candidate['repositories'].items():
        actual = subprocess.check_output(['git', '-C', str(sources / repo), 'rev-parse', 'HEAD'], text=True).strip()
        dirty = subprocess.check_output(['git', '-C', str(sources / repo), 'status', '--porcelain', '--untracked-files=no'], text=True)
        require(actual == source['revision'] and not dirty, f'{repo}: frozen source has drifted')
    require(node_archive.name == 'node-v26.8.1-linux-x64.tar.xz', 'use recorded Node 26.8.1 linux-x64 tooling')
    require(sha(node_archive) == blank.expected_hash(node_sums.read_text(), node_archive.name), 'Node checksum mismatch')
    for name, asset in candidate['assets'].items():
        require(sha(frozen / 'assets' / name) == asset['sha256'], f'frozen asset changed: {name}')
    # Bundle selection is deliberate: make-bundle.sh itself is not shipped.
    # Compare every packaged deploy file with its frozen source, then verify
    # that same inventory on the host (never demand files absent from release).
    source_hashes = {}
    with tarfile.open(frozen / 'assets' / f'vidra-bundle_{candidate["tag"]}.tar.gz') as archive:
        for member in archive.getmembers():
            name = member.name.removeprefix('./')
            if member.isfile() and name.startswith('deploy/'):
                digest = hashlib.sha256(archive.extractfile(member).read()).hexdigest()
                require(sha(sources / 'vidra' / name) == digest, f'bundle/source mismatch: {name}')
                source_hashes[name] = digest
    require('deploy/deploy.sh' in source_hashes and 'deploy/lib.sh' in source_hashes, 'bundle lacks deployment guards')
    out.mkdir(mode=0o700)  # never overwrite evidence, even a failed attempt
    shutil.copyfile(candidate_path, out / 'candidate.json')
    shutil.copyfile(sources / 'vidra/install.sh', out / 'install.sh')
    for filename in ('release_acceptance.py', 'release-acceptance.mjs', 'blank_server_smoke.py', 'runtime_smoke.py', 'owner-auth-smoke.mjs'):
        shutil.copyfile(ROOT / 'tests' / filename, out / filename)
    browser = out / 'browser'
    browser.mkdir()
    package, lock = minimal_browser_lock(json.loads((sources / 'vidra-user/package-lock.json').read_text()))
    save(browser / 'package.json', package)
    save(browser / 'package-lock.json', lock)
    shutil.copyfile(node_archive, out / node_archive.name)
    shutil.copyfile(node_sums, out / 'node-SHASUMS256.txt')
    migrations = {}
    for repo, table in (('vidra-core', 'schema_migrations'), ('vidra-search', 'vidra_search_migrations')):
        paths = sorted((sources / repo / 'migrations').glob('*.up.sql'))
        require(paths, f'{repo}: missing source migration files')
        migrations[table] = {'version': max(int(p.name.split('_')[0]) for p in paths),
                             'source_revision': candidate['repositories'][repo]['revision'],
                             'files': {p.name: sha(p) for p in paths}}
    save(out / 'expected-ledgers.json', migrations)
    # Only digest substitution changes the released deployment inputs. Its
    # scripts/manifest stay byte-for-byte frozen, retaining all shipped guards.
    prod = sources / 'vidra/docker-compose.prod.yml'
    (out / 'pinned-prod.yml').write_text(pin_images(prod.read_text(), candidate))
    save(out / 'frozen-deploy-hashes.json', source_hashes)
    files = {str(p.relative_to(out)): sha(p) for p in out.rglob('*') if p.is_file()}
    save(out / 'handoff.json', {'status': 'PREPARED_NOT_EXECUTED', 'files': files,
                              'candidate_sha256': sha(candidate_path), 'node_version': '26.8.1',
                              'application_builds': 'published digests only'})
    print(f'Prepared {out}; handoff.json sha256={sha(out / "handoff.json")}')


class Recorder:
    def __init__(self, stage):
        self.stage = stage
        self.private = stage / 'private'
        self.private.mkdir(mode=0o700)
        self.env = {k: os.environ[k] for k in ('PATH', 'HOME', 'LANG') if k in os.environ}
        self.env.update(COMPOSE_PROJECT_NAME=PROJECT, API_CPUS='2.0', API_MEM_LIMIT='4096m',
                        READY_TIMEOUT='600', EDGE_TIMEOUT='180', DEBIAN_FRONTEND='noninteractive')
        self.sequence = 0

    def run(self, args, label, cwd=INSTALL, env=None, expected=0, timeout=1800):
        self.sequence += 1
        logfile = self.private / f'{self.sequence:03d}-{label}.log'
        record = {'argv': [str(a) for a in args], 'cwd': str(cwd), 'label': label,
                  'started_at': time.time(), 'log': logfile.name}
        print(f'[release-acceptance] {label}', flush=True)
        try:
            with logfile.open('w') as stream:
                result = subprocess.run(args, cwd=cwd, env=env or self.env, stdin=subprocess.DEVNULL,
                                        stdout=stream, stderr=subprocess.STDOUT, timeout=timeout)
            record['exit_code'] = result.returncode
        except subprocess.TimeoutExpired:
            record['exit_code'] = 'TIMEOUT'
            raise
        finally:
            record['finished_at'] = time.time()
            with (self.private / 'commands.jsonl').open('a') as log:
                log.write(json.dumps(record) + '\n')
        require(result.returncode == expected, f'{label}: exit {result.returncode}; see {logfile.name}')
        return logfile.read_text()

    def compose(self, *args):
        return self.run(['bash', 'deploy/compose.sh', *args], 'compose-' + args[0])

    def sql(self, query):
        return self.compose('exec', '-T', 'postgres', 'psql', '-U', 'vidra', '-d', 'vidra',
                            '-At', '-v', 'ON_ERROR_STOP=1', '-c', query).strip()


def verify_image(info, image, container):
    require(image['reference'] in info.get('RepoDigests', []), 'loaded image digest mismatch')
    require(info['Os'] == 'linux' and info['Architecture'] == 'amd64', 'loaded image platform mismatch')
    require((info['Config'].get('Labels') or {}).get('org.opencontainers.image.revision') == image['revision'], 'loaded image revision mismatch')
    require(container['Config']['Image'] == image['reference'] and container['Image'] == info['Id'],
            'container is not running the inspected immutable image')


def wait_for_health(probe, timeout=180, clock=time.monotonic, pause=time.sleep):
    deadline = clock() + timeout
    while True:
        states = probe()
        require(states, 'no running-service health observations')
        if all(state == 'healthy' for state in states.values()):
            return states
        require(clock() < deadline, f'runtime health timeout: {states}')
        pause(2)


def wait_for_runtime(run):
    services = ('api', 'frontend', 'search', 'postgres', 'redis', 'caddy', 'clamav')

    def probe():
        ids = run.compose('ps', '-q', *services).split()
        require(ids, 'no running containers')
        containers = json.loads(run.run(['docker', 'inspect', *ids], 'runtime-health'))
        observed = {}
        for container in containers:
            name = container['Config']['Labels']['com.docker.compose.service']
            state = container['State']
            observed[name] = state.get('Health', {}).get('Status', 'healthy') if state['Running'] else 'stopped'
        return {name: observed.get(name, 'missing') for name in services}

    # deploy.sh's HTTP probe can pass before Docker has run the frontend's
    # first healthcheck. Record and wait for it; never accept a timed-out or
    # persistently unhealthy service as a passing runtime snapshot.
    return wait_for_health(probe)


def runtime_snapshot(run, candidate):
    rows, ports = {}, {}
    ids = run.compose('ps', '-aq').split()
    require(ids, 'no Compose containers')
    for cid in ids:
        container = json.loads(run.run(['docker', 'inspect', cid], 'inspect-container'))[0]
        service = container['Config']['Labels']['com.docker.compose.service']
        image = json.loads(run.run(['docker', 'image', 'inspect', container['Image']], 'inspect-image'))[0]
        if service in SERVICES:
            verify_image(image, candidate['images'][SERVICES[service]], container)
        rows[service] = {'container_id': cid, 'reference': container['Config']['Image'],
                         'image_id': image['Id'], 'repo_digests': image['RepoDigests'],
                         'platform': f'{image["Os"]}/{image["Architecture"]}',
                         'revision': (image['Config'].get('Labels') or {}).get('org.opencontainers.image.revision'),
                         'state': container['State'], 'restart_count': container['RestartCount']}
        ports[service] = container['NetworkSettings']['Ports'] or {}
    for service in ('api', 'frontend', 'search', 'postgres', 'redis', 'caddy', 'clamav'):
        require(rows.get(service, {}).get('state', {}).get('Running'), f'{service}: not running')
        health = rows[service]['state'].get('Health')
        require(not health or health['Status'] == 'healthy', f'{service}: unhealthy')
    check_runtime_ports(ports)
    return {'images': rows, 'ports': ports}


def execute(stage, approval):
    require(approval == 'fresh-disposable-host', 'explicit disposable-host acknowledgement required')
    # A failed before-state produces evidence too, but never creates /opt/vidra.
    require(not (stage / 'result.json').exists() and not (stage / 'private').exists(), 'use a new host/stage; retain failed evidence')
    os.umask(0o077)
    evidence = {'status': 'UNVERIFIED', 'scope': 'first runtime milestone only', 'checks': {},
                'candidate_certification': 'NOT_ESTABLISHED', 'started_at': time.time()}
    run = None
    try:
        handoff = json.loads((stage / 'handoff.json').read_text())
        for name, expected in handoff['files'].items():
            require(sha(stage / name) == expected, f'handoff file changed: {name}')
        candidate = json.loads((stage / 'candidate.json').read_text())
        validate_candidate(candidate)
        require(candidate['tag'] == 'v0.6.4' and candidate['platform'] == 'linux/amd64', 'wrong candidate')
        evidence.update(candidate_sha256=sha(stage / 'candidate.json'), handoff_sha256=sha(stage / 'handoff.json'),
                        before=host_facts())
        check_host(evidence['before'])
        run = Recorder(stage)
        run.run(['ss', '-lntup'], 'before-listeners', cwd=stage)
        run.run(['df', '-h'], 'before-disk', cwd=stage)
        require(os.cpu_count() >= 4 and shutil.disk_usage(stage).free >= 30 * 1024**3,
                'requires >=4 CPUs and >=30 GiB free for this rehearsal')
        evidence['checks']['blank_native_host'] = 'PASS'
        # Record A02's exact argv/exits as well as its corruption and rerun proofs.
        def install_command(args, private, label, cwd=None, env=None, expected=0):
            return run.run(args, 'install-' + label, cwd=cwd or stage, env=env, expected=expected)
        blank.command = install_command
        install_private = run.private / 'installer'
        install_private.mkdir()
        blank.run_guest(candidate, stage, install_private, evidence)
        require(run.run(['docker', 'info', '--format', '{{.OSType}}/{{.Architecture}}'], 'engine-platform').strip()
                in ('linux/x86_64', 'linux/amd64'), 'Docker engine is not native AMD64')
        require(not run.run(['docker', 'volume', 'ls', '-q'], 'empty-volumes').strip(), 'preexisting volumes')
        for name, expected in json.loads((stage / 'frozen-deploy-hashes.json').read_text()).items():
            require(sha(INSTALL / name) == expected, f'installed deployment source differs: {name}')
        shutil.copyfile(stage / 'pinned-prod.yml', INSTALL / 'docker-compose.prod.yml')
        evidence['deployment_adaptation'] = 'Only six application image references replaced with frozen digests and linux/amd64; scripts unchanged.'
        run.run(['vidra', 'setup', '--non-interactive', '--yes', '--domain', ORIGIN,
                 '--instance-name', 'v0.6.4 disposable acceptance', '--registration', 'closed',
                 '--tls-mode', 'internal', '--storage', 'local', '--release-tag', candidate['tag'],
                 '--template', 'env/production.env.example'], 'setup-internal')
        run.run(['vidra', 'setup', '--check', 'env/production.env'], 'setup-check')
        model = json.loads(run.compose('config', '--format', 'json'))
        check_ports(model)
        api_env = model['services']['api']['environment']
        require(str(api_env['TRANSCODING_ENABLED']).lower() == 'true'
                and api_env['TRANSCODING_PACKAGER'] == 'cmaf', 'real CMAF transcoding required')
        require(api_env['SEARCH_SERVICE_URL'] == 'http://search:8080'
                and api_env['CLAMAV_ADDR'] == 'clamav:3310'
                and api_env['MALWARE_SCAN_MODE'] == 'fail-closed', 'default search/scanning must stay wired')
        for service in ('migrate', 'search-migrate'):
            require(not model['services'][service].get('volumes'), 'migration mount forbidden')
        for service, repo in SERVICES.items():
            if service in model['services']:
                require(model['services'][service]['image'] == candidate['images'][repo]['reference'], 'mutable service image')
        deploy_started = str(int(time.time()))
        try:
            run.run(['bash', 'deploy/deploy.sh'], 'frozen-deploy', timeout=3600)
        finally:
            run.run(['docker', 'events', '--since', deploy_started, '--until', str(int(time.time()) + 1),
                     '--filter', 'type=container', '--filter', f'label=com.docker.compose.project={PROJECT}',
                     '--format', '{{json .}}'], 'deployment-container-events')
        evidence['initial_health'] = wait_for_runtime(run)
        evidence['runtime_before_browser'] = runtime_snapshot(run, candidate)
        ledgers = json.loads((stage / 'expected-ledgers.json').read_text())
        evidence['ledgers'] = {}
        for table, spec in ledgers.items():
            actual = run.sql(f'SELECT version, dirty FROM {table}')
            check_ledger(actual, spec['version'])
            evidence['ledgers'][table] = {'actual': actual, 'expected': spec['version'], 'source_revision': spec['source_revision']}
        require(run.sql('SELECT count(*) FROM users') == '0', 'owner already claimed')
        caddy = run.compose('ps', '-q', 'caddy').strip()
        run.run(['docker', 'cp', f'{caddy}:/data/caddy/pki/authorities/local/root.crt', str(stage / 'root.crt')], 'copy-test-ca')
        evidence['edge'] = {}
        for path in ('/healthz', '/readyz', '/version', '/', '/runtime-config.js'):
            body = run.run(['curl', '-fsS', '--max-time', '30', '--cacert', str(stage / 'root.crt'),
                            '--resolve', 'secure.video.test:443:127.0.0.1', ORIGIN + path], 'edge-' + path.strip('/').replace('/', '-'))
            evidence['edge'][path] = {'sha256': hashlib.sha256(body.encode()).hexdigest()}
            if path == '/version':
                version = json.loads(body)
                evidence['edge'][path]['body'] = version
                require(version['version'] == candidate['tag']
                        and re.fullmatch(r'[0-9a-f]{7,40}', version['commit'])
                        and candidate['repositories']['vidra-core']['revision'].startswith(version['commit']),
                        'running /version does not match frozen release')
            if path == '/runtime-config.js':
                require(ORIGIN in body and 'localhost:8080' not in body, 'wrong frontend runtime origin')
        evidence['checks']['installed_migrated_serving'] = 'PASS'
        # Test-only tools arrive AFTER the no-developer-tool installation proof.
        # The stock Ubuntu cloud image lacks Node 26's libatomic dependency;
        # install it before npm/Playwright can bootstrap their own dependencies.
        run.run(['apt-get', 'update'], 'test-prerequisites-index')
        run.run(['apt-get', 'install', '-y', '--no-install-recommends', 'libatomic1'], 'test-prerequisites')
        node_dir = stage / 'node'
        node_dir.mkdir()
        run.run(['tar', '-xJf', str(stage / 'node-v26.8.1-linux-x64.tar.xz'), '--strip-components=1', '-C', str(node_dir)], 'test-node')
        run.env['PATH'] = str(node_dir / 'bin') + ':' + run.env['PATH']
        run.run(['npm', 'ci', '--ignore-scripts', '--no-audit', '--no-fund'], 'browser-dependencies', cwd=stage / 'browser')
        run.run(['node', 'node_modules/playwright/cli.js', 'install', '--with-deps', 'chromium'], 'browser-install', cwd=stage / 'browser')
        # ffmpeg from the inspected released API image creates a moving pattern
        # plus audible sine. It is a source fixture, never a prebuilt HLS tree.
        api = run.compose('ps', '-q', 'api').strip()
        run.run(['docker', 'exec', api, 'ffmpeg', '-hide_banner', '-y', '-f', 'lavfi', '-i',
                 'testsrc2=size=640x360:rate=30', '-f', 'lavfi', '-i', 'sine=frequency=880:sample_rate=48000',
                 '-t', '12', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-movflags', '+faststart',
                 '/tmp/release-acceptance.mp4'], 'make-source-fixture')
        evidence['fixture_probe'] = json.loads(run.run(['docker', 'exec', api, 'ffprobe', '-v', 'error',
            '-show_format', '-show_streams', '-of', 'json', '/tmp/release-acceptance.mp4'], 'probe-source-fixture'))
        run.run(['docker', 'cp', f'{api}:/tmp/release-acceptance.mp4', str(stage / 'fixture.mp4')], 'copy-fixture')
        evidence['fixture_sha256'] = sha(stage / 'fixture.mp4')
        run.run(['node', str(stage / 'release-acceptance.mjs'), str(stage)], 'browser-milestone', cwd=stage, timeout=3600)
        browser = json.loads((stage / 'browser-result.json').read_text())
        require(browser['status'] == 'PASS', 'browser milestone did not pass')
        evidence['browser'] = browser
        evidence['runtime_after_browser'] = runtime_snapshot(run, candidate)
        evidence['checks']['browser_upload_transcode_playback_search'] = 'PASS'
        evidence['status'] = 'PASS'
        evidence['candidate_certification'] = 'BOUNDED_MILESTONE_ONLY'
    except Exception as error:
        # Unexpected tool/schema failures must also leave an explicit failed
        # evidence record, rather than an incomplete result resembling success.
        evidence['status'] = 'FAIL'
        evidence['error'] = str(error)
    finally:
        if run and INSTALL.exists() and shutil.which('docker'):
            try:
                run.compose('logs', '--no-color', '--timestamps')
            except (ValueError, OSError, subprocess.SubprocessError):
                evidence['diagnostic_logs'] = 'collection failed; earlier logs retained'
        evidence['finished_at'] = time.time()
        save(stage / 'result.json', evidence)
        print(f'{evidence["status"]}: {stage}/result.json; private logs retained; no cleanup performed')
    return 0 if evidence['status'] == 'PASS' else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest='mode', required=True)
    prep = modes.add_parser('prepare')
    prep.add_argument('--frozen', type=Path, required=True, help='existing release-preflight output (source/ plus assets/)')
    prep.add_argument('--node-archive', type=Path, required=True)
    prep.add_argument('--node-sums', type=Path, required=True)
    prep.add_argument('--out', type=Path, required=True)
    modes.add_parser('check-host')
    execute_parser = modes.add_parser('run')
    execute_parser.add_argument('stage', type=Path)
    execute_parser.add_argument('--acknowledge', required=True, choices=['fresh-disposable-host'])
    args = parser.parse_args()
    if args.mode == 'prepare':
        prepare(args.frozen.resolve(), args.out.resolve(), args.node_archive.resolve(), args.node_sums.resolve())
    elif args.mode == 'check-host':
        facts = host_facts()
        print(json.dumps(facts, indent=2))
        check_host(facts)
    else:
        sys.exit(execute(args.stage.resolve(), args.acknowledge))
