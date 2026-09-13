#!/usr/bin/env python3
"""Export reviewed recovery-drill evidence from one acceptance host.

Named result files and screenshots only. Raw command output stays private on
the host and is represented by its SHA-256; container health-probe output is
hashed the same way. Before anything is written the export is scanned for every
real secret this host holds (env-file secrets, the test-bucket key, the owner
password, the TOTP secret and recovery codes) and refused on any match. The
manifest records what the scan actually loaded (`secrets_loaded`), and an
export whose env scan set is empty is refused: "no secret found" must never be
mistaken for "no secret looked for".

  python3 recovery_release_export.py DRILL_DIR OUT_DIR STAGE [STAGE...]
"""
import hashlib
import json
from pathlib import Path
import re
import sys

# `_KEY_ID` is included on purpose: a bucket key id is half of a credential
# pair and must not reach the public record either.
SECRET_KEY = re.compile(r'(SECRET|PASSWORD|TOKEN|KEK|_KEY$|_KEY_ID$|ACCESS_KEY)')

# Where a v0.6.4 acceptance host keeps the secrets the scan must know about.
ENV_FILE = Path('/opt/vidra/env/production.env')
BUCKET_KEY_FILE = Path('/root/vidra-v064-b2-key.json')
OWNER_FILE = Path('/root/vidra-v064-runtime/private/owner.json')


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


def host_secrets(drill, env_file=ENV_FILE, bucket_key_file=BUCKET_KEY_FILE, owner_file=OWNER_FILE):
    """Collect the host's secret values and record what was actually loaded.

    The v0.6.4 drill exports were scanned by a revision that read each source
    only `if path.exists()` and kept no note of it, so a missing file silently
    shrank the scan. `loaded` is written into the export manifest so the record
    says which sources the scan covered; export() refuses an empty env set.
    """
    secrets = set()
    loaded = {'env': 0, 'bucket_key': False, 'mfa': False, 'owner': False}
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                key, value = line.split('=', 1)
                value = value.strip().strip('"\'')
                if SECRET_KEY.search(key.strip()) and len(value) >= 8:
                    secrets.add(value)
                    loaded['env'] += 1
    def collect(value):
        if isinstance(value, dict):
            for child in value.values():
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)
        elif isinstance(value, str) and len(value) >= 8:
            secrets.add(value)
    for name, path in (('bucket_key', bucket_key_file), ('mfa', drill / 'private/mfa.json')):
        if path.exists():
            collect(json.loads(path.read_text()))
            loaded[name] = True
    if owner_file.exists():
        secrets.add(json.loads(owner_file.read_text())['password'])
        loaded['owner'] = True
    return secrets, loaded


def leaks(files, secrets):
    found = []
    for name, data in files.items():
        for secret in secrets:
            if secret.encode() in data:
                found.append(name)
                break
    return sorted(found)


def export(drill, out, stages, **sources):
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
    secrets, loaded = host_secrets(drill, **sources)
    if loaded['env'] == 0:
        raise SystemExit('refusing export: no env secret was loaded, so a clean scan would prove nothing '
                         f'(env file {sources.get("env_file", ENV_FILE)} missing or without secret keys)')
    found = leaks(files, secrets)
    if found:
        raise SystemExit(f'refusing export: host secret material found in {found}')
    out.mkdir(mode=0o700)
    for name, data in files.items():
        target = out / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    manifest = {name: sha_bytes(data) for name, data in sorted(files.items())}
    # The v0.6.4 exports (exporter sha256 12b22ba4…) wrote the bare name→hash
    # map; the manifest now nests it under `files` beside the scan set.
    (out / 'artifact-hashes.json').write_text(
        json.dumps({'files': manifest, 'secrets_loaded': loaded}, indent=2) + '\n')
    return manifest


if __name__ == '__main__':
    if len(sys.argv) < 4:
        raise SystemExit(__doc__)
    manifest = export(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3:])
    print(json.dumps({'files': len(manifest)}))
