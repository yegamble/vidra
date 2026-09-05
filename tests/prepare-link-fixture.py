#!/usr/bin/env python3
"""Install an exact-source A08 lab fixture using the existing deploy gates."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import time


def run(args, **kwargs):
    return subprocess.check_output(args, text=True, timeout=1200, stderr=subprocess.STDOUT, **kwargs)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    a03_dir, source_dir, bundle_path, image_archive, output_dir = map(Path, sys.argv[1:])
    a03 = json.loads((a03_dir / 'result.json').read_text())
    vm = (a03_dir / 'vm-name.txt').read_text().strip()
    assert re.fullmatch(r'vidra-a02-\d+-\d+', vm)
    assert re.fullmatch(r'vidra-a03-\d+-\d+', a03['project'])
    assert a03['status'] == 'PASS' and a03['checks']['recovery'] == 'PASS'
    sources = json.loads((source_dir / 'source.json').read_text())
    images = json.loads((source_dir / 'images.json').read_text())
    with tarfile.open(bundle_path) as archive:
        manifest = archive.extractfile('./vidra-bundle.manifest').read().decode()
    fields = dict(line.split('=', 1) for line in manifest.splitlines() if line and not line.startswith('#'))
    assert fields['core_commit'] == sources['vidra-core']['revision']
    expected = max(int(p.name.split('_')[0]) for p in (source_dir / 'vidra-core/migrations').glob('*.up.sql'))
    assert int(fields['core_schema_version']) == expected
    assert fields['tag'] == 'v999.8.0', 'this is a lab-only bundle, never a published release'
    output_dir.mkdir(mode=0o700)
    root = '/home/ubuntu/vidra-a08-' + str(int(time.time()))
    result = dict(status='UNVERIFIED', vm=vm, project=a03['project'], guest_root=root,
                  sources=sources, images=images, expected_core_schema=expected,
                  bundle_sha256=digest(bundle_path), image_archive_sha256=digest(image_archive),
                  helper_sha256=digest(__file__), checks={})
    def checkpoint():
        (output_dir / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    def guest(*args):
        return run(['multipass', 'exec', vm, '--', 'sudo', *args])
    checkpoint()
    try:
        run(['multipass', 'start', vm])
        guest('mkdir', '-m', '700', root)
        for src, name in ((bundle_path, 'bundle.tar.gz'), (image_archive, 'images.tar')):
            # Transfer lands in the user's home; root-only staging then keeps the
            # copied configuration and deploy output off shared paths.
            temporary = root + '-' + name
            run(['multipass', 'transfer', str(src), vm + ':' + temporary])
            guest('mv', temporary, root + '/' + name)
        guest('docker', 'load', '-i', root + '/images.tar')
        for tag, expected_id in images.items():
            assert guest('docker', 'image', 'inspect', tag, '--format', '{{.Id}}').strip() == expected_id
        result['checks']['loaded_exact_images'] = 'PASS'
        old = '/home/ubuntu/' + a03['project'] + '/private/installation'
        # The generated manifest stays byte-for-byte untouched. Only the lab's
        # image transport changes: local immutable images, deliberately no registry
        # publication. deploy.sh still runs its normal pull step (policy never),
        # dump, discrete migrators and independent manifest-ledger assertions.
        prepare = r'''
import json,pathlib,re,shutil,subprocess,sys,tarfile
root=pathlib.Path(sys.argv[1]); old=pathlib.Path(sys.argv[2]); tree=root/'installation'
tree.mkdir()
with tarfile.open(root/'bundle.tar.gz') as t:
    assert all(not m.name.startswith('/') and '..' not in pathlib.PurePosixPath(m.name).parts for m in t.getmembers())
    t.extractall(tree)
shutil.copy2(old/'env/production.env',tree/'env/production.env')
shutil.copy2(old/'deploy/Caddyfile.local',tree/'deploy/Caddyfile.local')
env=tree/'env/production.env'; text=env.read_text()
for key in ('VIDRA_CORE_TAG','VIDRA_USER_TAG'):
    text,n=re.subn(r'^'+key+r'=.*$',key+'=v999.8.0',text,flags=re.M); assert n==1
env.write_text(text);env.chmod(0o600)
p=tree/'docker-compose.prod.yml'; text=p.read_text()
pins={}
for service in ('postgres','redis','caddy','search','prep-volumes'):
    cid=sys.argv[3]+'-'+service+'-1'
    image=json.loads(subprocess.check_output(['docker','inspect',cid]))[0]['Image']
    architecture=json.loads(subprocess.check_output(['docker','image','inspect',image]))[0]['Architecture']
    pins[service]=(image,'linux/'+architecture)
pins['search-migrate']=pins['search']
all_images={**pins,'api':('vidra-core:a08-source','linux/arm64'),'migrate':('vidra-core:a08-source','linux/arm64'),'frontend':('vidra-user:a08-source','linux/arm64')}
for service,(tag,platform) in all_images.items():
    pattern=r'(?m)(^  '+service+r':\n)(.*?)(?=^  [a-zA-Z_-]+:|\Z)'
    def replace(m):
        body,n=re.subn(r'(?m)^    image:.*$', '    image: '+tag, m.group(2));assert n<=1
        if n==0: body='    image: '+tag+'\n'+body
        body=re.sub(r'(?m)^    (pull_policy|platform):.*\n','',body)
        return m.group(1)+'    pull_policy: never\n    platform: '+platform+'\n'+body
    text,n=re.subn(pattern,replace,text,flags=re.S);assert n==1
p.write_text(text)
print(json.dumps(pins))
'''
        result['preserved_images'] = json.loads(guest('python3', '-c', prepare, root, old, a03['project']))
        checkpoint()
        command = ['multipass', 'exec', vm, '--', 'sudo', 'env',
                   'COMPOSE_PROJECT_NAME=' + a03['project'], 'bash',
                   root + '/installation/deploy/deploy.sh']
        with (output_dir / 'private-deploy.log').open('w') as log:
            completed = subprocess.run(command, text=True, stdout=log, stderr=subprocess.STDOUT, timeout=1200)
        assert completed.returncode == 0, 'normal deploy failed; preserve private log, do not bypass its gates'
        result['checks']['normal_deploy'] = 'PASS'
        row = guest('docker', 'exec', a03['project'] + '-postgres-1', 'psql', '-U', 'vidra', '-d', 'vidra', '-At', '-c', 'SELECT version,dirty FROM schema_migrations;').strip()
        assert row == str(expected) + '|f'
        result['core_ledger'] = row
        result['checks']['independent_schema'] = 'PASS'
        result['status'] = 'PASS'
    except Exception as error:
        result['status'] = 'FAIL'
        (output_dir / 'private-error.txt').write_text(str(error))
    finally:
        checkpoint()
    print('A08 fixture ' + result['status'] + ': ' + str(output_dir))
    return 0 if result['status'] == 'PASS' else 1


if __name__ == '__main__':
    sys.exit(main())
