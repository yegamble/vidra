#!/usr/bin/env python3
"""Exercise same-host rollback and recovery of newer content on disposable local Docker volumes."""
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
# The API fixture's deep check hashes each file against a real PostgreSQL row.
# Public ports and external networks are unnecessary for this rehearsal.
MODEL = """
services:
  postgres:
    image: postgres:18-alpine
    environment:
      POSTGRES_USER: fixture
      POSTGRES_DB: fixture
      POSTGRES_HOST_AUTH_METHOD: trust
    volumes: [pg:/var/lib/postgresql]
    healthcheck:
      test: ["CMD", pg_isready, -h, 127.0.0.1, -U, fixture, -d, fixture]
      interval: 1s
      timeout: 3s
      retries: 40
  redis:
    image: redis:8-alpine
    volumes: [cache:/data]
    healthcheck:
      test: ["CMD", redis-cli, ping]
      interval: 1s
      timeout: 3s
      retries: 40
  prep-volumes:
    image: alpine:3.24
    command: ["true"]
  api:
    image: ${FIXTURE_CORE_IMAGE:?}:${VIDRA_CORE_TAG:?}
    entrypoint: [sh, /fixture/api]
    command: [serve]
    environment:
      STORAGE_BACKEND: local
      STORAGE_LOCAL_ROOT: /app/data/media
      DATABASE_URL: postgresql://fixture@postgres:5432/fixture
      REDIS_URL: redis://redis:6379/0
      SMOKE_VERSION: ${VIDRA_CORE_TAG:?}
      PGHOST: postgres
      PGDATABASE: fixture
      PGUSER: fixture
    tmpfs: [/var/lib/postgresql]
    volumes:
      - media:/app/data
      - ./deploy/probe:/fixture/api:ro
  frontend:
    image: alpine:3.24
    entrypoint: [sh, /fixture/api]
    command: [serve]
    environment:
      SMOKE_VERSION: ${VIDRA_USER_TAG:?}
    volumes: [./deploy/probe:/fixture/api:ro]
  search:
    image: alpine:3.24
    entrypoint: [sh, /fixture/api]
    command: [serve]
    environment:
      SMOKE_VERSION: ${VIDRA_SEARCH_TAG:?}
      DATABASE_URL: postgresql://fixture@postgres:5432/fixture
      REDIS_URL: redis://redis:6379/0
    volumes: [./deploy/probe:/fixture/api:ro]
  pds:
    image: alpine:3.24
    entrypoint: [sh, /fixture/api]
    command: [serve]
    volumes:
      - ./deploy/probe:/fixture/api:ro
      - ./data/atproto-pds:/pds
volumes:
  pg: {}
  media: {}
  cache: {}
networks:
  default:
    internal: true
"""

PROBE = """#!/bin/sh
set -eu
case "$1" in
    serve) trap 'exit 0' TERM INT; while :; do sleep 1 & wait $!; done ;;
    verify-blobs)
        [ "$*" = 'verify-blobs --hash --deep --json --timeout=4h' ]
        psql -XAt -F ' ' -v ON_ERROR_STOP=1 -c 'SELECT digest, filename FROM photos ORDER BY filename' |
            (cd /app/data/media && md5sum -c - >&2)
        echo '{"deep_verification_version":1}' ;;
    *) exit 2 ;;
esac
"""


def command(argv, *, env, cwd, capture=False):
    result = subprocess.run(
        argv, env=env, cwd=cwd, text=True, check=True, stdout=subprocess.PIPE if capture else None
    )
    return result.stdout.strip() if capture else None


