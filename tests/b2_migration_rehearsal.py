#!/usr/bin/env python3
"""Disposable published-v0.7.8 importer COPY rehearsal; synthetic subset only.

prepare leaves the candidate running for independent provider/browser checks.
disconnect removes its source dependencies; cleanup removes only this project's
containers and volumes. Every raw response, configuration and log stays private.
"""
import argparse
import base64
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import stat
import subprocess
import time
import traceback
import uuid

import peertube_fixture_database as database
import peertube_fixture_media as media
import recovery_release_acceptance as recovery
from release_acceptance_b2 import TestBucket, validate_spec

ROOT = Path(__file__).resolve().parents[1]
RECORD = ROOT / 'releases/v0.7.8.json'
SCOPE = 'published v0.7.8 synthetic importer subset to Backblaze B2'
DOCKER = ['docker', '--host=unix:///var/run/docker.sock']


class Failure(Exception):
    """Only fixed categories may cross the public result boundary."""


def require(ok, code):
    if not ok:
        raise Failure(code)


def read_private_json(path):
    path = Path(path)
    require(path.is_absolute() and path.resolve() == path and path.is_file()
            and not path.is_symlink(), 'private_path_refused')
    # Managed sandboxes can hide .git metadata while leaving checkout files
    # visible. The harness knows its own checkout independently of that probe.
    require(ROOT not in path.parents, 'repository_secret_refused')
    require(path.stat().st_uid == os.getuid() and stat.S_IMODE(path.stat().st_mode) == 0o600,
            'private_permissions_refused')
    require(not any((parent / '.git').is_file() or (parent / '.git/HEAD').exists()
                    for parent in path.parents), 'repository_secret_refused')
    return json.loads(path.read_text())


def validate_stage_path(path):
    require(path.is_absolute() and path.resolve() == path, 'stage_path_refused')
    require(path != ROOT and ROOT not in path.parents, 'repository_stage_refused')


def validate_storage(spec, credentials):
    try:
        validate_spec(spec, 'v0.7.8')
    except (AssertionError, ValueError, KeyError, TypeError):
        raise Failure('dedicated_b2_spec_refused') from None
    require(set(credentials) == {'access_key', 'secret_key'} and all(
        isinstance(value, str) and value and not any(c in value for c in '\r\n\x00')
        for value in credentials.values()), 'dedicated_b2_credentials_refused')


def image_refs(record):
    require(record.get('release') == 'v0.7.8' and record.get('core_schema_version') == 182
            and record['components']['core']['commit'] == media.CORE_COMMIT, 'release_contract_differs')
    images = {}
    for role in ('core', 'user', 'search'):
        image = record['components'][role]['image']
        digest = image.get('platforms', {}).get('linux/amd64')
        require(image['repository'] == 'ghcr.io/yegamble/vidra-' + role
                and isinstance(digest, str) and re.fullmatch(r'sha256:[0-9a-f]{64}', digest), 'release_image_refused')
        images[role] = image['repository'] + '@' + digest
    return images


def verify_mapping(rows):
    require(len(rows) == len(media.CASES) and {row['source_id'] for row in rows} == set(media.UUIDS.values()),
            'video_mapping_population_differs')
    require(len({row['vidra_id'] for row in rows}) == len(rows), 'video_mapping_duplicate')
    for name, source_id in media.UUIDS.items():
        row = next(row for row in rows if row['source_id'] == source_id)
        try:
            uuid.UUID(row['vidra_id'])
        except (TypeError, ValueError, AttributeError):
            raise Failure('video_mapping_identity_differs') from None
        require(row['status'] == 'done' and row['title'] == 'Synthetic ' + name,
                'video_mapping_identity_differs')
        require(row['privacy'] == {'unlisted': 'unlisted', 'private': 'private', 'internal': 'internal',
                                   'password': 'private'}.get(name, 'public')
                and row['state'] == ('draft' if name == 'draft' else 'published')
                and row['blocked'] is (name == 'blacklisted'), 'video_policy_differs')


