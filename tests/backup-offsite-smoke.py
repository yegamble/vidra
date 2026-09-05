#!/usr/bin/env python3
"""Required encrypted B2/S3 round trip for a synthetic A36 recovery set.

Usage: SOURCE_DIR PRIVATE_RCLONE_CONFIG PRIVATE_S3_KEY_JSON TEST_BUCKET NEW_OUTPUT
The private config/key are provisioned separately with operator authorization.
"""
import configparser
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile

source, config, keyfile = map(Path, sys.argv[1:4])
bucket, output_name = sys.argv[4:]
assert re.fullmatch(r'vidra-acceptance-[a-z0-9-]+', bucket)
output = Path(output_name)
output.mkdir(mode=0o700)
record = json.loads((source / 'result.json').read_text())
assert record['status'] == 'PASS' and record['project'].startswith('vidra-a03-')
settings = configparser.ConfigParser(interpolation=None)
settings.read(config)
assert settings['encrypted']['type'] == 'crypt' and settings['encrypted']['password']
assert settings['encrypted']['remote'] == 'b2s3:' + bucket + '/a36'
assert settings['b2s3']['endpoint'] == 'https://s3.us-east-005.backblazeb2.com'
assert settings['b2s3']['no_check_bucket'] == 'true'
key = json.loads(keyfile.read_text())
env = {**os.environ, 'AWS_ACCESS_KEY_ID': key['id'], 'AWS_SECRET_ACCESS_KEY': key['key'],
       'AWS_EC2_METADATA_DISABLED': 'true'}
base = ['rclone', '--config', str(config)]
prefix = record['files']['dump']['name'].removeprefix('vidra-').removesuffix('.dump.gz')
assert re.fullmatch(r'\d{8}T\d{6}Z', prefix)
remote = 'encrypted:' + prefix
result = dict(status='UNVERIFIED', bucket=bucket, endpoint=settings['b2s3']['endpoint'],
              helper_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              capture=record, transport='S3', client_encryption='rclone crypt', files={})

def run(args):
    return subprocess.run(args, check=True, capture_output=True, timeout=180, env=env)

try:
    for kind, info in record['files'].items():
        name = info['name']
        assert Path(name).name == name
        assert hashlib.sha256((source / name).read_bytes()).hexdigest() == info['sha256']
        run([*base, 'copyto', str(source / name), remote + '/' + name])
    logical = json.loads(run([*base, 'lsjson', remote]).stdout)
    assert len(logical) == 3
    raw = json.loads(run([*base, 'lsjson', 'b2s3:' + bucket + '/a36', '--recursive']).stdout)
    objects = [x for x in raw if not x['IsDir']]
    names = {f['name'] for f in record['files'].values()}
    assert len(objects) >= 3 and not any(x['Name'] in names for x in objects)
    recovered = output / 'recovered'
    recovered.mkdir(mode=0o700)
    run([*base, 'copy', remote, str(recovered)])
    for kind, info in record['files'].items():
        path = recovered / info['name']
        path.chmod(0o600)
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        assert digest == info['sha256'] and len(data) == info['bytes']
        result['files'][kind] = dict(bytes=len(data), sha256=digest, matches=True)
    header = run([*base, 'cat', 'b2s3:' + bucket + '/a36/' + objects[0]['Path'], '--count', '8']).stdout
    assert header == b'RCLONE\x00\x00'
    result['ciphertext_header_verified'] = True
    a06 = json.loads(Path('docs/evidence/a06-upload.json').read_text())
    with tarfile.open(recovered / record['files']['media']['name']) as archive:
        media = [m for m in archive.getmembers() if m.isfile()]
        matches = [m for m in media if m.size == a06['fixture_bytes'] and
                   hashlib.sha256(archive.extractfile(m).read()).hexdigest() == a06['fixture_sha256']]
        assert matches
        result['media_files'] = len(media)
        result['exact_a06_media_matches'] = len(matches)
    result['recovered_archives'] = 3
    result['status'] = 'PASS'
except subprocess.CalledProcessError as error:
    (output / 'private-error.log').write_bytes(error.stderr or b'')
    raise RuntimeError('offsite command failed; inspect private log') from None
finally:
    (output / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps({'status': result['status'], 'bucket': bucket, 'recovered_archives': 3}))
