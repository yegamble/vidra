#!/usr/bin/env python3
"""Export named, secret-checked migration results; retain all raw failures privately."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tarfile

from blank_server_smoke import sha


def reject_secrets(content, secrets):
    assert not any(secret and secret in content for secret in secrets), 'secret detected; export refused'
    # Match PEM content, not the scanner's own marker literals in tool source.
    assert not re.search(r'-----BEGIN (?:RSA |EC )?PRIVATE KEY-----(?:\\n|\s)', content), 'private key detected'
    assert not re.search(r'\$2[aby]\$\d{2}\$[./A-Za-z0-9]{53}', content), 'password hash detected'


def export(label='reviewed'):
    os.umask(0o077)
    root = Path('/root/vidra-v064-migration-20260911')
    stage = Path(str(root) + '-ready')
    assert re.fullmatch(r'reviewed(?:-v[0-9]+)?', label), 'invalid export attempt label'
    out = Path(str(root) + '-' + label)
    out.mkdir(mode=0o700)
    provenance = {'raw_files': {}, 'raw_logs': [], 'tool_files': {}, 'scope':
                  'Generated-source packaged COPY milestone. Raw credentials, SQL dumps, configuration and logs remain private.'}

    def sanitized(value):
        if isinstance(value, dict):
            return {('output_sha256' if k == 'Output' else k):
                    (hashlib.sha256(v.encode()).hexdigest() if k == 'Output' else sanitized(v))
                    for k, v in value.items()}
        if isinstance(value, list):
            return [sanitized(v) for v in value]
        return value

    def save(name, value):
        (out / name).write_text(json.dumps(value, indent=2) + '\n')

    sources = [(root, 'prepare-original'), (Path(str(root) + '-continuation'), 'prepare-continuation'),
               (stage, 'prepare-ready')]
    for directory, label in sources:
        path = directory / 'preparation.json'
        provenance['raw_files'][str(path)] = sha(path)
        save(label + '.json', sanitized(json.loads(path.read_text())))
    for path in sorted(stage.glob('*-browser.json')):
        value = json.loads(path.read_text())
        assert value['status'] in ('PASS', 'FAIL'), 'browser still running'
        provenance['raw_files'][str(path)] = sha(path)
        save(path.name, sanitized(value))
    for path in sorted(stage.glob('*/result.json')):
        provenance['raw_files'][str(path)] = sha(path)
        save(path.parent.name + '.json', sanitized(json.loads(path.read_text())))
    commands = []
    for directory in [root, Path(str(root) + '-continuation'), stage, *sorted(p for p in stage.iterdir() if p.is_dir())]:
        path = directory / 'private/commands.jsonl'
        if not path.exists():
            continue
        provenance['raw_files'][str(path)] = sha(path)
        for line in path.read_text().splitlines():
            row = json.loads(line)
            row['directory'] = str(directory)
            row['log_sha256'] = sha(directory / 'private' / row['log'])
            row['log_visibility'] = 'private; only hash exported'
            commands.append(row)
    save('commands.json', commands)
    for path in sorted(stage.glob('*.png')):
        shutil.copyfile(path, out / path.name)
        provenance['raw_files'][str(path)] = sha(path)
    # Source snapshots are public harness code, including the failed revisions.
    tool_texts = []
    tool_sources = []
    for directory, label in sources:
        for path in sorted((directory / 'tools').glob('*')):
            if path.is_file() and path.suffix in ('.py', '.mjs'):
                name = label + '/' + path.name
                tool_texts.append(path.read_text())
                tool_sources.append((path, name))
                provenance['tool_files'][name] = sha(path)

    secrets = []
    for path in (root / 'private/source.env', Path('/opt/vidra/env/production.env')):
        for line in path.read_text().splitlines():
            if '=' in line and not line.startswith('#'):
                key, value = line.split('=', 1)
                if any(word in key for word in ('SECRET', 'PASSWORD', 'TOKEN', 'KEK', 'KEY', 'SOURCE_URL')) and len(value) >= 12:
                    secrets.append(value.strip('"\''))
    secrets.append(json.loads(Path('/root/vidra-v064-runtime/private/owner.json').read_text())['password'])
    secrets.extend(json.loads(Path('/root/vidra-v064-b2-key.json').read_text()).values())
    # The source is stopped for COPY independence. Exported result fields carry
    # aggregate counts/fingerprints, never account records or actor key material.
    for content in [p.read_text() for p in out.glob('*.json')] + tool_texts:
        reject_secrets(content, secrets)
    save('provenance.json', {**provenance, 'secret_scan': 'PASS', 'export_tool_sha256': sha(Path(__file__))})
    with tarfile.open(out / 'historical-tools.tar.gz', 'w:gz') as archive:
        for path, name in tool_sources:
            archive.add(path, arcname=name)
    save('artifact-hashes.json', {p.name: sha(p) for p in sorted(out.iterdir())})
    archive_path = Path(str(out) + '.tar.gz')
    with tarfile.open(archive_path, 'w:gz') as archive:
        for path in sorted(out.iterdir()):
            archive.add(path, arcname=path.name)
    print(json.dumps({'secret_scan': 'PASS', 'archive_sha256': sha(archive_path), 'files': len(list(out.iterdir()))}))


if __name__ == '__main__':
    export(sys.argv[1] if len(sys.argv) == 2 else 'reviewed')