def asset_pairs(inventory, originals, masters, captions, artwork, media_root):
    """Independently map SQL destination keys onto verified source inventory."""
    pairs = []
    root = Path(media_root)
    def add(key, relative, kind):
        require(isinstance(key, str) and key and not key.startswith('/') and
                all(part not in ('', '.', '..') for part in key.split('/')) and
                not re.search(r'[:?#\\\s]', key), 'destination_key_refused')
        require(relative in inventory['files'], 'source_asset_missing')
        source = root / relative
        require(source.resolve() == source and not source.is_symlink() and source.is_file(), 'source_asset_refused')
        expected = inventory['files'][relative]
        require(media.sha256(source) == expected['sha256'] and source.stat().st_size == expected['size'],
                'source_asset_hash_differs')
        pairs.append(dict(key=key, source_relative=relative, source_key=relative.removeprefix('source-media/'),
                          bytes=expected['size'], sha256=expected['sha256'], kind=kind))
    expected_originals = {media.UUIDS[name]: entry['original'] for name, entry in inventory['videos'].items()
                          if entry['original']}
    require(len(originals) == len(expected_originals) and {r['source_id'] for r in originals} == set(expected_originals),
            'original_population_differs')
    for row in originals:
        source = expected_originals[row['source_id']]
        require(row['original_name'] == Path(source).name, 'original_assignment_differs')
        add(row['storage_key'], 'source-media/' + source, 'original')
        require(row.get('sha256', pairs[-1]['sha256']) == pairs[-1]['sha256'], 'original_database_hash_differs')
    expected_hls = {media.UUIDS[name]: entry['hls'] for name, entry in inventory['videos'].items() if entry['hls']}
    require(len(masters) == len(expected_hls) and {r['source_id'] for r in masters} == set(expected_hls),
            'hls_population_differs')
    for row in masters:
        source = expected_hls[row['source_id']]
        require(row['master_key'] == source and row.get('state', 'ready') == 'ready', 'hls_assignment_differs')
        prefix = 'source-media/' + str(Path(source).parent) + '/'
        for relative in sorted(name for name in inventory['files'] if name.startswith(prefix)):
            add(relative.removeprefix('source-media/'), relative,
                'playlist' if relative.endswith('.m3u8') else 'hls_binary')
    require(len(captions) == 1 and captions[0]['source_id'] == media.UUIDS['public']
            and captions[0]['language'] == 'en', 'caption_assignment_differs')
    add(captions[0]['storage_key'], 'source-media/captions/fixture-en.vtt', 'caption')
    require(len(artwork) == 2 and {row['kind'] for row in artwork} == {'thumbnail', 'storyboard'}
            and all(row['source_id'] == media.UUIDS['public'] for row in artwork), 'artwork_assignment_differs')
    for row in artwork:
        relative = 'source-media/' + ('thumbnails/poster.jpg' if row['kind'] == 'thumbnail' else 'storyboards/sprite.jpg')
        add(row['storage_key'], relative, 'artwork' if row['kind'] == 'thumbnail' else 'storyboard')
    require(len({row['key'] for row in pairs}) == len(pairs), 'destination_asset_duplicate')
    return pairs


