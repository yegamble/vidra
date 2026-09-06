#!/usr/bin/env python3
"""Required A36 real backup/failure proof on the retained disposable fixture."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time


def main():
    fixture, output = map(Path, sys.argv[1:])
    prepared = json.loads((fixture / 'result.json').read_text())
    vm, project = prepared['vm'], prepared['project']
    assert prepared['status'] == 'PASS'
    assert re.fullmatch(r'vidra-a02-\d+-\d+', vm)
    assert re.fullmatch(r'vidra-a03-\d+-\d+', project)
    root = prepared['guest_root'] + '/installation'
    assert re.fullmatch(r'/home/ubuntu/vidra-a08-\d+/installation', root)
    output.mkdir(mode=0o700)
    result = dict(status='UNVERIFIED', vm=vm, project=project, checks={},
                  helper_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  backup_sha256=hashlib.sha256(Path('deploy/backup.sh').read_bytes()).hexdigest())

    def run(args, **kwargs):
        return subprocess.run(args, check=True, capture_output=True, timeout=180, **kwargs)

    def guest(*args, **kwargs):
        return run(['multipass', 'exec', vm, '--', 'sudo', *args], **kwargs)

    backup_dir = '/home/ubuntu/vidra-a36-' + str(int(time.time()))
    result['guest_backup_dir'] = backup_dir
    try:
        run(['multipass', 'start', vm])
        transfer = '/home/ubuntu/vidra-a36-backup.sh'
        run(['multipass', 'transfer', 'deploy/backup.sh', vm + ':' + transfer])
        guest('install', '-m', '755', transfer, root + '/deploy/backup.sh')
        command = ['env', 'COMPOSE_PROJECT_NAME=' + project, 'BACKUP_DIR=' + backup_dir,
                   'bash', root + '/deploy/backup.sh']
        completed = guest(*command)
        (output / 'private-backup.log').write_bytes(completed.stdout + completed.stderr)
        inspect = r'''
import gzip,json,pathlib,stat,subprocess,sys,tarfile
root=pathlib.Path(sys.argv[1]); installation=pathlib.Path(sys.argv[2]); project=sys.argv[3]
dumps=list(root.glob('*.dump.gz')); configs=list(root.glob('*.tar.gz'))
assert len(dumps)==len(configs)==1
assert dumps[0].name.removeprefix('vidra-').removesuffix('.dump.gz')==configs[0].name.removeprefix('vidra-config-').removesuffix('.tar.gz')
modes={p.name:stat.S_IMODE(p.stat().st_mode) for p in root.iterdir()}
assert stat.S_IMODE(root.stat().st_mode)==0o700
assert all(mode & 0o077==0 for mode in modes.values())
archive=gzip.decompress(dumps[0].read_bytes())
toc=subprocess.check_output(['docker','exec','-i',project+'-postgres-1','pg_restore','-l'],input=archive).decode()
assert 'TABLE public users ' in toc and 'TABLE search documents ' in toc
with tarfile.open(configs[0]) as t:
 names=t.getnames();assert names==['env/production.env','deploy/Caddyfile.local']
 for name in names:assert t.extractfile(name).read()==(installation/name).read_bytes()
 env=t.extractfile('env/production.env').read().decode()
 settings=dict(line.split('=',1) for line in env.splitlines() if '=' in line and not line.startswith('#'))
 assert settings.get('MFA_KEY_KEK') and settings.get('JWT_SECRET')
print(json.dumps({'modes':modes,'core_and_search_toc':True,'config_exact_match':True,'sealing_key_present':True,'marker':(root/'last_success').read_text(),'files':[p.name for p in dumps+configs]}))
'''
        result['archive'] = json.loads(guest('python3', '-c', inspect, backup_dir, root, project).stdout)
        result['checks']['archive_contents_and_permissions'] = 'PASS'
        # An absent DATABASE, on the real server, makes the real pg_dump fail.
        # No serving service or source configuration is changed for this probe.
        time.sleep(1.1)
        failed = subprocess.run(['multipass', 'exec', vm, '--', 'sudo', 'env',
                                 'POSTGRES_DB=vidra_a36_absent_' + str(int(time.time())),
                                 *command], capture_output=True, timeout=180)
        (output / 'private-failed-dump.log').write_bytes(failed.stdout + failed.stderr)
        assert failed.returncode != 0
        verify_failure = r'''
import json,pathlib,sys
root=pathlib.Path(sys.argv[1]); expected=json.loads(sys.argv[2])
assert (root/'last_success').read_text()==expected['marker']
assert sorted(p.name for p in root.iterdir() if p.name.endswith(('.dump.gz','.tar.gz')))==sorted(expected['files'])
parts=list(root.glob('*.part'));assert len(parts)==1
assert parts[0].stat().st_mode & 0o077==0
print(json.dumps({'exit_nonzero':True,'marker_unchanged':True,'no_finalized_failure':True,'partial_private':True}))
'''
        result['failure'] = json.loads(guest('python3', '-c', verify_failure, backup_dir,
                                           json.dumps(result['archive'])).stdout)
        result['failure']['exit_code'] = failed.returncode
        result['checks']['failed_dump_not_published'] = 'PASS'
        result['status'] = 'PASS'
    except Exception as error:
        result['status'] = 'FAIL'
        (output / 'private-error.txt').write_text(str(error))
    finally:
        (output / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'status': result['status'], 'checks': result['checks']}))
    return 0 if result['status'] == 'PASS' else 1


if __name__ == '__main__':
    sys.exit(main())
