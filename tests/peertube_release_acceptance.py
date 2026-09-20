#!/usr/bin/env python3
"""Configure a COPY rehearsal on a retained, disposable release B2 host.

Reuses the runtime recorder; never installs, wipes, or rewrites old evidence.
Inputs are copies of the generated fixture, verified against its retained hashes.
All configuration, SQL and raw logs stay in a new private directory on the host.
"""
import argparse
import json
import os
from pathlib import Path
import platform
import re
import secrets
import shutil
import tarfile
import subprocess
import time

import release_acceptance as runtime
from blank_server_smoke import require, sha
from release_acceptance_b2 import bucket_label, validate_spec

# The v0.6.4 drill's paths, now defaults rather than literals: the same harness
# runs against the v0.6.5 host without a source edit.
DEFAULT_BASELINE = Path('/root/vidra-v064-runtime')
DEFAULT_ROOT = Path('/root/vidra-v064-migration-20260911')
DEFAULT_B2_KEY = Path('/root/vidra-v064-b2-key.json')
# The generated PeerTube 8.0.0 fixture is the same input for every release.
HASHES = {
    'source-final.dump': 'ec26be5179544e8767c438dda2a26456da10f15d6536e63f38fdbc15f23b2273',
    'source-media-config.tgz': '9756abd405bb8e5801cb8fff4f4c76d3ac2fd6619879389668e445e187014b43',
}


def release_tag(candidate):
    """The release under rehearsal, named by the baseline's frozen candidate.

    Never a literal: a hard-coded tag both blocks the next release's host and,
    worse, would keep naming the OLD release in evidence produced on the new
    one.
    """
    tag = candidate.get('tag')
    # ASCII digits: unicode \d matches 'v٦.٥.٤', which names no tag, no release
    # asset and no container, but would pass the shape check and be used as one.
    require(isinstance(tag, str) and re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+', tag) is not None,
            f'baseline candidate carries no release tag: {tag!r}')
    return tag


def frozen_cli_sha256(candidate, tag):
    """The frozen CLI asset for this release, keyed by tag."""
    asset = candidate.get('assets', {}).get(f'vidra_{tag}_linux_amd64')
    require(isinstance(asset, dict) and asset.get('sha256'),
            f'baseline candidate ships no vidra_{tag}_linux_amd64 asset')
    return asset['sha256']


def scope(tag):
    return (f'Generated seven-video source through packaged {tag} admin import; '
            'not representative-source certification')


def source_container(tag, day=None):
    """`vidra-v065-migration-source-20260914`.

    The disposable PeerTube clone is named for the release it feeds and the day
    it was created, so two drills cannot collide on one host and no record can
    name the wrong release. The chosen name is RECORDED in the stage, and every
    later step (the checks, the browser driver, a continuation) reads it back
    from there rather than recomputing it: a step run on a later day must not
    address a different database.
    """
    return f'vidra-{bucket_label(tag)}-migration-source-{day or time.strftime("%Y%m%d", time.gmtime())}'


def check_source_container(container, tag, where):
    """The recorded clone name must be THIS release's own, not merely nonempty.

    `source_container()` builds the name and the stage records it; every later
    step reads it back rather than recomputing it, which is what stops a step
    run on a later day from addressing a different database. Accepting any
    nonempty string left the recorded name unverified: a v0.6.4 clone left
    running on the host answers `docker exec ... psql` exactly as a v0.6.5 one
    does, so the wrong release's database would be reconciled and the evidence
    would still be stamped with this release.
    """
    require(isinstance(container, str) and
            re.fullmatch(rf'vidra-{bucket_label(tag)}-migration-source-[0-9]{{8}}', container) is not None,
            f'{where} records no {tag} source_container ({container!r}); '
            'prepare the stage for this release with this harness')
    return container


def check_stage_prepared_for(prior, baseline, tag):
    """A stage carries the baseline and the release it was prepared against.

    `--baseline` and `--root` are supplied again on every later step, so a typo
    — or a second drill on the same host — could point a check at one release's
    stage while reading another release's candidate. The stage's own record is
    the second opinion. A field a legacy stage never wrote is accepted; a field
    that DISAGREES is not.
    """
    recorded = prior.get('baseline')
    require(recorded in (None, str(baseline)),
            f'stage was prepared against baseline {recorded}, not {baseline}')
    recorded = prior.get('candidate_tag')
    require(recorded in (None, tag), f'stage was prepared for release {recorded}, not {tag}')


def continuation_source(prepared_source, baseline, tag):
    """Validate a `--prepared-source` stage and return its recorded preparation.

    A continuation re-supplies `--baseline` as well, so the same typo that can
    point a check at another release's stage can point a continuation at one —
    and the generated PeerTube fixture hashes are IDENTICAL across releases, so
    nothing further down prepare() would notice. A v0.6.5 drill continued with
    `--prepared-source /root/vidra-v064-migration-20260911` would reuse that
    drill's container name and POSTGRES_PASSWORD and call the evidence v0.6.5.
    Everything here is read before the recorder, the clone or any host command
    exists, so a refusal leaves the host untouched.
    """
    prior = json.loads((prepared_source / 'preparation.json').read_text())
    check_stage_prepared_for(prior, baseline, tag)
    require(prior['status'] == 'FAIL' and prior['error'] == 'source role could write',
            'continuation is only for the preserved read-only probe recorder failure')
    # Continue against the database the original attempt created and recorded,
    # never a freshly derived name: a continuation run on a later day would
    # otherwise address a container that does not exist.
    check_source_container(prior.get('source_container'), tag,
                           f'{prepared_source}/preparation.json')
    return prior