class Rehearsal:
    def __init__(self, stage):
        self.stage = Path(stage)
        self.private = self.stage / 'private'
        self.sequence = len(list(self.private.glob('command-*.log')))
        self.state = read_private_json(self.private / 'state.json') if (self.private / 'state.json').exists() else {}
        self.env = os.environ.copy()
        for name in ('DOCKER_HOST', 'DOCKER_CONTEXT', 'DOCKER_TLS', 'DOCKER_TLS_VERIFY', 'DOCKER_CERT_PATH'):
            self.env.pop(name, None)

    def save(self, name, value):
        path = self.private / name
        data = json.dumps(value, sort_keys=True, indent=2) + '\n'
        if path.exists():
            path.write_text(data)
        else:
            media.write_private(path, data)
        path.chmod(0o600)

    def run(self, args, label, data=None, expected=0, timeout=180):
        self.sequence += 1
        result = subprocess.run(args, input=data, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                env=self.env, timeout=timeout)
        media.write_private(self.private / f'command-{self.sequence:04d}-{label}.log', result.stdout)
        require(result.returncode == expected, 'command_failed_' + label)
        return result.stdout.decode(errors='replace')

    def compose(self, *args, **kwargs):
        return self.run([*DOCKER, 'compose', '-p', self.state['project'], '-f', str(self.private / 'compose.json'),
                         *args], 'compose-' + args[0], **kwargs)

    def sql(self, query, source=False, reader=False, expected=0):
        return self.compose('exec', '-T', 'source' if source else 'postgres', 'psql', '-X', '-A', '-t',
                            '-U', 'pt_reader' if reader else 'postgres', '-d', 'peertube' if source else 'vidra',
                            '-v', 'ON_ERROR_STOP=1', data=query.encode(), expected=expected).strip()

    def rows(self, query):
        return json.loads(self.sql('SELECT COALESCE(json_agg(t),\'[]\'::json) FROM (' + query + ') t;'))

    def request(self, path, method='GET', body=None, token=None, expected=200):
        # A direct loopback connection is local candidate access; outbound B2
        # requests in the API retain the inherited proxy and TLS verification.
        conn = http.client.HTTPConnection('127.0.0.1', self.state['api_port'], timeout=30)
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = 'Bearer ' + token
        try:
            conn.request(method, path, json.dumps(body) if body is not None else None, headers)
            response = conn.getresponse()
            raw = response.read(4 * 1024 * 1024 + 1)
            self.sequence += 1
            media.write_private(self.private / f'command-{self.sequence:04d}-http.log', raw)
            require(response.status == expected, 'http_status_differs')
            require(len(raw) <= 4 * 1024 * 1024, 'http_response_oversized')
            return json.loads(raw)
        finally:
            conn.close()

    def ready(self):
        for _ in range(120):
            try:
                self.request('/readyz')
                return
            except (OSError, Failure, http.client.HTTPException):
                time.sleep(1)
        raise Failure('candidate_not_ready')

    def launch(self, mode, label):
        token = self.state['owner']['token']
        initial = self.request('/api/v1/admin/peertube-import', 'POST',
                               dict(mode=mode, media_mode='copy', conflict_policy='skip', source_authoritative=False),
                               token, 202)
        for _ in range(600):
            run = self.request('/api/v1/admin/peertube-import/' + initial['id'], token=token)
            if run['state'] not in ('pending', 'running'):
                self.save(label + '.json', run)
                return run
            time.sleep(1)
        raise Failure('import_did_not_terminate')

    def source_fingerprint(self):
        tables = self.sql("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename", source=True).splitlines()
        digests = {}
        for table in tables:
            require(re.fullmatch(r'[a-zA-Z]+', table), 'source_table_refused')
            rows = json.loads(self.sql('SELECT COALESCE(json_agg(t ORDER BY t::text),\'[]\') FROM '
                                      '(SELECT row_to_json(r) t FROM "' + table + '" r) s', source=True))
            digests[table] = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()
        return digests

    def images(self):
        checked = {}
        for service, role in (('api', 'core'), ('frontend', 'user'), ('search', 'search')):
            container = self.compose('ps', '-q', service).strip()
            info = json.loads(self.run([*DOCKER, 'inspect', container], 'inspect-' + service))[0]
            reference = self.state['images'][role]
            local = json.loads(self.run([*DOCKER, 'image', 'inspect', reference], 'image-' + service))[0]
            require(info['Config']['Image'] == reference and info['Image'] == local['Id'], 'running_image_differs')
            checked[service] = dict(reference=reference, image_id=info['Image'])
        return checked

    def catalogue(self):
        """The reviewed schema-182 recovery catalogue, plus importer relations."""
        snapshot = recovery.fingerprint(self, 182)
        for table in ('peertube_import_ledger', 'video_renditions', 'video_blocks',
                      'account_actor_keys', 'channel_actor_keys'):
            snapshot[table] = self.sql(recovery.fingerprint_sql(table))
        return snapshot

    def reconcile(self):
        rows = self.rows("SELECT l.source_id,l.vidra_id,l.status,v.title,v.privacy,v.state,"
                         "EXISTS(SELECT 1 FROM video_blocks b WHERE b.video_id=v.id) AS blocked "
                         "FROM peertube_import_ledger l LEFT JOIN videos v ON v.id=l.vidra_id "
                         "WHERE l.entity_kind='video' ORDER BY source_id")
        verify_mapping(rows)
        self.save('mapping.json', rows)
        joins = " FROM peertube_import_ledger l JOIN video_files f ON f.video_id=l.vidra_id WHERE l.entity_kind='video' "
        originals = self.rows("SELECT l.source_id,f.storage_key,f.original_name,f.sha256" + joins + "AND f.kind='original' ORDER BY source_id")
        masters = self.rows("SELECT l.source_id,p.master_key,p.state FROM peertube_import_ledger l JOIN streaming_playlists p "
                            "ON p.video_id=l.vidra_id WHERE l.entity_kind='video' ORDER BY source_id")
        captions = self.rows("SELECT l.source_id,c.storage_key,c.language FROM peertube_import_ledger l JOIN captions c "
                             "ON c.video_id=l.vidra_id WHERE l.entity_kind='video' ORDER BY source_id")
        artwork = self.rows("SELECT l.source_id,f.storage_key,f.kind" + joins + "AND f.kind IN ('thumbnail','storyboard') ORDER BY f.kind")
        inventory = read_private_json(self.stage / 'media/inventory.json')
        pairs = asset_pairs(inventory, originals, masters, captions, artwork, self.stage / 'media')
        vtts = self.rows("SELECT l.source_id,f.storage_key,f.sha256,f.size_bytes" + joins + "AND f.kind='storyboard_vtt'")
        require(len(vtts) == 1 and vtts[0]['source_id'] == media.UUIDS['public'], 'storyboard_vtt_population_differs')
        # This index is generated by the importer from the source grid. Freeze
        # its expected literal content independently, rather than reading it
        # back from B2 and calling that its own expected checksum.
        vtt = 'WEBVTT\n\n' + ''.join(f'00:00:0{i}.000 --> 00:00:0{i+1}.000\nstoryboard.jpg#xywh={(i%2)*160},{(i//2)*90},160,90\n\n' for i in range(4))
        vtt_path = self.stage / 'media/expected-storyboard.vtt'
        if not vtt_path.exists():
            media.write_private(vtt_path, vtt)
        vtt_sum = media.sha256(vtt_path)
        require(vtts[0]['sha256'] == vtt_sum and vtts[0]['size_bytes'] == vtt_path.stat().st_size,
                'storyboard_vtt_content_differs')
        pairs.append(dict(key=vtts[0]['storage_key'], source_relative='expected-storyboard.vtt',
                          source_key=vtts[0]['storage_key'], bytes=vtt_path.stat().st_size,
                          sha256=vtt_sum, kind='storyboard_vtt'))
        self.save('asset-pairs.json', pairs)
        self.save('storyboard-vtt-database.json', vtts)
        counts = {table: int(self.sql('SELECT count(*) FROM ' + table)) for table in
                  ('users', 'channels', 'videos', 'comments', 'playlists', 'playlist_items', 'channel_follows',
                   'video_ratings', 'video_tags', 'video_chapters', 'streaming_playlists', 'captions', 'video_files', 'video_renditions')}
        expected = dict(users=3, channels=2, videos=10, comments=2, playlists=1, playlist_items=2,
                        channel_follows=1, video_ratings=1, video_tags=1, video_chapters=2, streaming_playlists=3,
                        captions=1, video_files=10, video_renditions=3)
        require(counts == expected, 'catalogue_counts_differ')
        source_credentials = read_private_json(self.stage / 'database/credentials.json')
        users = self.rows("SELECT username,password_hash,is_active FROM users WHERE username IN ('alice','bob') ORDER BY username")
        require(len(users) == 2 and all(row['password_hash'] == source_credentials[row['username']]['bcrypt']
                and row['is_active'] is (row['username'] == 'alice') for row in users), 'account_policy_differs')
        for table, kind, foreign in (('account_actor_keys', 'user', 'user_id'),
                                     ('channel_actor_keys', 'channel', 'channel_id')):
            keys = self.rows('SELECT l.source_id,k.public_key_pem,k.private_key_pem LIKE \'enc:%\' AS sealed '
                             'FROM peertube_import_ledger l JOIN ' + table + ' k ON k.' + foreign + '=l.vidra_id '
                             'WHERE l.entity_kind=\'' + kind + '\' ORDER BY l.source_id')
            require(len(keys) == 2, 'actor_key_population_differs')
            for row in keys:
                source_id = int(row['source_id'])
                actor_id = source_id * 2 - (1 if kind == 'user' else 0)
                require(row['public_key_pem'] == source_credentials['actors'][str(actor_id)]['public']
                        and row['sealed'] is True, 'actor_key_policy_differs')
        browser = dict(api_origin='http://127.0.0.1:' + str(self.state['api_port']),
                       frontend_origin='http://127.0.0.1:' + str(self.state['frontend_port']), owner=self.state['owner'],
                       alice=dict(email='alice@example.invalid', password=source_credentials['alice']['password']),
                       bob=dict(email='bob@example.invalid', password=source_credentials['bob']['password']),
                       videos={name: dict(id=next(r for r in rows if r['source_id'] == source_id)['vidra_id'],
                                          **{k: next(r for r in rows if r['source_id'] == source_id)[k]
                                             for k in ('privacy', 'state', 'blocked')}) for name, source_id in media.UUIDS.items()})
        self.save('browser.json', browser)
        return dict(mapping=rows, pairs=pairs, counts=counts)


