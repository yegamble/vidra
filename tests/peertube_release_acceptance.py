#!/usr/bin/env python3
"""Configure a COPY rehearsal on the retained, disposable v0.6.4 B2 host.

Reuses the runtime recorder; never installs, wipes, or rewrites old evidence.
Inputs are copies of the generated fixture, verified against its retained hashes.
All configuration, SQL and raw logs stay in a new private directory on the host.
"""
import argparse
import json
import os
from pathlib import Path
import platform
import secrets
import shutil
import tarfile
import subprocess
import time

import release_acceptance as runtime
from blank_server_smoke import require, sha

SOURCE = 'vidra-v064-migration-source-20260911'
HASHES = {
    'source-final.dump': 'ec26be5179544e8767c438dda2a26456da10f15d6536e63f38fdbc15f23b2273',
    'source-media-config.tgz': '9756abd405bb8e5801cb8fff4f4c76d3ac2fd6619879389668e445e187014b43',
}


def media_members(archive):
    # Configuration and logs are unnecessary for import; never unpack them.
    for member in archive.getmembers():
        path = Path(member.name)
        if path.parts[:1] != ('source-media8',):
            continue
        require('..' not in path.parts and not path.is_absolute(), 'unsafe archive path')
        require(member.isfile() or member.isdir(), 'source archive contains a link/device')
        if any(part in ('logs', 'tmp', 'tmp-persistent', 'cache', 'bin', 'plugins') for part in path.parts):
            continue
        member.mode = 0o555 if member.isdir() else 0o444
        yield member


def source_mount(text, directory):
    anchor = '\n  - media_data:/app/data\n'
    require(text.count(anchor) == 1, 'unexpected production volume anchor')
    return text.replace(anchor, anchor + f'  - {directory}:/peertube-source:ro\n')