def baseline_storage(baseline, tag):
    """The dedicated acceptance bucket the runtime milestone actually used.

    The drill copies media into object storage and reconciles the bytes back out
    of it, so it is defined only on a B2 baseline; a local-storage baseline has
    no bucket to compare against and must be refused loudly rather than
    silently reconciling nothing.
    """
    storage = json.loads((baseline / 'storage.json').read_text())
    backend = storage.get('backend')
    require(backend == 'b2',
            f'the migration drill is defined on the B2 host; {baseline} recorded backend {backend!r} '
            f'(a local-storage runtime baseline has no acceptance bucket to reconcile against)')
    spec = storage['spec']
    validate_spec(spec, tag)
    return spec


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
    # The release, the bucket whose bytes its evidence may cite, and (on a
    # continuation) the stage being continued are all facts established before
    # anything is created: every refusal below leaves the host untouched.
    candidate = json.loads((baseline / 'candidate.json').read_text())
    tag = release_tag(candidate)
    spec = baseline_storage(baseline, tag)
    prior = continuation_source(prepared_source, baseline, tag) if prepared_source else None
    run = runtime.Recorder(stage)
    result = {'status': 'UNVERIFIED', 'started_at': time.time(), 'checks': {},
              'scope': scope(tag), 'candidate_tag': tag, 'test_bucket': spec['bucket'],
              'baseline': str(baseline), 'source_inputs': HASHES,
              'tools_sha256': {p.name: sha(p) for p in Path(__file__).parent.glob('*') if p.is_file()}}
    try:
        require(sha(Path('/usr/local/bin/vidra')) == frozen_cli_sha256(candidate, tag),
                'installed CLI differs from frozen release asset')
        result['shipped_files'] = json.loads((baseline / 'frozen-deploy-hashes.json').read_text())
        for name, digest in result['shipped_files'].items():
            require(sha(runtime.INSTALL / name) == digest, f'released file changed: {name}')
        result['candidate_sha256'] = sha(baseline / 'candidate.json')
        result['before'] = runtime.runtime_snapshot(run, candidate)
        api = result['before']['images']['api']['container_id']
        info = json.loads(run.run(['docker', 'inspect', api], 'private-api-config'))[0]
        env = dict(v.split('=', 1) for v in info['Config']['Env'] if '=' in v)
        require(env['STORAGE_S3_BUCKET'] == spec['bucket'],
                f'wrong test bucket: the runtime uses {env["STORAGE_S3_BUCKET"]}, '
                f'the baseline recorded {spec["bucket"]}')
        require(env['MALWARE_SCAN_MODE'] == 'fail-closed', 'scanner must stay enabled')
        require(env.get('RATE_LIMIT_ENABLED') != 'false', 'rate limits must stay enabled')
        source_stage = prepared_source or stage
        if prepared_source:
            container = prior['source_container']
            result['prior_preparation'] = {'path': str(prepared_source), 'sha256': sha(prepared_source / 'preparation.json')}
        else:
            container = source_container(tag)
        result['source_container'] = container
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
            run.run(['docker', 'run', '-d', '--name', container, '--network', runtime.PROJECT + '_default',
                     '--env-file', str(run.private / 'source.env'),
                     '-v', str(stage / 'source-db') + ':/var/lib/postgresql', 'postgres:18-alpine'], 'new-source-database')
            for _ in range(60):
                if subprocess.run(['docker', 'exec', container, 'pg_isready', '-U', 'postgres'],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
                    break
                time.sleep(1)
            run.run(['docker', 'cp', str(stage / 'source-final.dump'), container + ':/tmp/source.dump'], 'copy-generated-dump')
            run.run(['docker', 'exec', container, 'pg_restore', '--exit-on-error', '--no-owner', '--no-acl',
                     '-U', 'postgres', '-d', 'peertube', '/tmp/source.dump'], 'restore-new-source')
            sql = run.private / 'source-role.sql'
            sql.write_text(f"CREATE ROLE migration_reader LOGIN PASSWORD '{password}';\n"
                           "GRANT CONNECT ON DATABASE peertube TO migration_reader;\n"
                           "GRANT USAGE ON SCHEMA public TO migration_reader;\n"
                           "GRANT SELECT ON ALL TABLES IN SCHEMA public TO migration_reader;\n"
                           "ALTER ROLE migration_reader SET default_transaction_read_only=on;\n")
            run.run(['docker', 'cp', str(sql), container + ':/tmp/source-role.sql'], 'copy-readonly-role')
            run.run(['docker', 'exec', container, 'psql', '-U', 'postgres', '-d', 'peertube', '-v', 'ON_ERROR_STOP=1',
                     '-f', '/tmp/source-role.sql'], 'create-readonly-role')
        refused = run.run(['docker', 'exec', container, 'psql', '-U', 'migration_reader', '-d', 'peertube',
                          '-v', 'ON_ERROR_STOP=1', '-c', 'BEGIN READ WRITE; UPDATE video SET name=name WHERE false; ROLLBACK;'],
                         'source-write-refused', expected=1)
        require('permission denied for table video' in refused, 'source role could write')
        result['checks']['source_read_only'] = 'PASS'
        dsn = run.private / 'source-dsn'
        dsn.write_text(f'postgres://migration_reader:{password}@{container}:5432/peertube?sslmode=disable')
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
    parser.add_argument('--baseline', type=Path, default=DEFAULT_BASELINE,
                        help='runtime-milestone stage naming the release, its frozen candidate and its test bucket')
    parser.add_argument('--prepared-source', type=Path, help='original failed read-only probe stage; writes a separate continuation')
    args = parser.parse_args()
    prepare(args.stage.resolve(), args.baseline.resolve(),
            args.prepared_source.resolve() if args.prepared_source else None)