def compose_model(state, spec, credentials, source_media, ca_bundle):
    api_origin = 'http://127.0.0.1:' + str(state['api_port'])
    site_origin = 'http://127.0.0.1:' + str(state['frontend_port'])
    env = dict(VIDRA_ENV='production', VIDRA_ALLOW_PLAIN_HTTP='true', VIDRA_TLS_MODE='plain-http',
               PUBLIC_BASE_URL=site_origin, CORS_ALLOWED_ORIGINS=site_origin, HTTP_HOST='0.0.0.0', HTTP_PORT='8080',
               DATABASE_URL='postgres://postgres:' + state['db_password'] + '@postgres:5432/vidra?sslmode=disable',
               REDIS_URL='redis://redis:6379/0', JWT_SECRET=state['jwt_secret'], MFA_KEY_KEK=state['kek'],
               SEARCH_SERVICE_URL='http://search:8080', SEARCH_INTERNAL_SECRET=state['search_secret'],
               FEDERATION_KEY_KEK=state['kek'], STORAGE_BACKEND='s3', STORAGE_S3_ENDPOINT=spec['endpoint'],
               STORAGE_S3_BUCKET=spec['bucket'], STORAGE_S3_REGION=spec['region'], STORAGE_S3_USE_SSL='true',
               STORAGE_S3_FORCE_PATH_STYLE='false', STORAGE_S3_ACCESS_KEY=credentials['access_key'],
               STORAGE_S3_SECRET_KEY=credentials['secret_key'], MALWARE_SCAN_MODE='disabled', CLAMAV_ADDR='',
               REGISTRATION_ENABLED='false', FEDERATION_ENABLED='false', MAIL_ENABLED='false',
               DEV_MAIL_CAPTURE_ENABLED='false', IPFS_ENABLED='false', CHANNEL_SYNC_ENABLED='false',
               MEDIA_GC_ENABLED='false', FEATURE_LIVE_ENABLED='false', TRANSCODING_ENABLED='true',
               INSTANCE_DEFAULT_QUOTA_BYTES='0', PEERTUBE_IMPORT_ENABLED='true',
               PEERTUBE_SOURCE_DATABASE_URL='postgres://pt_reader:' + state['reader_password'] + '@source:5432/peertube?sslmode=disable',
               PEERTUBE_SOURCE_STORAGE_BACKEND='local', PEERTUBE_SOURCE_STORAGE_LOCAL_ROOT='/peertube-source',
               PEERTUBE_IMPORT_MEDIA_MODE='copy', PEERTUBE_IMPORT_CONFLICT_POLICY='skip', SSL_CERT_FILE='/run/ca.pem')
    # Docker's configured proxy defaults supply the reachable inner-container
    # address. The outer process uses the outer-only "proxy" hostname, so
    # copying that literal here would replace the working Docker defaults.
    # Preserve those defaults and extend their bypass list for Compose DNS.
    for key in ('NO_PROXY', 'no_proxy'):
        env[key] = ','.join(filter(None, (os.environ.get(key), '127.0.0.1,localhost,api,frontend,search,postgres,source,redis')))
    api = dict(image=state['images']['core'], platform='linux/amd64', environment=env,
               ports=[f'127.0.0.1:{state["api_port"]}:8080'],
               volumes=[dict(type='bind', source=str(source_media), target='/peertube-source', read_only=True),
                        dict(type='bind', source=str(ca_bundle), target='/run/ca.pem', read_only=True)],
               mem_limit='1536m', cpus=2.0)
    frontend = dict(image=state['images']['user'], platform='linux/amd64',
                    environment=dict(NODE_ENV='production', PUBLIC_API_BASE_URL=api_origin,
                                     PUBLIC_BASE_URL=site_origin, INTERNAL_API_BASE_URL='http://api:8080'),
                    ports=[f'127.0.0.1:{state["frontend_port"]}:3000'], mem_limit='768m')
    postgres = dict(image='postgres:18-alpine', environment=dict(POSTGRES_PASSWORD=state['db_password'], POSTGRES_DB='vidra'),
                    volumes=['target-db:/var/lib/postgresql'])
    source = dict(image='postgres:18-alpine', environment=dict(POSTGRES_PASSWORD=state['source_password'], POSTGRES_DB='peertube'),
                  volumes=['source-db:/var/lib/postgresql'])
    search = dict(image=state['images']['search'], platform='linux/amd64',
                  environment=dict(VIDRA_ENV='production', HTTP_HOST='0.0.0.0', HTTP_PORT='8080',
                                   DATABASE_URL=env['DATABASE_URL'], REDIS_URL='redis://redis:6379/1',
                                   INTERNAL_SECRET=state['search_secret']), mem_limit='512m')
    return dict(services=dict(postgres=postgres, source=source, redis=dict(image='redis:8-alpine'), api=api,
                              frontend=frontend, search=search), volumes={'target-db': {}, 'source-db': {}})


