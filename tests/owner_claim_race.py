#!/usr/bin/env python3
"""Race two real owner claims in a NEW database/API inside the A03 lab VM."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request


def main(project, stage):
    assert os.geteuid() == 0 and platform.node().startswith('vidra-a02-')
    assert re.fullmatch(r'vidra-a03-[0-9]+-[0-9]+', project)
    stage.mkdir(mode=0o700)
    name = f'a04race{int(time.time())}'
    result = {'status': 'UNVERIFIED', 'database': name, 'checks': {}}

    def run(args):
        p = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=180)
        with (stage / 'private-commands.log').open('a') as log:
            log.write(p.stdout)
        assert p.returncode == 0, 'guest command failed; see private log'
        return p.stdout.strip()

    def sql(query, database='vidra'):
        return run(['docker', 'exec', f'{project}-postgres-1', 'psql', '-U', 'vidra', '-d', database,
                    '-At', '-v', 'ON_ERROR_STOP=1', '-c', query])

    container = None
    try:
        parent = json.loads(run(['docker', 'inspect', f'{project}-api-1']))[0]
        image = parent['Config']['Image']
        assert re.fullmatch(r'ghcr.io/yegamble/vidra-core@sha256:[0-9a-f]{64}', image)
        result['image'] = image
        network = next(iter(parent['NetworkSettings']['Networks']))
        env = dict(item.split('=', 1) for item in parent['Config']['Env'])
        assert '/vidra?' in env['DATABASE_URL']
        env['DATABASE_URL'] = env['DATABASE_URL'].replace('/vidra?', f'/{name}?')
        env['VIDRA_ROLE'] = 'api'  # no background jobs against shared media/search
        env['REGISTRATION_ENABLED'] = 'true'
        envfile = stage / 'private.env'
        envfile.write_text(''.join(f'{key}={value}\n' for key, value in env.items()))
        envfile.chmod(0o600)
        sql(f'CREATE DATABASE {name}')
        common = ['--network', network, '--env-file', str(envfile), '--volumes-from', f'{project}-api-1']
        run(['docker', 'run', '--rm', *common, image, 'migrate', 'up'])
        # Docker may prepend a cross-architecture warning on this emulated
        # lane. The final line is the ID; retain the warning in private logs.
        container = run(['docker', 'run', '-d', '--name', name, *common, image]).splitlines()[-1]
        assert re.fullmatch(r'[0-9a-f]{64}', container)
        info = json.loads(run(['docker', 'inspect', container]))[0]
        ip = info['NetworkSettings']['Networks'][network]['IPAddress']

        def request(path, body=None):
            req = urllib.request.Request(f'http://{ip}:8080{path}',
                data=json.dumps(body).encode() if body is not None else None,
                headers={'Content-Type': 'application/json'})
            try:
                with urllib.request.urlopen(req, timeout=30) as response:
                    return response.status, json.load(response)
            except urllib.error.HTTPError as error:
                return error.code, json.load(error)

        deadline = time.monotonic() + 180
        while True:
            try:
                if request('/readyz')[0] == 200:
                    break
            except (OSError, ValueError):
                pass
            assert time.monotonic() < deadline, 'race API did not become ready'
            time.sleep(2)
        assert sql('SELECT count(*) FROM users', name) == '0'
        logs = run(['docker', 'logs', container])
        token = re.findall(r'403 owner_claim_required until claimed\): ([A-Za-z0-9_-]+)', logs)[-1]
        accounts = [{'token': token, 'username': f'racer{i}', 'email': f'racer{i}@example.test',
                     'password': f'race-test-password-{os.urandom(16).hex()}'} for i in (1, 2)]
        assert request('/api/v1/auth/register', {k: v for k, v in accounts[0].items() if k != 'token'})[0] == 403
        # A barrier makes both request workers leave together; neither waits
        # for the other's response before sending the competing claim.
        import threading
        barrier = threading.Barrier(2)

        def claim(account):
            barrier.wait()
            return request('/api/v1/setup/claim-owner', account)

        with ThreadPoolExecutor(max_workers=2) as pool:
            replies = list(pool.map(claim, accounts))
        assert sorted(code for code, _ in replies) == [201, 403]
        winner = next(body for code, body in replies if code == 201)
        loser = next(body for code, body in replies if code == 403)
        assert winner['user']['role'] == 'admin'
        assert loser['error']['code'] == 'owner_claim_invalid'
        assert sql("SELECT count(*) || '|' || count(*) FILTER (WHERE role='admin') FROM users", name) == '1|1'
        assert request('/api/v1/setup/claim-owner', accounts[0])[0] == 403
        result['checks']['simultaneous_claims'] = 'PASS: one 201, one 403 owner_claim_invalid, exactly one persisted admin'
        result['status'] = 'PASS'
    except (AssertionError, OSError, KeyError, IndexError, subprocess.TimeoutExpired) as error:
        import traceback
        (stage / 'private-error.txt').write_text(traceback.format_exc())
        result['status'] = 'FAIL'
        result['error_type'] = type(error).__name__
    finally:
        if container and re.fullmatch(r'[0-9a-f]{64}', container):
            run(['docker', 'stop', container])
        (stage / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    return 0 if result['status'] == 'PASS' else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1], Path(sys.argv[2])))
