#!/usr/bin/env python3
"""A03 real released-stack rehearsal; only runs in the retained A02 VM."""
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys

from blank_server_smoke import require, sha, validate_candidate, check_ports


def check_ledger(value, expected):
    require(value.strip() == f'{expected}|f', 'ledger must contain exactly the expected clean row')


def check_abort(code, output, family, before, after):
    require(code != 0 and f'{family} MIGRATION FAILED' in output,
            'deploy did not fail at the selected real migrator')
    require('4/6 start' not in output and before == after,
            'migration failure reached startup or changed serving containers')


def check_runtime_ports(ports):
    for name in ('postgres', 'redis', 'search'):
        require(not any(ports[name].values()), f'{name}: published runtime port')
    for name, port in (('api', 8080), ('frontend', 3000)):
        bound = {key: value for key, value in ports[name].items() if value}
        require(bound == {f'{port}/tcp': [{'HostIp': '127.0.0.1', 'HostPort': str(port)}]},
                f'{name}: runtime port is not loopback only')


def guest(stage):
    require(platform.system() == 'Linux' and os.geteuid() == 0
            and platform.node().startswith('vidra-a02-'), 'requires disposable A02 Linux VM')
    a02 = json.loads(Path('/home/ubuntu/a02-evidence/result.json').read_text())
    candidate = json.loads((stage / 'candidate.json').read_text())
    validate_candidate(candidate)
    require(a02['status'] == 'PASS' and a02['candidate_sha256'] == sha(stage / 'candidate.json'),
            'A02 evidence does not match candidate')
    private = stage / 'private'
    private.mkdir(mode=0o700)
    root = private / 'installation'
    shutil.copytree('/opt/vidra', root)
    evidence = {'status': 'UNVERIFIED', 'candidate_sha256': sha(stage / 'candidate.json'),
                'helper_sha256': sha(__file__), 'host_architecture': platform.machine(),
                'checks': {}, 'project': stage.name}
    env = dict(os.environ, COMPOSE_PROJECT_NAME=stage.name, API_CPUS='2.0', API_MEM_LIMIT='1536m',
               READY_TIMEOUT='300', EDGE_TIMEOUT='180')
    counter = 0

    def run(args, label, expected=0):
        nonlocal counter
        counter += 1
        print(f'[a03] {label}', flush=True)
        path = private / f'{counter:03d}-{label}.log'
        with path.open('w') as log:
            p = subprocess.run(args, cwd=root, env=env, stdin=subprocess.DEVNULL,
                               stdout=log, stderr=subprocess.STDOUT, timeout=1800)
        out = path.read_text()
        if expected is not None:
            require(p.returncode == expected, f'{label}: exit {p.returncode}; see private guest log')
        return p.returncode, out

    def compose(*args):
        return run(['bash', 'deploy/compose.sh', *args], 'compose-' + args[0])[1]

    def state():
        result, ports = {}, {}
        for service in ('api', 'frontend', 'search', 'caddy', 'postgres', 'redis'):
            cid = compose('ps', '-q', service).strip()
            require(cid, f'{service}: missing running container')
            info = json.loads(run(['docker', 'inspect', cid], 'inspect-' + service)[1])[0]
            result[service] = [info['Id'], info['State']['StartedAt'], info['RestartCount']]
            ports[service] = info['NetworkSettings']['Ports']
        check_runtime_ports(ports)
        return result

    def sql(statement):
        return compose('exec', '-T', 'postgres', 'psql', '-U', 'vidra', '-d', 'vidra',
                       '-At', '-v', 'ON_ERROR_STOP=1', '-c', statement).strip()

    def probe(mode, path, tls=False):
        host = 'video.test' if mode == 'plain-http' else 'secure.video.test'
        port = 443 if tls else 80
        args = ['curl', '-fsS', '--max-time', '60', '--resolve', f'{host}:{port}:127.0.0.1']
        if tls:
            args += ['--cacert', str(private / 'root.crt')]
        return run(args + [f'{"https" if tls else "http"}://{host}{path}'], 'edge-probe')[1]

    try:
        require(not run(['docker', 'ps', '-aq'], 'empty-containers')[1].strip(),
                'VM has containers; preserve them and use a fresh A02 VM')
        require(not run(['docker', 'volume', 'ls', '-q'], 'empty-volumes')[1].strip(),
                'VM has volumes; fresh first-deploy evidence required')
        evidence['checks']['empty_runtime'] = 'PASS'
        evidence['released_deploy_sha256'] = sha(root / 'deploy/deploy.sh')
        shutil.copyfile(stage / 'deploy-under-test.sh', root / 'deploy/deploy.sh')
        evidence['deploy_sha256'] = sha(root / 'deploy/deploy.sh')
        # Only the disposable bundle copy is changed: use immutable A01 images
        # with explicit platforms while leaving the semver/env and ledger gates intact.
        prod = root / 'docker-compose.prod.yml'
        content = prod.read_text()
        for repo, image in candidate['images'].items():
            pattern = r'(?m)^(\s*)image: ghcr.io/[^\n]*/' + repo + r':[^\n]+$'
            content, count = re.subn(pattern, lambda m: m[1] + 'image: ' + image['reference']
                                    + '\n' + m[1] + 'platform: ' + image['platform'], content)
            require(count > 0, f'{repo}: could not pin bundle image')
            output = run(['docker', 'run', '--rm', '--platform', image['platform'], '--entrypoint',
                          '/bin/sh', image['reference'], '-c', 'uname -m'], 'execute-' + repo)[1]
            require(output.strip() == {'linux/amd64': 'x86_64', 'linux/arm64': 'aarch64'}[image['platform']],
                    f'{repo}: image execution architecture mismatch')
        prod.write_text(content)
        evidence['checks']['image_execution'] = 'PASS'
        binfmt = Path('/proc/sys/fs/binfmt_misc/qemu-x86_64')
        evidence['emulation'] = binfmt.read_text() if binfmt.exists() else 'native'
        # The search second opinion comes from frozen SOURCE filenames, never
        # from the binary/ledger being tested. Core's comes from bundle provenance.
        revision = candidate['repositories']['vidra-search']['revision']
        tree = json.loads(run(['curl', '-fsSL', f'https://api.github.com/repos/yegamble/vidra-search/git/trees/{revision}?recursive=1'],
                             'search-source-tree')[1])
        versions = [int(Path(n['path']).name.split('_')[0]) for n in tree['tree']
                    if re.fullmatch(r'migrations/[0-9]+_.*\.up\.sql', n['path'])]
        require(versions, 'missing frozen search migration filenames')
        manifest = dict(line.split('=', 1) for line in (root / 'vidra-bundle.manifest').read_text().splitlines()
                        if line and not line.startswith('#'))
        expected = {'schema_migrations': int(manifest['core_schema_version']),
                    'vidra_search_migrations': max(versions)}
        # Default mode is asserted without asking a public CA for a lab certificate.
        model = json.loads(run(['env', 'VIDRA_TLS_MODE=acme', 'bash', 'deploy/compose.sh', 'config', '--format', 'json'], 'default-render')[1])
        check_ports(model)
        require('caddy' in model['services'], 'default edge profile missing')
        for migrator, service in (('migrate', 'api'), ('search-migrate', 'search')):
            require(not model['services'][migrator].get('volumes'), f'{migrator}: migration bind mount forbidden')
            require(model['services'][migrator]['image'] == model['services'][service]['image'],
                    f'{migrator}: service image differs')
        for mode, origin in (('plain-http', 'http://video.test'), ('internal', 'https://secure.video.test')):
            run(['vidra', 'setup', '--non-interactive', '--yes', '--domain', origin, '--instance-name', 'A03 rehearsal',
                 '--registration', 'closed', '--tls-mode', mode, '--storage', 'local',
                 '--release-tag', candidate['tag'], '--template', 'env/production.env.example'], 'setup-' + mode)
            run(['vidra', 'setup', '--check', 'env/production.env'], 'setup-check')
            run(['bash', 'deploy/deploy.sh'], 'deploy-' + mode)
            for table, version in expected.items():
                check_ledger(sql(f'SELECT version, dirty FROM {table}'), version)
            state()
            if mode == 'internal':
                cid = compose('ps', '-q', 'caddy').strip()
                run(['docker', 'cp', f'{cid}:/data/caddy/pki/authorities/local/root.crt', str(private / 'root.crt')], 'tls-root')
            for path in ('/healthz', '/readyz', '/'):
                output = probe(mode, path, mode == 'internal')
                if path == '/':
                    require('<html' in output.lower(), 'edge did not serve frontend HTML')
            config = probe(mode, '/runtime-config.js', mode == 'internal')
            require(origin in config and 'localhost:8080' not in config, 'frontend runtime API origin mismatch')
            evidence['checks'][mode] = 'PASS: setup, deploy, clean ledgers, runtime ports, edge and runtime origin'
        evidence['ledgers'] = expected
        for table, family in (('schema_migrations', 'CORE'), ('vidra_search_migrations', 'SEARCH')):
            before = state()
            sql(f'UPDATE {table} SET dirty = true')
            try:
                code, output = run(['bash', 'deploy/deploy.sh'], 'dirty-' + family.lower(), expected=None)
                check_abort(code, output, family, before, state())
                require(sql(f'SELECT dirty FROM {table}') == 't', 'dirty ledger was silently repaired')
            finally:
                # Synthetic fault only: no SQL migration ran while dirty. Clear
                # precisely our injected bit so the next independent case can run.
                sql(f'UPDATE {table} SET dirty = false')
            evidence['checks']['dirty-' + family.lower()] = 'PASS: nonzero migrator; serving IDs/start times/restarts unchanged'
        run(['bash', 'deploy/deploy.sh'], 'recovery-deploy')
        for table, version in expected.items():
            check_ledger(sql(f'SELECT version, dirty FROM {table}'), version)
        evidence['checks']['recovery'] = 'PASS'
        evidence['status'] = 'PASS'
    except (ValueError, OSError, KeyError, subprocess.TimeoutExpired) as error:
        evidence['status'] = 'FAIL'
        evidence['error'] = str(error)
    finally:
        (stage / 'result.json').write_text(json.dumps(evidence, indent=2) + '\n')
    return 0 if evidence['status'] == 'PASS' else 1


if __name__ == '__main__':
    require(len(sys.argv) == 2, 'usage: runtime_smoke.py GUEST_STAGE')
    sys.exit(guest(Path(sys.argv[1]).resolve()))