def prepare(args, result):
    spec, credentials = read_private_json(args.spec), read_private_json(args.credentials)
    validate_storage(spec, credentials)
    try:
        storage_proof = TestBucket(spec, credentials, 'v0.7.8').require_empty()
    except ValueError:
        raise Failure('b2_scope_or_empty_precondition_failed') from None
    record = json.loads(RECORD.read_text())
    images = image_refs(record)
    stage = media.new_private_directory(args.stage)
    (stage / 'private').mkdir(mode=0o700)
    run = Rehearsal(stage)
    run.state = dict(project='vidra-b2-' + secrets.token_hex(6), api_port=args.api_port, frontend_port=args.frontend_port,
                     images=images, db_password=secrets.token_hex(24), source_password=secrets.token_hex(24),
                     reader_password=secrets.token_hex(24), jwt_secret=secrets.token_hex(32),
                     search_secret=secrets.token_hex(32),
                     kek=base64.b64encode(secrets.token_bytes(32)).decode())
    run.save('state.json', run.state)
    run.save('provider-preflight.json', storage_proof)
    result['phase'] = 'fixture'
    media.generate(stage / 'media')
    database.generate(stage / 'database', stage / 'media', 'https://synthetic-peertube.invalid')
    mount = stage / 'private/mount-media'
    shutil.copytree(stage / 'media/source-media', mount)
    for path in [mount, *mount.rglob('*')]:
        path.chmod(0o555 if path.is_dir() else 0o444)
    ca_bundle = Path('/etc/ssl/certs/ca-certificates.crt')
    require(ca_bundle.is_file(), 'ca_bundle_missing')
    model = compose_model(run.state, spec, credentials, mount, ca_bundle)
    run.save('compose.json', model)
    run.compose('config', '-q')
    result['phase'] = 'published-images'
    run.compose('pull', timeout=900)
    run.compose('up', '-d', 'postgres', 'source', 'redis')
    for service in ('postgres', 'source'):
        for _ in range(60):
            try:
                run.compose('exec', '-T', service, 'pg_isready', '-U', 'postgres')
                break
            except Failure:
                time.sleep(1)
        else:
            raise Failure('database_not_ready')
    result['phase'] = 'source-role'
    run.sql((stage / 'database/source-1040.sql').read_text(), source=True)
    run.sql("CREATE ROLE pt_reader LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD '" +
            run.state['reader_password'] + "'; REVOKE ALL ON DATABASE peertube FROM PUBLIC; GRANT CONNECT ON DATABASE peertube TO pt_reader; "
            "REVOKE CREATE ON SCHEMA public FROM PUBLIC; GRANT USAGE ON SCHEMA public TO pt_reader; "
            "GRANT SELECT ON ALL TABLES IN SCHEMA public TO pt_reader; ALTER ROLE pt_reader SET default_transaction_read_only=on;", source=True)
    require(run.sql('SHOW default_transaction_read_only;', source=True, reader=True) == 'on', 'source_default_writable')
    refusal = run.sql('BEGIN READ WRITE; UPDATE video SET name=name WHERE false; ROLLBACK;', source=True, reader=True, expected=3)
    require('permission denied for table video' in refusal, 'source_write_not_refused')
    source_before = run.source_fingerprint()
    run.save('source-before.json', source_before)
    result['source_read_only'] = True
    result['phase'] = 'migrate'
    run.compose('run', '--rm', '--no-deps', 'api', 'migrate', 'up', timeout=600)
    require(run.sql('SELECT version::text || \'|\' || dirty::text FROM schema_migrations') == '182|false', 'core_schema_differs')
    run.compose('run', '--rm', '--no-deps', 'search', 'migrate', 'up', timeout=600)
    require(run.sql('SELECT version::text || \'|\' || dirty::text FROM vidra_search_migrations') == '18|false', 'search_schema_differs')
    run.compose('up', '-d', 'search')
    # Starting search before API ensures the initial reconciliation does not
    # hit a known reconcile-orphan race while search is still booting.
    for _ in range(60):
        try:
            run.compose('exec', '-T', 'search', 'wget', '-qO-', 'http://127.0.0.1:8080/readyz')
            break
        except Failure:
            time.sleep(1)
    else:
        raise Failure('search_not_ready')
    run.compose('up', '-d', 'api', 'frontend')
    run.ready()
    version = run.request('/version')
    require(version.get('version') == 'v0.7.8' and isinstance(version.get('commit'), str)
            and len(version['commit']) >= 7 and media.CORE_COMMIT.startswith(version['commit']), 'api_version_differs')
    result['phase'] = 'owner'
    logs = run.compose('logs', '--no-color', 'api')
    tokens = re.findall(r'403 owner_claim_required until claimed\): ([A-Za-z0-9_-]+)', logs)
    require(tokens, 'owner_claim_token_missing')
    owner = dict(username='rehearsal_owner', email='owner@rehearsal.invalid', password=secrets.token_hex(24))
    response = run.request('/api/v1/setup/claim-owner', 'POST', dict(token=tokens[-1], **owner), expected=201)
    owner['token'] = response['token']
    run.state['owner'] = owner
    run.save('state.json', run.state)
    settings = run.request('/api/v1/admin/instance-settings', 'PATCH', {'storyboards_enabled': False}, owner['token'])
    require(any(row['key'] == 'storyboards_enabled' and row['value'] is False for row in settings['settings']),
            'storyboard_pause_failed')
    before_preview = run.catalogue()
    run.save('catalogue-before-preview.json', before_preview)
    result['phase'] = 'schema-refusal'
    run.sql('UPDATE application SET "migrationVersion"=1041;', source=True)
    refused = run.launch('dry_run', 'schema-refusal')
    require(refused['state'] == 'failed' and refused.get('error_code') == 'unverified_schema', 'schema_gate_not_refused')
    require(run.sql('SELECT count(*) FROM peertube_import_ledger') == '0', 'schema_refusal_mutated_ledger')
    require(run.catalogue() == before_preview, 'schema_refusal_mutated_catalogue')
    run.sql('UPDATE application SET "migrationVersion"=1040;', source=True)
    result['schema_1041_refused'] = True
    result['phase'] = 'preview'
    preview = run.launch('dry_run', 'preview')
    require(preview['state'] == 'done' and preview['source_version'] == 1040
            and preview['report']['dry_run'] is True, 'preview_failed')
    require(run.sql('SELECT count(*) FROM videos') == '0' and run.sql('SELECT count(*) FROM users') == '1',
            'preview_mutated_catalogue')
    require(run.catalogue() == before_preview, 'preview_mutated_catalogue')
    result['phase'] = 'copy'
    copied = run.launch('run', 'copy')
    require(copied['state'] == 'done' and copied['report']['source_version'] == 1040, 'copy_run_failed')
    require(not any(counts['failed'] for counts in copied['report']['entities'].values()), 'copy_has_failed_entities')
    before = run.reconcile()
    result['phase'] = 'repeat'
    repeated = run.launch('run', 'repeat')
    require(repeated['state'] == 'done', 'repeat_run_failed')
    require(not any(counts['failed'] for counts in repeated['report']['entities'].values()), 'repeat_has_failed_entities')
    after = run.reconcile()
    require(before == after, 'repeat_changed_catalogue_or_assets')
    require(run.source_fingerprint() == source_before, 'source_changed')
    result.update(status='PASS', phase='prepared', preview_no_catalogue_writes=True,
                  repeat_preserved_ids_assets=True, source_snapshot_unchanged=True,
                  running_images=run.images(), catalogue_counts=before['counts'],
                  source_inventory_sha256=media.sha256(stage / 'media/inventory.json'),
                  database_inventory_sha256=media.sha256(stage / 'database/inventory.json'),
                  expected_asset_count=len(before['pairs']), record_sha256=media.sha256(RECORD), search_service=True)
    run.save('prepared.json', result)
    return run


