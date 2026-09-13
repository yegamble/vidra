#!/usr/bin/env python3
"""Export reviewed recovery-drill evidence from one acceptance host.

Named result files and screenshots only. Raw command output stays private on
the host and is represented by its SHA-256; container health-probe output is
hashed the same way. Before anything is written the export is scanned for every
real secret this host holds (env-file secrets, the test-bucket key, the owner
password, the TOTP secret and recovery codes) and refused on any match.

  python3 recovery_release_export.py DRILL_DIR OUT_DIR STAGE [STAGE...]
"""
import hashlib
import json
from pathlib import Path
import re
import sys

SECRET_KEY = re.compile(r'(SECRET|PASSWORD|TOKEN|KEK|_KEY$|ACCESS_KEY)')


def sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


def hash_health_output(value):
    if isinstance(value, dict):
        if 'Output' in value and isinstance(value['Output'], str):
            value['output_sha256'] = sha_bytes(value.pop('Output').encode())
        for child in value.values():
            hash_health_output(child)
    elif isinstance(value, list):
        for child in value:
            hash_health_output(child)
    return value


def host_secrets(drill):
    secrets = set()
    env = Path('/opt/vidra/env/production.env')
    if env.exists():
        for line in env.read_text().splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                key, value = line.split('=', 1)
                value = value.strip().strip('"\'')
                if SECRET_KEY.search(key.strip()) and len(value) >= 8:
                    secrets.add(value)
    def collect(value):
        if isinstance(value, dict):
            for child in value.values():
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)
        elif isinstance(value, str) and len(value) >= 8:
            secrets.add(value)
    for path in (Path('/root/vidra-v064-b2-key.json'), drill / 'private/mfa.json'):
        if path.exists():
            collect(json.loads(path.read_text()))
    owner = Path('/root/vidra-v064-runtime/private/owner.json')
    if owner.exists():
        secrets.add(json.loads(owner.read_text())['password'])
    return secrets


def leaks(files, secrets):
    found = []
    for name, data in files.items():
        for secret in secrets:
            if secret.encode() in data:
                found.append(name)
                break
    return sorted(found)


def export(drill, out, stages):
    files = {}
    for stage in stages:
        directory = drill / stage
        result = hash_health_output(json.loads((directory / 'result.json').read_text()))
        files[f'{stage}/result.json'] = (json.dumps(result, indent=2) + '\n').encode()
        commands = directory / 'private/commands.jsonl'
        if commands.exists():
            rows = []
            for line in commands.read_text().splitlines():
                row = json.loads(line)
                log = directory / 'private' / row['log']
                row['log_sha256'] = sha_bytes(log.read_bytes()) if log.exists() else None
                row['log_visibility'] = 'retained privately on host; output not exported'
                rows.append(row)
            files[f'{stage}/commands.json'] = (json.dumps(rows, indent=2) + '\n').encode()
        for image in sorted(directory.glob('*.png')):
            files[f'{stage}/{image.name}'] = image.read_bytes()
    found = leaks(files, host_secrets(drill))
    if found:
        raise SystemExit(f'refusing export: host secret material found in {found}')
    out.mkdir(mode=0o700)
    for name, data in files.items():
        target = out / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    manifest = {name: sha_bytes(data) for name, data in sorted(files.items())}
    (out / 'artifact-hashes.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return manifest


if __name__ == '__main__':
    if len(sys.argv) < 4:
        raise SystemExit(__doc__)
    manifest = export(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3:])
    print(json.dumps({'files': len(manifest)}))