def exercise(folder):
    install = folder / 'install'
    install.mkdir()
    deploy = install / 'deploy'
    deploy.mkdir()
    for path in [
        *ROOT.joinpath('deploy').glob('snapshot*.py'),
        ROOT / 'deploy/compose.sh',
        ROOT / 'deploy/lib.sh',
    ]:
        shutil.copy2(path, deploy / path.name)
    (deploy / 'probe').write_text(PROBE)
    (install / 'docker-compose.yml').write_text(MODEL)
    (install / 'docker-compose.prod.yml').write_text('services: {}\n')
    (install / 'env').mkdir()
    (install / 'data/atproto-pds').mkdir(parents=True)
    settings = install / 'env/production.env'
    project = 'vidra-snapshot-lab-' + secrets.token_hex(6)
    core_image = 'vidra-snapshot-fixture/' + project
    build = folder / 'build'
    build.mkdir()
    (build / 'Dockerfile').write_text(
        'FROM postgres:18-alpine\nARG RELEASE\nARG PROJECT\n'
        'ENV FIXTURE_IMAGE_VERSION=$RELEASE\nLABEL io.vidra.smoke.project=$PROJECT\n'
    )
    secretfile = folder / 'password'
    secretfile.write_text(secrets.token_hex(32))
    secretfile.chmod(0o600)
    env = {
        k: os.environ[k]
        for k in (
            'PATH',
            'HOME',
            'DOCKER_HOST',
            'DOCKER_CONTEXT',
            'DOCKER_CONFIG',
            'TMPDIR',
            'XDG_RUNTIME_DIR',
            'SSL_CERT_FILE',
        )
        if k in os.environ
    }
    env.update(
        COMPOSE_PROJECT_NAME=project,
        RESTIC_REPOSITORY=str(folder / 'repository'),
        RESTIC_PASSWORD_FILE=str(secretfile),
        RESTIC_CACHE_DIR=str(folder / 'cache'),
        PYTHONDONTWRITEBYTECODE='1',
    )

    def cmd(*args, capture=False):
        return command(list(args), env=env, cwd=install, capture=capture)

    def stack(*args, capture=False):
        return cmd('bash', deploy / 'compose.sh', *args, capture=capture)

    def snapshots(*args, capture=False):
        return cmd(sys.executable, deploy / 'snapshots.py', *args, capture=capture)

    def history():
        return json.loads(snapshots('list', '--json', capture=True))

    def version(tag):
        settings.write_text(
            f'VIDRA_TLS_MODE=external\nFIXTURE_CORE_IMAGE={core_image}\n'
            + ''.join(f'VIDRA_{component}_TAG={tag}\n' for component in ('CORE', 'USER', 'SEARCH'))
        )

    def sql(query):
        return stack(
            'exec',
            '-T',
            'postgres',
            'psql',
            '-XAt',
            '-U',
            'fixture',
            '-d',
            'fixture',
            '-v',
            'ON_ERROR_STOP=1',
            '-c',
            query,
            capture=True,
        )

    def upload(label):
        stack(
            'exec',
            '-T',
            'api',
            'sh',
            '-ec',
            'mkdir -p /app/data/media && printf %s "$1" > "/app/data/media/$1.jpg"',
            'sh',
            label,
        )
        sql(
            f"INSERT INTO photos VALUES ('{label}.jpg',md5('{label}')); "
            f"INSERT INTO messages VALUES ('{label} message')"
        )
        stack(
            'exec',
            '-T',
            'pds',
            'sh',
            '-ec',
            'printf %s "$1" > "/pds/$1" && chmod 0640 "/pds/$1" && chown 11001:11002 "/pds/$1"',
            'sh',
            label,
        )

    def check_state(tag, labels):
        ledgers = sql(
            "SELECT version::text || ':' || dirty::text FROM public.schema_migrations "
            "UNION ALL SELECT version::text || ':' || dirty::text FROM public.vidra_search_migrations"
        )
        assert ledgers.splitlines() == (
            ['1:false', '10:false'] if tag == 'v1.0.0' else ['2:false', '11:false']
        )
        current = sql("SELECT string_agg(body,',' ORDER BY body) FROM messages")
        assert current == ','.join(f'{v} message' for v in labels), current
        files = stack('exec', '-T', 'api', 'ls', '-1', '/app/data/media', capture=True).splitlines()
        assert sorted(files) == [v + '.jpg' for v in labels], files
        assert stack('exec', '-T', 'api', 'printenv', 'SMOKE_VERSION', capture=True) == tag
        assert stack('exec', '-T', 'api', 'printenv', 'FIXTURE_IMAGE_VERSION', capture=True) == tag
        assert f'VIDRA_CORE_TAG={tag}\n' in settings.read_text()
        assert stack('exec', '-T', 'pds', 'ls', '-1', '/pds', capture=True).splitlines() == labels
        for label in labels:
            assert (
                stack('exec', '-T', 'api', 'cat', f'/app/data/media/{label}.jpg', capture=True) == label
            )
            assert stack('exec', '-T', 'pds', 'cat', '/pds/' + label, capture=True) == label
            assert (
                stack('exec', '-T', 'pds', 'stat', '-c', '%u:%g:%a', '/pds/' + label, capture=True)
                == '11001:11002:640'
            )

    version('v1.0.0')
    cmd('restic', 'init')
    try:
        stack('pull', '--policy', 'missing', 'postgres')
        for tag in ('v1.0.0', 'v1.1.0'):
            cmd(
                'docker',
                'build',
                '--pull=false',
                '--network=none',
                '--build-arg',
                'RELEASE=' + tag,
                '--build-arg',
                'PROJECT=' + project,
                '-t',
                core_image + ':' + tag,
                str(build),
            )
        stack('up', '-d', '--wait', 'postgres', 'redis', 'api', 'frontend', 'search', 'pds')
        sql(
            'CREATE TABLE photos(filename text PRIMARY KEY,digest text NOT NULL);'
            'CREATE TABLE messages(body text PRIMARY KEY);'
            'CREATE TABLE public.schema_migrations(version bigint, dirty boolean);'
            'CREATE TABLE public.vidra_search_migrations(version bigint, dirty boolean);'
            'INSERT INTO public.schema_migrations VALUES (1,false);'
            'INSERT INTO public.vidra_search_migrations VALUES (10,false);'
        )
        upload('first')
        snapshots('create', '--reason', 'manual')
        (first,) = history()
        assert first['release'] == 'v1.0.0' and first['kind'] == 'install'
        version('v1.1.0')
        stack('up', '-d', '--wait', 'api', 'search', 'frontend')
        sql(
            'UPDATE public.schema_migrations SET version=2; '
            'UPDATE public.vidra_search_migrations SET version=11'
        )
        upload('later')
        check_state('v1.1.0', ['first', 'later'])

        snapshots('restore', first['id'])
        check_state('v1.1.0', ['first', 'later'])
        assert [entry['id'] for entry in history()] == [first['id']]
        snapshots('restore', first['id'], '--apply')
        check_state('v1.0.0', ['first'])
        (safety,) = [row for row in history() if row['reason'] == 'before-restore']
        assert safety['release'] == 'v1.1.0'
        # A failed deploy wrote a new API pin without recreating its container.
        settings.write_text(settings.read_text().replace('VIDRA_CORE_TAG=v1.0.0', 'VIDRA_CORE_TAG=v9.9.9'))
        failed = subprocess.run(
            [sys.executable, deploy / 'snapshots.py', 'create'],
            cwd=install,
            env=env,
            text=True,
            capture_output=True,
        )
        valid_refusals = ('Release pins have changed', 'differs from the saved configuration for SMOKE_VERSION')
        assert failed.returncode and any(reason in failed.stderr for reason in valid_refusals), failed.stderr
        assert {r['id'] for r in history()} == {first['id'], safety['id']}
        stack('stop', 'api')
        lost = cmd(
            'docker', 'image', 'inspect', '--format', '{{.Id}}', core_image + ':v1.1.0', capture=True
        )
        cmd('docker', 'image', 'rm', core_image + ':v1.1.0')
        missing = subprocess.run(
            ['docker', 'image', 'inspect', lost],
            cwd=install,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        assert missing.returncode, 'recovery fixture image must be absent from the local image store'

        first_doc = json.loads(cmd('restic', 'dump', first['id'], '/vidra-install.json', capture=True))
        snapshots('retire', first['id'])
        assert {r['id'] for r in history()} == {first['id'], safety['id']}
        snapshots('retire', first['id'], '--apply')
        assert json.loads(
            cmd('restic', 'snapshots', '--json', '--tag', first_doc['group'], capture=True)
        ) in (None, [])
        cmd('restic', 'prune')
        cmd('restic', 'check', '--read-data')
        snapshots('restore', safety['id'], '--apply', '--discard-current')
        check_state('v1.1.0', ['first', 'later'])
        assert [r['id'] for r in history()] == [safety['id']]
        print(
            'PASS: rollback preserved newer messages, media and bind ownership; a retained snapshot '
            'recovered the mixed-pin install after retirement and repository pruning',
            flush=True,
        )
    finally:
        stack('down', '--volumes', '--remove-orphans')
        # Recovery image aliases are local to this randomly named fixture.
        for repository in ('vidra-recovery/' + project, core_image):
            refs = cmd(
                'docker', 'image', 'ls', '--format', '{{.Repository}}:{{.Tag}}', repository, capture=True
            ).splitlines()
            if refs:
                cmd('docker', 'image', 'rm', *refs)


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='vidra-snapshot-lab-') as directory:
        exercise(Path(directory).resolve())