def disconnect(args, result):
    run = Rehearsal(args.stage)
    require(read_private_json(run.private / 'prepared.json')['status'] == 'PASS', 'prepare_first')
    before = run.reconcile()
    model = read_private_json(run.private / 'compose.json')
    api = model['services']['api']
    for key in list(api['environment']):
        if key.startswith('PEERTUBE_'):
            del api['environment'][key]
    api['environment']['PEERTUBE_IMPORT_ENABLED'] = 'false'
    api['volumes'] = [v for v in api['volumes'] if v['target'] != '/peertube-source']
    run.compose('stop', 'source')
    run.save('compose-before-disconnect.json', read_private_json(run.private / 'compose.json'))
    run.save('compose.json', model)
    run.compose('up', '-d', '--no-deps', '--force-recreate', 'api')
    run.ready()
    after = run.reconcile()
    require(before == after, 'disconnect_changed_catalogue_or_assets')
    require(not run.compose('ps', '-q', 'source').strip(), 'source_database_still_running')
    info = json.loads(run.run([*DOCKER, 'inspect', run.compose('ps', '-q', 'api').strip()], 'disconnected-api'))[0]
    require(not any(m['Destination'] == '/peertube-source' for m in info['Mounts']), 'source_mount_still_attached')
    actual_env = dict(value.split('=', 1) for value in info['Config']['Env'] if '=' in value)
    require(actual_env.get('PEERTUBE_IMPORT_ENABLED') == 'false' and not any(
            key.startswith('PEERTUBE_SOURCE_') for key in actual_env), 'source_config_still_attached')
    result.update(status='PASS', phase='disconnected', source_database_stopped=True,
                  source_mount_removed=True, source_configuration_removed=True,
                  catalogue_and_assets_preserved=True, running_images=run.images(), search_service=True)
    run.save('disconnected.json', result)
    return run


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'disconnect', 'cleanup'))
    parser.add_argument('--stage', type=Path, required=True)
    parser.add_argument('--spec', type=Path)
    parser.add_argument('--credentials', type=Path)
    parser.add_argument('--api-port', type=int, default=18178)
    parser.add_argument('--frontend-port', type=int, default=13178)
    args = parser.parse_args(argv)
    os.umask(0o077)
    result = dict(status='FAIL', phase='preconditions', scope=SCOPE, synthetic_only=True, g10_closed=False,
                  scanner='disabled', tls='loopback plain HTTP; B2 HTTPS verified')
    run = None
    stage_validated = False
    try:
        validate_stage_path(args.stage)
        stage_validated = True
        if args.action == 'prepare':
            require(args.spec and args.credentials, 'private_storage_inputs_required')
            require(1024 <= args.api_port <= 65535 and 1024 <= args.frontend_port <= 65535
                    and args.api_port != args.frontend_port, 'loopback_ports_refused')
            run = prepare(args, result)
        elif args.action == 'disconnect':
            run = disconnect(args, result)
        else:
            run = Rehearsal(args.stage)
            run.compose('down', '--volumes', '--remove-orphans')
            result.update(status='PASS', phase='cleaned', project_removed=True)
    except Exception as error:
        result['error'] = str(error) if isinstance(error, (Failure, media.FixtureError)) else 'rehearsal_failed'
        if stage_validated and (args.stage / 'private').is_dir():
            media.write_private(args.stage / 'private' / ('failure-' + secrets.token_hex(4) + '.log'), traceback.format_exc())
    if stage_validated and (args.stage / 'private').is_dir():
        media.write_private(args.stage / ('result-' + args.action + '-' + secrets.token_hex(4) + '.json'),
                            json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, sort_keys=True))
    return 0 if result['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
