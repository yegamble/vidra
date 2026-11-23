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
      test: ["CMD", pg_isready, -U, fixture, -d, fixture]
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
    image: postgres:18-alpine
    entrypoint: [sh, /fixture/api]
    command: [serve]
    environment:
      STORAGE_BACKEND: local
      STORAGE_LOCAL_ROOT: /app/data/media
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
    volumes: [./deploy/probe:/fixture/api:ro]
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
    settings = install / 'env/production.env'
    project = 'vidra-snapshot-lab-' + secrets.token_hex(6)
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
            'VIDRA_TLS_MODE=external\n'
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

    def check_state(tag, labels):
        current = sql("SELECT string_agg(body,',' ORDER BY body) FROM messages")
        assert current == ','.join(f'{v} message' for v in labels), current
        files = stack('exec', '-T', 'api', 'ls', '-1', '/app/data/media', capture=True).splitlines()
        assert sorted(files) == [v + '.jpg' for v in labels], files
        assert stack('exec', '-T', 'api', 'printenv', 'SMOKE_VERSION', capture=True) == tag
        assert f'VIDRA_CORE_TAG={tag}\n' in settings.read_text()
        for label in labels:
            assert (
                stack('exec', '-T', 'api', 'cat', f'/app/data/media/{label}.jpg', capture=True) == label
            )

    version('v1.0.0')
    cmd('restic', 'init')
    try:
        stack('up', '-d', '--wait', 'postgres', 'redis', 'api', 'frontend', 'search')
        sql(
            'CREATE TABLE photos(filename text PRIMARY KEY,digest text NOT NULL);'
            'CREATE TABLE messages(body text PRIMARY KEY)'
        )
        upload('first')
        snapshots('create', '--reason', 'manual')
        (first,) = history()
        assert first['release'] == 'v1.0.0' and first['kind'] == 'install'
        version('v1.1.0')
        stack('up', '-d', '--wait', 'api', 'search', 'frontend')
        upload('later')
        check_state('v1.1.0', ['first', 'later'])

        snapshots('restore', first['id'])
        check_state('v1.1.0', ['first', 'later'])
        assert [entry['id'] for entry in history()] == [first['id']]
        snapshots('restore', first['id'], '--apply')
        check_state('v1.0.0', ['first'])
        (safety,) = [row for row in history() if row['reason'] == 'before-restore']
        assert safety['release'] == 'v1.1.0'
        snapshots('restore', safety['id'], '--apply', '--discard-current')
        check_state('v1.1.0', ['first', 'later'])
        assert len(history()) == 2
        print(
            'PASS: dated snapshots, preview, release rollback and recovery of newer messages and media',
            flush=True,
        )
    finally:
        stack('down', '--volumes', '--remove-orphans')
        # Recovery image aliases are local to this randomly named fixture.
        refs = cmd(
            'docker',
            'image',
            'ls',
            '--format',
            '{{.Repository}}:{{.Tag}}',
            'vidra-recovery/' + project,
            capture=True,
        ).splitlines()
        if refs:
            cmd('docker', 'image', 'rm', *refs)


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='vidra-snapshot-lab-') as directory:
        exercise(Path(directory).resolve())