def prepare(stage, baseline, prepared_source=None):
    os.umask(0o077)
    require(platform.machine() == 'x86_64' and platform.system() == 'Linux', 'native AMD64 host required')
    require(not (stage / 'private').exists(), 'new stage required; retain failed attempt')
    if not prepared_source:
        require(all(not (stage / name).exists() and not (stage / name).is_symlink()
                    for name in ('source-media8', 'source-db')), 'source paths must be new')
    run = runtime.Recorder(stage)
    result = {'status': 'UNVERIFIED', 'started_at': time.time(), 'checks': {},
              'scope': 'Generated seven-video source through packaged v0.6.4 admin import; not representative-source certification',
              'baseline': str(baseline), 'source_inputs': HASHES,
              'tools_sha256': {p.name: sha(p) for p in Path(__file__).parent.glob('*') if p.is_file()}}
    try:
        candidate = json.loads((baseline / 'candidate.json').read_text())
        require(candidate['tag'] == 'v0.6.4', 'wrong candidate')
        require(sha(Path('/usr/local/bin/vidra')) == candidate['assets']['vidra_v0.6.4_linux_amd64']['sha256'],
                'installed CLI differs from frozen release asset')
        result['shipped_files'] = json.loads((baseline / 'frozen-deploy-hashes.json').read_text())
        for name, digest in result['shipped_files'].items():
            require(sha(runtime.INSTALL / name) == digest, f'released file changed: {name}')
        result['candidate_sha256'] = sha(baseline / 'candidate.json')
        result['before'] = runtime.runtime_snapshot(run, candidate)
        api = result['before']['images']['api']['container_id']
        info = json.loads(run.run(['docker', 'inspect', api], 'private-api-config'))[0]
        env = dict(v.split('=', 1) for v in info['Config']['Env'] if '=' in v)
        require(env['STORAGE_S3_BUCKET'] == 'vidra-acceptance-v064-20260911-media', 'wrong test bucket')
        require(env['MALWARE_SCAN_MODE'] == 'fail-closed', 'scanner must stay enabled')
        require(env.get('RATE_LIMIT_ENABLED') != 'false', 'rate limits must stay enabled')
        source_stage = prepared_source or stage
        if prepared_source:
            prior = json.loads((prepared_source / 'preparation.json').read_text())
            require(prior['status'] == 'FAIL' and prior['error'] == 'source role could write',
                    'continuation is only for the preserved read-only probe recorder failure')
            result['prior_preparation'] = {'path': str(prepared_source), 'sha256': sha(prepared_source / 'preparation.json')}
        for name, digest in HASHES.items():
            require(sha(source_stage / name) == digest, 'generated fixture hash mismatch')
        if not prepared_source:
            with tarfile.open(stage / 'source-media-config.tgz') as archive:
                archive.extractall(stage, members=media_members(archive))
        media = source_stage / 'source-media8'
        result['source_media'] = {str(p.relative_to(media)): sha(p) for p in sorted(media.rglob('*')) if p.is_file()}
        if prepared_source:
            require(result['source_media'] == prior['source_media'], 'source media changed after failed probe')
            password = dict(line.split('=', 1) for line in (prepared_source / 'private/source.env').read_text().splitlines())['POSTGRES_PASSWORD']
        else:
            # New source database/container only; no connection to the retained lab.
            password = secrets.token_hex(24)
            (run.private / 'source.env').write_text(f'POSTGRES_PASSWORD={password}\nPOSTGRES_DB=peertube\n')
            run.run(['docker', 'run', '-d', '--name', SOURCE, '--network', runtime.PROJECT + '_default',
                     '--env-file', str(run.private / 'source.env'),
                     '-v', str(stage / 'source-db') + ':/var/lib/postgresql', 'postgres:18-alpine'], 'new-source-database')
            for _ in range(60):
                if subprocess.run(['docker', 'exec', SOURCE, 'pg_isready', '-U', 'postgres'],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
                    break
                time.sleep(1)
            run.run(['docker', 'cp', str(stage / 'source-final.dump'), SOURCE + ':/tmp/source.dump'], 'copy-generated-dump')
            run.run(['docker', 'exec', SOURCE, 'pg_restore', '--exit-on-error', '--no-owner', '--no-acl',
                     '-U', 'postgres', '-d', 'peertube', '/tmp/source.dump'], 'restore-new-source')
            sql = run.private / 'source-role.sql'
            sql.write_text(f"CREATE ROLE migration_reader LOGIN PASSWORD '{password}';\n"
                           "GRANT CONNECT ON DATABASE peertube TO migration_reader;\n"
                           "GRANT USAGE ON SCHEMA public TO migration_reader;\n"
                           "GRANT SELECT ON ALL TABLES IN SCHEMA public TO migration_reader;\n"
                           "ALTER ROLE migration_reader SET default_transaction_read_only=on;\n")
            run.run(['docker', 'cp', str(sql), SOURCE + ':/tmp/source-role.sql'], 'copy-readonly-role')
            run.run(['docker', 'exec', SOURCE, 'psql', '-U', 'postgres', '-d', 'peertube', '-v', 'ON_ERROR_STOP=1',
                     '-f', '/tmp/source-role.sql'], 'create-readonly-role')
        refused = run.run(['docker', 'exec', SOURCE, 'psql', '-U', 'migration_reader', '-d', 'peertube',
                          '-v', 'ON_ERROR_STOP=1', '-c', 'BEGIN READ WRITE; UPDATE video SET name=name WHERE false; ROLLBACK;'],
                         'source-write-refused', expected=1)
        require('permission denied for table video' in refused, 'source role could write')
        result['checks']['source_read_only'] = 'PASS'
        dsn = run.private / 'source-dsn'
        dsn.write_text(f'postgres://migration_reader:{password}@{SOURCE}:5432/peertube?sslmode=disable')
        env_file = runtime.INSTALL / 'env/production.env'
        prod = runtime.INSTALL / 'docker-compose.prod.yml'
        for p in (env_file, prod):
            shutil.copyfile(p, run.private / p.name)
        before_env = dict(line.split('=', 1) for line in env_file.read_text().splitlines() if '=' in line and not line.startswith('#'))
        run.run(['vidra', 'setup', '--template', 'env/production.env.example', '--output', 'env/production.env',
                 '--non-interactive', '--yes', '--no-caddy', '--peertube', '--peertube-source-url', '@' + str(dsn),
                 '--peertube-source-storage', 'local', '--peertube-source-local-root', '/peertube-source',
                 '--peertube-media-mode', 'copy'], 'released-setup-source')
        after_env = dict(line.split('=', 1) for line in env_file.read_text().splitlines() if '=' in line and not line.startswith('#'))
        require({k: v for k, v in before_env.items() if not k.startswith('PEERTUBE_')} ==
                {k: v for k, v in after_env.items() if not k.startswith('PEERTUBE_')}, 'setup changed unrelated configuration')
        prod.write_text(source_mount(prod.read_text(), media))
        result['configuration_change'] = 'Released setup PEERTUBE_* flags and one read-only source-media mount on api/optional worker; images and scripts unchanged'
        run.compose('config', '-q')
        run.run(['bash', 'deploy/deploy.sh'], 'released-deploy-source', timeout=1800)
        runtime.wait_for_runtime(run)
        result['after'] = runtime.runtime_snapshot(run, candidate)
        result['checks']['published_setup_deploy'] = 'PASS'
        result['status'] = 'PASS'
    except Exception as error:
        result.update(status='FAIL', error=str(error))
        raise
    finally:
        result['finished_at'] = time.time()
        runtime.save(stage / 'preparation.json', result)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', type=Path)
    parser.add_argument('--baseline', type=Path, default=Path('/root/vidra-v064-runtime'))
    parser.add_argument('--prepared-source', type=Path, help='original failed read-only probe stage; writes a separate continuation')
    args = parser.parse_args()
    prepare(args.stage.resolve(), args.baseline.resolve(), args.prepared_source)
